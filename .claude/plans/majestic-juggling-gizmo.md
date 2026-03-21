# Plan: Child Event Re-Emission via Queue (Path A)

## Context

The lineage/completion/state plane refactor correctly stopped using session state as a telemetry bus, but it also silenced working-state events from recursive child `RLMOrchestratorAgent`s. In `dispatch.py:332-336`, child events are consumed into a local `_child_state` dict and never reach the ADK Runner's `_exec_with_plugin` loop. This means:

- Child state events are **not persisted** to `session.db`
- `SqliteTracingPlugin.on_event_callback` **never fires** for child events
- The `session_state_events` table in `traces.db` has **zero rows with `key_depth > 0`**

The session service (`SqliteSessionService`) is standard ADK — no refactor needed. The gap is upstream: child events never reach `session_service.append_event()`.

### Why this matters

The RLM architecture evolves a disorganized problem space into an organized world model through recursive layering. Child state events (iteration counts, REPL code submissions, stop decisions) are the fossil record of that cognitive work. Without them, we can't observe emergent topology or validate patterns for skill hardening.

### Solution: asyncio.Queue bridge

The call stack from child to Runner is non-generator (`_run_child` → `llm_query_async` → REPL exec → `REPLTool.run_async` → returns dict), so events can't yield through it. But the orchestrator IS a generator (`async for event in reasoning_agent.run_async(ctx): yield event`). We bridge the gap with an `asyncio.Queue`: dispatch pushes curated child events onto it; the orchestrator drains it after each yielded event.

```
dispatch._run_child()                    orchestrator._run_async_impl()
  async for _event in child.run_async:     async for event in reasoning_agent.run_async:
    if curated state-delta:                    yield event
      queue.put_nowait(event)  ──────>         while not queue.empty():
                                                   yield queue.get_nowait()
```

Causal ordering is natural: child events accumulate during tool execution, drain after the tool-response event, and appear before the next LLM call.

---

## Phase 1: Extract key-parsing utilities to `state.py`

Both `dispatch.py` and `sqlite_tracing.py` need `parse_key()` and `should_capture_state_key()`. Currently these live only in `sqlite_tracing.py`. Extract them to `state.py` (where key definitions already live) to avoid coupling dispatch to a plugin.

### `rlm_adk/state.py` — add at bottom (after `depth_key`)

```python
import re

_DEPTH_FANOUT_RE = re.compile(r"^(.+)@d(\d+)(?:f(\d+))?$")

def parse_depth_key(raw_key: str) -> tuple[str, int, int | None]:
    """Parse depth/fanout suffix from a state key. Inverse of depth_key().
    Returns (base_key, depth, fanout_or_None).
    """
    m = _DEPTH_FANOUT_RE.match(raw_key)
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3)) if m.group(3) else None
    return raw_key, 0, None

CURATED_STATE_KEYS = frozenset({
    CURRENT_DEPTH, ITERATION_COUNT, SHOULD_STOP,
    FINAL_RESPONSE_TEXT, LAST_REPL_RESULT, DYN_SKILL_INSTRUCTION,
})

CURATED_STATE_PREFIXES = (
    "obs:artifact_", "artifact_", "last_repl_result",
    "repl_submitted_code", "repl_expanded_code",
    "repl_skill_expansion_meta", "repl_did_expand",
)

def should_capture_state_key(base_key: str) -> bool:
    """Return True if this state key should be captured for observability."""
    if base_key in CURATED_STATE_KEYS:
        return True
    return any(base_key.startswith(p) for p in CURATED_STATE_PREFIXES)
```

### `rlm_adk/plugins/sqlite_tracing.py` — refactor to import from state.py

Replace the local `_DEPTH_FANOUT_RE`, `_parse_key`, `_CURATED_EXACT`, `_CURATED_PREFIXES`, `_should_capture` (lines 44-129) with imports:

```python
from rlm_adk.state import parse_depth_key, should_capture_state_key, CURATED_STATE_KEYS, CURATED_STATE_PREFIXES
```

Keep `_categorize_key` in sqlite_tracing (it's plugin-specific). Alias for internal use: `_parse_key = parse_depth_key` and `_should_capture = should_capture_state_key` if you want minimal diff in the rest of the file.

---

## Phase 2: Add `child_event_queue` to dispatch closures

### `rlm_adk/dispatch.py`

**Signature change** (line 108-117): Add optional `child_event_queue` parameter.

```python
def create_dispatch_closures(
    dispatch_config: DispatchConfig,
    ctx: InvocationContext,
    ...
    fanout_idx: int = 0,
    child_event_queue: "asyncio.Queue[Event] | None" = None,  # NEW
) -> tuple[Any, Any, Any]:
```

**New imports** (top of file):

```python
from google.adk.events import Event, EventActions
from rlm_adk.state import parse_depth_key, should_capture_state_key
```

**Modify `_run_child` event loop** (lines 332-336):

```python
async for _event in child.run_async(child_ctx):
    actions = getattr(_event, "actions", None)
    state_delta = getattr(actions, "state_delta", None) if actions else None
    if isinstance(state_delta, dict):
        _child_state.update(state_delta)
        # Push curated state-delta events onto queue for parent re-emission
        if child_event_queue is not None:
            curated = {
                k: v for k, v in state_delta.items()
                if should_capture_state_key(parse_depth_key(k)[0])
            }
            if curated:
                child_event_queue.put_nowait(Event(
                    invocation_id=ctx.invocation_id,
                    author=_event.author or f"child_d{depth + 1}f{fanout_idx}",
                    branch=child_ctx.branch,
                    actions=EventActions(state_delta=curated),
                    custom_metadata={
                        "rlm_child_event": True,
                        "child_depth": depth + 1,
                        "child_fanout_idx": fanout_idx,
                    },
                ))
```

Key decisions:
- `put_nowait`: Queue is unbounded, never blocks. Safe because child events are finite per run.
- `author`: Preserve original event author (usually the child's reasoning agent name). Fall back to synthetic `child_dNfM`.
- `branch`: Carry the child's branch for traceability.
- `invocation_id`: Use parent's `ctx.invocation_id` so Runner associates the event with the current invocation.
- Only `state_delta` events with curated keys pass through. Content events, partial events, and non-state events are filtered out.

---

## Phase 3: Drain queue in orchestrator yield loop

### `rlm_adk/orchestrator.py`

**Create queue** (after line 270, before `create_dispatch_closures` call):

```python
_child_event_queue: asyncio.Queue[Event] | None = None
if self.worker_pool is not None:
    _child_event_queue = asyncio.Queue()
```

**Pass to dispatch** (lines 277-285): Add `child_event_queue=_child_event_queue`.

**Drain after each yield** (lines 500-501):

```python
async for event in self.reasoning_agent.run_async(ctx):
    yield event
    # Drain child events accumulated during tool execution
    if _child_event_queue is not None:
        while not _child_event_queue.empty():
            try:
                yield _child_event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
```

**Final drain** after the retry loop completes (after line 540, before completion collection):

```python
# Final drain of any remaining child events
if _child_event_queue is not None:
    while not _child_event_queue.empty():
        try:
            yield _child_event_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
```

This covers edge cases where the last tool call produces child events but reasoning_agent terminates (via `set_model_response`) without yielding another event to trigger a drain.

---

## Phase 4: Verify SqliteTracingPlugin (minimal/no changes)

### `rlm_adk/plugins/sqlite_tracing.py`

The `on_event_callback` (lines 1541-1568) already handles this correctly:

1. Re-emitted child events flow through Runner → `on_event_callback`
2. `_insert_sse` calls `_parse_key(raw_key)` → extracts `key_depth > 0`
3. `_should_capture(base_key)` passes (curated keys only were re-emitted)
4. Row inserted with `key_depth=1` (or 2, etc.), `event_author="child_reasoning_d1"` etc.

**No code changes needed in `on_event_callback` or `_insert_sse`.** The infrastructure was built to handle depth-scoped keys — it was just starved of input.

After Phase 1's refactor (import from state.py), verify `_insert_sse` still works identically. This is a thin-alias verification, not a behavior change.

---

## Phase 5: Tests

### New file: `tests_rlm_adk/test_child_event_reemission.py`

**Test 1: Curated filter unit test** — Verify `should_capture_state_key` accepts curated keys and rejects non-curated keys. Verify `parse_depth_key` round-trips with `depth_key`.

**Test 2: Queue population in dispatch** — Mock a child orchestrator that yields events with depth-scoped state_delta. Verify the queue receives curated events with correct `custom_metadata`.

**Test 3: End-to-end with `recursive_ping` fixture** — Run a recursive fixture through `create_rlm_runner`. Collect all events from `runner.run_async()`. Assert events exist with `custom_metadata.get("rlm_child_event") == True` and `key_depth > 0` in their `state_delta` keys.

**Test 4: `session_state_events` rows with `key_depth > 0`** — After a recursive run, query `traces.db` for `SELECT * FROM session_state_events WHERE key_depth > 0`. Assert rows exist for `iteration_count`, `current_depth`, etc.

**Test 5: Backward compatibility** — Run a depth-0-only fixture. Assert zero child events in the event stream and zero `key_depth > 0` rows in `session_state_events`.

**Test 6: Concurrent children** — Use a fixture or mock that dispatches K>1 children via `llm_query_batched_async`. Assert events from all fanout indices appear in the stream, distinguishable by `custom_metadata["child_fanout_idx"]`.

---

## Phase 6: Documentation

- `rlm_adk_docs/dispatch_and_state.md` — Add "Child Event Re-Emission" section documenting queue mechanism, curated filter, causal ordering.
- `rlm_adk_docs/observability.md` — Note that `session_state_events` with `key_depth > 0` now represents child state evolution. `event_author` carries child provenance.
- Memory update — Record the architectural decision and key patterns.

---

## Files modified (summary)

| File | Change |
|---|---|
| `rlm_adk/state.py` | Add `parse_depth_key`, `should_capture_state_key`, `CURATED_STATE_KEYS`, `CURATED_STATE_PREFIXES` |
| `rlm_adk/dispatch.py` | Accept `child_event_queue`, push curated events in `_run_child` loop |
| `rlm_adk/orchestrator.py` | Create `asyncio.Queue`, pass to dispatch, drain after each yield |
| `rlm_adk/plugins/sqlite_tracing.py` | Import from state.py, remove duplicated definitions |
| `tests_rlm_adk/test_child_event_reemission.py` | New test file (6 tests) |
| `rlm_adk_docs/dispatch_and_state.md` | Document child event re-emission |
| `rlm_adk_docs/observability.md` | Document `key_depth > 0` in session_state_events |

## Verification

```bash
# Run default contract tests (should all pass, no regression)
.venv/bin/python -m pytest tests_rlm_adk/ -x -q

# Run new child event tests specifically
.venv/bin/python -m pytest tests_rlm_adk/test_child_event_reemission.py -x -q

# Lint
ruff check rlm_adk/ tests_rlm_adk/
ruff format --check rlm_adk/ tests_rlm_adk/

# Live validation: run with recursive fixture and inspect traces.db
.venv/bin/adk run --replay tests_rlm_adk/replay/recursive_ping.json rlm_adk
# Then: sqlite3 rlm_adk/.adk/traces.db "SELECT state_key, key_depth, event_author FROM session_state_events WHERE key_depth > 0"
```
