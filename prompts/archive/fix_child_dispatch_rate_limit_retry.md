<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Fix Child Dispatch Rate-Limit Retry and Observability

## Context

Child orchestrator dispatches in `rlm_adk/dispatch.py` fail immediately on 429 (rate-limit) errors instead of backing off and retrying. The orchestrator-level retry logic (`is_transient_error` + exponential backoff in `orchestrator.py`) only protects the root reasoning agent's LLM calls -- child dispatches spawned via `_run_child()` have no retry loop. Additionally, the error classification gate in `_run_child()`'s `except` clause may suppress `_classify_error()` for `google.genai.errors.ClientError` exceptions that carry a `code` attribute (since the `hasattr` guard is satisfied, this specific path works), but the broader concern is that child 429s are classified correctly yet never retried. The observability pipeline must record these rate-limit errors in `traces.db` so they are visible in post-run analysis.

## Original Transcription

> ok so I need to uh change the dispatch thing so that when a child agent hits a rate limit it actually backs off properly instead of just failing immediately. Right now I think the retry logic in the worker callback isn't catching 429s from the genai client correctly because it's checking the wrong attribute on the exception. Also the error classification function in dispatch dot py needs to handle that case. Oh and make sure the observability stuff picks it up too so I can see it in the traces database.

## Refined Instructions

1. **Add retry-with-backoff to `_run_child()` in `rlm_adk/dispatch.py` (line 383).**
   The `_run_child` inner function currently has a single `try/except` around the child orchestrator `run_async` call (lines 428-516). When a `ClientError` with `code=429` (or any transient error) is raised, the child fails immediately and the error is classified and returned as an `LLMResult(error=True)`. Add an exponential-backoff retry loop around the child orchestrator execution, similar to the pattern in `orchestrator.py` lines 447-491 (`is_transient_error` + `asyncio.sleep(delay)`). Respect configurable max retries (env var `RLM_CHILD_MAX_RETRIES`, default 2) and base delay (env var `RLM_CHILD_RETRY_DELAY`, default 2.0 seconds). Only retry on transient errors as defined by `is_transient_error()` from `orchestrator.py`.

2. **Verify `_classify_error()` in `rlm_adk/dispatch.py` (line 58) correctly handles `google.genai.errors.ClientError`.**
   The function already checks `code == 429` and returns `"RATE_LIMIT"` (line 78-79). The `google.genai.errors.ClientError` class inherits from `APIError` which defines `code: int` as an instance attribute set in `__init__`. So `getattr(error, "code", None)` will return the integer status code. However, the `except` clause in `_run_child()` (line 504-505) has a guard: `_classify_error(e) if (hasattr(e, "code") or hasattr(e, "status_code")) else "UNKNOWN"`. This guard passes for `ClientError` (which has `code`), so classification works. **No change needed here** -- but confirm this with a test (see step 5). *[Added -- the transcription implied this was broken, but code inspection shows the classification path works for genai exceptions. The real bug is the absence of retry, not misclassification.]*

3. **Track child retry attempts in dispatch accumulators.**
   Add a new local accumulator `_acc_child_retry_counts: dict[str, int]` (keyed by error category, e.g. `{"RATE_LIMIT": 2, "SERVER": 1}`) to the closure state in `create_dispatch_closures()`. When `_run_child()` retries a transient error, increment the appropriate category count. Add a new state key `OBS_CHILD_RETRY_COUNTS = "obs:child_retry_counts"` in `rlm_adk/state.py` and flush it in `flush_fn()`.

4. **Ensure `SqliteTracingPlugin` persists child retry counts to `traces.db`.**
   The plugin at `rlm_adk/plugins/sqlite_tracing.py` already persists `child_error_counts` (line 223, 728, 758). Add a parallel column `child_retry_counts TEXT` to the traces table schema and wire it through the same pattern: read from `state.get("obs:child_retry_counts")`, JSON-serialize, and write to the column. This ensures rate-limit retries are visible in the traces database.

5. **Add/update tests to cover the new retry behavior.**
   - Add a test in `tests_rlm_adk/` that verifies `_classify_error()` returns `"RATE_LIMIT"` when given a `google.genai.errors.ClientError` with `code=429`. Create the exception via `ClientError(429, {"error": {"message": "rate limited", "status": "RESOURCE_EXHAUSTED"}})`.
   - Add a test that verifies `is_transient_error()` returns `True` for the same `ClientError(429, ...)`.
   - Add a contract test (or extend an existing provider-fake fixture) that exercises the child retry path: the first child dispatch returns a 429, the retry succeeds, and `OBS_CHILD_RETRY_COUNTS` in the final state contains `{"RATE_LIMIT": 1}`.

6. **Import `is_transient_error` into `dispatch.py`.** *[Added -- the transcription didn't mention this, but step 1 requires reusing the orchestrator's transient-error classifier. Import it rather than duplicating the logic.]*
   Add `from rlm_adk.orchestrator import is_transient_error` at the top of `dispatch.py`. Be mindful of circular imports -- `orchestrator.py` already imports from `dispatch.py`. If a circular import arises, extract `is_transient_error` and `_TRANSIENT_STATUS_CODES` into a shared module (e.g., `rlm_adk/errors.py`) and import from there in both files.

## Considerations

- **AR-CRIT-001 compliance**: The new retry accumulator must follow the same local-accumulator + flush_fn pattern as the existing accumulators. Never write retry counts directly to `ctx.session.state`.
- **Scope boundary**: The orchestrator-level retry in `orchestrator.py` (lines 447-491) handles transient errors from the *reasoning agent's own LLM calls*. The child dispatch retry in `dispatch.py` handles transient errors from *child orchestrator execution*. These are independent retry loops at different levels of the call stack. Do not merge them.
- **Child semaphore interaction**: The retry loop should occur *inside* the `async with _child_semaphore:` block so that a retrying child does not release and re-acquire the semaphore (which could cause starvation). Alternatively, if retries should not hold the semaphore during backoff sleep, place the retry loop *outside* the semaphore and re-acquire on each attempt. Choose based on whether you want to block other children during backoff. Document the choice.
- **No retry for `SCHEMA_VALIDATION_EXHAUSTED`**: The existing `except` clause treats all exceptions as schema validation failures when `output_schema is not None` (line 504). This should be refined -- a 429 during a child dispatch with an output schema is still a rate-limit error, not a schema validation failure. The `output_schema is not None` check should only apply when the exception is actually a schema validation error, not a transport-level error.
- **Testing**: Run `.venv/bin/python -m pytest tests_rlm_adk/` (default ~28 contract tests) after changes. Do NOT run `-m ""`. For focused TDD, use `-x -q` on your specific test file.
- **Existing retry paths**: `WorkerRetryPlugin` in `callbacks/worker_retry.py` handles *structured output validation* retries (set_model_response tool errors), not LLM-level transport errors. It is unrelated to this change -- do not modify it.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/dispatch.py` | `_classify_error()` | L58 | Error classification function -- already handles 429 correctly |
| `rlm_adk/dispatch.py` | `create_dispatch_closures()` | L167 | Closure factory -- add retry accumulator here |
| `rlm_adk/dispatch.py` | `_run_child()` | L383 | Child orchestrator execution -- add retry loop here |
| `rlm_adk/dispatch.py` | `except Exception as e` | L501 | Exception handler with hasattr guard -- refine schema-vs-transport classification |
| `rlm_adk/dispatch.py` | `flush_fn()` | L783 | Accumulator flush -- add retry counts to delta |
| `rlm_adk/orchestrator.py` | `is_transient_error()` | L76 | Transient error classifier -- reuse for child retry |
| `rlm_adk/orchestrator.py` | `_TRANSIENT_STATUS_CODES` | L72 | Status code set `{408, 429, 500, 502, 503, 504}` |
| `rlm_adk/state.py` | `OBS_CHILD_ERROR_COUNTS` | L99 | Existing error counts key -- add parallel retry counts key |
| `rlm_adk/plugins/observability.py` | `ObservabilityPlugin` | L50 | Reads `OBS_CHILD_ERROR_COUNTS` in `after_run_callback` -- extend for retry counts |
| `rlm_adk/plugins/sqlite_tracing.py` | `SqliteTracingPlugin` | L318 | Persists `child_error_counts` to traces.db -- add `child_retry_counts` column |
| `rlm_adk/plugins/sqlite_tracing.py` | `child_error_counts` column | L223 | Schema definition for the traces table |
| `rlm_adk/callbacks/worker_retry.py` | `WorkerRetryPlugin` | L79 | Structured output retry -- NOT related to this change |
| `.venv/.../google/genai/errors.py` | `APIError` / `ClientError` | L29-234 | `code: int` attribute set in `__init__` from HTTP status code |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` -- compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` -- documentation entrypoint (follow branch links for **Dispatch & State** and **Observability**)
3. `rlm_adk_docs/dispatch_and_state.md` -- full dispatch closure and accumulator reference
4. `rlm_adk_docs/observability.md` -- plugin architecture and worker obs path
