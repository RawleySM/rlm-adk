# GAP-EL-007: No loop-aliveness check before `run_coroutine_threadsafe`

**Severity**: MEDIUM
**Category**: event-loop
**Files**: `rlm_adk/repl/thread_bridge.py`

## Problem

The `llm_query` and `llm_query_batched` closures call `asyncio.run_coroutine_threadsafe(coro, loop)` without checking whether `loop` is still running. If the loop has been closed (e.g., because the ADK Runner finished and `asyncio.run()` completed), `run_coroutine_threadsafe` raises `RuntimeError: Event loop is closed`.

This `RuntimeError` is indistinguishable from other `RuntimeError` exceptions (e.g., the deliberate "Thread depth limit exceeded" error) and propagates as an unhandled exception through the REPL code, producing a confusing traceback.

The `loop` reference is captured at orchestrator initialization time (`orchestrator.py` line 305: `_loop = asyncio.get_running_loop()`) and stored in the closure. The closure has no way to know if the loop has been closed between capture time and use time.

## Evidence

`thread_bridge.py` lines 71-74:
```python
future = asyncio.run_coroutine_threadsafe(
    llm_query_async(prompt, **kwargs), loop
)
return future.result(timeout=_timeout)
```

No guard for `loop.is_closed()` or `loop.is_running()`.

Empirical verification: after `asyncio.run()` completes and closes the loop, `run_coroutine_threadsafe(coro, loop)` raises `RuntimeError: Event loop is closed`. The coroutine `coro` is never awaited, generating a `RuntimeWarning: coroutine was never awaited`.

## Suggested Fix

Add a loop-aliveness check before calling `run_coroutine_threadsafe`:

```python
def llm_query(prompt: str, **kwargs: Any) -> Any:
    if loop.is_closed():
        raise RuntimeError(
            "Event loop is closed. The parent orchestrator has already finished. "
            "This typically happens when REPL code continues executing after a timeout."
        )
    ...
```

Additionally, wrap `run_coroutine_threadsafe` in a try/except to catch `RuntimeError` and convert it to an `LLMResult` with a clear error message:

```python
try:
    future = asyncio.run_coroutine_threadsafe(
        llm_query_async(prompt, **kwargs), loop
    )
except RuntimeError as e:
    if "closed" in str(e).lower():
        return LLMResult(
            f"[EVENT_LOOP_CLOSED] {e}",
            error=True,
            error_category="EVENT_LOOP_CLOSED",
        )
    raise
```
