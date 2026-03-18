# Refined Engineering Prompt: Child Dispatch 429 Rate-Limit Backoff and Observability

## Objective

Fix the child orchestrator dispatch path so that HTTP 429 (rate-limit) errors from the `google.genai` client are (1) correctly classified, (2) retried with exponential backoff instead of failing immediately, and (3) recorded in the observability pipeline (both in-memory state and the `traces.db` SQLite database).

## Background

Currently there are **two** retry/backoff mechanisms in the codebase, operating at different levels:

- **Parent-level retry** in `rlm_adk/orchestrator.py` (lines 447-491): `is_transient_error()` + exponential backoff loop around `reasoning_agent.run_async(ctx)`. This already handles 429s correctly for the root reasoning agent via `_TRANSIENT_STATUS_CODES` (line 72) and `google.genai.errors.ClientError` / `ServerError` type checks (lines 82-83).

- **Child dispatch path** in `rlm_adk/dispatch.py`: The `_run_child()` function (lines 383-653) spawns a child `RLMOrchestratorAgent` but catches exceptions only in a bare `except Exception` block (line 501) with **no retry loop and no backoff**. When a child hits a 429, the exception is caught once, classified, and returned as an error `LLMResult` -- the child fails immediately.

## Problem Analysis

### Problem 1: Child dispatch has no retry loop for transient errors

In `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py`, the `_run_child()` function (line 383) has a single `try/except` around `child.run_async(child_ctx)` (line 440). When a 429 propagates up from the child's inner `reasoning_agent.run_async()`, the child orchestrator's own retry loop (in `orchestrator.py` lines 450-491) may or may not catch it depending on whether the error escapes that inner loop. If the child orchestrator itself exhausts its retries, the exception reaches `_run_child()`'s `except` block and is immediately returned as a failed `LLMResult` with no further retry at the dispatch level.

The fix should add an **optional dispatch-level retry with backoff** in `_run_child()` for transient errors (reusing `is_transient_error()` from `rlm_adk/orchestrator.py`, line 76). This gives child dispatches a second chance when the child orchestrator's own retries are exhausted.

### Problem 2: `_classify_error()` may miss 429s from `google.genai.errors.ClientError`

In `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py`, `_classify_error()` (line 58) checks `getattr(error, "code", None)` and `getattr(error, "status_code", None)`. The `google.genai.errors.ClientError` class (confirmed in `.venv/lib/python3.12/site-packages/google/genai/errors.py`, line 232) inherits from `APIError` which sets `self.code` as an `int` in `__init__` (line 52). So `code == 429` (line 78) **should** work for `ClientError`.

However, there is a gate in `_run_child()`'s except block at line 504-505:

```python
cat = "SCHEMA_VALIDATION_EXHAUSTED" if output_schema is not None else (
    _classify_error(e) if (hasattr(e, "code") or hasattr(e, "status_code")) else "UNKNOWN"
)
```

This means:
- If `output_schema is not None`, the error is **always** classified as `SCHEMA_VALIDATION_EXHAUSTED` regardless of the actual HTTP status code. A 429 during a structured-output child dispatch would be misclassified.
- The `hasattr` guard is redundant since `_classify_error()` already handles missing attributes gracefully.

**Fix**: Always call `_classify_error(e)` first. Only fall back to `SCHEMA_VALIDATION_EXHAUSTED` if the error is not a recognized transient HTTP error.

### Problem 3: Observability records the error but doesn't distinguish retried-then-succeeded vs. failed

The observability path for child errors flows through:
1. `_acc_child_error_counts` dict in dispatch closures (line 203) -- accumulated per `_run_child()` call
2. `flush_fn()` (line 783) writes `OBS_CHILD_ERROR_COUNTS` to `tool_context.state`
3. `ObservabilityPlugin.after_run_callback()` in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py` (line 344) reads `OBS_CHILD_ERROR_COUNTS` from session state
4. `SqliteTracingPlugin.after_run_callback()` in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py` (line 758) writes `child_error_counts` JSON to the `traces` table
5. `session_report.py` (line 264-270) queries `telemetry` table for rate-limit errors using pattern matching on `error_type`/`error_message`

If dispatch-level retries are added, the observability pipeline should also record:
- **`obs:child_retry_counts`**: A dict of `{error_category: retry_count}` showing how many retries occurred per category
- Update the per-child summary dict (written at line 572) with a `"dispatch_retry"` sub-dict showing `{"attempts": N, "delay_ms": total_delay, "recovered": bool}`

## Files to Modify

| File | What to Change |
|------|----------------|
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py` | (1) Add dispatch-level retry loop with backoff in `_run_child()` around lines 428-445. (2) Fix error classification at lines 504-505 to not unconditionally mask 429s as SCHEMA_VALIDATION_EXHAUSTED. (3) Add `_acc_child_retry_counts` accumulator and include it in `flush_fn()` output. (4) Add retry metadata to per-child summary dict. |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py` | Add `OBS_CHILD_RETRY_COUNTS = "obs:child_retry_counts"` constant (after line 101). |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py` | Read and log `OBS_CHILD_RETRY_COUNTS` in `after_run_callback()` (around line 344). |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py` | (1) Add `child_retry_counts TEXT` column to the `traces` table schema (after line 223). (2) Write the retry counts JSON in `after_run_callback()` alongside `child_error_counts`. |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/eval/session_report.py` | Update the rate-limit error query (lines 264-270) to also count retried-then-recovered dispatches from the new `child_retry_counts` column. |

## Implementation Guidance

### Retry loop in `_run_child()` (dispatch.py)

Reuse `is_transient_error()` from `rlm_adk/orchestrator.py` (line 76). The retry parameters should be configurable via env vars for consistency with the parent-level retry:

```
RLM_CHILD_MAX_RETRIES (default: 2)
RLM_CHILD_RETRY_DELAY (default: 3.0 seconds)
```

Read these once in `create_dispatch_closures()` (not inside the hot loop). The backoff should be exponential: `delay * (2 ** attempt)`.

The retry loop wraps the `async with _child_semaphore:` block (lines 429-444). On transient error, log a warning, sleep, and retry. On non-transient error or retry exhaustion, fall through to the existing error-handling path.

### Error classification fix (dispatch.py, line 504)

Replace:
```python
cat = "SCHEMA_VALIDATION_EXHAUSTED" if output_schema is not None else (
    _classify_error(e) if (hasattr(e, "code") or hasattr(e, "status_code")) else "UNKNOWN"
)
```

With logic that calls `_classify_error(e)` first. If the result is a transient category (`RATE_LIMIT`, `SERVER`, `TIMEOUT`, `NETWORK`), use that classification regardless of `output_schema`. Only fall back to `SCHEMA_VALIDATION_EXHAUSTED` for non-transient errors when `output_schema is not None`.

### Observability additions

Follow the existing accumulator pattern (AR-CRIT-001 compliant):
- Add `_acc_child_retry_counts: dict[str, int] = {}` alongside `_acc_child_error_counts` (line 203)
- Increment in the retry loop: `_acc_child_retry_counts[cat] = _acc_child_retry_counts.get(cat, 0) + 1`
- Flush in `flush_fn()` alongside `OBS_CHILD_ERROR_COUNTS`
- The per-child summary (line 572) should include `"dispatch_retry": {"attempts": N, "total_delay_ms": M, "recovered": bool}`

### SqliteTracingPlugin schema migration

The plugin uses `_ensure_columns()` (around line 390) to add missing columns at startup. Add:
```python
("child_retry_counts", "TEXT"),
```
to the `traces` table column list.

## Testing

### Unit tests

Add tests to the default test suite (not `-m ""` full suite):

1. **`_classify_error` with `google.genai.errors.ClientError(429, ...)`**: Verify it returns `"RATE_LIMIT"`. (This likely already works but confirm with a targeted test.)
2. **`_classify_error` with a mock exception having `status_code=429` but no `code`**: Verify the LiteLLM fallback path returns `"RATE_LIMIT"`.
3. **Error classification priority over SCHEMA_VALIDATION_EXHAUSTED**: Create a `ClientError(429, ...)` and call the fixed classification logic with `output_schema=SomeModel`. Verify the result is `"RATE_LIMIT"`, not `"SCHEMA_VALIDATION_EXHAUSTED"`.

### Provider-fake fixture

The existing `worker_429_mid_batch.json` fixture at `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/worker_429_mid_batch.json` is currently excluded from the default test run (see `_WORKER_FIXTURE_EXCLUSIONS` in `test_provider_fake_e2e.py`, line 44). This fixture was designed for the old leaf-worker architecture. Consider creating a new child-orchestrator-compatible fixture that exercises the retry path, or adapt the existing one.

### Run commands

```bash
# Default contract tests (should still pass)
.venv/bin/python -m pytest tests_rlm_adk/ -x -q

# Focused test for new/changed tests
.venv/bin/python -m pytest tests_rlm_adk/test_your_new_file.py -x -q

# Lint
ruff check rlm_adk/ tests_rlm_adk/
ruff format --check rlm_adk/ tests_rlm_adk/
```

## Constraints

- **AR-CRIT-001**: All state mutations in dispatch closures must use local accumulators + `flush_fn()`. Never write `ctx.session.state[key] = value` directly.
- **Never run `pytest -m ""`** for routine verification.
- The `google.genai.errors.APIError.code` attribute is an `int` set in `__init__`. It is always present on `ClientError` and `ServerError` instances created by the SDK's `raise_for_response()` / `raise_error()` class methods.
- Child orchestrators already have their own internal retry loop (inherited from `RLMOrchestratorAgent._run_async_impl`). The dispatch-level retry is an outer safety net, not a replacement. Keep retry counts low (default 2) to avoid excessive latency.
