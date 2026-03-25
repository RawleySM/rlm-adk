# GAP-EL-006: `llm_query_batched` in thread bridge lacks depth tracking

**Severity**: LOW
**Category**: event-loop
**Files**: `rlm_adk/repl/thread_bridge.py`

## Problem

`make_sync_llm_query` (lines 32-78) includes `_THREAD_DEPTH` tracking: it increments the depth counter before dispatch and decrements it after. This prevents runaway recursive calls within a single worker thread.

`make_sync_llm_query_batched` (lines 81-111) does NOT include any `_THREAD_DEPTH` tracking. A single code block could call `llm_query_batched()` with arbitrarily many prompts, and if any of those child orchestrators' REPL code calls `llm_query_batched()` recursively (within the same thread via skill function chaining), the depth limit is never checked.

While this is partially mitigated by `max_depth` in `dispatch.py`, the lack of depth tracking for batched calls is an inconsistency that could allow bursts of concurrent child dispatches beyond the intended recursion budget.

## Evidence

`thread_bridge.py` lines 63-77 -- `llm_query` tracks depth:
```python
def llm_query(prompt: str, **kwargs: Any) -> Any:
    depth = _THREAD_DEPTH.get(0)
    if depth >= _max_depth:
        raise RuntimeError(
            f"Thread depth limit exceeded: {depth}/{_max_depth}"
        )
    _THREAD_DEPTH.set(depth + 1)
    try:
        future = asyncio.run_coroutine_threadsafe(...)
        return future.result(timeout=_timeout)
    finally:
        _THREAD_DEPTH.set(depth)
```

`thread_bridge.py` lines 105-109 -- `llm_query_batched` does NOT track depth:
```python
def llm_query_batched(prompts: list[str], **kwargs: Any) -> list[Any]:
    future = asyncio.run_coroutine_threadsafe(
        llm_query_batched_async(prompts, **kwargs), loop
    )
    return future.result(timeout=_timeout)
```

## Suggested Fix

Add `_THREAD_DEPTH` tracking to `llm_query_batched` with the same increment/decrement/check pattern as `llm_query`. This is a simple copy of the depth-tracking logic:

```python
def llm_query_batched(prompts: list[str], **kwargs: Any) -> list[Any]:
    depth = _THREAD_DEPTH.get(0)
    if depth >= _max_depth:
        raise RuntimeError(
            f"Thread depth limit exceeded: {depth}/{_max_depth}"
        )
    _THREAD_DEPTH.set(depth + 1)
    try:
        future = asyncio.run_coroutine_threadsafe(
            llm_query_batched_async(prompts, **kwargs), loop
        )
        return future.result(timeout=_timeout)
    finally:
        _THREAD_DEPTH.set(depth)
```
