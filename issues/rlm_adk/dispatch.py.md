# `rlm_adk/dispatch.py`

## Findings
1. High: child completion normalization still assumes structured results are dicts. `CompletionEnvelope.validated_output` is discarded for list and primitive schemas, so arbitrary child schemas lose parsed payloads and are downgraded to plain text. Relevant lines: `rlm_adk/dispatch.py:286-292`, `rlm_adk/dispatch.py:336-345`, `rlm_adk/dispatch.py:553-565`.
2. High: the refactor removed flushing, but most accumulator and per-child summary machinery is still alive. `_acc_child_*`, `_cum_child_*`, and `_acc_child_summaries` are populated but never emitted, so they are dead overhead and any trace/reporting path still expecting them now sees stale zeros. Relevant lines: `rlm_adk/dispatch.py:194-207`, `rlm_adk/dispatch.py:657-739`, `rlm_adk/dispatch.py:883-892`.
3. Medium: `_read_child_completion()` still mines nested observability from child state via `OBS_REASONING_RETRY_*` and `OBS_CHILD_*` keys, which keeps state in the lineage path even though the refactor explicitly moved lineage off session state. Relevant lines: `rlm_adk/dispatch.py:304-333`, `rlm_adk/dispatch.py:347-376`, `rlm_adk/dispatch.py:404-473`.
4. Medium: `_run_child()` still does not pass `parent_fanout_idx` into the child orchestrator even though the closure already captured `_parent_fanout_idx`. Nested batched dispatches therefore lose parent fanout lineage at the child-agent boundary. Relevant lines: `rlm_adk/dispatch.py:201`, `rlm_adk/dispatch.py:509-517`.
5. Medium: child `LLMResult` objects now lose most response metadata. `_read_child_completion()` does not return `finish_reason`, token counts, or visible/thought text, and `_run_child()` rebuilds `LLMResult` without them, even though the plan explicitly said the child result path should keep those `LLMResult` fields. Relevant lines: `rlm_adk/dispatch.py:297-334`, `rlm_adk/dispatch.py:340-376`, `rlm_adk/dispatch.py:397-434`, `rlm_adk/dispatch.py:553-566`.
6. Low: the per-child summary path still uses legacy structured-output outcome values like `retry_recovered` and `missing`, which no longer match the refactor’s simplified lineage outcome set. Relevant lines: `rlm_adk/dispatch.py:642-655`.

## Legacy / dead code
1. `_serialize_child_payload()` is now unused and can be removed. Relevant lines: `rlm_adk/dispatch.py:247-256`.
2. `child_obs_key(...)`-driven child summary construction is dead baggage unless those summaries are persisted somewhere new. Relevant lines: `rlm_adk/dispatch.py:657-739`.
