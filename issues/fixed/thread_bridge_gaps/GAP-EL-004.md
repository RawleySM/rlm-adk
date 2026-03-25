# GAP-EL-004: Executor shutdown ordering allows resource leak on timeout with in-flight child dispatches

**Severity**: HIGH
**Category**: event-loop
**Files**: `rlm_adk/repl/local_repl.py`, `rlm_adk/dispatch.py`

## Problem

When `execute_code_threaded` times out (line 461), `executor.shutdown(wait=False)` is called at line 469. But the worker thread continues running. If the worker thread is in the middle of a `llm_query()` call, the sequence is:

1. Worker thread called `run_coroutine_threadsafe(llm_query_async(...), loop)` and is blocked on `future.result(timeout=300)`.
2. `execute_code_threaded` timed out (e.g., at 30 seconds).
3. `executor.shutdown(wait=False)` returns immediately.
4. `execute_code_threaded` returns a timeout `REPLResult`.
5. REPLTool returns this result to the reasoning agent.
6. The reasoning agent may call `set_model_response` or another `execute_code`.

Meanwhile:

7. The child orchestrator coroutine (`llm_query_async`) is still running on the event loop.
8. The child orchestrator creates its OWN `execute_code_threaded` with its OWN executor.
9. The child orchestrator makes API calls, consuming quota.
10. When the child finishes, `future.result()` returns to the (now-orphaned) worker thread.
11. The worker thread continues executing the rest of the REPL code (potentially more `llm_query()` calls).

This creates a cascade of orphaned child orchestrators, each consuming API quota and event loop resources, with no mechanism to:
- Cancel them
- Collect their results
- Account for their resource usage

The `_child_semaphore` in `dispatch.py` is per-parent-orchestrator, so orphaned children do not count against the semaphore of subsequent dispatches.

## Evidence

`local_repl.py` lines 453-469:
```python
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
try:
    stdout, stderr, _success = await asyncio.wait_for(
        loop.run_in_executor(executor, self._execute_code_threadsafe, code, trace),
        timeout=self.sync_timeout,
    )
except TimeoutError:
    ...
finally:
    executor.shutdown(wait=False)  # Does not cancel in-flight coroutines
```

`thread_bridge.py` lines 71-74:
```python
future = asyncio.run_coroutine_threadsafe(
    llm_query_async(prompt, **kwargs), loop
)
return future.result(timeout=_timeout)  # 300s default -- much longer than sync_timeout
```

Note the timeout mismatch: `sync_timeout` defaults to 30 seconds (`RLM_REPL_SYNC_TIMEOUT`), but `_timeout` in the thread bridge defaults to 300 seconds. A code block that calls `llm_query()` could be timed out by `execute_code_threaded` after 30s while the `llm_query` future has 270 seconds remaining.

## Suggested Fix

1. **Cancel the `concurrent.futures.Future` on timeout**: After `wait_for` raises `TimeoutError`, call `future.cancel()` on the `run_coroutine_threadsafe` future stored in the thread bridge. This requires the thread bridge to expose a handle to the most recent future.

2. **Propagate a cancellation token**: Create a `threading.Event` that is shared between `execute_code_threaded` and the `llm_query` closure. On timeout, set the event. The `llm_query` closure checks it before submitting work and calls `future.cancel()` on any outstanding future.

3. **Align timeouts**: Set the thread bridge timeout to be <= the sync_timeout, so `future.result(timeout)` in the worker thread times out before or at the same time as `asyncio.wait_for`.

4. **Track and cancel orphaned child coroutines**: Maintain a set of in-flight `asyncio.Task` objects created by `run_coroutine_threadsafe`. On timeout, cancel all of them.
