# RLM ADK Architecture Summary

This document summarizes the runtime flow from `reasoning_agent` to child orchestrator dispatch through the REPL bridge, including data contracts, retry behavior, and state/observability propagation.

## 1. End-to-End Flow

1. App assembly builds the root orchestrator and reasoning agent:
   - `create_reasoning_agent` configures the reasoning model and output key (`reasoning_output`) (`rlm_adk/agent.py:151`).
   - `create_rlm_orchestrator` wraps it in `RLMOrchestratorAgent` (`rlm_adk/agent.py:233`).
   - App/runner entrypoints wire this into ADK (`rlm_adk/agent.py:384`, `rlm_adk/agent.py:443`).
2. Orchestrator runtime starts in `RLMOrchestratorAgent._run_async_impl` (`rlm_adk/orchestrator.py:106`).
3. Orchestrator initializes:
   - `LocalREPL` with helper functions and shared trace holder (`rlm_adk/orchestrator.py:118`, `rlm_adk/orchestrator.py:128`).
   - `DispatchConfig` and dispatch closures via `create_dispatch_closures(...)` (`rlm_adk/orchestrator.py:136`, `rlm_adk/dispatch.py:68`).
   - REPL async query globals: `llm_query_async`, `llm_query_batched_async` (`rlm_adk/orchestrator.py:142`, `rlm_adk/repl/local_repl.py:210`).
4. Orchestrator creates `REPLTool`, mounts it onto the reasoning agent, then delegates to `reasoning_agent.run_async(ctx)` (`rlm_adk/orchestrator.py:161`, `rlm_adk/orchestrator.py:179`, `rlm_adk/orchestrator.py:228`).
5. Reasoning model tool-calls `execute_code`; ADK invokes `REPLTool.run_async(args, tool_context)` (`rlm_adk/tools/repl_tool.py:86`).
6. REPL tool chooses execution mode:
   - If code contains `llm_query*`, it rewrites sync calls to awaited async calls (`rewrite_for_async`) and uses async REPL execution (`rlm_adk/tools/repl_tool.py:118`, `rlm_adk/repl/ast_rewriter.py:161`, `rlm_adk/repl/local_repl.py:368`).
   - Otherwise it runs sync REPL execution (`rlm_adk/tools/repl_tool.py:137`, `rlm_adk/repl/local_repl.py:311`).
7. Rewritten `await llm_query_async(...)` and `await llm_query_batched_async(...)` calls enter dispatcher closures (`rlm_adk/dispatch.py:196`, `rlm_adk/dispatch.py:228`).
8. Dispatcher spawns child orchestrators via `_run_child()` (`rlm_adk/dispatch.py:106`):
   - `create_child_orchestrator(model, depth+1, prompt, worker_pool, output_schema)` builds a full `RLMOrchestratorAgent` at depth+1 with its own reasoning agent and REPL (`rlm_adk/agent.py:274`).
   - For single queries, `llm_query_async` delegates to `llm_query_batched_async` which runs one child.
   - For batched queries (`llm_query_batched_async`), K children run concurrently via `asyncio.gather`, with concurrency limited by `_child_semaphore` (default 3, configurable via `RLM_MAX_CONCURRENT_CHILDREN`).
9. Each child orchestrator runs its full lifecycle: REPL setup, reasoning agent delegation, and answer extraction -- identical to the root orchestrator but at increased depth.
10. `_run_child` reads the child's result from its `output_key` in session state (`ctx.session.state[f"reasoning_output@d{depth+1}"]`), parses the final answer from JSON or plain text, and returns an `LLMResult` (`rlm_adk/dispatch.py:142`).
11. REPL tool flushes dispatch counters into state, stores `LAST_REPL_RESULT`, and returns tool payload (`stdout`, `stderr`, `variables`, call counters) to reasoning loop (`rlm_adk/tools/repl_tool.py:187`, `rlm_adk/dispatch.py:314`, `rlm_adk/tools/repl_tool.py:224`).
12. After reasoning completes, orchestrator parses `reasoning_output`, extracts `FINAL_ANSWER`, emits final state delta, and stops (`rlm_adk/orchestrator.py:283`, `rlm_adk/orchestrator.py:306`, `rlm_adk/orchestrator.py:319`).

## 2. Primary Runtime Components

- `RLMOrchestratorAgent` (`rlm_adk/orchestrator.py:78`)
  - Owns lifecycle, retries of top-level reasoning run, startup/final state events, and answer extraction. Used for both root (depth=0) and child (depth>0) orchestrators.
- `Reasoning Agent` (`rlm_adk/agent.py:151`)
  - Produces tool calls and final structured/text output under `reasoning_output` (or depth-suffixed `reasoning_output@d{N}` for children).
- `REPLTool` (`rlm_adk/tools/repl_tool.py:34`)
  - Tool boundary between ADK function-calls and local execution, with async AST bridge and state flush. Tracks AST rewrite instrumentation (`OBS_REWRITE_COUNT`, `OBS_REWRITE_TOTAL_MS`).
- `LocalREPL` (`rlm_adk/repl/local_repl.py:176`)
  - Persistent namespace execution engine for sync and async code.
- AST rewriter (`rlm_adk/repl/ast_rewriter.py:15`)
  - Converts `llm_query*` sync-style code to awaitable async code for ADK runtime dispatch.
- Dispatch layer (`rlm_adk/dispatch.py:68`)
  - `DispatchConfig` (aliased as `WorkerPool` for backward compatibility) holds model config. `create_dispatch_closures()` returns 3-tuple of `(llm_query_async, llm_query_batched_async, flush_fn)`. Spawns child `RLMOrchestratorAgent` instances at depth+1 via `_run_child()`, with semaphore-limited concurrency.
- Child orchestrator factory (`rlm_adk/agent.py:274`)
  - `create_child_orchestrator()` builds a depth+1 orchestrator with condensed instructions (no repomix), depth-suffixed output keys, and shared `DispatchConfig`.
- Worker callbacks (`rlm_adk/callbacks/worker.py:32`)
  - Error classification via `_classify_error()` used by dispatch for child error categorization.
- Structured-output retry path (`rlm_adk/callbacks/worker_retry.py:74`)
  - `make_worker_tool_callbacks()` returns `(after_tool_cb, on_tool_error_cb)` wired onto the reasoning agent for `set_model_response` validation. BUG-13 monkey-patch (`_patch_output_schema_postprocessor`, line 167) suppresses premature agent termination.

## 3. Data Contracts Across Boundaries

- Tool input: `execute_code(args={"code": <python-source>})` (`rlm_adk/tools/repl_tool.py:86`).
- REPL result object: `REPLResult(stdout, stderr, locals, execution_time, llm_calls, trace)` (`rlm_adk/types.py:165`).
- Child dispatch result flow:
  - Child orchestrators write their final answer to a depth-suffixed output_key: `ctx.session.state[f"reasoning_output@d{depth+1}"]`.
  - `_run_child()` reads this key, parses JSON (ReasoningOutput) or plain text, and wraps the answer in `LLMResult` (`rlm_adk/dispatch.py:142`).
  - Errors are caught and classified via `_classify_error()`, returned as `LLMResult(error=True, error_category=cat)`.
  - Per-child observability summaries are accumulated in `_acc_child_summaries` keyed by `child_obs_key(depth+1, fanout_idx)`.
- `LLMResult(str)` subclass: carries `error`, `error_category`, `http_status`, `finish_reason`, token counts, `model`, `wall_time_ms`, and optional `parsed` (validated structured output) (`rlm_adk/types.py:50`).
- Final answer extraction source: `ctx.session.state["reasoning_output"]` (root) or `ctx.session.state[f"reasoning_output@d{N}"]` (children) (`rlm_adk/orchestrator.py:283`).

## 4. Retry, Timeout, and Termination Semantics

- Top-level reasoning retries: transient 408/429/5xx/network classes retried with exponential backoff; exhaustion sets terminal error and stop (`rlm_adk/orchestrator.py:56`, `rlm_adk/orchestrator.py:226`, `rlm_adk/orchestrator.py:256`).
- Depth limit enforcement: `max_depth` (default 3, configurable via `RLM_MAX_DEPTH`) prevents infinite recursion. Child dispatches beyond the limit return `LLMResult(error=True, error_category="DEPTH_LIMIT")` (`rlm_adk/dispatch.py:113`).
- Child dispatch concurrency: `_child_semaphore` (default 3, configurable via `RLM_MAX_CONCURRENT_CHILDREN`) limits concurrent child orchestrators per batch (`rlm_adk/dispatch.py:96`).
- Structured output retries: `make_worker_tool_callbacks(max_retries=2)` wired onto reasoning agent for `set_model_response` validation. BUG-13 monkey-patch suppresses ADK's premature termination on retry signals (`rlm_adk/callbacks/worker_retry.py:167`).
- REPL call-limit safeguard: `max_calls` enforces cap per run (`rlm_adk/tools/repl_tool.py:42`, `rlm_adk/tools/repl_tool.py:94`).

## 5. State and Observability Flow

- Orchestrator state deltas set startup context (`request_id`, depth, iteration, prompt/repo) and completion (`final_answer`, `should_stop`) (`rlm_adk/orchestrator.py:192`, `rlm_adk/orchestrator.py:205`, `rlm_adk/orchestrator.py:319`).
- Reasoning retry count: `OBS_REASONING_RETRY_COUNT` emitted via state_delta when transient retries occur (`rlm_adk/orchestrator.py:271`).
- Reasoning callbacks update context/token accounting around each reasoning model call (`rlm_adk/callbacks/reasoning.py:74`, `rlm_adk/callbacks/reasoning.py:143`).
- Dispatch `flush_fn` reports child metrics (dispatch counts, latencies, error counts by category, batch dispatch totals, structured output failures, BUG-13 suppress count, per-child summaries) (`rlm_adk/dispatch.py:314`).
- AST rewrite instrumentation: `OBS_REWRITE_COUNT` and `OBS_REWRITE_TOTAL_MS` written to `tool_context.state` before execution begins (survives execution errors) (`rlm_adk/tools/repl_tool.py:128`).
- REPL tool merges flush data into tool state and persists `LAST_REPL_RESULT` summary for downstream plugins/tracing (`rlm_adk/tools/repl_tool.py:187`, `rlm_adk/tools/repl_tool.py:204`).
- REPL trace object is shared between REPL tool and dispatcher and can be persisted by tracing plugin (`rlm_adk/orchestrator.py:128`, `rlm_adk/dispatch.py:244`, `rlm_adk/plugins/repl_tracing.py:23`).
- Session report CLI (`rlm_adk/eval/session_report.py`): Queries all 4 SQLite tables (traces, telemetry, session_state_events, spans) for a given trace_id and produces structured JSON reports for debugging and performance analysis.
- SQLite tracing plugin (`rlm_adk/plugins/sqlite_tracing.py:243`): 4-table schema with `_migrate_schema()` (line 311) for forward-compatible migrations; columns include `config_json`, `prompt_hash`, `max_depth_reached`.

## 6. Key Architectural Boundaries

- AST rewrite is a control-flow bridge (sync-style authoring to async execution), not a security sandbox.
- Child orchestrators are the dispatch boundary: each sub-query gets a full orchestrator (REPL + reasoning agent + tools) at depth+1, sharing the `DispatchConfig` and session state but with isolated REPL namespaces and depth-suffixed output keys.
- `flush_fn` is the boundary where transient dispatch internals are converted into persisted/session-visible telemetry.
- Final orchestrator output is derived from `reasoning_output` (or depth-suffixed variant); child dispatch metadata remains internal unless surfaced via flush_fn metrics/trace state.
- Depth limit (`max_depth`) is the recursion safety boundary, enforced at the start of `_run_child()` before any child orchestrator is created.
