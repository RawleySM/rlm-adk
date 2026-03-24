# Callback-Agent Expert Review: woolly-sprouting-mochi

## Plan Under Review

`/home/rawley-stanhope/dev/rlm-adk/proposals/woolly-sprouting-mochi.md`

---

## Question 1: Thread Bridge + Callbacks — Do Child Orchestrator Plugin Callbacks Fire Correctly?

### Verdict: YES, with one subtle hazard the plan does not discuss.

**Why it works**: The plan's thread bridge architecture is sound from a callback perspective. Here is the execution flow:

```
T1 (worker thread): exec(code) -> llm_query() -> run_coroutine_threadsafe(coro, loop)
T0 (event loop):    child orchestrator -> reasoning_agent.run_async(ctx)
                     -> ADK step loop -> _preprocess_async -> _call_llm_async
                     -> before_model_callback (plugin) -> before_model_callback (agent-local)
                     -> LLM call -> after_model_callback (plugin) -> after_model_callback (agent-local)
                     -> tool calls -> before_tool_callback -> after_tool_callback
```

All plugin callbacks (`SqliteTracingPlugin`, `ObservabilityPlugin`) fire on T0, the event loop thread. This is correct because:

1. `run_coroutine_threadsafe` schedules the child dispatch coroutine onto the event loop
2. T0 is free because `loop.run_in_executor` suspended the parent's `execute_code_threaded` awaitable (not the event loop itself)
3. ADK's callback dispatch is all coroutine-based (the `_handle_before_model_callback`, tool callback dispatch in `functions.py`) -- they run in the event loop naturally

**Hazard the plan MISSES: `SqliteTracingPlugin` instance-level state is not thread-safe across concurrent children.**

The `SqliteTracingPlugin` uses instance-level mutable state:
- `self._pending_model_telemetry: dict` (line 296)
- `self._pending_tool_telemetry: dict` (line 297)
- `self._model_call_count: int` (line 299)
- `self._deferred_tool_lineage: list` (line 302)
- `self._sse_seq: int` (line 304)
- `self._agent_span_stack: list` (line 306)

These are NOT protected by any lock. Under the thread bridge model, when multiple children are dispatched via `llm_query_batched()`, multiple child orchestrators run concurrently on T0 as asyncio tasks. Since asyncio is cooperative (single-thread), there is no data race per se -- but interleaving IS possible between `await` points. For example:

1. Child A's `before_model_callback` inserts telemetry and stores pending ID at `self._pending_model_telemetry[key_A]`
2. Child B's `before_model_callback` inserts telemetry at `self._pending_model_telemetry[key_B]`
3. Child A's `after_model_callback` uses `self._pending_key(callback_context)` -- if `id(callback_context)` was reused (unlikely but possible), wrong telemetry row gets updated

More critically, `self._agent_span_stack` is a flat list used as a stack. With interleaved child agents, Child A pushes "reasoning_agent", then Child B pushes "reasoning_agent", then Child A pops -- now the stack is wrong for Child B.

### Recommended Fix

Add to Phase 4 (Observability):

> **GAP-BRIDGE-01**: `SqliteTracingPlugin._agent_span_stack` will produce incorrect agent_name attribution when batched children interleave. The span stack must be scoped per-invocation, not per-plugin-instance. Replace the flat list with a dict keyed by `invocation_id`. Similarly, `_pending_model_telemetry` and `_pending_tool_telemetry` use `id(callback_context)` as keys -- this is safe because `id()` values are unique for live objects and these dicts are cleaned up in after_* callbacks, but document this assumption explicitly.

---

## Question 2: SkillToolset Tool Callbacks — Does the Plan Account for Telemetry Capture?

### Verdict: PARTIALLY. The plan claims "No changes needed" in Phase 4C. This is WRONG.

**What the plan says (Phase 4C)**:
> "No changes needed -- SkillToolset tools are regular ADK tools, captured by existing before_tool_callback / after_tool_callback. The skill_instruction and skill_name_loaded telemetry columns already exist."

**What actually happens**: This is correct at the surface level -- `SqliteTracingPlugin.before_tool_callback` and `after_tool_callback` will fire for `load_skill`, `load_skill_resource`, `list_skills`, and `run_skill_script` because they are plugin callbacks (global). The telemetry columns `skill_name_loaded` (line 229) and `skill_instructions_len` (line 230) already exist in the schema.

**What the plan MISSES**:

### MISS 2A: `decision_mode` classification does not handle SkillToolset tool names

In `SqliteTracingPlugin.after_tool_callback` (line 1291-1303), `decision_mode` is only set for two tool names:

```python
if tool_name == "set_model_response":
    update_kwargs["decision_mode"] = "set_model_response"
elif tool_name == "execute_code":
    update_kwargs["decision_mode"] = "execute_code"
```

When `load_skill` or `load_skill_resource` is called, `decision_mode` will be set to the raw `tool_name` in `before_tool_callback` (line 1244: `decision_mode=tool_name`), which means it will be `"load_skill"` or `"load_skill_resource"`. This actually **works by accident** because `LineageEnvelope.decision_mode` (types.py line 273-278) already includes these as valid literals:

```python
decision_mode: Literal[
    "execute_code",
    "set_model_response",
    "load_skill",
    "load_skill_resource",
    "unknown",
] = "unknown"
```

However, `list_skills` and `run_skill_script` are NOT in the `Literal` type. If the model ever calls `list_skills`, the `decision_mode` value `"list_skills"` will be written to SQLite (no schema validation there) but will fail Pydantic validation if anyone constructs a `LineageEnvelope` from it.

**Action**: Add `"list_skills"` and `"run_skill_script"` to the `LineageEnvelope.decision_mode` Literal type in `types.py`.

### MISS 2B: `skill_name_loaded` is never populated

The telemetry column `skill_name_loaded` exists (line 229) but is NEVER written to by any callback. `SqliteTracingPlugin.after_tool_callback` does not extract the skill name from the `load_skill` tool's args or result. The plan should add extraction logic:

```python
# In after_tool_callback, after the existing decision_mode block:
if tool_name in ("load_skill", "load_skill_resource"):
    update_kwargs["decision_mode"] = tool_name
    skill_name = tool_args.get("name") or tool_args.get("skill_name")
    if skill_name:
        update_kwargs["skill_name_loaded"] = skill_name
    # Also capture instruction length from result
    if isinstance(result, dict):
        instructions = result.get("instructions") or result.get("content") or ""
        if isinstance(instructions, str):
            update_kwargs["skill_instructions_len"] = len(instructions)
```

### MISS 2C: No observability state key writes for skill loading events

The plan adds `SKILL_REPL_GLOBALS_INJECTED` but has no state key for tracking which skills the model actually loaded at runtime via `load_skill`. ADK's internal `_adk_activated_skill_{agent_name}` key is private and not in the curated capture set. The plan should add:

```python
# state.py
SKILL_LOADED_NAMES = "skill_loaded_names"  # list of skill names loaded via load_skill
```

And `should_capture_state_key` should either include this key in `CURATED_STATE_KEYS` or add a `"skill_"` prefix to `CURATED_STATE_PREFIXES`.

---

## Question 3: `before_agent_callback` vs `process_llm_request` — Ordering Conflict?

### Verdict: NO conflict, but the plan's reasoning is incomplete and there is a SUBTLE interaction.

**Verified ADK execution order** (from reading `base_llm_flow.py`):

The ADK step loop in `_run_one_step_async` (line 766) does:

1. `_preprocess_async` (line 774) which calls:
   - Request processors (line 862)
   - `_resolve_toolset_auth` (line 871)
   - `_process_agent_tools` (line 881) -- this calls `SkillToolset.process_llm_request()` which appends L1 skill XML to `llm_request`
2. `_call_llm_async` (line 831) which calls:
   - `_handle_before_model_callback` (line 1110) -- this runs plugin `before_model_callback` first, then agent-local `before_model_callback` (i.e., `reasoning_before_model`)

And separately, the agent lifecycle:

3. `before_agent_callback` fires ONCE per agent run (before `_run_async_impl`), NOT per step

**Therefore the ordering is**:

```
[once] before_agent_callback (plugin, then agent-local _seed_skill_instruction)
  -> [per step] _process_agent_tools -> SkillToolset.process_llm_request() -> appends L1 XML
  -> [per step] before_model_callback (plugin SqliteTracingPlugin, then agent-local reasoning_before_model)
  -> [per step] LLM call
```

**No conflict**: `_seed_skill_instruction` writes to `callback_context.state[DYN_SKILL_INSTRUCTION]` once at agent start. `SkillToolset.process_llm_request()` appends L1 XML to `llm_request.instructions` at each step. `reasoning_before_model` then merges the dynamic instruction (resolved from state) into `system_instruction`. These are additive, not conflicting.

**HOWEVER, the plan MISSES a subtle interaction**:

`SkillToolset.process_llm_request()` calls `llm_request.append_instructions(instructions)` which appends to `llm_request.config.system_instruction`. Then `reasoning_before_model` REPLACES `llm_request.config.system_instruction` with its own merged version (static + dynamic). This means:

**The L1 skill XML injected by `SkillToolset.process_llm_request()` will be OVERWRITTEN by `reasoning_before_model`.**

This is a critical bug. `reasoning_before_model` (line 144-146) does:

```python
if system_instruction_text:
    llm_request.config = llm_request.config or types.GenerateContentConfig()
    llm_request.config.system_instruction = system_instruction_text
```

It overwrites `system_instruction` entirely with the merged static+dynamic text, discarding whatever `SkillToolset.process_llm_request()` appended.

### Recommended Fix

Modify `reasoning_before_model` to PRESERVE existing system_instruction content added by `process_llm_request`:

```python
# In reasoning_before_model, after computing system_instruction_text:
# Preserve any instructions already appended by toolset processors (e.g., SkillToolset L1 XML)
existing_si = _extract_system_instruction_text(llm_request)
if existing_si != static_si:
    # Something was appended between static_instruction resolution and this callback
    # (e.g., SkillToolset.process_llm_request appended L1 XML)
    toolset_additions = existing_si[len(static_si):].strip()
    if toolset_additions:
        system_instruction_text += "\n\n" + toolset_additions
```

Or, better: restructure `reasoning_before_model` to APPEND to the existing `system_instruction` rather than replace it. This is the cleaner fix.

---

## Question 4: State Key Hygiene Across Data Planes

### Verdict: The plan's state key additions are INSUFFICIENT.

**What the plan adds**: `SKILL_REPL_GLOBALS_INJECTED` (Phase 4A) -- a list of function names injected into REPL globals.

**What is missing**:

### MISS 4A: Runtime skill activation tracking

ADK's `LoadSkillTool` writes `_adk_activated_skill_{agent_name}` to `tool_context.state`. This is an ADK-internal key that:
- Is NOT in `CURATED_STATE_KEYS` or `CURATED_STATE_PREFIXES`
- Will NOT be captured by `SqliteTracingPlugin.on_event_callback` (which filters via `should_capture_state_key`)
- Will NOT be visible in the `session_state_events` table

The plan should either:
1. Add `"_adk_activated_skill_"` to `CURATED_STATE_PREFIXES`, OR
2. Write a parallel RLM-owned key in a custom `after_tool_callback` handler that fires for `load_skill`

Option 2 is cleaner (don't capture ADK-internal keys; maintain your own):

```python
SKILL_ACTIVATED_NAMES = "skill_activated_names"  # list[str] — skills loaded via load_skill at runtime
```

### MISS 4B: Per-depth skill availability

The plan does not address depth-scoping for skills. When a child orchestrator at depth 1 runs, should it have the same skills as depth 0? The `enabled_skills` tuple flows through `create_child_orchestrator` but the plan does not discuss:
- Whether `SkillToolset` should be recreated per child or shared
- Whether `SKILL_REPL_GLOBALS_INJECTED` should be depth-scoped (added to `DEPTH_SCOPED_KEYS`)
- Whether child orchestrators should inherit the parent's activated skills

**Recommendation**: `SKILL_REPL_GLOBALS_INJECTED` should NOT be in `DEPTH_SCOPED_KEYS` because REPL globals injection happens at orchestrator creation time and each child orchestrator creates its own REPL. However, the plan should explicitly state that each child orchestrator gets its own `SkillToolset` instance (or none, if `enabled_skills` is empty for children).

### MISS 4C: Skill function invocation tracking in the REPL

There is no mechanism to track WHEN a skill function is actually called inside REPL code (as opposed to when `load_skill` is called by the model). The plan injects skill functions into `repl.globals` but provides no instrumentation for:
- How many times each skill function was invoked per REPL execution
- Whether the skill function's internal `llm_query()` calls succeeded or failed
- Timing of skill function execution

This is a future concern, not a Phase 1 blocker, but the plan should acknowledge the gap and suggest that skill functions could be wrapped with a lightweight decorator at injection time:

```python
def _instrument_skill_fn(fn, skill_name):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # increment counter in a thread-local or REPL-local accumulator
        return fn(*args, **kwargs)
    return wrapper
```

---

## Question 5: Plugin vs Agent-Local Callback Placement for Skill Tracking

### Verdict: Piggyback on existing `SqliteTracingPlugin` with targeted additions; do NOT create a new plugin.

**Analysis of the three options**:

### Option A: New plugin (global) -- REJECTED

A new `SkillTracingPlugin` would add another entry to `plugins=[...]` and would fire for every agent/model/tool globally. This creates:
- Another plugin in the callback chain (slows every callback dispatch)
- Potential short-circuit risk (if it accidentally returns non-None)
- Unnecessary when only 2-3 tool names (`load_skill`, `load_skill_resource`) need handling

### Option B: Agent-local callbacks on reasoning_agent -- PARTIALLY REJECTED

Agent-local callbacks cannot be used because the `after_tool_callback` slot on `reasoning_agent` is already occupied by `make_worker_tool_callbacks()` (orchestrator.py line 362-364):

```python
after_tool_cb, on_tool_error_cb = make_worker_tool_callbacks(max_retries=2)
object.__setattr__(self.reasoning_agent, "after_tool_callback", after_tool_cb)
```

ADK only supports ONE `after_tool_callback` per agent instance. Adding skill tracking here would require modifying `make_worker_tool_callbacks()` to compose with skill-tracking logic, which conflates two unrelated concerns.

**HOWEVER**, there is one case where agent-local IS correct: the `before_agent_callback` for `_seed_skill_instruction` already uses the agent-local slot. The plan correctly uses this for one-time setup.

### Option C: Piggyback on SqliteTracingPlugin -- RECOMMENDED

This is the correct approach because:
1. `SqliteTracingPlugin` already fires for all tools globally
2. The `before_tool_callback` and `after_tool_callback` already insert/update telemetry rows
3. The `skill_name_loaded` and `skill_instructions_len` columns already exist
4. Only 5-10 lines of additional logic are needed in `after_tool_callback`

**Specific changes to SqliteTracingPlugin.after_tool_callback**:

```python
# After the existing decision_mode block (line 1291-1303), add:
elif tool_name in ("load_skill", "load_skill_resource", "list_skills"):
    update_kwargs["decision_mode"] = tool_name
    skill_name = tool_args.get("name") or tool_args.get("skill_name")
    if skill_name:
        update_kwargs["skill_name_loaded"] = skill_name
    if isinstance(result, dict):
        instr = result.get("instructions") or result.get("content") or ""
        if isinstance(instr, str):
            update_kwargs["skill_instructions_len"] = len(instr)
```

---

## Summary of Plan Deficiencies (Ordered by Severity)

### CRITICAL (will cause incorrect behavior)

1. **`reasoning_before_model` overwrites SkillToolset L1 XML** (Question 3): `process_llm_request()` appends skill XML to `system_instruction`, then `reasoning_before_model` replaces `system_instruction` entirely. Skills will NEVER appear in the model's system instruction. This is a silent failure -- the model will never see skill descriptions and will never call `load_skill`.

### HIGH (observability gaps)

2. **`skill_name_loaded` column never populated** (Question 2B): The telemetry schema has the column but no code writes to it. Add extraction in `after_tool_callback` for `load_skill` tool calls.

3. **`LineageEnvelope.decision_mode` missing `list_skills` and `run_skill_script`** (Question 2A): These tool names will produce invalid enum values if used to construct a `LineageEnvelope`.

4. **No runtime skill activation state key** (Question 4A): ADK's internal `_adk_activated_skill_*` key is not captured. Add an RLM-owned key to track which skills were loaded.

### MEDIUM (correctness risks under concurrency)

5. **`_agent_span_stack` interleaving under batched children** (Question 1): The flat stack will produce wrong agent_name attribution when concurrent child orchestrators interleave on the event loop. Scope per invocation_id.

### LOW (documentation / future gaps)

6. **No skill function invocation instrumentation** (Question 4C): Skill functions injected into REPL globals are opaque to telemetry. Acknowledge the gap.

7. **Per-depth skill availability not discussed** (Question 4B): The plan should explicitly state whether child orchestrators get SkillToolset and/or REPL globals.

---

## Recommended Phase 4 Revision

Replace the plan's Phase 4 ("Observability") with:

### 4A. State keys (`rlm_adk/state.py`)

```python
SKILL_REPL_GLOBALS_INJECTED = "skill_repl_globals_injected"  # list of function names
SKILL_ACTIVATED_NAMES = "skill_activated_names"              # list of skills loaded via load_skill
```

Add `"skill_"` to `CURATED_STATE_PREFIXES` so both keys are captured by `should_capture_state_key`.

### 4B. Fix `reasoning_before_model` to preserve `process_llm_request` additions

In `reasoning_before_model` (`rlm_adk/callbacks/reasoning.py`), change the system_instruction merge to APPEND to the existing value rather than REPLACE it. The existing `_extract_system_instruction_text` already reads the current value; the callback should only append the dynamic instruction, not overwrite.

### 4C. LineageEnvelope decision_mode expansion (`rlm_adk/types.py`)

Add `"list_skills"` and `"run_skill_script"` to the `decision_mode` Literal type.

### 4D. SqliteTracingPlugin skill telemetry (`rlm_adk/plugins/sqlite_tracing.py`)

Add `load_skill` / `load_skill_resource` / `list_skills` handling in `after_tool_callback` to populate `skill_name_loaded` and `skill_instructions_len` columns.

### 4E. Execution mode tracking

In `REPLTool.run_async()` return dict, add `"execution_mode": "thread_bridge"` (or `"async_rewrite"` / `"sync"` for fallback). Also in `LAST_REPL_RESULT` summary.

### 4F. Document per-invocation scoping need for `_agent_span_stack`

File a follow-up to scope `_agent_span_stack` per `invocation_id` instead of per plugin instance, to prevent interleaving under batched child dispatch.
