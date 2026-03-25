# GAP-TH-002: `_THREAD_DEPTH` ContextVar does not propagate across `run_coroutine_threadsafe` boundary

**Severity**: HIGH
**Category**: threading
**Files**: `rlm_adk/repl/thread_bridge.py`, `rlm_adk/repl/local_repl.py`

## Problem

`_THREAD_DEPTH` is a `contextvars.ContextVar` used to enforce the recursive thread depth limit (default max 10). The depth check works like this:

1. Parent REPL runs in worker thread T1
2. User code calls `llm_query()` in T1 -> `_THREAD_DEPTH` incremented from 0 to 1
3. `run_coroutine_threadsafe(llm_query_async(...), loop)` schedules a coroutine on the event loop
4. The event loop runs the child orchestrator, which calls `execute_code_threaded`
5. `execute_code_threaded` uses `loop.run_in_executor(executor, ...)` to run child code in a NEW worker thread T2
6. In T2, child code calls `llm_query()` -> reads `_THREAD_DEPTH`

The problem: ContextVars are **thread-local** in the threading sense. Thread T2 (created by `ThreadPoolExecutor`) gets a **fresh** ContextVar context with `_THREAD_DEPTH = 0` (the default). It does NOT inherit T1's depth of 1. So the depth counter resets to 0 at each thread boundary.

Furthermore, `run_coroutine_threadsafe` creates a new `Task` on the event loop. In Python 3.12+, new tasks copy the current context of the **submitting thread** via `contextvars.copy_context()`. But the task runs on the event loop thread, and the ContextVar set in the worker thread (T1) is captured into the task's context. However, this task then calls `execute_code_threaded` which calls `loop.run_in_executor()`, which creates yet another thread (T2). The `run_in_executor` call does NOT propagate the task's context to the new thread in CPython's `ThreadPoolExecutor`.

This means the depth limit is NOT enforced across recursive dispatch levels. A chain of depth-5 recursive calls would show `_THREAD_DEPTH = 0` at every level, never triggering the limit.

## Evidence

```python
# thread_bridge.py lines 63-76
def llm_query(prompt: str, **kwargs: Any) -> Any:
    depth = _THREAD_DEPTH.get(0)       # Always 0 in a fresh thread
    if depth >= _max_depth:
        raise RuntimeError(...)
    _THREAD_DEPTH.set(depth + 1)       # Sets to 1, but only in this thread
    try:
        future = asyncio.run_coroutine_threadsafe(
            llm_query_async(prompt, **kwargs), loop
        )
        return future.result(timeout=_timeout)
    finally:
        _THREAD_DEPTH.set(depth)
```

```python
# local_repl.py lines 453-458
async def execute_code_threaded(self, code, trace=None):
    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    # run_in_executor creates a NEW thread -- ContextVars don't propagate
    stdout, stderr, _success = await asyncio.wait_for(
        loop.run_in_executor(executor, self._execute_code_threadsafe, code, trace),
        ...
    )
```

The actual recursion depth limit that IS enforced is `max_depth` in `dispatch.py` (line 281: `if depth + 1 >= max_depth`), which uses an integer parameter passed down the call chain. So the `_THREAD_DEPTH` ContextVar is redundant with the `max_depth` check but provides a false sense of security -- it would catch only within-thread recursion (e.g., a skill function that calls `llm_query` which somehow re-enters the same thread), not cross-thread recursion.

## Suggested Fix

Replace the ContextVar-based depth tracking with explicit depth propagation through the closure chain:

**Option A**: Pass the current depth as an argument through `make_sync_llm_query` and wire it through `llm_query_async` -> `create_child_orchestrator`. The `dispatch.py` `max_depth` check (line 281) already does this correctly. Remove `_THREAD_DEPTH` or document it as a same-thread-only guard.

**Option B**: Use `loop.run_in_executor` with a context-aware wrapper. Before calling `run_in_executor`, capture the current context with `contextvars.copy_context()` and run the target function inside that context:

```python
async def execute_code_threaded(self, code, trace=None):
    loop = asyncio.get_running_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    ctx = contextvars.copy_context()
    stdout, stderr, _success = await asyncio.wait_for(
        loop.run_in_executor(executor, ctx.run, self._execute_code_threadsafe, code, trace),
        ...
    )
```

This propagates the ContextVar values (including `_THREAD_DEPTH`) from the event-loop task into the worker thread.

**Recommendation**: Option B is the minimal fix. But also document that `_THREAD_DEPTH` is a defense-in-depth measure and that `dispatch.py`'s `max_depth` is the primary depth limiter.
