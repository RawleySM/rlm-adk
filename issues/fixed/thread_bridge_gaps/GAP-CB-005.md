# GAP-CB-005: Thread bridge `llm_query_batched` lacks depth-limit enforcement

**Severity**: MEDIUM
**Category**: callback-lifecycle
**Files**: `rlm_adk/repl/thread_bridge.py` (lines 81-111)

## Problem

`make_sync_llm_query` enforces a thread depth limit via the `_THREAD_DEPTH` ContextVar (lines 63-76). It increments the depth, checks against the max, and resets it in a `finally` block. This prevents runaway recursive thread creation.

`make_sync_llm_query_batched` does NOT enforce any depth limit (lines 105-109). A batched call from within a thread bridge context can create K concurrent children, each of which may create more batched calls, leading to unbounded recursive thread creation.

## Evidence

`make_sync_llm_query` (lines 63-76):
```python
def llm_query(prompt: str, **kwargs: Any) -> Any:
    depth = _THREAD_DEPTH.get(0)
    if depth >= _max_depth:
        raise RuntimeError(
            f"Thread depth limit exceeded: {depth}/{_max_depth}"
        )
    _THREAD_DEPTH.set(depth + 1)
    try:
        future = asyncio.run_coroutine_threadsafe(
            llm_query_async(prompt, **kwargs), loop
        )
        return future.result(timeout=_timeout)
    finally:
        _THREAD_DEPTH.set(depth)
```

`make_sync_llm_query_batched` (lines 105-109):
```python
def llm_query_batched(prompts: list[str], **kwargs: Any) -> list[Any]:
    future = asyncio.run_coroutine_threadsafe(
        llm_query_batched_async(prompts, **kwargs), loop
    )
    return future.result(timeout=_timeout)
```

No `_THREAD_DEPTH` check or increment.

## Impact

In practice, the depth limit is also enforced at the dispatch level (`dispatch.py` line 281: `if depth + 1 >= max_depth`), which catches recursive depth regardless of whether the call came through `llm_query` or `llm_query_batched`. So the dispatch-level limit provides a safety net.

However, the `_THREAD_DEPTH` ContextVar tracks the thread-bridge-specific depth (how many nested `run_coroutine_threadsafe` calls are stacked), which is different from the logical orchestrator depth. A pathological case could create many threads at the same logical depth but different thread depths. The dispatch-level limit would not catch this.

## Suggested Fix

Add `_THREAD_DEPTH` checking to `make_sync_llm_query_batched`:

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
