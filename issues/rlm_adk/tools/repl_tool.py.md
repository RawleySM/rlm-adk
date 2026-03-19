# `rlm_adk/tools/repl_tool.py`

## Findings
1. High: `last_repl_result.total_llm_calls` is hardcoded to `0` on every success, exception, and cancellation path. Any telemetry or REPL logic reading that field now sees a permanent false zero even when the code block dispatched children. Relevant lines: `rlm_adk/tools/repl_tool.py:258`, `rlm_adk/tools/repl_tool.py:288`, `rlm_adk/tools/repl_tool.py:313`.

## Legacy / dead code
1. The old dispatch-count reporting path was removed without replacing the count source. The remaining `total_llm_calls` field is now misleading and should either be recomputed correctly or dropped entirely.
