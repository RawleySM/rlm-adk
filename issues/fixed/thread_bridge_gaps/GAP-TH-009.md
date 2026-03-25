# GAP-TH-009: `llm_query_batched` does not enforce `_THREAD_DEPTH` limit

**Severity**: LOW
**Category**: threading
**Files**: `rlm_adk/repl/thread_bridge.py`

## Problem

`make_sync_llm_query` (line 63-78) checks and increments `_THREAD_DEPTH` before dispatching. But `make_sync_llm_query_batched` (lines 105-111) does NOT check or increment `_THREAD_DEPTH`:

```python
def llm_query_batched(prompts: list[str], **kwargs: Any) -> list[Any]:
    future = asyncio.run_coroutine_threadsafe(
        llm_query_batched_async(prompts, **kwargs), loop
    )
    return future.result(timeout=_timeout)
```

If REPL code calls `llm_query_batched(["p1", "p2", "p3"])`, this bypasses the thread depth check entirely. The batched dispatch creates multiple child orchestrators, each of which can recursively call `llm_query_batched` without any depth tracking from the thread bridge side.

As noted in GAP-TH-002, the ContextVar-based depth tracking doesn't propagate across thread boundaries anyway. But within the same thread, a code pattern like:

```python
# In REPL code
result = llm_query_batched(["a"] * 100)
```

Would not trigger the depth limit even if it were working correctly, because `llm_query_batched` doesn't check it at all.

The `dispatch.py` `max_depth` check (line 281) is the actual guard, so this is defense-in-depth only.

## Evidence

```python
# thread_bridge.py lines 63-76 (llm_query -- HAS depth check)
def llm_query(prompt: str, **kwargs: Any) -> Any:
    depth = _THREAD_DEPTH.get(0)
    if depth >= _max_depth:
        raise RuntimeError(...)
    _THREAD_DEPTH.set(depth + 1)
    ...

# thread_bridge.py lines 105-111 (llm_query_batched -- NO depth check)
def llm_query_batched(prompts: list[str], **kwargs: Any) -> list[Any]:
    future = asyncio.run_coroutine_threadsafe(
        llm_query_batched_async(prompts, **kwargs), loop
    )
    return future.result(timeout=_timeout)
```

## Suggested Fix

Add the same depth check to `llm_query_batched`:

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

Note: this is only meaningful if GAP-TH-002 is also fixed (ContextVar propagation).
