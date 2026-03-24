# Thread Bridge Data Model Review

**Reviewer**: Data Model Expert (lineage, completion, state-event plane integrity)
**Date**: 2026-03-24
**Scope**: Plans A, B, C evaluated against the existing three-plane architecture in `state.py`, `sqlite_tracing.py`, `dispatch_and_state.md`, and `observability.md`.

---

## Executive Summary

**Plan B best preserves data plane cleanliness.** It is the only plan that (a) explicitly scopes new state keys with the correct depth/prefix conventions, (b) identifies and fixes the `reasoning_before_model` system instruction overwrite that would silently destroy SkillToolset L1 injection, (c) separates SkillToolset gating from REPL globals injection in child orchestrators, (d) explicitly addresses the `_agent_span_stack` interleaving bug under batched children, and (e) introduces the narrowest possible state key surface (one new key: `REPL_SKILL_GLOBALS_INJECTED`).

Plan A is structurally sound but adds four new state keys where one suffices, and leaves several observability gaps unspecified. Plan C embeds sync closures inside `dispatch.py` (widening the dispatch module's responsibility) and is the least specific about state key naming, depth scoping, and sqlite schema impact.

All three plans share the same correct thread-bridge architecture for Phase 1. The differentiation is in how cleanly they handle the data model consequences.

---

## Per-Plan Data Model Analysis

### Plan A

**Thread bridge (Phase 1)**: Correct. `make_sync_llm_query` / `make_sync_llm_query_batched` in a standalone `rlm_adk/repl/thread_bridge.py`. Event loop captured in `_run_async_impl`. `run_coroutine_threadsafe` dispatches to event loop, worker thread blocks on `future.result()`. No state mutations in the bridge module itself.

**Skill infrastructure (Phase 2)**: Introduces `collect_skill_repl_globals()` that imports Python modules and injects functions into `repl.globals`. Functions reference `llm_query` as a free variable resolved from the REPL namespace at call time. This is the simplest approach but has a subtle failure mode: if a skill function is called outside the REPL namespace (e.g., in a unit test), `llm_query` is undefined and produces a `NameError` with no helpful message. Plan B's `llm_query_fn` parameter pattern with auto-injection avoids this.

**SkillToolset (Phase 3)**: Wires `SkillToolset` onto the reasoning agent tools list. Does not address the `reasoning_before_model` system instruction overwrite that would clobber the L1 XML. This is a critical omission -- the SkillToolset's `process_llm_request()` appends to `system_instruction`, but `reasoning_before_model` replaces it entirely. Skills would never appear in the model's prompt.

**State keys (Phase 4)**: Introduces four new keys:
- `SKILL_LAST_LOADED` -- session-scoped
- `SKILL_LOAD_COUNT` -- session-scoped
- `SKILL_LOADED_NAMES` -- session-scoped
- `SKILL_REPL_GLOBALS_INJECTED` -- session-scoped

Of these, `SKILL_LAST_LOADED` and `SKILL_LOAD_COUNT` duplicate what ADK's `LoadSkillTool` already tracks via `_adk_activated_skill_{agent_name}`. `SKILL_LOADED_NAMES` is redundant with reading the ADK activation keys. Only `SKILL_REPL_GLOBALS_INJECTED` provides genuinely new information (which Python functions were injected into the REPL).

**sqlite_tracing**: Plan A states "No changes needed -- the REPLTool still writes the same state keys." This is incomplete. The new `execution_mode` field in `LAST_REPL_RESULT` would flow through the existing `repl_trace_summary` JSON column, but the `SkillToolset` tools (`load_skill`, `list_skills`, etc.) need explicit `decision_mode` handling in `after_tool_callback`. Plan A does not specify this.

**Child propagation**: Not addressed. Does `enabled_skills` pass to child orchestrators? Do children get SkillToolset or just REPL globals?

### Plan B

**Thread bridge (Phase 1)**: Same correct architecture as Plan A, with three improvements:
1. `_execute_code_threadsafe()` method avoids `_EXEC_LOCK` entirely, preventing deadlock under recursive dispatch where parent holds the lock and child needs its own thread. Uses `_make_cwd_open()` instead of `os.chdir()`.
2. One-shot `ThreadPoolExecutor` per call prevents default-pool exhaustion under deep recursion.
3. ContextVar-based stdout/stderr capture is explicitly addressed for thread safety.

**Skill infrastructure (Phase 2)**: The `llm_query_fn` parameter pattern is architecturally superior. Functions declare their dependency explicitly via `llm_query_fn: Callable | None = None`. The loader auto-injects it from REPL globals at call time via `_wrap_with_llm_query_injection()`. This means:
- Functions are testable in isolation (pass a mock `llm_query_fn`)
- No module-level global mutation
- No `NameError` when called outside the REPL
- The wrapper reads `llm_query` lazily from `repl_globals` at call time, not at wrap time, so wiring order is irrelevant

**SkillToolset (Phase 3 + 3.5)**: Identifies and fixes the `reasoning_before_model` overwrite. This is the critical finding that Plans A and C miss entirely. Without this fix, `SkillToolset.process_llm_request()` appends L1 XML to `system_instruction`, then `reasoning_before_model` overwrites it. Plan B proposes checking whether toolset content was appended and preserving it.

**State keys (Phase 4)**: One new key:
- `REPL_SKILL_GLOBALS_INJECTED` -- session-scoped, follows the `repl_` prefix convention

Explicitly does NOT add to `DEPTH_SCOPED_KEYS` (correct -- skill globals are injected once at REPL creation, not per-iteration). Adds to `CURATED_STATE_PREFIXES` for sqlite capture.

**sqlite_tracing**: Specifies explicit `elif` branches in `after_tool_callback` for `load_skill`, `load_skill_resource`, `list_skills`, `run_skill_script`. Populates the existing `skill_name_loaded` and `skill_instructions_len` telemetry columns. Identifies the `_agent_span_stack` interleaving bug under batched children and files it as a follow-up.

**Child propagation**: Explicitly specifies split gating:
- SkillToolset (L1/L2 discovery tools): gated by `enabled_skills`, NOT given to children
- REPL globals (Python functions): injected unconditionally into all orchestrators
This is the correct separation -- children are narrow-scope workers that should not discover skills, but their REPL code must be able to call skill functions.

**LineageEnvelope expansion**: Adds `list_skills`, `run_skill_script` to the `decision_mode` Literal type. This ensures telemetry rows correctly attribute which tool was invoked.

**REPLTrace type narrowing**: `execution_mode: Literal["sync", "async", "thread_bridge"]`. Sources from trace object, not independently computed.

### Plan C

**Thread bridge (Phase 1)**: Embeds the sync closure wrappers directly inside `create_dispatch_closures()` in `dispatch.py`, widening the return type from a 3-tuple to a 5-tuple (or named tuple). This is architecturally viable but widens `dispatch.py`'s responsibility from "async child dispatch" to "async + sync + thread bridge wiring." Plan A and B keep the bridge in a standalone module, which is cleaner.

**Return type change**: The 3-tuple to 5-tuple change (or dataclass) is a significant API surface change. Every call site of `create_dispatch_closures()` must be updated. The orchestrator, tests, and child dispatch code all destructure this return value. Plan B avoids this by keeping dispatch unchanged and creating bridge closures in a separate module.

**Skill infrastructure (Phase 2)**: Proposes `SKILL_EXPORTS` list in `__init__.py` per skill. Uses the `llm_query_fn` parameter pattern (same as Plan B) but also explores several alternative approaches (free variable resolution, module-level injection, `builtins.__import__`), ultimately settling on the wrapper approach. The exploration of multiple alternatives suggests less certainty in the design.

**SkillToolset (Phase 2.3)**: Wires `SkillToolset` via a new `rlm_adk/skills/toolset.py` module. Does not identify the `reasoning_before_model` overwrite problem.

**State keys**: Mentions "Add any new state key constants for skill tracking" in the file change table but does not specify which keys. Defers to "Phase 2.7" which references ADK's `_adk_activated_skill_{agent_name}` keys and existing `skill_name_loaded` / `skill_instructions_len` columns, but introduces no new RLM state keys. This means no observability for which skill functions were injected into the REPL.

**sqlite_tracing**: No specific schema changes proposed. References that existing columns exist but does not specify how to populate them.

**instruction_router**: Proposes building an `instruction_router` from skills (`build_instruction_router_from_skills`). This creates a new cross-cutting dependency between the skill system and the instruction routing mechanism, which is the kind of entanglement that previously caused the "spaghetti soup" problem. Plan B explicitly keeps `instruction_router` orthogonal.

---

## State Key Inventory

### Plan A -- 4 new keys

| Key | Scope | Depth-Scoped | CURATED | Purpose |
|-----|-------|:---:|:---:|---------|
| `skill_last_loaded` | session | No | Not specified | Last skill loaded via `load_skill` |
| `skill_load_count` | session | No | Not specified | Count of `load_skill` calls |
| `skill_loaded_names` | session | No | Not specified | List of loaded skill names |
| `skill_repl_globals_injected` | session | No | Not specified | List of injected function names |

**Issues**: `skill_last_loaded`, `skill_load_count`, and `skill_loaded_names` overlap with ADK's built-in `_adk_activated_skill_{agent_name}` tracking. No specification of whether these belong in `CURATED_STATE_KEYS`, `CURATED_STATE_PREFIXES`, or `DEPTH_SCOPED_KEYS`. The `skill_` prefix does not match any existing prefix convention (existing prefixes: `obs:`, `repl_`, `artifact_`, `cache:`, `app:`, `user:`, `step:`, `migration:`, `cb_`).

### Plan B -- 1 new key

| Key | Scope | Depth-Scoped | CURATED | Purpose |
|-----|-------|:---:|:---:|---------|
| `repl_skill_globals_injected` | session | No | Yes (prefix) | List of injected function names |

**Issues**: None. Uses the established `repl_` prefix. Explicitly excluded from `DEPTH_SCOPED_KEYS` with documented rationale. Added to `CURATED_STATE_PREFIXES` for sqlite capture.

### Plan C -- 0 new keys (explicitly), undefined state tracking

| Key | Scope | Depth-Scoped | CURATED | Purpose |
|-----|-------|:---:|:---:|---------|
| *(none specified)* | -- | -- | -- | -- |

**Issues**: No state key tracking for skill injection. Relies entirely on ADK's `_adk_activated_skill_{agent_name}` for skill discovery tracking. No observability for which Python functions were injected into the REPL.

---

## AR-CRIT-001 Compliance Check

### Plan A -- COMPLIANT

- Thread bridge closures in `rlm_adk/repl/thread_bridge.py` perform no state writes. They submit async coroutines via `run_coroutine_threadsafe` and block on results.
- `llm_query_async` and `llm_query_batched_async` run on the event loop thread. State writes in `_run_child()` flow through child orchestrator events, not direct `ctx.session.state` writes.
- `post_dispatch_state_patch_fn()` returns a dict that REPLTool writes to `tool_context.state`. This path is unchanged.
- Skill state keys (`SKILL_LAST_LOADED` etc.) are described as "written by the orchestrator when skill globals are injected, and by ADK's `LoadSkillTool` when the model loads a skill (via `tool_context.state`)." The "written by the orchestrator" part is vague -- it must use `EventActions(state_delta={})`, not `ctx.session.state`. Plan does not specify the mutation channel.

**Verdict**: Likely compliant but the orchestrator skill key write path is underspecified.

### Plan B -- COMPLIANT

- Same thread bridge architecture as Plan A, no state writes in bridge closures.
- `REPL_SKILL_GLOBALS_INJECTED` is written via `initial_state` dict in `_run_async_impl()`, which feeds into the session's initial state setup -- this is an ADK-tracked channel (state is set before the run begins, not mutated during dispatch closures).
- `execution_mode` is written into `LAST_REPL_RESULT` via `tool_context.state` in `REPLTool.run_async()` -- correct channel.
- `decision_mode` for skill tools is written in `after_tool_callback` via sqlite direct writes to the telemetry table (plugin-internal, not session state) -- no AR-CRIT-001 concern.

**Verdict**: Fully compliant. All mutation paths are specified and correct.

### Plan C -- COMPLIANT (with caveat)

- Sync closures embedded in `dispatch.py` perform no state writes.
- `event_loop` parameter added to `create_dispatch_closures()` -- closure captures the loop, uses `run_coroutine_threadsafe`. No state side effects.
- Plan references ADK's `_adk_activated_skill_{agent_name}` for skill tracking, which is written by `LoadSkillTool` via `tool_context.state` -- correct channel.
- No new state keys introduced, so no new mutation paths to evaluate.

**Verdict**: Compliant by virtue of introducing no new state mutations. But the lack of skill injection tracking means less observability.

---

## SQLite Schema Impact Assessment

### Plan A

**New columns**: None proposed. Plan states "No changes needed."

**Gaps**:
- `execution_mode` in `LAST_REPL_RESULT` flows through `repl_trace_summary` JSON column in telemetry, but there is no first-class column for it. This means querying "how many REPL calls used thread_bridge vs async_rewrite" requires JSON parsing.
- No `decision_mode` handling for SkillToolset tools. `load_skill`, `list_skills` etc. would all have `decision_mode = NULL` in telemetry rows.
- Existing `skill_name_loaded` and `skill_instructions_len` columns in telemetry remain permanently NULL.

**Migration**: None needed (no schema changes), but the "no changes needed" claim leaves permanent data gaps.

### Plan B

**New columns**: None. All new data fits into existing columns:
- `skill_name_loaded` (existing, currently NULL) -- populated by `after_tool_callback` when tool is `load_skill`
- `skill_instructions_len` (existing, currently NULL) -- populated alongside `skill_name_loaded`
- `decision_mode` (existing) -- expanded with `load_skill`, `load_skill_resource`, `list_skills`, `run_skill_script` values
- `execution_mode` in `LAST_REPL_RESULT` flows through `repl_trace_summary` (existing JSON column)

**Gaps**: None identified. The plan explicitly populates the previously-NULL columns and documents the follow-up for `_agent_span_stack` scoping.

**Migration**: No DDL migration needed. The schema already has the columns; they just gain non-NULL values.

### Plan C

**New columns**: None proposed. References existing columns but does not specify how they get populated.

**Gaps**:
- Same as Plan A: `skill_name_loaded`, `skill_instructions_len`, `decision_mode` for skill tools all remain unspecified.
- No `execution_mode` tracking specified.

**Migration**: None.

---

## Event Flow Integrity

### Child Event Re-Emission

All three plans preserve the existing `child_event_queue` mechanism. The thread bridge does not affect event flow because:
1. REPL code runs in a worker thread
2. `llm_query()` submits coroutines via `run_coroutine_threadsafe` to the event loop
3. `_run_child()` runs entirely on the event loop, pushing curated state keys onto the queue via `put_nowait()`
4. The orchestrator drains the queue in its yield loop
5. Re-emitted events carry `rlm_child_event=True` metadata

The critical question is whether the drain loop timing changes. In the current async-rewrite model, `execute_code_async()` runs on the event loop, so child events accumulate during tool execution and drain after the tool-response event. In the thread-bridge model, `execute_code_threaded()` yields the event loop via `run_in_executor()`, so child events can be produced concurrently with REPL execution. The drain loop fires after the tool-response event, same as before. No timing change.

**Plan B explicitly addresses this** in its thread safety analysis (section 1.7, point 3). Plans A and C do not explicitly address the event flow timing under the new execution model, though the architecture is equivalent.

### Depth Tracking

All three plans maintain `depth_key()` scoping. Child orchestrators are created at `depth + 1` in `_run_child()`, which is unchanged. The `DEPTH_SCOPED_KEYS` set is not modified by any plan. `DYN_SKILL_INSTRUCTION` continues to flow through `instruction_router` -> `post_dispatch_state_patch_fn` -> `tool_context.state`.

---

## Lineage Plane Preservation

The lineage plane (depth-scoped state keys, `telemetry` table with `depth`, `fanout_idx`, `parent_depth`, `parent_fanout_idx` columns) is unaffected by the thread bridge. All three plans:
- Do not modify `depth_key()` or `DEPTH_SCOPED_KEYS`
- Do not change `_run_child()` lineage tracking
- Do not alter `post_dispatch_state_patch_fn()` behavior
- Preserve `DYN_SKILL_INSTRUCTION` flow through `instruction_router`

**Plan B adds**: `enabled_skills` propagation to child orchestrators with split gating. This is additive and does not touch lineage columns. REPL globals injection for children is unconditional (no lineage impact). SkillToolset is gated by `enabled_skills` (root-only concern, no lineage impact).

**Plan C risk**: Proposes `build_instruction_router_from_skills()` which would generate instruction routing from skill metadata. If the router function reads skill state or modifies `DYN_SKILL_INSTRUCTION` in ways that depend on skill activation history, this creates a new cross-cutting dependency between the skill system and the lineage plane. The plan does not fully specify this function's behavior.

---

## Completion Plane Preservation

The completion plane consists of:
- `LAST_REPL_RESULT` (depth-scoped, written by REPLTool to `tool_context.state`)
- `FINAL_RESPONSE_TEXT` (depth-scoped, set by `set_model_response`)
- `OBS_WORKER_ERROR_COUNTS` -- removed in three-plane cleanup, now plugin-local
- `CompletionEnvelope` / `_rlm_terminal_completion` on orchestrator instances

### Plan A
- `LAST_REPL_RESULT` write path unchanged. Adds `execution_mode` field to the dict.
- `FINAL_RESPONSE_TEXT` unchanged.
- No completion plane modification.

### Plan B
- `LAST_REPL_RESULT` write path unchanged. Adds `execution_mode` sourced from `REPLTrace`. Adds `skill_globals_count` and `skill_expansion_occurred` metadata.
- `FINAL_RESPONSE_TEXT` unchanged.
- `CompletionEnvelope` gains expanded `decision_mode` Literal values.
- No completion plane modification.

### Plan C
- `LAST_REPL_RESULT` write path unchanged.
- No additional metadata specified.
- No completion plane modification.

All three plans preserve completion plane integrity.

---

## Data Plane Separation (Spaghetti Risk)

### Plan A -- Spaghetti Risk: 2/5

Low risk overall. The thread bridge is clean. The four new state keys (`skill_last_loaded`, `skill_load_count`, `skill_loaded_names`, `skill_repl_globals_injected`) are all session-scoped and do not cross into lineage or completion planes. However:
- The `skill_` prefix creates a new namespace that is not aligned with existing prefixes
- `skill_loaded_names` duplicates ADK's `_adk_activated_skill_{agent_name}` tracking
- No specification of how these keys interact with `CURATED_STATE_KEYS` / `CURATED_STATE_PREFIXES` means they could silently fail to appear in `session_state_events`

The skill function approach (free variable resolution from REPL globals) is simple but creates an implicit coupling: skill functions only work when the REPL namespace has `llm_query` wired. This is not entanglement per se, but it is an invisible dependency.

### Plan B -- Spaghetti Risk: 1/5

Minimal risk. One new state key with correct prefix convention. Explicit separation of:
- SkillToolset (tool-level, discovery) vs REPL globals (namespace-level, execution)
- `instruction_router` (per-depth/fanout instruction injection) vs SkillToolset (model-driven discovery)
- Root orchestrator concerns (SkillToolset gated) vs child concerns (REPL globals unconditional)

The `llm_query_fn` parameter pattern makes the dependency explicit rather than implicit. The auto-injection wrapper is a single function in `loader.py` that reads from `repl_globals` at call time -- no module-level mutation, no shared state between REPL instances.

The `reasoning_before_model` fix (Phase 3.5) prevents the SkillToolset from becoming silently broken, which would have led to debugging sessions that cross multiple planes.

### Plan C -- Spaghetti Risk: 3/5

Moderate risk. Two specific concerns:

1. **`build_instruction_router_from_skills()`**: This function creates a new coupling between the skill system and the instruction routing mechanism. The instruction router is a function `(depth, fanout_idx) -> str` that feeds `DYN_SKILL_INSTRUCTION` in the state plane. If the router starts reading skill metadata, skill activation state, or model-time `load_skill` decisions, it creates a cross-cutting dependency between:
   - The skill discovery plane (SkillToolset, L1/L2)
   - The state plane (`DYN_SKILL_INSTRUCTION` via `instruction_router`)
   - The lineage plane (`post_dispatch_state_patch_fn` restores parent skill instruction)

   This is exactly the kind of entanglement that forced the previous skill system gutting. Plan B explicitly keeps `instruction_router` orthogonal to SkillToolset.

2. **Sync closures in `dispatch.py`**: Embedding the sync bridge inside `create_dispatch_closures()` widens the dispatch module's API surface and responsibility. The 3-tuple to 5-tuple return change means every consumer of dispatch closures must be updated. If a future change to the bridge (timeout handling, error wrapping, metrics) requires modifying dispatch.py, it risks destabilizing the async dispatch path that lineage tracking depends on.

---

## Skill Activation Tracking

ADK's `LoadSkillTool` writes `_adk_activated_skill_{agent_name}` to `tool_context.state` when the model calls `load_skill`. This is a tracked channel (AR-CRIT-001 compliant).

### Plan A
Does not mention `_adk_activated_skill_*` keys. Introduces its own `skill_loaded_names` and `skill_load_count` keys, creating parallel tracking. The `_adk_activated_skill_*` keys use a dynamic suffix pattern (`{agent_name}`) that does not match any existing `CURATED_STATE_KEYS` or `CURATED_STATE_PREFIXES`. This means ADK's activation keys would NOT be captured by `session_state_events`. Plan A's custom keys would need to be added to the curated set to be captured.

### Plan B
Does not introduce parallel tracking. Relies on ADK's `_adk_activated_skill_*` for model-time discovery tracking. Adds `repl_skill_globals_injected` for construction-time REPL injection tracking. The `_adk_activated_skill_*` keys would NOT be captured by `session_state_events` (not in curated sets), but the telemetry table's `skill_name_loaded` column captures this information directly in `after_tool_callback`.

### Plan C
References `_adk_activated_skill_*` explicitly and notes the existing sqlite columns. Does not introduce new state keys. Same gap as Plan B regarding `session_state_events` capture, mitigated by telemetry table direct writes.

**Recommendation for all plans**: If `_adk_activated_skill_*` keys should appear in `session_state_events`, add `"_adk_activated_skill_"` to `CURATED_STATE_PREFIXES`. However, since these are ADK-internal keys with an underscore prefix, it may be better to rely on the telemetry table's `skill_name_loaded` column (as Plan B does).

---

## Recommendations

### 1. Adopt Plan B as the implementation reference

Plan B has the cleanest data model impact, the most complete observability specification, and the only identification of the critical `reasoning_before_model` overwrite bug. Its one-key state footprint, explicit `llm_query_fn` parameter pattern, and split gating for child orchestrators demonstrate the most careful separation of concerns.

### 2. From Plan A, adopt nothing additional

Plan A's four state keys add noise without new signal. Its skill function free-variable approach is simpler but less robust than Plan B's parameter injection.

### 3. From Plan C, avoid the `build_instruction_router_from_skills()` pattern

This creates exactly the cross-cutting dependency that previously caused the skill system to be gutted. Keep `instruction_router` orthogonal to the skill system.

### 4. From Plan C, avoid embedding sync closures in `dispatch.py`

Keep the thread bridge as a standalone module (`rlm_adk/repl/thread_bridge.py`). The dispatch module should remain focused on async child orchestrator lifecycle.

### 5. Address `_adk_activated_skill_*` capture decision

Decide explicitly: should ADK's skill activation keys appear in `session_state_events`? If yes, add the prefix to `CURATED_STATE_PREFIXES`. If no (recommended), document that skill activation tracking flows exclusively through the telemetry table's `skill_name_loaded` column.

### 6. Plan B Phase 3.5 is not optional

The `reasoning_before_model` system instruction overwrite must be fixed before SkillToolset is wired. This is a silent data loss bug -- the L1 XML would be injected by `process_llm_request()` and then destroyed by the callback. Any plan that wires SkillToolset without this fix will produce an invisible failure where skills appear registered but the model never sees them.

### 7. Add `execution_mode` as a first-class telemetry column (future)

All three plans put `execution_mode` inside the `LAST_REPL_RESULT` JSON dict, which flows through `repl_trace_summary`. For queryability, consider adding `execution_mode TEXT` as a top-level column on the `telemetry` table in a future migration. This is not a blocker but would simplify dashboard queries like "what percentage of REPL calls used thread_bridge."

---

## Summary Table

| Criterion | Plan A | Plan B | Plan C |
|-----------|:------:|:------:|:------:|
| New state keys | 4 | 1 | 0 |
| AR-CRIT-001 compliant | Yes (underspecified) | Yes (fully specified) | Yes (by absence) |
| sqlite schema impact | Unspecified | Fully specified | Unspecified |
| `reasoning_before_model` fix | Missing | Present | Missing |
| Child propagation specified | No | Yes (split gating) | Partial |
| `_agent_span_stack` bug identified | No | Yes | No |
| `instruction_router` orthogonality | Preserved | Preserved | Compromised |
| Spaghetti risk (1-5) | 2 | 1 | 3 |
| Thread bridge module placement | Standalone (clean) | Standalone (clean) | Inside dispatch.py |
| Skill function testability | Fragile (free var) | Robust (param injection) | Robust (param injection) |
| `execution_mode` tracking | Partial | Complete | Absent |
| `decision_mode` expansion | Absent | Complete | Absent |
| **Overall data model grade** | **B** | **A** | **C+** |
