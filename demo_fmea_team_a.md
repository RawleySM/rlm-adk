# FMEA Team A: Worker HTTP Fault Injection

*2026-03-01T11:36:59Z by Showboat 0.6.0*
<!-- showboat-id: a5950c61-2d15-4377-aa01-152950e7fb95 -->

## FM-08: Worker HTTP 429 Mid-Batch (RPN=96, Pathway: P6d)

**Failure Mode:** During a parallel worker batch dispatch (K=3), one worker hits
an HTTP 429 (rate limit) on all SDK retry attempts. The other two workers succeed.

**Risk:** RPN=96 is the highest-priority worker fault. REPL code that does not
check `result.error` will silently consume the error string as a real answer.

**Fixture:** `worker_429_mid_batch.json` — 6 total model calls:
- call 0: reasoning emits `execute_code` with `llm_query_batched(K=3)`
- call 1: worker A succeeds → "Result A"
- call 2: worker B gets 429 (first attempt)
- call 3: worker C succeeds → "Result C"
- call 4: worker B gets 429 (SDK retry exhausted)
- call 5: reasoning sees mixed results, returns FINAL

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/fixtures/provider_fake/worker_429_mid_batch.json') as f:
    fixture = json.load(f)

# Extract REPL code from the reasoning response (call_index 0)
for resp in fixture['responses']:
    if resp['call_index'] == 0:
        parts = resp['body']['candidates'][0]['content']['parts']
        for part in parts:
            fc = part.get('functionCall')
            if fc and fc['name'] == 'execute_code':
                print('--- REPL code emitted by reasoning agent (call_index=0) ---')
                print(fc['args']['code'])
                print('--- end ---')
                break

print()
print('--- Fault injections ---')
for fi in fixture['fault_injections']:
    print(f\"  call_index={fi['call_index']}  status={fi['status']}  type={fi['fault_type']}\")
"

```

```output
--- REPL code emitted by reasoning agent (call_index=0) ---
prompts = ["Analyze item A", "Analyze item B", "Analyze item C"]
results = llm_query_batched(prompts)
successes = [r for r in results if not r.error]
errors = [r for r in results if r.error]
print(f"Successes: {len(successes)}, Errors: {len(errors)}")
for i, r in enumerate(results):
    if r.error:
        print(f"  Result {i}: ERROR - {r.error_category}")
    else:
        print(f"  Result {i}: {str(r)[:50]}")
--- end ---

--- Fault injections ---
  call_index=2  status=429  type=http_error
  call_index=4  status=429  type=http_error
```

The REPL code dispatches 3 prompts via `llm_query_batched()`. The AST rewriter
transforms this to `await llm_query_batched_async()`, which acquires 3 workers
from the `WorkerPool` and dispatches them via `ParallelAgent`.

**Fault injection:** Worker B (call indices 2 and 4) receives HTTP 429 on both
its initial attempt and the SDK retry. The SDK's `HttpRetryOptions(attempts=2)`
exhausts both attempts, then the error propagates to ADK's
`on_model_error_callback`.

The REPL code defensively checks `result.error` on each result and tallies
successes vs. failures — this is the correct pattern for handling partial
batch failures.

```bash
echo "=== worker_on_model_error (rlm_adk/callbacks/worker.py:111-147) ===" && sed -n "111,147p" rlm_adk/callbacks/worker.py
```

```output
=== worker_on_model_error (rlm_adk/callbacks/worker.py:111-147) ===
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
echo "=== _classify_error (rlm_adk/callbacks/worker.py:22-37) ===" && sed -n "22,37p" rlm_adk/callbacks/worker.py
```

```output
=== _classify_error (rlm_adk/callbacks/worker.py:22-37) ===
def _classify_error(error: Exception) -> str:
    """Classify an exception into an error category for observability."""
    code = getattr(error, "code", None)
    if isinstance(error, asyncio.TimeoutError):
        return "TIMEOUT"
    if code == 429:
        return "RATE_LIMIT"
    if code in (401, 403):
        return "AUTH"
    if code and isinstance(code, int) and code >= 500:
        return "SERVER"
    if code and isinstance(code, int) and code >= 400:
        return "CLIENT"
    if isinstance(error, (ConnectionError, OSError)):
        return "NETWORK"
    return "UNKNOWN"
```

```bash
echo "=== dispatch result reading (rlm_adk/dispatch.py:401-423) ===" && sed -n "401,423p" rlm_adk/dispatch.py
```

```output
=== dispatch result reading (rlm_adk/dispatch.py:401-423) ===
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

**How the code handles FM-08:**

1. **Error isolation:** `worker_on_model_error` catches the exception from the
   failed worker, sets `_result_error=True` and `_result_ready=True` on the
   agent object, and returns a synthetic `LlmResponse` so `ParallelAgent`
   does not crash. The other workers complete independently.

2. **Error classification:** `_classify_error()` inspects the exception's
   `.code` attribute. HTTP 429 maps to `"RATE_LIMIT"` category, which is
   carried through `_call_record["error_category"]` into the `LLMResult`.

3. **Result reading:** In `dispatch.py` lines 401-423, the dispatch closure
   checks `_result_error` on each worker. Error workers produce
   `LLMResult(error=True, error_category="RATE_LIMIT", http_status=429)`.
   Success workers produce `LLMResult(error=False)` with the text response.

4. **REPL visibility:** The `LLMResult` (a `str` subclass) exposes `.error`
   and `.error_category` so REPL code can distinguish real answers from errors.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestWorker429MidBatch -q --no-header 2>&1 | grep -oP "^\d+ passed"
```

```output
4 passed
```

**FM-08 Test Results: All 4 tests pass.**

- `test_contract` — basic contract (final_answer, iterations, model_calls) validated
- `test_partial_failure_reported_in_final_answer` — confirms "2 succeeded" and "1 failed" in FINAL_ANSWER
- `test_worker_dispatch_count` — WORKER_DISPATCH_COUNT >= 3 (all workers counted, including the failed one)
- `test_tool_result_has_llm_calls` — execute_code function_response includes `llm_calls_made=True`

This proves that a 429 mid-batch does NOT crash the parallel dispatch.
The error is isolated to the single failed worker, classified as `RATE_LIMIT`,
and surfaced to REPL code via `LLMResult.error`. The other two workers
complete successfully and their results are available.

---

## FM-09: Worker HTTP 500/503 Service Error (RPN=60, Pathway: P6d)

**Failure Mode:** A worker's Gemini API call returns HTTP 500 (Internal Server
Error). The SDK's `HttpRetryOptions(attempts=2)` retries the request. The second
attempt succeeds.

**Risk:** RPN=60. If the SDK retry also fails, `worker_on_model_error` fires
and the error is surfaced via `LLMResult(error=True, error_category="SERVER")`.
But when retry succeeds, the failure is completely transparent to REPL code.

**Fixture:** `worker_500_then_success.json` — 4 total model calls:
- call 0: reasoning emits `execute_code` with `llm_query("What is the status?")`
- call 1: worker gets HTTP 500 (fault injection)
- call 2: worker SDK retry succeeds → "Server recovered answer"
- call 3: reasoning returns FINAL with the recovered answer

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import json
with open('tests_rlm_adk/fixtures/provider_fake/worker_500_then_success.json') as f:
    fixture = json.load(f)

# Extract REPL code from the reasoning response (call_index 0)
for resp in fixture['responses']:
    if resp['call_index'] == 0:
        parts = resp['body']['candidates'][0]['content']['parts']
        for part in parts:
            fc = part.get('functionCall')
            if fc and fc['name'] == 'execute_code':
                print('--- REPL code emitted by reasoning agent (call_index=0) ---')
                print(fc['args']['code'])
                print('--- end ---')
                break

print()
print('--- Fault injection ---')
for fi in fixture['fault_injections']:
    print(f\"  call_index={fi['call_index']}  status={fi['status']}  type={fi['fault_type']}\")

print()
print('--- Expected outcome ---')
expected = fixture['expected']
for k, v in expected.items():
    print(f'  {k}: {v}')
"

```

```output
--- REPL code emitted by reasoning agent (call_index=0) ---
result = llm_query("What is the status?")
print(result)
--- end ---

--- Fault injection ---
  call_index=1  status=500  type=http_error

--- Expected outcome ---
  final_answer: Server recovered answer
  total_iterations: 1
  total_model_calls: 4
```

The REPL code is minimal: a single `llm_query("What is the status?")` call.
The AST rewriter transforms this to `await llm_query_async(...)`, which
acquires one worker and dispatches it.

**Fault injection:** At call_index=1, the worker's first HTTP attempt returns
500 Internal Server Error. The SDK's `HttpRetryOptions(attempts=2)` fires a
retry. Call_index=2 is the retry attempt — it succeeds with "Server recovered
answer".

Unlike FM-08 (where the SDK retry was also exhausted), here the SDK retry
**succeeds**. This means `worker_on_model_error` is never called — the error
is handled entirely at the SDK/transport layer and is invisible to application
code. The REPL code receives a clean `LLMResult` with no error flag.

```bash
echo "=== Worker HttpRetryOptions wiring (rlm_adk/dispatch.py:122-130) ===" && sed -n "122,130p" rlm_adk/dispatch.py
```

```output
=== Worker HttpRetryOptions wiring (rlm_adk/dispatch.py:122-130) ===
            generate_content_config=types.GenerateContentConfig(
                temperature=0.0,
                http_options=HttpOptions(
                    timeout=int(os.getenv("RLM_WORKER_HTTP_TIMEOUT", "120000")),
                    retry_options=HttpRetryOptions(
                        attempts=2, initial_delay=1.0, max_delay=30.0,
                    ),
                ),
            ),
```

```bash
echo "=== Single worker dispatch path (rlm_adk/dispatch.py:374-383) ===" && sed -n "374,383p" rlm_adk/dispatch.py
```

```output
=== Single worker dispatch path (rlm_adk/dispatch.py:374-383) ===
                if len(workers) == 1:
                    try:
                        await asyncio.wait_for(
                            _consume_events(workers[0].run_async(ctx)),
                            timeout=_WORKER_DISPATCH_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        workers[0]._result = f"[Worker {workers[0].name} timed out after {_WORKER_DISPATCH_TIMEOUT}s]"  # type: ignore[attr-defined]
                        workers[0]._result_ready = True  # type: ignore[attr-defined]
                        workers[0]._result_error = True  # type: ignore[attr-defined]
```

**How the code handles FM-09:**

1. **SDK-level retry:** Each worker is configured with
   `HttpRetryOptions(attempts=2, initial_delay=1.0, max_delay=30.0)`. When the
   Gemini API returns 500, the SDK retries after an exponential backoff delay.
   This is the first line of defense — entirely within the `google.genai` SDK.

2. **Transparent recovery:** When the SDK retry succeeds, `worker_after_model`
   fires normally. It extracts the text response, sets `_result` and
   `_result_ready=True` on the worker object. The error is never visible to
   application code or callbacks.

3. **Fallback if retry fails:** If both SDK attempts fail, the exception
   propagates to `worker_on_model_error` (shown in FM-08 above). The error
   is classified as `"SERVER"` by `_classify_error()` and surfaced via
   `LLMResult(error=True, error_category="SERVER", http_status=500)`.

4. **Single worker path:** For K=1, the dispatch closure uses direct
   `asyncio.wait_for(worker.run_async(ctx))` instead of `ParallelAgent`,
   avoiding the overhead of a wrapper agent for single dispatches.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestWorker500ThenSuccess -q --no-header 2>&1 | grep -oP "^\d+ passed"
```

```output
3 passed
```

**FM-09 Test Results: All 3 tests pass.**

- `test_contract` — basic contract validated (final_answer, 1 iteration, 4 model calls)
- `test_recovery_transparent` — confirms "Server recovered answer" in FINAL_ANSWER with no error keywords
- `test_single_iteration` — ITERATION_COUNT == 1 (SDK retry is transparent; no REPL retry needed)

This proves that HTTP 500 recovery via SDK retry is completely invisible to
application code. The REPL receives a clean result string. The 4 total model
calls (reasoning + 500_fault + 500_retry_success + reasoning_final) confirm
the SDK retry consumed one additional call slot, but the application saw only
a single successful worker dispatch.

---

## Summary

| FM | Name | RPN | Workers | Fault | Recovery | Tests |
|----|------|-----|---------|-------|----------|-------|
| FM-08 | Worker 429 Mid-Batch | 96 | K=3 | 429 x2 on worker B | `on_model_error` isolates; 2/3 succeed | 4/4 pass |
| FM-09 | Worker 500 Then Success | 60 | K=1 | 500 x1 | SDK retry succeeds transparently | 3/3 pass |

**Key architectural insight:** RLM-ADK has two layers of fault tolerance for
worker HTTP errors:
1. **SDK layer** — `HttpRetryOptions` handles transient 5xx errors automatically
2. **Callback layer** — `worker_on_model_error` catches errors that survive SDK
   retries, classifies them, and surfaces them as `LLMResult(error=True)` so
   REPL code can make informed decisions

Both layers are exercised by these fixtures, proving the error handling
pipeline from HTTP fault through to REPL-visible error metadata.

