# FMEA Team B: Batch-Level Worker Failures

*2026-03-01T11:37:09Z by Showboat 0.6.0*
<!-- showboat-id: a82ec4c8-367f-4207-a8c8-c2214cf2ccdf -->

## FM-19: All Workers Fail in Batch (RPN=60, Pathway: P6b)

**Failure Mode:** Every worker in a K>1 parallel batch returns a server error (HTTP 500). With `HttpRetryOptions(attempts=2)`, each worker makes 2 HTTP attempts before `on_model_error_callback` fires. The REPL code receives an array of `LLMResult(error=True)` objects and must detect and handle all failures gracefully.

**Risk:** Correlated failures (e.g., Gemini outage) cause all concurrent workers to fail simultaneously. REPL code that does not check `result.error` will silently use error strings as real answers.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
fixture = json.load(open('tests_rlm_adk/fixtures/provider_fake/all_workers_fail_batch.json'))
# Extract the REPL code from the first reasoning response (execute_code functionCall)
for resp in fixture['responses']:
    parts = resp['body']['candidates'][0]['content']['parts']
    for part in parts:
        fc = part.get('functionCall')
        if fc and fc['name'] == 'execute_code':
            print('--- REPL code dispatched by reasoning agent ---')
            print(fc['args']['code'])
            print()
        text = part.get('text')
        if text:
            print('--- Final reasoning response ---')
            print(text)
"

```

```output
--- REPL code dispatched by reasoning agent ---
results = llm_query_batched(["Task A", "Task B", "Task C"])
failed = sum(1 for r in results if r.error)
print(f"All {failed} workers failed")

--- Final reasoning response ---
All three workers failed with server errors.

FINAL(All 3 workers failed)
```

### Fixture: `all_workers_fail_batch.json`

The fixture simulates a **K=3 batch dispatch** where all three workers hit HTTP 500 errors. Key design:

- **6 fault injections** at `call_index` 1-6: Each of the 3 workers gets 2 faulted HTTP attempts (initial + 1 SDK retry via `HttpRetryOptions(attempts=2)`), totalling 6 server errors.
- **call_index 0**: Reasoning agent emits `execute_code` with `llm_query_batched(["Task A", "Task B", "Task C"])`.
- **call_index 7**: After REPL returns results, reasoning produces `FINAL(All 3 workers failed)`.
- The REPL code checks `r.error` on each result -- this is the correct pattern for detecting worker failures.

```bash
echo "=== worker_on_model_error (rlm_adk/callbacks/worker.py) ===" && sed -n "111,148p" rlm_adk/callbacks/worker.py
```

```output
=== worker_on_model_error (rlm_adk/callbacks/worker.py) ===
def worker_on_model_error(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
    error: Exception,
) -> LlmResponse | None:
    """Handle worker LLM errors gracefully without crashing ParallelAgent.

    Sets error result on the agent object so the dispatch closure can detect
    the failure and include the error message in the results list. Returns
    an LlmResponse so the agent completes normally within ParallelAgent.
    """
    agent = callback_context._invocation_context.agent
    error_msg = f"[Worker {agent.name} error: {type(error).__name__}: {error}]"

    agent._result = error_msg  # type: ignore[attr-defined]
    agent._result_ready = True  # type: ignore[attr-defined]
    agent._result_error = True  # type: ignore[attr-defined]

    # Write error call record onto agent object for dispatch closure
    agent._call_record = {  # type: ignore[attr-defined]
        "prompt": getattr(agent, "_pending_prompt", None),
        "response": error_msg,
        "input_tokens": 0,
        "output_tokens": 0,
        "model": None,
        "finish_reason": None,
        "error": True,
        "error_category": _classify_error(error),
        "http_status": getattr(error, "code", None),
    }

    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=error_msg)],
        )
    )
```

```bash
echo "=== dispatch error-result reading (rlm_adk/dispatch.py:401-423) ===" && sed -n "401,423p" rlm_adk/dispatch.py
```

```output
=== dispatch error-result reading (rlm_adk/dispatch.py:401-423) ===
                # Read results from worker objects
                for worker in workers:
                    record = getattr(worker, "_call_record", {}) or {}
                    if not worker._result_ready:  # type: ignore[attr-defined]
                        logger.error(
                            "Worker %s produced no result", worker.name,
                        )
                        all_results.append(LLMResult(
                            "", error=True, error_category="NO_RESULT",
                        ))
                    elif getattr(worker, '_result_error', False):
                        logger.warning(
                            "Worker %s returned error result: %s",
                            worker.name, worker._result,  # type: ignore[attr-defined]
                        )
                        all_results.append(LLMResult(
                            worker._result,  # type: ignore[attr-defined]
                            error=True,
                            error_category=record.get("error_category", "UNKNOWN"),
                            http_status=record.get("http_status"),
                            finish_reason=record.get("finish_reason"),
                            model=record.get("model"),
                        ))
```

### How the Source Handles FM-19

The error isolation works through a **three-layer chain**:

1. **SDK retry layer** (`HttpRetryOptions(attempts=2)`): Each worker automatically retries on 500 errors. After 2 failed attempts, the SDK raises an exception.

2. **`worker_on_model_error` callback** (`callbacks/worker.py`): Catches the exception, classifies it via `_classify_error()` (returns `"SERVER"` for HTTP 500), writes the error onto the worker's `_result`/`_result_error` carrier attributes, and returns a synthetic `LlmResponse` so `ParallelAgent` does not crash.

3. **Dispatch result reader** (`dispatch.py:401-423`): After `ParallelAgent` completes, the dispatch loop reads each worker's carrier. When `_result_error=True`, it wraps the error into `LLMResult(error=True, error_category="SERVER")`. The REPL code receives a list where every element has `.error=True`.

The key design property: **individual worker errors never crash the batch**. Even when all K workers fail, the REPL code receives K error results and can report them.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestAllWorkersFail -q --no-header --tb=no 2>&1 | grep -oP "^\d+ passed" | head -1
```

```output
3 passed
```

### FM-19 Test Summary

All 3 tests in `TestAllWorkersFail` pass:

- **`test_contract`**: Validates the fixture contract -- `final_answer="All 3 workers failed"`, `total_iterations=1`, `total_model_calls=8` (1 reasoning + 6 faulted worker attempts + 1 final reasoning).
- **`test_all_failures_detected`**: Asserts that `FINAL_ANSWER` contains `"3 workers failed"`, confirming the REPL code detected all failures via `r.error`.
- **`test_repl_code_did_not_crash`**: Verifies the `execute_code` function\_response has non-empty stdout (the `print()` output), proving the REPL completed without uncaught exceptions despite all workers failing.

**Conclusion for FM-19:** The error-isolation chain (`HttpRetryOptions` -> `worker_on_model_error` -> dispatch result reader -> `LLMResult(error=True)`) correctly handles correlated batch failures. No crash, no silent data corruption.

---

## FM-25: Worker SAFETY/MAX_TOKENS Finish Reason (RPN=75, Pathway: P6d)

**Failure Mode:** A worker's Gemini response is truncated by token limit or blocked by a safety filter. The `worker_after_model` callback reads empty/truncated text and writes it to the result carrier with `_result_ready=True` but `_result_error=False` -- it is treated as a successful (but empty) response.

**Risk:** REPL code cannot distinguish an empty success from an error unless it explicitly checks the string length or content. This is a **silent failure** -- the worker completed without error, but the answer is useless.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
fixture = json.load(open('tests_rlm_adk/fixtures/provider_fake/worker_empty_response.json'))
for resp in fixture['responses']:
    parts = resp['body']['candidates'][0]['content']['parts']
    caller = resp.get('caller', '')
    for part in parts:
        fc = part.get('functionCall')
        if fc and fc['name'] == 'execute_code':
            print('--- REPL code dispatched by reasoning agent ---')
            print(fc['args']['code'])
            print()
        text = part.get('text')
        if text is not None:
            finish = resp['body']['candidates'][0].get('finishReason', '')
            if caller == 'worker':
                print(f'--- Worker response (finishReason={finish}) ---')
                print(repr(text))
                print()
            elif 'FINAL' in text:
                print('--- Final reasoning response ---')
                print(text)
"

```

```output
--- REPL code dispatched by reasoning agent ---
results = llm_query_batched(["Analyze market A", "Analyze market B"])
valid = [r for r in results if str(r).strip()]
empty = [r for r in results if not str(r).strip()]
print(f"Valid: {len(valid)}, Empty: {len(empty)}")
for i, r in enumerate(results):
    status = "valid" if str(r).strip() else "empty"
    print(f"  Result {i}: {status} (len={len(str(r))})")

--- Worker response (finishReason=STOP) ---
'Analysis: positive trend'

--- Worker response (finishReason=SAFETY) ---
''

--- Final reasoning response ---
The batch analysis completed with mixed results: 1 market analysis succeeded, 1 was filtered by safety.

FINAL(2 results: 1 valid, 1 empty)
```

### Fixture: `worker_empty_response.json`

The fixture simulates a **K=2 batch dispatch** with mixed results:

- **Worker 1** (`call_index=1`): Returns `"Analysis: positive trend"` with `finishReason=STOP` -- normal success.
- **Worker 2** (`call_index=2`): Returns `""` (empty string) with `finishReason=SAFETY` -- the safety filter suppressed the response.
- **No fault injections**: Both HTTP responses are 200 OK. The empty text is delivered through the normal response path, not the error path.
- The REPL code checks `str(r).strip()` to distinguish valid from empty responses -- this is the defensive pattern for handling FM-25.

```bash
echo "=== worker_after_model (rlm_adk/callbacks/worker.py:63-108) ===" && sed -n "63,108p" rlm_adk/callbacks/worker.py
```

```output
=== worker_after_model (rlm_adk/callbacks/worker.py:63-108) ===
def worker_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Extract response text, write to state output_key and agent object.

    Writes result onto the agent object (_result, _result_ready, _call_record)
    for the dispatch closure to read after ParallelAgent completes.
    Also writes to callback_context.state[output_key] for ADK persistence.
    """
    response_text = ""
    if llm_response.content and llm_response.content.parts:
        response_text = "".join(
            part.text for part in llm_response.content.parts if part.text and not part.thought
        )

    agent = callback_context._invocation_context.agent

    # Write result onto agent object for dispatch closure reads
    agent._result = response_text  # type: ignore[attr-defined]
    agent._result_ready = True  # type: ignore[attr-defined]

    # Extract usage from response metadata
    usage = llm_response.usage_metadata
    input_tokens = 0
    output_tokens = 0
    if usage:
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0

    # Write call record onto agent object for dispatch closure to accumulate
    agent._call_record = {  # type: ignore[attr-defined]
        "prompt": getattr(agent, "_pending_prompt", None),
        "response": response_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model": getattr(llm_response, "model_version", None),
        "finish_reason": str(llm_response.finish_reason) if llm_response.finish_reason else None,
        "error": False,
    }

    # Write to the worker's output_key in state (for ADK persistence)
    output_key = getattr(agent, "output_key", None)
    if output_key:
        callback_context.state[output_key] = response_text

    return None
```

```bash
echo "=== dispatch success-result reading (rlm_adk/dispatch.py:424-439) ===" && sed -n "424,439p" rlm_adk/dispatch.py
```

```output
=== dispatch success-result reading (rlm_adk/dispatch.py:424-439) ===
                    else:
                        # Extract structured result if available
                        structured = getattr(worker, "_structured_result", None)
                        if structured is not None:
                            result_text = json.dumps(structured)
                        else:
                            result_text = worker._result  # type: ignore[attr-defined]
                        all_results.append(LLMResult(
                            result_text,
                            error=False,
                            finish_reason=record.get("finish_reason"),
                            input_tokens=record.get("input_tokens", 0),
                            output_tokens=record.get("output_tokens", 0),
                            model=record.get("model"),
                            parsed=structured,
                        ))
```

### How the Source Handles FM-25

The key insight is that **empty/safety responses flow through the success path, not the error path**:

1. **`worker_after_model` callback** (`callbacks/worker.py:63-108`): Extracts text by joining `part.text` from response parts. When the safety filter fires, `part.text` is empty string `""`, so `response_text = ""`. The callback writes `_result=""`, `_result_ready=True`, but **does NOT set `_result_error=True`** -- the HTTP call succeeded.

2. **Dispatch result reader** (`dispatch.py:424-439`): Since `_result_error` is False, the empty string is wrapped in `LLMResult("", error=False, finish_reason="SAFETY")`. The `finish_reason` metadata is preserved from the call record.

3. **REPL-level detection**: The burden falls on the REPL code to check content. In this fixture, `str(r).strip()` distinguishes valid from empty. A more robust pattern would check `result.finish_reason` for `"SAFETY"`.

**Residual risk identified by FMEA:** REPL code that blindly uses results without length/content checks will treat the empty string as a valid answer. The `LLMResult.error` flag is `False` because the HTTP call itself succeeded.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestWorkerEmptyResponse -q --no-header --tb=no 2>&1 | grep -oP "^\d+ passed" | head -1
```

```output
3 passed
```

### FM-25 Test Summary

All 3 tests in `TestWorkerEmptyResponse` pass:

- **`test_contract`**: Validates `final_answer="2 results: 1 valid, 1 empty"`, `total_iterations=1`, `total_model_calls=4` (1 reasoning + 2 workers + 1 final reasoning).
- **`test_empty_detection_in_final_answer`**: Asserts `FINAL_ANSWER` contains both `"1 valid"` and `"1 empty"`, confirming the REPL code correctly distinguished the normal response from the safety-filtered empty one.
- **`test_single_iteration_suffices`**: Asserts `ITERATION_COUNT == 1`, proving the empty response was handled gracefully in a single REPL pass with no error-triggered retry loop.

**Conclusion for FM-25:** Empty worker responses from safety filters pass through the success path (`error=False`). Detection relies on REPL-level content checks. The `finish_reason="SAFETY"` metadata is preserved in `LLMResult` for code that wants to inspect it, but it requires explicit checking. This is a known residual risk documented in the FMEA.

---

## Comparison: FM-19 vs FM-25

| Property | FM-19 (All Workers Fail) | FM-25 (Empty/Safety Response) |
|---|---|---|
| **RPN** | 60 | 75 |
| **Pathway** | P6b (ParallelAgent batch) | P6d (Worker Gemini response) |
| **HTTP status** | 500 (server error) | 200 (success) |
| **`LLMResult.error`** | `True` | `False` |
| **Detection mechanism** | `result.error` flag | Content-length / `finish_reason` check |
| **Error isolation layer** | `worker_on_model_error` callback | `worker_after_model` (success path) |
| **REPL crash risk** | Low (errors are explicit) | Medium (empty success is silent) |

FM-25 has a **higher RPN** (75 vs 60) because its detection difficulty (D=5) is higher -- the empty response masquerades as a success. FM-19 is more explicit because the `error=True` flag is set automatically by the error callback chain.

Both failure modes are now covered by provider-fake fixtures with deterministic e2e tests, closing two gaps identified in the FMEA risk matrix.

