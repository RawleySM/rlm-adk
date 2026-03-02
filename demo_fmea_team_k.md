# FMEA Team K: Worker Error Scenarios (FM-09, FM-18)

*2026-03-02T11:34:01Z by Showboat 0.6.0*
<!-- showboat-id: 653021fe-28a6-43da-b40a-ce6d212c84e3 -->

## Overview

This demo verifies two worker error failure modes from the FMEA:

**FM-09: Worker HTTP 500 Retry Exhausted (RPN=60, Pathway P6d)**
- Trigger: Worker Gemini call returns HTTP 500; both SDK retry attempts also fail
- Effect: `worker_on_model_error` fires, producing `LLMResult(error=True, error_category="SERVER")`
- Fixture: `worker_500_retry_exhausted.json` (2 fault injections, both 500s)

**FM-18: Malformed JSON from Gemini API (RPN=24, Pathway P2b/P6d)**
- Trigger: Worker API response is status 200 but body is unparseable JSON
- Effect: SDK parse failure triggers `on_model_error_callback`, producing `LLMResult(error=True)`
- Fixture: `worker_malformed_json.json` (1 fault injection, malformed_json type)

Both scenarios test the error isolation path: `worker_on_model_error` in `rlm_adk/callbacks/worker.py` catches the error, writes an error result onto the agent object, and returns an `LlmResponse` so `ParallelAgent` completes normally without crashing sibling workers.

```bash
jq "{scenario_id, config, fault_count: (.fault_injections | length), expected}" tests_rlm_adk/fixtures/provider_fake/worker_500_retry_exhausted.json
```

```output
{
  "scenario_id": "worker_500_retry_exhausted",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.0,
    "max_retries": 0
  },
  "fault_count": 2,
  "expected": {
    "final_answer": "Worker error: server retry exhausted",
    "total_iterations": 1,
    "total_model_calls": 4
  }
}
```

```bash
jq "{scenario_id, config, fault_count: (.fault_injections | length), expected}" tests_rlm_adk/fixtures/provider_fake/worker_malformed_json.json
```

```output
{
  "scenario_id": "worker_malformed_json",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.0,
    "max_retries": 0
  },
  "fault_count": 1,
  "expected": {
    "final_answer": "Worker failed: malformed API response",
    "total_iterations": 1,
    "total_model_calls": 3
  }
}
```

```bash
jq ".fault_injections" tests_rlm_adk/fixtures/provider_fake/worker_500_retry_exhausted.json
```

```output
[
  {
    "call_index": 1,
    "fault_type": "http_error",
    "status": 500,
    "body": {
      "error": {
        "code": 500,
        "message": "Internal server error (worker HTTP attempt 1)",
        "status": "INTERNAL"
      }
    }
  },
  {
    "call_index": 2,
    "fault_type": "http_error",
    "status": 500,
    "body": {
      "error": {
        "code": 500,
        "message": "Internal server error (worker HTTP attempt 2 - retry exhausted)",
        "status": "INTERNAL"
      }
    }
  }
]
```

```bash
jq ".fault_injections" tests_rlm_adk/fixtures/provider_fake/worker_malformed_json.json
```

```output
[
  {
    "call_index": 1,
    "fault_type": "malformed_json",
    "body_raw": "{\"candidates\": [{\"content\": {\"parts\": [{\"text\": malformed"
  }
]
```

## Fault Injection Infrastructure

The provider_fake test infrastructure uses two components:

1. **ScenarioRouter** (`tests_rlm_adk/provider_fake/fixtures.py`): Loads fixture JSON, maintains a `call_index` counter, and routes each API call to either a normal response or a fault injection based on `call_index` matching.

2. **FakeGeminiServer** (`tests_rlm_adk/provider_fake/server.py`): An aiohttp server that intercepts Gemini API calls. For `http_error`, it returns the specified HTTP status. For `malformed_json`, it returns HTTP 200 with unparseable body, causing SDK parse failure.

**FM-09 flow**: call_index 0 (reasoning) returns normally. call_index 1 and 2 (worker HTTP attempts) both return 500. SDK `HttpRetryOptions(attempts=2)` exhausts retries. `worker_on_model_error` fires with the exception, `_classify_error` maps code >= 500 to `"SERVER"`, and an error LLMResult is written to the agent object.

**FM-18 flow**: call_index 0 (reasoning) returns normally. call_index 1 (worker) returns 200 with garbled JSON. The SDK fails to parse the response body and raises an exception. `worker_on_model_error` catches it, writes error result, and returns a synthetic `LlmResponse` so `ParallelAgent` does not crash.

```bash
grep -n "_classify_error\|worker_on_model_error\|_result_error" rlm_adk/callbacks/worker.py
```

```output
9:worker_on_model_error: ERROR ISOLATION - Handles LLM errors gracefully without
26:def _classify_error(error: Exception) -> str:
99:            agent._result_error = True  # type: ignore[attr-defined]
134:        agent._result_error = True  # type: ignore[attr-defined]
149:def worker_on_model_error(
165:    agent._result_error = True  # type: ignore[attr-defined]
176:        "error_category": _classify_error(error),
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestWorker500RetryExhausted tests_rlm_adk/test_fmea_e2e.py::TestWorkerMalformedJson -v 2>&1 | sed "s/ in [0-9.]*s//"
```

```output
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /home/rawley-stanhope/dev/rlm-adk/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/rawley-stanhope/dev/rlm-adk
configfile: pyproject.toml
plugins: asyncio-1.3.0, anyio-4.12.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 7 items

tests_rlm_adk/test_fmea_e2e.py::TestWorker500RetryExhausted::test_contract PASSED [ 14%]
tests_rlm_adk/test_fmea_e2e.py::TestWorker500RetryExhausted::test_error_in_final_answer PASSED [ 28%]
tests_rlm_adk/test_fmea_e2e.py::TestWorker500RetryExhausted::test_single_iteration PASSED [ 42%]
tests_rlm_adk/test_fmea_e2e.py::TestWorker500RetryExhausted::test_tool_result_shows_error PASSED [ 57%]
tests_rlm_adk/test_fmea_e2e.py::TestWorkerMalformedJson::test_contract PASSED [ 71%]
tests_rlm_adk/test_fmea_e2e.py::TestWorkerMalformedJson::test_error_in_final_answer PASSED [ 85%]
tests_rlm_adk/test_fmea_e2e.py::TestWorkerMalformedJson::test_single_iteration PASSED [100%]

============================== 7 passed ===============================
```

## Analysis and Summary

### FM-09: Worker HTTP 500 Retry Exhausted
- **Fixture**: `worker_500_retry_exhausted.json` injects two consecutive HTTP 500 faults at call_index 1 and 2
- **Coverage**: Tests the full retry-exhaustion path (both SDK attempts fail), unlike `worker_500_then_success.json` which tests recovery
- **Error path**: `worker_on_model_error` -> `_classify_error(code=500)` -> `"SERVER"` -> `LLMResult(error=True, error_category="SERVER")`
- **Assertions**: Contract passes, final answer contains error/exhaustion keywords, single iteration (no app-level retry), tool result stdout shows error
- **All 4 tests pass**

### FM-18: Malformed JSON from Gemini API
- **Fixture**: `worker_malformed_json.json` injects one `malformed_json` fault at call_index 1
- **Coverage**: Validates that unparseable API responses are caught by the SDK, surfaced via `on_model_error_callback`, and gracefully handled
- **Error path**: SDK JSON parse failure -> `worker_on_model_error` -> `LLMResult(error=True)` -> REPL detects `result.error`
- **Assertions**: Contract passes, final answer contains failed/malformed keywords, single iteration
- **All 3 tests pass**

### Key Design Points
1. **Error isolation via `worker_on_model_error`**: Returns a synthetic `LlmResponse` so the worker agent completes normally within `ParallelAgent`, preventing blast radius to sibling workers
2. **Type-based error classification**: `_classify_error` maps HTTP status codes to categories (SERVER, RATE_LIMIT, AUTH, etc.) for observability
3. **Object carrier pattern**: Error results written to `agent._result_error` / `agent._result` / `agent._result_ready` for dispatch closure reads, avoiding dirty state reads
4. **7/7 tests green**: All FM-09 (4 tests) and FM-18 (3 tests) pass deterministically
