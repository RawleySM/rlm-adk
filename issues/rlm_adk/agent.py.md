# `rlm_adk/agent.py`

## Findings
1. Medium: child lineage drops `parent_fanout_idx` completely. `create_child_orchestrator()` hardcodes `parent_fanout_idx=None`, so nested batched dispatches cannot reconstruct the full parent scope in lineage or telemetry. Relevant lines: `rlm_adk/agent.py:395-396`.

## Legacy / dead code
1. No additional dead-code finding in this file beyond the missing parent fanout plumbing.
