# FMEA Provider-Fake Fixtures — 6 New Failure Mode Scenarios

*2026-03-02T10:38:39Z by Showboat 0.6.0*
<!-- showboat-id: 949aee2d-1b1f-4066-bae9-37778e8208fd -->

Six new provider-fake fixtures covering FMEA failure modes FM-09, FM-14, FM-16, FM-17, FM-18, and FM-25. Each fixture scripts deterministic Gemini API responses for fault injection, retry exhaustion, safety/truncation, malformed JSON, and structured output validation failures.

## 1. Contract Validation — All 6 New Fixtures

Each fixture passes through the full production pipeline (FakeGeminiServer + ScenarioRouter + Runner) and checks final_answer, total_iterations, and total_model_calls.

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract -k "structured_output_batched_k3_with_retry or repl_cancelled_during_async or worker_500_retry_exhausted or worker_max_tokens_truncated or worker_malformed_json or structured_output_retry_exhaustion" -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
6 passed, 29 deselected
```

## 2. FM-17: Structured Output K=3 With Retry (RPN=90)

Exercises BUG-13 suppression under concurrent K>1 ParallelAgent dispatch. Worker 2 returns empty sentiment field triggering WorkerRetryPlugin. After retry, all 3 workers produce valid structured output.

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputBatchedK3WithRetry -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
4 passed
```

```bash
PYTHONWARNINGS=ignore .venv/bin/python3 -c "
import json
f = json.load(open('tests_rlm_adk/fixtures/provider_fake/structured_output_batched_k3_with_retry.json'))
print(f'scenario_id: {f[\"scenario_id\"]}')
print(f'FM: FM-17 | RPN: 90')
print(f'responses: {len(f[\"responses\"])} | faults: {len(f[\"fault_injections\"])}')
print(f'expected: {json.dumps(f[\"expected\"])}')
smr = sum(1 for r in f['responses'] if r['body'].get('candidates',[{}])[0].get('content',{}).get('parts',[{}])[0].get('functionCall',{}).get('name') == 'set_model_response')
print(f'set_model_response calls: {smr} (3 initial + 1 retry)')
"
```

```output
scenario_id: structured_output_batched_k3_with_retry
FM: FM-17 | RPN: 90
responses: 6 | faults: 0
expected: {"final_answer": "3 sentiments: 2 positive, 1 negative with retry", "total_iterations": 1, "total_model_calls": 6}
set_model_response calls: 4 (3 initial + 1 retry)
```

## 3. FM-14: REPL Cancelled During Async (RPN=96)

Happy-path base fixture for CancelledError injection tests. The CancelledError is injected test-side (not fixture-side) to exercise the FM-13 fix in repl_tool.py:120-143 where flush_fn runs before returning on cancellation.

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestReplCancelledDuringAsync -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
3 passed
```

## 4. FM-09: Worker 500 Retry Exhausted (RPN=60)

Both SDK HTTP retry attempts get 500 errors. After exhaustion, on_model_error_callback fires producing LLMResult(error=True, error_category=SERVER). REPL code detects result.error and reports the failure.

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestWorker500RetryExhausted -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
4 passed
```

## 5. FM-25: Worker MAX_TOKENS Truncated (RPN=75)

Worker response has finishReason=MAX_TOKENS with text truncated mid-sentence. With BUG-B fix, MAX_TOKENS does NOT set _result_error (only SAFETY does). REPL code detects the truncation.

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestWorkerMaxTokensTruncated -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
3 passed
```

## 6. FM-18: Worker Malformed JSON (RPN=24)

Uses fault_type=malformed_json to inject raw unparseable text as application/json. SDK parse failure triggers on_model_error_callback. First fixture to exercise the existing malformed_json infrastructure.

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestWorkerMalformedJson -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
3 passed
```

## 7. FM-16: Structured Output Retry Exhaustion (RPN=50)

All structured output retry attempts fail validation. Worker attempt 1: missing field (ValidationError). Worker attempt 2: empty string (WorkerRetryPlugin). Worker attempt 3: missing field again (exhausted). Dispatch FM-16 fix detects _structured_result=None and returns LLMResult(error=True, error_category=SCHEMA_VALIDATION_EXHAUSTED).

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputRetryExhaustion -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
4 passed
```

## 8. Full Suite Regression Check

All tests including the 6 new fixtures and 27 new test methods, with zero regressions against the existing 608-test baseline.

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/ -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s.*//"
```

```output
635 passed, 1 skipped
```

## Summary

| Fixture | FM | RPN | Tests | Status |
|---------|-----|-----|-------|--------|
| structured_output_batched_k3_with_retry | FM-17 | 90 | 4 | PASS |
| repl_cancelled_during_async | FM-14 | 96 | 3 | PASS |
| worker_500_retry_exhausted | FM-09 | 60 | 4 | PASS |
| worker_max_tokens_truncated | FM-25 | 75 | 3 | PASS |
| worker_malformed_json | FM-18 | 24 | 3 | PASS |
| structured_output_retry_exhaustion | FM-16 | 50 | 4 | PASS |
| **Total** | | | **21** | **ALL PASS** |

Full suite: 635 passed (+27 new), 0 failed, 1 skipped (pre-existing). Zero regressions.
