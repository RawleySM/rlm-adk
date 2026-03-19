# `rlm_adk/types.py`

## Findings
1. Low: `ReasoningObservability` and `parse_reasoning_output()` are legacy completion-era abstractions that the refactor intended to replace with `CompletionEnvelope` plus deterministic rendering. Relevant lines: `rlm_adk/types.py:29-68`.
2. Low: `render_completion_text()` claims to emit compact JSON but uses default `json.dumps(...)` formatting, so the output is deterministic but not actually compact. Relevant lines: `rlm_adk/types.py:316-334`.

## Legacy / dead code
1. The legacy `ReasoningObservability` path at `rlm_adk/types.py:29-68` can be removed once orchestrator/dispatch stop reparsing output-key payloads.
