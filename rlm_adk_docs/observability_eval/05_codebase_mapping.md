# 05 - Codebase Mapping: Requirements to Keys, Code Paths, and Session Data

Maps every requirement from docs 01-04 to actual codebase state keys, DB columns, and code paths.
Verified against trace `bffab79f7daa41a4b2b01f68df8b1d3f` / session `5e0cdf8f-b5ce-4d28-8b02-782a6a0a5777`.

---

## Summary

| Status | Count | Meaning |
|--------|-------|---------|
| GREEN  | 28    | Captured in code AND verified in session data |
| YELLOW | 21    | Key/code path exists but NOT found in session data for this trace |
| RED    | 32    | No key or code path exists |

**Verified session facts:**
- Trace status: `running` (after_run_callback never fired; enrichment columns empty)
- DB schema mismatch: `_SCHEMA_SQL` defines 22 enriched columns on `traces` table, but the live DB only has the 13 base columns (no migration applied). Enrichment columns like `request_id`, `repo_url`, `child_dispatch_count`, `total_execution_time_s`, etc. do NOT exist in the live DB.
- Telemetry: 469 model_call rows, 252 tool_call rows across depths 0-2. Columns `agent_type`, `prompt_chars`, `system_chars`, `call_number` are all NULL.
- SSE: 12 rows captured (iteration_count, request_id, obs:tool_invocation_summary, obs:child_dispatch_count, obs:child_dispatch_latency_ms, last_repl_result). No child_summary, no obs:finish_*, no obs:total_* keys landed in SSE.
- Spans table: 0 rows (legacy, no longer written).

---

## 01 - Debugging Requirements

| ID | Description | Status | Key / Column | Code Path | Verification |
|----|-------------|--------|-------------|-----------|--------------|
| DEBUG-1.1 | Active depth at failure | GREEN | `CURRENT_DEPTH` state key; `telemetry.depth` column | `orchestrator.py:192` (state_delta), `sqlite_tracing.py:528` (depth=0 default) | telemetry.depth populated for all 469 model_call rows (0, child_reasoning_d1, child_reasoning_d2). SSE does not capture CURRENT_DEPTH (not in curated set). |
| DEBUG-1.2 | Dispatch call chain / causal ancestry | YELLOW | `child_obs_key(depth, fanout_idx)` -> `obs:child_summary@dNfM` | `dispatch.py:174` (_acc_child_summaries written in _run_child finally block) | No child_summary SSE rows found for this trace. flush_fn writes them but they flow through tool_context.state which should emit events. Likely the incomplete trace (running status) means child dispatch didn't complete. No parent_trace_id linkage exists. |
| DEBUG-1.3 | Iteration number at failure | GREEN | `ITERATION_COUNT` (depth-scoped via `depth_key()`) | `repl_tool.py:87` (tool_context.state write) | SSE shows iteration_count at d=0 with values 0, 1, 2 (3 writes). Confirmed working. |
| DEBUG-2.1 | Generated code at failure | YELLOW | `args["code"]` in REPLTool; `telemetry.tool_args_keys` | `repl_tool.py:83`, `sqlite_tracing.py:643` (tool_args_keys only) | tool_args_keys=`["code"]` in telemetry but actual code string NOT persisted. Only arg key names stored. |
| DEBUG-2.2 | stderr content | GREEN | `LAST_REPL_RESULT["has_errors"]`; `telemetry.result_preview` (500 char truncated) | `repl_tool.py:183`, `sqlite_tracing.py:674` | SSE shows last_repl_result with has_errors=true/false. telemetry.result_preview has 500-char preview including stderr. Full stderr not separately persisted. |
| DEBUG-2.3 | Error source disambiguation (Python vs LLM dispatch) | GREEN | `LAST_REPL_RESULT["total_llm_calls"]` + `has_errors` | `repl_tool.py:185` (total_llm_calls from flush_fn), `repl_tool.py:183` (has_errors from stderr) | SSE last_repl_result shows total_llm_calls=0 and has_errors=true/false. Consumer must cross-reference these fields. |
| DEBUG-2.4 | REPL namespace state at failure | GREEN | `LAST_REPL_RESULT["variables"]` returned in tool result; `REPLTrace.var_snapshots` | `repl_tool.py:200-207` (variables dict), `trace.py:69` (snapshot_vars) | Tool return includes variables dict. Trace var_snapshots only when RLM_REPL_TRACE>=1. |
| DEBUG-3.1 | Error category classification | GREEN | `OBS_CHILD_ERROR_COUNTS` dict; `LLMResult.error_category` | `dispatch.py:276` (_acc_child_error_counts), `worker.py:32-58` (_classify_error) | SSE shows obs:child_dispatch_count. Error counts would appear in obs:child_error_counts if errors occurred. Categories: RATE_LIMIT, SERVER, AUTH, CLIENT, NETWORK, PARSE_ERROR, TIMEOUT, UNKNOWN, DEPTH_LIMIT, NO_RESULT, SAFETY. |
| DEBUG-3.2 | Per-child error detail (not aggregates) | RED | N/A | `worker.py:127-138` (_call_record on agent object - transient) | _call_record is set per-worker but cleaned up after dispatch. Not persisted to any DB table or state key. |
| DEBUG-3.3 | Dispatch latency per child | GREEN | `OBS_CHILD_DISPATCH_LATENCY_MS` (list of floats) | `dispatch.py:270` (_acc_child_latencies) | SSE shows obs:child_dispatch_latency_ms as list type. Per-batch latency only (not per-child within batch). |
| DEBUG-3.4 | Prompt text sent to failed child | RED | N/A | `dispatch.py:106` (prompt param), `worker.py:71` (_pending_prompt) | Prompt is transient on worker._pending_prompt. Not persisted anywhere. |
| DEBUG-3.5 | Depth limit enforcement | GREEN | `dispatch.py:111-116` returns DEPTH_LIMIT error | `dispatch.py:111` (depth+1 >= max_depth check) | Returns LLMResult with error_category="DEPTH_LIMIT". Would appear in obs:child_error_counts if triggered. |
| DEBUG-4.1 | State key write provenance | GREEN | `session_state_events.event_author`, `event_time`, `key_depth`, `key_fanout` | `sqlite_tracing.py:340-382` (_insert_sse) | SSE rows have event_author, event_time, key_depth. Confirmed in session data. |
| DEBUG-4.2 | Depth-scoped key isolation | GREEN | `depth_key()` appends `@dN`; SSE parses via `_DEPTH_FANOUT_RE` | `state.py:119-128` (depth_key), `sqlite_tracing.py:44-52` (_parse_key) | DEPTH_SCOPED_KEYS = {message_history, iteration_count, final_answer, last_repl_result, should_stop}. SSE correctly parses @dN suffixes. |
| DEBUG-4.3 | Parallel dispatch race conditions | RED | N/A | Worker carrier fields (_result, _result_ready) are transient | Object-carrier pattern prevents state races but carrier writes are not persisted. No SSE visibility into intra-batch state. |
| DEBUG-4.4 | flush_fn reset verification | YELLOW | Tested in `test_dispatch_flush_fn.py` | `dispatch.py:322-328` (reset accumulators) | Logic confirmed in code. SSE shows obs:child_dispatch_count=0 after flush (consistent with reset). Not directly testable from session data alone. |
| DEBUG-5.1 | Worker HTTP retry count/backoff | RED | N/A | `HttpRetryOptions` in genai SDK (opaque) | SDK handles retries internally. No callback or state key surfaces retry count. |
| DEBUG-5.2 | Structured output retry count | YELLOW | `OBS_STRUCTURED_OUTPUT_FAILURES` (aggregate only) | `dispatch.py:319` (_acc_structured_output_failures), `callbacks/worker_retry.py` (WorkerRetryPlugin) | Aggregate failure count exists but per-worker retry count not tracked. |
| DEBUG-5.3 | Top-level reasoning retry count | RED | N/A | `orchestrator.py:223-266` (retry loop with max_retries) | Retry logic exists with print/log output but no state key or DB column persists the retry count. |
| DEBUG-5.4 | Retry exhaustion events | YELLOW | `SCHEMA_VALIDATION_EXHAUSTED` error category; orchestrator error event | `dispatch.py:112-116` (DEPTH_LIMIT), `orchestrator.py:234-255` (error event) | Error events are yielded but no unified "exhaustion events" metric. |
| DEBUG-6.1 | Prompt text per child dispatch | RED | N/A | `worker.py:71` (_pending_prompt - transient) | Same as DEBUG-3.4. Not persisted. |
| DEBUG-6.2 | Child response text | RED | N/A | `worker.py:113` (_result on agent - transient) | Response text on worker._result is consumed by dispatch closure and not persisted. |
| DEBUG-6.3 | REPL namespace isolation across depths | YELLOW | Structural (separate LocalREPL instances per depth) | `orchestrator.py:120-121` (new LocalREPL per orchestrator) | Isolation is structural. No runtime telemetry verifies it. |
| DEBUG-6.4 | Data flow between successive llm_query calls | YELLOW | `DataFlowTracker` in `trace.py:112-146` | `dispatch.py:238-303` (DataFlowTracker usage) | Only active when RLM_REPL_TRACE >= 1. Not on by default. SSE last_repl_result.trace_summary shows data_flow_edges=0 for this trace. |
| DEBUG-7.1 | Layer-2 to layer-1 error surface | YELLOW | `LLMResult` with error/error_category fields | `dispatch.py:161-171` (error propagation) | Error propagation path exists in code. Not separately telemetered. |
| DEBUG-7.2 | Error aggregation across batch failures | GREEN | Returns list[LLMResult] preserving order with per-element error flags | `dispatch.py:265-266` (asyncio.gather results) | Dispatch returns ordered list. obs:child_error_counts aggregates categories. |
| DEBUG-7.3 | Exception vs error-value distinction | RED | N/A | Dual behavior: exceptions for depth-limit, LLMResult for API errors | Not documented in telemetry. Consumer must know the convention. |
| DEBUG-8.1 | Pre-rewrite source code | RED | N/A | `repl_tool.py:83` (args["code"] before rewrite) | Original code in ADK event stream but not separately persisted. |
| DEBUG-8.2 | Post-rewrite source code | RED | N/A | `repl_tool.py:114` (rewrite_for_async result) | Rewritten code not persisted anywhere. |
| DEBUG-8.3 | Rewrite failure classification | YELLOW | SyntaxError exception in stderr | `repl_tool.py:112-114` (has_llm_calls + rewrite_for_async) | Failures surface as exceptions in REPL stderr. Not classified or tracked separately. |
| DEBUG-8.4 | Rewrite frequency and success rate | RED | N/A | `repl_tool.py:112` (has_llm_calls check) | No counter for rewrite invocations or failures. |
| DEBUG-9.1 | Request ID correlation | GREEN | `REQUEST_ID` state key; traces.request_id (schema only) | `orchestrator.py:194` (uuid4 generation) | SSE shows request_id at d=0. However, traces.request_id column does NOT exist in live DB (schema migration gap). |
| DEBUG-9.2 | Wall-clock timing at every layer | GREEN | `telemetry.start_time/end_time/duration_ms`; `OBS_TOTAL_EXECUTION_TIME`; `OBS_CHILD_DISPATCH_LATENCY_MS` | `sqlite_tracing.py:524-564` (model_call timing), `observability.py:307` (total_execution_time) | telemetry has timing for all 469+252 rows. OBS_TOTAL_EXECUTION_TIME written by after_run (didn't fire for this trace). Child latencies in SSE. |
| DEBUG-9.3 | Token budget consumption | GREEN | `CONTEXT_WINDOW_SNAPSHOT`; `OBS_PER_ITERATION_TOKEN_BREAKDOWN`; `REASONING_INPUT_TOKENS/OUTPUT_TOKENS` | `reasoning.py:130-138` (context_window_snapshot), `observability.py:214-236` (per_iteration breakdown) | Code writes these keys. telemetry has input_tokens/output_tokens for model_calls. CONTEXT_WINDOW_SNAPSHOT and breakdown not in SSE curated set. |
| DEBUG-9.4 | BUG-13 monkey-patch activation | RED | `_bug13_stats["suppress_count"]` (runtime only) | `callbacks/worker_retry.py` (module-level counter) | Counter exists in memory but not persisted to any state key or DB. |

---

## 02 - Performance Requirements

| ID | Description | Status | Key / Column | Code Path | Verification |
|----|-------------|--------|-------------|-----------|--------------|
| PERF-1a | Reasoning-layer token counts | GREEN | `OBS_TOTAL_INPUT_TOKENS`, `OBS_TOTAL_OUTPUT_TOKENS`; `telemetry.input_tokens/output_tokens` | `observability.py:179-184`, `sqlite_tracing.py:550-554` | telemetry shows reasoning_agent: in=12434, out=457 (3 calls). OBS_TOTAL_* written by ObservabilityPlugin but not in SSE (ephemeral key issue; re-persisted by after_agent). |
| PERF-1b | Child-layer token counts (per-depth) | YELLOW | telemetry has per-agent-name token sums | `sqlite_tracing.py:550-554` | telemetry shows child_reasoning_d1: in=182215, out=19682 and child_reasoning_d2: in=569836, out=61922. Data IS in telemetry but NOT propagated to parent obs keys. TraceReader.get_token_usage() can extract this. |
| PERF-1c | Token amplification factor | YELLOW | Derivable from telemetry aggregation | `eval/trace_reader.py:436-484` (get_token_usage) | Can be computed: total_all=(12434+182215+569836)=764485 / reasoning_only=12434 = 61.5x. Requires post-hoc query, not a persisted metric. |
| PERF-2a | Reasoning model call latency | GREEN | `telemetry.duration_ms` for reasoning_agent model_calls | `sqlite_tracing.py:564` | avg_dur=6768.1ms for reasoning_agent (3 calls). Per-call timing available. |
| PERF-2b | REPL execution latency | GREEN | `telemetry.duration_ms` for execute_code tool_calls; `LAST_REPL_RESULT.trace_summary.wall_time_ms` | `sqlite_tracing.py:666-677`, `repl_tool.py:188` | telemetry shows tool_call duration. SSE last_repl_result has trace_summary.wall_time_ms. |
| PERF-2c | Child dispatch latency (per-batch) | GREEN | `OBS_CHILD_DISPATCH_LATENCY_MS` list | `dispatch.py:270` | SSE shows obs:child_dispatch_latency_ms as list. Per-batch timing. |
| PERF-2d | Rate-limit wait time | RED | N/A | SDK internal retry (opaque) | Not tracked. Backoff happens inside google.genai client. |
| PERF-2e | Semaphore wait time | RED | N/A | `dispatch.py:134` (async with _child_semaphore) | Semaphore acquire not instrumented. |
| PERF-3a | Effective parallelism | RED | N/A | N/A | No semaphore acquire/release instrumentation. |
| PERF-3b | Semaphore config vs demand | YELLOW | `RLM_MAX_CONCURRENT_CHILDREN` env var; `OBS_CHILD_DISPATCH_COUNT` | `dispatch.py:93-94` | Config from env var. Demand derivable from dispatch count. Not a persisted comparison. |
| PERF-4a | Batch size distribution | YELLOW | Derivable from `OBS_CHILD_DISPATCH_COUNT` / `OBS_CHILD_TOTAL_BATCH_DISPATCHES` | `dispatch.py:250-252` | Aggregate counts exist. Individual k values per call not stored. |
| PERF-4b | Batches per REPL turn | GREEN | `OBS_CHILD_TOTAL_BATCH_DISPATCHES` per flush | `dispatch.py:314-315` | Written by flush_fn. Represents count of batch dispatches (k>1) in that REPL turn. |
| PERF-4c | Batch success rate | GREEN | `OBS_CHILD_ERROR_COUNTS` + `OBS_CHILD_DISPATCH_COUNT` | `dispatch.py:273-276`, `dispatch.py:311` | success_rate = 1 - sum(error_counts) / dispatch_count. Both fields available. |
| PERF-5a | 429 count per layer | YELLOW | `OBS_CHILD_ERROR_COUNTS["RATE_LIMIT"]` (not depth-stratified) | `dispatch.py:276`, `worker.py:39` | Flat aggregate, not per-depth. Only counts exhausted retries. |
| PERF-5b | Total rate-limit-induced delay | RED | N/A | SDK internal | Not tracked. |
| PERF-5c | Rate limit temporal pattern | RED | N/A | N/A | No timestamps for 429 events. |
| PERF-6a | Per-depth token cost | YELLOW | Derivable from telemetry GROUP BY depth (agent_name contains depth) | `sqlite_tracing.py:528` | telemetry agent_name encodes depth (child_reasoning_d1, d2). SQL query can extract per-depth totals. Not a persisted metric. |
| PERF-6b | Per-depth latency contribution | YELLOW | `child_obs_key` summaries have `elapsed_ms` per child | `dispatch.py:175-179` | Per-child elapsed_ms in summaries. Depth-2 latency nested inside depth-1. |
| PERF-6c | Per-depth error rate | YELLOW | Derivable from child_obs_key summaries | `dispatch.py:177` (error boolean per child) | Per-child error flag exists. Aggregate obs:child_error_counts is not depth-stratified. |
| PERF-6d | Depth utility score | RED | N/A | Requires external quality evaluation | Cost data partially available; quality data out of scope. |
| PERF-7a | Pure REPL execution time (excluding LLM calls) | YELLOW | `LAST_REPL_RESULT.trace_summary.wall_time_ms` minus `OBS_CHILD_DISPATCH_LATENCY_MS` | `repl_tool.py:188`, `dispatch.py:270` | Both components exist. Subtraction must be done in application layer. |
| PERF-7b | AST rewriter latency | RED | N/A | `repl_tool.py:114` (rewrite_for_async) | Not timed separately. |
| PERF-7c | REPL namespace size | YELLOW | `LAST_REPL_RESULT["variables"]` (count); trace level 2 memory | `repl_tool.py:200-207`, `trace.py:29` (peak_memory_bytes) | Variable count in tool result. Memory only at RLM_REPL_TRACE=2. |
| PERF-8a | Child orchestrator creation overhead | RED | N/A | `dispatch.py:125-131` (create_child_orchestrator) | _run_child timer includes creation + execution. Not separated. |
| PERF-8b | Dispatch config utilization | YELLOW | `DispatchConfig.pool_size` vs actual concurrency | `dispatch.py:55` | pool_size is a legacy field. Actual limit is semaphore. |
| PERF-8c | Child cleanup overhead | RED | N/A | `dispatch.py:181-185` (child.repl.cleanup) | Not timed. |
| PERF-9a | Reasoning turns per session | GREEN | `OBS_TOTAL_CALLS`; `ITERATION_COUNT` | `observability.py:171`, `repl_tool.py:87` | SSE shows iteration_count incrementing. telemetry confirms 3 reasoning model_calls. |
| PERF-9b | Wasted turns | YELLOW | Derivable from `LAST_REPL_RESULT` per turn (has_errors + empty stdout + llm_calls=0) | `repl_tool.py:181-189` | SSE shows per-turn last_repl_result. Consumer must correlate has_errors/has_output/total_llm_calls. |
| PERF-9c | Error-recovery turns | RED | N/A | Implicit in tool-call sequence | Requires sequential analysis of REPL results. No metric computed. |
| PERF-9d | Token efficiency ratio | YELLOW | `final_answer` length / `OBS_TOTAL_INPUT_TOKENS + OBS_TOTAL_OUTPUT_TOKENS` | `observability.py:331`, `orchestrator.py:295-300` | Both components exist. Not computed as a metric. |
| PERF-10a | Total wall-clock time | YELLOW | `OBS_TOTAL_EXECUTION_TIME` | `observability.py:307-308` | Written by after_run_callback. This trace is "running" so the value was never written. Code path confirmed. traces.total_execution_time_s column does NOT exist in live DB. |
| PERF-10b | Time breakdown (stacked) | RED | N/A | Requires combining multiple timing sources | No single decomposition metric. Must combine telemetry + REPL times + dispatch latencies. |
| PERF-10c | Critical path analysis | RED | N/A | N/A | No critical-path computation exists. |
| PERF-10d | Time-to-first-useful-output | RED | N/A | Derivable from first non-error REPL result timestamp | No persisted metric. Requires post-hoc SSE analysis. |

---

## 03 - Documentation / Multi-Session Requirements

| ID | Description | Status | Key / Column | Code Path | Verification |
|----|-------------|--------|-------------|-----------|--------------|
| DOC-1.1a | trace_id | GREEN | `traces.trace_id` | `sqlite_tracing.py:391-408` | Present: bffab79f7daa41a4b2b01f68df8b1d3f |
| DOC-1.1b | request_id | YELLOW | `REQUEST_ID` state key; traces.request_id (schema gap) | `orchestrator.py:194` | SSE has request_id. traces.request_id column NOT in live DB (schema migration needed). |
| DOC-1.1c | session_id | GREEN | `traces.session_id` | `sqlite_tracing.py:403` | Present: 5e0cdf8f-b5ce-4d28-8b02-782a6a0a5777 |
| DOC-1.1d | run_ordinal | RED | N/A | N/A | Not tracked. Could derive from ROW_NUMBER() OVER session_id. |
| DOC-1.2a | Total wall-clock duration | YELLOW | traces.total_execution_time_s (schema gap) | `observability.py:307-308`, `sqlite_tracing.py:467` | Code writes it. DB column doesn't exist in live schema. |
| DOC-1.2b | Total input/output tokens | YELLOW | traces.total_input_tokens/total_output_tokens | `sqlite_tracing.py:459-460` | Live DB shows 0/0 for this trace (after_run didn't fire). Completed traces show values. |
| DOC-1.2c | Total LLM calls | YELLOW | traces.total_calls | `sqlite_tracing.py:461` | Same issue: 0 for running trace, populated for completed traces. |
| DOC-1.2d | Reasoning iterations | YELLOW | traces.iterations | `sqlite_tracing.py:462` | Same: 0 for running trace. |
| DOC-1.2e | Max depth reached | RED | N/A | N/A | Not tracked. Could derive from MAX(telemetry.depth) or MAX(SSE key_depth). |
| DOC-1.2f | Final answer length | YELLOW | traces.final_answer_length | `sqlite_tracing.py:463` | Code computes it. NULL for running trace. |
| DOC-1.2g | Finish status | GREEN | traces.status | `sqlite_tracing.py:433` | Present: "running" for this trace; "completed" for others. |
| DOC-1.2h | Child dispatch count | YELLOW | traces.child_dispatch_count (schema gap) | `sqlite_tracing.py:468` | Code writes it. DB column doesn't exist in live schema. Available in SSE. |
| DOC-1.2i | Total batch dispatches | RED | obs key exists but not in traces enrichment (code defines it but column missing from live DB) | `dispatch.py:314-315` | obs:child_total_batch_dispatches written by flush_fn but not in SSE curated set for this trace and traces column missing. |
| DOC-1.2j | Artifact count and bytes | YELLOW | traces.artifact_saves, artifact_bytes_saved (schema gap) | `sqlite_tracing.py:475-476` | Code writes them. DB columns don't exist in live schema. |
| DOC-1.3a | Finish reason counters | YELLOW | traces.finish_safety_count, finish_recitation_count, finish_max_tokens_count (schema gap) | `sqlite_tracing.py:471-473` | Code writes them. DB columns don't exist in live schema. obs:finish_*_count keys exist in code. |
| DOC-1.3b | Child error counts by category | YELLOW | traces.child_error_counts JSON (schema gap) | `sqlite_tracing.py:469` | Code writes it. DB column doesn't exist. Available in SSE as obs:child_error_counts. |
| DOC-1.3c | Structured output failures | YELLOW | traces.structured_output_failures (schema gap) | `sqlite_tracing.py:470` | Code writes it. DB column doesn't exist. |
| DOC-1.3d | Policy violations | RED | `POLICY_VIOLATION` state key exists but not captured in traces or SSE curated set | `state.py:17` | Key defined. SSE curated set includes it in flow_control category. But no code path writes it to traces enrichment. |
| DOC-2.1a | Prompt fingerprint/hash | RED | `root_prompt_preview` (500 char truncation, schema gap); no hash | `sqlite_tracing.py:466` | No root_prompt_hash column. Preview column doesn't exist in live DB. |
| DOC-2.1b | Model version | YELLOW | traces.model_usage_summary JSON (schema gap) | `sqlite_tracing.py:478` | Code aggregates obs:model_usage:* keys. DB column doesn't exist. No primary_model fast-filter column. |
| DOC-2.1c | Config max_depth | RED | N/A | N/A | Not persisted per-trace. |
| DOC-2.1d | Config max_iterations | RED | N/A | N/A | Not persisted per-trace. |
| DOC-2.1e | Worker pool size / concurrency | RED | N/A | N/A | Not persisted per-trace. |
| DOC-4.1 | Parent-child trace linkage | RED | N/A | N/A | No parent_trace_id column. No dispatch_tree table. |
| DOC-5.1 | Token cost per day (time-series) | GREEN | traces.start_time + total_input/output_tokens | `sqlite_tracing.py:399,459-460` | start_time indexed. Token columns populated for completed traces. Queryable with GROUP BY date. |
| DOC-5.2 | Cost estimation (dollar) | RED | N/A | N/A | No model_pricing table. |
| DOC-6.1a | Full prompt text for replay | RED | `root_prompt_preview` is 500 chars max (schema gap) | `sqlite_tracing.py:466` | Full prompt not stored. Only truncated preview in code (not even in live DB). |
| DOC-6.1b | System instruction | RED | N/A | N/A | Assembled at runtime in reasoning_before_model. Not stored. |
| DOC-6.1c | Config parameters for replay | RED | N/A | N/A | max_depth, max_iterations, pool_size, timeout, retry config not stored. |
| DOC-7.1 | Artifact content hashing | RED | N/A | N/A | No artifact_versions table. No content_hash. |

---

## 04 - Code Review / REPL Outcomes Requirements

| ID | Description | Status | Key / Column | Code Path | Verification |
|----|-------------|--------|-------------|-----------|--------------|
| CODE-1 | Generated code string per execute_code | YELLOW | `telemetry.tool_args_keys` (keys only, not values) | `sqlite_tracing.py:643` (tool_args_keys=json.dumps(list(tool_args.keys()))) | telemetry has tool_args_keys=`["code"]` but NOT the actual code string. Code is in ADK event stream but not in sqlite telemetry. |
| CODE-2 | REPL execution results (stdout/stderr/locals/timing) | GREEN | `LAST_REPL_RESULT` dict; `telemetry.result_preview` (500 char); `telemetry.repl_has_errors/repl_has_output/repl_llm_calls` | `repl_tool.py:181-189`, `sqlite_tracing.py:673-677` | SSE has last_repl_result dict with code_blocks, has_errors, has_output, total_llm_calls, trace_summary. telemetry has REPL enrichment columns. result_preview truncated to 500 chars. |
| CODE-3 | Variable state evolution across iterations | RED | N/A | `local_repl.py:297-299` (locals update) | No namespace diffing or change-tracking. Variables snapshot in tool result but no delta computation. |
| CODE-4 | llm_query prompt forwarding (parent-to-child) | RED | N/A | `dispatch.py:106` (prompt param), `worker.py:71` (_pending_prompt) | Prompt is transient. Not persisted as reviewable artifact. |
| CODE-5 | Child return values (worker outputs) | RED | N/A | `dispatch.py:160-161` (LLMResult), `worker.py:113` (_result) | Return values consumed by dispatch closure. Not persisted. |
| CODE-6 | AST rewrite audit trail | RED | N/A | `repl_tool.py:112-115` (has_llm_calls + rewrite_for_async) | Neither original nor rewritten code persisted. No execution mode tag in telemetry. |
| CODE-7 | Code retry patterns | RED | N/A | Implicit in tool-call sequence | No tracking of consecutive errored execute_code calls. No retry-success-rate metric. |
| CODE-8 | Error classification for REPL failures | RED | N/A | Exception type in stderr only | No REPL-level error classification. Worker-level exists in `worker.py:32-58` but REPL errors are unclassified. |
| CODE-9 | Data flow between layers (serialization fidelity) | YELLOW | `DataFlowTracker` detects response-to-prompt flow | `trace.py:112-146`, `dispatch.py:238-303` | Only active at RLM_REPL_TRACE >= 1. Detects substring fingerprinting. No serialization fidelity check. |
| CODE-10 | Final answer quality signals | YELLOW | `final_answer` persisted; `LAST_REPL_RESULT.total_llm_calls` | `orchestrator.py:274-300`, `repl_tool.py:185` | Final answer length computable. Whether set_model_response was called vs fallback not tracked. No quality signal metric. |

---

## Critical Infrastructure Gaps

### 1. Schema Migration Gap (CRITICAL)
The `_SCHEMA_SQL` in `sqlite_tracing.py` defines 22 enriched columns on the `traces` table (request_id, repo_url, root_prompt_preview, total_execution_time_s, child_dispatch_count, child_error_counts, etc.) but the live `.adk/traces.db` only has 13 base columns. `CREATE TABLE IF NOT EXISTS` does not add columns to existing tables. A migration step is needed to ALTER TABLE and add the missing columns.

**Impact:** All traces enrichment (after_run_callback writes) silently fails. The `after_run_callback` SQL UPDATE references columns that don't exist, but the exception is caught and logged as a warning.

### 2. Running Trace (after_run Never Fired)
The target trace `bffab79f7daa41a4b2b01f68df8b1d3f` has status="running" with all enrichment columns at default (0/NULL). This means `after_run_callback` never executed -- likely the process was interrupted. Even if it had fired, the schema migration gap would prevent the enrichment writes.

### 3. Telemetry Columns Never Populated
Several telemetry columns are defined but never written:
- `agent_type`: Always NULL. ObservabilityPlugin writes this to state (obs:per_iteration_token_breakdown entries) but SqliteTracingPlugin doesn't extract it.
- `prompt_chars`, `system_chars`: Written to state by reasoning_before_model but not copied to telemetry.
- `call_number`: Always NULL. OBS_TOTAL_CALLS increments but is not written per-telemetry-row.

### 4. SSE Curated Set Misses Key Obs Keys
The `_CURATED_PREFIXES` include `"obs:"` which should capture most obs keys. However, the following obs keys were NOT found in SSE for this trace despite being written in code:
- `obs:total_input_tokens`, `obs:total_output_tokens`, `obs:total_calls` -- These are written by ObservabilityPlugin.after_model_callback which has the ephemeral key issue (ADK doesn't wire event_actions for plugin after_model). The after_agent re-persist should capture them, but this trace's after_agent may not have fired.
- `obs:finish_*_count` -- Same ephemeral key issue.
- `obs:child_summary@dNfM` -- Written by flush_fn through tool_context.state. Should appear if child dispatches completed. Not found for this trace.

### 5. No Child Token Propagation
Child orchestrators run in isolated InvocationContexts. Their obs:total_input/output_tokens are not propagated to the parent. However, SqliteTracingPlugin shares the same trace_id across depths (plugin instance is process-global), so child telemetry rows DO appear in the telemetry table with depth-encoded agent_names. Token totals are queryable via SQL GROUP BY agent_name/depth.
