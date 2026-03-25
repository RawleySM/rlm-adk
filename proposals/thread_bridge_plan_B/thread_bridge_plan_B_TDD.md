# Thread Bridge Plan B -- TDD Implementation Roadmap

## Preamble

This document restructures Plan B into a strict RED/GREEN TDD implementation sequence. Tests are written FIRST and fail (RED), then the minimum implementation makes them pass (GREEN). Each cycle is independently committable.

**Reviewer refinements incorporated:**
1. Cleaner `reasoning_before_model` fix: use `llm_request.append_instructions([dynamic_instruction])` instead of overwriting `system_instruction` entirely
2. Thread-depth limit: configurable counter to prevent runaway thread creation under deep recursion
3. `_finalize_telemetry()` in a `finally` block in `REPLTool.run_async()`
4. Explicit `_adk_activated_skill_*` capture decision: skill activation tracking flows through telemetry table's `skill_name_loaded` column, not `session_state_events`
5. Document `ContextVar` visibility boundary in `thread_bridge.py` docstring

**Test infrastructure conventions:**
- Unit tests: mocks/stubs, no server, no database
- Integration tests: real `LocalREPL`, real `REPLTool`, mocked ADK context
- Provider-fake e2e tests: `FakeGeminiServer` + `ScenarioRouter` + `SqliteTracingPlugin` + full plugin stack via `run_fixture_contract_with_plugins()`
- All tests use `pytest` with `pytest-asyncio` where needed
- Run commands always use `.venv/bin/python -m pytest` with `-x -q`

---

## Phase 0: Legacy Cleanup (BEFORE any thread-bridge work)

Phase 0 removes all legacy code that the thread bridge replaces. This prevents implementing agents from being distracted by dead code paths during Phases 1-7. Every sub-step below lists exact files, exact removals, and a verification command.

**Rationale:** The AST rewriter, source-expansion registry, async REPL execution path, and sync-unsupported stub are all being replaced by the thread bridge. Removing them first creates a clean slate so that Phases 1-7 never encounter confusing bifurcation.

---

### Phase 0A: AST Rewriter Removal

#### Step 0A-1: Delete `rlm_adk/repl/ast_rewriter.py`

- **File to delete**: `rlm_adk/repl/ast_rewriter.py`
- **What to remove**: The entire file (231 lines). Contains `has_llm_calls()`, `LlmCallRewriter`, `_contains_await()`, `_promote_functions_to_async()`, `_FuncDefPromoter`, `_PromotedCallAwaiter`, `rewrite_for_async()`.
- **Verify**: `ls rlm_adk/repl/ast_rewriter.py` should return "No such file"
- **Run**: `.venv/bin/python -c "from rlm_adk.repl import ast_rewriter"` should raise `ModuleNotFoundError`

#### Step 0A-2: Remove AST rewriter imports and bifurcation from `REPLTool`

- **File to modify**: `rlm_adk/tools/repl_tool.py`
- **What to remove**:
  - Line 26: `from rlm_adk.repl.ast_rewriter import has_llm_calls, rewrite_for_async`
  - Lines 92-94: The `_rewrite_count`, `_rewrite_total_ms`, `_rewrite_failure_count` instance vars
  - Lines 222-243: The entire `if has_llm_calls(exec_code):` branch (AST rewrite + `execute_code_async` call). Replace with ONLY the sync path: `result = self.repl.execute_code(exec_code, trace=trace)`. The `llm_calls_made` variable becomes unconditionally `False` for now (the thread bridge will set it properly in Phase 1).
- **What to keep**: The sync execution path (`self.repl.execute_code(exec_code, trace=trace)`) on line 243. All error handling (`CancelledError`, `Exception`). All observability state writes. `_finalize_telemetry` calls.
- **Verify after removal**: `ruff check rlm_adk/tools/repl_tool.py` passes with no import errors
- **Run**: `.venv/bin/python -m pytest tests_rlm_adk/ -x -q --ignore=tests_rlm_adk/test_skill_arch_e2e.py -m "not provider_fake_extended"` -- existing tests should still pass for non-LLM-call code paths

#### Step 0A-3: Remove AST rewriter test files (if any exist)

- **Files to check**: `tests_rlm_adk/test_ast_rewriter.py`, `tests_rlm_adk/test_repl_rewriter.py`
- **Action**: Delete if they exist. These test removed functionality.
- **Run**: `.venv/bin/python -m pytest tests_rlm_adk/ -x -q --co` to confirm no test collection errors

---

### Phase 0B: Source Expansion Removal

#### Step 0B-1: Delete `rlm_adk/repl/skill_registry.py`

- **File to delete**: `rlm_adk/repl/skill_registry.py`
- **What to remove**: The entire file (237 lines). Contains `ReplSkillExport`, `ExpandedSkillCode`, `SkillRegistry` singleton, `register_skill_export()`, `expand_skill_imports()`, `build_auto_import_lines()`.
- **Verify**: `ls rlm_adk/repl/skill_registry.py` should return "No such file"
- **Run**: `.venv/bin/python -c "from rlm_adk.repl import skill_registry"` should raise `ModuleNotFoundError`

#### Step 0B-2: Remove `expand_skill_imports()` from `REPLTool`

- **File to modify**: `rlm_adk/tools/repl_tool.py`
- **What to remove**:
  - Line 28: `from rlm_adk.repl.skill_registry import expand_skill_imports`
  - Lines 35-38: Imports of `REPL_DID_EXPAND`, `REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META` from state
  - Lines 172-195: The entire skill expansion block (the `try: expansion = expand_skill_imports(code)` block, the `except RuntimeError` handler, the `exec_code = expansion.expanded_code` assignment, and the `if expansion.did_expand:` state writes)
  - Replace with: `exec_code = code` (the submitted code passes through unmodified)
- **What to keep**: Everything else in `run_async()`.
- **Verify**: `ruff check rlm_adk/tools/repl_tool.py`
- **Run**: `.venv/bin/python -m pytest tests_rlm_adk/ -x -q --ignore=tests_rlm_adk/test_skill_arch_e2e.py -m "not provider_fake_extended"`

#### Step 0B-3: Remove skill_registry references from `sqlite_tracing.py`

- **File to modify**: `rlm_adk/plugins/sqlite_tracing.py`
- **What to remove**: Line 72 area: `if key.startswith("repl_skill_expansion_meta"):` branch (and any associated handling). This key is no longer written.
- **Verify**: `ruff check rlm_adk/plugins/sqlite_tracing.py`

#### Step 0B-4: Remove `rlm_adk/skills/test_skill.py` (source-expandable test skill)

- **File to modify or delete**: `rlm_adk/skills/test_skill.py`
- **What to remove**: This file imports from `rlm_adk.repl.skill_registry` and registers a `ReplSkillExport`. Delete it entirely.
- **Impact**: `test_skill_arch_e2e.py` depends on this file. That test file tests the source-expansion delivery mechanism which no longer exists. Either delete `test_skill_arch_e2e.py` and its supporting files, or mark them as skip/xfail. The thread bridge e2e tests (Cycles 19-24) will replace this coverage.
- **Files to also handle**:
  - `tests_rlm_adk/test_skill_arch_e2e.py` -- delete or mark xfail
  - `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json` -- delete if test is deleted
  - `tests_rlm_adk/provider_fake/instrumented_runner.py` -- keep (reusable for thread bridge e2e)
  - `tests_rlm_adk/provider_fake/stdout_parser.py` -- keep (reusable)
  - `tests_rlm_adk/provider_fake/expected_lineage.py` -- keep (reusable)
- **Verify**: `.venv/bin/python -m pytest tests_rlm_adk/ -x -q --co` -- no collection errors

#### Step 0B-5: Update `rlm_adk/skills/__init__.py` docstring

- **File to modify**: `rlm_adk/skills/__init__.py`
- **What to remove**: References to `repl/skill_registry.py`, `expand_skill_imports()`, and source-expandable mechanism in the docstring. Replace with a note that the skill system is being rebuilt via the thread bridge + module-import delivery (Plan B).
- **Verify**: `ruff check rlm_adk/skills/__init__.py`

---

### Phase 0C: Fallback Infrastructure Removal

#### Step 0C-1: Remove `sync_llm_query_unsupported` from `orchestrator.py`

- **File to modify**: `rlm_adk/orchestrator.py`
- **What to remove**:
  - Lines 290-297: The `sync_llm_query_unsupported` function definition and the `repl.set_llm_query_fns(sync_llm_query_unsupported, sync_llm_query_unsupported)` call.
- **What to keep**: The `repl.set_async_llm_query_fns(llm_query_async, llm_query_batched_async)` call at line 288 stays for now (removed in 0C-2).
- **Verify**: `ruff check rlm_adk/orchestrator.py`

#### Step 0C-2: Remove `set_async_llm_query_fns()` from `LocalREPL`

- **File to modify**: `rlm_adk/repl/local_repl.py`
- **What to remove**:
  - Lines 216-223: The entire `set_async_llm_query_fns()` method. The thread bridge will wire sync functions via `set_llm_query_fns()` -- there is no separate async path.
- **Also modify**: `rlm_adk/orchestrator.py`
  - Line 288: Remove the `repl.set_async_llm_query_fns(llm_query_async, llm_query_batched_async)` call. The orchestrator will wire sync bridge closures via `set_llm_query_fns()` in Phase 1 Cycle 7.
- **Verify**: `ruff check rlm_adk/repl/local_repl.py rlm_adk/orchestrator.py`

#### Step 0C-3: Remove `execute_code_async()` from `LocalREPL`

- **File to modify**: `rlm_adk/repl/local_repl.py`
- **What to remove**:
  - Lines 385-481: The entire `execute_code_async()` method. The thread bridge replaces this with `execute_code_threaded()` (added in Phase 1 Cycle 5).
  - The `_make_cwd_open()` method at lines 369-383: Keep this -- it will be reused by `_execute_code_threadsafe()`.
  - The `ContextVar` infrastructure at the top of the file (lines 31-71: `_capture_stdout`, `_capture_stderr`, `_TaskLocalStream`): Keep this -- it will be reused by `_execute_code_threadsafe()`.
- **Verify**: `ruff check rlm_adk/repl/local_repl.py`
- **Run**: `.venv/bin/python -m pytest tests_rlm_adk/ -x -q --ignore=tests_rlm_adk/test_skill_arch_e2e.py -m "not provider_fake_extended"`

---

### Phase 0D: State Key Cleanup (skill expansion keys)

#### Step 0D-1: Remove unused skill expansion state keys

- **File to modify**: `rlm_adk/state.py`
- **What to remove**:
  - Lines 81-84: `REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND` constant definitions
  - Remove these keys from `DEPTH_SCOPED_KEYS` (line 141 area)
  - Remove these keys from `EXPOSED_STATE_KEYS` (lines 156-159 area)
- **What to keep**: All other state keys.
- **Impact**: Check `repl_capture_plugin.py` and `dashboard/live_loader.py` which import these keys. Remove the imports and any code that references them.
- **Files to also modify**:
  - `rlm_adk/plugins/repl_capture_plugin.py`: Remove imports of `REPL_DID_EXPAND`, `REPL_EXPANDED_CODE` and any code referencing them
  - `rlm_adk/dashboard/live_loader.py`: Remove import of `REPL_EXPANDED_CODE` and any code referencing it
- **Verify**: `ruff check rlm_adk/state.py rlm_adk/plugins/repl_capture_plugin.py rlm_adk/dashboard/live_loader.py`

---

### Phase 0E: Verify Clean Slate

- **Run the full default test suite**:
  ```bash
  .venv/bin/python -m pytest tests_rlm_adk/ -x -q --ignore=tests_rlm_adk/test_skill_arch_e2e.py -m "not provider_fake_extended"
  ```
- **Expected result**: All passing tests still pass. Tests that depended on removed code (`test_skill_arch_e2e.py`) are ignored/deleted.
- **Run lint**:
  ```bash
  ruff check rlm_adk/ tests_rlm_adk/
  ruff format --check rlm_adk/ tests_rlm_adk/
  ```
- **Verify imports**:
  ```bash
  .venv/bin/python -c "from rlm_adk.tools.repl_tool import REPLTool; print('REPLTool OK')"
  .venv/bin/python -c "from rlm_adk.orchestrator import RLMOrchestratorAgent; print('Orchestrator OK')"
  .venv/bin/python -c "from rlm_adk.repl.local_repl import LocalREPL; print('LocalREPL OK')"
  ```
- **Confirm removed modules are gone**:
  ```bash
  .venv/bin/python -c "from rlm_adk.repl.ast_rewriter import has_llm_calls" 2>&1 | grep ModuleNotFoundError
  .venv/bin/python -c "from rlm_adk.repl.skill_registry import expand_skill_imports" 2>&1 | grep ModuleNotFoundError
  ```
- **The sync execution path in REPLTool should still work** for code that does NOT contain `llm_query()` calls. Only `llm_query()` dispatch is temporarily broken (it will be restored by Phase 1 Cycle 7).
- **Fix any breakage** before proceeding to Phase 1.

---

## Phase 0 Summary: Files Removed / Modified

| Action | File | What |
|--------|------|------|
| DELETE | `rlm_adk/repl/ast_rewriter.py` | Entire AST rewriter |
| DELETE | `rlm_adk/repl/skill_registry.py` | Entire source expansion registry |
| DELETE | `rlm_adk/skills/test_skill.py` | Source-expandable test skill |
| DELETE or SKIP | `tests_rlm_adk/test_skill_arch_e2e.py` | Tests for removed source-expansion delivery |
| MODIFY | `rlm_adk/tools/repl_tool.py` | Remove AST rewriter imports, bifurcation, skill expansion block |
| MODIFY | `rlm_adk/orchestrator.py` | Remove `sync_llm_query_unsupported`, `set_async_llm_query_fns` call |
| MODIFY | `rlm_adk/repl/local_repl.py` | Remove `set_async_llm_query_fns()`, `execute_code_async()` |
| MODIFY | `rlm_adk/plugins/sqlite_tracing.py` | Remove `repl_skill_expansion_meta` branch |
| MODIFY | `rlm_adk/state.py` | Remove `REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND` |
| MODIFY | `rlm_adk/plugins/repl_capture_plugin.py` | Remove expansion key imports/references |
| MODIFY | `rlm_adk/dashboard/live_loader.py` | Remove `REPL_EXPANDED_CODE` import/references |
| MODIFY | `rlm_adk/skills/__init__.py` | Update docstring |

---

## Phase 1: Thread Bridge Foundation

### Cycle 1: `make_sync_llm_query` -- basic dispatch from worker thread

**Plan B reference:** Step 1A

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_thread_bridge.py`
- **Test class/method**:
  - `TestMakeSyncLlmQuery::test_dispatches_from_worker_thread`
  - `TestMakeSyncLlmQuery::test_passes_keyword_args`
- **What the tests assert**:
  - A sync wrapper created by `make_sync_llm_query()` can be called from a worker thread (via `loop.run_in_executor`), submits the async dispatch to the event loop, blocks the calling thread, and returns the result.
  - Keyword arguments (`model=`, `output_schema=`) pass through to the async callable.
- **Exact behavior being validated**: The `asyncio.run_coroutine_threadsafe()` + `future.result()` pattern works when the sync wrapper is called from a non-event-loop thread while the event loop processes the submitted coroutine.
- **Fixtures/mocks**: A fake async `llm_query_async` coroutine that returns a deterministic string. A `ThreadPoolExecutor` to simulate the REPL worker thread. A real `asyncio` event loop.
- **WHY this test exists**: This is the core mechanism of the entire thread bridge. If `run_coroutine_threadsafe` + `future.result()` does not work from a worker thread, nothing else in the plan works.

```python
# RED assertion that fails:
from rlm_adk.repl.thread_bridge import make_sync_llm_query
# ImportError: No module named 'rlm_adk.repl.thread_bridge'
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestMakeSyncLlmQuery::test_dispatches_from_worker_thread -x -q`

#### GREEN: Minimum implementation to pass

- **File to create**: `rlm_adk/repl/thread_bridge.py`
- **What changes**: Implement `make_sync_llm_query()` with the `asyncio.run_coroutine_threadsafe()` + `future.result(timeout)` pattern. Include the module docstring documenting the `ContextVar` visibility boundary (reviewer refinement #5).
- **What NOT to do yet**: `make_sync_llm_query_batched`, `execute_code_threaded`, REPLTool changes, orchestrator wiring.

---

### Cycle 2: `make_sync_llm_query` -- timeout and error propagation

**Plan B reference:** Step 1A (timeout/error paths)

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_thread_bridge.py`
- **Test class/method**:
  - `TestMakeSyncLlmQuery::test_timeout_raises`
  - `TestMakeSyncLlmQuery::test_error_propagation`
  - `TestMakeSyncLlmQuery::test_thread_depth_limit`
- **What the tests assert**:
  - When the async dispatch takes longer than `timeout`, the sync wrapper raises a `TimeoutError` (from `concurrent.futures`).
  - When the async dispatch raises an exception, that exception propagates through `future.result()` to the calling worker thread.
  - When thread depth exceeds the configurable limit, a clear `RuntimeError` is raised (reviewer refinement #2).
- **Exact behavior being validated**: Error paths do not silently swallow failures. The worker thread receives actionable exceptions. Thread depth is bounded.
- **Fixtures/mocks**: Fake async coroutines that either `await asyncio.sleep(999)` (for timeout) or `raise ValueError("test error")` (for error propagation). A `_thread_depth` `ContextVar` counter.
- **WHY this test exists**: Timeout guards against hung child dispatches. Error propagation ensures REPL stderr captures child failures. Thread depth limit prevents runaway recursive dispatch from exhausting OS threads (reviewer refinement #2 from workflow agent review).

```python
# RED assertions that fail:
# test_timeout_raises: make_sync_llm_query does not yet implement timeout behavior
# test_thread_depth_limit: no _THREAD_DEPTH ContextVar or max_thread_depth param exists
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestMakeSyncLlmQuery -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/repl/thread_bridge.py`
- **What changes**: Add `max_thread_depth` parameter (default from `RLM_MAX_THREAD_DEPTH` env var, fallback 10). Add module-level `_THREAD_DEPTH: contextvars.ContextVar[int]` counter. In `llm_query()` closure, check depth before dispatch, raise `RuntimeError` if exceeded, increment on entry, decrement in `finally`. Timeout is already in place from Cycle 1 via `future.result(timeout=_timeout)`.
- **What NOT to do yet**: Batched wrapper, LocalREPL changes.

---

### Cycle 3: `make_sync_llm_query_batched` -- batched dispatch

**Plan B reference:** Step 1A (batched)

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_thread_bridge.py`
- **Test class/method**:
  - `TestMakeSyncLlmQueryBatched::test_batched_returns_list`
  - `TestMakeSyncLlmQueryBatched::test_batched_runs_concurrently`
  - `TestMakeSyncLlmQueryBatched::test_batched_timeout`
  - `TestMakeSyncLlmQueryBatched::test_batched_error_propagation`
- **What the tests assert**:
  - Returns a `list` of results matching the input prompts length.
  - All N children run concurrently (not sequentially) by checking elapsed time is closer to max(child_time) than sum(child_time).
  - Timeout and error propagation work as in single dispatch.
- **Fixtures/mocks**: Fake async `llm_query_batched_async` that uses `asyncio.gather` internally (or just returns a list). For concurrency check, each child sleeps 0.1s -- 3 children should complete in ~0.1s not ~0.3s.
- **WHY this test exists**: Batched dispatch is used by `llm_query_batched()` in REPL code. Must verify the sync bridge correctly handles N concurrent children.

```python
# RED assertion:
from rlm_adk.repl.thread_bridge import make_sync_llm_query_batched
# ImportError or AttributeError
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestMakeSyncLlmQueryBatched -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/repl/thread_bridge.py`
- **What changes**: Implement `make_sync_llm_query_batched()` with the same `run_coroutine_threadsafe` + `future.result(timeout)` pattern.
- **What NOT to do yet**: LocalREPL changes, REPLTool changes.

---

### Cycle 4: `LocalREPL._execute_code_threadsafe` -- lock-free execution

**Plan B reference:** Step 1B (`_execute_code_threadsafe`)

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_thread_bridge.py`
- **Test class/method**:
  - `TestExecuteCodeThreadsafe::test_executes_simple_code`
  - `TestExecuteCodeThreadsafe::test_does_not_acquire_exec_lock`
  - `TestExecuteCodeThreadsafe::test_captures_stdout_via_contextvar`
  - `TestExecuteCodeThreadsafe::test_updates_locals_on_success`
  - `TestExecuteCodeThreadsafe::test_sets_last_exec_error_on_failure`
  - `TestExecuteCodeThreadsafe::test_uses_cwd_open_not_chdir`
- **What the tests assert**:
  - Simple code (`x = 42; print(x)`) executes and returns `(stdout, stderr, success)`.
  - The method does NOT acquire `_EXEC_LOCK` (test by holding the lock in another thread and verifying `_execute_code_threadsafe` does not deadlock within 2s).
  - stdout/stderr are captured via `ContextVar` tokens, not by replacing `sys.stdout`/`sys.stderr` globally.
  - `self.locals` is updated with new variables on success.
  - `self._last_exec_error` is set on failure.
  - `open("test.txt", "w")` inside the code resolves to `self.temp_dir/test.txt` (via `_make_cwd_open`), not the process CWD.
- **Fixtures/mocks**: A real `LocalREPL` instance from the `repl` conftest fixture.
- **WHY this test exists**: The lock-free execution path is what prevents the _EXEC_LOCK deadlock under recursive dispatch. This is the most critical correctness property of Phase 1.

```python
# RED assertion:
repl._execute_code_threadsafe("x = 42", None)
# AttributeError: 'LocalREPL' object has no attribute '_execute_code_threadsafe'
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestExecuteCodeThreadsafe -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/repl/local_repl.py`
- **What changes**: Add `_execute_code_threadsafe()` method after `execute_code()`. Uses `_make_cwd_open()` for CWD-safe file access. Uses `ContextVar` tokens for stdout/stderr capture. Does NOT use `_EXEC_LOCK` or `os.chdir()`. Delegates actual code execution to `self._executor.execute_sync()`.
- **What NOT to do yet**: `execute_code_threaded()` (the async wrapper), REPLTool changes.

---

### Cycle 5: `LocalREPL.execute_code_threaded` -- async wrapper with one-shot executor

**Plan B reference:** Step 1B (`execute_code_threaded`)

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_thread_bridge.py`
- **Test class/method**:
  - `TestExecuteCodeThreaded::test_returns_repl_result`
  - `TestExecuteCodeThreaded::test_timeout_produces_error_result`
  - `TestExecuteCodeThreaded::test_sets_trace_execution_mode`
  - `TestExecuteCodeThreaded::test_one_shot_executor_cleanup`
- **What the tests assert**:
  - Returns a `REPLResult` with stdout, stderr, locals, execution_time, llm_calls.
  - When code exceeds `sync_timeout`, returns a `REPLResult` with timeout error in stderr.
  - When a `REPLTrace` is provided, `trace.execution_mode` is set to `"thread_bridge"`.
  - The one-shot `ThreadPoolExecutor` is shut down after each call (verify via `executor._shutdown` or by confirming no leaked threads).
- **Fixtures/mocks**: A real `LocalREPL`. For timeout test, inject a `llm_query` that sleeps for 10s and set `sync_timeout=0.5`.
- **WHY this test exists**: This is the method `REPLTool.run_async()` will call in thread-bridge mode. It must correctly wrap `_execute_code_threadsafe` in `loop.run_in_executor()` with timeout handling.

```python
# RED assertion:
import asyncio
result = asyncio.run(repl.execute_code_threaded("x = 1"))
# AttributeError: 'LocalREPL' object has no attribute 'execute_code_threaded'
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestExecuteCodeThreaded -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/repl/local_repl.py`
- **What changes**: Add `async def execute_code_threaded()` method. Creates one-shot `ThreadPoolExecutor(max_workers=1)`. Uses `asyncio.wait_for(loop.run_in_executor(executor, self._execute_code_threadsafe, code, trace), timeout=self.sync_timeout)`. Handles `asyncio.TimeoutError`. Returns `REPLResult`. Shuts down executor in `finally`.
- **What NOT to do yet**: REPLTool changes, orchestrator wiring.

---

### Cycle 6: `REPLTool` -- thread bridge execution path with `_finalize_telemetry` in `finally`

**Plan B reference:** Step 1C + reviewer refinement #3

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_thread_bridge.py`
- **Test class/method**:
  - `TestREPLToolThreadBridge::test_uses_thread_bridge_for_llm_calls`
  - `TestREPLToolThreadBridge::test_execution_mode_in_result`
  - `TestREPLToolThreadBridge::test_finalize_telemetry_called_on_success`
  - `TestREPLToolThreadBridge::test_finalize_telemetry_called_on_exception`
  - `TestREPLToolThreadBridge::test_finalize_telemetry_called_on_cancel`
- **What the tests assert**:
  - `REPLTool` always uses `repl.execute_code_threaded()` for code execution. There is no fallback path.
  - The result dict contains `"execution_mode"` field with value `"thread_bridge"` or `"sync"` (depending on whether llm_calls were detected).
  - `_finalize_telemetry()` is called in ALL code paths (success, exception, cancellation) -- this validates reviewer refinement #3 that it lives in a `finally` block.
- **Fixtures/mocks**: A `LocalREPL` with dummy `llm_query` wired. A mock `ToolContext` (using the pattern from existing tests: mock `_invocation_context.agent`). A mock `telemetry_finalizer` to track calls.
- **WHY this test exists**: The REPLTool is the integration point between the thread bridge and ADK's tool-calling loop. The `_finalize_telemetry` in `finally` (refinement #3) prevents orphaned telemetry rows when unexpected exceptions escape.

```python
# RED assertion:
# REPLTool.run_async() does not yet call repl.execute_code_threaded()
# (after Phase 0, it only has the sync execute_code path)
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestREPLToolThreadBridge -x -q`

#### GREEN: Minimum implementation to pass

- **Files to modify**:
  - `rlm_adk/tools/repl_tool.py`
- **What changes**:
  - Replace the sync `self.repl.execute_code(exec_code, trace=trace)` call with `await self.repl.execute_code_threaded(exec_code, trace=trace)`. This is the only execution path -- no bifurcation.
  - Move `_finalize_telemetry()` into a `finally` block so it fires on success, exception, AND cancellation (reviewer refinement #3).
  - Add `"execution_mode"` to both `last_repl` dict and result dict.
  - Detect `llm_calls_made` from `result.llm_calls` (the thread bridge populates this when `llm_query()` is called during execution).
- **What NOT to do yet**: Orchestrator wiring (sync bridge closures).

#### REFACTOR

- Remove the duplicated `_finalize_telemetry()` calls from each `except` handler. The `finally` block handles all paths.

---

### Cycle 7: Orchestrator wiring -- sync bridge closures

**Plan B reference:** Step 1D

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_thread_bridge.py`
- **Test class/method**:
  - `TestOrchestratorWiring::test_sync_llm_query_wired_to_repl_globals`
  - `TestOrchestratorWiring::test_sync_llm_query_is_callable`
- **What the tests assert**:
  - After orchestrator wiring, `repl.globals["llm_query"]` is a callable (not missing or raising `RuntimeError`).
  - Calling `repl.globals["llm_query"]("test")` from a worker thread succeeds (with a mock async dispatch).
- **Fixtures/mocks**: This test needs a partial orchestrator setup. Create a `LocalREPL`, a mock `InvocationContext`, a mock `DispatchConfig`, and call the orchestrator's wiring section in isolation. This is tricky since `_run_async_impl` is an async generator; extract the wiring logic into a testable helper or test via a provider-fake fixture.
- **WHY this test exists**: After Phase 0 removed the `sync_llm_query_unsupported` stub, the orchestrator does not wire any sync `llm_query` at all. This cycle replaces it with the real sync bridge. If the wiring is wrong, every `llm_query()` call in REPL code will crash.

```python
# RED assertion: repl.globals["llm_query"] is not set
# because Phase 0C removed the sync_llm_query_unsupported wiring
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestOrchestratorWiring -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/orchestrator.py`
- **What changes**:
  - In the `if self.worker_pool is not None:` block, after `create_dispatch_closures(...)`, add:
    ```python
    from rlm_adk.repl.thread_bridge import (
        make_sync_llm_query,
        make_sync_llm_query_batched,
    )
    _loop = asyncio.get_running_loop()
    repl.set_llm_query_fns(
        make_sync_llm_query(llm_query_async, _loop),
        make_sync_llm_query_batched(llm_query_batched_async, _loop),
    )
    ```
- **What NOT to do yet**: Skill infrastructure, SkillToolset.

---

### Cycle 8: Execution mode in `LAST_REPL_RESULT`

**Plan B reference:** Step 1E + Step 4D

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_thread_bridge.py`
- **Test class/method**:
  - `TestExecutionModeObservability::test_last_repl_result_has_execution_mode`
  - `TestExecutionModeObservability::test_trace_execution_mode_literal`
- **What the tests assert**:
  - After `REPLTool.run_async()` completes, `tool_context.state[depth_key(LAST_REPL_RESULT, depth)]` contains `"execution_mode"` with value `"thread_bridge"`.
  - `REPLTrace.execution_mode` is typed as a `Literal["sync", "thread_bridge"]`.
- **Fixtures/mocks**: Same as Cycle 6 -- mock `ToolContext`, real `LocalREPL`.
- **WHY this test exists**: The `execution_mode` field enables downstream consumers (dashboard, sqlite queries) to distinguish which execution path was used.

```python
# RED assertion:
# REPLTrace.execution_mode is currently typed as str, not Literal
# LAST_REPL_RESULT dict does not yet contain "execution_mode" key
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py::TestExecutionModeObservability -x -q`

#### GREEN: Minimum implementation to pass

- **Files to modify**:
  - `rlm_adk/repl/trace.py`: Change `execution_mode: str = "sync"` to `execution_mode: Literal["sync", "thread_bridge"] = "sync"` (add `Literal` import).
  - `rlm_adk/tools/repl_tool.py`: Add `"execution_mode"` field to the `last_repl` dict, sourced from `trace.execution_mode` if trace exists, else `"thread_bridge"`.
- **What NOT to do yet**: Skill-specific metadata in LAST_REPL_RESULT.

---

### Cycle 9: Regression -- existing tests pass under thread bridge

**Plan B reference:** Step 5D

#### RED: Test(s) to write first

No new test files. This is a validation cycle.

- **What to verify**:
  - `.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py -x -q` -- all new tests pass
  - `.venv/bin/python -m pytest tests_rlm_adk/ -x -q --ignore=tests_rlm_adk/test_skill_arch_e2e.py -m "not provider_fake_extended"` -- existing default suite passes

#### GREEN: Fix any regressions

- If any existing test breaks, fix the implementation (not the test).
- Common expected issues: tests that mock `repl.execute_code()` may need updating if `REPLTool` now routes through `execute_code_threaded()`.

---

## Phase 2: Skill Infrastructure with `llm_query_fn` Parameter Pattern

### Cycle 10: Skill loader -- `discover_skill_dirs()`

**Plan B reference:** Step 2D (discovery portion)

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_loader.py`
- **Test class/method**:
  - `TestDiscoverSkillDirs::test_returns_empty_when_no_skill_dirs`
  - `TestDiscoverSkillDirs::test_skips_obsolete_and_pycache`
  - `TestDiscoverSkillDirs::test_requires_skill_md`
  - `TestDiscoverSkillDirs::test_filters_by_enabled_skills`
- **What the tests assert**:
  - Returns `[]` when no subdirectories have `SKILL.md`.
  - Skips directories named `obsolete`, `__pycache__`, or starting with `.`.
  - Only returns directories that contain a `SKILL.md` file.
  - When `enabled_skills` is provided, only returns matching directories.
- **Fixtures/mocks**: Create temporary directories under a test-specific path using `tmp_path`. Monkeypatch `_SKILLS_DIR` in `loader.py` to point at the temp directory.
- **WHY this test exists**: Discovery is the foundation. If skill directories are not found, nothing else works.

```python
# RED assertion:
from rlm_adk.skills.loader import discover_skill_dirs
# ImportError: No module named 'rlm_adk.skills.loader'
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_loader.py::TestDiscoverSkillDirs -x -q`

#### GREEN: Minimum implementation to pass

- **File to create**: `rlm_adk/skills/loader.py`
- **What changes**: Implement `discover_skill_dirs()` with the `_SKILLS_DIR`, `_SKIP_DIRS` constants, and the directory-scanning logic from Plan B Step 2D.
- **What NOT to do yet**: `load_adk_skills`, `collect_skill_repl_globals`, `_wrap_with_llm_query_injection`.

---

### Cycle 11: `_has_llm_query_fn_param` and `_wrap_with_llm_query_injection`

**Plan B reference:** Step 2D (injection portion)

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_loader.py`
- **Test class/method**:
  - `TestLlmQueryFnInjection::test_has_llm_query_fn_param_detects_param`
  - `TestLlmQueryFnInjection::test_has_llm_query_fn_param_returns_false_without`
  - `TestLlmQueryFnInjection::test_wrapper_injects_from_globals`
  - `TestLlmQueryFnInjection::test_wrapper_respects_explicit_llm_query_fn`
  - `TestLlmQueryFnInjection::test_wrapper_raises_when_no_llm_query_available`
  - `TestLlmQueryFnInjection::test_wrapper_preserves_functools_wraps`
- **What the tests assert**:
  - `_has_llm_query_fn_param(fn)` returns `True` when `fn` has a `llm_query_fn` keyword parameter, `False` otherwise.
  - The wrapper reads `llm_query` from `repl_globals` at call time (lazy binding) and injects it as `llm_query_fn`.
  - If `llm_query_fn` is explicitly provided in `kwargs`, the wrapper does NOT override it.
  - If `llm_query` is not in `repl_globals`, the wrapper raises `RuntimeError` with a helpful message.
  - `functools.wraps` preserves `__name__`, `__doc__`, etc.
- **Fixtures/mocks**: Simple test functions with and without the `llm_query_fn` parameter. A mock `repl_globals` dict.
- **WHY this test exists**: The `llm_query_fn` injection pattern is what makes skill functions testable in isolation. If the wrapper fails, skill functions cannot call `llm_query` from the REPL.

```python
# RED assertion:
from rlm_adk.skills.loader import _has_llm_query_fn_param, _wrap_with_llm_query_injection
# ImportError: cannot import name '_has_llm_query_fn_param'
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_loader.py::TestLlmQueryFnInjection -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/skills/loader.py`
- **What changes**: Implement `_has_llm_query_fn_param()` and `_wrap_with_llm_query_injection()` as specified in Plan B Step 2D.
- **What NOT to do yet**: `collect_skill_repl_globals`, `load_adk_skills`.

---

### Cycle 12: `collect_skill_repl_globals` -- module import and SKILL_EXPORTS

**Plan B reference:** Step 2D (collect portion)

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_loader.py`
- **Test class/method**:
  - `TestCollectSkillReplGlobals::test_returns_empty_dict_when_no_skills`
  - `TestCollectSkillReplGlobals::test_imports_module_and_reads_exports`
  - `TestCollectSkillReplGlobals::test_wraps_functions_with_llm_query_fn`
  - `TestCollectSkillReplGlobals::test_skips_module_without_skill_exports`
  - `TestCollectSkillReplGlobals::test_passes_types_unwrapped`
- **What the tests assert**:
  - When no skill dirs exist, returns `{}`.
  - For a skill dir with a valid module and `SKILL_EXPORTS`, returns a dict with the exported names.
  - Functions with `llm_query_fn` parameter are wrapped; functions without are passed through unwrapped.
  - Types (classes, dataclasses) are passed through unwrapped.
  - Modules without `SKILL_EXPORTS` are skipped with a debug log.
- **Fixtures/mocks**: Create a temporary skill directory structure with a Python module, `SKILL.md`, and `__init__.py` containing `SKILL_EXPORTS`. Monkeypatch `_SKILLS_DIR`.
- **WHY this test exists**: This is the mechanism that populates REPL globals with skill functions. If it fails, the model's `execute_code` calls cannot access skill functions.

```python
# RED assertion:
from rlm_adk.skills.loader import collect_skill_repl_globals
result = collect_skill_repl_globals()
# Function exists but returns {} because no skill dirs have SKILL.md yet
# (or fails on import)
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_loader.py::TestCollectSkillReplGlobals -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/skills/loader.py`
- **What changes**: Implement `collect_skill_repl_globals()` as specified in Plan B Step 2D.
- **What NOT to do yet**: `load_adk_skills`, actual skill directory (recursive-ping), orchestrator wiring.

---

### Cycle 13: Recursive-ping skill directory

**Plan B reference:** Steps 2A, 2B, 2C

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_loader.py`
- **Test class/method**:
  - `TestRecursivePingSkill::test_discover_finds_recursive_ping`
  - `TestRecursivePingSkill::test_collect_exports_run_recursive_ping`
  - `TestRecursivePingSkill::test_run_recursive_ping_terminal_layer`
  - `TestRecursivePingSkill::test_run_recursive_ping_raises_without_llm_query_fn`
  - `TestRecursivePingSkill::test_run_recursive_ping_with_mock_llm_query`
- **What the tests assert**:
  - `discover_skill_dirs()` finds a `recursive-ping` directory.
  - `collect_skill_repl_globals()` returns a dict containing `"run_recursive_ping"` and `"RecursivePingResult"`.
  - At terminal layer (`starting_layer >= max_layer`), `run_recursive_ping` returns without calling `llm_query_fn`.
  - Without `llm_query_fn`, raises `RuntimeError` with a helpful message.
  - With a mock `llm_query_fn`, dispatches and returns a result.
- **Fixtures/mocks**: For the mock test, pass `llm_query_fn=lambda p: "mock_response"`.
- **WHY this test exists**: The recursive-ping skill is the first concrete skill. These tests verify the directory convention, the SKILL_EXPORTS pattern, and the `llm_query_fn` parameter contract.

```python
# RED assertion:
from rlm_adk.skills.recursive_ping import run_recursive_ping
# ModuleNotFoundError: No module named 'rlm_adk.skills.recursive_ping'
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_loader.py::TestRecursivePingSkill -x -q`

#### GREEN: Minimum implementation to pass

- **Files to create**:
  - `rlm_adk/skills/recursive-ping/SKILL.md` -- ADK L1 frontmatter + L2 instructions
  - `rlm_adk/skills/recursive-ping/__init__.py` -- `SKILL_EXPORTS` list
  - `rlm_adk/skills/recursive-ping/ping.py` -- `run_recursive_ping()` + `RecursivePingResult`

  Note: Python import uses `rlm_adk.skills.recursive_ping` (underscore). The directory is `recursive-ping` (kebab-case, matching ADK convention). The loader converts kebab to underscore.

  **Important**: Because Python cannot import from directories with hyphens, the loader must handle the conversion. Alternatively, use underscore directory name `recursive_ping` and set `frontmatter.name = "recursive-ping"` in SKILL.md. This is the safer approach -- use `recursive_ping` as directory name.

- **What changes**: Create the skill directory with the function implementation from Plan B Step 2B.
- **What NOT to do yet**: Orchestrator wiring, SkillToolset.

---

### Cycle 14: Wire skill globals in orchestrator

**Plan B reference:** Step 2E

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_loader.py`
- **Test class/method**:
  - `TestOrchestratorSkillGlobals::test_skill_globals_injected_when_enabled`
  - `TestOrchestratorSkillGlobals::test_skill_globals_not_injected_when_disabled`
  - `TestOrchestratorSkillGlobals::test_repl_skill_globals_injected_state_key`
- **What the tests assert**:
  - When `enabled_skills=("recursive_ping",)` on the orchestrator, `repl.globals` contains `"run_recursive_ping"`.
  - When `enabled_skills=()`, `repl.globals` does NOT contain `"run_recursive_ping"`.
  - The `REPL_SKILL_GLOBALS_INJECTED` state key is emitted in the initial state delta event.
- **Fixtures/mocks**: This is best tested via a provider-fake fixture that exercises the orchestrator with `enabled_skills`. For the unit test, create an `RLMOrchestratorAgent` with `enabled_skills` and inspect the REPL globals after partial initialization.
- **WHY this test exists**: This is the final wiring step that makes skill functions available in the REPL namespace.

```python
# RED assertion: orchestrator does not yet call collect_skill_repl_globals()
# repl.globals will not contain "run_recursive_ping"
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_loader.py::TestOrchestratorSkillGlobals -x -q`

#### GREEN: Minimum implementation to pass

- **Files to modify**:
  - `rlm_adk/orchestrator.py`: Add skill globals injection after `repl.globals["LLMResult"] = LLMResult` (line 259). Add `REPL_SKILL_GLOBALS_INJECTED` to `initial_state`.
  - `rlm_adk/state.py`: Add `REPL_SKILL_GLOBALS_INJECTED = "repl_skill_globals_injected"`. Add `"repl_skill_globals_injected"` to `CURATED_STATE_PREFIXES`. Do NOT add to `DEPTH_SCOPED_KEYS`.
- **What NOT to do yet**: SkillToolset, `reasoning_before_model` fix.

---

## Phase 3: Wire ADK SkillToolset for L1/L2 Discovery

### Cycle 15: SkillToolset creation in orchestrator

**Plan B reference:** Step 3A

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_toolset_integration.py`
- **Test class/method**:
  - `TestSkillToolsetWiring::test_toolset_added_when_skills_enabled`
  - `TestSkillToolsetWiring::test_toolset_not_added_when_no_skills`
  - `TestSkillToolsetWiring::test_toolset_tools_include_load_skill`
- **What the tests assert**:
  - When `enabled_skills=("recursive_ping",)`, the reasoning agent's tools list contains an item that is a `SkillToolset` instance.
  - When `enabled_skills=()`, the tools list contains only `REPLTool` and `SetModelResponseTool`.
  - The `SkillToolset`'s `get_tools()` returns tools including `load_skill`.
- **Fixtures/mocks**: Create an `RLMOrchestratorAgent` and inspect the tools list. Requires `load_adk_skills()` to succeed.
- **WHY this test exists**: SkillToolset wiring is what enables L1/L2 discovery. Without it, the model has no way to discover or load skill instructions.

```python
# RED assertion: orchestrator does not yet create SkillToolset
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_toolset_integration.py::TestSkillToolsetWiring -x -q`

#### GREEN: Minimum implementation to pass

- **Files to modify**:
  - `rlm_adk/orchestrator.py`: In the tools list construction, add `SkillToolset(skills=_adk_skills)` when `self.enabled_skills` is non-empty.
  - `rlm_adk/skills/loader.py`: Implement `load_adk_skills()` using `google.adk.skills.load_skill_from_dir()`.
- **What NOT to do yet**: Fix `reasoning_before_model` (skills will appear wired but silently broken without Phase 3.5).

---

### Cycle 16: CRITICAL -- Fix `reasoning_before_model` system instruction overwrite

**Plan B reference:** Phase 3.5 + reviewer refinement #1

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_toolset_integration.py`
- **Test class/method**:
  - `TestReasoningBeforeModelSkillPreservation::test_toolset_l1_xml_survives_before_model_callback`
  - `TestReasoningBeforeModelSkillPreservation::test_dynamic_instruction_appended_not_overwritten`
  - `TestReasoningBeforeModelSkillPreservation::test_no_toolset_preserves_existing_behavior`
- **What the tests assert**:
  - When `SkillToolset.process_llm_request()` has appended L1 XML to `system_instruction`, and then `reasoning_before_model` fires, the final `system_instruction` contains BOTH the RLM static/dynamic instruction AND the `<available_skills>` XML block.
  - The dynamic instruction is appended (not replacing the entire system instruction).
  - When no toolset is present, the callback behavior is unchanged from the current implementation.
- **Exact behavior being validated**: The callback uses `llm_request.append_instructions([dynamic_instruction])` for the dynamic portion instead of overwriting `system_instruction` entirely (reviewer refinement #1).
- **Fixtures/mocks**: Create a mock `LlmRequest` with `config.system_instruction` already containing static instruction + SkillToolset appended XML. Create a mock `CallbackContext`. Call `reasoning_before_model()` and inspect the resulting `system_instruction`.
- **WHY this test exists**: This is THE critical bug that Plans A and C miss. Without this fix, `SkillToolset.process_llm_request()` appends L1 XML to `system_instruction`, then `reasoning_before_model` destroys it. Skills would NEVER appear in the model's prompt. This test guards against that silent failure.

```python
# RED assertion:
# After reasoning_before_model fires, system_instruction does NOT contain
# "<available_skills>" because the callback overwrites it entirely.
mock_request.config.system_instruction  # Missing the XML that was appended
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_toolset_integration.py::TestReasoningBeforeModelSkillPreservation -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/callbacks/reasoning.py`
- **What changes**: Modify `reasoning_before_model` to use `llm_request.append_instructions([dynamic_instruction])` for the dynamic portion instead of overwriting `system_instruction` entirely. The static instruction is already set by ADK's instructions processor before `_process_agent_tools` runs. The callback only needs to append the dynamic metadata.

  Specifically, replace:
  ```python
  if system_instruction_text:
      llm_request.config = llm_request.config or types.GenerateContentConfig()
      llm_request.config.system_instruction = system_instruction_text
  ```

  With logic that:
  1. Does NOT overwrite `system_instruction` (static + toolset content is already set by ADK)
  2. Only appends the dynamic instruction portion using `append_instructions()`
  3. Preserves anything toolsets appended

- **What NOT to do yet**: Observability, state keys, sqlite_tracing changes.

#### REFACTOR

- Verify that `_extract_adk_dynamic_instruction` still works correctly -- it reads from `contents`, not `system_instruction`, so it should be unaffected.

---

## Phase 4: Observability

### Cycle 17: State key `REPL_SKILL_GLOBALS_INJECTED` + `CURATED_STATE_PREFIXES`

**Plan B reference:** Step 4A

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_toolset_integration.py`
- **Test class/method**:
  - `TestSkillStateKeys::test_repl_skill_globals_injected_key_exists`
  - `TestSkillStateKeys::test_key_in_curated_prefixes`
  - `TestSkillStateKeys::test_key_not_in_depth_scoped`
  - `TestSkillStateKeys::test_should_capture_returns_true`
- **What the tests assert**:
  - `REPL_SKILL_GLOBALS_INJECTED` constant exists in `state.py`.
  - The key matches `CURATED_STATE_PREFIXES` (so `should_capture_state_key` returns `True`).
  - The key is NOT in `DEPTH_SCOPED_KEYS`.
  - `should_capture_state_key("repl_skill_globals_injected")` returns `True`.
- **Fixtures/mocks**: None -- pure import-and-assert.
- **WHY this test exists**: State key hygiene. If the key is not in curated prefixes, it silently fails to appear in `session_state_events`.

```python
# RED assertion:
from rlm_adk.state import REPL_SKILL_GLOBALS_INJECTED
# ImportError: cannot import name 'REPL_SKILL_GLOBALS_INJECTED'
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_toolset_integration.py::TestSkillStateKeys -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/state.py`
- Already done in Cycle 14. This cycle validates the key is correctly curated.

---

### Cycle 18: `LineageEnvelope.decision_mode` expansion

**Plan B reference:** Step 4B

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_toolset_integration.py`
- **Test class/method**:
  - `TestLineageEnvelopeExpansion::test_decision_mode_accepts_skill_tool_values`
- **What the tests assert**:
  - `LineageEnvelope(decision_mode="load_skill", ...)` does not raise a validation error.
  - `LineageEnvelope(decision_mode="list_skills", ...)` does not raise.
  - `LineageEnvelope(decision_mode="load_skill_resource", ...)` does not raise.
  - `LineageEnvelope(decision_mode="run_skill_script", ...)` does not raise.
- **Fixtures/mocks**: None -- pure model construction.
- **WHY this test exists**: Without expanding the Literal type, telemetry rows with skill tool names will fail Pydantic validation.

```python
# RED assertion:
from rlm_adk.types import LineageEnvelope
LineageEnvelope(decision_mode="load_skill", agent_name="test")
# pydantic.ValidationError: decision_mode "load_skill" not in Literal[...]
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_toolset_integration.py::TestLineageEnvelopeExpansion -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/types.py`
- **What changes**: Expand `decision_mode` Literal to include `"load_skill"`, `"load_skill_resource"`, `"list_skills"`, `"run_skill_script"`.

---

### Cycle 19: `SqliteTracingPlugin` skill tool branches in `after_tool_callback`

**Plan B reference:** Step 4C

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_toolset_integration.py`
- **Test class/method**:
  - `TestSqliteSkillTelemetry::test_load_skill_populates_decision_mode`
  - `TestSqliteSkillTelemetry::test_load_skill_populates_skill_name_loaded`
  - `TestSqliteSkillTelemetry::test_list_skills_populates_decision_mode`
- **What the tests assert**:
  - When `after_tool_callback` fires for a tool named `"load_skill"`, the telemetry row has `decision_mode = "load_skill"` and `skill_name_loaded = <the skill name>`.
  - When `after_tool_callback` fires for `"list_skills"`, `decision_mode = "list_skills"`.
- **Fixtures/mocks**: This requires creating a mock `after_tool_callback` invocation with the right parameters. Use the plugin's `after_tool_callback` method directly with mock contexts. Alternatively, defer to the e2e test in Cycle 22 and make this a unit test of the specific `elif` branch.
- **WHY this test exists**: The `skill_name_loaded` and `skill_instructions_len` columns in telemetry are currently always NULL. This cycle populates them. Also documents that `_adk_activated_skill_*` keys are intentionally NOT captured in `session_state_events` (reviewer refinement #4).

```python
# RED assertion:
# after_tool_callback for tool_name="load_skill" does not set decision_mode
# because the elif branch does not exist yet
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_toolset_integration.py::TestSqliteSkillTelemetry -x -q`

#### GREEN: Minimum implementation to pass

- **File to modify**: `rlm_adk/plugins/sqlite_tracing.py`
- **What changes**: Add `elif` branches in `after_tool_callback` for `load_skill`, `load_skill_resource`, `list_skills`, `run_skill_script`. Populate `decision_mode`, `skill_name_loaded`, `skill_instructions_len`.
- Add code comment documenting that `_adk_activated_skill_*` keys are intentionally NOT added to `CURATED_STATE_PREFIXES` -- skill activation tracking flows through the telemetry table's `skill_name_loaded` column (reviewer refinement #4).

---

### Cycle 20: Instruction disambiguation in static prompt + child split gating

**Plan B reference:** Steps 4E, 4F, 4G

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_toolset_integration.py`
- **Test class/method**:
  - `TestInstructionDisambiguation::test_static_instruction_mentions_skill_tools`
  - `TestChildSkillPropagation::test_children_get_repl_globals_unconditionally`
  - `TestChildSkillPropagation::test_children_do_not_get_skilltoolset`
- **What the tests assert**:
  - `RLM_STATIC_INSTRUCTION` contains text about `list_skills`, `load_skill`, and `run_skill_script` distinguishing them from `execute_code`.
  - Child orchestrators (created via `create_child_orchestrator`) have skill functions in their REPL globals (unconditional).
  - Child orchestrators do NOT have `SkillToolset` in their tools list (gated by `enabled_skills` being empty for children).
- **Fixtures/mocks**: Import `RLM_STATIC_INSTRUCTION` and assert substring. Create a child orchestrator with the existing test infrastructure.
- **WHY this test exists**: Without instruction disambiguation, the model might confuse `run_skill_script` with `execute_code`. Without split gating, children either lack skill functions or waste tokens on discovery tools.

```python
# RED assertion:
from rlm_adk.utils.prompts import RLM_STATIC_INSTRUCTION
assert "list_skills" in RLM_STATIC_INSTRUCTION  # Fails
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_toolset_integration.py::TestInstructionDisambiguation -x -q`

#### GREEN: Minimum implementation to pass

- **Files to modify**:
  - `rlm_adk/utils/prompts.py`: Add skill tool disambiguation text to `RLM_STATIC_INSTRUCTION`.
  - `rlm_adk/orchestrator.py`: Call `collect_skill_repl_globals()` unconditionally for ALL orchestrators (not just those with `enabled_skills`). Only create `SkillToolset` when `self.enabled_skills` is non-empty.
  - `rlm_adk/orchestrator.py`: Add `# NOTE: SkillToolset.additional_tools intentionally not used` comment.
- **What NOT to do yet**: E2e provider-fake tests.

---

## Phase 5: Provider-Fake E2E Tests

**Implementation status**: The architecture introspection E2E test suite was previously implemented
via the consolidated plan (`e2e_test_consolidated_plan.md`) using source-expansion delivery. That test (`test_skill_arch_e2e.py`) is removed in Phase 0B because the source-expansion mechanism is deleted. The following files remain as reusable infrastructure:
- `tests_rlm_adk/provider_fake/instrumented_runner.py` -- InstrumentationPlugin + run_fixture_contract_instrumented()
- `tests_rlm_adk/provider_fake/stdout_parser.py` -- ParsedLog + parse_stdout() tagged line parser
- `tests_rlm_adk/provider_fake/expected_lineage.py` -- ExpectedLineage + assertion groups + run_all_assertions()

Cycles 21-26 use the **module-import delivery** mechanism -- `collect_skill_repl_globals()` loads `run_recursive_ping` as compiled bytecode via the skill loader, with `llm_query_fn` parameter auto-injected. The bare `llm_query()` call inside the skill function works because it is a real sync callable created by `make_sync_llm_query()` via the thread bridge.

### Cycle 21: Provider-fake fixture for thread bridge skill execution

**Plan B reference:** Step 5C + companion spec `Thread_bridge_plan_B_e2e_test_design_rec.md`

**Companion implementation (source-expansion delivery)**: `test_skill_arch_e2e.py` + `skill_arch_test.json` (implemented via `e2e_test_consolidated_plan.md`) already validates the full thread-bridge execution pipeline using source-expansion as the delivery mechanism. This cycle's `skill_thread_bridge.json` tests the **module-import delivery** path — the skill function is opaque bytecode loaded by `collect_skill_repl_globals()`, not inlined source. Both use the thread bridge for `llm_query()` execution.

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_thread_bridge_e2e.py`
- **Fixture file**: `tests_rlm_adk/fixtures/provider_fake/skill_thread_bridge.json`
- **Test class/method**:
  - `TestSkillThreadBridgeContract::test_contract_passes`
  - `TestSkillThreadBridgeContract::test_final_answer_contains_expected_text`
  - `TestSkillThreadBridgeContract::test_events_emitted`
- **What the tests assert**:
  - The fixture contract passes (correct number of model calls, no crashes).
  - The final answer contains the expected skill result text.
  - Events were emitted during the run.
- **Exact behavior being validated**: The full pipeline: model calls `execute_code` with skill function code -> skill function calls `llm_query()` via thread bridge -> child orchestrator dispatches -> child returns -> parent REPL continues -> model calls `set_model_response`.
- **Fixtures/mocks**: `FakeGeminiServer` + `ScenarioRouter` serving the scripted responses from the fixture JSON. Real `SqliteTracingPlugin`, `ObservabilityPlugin`, `REPLTracingPlugin`. Real `FileArtifactService` and `SqliteSessionService`. Uses `run_fixture_contract_with_plugins()`.
- **WHY this test exists**: This is the previously impossible test. A module-imported function calling `llm_query()` through the thread bridge. If this passes, the core mission of Plan B is achieved.

```python
# RED assertion:
# Fixture file does not exist yet:
# FileNotFoundError: tests_rlm_adk/fixtures/provider_fake/skill_thread_bridge.json
# Or: the run crashes because llm_query raises RuntimeError inside opaque bytecode
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py::TestSkillThreadBridgeContract -x -q`

#### GREEN: Minimum implementation to pass

- **Files to create**:
  - `tests_rlm_adk/fixtures/provider_fake/skill_thread_bridge.json` -- the provider-fake fixture from the companion spec. Scripts 3 responses: reasoning `execute_code`, worker `set_model_response`, reasoning `set_model_response`.
  - `tests_rlm_adk/test_skill_thread_bridge_e2e.py` -- test file with helper `_run()` and contract test class.
- **What changes**: The fixture exercises the real pipeline. All prior cycles must be implemented for this to pass.
- **What NOT to do yet**: State/event plane tests, telemetry plane tests, trace plane tests (those are Cycles 22-24).

**NOTE on fixture design**: The fixture must use the thread bridge path. The skill function body is opaque bytecode -- the thread bridge is the ONLY execution path (no AST rewriter fallback). If the thread bridge is not working, the `llm_query()` call inside the skill function raises `RuntimeError`. This is the real test -- not reward-hacked.

---

### Cycle 22: E2E state/event plane verification

**Partial coverage**: `test_skill_arch_e2e.py::TestSqliteTelemetry` already verifies `traces.status == "completed"` and `repl_llm_calls >= 1` using source-expansion delivery (thread-bridge execution). This cycle adds state/event assertions specific to the **module-import delivery** path.

**Plan B reference:** companion spec -- `TestSkillThreadBridgeStateEvents`

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_thread_bridge_e2e.py`
- **Test class/method**:
  - `TestSkillThreadBridgeStateEvents::test_repl_submitted_code_events`
  - `TestSkillThreadBridgeStateEvents::test_last_repl_result_events`
  - `TestSkillThreadBridgeStateEvents::test_iteration_count_events`
  - `TestSkillThreadBridgeStateEvents::test_child_state_events_captured`
- **What the tests assert**: Each test queries the `session_state_events` table in the SQLite traces database and verifies specific rows exist with correct values. See companion spec for exact SQL queries.
- **Fixtures/mocks**: Same `_run()` helper as Cycle 21.
- **WHY these tests exist**: They verify the three-plane architecture integrity -- the state/event plane must capture REPL results and child state events through the thread bridge.

```python
# RED: Tests will fail if session_state_events rows are missing
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py::TestSkillThreadBridgeStateEvents -x -q`

#### GREEN: Already passing

- If all prior cycles are implemented correctly, these tests should pass without additional changes. If any fail, investigate the specific data plane gap.

---

### Cycle 23: E2E telemetry plane verification

**Partial coverage**: `test_skill_arch_e2e.py::TestSqliteTelemetry::test_traces_completed` covers the traces row using source-expansion delivery (thread-bridge execution). This cycle adds telemetry assertions specific to the **module-import delivery** path (depth=0/1 rows, skill_name_loaded column).

**Plan B reference:** companion spec -- `TestSkillThreadBridgeTelemetry`

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_thread_bridge_e2e.py`
- **Test class/method**:
  - `TestSkillThreadBridgeTelemetry::test_traces_row_completed`
  - `TestSkillThreadBridgeTelemetry::test_model_call_telemetry_rows`
  - `TestSkillThreadBridgeTelemetry::test_execute_code_tool_telemetry`
  - `TestSkillThreadBridgeTelemetry::test_set_model_response_tool_telemetry`
  - `TestSkillThreadBridgeTelemetry::test_tool_invocation_summary_in_traces`
  - `TestSkillThreadBridgeTelemetry::test_skill_instruction_column_populated`
- **What the tests assert**: Each test queries the `telemetry` and `traces` tables. Verifies model_call rows, tool_call rows with correct `decision_mode`, `repl_llm_calls >= 1` for the execute_code row, and traces.status == "completed".
- **Fixtures/mocks**: Same `_run()` helper.
- **WHY these tests exist**: Telemetry plane integrity. The thread bridge changes the execution path inside `REPLTool.run_async()`, so telemetry capture could break. These tests verify it does not.

```python
# RED: telemetry rows may be incomplete if _finalize_telemetry flow is broken
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py::TestSkillThreadBridgeTelemetry -x -q`

#### GREEN: Already passing

- If prior cycles are correct (especially Cycle 6's `_finalize_telemetry` in `finally`), these pass.

---

### Cycle 24: E2E trace plane verification

**Partial coverage**: `test_skill_arch_e2e.py::TestArchitectureLineage` verifies state key lineage and execution_mode via the assertion framework using source-expansion delivery (thread-bridge execution). This cycle validates the same assertions via the **module-import delivery** path.

**Plan B reference:** companion spec -- `TestSkillThreadBridgeTracePlane`

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_thread_bridge_e2e.py`
- **Test class/method**:
  - `TestSkillThreadBridgeTracePlane::test_repl_submitted_code_in_state`
  - `TestSkillThreadBridgeTracePlane::test_last_repl_result_has_llm_calls`
  - `TestSkillThreadBridgeTracePlane::test_execution_mode_in_last_repl_result`
- **What the tests assert**: Each test inspects `result.final_state` for the expected state keys and values. The execution_mode test verifies `LAST_REPL_RESULT["execution_mode"] == "thread_bridge"`.
- **Fixtures/mocks**: Same `_run()` helper.
- **WHY these tests exist**: Verify REPL trace data flows correctly through the thread bridge path, including the new `execution_mode` field.

```python
# RED: execution_mode field not yet in LAST_REPL_RESULT (if Cycle 8 GREEN is incomplete)
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py::TestSkillThreadBridgeTracePlane -x -q`

#### GREEN: Already passing

- Depends on Cycle 8 (execution_mode in LAST_REPL_RESULT).

---

## Phase 6: SkillToolset E2E Integration

### Cycle 25: SkillToolset discovery in provider-fake fixture

**Plan B reference:** Phase 3 (SkillToolset wiring) + Phase 3.5 (reasoning_before_model fix)

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_toolset_integration.py`
- **Test class/method**:
  - `TestSkillToolsetE2E::test_l1_xml_in_system_instruction`
  - `TestSkillToolsetE2E::test_load_skill_returns_l2_instructions`
- **What the tests assert**:
  - After the orchestrator runs with `enabled_skills`, the system instruction sent to the model contains `<available_skills>` XML with the recursive-ping skill listed.
  - When the model calls `load_skill(name="recursive-ping")`, the response contains the L2 instructions from `SKILL.md`.
- **Fixtures/mocks**: A provider-fake fixture that scripts: (1) model calls `load_skill`, (2) model calls `execute_code`, (3) model calls `set_model_response`. Inspect the captured request body for system instruction content.
- **WHY this test exists**: This validates the complete L1/L2 discovery flow. Combined with the Phase 3.5 fix, it proves that skills are visible to the model.

```python
# RED: Before Phase 3.5 fix, system_instruction does not contain <available_skills>
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_toolset_integration.py::TestSkillToolsetE2E -x -q`

#### GREEN: Minimum implementation to pass

- **Files to create**:
  - `tests_rlm_adk/fixtures/provider_fake/skill_toolset_discovery.json` -- fixture that scripts `load_skill` + `execute_code` + `set_model_response`.
- All implementation should already be in place from prior cycles. If this test fails, the `reasoning_before_model` fix (Cycle 16) is incomplete.

---

### Cycle 26: Recursive-ping skill end-to-end through thread bridge

**Plan B reference:** Step 5C (the capstone test)

#### RED: Test(s) to write first

- **Test file**: `tests_rlm_adk/test_skill_thread_bridge_e2e.py`
- **Test class/method**:
  - `TestRecursivePingE2E::test_skill_function_calls_llm_query_via_thread_bridge`
  - `TestRecursivePingE2E::test_child_dispatch_at_depth_1`
  - `TestRecursivePingE2E::test_result_propagates_to_parent_repl`
- **What the tests assert**:
  - The recursive-ping skill function is called from `execute_code`, internally calls `llm_query()` via the thread bridge, child dispatches at depth+1, child returns, parent REPL receives the result.
  - The telemetry table has rows for both depth=0 (reasoning) and depth=1 (child).
  - The final answer contains the ping result payload.
- **Fixtures/mocks**: This may reuse the `skill_thread_bridge.json` fixture from Cycle 21, or create a new fixture that explicitly exercises `run_recursive_ping` with `llm_query_fn=llm_query` in the REPL code (relying on the auto-injection wrapper, not a source expansion path).
- **WHY this test exists**: This is the **capstone test** -- the previously impossible scenario that motivated the entire thread bridge. A module-imported Python function calls `llm_query()` as a real sync callable, not through AST rewriting.

```python
# RED: If thread bridge is not wired, llm_query() raises RuntimeError inside
# the opaque bytecode of run_recursive_ping
```

- **How to run**: `.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py::TestRecursivePingE2E -x -q`

#### GREEN: Already passing

- All prior cycles provide the implementation. If this fails, trace back through the chain.

---

## Phase 7: Final Regression + Documentation

### Cycle 27: Full regression

**No new tests.** Verification cycle.

- **Thread bridge (the only mode)**:
  ```bash
  .venv/bin/python -m pytest tests_rlm_adk/ -x -q -m "not provider_fake_extended"
  ```

- **Thread bridge + new tests**:
  ```bash
  .venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py tests_rlm_adk/test_skill_loader.py tests_rlm_adk/test_skill_toolset_integration.py tests_rlm_adk/test_skill_thread_bridge_e2e.py -x -q
  ```

---

## Summary: Cycle-to-Phase Mapping

| Cycle | Phase | Description | Test File |
|-------|-------|-------------|-----------|
| 0A-0E | 0 | Legacy cleanup: AST rewriter, skill registry, fallback infrastructure | existing suite (validation) |
| 1 | 1 | `make_sync_llm_query` basic | `test_thread_bridge.py` |
| 2 | 1 | Timeout + error + thread depth limit | `test_thread_bridge.py` |
| 3 | 1 | `make_sync_llm_query_batched` | `test_thread_bridge.py` |
| 4 | 1 | `_execute_code_threadsafe` lock-free | `test_thread_bridge.py` |
| 5 | 1 | `execute_code_threaded` async wrapper | `test_thread_bridge.py` |
| 6 | 1 | `REPLTool` thread bridge + `_finalize_telemetry` in `finally` | `test_thread_bridge.py` |
| 7 | 1 | Orchestrator sync bridge wiring | `test_thread_bridge.py` |
| 8 | 1 | `execution_mode` in LAST_REPL_RESULT | `test_thread_bridge.py` |
| 9 | 1 | Full regression | existing suite |
| 10 | 2 | `discover_skill_dirs` | `test_skill_loader.py` |
| 11 | 2 | `llm_query_fn` injection wrappers | `test_skill_loader.py` |
| 12 | 2 | `collect_skill_repl_globals` | `test_skill_loader.py` |
| 13 | 2 | Recursive-ping skill directory | `test_skill_loader.py` |
| 14 | 2 | Wire skill globals in orchestrator | `test_skill_loader.py` |
| 15 | 3 | SkillToolset creation | `test_skill_toolset_integration.py` |
| 16 | 3.5 | CRITICAL: `reasoning_before_model` fix | `test_skill_toolset_integration.py` |
| 17 | 4 | `REPL_SKILL_GLOBALS_INJECTED` state key | `test_skill_toolset_integration.py` |
| 18 | 4 | `LineageEnvelope.decision_mode` expansion | `test_skill_toolset_integration.py` |
| 19 | 4 | `sqlite_tracing` skill tool branches | `test_skill_toolset_integration.py` |
| 20 | 4 | Instruction disambiguation + child split gating | `test_skill_toolset_integration.py` |
| --  | 5 | Architecture introspection e2e — source-expansion delivery, thread-bridge execution (IMPLEMENTED) | `test_skill_arch_e2e.py` + 123 unit tests |
| 21 | 5 | Provider-fake e2e contract | `test_skill_thread_bridge_e2e.py` |
| 22 | 5 | E2E state/event plane | `test_skill_thread_bridge_e2e.py` |
| 23 | 5 | E2E telemetry plane | `test_skill_thread_bridge_e2e.py` |
| 24 | 5 | E2E trace plane | `test_skill_thread_bridge_e2e.py` |
| 25 | 6 | SkillToolset L1/L2 e2e | `test_skill_toolset_integration.py` |
| 26 | 6 | Recursive-ping capstone | `test_skill_thread_bridge_e2e.py` |
| 27 | 7 | Full regression | existing suite |

---

## Critical Implementation Constraints

1. **Tests MUST NOT be reward-hacked.** The e2e fixtures exercise the real pipeline. The skill function body is opaque bytecode. The thread bridge is the only execution path -- there is no AST rewriter fallback. If the thread bridge is not working, the test fails with `RuntimeError`.

2. **`_finalize_telemetry()` MUST be in a `finally` block** (reviewer refinement #3). This is explicitly tested in Cycle 6.

3. **Thread depth limit** (reviewer refinement #2) is implemented and tested in Cycle 2. Default configurable via `RLM_MAX_THREAD_DEPTH` env var.

4. **`ContextVar` visibility boundary** (reviewer refinement #5) is documented in the `thread_bridge.py` module docstring in Cycle 1.

5. **`reasoning_before_model` uses `append_instructions`** (reviewer refinement #1) instead of overwriting `system_instruction`. Tested in Cycle 16.

6. **`_adk_activated_skill_*` capture decision** (reviewer refinement #4): documented as a code comment in Cycle 19. Skill activation tracking flows through telemetry table's `skill_name_loaded` column, not `session_state_events`.

7. **Each cycle is independently committable.** Tests fail first (RED), then the minimum implementation makes them pass (GREEN). No forward references.

8. **Provider-fake tests use existing infrastructure.** `FakeGeminiServer` + `ScenarioRouter` + `run_fixture_contract_with_plugins()`. No new test infrastructure.

9. **`_EXEC_LOCK` is NEVER used in the thread bridge path.** Tested explicitly in Cycle 4 (`test_does_not_acquire_exec_lock`).

10. **One-shot `ThreadPoolExecutor`** per `execute_code_threaded` call prevents default-pool exhaustion under recursive dispatch. Tested in Cycle 5.

11. **Phase 0 removes all legacy code BEFORE any thread-bridge work.** The AST rewriter (`ast_rewriter.py`), source expansion registry (`skill_registry.py`), `execute_code_async()`, `set_async_llm_query_fns()`, and `sync_llm_query_unsupported` are all deleted in Phase 0. No fallback path exists. The thread bridge is the only mechanism for `llm_query()` dispatch from REPL code.
