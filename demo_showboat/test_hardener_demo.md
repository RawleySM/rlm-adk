# Phase 5: FMEA Test Hardening + Docs Update

*2026-03-05T19:04:28Z by Showboat 0.6.0*
<!-- showboat-id: dde596c7-c369-469c-9dda-86f578e112a5 -->

Phase 5 adds e2e test assertions for previously untested observability keys and updates the canonical observability_keys.md reference doc to reflect all changes from Phases 1-4.

## New Test File: test_obs_e2e_hardening.py

18 new e2e tests across 8 test classes validating obs keys that were previously written but never asserted in tests:

- OBS_PER_ITERATION_TOKEN_BREAKDOWN (list existence, entry fields, agent_type)
- OBS_FINISH_SAFETY_COUNT (>= 1 for safety finish fixtures)
- OBS_FINISH_MAX_TOKENS_COUNT (type validation)
- obs:model_usage:{model} (key existence, dict fields)
- OBS_TOTAL_EXECUTION_TIME (ADK limitation documented, SQLite fallback verified)
- OBS_CHILD_DISPATCH_COUNT (canonical key populated, legacy keys absent)
- OBS_TOOL_INVOCATION_SUMMARY (dict with execute_code entry)
- OBS_TOTAL_CALLS / OBS_TOTAL_INPUT_TOKENS / OBS_TOTAL_OUTPUT_TOKENS (cross-fixture)

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_obs_e2e_hardening.py -v 2>&1 | grep -E '(PASSED|FAILED|ERROR|passed|failed)'
```

```output
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsPerIterationTokenBreakdown::test_breakdown_list_exists PASSED [  5%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsPerIterationTokenBreakdown::test_breakdown_entry_fields PASSED [ 11%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsPerIterationTokenBreakdown::test_breakdown_has_reasoning_agent_type PASSED [ 16%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsFinishSafetyCount::test_safety_count_populated PASSED [ 22%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsFinishMaxTokensCount::test_max_tokens_count_type PASSED [ 27%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsModelUsage::test_model_usage_key_exists PASSED [ 33%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsModelUsage::test_model_usage_fields PASSED [ 38%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsTotalExecutionTime::test_execution_time_not_in_final_state PASSED [ 44%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsTotalExecutionTime::test_execution_time_in_sqlite PASSED [ 50%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsChildDispatchCount::test_canonical_key_populated PASSED [ 55%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsChildDispatchCount::test_old_worker_key_absent PASSED [ 61%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsChildDispatchCount::test_child_latency_populated PASSED [ 66%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsChildDispatchCount::test_child_batch_dispatches PASSED [ 72%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsToolInvocationSummary::test_summary_exists PASSED [ 77%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsToolInvocationSummary::test_execute_code_entry PASSED [ 83%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsTokenAggregates::test_total_calls_positive PASSED [ 88%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsTokenAggregates::test_total_input_tokens_positive PASSED [ 94%]
tests_rlm_adk/test_obs_e2e_hardening.py::TestObsTokenAggregates::test_total_output_tokens_positive PASSED [100%]
======================= 18 passed, 93 warnings in 19.82s =======================
```

## Finding: OBS_TOTAL_EXECUTION_TIME ADK Limitation

During RED phase, discovered that OBS_TOTAL_EXECUTION_TIME is written by after_run_callback to invocation_context.session.state, but InMemorySessionService.get_session returns a pre-after_run snapshot. The key does NOT appear in final_state obtained via get_session.

However, SqliteTracingPlugin successfully reads it in its own after_run_callback (same invocation_context). The test documents this limitation and verifies the SQLite fallback path.

## Docs Update: observability_keys.md

Canonical reference doc updated to reflect all Phase 1-4 changes:

- Removed keys section: 7 dead keys, 4 legacy worker keys, 5 duplicate dispatch keys listed with reasons
- DebugLoggingPlugin listed as REMOVED
- Plugin matrix updated (3 active plugins, no DebugLoggingPlugin column)
- New SQLite 3-table schema documented (traces, telemetry, session_state_events)
- Ephemeral re-persist mechanism documented with fixed keys and dynamic prefixes
- Test coverage matrix updated with both test_fmea_e2e.py and test_obs_e2e_hardening.py

```bash
.venv/bin/python -m pytest tests_rlm_adk/ -q 2>&1 | tail -3
```

```output

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
832 passed, 1 skipped, 1156 warnings in 162.04s (0:02:42)
```

## Summary

- 18 new obs e2e tests added (test_obs_e2e_hardening.py)
- 832 tests pass, 0 failures, 1 skip (pre-existing)
- observability_keys.md fully updated for Phases 1-4
- ADK limitation discovered and documented (OBS_TOTAL_EXECUTION_TIME persistence)
- No source code modifications needed (all obs keys already written correctly)
