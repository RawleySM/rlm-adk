# RLM ADK Architecture Summary

This document summarizes the runtime flow from `reasoning_agent` to worker execution through the REPL bridge, including data contracts, retry behavior, and state/observability propagation.

## 1. End-to-End Flow

1. App assembly builds the root orchestrator and reasoning agent:
   - `create_reasoning_agent` configures the reasoning model and output key (`reasoning_output`) (`rlm_adk/agent.py:151`).
   - `create_rlm_orchestrator` wraps it in `RLMOrchestratorAgent` (`rlm_adk/agent.py:229`).
   - App/runner entrypoints wire this into ADK (`rlm_adk/agent.py:326`, `rlm_adk/agent.py:389`).
2. Orchestrator runtime starts in `RLMOrchestratorAgent._run_async_impl` (`rlm_adk/orchestrator.py:99`).
3. Orchestrator initializes:
   - `LocalREPL` with helper functions and shared trace holder (`rlm_adk/orchestrator.py:110`, `rlm_adk/orchestrator.py:121`).
   - Worker pools and dispatch closures via `create_dispatch_closures(...)` (`rlm_adk/orchestrator.py:123`, `rlm_adk/dispatch.py:222`).
   - REPL async query globals: `llm_query_async`, `llm_query_batched_async` (`rlm_adk/orchestrator.py:129`, `rlm_adk/repl/local_repl.py:210`).
4. Orchestrator creates `REPLTool`, mounts it onto the reasoning agent, then delegates to `reasoning_agent.run_async(ctx)` (`rlm_adk/orchestrator.py:152`, `rlm_adk/orchestrator.py:168`, `rlm_adk/orchestrator.py:210`).
5. Reasoning model tool-calls `execute_code`; ADK invokes `REPLTool.run_async(args, tool_context)` (`rlm_adk/tools/repl_tool.py:76`).
6. REPL tool chooses execution mode:
   - If code contains `llm_query*`, it rewrites sync calls to awaited async calls (`rewrite_for_async`) and uses async REPL execution (`rlm_adk/tools/repl_tool.py:108`, `rlm_adk/repl/ast_rewriter.py:161`, `rlm_adk/repl/local_repl.py:368`).
   - Otherwise it runs sync REPL execution (`rlm_adk/tools/repl_tool.py:119`, `rlm_adk/repl/local_repl.py:311`).
7. Rewritten `await llm_query_async(...)` and `await llm_query_batched_async(...)` calls enter dispatcher closures (`rlm_adk/dispatch.py:257`, `rlm_adk/dispatch.py:300`).
8. Dispatcher acquires workers from `WorkerPool`, assigns prompt carriers (`_pending_prompt`), and runs one worker or a `ParallelAgent` batch (`rlm_adk/dispatch.py:55`, `rlm_adk/dispatch.py:366`, `rlm_adk/dispatch.py:406`).
9. Worker callbacks bridge request/response:
   - `worker_before_model` injects prompt into request contents (`rlm_adk/callbacks/worker.py:55`).
   - `worker_after_model` captures text/usage and marks result ready (`rlm_adk/callbacks/worker.py:78`).
   - `worker_on_model_error` converts failure into structured error state (`rlm_adk/callbacks/worker.py:160`).
10. Dispatcher normalizes each worker output into `LLMResult`, preserving order, then cleans worker transient state and releases back to pool (`rlm_adk/dispatch.py:433`, `rlm_adk/types.py:50`, `rlm_adk/dispatch.py:592`).
11. REPL tool flushes dispatch counters into state, stores `LAST_REPL_RESULT`, and returns tool payload (`stdout`, `stderr`, `variables`, call counters) to reasoning loop (`rlm_adk/tools/repl_tool.py:168`, `rlm_adk/dispatch.py:625`, `rlm_adk/tools/repl_tool.py:200`).
12. After reasoning completes, orchestrator parses `reasoning_output`, extracts `FINAL_ANSWER`, emits final state delta, and stops (`rlm_adk/orchestrator.py:255`, `rlm_adk/orchestrator.py:286`, `rlm_adk/orchestrator.py:289`).

## 2. Primary Runtime Components

- `RLMOrchestratorAgent` (`rlm_adk/orchestrator.py:73`)
  - Owns lifecycle, retries of top-level reasoning run, startup/final state events, and answer extraction.
- `Reasoning Agent` (`rlm_adk/agent.py:151`)
  - Produces tool calls and final structured/text output under `reasoning_output`.
- `REPLTool` (`rlm_adk/tools/repl_tool.py:30`)
  - Tool boundary between ADK function-calls and local execution, with async AST bridge and state flush.
- `LocalREPL` (`rlm_adk/repl/local_repl.py:62`)
  - Persistent namespace execution engine for sync and async code.
- AST rewriter (`rlm_adk/repl/ast_rewriter.py:15`)
  - Converts `llm_query*` sync-style code to awaitable async code for ADK runtime dispatch.
- Dispatch layer + pool (`rlm_adk/dispatch.py:222`, `rlm_adk/dispatch.py:55`)
  - Plans batches, manages worker reuse/concurrency, and aggregates results/metrics.
- Worker callbacks (`rlm_adk/callbacks/worker.py:55`)
  - Request injection and response/error materialization onto worker carrier fields.
- Structured-output retry path (`rlm_adk/callbacks/worker_retry.py:74`)
  - Optional schema enforcement + bounded retries for worker outputs.

## 3. Data Contracts Across Boundaries

- Tool input: `execute_code(args={"code": <python-source>})` (`rlm_adk/tools/repl_tool.py:79`).
- REPL result object: `REPLResult(stdout, stderr, locals, execution_time, llm_calls, trace)` (`rlm_adk/types.py:165`).
- Worker prompt/result carriers (in-memory worker fields):
  - Inputs: `_pending_prompt`.
  - Outputs: `_result`, `_result_ready`, `_result_error`, `_call_record`, optional `_structured_result`.
  - References: `rlm_adk/dispatch.py:368`, `rlm_adk/dispatch.py:380`, `rlm_adk/callbacks/worker.py:121`.
- Worker return normalization: `LLMResult` includes content plus metadata (`error`, `error_category`, usage/model, optional `parsed`) (`rlm_adk/types.py:50`, `rlm_adk/dispatch.py:460`).
- Final answer extraction source: `ctx.session.state["reasoning_output"]` (`rlm_adk/orchestrator.py:255`).

## 4. Retry, Timeout, and Termination Semantics

- Top-level reasoning retries: transient 408/429/5xx/network classes retried with exponential backoff; exhaustion sets terminal error and stop (`rlm_adk/orchestrator.py:54`, `rlm_adk/orchestrator.py:206`, `rlm_adk/orchestrator.py:233`).
- Worker HTTP retry config at model layer: bounded attempts/backoff (`rlm_adk/dispatch.py:128`, `rlm_adk/dispatch.py:132`).
- Worker dispatch timeout: `RLM_WORKER_TIMEOUT` (default 180s) wraps single and parallel worker execution; timed-out workers are represented as error results rather than aborting the whole reasoning turn (`rlm_adk/dispatch.py:213`, `rlm_adk/dispatch.py:386`, `rlm_adk/dispatch.py:415`).
- Structured output retries: bounded (`max_retries=2`) with explicit exhaustion marker `SCHEMA_VALIDATION_EXHAUSTED` (`rlm_adk/dispatch.py:377`, `rlm_adk/dispatch.py:467`).
- REPL call-limit safeguard: `max_calls` enforces cap per run (`rlm_adk/tools/repl_tool.py:42`, `rlm_adk/tools/repl_tool.py:84`).

## 5. State and Observability Flow

- Orchestrator state deltas set startup context (`request_id`, depth, iteration, prompt/repo) and completion (`final_answer`, `should_stop`) (`rlm_adk/orchestrator.py:174`, `rlm_adk/orchestrator.py:187`, `rlm_adk/orchestrator.py:289`).
- Reasoning callbacks update context/token accounting around each reasoning model call (`rlm_adk/callbacks/reasoning.py:65`, `rlm_adk/callbacks/reasoning.py:128`).
- Dispatch `flush_fn` reports worker metrics (counts, latencies, category errors, timeout/rate-limit totals, pool exhaustion, schema failures) (`rlm_adk/dispatch.py:625`, `rlm_adk/dispatch.py:633`).
- REPL tool merges flush data into tool state and persists `LAST_REPL_RESULT` summary for downstream plugins/tracing (`rlm_adk/tools/repl_tool.py:170`, `rlm_adk/tools/repl_tool.py:185`).
- REPL trace object is shared between REPL tool and dispatcher and can be persisted by tracing plugin (`rlm_adk/orchestrator.py:121`, `rlm_adk/dispatch.py:329`, `rlm_adk/plugins/repl_tracing.py:23`).

## 6. Key Architectural Boundaries

- AST rewrite is a control-flow bridge (sync-style authoring to async execution), not a security sandbox.
- Worker callbacks are the core data bridge between ADK worker runs and dispatcher aggregation.
- `flush_fn` is the boundary where transient dispatch internals are converted into persisted/session-visible telemetry.
- Final orchestrator output is derived from `reasoning_output`; REPL worker metadata remains internal unless surfaced via metrics/trace state.
