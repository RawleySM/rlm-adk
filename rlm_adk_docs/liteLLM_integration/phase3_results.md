<!-- phase3: completed 2026-03-09 -->

# Phase 3: Error Handling — Results

## Summary

Extended `is_transient_error` (orchestrator) and `_classify_error` (worker callbacks) to correctly
handle LiteLLM exception types. Also fixed the `dispatch.py` error-classification guard to recognize
`status_code` in addition to `code`.

## Key Finding: LiteLLM `status_code` vs `code`

LiteLLM exceptions use `status_code` (int) as the canonical HTTP status attribute.
The `code` attribute exists but is a **string** (e.g., `'429'`) for some exception types
and `None` for others (InternalServerError, AuthenticationError, Timeout, ServiceUnavailableError).
This means the existing `_classify_error` logic (which compares `code` against integer literals)
silently falls through to `"UNKNOWN"` for most LiteLLM exceptions.

| Exception | `.code` | `.status_code` |
|-----------|---------|----------------|
| `RateLimitError` | `'429'` (str) | `429` (int) |
| `InternalServerError` | `None` | `500` (int) |
| `AuthenticationError` | `None` | `401` (int) |
| `ServiceUnavailableError` | `None` | `503` (int) |
| `BadRequestError` | `None` | `400` (int) |
| `Timeout` | `None` | `408` (int) |

## MED-1 Resolution

Verified litellm exception constructors via `inspect.signature`. All APIStatusError subclasses
accept `(message, llm_provider, model, ...)` positional args. `Timeout` uses `(message, model, llm_provider, ...)`.
Real exception instances used in tests (no MagicMock needed).

## Changes Made

### `rlm_adk/callbacks/worker.py` — `_classify_error`
- Added `status_code` fallback: when `code` is None or non-integer, uses `status_code` (int) instead
- Added `litellm.Timeout` detection (not an `asyncio.TimeoutError` subclass, needs explicit check)

### `rlm_adk/orchestrator.py` — `is_transient_error`
- Added LiteLLM exception branches after existing google.genai + httpx checks
- Transient: `RateLimitError`, `InternalServerError`, `Timeout`, `ServiceUnavailableError`
- Non-transient: `AuthenticationError`, `BadRequestError`
- Guarded by `try/except ImportError` (zero impact when litellm not installed)

### `rlm_adk/dispatch.py` — exception handler guard
- Changed `hasattr(e, "code")` to `hasattr(e, "code") or hasattr(e, "status_code")`
- Ensures LiteLLM exceptions (which have `status_code` but may lack `code`) are classified
  instead of falling through to `"UNKNOWN"`

### `tests_rlm_adk/test_litellm_errors.py` — 19 tests
- `TestClassifyLiteLLMErrors` (6 tests): rate_limit, server, auth, service_unavailable, bad_request, timeout
- `TestIsTransientLiteLLM` (6 tests): rate_limit, auth, server, timeout, service_unavailable, bad_request
- `TestExistingGeminiErrorsUnchanged` (7 tests): gemini ServerError, ClientError 429, ClientError 400,
  classify ServerError, classify rate_limit, asyncio timeout (both functions)

## Test Results

```
tests_rlm_adk/test_litellm_errors.py: 19 passed (marker: unit_nondefault)
Existing suite (default markers):      28 passed, 2 skipped, 0 failed
```

## Acceptance Criteria

- [x] `_classify_error(litellm.RateLimitError(...))` returns `"RATE_LIMIT"`
- [x] `_classify_error(litellm.InternalServerError(...))` returns `"SERVER"`
- [x] `_classify_error(litellm.AuthenticationError(...))` returns `"AUTH"`
- [x] `_classify_error(litellm.Timeout(...))` returns `"TIMEOUT"`
- [x] `is_transient_error(litellm.RateLimitError(...))` returns `True`
- [x] `is_transient_error(litellm.AuthenticationError(...))` returns `False`
- [x] Existing Gemini error paths unchanged (7 regression tests pass)
- [x] No regressions in existing test suite
