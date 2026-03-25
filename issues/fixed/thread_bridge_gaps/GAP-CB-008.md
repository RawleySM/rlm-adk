# GAP-CB-008: `_THREAD_DEPTH` ContextVar does not accumulate across dispatch boundaries

**Severity**: LOW
**Category**: callback-lifecycle
**Files**: `rlm_adk/repl/thread_bridge.py` (lines 27-76), `rlm_adk/repl/local_repl.py` (lines 433-478)

## Problem

The `_THREAD_DEPTH` ContextVar is intended to prevent runaway recursive thread creation. However, it effectively resets to 0 at each dispatch boundary due to how ContextVars propagate across the thread bridge:

1. REPL worker thread: `_THREAD_DEPTH` is set to 1 when `llm_query()` is called
2. `run_coroutine_threadsafe()` submits the async dispatch to the event loop
3. The event loop thread runs the child orchestrator (its `_THREAD_DEPTH` is 0 -- the event loop's own context)
4. The child orchestrator's `execute_code_threaded()` creates a NEW worker thread via `loop.run_in_executor()`
5. Python 3.12's `run_in_executor` copies the event loop thread's context to the new worker thread
6. The new worker thread has `_THREAD_DEPTH=0` (copied from event loop context, not from the parent worker thread)

So `_THREAD_DEPTH` only protects against recursion within a single `llm_query()` call (e.g., if the return value somehow triggered another `llm_query()` before the first returned). It does NOT accumulate across recursive child dispatch.

## Evidence

Thread bridge flow:
```
Worker Thread A (_THREAD_DEPTH=0)
  -> llm_query() sets _THREAD_DEPTH=1
    -> run_coroutine_threadsafe(llm_query_async, loop)
      -> Event Loop Thread (_THREAD_DEPTH=0, separate context)
        -> child orchestrator
          -> execute_code_threaded()
            -> run_in_executor(executor, _execute_code_threadsafe)
              -> Worker Thread B (_THREAD_DEPTH=0, copied from event loop)
                -> llm_query() sets _THREAD_DEPTH=1
                  -> ...
```

The depth never exceeds 1 in any thread.

## Impact

Low. The real recursion guard is `dispatch.py`'s `max_depth` check at line 281:
```python
if depth + 1 >= max_depth:
    result = LLMResult(f"[DEPTH_LIMIT] ...")
```

This check uses the logical orchestrator depth (an integer parameter, not a ContextVar), so it correctly accumulates across dispatch boundaries. The `_THREAD_DEPTH` ContextVar is a redundant (but ineffective) secondary guard.

## Suggested Fix

Two options:
1. **Remove `_THREAD_DEPTH`** and document that the dispatch-level `max_depth` is the authoritative recursion guard. The thread bridge timeout (300s default) provides a secondary safety net against infinite blocking.

2. **Propagate depth as a function argument** instead of a ContextVar. Pass the current depth through the dispatch closures so it accumulates correctly. This would require changing the `llm_query` signature to carry depth metadata, which is a larger change.

Given that the dispatch-level depth limit already works correctly, option 1 (document + remove) is the lowest-risk fix.
