# Dashboard: Child Summaries Empty for New Runs (Stale State-Plane Reader)

## Context

The three-plane refactoring (state/lineage/completion) removed the old state-transport pattern where dispatch mirrored child lineage into parent session state via `obs:child_summary@d{D}f{F}` keys. Child dispatch metrics are now captured directly in the SQLite `telemetry` table columns (`decision_mode`, `structured_outcome`, `terminal_completion`, `depth`, `fanout_idx`, etc.) by `SqliteTracingPlugin`.

## Problem

`rlm_adk/dashboard/live_loader.py` method `_build_child_summaries()` (line 748) reads `obs:child_summary` rows from the `session_state_events` table. Since the refactoring, `obs:child_summary` is never written to state by any production code path. This means:

1. `_build_child_summaries()` returns empty results for all new runs.
2. The `LivePane.child_summaries` field is always empty for new traces.
3. The dashboard cannot display child dispatch information (depth, fanout, structured output, errors) for runs created after the refactoring.

The `obs:child_summary` filter appears at line 753 where it checks `row.get("state_key") != "obs:child_summary"` -- this is an inclusion filter (it skips non-matching rows via `continue`).

Old traces (pre-refactoring) continue to display correctly because the historical `session_state_events` rows still exist.

## Relevant lines

- `rlm_adk/dashboard/live_loader.py:748-808` -- `_build_child_summaries()` method, reads from `sse_rows` filtering on `obs:child_summary` state key
- `rlm_adk/dashboard/live_models.py:107-132` -- `LiveChildSummary` dataclass with 25 fields populated from the old state-event payload
- `rlm_adk/plugins/sqlite_tracing.py:226-274` -- `telemetry` table schema with lineage columns that replaced the state-transport pattern
- `rlm_adk/state.py:123-125` -- `child_obs_key()` helper (dead code, generates the removed `obs:child_summary@d{D}f{F}` keys)

## Proposed fix

Migrate `_build_child_summaries()` to query the `telemetry` table instead of `session_state_events`. The telemetry table already has all needed columns:

| Telemetry column | Purpose |
|---|---|
| `depth`, `fanout_idx`, `parent_depth`, `parent_fanout_idx` | Lineage coordinates |
| `decision_mode` | `"execute_code"` or `"set_model_response"` |
| `structured_outcome` | `"validated"`, `"retry_exhausted"`, etc. |
| `terminal_completion` | Whether this was a terminal result |
| `validated_output_json` | The actual structured output payload |
| `branch`, `invocation_id`, `session_id` | Scope identifiers |
| `output_schema_name` | Schema used for structured output |
| `model` | Model name |
| `input_tokens`, `output_tokens`, `thought_tokens` | Token accounting |
| `finish_reason` | LLM finish reason |
| `duration_ms` | Elapsed time (maps to `elapsed_ms` on `LiveChildSummary`) |
| `status`, `error_type`, `error_message` | Error information |
| `result_preview` | Result text preview |

The query would filter telemetry rows where `depth > 0`, group by `(depth, fanout_idx)`, and build `LiveChildSummary` objects from the aggregated data. This replaces the old pattern of reading pre-assembled summaries from state events.

## Files to modify

- `rlm_adk/dashboard/live_loader.py` -- Rewrite `_build_child_summaries()` to query telemetry table rows instead of `session_state_events` rows
- `rlm_adk/dashboard/live_models.py` -- Possibly update `LiveChildSummary` fields if the telemetry-derived data has a different shape (e.g., `decision_mode` and `structured_outcome` are new fields not present in the old summary dict; some old fields like `prompt`, `thought_text`, `raw_output` have no direct telemetry equivalent)

## Acceptance criteria

1. New runs show child dispatch information in the dashboard.
2. Old traces still display correctly (graceful fallback or dual-path query).
3. No reads of `obs:child_summary` from `session_state_events` for new data.
