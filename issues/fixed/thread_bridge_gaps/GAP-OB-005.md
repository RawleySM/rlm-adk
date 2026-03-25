# GAP-OB-005: DataFlowTracker edge detection is scoped to single batched dispatch, not across calls
**Severity**: LOW
**Category**: observability
**Files**: `rlm_adk/dispatch.py`, `rlm_adk/repl/trace.py`

## Problem

`DataFlowTracker` (trace.py lines 120-154) detects when one `llm_query()` response feeds into a subsequent prompt by checking if substrings of previous responses appear in new prompts. This is designed to track data flow edges within a code block.

In the thread bridge architecture, the tracker is instantiated fresh inside each `llm_query_batched_async` call (dispatch.py line 482):
```python
_data_flow = DataFlowTracker() if current_trace is not None else None
```

This means edges are only detected WITHIN a single batched dispatch. If code makes two separate `llm_query()` calls (not batched), the first goes through `llm_query_async` which delegates to `llm_query_batched_async` with `_record_trace_entries=False` (dispatch.py line 446). The second call creates a NEW `DataFlowTracker` in its own `llm_query_batched_async` invocation, which has no knowledge of the first call's response.

Cross-call data flow edges (e.g., `result1 = llm_query("q1")` followed by `result2 = llm_query(f"given {result1}, ...")`) are never detected because the tracker is not shared across calls.

In the old AST rewriter architecture, the same limitation existed -- the DataFlowTracker was per-batch. This is not a regression, but it is a known gap in the trace data flow model that persists through the migration.

## Evidence

`dispatch.py` line 482: `_data_flow = DataFlowTracker()` -- fresh instance per batch
`dispatch.py` lines 431-462: `llm_query_async` delegates to `llm_query_batched_async` with `_record_trace_entries=False`, so the data flow tracker in the batch call never sees cross-call data.

The `REPLTrace` accumulates `data_flow_edges` from multiple batched calls (line 533: `current_trace.data_flow_edges = _data_flow.get_edges()`), but this overwrites rather than extends, so only the last batch's edges survive.

## Suggested Fix

1. Move DataFlowTracker to trace-level scope (one per REPLTrace, not one per batch).
2. Pass it through as a parameter to `llm_query_batched_async` rather than creating it locally.
3. Change line 533 from `=` to `+=` to accumulate rather than overwrite edges.
