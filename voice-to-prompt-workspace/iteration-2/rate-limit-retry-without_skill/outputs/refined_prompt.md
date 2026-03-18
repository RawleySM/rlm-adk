# Rate-Limit Backoff for Child Dispatch

## Goal

When a child orchestrator's LLM call receives an HTTP 429 (rate limit) from the genai API, the system should perform exponential backoff retries instead of failing immediately. Currently the child-level retry in `orchestrator.py` handles this for the reasoning agent, but errors caught in the dispatch exception handler in `dispatch.py` may misclassify 429s due to a guarded `_classify_error` call. Fix the classification, ensure the child orchestrator's retry loop fires for rate-limited children, and verify the error category flows through the observability pipeline into `traces.db`.

## Context

There are two retry layers in this codebase:

1. **Orchestrator-level retry** (`/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py`, lines 447-503): Wraps `reasoning_agent.run_async(ctx)` in a retry loop. Uses `is_transient_error()` (line 76-93) which checks `isinstance(exc, (ServerError, ClientError))` and then `getattr(exc, "code", None) in _TRANSIENT_STATUS_CODES` where `_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})` (line 72). This correctly handles 429s from `google.genai.errors.ClientError` because `APIError.code` is an `int` attribute set in `__init__` (confirmed via source inspection of `google.genai.errors.APIError`).

2. **Dispatch exception handler** (`/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py`, lines 501-516): Catches exceptions from `child.run_async(child_ctx)`. At line 504-505, the error classification is:
   ```python
   cat = "SCHEMA_VALIDATION_EXHAUSTED" if output_schema is not None else (
       _classify_error(e) if (hasattr(e, "code") or hasattr(e, "status_code")) else "UNKNOWN"
   )
   ```

## Problems to Fix

### Problem 1: Dispatch exception handler guard is too narrow (dispatch.py line 505)

The guard `hasattr(e, "code") or hasattr(e, "status_code")` before calling `_classify_error` is unnecessary. The `_classify_error` function (lines 58-97) already handles the case where `code` is `None` -- it falls through to type-based checks (`isinstance(error, (ConnectionError, OSError))`, JSON decode checks, etc.) and returns `"UNKNOWN"` as a safe default. The guard prevents `_classify_error` from being called on exceptions that lack both attributes, but `_classify_error` would correctly return `"UNKNOWN"` for those anyway, plus the guard prevents classification of exceptions like `asyncio.TimeoutError` and `ConnectionError` which `_classify_error` handles via `isinstance` checks on lines 68-86.

**Fix:** Remove the `hasattr` guard so `_classify_error(e)` is always called when `output_schema is None`:
```python
cat = "SCHEMA_VALIDATION_EXHAUSTED" if output_schema is not None else _classify_error(e)
```

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py`, line 504-505.

### Problem 2: Dispatch exception handler short-circuits to SCHEMA_VALIDATION_EXHAUSTED for all errors when output_schema is set

When `output_schema is not None`, every exception -- including 429 rate limits -- is classified as `"SCHEMA_VALIDATION_EXHAUSTED"` (line 504). A 429 from a child with `output_schema` should still be classified as `"RATE_LIMIT"`, not `"SCHEMA_VALIDATION_EXHAUSTED"`.

**Fix:** Only classify as `SCHEMA_VALIDATION_EXHAUSTED` when the error is genuinely a schema validation failure (i.e., not a transport/API error). Use `_classify_error(e)` first; if it returns `"UNKNOWN"` and `output_schema` is set, then fall back to `"SCHEMA_VALIDATION_EXHAUSTED"`:
```python
cat = _classify_error(e)
if cat == "UNKNOWN" and output_schema is not None:
    cat = "SCHEMA_VALIDATION_EXHAUSTED"
if cat == "SCHEMA_VALIDATION_EXHAUSTED":
    _acc_structured_output_failures += 1
```

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py`, lines 504-508.

### Problem 3: Child orchestrators already have retry logic, but verify it fires for child dispatches

Each child orchestrator is a full `RLMOrchestratorAgent` instance created by `create_child_orchestrator()`. Its `_run_async_impl` (orchestrator.py line 227) already wraps `reasoning_agent.run_async(ctx)` in the retry loop (lines 447-503) using `is_transient_error()`. This means a 429 from the genai API during a child's LLM call should trigger retry with exponential backoff (`delay = base_delay * (2**attempt)`, line 478) inside the child's own orchestrator, before the error ever reaches the dispatch exception handler.

**Verify:** Confirm the child orchestrator's retry env vars (`RLM_LLM_MAX_RETRIES`, `RLM_LLM_RETRY_DELAY`) apply at child depth. The defaults are `max_retries=3`, `base_delay=5.0` (lines 447-448). If the intent is for children to retry faster (or not at all), expose these as parameters on `create_child_orchestrator()` in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py`.

**Verify:** The existing provider-fake fixture `worker_429_mid_batch.json` (`/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/worker_429_mid_batch.json`) injects five consecutive 429 faults at call indices 2, 4, 5, 6, 7. The child orchestrator retries are configured with `"retry_delay": 0.0` in the fixture config (line 8). Confirm whether the child's retry loop exhausts all attempts before the error propagates to the dispatch handler. If the child retries and eventually its reasoning turn succeeds (call index 8 returns a text answer), the error never reaches dispatch.py's exception handler at all -- it is handled inside the child.

### Problem 4: Observability pipeline must surface RATE_LIMIT errors in traces.db

The observability path for child errors flows through:

1. **Dispatch accumulators** (`dispatch.py` lines 747-751): After `asyncio.gather` completes, errors from `all_results` are accumulated into `_acc_child_error_counts` dict keyed by `error_category`.
2. **flush_fn** (`dispatch.py` lines 783-812): Snapshots `_acc_child_error_counts` into `OBS_CHILD_ERROR_COUNTS` state key.
3. **SqliteTracingPlugin.on_event_callback** (`/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py`): Picks up the `state_delta` event containing `OBS_CHILD_ERROR_COUNTS` and inserts a row in `session_state_events` table with `key_category = "obs_dispatch"`.
4. **SqliteTracingPlugin.after_agent_callback**: Reads `OBS_CHILD_ERROR_COUNTS` from session state and writes it to the `child_error_counts` JSON column in the `traces` table.

**Verify:** After fixing Problem 1 and 2, run the existing test `test_fixture_contract[worker_429_mid_batch]` and confirm:
- `obs:child_error_counts` contains a `"RATE_LIMIT"` key (or the child handled the error internally and it shows up in the child summary's `error_category`).
- The `obs:child_summary@d1f{N}` state key for the failed child has `"error_category": "RATE_LIMIT"` (not `"UNKNOWN"`).
- The `traces.child_error_counts` column in `traces.db` includes the `RATE_LIMIT` entry.

**Note on current test fixture:** The `worker_429_mid_batch` fixture's child B eventually succeeds via a reasoning turn (call index 8) that summarizes the failure. This means the child's `_rlm_completion` text contains `"rate limit retry exhausted"` but the child itself is not marked `error=True` because it produced a final answer. The 429s are absorbed by the child's SDK-level or app-level retry. The `obs:child_error_counts` in this fixture's expected contract does NOT assert `RATE_LIMIT` -- it expects the error to be handled within the child. To test the classification fix, you may need a new fixture where the child's retry is exhausted and the error propagates to dispatch.

## Implementation Steps

1. **Read** the dispatch_and_state branch doc: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/dispatch_and_state.md`

2. **Fix** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py` lines 504-508:
   - Replace the guarded classification with unconditional `_classify_error(e)` call
   - Only fall back to `SCHEMA_VALIDATION_EXHAUSTED` when `_classify_error` returns `UNKNOWN` and `output_schema is not None`

3. **Add unit tests** for `_classify_error` with `google.genai.errors.ClientError(429, ...)`:
   - File: `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/` (new or existing test file)
   - Test that `_classify_error(ClientError(429, {"error": {"code": 429, "message": "Rate limited"}}))` returns `"RATE_LIMIT"`
   - Test that `_classify_error(asyncio.TimeoutError())` returns `"TIMEOUT"` (previously blocked by `hasattr` guard in the dispatch handler -- the function itself handles it, but confirm no regression)
   - Test that `_classify_error(ConnectionError())` returns `"NETWORK"`

4. **Run existing tests** to verify no regression:
   ```bash
   .venv/bin/python -m pytest tests_rlm_adk/ -x -q
   ```

5. **Verify observability** by checking that the `worker_429_mid_batch` fixture's child summary includes proper error categorization after the fix. If needed, add an assertion to `expected_contract.observability` for `RATE_LIMIT` in the error counts (only if child errors now propagate differently after the fix).

## Files Involved

| File | Lines | Role |
|------|-------|------|
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py` | 58-97 (\_classify\_error), 501-516 (exception handler) | Error classification + dispatch catch block |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py` | 72-93 (is\_transient\_error, \_TRANSIENT\_STATUS\_CODES), 447-503 (retry loop) | Child orchestrator retry logic |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py` | 97-101 | OBS\_CHILD\_ERROR\_COUNTS and related keys |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py` | 343-344 | after\_run reads child\_error\_counts |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py` | (traces table schema) | Persists child\_error\_counts to traces.db |
| `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/worker_429_mid_batch.json` | Full file | Existing 429 test fixture |
| `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/worker_auth_error_401.json` | Full file | Reference: similar error fixture pattern |

## Testing

```bash
# Default test suite (regression check)
.venv/bin/python -m pytest tests_rlm_adk/ -x -q

# Specific fixture test
.venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -k "worker_429_mid_batch" -x -v
```

**NEVER** run `pytest -m ""` -- it triggers the full 970+ test suite.
