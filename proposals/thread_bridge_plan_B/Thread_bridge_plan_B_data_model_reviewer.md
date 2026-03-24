# Data Model Review: woolly-sprouting-mochi (Thread Bridge + SkillToolset)

**Reviewer role**: Data Modeler -- state key design, Pydantic data models, three-plane architecture
**Plan reviewed**: `/home/rawley-stanhope/dev/rlm-adk/proposals/woolly-sprouting-mochi.md`
**Date**: 2026-03-24

---

## Question 1: LineageEnvelope.decision_mode and SkillToolset tools

### Current state

`LineageEnvelope.decision_mode` (in `rlm_adk/types.py:273`) defines five literals: `"execute_code"`, `"set_model_response"`, `"load_skill"`, `"load_skill_resource"`, `"unknown"`.

The `"load_skill"` and `"load_skill_resource"` values are forward-compatible plumbing -- no code path currently produces them. The `skill_state.md` analysis (line 98) confirms: "Forward-compatible plumbing -- it would work if a skill toolset were wired, but currently no code path produces these values since RLMSkillToolset is not wired."

### How decision_mode is currently set

There are exactly two producers of `decision_mode` in the telemetry pipeline:

1. **`sqlite_tracing.py` before_tool_callback (line 1244)**: Sets `decision_mode=tool_name` as a raw pass-through of whatever `tool.name` is. This means *any* ADK tool's name string becomes the initial decision_mode.

2. **`sqlite_tracing.py` after_tool_callback (lines 1291-1303)**: Overwrites with explicit string literals for known tools: `"set_model_response"` and `"execute_code"`. Any other tool name falls through with the raw `tool.name` from the before_tool insert.

### Gap in the plan

The plan (Phase 3A) states: "ADK's `_process_agent_tools` handles the rest... Extracts individual tools via `get_tools()` -> `list_skills`, `load_skill`, `load_skill_resource`, `run_skill_script`." The plan (Phase 4C) then claims: "No changes needed -- `SkillToolset` tools are regular ADK tools, captured by existing `before_tool_callback` / `after_tool_callback`."

This is **partially correct but incomplete**:

- **Correct**: The `before_tool_callback` will fire for `load_skill`, `load_skill_resource`, `list_skills`, and `run_skill_script` because they are regular ADK tools. The `decision_mode` column will receive the raw tool name from line 1244.
- **Incomplete**: The `after_tool_callback` (line 1291-1303) only has `if/elif` branches for `"set_model_response"` and `"execute_code"`. SkillToolset tool names will fall through with no explicit handling. The `decision_mode` column will contain the raw tool name (e.g., `"load_skill"`), which *coincidentally* matches the `LineageEnvelope` literal. But this is accidental alignment, not deliberate wiring.

### Recommendations

**R1.1**: Add explicit `elif` branches in `sqlite_tracing.py` `after_tool_callback` for SkillToolset tool names. This makes the mapping deliberate rather than accidental:

```python
elif tool_name == "load_skill":
    update_kwargs["decision_mode"] = "load_skill"
    # Extract skill name from tool_args for skill_name_loaded column
    if isinstance(tool_args, dict):
        update_kwargs["skill_name_loaded"] = tool_args.get("name")
    if isinstance(result, dict):
        instructions = result.get("instructions", "")
        update_kwargs["skill_instructions_len"] = len(instructions)
elif tool_name == "load_skill_resource":
    update_kwargs["decision_mode"] = "load_skill_resource"
    if isinstance(tool_args, dict):
        update_kwargs["skill_name_loaded"] = tool_args.get("skill_name")
```

**R1.2**: Expand the `LineageEnvelope.decision_mode` Literal to include `"list_skills"` and `"run_skill_script"` since ADK's `SkillToolset.get_tools()` exposes four tools, not two. The current Literal was designed when only the custom `RLMSkillToolset` was considered, which only had `load_skill` and `load_skill_resource`. With upstream `SkillToolset`, all four tool names should be covered:

```python
decision_mode: Literal[
    "execute_code",
    "set_model_response",
    "load_skill",
    "load_skill_resource",
    "list_skills",
    "run_skill_script",
    "unknown",
] = "unknown"
```

**R1.3**: The `_build_lineage` function in `callbacks/reasoning.py` (line 97) builds `LineageEnvelope` from agent runtime attrs but does NOT set `decision_mode` -- it always gets the default `"unknown"`. This function is called from `before_model_callback`, not tool callbacks, so this is correct behavior (model calls don't have a decision_mode). No change needed here, but worth documenting that LineageEnvelope is used at two different points: model-call lineage (decision_mode=unknown) and tool-call lineage (decision_mode set by sqlite_tracing).

---

## Question 2: REPLResult model and execution_mode

### Current state

`REPLResult(BaseModel)` in `rlm_adk/types.py:216` has these fields:
- `stdout: str`
- `stderr: str`
- `locals: dict`
- `execution_time: float | None`
- `llm_calls: list[RLMChatCompletion]`
- `trace: dict[str, Any] | None`

The plan (Phase 4B) says: "In `REPLTool.run_async()` return dict, add `"execution_mode": "thread_bridge"` (or `"async_rewrite"` / `"sync"` for fallback). Also in `LAST_REPL_RESULT` summary."

### Analysis

The plan proposes adding `execution_mode` to the **return dict** (the dict returned to ADK/model) and to the **LAST_REPL_RESULT state dict**, but NOT to the `REPLResult` Pydantic model. This creates a data model inconsistency:

1. `REPLTrace` (dataclass in `repl/trace.py:32`) already has `execution_mode: str = "sync"` and serializes it in `to_dict()` and `summary()`. This is the authoritative source of execution mode during tracing.

2. `REPLResult` does NOT have an `execution_mode` field. The trace data is carried in `REPLResult.trace` as an opaque dict.

3. The return dict to ADK (`normal_result` at `repl_tool.py:347`) is an ad-hoc dict, not a `REPLResult.to_dict()`. It contains `stdout`, `stderr`, `variables`, `llm_calls_made`, `call_number` -- none of which come from REPLResult directly.

### Recommendations

**R2.1**: Do NOT add `execution_mode` as a formal field on `REPLResult(BaseModel)`. The REPLResult model represents REPL execution output. Execution mode is a property of the tool dispatch path, not the REPL result. It already lives correctly in `REPLTrace.execution_mode`.

**R2.2**: DO add `execution_mode` to the `LAST_REPL_RESULT` state dict (the observability summary written to `tool_context.state`). This is the right place because it's the telemetry/state plane.

**R2.3**: DO add `execution_mode` to the return dict, but recognize this is for model-facing observability only. The model can see which execution path ran, which is useful for debugging but not load-bearing.

**R2.4**: Update `REPLTrace.execution_mode` to support the new `"thread_bridge"` value. Currently the field is typed as `str` with values `"sync"` and `"async"`. The new path adds `"thread_bridge"`. Consider making this an enum or Literal for type safety:

```python
execution_mode: Literal["sync", "async", "thread_bridge"] = "sync"
```

This is the single source of truth for execution mode; the LAST_REPL_RESULT dict and return dict should read from `trace.execution_mode` rather than being set independently.

---

## Question 3: LAST_REPL_RESULT summary and skill_functions_called tracking

### Current state

`LAST_REPL_RESULT` is built at `repl_tool.py:314-327`:

```python
last_repl: dict[str, Any] = {
    "code_blocks": 1,
    "has_errors": bool(result.stderr),
    "has_output": bool(result.stdout),
    "total_llm_calls": len(result.llm_calls),
    "stdout_preview": result.stdout[:500],
    "stdout": result.stdout,
    "stderr": result.stderr,
    "submitted_code_chars": len(code),
    "submitted_code_hash": code_hash,
}
if trace is not None:
    last_repl["trace_summary"] = trace.summary()
```

### Recommendations

**R3.1**: Add `execution_mode` to LAST_REPL_RESULT, sourced from the trace when available:

```python
if trace is not None:
    last_repl["trace_summary"] = trace.summary()
    last_repl["execution_mode"] = trace.execution_mode
else:
    last_repl["execution_mode"] = "thread_bridge" if self._use_thread_bridge else "sync"
```

**R3.2**: Consider adding `skill_functions_available` (not `called`) to LAST_REPL_RESULT. Tracking which skill functions were *called* during execution would require AST analysis or runtime instrumentation of the REPL globals, which is heavyweight. Instead, record what was *available*:

```python
last_repl["skill_globals_count"] = len(self._injected_skill_names) if hasattr(self, '_injected_skill_names') else 0
```

This is lighter-weight and still useful for telemetry. Do NOT try to track individual function calls at the REPL level -- that belongs in the REPL tracing infrastructure (trace level 1+).

**R3.3**: Add `skill_expansion_occurred` to mirror the existing `REPL_DID_EXPAND` state key:

```python
last_repl["skill_expansion_occurred"] = expansion.did_expand
```

This field already exists conceptually via `REPL_DID_EXPAND` in a separate state key, but having it in LAST_REPL_RESULT makes the summary self-contained for downstream consumers (sqlite_tracing, dashboard).

---

## Question 4: SKILL_REPL_GLOBALS_INJECTED state key naming

### Current state

The plan proposes:
```python
SKILL_REPL_GLOBALS_INJECTED = "skill_repl_globals_injected"  # list of function names
```

### Review against naming conventions

**Naming convention analysis:**

The existing state keys follow these patterns:
- `snake_case` for session-scoped keys (e.g., `iteration_count`, `should_stop`, `last_repl_result`)
- `app:` prefix for application-scoped keys (e.g., `app:max_depth`)
- `obs:` prefix for observability counters (e.g., `obs:rewrite_count`)
- `repl_` prefix for REPL execution metadata (e.g., `repl_submitted_code`, `repl_expanded_code`)
- `DYN_` Python constant prefix for dynamic instruction template variables (e.g., `DYN_SKILL_INSTRUCTION = "skill_instruction"`)

The proposed name `skill_repl_globals_injected` mixes two concerns: "skill" (what) and "repl_globals" (where). It doesn't follow the `repl_` prefix convention for REPL metadata.

### Recommendations

**R4.1**: Rename to follow the `repl_` prefix convention for REPL-scoped metadata:

```python
REPL_SKILL_GLOBALS_INJECTED = "repl_skill_globals_injected"  # list[str] of function names
```

This is consistent with `REPL_SUBMITTED_CODE`, `REPL_EXPANDED_CODE`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND`.

**R4.2**: This key should NOT be depth-scoped. Skill globals are injected once at REPL creation time in `_run_async_impl`, before any depth-scoped iteration begins. The same skill functions are available across all iterations. Adding it to `DEPTH_SCOPED_KEYS` would be wrong because:
- It is set once at orchestrator startup, not per-iteration
- Its value does not vary across depths (unlike `ITERATION_COUNT` or `LAST_REPL_RESULT`)
- Child orchestrators create their own REPLs with independently-injected globals

**R4.3**: Add to `CURATED_STATE_PREFIXES` (not `CURATED_STATE_KEYS`). Since the key starts with `repl_`, it is already captured by the existing prefix `"repl_"` -- wait, actually looking at the prefixes:

```python
CURATED_STATE_PREFIXES: tuple[str, ...] = (
    "obs:",
    "artifact_",
    "last_repl_result",
    "repl_submitted_code",
    "repl_expanded_code",
    "repl_skill_expansion_meta",
    "repl_did_expand",
    "reasoning_",
    "final_answer",
)
```

There is no generic `"repl_"` prefix -- each `repl_*` key is listed individually. So `repl_skill_globals_injected` would NOT be captured by the current prefixes. You must add it explicitly:

```python
CURATED_STATE_PREFIXES: tuple[str, ...] = (
    "obs:",
    "artifact_",
    "last_repl_result",
    "repl_submitted_code",
    "repl_expanded_code",
    "repl_skill_expansion_meta",
    "repl_skill_globals_injected",   # NEW
    "repl_did_expand",
    "reasoning_",
    "final_answer",
)
```

Alternatively, consider refactoring to a single `"repl_"` prefix to capture all REPL metadata. But that is a separate cleanup -- for this plan, add the explicit entry.

**R4.4**: Consider adding a companion key for when skill loading occurs at the SkillToolset level (L2 load_skill calls by the model):

```python
REPL_SKILL_L2_LOADS = "repl_skill_l2_loads"  # list[str] of skill names loaded via load_skill tool
```

However, this may be premature. The `skill_name_loaded` telemetry column (populated per-tool-call in sqlite_tracing) already captures this at the telemetry plane level. Adding a redundant state key violates the three-plane principle: telemetry belongs in the telemetry plane (sqlite), not the state plane (session state). **Recommendation: Do NOT add this companion key.** Let sqlite_tracing handle it.

---

## Question 5: SqliteTracingPlugin schema and SkillToolset telemetry

### Current schema columns

The `telemetry` table already has:
- `skill_instruction TEXT` (line 213) -- populated from `callback_context.state.get(DYN_SKILL_INSTRUCTION)` in `before_model_callback` (line 977/992). This is the instruction_router text, which is orthogonal to SkillToolset.
- `skill_name_loaded TEXT` (line 229) -- schema column exists, migration entry exists, but **no code path writes to it**. Always NULL.
- `skill_instructions_len INTEGER` (line 230) -- schema column exists, migration entry exists, but **no code path writes to it**. Always NULL.

### How these should be populated with SkillToolset

When the model calls `load_skill(name="example-analyzer")`, the `after_tool_callback` fires with:
- `tool.name = "load_skill"`
- `tool_args = {"name": "example-analyzer"}`
- `result` = the L2 instruction content returned by ADK's SkillToolset

### Recommendations

**R5.1**: Populate `skill_name_loaded` and `skill_instructions_len` in the `after_tool_callback` by adding a branch for `tool_name == "load_skill"` (per R1.1 above):

```python
elif tool_name == "load_skill":
    update_kwargs["decision_mode"] = "load_skill"
    if isinstance(tool_args, dict):
        update_kwargs["skill_name_loaded"] = tool_args.get("name")
    if isinstance(result, dict):
        instructions_text = str(result.get("instructions", result.get("output", "")))
        update_kwargs["skill_instructions_len"] = len(instructions_text)
```

Note: The exact shape of `result` from ADK's `load_skill` tool needs to be verified at implementation time. The `after_tool_callback` receives whatever the tool's `run_async` returns.

**R5.2**: No additional columns are strictly needed for Phase 1-3 of this plan. The existing columns cover the essential SkillToolset telemetry:
- `decision_mode` captures which tool was called
- `skill_name_loaded` captures which skill the model loaded
- `skill_instructions_len` captures instruction size (cost proxy)
- `skill_instruction` captures the instruction_router text (orthogonal)
- `tool_args_keys` captures the tool argument names

**R5.3**: Consider adding one new column for Phase 2+ when skill functions in REPL globals call `llm_query()`:

```
repl_skill_function_llm_calls INTEGER
```

This would count how many of the `total_llm_calls` in a REPL execution originated from skill function code vs. inline user code. However, this requires the dispatch closure to know whether it was called from a module-imported function or inline code, which is not currently possible without stack introspection. **Recommendation: Defer this column.** The existing `repl_llm_calls` counter is sufficient for now.

**R5.4**: Add `"load_skill"` and `"load_skill_resource"` to the `_categorize_key` classifier in sqlite_tracing if they ever become state keys. Currently they are tool names only, not state keys, so no change is needed.

---

## Question 6: LLMResult metadata for skill-originated dispatches

### Current state

When REPL code calls `llm_query()`, the dispatch closure in `dispatch.py` creates a child orchestrator, runs it, and returns an `LLMResult(str)` with metadata:

```python
LLMResult(text, error=..., error_category=..., input_tokens=..., output_tokens=...,
          model=..., wall_time_ms=..., finish_reason=..., parsed=...)
```

### Analysis

When a skill function calls `llm_query()` internally (the new capability enabled by the thread bridge), the dispatch path is identical. The `llm_query` sync wrapper calls `run_coroutine_threadsafe(llm_query_async(...), loop)`, which executes the same `llm_query_async` closure from `dispatch.py`. The child orchestrator sees no difference.

The question is whether downstream observability needs to distinguish "this LLM call came from a skill function" vs. "this LLM call came from inline REPL code."

### Recommendations

**R6.1**: Do NOT modify `LLMResult` to carry a `source: Literal["inline", "skill"]` field. The cost is high (requires stack introspection or caller annotation) and the benefit is low. The telemetry plane already captures the full call tree via depth/fanout_idx, and the `repl_submitted_code` state key captures the code that triggered the dispatch.

**R6.2**: If provenance tracking becomes important later, the right mechanism is a **thread-local context variable** set by the thread bridge wrapper:

```python
_dispatch_context = threading.local()

def make_sync_llm_query(llm_query_async, loop, timeout=600.0):
    def llm_query(prompt, model=None, output_schema=None):
        # The thread-local already carries caller context
        coro = llm_query_async(prompt, model=model, output_schema=output_schema)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)
    return llm_query
```

The `llm_query_async` closure could read `threading.current_thread().name` or a custom thread-local to determine whether it's running in a user-code thread vs. a skill-function thread. But this is speculative and should be deferred.

**R6.3**: The existing `REPLTrace.llm_calls` list records every LLM call with timing. At trace level 1+, the `DataFlowTracker` detects prompt-response chains. These existing mechanisms provide sufficient observability for skill-originated dispatches without any LLMResult changes.

---

## Question 7: Depth-scoping for skills

### Current state

Depth-scoping (`depth_key()` in `state.py:163`) suffixes state keys with `@dN` for depth N > 0. `DEPTH_SCOPED_KEYS` (line 142) lists which keys get scoped. Skills are currently not depth-scoped in any way.

### Analysis

The plan wires `enabled_skills` at two points:
1. `collect_skill_repl_globals(enabled_skills=...)` -- filters which Python functions are injected into REPL globals
2. `load_adk_skills(enabled_skills=...)` -- filters which ADK Skill objects go into the SkillToolset

Both are consumed once at orchestrator startup, before the reasoning agent runs. The question is what happens at depth > 0: child orchestrators created by `dispatch.py:create_child_orchestrator()`.

### Recommendations

**R7.1**: Skill availability should NOT be depth-scoped via the `depth_key()` mechanism. The reasons:

1. **REPL globals are per-LocalREPL instance.** Each child orchestrator creates its own `LocalREPL` (or reuses a provided one). The Python functions injected into `repl.globals` are already isolated per REPL instance. There is no shared mutable state to scope.

2. **SkillToolset is per-tool-list wiring.** Each orchestrator wires `tools=[repl_tool, set_model_response_tool, ...]` onto its reasoning agent independently. The SkillToolset instance lives on the tools list, not in session state.

3. **`enabled_skills` is a Pydantic field, not a state key.** It flows through the agent construction graph, not the state plane. Depth-scoping is a state-plane concept.

**R7.2**: For child skill filtering, the `enabled_skills` tuple should be passed through to child orchestrators via `create_child_orchestrator()` in `dispatch.py`. Currently this function accepts and passes `instruction_router` -- it should similarly accept `enabled_skills`:

```python
def create_child_orchestrator(
    ...,
    instruction_router=None,
    enabled_skills=(),   # NEW
) -> RLMOrchestratorAgent:
```

Then the child orchestrator's `_run_async_impl` calls `collect_skill_repl_globals(enabled_skills=self.enabled_skills)` and `load_adk_skills(enabled_skills=self.enabled_skills)` to get its own filtered skill set. If a parent has skills A, B, C but the child only needs A, the parent passes `enabled_skills=("A",)` when constructing the child.

**R7.3**: The mechanism for a parent to specify which skills a child gets is the `instruction_router` pattern (already exists). The instruction_router is a `Callable[[int, int], str]` that takes `(depth, fanout_idx)` and returns instruction text. Extending this to also influence skill selection is the natural path:

Option A: Add a `skill_router: Callable[[int, int], tuple[str, ...]] | None` parameter parallel to `instruction_router`.

Option B: Have the instruction_router return a richer object that includes both instruction text and skill filter. But this changes the signature contract.

**Recommendation**: For Phase 1 of this plan, just pass the parent's `enabled_skills` to children unchanged. Per-child skill filtering is a future enhancement. Do NOT add depth-scoping infrastructure for this.

**R7.4**: Do NOT add `enabled_skills` or skill names to `DEPTH_SCOPED_KEYS`. Skill availability is a construction-time parameter, not a per-iteration mutable state value. Putting it in the state plane would be architecturally wrong.

---

## Summary of All Recommendations

### types.py changes
- **R1.2**: Expand `LineageEnvelope.decision_mode` Literal to add `"list_skills"` and `"run_skill_script"`
- **R2.1**: Do NOT add `execution_mode` to `REPLResult`
- **R2.4**: Type-narrow `REPLTrace.execution_mode` to `Literal["sync", "async", "thread_bridge"]`

### state.py changes
- **R4.1**: Rename to `REPL_SKILL_GLOBALS_INJECTED = "repl_skill_globals_injected"`
- **R4.2**: Do NOT add to `DEPTH_SCOPED_KEYS`
- **R4.3**: Add `"repl_skill_globals_injected"` to `CURATED_STATE_PREFIXES`
- **R4.4**: Do NOT add a companion `REPL_SKILL_L2_LOADS` key -- let sqlite_tracing handle it
- **R7.4**: Do NOT add `enabled_skills` to `DEPTH_SCOPED_KEYS`

### sqlite_tracing.py changes
- **R1.1**: Add explicit `elif` branches in `after_tool_callback` for `load_skill` and `load_skill_resource` to populate `skill_name_loaded` and `skill_instructions_len`
- **R5.1**: Same as R1.1 -- these are the code paths that populate the existing-but-NULL columns
- **R5.2**: No additional schema columns needed for initial phases
- **R5.3**: Defer `repl_skill_function_llm_calls` column

### repl_tool.py changes
- **R3.1**: Add `execution_mode` to LAST_REPL_RESULT, sourced from trace
- **R3.2**: Consider `skill_globals_count` in LAST_REPL_RESULT (lightweight)
- **R3.3**: Add `skill_expansion_occurred` to LAST_REPL_RESULT

### LLMResult / dispatch.py changes
- **R6.1**: Do NOT modify LLMResult for skill provenance
- **R6.2**: Defer thread-local dispatch context
- **R6.3**: Existing REPLTrace mechanisms are sufficient

### dispatch.py / orchestrator.py changes
- **R7.2**: Pass `enabled_skills` through to `create_child_orchestrator()`
- **R7.3**: Defer per-child skill filtering (pass parent's enabled_skills unchanged for now)

### Plan corrections
- Phase 4C claim "No changes needed" is **incorrect** -- sqlite_tracing needs explicit `elif` branches to populate `skill_name_loaded` and `skill_instructions_len` (R1.1/R5.1)
- Phase 4A key name `SKILL_REPL_GLOBALS_INJECTED` should be renamed to `REPL_SKILL_GLOBALS_INJECTED` (R4.1)
- Phase 4B `execution_mode` should be sourced from `REPLTrace`, not set independently in the return dict (R3.1/R2.4)
