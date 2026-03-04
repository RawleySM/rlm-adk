# FMEA Team F: Orchestrator Error Handling

*2026-03-01 by Showboat 0.6.0*

## FM-01: Orchestrator Transient Error Retry Exhaustion (RPN=84, Pathway: P2)

**Failure Mode:** The reasoning agent's Gemini API call returns transient errors
(HTTP 429, 500, or 503) on ALL retry attempts. After exhausting `RLM_LLM_MAX_RETRIES`
(default 3), the exception propagates to the Runner. No `FINAL_ANSWER` is written
to state, and no structured error event is yielded.

**Risk:** RPN=84 (Severity=7, Occurrence=3, Detection=4). The residual risk is
that the caller sees a raw Python exception rather than a structured error event.
No `FINAL_ANSWER` or `SHOULD_STOP` state key is set, which can confuse downstream
consumers that rely on those keys to detect completion.

**Source Code Inspection:**

The transient status code set and `is_transient_error()` classifier:

```bash
echo "=== _TRANSIENT_STATUS_CODES and is_transient_error (rlm_adk/orchestrator.py:50-70) ===" && sed -n "50,70p" rlm_adk/orchestrator.py
```

```output
=== _TRANSIENT_STATUS_CODES and is_transient_error (rlm_adk/orchestrator.py:50-70) ===
# Transient HTTP status codes that warrant a retry.
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def is_transient_error(exc: Exception) -> bool:
    """Classify an exception as transient (retryable) using type-based checks.

    Recognizes google.genai errors, asyncio timeouts, and network-level
    exceptions as transient.  Generic exceptions are never retried.
    """
    if isinstance(exc, (ServerError, ClientError)):
        return getattr(exc, "code", None) in _TRANSIENT_STATUS_CODES
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    try:
        import httpx as _httpx
        if isinstance(exc, (_httpx.ConnectError, _httpx.TimeoutException)):
            return True
    except ImportError:
        pass
    return False
```

The retry loop in `_run_async_impl`:

```bash
echo "=== Retry loop (rlm_adk/orchestrator.py:205-226) ===" && sed -n "205,226p" rlm_adk/orchestrator.py
```

```output
=== Retry loop (rlm_adk/orchestrator.py:205-226) ===
            # --- Delegate to reasoning_agent (with retry for transient errors) ---
            max_retries = int(os.getenv("RLM_LLM_MAX_RETRIES", "3"))
            base_delay = float(os.getenv("RLM_LLM_RETRY_DELAY", "5.0"))
            for attempt in range(max_retries + 1):
                try:
                    async for event in self.reasoning_agent.run_async(ctx):
                        yield event
                    break
                except Exception as exc:
                    if not is_transient_error(exc) or attempt >= max_retries:
                        raise
                    delay = base_delay * (2 ** attempt)
                    print(
                        f"[RLM] transient error (attempt {attempt + 1}/{max_retries + 1}): "
                        f"{type(exc).__name__}. Retrying in {delay:.1f}s...",
                        flush=True,
                    )
                    logger.warning(
                        "Transient LLM error at attempt=%d: %s. Retrying in %.1fs",
                        attempt + 1, exc, delay,
                    )
                    await asyncio.sleep(delay)
```

The `finally` block that cleans up regardless of success or failure:

```bash
echo "=== finally cleanup (rlm_adk/orchestrator.py:307-312) ===" && sed -n "307,312p" rlm_adk/orchestrator.py
```

```output
=== finally cleanup (rlm_adk/orchestrator.py:307-312) ===
        finally:
            # Clean up reasoning_agent wiring
            object.__setattr__(self.reasoning_agent, 'tools', [])
            if not self.persistent:
                repl.cleanup()
```

The SDK-level retry options configured on the reasoning agent:

```bash
echo "=== Reasoning agent HttpRetryOptions (rlm_adk/agent.py:65-70) ===" && sed -n "65,70p" rlm_adk/agent.py
```

```output
=== Reasoning agent HttpRetryOptions (rlm_adk/agent.py:65-70) ===
_DEFAULT_RETRY_OPTIONS = HttpRetryOptions(
    attempts=3,
    initial_delay=1.0,
    max_delay=60.0,
    exp_base=2.0,
)
```

```bash
echo "=== _build_generate_content_config (rlm_adk/agent.py:123-148) ===" && sed -n "123,148p" rlm_adk/agent.py
```

```output
=== _build_generate_content_config (rlm_adk/agent.py:123-148) ===
def _build_generate_content_config(
    retry_config: dict[str, Any] | None,
) -> GenerateContentConfig | None:
    """Build a GenerateContentConfig with HTTP retry options.

    Args:
        retry_config: Optional dict with keys matching ``HttpRetryOptions``
            fields (``attempts``, ``initial_delay``, ``max_delay``,
            ``exp_base``, ``jitter``, ``http_status_codes``).  When ``None``,
            sensible defaults (3 attempts, exponential backoff) are used.
            Pass an empty dict ``{}`` to use the SDK's built-in defaults.
    """
    if retry_config is not None:
        retry_opts = HttpRetryOptions(**retry_config) if retry_config else None
    else:
        retry_opts = _DEFAULT_RETRY_OPTIONS

    if retry_opts is None:
        return None

    return GenerateContentConfig(
        http_options=HttpOptions(
            timeout=int(os.getenv("RLM_REASONING_HTTP_TIMEOUT", "300000")),
            retry_options=retry_opts,
        ),
    )
```

**How the code handles FM-01:**

1. **Two-layer retry architecture.** The reasoning agent has TWO independent retry
   layers. First, the SDK layer: `HttpRetryOptions(attempts=3)` in `agent.py` line 65
   retries transient HTTP errors at the transport level with exponential backoff.
   Second, the application layer: `orchestrator.py` lines 206-226 implements its own
   retry loop wrapping `reasoning_agent.run_async(ctx)`.

2. **Transient classification.** `is_transient_error()` at line 54 checks whether the
   exception is a `ServerError` or `ClientError` from `google.genai.errors` and whether
   its `.code` attribute is in `_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}`.
   It also classifies `asyncio.TimeoutError`, `ConnectionError`, `OSError`, and httpx
   transport errors as transient.

3. **Retry exhaustion path.** The loop runs `max_retries + 1` times (default 4 attempts:
   indices 0, 1, 2, 3). On each failure, the guard at line 214 checks
   `not is_transient_error(exc) or attempt >= max_retries`. When `attempt >= 3`
   (the final attempt), the condition is true and the exception is re-raised.

4. **Exponential backoff.** The delay between retries is `base_delay * (2 ** attempt)`,
   so with default `RLM_LLM_RETRY_DELAY=5.0`, the delays are 5.0s, 10.0s, 20.0s.

5. **No graceful error event.** When `raise` executes on the final attempt, the
   exception propagates out of `_run_async_impl`. The `finally` block at line 307
   runs cleanup (detach tools, cleanup REPL), but no `FINAL_ANSWER` or `SHOULD_STOP`
   state delta is yielded. The caller (Runner) sees a raw exception.

6. **Partial event yield risk.** If the reasoning agent yields some events before
   failing (e.g., the first model turn succeeds but a subsequent turn fails), those
   events have already been yielded to the Runner. The retry loop starts a fresh
   `reasoning_agent.run_async(ctx)` but the conversation history now includes the
   partial events from the failed attempt, which could confuse the model.

**Testability Assessment:**

- **Provider-fake e2e fixture:** Partially testable. The existing
  `fault_429_then_success.json` fixture injects a 429 on call_index=0 and succeeds
  on call_index=1, covering single-retry recovery. To cover FM-01 (exhaustion),
  a fixture would need to inject 429 errors on ALL call indices (e.g., call_index 0
  through 3), with no successful response. However, the provider-fake infrastructure
  would need to expect the test to raise an exception rather than produce a
  `FINAL_ANSWER`.

- **Unit test:** The most practical approach. Mock `reasoning_agent.run_async` to
  always raise `ServerError(code=503)`. Assert that after `max_retries + 1` calls,
  the exception propagates. Verify `FINAL_ANSWER` is NOT in state. Verify the
  `finally` cleanup executes.

- **Architectural analysis:** The gap between "retry succeeds" (covered) and
  "retry exhausted" (not covered) is significant because the exhaustion path has
  the residual risk of no structured error event.

**Recommended Test Scenario:**

A unit test that patches `reasoning_agent.run_async` as an async generator raising
`ServerError(code=503)` on every invocation. Set `RLM_LLM_MAX_RETRIES=2` and
`RLM_LLM_RETRY_DELAY=0.0` for speed. Assert:
- `ServerError` propagates after 3 attempts (0, 1, 2)
- `FINAL_ANSWER` is NOT in `ctx.session.state`
- `reasoning_agent.tools` is reset to `[]` (finally block ran)
- `repl.cleanup()` was called (finally block ran)

**Gaps:**
- No test for retry exhaustion (only single-retry recovery is covered)
- No structured error event on exhaustion -- caller sees raw exception
- Partial event yield on mid-conversation failures is untested
- The interaction between SDK-level retries (`HttpRetryOptions.attempts=3`) and
  application-level retries (`RLM_LLM_MAX_RETRIES=3`) creates a multiplicative
  retry budget (up to 3 x 4 = 12 total HTTP attempts) that is not documented

---

## FM-02: Non-Transient Reasoning API Error (RPN=70, Pathway: P2)

**Failure Mode:** The Gemini API returns a non-transient error such as HTTP 400
(Bad Request), 404 (Not Found), or a Pydantic `ValidationError` inside ADK. The
`is_transient_error()` classifier returns `False`, so no retry is attempted. The
exception propagates immediately to the Runner.

**Risk:** RPN=70 (Severity=7, Occurrence=2, Detection=5). The residual risk is
identical to FM-01 (no structured error event), but occurrence is lower because
non-transient errors typically indicate a configuration problem rather than an
intermittent service issue. Detection is worse (5 vs 4) because the caller cannot
distinguish "gave up after retries" from "failed immediately" -- both surface as
raw exceptions.

**Source Code Inspection:**

The `is_transient_error()` function and the transient status code set:

```bash
echo "=== _TRANSIENT_STATUS_CODES (rlm_adk/orchestrator.py:51) ===" && sed -n "51,51p" rlm_adk/orchestrator.py
```

```output
=== _TRANSIENT_STATUS_CODES (rlm_adk/orchestrator.py:51) ===
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
```

```bash
echo "=== is_transient_error (rlm_adk/orchestrator.py:54-70) ===" && sed -n "54,70p" rlm_adk/orchestrator.py
```

```output
=== is_transient_error (rlm_adk/orchestrator.py:54-70) ===
def is_transient_error(exc: Exception) -> bool:
    """Classify an exception as transient (retryable) using type-based checks.

    Recognizes google.genai errors, asyncio timeouts, and network-level
    exceptions as transient.  Generic exceptions are never retried.
    """
    if isinstance(exc, (ServerError, ClientError)):
        return getattr(exc, "code", None) in _TRANSIENT_STATUS_CODES
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    try:
        import httpx as _httpx
        if isinstance(exc, (_httpx.ConnectError, _httpx.TimeoutException)):
            return True
    except ImportError:
        pass
    return False
```

The exception guard in the retry loop:

```bash
echo "=== Exception guard (rlm_adk/orchestrator.py:213-215) ===" && sed -n "213,215p" rlm_adk/orchestrator.py
```

```output
=== Exception guard (rlm_adk/orchestrator.py:213-215) ===
                except Exception as exc:
                    if not is_transient_error(exc) or attempt >= max_retries:
                        raise
```

The import of `ClientError` and `ServerError`:

```bash
echo "=== Error imports (rlm_adk/orchestrator.py:26) ===" && sed -n "26,26p" rlm_adk/orchestrator.py
```

```output
=== Error imports (rlm_adk/orchestrator.py:26) ===
from google.genai.errors import ClientError, ServerError
```

**How the code handles FM-02:**

1. **Classification as non-transient.** A `ClientError(code=400)` or
   `ClientError(code=404)` passes the `isinstance` check at line 60, but
   `.code` (400 or 404) is NOT in `_TRANSIENT_STATUS_CODES`. So
   `is_transient_error()` returns `False`.

2. **Immediate raise.** In the retry loop at line 214, `not is_transient_error(exc)`
   evaluates to `True`, so the `if` condition short-circuits (regardless of `attempt`
   value). The `raise` at line 215 re-raises the exception on the very first attempt.

3. **No retry, no backoff.** The loop body after the `raise` is unreachable. The
   `print()` and `logger.warning()` calls at lines 217-225 are skipped. The
   `asyncio.sleep(delay)` at line 226 is never called.

4. **Cleanup still runs.** The `finally` block at line 307 executes: tools are
   detached and REPL is cleaned up. But like FM-01, no `FINAL_ANSWER` or
   `SHOULD_STOP` state delta is yielded before the exception propagates.

5. **ValidationError path.** If ADK raises a Python `ValidationError` (e.g.,
   Pydantic schema validation failure inside ADK internals), it is NOT a
   `ServerError` or `ClientError`. The `isinstance` check at line 60 fails.
   It is also not a `TimeoutError`, `ConnectionError`, or `OSError`. So
   `is_transient_error()` returns `False`, and the exception is raised immediately.
   This is correct behavior -- schema validation errors are not retryable.

6. **Generic Exception fallthrough.** Any exception type not explicitly handled by
   `is_transient_error()` returns `False`, which means it is raised immediately.
   This is a safe default -- unknown errors are not retried.

**Testability Assessment:**

- **Provider-fake e2e fixture:** A fixture could inject a `fault_type: http_error`
  with `status: 400` at call_index=0. The expected behavior is that the test runner
  catches the exception. This requires the contract runner to support an
  `expected_exception` field rather than requiring a `final_answer`.

- **Unit test:** The most straightforward approach. Mock `reasoning_agent.run_async`
  to raise `ClientError(code=400, message="Bad Request")`. Assert that:
  (a) the exception propagates without retry,
  (b) `reasoning_agent.run_async` was called exactly once,
  (c) no `FINAL_ANSWER` is in state.

- **Pure `is_transient_error()` unit test:** Test the classifier directly with
  various error types and codes. This is lightweight and does not require any ADK
  infrastructure.

**Recommended Test Scenario:**

Two-part test:

1. **Unit test for `is_transient_error()`:** Parametrize with:
   - `ClientError(code=400)` -> `False`
   - `ClientError(code=404)` -> `False`
   - `ClientError(code=429)` -> `True` (boundary: 429 is a ClientError but transient)
   - `ServerError(code=500)` -> `True`
   - `ValueError("random")` -> `False`

2. **Integration test for orchestrator:** Mock `reasoning_agent.run_async` to raise
   `ClientError(code=400)`. Set `RLM_LLM_MAX_RETRIES=3`. Assert the exception
   propagates after exactly 1 call (no retry).

**Gaps:**
- No test for non-transient error fast-failure path
- No test for the `is_transient_error()` classifier itself (no unit test)
- No distinction at the caller level between "retry exhausted" and "non-retryable"
- The boundary case of `ClientError(code=429)` being classified as transient is
  noteworthy: 429 is semantically a client error but operationally transient.
  This is correct behavior but warrants a targeted test.

---

## FM-28: HTTP 401/403 Authentication Error (RPN=6, Pathway: P2b/P6d)

**Failure Mode:** An invalid or expired API key causes the Gemini API to return
HTTP 401 (Unauthorized) or 403 (Forbidden). At the orchestrator level, this is a
`ClientError` with a non-transient code, so it is raised immediately. At the worker
level, it is caught by `worker_on_model_error` and classified as `"AUTH"`.

**Risk:** RPN=6 (Severity=3, Occurrence=2, Detection=1). This is the
lowest-priority failure mode in the FMEA because authentication errors are
immediately obvious (Detection=1) and severity is low (the system fails fast with
a clear error message). The error typically manifests on the very first API call,
so the user gets rapid feedback.

**Source Code Inspection:**

The orchestrator-level handling (reasoning agent path P2b):

```bash
echo "=== is_transient_error — 401/403 path (rlm_adk/orchestrator.py:54-70) ===" && sed -n "54,70p" rlm_adk/orchestrator.py
```

```output
=== is_transient_error — 401/403 path (rlm_adk/orchestrator.py:54-70) ===
def is_transient_error(exc: Exception) -> bool:
    """Classify an exception as transient (retryable) using type-based checks.

    Recognizes google.genai errors, asyncio timeouts, and network-level
    exceptions as transient.  Generic exceptions are never retried.
    """
    if isinstance(exc, (ServerError, ClientError)):
        return getattr(exc, "code", None) in _TRANSIENT_STATUS_CODES
    if isinstance(exc, (asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    try:
        import httpx as _httpx
        if isinstance(exc, (_httpx.ConnectError, _httpx.TimeoutException)):
            return True
    except ImportError:
        pass
    return False
```

The transient status code set does NOT include 401 or 403:

```bash
echo "=== _TRANSIENT_STATUS_CODES (rlm_adk/orchestrator.py:51) ===" && sed -n "51,51p" rlm_adk/orchestrator.py
```

```output
=== _TRANSIENT_STATUS_CODES (rlm_adk/orchestrator.py:51) ===
_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
```

The worker-level handling (worker path P6d) -- `_classify_error` for comparison:

```bash
echo "=== _classify_error — AUTH classification (rlm_adk/callbacks/worker.py:22-37) ===" && sed -n "22,37p" rlm_adk/callbacks/worker.py
```

```output
=== _classify_error — AUTH classification (rlm_adk/callbacks/worker.py:22-37) ===
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

The `worker_on_model_error` callback that handles worker-level auth errors:

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

**How the code handles FM-28:**

1. **Orchestrator path (reasoning agent, P2b).** A `ClientError(code=401)` or
   `ClientError(code=403)` passes the `isinstance` check at line 60. However,
   401 and 403 are NOT in `_TRANSIENT_STATUS_CODES`. So `is_transient_error()`
   returns `False`, and the exception is raised immediately on the first attempt
   (line 214-215). No retry, no backoff. This is correct -- retrying an auth
   failure would be pointless.

2. **Worker path (sub-LM dispatch, P6d).** If a worker hits 401/403, the error
   propagates past the SDK's `HttpRetryOptions` (SDK only retries codes in its
   own transient set, which also excludes 401/403). The error reaches
   `worker_on_model_error` at line 111. The callback:
   - Sets `_result_error = True` on the worker object (line 127)
   - Calls `_classify_error(error)` which checks `code in (401, 403)` at line 29
     and returns `"AUTH"` (line 30)
   - Writes the classification into `_call_record["error_category"]` (line 138)
   - Returns a synthetic `LlmResponse` so `ParallelAgent` does not crash

3. **Asymmetric handling.** Note the architectural asymmetry:
   - **Reasoning agent auth error:** Exception propagates to Runner (crash).
   - **Worker agent auth error:** Error isolated, classified as `"AUTH"`, surfaced
     to REPL code via `LLMResult(error=True, error_category="AUTH", http_status=401)`.

   This asymmetry is by design. A reasoning agent auth error means the entire
   system cannot function (the primary API key is invalid). A worker auth error
   could theoretically affect only one model endpoint if multi-model routing is
   used in the future.

4. **Worker `_classify_error` vs orchestrator `is_transient_error`.** These two
   classifiers serve different purposes:
   - `is_transient_error()` (orchestrator.py:54): Binary yes/no for retry decisions.
     Returns `True` for codes in `{408, 429, 500, 502, 503, 504}`.
   - `_classify_error()` (worker.py:22): Categorical classification for observability.
     Returns one of `"TIMEOUT"`, `"RATE_LIMIT"`, `"AUTH"`, `"SERVER"`, `"CLIENT"`,
     `"NETWORK"`, or `"UNKNOWN"`.

   Both correctly identify 401/403 as non-transient/AUTH, but through different
   mechanisms: `is_transient_error` by exclusion from the transient set,
   `_classify_error` by explicit pattern matching.

5. **SDK-level retry interaction.** The SDK's `HttpRetryOptions` at both reasoning
   and worker levels only retry on its own internal transient set. HTTP 401/403 is
   not retried at the SDK level either, so the error reaches application code on the
   first attempt.

**Testability Assessment:**

- **Provider-fake e2e fixture:** A fixture could inject `fault_type: http_error`
  with `status: 401` at call_index=0 for the reasoning path. For the worker path,
  inject 401 on the worker's call_index. The reasoning-path test would need to
  expect an exception. The worker-path test would assert that `LLMResult.error=True`
  and `LLMResult.error_category="AUTH"`.

- **Unit test for `is_transient_error()`:** Test with `ClientError(code=401)` and
  `ClientError(code=403)` to confirm both return `False`.

- **Unit test for `_classify_error()`:** Test with mock exceptions having
  `.code=401` and `.code=403` to confirm both return `"AUTH"`.

- **Integration test:** The most useful test would be a worker-path integration
  test showing that a 401 error on a worker is properly classified as `"AUTH"` and
  does not crash `ParallelAgent`.

**Recommended Test Scenario:**

Three-part test:

1. **`is_transient_error()` unit test:** Assert `is_transient_error(ClientError(code=401))` is `False`
   and `is_transient_error(ClientError(code=403))` is `False`.

2. **`_classify_error()` unit test:** Create a mock exception with `.code=401`,
   assert `_classify_error(exc) == "AUTH"`. Repeat for `.code=403`.

3. **Worker integration test:** Use a provider-fake fixture that injects HTTP 401 on
   a worker dispatch. Assert that the REPL receives an `LLMResult` with `error=True`,
   `error_category="AUTH"`, and `http_status=401`. Assert `ParallelAgent` does not
   crash and other workers (if batched) complete successfully.

**Gaps:**
- No test for 401/403 at the orchestrator level (reasoning agent path)
- No test for 401/403 at the worker level
- No unit test for `is_transient_error()` with auth error codes
- No unit test for `_classify_error()` with auth error codes
- The asymmetry between orchestrator (crash) and worker (graceful degradation)
  handling is undocumented

---

## Summary

| FM | Name | RPN | Testability | Current Coverage | Key Finding |
|----|------|-----|-------------|-----------------|-------------|
| FM-01 | Orchestrator Transient Error Retry Exhaustion | 84 | Unit test (mock reasoning_agent.run_async) | **Partial** -- `fault_429_then_success.json` covers single-retry recovery only | Two-layer retry (SDK + app) creates multiplicative retry budget up to 12 attempts; exhaustion path yields no structured error event |
| FM-02 | Non-Transient Reasoning API Error | 70 | Unit test (mock + `is_transient_error` parametrized) | **Gap** -- no test for non-transient fast-failure | `is_transient_error()` correctly excludes 400/404; immediate raise is correct behavior; but no structured error event on failure |
| FM-28 | HTTP 401/403 Authentication Error | 6 | Unit test + worker integration fixture | **Gap** -- no test for auth errors at either level | Asymmetric handling: orchestrator crashes, worker degrades gracefully to `LLMResult(error=True, error_category="AUTH")`; both classifiers correctly identify auth errors as non-retryable |

**Key architectural insight:** All three failure modes share a common residual risk:
when the orchestrator's retry loop raises (whether from exhaustion or immediate
non-transient failure), the `finally` block cleans up REPL and tool wiring, but NO
structured `FINAL_ANSWER` or `SHOULD_STOP` state delta is yielded. The caller
(Runner) receives a raw Python exception. This contrasts with the worker error
path, where `worker_on_model_error` provides graceful degradation via synthetic
`LlmResponse` and classified `LLMResult` objects.

A potential improvement would be to wrap the retry loop's final `raise` in a
handler that yields an error event with `FINAL_ANSWER = "[RLM ERROR] ..."` and
`SHOULD_STOP = True` before re-raising, mirroring the empty-output error path at
lines 280-305.
