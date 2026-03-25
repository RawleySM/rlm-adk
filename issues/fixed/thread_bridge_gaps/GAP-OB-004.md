# GAP-OB-004: REPLCapturePlugin inventory documents deleted async globals
**Severity**: LOW
**Category**: observability
**Files**: `rlm_adk/plugins/repl_capture_plugin.py`

## Problem

The `_repl_globals_inventory()` function in `repl_capture_plugin.py` (lines 27-80) documents the canonical REPL namespace injections. Two entries reference architecture that no longer exists:

1. Line 41-42: `llm_query` described as `"sync placeholder; AST rewriter converts to async"` -- the AST rewriter is deleted. `llm_query` is now a real sync callable created by `thread_bridge.py:make_sync_llm_query()`.

2. Lines 43-45: `llm_query_async` and `llm_query_batched_async` are documented as being injected into REPL globals. In the thread bridge architecture, only `llm_query` and `llm_query_batched` (sync) are injected via `LocalREPL.set_llm_query_fns()`. The async variants are NOT in repl.globals -- they live only inside the dispatch closures.

When `_repl_globals_inventory()` is called with a live `repl_globals` dict, the async entries will show `"present": False` because they do not exist. The inventory is misleading and can confuse debugging.

## Evidence

`repl_capture_plugin.py` lines 41-45:
```python
"llm_query": {"type": "function", "source": "orchestrator.py:295", "note": "sync placeholder; AST rewriter converts to async"},
"llm_query_batched": {"type": "function", "source": "orchestrator.py:295", "note": "sync placeholder; AST rewriter converts to async"},
"llm_query_async": {"type": "async function", "source": "dispatch.py:435", "note": "single child dispatch"},
"llm_query_batched_async": {"type": "async function", "source": "dispatch.py:477", "note": "batched child dispatch"},
```

`local_repl.py` line 212-215 (the actual injection):
```python
def set_llm_query_fns(self, llm_query_fn: Callable, llm_query_batched_fn: Callable) -> None:
    self.globals["llm_query"] = llm_query_fn
    self.globals["llm_query_batched"] = llm_query_batched_fn
```

No `llm_query_async` or `llm_query_batched_async` is injected into globals.

## Suggested Fix

Update the canonical inventory in `_repl_globals_inventory()`:
1. Change `llm_query` note to `"sync callable via thread_bridge.py"` and source to `"thread_bridge.py:63"`.
2. Change `llm_query_batched` similarly.
3. Remove `llm_query_async` and `llm_query_batched_async` entries (they are not REPL globals in the thread bridge architecture).
