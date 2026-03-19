# Eval: Stale State-Plane Readers for Child Summaries and Worker Errors

## Context

The three-plane refactoring (state/lineage/completion) removed the old state-transport pattern where dispatch wrote per-iteration child lineage counters and worker error classifications into session state. These metrics are now captured directly in the SQLite telemetry table by `SqliteTracingPlugin` (via `decision_mode`, `structured_outcome`, `terminal_completion` columns, and error classification from tool callback lineage status).

## Findings

1. High: `rlm_adk/eval/session_report.py` queries `obs:child_summary` from `session_state_events` to build child dispatch reports for evaluator consumption. The `_flatten_child_summary()` function (line 487) expects a dict payload with `structured_output`, `depth`, `fanout_idx` fields, and the SQL query at line 543 filters `WHERE state_key = 'obs:child_summary'`. Since `obs:child_summary` is never written by new code, this query returns zero rows for all new runs. Eval reports for new runs will have no child dispatch data. Relevant lines: `rlm_adk/eval/session_report.py:487`, `rlm_adk/eval/session_report.py:543`.

2. High: `rlm_adk/eval/trace_reader.py` queries `obs:worker_error_counts` from `session_state_events` to populate worker error classification data. This was the old per-iteration worker error accumulator (classified errors like RATE_LIMIT, SERVER, AUTH, etc.). Since `obs:worker_error_counts` is never written by new code, this query returns NULL for all new runs. Error classification data for new runs is lost from eval reports. Relevant lines: `rlm_adk/eval/trace_reader.py:606`.

## Proposed fix

Migrate both queries to read from the `telemetry` table:

### For `obs:child_summary` (session_report.py)

Replace the SSE query with a telemetry query that aggregates child dispatch data:

```sql
SELECT depth, fanout_idx, decision_mode, structured_outcome,
       terminal_completion, validated_output_json, output_schema_name
FROM telemetry
WHERE trace_id = ? AND event_type = 'tool_call'
  AND depth > 0 AND decision_mode IS NOT NULL
ORDER BY depth, fanout_idx, start_time
```

Build `LiveChildSummary`-equivalent dicts from the telemetry rows.

### For `obs:worker_error_counts` (trace_reader.py)

Replace the SSE query with a telemetry aggregation:

```sql
SELECT status, error_type, COUNT(*) as count
FROM telemetry
WHERE trace_id = ? AND event_type = 'model_call'
  AND status = 'error'
GROUP BY error_type
```

This derives the same error classification breakdown from telemetry rows.

## Files to modify

- `rlm_adk/eval/session_report.py` -- `_flatten_child_summary()` and the `obs:child_summary` query
- `rlm_adk/eval/trace_reader.py` -- the `obs:worker_error_counts` query

## Acceptance criteria

- Eval reports for new runs include child dispatch data derived from telemetry
- Eval reports for new runs include worker error classification data derived from telemetry
- Old traces still produce correct reports (graceful fallback or dual-path query)
- No reads of `obs:child_summary` or `obs:worker_error_counts` from `session_state_events` for new data
