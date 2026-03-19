# `rlm_adk/plugins/sqlite_tracing.py`

## Findings
1. High: `after_run_callback()` still builds the authoritative trace summary from session-state `obs:*` keys instead of telemetry rows. That violates the new lineage-plane design and guarantees drift when state mirroring is removed. Relevant lines: `rlm_adk/plugins/sqlite_tracing.py:742-850`.
2. High: `_CURATED_PREFIXES` still captures broad `obs:*` telemetry into `session_state_events`, so session state remains a second lineage bus instead of “working state only.” Relevant lines: `rlm_adk/plugins/sqlite_tracing.py:67-145`.
3. Medium: `after_model_callback()` stores `custom_metadata["rlm"]` as JSON but does not project the lineage fields into the dedicated telemetry columns it added (`decision_mode`, `structured_outcome`, `terminal_completion`, etc.), leaving those columns mostly unused on model-call rows. Relevant lines: `rlm_adk/plugins/sqlite_tracing.py:1058-1100`.
4. Medium: tool-call telemetry still omits the full lineage scope. `before_tool_callback()` only inserts `tool_name`, `depth`, and `iteration`, but not `fanout_idx`, parent scope, branch, invocation/session IDs, or `output_schema_name`. Relevant lines: `rlm_adk/plugins/sqlite_tracing.py:1170-1204`.
5. Medium: `validated_output_json` is written from the generic `result` payload in `after_tool_callback()`, so retry/reflection payloads can be persisted as if they were validated terminal outputs. Relevant lines: `rlm_adk/plugins/sqlite_tracing.py:1264-1280`.

## Legacy / dead code
1. The old session-state categorization and curated-capture machinery is largely legacy if SQLite telemetry is meant to be the real lineage sink. The main removable surface starts at `rlm_adk/plugins/sqlite_tracing.py:67-145`.
