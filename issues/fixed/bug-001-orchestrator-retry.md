# BUG-001: Orchestrator retry/error handling issues

**Bug ID:** BUG-001
**Title:** Orchestrator retry/error handling - fragile classification, dead code, disabled tenacity
**Severity:** Medium-High (affects reliability under transient LLM failures)
**Status:** Open

## Affected Files

| File | Lines | Classes / Functions |
|------|-------|---------------------|
| `rlm_adk/orchestrator.py` | 159-191 | `RLMOrchestratorAgent._run_async_impl` |
| `rlm_adk/agent.py` | 52-99, 102-138 | `create_reasoning_agent`, `create_rlm_orchestrator` |

## Sub-Issues

### (A) String-matching error classification is fragile

**Location:** `rlm_adk/orchestrator.py`, lines 170-175

```python
exc_str = str(exc)
is_transient = any(
    code in exc_str
    for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")
)
```

**Problem:** The error classification converts exceptions to strings and checks for
substring containment. This is fragile because:

1. A generic `Exception("Error processing item 503 in batch")` would be incorrectly
   classified as a transient server error, triggering retries when the error is
   actually a bug in user code.
2. Any exception whose traceback, message, or repr happens to contain the strings
   "503", "429", "UNAVAILABLE", or "RESOURCE_EXHAUSTED" will be misclassified.
3. The Google GenAI SDK already provides typed error classes:
   - `google.genai.errors.ServerError` (inherits from `APIError`) -- has a `.code`
     attribute (int) and `.status` attribute (str).
   - `google.genai.errors.ClientError` (inherits from `APIError`) -- same attributes.
   These should be used with `isinstance()` checks and numeric code comparison.

### (B) `reasoning_succeeded` dead code

**Location:** `rlm_adk/orchestrator.py`, lines 162, 167-168, 190-191

```python
reasoning_succeeded = False          # line 162
for attempt in range(max_retries + 1):
    try:
        async for event in self.reasoning_agent.run_async(ctx):
            yield event
        reasoning_succeeded = True   # line 167
        break                        # line 168
    except Exception as exc:
        ...
        if not is_transient or attempt >= max_retries:
            raise                    # always raised on final attempt
        ...

if not reasoning_succeeded:          # line 190 -- UNREACHABLE
    print(...)                       # line 191 -- UNREACHABLE
```

**Problem:** The retry loop has exactly two exit paths:
1. **Success:** `reasoning_succeeded = True` is set, then `break`.
2. **Failure:** The exception is re-raised via `raise`, unwinding the stack past
   the `if not reasoning_succeeded:` check entirely.

There is no path where the loop completes all iterations without either setting
`reasoning_succeeded = True` or raising. The `for` loop itself would only exhaust
naturally if `max_retries + 1 == 0` (impossible since `max_retries >= 0`), and even
then the `try` block would either succeed or raise. Therefore lines 190-191 are dead
code that can never execute.

### (C) Tenacity retries disabled by default

**Location:** `rlm_adk/agent.py`, lines 52-99

The `create_reasoning_agent()` factory creates an `LlmAgent` but does not configure
any retry options for the underlying Gemini model client. The Google GenAI SDK supports
tenacity-based retry configuration, but when no retry config is provided, the client
defaults to `stop_after_attempt(1)` -- meaning zero retries.

This places all retry responsibility on the orchestrator's manual retry loop (sub-issue A),
which itself has the string-matching fragility described above. Enabling tenacity retries
at the SDK level would provide a proper first line of defense for transient HTTP errors
(503, 429) with exponential backoff, complementing the orchestrator-level retries.

Neither `create_reasoning_agent()` nor `create_rlm_orchestrator()` accept or pass through
a retry configuration parameter.

## Evidence from Logs

The debug YAML (`rlm_adk_debug.yaml`) from a successful session shows 15 reasoning calls
completed without errors:

```
obs:total_calls: 15
obs:total_input_tokens: 477118
obs:total_output_tokens: 6902
```

No `model_error`, `ServerError`, `503`, or `UNAVAILABLE` entries were found in the current
debug log, which means the bug has not manifested in this particular recorded session.
However, the code path is clearly exercisable under server load or quota pressure --
the retry logic exists precisely for these scenarios, and its incorrect string-matching
classification poses a latent risk of:
- Retrying non-transient errors (wasting time and tokens)
- Not retrying actual transient errors that don't match the string patterns

The dead code (sub-issue B) suggests the retry logic was written with incomplete control
flow analysis and may not have been thoroughly tested.

## Resolution

**Status:** Fixed

### What was fixed

**(A) Type-based error classification** (`rlm_adk/orchestrator.py`):
- Extracted error classification into a new public function `is_transient_error(exc)`.
- The function uses `isinstance(exc, (ServerError, ClientError))` to verify the
  exception originates from the Google GenAI SDK, then checks `exc.code` against a
  frozenset of known transient HTTP status codes (`{408, 429, 500, 502, 503, 504}`).
- Generic exceptions (e.g., `Exception("item 503 in batch")`) are no longer
  misclassified as transient. Only typed SDK errors with matching status codes
  trigger retries.
- Imported `ServerError`, `ClientError`, and `APIError` from `google.genai.errors`.

**(B) Dead `reasoning_succeeded` code removed** (`rlm_adk/orchestrator.py`):
- Removed the `reasoning_succeeded = False` variable initialization.
- Removed the `reasoning_succeeded = True` assignment inside the try block.
- Removed the unreachable `if not reasoning_succeeded:` block and its warning print.
- The retry loop now simply `break`s on success (no sentinel variable needed).

**(C) Retry config pass-through** (`rlm_adk/agent.py`):
- Added a module-level `_DEFAULT_RETRY_OPTIONS` constant: `HttpRetryOptions(attempts=3,
  initial_delay=1.0, max_delay=60.0, exp_base=2.0)`.
- Added `_build_generate_content_config(retry_config)` helper that converts a
  user-provided dict (or the defaults) into a `GenerateContentConfig` with
  `HttpOptions.retry_options` set.
- Added `retry_config: dict[str, Any] | None = None` parameter to both
  `create_reasoning_agent()` and `create_rlm_orchestrator()`.
- When `retry_config` is `None` (the default), sensible defaults (3 attempts,
  exponential backoff) are applied. Callers can pass a custom dict with
  `HttpRetryOptions` field names (`attempts`, `initial_delay`, `max_delay`,
  `exp_base`, `jitter`, `http_status_codes`) to customize.
- The `generate_content_config` is now set on the `LlmAgent`, enabling the SDK's
  built-in tenacity retries as a first line of defense before the orchestrator-level
  retry loop kicks in.

### Test results

15 new tests in `tests_rlm_adk/test_bug001_orchestrator_retry.py`:

- **Sub-issue A (7 tests):** ServerError 503 classified as transient; ClientError 429
  classified as transient; generic Exception with "503" in message NOT classified as
  transient; generic Exception with "429" NOT transient; ServerError 500 is transient;
  ClientError 400 is NOT transient; source code no longer contains `exc_str` or
  string literal `"503"` for matching.
- **Sub-issue B (3 tests):** `reasoning_succeeded` variable absent from source;
  unreachable warning message absent; class still importable and valid.
- **Sub-issue C (5 tests):** `create_reasoning_agent` accepts `retry_config`;
  `create_rlm_orchestrator` accepts `retry_config`; custom retry config reaches
  `generate_content_config`; default factory sets up retry config; orchestrator
  forwards config to reasoning agent.

Full suite: **261 passed, 0 failed** (0.44s). No regressions.

### Concerns and caveats

1. **Two layers of retry:** The system now has retry at two levels -- the SDK-level
   `HttpRetryOptions` (tenacity-based, handles raw HTTP 5xx/429) and the
   orchestrator-level retry loop (handles SDK-raised `ServerError`/`ClientError`).
   These are complementary but could result in up to `sdk_attempts * orchestrator_retries`
   total attempts in the worst case. The defaults (3 SDK attempts x 4 orchestrator
   attempts = 12 max) are reasonable, but callers should be aware of the multiplicative
   effect.

2. **`create_rlm_app` and `create_rlm_runner` do not expose `retry_config`:** The
   higher-level factory functions do not yet pass through the `retry_config` parameter.
   This is acceptable for now since the defaults are sensible, but a future enhancement
   should thread it through the full factory chain for callers who need custom retry
   behavior via the top-level API.

3. **The `import time` and `import uuid` in `orchestrator.py`:** The `time` import
   appears unused after the changes; `uuid` was added by a linter for the `REQUEST_ID`
   feature. These are cosmetic and do not affect correctness.
