# Plan: Event-Driven Recursive Notebook Dashboard (v6)

## Context

The current dashboard joins 3 data sources (traces.db, context_snapshots.jsonl, model_outputs.jsonl) via ~1900 lines of temporal scoping logic in `live_loader.py`. This complexity causes tool events like `list_skills` and `load_skill` to be missed or misordered. This plan replaces that with a canonical append-only event log with explicit lineage, producing finalized events that the dashboard reads directly — no SQLite reads, no temporal inference.

## Critique History

### Round 1 (4 findings) — incorporated in v2

1. **High**: `before_model_callback` can't emit complete events → stash-then-finalize pattern
2. **High**: `after_tool_callback` not lossless (GAP-06) → dual-path with `make_event_finalizer()`
3. **High**: Event identity too weak → explicit lineage fields
4. **Medium**: "No temporal scoping" overstated → edge-based DAG reconstruction

### Round 2 (4 findings) — incorporated in v3

1. **High**: Parent edge scheme requires NEW plumbing → `parent_invocation_id` via 3-file change
2. **Medium**: `tool_decision` underspecified → dropped from schema
3. **Medium**: ContextWindowSnapshotPlugin retirement needs migration → phased cutover
4. **Medium**: Write serialization for concurrent JSONL → threading.Lock + per-invocation_id pending maps

### Round 3 (5 findings) — incorporated in v4

### R3-1 (High): `parent_tool_call_id` must be Phase 1

**Problem**: Deferring `parent_tool_call_id` to Phase 2 means the tree reader still falls back to matching children to parent execute_code events by `llm_query_detected=True` + timestamp ordering. That's temporal inference. It's ambiguous when one execute_code has multiple `llm_query()` callsites, or when repeated single-child dispatches all have `dispatch_ordinal=0`.

**Fix**: The InvocationContext bridge. The plugin and the dispatch closure share the same `ctx` object:

```
before_tool_callback(execute_code)
  └─ inv_ctx = tool_context._invocation_context   ← same object as ctx in closure
  └─ object.__setattr__(inv_ctx, "_dashboard_execute_code_event_id", event_id)

_run_child() [dispatch.py:271]
  └─ captures ctx                                  ← same InvocationContext
  └─ parent_tool_call_id = getattr(ctx, "_dashboard_execute_code_event_id", None)
  └─ create_child_orchestrator(..., parent_tool_call_id=parent_tool_call_id)
```

This works because:
- `before_tool_callback` fires BEFORE tool execution starts
- `_run_child()` reads the attr DURING tool execution (REPL code is running)
- `object.__setattr__` on Pydantic models is an established pattern in this codebase (orchestrator.py:361)
- For batched children from one execute_code: all read the same `parent_tool_call_id` — correct
- For sequential execute_code calls: the attr is overwritten each time — correct (each dispatch reads the current value)
- For multiple `llm_query()` callsites within one execute_code block: same parent_tool_call_id, distinguished by `dispatch_ordinal` — correct

Concrete changes (4 files):

1. **`DashboardEventPlugin.before_tool_callback`** — set attr on InvocationContext for execute_code
2. **dispatch.py:301** — read attr, pass to `create_child_orchestrator()`
3. **agent.py:create_child_orchestrator()** — accept + store `parent_tool_call_id`
4. **orchestrator.py:359** — propagate to reasoning_agent: `object.__setattr__(_ra, "_rlm_parent_tool_call_id", ...)`

### R3-2 (High): `invocation_id + iteration` is not a safe model/tool pairing key

**Problem**: `iteration` is incremented by REPLTool (repl_tool.py:132), not by every tool step. Non-REPL tools (list_skills, load_skill) don't increment it. So multiple model→tool pairs can share the same `(invocation_id, iteration)`.

**Fix**: Each tool event carries `model_event_id` — the `event_id` of the model event that triggered it. The plugin tracks the last emitted model event per invocation:

```python
# In DashboardEventPlugin:
self._last_model_event_id: dict[str, str] = {}  # invocation_id → event_id

async def after_model_callback(self, ...):
    event = StepEvent(phase="model", event_id=uuid4().hex, ...)
    inv_id = event.invocation_id
    self._last_model_event_id[inv_id] = event.event_id
    await self._flush_event(event)

async def after_tool_callback(self, ...):
    inv_id = ...  # from lineage
    model_event_id = self._last_model_event_id.get(inv_id)
    event = StepEvent(phase="tool", model_event_id=model_event_id, ...)
    await self._flush_event(event)
```

Within a single invocation, ADK's step loop guarantees strict model→tool→model→tool ordering. So `_last_model_event_id[inv_id]` always points to the correct model event.

### R3-3 (High): `_pending_model` must NOT be keyed by agent_name

**Problem**: In recursive concurrent execution, multiple active children can share the same generated agent name (`child_reasoning_d2f0` in two parallel subtrees dispatched from d1f0 and d1f1). Agent-name keying causes collisions.

**Fix**: Key by `invocation_id` (from ADK). Each agent run gets a unique invocation_id from the Runner. No collisions regardless of agent name reuse:

```python
self._pending_model: dict[str, dict] = {}   # keyed by invocation_id
self._pending_tool: dict[int, dict] = {}     # keyed by id(tool_context) — already safe
```

In `before_model_callback`:
```python
inv_id = getattr(inv_ctx, "invocation_id", "") or f"fallback_{id(callback_context)}"
self._pending_model[inv_id] = {"request": llm_request, "timestamp": time.time(), ...}
```

### Round 4 (2 findings) — incorporated in v5

### R4-1 (High): `dispatch_ordinal` doesn't distinguish sequential single `llm_query()` calls

**Problem**: `llm_query_async()` delegates to `llm_query_batched_async([prompt])` (dispatch.py:445), so `_run_child(prompt, model, schema, idx=0)` always gets `idx=0`. Two sequential `llm_query()` calls within one execute_code block both produce `(parent_tool_call_id=same, dispatch_ordinal=0)` — indistinguishable.

**Fix**: Replace `dispatch_ordinal` (batch-internal index) with `dispatch_call_index` — a per-execute_code monotonic counter on the InvocationContext. Advanced synchronously in `llm_query_batched_async` before creating child tasks:

```python
# In llm_query_batched_async (dispatch.py:468):
dispatch_base = getattr(ctx, "_dispatch_call_counter", 0)
object.__setattr__(ctx, "_dispatch_call_counter", dispatch_base + len(prompts))

tasks = [_run_child(p, model, output_schema, idx,
                    dispatch_call_index=dispatch_base + idx)
         for idx, p in enumerate(prompts)]
```

The counter is reset per execute_code block by the plugin in `before_tool_callback`:
```python
if tool.name == "execute_code":
    object.__setattr__(inv_ctx, "_dispatch_call_counter", 0)
```

Trace through sequential single-query dispatches within one execute_code:
```python
a = llm_query("first")   # batched([prompt]): base=0, counter→1, child gets index=0
b = llm_query("second")  # batched([prompt]): base=1, counter→2, child gets index=1
```

Trace through a real batch:
```python
results = llm_query_batched(["p1", "p2"])  # base=0, counter→2, children get [0, 1]
```

Trace through mixed:
```python
a = llm_query("solo")            # base=0, counter→1, child gets 0
r = llm_query_batched(["x","y"]) # base=1, counter→3, children get [1, 2]
```

Every child within an execute_code block has a unique `(parent_tool_call_id, dispatch_call_index)`. The list comprehension assigns indices synchronously before `asyncio.gather` runs any coroutines, so ordering is deterministic.

Concrete changes (2 files):
1. **dispatch.py:llm_query_batched_async** — read + advance `_dispatch_call_counter` on `ctx`, pass `dispatch_call_index=dispatch_base + idx` to `_run_child()`
2. **dispatch.py:_run_child** — accept `dispatch_call_index` param, pass to `create_child_orchestrator()`

### R4-2 (Medium): GAP-06 sync finalizer vs async write path

**Problem**: REPLTool calls `telemetry_finalizer(id(tool_context), result)` synchronously — it does not await (repl_tool.py:102). The SQLite finalizer works because `_update_telemetry` is synchronous inline (sqlite_tracing.py:539-568). But v4's `_flush_event()` uses `asyncio.Lock` which requires `await`. A sync caller can't use an async lock.

**Fix**: Use `threading.Lock` for ALL write paths — both async callbacks and the sync finalizer. This matches SqliteTracingPlugin's pattern: synchronous inline I/O, no async coordination needed.

```python
import threading

class DashboardEventPlugin(BasePlugin):
    def __init__(self, ...):
        self._write_lock = threading.Lock()   # NOT asyncio.Lock
        self._file_handle: TextIOWrapper | None = None

    def _write_event(self, event: dict) -> None:
        """Synchronous serialized JSONL append. Safe from both async and sync callers."""
        with self._write_lock:
            if self._file_handle is None:
                self._output_path.parent.mkdir(parents=True, exist_ok=True)
                self._file_handle = open(self._output_path, "a")
            self._file_handle.write(json.dumps(event, default=str) + "\n")
            self._file_handle.flush()
```

Both paths call `_write_event()` directly:
- **Async callbacks** (`after_model_callback`, `after_tool_callback`): call `self._write_event(event)` — blocks event loop for ~microseconds (one JSON line + flush), identical to how SqliteTracingPlugin's synchronous `_update_telemetry` blocks
- **Sync finalizer** (`make_telemetry_finalizer` closure): call `_write_event(event)` — same path, no async needed

```python
def make_telemetry_finalizer(self):
    pending = self._pending_tool
    write = self._write_event    # synchronous — no await needed

    def _finalize(tool_context_id: int, result: dict) -> None:
        entry = pending.pop(tool_context_id, None)
        if entry is None: return
        event = _build_tool_event_dict(entry, result)
        write(event)             # synchronous — matches SQLite pattern exactly
    return _finalize
```

Why `threading.Lock` not `asyncio.Lock`:
- `asyncio.Lock` requires `await` — unusable from synchronous finalizer
- `threading.Lock` blocks the caller thread — acceptable for one-line JSONL writes (~microseconds)
- SqliteTracingPlugin uses the same pattern: synchronous DB operations inline in both callbacks and finalizer
- Concurrent batch children in `asyncio.gather` share the event loop thread, so `threading.Lock` serializes them correctly (only one coroutine runs at a time per event loop tick, and the lock is released within the same tick)

### R3-4 + R3-5: Hard cutover, keep identity plumbing

**Problem**: Phased coexistence with ContextWindowSnapshotPlugin, `/live-v2`, and backward compatibility adds complexity without adding correctness. The identity plumbing (stash-finalize, finalizer, lock, lineage) is core correctness and must stay.

**Fix**:
- Remove phased migration. `dashboard_events.jsonl` is the single canonical sink. `/live` reads it directly.
- Remove ContextWindowSnapshotPlugin coexistence. The new plugin subsumes it.
- Stop treating `context_snapshots.jsonl` and `model_outputs.jsonl` as dashboard inputs.
- Keep all correctness plumbing: stash-then-finalize, GAP-06 finalizer, threading.Lock, full lineage fields.

### Round 5 (2 findings) — incorporated in v6

### R5-1 (Medium): Batch child ordering is nondeterministic in reader/UI

**Problem**: The tree builder groups children by `parent_tool_call_id` and appends `invocation_id`s in first-seen event order (completion order from `asyncio.gather`). Batched children run concurrently (dispatch.py:502), so first-seen is completion order, not dispatch order. The batch selector tabs would show children in wrong order.

**Fix**: Sort each child list by the child invocation's `dispatch_call_index` after grouping:

```python
# In build_tree(), after populating children_of_tool:
for tool_id, child_inv_ids in children_of_tool.items():
    child_inv_ids.sort(key=lambda inv_id: _first_event_dispatch_index(by_inv[inv_id]))

def _first_event_dispatch_index(events: list[StepEvent]) -> int:
    """Return dispatch_call_index from the first event of a child invocation."""
    for e in events:
        if e.dispatch_call_index is not None:
            return e.dispatch_call_index
    return 0
```

This ensures batch selector tabs display in dispatch order (0, 1, 2...) regardless of which child completes first.

### R5-2 (Low): `_last_model_event_id` grows unbounded over long sessions

**Problem**: `_pending_model` is naturally popped after each model call, but `_last_model_event_id` accumulates one entry per invocation_id forever. In deep recursive sessions this leaks.

**Fix**: Clean up the entry when the invocation's final tool event (set_model_response) is emitted:

```python
async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
    ...
    tool_name = getattr(tool, "name", "")
    if tool_name == "set_model_response":
        self._last_model_event_id.pop(inv_id, None)
```

`set_model_response` is the terminal tool call for any invocation — no more model→tool pairs follow. The cleanup is also applied in `make_telemetry_finalizer` for the GAP-06 path.

---

## Architecture: Canonical Event Log with Explicit Lineage

### Callback lifecycle

| Phase | Callback | Action |
|-------|----------|--------|
| Model open | `before_model_callback` | Stash mutable `LlmRequest` ref + lineage (keyed by `invocation_id`) |
| Model close | `after_model_callback` | Decompose mutated request + tokens → emit `StepEvent(phase="model")`, record `_last_model_event_id[inv_id]` |
| Model error | `on_model_error_callback` | Emit `StepEvent(phase="model", error=True)` |
| Tool open | `before_tool_callback` | Stash `(event_id, start_time, tool_name, args, lineage)` keyed by `id(tool_context)`. For execute_code: also set `_dashboard_execute_code_event_id` and reset `_dispatch_call_counter=0` on InvocationContext. |
| Tool close (primary) | `after_tool_callback` | Pop pending → emit `StepEvent(phase="tool")` with `model_event_id` link |
| Tool close (fallback) | `make_event_finalizer()` → REPLTool | Idempotent: emit if `after_tool_callback` didn't fire (GAP-06) |

All emits go through `_write_event()` under `threading.Lock` — synchronous inline, usable from both async callbacks and the sync GAP-06 finalizer.

### Unified event model: `StepEvent`

```python
@dataclass
class StepEvent:
    # ── Identity ──
    event_id: str                        # uuid4, unique per event
    phase: Literal["model", "tool"]

    # ── Lineage (all Phase 1 — no deferred fields) ──
    invocation_id: str                   # ADK invocation_id (unique per agent run)
    parent_invocation_id: str | None     # parent agent's invocation_id
    parent_tool_call_id: str | None      # event_id of parent's execute_code StepEvent
    dispatch_call_index: int             # per-execute_code monotonic counter (NOT batch-internal idx)
    branch: str | None                   # ADK branch
    session_id: str

    # ── Step pairing ──
    model_event_id: str | None           # tool events: event_id of the model event that triggered this tool
                                         # model events: None

    # ── Scope ──
    agent_name: str
    depth: int
    fanout_idx: int | None
    iteration: int
    ts: float

    # ── Model phase (populated when phase="model") ──
    chunks: list[dict] | None            # decomposed request chunks
    input_tokens: int
    output_tokens: int
    thought_tokens: int
    model: str
    finish_reason: str | None
    error: bool
    error_message: str | None

    # ── Tool phase (populated when phase="tool") ──
    tool_name: str | None
    tool_args: dict | None
    tool_result: dict | None
    code: str | None                     # execute_code only
    stdout: str | None                   # execute_code only
    stderr: str | None                   # execute_code only
    duration_ms: float | None
    llm_query_detected: bool             # execute_code: did code contain llm_query?
    llm_query_count: int                 # how many llm_query calls
```

### Event stream example (skill_arch_test, 30 events)

```jsonl
{"event_id":"m0","phase":"model","invocation_id":"inv0","parent_invocation_id":null,"parent_tool_call_id":null,"depth":0,"iter":0,"model_event_id":null,"chunks":[...]}
{"event_id":"t0","phase":"tool","invocation_id":"inv0","model_event_id":"m0","tool_name":"list_skills","tool_result":{"skills":["test-skill"]}}
{"event_id":"m1","phase":"model","invocation_id":"inv0","depth":0,"iter":0,"model_event_id":null,"chunks":[...]}
{"event_id":"t1","phase":"tool","invocation_id":"inv0","model_event_id":"m1","tool_name":"load_skill","tool_args":{"name":"test-skill"}}
{"event_id":"m2","phase":"model","invocation_id":"inv0","depth":0,"iter":0,"model_event_id":null,"chunks":[...]}
{"event_id":"t2","phase":"tool","invocation_id":"inv0","model_event_id":"m2","tool_name":"execute_code","code":"result = run_test_skill(...)","llm_query_detected":true,"llm_query_count":1}
{"event_id":"m3","phase":"model","invocation_id":"inv1","parent_invocation_id":"inv0","parent_tool_call_id":"t2","dispatch_call_index":0,"depth":1,"model_event_id":null}
{"event_id":"t3","phase":"tool","invocation_id":"inv1","model_event_id":"m3","tool_name":"list_skills"}
...
```

Key identity properties:
- **Model→tool pairing**: tool event `t0` carries `model_event_id:"m0"` — unambiguous, no iteration needed
- **Parent→child edge**: child event `m3` carries `parent_tool_call_id:"t2"` — points to exact execute_code
- **Batch discrimination**: batch children share `parent_tool_call_id` but differ by `dispatch_call_index`
- **Sequential single-child within one execute_code**: same `parent_tool_call_id`, different `dispatch_call_index` (0, 1, 2... — monotonic per execute_code block, not per batch)
- **Sequential single-child across execute_code blocks**: different `parent_tool_call_id` (each execute_code gets its own event_id)

### Tree reconstruction

```python
def build_tree(events: list[StepEvent]) -> InvocationTree:
    by_inv: dict[str, list[StepEvent]] = defaultdict(list)
    for e in events:
        by_inv[e.invocation_id].append(e)

    # Children grouped by parent_tool_call_id (the exact execute_code that spawned them)
    children_of_tool: dict[str, list[str]] = defaultdict(list)
    seen_inv: set[str] = set()
    for e in events:
        if e.parent_tool_call_id and e.invocation_id not in seen_inv:
            children_of_tool[e.parent_tool_call_id].append(e.invocation_id)
            seen_inv.add(e.invocation_id)

    # Sort children by dispatch_call_index (not completion order from asyncio.gather) — R5-1
    for tool_id, child_inv_ids in children_of_tool.items():
        child_inv_ids.sort(key=lambda inv_id: next(
            (e.dispatch_call_index for e in by_inv[inv_id] if e.dispatch_call_index is not None), 0
        ))

    # Pair model+tool within each invocation via model_event_id
    steps: dict[str, list[tuple[StepEvent, StepEvent|None]]] = {}
    for inv_id, inv_events in by_inv.items():
        model_by_id = {e.event_id: e for e in inv_events if e.phase == "model"}
        paired = []
        for e in inv_events:
            if e.phase == "model":
                paired.append((e, None))  # placeholder
            elif e.phase == "tool" and e.model_event_id:
                # Replace placeholder
                for i, (m, _) in enumerate(paired):
                    if m.event_id == e.model_event_id:
                        paired[i] = (m, e)
                        break
        steps[inv_id] = paired

    return InvocationTree(by_inv=by_inv, children_of_tool=children_of_tool, steps=steps)
```

No temporal scoping. No timestamp windows. Tree structure is in the edges.

### What this eliminates vs. what stays

| Current component | Lines | Fate |
|-------------------|-------|------|
| `live_loader.py` | ~1900 | **Replaced** by ~200-line edge-based reader |
| `live_models.py` | ~250 | **Replaced** by `StepEvent` dataclass |
| `live_controller.py` pane/watermark logic | ~400 | **Simplified** to tree traversal |
| `data_loader.py` | ~300 | **Removed** |
| `flow_builder.py` temporal ordering | ~270 | **Simplified** — events carry explicit order |
| `ContextWindowSnapshotPlugin` | ~300 | **Removed** — new plugin subsumes it |
| `context_snapshots.jsonl` / `model_outputs.jsonl` | — | **Removed** as dashboard inputs |
| SQLite reads for dashboard | all | **Eliminated** — traces.db write-only sink |

Stays: `SqliteTracingPlugin` (analytics/Langfuse), arrow/cell renderers in `components/`

---

## UI Layout: Split-Panel Recursive Notebook

```
┌──────────────────── LlmRequest Banner (full width) ─────────────────────┐
│ agent_name │ iteration │ token count │ collapsible request chunks       │
└─────────────────────────────────────────────────────────────────────────┘
┌──── Parent Code Panel (left 50%) ────┐┌── Child Panel (right 50%) ─────┐
│  Vertically scrolling:               ││ [f0 | f1 | f2] batch selector  │
│  - list_skills result                ││  Horizontally scrolling →      │
│  - load_skill result                 ││  - Child LlmRequest card       │
│  - execute_code (rich Python)        ││  - Child tool results          │
│  - stdout pane                       ││  - Child execute_code + stdout │
│  - set_model_response                ││  - set_model_response          │
└──────────────────────────────────────┘└────────────────────────────────┘
```

| Dimension | Represents |
|-----------|-----------|
| **Vertical scroll** (parent) | Temporal execution — steps append downward |
| **Horizontal scroll** (child) | Child's steps at depth+1, appending rightward |
| **Batch selector tabs** | Fanout — switches active child of `llm_query_batched` |

---

## Implementation Steps

### Step 1: Lineage plumbing (4 files, 3 new fields)

**`parent_invocation_id`**:
- **dispatch.py:301** — `parent_invocation_id=ctx.invocation_id`
- **agent.py:create_child_orchestrator()** — accept + forward
- **orchestrator.py:359** — `object.__setattr__(_ra, "_rlm_parent_invocation_id", ...)`

**`parent_tool_call_id`** (InvocationContext bridge):
- **dispatch.py:301** — `parent_tool_call_id=getattr(ctx, "_dashboard_execute_code_event_id", None)`
- **agent.py:create_child_orchestrator()** — accept + forward
- **orchestrator.py:359** — `object.__setattr__(_ra, "_rlm_parent_tool_call_id", ...)`

**`dispatch_call_index`** (per-execute_code monotonic counter):
- **dispatch.py:llm_query_batched_async** — read + advance `_dispatch_call_counter` on `ctx`:
  ```python
  dispatch_base = getattr(ctx, "_dispatch_call_counter", 0)
  object.__setattr__(ctx, "_dispatch_call_counter", dispatch_base + len(prompts))
  tasks = [_run_child(p, model, output_schema, idx,
                      dispatch_call_index=dispatch_base + idx)
           for idx, p in enumerate(prompts)]
  ```
- **dispatch.py:_run_child** — accept `dispatch_call_index`, pass to `create_child_orchestrator()`
- **agent.py:create_child_orchestrator()** — accept + forward
- **orchestrator.py:359** — `object.__setattr__(_ra, "_rlm_dispatch_call_index", ...)`
- Counter reset: plugin sets `_dispatch_call_counter=0` on InvocationContext in `before_tool_callback` for execute_code

### Step 2: `DashboardEventPlugin` (new file)

**New file**: `rlm_adk/plugins/dashboard_events.py`

```python
import threading

class DashboardEventPlugin(BasePlugin):
    def __init__(self, output_path=".adk/dashboard_events.jsonl"):
        self._pending_model: dict[str, dict] = {}       # keyed by invocation_id
        self._pending_tool: dict[int, dict] = {}         # keyed by id(tool_context)
        self._last_model_event_id: dict[str, str] = {}   # invocation_id → event_id
        self._write_lock = threading.Lock()               # NOT asyncio.Lock (R4-2)
        self._file_handle: TextIOWrapper | None = None

    async def before_model_callback(self, *, callback_context, llm_request):
        inv_id = inv_ctx.invocation_id
        self._pending_model[inv_id] = {"request": llm_request, ...}

    async def after_model_callback(self, *, callback_context, llm_response):
        event_id = uuid4().hex
        self._last_model_event_id[inv_id] = event_id
        self._write_event({"phase": "model", "event_id": event_id, ...})

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        event_id = uuid4().hex
        self._pending_tool[id(tool_context)] = {"event_id": event_id, ...}
        if tool.name == "execute_code":
            inv_ctx = tool_context._invocation_context
            object.__setattr__(inv_ctx, "_dashboard_execute_code_event_id", event_id)
            object.__setattr__(inv_ctx, "_dispatch_call_counter", 0)  # R4-1

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
        pending = self._pending_tool.pop(id(tool_context), None)
        model_event_id = self._last_model_event_id.get(inv_id)
        self._write_event({"phase": "tool", "model_event_id": model_event_id, ...})
        # Cleanup: set_model_response is terminal — no more model→tool pairs (R5-2)
        if getattr(tool, "name", "") == "set_model_response":
            self._last_model_event_id.pop(inv_id, None)

    def make_telemetry_finalizer(self):
        pending = self._pending_tool
        write = self._write_event       # synchronous — same path as callbacks (R4-2)

        def _finalize(tool_context_id: int, result: dict) -> None:
            entry = pending.pop(tool_context_id, None)
            if entry is None: return     # already finalized by after_tool_callback
            event = _build_tool_event_dict(entry, result)
            write(event)                 # synchronous inline (matches sqlite pattern)
        return _finalize

    def _write_event(self, event: dict) -> None:
        """Synchronous serialized JSONL append under threading.Lock.
        Safe from async callbacks AND sync GAP-06 finalizer."""
        with self._write_lock:
            if self._file_handle is None:
                self._output_path.parent.mkdir(parents=True, exist_ok=True)
                self._file_handle = open(self._output_path, "a")
            self._file_handle.write(json.dumps(event, default=str) + "\n")
            self._file_handle.flush()
```

### Step 3: Wire plugin + finalizer composition

**agent.py** — replace `RLM_CONTEXT_SNAPSHOTS` block with `DashboardEventPlugin` (always-on or env-gated):

```python
from rlm_adk.plugins.dashboard_events import DashboardEventPlugin
plugins.append(DashboardEventPlugin(
    output_path=f"{_adk_dir}/dashboard_events.jsonl",
))
```

**orchestrator.py:320-328** — compose finalizers from all plugins:

```python
finalizers = []
if plugin_manager:
    for plugin_name in ("sqlite_tracing", "dashboard_events"):
        plugin = plugin_manager.get_plugin(plugin_name)
        if plugin and hasattr(plugin, "make_telemetry_finalizer"):
            finalizers.append(plugin.make_telemetry_finalizer())
telemetry_finalizer = (
    (lambda fns: lambda tid, r: [f(tid, r) for f in fns])(finalizers)
    if finalizers else None
)
```

### Step 4: Event reader (new file, replaces live_loader.py)

**New file**: `rlm_adk/dashboard/event_reader.py` (~200 lines)

- `read_events(path) → list[StepEvent]` — JSONL reader
- `build_tree(events) → InvocationTree` — edge-based from `parent_tool_call_id` + `model_event_id`
- `events_for_invocation(tree, inv_id) → list[StepEvent]`
- `children_of_tool_event(tree, tool_event_id) → list[str]`

### Step 5: Split-panel notebook component (new file)

**New file**: `rlm_adk/dashboard/components/notebook_panel.py`

- Left column: parent steps as vertical cells (model banner + tool cell pairs)
- Right column: child invocation's events as horizontal scroll
- Batch selector tabs when `children_of_tool_event()` returns multiple invocation_ids
- Reuses: `flow_tool_call_cell.py`, `flow_connectors.py`, `flow_code_pane.py`

### Step 6: Controller + live_app wiring

- **live_controller.py** — replace pane/watermark with: read events, build tree, pass to notebook
- **live_app.py** — `/live` reads `dashboard_events.jsonl` directly

### Step 7: Remove superseded code

- Delete `ContextWindowSnapshotPlugin`, `context_snapshots.jsonl`/`model_outputs.jsonl` generation
- Delete `live_loader.py`, `live_models.py`, `data_loader.py` (~2400 lines)
- Delete `flow_builder.py` temporal ordering logic
- Update `dashboard/README.md`, `provider_fake/README.md`

---

## Verification

1. Run `pytest tests_rlm_adk/test_skill_arch_e2e.py -v -x`
2. Inspect `.adk/dashboard_events.jsonl`:
   - 30 events (15 model + 15 tool)
   - Every tool event has `model_event_id` pointing to its triggering model event
   - Every child event has both `parent_invocation_id` and `parent_tool_call_id`
   - Sequential `llm_query()` within one execute_code: same `parent_tool_call_id`, distinct `dispatch_call_index`
   - Sequential across execute_code blocks: distinct `parent_tool_call_id`
   - Concurrent batch children: not interleaved mid-line (`threading.Lock`)
   - `_pending_model` keyed by invocation_id — no collisions in parallel subtrees
   - Batch selector tabs in dispatch order (sorted by `dispatch_call_index`, not completion order)
   - `_last_model_event_id` cleaned up after `set_model_response` — no unbounded growth
3. Dashboard at `/live`: all 15 calls visible across panels, paired correctly

---

## Agent Team: Red/Green TDD Implementation

### Team definition

| Agent | Role | Context budget | Tools |
|-------|------|---------------|-------|
| **A: Plumbing** | Lineage plumbing in dispatch.py, agent.py, orchestrator.py | Small — 3 focused files | Edit, Bash (pytest) |
| **B: Plugin** | `DashboardEventPlugin` — callbacks, finalizer, JSONL writer | Medium — 1 new file + wiring in agent.py, orchestrator.py | Edit, Write, Bash (pytest) |
| **C: Reader** | `event_reader.py` — JSONL reader, tree builder, model/tool pairing | Medium — 1 new file | Edit, Write, Bash (pytest) |
| **D: UI** | `notebook_panel.py` — split-panel NiceGUI component | Large — 1 new file, reuses existing renderers | Edit, Write, Bash (pytest, dashboard launch) |
| **E: Cleanup** | Remove superseded code, update docs | Medium — multi-file deletion | Edit, Bash (pytest, ruff) |

### Red/Green TDD protocol

Each agent writes a **failing test first** (red), then the **minimal implementation** to pass it (green), then moves to the next test. Tests accumulate — each new green must not break prior greens.

**Test file convention**: `tests_rlm_adk/test_dashboard_events_<agent_letter>.py`

### Implementation DAG

```
                    ┌─────────────────────┐
                    │   A: Plumbing       │
                    │                     │
                    │ TDD cycles:         │
                    │ 1. parent_inv_id    │
                    │    propagates to    │
                    │    child reasoning  │
                    │    agent attr       │
                    │ 2. parent_tool_call │
                    │    _id reads from   │
                    │    InvocationCtx    │
                    │ 3. dispatch_call_   │
                    │    index counter    │
                    │    advances per     │
                    │    llm_query call   │
                    │                     │
                    │ ~3 TDD cycles       │
                    │ ~500 lines changed  │
                    └────────┬────────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
                ▼                         ▼
   ┌────────────────────┐    ┌────────────────────┐
   │   B: Plugin        │    │   C: Reader        │
   │                    │    │                    │
   │ TDD cycles:        │    │ TDD cycles:        │
   │ 1. before_model    │    │ 1. read_events     │
   │    stash +         │    │    parses JSONL     │
   │    after_model     │    │    into StepEvent   │
   │    finalize emits  │    │    list             │
   │    model StepEvent │    │ 2. build_tree       │
   │ 2. before_tool     │    │    groups by        │
   │    stash + after   │    │    invocation_id,   │
   │    _tool emits     │    │    links parent_    │
   │    tool StepEvent  │    │    tool_call_id     │
   │    with model_     │    │    edges, sorts     │
   │    event_id link   │    │    children by      │
   │ 3. execute_code    │    │    dispatch_call_   │
   │    sets InvCtx     │    │    index            │
   │    attrs +         │    │ 3. model/tool       │
   │    counter reset   │    │    pairing via      │
   │ 4. GAP-06 sync     │    │    model_event_id   │
   │    finalizer +     │    │ 4. children_of_     │
   │    threading.Lock  │    │    tool_event       │
   │ 5. finalizer       │    │    returns sorted   │
   │    composition     │    │    child inv_ids    │
   │    in orchestrator │    │                    │
   │ 6. _last_model_    │    │ ~4 TDD cycles      │
   │    event_id        │    │ ~200 lines new     │
   │    cleanup on      │    │                    │
   │    set_model_resp  │    │ Input: fixture     │
   │                    │    │ JSONL (hand-written │
   │ ~6 TDD cycles      │    │ from event stream  │
   │ ~400 lines new     │    │ example in plan)   │
   └────────┬───────────┘    └────────┬───────────┘
            │                         │
            └────────────┬────────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │   D: UI                │
            │                        │
            │ TDD cycles:            │
            │ 1. notebook_panel      │
            │    renders parent      │
            │    model banner +      │
            │    tool cells from     │
            │    InvocationTree      │
            │ 2. child panel         │
            │    horizontal scroll   │
            │    from children_of_   │
            │    tool_event          │
            │ 3. batch selector      │
            │    tabs switch active  │
            │    child by dispatch_  │
            │    call_index          │
            │ 4. live_controller     │
            │    wiring: read →      │
            │    build_tree → render │
            │ 5. live_app /live      │
            │    route reads         │
            │    dashboard_events    │
            │    .jsonl              │
            │                        │
            │ ~5 TDD cycles          │
            │ ~500 lines new         │
            └────────────┬───────────┘
                         │
                         ▼
            ┌────────────────────────┐
            │   E: Cleanup           │
            │                        │
            │ 1. Delete live_loader  │
            │    .py, live_models.py │
            │    data_loader.py,     │
            │    flow_builder.py     │
            │    temporal ordering   │
            │ 2. Delete Context      │
            │    WindowSnapshot      │
            │    Plugin + env var    │
            │ 3. Delete context_     │
            │    snapshots.jsonl /   │
            │    model_outputs.jsonl │
            │    generation          │
            │ 4. Update dashboard/   │
            │    README.md,          │
            │    provider_fake/      │
            │    README.md           │
            │ 5. ruff check pass     │
            │                        │
            │ ~5 deletion tasks      │
            │ ~2400 lines removed    │
            └────────────────────────┘
```

### Parallelism opportunities

- **A** runs first (dependency for B and C)
- **B and C run in parallel** after A completes — no dependencies between them. B writes JSONL, C reads JSONL. C can use a hand-written fixture JSONL matching the event stream example in this plan while B is still being built.
- **D** requires both B and C — needs the plugin to produce events AND the reader to parse them
- **E** runs last — must verify all tests pass before deleting superseded code

### TDD test sketches per agent

**Agent A** (3 tests):
```python
# test_dashboard_events_a.py
def test_parent_invocation_id_propagates():
    """Child orchestrator's reasoning agent has _rlm_parent_invocation_id set."""

def test_parent_tool_call_id_reads_from_invocation_context():
    """_run_child reads _dashboard_execute_code_event_id from ctx."""

def test_dispatch_call_index_increments_per_llm_query():
    """Sequential llm_query() calls get dispatch_call_index 0, 1, 2."""
```

**Agent B** (6 tests):
```python
# test_dashboard_events_b.py
def test_model_event_emitted_after_model_callback():
    """after_model_callback decomposes request + tokens → JSONL line with phase=model."""

def test_tool_event_carries_model_event_id():
    """after_tool_callback emits phase=tool with model_event_id pointing to preceding model event."""

def test_execute_code_sets_invocation_context_attrs():
    """before_tool_callback for execute_code sets _dashboard_execute_code_event_id and resets _dispatch_call_counter."""

def test_gap06_finalizer_emits_when_after_tool_skipped():
    """make_telemetry_finalizer closure emits tool event synchronously."""

def test_finalizer_composition_calls_both():
    """Combined finalizer calls both sqlite and dashboard finalizers."""

def test_last_model_event_id_cleaned_on_set_model_response():
    """_last_model_event_id entry removed after set_model_response tool event."""
```

**Agent C** (4 tests):
```python
# test_dashboard_events_c.py
def test_read_events_parses_jsonl():
    """read_events returns list[StepEvent] from JSONL file."""

def test_build_tree_links_parent_tool_call_id():
    """children_of_tool maps parent execute_code event_id → child invocation_ids."""

def test_build_tree_sorts_children_by_dispatch_call_index():
    """Batch children appear in dispatch order, not completion order."""

def test_model_tool_pairing_via_model_event_id():
    """steps[inv_id] pairs each model event with its tool event via model_event_id."""
```

**Agent D** (5 tests):
```python
# test_dashboard_events_d.py
def test_notebook_panel_renders_model_banner():
    """Parent panel shows LlmRequest banner for each model event."""

def test_notebook_panel_renders_tool_cells():
    """Parent panel shows tool result cells below model banners."""

def test_child_panel_activates_on_llm_query():
    """Right panel appears when execute_code has llm_query_detected=True."""

def test_batch_selector_tabs_in_dispatch_order():
    """Tabs ordered by dispatch_call_index, not completion order."""

def test_live_controller_reads_dashboard_events_jsonl():
    """Controller reads events, builds tree, passes to notebook."""
```
