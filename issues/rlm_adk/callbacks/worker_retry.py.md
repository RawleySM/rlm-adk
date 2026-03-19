# `rlm_adk/callbacks/worker_retry.py`

## Findings
1. High: successful `set_model_response` only creates `_rlm_terminal_completion` when `tool_response` is a `dict`. ADK also returns lists for list-of-model schemas and raw primitives for non-`BaseModel` schemas, so arbitrary schemas silently miss the canonical terminal completion path. Relevant lines: `rlm_adk/callbacks/worker_retry.py:166-197`.
2. Low: the file still mixes direct attribute assignment (`agent._structured_result`, `agent._structured_output_obs`) with the new `object.__setattr__()` discipline. That keeps the runtime attr handling inconsistent for Pydantic agents. Relevant lines: `rlm_adk/callbacks/worker_retry.py:49`, `rlm_adk/callbacks/worker_retry.py:175`.

## Legacy / dead code
1. None beyond the dict-only success branch; that branch is the main cleanup target because it preserves the old “structured output means dict payload” assumption.
