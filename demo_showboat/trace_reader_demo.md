# TraceReader 3-Table Schema Support

*2026-03-05T19:37:25Z by Showboat 0.6.0*
<!-- showboat-id: aab7517c-0eae-4147-a611-dc4443c81093 -->

## Overview

TraceReader now covers all 3 tables written by SqliteTracingPlugin:

| Table | Methods | Purpose |
|-------|---------|---------|
| **traces** | list_traces, get_trace, get_trace_summary | Invocation-level summaries (28 cols) |
| **telemetry** | get_telemetry, get_model_calls, get_tool_calls, get_token_usage, get_iteration_timeline | Per-call model/tool events (27 cols) |
| **session_state_events** | get_state_events, get_state_key_history, get_error_summary | Curated state mutations (14 cols) |

All methods handle missing tables gracefully (return empty list/dict/None).

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_trace_reader.py -v --tb=short 2>&1 | grep -E 'PASSED|FAILED|ERROR|passed|failed'
```

```output
tests_rlm_adk/test_trace_reader.py::test_trace_reader_raises_on_missing_db PASSED [  2%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_attaches_sqlite PASSED [  5%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_context_manager PASSED [  8%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_list_sessions PASSED [ 10%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_list_sessions_with_user_filter PASSED [ 13%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_get_session_event_count PASSED [ 16%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_get_session_state PASSED [ 18%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_get_session_state_missing PASSED [ 21%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_get_invocation_ids PASSED [ 24%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_get_events_raw PASSED [ 27%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_get_events_raw_with_invocation_filter PASSED [ 29%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_get_events_raw_with_limit PASSED [ 32%]
tests_rlm_adk/test_trace_reader.py::test_trace_reader_execute_custom_query PASSED [ 35%]
tests_rlm_adk/test_trace_reader.py::TestListTraces::test_list_traces_returns_all PASSED [ 37%]
tests_rlm_adk/test_trace_reader.py::TestListTraces::test_list_traces_with_limit PASSED [ 40%]
tests_rlm_adk/test_trace_reader.py::TestListTraces::test_list_traces_with_status_filter PASSED [ 43%]
tests_rlm_adk/test_trace_reader.py::TestGetTrace::test_get_trace_returns_dict PASSED [ 45%]
tests_rlm_adk/test_trace_reader.py::TestGetTrace::test_get_trace_returns_none_for_missing PASSED [ 48%]
tests_rlm_adk/test_trace_reader.py::TestGetTraceSummary::test_get_trace_summary_metrics PASSED [ 51%]
tests_rlm_adk/test_trace_reader.py::TestGetTraceSummary::test_get_trace_summary_returns_none_for_missing PASSED [ 54%]
tests_rlm_adk/test_trace_reader.py::TestGetTelemetry::test_get_telemetry_all PASSED [ 56%]
tests_rlm_adk/test_trace_reader.py::TestGetTelemetry::test_get_telemetry_filter_model_call PASSED [ 59%]
tests_rlm_adk/test_trace_reader.py::TestGetTelemetry::test_get_telemetry_filter_tool_call PASSED [ 62%]
tests_rlm_adk/test_trace_reader.py::TestGetModelCalls::test_get_model_calls PASSED [ 64%]
tests_rlm_adk/test_trace_reader.py::TestGetToolCalls::test_get_tool_calls PASSED [ 67%]
tests_rlm_adk/test_trace_reader.py::TestGetTokenUsage::test_get_token_usage_totals PASSED [ 70%]
tests_rlm_adk/test_trace_reader.py::TestGetIterationTimeline::test_get_iteration_timeline PASSED [ 72%]
tests_rlm_adk/test_trace_reader.py::TestGetStateEvents::test_get_state_events_all PASSED [ 75%]
tests_rlm_adk/test_trace_reader.py::TestGetStateEvents::test_get_state_events_filter_by_category PASSED [ 78%]
tests_rlm_adk/test_trace_reader.py::TestGetStateEvents::test_get_state_events_filter_by_state_key PASSED [ 81%]
tests_rlm_adk/test_trace_reader.py::TestGetStateKeyHistory::test_get_state_key_history_ordered PASSED [ 83%]
tests_rlm_adk/test_trace_reader.py::TestGetStateKeyHistory::test_get_state_key_history_empty_for_unknown_key PASSED [ 86%]
tests_rlm_adk/test_trace_reader.py::TestGetErrorSummary::test_get_error_summary PASSED [ 89%]
tests_rlm_adk/test_trace_reader.py::TestGetErrorSummary::test_get_error_summary_empty_for_clean_trace PASSED [ 91%]
tests_rlm_adk/test_trace_reader.py::TestMissingTablesGraceful::test_list_traces_on_session_only_db PASSED [ 94%]
tests_rlm_adk/test_trace_reader.py::TestMissingTablesGraceful::test_get_telemetry_on_session_only_db PASSED [ 97%]
tests_rlm_adk/test_trace_reader.py::TestMissingTablesGraceful::test_get_state_events_on_session_only_db PASSED [100%]
======================== 37 passed, 1 warning in 5.21s =========================
```

## New API Methods

### traces table
- **list_traces(limit=None, status=None)** — All traces, newest first. Optional limit/status filter.
- **get_trace(trace_id)** — Single trace dict or None.
- **get_trace_summary(trace_id)** — Key metrics: tokens, iterations, duration_s, calls, dispatch counts.

### telemetry table
- **get_telemetry(trace_id, event_type=None)** — All telemetry rows, optionally filtered by 'model_call'|'tool_call'.
- **get_model_calls(trace_id)** — Shorthand for model_call telemetry.
- **get_tool_calls(trace_id)** — Shorthand for tool_call telemetry.
- **get_token_usage(trace_id)** — Total + per-model token breakdown via DuckDB GROUP BY.
- **get_iteration_timeline(trace_id)** — Per-iteration aggregates (tokens, calls, duration).

### session_state_events table
- **get_state_events(trace_id, key_category=None, state_key=None)** — State mutations ordered by seq.
- **get_state_key_history(trace_id, state_key)** — Value timeline for a single key.
- **get_error_summary(trace_id)** — Aggregated error info from telemetry + SSE.

### Graceful degradation
All new methods return empty results when tracing tables are absent (session-only DBs).

```bash
.venv/bin/python /tmp/trace_reader_demo_script.py
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
=== list_traces ===
  t1: completed (4 iters, 8000in/4000out)

=== get_trace_summary ===
  tokens: 8000in/4000out
  calls: 15, iterations: 4, duration: 60.0s

=== get_token_usage (from telemetry) ===
  total: 7500in/3600out
  gemini-3-pro: {'input_tokens': 7500, 'output_tokens': 3600, 'calls': 3}

=== get_iteration_timeline ===
  iter 0: 1 model, 1 tool, 4500.0ms
  iter 1: 1 model, 0 tool, 3000.0ms
  iter 2: 1 model, 0 tool, 3000.0ms

=== get_state_key_history ===
  seq 0: iteration_count = 1
  seq 1: iteration_count = 2

=== graceful degradation (no tracing tables) ===
  list_traces on session-only DB would return: []
```
