# 04 - Code Generation & REPL Outcomes: Observability Requirements

Perspective: reviewing the quality and correctness of LLM-generated code at every recursive layer of the RLM-ADK REPL pipeline.

---

## 1. Generated Code Capture (per execute_code call)

**What:** The full Python source string the reasoning agent emitted in each `execute_code` function-call argument.

**Why it matters:** This is the primary artifact a code reviewer inspects. Without it you cannot answer "what did the model actually write?" Patterns visible here include: dead code, hallucinated APIs, redundant imports, unsafe operations, and stylistic drift across iterations.

**Where to find it:**
- `REPLTool.run_async` receives `args["code"]` (`rlm_adk/tools/repl_tool.py:79`).
- ADK function-call event payload contains the tool arguments.
- Currently NOT persisted as a standalone observable -- it is embedded inside the ADK event stream and partially echoed in `LAST_REPL_RESULT`.

**Requirement:** Persist the raw code string per invocation with iteration index and depth, keyed so it can be replayed or diffed across turns.

---

## 2. REPL Execution Results (stdout, stderr, locals, timing)

**What:** The `REPLResult` tuple returned by `LocalREPL`: `stdout`, `stderr`, the post-execution `locals()` snapshot, `execution_time`, and `llm_calls` count (`rlm_adk/types.py:165`).

**Why it matters:**
- `stdout` is the model's primary feedback channel -- if it prints wrong data, the next iteration will reason over wrong context.
- `stderr` reveals runtime warnings, deprecation notices, and uncaught exception tracebacks that the model may or may not address.
- `execution_time` flags runaway computations (infinite loops, large data ops).
- `llm_calls` count reveals how many child dispatches a single code block triggered.

**Where to find it:**
- Returned from `LocalREPL.run_cell` / `run_cell_async` (`rlm_adk/repl/local_repl.py:311`, `:368`).
- Partially surfaced in `LAST_REPL_RESULT` state key (`rlm_adk/tools/repl_tool.py:185`).

**Requirement:** Persist the complete `REPLResult` per code block (not a truncated summary). Include the full stderr even when empty -- its absence is an important signal.

---

## 3. Variable State Evolution Across Iterations

**What:** A diff of the REPL namespace (`locals()`) between consecutive `execute_code` calls: which variables were created, modified, or deleted.

**Why it matters:**
- Reveals whether the model is building up state correctly across turns or accidentally clobbering prior results.
- Detects namespace pollution: leftover temp variables from previous iterations that could confuse the model.
- Detects orphaned allocations (large DataFrames, file handles) that accumulate across iterations.
- Critical for debugging NameError failures -- if a variable disappeared between turns, the diff shows when and why.

**Where to find it:**
- `LocalREPL` maintains a persistent namespace dict (`rlm_adk/repl/local_repl.py:62`).
- Post-execution locals are part of `REPLResult`.
- Currently no diffing or change-tracking is performed.

**Requirement:** Compute and persist a namespace delta (added, modified, removed keys with type/size metadata) after each code block. Flag large objects and type changes.

---

## 4. llm_query Prompt Forwarding (Parent-to-Child Contract)

**What:** The exact prompt string passed to `llm_query(prompt, ...)` or `llm_query_batched(prompts, ...)` inside the REPL code -- the text the parent layer composes to instruct a child worker.

**Why it matters:** This is the inter-layer contract. If the parent serializes data incorrectly, embeds contradictory instructions, or forgets to include required context, the child will fail or produce garbage. Reviewing these prompts is essential for diagnosing "correct parent code, wrong child output" scenarios.

**Where to find it:**
- The prompt enters the dispatch closure at `llm_query_async(prompt, ...)` (`rlm_adk/dispatch.py:257`).
- It is assigned to `worker._pending_prompt` (`rlm_adk/dispatch.py:368`).
- `worker_before_model` injects it into the LLM request (`rlm_adk/callbacks/worker.py:55`).
- Currently not persisted as a reviewable artifact.

**Requirement:** Capture and persist each `llm_query` / `llm_query_batched` prompt with: parent depth, iteration index, batch index (for batched calls), and the output_schema name if structured output was requested. Link it to the corresponding child result.

---

## 5. Child Return Values (Worker Outputs)

**What:** The `LLMResult` returned by each worker dispatch: content text, error/error_category, usage metadata, and optional `parsed` dict for structured output (`rlm_adk/types.py:50`, `rlm_adk/dispatch.py:460`).

**Why it matters:**
- The return value is what the parent REPL code assigns to a variable and reasons over. If it is truncated, malformed, or an error sentinel, the parent's downstream logic will break.
- For structured output, verifying `parsed` against the schema reveals silent coercion or missing fields.
- Comparing the child's return with what the parent actually uses (via variable state evolution) shows whether the parent correctly consumed the child result.

**Where to find it:**
- Normalized in `_normalize_worker_result` (`rlm_adk/dispatch.py:433`).
- Carrier fields on workers: `_result`, `_result_error`, `_structured_result` (`rlm_adk/dispatch.py:380`, `rlm_adk/callbacks/worker.py:121`).
- Usage metadata from `worker_after_model` callback (`rlm_adk/callbacks/worker.py:78`).

**Requirement:** Persist each child result paired with its prompt (from requirement 4). Include: full text content (not truncated), error category if failed, token usage, latency, and schema validation outcome if applicable. Preserve batch ordering for `llm_query_batched` calls.

---

## 6. AST Rewrite Audit Trail

**What:** The original sync code the model wrote and the async-rewritten version that actually executed, plus any rewrite failures.

**Why it matters:**
- The AST rewriter transforms `result = llm_query(...)` into `result = await llm_query_async(...)` (`rlm_adk/repl/ast_rewriter.py:161`). This is a semantic transformation -- if the rewriter mishandles complex expressions (e.g., nested calls, list comprehensions containing llm_query, conditional expressions), the executed code diverges from what the model intended.
- Rewrite failures (SyntaxError in the original code, unsupported AST patterns) should be distinguished from REPL execution failures.
- Comparing pre/post rewrite reveals whether the model is writing patterns the rewriter handles well or fighting against it.

**Where to find it:**
- `rewrite_for_async` in `rlm_adk/repl/ast_rewriter.py:161`.
- REPLTool decides the execution path at `rlm_adk/tools/repl_tool.py:108`.
- Currently no before/after diff is persisted.

**Requirement:** When async rewriting occurs, persist both the original and rewritten code. Log rewrite failures separately with the AST error. Tag each code block with its execution mode (sync vs. async-rewritten).

---

## 7. Code Retry Patterns

**What:** When a code block raises an exception, does the reasoning model retry? How many retries? Does the retry fix the root cause or apply a superficial workaround?

**Why it matters:**
- Retry-then-succeed is a quality signal: the model self-corrected. But retry-with-same-error indicates the model is stuck.
- Superficial fixes (wrapping in try/except, adding `if x is not None` guards without fixing why x is None) mask bugs and produce fragile code.
- Excessive retries waste tokens and latency without progress.

**Where to find it:**
- Retry behavior is implicit in the reasoning agent's tool-call loop: after an `execute_code` returns an error in `LAST_REPL_RESULT`, the model may issue another `execute_code`.
- The sequence of `execute_code` calls and their results constitutes the retry trace.
- REPL call-limit safeguard at `rlm_adk/tools/repl_tool.py:84` caps total calls.

**Requirement:** Track consecutive `execute_code` calls where the prior call produced a non-empty stderr or exception. For each retry sequence, persist: the original error, each retry's code diff (vs. previous attempt), whether the error class changed, and whether the retry ultimately succeeded. Compute a retry-success-rate metric per run.

---

## 8. Error Classification for REPL Failures

**What:** For each REPL execution that raises an exception, classify the error type and map it to a root cause category.

**Why it matters:** Different error types indicate different failure modes in the code generation pipeline:
- **NameError**: Namespace isolation issue -- the model referenced a variable that doesn't exist in the REPL scope. Often caused by the model assuming state from a previous conversation or hallucinating a variable name.
- **TypeError**: Bad child return value (e.g., model expected a dict but got an LLMResult string), incorrect function signatures, or wrong argument types.
- **SyntaxError**: The model produced syntactically invalid Python. May also originate from the AST rewriter.
- **RuntimeError / ValueError**: Logic errors in the generated code -- correct syntax but wrong semantics.
- **AttributeError**: The model hallucinated an API or method name.
- **TimeoutError**: Code block exceeded execution time limit.
- **KeyError / IndexError**: Incorrect assumptions about data structure shape, often from bad child return parsing.

**Where to find it:**
- Exception type and traceback are in `REPLResult.stderr`.
- Worker-level errors classified in `_classify_error` (`rlm_adk/callbacks/worker.py:160`).
- No REPL-level error classification currently exists.

**Requirement:** Parse the exception type from stderr for each failed code block. Maintain per-run counters by error class. Cross-reference NameErrors with the namespace delta (requirement 3) to identify the missing variable's last-known state.

---

## 9. Data Flow Between Layers (Serialization Fidelity)

**What:** When layer-0 code constructs a prompt string that embeds data (e.g., f-string interpolation of a DataFrame summary, JSON serialization of intermediate results) to pass to `llm_query`, was the serialization faithful? Did the child parse the embedded data correctly?

**Why it matters:**
- Data corruption at layer boundaries is a silent killer: the parent code runs fine, the child LLM call succeeds, but the child operated on garbled input and returned plausible-looking but wrong results.
- Common failure modes: truncated string representations (repr of large objects), encoding issues, escaped quotes breaking prompt parsing, numeric precision loss.
- The `DataFlowTracker` (`rlm_adk/repl/trace.py`) already detects when one `llm_query` response feeds into the next prompt -- this can be extended to verify fidelity.

**Where to find it:**
- `DataFlowTracker` in `rlm_adk/repl/trace.py`.
- Prompt text in dispatch closure (`rlm_adk/dispatch.py:257`).
- Parent REPL namespace showing the source variable before serialization.

**Requirement:** For each `llm_query` call, capture: (a) the variable(s) interpolated into the prompt (via AST analysis of the call expression), (b) their types and sizes, (c) the resulting prompt length in characters and tokens. Flag prompts that contain repr() output of objects > 1000 chars or that truncate with "...". Link parent variable snapshots to child prompt text for manual review.

---

## 10. Final Answer Quality Signals

**What:** Signals indicating whether the reasoning agent produced a meaningful final answer that correctly synthesizes child-layer results.

**Why it matters:**
- A run can "succeed" (no crashes, all code executes) but produce a vacuous or hallucinated final answer that ignores the actual data from child queries.
- The final answer is extracted from `reasoning_output` via `set_model_response` or output key parsing (`rlm_adk/orchestrator.py:255`). If the model never calls `set_model_response`, the answer extraction may fall back to heuristics.

**Where to find it:**
- `reasoning_output` state key, parsed in orchestrator (`rlm_adk/orchestrator.py:255`).
- `FINAL_ANSWER` extraction (`rlm_adk/orchestrator.py:286`).
- `should_stop` signal (`rlm_adk/orchestrator.py:289`).

**Requirement:** Persist the following per-run quality signals:
- Whether `set_model_response` was called vs. fallback extraction.
- Final answer length (chars and tokens).
- Whether the final answer references variables that were populated by child `llm_query` calls (cross-ref with data flow tracking).
- Whether any child call errored and whether the final answer acknowledges the error or silently ignores it.
- The number of REPL iterations and child dispatches that contributed data to the final answer vs. total iterations (utilization ratio).

---

## Summary: Data Points by Source Location

| # | Data Point | Source File(s) | Currently Persisted? |
|---|-----------|----------------|---------------------|
| 1 | Generated code string | `repl_tool.py:79` | Partial (in ADK events) |
| 2 | REPL stdout/stderr/locals/timing | `local_repl.py:311`, `types.py:165` | Partial (truncated in LAST_REPL_RESULT) |
| 3 | Namespace delta across iterations | `local_repl.py:62` | No |
| 4 | llm_query prompt text | `dispatch.py:257`, `worker.py:55` | No |
| 5 | Child LLMResult values | `dispatch.py:433`, `types.py:50` | No (transient on worker) |
| 6 | AST rewrite before/after | `ast_rewriter.py:161` | No |
| 7 | Code retry sequences | Implicit in tool-call loop | No |
| 8 | REPL error classification | `REPLResult.stderr` | No (workers have it, REPL does not) |
| 9 | Serialization fidelity at layer boundaries | `trace.py`, `dispatch.py:257` | Partial (DataFlowTracker) |
| 10 | Final answer quality signals | `orchestrator.py:255-289` | Partial (final_answer persisted, quality signals not) |

---

## Priority Ordering for Implementation

1. **Generated code capture** (#1) and **REPL execution results** (#2) -- foundational; everything else builds on having the raw code and its output.
2. **llm_query prompt forwarding** (#4) and **child return values** (#5) -- the inter-layer contract; without these you cannot diagnose cross-depth failures.
3. **Error classification** (#8) and **code retry patterns** (#7) -- actionable diagnostics for the most common failure mode (code errors).
4. **AST rewrite audit** (#6) -- important but lower frequency; most rewrites succeed.
5. **Variable state evolution** (#3) and **data flow fidelity** (#9) -- high value for deep debugging, but require more instrumentation.
6. **Final answer quality signals** (#10) -- end-to-end quality metric; depends on several other data points being available first.
