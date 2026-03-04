# RLM-ADK Failure Mode and Effects Analysis (FMEA)

**Date:** 2026-03-02
**Codebase:** `/home/rawley-stanhope/dev/rlm-adk`
**Scope:** All agent-REPL execution pathways including reasoning agent, worker dispatch, AST rewriter, structured output, and state management.

---

## 1. FMEA Methodology

Each failure mode is assigned:
- **Severity (S):** 1-10 (10 = system crash / data loss, 1 = cosmetic)
- **Occurrence (O):** 1-10 (10 = every run, 1 = theoretical only)
- **Detection (D):** 1-10 (10 = completely invisible, 1 = immediately obvious)
- **RPN:** S x O x D (Risk Priority Number, max 1000)

Fixture coverage status:
- **Covered** = existing provider-fake fixture exercises this path
- **Partial** = related scenario exists but doesn't target this specific mode
- **Analyzed** = source-analysis verdict exists, but no provider-fake fixture backs it yet
- **Gap** = no fixture and no source-analysis verdict

---

## 2. Pathway Map

```
User → Runner → RLMOrchestratorAgent._run_async_impl()
  │
  ├── [P1] Orchestrator initialization (REPL, WorkerPool, dispatch closures)
  ├── [P2] reasoning_agent.run_async(ctx) ← ADK tool-calling loop
  │     ├── [P2a] reasoning_before_model callback
  │     ├── [P2b] Gemini API call (reasoning)
  │     ├── [P2c] reasoning_after_model callback
  │     └── [P2d] REPLTool.run_async() ← function_call dispatch
  │           ├── [P3] has_llm_calls() → sync vs async branch
  │           ├── [P4a] Sync: LocalREPL.execute_code()
  │           ├── [P4b] Async: rewrite_for_async() → execute_code_async()
  │           │     └── [P5] AST rewriter pipeline
  │           ├── [P6] Worker dispatch (llm_query_async / llm_query_batched_async)
  │           │     ├── [P6a] WorkerPool.acquire()
  │           │     ├── [P6b] worker.run_async(ctx) / ParallelAgent.run_async(ctx)
  │           │     │     ├── [P6c] worker_before_model callback
  │           │     │     ├── [P6d] Gemini API call (worker)
  │           │     │     ├── [P6e] worker_after_model callback
  │           │     │     └── [P6f] worker_on_model_error callback
  │           │     ├── [P6g] Structured output: SetModelResponseTool + WorkerRetryPlugin
  │           │     └── [P6h] Worker cleanup (parent_agent, pool release)
  │           ├── [P7] flush_fn → tool_context.state writes
  │           └── [P8] Variable serialization + LAST_REPL_RESULT
  ├── [P9] Final answer extraction (JSON parse / FINAL() regex)
  └── [P10] Orchestrator cleanup (tools detach, REPL cleanup)
```

---

## 3. Failure Mode Catalog

### FM-01: Orchestrator Transient Error Retry Exhaustion

| Attribute | Value |
|---|---|
| **Pathway** | P2 — reasoning_agent.run_async retry loop |
| **Trigger** | Reasoning Gemini API returns transient errors (429/500/503) on all retry attempts |
| **Effect** | Exception propagates to Runner; session ends with no FINAL_ANSWER in state |
| **Root Cause** | `is_transient_error()` retries up to `RLM_LLM_MAX_RETRIES` (default 3), then re-raises |
| **Current Handling** | Exception propagates; `finally` block cleans up REPL and tools |
| **Residual Risk** | No graceful error event yielded — caller sees raw exception, not structured error |
| **S/O/D/RPN** | 7 / 3 / 4 / **84** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-02: Non-Transient Reasoning API Error

| Attribute | Value |
|---|---|
| **Pathway** | P2 — reasoning_agent.run_async |
| **Trigger** | Gemini API returns 400 Bad Request, 404, or Pydantic ValidationError inside ADK |
| **Effect** | Exception propagates immediately (no retry); no FINAL_ANSWER, no SHOULD_STOP |
| **Root Cause** | `is_transient_error()` returns False for non-transient codes; raise is immediate |
| **Current Handling** | Exception propagates; `finally` cleans up |
| **Residual Risk** | Caller cannot distinguish "gave up" vs "failed fast"; no user-visible error content event |
| **S/O/D/RPN** | 7 / 2 / 5 / **70** |
| **Fixture Coverage** | **Analyzed** - source_analysis (partial); no provider-fake fixture yet |

### FM-03: REPLTool Call Limit Exceeded

| Attribute | Value |
|---|---|
| **Pathway** | P2d — REPLTool.run_async |
| **Trigger** | Model keeps calling execute_code beyond `max_calls` (default 30) |
| **Effect** | Model receives `_CALL_LIMIT_MSG` in stderr; no enforcement mechanism stops the loop |
| **Root Cause** | Call limit is advisory — model can keep calling, gets same error repeatedly |
| **Current Handling** | Returns `stderr` with limit message; `ITERATION_COUNT` still incremented |
| **Residual Risk** | Infinite loop if model ignores the message (ADK has no tool-call ceiling) |
| **S/O/D/RPN** | 5 / 2 / 3 / **30** |
| **Fixture Coverage** | **Covered** - `max_iterations_exceeded.json` (faithful) |

### FM-04: REPL SyntaxError in User Code

| Attribute | Value |
|---|---|
| **Pathway** | P4a (sync) or P4b (async via compile()) |
| **Trigger** | Model generates syntactically invalid Python in execute_code args |
| **Effect** | `SyntaxError` caught; model receives error in stderr; can retry |
| **Root Cause** | Normal LLM behavior — models produce invalid syntax occasionally |
| **Current Handling** | `exec()` raises → caught in `execute_code()` → appended to stderr |
| **Residual Risk** | Low — model sees the error and can self-correct |
| **S/O/D/RPN** | 2 / 5 / 1 / **10** |
| **Fixture Coverage** | **Covered** - `repl_syntax_error.json` (faithful) |

### FM-05: REPL RuntimeError in User Code

| Attribute | Value |
|---|---|
| **Pathway** | P4a / P4b — execute_code / execute_code_async |
| **Trigger** | Model code raises NameError, TypeError, ValueError, ZeroDivisionError, etc. |
| **Effect** | Exception caught; stderr populated; model can observe and retry |
| **Root Cause** | Normal LLM behavior |
| **Current Handling** | `except Exception` in local_repl; error in stderr + `_last_exec_error` |
| **Residual Risk** | Partial variable state — assignments before the error are lost in async path |
| **S/O/D/RPN** | 3 / 4 / 2 / **24** |
| **Fixture Coverage** | **Covered** - `repl_runtime_error.json` (faithful); `repl_error_then_retry.json` (partial) |

### FM-06: AST Rewriter Alias Blindness

| Attribute | Value |
|---|---|
| **Pathway** | P3 / P5 — has_llm_calls → rewrite_for_async |
| **Trigger** | REPL code uses `q = llm_query; q("prompt")` — alias not detected as LLM call |
| **Effect** | Code routed to sync path; `llm_query` is the sync stub → raises RuntimeError |
| **Root Cause** | `has_llm_calls` only checks `ast.Name` nodes, not aliased callables |
| **Current Handling** | RuntimeError caught by sync execute_code; model sees error in stderr |
| **Residual Risk** | Model may not understand why `q("prompt")` fails |
| **S/O/D/RPN** | 3 / 2 / 3 / **18** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-07: AST Rewriter — List Comprehension with llm_query

| Attribute | Value |
|---|---|
| **Pathway** | P5 — rewrite_for_async |
| **Trigger** | `[llm_query(p) for p in prompts]` — list comprehension with LLM call |
| **Effect** | Rewrites to `[await llm_query_async(p) for p in prompts]` — valid syntax in Python 3.11+ async comprehension |
| **Root Cause** | AST rewriter wraps in `async def _repl_exec()` so comprehension is in async context |
| **Current Handling** | Works correctly on Python 3.11+ |
| **Residual Risk** | May fail on Python < 3.11 where async comprehensions have restrictions |
| **S/O/D/RPN** | 2 / 2 / 4 / **16** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-08: Worker HTTP 429 Mid-Batch

| Attribute | Value |
|---|---|
| **Pathway** | P6d — Gemini API call (worker) during parallel batch |
| **Trigger** | One worker in a K>1 batch hits rate limit (429) |
| **Effect** | `worker_on_model_error` fires → synthetic error response → `LLMResult(error=True)` |
| **Root Cause** | Rate limiting affects individual workers independently |
| **Current Handling** | Error isolated by `worker_on_model_error`; other workers succeed; REPL sees mixed results |
| **Residual Risk** | REPL code must check `result.error` — unaware code uses error string as real answer |
| **S/O/D/RPN** | 6 / 4 / 4 / **96** |
| **Fixture Coverage** | **Covered** - `worker_429_mid_batch.json` (faithful) |

### FM-09: Worker HTTP 500/503 Service Error

| Attribute | Value |
|---|---|
| **Pathway** | P6d — Gemini API call (worker) |
| **Trigger** | Worker's Gemini call returns 500 Internal Server Error or 503 Service Unavailable |
| **Effect** | Worker HTTP retry (2 attempts) → if all fail, `worker_on_model_error` fires |
| **Root Cause** | Transient cloud infrastructure issues |
| **Current Handling** | `HttpRetryOptions(attempts=2)` at SDK level → `worker_on_model_error` → `LLMResult(error=True, error_category="SERVER")` |
| **Residual Risk** | If all workers in a batch fail, REPL code gets all-error results |
| **S/O/D/RPN** | 5 / 3 / 4 / **60** |
| **Fixture Coverage** | **Covered** - `worker_500_retry_exhausted.json` (faithful); `worker_500_then_success.json` (partial) |

### FM-10: Worker Dispatch Timeout

| Attribute | Value |
|---|---|
| **Pathway** | P6b — asyncio.wait_for around worker/ParallelAgent |
| **Trigger** | Worker(s) exceed `RLM_WORKER_TIMEOUT` (default 180s) |
| **Effect** | `asyncio.TimeoutError` caught; unfinished workers get error result; finally releases workers |
| **Root Cause** | Slow model response, network issues, or server-side processing delay |
| **Current Handling** | Timeout handler sets `_result_error=True` on incomplete workers |
| **Residual Risk** | Cancelled coroutine may leave ADK internal state inconsistent for that worker context |
| **S/O/D/RPN** | 5 / 2 / 5 / **50** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-11: Worker Pool Exhaustion with On-Demand Creation

| Attribute | Value |
|---|---|
| **Pathway** | P6a — WorkerPool.acquire |
| **Trigger** | All pool_size workers in-flight; new acquire creates on-demand worker |
| **Effect** | On-demand worker created synchronously (blocks event loop during LlmAgent construction) |
| **Root Cause** | Batch size exceeds pool_size (default 5) |
| **Current Handling** | `get_nowait()` → `QueueEmpty` → `_create_worker()` on demand |
| **Residual Risk** | Transient event loop stall; on-demand workers discarded at release (pool size cap) |
| **S/O/D/RPN** | 3 / 3 / 6 / **54** |
| **Fixture Coverage** | **Analyzed** - source_analysis (partial); no provider-fake fixture yet |

### FM-12: Worker parent_agent Not Cleared

| Attribute | Value |
|---|---|
| **Pathway** | P6h — Worker cleanup after ParallelAgent |
| **Trigger** | `worker.parent_agent` not set to None before re-pooling |
| **Effect** | Next ParallelAgent raises `ValueError` when setting parent_agent |
| **Root Cause** | ADK sets parent_agent in model_post_init; raises if already set |
| **Current Handling** | `finally` block always executes `worker.parent_agent = None` (Bug-7 fix) |
| **Residual Risk** | If `finally` itself raises before reaching this line, subsequent workers skip cleanup |
| **S/O/D/RPN** | 8 / 1 / 2 / **16** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-13: CancelledError Swallowed by REPLTool

| Attribute | Value |
|---|---|
| **Pathway** | P2d — REPLTool.run_async exception handler |
| **Trigger** | Task cancellation (e.g., outer timeout) during REPL code execution |
| **Effect** | `asyncio.CancelledError` caught; returned as stderr string; loop continues |
| **Root Cause** | `except (Exception, asyncio.CancelledError)` catches cancellation |
| **Current Handling** | Error string returned to model as if code failed |
| **Residual Risk** | Cancellation signal lost; orchestrator cannot detect the cancellation |
| **S/O/D/RPN** | 4 / 2 / 7 / **56** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-14: flush_fn Skipped on REPL Exception

| Attribute | Value |
|---|---|
| **Pathway** | P7 — flush_fn after code execution |
| **Trigger** | REPL code throws exception; except handler returns early before flush_fn call |
| **Effect** | Dispatch accumulators (_acc_dispatch_count, _acc_latencies) retain stale values |
| **Root Cause** | flush_fn call is after the except return; unreachable on exception |
| **Current Handling** | None — accumulators carry over to next iteration's flush |
| **Residual Risk** | Double-counting: next successful flush includes counts from the failed iteration |
| **S/O/D/RPN** | 4 / 3 / 8 / **96** |
| **Fixture Coverage** | **Partial** - `repl_error_then_retry.json` and `repl_cancelled_during_async.json` (both partial) |

### FM-15: Empty reasoning_output

| Attribute | Value |
|---|---|
| **Pathway** | P9 — Final answer extraction |
| **Trigger** | Reasoning agent returns empty text or only thinking tokens |
| **Effect** | `find_final_answer("")` returns None; orchestrator yields synthetic error event |
| **Root Cause** | Model generates empty response (SAFETY finish, MAX_TOKENS truncation) |
| **Current Handling** | Error event with `FINAL_ANSWER = "[RLM ERROR] ..."` and `SHOULD_STOP=True` |
| **Residual Risk** | Low for production; model error is visible to caller |
| **S/O/D/RPN** | 4 / 2 / 2 / **16** |
| **Fixture Coverage** | **Covered** - `empty_reasoning_output.json` (faithful) |

### FM-16: Structured Output Retry Exhaustion

| Attribute | Value |
|---|---|
| **Pathway** | P6g — WorkerRetryPlugin |
| **Trigger** | Worker fails structured output validation on all retry attempts (max_retries=2) |
| **Effect** | Last attempt's partial/invalid result accepted as final |
| **Root Cause** | Model cannot produce valid schema-conforming output |
| **Current Handling** | ReflectAndRetryToolPlugin stops retrying; worker completes with invalid data |
| **Residual Risk** | `_structured_result` may be None or contain invalid data; `LLMResult.parsed` is None |
| **S/O/D/RPN** | 5 / 2 / 5 / **50** |
| **Fixture Coverage** | **Covered** - `structured_output_retry_exhaustion.json` (faithful) |

### FM-17: Structured Output Batched K>1

| Attribute | Value |
|---|---|
| **Pathway** | P6g — Parallel workers with SetModelResponseTool |
| **Trigger** | `llm_query_batched(prompts, output_schema=Schema)` with K>1 |
| **Effect** | Multiple workers each wire SetModelResponseTool + WorkerRetryPlugin simultaneously |
| **Root Cause** | Each worker has independent structured output wiring |
| **Current Handling** | Per-worker isolation via independent tool callbacks |
| **Residual Risk** | BUG-13 patch is process-global; multiple concurrent workers share the patched postprocessor |
| **S/O/D/RPN** | 5 / 3 / 6 / **90** |
| **Fixture Coverage** | **Covered** - `structured_output_batched_k3_with_retry.json` (faithful); `structured_output_batched_k3.json` (partial) |

### FM-18: Malformed JSON from Gemini API

| Attribute | Value |
|---|---|
| **Pathway** | P2b / P6d — API response parsing |
| **Trigger** | Gemini API returns malformed/truncated JSON body |
| **Effect** | SDK-level parse failure → exception → retry or error callback |
| **Root Cause** | Network truncation, proxy interference, or API bug |
| **Current Handling** | SDK's HTTP retry handles at transport level; `on_model_error_callback` catches remaining |
| **Residual Risk** | No explicit test of this path |
| **S/O/D/RPN** | 4 / 1 / 6 / **24** |
| **Fixture Coverage** | **Covered** - `worker_malformed_json.json` (faithful) |

### FM-19: All Workers Fail in Batch

| Attribute | Value |
|---|---|
| **Pathway** | P6b — Parallel batch dispatch |
| **Trigger** | Every worker in a K>1 batch returns error (rate limit, server error, timeout) |
| **Effect** | All `LLMResult` objects have `error=True`; REPL code gets array of error strings |
| **Root Cause** | Correlated failures (e.g., Gemini outage affects all concurrent calls) |
| **Current Handling** | Each worker error isolated independently; REPL code responsible for checking |
| **Residual Risk** | REPL code that doesn't check `result.error` uses error strings as real answers |
| **S/O/D/RPN** | 6 / 2 / 5 / **60** |
| **Fixture Coverage** | **Covered** - `all_workers_fail_batch.json` (faithful) |

### FM-20: worker_after_model Callback Exception

| Attribute | Value |
|---|---|
| **Pathway** | P6e — worker_after_model |
| **Trigger** | Exception inside callback (e.g., Pydantic attribute write fails, ADK API change) |
| **Effect** | Exception propagates through ADK BaseLlmFlow; may crash ParallelAgent |
| **Root Cause** | No try/except in `worker_after_model`; ADK does not call `on_model_error` for callback errors |
| **Current Handling** | None — unhandled exception |
| **Residual Risk** | Entire batch crashes if one worker's callback fails |
| **S/O/D/RPN** | 8 / 1 / 3 / **24** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-21: BUG-13 Patch Import Failure

| Attribute | Value |
|---|---|
| **Pathway** | Module import — worker_retry.py |
| **Trigger** | ADK version change removes `_output_schema_processor` module |
| **Effect** | `ImportError` at module load time; cascades to dispatch.py → orchestrator.py |
| **Root Cause** | Monkey-patch depends on private ADK internal module path |
| **Current Handling** | None — import fails, entire package unusable |
| **Residual Risk** | Breaks on ADK upgrade |
| **S/O/D/RPN** | 9 / 2 / 1 / **18** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-22: RecursionError from REPL Variable Serialization

| Attribute | Value |
|---|---|
| **Pathway** | P8 — Variable serialization in REPLTool |
| **Trigger** | REPL code creates deeply recursive dict (e.g., `d = {}; d['self'] = d`) |
| **Effect** | `json.dumps(v)` raises `RecursionError` (BaseException); propagates to ADK |
| **Root Cause** | `except (TypeError, ValueError, OverflowError)` doesn't catch `RecursionError` |
| **Current Handling** | Unhandled |
| **Residual Risk** | Tool call crashes; ADK may or may not recover |
| **S/O/D/RPN** | 5 / 1 / 5 / **25** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-23: Cross-Iteration Variable Persistence After Error

| Attribute | Value |
|---|---|
| **Pathway** | P4a/P4b — REPL namespace management |
| **Trigger** | Iteration N raises exception mid-execution; iteration N+1 expects variables from N |
| **Effect** | Partial state — some variables assigned before error exist, later ones don't |
| **Root Cause** | Sync path: `self.locals` not updated on exception. Async path: `new_locals` never returned |
| **Current Handling** | REPL retains pre-exception state; new assignments lost |
| **Residual Risk** | Model may reference non-existent variables in subsequent iteration |
| **S/O/D/RPN** | 4 / 3 / 4 / **48** |
| **Fixture Coverage** | **Partial** - `repl_error_then_retry.json` (partial) |

### FM-24: Reasoning Agent SAFETY Finish Reason

| Attribute | Value |
|---|---|
| **Pathway** | P2b — Gemini API reasoning response |
| **Trigger** | Gemini triggers safety filter on reasoning agent response |
| **Effect** | Response may have empty content; `reasoning_output` is empty → FM-15 path |
| **Root Cause** | Model safety filter on generated content |
| **Current Handling** | Empty content → error event path |
| **Residual Risk** | `OBS_FINISH_SAFETY_COUNT` never incremented in tests |
| **S/O/D/RPN** | 4 / 2 / 6 / **48** |
| **Fixture Coverage** | **Partial** - `worker_safety_finish.json` (partial; fixture note flags FM-24 misclassification) |

### FM-25: Worker SAFETY / MAX_TOKENS Finish Reason

| Attribute | Value |
|---|---|
| **Pathway** | P6d — Worker Gemini response |
| **Trigger** | Worker response truncated by token limit or blocked by safety |
| **Effect** | `worker_after_model` reads empty/truncated text; `_result_ready=True` with empty/partial result |
| **Root Cause** | Model output limit or safety filter |
| **Current Handling** | Empty string result is valid (error=False); REPL code gets empty/truncated answer |
| **Residual Risk** | REPL code may not distinguish empty success from error |
| **S/O/D/RPN** | 5 / 3 / 5 / **75** |
| **Fixture Coverage** | **Covered** - `worker_max_tokens_truncated.json` (faithful); `worker_empty_response.json`/`worker_safety_finish.json` (partial) |

### FM-26: Sync REPL Under _EXEC_LOCK with Infinite Loop

| Attribute | Value |
|---|---|
| **Pathway** | P4a — sync execute_code |
| **Trigger** | Model generates `while True: pass` or similar infinite loop |
| **Effect** | Thread holds _EXEC_LOCK indefinitely; all subsequent sync REPL calls deadlock |
| **Root Cause** | No execution timeout for sync exec(); asyncio.wait_for cannot interrupt threads |
| **Current Handling** | None — process must be killed |
| **Residual Risk** | Complete system hang |
| **S/O/D/RPN** | 8 / 1 / 3 / **24** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-27: execute_code_async CWD Race Condition

| Attribute | Value |
|---|---|
| **Pathway** | P4b — async REPL execution |
| **Trigger** | Two LocalREPL instances execute_code_async concurrently on same event loop |
| **Effect** | `os.chdir()` interleaves; file operations may use wrong CWD |
| **Root Cause** | No lock protection in async path (unlike sync path with _EXEC_LOCK) |
| **Current Handling** | None — latent risk |
| **Residual Risk** | Low in current architecture (one REPL per orchestrator) |
| **S/O/D/RPN** | 4 / 1 / 8 / **32** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

### FM-28: HTTP 401/403 Authentication Error

| Attribute | Value |
|---|---|
| **Pathway** | P2b / P6d — API authentication |
| **Trigger** | Invalid or expired API key |
| **Effect** | `ClientError` with code 401/403; NOT in transient set → no retry |
| **Root Cause** | Authentication failure |
| **Current Handling** | Non-transient → immediate raise from orchestrator retry loop |
| **Residual Risk** | Fast failure; clear error message |
| **S/O/D/RPN** | 3 / 2 / 1 / **6** |
| **Fixture Coverage** | **Analyzed** - source_analysis (faithful); no provider-fake fixture yet |

---

## 4. Risk Priority Matrix (Sorted by RPN)

| RPN | FM | Failure Mode | Coverage |
|---|---|---|---|
| **96** | FM-08 | Worker HTTP 429 Mid-Batch | Covered |
| **96** | FM-14 | flush_fn Skipped on REPL Exception | Partial |
| **90** | FM-17 | Structured Output Batched K>1 | Covered |
| **84** | FM-01 | Orchestrator Transient Error Retry Exhaustion | Analyzed |
| **75** | FM-25 | Worker SAFETY / MAX_TOKENS Finish Reason | Covered |
| **70** | FM-02 | Non-Transient Reasoning API Error | Analyzed |
| **60** | FM-09 | Worker HTTP 500/503 Service Error | Covered |
| **60** | FM-19 | All Workers Fail in Batch | Covered |
| **56** | FM-13 | CancelledError Swallowed by REPLTool | Analyzed |
| **54** | FM-11 | Worker Pool Exhaustion with On-Demand Creation | Analyzed |
| **50** | FM-10 | Worker Dispatch Timeout | Analyzed |
| **50** | FM-16 | Structured Output Retry Exhaustion | Covered |
| **48** | FM-23 | Cross-Iteration Variable Persistence After Error | Partial |
| **48** | FM-24 | Reasoning Agent SAFETY Finish Reason | Partial |
| **32** | FM-27 | execute_code_async CWD Race | Analyzed |
| **30** | FM-03 | REPLTool Call Limit Exceeded | Covered |
| **25** | FM-22 | RecursionError Variable Serialization | Analyzed |
| **24** | FM-05 | REPL RuntimeError in User Code | Covered |
| **24** | FM-18 | Malformed JSON from Gemini API | Covered |
| **24** | FM-20 | worker_after_model Callback Exception | Analyzed |
| **24** | FM-26 | Sync REPL Infinite Loop Under Lock | Analyzed |
| **18** | FM-06 | AST Rewriter Alias Blindness | Analyzed |
| **18** | FM-21 | BUG-13 Patch Import Failure | Analyzed |
| **16** | FM-07 | AST Rewriter List Comprehension | Analyzed |
| **16** | FM-12 | Worker parent_agent Not Cleared | Analyzed |
| **16** | FM-15 | Empty reasoning_output | Covered |
| **10** | FM-04 | REPL SyntaxError | Covered |
| **6** | FM-28 | HTTP 401/403 Auth Error | Analyzed |

---

## 5. Existing Fixture Coverage Map

### Reviewed Existing Fixtures (11)

| Fixture | FMs | Verdict |
|---|---|---|
| `worker_429_mid_batch.json` | FM-08 | faithful |
| `worker_500_then_success.json` | FM-09 | partial |
| `all_workers_fail_batch.json` | FM-19 | faithful |
| `worker_empty_response.json` | FM-25 | partial |
| `repl_error_then_retry.json` | FM-05, FM-14, FM-23 | partial |
| `repl_syntax_error.json` | FM-04 | faithful |
| `repl_runtime_error.json` | FM-05 | faithful |
| `structured_output_batched_k3.json` | FM-17 | partial |
| `max_iterations_exceeded.json` | FM-03 | faithful |
| `empty_reasoning_output.json` | FM-15 | faithful |
| `worker_safety_finish.json` | FM-24, FM-25 | partial |

### New Fixture Coverage Notes (6)

| Fixture | FM | Verdict | Coverage Note |
|---|---|---|---|
| `structured_output_retry_exhaustion.json` | FM-16 | faithful | Adds retry-exhaustion structured output coverage. |
| `structured_output_batched_k3_with_retry.json` | FM-17 | faithful | Adds K>1 structured output path where one worker retries. |
| `worker_500_retry_exhausted.json` | FM-09 | faithful | Adds worker 500 retry-exhausted path (SERVER error outcome). |
| `worker_malformed_json.json` | FM-18 | faithful | Adds malformed JSON fault injection coverage. |
| `repl_cancelled_during_async.json` | FM-14 | partial | Scaffolds cancellation path, but no direct `CancelledError` injection/assertion yet. |
| `worker_max_tokens_truncated.json` | FM-25 | faithful | Adds MAX_TOKENS truncation variant for FM-25. |

### Gap Summary (compiled_at 2026-03-02)

- Fixture-backed status: 11 Covered + 3 Partial = 14/28 failure modes.
- Source-analysis-only status: 14/28 failure modes (no provider-fake fixture yet).
- No unreviewed failure modes remain in `fmea_gaps_compiled_2.json` (`failure_modes_covered` includes FM-01..FM-28).

---

## 6. Remaining Fixture Gaps / Follow-Ups

### Priority 1 (RPN >= 75)

| Fixture Name | Target FM | Scenario |
|---|---|---|
| `repl_exception_flush_skip.json` | FM-14 | Force exception to escape REPL execution path (not user-code `Exception`) and assert `flush_fn` + `LAST_REPL_RESULT` writes. |
| `reasoning_safety_finish.json` | FM-24 | Reasoning-level `finishReason=SAFETY` response (not worker-level), verify FM-24 coverage explicitly. |
| `worker_error_naive_repl_consumption.json` | FM-08, FM-09, FM-19 | Naive REPL code that does not check `result.error`, validating residual silent-error-consumption risk. |

### Priority 2 (RPN 50-74)

| Fixture Name | Target FM | Scenario |
|---|---|---|
| `orchestrator_retry_exhaustion.json` | FM-01, FM-02 | Integration fixture for transient-exhaustion and non-transient fast-fail behavior in orchestrator retry loop. |
| `worker_pool_exhaustion_e2e.json` | FM-11 | Batch/concurrency profile that forces on-demand worker creation and validates release behavior. |
| `worker_dispatch_timeout_injection.json` | FM-10 | Timeout fault path with assertions on per-worker timeout classification and observability counters. |

### Priority 3 (RPN 25-49)

| Fixture Name | Target FM | Scenario |
|---|---|---|
| `repl_async_variable_persistence_assertions.json` | FM-23 | Explicit assertions for variable-loss behavior after async REPL exception. |
| `ast_alias_llm_query_path.json` | FM-06 | Alias/attribute-based `llm_query` detection miss and sync-path fallback behavior. |
| `ast_comprehension_llm_query.json` | FM-07 | List/dict/set/generator comprehension usage with `llm_query` and rewrite semantics checks. |
| `repl_recursion_serialization.json` | FM-22 | Circular/deep recursion serialization path with explicit `RecursionError` handling assertions. |

---

## 7. Test Strategy

### Contract Tests (parametrized)
Every follow-up fixture should be added to `test_provider_fake_e2e.py::test_fixture_contract` parametrized list for `final_answer`, `total_iterations`, `total_model_calls` validation.

### Targeted Assertions
Each Priority 1-2 fixture gets a dedicated test function that asserts on:
- Specific state keys (e.g., `OBS_FINISH_SAFETY_COUNT`, `WORKER_DISPATCH_COUNT`)
- Error result properties (`LLMResult.error`, `LLMResult.error_category`)
- Event stream content (error events, state deltas)
- Plugin metrics (SqliteTracing span counts, observability counters)

### Plugin Integration
Run Priority 1 fixtures through `run_fixture_contract_with_plugins()` to verify observability, tracing, and debug logging handle error scenarios without crashing.

---

*Document updated from compiled fixture review file `fmea_gaps_compiled_2.json` (compiled_at `2026-03-02`).*
