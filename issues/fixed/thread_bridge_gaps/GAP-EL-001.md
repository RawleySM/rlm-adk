# GAP-EL-001: Dangling worker thread after timeout calls `run_coroutine_threadsafe` on a potentially closed loop

**Severity**: HIGH
**Category**: event-loop
**Files**: `rlm_adk/repl/local_repl.py`, `rlm_adk/repl/thread_bridge.py`

## Problem

When `execute_code_threaded` times out via `asyncio.wait_for`, the worker thread is NOT terminated. The `executor.shutdown(wait=False)` at line 469 of `local_repl.py` returns immediately without killing the thread. The dangling worker thread continues executing REPL code, and if that code calls `llm_query()`, the thread bridge calls `asyncio.run_coroutine_threadsafe(coro, loop)`.

Two scenarios arise:

1. **Loop still running (normal case)**: The scheduled coroutine executes successfully on the event loop, but the parent `execute_code_threaded` has already returned a timeout `REPLResult`. The child orchestrator runs to completion silently, consuming resources (API calls, compute) with no way to report results back. The `future.result(timeout=300)` in `thread_bridge.py:74` eventually returns, but nobody reads it.

2. **Loop closed (Runner finished)**: If the ADK Runner finishes its `run_async` generator (e.g., because `set_model_response` was called by the reasoning agent while the worker was blocked), the event loop closes. The dangling thread then gets `RuntimeError: Event loop is closed` from `run_coroutine_threadsafe`. This exception propagates unhandled in the worker thread.

Both scenarios waste resources and can produce confusing error logs.

## Evidence

`local_repl.py` lines 453-469:
```python
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
try:
    stdout, stderr, _success = await asyncio.wait_for(
        loop.run_in_executor(
            executor, self._execute_code_threadsafe, code, trace,
        ),
        timeout=self.sync_timeout,
    )
except TimeoutError:
    stdout = ""
    stderr = (...)
    self._last_exec_error = stderr.strip()
finally:
    executor.shutdown(wait=False)  # Thread keeps running!
```

`thread_bridge.py` lines 71-74:
```python
future = asyncio.run_coroutine_threadsafe(
    llm_query_async(prompt, **kwargs), loop
)
return future.result(timeout=_timeout)  # Blocks in dangling thread
```

Empirical verification: after `asyncio.run()` completes and the loop is closed, a dangling thread calling `run_coroutine_threadsafe` gets `RuntimeError: Event loop is closed`.

## Suggested Fix

1. Add a `threading.Event` cancellation flag to the REPL or thread bridge context. Set it when `wait_for` times out. The `llm_query` closure should check this flag before calling `run_coroutine_threadsafe` and raise a clean `TimeoutError("Parent execution timed out")` instead.

2. Alternatively, use `cancel_futures=True` (Python 3.9+) in `executor.shutdown()` to cancel pending futures. Note: this still does not interrupt a running thread, but prevents new submissions.

3. For the "loop closed" case, wrap `run_coroutine_threadsafe` in `thread_bridge.py` with a try/except that catches `RuntimeError` and converts it to an `LLMResult` with `error=True, error_category="EVENT_LOOP_CLOSED"`.
