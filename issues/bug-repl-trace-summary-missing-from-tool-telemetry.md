# Bug: `repl_trace_summary` is not landing in tool telemetry rows

## Summary
`last_repl_result.trace_summary` is present in final state and the `repl_traces.json` artifact, but the corresponding `telemetry.repl_trace_summary` column remains `NULL` for `execute_code` rows.

## Location
- [repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L276)
- [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L975)
- [repl_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py#L45)

## Expected
When `last_repl_result.trace_summary` exists for an `execute_code` tool invocation, `SqliteTracingPlugin.after_tool_callback()` should serialize it into `telemetry.repl_trace_summary`.

## Actual
`trace_summary` is present in state and artifact output, but all `execute_code` telemetry rows have `repl_trace_summary = NULL`.

## Evidence
From rerunning [fake_recursive_ping.json](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/fake_recursive_ping.json) with `repl_trace_level=2`:

Final state contained:
- `last_repl_result.trace_summary.wall_time_ms = 427.89`
- `last_repl_result.trace_summary.llm_call_count = 1`
- `last_repl_result.trace_summary.submitted_code_hash = cd27e0f90d34d125a4cb16efa9d9acb131ee170e59050b142dad3a1e998539e6`

`repl_traces.json` artifact contained:
- `d0:i1.trace_summary` with the same values

But SQLite query:
```sql
select tool_name, agent_name, repl_trace_summary
from telemetry
where event_type='tool_call'
order by start_time;
```
returned `NULL` for all `execute_code` rows.

## Root Cause
`SqliteTracingPlugin.after_tool_callback()` attempts to load `trace_summary` from the current tool's REPL state and write it into telemetry, but that path is not succeeding for this run even though the state and artifact prove the summary exists.

The intended write path is here:
- [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L983)

## Impact
This leaves telemetry materially less useful than intended:
- no wall-time summary in the tool row
- no per-tool submitted-code hash in telemetry
- no direct SQL access to compact trace summaries

Today the data is split across:
- telemetry for stdout/stderr lengths
- state for `last_repl_result`
- artifact storage for `repl_traces.json`

## Reproduction
1. Run the provider-fake fixture with `repl_trace_level=2`.
2. Confirm `last_repl_result.trace_summary` exists in final state.
3. Confirm `repl_traces.json` artifact exists.
4. Query `telemetry.repl_trace_summary` for `execute_code` rows.
5. Observe `NULL` values.

## Proposed Fix
Trace why `after_tool_callback()` is not seeing or serializing the REPL trace summary for the active tool state, then ensure `telemetry.repl_trace_summary` is populated whenever `last_repl_result.trace_summary` exists.
