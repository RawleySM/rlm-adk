# GAP-EL-002: `_THREAD_DEPTH` ContextVar does not track actual recursive dispatch depth

**Severity**: MEDIUM
**Category**: event-loop
**Files**: `rlm_adk/repl/thread_bridge.py`, `rlm_adk/repl/local_repl.py`

## Problem

`_THREAD_DEPTH` is a `contextvars.ContextVar` used to prevent runaway recursive dispatch (default limit 10). However, ContextVars are NOT inherited by threads created via `ThreadPoolExecutor`. Each new worker thread starts with `_THREAD_DEPTH = 0` (the default), regardless of the actual recursion depth.

The recursive dispatch path is:

```
Worker thread A (depth=0 in REPL code)
  -> llm_query() increments _THREAD_DEPTH to 1
    -> run_coroutine_threadsafe schedules on event loop
      -> child orchestrator runs
        -> execute_code_threaded creates NEW ThreadPoolExecutor
          -> Worker thread B starts with _THREAD_DEPTH = 0 (RESET!)
            -> llm_query() increments to 1 (should be 2)
```

This means the `_THREAD_DEPTH` limit (default 10) protects against 10 recursive `llm_query()` calls within a SINGLE code block, but NOT against 10 levels of orchestrator nesting. Each level of orchestrator nesting gets its own fresh `_THREAD_DEPTH = 0`.

The ACTUAL recursion depth limit is enforced by `max_depth` in `dispatch.py` (line 281: `if depth + 1 >= max_depth`), which works correctly because it uses an integer parameter, not a ContextVar. So the system IS protected against infinite recursion, but `_THREAD_DEPTH` is NOT doing what its name and documentation suggest.

## Evidence

`thread_bridge.py` lines 27-29:
```python
_THREAD_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_THREAD_DEPTH", default=0
)
```

`local_repl.py` line 453:
```python
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
```

Empirical verification: setting a ContextVar to 10 in the event loop thread, then running a function in `loop.run_in_executor()` -- the worker thread sees the default value (0), not 10.

## Suggested Fix

This is not a correctness bug because `dispatch.py` enforces `max_depth` independently. However, the `_THREAD_DEPTH` variable is misleading. Options:

1. **Rename and re-document**: Rename to `_INTRA_BLOCK_LLM_DEPTH` and document that it only prevents recursive `llm_query()` calls within a single code block (e.g., skill function A calls `llm_query()` which triggers skill function B which calls `llm_query()` -- all within the same worker thread).

2. **Thread the depth value explicitly**: Pass the current orchestrator depth into `make_sync_llm_query` and use it as the initial value instead of 0. This would make `_THREAD_DEPTH` reflect actual total depth = orchestrator depth + intra-block depth.
