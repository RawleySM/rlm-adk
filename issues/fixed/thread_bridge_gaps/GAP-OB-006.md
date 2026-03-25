# GAP-OB-006: DataFlowTracker edges overwritten on each batch call
**Severity**: MEDIUM
**Category**: observability
**Files**: `rlm_adk/dispatch.py`, `rlm_adk/repl/trace.py`

## Problem

In `dispatch.py` line 533, the data flow edges from each batch are assigned with `=` (assignment) rather than `+=` (extend):

```python
current_trace.data_flow_edges = _data_flow.get_edges()
```

If a single REPL code block makes multiple `llm_query()` / `llm_query_batched()` calls, each invocation of `llm_query_batched_async` overwrites `current_trace.data_flow_edges` with only the edges from the current batch. Edges detected in earlier batches within the same code block execution are lost.

## Evidence

`dispatch.py` line 533:
```python
current_trace.data_flow_edges = _data_flow.get_edges()
```

`trace.py` line 104: `data_flow_edges` is a `list[tuple[int, int]]` initialized to `[]`. Each batch creates a fresh `DataFlowTracker` (line 482) and overwrites the trace's edges list (line 533).

Scenario:
1. Code block calls `llm_query("A")` -- batch 1 runs, edges = []
2. Code block calls `llm_query("B using A's result")` -- batch 2 runs, detects edge (0, 1)
3. `current_trace.data_flow_edges` = [(0, 1)] -- correct so far
4. Code block calls `llm_query("C using B's result")` -- batch 3 runs, creates fresh tracker, has no knowledge of call 0 or 1, no edges detected
5. `current_trace.data_flow_edges` = [] -- edge (0, 1) is lost

## Suggested Fix

Change line 533 to extend rather than replace:
```python
current_trace.data_flow_edges.extend(_data_flow.get_edges())
```

This preserves edges detected in earlier batches within the same code block. For full cross-call tracking, see GAP-OB-005.
