# Debugging Observability Requirements

Enumeration of every observability data point valuable for diagnosing failures in the RLM-ADK recursive REPL agent system, from the perspective of a debugging engineer.

---

## 1. Layer Failure Attribution

When a recursive REPL run fails, the first question is always: **which layer failed, and what was the call chain that got there?**

### 1.1 Active Depth at Failure

- **What:** The `current_depth` value (0, 1, 2, ...) at the moment an error occurred.
- **Why:** Without this, a generic "LLM call failed" error is ambiguous -- it could be the root reasoning agent, a depth-1 child dispatched by `llm_query`, or a depth-2 grandchild. Knowing the depth immediately narrows the search space.
- **Where expected:** `CURRENT_DEPTH` in session state; `depth` column in `telemetry` table; depth suffix (`@dN`) on depth-scoped keys in `session_state_events`.

### 1.2 Dispatch Call Chain / Causal Ancestry

- **What:** A trace of the parent-child dispatch relationship: which layer-0 REPL code block triggered which layer-1 dispatch, and which layer-1 REPL code block triggered which layer-2 dispatch.
- **Why:** In a recursive system, errors propagate upward. If a layer-2 child fails, the layer-1 parent's `llm_query()` call returns an `LLMResult` with `error=True`. Without a causal chain, you cannot tell which specific `llm_query()` call in which REPL code block at which depth produced the failure. This is the single most important debugging signal for recursive dispatch.
- **Where expected:** Currently partially available via `child_obs_key(depth, fanout_idx)` keys (`obs:child_summary@d{depth}f{idx}`). However, there is no cross-depth linking -- you can see fanout at each depth independently, but cannot trace "layer-2 child #3 was spawned by layer-1 child #1's REPL code block #2." A `parent_trace_id` or `parent_dispatch_id` field would close this gap. The `telemetry` table records `depth` but not `parent_telemetry_id`.

### 1.3 Iteration Number at Failure

- **What:** The `iteration_count` (depth-scoped) when the failure occurred.
- **Why:** Failures on iteration 1 vs iteration 15 have very different implications. Early failures suggest prompt/setup issues; late failures suggest context window exhaustion or accumulated state corruption.
- **Where expected:** `ITERATION_COUNT` state key (depth-scoped via `depth_key()`); `iteration` column in `telemetry` table.

---

## 2. REPL Error Forensics

### 2.1 Generated Code at Failure

- **What:** The exact Python source code that was sent to `LocalREPL.run()` or `LocalREPL.run_async()` at the time of failure, including any AST-rewritten form.
- **Why:** The reasoning model generates arbitrary Python code. When execution fails, you need to see exactly what code was run -- not just the model's raw output (which may differ after AST rewriting). The pre-rewrite and post-rewrite forms are both needed to diagnose AST rewriter bugs vs model code-generation bugs.
- **Where expected:** `LAST_REPL_RESULT` dict contains `stdout`/`stderr`/`variables` but the original code string is passed through `REPLTool.run_async(args={"code": ...})`. The `telemetry` table captures `tool_args_keys` but not argument values. The code itself is available in the ADK event stream as tool call arguments but is not persisted to SQLite or obs state by default.

### 2.2 stderr Content

- **What:** The full stderr output from REPL execution.
- **Why:** Python tracebacks, import errors, and runtime exceptions all surface through stderr. This is the primary signal for diagnosing code execution failures. Truncation of stderr loses critical traceback information.
- **Where expected:** `LAST_REPL_RESULT["stderr"]` in session state. `result_preview` in `telemetry` table (truncated to 500 chars -- may lose deep tracebacks). `REPLTrace` objects (when `RLM_REPL_TRACE >= 1`).

### 2.3 Error Source Disambiguation (Python vs LLM Dispatch)

- **What:** Whether a REPL execution error came from Python runtime execution (syntax error, exception, import failure) or from an embedded `llm_query()` / `llm_query_batched()` call failing within the REPL code.
- **Why:** These require completely different debugging approaches. A Python error means the model generated bad code. An LLM dispatch error means the child model call failed (rate limit, timeout, safety filter, etc.). The fix paths diverge entirely.
- **Where expected:** `LAST_REPL_RESULT` contains both `stderr` (Python errors) and `llm_calls` count. The dispatch `flush_fn` output contains `OBS_CHILD_ERROR_COUNTS` which is non-empty only when LLM dispatch errors occurred. However, there is no single field that says "this REPL failure was caused by an LLM dispatch error vs a Python execution error." The consumer must cross-reference stderr content with dispatch error counts.

### 2.4 REPL Namespace State at Failure

- **What:** The set of variables in the REPL namespace at the time of failure, with their types and (for small values) their content.
- **Why:** REPL state is persistent across iterations. A variable set in iteration 3 may cause a NameError or type confusion in iteration 7. Seeing the full namespace helps diagnose state-dependent failures.
- **Where expected:** `LAST_REPL_RESULT["variables"]` captures the namespace snapshot after execution. `REPLTrace` (level 1+) captures variable snapshots per code block. Neither captures the namespace *before* execution of the failing block, which would be needed to see what state the code was operating on.

---

## 3. Child Dispatch Failures

### 3.1 Error Category Classification

- **What:** The classified error category for each failed child dispatch: `RATE_LIMIT`, `SERVER_ERROR`, `TIMEOUT`, `SAFETY`, `AUTH`, `UNKNOWN`, `SCHEMA_VALIDATION_EXHAUSTED`.
- **Why:** Each category implies a different remediation. Rate limits need backoff. Server errors may be transient. Timeouts suggest the child task is too complex. Safety filters indicate content policy violations. Schema exhaustion means the model cannot produce valid structured output.
- **Where expected:** `OBS_CHILD_ERROR_COUNTS` dict (category -> count) in session state; `child_error_counts` JSON column in `traces` table. Per-worker: `LLMResult.error_category` on the dispatch return value. Worker callback: `_classify_error()` in `callbacks/worker.py`.

### 3.2 Per-Child Error Detail (Not Just Aggregates)

- **What:** For each failed child in a batch, the specific error message, HTTP status code, and model response (if any).
- **Why:** `OBS_CHILD_ERROR_COUNTS` is an aggregate (`{"RATE_LIMIT": 2, "SERVER_ERROR": 1}`). When debugging, you need to know *which* child in a k=5 batch failed and what its specific error was. Two RATE_LIMIT errors may have different status codes (429 vs 503) or different retry-after headers.
- **Where expected:** `LLMResult` objects carry `error_category` and content text, but these are consumed by the dispatch closure and not persisted individually. The `_call_record` on each worker captures per-worker detail but is transient (cleaned up after dispatch). There is no per-child-per-batch error log in the persistence layer.

### 3.3 Dispatch Latency Per Child

- **What:** Wall-clock time for each individual child dispatch call.
- **Why:** A batch of k=3 children where one takes 170s and the others take 2s reveals a specific child prompt that is causing model slowness. Aggregate latency hides this.
- **Where expected:** `OBS_CHILD_DISPATCH_LATENCY_MS` is a list of per-dispatch latencies. This is good for single dispatches but for batched dispatches (`ParallelAgent`), the latency recorded is the wall-clock time for the entire batch, not per-child within the batch.

### 3.4 Prompt Text Sent to Failed Child

- **What:** The exact prompt string that was sent to the child LLM call that failed.
- **Why:** Prompt content directly affects model behavior. A prompt that triggers a safety filter or causes a timeout needs to be inspected. Without the prompt, you cannot reproduce or diagnose the failure.
- **Where expected:** The prompt is set on `worker._pending_prompt` and injected by `worker_before_model`. It is not persisted to any obs key or database table. It exists only transiently during dispatch execution. This is a significant debugging gap.

### 3.5 Depth Limit Enforcement

- **What:** Whether a dispatch was rejected because `current_depth >= max_depth`.
- **Why:** Depth limit hits are silent failures from the perspective of the REPL code -- the `llm_query()` call may raise or return an error, but without explicit tracking, it is unclear whether the failure was a depth limit vs a model error.
- **Where expected:** `APP_MAX_DEPTH` and `CURRENT_DEPTH` are in state. The dispatch closure checks depth before spawning a child orchestrator. If rejected, it should produce a specific error category (not lumped into `UNKNOWN`).

---

## 4. State Corruption Debugging

### 4.1 State Key Write Provenance

- **What:** For each state key mutation, which agent (by name and depth) wrote it, and at what time.
- **Why:** In a recursive system with parallel dispatch, multiple agents at different depths may write to state. If `obs:child_dispatch_count` has an unexpected value, you need to know whether it was written by the depth-0 flush_fn or leaked from a depth-1 child's flush_fn. State key collisions across depths are a class of bug that is invisible without provenance tracking.
- **Where expected:** `session_state_events` table captures `event_author`, `event_time`, `key_depth`, and `key_fanout`. This is the primary tool for state provenance debugging. The `state_key` + `key_depth` combination should uniquely identify the writer.

### 4.2 Depth-Scoped Key Isolation Verification

- **What:** Confirmation that `DEPTH_SCOPED_KEYS` (message_history, iteration_count, final_answer, last_repl_result, should_stop) are correctly scoped and do not collide across depths.
- **Why:** If depth-scoping fails, a depth-1 child writing `should_stop=True` could terminate the depth-0 orchestrator. This is a catastrophic state corruption bug.
- **Where expected:** `session_state_events` table with `key_depth` column. `depth_key()` function appends `@dN` suffix. Tests in `test_depth_key_scoping.py` validate isolation.

### 4.3 Parallel Dispatch Race Conditions

- **What:** Whether two workers in a `ParallelAgent` batch wrote to the same state key, and whether the final value is deterministic.
- **Why:** Workers in a parallel batch run concurrently. If two workers both write to the same carrier field or state key, the result depends on execution order. The object-carrier pattern (`_result`, `_result_ready`) was designed to prevent this, but regressions could reintroduce races.
- **Where expected:** `session_state_events` with timestamps would show two writes to the same key with very close timestamps. However, worker carrier fields are transient (not persisted to session_state_events), so intra-batch races on carrier fields are invisible to the persistence layer.

### 4.4 flush_fn Reset Verification

- **What:** Confirmation that `flush_fn()` resets accumulators to zero after each call, and that no stale accumulator data leaks across REPL iterations.
- **Why:** If accumulators are not reset, dispatch counts from iteration N will be added to iteration N+1's counts, producing inflated metrics. This was a previous bug pattern.
- **Where expected:** `test_dispatch_flush_fn.py` validates this. At runtime, comparing `OBS_CHILD_DISPATCH_COUNT` across iterations (via `session_state_events` sequence numbers) can reveal non-reset accumulators if values only increase.

---

## 5. Retry Loop Visibility

### 5.1 Worker HTTP Retry Count and Backoff

- **What:** For each child dispatch, how many HTTP-level retries occurred (408, 429, 5xx), what the backoff delays were, and whether retries were exhausted.
- **Why:** A child that succeeds after 3 retries with 60s total backoff is very different from one that succeeds on the first try. Retry exhaustion is the boundary between transient and permanent failure.
- **Where expected:** `HttpRetryOptions(attempts=3, initial_delay=1.0, max_delay=60.0)` configured in dispatch. However, the retry count and individual retry delays are handled inside the `google.genai` client and are not surfaced to the ADK callback layer. Only the final outcome (success or the last error) is visible. This is a significant observability gap -- retries happen silently inside the SDK.

### 5.2 Structured Output Retry Count

- **What:** For workers with `output_schema`, how many schema validation retries occurred before success or exhaustion.
- **Why:** A worker that needs 2 retries to produce valid JSON suggests a borderline prompt/schema combination. Exhaustion (`SCHEMA_VALIDATION_EXHAUSTED`) means the model fundamentally cannot satisfy the schema.
- **Where expected:** `WorkerRetryPlugin` extends `ReflectAndRetryToolPlugin` with `max_retries=2`. The retry count per-worker is not persisted -- only the aggregate `OBS_STRUCTURED_OUTPUT_FAILURES` count appears in state. Individual retry counts per-worker-per-batch would be valuable.

### 5.3 Top-Level Reasoning Retry Count

- **What:** How many times the orchestrator retried the entire reasoning agent run due to transient errors (408/429/5xx).
- **Why:** Knowing whether the system recovered from 0, 1, or 3 top-level retries indicates infrastructure reliability and whether the eventual result was "clean" or "recovered."
- **Where expected:** `RLMOrchestratorAgent._run_async_impl` has retry logic with exponential backoff. The retry count is logged but not persisted to a state key or database column.

### 5.4 Retry Exhaustion Events

- **What:** Explicit markers when any retry budget is fully exhausted -- HTTP retries, structured output retries, or top-level reasoning retries.
- **Why:** Exhaustion events are the transition from "transient error, system recovering" to "permanent failure, investigation needed." They should be high-visibility signals.
- **Where expected:** `SCHEMA_VALIDATION_EXHAUSTED` is a specific error marker in dispatch. HTTP retry exhaustion surfaces as the final error from the genai client. Top-level exhaustion sets terminal error state in the orchestrator. These are logged but not uniformly tracked as a single "exhaustion events" metric.

---

## 6. Prompt Chain Tracing

### 6.1 Prompt Text Per Child Dispatch

- **What:** The exact prompt string sent to each child orchestrator or worker via `llm_query()` / `llm_query_batched()`.
- **Why:** The REPL code constructs prompts dynamically. The prompt sent to a child is often derived from previous child results, REPL computation, or string formatting. Seeing the exact prompt is essential for reproducing failures and understanding model behavior.
- **Where expected:** The prompt is set on `worker._pending_prompt` and exists only transiently. It is not captured in any obs key, database table, or artifact. This is a major debugging gap for production failure analysis.

### 6.2 Child Response Text

- **What:** The full text response from each child LLM call.
- **Why:** The response is what the REPL code operates on. If the model returns unexpected content (e.g., refusal, off-topic text, malformed JSON), the downstream REPL code may fail in confusing ways. Seeing the response clarifies whether the failure is model-side or code-side.
- **Where expected:** `LLMResult` carries the response text, but it is returned to the REPL code and not persisted. The REPL namespace will contain whatever variable the result was assigned to (visible in `LAST_REPL_RESULT["variables"]`), but the raw LLM response text is not separately stored.

### 6.3 REPL Namespace Isolation Across Depths

- **What:** Confirmation that each depth level's `LocalREPL` instance has an independent namespace, and that variables from a depth-1 child are not leaking into the depth-0 namespace.
- **Why:** If namespaces leak, a variable defined in a child's REPL could shadow or corrupt a parent's variable, causing subtle and hard-to-reproduce bugs.
- **Where expected:** Each `RLMOrchestratorAgent` creates its own `LocalREPL` instance. Namespace isolation is structural (separate Python dicts), not enforced by state key scoping. There is no runtime check or telemetry for namespace leakage. Tests would need to explicitly verify isolation.

### 6.4 Data Flow Between Successive llm_query Calls

- **What:** When one `llm_query()` result is used as input to a subsequent `llm_query()` call, tracking this data dependency.
- **Why:** Multi-step REPL programs often chain LLM calls: `result1 = llm_query(prompt1)` then `result2 = llm_query(f"Given {result1}, ...")`. If result2 fails, knowing that it depended on result1's content helps trace the root cause.
- **Where expected:** `DataFlowTracker` in `rlm_adk/repl/trace.py` detects when one `llm_query` response feeds into the next prompt (REPL trace level 1+). This is only available when `RLM_REPL_TRACE >= 1` and is not on by default.

---

## 7. Error Propagation Tracing

### 7.1 Layer-2 to Layer-1 Error Surface

- **What:** When a depth-2 child fails, what error representation does the depth-1 parent's `llm_query()` call receive? Is it an `LLMResult` with `error=True`, a Python exception, or a timeout?
- **Why:** The error propagation path determines whether the depth-1 REPL code can handle the error gracefully (try/except) or whether it crashes. If the error surface is inconsistent (sometimes exception, sometimes error string), debugging is much harder.
- **Where expected:** `LLMResult` is the normalized error carrier. `error`, `error_category`, and content text fields carry failure info. The dispatch closure wraps timeout with `asyncio.TimeoutError` -> `LLMResult(error=True, error_category="TIMEOUT")`. But the specific propagation chain (depth-2 error -> depth-1 LLMResult -> depth-1 REPL stderr) is not traced end-to-end.

### 7.2 Error Aggregation Across Batch Failures

- **What:** In a `llm_query_batched(prompts, k=5)` call, if 3 of 5 children fail, what does the parent receive? A list of 5 `LLMResult` objects with 3 having `error=True`? Or does the entire batch fail?
- **Why:** Partial batch failures are common (e.g., 2 of 5 hit rate limits). The parent REPL code needs to handle partial results. Understanding the exact semantics is critical for debugging "some children failed" scenarios.
- **Where expected:** Dispatch returns a list of `LLMResult` objects, preserving order, with per-element error flags. The `OBS_CHILD_ERROR_COUNTS` aggregate captures category counts but not per-position failure maps. A per-batch results summary (position -> success/error) would aid debugging.

### 7.3 Exception vs Error-Value Distinction

- **What:** Whether a dispatch failure raises a Python exception in the REPL code or returns an `LLMResult` error value.
- **Why:** These have very different debugging signatures. Exceptions produce tracebacks in stderr. Error values are silent unless the REPL code explicitly checks `result.error`. A bug where errors are silently swallowed (no exception, no check) is invisible without this distinction.
- **Where expected:** Dispatch raises exceptions for depth-limit violations and timeouts. Returns `LLMResult(error=True)` for model/API errors. This dual behavior is not documented in a single place and is not captured in telemetry.

---

## 8. AST Rewrite Failures

### 8.1 Pre-Rewrite Source Code

- **What:** The original Python source code as generated by the reasoning model, before AST rewriting.
- **Why:** The AST rewriter transforms `llm_query(...)` to `await llm_query_async(...)`. If the rewriter fails (syntax error, unsupported construct), you need the original code to understand what the model intended and what the rewriter could not handle.
- **Where expected:** The original code is in `args["code"]` passed to `REPLTool.run_async()`. The tool calls `rewrite_for_async()` and may raise `SyntaxError`. The original code is in the ADK event stream as tool call arguments but is not separately logged or persisted on failure.

### 8.2 Post-Rewrite Source Code

- **What:** The AST-rewritten Python source code that was actually executed.
- **Why:** Comparing pre-rewrite and post-rewrite reveals what the rewriter changed. If the rewriter incorrectly transforms a call (e.g., rewrites a non-LLM function that happens to match the pattern), the post-rewrite code shows the bug.
- **Where expected:** The rewritten code is returned by `rewrite_for_async()` and passed to `LocalREPL.run_async()`. It is not persisted anywhere. A debug-level log message may capture it, but there is no structured telemetry for rewritten code.

### 8.3 Rewrite Failure Classification

- **What:** When `rewrite_for_async()` fails, what class of failure was it? Syntax error in the model's code? Unsupported AST construct? Internal rewriter bug?
- **Why:** Syntax errors are the model's fault (prompt improvement needed). Unsupported constructs are rewriter limitations (engineering needed). Internal bugs need code fixes.
- **Where expected:** `rewrite_for_async()` raises `SyntaxError` for parse failures. Other failures would be unexpected exceptions. The exception type and message end up in REPL stderr but are not classified or tracked as a metric.

### 8.4 Rewrite Frequency and Success Rate

- **What:** How often the AST rewriter is invoked (i.e., how many REPL code blocks contain `llm_query` calls) and what percentage succeed.
- **Why:** A high rewrite failure rate suggests the model is generating code patterns the rewriter cannot handle, indicating either a prompt problem or a rewriter gap.
- **Where expected:** Not tracked. The REPLTool conditionally invokes the rewriter but does not count invocations or failures. Adding `obs:ast_rewrite_count` and `obs:ast_rewrite_failures` would close this gap.

---

## 9. Cross-Cutting Debugging Signals

### 9.1 Request ID Correlation

- **What:** A single `request_id` that links all telemetry, state events, and logs for one end-to-end run.
- **Why:** When debugging production failures, the request_id is the primary query key for retrieving all related data.
- **Where expected:** `REQUEST_ID` in session state; `request_id` column in `traces` table. Available and functional.

### 9.2 Wall-Clock Timing at Every Layer

- **What:** Start/end timestamps for: orchestrator run, each reasoning model call, each REPL execution, each child dispatch.
- **Why:** Timing reveals bottlenecks. A 300s run where 280s is spent in one child dispatch immediately identifies the bottleneck.
- **Where expected:** `OBS_TOTAL_EXECUTION_TIME` for total run time. `telemetry` table has `start_time`/`end_time`/`duration_ms` per model call and tool call. `OBS_CHILD_DISPATCH_LATENCY_MS` for dispatch-level timing. `REASONING_CALL_START` for reasoning call timing. Coverage is good but child-within-batch timing is aggregated.

### 9.3 Token Budget Consumption

- **What:** Cumulative token usage at each point in the run, and how close the system is to context window limits.
- **Why:** Context window exhaustion is a common failure mode in long-running reasoning sessions. Seeing token consumption over time reveals whether the system is approaching limits.
- **Where expected:** `CONTEXT_WINDOW_SNAPSHOT` captures context state at each reasoning call. `OBS_PER_ITERATION_TOKEN_BREAKDOWN` tracks per-call token usage. `REASONING_INPUT_TOKENS` / `REASONING_OUTPUT_TOKENS` for current call. Coverage is strong for reasoning-level tokens but child dispatch token usage is not tracked separately (children have their own isolated token budgets).

### 9.4 BUG-13 Monkey-Patch Activation

- **What:** Whether the BUG-13 monkey-patch (suppressing premature worker termination) was activated during the run, and how many times.
- **Why:** BUG-13 is a critical correctness fix. If the patch fires, it means the underlying ADK bug was triggered. High activation counts may indicate a regression or change in ADK behavior.
- **Where expected:** `_bug13_stats["suppress_count"]` counter in `worker_retry.py`. Accessible at runtime but not persisted to any obs key or database table.

---

## Summary: Gaps and Priorities

### High-Priority Gaps (data not currently captured)

| Gap | Impact | Suggested Fix |
|---|---|---|
| **Prompt text sent to children** | Cannot reproduce child failures | Persist `_pending_prompt` to telemetry or artifact |
| **Child response text** | Cannot diagnose model-side issues | Persist `LLMResult` content to telemetry |
| **Cross-depth causal chain** | Cannot trace recursive failure propagation | Add `parent_dispatch_id` linking |
| **Pre/post AST rewrite code** | Cannot debug rewriter failures | Log both forms to telemetry on failure |
| **Per-child error detail in batches** | Only aggregates available | Persist per-position error map |
| **HTTP retry count inside genai SDK** | Retries are invisible | SDK instrumentation or wrapper logging |

### Medium-Priority Gaps

| Gap | Impact | Suggested Fix |
|---|---|---|
| **AST rewrite success/failure counters** | No rewriter health metric | Add `obs:ast_rewrite_count/failures` |
| **Per-worker structured output retry count** | Only aggregate exhaustion count | Track retries per-worker |
| **Top-level reasoning retry count** | Orchestrator recovery invisible | Add `obs:reasoning_retry_count` |
| **BUG-13 activation count in obs** | Patch activation not persisted | Write `_bug13_stats` to state |
| **REPL namespace before execution** | Only post-execution snapshot | Capture pre-execution snapshot at trace level 1+ |

### Well-Covered Areas

| Area | Coverage |
|---|---|
| Token accounting (reasoning-level) | Comprehensive via ObservabilityPlugin |
| Finish reason tracking | Per-call breakdown with dynamic reason keys |
| State key provenance | `session_state_events` 3-table schema |
| Dispatch aggregate metrics | flush_fn -> tool_context.state pipeline |
| REPL execution results | `LAST_REPL_RESULT` with stdout/stderr/variables |
| Request correlation | `REQUEST_ID` across all tables |
| Data flow between LLM calls | `DataFlowTracker` at trace level 1+ |
