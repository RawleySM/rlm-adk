# GAP-TH-010: `repl.globals` mutations from `set_llm_query_fns` and `collect_skill_repl_globals` are not atomic with respect to concurrent REPL execution

**Severity**: LOW
**Category**: threading
**Files**: `rlm_adk/repl/local_repl.py`, `rlm_adk/orchestrator.py`

## Problem

In `orchestrator.py` `_run_async_impl`, multiple mutations to `repl.globals` happen sequentially (lines 263-274, 306-309):

```python
repl.globals["LLMResult"] = LLMResult                       # line 263
_skill_globals = collect_skill_repl_globals(...)             # line 270
repl.globals.update(_skill_globals)                          # line 274
...
repl.set_llm_query_fns(sync_llm_query, sync_llm_query_batched)  # line 306-309
```

`set_llm_query_fns` (local_repl.py lines 212-215) writes:
```python
self.globals["llm_query"] = llm_query_fn
self.globals["llm_query_batched"] = llm_query_batched_fn
```

All of this happens on the event loop thread BEFORE `reasoning_agent.run_async(ctx)` starts, so there is no concurrent REPL execution at this point. The setup is sequential and safe.

However, the skill function wrappers created by `_wrap_with_llm_query_injection` (loader.py lines 83-96) read from `repl_globals["llm_query"]` lazily at call time:

```python
def wrapper(*args, **kwargs):
    if "llm_query_fn" not in kwargs:
        llm_query = repl_globals.get("llm_query")  # <-- Reads from shared dict
```

This lazy read happens in the WORKER thread during REPL execution. If `repl.globals["llm_query"]` were ever modified while a skill function is executing, the skill could see a stale or partially-updated reference.

In the current architecture, `llm_query` is set once during orchestrator setup and never modified again during execution. So this is safe in practice. The risk is future modifications that might update globals mid-execution.

## Evidence

```python
# loader.py lines 83-96 (_wrap_with_llm_query_injection)
def wrapper(*args, **kwargs):
    if "llm_query_fn" not in kwargs:
        llm_query = repl_globals.get("llm_query")  # Worker thread reads
        ...
    return fn(*args, **kwargs)

# orchestrator.py lines 306-309 (event loop thread sets)
repl.set_llm_query_fns(
    make_sync_llm_query(llm_query_async, _loop),
    make_sync_llm_query_batched(llm_query_batched_async, _loop),
)
```

## Suggested Fix

No fix needed for the current architecture -- the write happens strictly before any reads. Document the ordering contract:

```python
# In set_llm_query_fns:
"""Set/update the sync LM query functions.

Must be called before any REPL execution starts. The llm_query and
llm_query_batched globals are read lazily by skill function wrappers
from worker threads; this method must complete before execute_code_threaded
is called for the first time.
"""
```

For future-proofing, if there's ever a need to update these functions mid-execution (e.g., for hot-swapping models), use a `threading.Lock` or `threading.Event` to gate reads.
