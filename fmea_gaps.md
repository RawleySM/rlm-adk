# FMEA Gaps Report — Compiled Review Findings

**Date:** 2026-03-01
**Input:** 27 reviews (11 fixture reviews + 16 source analyses) from 9 teams + 9 review agents
**Source data:** `fmea_gaps_compiled.json`, `review_team_{a..i}.json`
**FM coverage:** All 28 failure modes reviewed

---

## 1. Executive Summary

| Metric | Count |
|--------|-------|
| Total reviews | 27 |
| Fixture reviews (Teams A-E) | 11 |
| Source analyses (Teams F-I) | 16 |
| Verdict: faithful | 20 |
| Verdict: partial | 7 |
| Verdict: misleading | 0 |
| High-priority recommendations | 44 |
| Medium-priority recommendations | 49 |
| Low-priority recommendations | 34 |
| Source bugs discovered | 2 (confirmed) + 5 (new design gaps) |
| Dead state keys found | 6 |
| Misclassified FM coverage | 2 fixtures |
| FMEA catalog corrections | 1 (FM-22) |

---

## 2. Critical Findings (Teams A-E: Fixture Reviews)

### CRIT-1: FM-14 (RPN=96) Is NOT Exercised by Any Fixture

**Fixture:** `repl_error_then_retry.json` claims FM-14 (flush_fn skip on REPL exception) coverage.

**Reality:** The `KeyError` is caught by `local_repl.py:361` (inner exception handler), NOT by `repl_tool.py:120` (outer exception handler). `execute_code_async` returns a normal `REPLResult` with the error in stderr. Back in `repl_tool.py`, the assignment at line 117 succeeds normally, and **flush_fn at lines 131-135 IS reached and executes.**

**Impact:** The highest-RPN REPL failure mode (flush_fn accumulator double-counting) has **zero fixture coverage**. The FMEA's listed coverage for FM-14 is incorrect.

**Fix:** Create a fixture that triggers an exception escaping `execute_code_async` (e.g., `asyncio.CancelledError`). Reclassify `repl_error_then_retry.json` as FM-05/FM-23 only.

### CRIT-2: FM-17 (RPN=90) BUG-13 Patch Never Exercised Under K>1

**Fixture:** `structured_output_batched_k3.json` tests K=3 structured output.

**Reality:** All 3 workers succeed on their first `set_model_response` call. The `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel is never generated. The BUG-13 suppression branch at `worker_retry.py:185-192` is never invoked.

**Impact:** The core risk of FM-17 (process-global patch under concurrent ParallelAgent dispatch) is untested. Only K=1 retry fixtures exist.

**Fix:** Create `structured_output_batched_k3_with_retry.json` where one worker triggers `WorkerRetryPlugin` while the other two succeed immediately.

### CRIT-3: ObservabilityPlugin `str(FinishReason)` Bug

**Location:** `observability.py:147-150` and `worker.py:99`

**Bug:** `str(FinishReason.SAFETY)` returns `"FinishReason.SAFETY"`, not `"SAFETY"`. The dynamically generated key becomes `obs:finish_finishreason.safety_count` instead of the expected `obs:finish_safety_count`.

**Impact:** ALL finish_reason tracking is broken — SAFETY, MAX_TOKENS, RECITATION. The state constants `OBS_FINISH_SAFETY_COUNT`, `OBS_FINISH_RECITATION_COUNT`, `OBS_FINISH_MAX_TOKENS_COUNT` in `state.py:74-76` are **dead code** that never matches any written key.

**Fix:** Change `str(finish_reason)` to `finish_reason.name` (or `.value`) in both locations.

### CRIT-4: FM-24 (Reasoning-Level SAFETY, RPN=48) Has Zero Fixture Coverage

**Fixture:** `worker_safety_finish.json` claims FM-24/25 but only targets FM-25 (worker-level SAFETY).

**Reality:** FM-24 requires a `finishReason=SAFETY` on a **reasoning-level** response. No fixture provides this.

**Fix:** Create `reasoning_safety_finish.json`. Reclassify `worker_safety_finish.json` as FM-25 only.

---

## 3. Critical Findings (Teams F-I: Source Analyses)

### CRIT-5: FM-22 FMEA Catalog Correction — RecursionError IS Caught

**Location:** `repl_tool.py:158` (variable serialization except clause)

**FMEA says:** RecursionError from circular dict serialization "propagates to ADK."

**Reality:** The outer `except (Exception, asyncio.CancelledError)` at `repl_tool.py:120` catches RecursionError (since `RecursionError -> RuntimeError -> Exception`). The error **does not** propagate to ADK. However, the real impact is that **all execution results (stdout, variables) from a successful REPL execution are discarded** because the serialization error triggers the outer except handler.

**Fix:** One-line fix: add `RecursionError` to the except tuple at `repl_tool.py:158`:
`except (TypeError, ValueError, OverflowError, RecursionError):`

### CRIT-6: FM-20 (RPN=24) worker_after_model Has Zero Exception Handling

**Location:** `worker.py:63-108`

**Bug:** `worker_after_model` has **zero try/except blocks** across 46 lines of code. Any exception (e.g., `AttributeError` from ADK private API change at line 78) propagates through ParallelAgent and is caught by `dispatch.py:505-510`, which **discards ALL successful sibling results** in the batch.

**Impact:** One worker's callback failure crashes the entire K-worker batch. Completed workers' results are overwritten with error LLMResult objects.

**Fix:** Wrap worker_after_model body in try/except, set `_result_error=True` on failure. Also modify dispatch except handler to check `_result_ready` before overwriting.

### CRIT-7: FM-21 (RPN=18) BUG-13 Import Has No try/except

**Location:** `worker_retry.py:167` (private module import)

**Bug:** `import google.adk.flows.llm_flows._output_schema_processor` at module level with no ImportError guard. If ADK restructures this private module, the import fails at line 167, cascading through `dispatch.py:37` to crash the entire package.

**Fix:** Wrap import in `try/except ImportError` with warning log. Graceful degradation: structured output retry disabled but all other functionality intact.

### CRIT-8: FM-10 (RPN=50) Timed-Out Workers Get Wrong Error Category

**Location:** `dispatch.py:380-383` and `dispatch.py:394-399`

**Bug:** Dispatch-level timeout handlers set `_result_error=True` on timed-out workers but **never write `_call_record`**. In the result-reading loop at `dispatch.py:419`, `record.get('error_category', 'UNKNOWN')` returns `'UNKNOWN'` instead of `'TIMEOUT'`. Additionally, `OBS_WORKER_TIMEOUT_COUNT` (state.py:79) is never written.

**Fix:** Set `_call_record = {'error_category': 'TIMEOUT', ...}` in timeout handlers. Populate `OBS_WORKER_TIMEOUT_COUNT`.

### CRIT-9: FM-13 (RPN=56) CancelledError Swallowed, Violates asyncio Contract

**Location:** `repl_tool.py:120`

**Bug:** `except (Exception, asyncio.CancelledError)` catches CancelledError alongside generic exceptions, formats it as a normal tool result, and returns. This violates Python's asyncio cancellation semantics. Additionally, flush_fn and LAST_REPL_RESULT writes (lines 130-146) are unreachable after the except return, causing accumulator drift.

**Fix:** Separate CancelledError from Exception handler — either re-raise or set SHOULD_STOP=True.

---

## 4. Fixture Verdict Summary (Teams A-E)

| Fixture | FM(s) | RPN | Verdict | Key Gap |
|---------|-------|-----|---------|---------|
| `worker_429_mid_batch.json` | FM-08 | 96 | faithful | No error_category assertions |
| `worker_500_then_success.json` | FM-09 | 60 | partial | Can't distinguish fault-served vs no-fault; no exhausted-retry companion |
| `all_workers_fail_batch.json` | FM-19 | 60 | faithful | Missing WORKER_DISPATCH_COUNT and llm_calls_made tests |
| `worker_empty_response.json` | FM-25 | 75 | partial | Weak detection pattern; MAX_TOKENS untested; OBS_FINISH_SAFETY_COUNT missing |
| `repl_error_then_retry.json` | FM-05/23 | 96 | partial | FM-14 NOT exercised (misclassified); no variable persistence assertion |
| `repl_syntax_error.json` | FM-04 | 10 | faithful | Minor: no sync-path routing assertion |
| `repl_runtime_error.json` | FM-05 | 24 | faithful | Single-statement only; no partial-state variant |
| `structured_output_batched_k3.json` | FM-17 | 90 | partial | BUG-13 patch never triggered; no retry under K>1 |
| `max_iterations_exceeded.json` | FM-03 | 30 | faithful | No stdout=="" assertion on blocked call |
| `empty_reasoning_output.json` | FM-15 | 16 | faithful | No SHOULD_STOP assertion |
| `worker_safety_finish.json` | FM-25 | 75 | partial | FM-24 misclassified; no LLMResult.error=False assertion |

---

## 5. Source Analysis Verdict Summary (Teams F-I)

| FM | RPN | Team | Verdict | Key Finding |
|----|-----|------|---------|-------------|
| FM-01 | 84 | F | faithful | Two-layer retry; no error event on exhaustion; existing unit tests missed by demo |
| FM-02 | 70 | F | partial | Demo incorrectly claimed no is_transient_error unit tests (6 exist in test_bug001) |
| FM-28 | 6 | F | faithful | Asymmetric auth handling; _classify_error has zero test coverage |
| FM-13 | 56 | G | faithful | CancelledError swallowed; flush_fn/LAST_REPL_RESULT skipped; accumulator drift |
| FM-11 | 54 | G | partial | Demo claimed 12 tests in dispatch pool test, actual count is 16 |
| FM-10 | 50 | G | faithful | Timed-out workers get 'UNKNOWN' not 'TIMEOUT'; OBS_WORKER_TIMEOUT_COUNT never written |
| FM-12 | 16 | G | faithful | Bug-7 fix confirmed; risk if structured output cleanup fails before parent_agent=None |
| FM-16 | 50 | H | faithful | LLMResult(error=False, parsed=None) on retry exhaustion — no error signal |
| FM-18 | 24 | H | faithful | malformed_json infra exists but zero fixtures use it; no PARSE_ERROR category |
| FM-20 | 24 | H | faithful | worker_after_model has 0 try/except blocks; batch blast radius |
| FM-21 | 18 | H | faithful | No ImportError guard on private ADK module import; catastrophic cascade |
| FM-06 | 18 | I | faithful | has_llm_calls only checks ast.Name; aliases bypass detection |
| FM-07 | 16 | I | faithful | List comprehensions compile but execute sequentially (not parallel) |
| FM-22 | 25 | I | faithful | CORRECTS FMEA — RecursionError IS caught, but discards all results. One-line fix. |
| FM-26 | 24 | I | faithful | Infinite loop holds _EXEC_LOCK indefinitely; no execution timeout |
| FM-27 | 32 | I | faithful | os.chdir() unprotected in async path; mitigated by one-REPL-per-orchestrator |

---

## 6. New Fixtures Needed (Updated)

### From Teams A-E (Fixture Gap Analysis)

| Priority | Fixture | Target FM | Rationale |
|----------|---------|-----------|-----------|
| **HIGH** | `structured_output_batched_k3_with_retry.json` | FM-17 | Exercise BUG-13 suppression under concurrent K>1 |
| **HIGH** | `repl_cancelled_during_async.json` | FM-14 | Trigger exception escaping execute_code_async to skip flush_fn |
| **HIGH** | `worker_500_retry_exhausted.json` | FM-09 | SERVER error classification path |
| **HIGH** | `worker_max_tokens_truncated.json` | FM-25 | MAX_TOKENS variant of FM-25 |
| **MEDIUM** | `reasoning_safety_finish.json` | FM-24 | Reasoning-level SAFETY finishReason |
| **MEDIUM** | `worker_429_mid_batch_naive.json` | FM-08 | REPL code that does NOT check result.error |
| **MEDIUM** | `repl_runtime_error_partial_state.json` | FM-05 | Multi-statement code where early statements succeed |
| **MEDIUM** | `max_iterations_exceeded_persistent.json` | FM-03 | Model ignores limit message and makes 4+ calls |
| **LOW** | `empty_reasoning_output_safety.json` | FM-15/24 | FM-15 variant with finishReason=SAFETY |

### From Teams F-I (Source Analysis)

| Priority | Fixture/Test | Target FM | Rationale |
|----------|-------------|-----------|-----------|
| **HIGH** | `worker_malformed_json.json` | FM-18 | Existing malformed_json infra, zero fixtures use it |
| **HIGH** | `structured_output_retry_exhaustion.json` | FM-16 | Full exhaustion path (LLMResult error=False, parsed=None) |
| **MEDIUM** | Pool exhaustion e2e (K > pool_size) | FM-11 | Full dispatch pipeline under pool exhaustion |
| **MEDIUM** | `worker_auth_error_401.json` | FM-28 | Worker-level AUTH error classification |

---

## 7. Source Code Bugs Discovered

### BUG-A: `str(FinishReason)` Key Generation (HIGH) — Teams A-E

| Attribute | Value |
|-----------|-------|
| **Files** | `observability.py:147-150`, `worker.py:99` |
| **Bug** | `str(FinishReason.SAFETY)` -> `"FinishReason.SAFETY"` not `"SAFETY"` |
| **Effect** | Keys `obs:finish_finishreason.safety_count` generated instead of `obs:finish_safety_count` |
| **Dead constants** | `OBS_FINISH_SAFETY_COUNT`, `OBS_FINISH_RECITATION_COUNT`, `OBS_FINISH_MAX_TOKENS_COUNT` |
| **Fix** | `finish_reason.name` or `finish_reason.value` |

### BUG-B: Safety-Filtered Responses Pass as Success (MEDIUM) — Teams A-E

| Attribute | Value |
|-----------|-------|
| **File** | `worker.py:100` |
| **Behavior** | `worker_after_model` sets `error: False` for SAFETY finishReason |
| **Effect** | `LLMResult.error=False` for empty safety-filtered responses |
| **Potential fix** | Detect `finishReason=SAFETY` and set `_result_error=True, error_category='SAFETY'` |

### BUG-C: RecursionError Missing from Serialization Except (HIGH) — Team I

| Attribute | Value |
|-----------|-------|
| **File** | `repl_tool.py:158` |
| **Bug** | `except (TypeError, ValueError, OverflowError)` does not catch `RecursionError` from circular references |
| **Effect** | RecursionError propagates to outer except, discarding ALL execution results (stdout + variables) |
| **Fix** | Add `RecursionError` to except tuple (one-line fix) |

### BUG-D: Timeout Error Category Mismatch (MEDIUM) — Team G

| Attribute | Value |
|-----------|-------|
| **File** | `dispatch.py:380-383, 394-399` |
| **Bug** | Timeout handlers set `_result_error=True` but never write `_call_record` |
| **Effect** | `error_category='UNKNOWN'` instead of `'TIMEOUT'` for timed-out workers |
| **Fix** | Set `_call_record = {'error_category': 'TIMEOUT', ...}` in timeout handlers |

### Design Gap: worker_after_model Zero Exception Handling (HIGH) — Team H

| Attribute | Value |
|-----------|-------|
| **File** | `worker.py:63-108` |
| **Bug** | 46 lines of callback code with zero try/except blocks |
| **Effect** | One callback failure crashes entire K-worker batch via ParallelAgent |
| **Fix** | Wrap body in try/except, set `_result_error=True` on failure |

### Design Gap: BUG-13 Import No ImportError Guard (HIGH) — Team H

| Attribute | Value |
|-----------|-------|
| **File** | `worker_retry.py:167` |
| **Bug** | Private ADK module import with no try/except ImportError |
| **Effect** | Package unimportable if ADK restructures private module |
| **Fix** | Wrap in try/except ImportError with warning log |

### Design Gap: Retry Exhaustion Silent Failure (MEDIUM) — Team H

| Attribute | Value |
|-----------|-------|
| **File** | `dispatch.py:424-439` |
| **Bug** | `LLMResult(error=False, parsed=None)` when structured output retries exhaust |
| **Effect** | No error signal to REPL code; silent TypeError when accessing `.parsed['field']` |
| **Fix** | Check if output_schema was requested but `_structured_result` is None, set `error=True` |

---

## 8. Dead State Keys

These keys are declared in `state.py` but **never written** by any production code:

| Key | state.py Line | Intended Purpose | Status |
|-----|---------------|-----------------|--------|
| `OBS_WORKER_RATE_LIMIT_COUNT` | 80 | Count 429 errors | Never written |
| `OBS_WORKER_TIMEOUT_COUNT` | 79 | Count timeouts | Never written |
| `OBS_WORKER_ERROR_COUNTS` | 81 | Dict of category->count | Never written |
| `OBS_FINISH_SAFETY_COUNT` | 74 | Count SAFETY finishes | Written to wrong key (BUG-A) |
| `OBS_FINISH_RECITATION_COUNT` | 75 | Count RECITATION finishes | Written to wrong key (BUG-A) |
| `OBS_FINISH_MAX_TOKENS_COUNT` | 76 | Count MAX_TOKENS finishes | Written to wrong key (BUG-A) |

---

## 9. Missing Test Assertions — High Priority

### From Teams A-E (Fixture Tests)

| Test Class | Missing Assertion | Rationale |
|------------|------------------|-----------|
| `TestWorker429MidBatch` | `RATE_LIMIT` in tool_result stdout | Validates error classification pipeline end-to-end |
| `TestWorker500ThenSuccess` | `WORKER_DISPATCH_COUNT == 1` | Basic dispatch accounting |
| `TestWorker500ThenSuccess` | `router.call_index == 4` | Proves the 500 fault was served |
| `TestAllWorkersFail` | `WORKER_DISPATCH_COUNT == 3` | Consistency with FM-08 |
| `TestAllWorkersFail` | `llm_calls_made=True` in tool_result | Consistency with FM-08 |
| `TestReplErrorThenRetry` | `WORKER_DISPATCH_COUNT == 2` | Proves flush_fn ran for both iterations |
| `TestStructuredOutputBatchedK3` | BUG-13 `_rlm_patched` flag check | Regression guard |
| `TestWorkerSafetyFinish` | `OBS_FINISH_SAFETY_COUNT >= 1` | Exposes BUG-A |
| `TestWorkerSafetyFinish` | `LLMResult.error == False` explicit | Documents FM-25 residual risk |
| `TestEmptyReasoningOutput` | `SHOULD_STOP == True` | Session termination signal |

### From Teams F-I (Source Analysis — New Unit Tests Needed)

| Target | Missing Test | Rationale |
|--------|------------|-----------|
| orchestrator.py:214-215 | Retry exhaustion: ServerError propagates after N+1 calls | FM-01: zero coverage for exhaustion path |
| orchestrator.py:214-215 | Non-transient fast-failure: ClientError(400) after 1 call | FM-02: classifier unit tests exist but integration missing |
| worker.py:22-37 | _classify_error parametrized test class | FM-28: zero test coverage for _classify_error |
| repl_tool.py:120 | CancelledError in async path (execute_code_async) | FM-13: only sync path tested |
| dispatch.py:380-383 | Single-worker and multi-worker timeout paths | FM-10: zero test coverage |
| dispatch.py:352-530 | Two sequential batches through same WorkerPool | FM-12: Bug-7 fix never explicitly validated |
| dispatch.py:424-439 | Retry exhaustion with _structured_result=None | FM-16: zero e2e coverage |
| worker_retry.py:167 | Import failure graceful degradation | FM-21: no try/except ImportError |
| worker.py:63-108 | worker_after_model with injected exception | FM-20: zero error resilience tests |
| ast_rewriter.py:31 | has_llm_calls with aliased function name | FM-06: alias detection gap |
| ast_rewriter.py:161-228 | List comprehension rewrite compiles + executes | FM-07: zero comprehension tests |
| repl_tool.py:158 | Circular reference in variable serialization | FM-22: RecursionError not caught |
| local_repl.py:278 | _EXEC_LOCK held during execution + released after | FM-26: zero lock behavior tests |

---

## 10. Fixture Misclassifications

| Fixture | Claimed FMs | Actual FMs | Action |
|---------|-------------|------------|--------|
| `repl_error_then_retry.json` | FM-05/14/23 | FM-05/23 only | Remove FM-14 claim; create new fixture for FM-14 |
| `worker_safety_finish.json` | FM-24/25 | FM-25 only | Remove FM-24 claim; create new fixture for FM-24 |

---

## 11. FMEA Catalog Corrections

| FM | FMEA Statement | Correction | Source |
|----|---------------|------------|--------|
| FM-22 | "RecursionError propagates to ADK" | RecursionError IS caught by outer `except (Exception, asyncio.CancelledError)` at repl_tool.py:120. Real impact: execution results discarded, not ADK crash. | Team I review |

---

## 12. Revised FM Coverage — Full 28 FM Map

### FMs with Fixture Coverage (Teams A-E)

| FM | RPN | Previous Status | Revised Status | Gap |
|----|-----|----------------|----------------|-----|
| FM-03 | 30 | Covered | **COVERED** | Minor: no stdout=="" assertion |
| FM-04 | 10 | Covered | **COVERED** | Minor: no sync-path routing assertion |
| FM-05 | 24 | Covered by 2 fixtures | **COVERED** | Single-statement only |
| FM-08 | 96 | Covered | **COVERED (weak assertions)** | Error classification not asserted end-to-end |
| FM-09 | 60 | Covered | **PARTIAL** | Only happy-path retry; exhausted-retry untested |
| FM-14 | 96 | "Covered by repl_error_then_retry" | **GAP** | Misclassified; flush_fn is NOT skipped |
| FM-15 | 16 | Covered | **COVERED** | No SHOULD_STOP assertion |
| FM-17 | 90 | "Covered by structured_output" | **PARTIAL** | BUG-13 branch untested under K>1 |
| FM-19 | 60 | Covered | **COVERED** | Missing dispatch count assertions |
| FM-23 | 96 | Covered | **COVERED** | Via repl_error_then_retry |
| FM-24 | 48 | "Covered by worker_safety_finish" | **GAP** | Misclassified; worker-level only |
| FM-25 | 75 | Covered by 2 fixtures | **PARTIAL** | Only SAFETY tested; MAX_TOKENS untested |

### FMs Without Fixture Coverage — Source Analysis Only (Teams F-I)

| FM | RPN | Coverage | Key Risk | Highest-Priority Action |
|----|-----|----------|----------|------------------------|
| FM-01 | 84 | Unit tests exist (classifier) | No exhaustion integration test | Mock run_async to raise ServerError; verify N+1 attempts then propagation |
| FM-02 | 70 | Unit tests exist (classifier) | No orchestrator integration test | Mock run_async to raise ClientError(400); verify 1 call then propagation |
| FM-06 | 18 | No tests for alias case | Aliased llm_query bypasses detection | Add test_has_llm_calls_misses_alias to test_adk_ast_rewriter.py |
| FM-07 | 16 | No comprehension tests | List comprehensions execute sequentially | Add compilation + execution tests |
| FM-10 | 50 | Zero timeout tests | error_category='UNKNOWN' not 'TIMEOUT' | Unit test timeout paths + fix _call_record + populate OBS_WORKER_TIMEOUT_COUNT |
| FM-11 | 54 | Pool size tests exist (3+16) | No event loop stall measurement | Add _worker_counter and caplog assertions |
| FM-12 | 16 | Implicit (e2e fixtures pass) | parent_agent not explicitly asserted | Two-batch worker reuse test |
| FM-13 | 56 | Unit test exists (swallowing) | Only sync path, not async | Test execute_code_async CancelledError; separate handler |
| FM-16 | 50 | Unit tests (retry mechanics) | No exhaustion e2e | Create structured_output_retry_exhaustion fixture |
| FM-18 | 24 | Zero tests | malformed_json infra unused | Create worker_malformed_json fixture |
| FM-20 | 24 | Zero error resilience tests | Batch blast radius from callback exception | Wrap worker_after_model in try/except |
| FM-21 | 18 | Zero import failure tests | Catastrophic cascade on ADK restructure | Wrap import in try/except ImportError |
| FM-22 | 25 | Zero tests | RecursionError discards results | Add RecursionError to except tuple (one-line fix) |
| FM-26 | 24 | Zero lock tests | Infinite loop holds _EXEC_LOCK | Add lock held/released tests |
| FM-27 | 32 | Zero CWD race tests | os.chdir unprotected in async | Documentation test; architectural mitigation exists |
| FM-28 | 6 | Zero 401/403 tests | _classify_error has zero coverage | Add parametrized _classify_error test class |

---

## 13. High-Priority Recommendations Summary

### Source Fixes (10)

| # | File | Action |
|---|------|--------|
| 1 | observability.py:149, worker.py:99 | Fix `str(FinishReason)` -> `finish_reason.name` (BUG-A) |
| 2 | dispatch.py flush_fn | Populate `OBS_WORKER_RATE_LIMIT_COUNT`, `OBS_WORKER_ERROR_COUNTS` |
| 3 | worker.py:100 | Detect SAFETY finishReason -> set `_result_error=True, error_category='SAFETY'` (BUG-B) |
| 4 | repl_tool.py:158 | Add `RecursionError` to except tuple (BUG-C, one-line fix) |
| 5 | dispatch.py:380-399 | Set `_call_record` with `error_category='TIMEOUT'` + write OBS_WORKER_TIMEOUT_COUNT (BUG-D) |
| 6 | worker.py:63-108 | Wrap worker_after_model in try/except (FM-20 blast radius) |
| 7 | dispatch.py:505-510 | Check `_result_ready` before overwriting with error results (FM-20 sibling preservation) |
| 8 | worker_retry.py:167 | Wrap private import in try/except ImportError (FM-21 cascade) |
| 9 | dispatch.py:424-439 | Detect output_schema requested but `_structured_result=None` -> set error=True (FM-16) |
| 10 | repl_tool.py:120 | Separate CancelledError from Exception handler (FM-13 asyncio contract) |

### New Fixtures/Tests (6)

| # | Target | Action |
|---|--------|--------|
| 1 | FM-17 | Create `structured_output_batched_k3_with_retry.json` for BUG-13 concurrent coverage |
| 2 | FM-14 | Create `repl_cancelled_during_async.json` for flush_fn skip |
| 3 | FM-09 | Create `worker_500_retry_exhausted.json` for SERVER exhaustion |
| 4 | FM-25 | Create `worker_max_tokens_truncated.json` for MAX_TOKENS variant |
| 5 | FM-18 | Create `worker_malformed_json.json` using existing infra |
| 6 | FM-16 | Create `structured_output_retry_exhaustion.json` for retry exhaustion |

### Unit Tests (8)

| # | Target | Action |
|---|--------|--------|
| 1 | FM-01 | Orchestrator retry exhaustion: mock run_async, verify N+1 calls then propagation |
| 2 | FM-02 | Non-transient fast-failure: mock run_async with ClientError(400), verify 1 call |
| 3 | FM-28 | Parametrized _classify_error test class (all branches: AUTH, RATE_LIMIT, SERVER, TIMEOUT, NETWORK, UNKNOWN) |
| 4 | FM-10 | Single-worker and multi-worker timeout paths with short timeout |
| 5 | FM-12 | Two sequential batches through same WorkerPool (Bug-7 validation) |
| 6 | FM-13 | CancelledError in async path (execute_code_async) |
| 7 | FM-22 | Circular reference in variable serialization (before and after fix) |
| 8 | FM-21 | Import failure graceful degradation with sys.modules patching |

### Existing Test Fixes (10)

| # | Test | Action |
|---|------|--------|
| 1 | TestWorker429MidBatch | Assert `RATE_LIMIT` in stdout |
| 2 | TestWorker500ThenSuccess | Assert `WORKER_DISPATCH_COUNT == 1` |
| 3 | TestWorker500ThenSuccess | Assert `router.call_index == 4` |
| 4 | TestAllWorkersFail | Assert `WORKER_DISPATCH_COUNT == 3` |
| 5 | TestAllWorkersFail | Add `test_tool_result_has_llm_calls` |
| 6 | TestReplErrorThenRetry | Assert `WORKER_DISPATCH_COUNT == 2` |
| 7 | TestStructuredOutputBatchedK3 | Assert BUG-13 `_rlm_patched` flag |
| 8 | TestWorkerSafetyFinish | Assert `OBS_FINISH_SAFETY_COUNT >= 1` |
| 9 | TestWorkerSafetyFinish | Assert `LLMResult.error == False` |
| 10 | TestEmptyReasoningOutput | Assert `SHOULD_STOP == True` |

### Fixture Reclassifications (2)

| # | Fixture | Action |
|---|---------|--------|
| 1 | repl_error_then_retry.json | Reclassify FM-05/23 only (not FM-14) |
| 2 | worker_safety_finish.json | Reclassify FM-25 only (not FM-24) |

---

## 14. Medium and Low Priority Recommendations

See `fmea_gaps_compiled.json` for the complete list of 49 medium-priority and 34 low-priority recommendations.

Key medium-priority items:
- Add `OBS_WORKER_TOTAL_BATCH_DISPATCHES` assertions to all K>1 tests
- Create `reasoning_safety_finish.json` for FM-24
- Create `repl_runtime_error_partial_state.json` for multi-statement FM-05
- Add `SHOULD_STOP` assertions to terminal-state test classes
- Add is_transient_error boundary tests (ClientError 404, 408) to test_bug001
- Add pool exhaustion caplog and _worker_counter assertions
- Add worker_after_model exception injection test
- Add patch wrapper and idempotency unit tests for BUG-13 fix
- Consider asyncio.Lock for os.chdir race in async REPL path
- Add PARSE_ERROR category to _classify_error

Key low-priority items:
- Document asymmetric auth error handling in module docstrings
- Add dict/set/generator comprehension variants for FM-07 tests
- Add deeply nested non-circular structure test for FM-22
- Add lock release verification tests for FM-26
- Add BaseException subclass tests for retry loop (KeyboardInterrupt, SystemExit)
