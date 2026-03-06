# 07 - Session Assessment Scripter

Module: `rlm_adk/eval/session_report.py`

## Purpose

Consolidates a session's SQLite telemetry into a single machine-readable JSON report. Designed to be consumed by LLM-based evaluation agents or human reviewers without needing to write SQL.

## Usage

### CLI
```bash
python -m rlm_adk.eval.session_report --trace-id <trace_id> --db .adk/traces.db
```

### Python API
```python
from rlm_adk.eval.session_report import build_session_report

report = build_session_report("bffab79f7daa41a4b2b01f68df8b1d3f", db_path=".adk/traces.db")
```

## Report Sections

### `overview`
Top-level session identity and summary metrics. Maps to the **Documentation/Historian** persona (doc 03).

| Field | Source | Notes |
|-------|--------|-------|
| `trace_id` | traces table | Primary key |
| `session_id` | traces table | ADK session container |
| `status` | traces table | "running" or "completed" |
| `wall_clock_s` | traces.start_time/end_time or telemetry bounds | Fallback to telemetry if trace incomplete |
| `total_input_tokens` | SUM(telemetry.input_tokens) | Aggregated from all model_call rows |
| `total_output_tokens` | SUM(telemetry.output_tokens) | Aggregated from all model_call rows |
| `total_model_calls` | COUNT(telemetry) where model_call | All depths |
| `total_tool_calls` | COUNT(telemetry) where tool_call | All depths |
| `iterations` | MAX(SSE iteration_count at d=0) | Depth-0 reasoning iterations |
| `final_answer_length` | traces table | NULL for incomplete runs |

### `layer_tree`
Hierarchical dispatch tree view. Maps to **Debugging** (doc 01, section 1) and **Performance** (doc 02, section 6) personas.

Each layer key (`depth_0`, `depth_1`, `depth_2`) contains:
- `agents`: list of agent names at this depth
- `model_calls`, `tool_calls`: counts
- `input_tokens`, `output_tokens`: sums
- `error_count`: telemetry rows with status=error

Note: `depth_-1` captures model calls with NULL agent_name (typically before agent callbacks fire).

### `performance`
Latency statistics and rate limit impact. Maps to **Performance** persona (doc 02).

- `model_call_latency_by_layer`: min/max/avg/p95 of `duration_ms` per depth
- `rate_limit_errors`: count of telemetry errors matching ResourceExhausted/429 patterns
- `repl_execution`: latency stats for execute_code tool calls

### `errors`
Error breakdown by depth and type. Maps to **Debugging** persona (doc 01, sections 3 and 7).

- `telemetry_errors`: grouped by agent_name and error_type with sample messages
- `repl_errors`: execute_code calls where repl_has_errors=1 (with result_preview)
- `error_propagation_by_depth`: which error types appeared at which depths

### `repl_outcomes`
Code execution results. Maps to **Code Review** persona (doc 04).

- `by_depth`: per-depth counts of total/errors/with_output/with_llm_calls
- `reasoning_agent_calls`: per-call detail for depth-0 only (compact)
- `error_pattern_counts`: Python exception type frequencies from result_preview

### `state_timeline`
Ordered state mutation log. Maps to **Debugging** (doc 01, section 4) for state provenance tracking.

- `categories`: count of events by key_category (obs_reasoning, obs_dispatch, flow_control, etc.)
- `events`: ordered list with seq, time, author, key, value (truncated to 200 chars)

## Design Decisions

1. **Uses raw sqlite3, not DuckDB**: Avoids the DuckDB dependency for a standalone CLI tool. The TraceReader in `eval/trace_reader.py` uses DuckDB for analytics; this module prioritizes portability.

2. **Token totals from telemetry, not traces table**: The live DB has a schema migration gap (traces table missing enrichment columns). Telemetry rows are always populated, making them a reliable source even for "running" traces.

3. **Per-call detail only for depth-0**: Including all 252 tool calls in per-call detail would produce 50K+ chars. Only reasoning agent calls are listed individually; deeper depths get aggregate summaries.

4. **Value truncation at 200 chars**: Large state values (JSON blobs, text) are truncated to keep the report compact enough for LLM context windows.

5. **depth_-1 bucket**: Model calls with NULL agent_name (before agent callbacks fire) are grouped separately rather than dropped.

## Data Flow

```
.adk/traces.db
  |
  +-- traces table -----> overview (identity, status, timing)
  |
  +-- telemetry table ---> layer_tree (GROUP BY agent_name)
  |                    |-> performance (duration_ms stats)
  |                    |-> errors (status='error' rows)
  |                    |-> repl_outcomes (tool_name='execute_code')
  |
  +-- session_state_events -> state_timeline (ordered by seq)
  |
  +-- spans table -----> (not used; legacy, 0 rows)
```

## Known Limitations

1. **Schema migration gap**: The traces table in the live DB only has 13 base columns, not the 22 enriched columns defined in `_SCHEMA_SQL`. Fields like `request_id`, `child_dispatch_count`, `total_execution_time_s` are NOT available from the traces table. The report works around this by querying telemetry and SSE directly.

2. **Incomplete traces**: Traces with status="running" (where after_run_callback never fired) have NULL end_time and zero enrichment values. The report falls back to telemetry-derived bounds.

3. **REPL enrichment columns often NULL**: `repl_has_errors`, `repl_has_output`, `repl_llm_calls` are only populated when SqliteTracingPlugin's after_tool_callback processes execute_code results. For some rows these are NULL (before/after callback mismatch).

4. **No child prompt/response text**: Prompt text sent to workers (`_pending_prompt`) and worker response text are transient and not persisted (RED gap in doc 05).

5. **SSE coverage**: Only 12 SSE rows for the test trace. Many obs keys (obs:total_*, obs:finish_*, child_summary) did not land in SSE due to the trace being interrupted and/or ephemeral key issues.
