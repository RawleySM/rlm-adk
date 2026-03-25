# GAP-EL-003: `CancelledError` type mismatch between `concurrent.futures` and `asyncio`

**Severity**: MEDIUM
**Category**: event-loop
**Files**: `rlm_adk/repl/thread_bridge.py`, `rlm_adk/tools/repl_tool.py`

## Problem

When ADK cancels an invocation (e.g., `end_invocation = True` causes the async generator to close), the coroutine scheduled via `run_coroutine_threadsafe` may be cancelled. When this happens, `future.result()` in the worker thread raises `concurrent.futures.CancelledError`.

This is a DIFFERENT type from `asyncio.CancelledError`:

```
concurrent.futures.CancelledError -> concurrent.futures._base.Error -> Exception -> BaseException
asyncio.CancelledError -> BaseException
```

They share NO common ancestor other than `BaseException`. In particular, `concurrent.futures.CancelledError` IS a subclass of `Exception`, while `asyncio.CancelledError` is NOT.

In `thread_bridge.py`, the `llm_query` closure (line 63-77) has no explicit exception handling for `CancelledError`. If `future.result()` raises `concurrent.futures.CancelledError`, it propagates up through the REPL code, through `_execute_code_threadsafe`, and arrives at `execute_code_threaded` as an exception from `run_in_executor`.

In `repl_tool.py`, line 193 catches `asyncio.CancelledError`:
```python
except asyncio.CancelledError as exc:
```

But the exception from the worker thread is `concurrent.futures.CancelledError`, which is NOT an `asyncio.CancelledError`. It would fall through to the generic `except Exception` handler at line 225 instead, losing the specific cancellation semantics (the `cancelled: True` flag in the LAST_REPL_RESULT).

## Evidence

`thread_bridge.py` lines 63-77 -- no CancelledError handling:
```python
def llm_query(prompt: str, **kwargs: Any) -> Any:
    depth = _THREAD_DEPTH.get(0)
    if depth >= _max_depth:
        raise RuntimeError(...)
    _THREAD_DEPTH.set(depth + 1)
    try:
        future = asyncio.run_coroutine_threadsafe(
            llm_query_async(prompt, **kwargs), loop
        )
        return future.result(timeout=_timeout)
    finally:
        _THREAD_DEPTH.set(depth)
```

`repl_tool.py` lines 193-224 -- catches `asyncio.CancelledError` specifically:
```python
except asyncio.CancelledError as exc:
    # ... sets cancelled=True in LAST_REPL_RESULT
```

Empirical verification: `concurrent.futures.CancelledError` and `asyncio.CancelledError` have NO shared inheritance. `issubclass(concurrent.futures.CancelledError, asyncio.CancelledError)` returns `False`.

## Suggested Fix

In `thread_bridge.py`, catch `concurrent.futures.CancelledError` in the `llm_query` closure and re-raise as a custom exception (e.g., `LLMQueryCancelled`) that extends `Exception`:

```python
try:
    future = asyncio.run_coroutine_threadsafe(...)
    return future.result(timeout=_timeout)
except concurrent.futures.CancelledError:
    raise RuntimeError("llm_query cancelled: parent invocation was terminated")
```

In `repl_tool.py`, either:
- Catch both `asyncio.CancelledError` and `concurrent.futures.CancelledError`, or
- Catch `BaseException` for the cancellation path and check `isinstance` for both types.
