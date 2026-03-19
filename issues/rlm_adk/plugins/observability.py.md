# `rlm_adk/plugins/observability.py`

## Findings
1. Medium: the plugin still uses session state as a telemetry bus and keeps the old “re-persist in `after_agent_callback()`” workaround alive. That directly conflicts with the refactor’s “SQLite + custom metadata is the lineage plane” contract. Relevant lines: `rlm_adk/plugins/observability.py:72-111`, `rlm_adk/plugins/observability.py:129-188`.
2. Medium: `reasoning_before_model()` now publishes request metadata on `agent._rlm_pending_request_meta`, but `ObservabilityPlugin` never consumes it. That drops the request-side context the workflow doc explicitly called out during sequencing. Relevant lines: producer `rlm_adk/callbacks/reasoning.py:169-188`, missing consumer `rlm_adk/plugins/observability.py:129-188`.

## Legacy / dead code
1. `_SUMMARY_COUNTER_KEYS` plus the repersistence loop are legacy workaround code and can be deleted once this plugin stops acting as a second telemetry path. Relevant lines: `rlm_adk/plugins/observability.py:72-79`, `rlm_adk/plugins/observability.py:91-98`.
