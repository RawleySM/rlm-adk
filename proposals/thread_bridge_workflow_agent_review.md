# Thread Bridge Plans: Workflow Agent Expert Review

**Reviewer**: Workflow Agent Expert (Google ADK agent class hierarchy)
**Date**: 2026-03-24
**Scope**: Plans A, B, and C evaluated against 8 multi-agent workflow criteria

---

## Executive Summary

**Plan B best preserves multi-agent workflow integrity.** It is the only plan that (a) identifies and solves the `_EXEC_LOCK` deadlock under recursive dispatch, (b) discovers and provides a concrete fix for the `reasoning_before_model` system instruction overwrite that would silently destroy SkillToolset L1 XML injection, and (c) provides a disciplined `llm_query_fn` parameter pattern that keeps skill functions testable without module-global mutation. Plan A is sound on the core thread-bridge mechanism but has a latent `_EXEC_LOCK` deadlock and no awareness of the system instruction overwrite. Plan C is the least detailed, places sync closures inside `dispatch.py` (coupling the event-loop reference into the wrong module), and also misses the `_EXEC_LOCK` and system instruction issues.

**Recommendation**: Implement Plan B with the two amendments noted in the Recommendations section.

---

## Per-Plan Workflow Analysis

### Plan A

**Thread bridge approach**: New module `rlm_adk/repl/thread_bridge.py` with `make_sync_llm_query()` and `make_sync_llm_query_batched()`. Orchestrator captures the running event loop in `_run_async_impl()` and passes it to the factory functions. `REPLTool.run_async()` routes through a new `execute_code_threaded()` on `LocalREPL` that calls `loop.run_in_executor(None, _execute_code_inner, ...)`.

**Strengths**:
- Clean separation of the thread bridge into its own module
- Correct identification that `run_in_executor` yields the event loop so `run_coroutine_threadsafe` will not deadlock
- Retains AST rewriter as an env-var-toggled fallback (`RLM_REPL_THREAD_BRIDGE=0`)
- `dispatch.py` is explicitly left unchanged -- async closures are the target of `run_coroutine_threadsafe`, and they run entirely on the event loop thread

**Weaknesses**:
- **CRITICAL: `_EXEC_LOCK` deadlock not addressed.** Plan A's `execute_code_threaded()` calls `self._execute_code_inner(code, trace)` which acquires `_EXEC_LOCK` (line 292 of `local_repl.py`: `with _EXEC_LOCK, self._temp_cwd()`). When code inside this locked section calls `llm_query()` -> `run_coroutine_threadsafe` -> child orchestrator -> child REPL's `execute_code_threaded()` -> child `_execute_code_inner()` tries to acquire `_EXEC_LOCK` -> **DEADLOCK**. The parent thread holds `_EXEC_LOCK` and is blocked on `future.result()`. The child thread cannot acquire `_EXEC_LOCK` because it is process-global. Plan A's risk analysis table row for "Recursive dispatch (child orchestrator also uses thread bridge)" claims "The event loop handles all async scheduling" but misses that each child creates its own REPL and calls `_execute_code_inner`, which re-enters the same process-global lock.
- Skill function globals pattern uses bare module-level references (`llm_query()` resolved from REPL globals at call time). While this works, it is untestable without patching module globals or REPL namespace.
- No awareness of the `reasoning_before_model` system instruction overwrite that would silently destroy SkillToolset L1 XML.

### Plan B

**Thread bridge approach**: Same `thread_bridge.py` module with `make_sync_llm_query()` and `make_sync_llm_query_batched()`. Same orchestrator loop-capture pattern. However, Plan B introduces a new `_execute_code_threadsafe()` method on `LocalREPL` that **does NOT acquire `_EXEC_LOCK`** and does NOT call `os.chdir()`. Instead it uses `_make_cwd_open()` for CWD-safe file access. Furthermore, `execute_code_threaded()` uses a **one-shot `ThreadPoolExecutor(max_workers=1)`** created and destroyed per call, preventing default-pool exhaustion under recursive dispatch.

**Strengths**:
- **`_EXEC_LOCK` deadlock solved.** The `_execute_code_threadsafe()` method avoids `_EXEC_LOCK` entirely. Plan B explicitly documents the deadlock scenario: "Parent worker thread T1 holds `_EXEC_LOCK` -> calls `llm_query()` -> blocks on `future.result()` -> event loop runs child -> child REPLTool -> child worker T2 tries `_EXEC_LOCK` -> DEADLOCK." The fix is architecturally sound: using `_make_cwd_open()` instead of `os.chdir()` removes the need for process-global locking.
- **One-shot executor prevents pool exhaustion.** Under recursive dispatch (depth 3+), each level needs a blocked worker thread simultaneously. The default `ThreadPoolExecutor` has limited workers. One-shot executors are created per-call and cleaned up immediately, so N depth levels can each have their own thread.
- **`reasoning_before_model` overwrite identified and fixed.** Plan B documents a Phase 3.5 as "CRITICAL" -- ADK's execution order is: (1) `_preprocess_async` -> `_process_agent_tools` -> `SkillToolset.process_llm_request()` -> `append_instructions()` appends L1 XML to `system_instruction`, then (2) `_call_llm_async` -> `_handle_before_model_callback` -> `reasoning_before_model` **replaces** `system_instruction` with the merged static+dynamic text. This overwrites the SkillToolset's appended content. The fix proposes reading back existing additions and preserving them.
- **`llm_query_fn` parameter pattern.** Skill functions accept `llm_query_fn` as a keyword parameter, auto-injected by the loader via `_wrap_with_llm_query_injection()`. This makes skill functions testable in isolation (pass a mock `llm_query_fn` in tests) without module-global mutation.
- **Split gating for children.** Plan B correctly observes that child orchestrators should NOT get SkillToolset discovery tools (L1/L2 are a root-agent concern) but SHOULD get REPL globals (Python functions must be callable at any depth). This is a nuanced workflow-aware design.
- **`_agent_span_stack` interleaving bug identified.** Plan B notes that `SqliteTracingPlugin._agent_span_stack` is a flat list used as a stack for agent_name attribution. Under batched child dispatch, cooperative interleaving at `await` points can corrupt the stack. The fix (scope per `invocation_id`) is deferred but documented.

**Weaknesses**:
- The `reasoning_before_model` fix (Phase 3.5) is described conceptually but the proposed code is somewhat tentative (multiple alternatives offered). The cleanest solution would be to change `reasoning_before_model` to use `append_instructions()` for the dynamic portion rather than replacing the full system instruction, but this requires careful understanding of ADK's instruction processor ordering.
- The plan is the longest and most detailed, which could increase implementation risk from scope creep.

### Plan C

**Thread bridge approach**: Places sync closure wrappers **inside `create_dispatch_closures()`** in `dispatch.py` (new `llm_query_sync` and `llm_query_batched_sync` closures). Adds an `event_loop` parameter to `create_dispatch_closures()`. Changes the return type from a 3-tuple to a 5-tuple (or named tuple). `REPLTool` gets a new `_execute_in_thread()` method that calls `loop.run_in_executor(None, self.repl.execute_code, code, trace)`.

**Strengths**:
- Simplest of the three plans -- fewest new files, fewest new methods.
- Correctly identifies that ADK's `functions.py` already has thread pool infrastructure for sync tools.
- Acknowledges existing `_TaskLocalStream` + `ContextVar` mechanism handles thread-safe stdout/stderr capture.

**Weaknesses**:
- **CRITICAL: `_EXEC_LOCK` deadlock not addressed.** Plan C calls `self.repl.execute_code` from `_execute_in_thread`, which goes through `_execute_code_inner` -> `_EXEC_LOCK`. Same deadlock as Plan A under recursive dispatch.
- **Sync closures placed in `dispatch.py` -- wrong module boundary.** The sync closures need a reference to the running event loop, which is only available inside `_run_async_impl()`. Passing `event_loop` into `create_dispatch_closures()` works but couples an asyncio-level concern (event loop reference) into a module whose responsibility is child orchestrator dispatch logic. Plans A and B correctly isolate this in `thread_bridge.py` / orchestrator wiring.
- **Return type fragility.** Changing from a 3-tuple to a 5-tuple is acknowledged as fragile. Plan C notes "Or better: return a named tuple / dataclass" but does not commit to a solution.
- **No awareness of `reasoning_before_model` system instruction overwrite.**
- **Least detailed skill infrastructure.** The `llm_query` parameter injection discussion rambles through multiple approaches without settling on one (global reference vs `llm_query_fn` parameter vs module global patching vs `functools.partial` wrapper). Plan B's `llm_query_fn` parameter + loader wrapper is much cleaner.
- **No `_EXEC_LOCK`-free execution path.** Plan C's `_execute_in_thread` delegates to the existing `execute_code()`, which always uses `_EXEC_LOCK`.

---

## Criterion-by-Criterion Assessment

### 1. ParallelAgent Compatibility

The current `dispatch.py` no longer uses `ParallelAgent` directly -- it was replaced by child `RLMOrchestratorAgent` instances with `asyncio.gather()` for batched dispatch. All three plans preserve this pattern correctly. The `asyncio.gather()` inside `llm_query_batched_async` runs all N children concurrently in the event loop. `run_coroutine_threadsafe()` submits the entire `llm_query_batched_async` coroutine (which internally uses `asyncio.gather()`) to the event loop as a single unit. The parent worker thread blocks on `future.result()`, so there is no concurrent mutation of `call_log_sink` or `_pending_llm_calls`.

**Verdict**: All three plans are compatible. The `worker.parent_agent = None` cleanup pattern is not applicable (dispatch.py uses child orchestrators, not ParallelAgent workers). The `_child_semaphore` limits concurrency correctly regardless of thread bridge.

### 2. RLMOrchestratorAgent Lifecycle

The orchestrator's `async for event in self.reasoning_agent.run_async(ctx)` loop runs on the event loop thread. With the thread bridge, `REPLTool.run_async()` calls `loop.run_in_executor()` which returns an awaitable Future. The event loop is free while the worker thread runs REPL code. When the worker thread calls `llm_query()` -> `run_coroutine_threadsafe()`, the submitted coroutine (child dispatch) runs on the same event loop.

The child event queue drain (`while not _child_event_queue.empty()`) happens after each event yielded from `reasoning_agent.run_async(ctx)`. Since `REPLTool.run_async()` is one such event source, child events accumulated during REPL execution are drained when the tool returns its result event.

**Verdict**: All three plans maintain the orchestrator lifecycle correctly. The event queue drain timing is unchanged because `run_in_executor` is awaited inside `REPLTool.run_async()`, and the drain happens at the orchestrator level after each yielded event.

### 3. Child Orchestrator Dispatch

When `llm_query()` dispatches a child `RLMOrchestratorAgent`, that child runs its own `_run_async_impl()` which creates its own REPL, reasoning agent, and tools. Each child captures `asyncio.get_running_loop()` in its own `_run_async_impl()`.

- **Plan A**: Each child creates its own `LocalREPL` and calls `execute_code_threaded()`. **DEADLOCK RISK**: child's `_execute_code_inner` tries to acquire process-global `_EXEC_LOCK` while parent thread holds it.
- **Plan B**: Each child creates its own `LocalREPL` and calls `execute_code_threaded()` -> `_execute_code_threadsafe()` which **does NOT use `_EXEC_LOCK`**. Safe.
- **Plan C**: Each child creates its own `LocalREPL` and calls `execute_code()` via `_execute_in_thread`. **DEADLOCK RISK**: same as Plan A.

**Verdict**: Only Plan B handles recursive dispatch correctly. Plans A and C have a latent deadlock that will manifest at depth >= 2 when both parent and child REPL code contain `llm_query()` calls.

### 4. SkillToolset as a tool_union

ADK resolves `tool_union` objects in `_process_agent_tools` (line 881 of `base_llm_flow.py`). For each `tool_union` in `agent.tools`:
- If it is a `BaseToolset`, call `tool_union.process_llm_request()` (injects L1 XML via `append_instructions`)
- Then call `get_tools()` to get individual `BaseTool` instances (ListSkillsTool, LoadSkillTool, etc.)

All three plans add `SkillToolset` to the tools list alongside `REPLTool` and `SetModelResponseTool`. This is correct -- `_process_agent_tools` iterates the full tools list and handles both `BaseTool` and `BaseToolset` instances.

However, there is a **critical interaction** that only Plan B identifies:

1. `_preprocess_async` runs `request_processors` (instructions processor sets `system_instruction` from `static_instruction`), then calls `_process_agent_tools` which calls `SkillToolset.process_llm_request()` -> `append_instructions()` -> appends L1 XML to `system_instruction`.
2. `_call_llm_async` calls `_handle_before_model_callback` -> `reasoning_before_model` at line 146 of `callbacks/reasoning.py`: `llm_request.config.system_instruction = system_instruction_text` -- this **overwrites** the appended SkillToolset content.

**Verdict**: Plan B is the only plan that identifies and fixes this critical issue. Plans A and C would silently lose all skill discovery XML. The SkillToolset would appear to be wired but the model would never see the L1 skill listing.

### 5. InvocationContext Branching

Child agents are created via `ctx.model_copy()` with a branch suffix (dispatch.py line 316-317). The thread bridge does not affect context isolation because:
- `run_coroutine_threadsafe()` submits a coroutine to the event loop, and that coroutine creates its own branch context
- The worker thread never touches `InvocationContext` directly -- it only calls `llm_query()` which returns an `LLMResult`
- Branch isolation is handled entirely in the event loop thread by `_run_child`

**Verdict**: All three plans maintain branch isolation correctly. The thread bridge is transparent to context branching.

### 6. LlmAgent Tool Loop Termination

The reasoning agent's tool loop ends when `set_model_response` is called. `SetModelResponseTool` is wired alongside `REPLTool` (and now `SkillToolset`). The BUG-13 monkey-patch in `worker_retry.py` suppresses premature termination when `_output_schema_processor.get_structured_model_response()` encounters a `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel.

The thread bridge does not affect this mechanism:
- `SetModelResponseTool.run_async()` runs on the event loop thread (it is not a REPL-executed tool)
- The BUG-13 patch is process-global and idempotent
- `ReflectAndRetryToolPlugin` / `make_worker_tool_callbacks` operates at the ADK callback level, which fires after tool completion
- `REPLTool.run_async()` returns normally after `run_in_executor` completes -- ADK's post-tool callback flow is unchanged

**Verdict**: All three plans are compatible. The thread bridge does not affect tool loop termination or the BUG-13 patch.

### 7. Worker Pool Lifecycle

The `WorkerPool` has been replaced by `DispatchConfig` (a simple configuration holder). The actual dispatch uses child `RLMOrchestratorAgent` instances created per-call in `_run_child()`. There is no acquire/release/on-demand creation lifecycle to maintain.

The thread bridge affects timing but not lifecycle:
- `run_coroutine_threadsafe()` submits `_run_child()` to the event loop
- `_run_child()` creates a `create_child_orchestrator()`, runs it, reads the completion, cleans up the child REPL
- The `_child_semaphore` limits concurrency
- All of this happens on the event loop thread, not the worker thread

**Verdict**: All three plans maintain the dispatch lifecycle correctly. `DispatchConfig.ensure_initialized()` is a no-op, and child creation/cleanup happens entirely in the event loop.

### 8. Skill Function as a Workflow Primitive

The vision is that skill functions can call `llm_query()` which dispatches child orchestrators. This requires the thread bridge to work because the skill function body is opaque bytecode (not AST-rewritable).

- **Plan A**: Skill functions reference `llm_query` as a bare global resolved from REPL namespace. Works at runtime but is untestable in isolation.
- **Plan B**: Skill functions accept `llm_query_fn` as a keyword parameter. The loader wraps them with auto-injection from REPL globals. Testable with mock `llm_query_fn`. The wrapper checks if `llm_query_fn` is already provided, allowing explicit override in tests.
- **Plan C**: Rambles through multiple approaches. The final recommendation is the same `llm_query_fn` parameter + loader wrapper pattern, but arrived at after extensive deliberation rather than presented as a clean design.

For batched dispatch: `llm_query_batched()` works identically to `llm_query()` through the thread bridge. The sync wrapper submits `llm_query_batched_async()` to the event loop via `run_coroutine_threadsafe()`. Inside, `asyncio.gather()` runs all N children concurrently. The parent worker thread blocks until all children complete.

**Recursive skill dispatch**: A skill function calls `llm_query()` -> child orchestrator at depth+1 -> child REPL executes code -> child code might call another skill function -> another `llm_query()` -> depth+2. This requires:
1. No `_EXEC_LOCK` deadlock (only Plan B)
2. Sufficient threads (Plan B's one-shot executor; Plans A/C use default pool which may exhaust)
3. Each depth level captures its own event loop reference (all plans)

**Verdict**: Plan B provides the cleanest and most correct skill function design. Plans A and C would deadlock on recursive skill dispatch.

---

## Risks and Gaps

### Risks Shared Across All Plans

1. **ContextVar stdout/stderr capture in worker threads.** All plans rely on `_TaskLocalStream` + `ContextVar` for thread-safe output capture. `ContextVar` provides task-local (not thread-local) storage by default. When `run_in_executor` creates a new thread, the context is **copied** from the calling coroutine's context. This means the ContextVar tokens set in `_execute_code_threadsafe` (Plan B) or `_execute_code_inner` (Plans A/C) are visible in the worker thread. However, `_TaskLocalStream` at line 39-68 of `local_repl.py` uses `_capture_stdout.get(None)` which returns `None` in threads that did not set the token, falling through to the real `sys.stdout`. Plan B's `_execute_code_threadsafe` explicitly sets ContextVar tokens (`tok_out = _capture_stdout.set(stdout_buf)`) in the worker thread, which is correct. Plans A and C do not explicitly address this -- they rely on `_execute_code_inner` which uses the context manager `_capture_output()` that replaces `sys.stdout`/`sys.stderr` globally (not ContextVar-based). This is the OLD pattern that `_TaskLocalStream` is supposed to replace. Under concurrent execution (parent blocked + child running), the global `sys.stdout`/`sys.stderr` replacement in `_execute_code_inner` could interleave output. Plan B avoids this by using ContextVars exclusively.

2. **`asyncio.wait_for` + `run_in_executor` cancellation semantics.** When `asyncio.wait_for` times out on `run_in_executor`, the underlying thread continues running (Python cannot interrupt threads). The `cancel_futures=True` in Plan B's `executor.shutdown()` requests cancellation but does not guarantee the thread stops. Code stuck in `future.result()` inside `llm_query()` will raise `concurrent.futures.CancelledError` if the event loop closes the future, but the REPL code above the `llm_query()` call site may leave partial state. This is a fundamental Python limitation, not specific to any plan.

3. **ADK version coupling.** All plans depend on ADK's `SkillToolset`, `append_instructions`, and the `_process_agent_tools` -> `_call_llm_async` execution order. If ADK changes the order of preprocessors vs callbacks, the `reasoning_before_model` fix (Plan B) may need adjustment.

### Plan-Specific Risks

| Plan | Risk | Severity | Notes |
|------|------|----------|-------|
| A | `_EXEC_LOCK` deadlock at depth >= 2 | **Critical** | Manifests when parent REPL code calls `llm_query()` and child REPL code also calls `llm_query()` |
| A | System instruction overwrite destroys skill XML | **Critical** | Skills appear wired but model never sees L1 listing |
| A | Default `ThreadPoolExecutor` exhaustion at depth >= 4 | **High** | Default pool has ~5 workers; each depth level blocks one |
| B | `reasoning_before_model` fix needs precise implementation | **Medium** | The conceptual fix is correct but code is tentative |
| B | One-shot executor overhead | **Low** | Creating a `ThreadPoolExecutor(max_workers=1)` per REPL call adds ~0.1ms overhead |
| C | `_EXEC_LOCK` deadlock at depth >= 2 | **Critical** | Same as Plan A |
| C | System instruction overwrite destroys skill XML | **Critical** | Same as Plan A |
| C | Return type fragility (5-tuple) | **Medium** | Acknowledged but not resolved |
| C | Sync closures in `dispatch.py` couples event-loop concern | **Medium** | Violates module boundary (dispatch handles orchestrator logic, not asyncio bridging) |

---

## Recommendations

1. **Implement Plan B** as the foundation. It is the only plan that correctly handles all eight review criteria.

2. **Refine the `reasoning_before_model` fix (Phase 3.5).** Rather than the read-back-and-preserve approach proposed in Plan B, the cleaner fix is to change `reasoning_before_model` so that it uses `llm_request.append_instructions([dynamic_instruction])` for the dynamic portion instead of overwriting `system_instruction` entirely. The static instruction is already set by ADK's instructions processor (`instructions.py` line 97-111). The callback should only append the dynamic metadata. This preserves anything previously appended by toolsets (SkillToolset, ExampleTool, etc.) and aligns with ADK's own append-based pattern. The specific change would be:

   ```python
   # BEFORE (line 144-146 of callbacks/reasoning.py):
   if system_instruction_text:
       llm_request.config = llm_request.config or types.GenerateContentConfig()
       llm_request.config.system_instruction = system_instruction_text

   # AFTER:
   if dynamic_instruction:
       llm_request.append_instructions([dynamic_instruction])
   # static_instruction is already set by ADK's instructions processor -- do not overwrite
   ```

   This requires verifying that ADK's instructions processor correctly handles the `static_instruction` field before `before_model_callback` fires. Based on the flow analysis (`_preprocess_async` at line 862 runs `request_processors` which includes the instructions processor, then `_process_agent_tools`; `_call_llm_async` at line 1109 runs `before_model_callback`), this ordering is confirmed: instructions processor runs first, then toolsets, then before_model_callback.

3. **Add a regression test for the system instruction overwrite.** The test should verify that when `SkillToolset` is wired, the L1 XML appears in the final `system_instruction` that reaches the model. This can be done by inspecting `llm_request.config.system_instruction` after `reasoning_before_model` runs, asserting it contains both the RLM static/dynamic instruction AND the `<available_skills>` XML block.

4. **Consider depth-limiting thread creation.** Plan B's one-shot executor pattern is correct but creates unbounded threads for very deep recursion. Consider adding a thread-depth counter (distinct from the orchestrator depth limit) that raises a clear error when exceeded, preventing runaway thread creation under pathological recursive dispatch.
