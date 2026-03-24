# Thread-Bridge Callback Expert Review

## Executive Summary

**Plan B wins on callback safety**, with Plan A a close second and Plan C trailing due to incomplete analysis of critical edge cases.

All three plans share the same core mechanism -- `loop.run_in_executor()` for REPL code, `asyncio.run_coroutine_threadsafe()` for `llm_query()` bridging back -- so the fundamental callback safety property is identical across them: **ADK callbacks always fire on the event loop thread, after `tool.run_async()` completes, and the thread bridge does not change this**. The differentiation is in how thoroughly each plan addresses the secondary callback concerns: `_EXEC_LOCK` deadlock under recursive dispatch, `reasoning_before_model` system instruction overwrite when `SkillToolset` is present, and `SqliteTracingPlugin._agent_span_stack` corruption under batched children.

Plan B is the only plan that:
1. Identifies and solves the `_EXEC_LOCK` deadlock under recursive dispatch (parent holds lock, child needs it)
2. Identifies and proposes a fix for the `reasoning_before_model` / `SkillToolset.process_llm_request()` system instruction overwrite (Phase 3.5)
3. Identifies the `_agent_span_stack` interleaving bug under batched children as a known gap
4. Uses one-shot `ThreadPoolExecutor` per execution to prevent default-pool exhaustion under recursive depth

Plan A is architecturally sound but misses risks #1 and #2. Plan C is the least refined, with unresolved design decisions inline (e.g., multiple competing approaches for `llm_query` injection into skill functions) and no analysis of the callback interaction risks that Plan B catches.

---

## Criterion 1: Callback Safety Under Threading

### Ground Truth (from ADK source, functions.py lines 430-570)

The callback execution sequence in `_execute_single_function_call_async()` is:

```
1. plugin_manager.run_before_tool_callback()     [event loop]
2. agent.canonical_before_tool_callbacks          [event loop]
3. tool.run_async()                               [event loop, awaits run_in_executor]
   -- worker thread runs REPL code here --
   -- worker thread blocks on future.result() for llm_query --
   -- event loop is FREE during run_in_executor --
4. plugin_manager.run_after_tool_callback()       [event loop]
5. agent.canonical_after_tool_callbacks           [event loop]
```

The critical property: `tool.run_async()` is `await`ed. When it internally does `await loop.run_in_executor(...)`, the event loop is yielded. All code before and after `tool.run_async()` runs on the event loop thread. The worker thread never touches `tool_context`, `callback_context`, or any ADK callback objects.

### Plan A Assessment

Plan A correctly identifies that `tool_context.state[key] = value` writes happen inside `REPLTool.run_async()` (on the event loop thread, before/after the `run_in_executor` call), not inside the worker thread. The REPL code in the worker thread writes to `repl.locals` and `repl.globals` -- these are REPL-internal dicts, not ADK state objects. The `flush_fn` pattern (dispatch closures) runs on the event loop via `run_coroutine_threadsafe`, so state mutations from child dispatch also stay on the event loop.

**Verdict**: Safe. Callbacks fire correctly. No race conditions between worker thread and callbacks.

**Missed risk**: Plan A uses the existing `_execute_code_inner()` method which acquires `_EXEC_LOCK`. Under recursive dispatch (parent REPL thread holds lock -> `llm_query()` -> child orchestrator -> child REPL needs lock), this deadlocks. Plan A does not analyze this scenario.

### Plan B Assessment

Plan B correctly identifies all of the above and additionally:
- Creates a new `_execute_code_threadsafe()` method that explicitly avoids `_EXEC_LOCK` and `os.chdir()`, using `_make_cwd_open()` instead (line 235 of Plan B)
- Uses a one-shot `ThreadPoolExecutor(max_workers=1)` per execution (line 201 of Plan B) instead of the default executor, preventing pool exhaustion under recursive depth
- Explicitly states that "Plugin/agent callbacks fire in `_execute_single_function_call_async()` which runs on the event loop. They fire AFTER `tool.run_async()` returns" (Plan B section 1.7, point 2)

**Verdict**: Safe, and more robust under recursive dispatch than Plan A.

### Plan C Assessment

Plan C proposes putting sync closures directly inside `dispatch.py` rather than a separate `thread_bridge.py` module. The callback safety analysis is briefer: "ADK already runs sync tools in thread pools" is stated but the specific callback ordering is not traced through the ADK source. Plan C's thread safety section (1.7) covers the same GIL / callback ordering points as Plans A and B but with less specificity.

Plan C proposes reusing the existing `execute_code()` method via `loop.run_in_executor(None, self.repl.execute_code, code, trace)` (line 122-124). Like Plan A, this hits `_EXEC_LOCK` and will deadlock under recursive dispatch.

**Verdict**: Safe for single-depth execution. Deadlocks under recursive dispatch.

---

## Criterion 2: Plugin Lifecycle Preservation

### Current Plugin Stack (from Runner)

1. `SqliteTracingPlugin` -- before/after agent, before/after model, on_model_error, before/after tool, on_event, before/after run
2. `ObservabilityPlugin` -- before/after agent, before/after model, before_tool, on_event, after_run
3. `LangfuseTracingPlugin` (optional) -- wraps OTel instrumentation
4. `DebugLoggingPlugin` (deprecated, replaced by ObservabilityPlugin verbose mode)

### Impact Analysis (All Plans)

**No plugin lifecycle changes.** The thread bridge modifies what happens *inside* `REPLTool.run_async()`, not the call site in `_execute_single_function_call_async()`. The ADK framework calls:
- `before_tool_callback` before `tool.run_async()` -- unchanged
- `after_tool_callback` after `tool.run_async()` returns -- unchanged
- The `result` dict passed to `after_tool_callback` is the return value of `run_async()` -- unchanged

The `REPLTool.run_async()` method still:
- Writes `LAST_REPL_RESULT` to `tool_context.state` (lines 314-327 of repl_tool.py) -- unchanged
- Calls `_finalize_telemetry()` (line 354) for `SqliteTracingPlugin`'s telemetry finalizer -- unchanged
- Returns the same `{stdout, stderr, variables, llm_calls_made, call_number}` dict -- unchanged

### SqliteTracingPlugin Specific

The `SqliteTracingPlugin.before_tool_callback` (line 1194) stores `id(tool_context)` as a pending key. The `after_tool_callback` (line 1254) pops that key and updates the telemetry row. This pairing works because `tool_context` is created once per function call in `_create_tool_context()` (functions.py line 1013) and the same object reference flows through both callbacks. The thread bridge does not change `tool_context` identity or lifecycle.

The `make_telemetry_finalizer()` closure (line 460) is called by `REPLTool._finalize_telemetry()` using `id(tool_context)` as key. This fires inside `run_async()` on the event loop thread, before the return. Safe and unchanged across all plans.

**New `execution_mode` field**: Plans A and B both add an `execution_mode` field to `LAST_REPL_RESULT`. This is additive -- `SqliteTracingPlugin.after_tool_callback` already captures `result_payload` (line 1278) as a JSON serialization of the full result dict, so the new field flows through automatically. No schema change needed in the telemetry table (it goes into `result_payload`). Plan B additionally proposes sourcing it from `REPLTrace.execution_mode` (Phase 4D), which is cleaner.

### SkillToolset Tools and Plugin Callbacks

When `SkillToolset` is added to the tools list, ADK's `_process_agent_tools` resolves it into individual tools (`ListSkillsTool`, `LoadSkillTool`, `LoadSkillResourceTool`, `RunSkillScriptTool`). Each of these is a regular `BaseTool`. When the model calls `load_skill`, ADK invokes it through `_execute_single_function_call_async`, which fires the full plugin callback chain: `before_tool_callback` -> `tool.run_async()` -> `after_tool_callback`. `SqliteTracingPlugin` captures these automatically -- it already records `tool_name` and `tool_args_keys` for any tool.

Plan B (Phase 4C, line 753) explicitly adds `elif` branches in `after_tool_callback` for skill tool names to populate `skill_name_loaded` and `skill_instructions_len` telemetry columns. This is the most observability-complete approach. Plan A mentions this in passing (Phase 4C). Plan C does not address it.

**Verdict**: All three plans preserve plugin lifecycle. Plan B is most thorough on SkillToolset observability.

---

## Criterion 3: SkillToolset Callback Interaction

### The System Instruction Overwrite Problem

This is the most important callback interaction risk, and **only Plan B identifies it**.

ADK's execution order within an LlmAgent step is:
1. `_process_agent_tools()` iterates `agent.tools`. For `BaseToolset` instances (including `SkillToolset`), it calls `toolset.process_llm_request(llm_request)` which **appends** L1 XML and skill system instructions to `llm_request.config.system_instruction`.
2. `_handle_before_model_callback()` fires plugin `before_model_callback` chain, then agent `before_model_callback`.
3. `reasoning_before_model` (the agent's `before_model_callback` in `reasoning.py` line 113) does:
   ```python
   llm_request.config.system_instruction = system_instruction_text
   ```
   This **replaces** the system instruction entirely, destroying whatever `SkillToolset.process_llm_request()` appended in step 1.

**Impact**: If not fixed, skills would never appear in the model's prompt. The model would never see `<available_skills>` XML. `load_skill` / `list_skills` tool calls would appear in the tool list but the model would have no L1 context telling it those tools exist or when to use them.

**Plan B's fix** (Phase 3.5, line 678): Change `reasoning_before_model` to detect and preserve toolset-injected content in `system_instruction` rather than blindly overwriting it. The proposed approach reads back `llm_request.config.system_instruction` to find toolset additions and preserves them.

**Plan A**: Does not identify this problem. States that "The `SkillToolset`'s default system instruction tells the model to use skill tools for interaction. This is additive" (line 408), which is incorrect -- it would be additive if `reasoning_before_model` did not overwrite it.

**Plan C**: Does not identify this problem. States that "the new skill system should create an instruction_router from the active skills" as an alternative approach, but does not analyze the `system_instruction` overwrite.

**Verdict**: Plan B is the only plan that would produce a working SkillToolset integration. Plans A and C would silently lose skill discovery.

---

## Criterion 4: Error Propagation Through Callbacks

### Child Dispatch Error Path

When REPL code calls `llm_query()` from the worker thread:
1. `asyncio.run_coroutine_threadsafe(llm_query_async(...), loop)` submits the coroutine
2. If the child dispatch fails (network error, model error, schema validation exhausted), the exception propagates into the `Future`
3. `future.result(timeout=...)` in the worker thread raises the exception
4. The exception propagates up through `exec()` in `_execute_code_inner()` / `_execute_code_threadsafe()`
5. Python's `exec()` catches it and sets `stderr` to the traceback
6. `REPLTool.run_async()` receives the `REPLResult` with `stderr` populated
7. The `result` dict with `has_errors=True` flows through `after_tool_callback`

All three plans handle this identically: exceptions from `future.result()` surface as REPL stderr, and the tool result dict carries error information to callbacks.

### Timeout Error Path

All plans use `asyncio.wait_for()` or `future.result(timeout=...)` with configurable timeouts. Plan B adds an explicit `asyncio.TimeoutError` handler in `execute_code_threaded()` (lines 211-218) that sets `stderr` and `_last_exec_error`. Plans A and C rely on the existing `execute_code()` timeout handling or propose similar explicit handling.

### `on_tool_error_callback` Path

If `tool.run_async()` itself raises (not a REPL code error, but e.g. a Python exception escaping `REPLTool.run_async()`), ADK's `_run_on_tool_error_callbacks()` fires (functions.py line 439). This path is unchanged by the thread bridge -- the exception would need to escape the `try/except` blocks in `run_async()` (lines 244-306 of repl_tool.py), which already catch `asyncio.CancelledError` and generic `Exception`. Only truly unexpected errors (e.g., `SystemExit`, `KeyboardInterrupt`) would reach `on_tool_error_callback`.

**Verdict**: Error propagation is safe across all plans. No differences.

---

## Criterion 5: Worker Retry Plugin Compatibility

### WorkerRetryPlugin Architecture

The `WorkerRetryPlugin` operates on **worker agents** (child LlmAgents in `ParallelAgent` batches), not on the reasoning agent. Its callbacks fire when a worker calls `set_model_response`:

1. `WorkerRetryPlugin.extract_error_from_result()` checks for empty values
2. `after_tool_cb` (from `make_worker_tool_callbacks()`) captures validated results on `agent._structured_result`
3. The BUG-13 patch (`_patch_output_schema_postprocessor()`) prevents ADK from terminating the worker loop on retry guidance responses

### Thread Bridge Impact on Workers

Workers do not use the thread bridge. Workers are `LlmAgent` instances that call `set_model_response` (not `execute_code`). The thread bridge only affects `REPLTool.run_async()` on the reasoning agent. Worker dispatch happens via `_run_child()` in `dispatch.py`, which creates a child `RLMOrchestratorAgent` and runs it entirely on the event loop via `run_coroutine_threadsafe`.

The child orchestrator's reasoning agent gets its own `REPLTool` and its own `LocalREPL`. If the child's REPL code calls `llm_query()`, the thread bridge kicks in for the child, but this is independent of the parent's thread bridge. The critical point: the BUG-13 monkey-patch is process-global and idempotent, so it works regardless of which thread or coroutine triggers structured output validation.

### Callback Ordering Preservation

The `WorkerRetryPlugin` depends on this callback ordering:
1. Plugin `after_tool_callback` (SqliteTracingPlugin) fires first -- records telemetry, defers lineage
2. Agent `after_tool_callback` (worker_retry `after_tool_cb`) fires second -- captures result, sets `_rlm_lineage_status`
3. Next `before_model_callback` (SqliteTracingPlugin) flushes deferred lineage

This ordering is determined by ADK's `_execute_single_function_call_async()` (functions.py line 541-565): plugins fire before canonical agent callbacks. The thread bridge does not change this ordering because it does not change the callback invocation site.

**Verdict**: WorkerRetryPlugin is unaffected by the thread bridge across all three plans.

---

## Criterion 6: Differences Between Plans

### Thread Pool Strategy

| Aspect | Plan A | Plan B | Plan C |
|--------|--------|--------|--------|
| Executor | Default (`None`) | One-shot `ThreadPoolExecutor(max_workers=1)` | Default (`None`) |
| `_EXEC_LOCK` | Uses existing (deadlocks under recursion) | Avoids entirely (new `_execute_code_threadsafe`) | Uses existing (deadlocks under recursion) |
| CWD handling | `os.chdir()` via `_EXEC_LOCK` | `_make_cwd_open()` (no chdir) | `os.chdir()` via `_EXEC_LOCK` |
| Recursive safety | No | Yes | No |

Plan B's approach is the only one safe for recursive dispatch (parent REPL -> `llm_query()` -> child orchestrator -> child REPL -> `llm_query()` -> grandchild). Plans A and C deadlock at depth 2 because the child's REPL thread tries to acquire `_EXEC_LOCK` held by the parent's blocked thread.

### Sync Bridge Placement

| Aspect | Plan A | Plan B | Plan C |
|--------|--------|--------|--------|
| Module | `rlm_adk/repl/thread_bridge.py` (new) | `rlm_adk/repl/thread_bridge.py` (new) | Inside `rlm_adk/dispatch.py` |
| Wiring | Orchestrator captures loop, creates wrappers | Orchestrator captures loop, creates wrappers | `create_dispatch_closures()` takes `event_loop` param, creates sync closures internally |

Plan C's approach modifies `dispatch.py`'s return type from 3-tuple to 5-tuple (or named tuple), which is a larger API change. Plans A and B keep `dispatch.py` unchanged and add the sync bridge as a separate concern.

### Skill Function Design

| Aspect | Plan A | Plan B | Plan C |
|--------|--------|--------|--------|
| `llm_query` access | Global name resolution in REPL namespace | `llm_query_fn` keyword parameter, auto-injected by loader wrapper | Multiple competing approaches discussed, no final decision |
| Testability | Requires REPL namespace setup | Pass explicit `llm_query_fn` in tests | Unclear |
| Loader wrapping | `collect_skill_repl_globals()` with late-binding wrapper | `_wrap_with_llm_query_injection()` with `functools.wraps` | `_make_bound_skill_fn()` proposed as one option |

Plan B's `llm_query_fn` parameter pattern is the most testable and explicit. Plan A's global-name approach works but makes skill functions untestable outside a REPL context. Plan C never converges on a design.

### Fallback Strategy

All three plans retain the AST rewriter as a fallback via environment variable (`RLM_REPL_THREAD_BRIDGE=0`). Plan B is the most explicit about the fallback code paths in `REPLTool.run_async()`.

---

## Callback-Related Gaps ALL Plans Miss

### GAP-1: `SqliteTracingPlugin._pending_tool_telemetry` Key Stability Under `asyncio.wait_for` Timeout

When `execute_code_threaded()` uses `asyncio.wait_for()` and the timeout fires, `asyncio.CancelledError` is raised inside `run_async()`. The `except asyncio.CancelledError` handler (line 244 of repl_tool.py) calls `_finalize_telemetry()`, which pops the `id(tool_context)` key from `_pending_tool_telemetry`. This is fine.

However, if the `CancelledError` propagates *before* `_finalize_telemetry` runs (e.g., during `await save_repl_code()`), the pending telemetry entry from `before_tool_callback` would be orphaned. This is a pre-existing gap in the current code, not introduced by the thread bridge, but the thread bridge's timeout path makes it slightly more likely. None of the plans address this.

**Recommendation**: Ensure `_finalize_telemetry()` is called in a `finally` block rather than in each exception handler, or rely on the existing `make_telemetry_finalizer` closure which is specifically designed to handle GAP-06 (cases where `after_tool_callback` does not fire).

### GAP-2: `SqliteTracingPlugin._agent_span_stack` Is Not Thread-Safe Under Concurrent Invocations

The `_agent_span_stack` is a plain `list` on the plugin instance. If multiple concurrent invocations share the same `SqliteTracingPlugin` instance (e.g., concurrent runner calls), `append()` and `pop()` interleave. This is a pre-existing bug, not introduced by the thread bridge. Plan B (Phase 4, line 769) is the only plan that identifies this as a known gap and proposes scoping by `invocation_id`.

### GAP-3: `ContextVar` Propagation Into Worker Thread

All three plans run REPL code in a worker thread via `loop.run_in_executor()`. Python `ContextVar` values are **copied** into the new thread's context by `run_in_executor()` (per PEP 567 and asyncio documentation). The existing `_capture_stdout` / `_capture_stderr` `ContextVar` tokens in `local_repl.py` are set before `run_in_executor()` in Plan B's `_execute_code_threadsafe()` (lines 128-129) and reset in the `finally` block (lines 173-174). This is correct.

However, none of the plans verify that `ContextVar` values set *inside* the worker thread (e.g., by `_TaskLocalStream`) are visible to callbacks that run after `run_in_executor` completes. Since callbacks run on the event loop thread, they see the event loop's `ContextVar` values, not the worker thread's. This is actually fine for the RLM use case (stdout/stderr are captured in `StringIO` buffers in the worker thread and returned as strings in `REPLResult`), but it would be incorrect if any callback tried to read `_capture_stdout` directly.

**Recommendation**: Document that `ContextVar` values set inside the worker thread are not visible to post-tool callbacks. This is not a bug for the current code but could become one if someone adds a callback that reads from capture `ContextVar`s.

### GAP-4: `_pending_llm_calls` Thread Safety Under Batched `llm_query`

`_pending_llm_calls` is a `list` on `LocalREPL`. In the thread bridge model, the REPL code runs in a worker thread, and `llm_query()` uses `run_coroutine_threadsafe()` to dispatch to the event loop. The `call_log_sink` (which is `repl._pending_llm_calls`) is appended to inside the dispatch closure, which runs on the event loop thread. Meanwhile, the worker thread is blocked on `future.result()`.

For single `llm_query()` calls, there is no race -- the worker is blocked while the event loop appends. For `llm_query_batched()`, all N children run concurrently on the event loop (via `asyncio.gather`), and all N append to `call_log_sink` from the event loop thread. Since `asyncio.gather` coroutines are cooperative (not preemptive), and `list.append()` is atomic under the GIL, this is safe.

Plan A explicitly analyzes this (risk table, line 544). Plan B implicitly covers it. Plan C does not address it.

### GAP-5: `telemetry_finalizer` and `make_telemetry_finalizer` Interaction With Thread-Bridged Timeout

The `make_telemetry_finalizer()` closure in `SqliteTracingPlugin` (line 460) is designed to handle GAP-06 where ADK's `after_tool_callback` may not fire. It uses the `_pending_tool_telemetry` dict shared with `after_tool_callback`. In the thread bridge, if `execute_code_threaded()` times out via `asyncio.wait_for()`, `REPLTool.run_async()` catches the `asyncio.TimeoutError` (wrapped as `CancelledError`) and calls `_finalize_telemetry()`. This pops the entry from `_pending_tool_telemetry`. Later, if `after_tool_callback` fires (which it should, since the tool returned a result), it finds the entry already popped and does a `popitem()` fallback (line 1026-1027 of sqlite_tracing.py). Since both run on the event loop thread, there is no race. But the `popitem()` fallback could pick up an entry from a *different* tool call if multiple tools were called in parallel. This is a pre-existing fragility.

---

## Recommendations

1. **Adopt Plan B as the implementation baseline.** It is the most thorough on callback safety, addresses the `_EXEC_LOCK` deadlock, identifies the `reasoning_before_model` overwrite, and uses the cleanest skill function pattern.

2. **Phase 3.5 is mandatory.** The `reasoning_before_model` system instruction overwrite must be fixed before `SkillToolset` integration or skills will be invisible to the model. The fix should read back `llm_request.config.system_instruction` after `_extract_system_instruction_text()` to detect and preserve toolset-injected content.

3. **Add a `finally` guard for `_finalize_telemetry()`** in `REPLTool.run_async()` to ensure telemetry rows are always finalized, even on unexpected exception paths. This mitigates GAP-1.

4. **Scope `_agent_span_stack` by `invocation_id`** as Plan B suggests (GAP-2). This should be done as a follow-up before batched skill dispatch is exercised.

5. **Document `ContextVar` visibility boundary** (GAP-3) in the thread bridge module docstring to prevent future callback authors from reading worker-thread-scoped `ContextVar`s from event-loop callbacks.

6. **Consider Plan B's `llm_query_fn` parameter pattern** for skill functions. It is more testable than Plan A's global-name approach and enables isolated unit tests of skill functions without REPL infrastructure.

7. **Retain the AST rewriter fallback** (env var `RLM_REPL_THREAD_BRIDGE=0`) for at least one release cycle, but make the thread bridge the default. All three plans agree on this.
