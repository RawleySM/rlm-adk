# `rlm_adk/orchestrator.py`

## Findings
1. High: `_collect_completion()` still treats “validated structured output” as dict-only. Successful list and primitive schemas fall back to text mode, lose `validated_output`, and no longer follow the arbitrary-schema contract described in the refactor docs. Relevant lines: `rlm_adk/orchestrator.py:188-194`, `rlm_adk/orchestrator.py:218-234`.
2. Medium: the root reasoning agent drops its schema name when using the default `ReasoningOutput`, because `_rlm_output_schema_name` is only set from `self.output_schema`. That leaves root lineage/telemetry without the output schema name on the default path. Relevant lines: `rlm_adk/orchestrator.py:361-381`.
3. Medium: the orchestrator still seeds cumulative child-dispatch totals in session state even though dispatch no longer updates them. That preserves dead legacy state and makes trace aggregates look correct in shape while remaining wrong in value. Relevant lines: `rlm_adk/orchestrator.py:405-409`.
4. High: every child orchestrator still writes the global `CURRENT_DEPTH` key into shared session state. Because `current_depth` is not depth-scoped and is exposed through `_rlm_state`, a parent REPL turn after nested dispatch can observe the child’s depth instead of its own. Relevant lines: `rlm_adk/orchestrator.py:401-403`.
5. Medium: every orchestrator invocation generates and writes a fresh global `REQUEST_ID`, including children. That stomps the request correlation ID seeded by the policy/plugin path, so logs and SQLite trace summaries can end up attributed to the last child that started instead of the root user request. Relevant lines: `rlm_adk/orchestrator.py:401-405`.
6. Medium: skill-instruction seeding installs a `before_agent_callback` on `reasoning_agent` but the orchestrator never clears it in `finally`. Reused orchestrators can therefore leak a stale skill instruction into later invocations when the next run has no router output, and the ad hoc assignment also overwrites any pre-existing agent callback for that run. Relevant lines: `rlm_adk/orchestrator.py:420-442`, `rlm_adk/orchestrator.py:670-676`.

## Legacy / dead code
1. `_serialize_completion_payload()` is unused and can be removed. Relevant lines: `rlm_adk/orchestrator.py:96-105`.
