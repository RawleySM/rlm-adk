# Performance Observability Requirements

Observability data needed to evaluate the efficiency, cost, and throughput of the RLM-ADK recursive dispatch architecture.

---

## 1. Token Economics Per Layer

### 1a. Reasoning-Layer Token Counts

- **What:** Input and output tokens consumed by the reasoning agent (depth=0) across all its model calls in a session.
- **Why:** The reasoning agent is the most expensive single consumer -- it sees the full context window (system prompt + conversation history + REPL results). Understanding its token budget is the baseline for cost analysis.
- **Metric:** Sum per session; per-call breakdown (histogram of input_tokens per reasoning call).
- **Where:** `obs:total_input_tokens`, `obs:total_output_tokens` (ObservabilityPlugin), `obs:per_iteration_token_breakdown` list entries with `agent_type=reasoning`.

### 1b. Child-Layer Token Counts (depth=1, depth=2)

- **What:** Input and output tokens consumed by each child orchestrator, broken down by depth level.
- **Why:** Token amplification is the core cost risk in recursive dispatch. If depth-1 children each spawn depth-2 children, total tokens can grow combinatorially. Knowing per-depth token totals reveals whether deeper layers are cost-effective.
- **Metric:** Sum per depth level; ratio of child tokens to reasoning tokens (amplification factor); per-child min/avg/max/p99.
- **Where:** Currently NOT directly available. Child orchestrators run in isolated InvocationContexts, so their `obs:total_input_tokens` / `obs:total_output_tokens` are not propagated to the parent. The `child_obs_key(depth, fanout_idx)` summaries in `_acc_child_summaries` capture elapsed_ms and error status but NOT token counts.

### 1c. Token Amplification Factor

- **What:** Ratio of total tokens (all layers combined) to reasoning-layer tokens alone.
- **Why:** A 10x amplification factor means the reasoning agent's 50K-token call spawns 500K tokens of child work. This directly determines whether recursive dispatch is economically viable.
- **Metric:** Scalar ratio per session: `total_all_layers / reasoning_only`.
- **Where:** Requires aggregating child token counts (see gap in 1b).

---

## 2. Latency Decomposition

### 2a. Reasoning Model Call Latency

- **What:** Wall-clock time for each reasoning agent model call (prompt submission to response received).
- **Why:** Reasoning calls are on the critical path -- every millisecond here is directly added to end-to-end latency.
- **Metric:** Per-call duration_ms; avg/p50/p99 across all reasoning calls in a session.
- **Where:** `REASONING_CALL_START` timestamp (reasoning_before_model) compared to reasoning_after_model timing. Also in `telemetry` table rows where `agent_type=reasoning`.

### 2b. REPL Execution Latency

- **What:** Wall-clock time from REPLTool.run_async entry to completion, excluding child dispatch wait time.
- **Why:** Pure REPL execution (code compilation, namespace eval, stdout capture) should be fast. If it is not, the bottleneck is in the REPL infrastructure rather than the LLM.
- **Metric:** Per-execution duration_ms; breakdown into pure-python-eval vs llm_query wait.
- **Where:** `last_repl_result.execution_time` (REPLResult), `telemetry` table tool_call rows for `execute_code` with `duration_ms`.

### 2c. Child Dispatch Latency (Per-Batch)

- **What:** Wall-clock time from batch dispatch start (`asyncio.gather` entry) to all children completing.
- **Why:** This is the dominant cost inside REPL execution when code calls `llm_query_batched`. It reveals whether the bottleneck is model inference time, semaphore contention, or rate limiting.
- **Metric:** Per-batch duration_ms list; avg/p50/p99; breakdown by batch size.
- **Where:** `obs:child_dispatch_latency_ms` (list of floats from flush_fn). Per-child elapsed_ms in `child_obs_key(depth, fanout_idx)` summaries.

### 2d. Rate-Limit Wait Time

- **What:** Total time spent blocked due to 429 responses and backoff delays.
- **Why:** Rate limiting can dominate latency but is invisible if only end-to-end time is measured. Separating rate-limit wait from useful inference time is critical for capacity planning.
- **Metric:** Sum per session; per-child backoff durations; fraction of total wall-clock time spent rate-limited.
- **Where:** Currently NOT directly tracked. The `HttpRetryOptions` retry loop in the SDK handles backoff internally without surfacing wait durations. 429 errors that exhaust retries appear in `obs:child_error_counts["RATE_LIMIT"]`, but successful retries (with their wait time) are invisible.

### 2e. Semaphore Wait Time

- **What:** Time each child task spends waiting to acquire `_child_semaphore` before execution begins.
- **Why:** If semaphore wait >> child execution time, the concurrency limit (`RLM_MAX_CONCURRENT_CHILDREN`) is the bottleneck and should be raised. If semaphore wait is near zero, concurrency is underutilized.
- **Metric:** Per-child semaphore_wait_ms; histogram; max.
- **Where:** Currently NOT tracked. The `async with _child_semaphore` in `_run_child` does not record acquisition time.

---

## 3. Concurrency Utilization

### 3a. Effective Parallelism

- **What:** For each batch dispatch, how many children actually ran concurrently vs the semaphore limit.
- **Why:** If `RLM_MAX_CONCURRENT_CHILDREN=3` but only 2 children ever run simultaneously (because one finishes before the third starts), the system is not utilizing available concurrency.
- **Metric:** Peak concurrent children per batch; avg concurrent children; semaphore utilization ratio (peak / max_concurrent).
- **Where:** Currently NOT tracked. Would require instrumenting semaphore acquire/release with timestamps.

### 3b. Semaphore Configuration vs Actual Demand

- **What:** The configured `RLM_MAX_CONCURRENT_CHILDREN` value vs the max batch size requested in a session.
- **Why:** If max_batch_size is always <= max_concurrent, the semaphore never blocks and is not a factor. If max_batch_size >> max_concurrent, batches are serialized and concurrency is the bottleneck.
- **Metric:** max(batch_sizes) vs RLM_MAX_CONCURRENT_CHILDREN; number of times semaphore blocked.
- **Where:** Batch sizes derivable from `obs:child_dispatch_count` and `obs:child_total_batch_dispatches`. Semaphore config from env var. Actual blocking count not tracked.

---

## 4. Batch Effectiveness

### 4a. Batch Size Distribution

- **What:** For each `llm_query_batched_async` call, the number of prompts submitted (k).
- **Why:** Small batches (k=1) get no parallelism benefit. Very large batches hit semaphore limits. The distribution reveals whether the reasoning agent's code is effectively using batched queries.
- **Metric:** Histogram of batch sizes; avg/median/max.
- **Where:** Derivable from per-REPL-turn `obs:child_dispatch_count` (total children) and `obs:child_total_batch_dispatches` (number of batch calls with k>1). Individual k values per call not directly stored.

### 4b. Batches Per REPL Turn

- **What:** How many separate batch dispatches occurred within a single REPL execution.
- **Why:** Multiple sequential batches in one REPL turn (e.g., a for-loop calling llm_query) serialize child work. A single large batch parallelizes it. This reveals code-level optimization opportunities.
- **Metric:** Count of batch dispatches per REPL turn (from flush_fn snapshots).
- **Where:** `obs:child_total_batch_dispatches` per flush. Individual dispatch timestamps in `obs:child_dispatch_latency_ms`.

### 4c. Batch Success Rate

- **What:** Fraction of children in each batch that succeeded vs errored.
- **Why:** A batch where 4/5 children succeed but 1 errors may still produce a useful result. A batch where 5/5 error is wasted compute.
- **Metric:** Per-batch success_rate; session-wide avg batch success rate.
- **Where:** `obs:child_error_counts` (aggregate errors) and `obs:child_dispatch_count` (total dispatches). Per-child error status in `child_obs_key(depth, fanout_idx)` summaries.

---

## 5. Rate Limit Impact

### 5a. 429 Count Per Layer

- **What:** Number of HTTP 429 (rate limit) responses received, broken down by depth.
- **Why:** Depth-1 children hitting rate limits delays reasoning. Depth-2 children hitting limits delays depth-1. Knowing where 429s concentrate guides API quota allocation.
- **Metric:** Count per depth; total across session.
- **Where:** `obs:child_error_counts["RATE_LIMIT"]` captures 429 errors that exhausted retries. Successful retries after initial 429 are NOT counted (SDK handles them transparently).

### 5b. Total Rate-Limit-Induced Delay

- **What:** Cumulative wall-clock time spent in backoff/retry due to 429 responses.
- **Why:** A session might have only 5 rate-limit events, but if each causes a 60-second backoff, that is 5 minutes of dead time.
- **Metric:** Sum of all backoff delays in seconds; fraction of total session time.
- **Where:** NOT currently tracked. The genai SDK's retry mechanism does not expose per-retry timing.

### 5c. Rate Limit Temporal Pattern

- **What:** Timestamps of 429 events relative to session start.
- **Why:** Burst patterns (all 429s in the first 10 seconds) indicate cold-start quota issues. Steady-state 429s indicate sustained over-provisioning.
- **Metric:** Time-series of 429 events; inter-arrival time histogram.
- **Where:** NOT currently tracked at the dispatch level. Would require logging 429 events with timestamps before retry.

---

## 6. Depth Cost Analysis

### 6a. Per-Depth Token Cost

- **What:** Total input + output tokens attributed to each depth level (0=reasoning, 1=child, 2=grandchild).
- **Why:** If depth-2 consumes 60% of total tokens but contributes only 10% of useful information, recursive dispatch past depth-1 is not cost-effective.
- **Metric:** Per-depth token sum; per-depth cost in dollars (using model pricing); per-depth percentage of total.
- **Where:** Requires child token propagation (see gap in 1b). Currently only depth-0 tokens are tracked in `obs:total_input_tokens` / `obs:total_output_tokens`.

### 6b. Per-Depth Latency Contribution

- **What:** Wall-clock time attributed to each depth level.
- **Why:** Even if deeper layers are cheap in tokens, they may dominate latency due to serialization.
- **Metric:** Per-depth sum of elapsed_ms; fraction of total `obs:total_execution_time`.
- **Where:** `child_obs_key(depth, fanout_idx)["elapsed_ms"]` for depth-1 children. Depth-2 latency is nested inside depth-1 elapsed_ms and not separately tracked.

### 6c. Per-Depth Error Rate

- **What:** Fraction of children at each depth that returned errors.
- **Why:** Higher error rates at deeper depths suggest the model struggles with narrower sub-tasks, or that depth increases rate-limit pressure.
- **Metric:** error_count / dispatch_count per depth.
- **Where:** `child_obs_key(depth, fanout_idx)["error"]` boolean per child. Aggregate `obs:child_error_counts` is not depth-stratified.

### 6d. Depth Utility Score

- **What:** A composite metric: (quality_improvement_from_depth_N) / (cost_of_depth_N).
- **Why:** The fundamental question: is adding depth-2 worth it? Requires both cost data (tokens, latency) and quality data (answer improvement).
- **Metric:** Requires external quality evaluation; cost side needs per-depth token counts.
- **Where:** Cost data partially in child summaries; quality data outside current observability scope.

---

## 7. REPL Overhead

### 7a. Pure REPL Execution Time (Excluding LLM Calls)

- **What:** Time spent in Python code execution, AST rewriting, namespace management -- everything except waiting for child LLM dispatches.
- **Why:** If REPL overhead is >10% of total REPL time, there may be optimization opportunities in the execution engine.
- **Metric:** `repl_execution_time - sum(child_dispatch_latencies)` per REPL turn; avg/max across session.
- **Where:** `last_repl_result.execution_time` minus sum of `obs:child_dispatch_latency_ms` entries for that turn.

### 7b. AST Rewriter Latency

- **What:** Time spent in `rewrite_for_async()` transforming sync llm_query calls to awaited async calls.
- **Why:** AST parsing and transformation on every REPL turn is overhead. If code blocks are large or complex, this could become measurable.
- **Metric:** Per-call duration_ms for AST rewrite; avg/max.
- **Where:** NOT currently tracked. The rewrite happens inside REPLTool.run_async before execution but is not timed separately.

### 7c. REPL Namespace Size

- **What:** Number of variables and total memory footprint of the persistent REPL namespace.
- **Why:** A growing namespace slows variable lookup and increases memory pressure. If the namespace accumulates large DataFrames or model outputs across turns, it can cause OOM.
- **Metric:** Variable count per turn; total memory (via `sys.getsizeof` or tracemalloc snapshot).
- **Where:** `last_repl_result.variables` (dict of variable names/summaries). Memory tracking available at REPL trace level 2 (`RLM_REPL_TRACE=2`).

---

## 8. Pool / Dispatch Efficiency

### 8a. Child Orchestrator Creation Overhead

- **What:** Time to construct a child orchestrator (agent factory, REPL setup, dispatch closure creation).
- **Why:** If child creation takes 50ms and you spawn 20 children, that is 1 second of overhead. Pre-warming or caching could help.
- **Metric:** Per-child creation_time_ms; avg/max.
- **Where:** NOT directly tracked. The `child_start` timer in `_run_child` includes both creation and execution. Would need a separate timer between `create_child_orchestrator()` call and `child.run_async()` start.

### 8b. Dispatch Config Utilization

- **What:** The configured `pool_size` vs actual number of concurrent children created.
- **Why:** `pool_size` in DispatchConfig is a legacy field. The actual concurrency limit is `RLM_MAX_CONCURRENT_CHILDREN` (semaphore). If these are misaligned, the config is misleading.
- **Metric:** Configured pool_size vs max children alive simultaneously.
- **Where:** `DispatchConfig.pool_size` vs peak semaphore waiters + active children.

### 8c. Child Cleanup Overhead

- **What:** Time spent in REPL cleanup (`child.repl.cleanup()`) after each child completes.
- **Why:** If cleanup is expensive (e.g., large namespace teardown), it delays semaphore release and blocks subsequent children.
- **Metric:** Per-child cleanup_time_ms.
- **Where:** NOT tracked. Cleanup happens in the `finally` block of `_run_child`.

---

## 9. Iteration Efficiency

### 9a. Reasoning Turns Per Session

- **What:** Total number of reasoning agent model calls before producing FINAL_ANSWER.
- **Why:** More turns = more tokens = more latency. A session that takes 15 turns to answer a simple question has poor iteration efficiency.
- **Metric:** Count per session; comparison to task complexity.
- **Where:** `obs:total_calls` (reasoning-level calls), `iteration_count` (orchestrator iteration counter).

### 9b. Wasted Turns

- **What:** Reasoning turns that produced no useful REPL execution (no-op code, syntax errors, repeated identical code).
- **Why:** Wasted turns consume tokens and latency without advancing toward the answer.
- **Metric:** Count of turns where REPL returned only errors or empty output; fraction of total turns.
- **Where:** `last_repl_result` per turn: check `has_errors=True` and `llm_calls=0` and empty stdout. `obs:per_iteration_token_breakdown` entries can be correlated with REPL results.

### 9c. Error-Recovery Turns

- **What:** Reasoning turns spent recovering from REPL errors (import failures, runtime exceptions, child dispatch errors).
- **Why:** Error recovery is expected but expensive. If 40% of turns are error recovery, the prompt or available tools may need improvement.
- **Metric:** Count of turns following an error turn that produce corrected code.
- **Where:** Sequential analysis of `last_repl_result` entries (error followed by success on similar code).

### 9d. Token Efficiency Ratio

- **What:** Ratio of tokens in the final answer to total tokens consumed across all layers.
- **Why:** A 200-token answer that consumed 500K tokens has a 0.04% efficiency ratio. This is a high-level "bang for buck" metric.
- **Metric:** `len(final_answer_tokens) / (total_input_tokens + total_output_tokens)`.
- **Where:** `final_answer` length from session state; `obs:total_input_tokens` + `obs:total_output_tokens` for reasoning layer (child tokens need gap-fill per 1b).

---

## 10. End-to-End Timeline

### 10a. Total Wall-Clock Time

- **What:** Time from orchestrator start to FINAL_ANSWER emission.
- **Why:** The single most important user-facing performance metric.
- **Metric:** Scalar seconds per session.
- **Where:** `obs:total_execution_time` (written by ObservabilityPlugin.after_run_callback). Note: this key does NOT appear in `get_session` final_state due to ADK limitation, but IS available to other plugins and in the SQLite `traces.total_execution_time_s` column.

### 10b. Time Breakdown (Stacked)

- **What:** Decomposition of total wall-clock time into: reasoning model calls, REPL pure execution, child dispatch wait, rate-limit backoff, overhead (everything else).
- **Why:** Identifies the dominant cost driver. If 80% of time is in child dispatch, optimize children. If 80% is reasoning, optimize the prompt.
- **Metric:** Per-category sum in seconds and percentage; stacked bar or waterfall chart.
- **Where:** Requires combining: reasoning call durations (telemetry table), REPL execution times (last_repl_result), child dispatch latencies (obs:child_dispatch_latency_ms). Rate-limit wait and overhead are residual (total - accounted categories).

### 10c. Critical Path Analysis

- **What:** The longest sequential chain of operations from start to finish.
- **Why:** Parallel operations (batch dispatch) do not extend the critical path -- only the slowest child in each batch matters. Understanding the critical path reveals which operations actually determine end-to-end latency.
- **Metric:** Critical path duration in ms; list of operations on the critical path.
- **Where:** Requires correlating timestamps: reasoning call -> REPL -> max(child_dispatch_latency per batch) -> next reasoning call. Per-child `elapsed_ms` from child summaries identifies the slowest child per batch.

### 10d. Time-to-First-Useful-Output

- **What:** Wall-clock time from session start to the first REPL execution that produces non-error output.
- **Why:** In interactive use, users care about responsiveness. A system that spends 60 seconds "thinking" before producing anything feels slow even if the total time is reasonable.
- **Metric:** Seconds from start to first successful REPL turn.
- **Where:** First `last_repl_result` with `has_errors=False` and non-empty stdout, correlated with `invocation_start_time`.

---

## Summary of Observability Gaps

The following data points are needed for performance evaluation but are NOT currently captured:

| Gap ID | Data Point | Current State | Impact |
|--------|-----------|---------------|--------|
| **PERF-GAP-1** | Child-layer token counts (per-depth) | Child InvocationContexts are isolated; tokens not propagated to parent | Blocks token amplification analysis, per-depth cost attribution, token efficiency ratio |
| **PERF-GAP-2** | Rate-limit backoff duration | SDK handles retries internally; wait time not surfaced | Cannot separate rate-limit delay from inference time |
| **PERF-GAP-3** | Semaphore wait time | `async with _child_semaphore` not instrumented | Cannot determine if concurrency limit is the bottleneck |
| **PERF-GAP-4** | Effective parallelism (concurrent child count) | No semaphore acquire/release instrumentation | Cannot verify concurrency utilization |
| **PERF-GAP-5** | AST rewriter latency | Rewrite not timed separately | Cannot quantify REPL infrastructure overhead |
| **PERF-GAP-6** | Child creation overhead | `_run_child` timer includes both creation and execution | Cannot separate orchestrator setup from inference |
| **PERF-GAP-7** | Per-batch individual k values | Only aggregate counts stored, not per-call batch sizes | Histogram of batch sizes requires inference from aggregates |
| **PERF-GAP-8** | 429 temporal pattern / retry-success timing | Only exhausted retries counted; successful retries invisible | Rate-limit impact understated |
| **PERF-GAP-9** | Depth-stratified error counts | `obs:child_error_counts` is flat (not per-depth) | Cannot compare error rates across depth levels |
| **PERF-GAP-10** | Child cleanup overhead | Not timed | Cannot quantify semaphore-blocking cleanup cost |
