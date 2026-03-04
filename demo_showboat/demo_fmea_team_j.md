# FMEA Team J: Structured Output Failure Modes (FM-16, FM-17)

*2026-03-02T11:30:48Z by Showboat 0.6.0*
<!-- showboat-id: af71f447-de86-49c0-b9e3-8d309afd87aa -->

FM-16 and FM-17 test structured output self-healing in the worker dispatch pipeline. FM-16 (RPN=50) covers retry exhaustion: a worker fails structured output validation on ALL attempts, and dispatch returns LLMResult with error=True and error_category=SCHEMA_VALIDATION_EXHAUSTED. FM-17 (RPN=90) covers K>1 batched dispatch with retry: one worker in a K=3 batch returns an empty field, triggers WorkerRetryPlugin, and the BUG-13 monkey-patch suppresses premature worker termination so the retry succeeds.

```bash
jq '{scenario_id, description: (.description[:120] + "..."), config}' tests_rlm_adk/fixtures/provider_fake/structured_output_retry_exhaustion.json && echo "---" && jq '{scenario_id, description: (.description[:120] + "..."), config}' tests_rlm_adk/fixtures/provider_fake/structured_output_batched_k3_with_retry.json
```

```output
{
  "scenario_id": "structured_output_retry_exhaustion",
  "description": "FM-16 (RPN=50): Single worker dispatch with output_schema where ALL retry attempts fail validation. Worker attempt 1: se...",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.0,
    "max_retries": 2
  }
}
---
{
  "scenario_id": "structured_output_batched_k3_with_retry",
  "description": "FM-17 (RPN=90): K=3 structured output batch where Worker 1 and Worker 3 succeed immediately but Worker 2 returns empty s...",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.0
  }
}
```

FM-16 Scenario: Reasoning emits execute_code calling llm_query with output_schema=AnalysisResult. The worker makes 3 set_model_response attempts: (1) missing confidence field triggers ValidationError, (2) empty summary triggers WorkerRetryPlugin, (3) still missing confidence, max_retries=2 exhausted. dispatch.py detects output_schema\!=None and _structured_result==None, returns LLMResult(error=True, error_category=SCHEMA_VALIDATION_EXHAUSTED). The REPL code checks result.error and reports the exhaustion. FM-17 Scenario: K=3 batch with output_schema=SentimentResult. Workers 1 and 3 succeed immediately, Worker 2 returns empty sentiment triggering WorkerRetryPlugin. The BUG-13 monkey-patch in worker_retry.py intercepts set_model_response reflection calls to prevent premature termination. Worker 2 retries with correct data, all 3 results returned.

```bash
grep -n "SCHEMA_VALIDATION_EXHAUSTED\|_structured_result.*None\|output_schema is not None and structured" rlm_adk/dispatch.py
```

```output
374:                        worker._structured_result = None  # type: ignore[attr-defined]
455:                        structured = getattr(worker, "_structured_result", None)
461:                        if output_schema is not None and structured is None:
470:                                error_category="SCHEMA_VALIDATION_EXHAUSTED",
477:                            _acc_error_counts["SCHEMA_VALIDATION_EXHAUSTED"] = (
478:                                _acc_error_counts.get("SCHEMA_VALIDATION_EXHAUSTED", 0) + 1
597:                            worker._structured_result = None  # type: ignore[attr-defined]
```

```bash
grep -n "extract_error_from_result\|_rlm_patched\|_structured_result" rlm_adk/callbacks/worker_retry.py
```

```output
46:    async def extract_error_from_result(
78:    agent's _structured_result attribute when set_model_response succeeds.
107:            agent._structured_result = tool_response  # type: ignore[attr-defined]
114:        # Delegate to plugin for extract_error_from_result checks
180:    if getattr(_osp.get_structured_model_response, "_rlm_patched", False):
205:    _retry_aware_get_structured_model_response._rlm_patched = True  # type: ignore[attr-defined]
```

Key code paths: dispatch.py:374 initializes _structured_result=None on each worker. dispatch.py:455-478 reads the result after the worker loop -- if output_schema was provided but _structured_result is still None, it constructs an error LLMResult with SCHEMA_VALIDATION_EXHAUSTED category. worker_retry.py:46 defines extract_error_from_result for empty-value detection, line 107 captures successful structured results on the agent, and lines 180-205 install the BUG-13 monkey-patch that prevents premature worker termination during set_model_response reflection.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputRetryExhaustion tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputBatchedK3WithRetry -v 2>&1 | sed "s/ in [0-9.]*s//"
```

```output
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /home/rawley-stanhope/dev/rlm-adk/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/rawley-stanhope/dev/rlm-adk
configfile: pyproject.toml
plugins: asyncio-1.3.0, anyio-4.12.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 8 items

tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputRetryExhaustion::test_contract PASSED [ 12%]
tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputRetryExhaustion::test_error_in_final_answer PASSED [ 25%]
tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputRetryExhaustion::test_single_iteration PASSED [ 37%]
tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputRetryExhaustion::test_tool_result_shows_error PASSED [ 50%]
tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputBatchedK3WithRetry::test_contract PASSED [ 62%]
tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputBatchedK3WithRetry::test_retry_worker_recovered PASSED [ 75%]
tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputBatchedK3WithRetry::test_dispatch_count_equals_3 PASSED [ 87%]
tests_rlm_adk/test_fmea_e2e.py::TestStructuredOutputBatchedK3WithRetry::test_bug13_patch_active PASSED [100%]

============================== 8 passed ===============================
```

All 8 tests pass. FM-16 coverage: test_contract validates fixture contract (final_answer, iterations, model_calls). test_error_in_final_answer confirms the exhaustion keyword reaches FINAL_ANSWER. test_single_iteration verifies retry exhaustion is handled in one iteration. test_tool_result_shows_error confirms the REPL tool result contains error indication. FM-17 coverage: test_contract validates the fixture contract. test_retry_worker_recovered confirms all 3 workers produced results (2 positive, 1 negative after retry). test_dispatch_count_equals_3 verifies all 3 workers were dispatched. test_bug13_patch_active confirms the BUG-13 monkey-patch is installed (_rlm_patched flag on get_structured_model_response). Together these fixtures verify the complete structured output self-healing pipeline: WorkerRetryPlugin empty-value detection, BUG-13 premature termination suppression, and FM-16 exhaustion error propagation.
