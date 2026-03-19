# `tests_rlm_adk/test_dashboard_telemetry.py`

## Findings
1. Medium: the telemetry tests still assert only coarse legacy invariants such as “child rows exist at depth > 0” and “trace total_calls > 0”, but they never verify the new lineage columns introduced by the refactor: `fanout_idx`, parent scope, `branch`, `invocation_id`, `output_schema_name`, `decision_mode`, `structured_outcome`, `terminal_completion`, and `validated_output_json`. Relevant lines: `tests_rlm_adk/test_dashboard_telemetry.py:116-204`.

## Legacy / dead code
1. The GAP-02 wording is still anchored in the old “child state propagation” framing even though the test now checks telemetry rows instead. Relevant lines: `tests_rlm_adk/test_dashboard_telemetry.py:111-123`.
