# Recursive REPL Report - State Collision Analysis

## Collision Surface
- Orchestrator writes unsuffixed `current_depth`, `iteration_count`, `request_id` into shared session state at run start ([orchestrator.py:174](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py:174)).
- `REPLTool` writes unsuffixed `iteration_count` and `last_repl_result` every tool invocation ([repl_tool.py:83](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py:83), [repl_tool.py:185](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py:185)).
- Orchestrator completion/error paths write unsuffixed `final_answer` and `should_stop` ([orchestrator.py:289](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py:289), [orchestrator.py:317](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py:317)).
- Dispatch `flush_fn` writes global worker counters that are currently intended as aggregate metrics, but become ambiguous under recursion without lineage tags ([dispatch.py:633](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py:633)).

## Existing Guardrails (Not Applied)
- `DEPTH_SCOPED_KEYS` and `depth_key()` exist exactly for nested runs, but runtime paths do not use them yet ([state.py:117](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py:117), [state.py:125](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py:125)).

## Key Collision Risks Under Recursive Workers
1. Parent/child overwrite `iteration_count` causing premature call-limit stop or incorrect observability.
2. Child `final_answer` can overwrite parent final output before parent reasoning loop completes.
3. `should_stop=True` from child can terminate parent orchestration logic unexpectedly.
4. Child `last_repl_result` can hide parent trace summary, breaking `REPLTracingPlugin` interpretation.
5. Single global `request_id` prevents distinct span/session correlation for child runs.

## Proposed State Contract
- Depth-scope loop-local keys immediately:
  - `MESSAGE_HISTORY`, `ITERATION_COUNT`, `FINAL_ANSWER`, `LAST_REPL_RESULT`, `SHOULD_STOP`.
- Keep aggregate observability keys global but attach lineage dimensions in value payloads:
  - add `depth`, `worker_name`, `parent_request_id` fields when writing worker dispatch metrics.
- Introduce explicit lineage keys:
  - `lineage:stack` (list of request ids),
  - `lineage:depth` (current integer depth),
  - `lineage:root_request_id`.

## Migration Rule
- Reads/writes for any key in `DEPTH_SCOPED_KEYS` must pass through a resolver helper:
  - `resolve_state_key(base_key, depth)` => `depth_key(...)`.
- Ban direct literal writes of those keys in orchestrator/repl_tool/dispatch with lint-style tests.

## Required Tests
- Parent and child runs both set `final_answer` without collision.
- Child `should_stop` does not stop parent unless explicitly propagated.
- Two concurrent child workers at same depth use distinct scoped keys.
- Aggregated worker metrics remain cumulative and deterministic.
