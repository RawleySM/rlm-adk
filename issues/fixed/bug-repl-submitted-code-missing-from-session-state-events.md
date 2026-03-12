# Bug: `repl_submitted_code*` keys are not persisted to `session_state_events`

## Summary
`REPLTool` writes `repl_submitted_code`, `repl_submitted_code_preview`, `repl_submitted_code_hash`, and `repl_submitted_code_chars` into session state, but `SqliteTracingPlugin` does not persist those keys into `session_state_events`.

## Location
- [repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L85)
- [state.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L95)
- [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L91)

## Expected
When REPL code is submitted, the corresponding `repl_submitted_code*` state keys should appear in `session_state_events`, just like `last_repl_result` does.

## Actual
The keys are present in final session state but absent from SQLite `session_state_events`.

## Evidence
From rerunning [fake_recursive_ping.json](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/fake_recursive_ping.json) with `run_fixture_contract_with_plugins(..., repl_trace_level=2)`:

Final state included:
- `repl_submitted_code`
- `repl_submitted_code_preview`
- `repl_submitted_code_hash`
- `repl_submitted_code_chars`

SQLite query result:
```sql
select seq, state_key, key_depth, value_type
from session_state_events
where state_key like 'repl_submitted_code%'
order by seq;
```
Returned: `0 rows`

At the same time:
```sql
select seq, state_key, key_depth, value_type
from session_state_events
where key_category='repl'
order by seq;
```
Returned only:
- `last_repl_result`

## Root Cause
`SqliteTracingPlugin` only persists a curated subset of state keys. The capture set includes `last_repl_result` but not `repl_submitted_code*`.

Current curated prefixes:
- `obs:`
- `artifact_`
- `last_repl_result`

See [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L93).

## Impact
This breaks traceability for REPL execution history in SQLite:
- the submitted code is not queryable from `session_state_events`
- state/event replay cannot reconstruct REPL input from the SQLite event stream
- REPL input exists only in final state, which is weaker than event-level persistence

## Reproduction
1. Run the provider-fake fixture through `run_fixture_contract_with_plugins()` with SQLite tracing enabled.
2. Confirm final state contains `repl_submitted_code*`.
3. Query `session_state_events` for `repl_submitted_code%`.
4. Observe no rows.

## Proposed Fix
Extend the `SqliteTracingPlugin` curated capture set to include:
- `repl_submitted_code`
- `repl_submitted_code_preview`
- `repl_submitted_code_hash`
- `repl_submitted_code_chars`

A prefix-based inclusion for `repl_submitted_code` is the simplest option.
