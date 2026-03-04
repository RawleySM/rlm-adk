# Callback & State Mutation Review: Recursive Worker Orchestrator Plan

## Summary

The plan proposes replacing leaf `LlmAgent` workers with recursive `RLMOrchestratorAgent` children sharing the parent's `InvocationContext`. This review examines ADK callback correctness, state mutation safety, and shared-context risks. **Several critical issues were found** that require plan amendments before implementation.

---

## Issue 1 (CRITICAL): Shared InvocationContext — `run_async` Creates a New Context

**Plan assumption** (Phase 3): Child orchestrators call `child._run_async_impl(ctx)` directly with the parent's `InvocationContext`.

**Problem**: ADK's `BaseAgent.run_async()` is a `@final` method that:
1. Creates a **new** `InvocationContext` via `_create_invocation_context(parent_context)` (BaseAgent line ~287)
2. Executes before/after agent callbacks
3. Calls `_run_async_impl(new_ctx)` internally

By calling `_run_async_impl(ctx)` directly, the plan **bypasses** context creation and agent lifecycle callbacks. This means:
- `before_agent_callback` / `after_agent_callback` never fire on the child
- The child's events use the parent's `invocation_id` — event attribution becomes ambiguous
- ADK's internal bookkeeping (agent call tracking, end_invocation flags) is skipped

**However**, calling `run_async(ctx)` instead creates a child context that still shares the same `Session` object. State writes through `EventActions.state_delta` flow to the same session. This is actually what we want for `depth_key()` scoping to work.

**Recommendation**: Use `child.run_async(ctx)` instead of `child._run_async_impl(ctx)`. This gives proper context isolation while maintaining shared session state. The child gets its own `invocation_id` (important for event attribution) and agent callbacks fire correctly.

**Risk if ignored**: Events from child and parent are indistinguishable in the session history. Agent lifecycle callbacks are silently skipped. Future ADK upgrades may break assumptions about context structure.

---

## Issue 2 (CRITICAL): Concurrent Children on Shared Session — No Synchronization

**Plan assumption** (Phase 3): `llm_query_batched_async` uses `asyncio.gather(*[_run_child(p) for p in prompts])` with a semaphore.

**Problem**: ADK's `ParallelAgent` explicitly copies the `InvocationContext` via `model_copy()` and creates separate branches for each sub-agent (`_create_branch_ctx_for_sub_agent`, lines 35-48). The ADK documentation explicitly warns:

> "If you need communication or data sharing between these agents, you must implement it explicitly... you'd need to manage concurrent access to this shared context carefully (e.g., using locks) to avoid race conditions."

When multiple child orchestrators run concurrently via `asyncio.gather`, they each yield `Event` objects with `state_delta` dicts that are appended to the same `Session`. The `SessionService.append_event()` applies deltas sequentially, but the **interleaving order is nondeterministic** under `asyncio.gather`.

**Specific collision scenario**: Two children at depth=1 both write `depth_key(FINAL_ANSWER, 1)` = `"final_answer@d1"`. Since `depth_key` scopes by depth level (not per-child instance), concurrent children at the same depth **collide on the same state key**.

**Recommendation**:
1. State keys must be scoped by **child instance**, not just depth. Consider `depth_key(FINAL_ANSWER, depth, child_id)` → `"final_answer@d1_c0"`.
2. Alternatively, do NOT read child results from session state. Instead, have the child orchestrator return its result through a different channel (e.g., an in-memory carrier attribute on the child object, similar to the current `worker._result` pattern).
3. If using session state, serialize child execution (semaphore=1) or use branch contexts.

**Risk if ignored**: Concurrent children overwrite each other's `FINAL_ANSWER`, `SHOULD_STOP`, `ITERATION_COUNT` etc. at the same depth scope. Results are nondeterministic and incorrect.

---

## Issue 3 (HIGH): `output_key` Collision Between Concurrent Children

**Plan assumption** (Phase 2): Child at depth 1 uses `output_key="reasoning_output@d1"`.

**Problem**: `output_key` is set on the `reasoning_agent` (an `LlmAgent`). ADK's `__maybe_save_output_to_state` writes `event.actions.state_delta[self.output_key]` when the event author matches the agent's name. If two child orchestrators at depth=1 both have reasoning agents with `output_key="reasoning_output@d1"`, they write to the same session state key.

Since `output_key` writes go through `EventActions.state_delta` (confirmed by ADK source), the last child to emit its final response wins. Earlier children's output is overwritten.

**Recommendation**: Include a unique child identifier in the output_key: `output_key=f"reasoning_output@d{depth}_c{child_index}"`. The dispatch closure can then read the correct key per child.

---

## Issue 4 (MEDIUM): Reasoning Callbacks Share State Keys Without Depth Scoping

**Current code** (`rlm_adk/callbacks/reasoning.py:90-132`): `reasoning_before_model` writes to:
- `REASONING_CALL_START`
- `REASONING_PROMPT_CHARS`
- `REASONING_SYSTEM_CHARS`
- `REASONING_CONTENT_COUNT`
- `REASONING_HISTORY_MSG_COUNT`
- `CONTEXT_WINDOW_SNAPSHOT`
- `REASONING_INPUT_TOKENS` (after_model)
- `REASONING_OUTPUT_TOKENS` (after_model)

These keys are NOT in `DEPTH_SCOPED_KEYS` and are not threaded through `depth_key()`. When parent and child reasoning agents share the same session, the child's callbacks overwrite the parent's token accounting.

**Plan comment** (Risks table): "Acceptable for v1: OBS_PER_ITERATION_TOKEN_BREAKDOWN list captures all; individual keys are per-call snapshots."

**Assessment**: This is acceptable for v1 IF the plan explicitly documents that `REASONING_INPUT_TOKENS` etc. reflect the **last** model call across all depths, not per-depth values. The `OBS_PER_ITERATION_TOKEN_BREAKDOWN` list accumulation pattern handles aggregation correctly.

**Recommendation**: Add a note to Phase 4 to optionally add depth to `CONTEXT_WINDOW_SNAPSHOT` dict (the plan already mentions this at line 241). No blocking issue for v1.

---

## Issue 5 (MEDIUM): Orchestrator State Reads Bypass Event Tracking

**Current code** (`orchestrator.py:107`):
```python
max_iterations = ctx.session.state.get(APP_MAX_ITERATIONS, _default_max_iter)
```

And at line 255:
```python
raw = ctx.session.state.get("reasoning_output", "")
```

**Assessment**: These are **reads**, not writes. The ADK documentation states: "Use direct access to `session.state` (from a `SessionService`-retrieved session) only for *reading* state." Reading from `ctx.session.state` is acceptable since `InvocationContext.session` provides access to the current session state including all applied deltas.

**No issue** with the current code or the plan's proposed changes to these read patterns.

---

## Issue 6 (LOW): Orchestrator State Writes Are Correct

**Current code** (`orchestrator.py:187-191, 230-237, 286-293, 313-320`): All state writes use `yield Event(actions=EventActions(state_delta={...}))` — the correct pattern for `BaseAgent._run_async_impl`.

**Plan proposal** (Phase 1): Wrap these writes with `depth_key()`:
```python
yield Event(
    actions=EventActions(state_delta={
        depth_key(FINAL_ANSWER, self.depth): final_answer,
        depth_key(SHOULD_STOP, self.depth): True,
    }),
)
```

**Assessment**: Correct. `EventActions.state_delta` is the right mechanism for `_run_async_impl`. The depth_key wrapping is syntactically and semantically correct. At depth=0, `depth_key(k, 0) == k` — transparent refactor.

---

## Issue 7 (LOW): REPLTool State Writes Are Correct

**Current code** (`repl_tool.py:83, 127, 130, 151, 154, 173, 185`): All state writes use `tool_context.state[key] = value` — the correct pattern for tools.

**Plan proposal** (Phase 1): Wrap with `depth_key()`:
```python
tool_context.state[depth_key(ITERATION_COUNT, self.depth)] = self._call_count
```

**Assessment**: Correct. `ToolContext.state` modifications are automatically tracked in `EventActions.state_delta`.

---

## Issue 8 (MEDIUM): Phase 0 — SetModelResponseTool on Parent Needs Careful Callback Wiring

**Plan proposal**: Wire `make_worker_tool_callbacks(max_retries=2)` onto the reasoning agent's `after_tool_callback` and `on_tool_error_callback`.

**Current behavior**: The reasoning agent currently has NO `after_tool_callback` or `on_tool_error_callback`. The plan proposes wiring these at runtime via `object.__setattr__`.

**Concern**: `make_worker_tool_callbacks` (from `worker_retry.py`) is designed for leaf workers and writes `_structured_result` onto the agent object. When used on the parent's reasoning agent, the `after_tool_cb` must distinguish between `execute_code` (REPLTool) and `set_model_response` (SetModelResponseTool) calls. The current `WorkerRetryPlugin` logic checks tool name internally, so this should be safe.

**Recommendation**: Verify that `make_worker_tool_callbacks` only acts on `set_model_response` tool calls and passes through `execute_code` tool calls without interference. The `after_tool_callback` fires for ALL tools on the agent — both `execute_code` and `set_model_response`.

---

## Issue 9 (INFO): `temp:` Prefix Correctly Avoided

The plan does not introduce any `temp:` prefixed keys. Per MEMORY.md: "ADK Runner strips `temp:` keys from yielded events." The existing codebase correctly avoids `temp:` prefixes (Fix 8). No issue.

---

## Issue 10 (MEDIUM): Phase 3 Delete of Worker Callbacks — Verify No External Consumers

**Plan proposal**: Delete `worker_before_model`, `worker_after_model`, `worker_on_model_error` from `rlm_adk/callbacks/worker.py`.

**Current consumers**:
- `dispatch.py:125-127` — wired onto workers during `_create_worker`
- `worker_test_state_hook` (`worker.py:210`) — test-only, chains with `worker_before_model`
- Provider-fake fixtures likely reference these callbacks

**Recommendation**: Search for all imports of these functions across tests and fixtures before deletion. The test-only `worker_test_state_hook` depends on `worker_before_model` for chaining — it must be deleted or rewritten too.

---

## Consolidated Risk Assessment

| # | Severity | Issue | Recommendation |
|---|----------|-------|----------------|
| 1 | CRITICAL | `_run_async_impl(ctx)` bypasses context creation | Use `run_async(ctx)` instead |
| 2 | CRITICAL | Concurrent children collide on depth-scoped keys | Per-child key scoping or result carrier pattern |
| 3 | HIGH | `output_key` collision between concurrent children | Include child_id in output_key |
| 4 | MEDIUM | Reasoning callback keys not depth-scoped | Acceptable for v1, document explicitly |
| 5 | N/A | Orchestrator state reads | Correct (reads, not writes) |
| 6 | LOW | Orchestrator state writes with depth_key | Correct |
| 7 | LOW | REPLTool state writes with depth_key | Correct |
| 8 | MEDIUM | SetModelResponseTool callback must filter by tool name | Verify make_worker_tool_callbacks tool-name guard |
| 9 | INFO | No temp: prefix usage | Correct |
| 10 | MEDIUM | Worker callback deletion needs import audit | Search all consumers before deleting |

## Key Amendments Required Before Implementation

1. **Phase 3 dispatch must use `child.run_async(ctx)` not `child._run_async_impl(ctx)`** — ensures proper ADK lifecycle.
2. **Concurrent children need per-instance state isolation** — either:
   - (a) Use in-memory result carriers on child objects (like current worker pattern), OR
   - (b) Add `child_id` to `depth_key()` signature: `depth_key(key, depth, child_id)`, OR
   - (c) Serialize child execution (defeats purpose of batched dispatch)
3. **Phase 0 should verify `make_worker_tool_callbacks` tool-name filtering** — ensure `after_tool_callback` doesn't interfere with `execute_code` results.
