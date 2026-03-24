<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Fix Child Dispatch Rate-Limit Retry and Observability

## Context

Child orchestrator dispatches in `rlm_adk/dispatch.py` fail immediately on HTTP 429 (rate-limit) errors instead of backing off and retrying. The orchestrator-level retry logic (`is_transient_error` + exponential backoff) only protects the root reasoning agent's LLM calls -- child dispatches spawned via `_run_child()` have no retry loop. The error classification function `_classify_error()` already handles 429s correctly (the `google.genai.errors.ClientError` class exposes `.code` as an `int`), but the exception handler gate in `_run_child()` line 504 that decides whether to call `_classify_error()` could be tightened. The observability pipeline must record rate-limit errors so they are queryable in `.adk/traces.db` via the `child_error_counts` column and the `session_report.py` rate-limit query.

## Original Transcription

> ok so I need to uh change the dispatch thing so that when a child agent hits a rate limit it actually backs off properly instead of just failing immediately. Right now I think the retry logic in the worker callback isn't catching 429s from the genai client correctly because it's checking the wrong attribute on the exception. Also the error classification function in dispatch dot py needs to handle that case. Oh and make sure the observability stuff picks it up too so I can see it in the traces database.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn a `Retry-Agent` teammate to add retry-with-exponential-backoff to `_run_child()` in `rlm_adk/dispatch.py` (around line 428).**
   The `_run_child` inner function (inside `create_dispatch_closures`) currently wraps the child orchestrator `run_async` call in a single `try/except` block (lines 428-516). When a `google.genai.errors.ClientError` with `code=429` is raised, the child fails immediately and the error is classified and returned as an `LLMResult(error=True)`. Add an exponential-backoff retry loop around the child orchestrator execution. Reuse the existing `is_transient_error()` function from `rlm_adk/orchestrator.py` (line 76) to determine retryability. Respect configurable max retries (env var `RLM_CHILD_MAX_RETRIES`, default 2) and base delay (env var `RLM_CHILD_RETRY_DELAY`, default 2.0 seconds). Use jittered exponential backoff (`delay * (2 ** attempt) + random jitter`). Only retry on transient errors -- all other exceptions must still fail immediately. On final retry exhaustion, fall through to the existing error classification and `LLMResult` construction. Add a new local accumulator `_acc_child_retry_counts: dict[str, int]` to track retry attempts per error category (e.g., `{"RATE_LIMIT": 3, "SERVER": 1}`), and flush it through `flush_fn` as a new state key `OBS_CHILD_RETRY_COUNTS` (define in `rlm_adk/state.py`). **AR-CRIT-001 compliance**: use the local accumulator pattern -- never write `ctx.session.state` directly in the dispatch closure.

2. **Spawn a `Classify-Guard` teammate to remove the `hasattr` gate in the `_run_child()` exception handler at line 504-505 of `rlm_adk/dispatch.py`.**
   Currently the exception handler reads:
   ```python
   cat = "SCHEMA_VALIDATION_EXHAUSTED" if output_schema is not None else (
       _classify_error(e) if (hasattr(e, "code") or hasattr(e, "status_code")) else "UNKNOWN"
   )
   ```
   The `hasattr` guard causes exceptions that lack both `.code` and `.status_code` to be classified as `"UNKNOWN"` without ever calling `_classify_error()`. But `_classify_error()` already has its own fallback logic for exceptions without HTTP codes (e.g., `asyncio.TimeoutError` returns `"TIMEOUT"`, `ConnectionError` returns `"NETWORK"`, `JSONDecodeError` returns `"PARSE_ERROR"`). The guard suppresses these type-based classifications. Change the line to always call `_classify_error(e)` for the non-schema path:
   ```python
   cat = "SCHEMA_VALIDATION_EXHAUSTED" if output_schema is not None else _classify_error(e)
   ```
   This ensures `asyncio.TimeoutError`, `ConnectionError`, and other non-HTTP exceptions get properly classified instead of falling to `"UNKNOWN"`. The `_classify_error()` function (line 58) already returns `"UNKNOWN"` as its own fallback, so removing the guard does not change the final behavior for truly unrecognizable exceptions.

3. **Spawn an `Obs-Trace` teammate to verify the observability pipeline end-to-end for rate-limit errors.**
   Confirm that the existing plumbing correctly propagates `RATE_LIMIT` error counts from the dispatch accumulator through to `traces.db`. The data flow is:
   - `_run_child()` classifies error as `"RATE_LIMIT"` and increments `_acc_child_error_counts["RATE_LIMIT"]` (line 751)
   - `flush_fn()` writes `_acc_child_error_counts` to `OBS_CHILD_ERROR_COUNTS` state key (line 792-793)
   - `REPLTool.run_async_impl()` calls `flush_fn()` and writes delta to `tool_context.state`
   - `ObservabilityPlugin.after_run_callback()` reads `OBS_CHILD_ERROR_COUNTS` from state (line 344) and includes it in the summary log
   - `SqliteTracingPlugin.after_run_callback()` writes `child_error_counts` JSON to `traces.child_error_counts` column (line 728, 758)
   - `session_report.py` `_build_perf()` queries `telemetry` for rows matching `429` or `RESOURCE` (line 264-271)

   Additionally, wire the new `OBS_CHILD_RETRY_COUNTS` key from step 1 into:
   - `ObservabilityPlugin.after_run_callback()` log output in `rlm_adk/plugins/observability.py`
   - `SqliteTracingPlugin` traces table (add a `child_retry_counts TEXT` column via the migration pattern already used for schema evolution)
   - `session_report.py` `_build_perf()` to expose retry counts in the report

4. **Spawn a `Batch-Retry` teammate to add retry logic to `_run_batch_child()` in `rlm_adk/dispatch.py`.**
   The batched dispatch path (`llm_query_batched_async`, starting around line 700) calls `_run_child` for each prompt via `asyncio.gather`. If one child in a batch hits a 429, the retry loop from step 1 handles it at the per-child level. Verify this works correctly for partial-batch failures (some children succeed, some retry). Ensure the `_child_semaphore` (line 197) is released and re-acquired correctly across retries so that a retrying child does not hold the semaphore during its backoff sleep. *[Added -- the transcription did not mention batched dispatch, but retry logic must work correctly in the batch path to avoid deadlocking the semaphore.]*

5. **Spawn a `Test-Contract` teammate to add/update provider-fake fixtures and contract tests for the retry behavior.**
   The existing fixture `worker_429_mid_batch.json` tests a scenario where a child hits repeated 429s and the parent REPL handles the failure summary. This fixture should be preserved as-is (it tests the no-retry failure path). Create a new fixture `child_429_retry_success.json` that tests the new retry-with-backoff path: the child hits one 429, retries with backoff, and succeeds on the second attempt. Also create `child_429_retry_exhausted.json` where the child exhausts all retries and fails. Both fixtures must validate:
   - The `OBS_CHILD_ERROR_COUNTS` state key contains `{"RATE_LIMIT": N}` with correct counts
   - The new `OBS_CHILD_RETRY_COUNTS` state key reflects retry attempts
   - The final `LLMResult.error_category` is `"RATE_LIMIT"` for exhausted retries
   - Wall time reflects actual backoff delays (not zero)

## Provider-Fake Fixture & TDD

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/child_429_retry_success.json`

**Essential requirements the fixture must capture:**
- The fixture must serve a 429 response on the first child dispatch attempt, then a 200 success on the retry -- proving the retry loop actually re-executes the child orchestrator (not just returning a cached result)
- The fixture must verify that `OBS_CHILD_RETRY_COUNTS` contains `{"RATE_LIMIT": 1}` -- proving the retry counter increments correctly and is visible in state
- The fixture must verify that wall time for the retried child exceeds the base backoff delay (e.g., >2s) -- proving the backoff sleep actually executed and was not short-circuited
- The fixture must verify that non-retried children in the same batch are not delayed by the retrying child -- proving the semaphore is released during backoff

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/child_429_retry_exhausted.json`

**Essential requirements:**
- All retry attempts return 429 -- proving the retry loop terminates after `RLM_CHILD_MAX_RETRIES` attempts
- `LLMResult.error_category` is `"RATE_LIMIT"` -- not `"UNKNOWN"` or `"SCHEMA_VALIDATION_EXHAUSTED"`
- `OBS_CHILD_ERROR_COUNTS["RATE_LIMIT"]` matches the expected count (initial attempt + retries)
- The `child_error_counts` column in `traces.db` is populated with the correct JSON

**TDD sequence:**
1. Red: Write test asserting `_classify_error(ClientError(429, {...}))` returns `"RATE_LIMIT"`. Run, confirm pass (this already works -- validates the baseline).
2. Red: Write test asserting that `_run_child()` retries on 429 and returns success on second attempt. Run, confirm failure (no retry loop exists yet).
3. Green: Implement the retry loop in `_run_child()`. Run, confirm pass.
4. Red: Write test asserting that `_run_child()` fails after max retries exhausted. Run, confirm failure (need exhaustion logic).
5. Green: Add exhaustion logic. Run, confirm pass.
6. Red: Write test asserting `OBS_CHILD_RETRY_COUNTS` appears in `flush_fn()` output. Run, confirm failure.
7. Green: Add accumulator and flush logic. Run, confirm pass.
8. Red: Write contract test using `child_429_retry_success.json` fixture. Run, confirm failure (fixture not yet created).
9. Green: Create fixture, wire into index.json. Run, confirm pass.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the retry, backoff timing, and observability pipeline work end-to-end.

## Considerations

- **AR-CRIT-001 compliance**: All new state writes must go through the local accumulator + `flush_fn` pattern. The retry count accumulator must not write to `ctx.session.state` directly.
- **Semaphore handling during backoff**: The `_child_semaphore` (asyncio.Semaphore) in dispatch.py limits concurrent child dispatches. During a backoff sleep, the semaphore must be released so other children can proceed. Re-acquire before retrying. Failure to do this will deadlock batched dispatches when one child is backing off.
- **`HttpRetryOptions` vs. dispatch-level retry**: The genai SDK already has `HttpRetryOptions` (configured in `rlm_adk/agent.py` line 109 with `attempts=3`). This handles HTTP-level retries transparently for the genai client. The dispatch-level retry proposed here is a higher-level retry that re-runs the entire child orchestrator (not just the HTTP call). Both layers are needed: SDK retries handle transient HTTP failures before they become exceptions; dispatch retries handle exceptions that escape the SDK retry layer.
- **Worker callback path**: The `WorkerRetryPlugin` in `rlm_adk/callbacks/worker_retry.py` handles structured output validation retries (set_model_response), not HTTP error retries. It is unrelated to the 429 retry problem. The transcription mentioned "worker callback" but the actual fix is in the dispatch closure, not the callback.
- **Existing FMEA coverage**: The `worker_429_mid_batch.json` fixture (referenced in `index.json` with FMEA class `TestWorker429MidBatch`) tests the current no-retry behavior. After adding retry logic, this fixture's behavior may change. Verify whether the fixture's `fault_injections` serve enough 429s to exhaust the new retry loop, or update the fixture to reflect the new expected behavior.
- **Pydantic model constraints**: Any new attributes on worker agents must use `object.__setattr__` (not normal setattr) because `LlmAgent` is a Pydantic model.
- **ADK event tracking**: Do not use `temp:` prefix on any new state keys -- ADK Runner strips `temp:` keys from yielded events.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/dispatch.py` | `_classify_error()` | L58 | Error classification function -- already handles 429 correctly |
| `rlm_adk/dispatch.py` | `_classify_error` guard in except clause | L504-505 | `hasattr` gate that suppresses classification for non-HTTP exceptions |
| `rlm_adk/dispatch.py` | `_run_child()` try/except block | L428-516 | Main exception handler where retry loop must be added |
| `rlm_adk/dispatch.py` | `_acc_child_error_counts` accumulator | L203 | Existing error count accumulator -- model for new retry accumulator |
| `rlm_adk/dispatch.py` | `flush_fn()` | L783 | Flush function that writes accumulators to state delta |
| `rlm_adk/dispatch.py` | `_child_semaphore` | L197 | Concurrency limiter -- must be released during backoff |
| `rlm_adk/orchestrator.py` | `is_transient_error()` | L76 | Transient error classifier -- reuse for retry decision |
| `rlm_adk/orchestrator.py` | `_TRANSIENT_STATUS_CODES` | L72 | `{408, 429, 500, 502, 503, 504}` |
| `rlm_adk/state.py` | `OBS_CHILD_ERROR_COUNTS` | L99 | Existing state key for child error counts |
| `rlm_adk/plugins/observability.py` | `after_run_callback` child_errors read | L344 | Reads `OBS_CHILD_ERROR_COUNTS` for summary log |
| `rlm_adk/plugins/sqlite_tracing.py` | `child_error_counts` column | L223, L728, L758 | Traces DB column where error counts are persisted |
| `rlm_adk/eval/session_report.py` | rate_limit query | L264-271 | Queries telemetry for 429/RESOURCE errors |
| `rlm_adk/agent.py` | `_DEFAULT_RETRY_OPTIONS` | L109 | SDK-level `HttpRetryOptions(attempts=3)` -- separate from dispatch retry |
| `rlm_adk/callbacks/worker_retry.py` | `WorkerRetryPlugin` | L79 | Structured output retry -- unrelated to HTTP 429 retry |
| `.venv/.../google/genai/errors.py` | `APIError` / `ClientError` | L29-234 | `code: int` attribute on genai exceptions |
| `tests_rlm_adk/fixtures/provider_fake/worker_429_mid_batch.json` | existing fixture | -- | Current FMEA fixture for 429 in batch -- may need update |
| `tests_rlm_adk/fixtures/provider_fake/fault_429_then_success.json` | existing fixture | -- | SDK-level 429 retry fixture (HttpRetryOptions) |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` -- compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` -- documentation entrypoint (follow Dispatch & State and Observability branches)
3. `rlm_adk_docs/dispatch_and_state.md` -- accumulator pattern, flush_fn mechanics, AR-CRIT-001 rules
4. `rlm_adk_docs/observability.md` -- worker obs path, plugin architecture, SqliteTracingPlugin
5. `rlm_adk_docs/testing.md` -- provider-fake fixture schema, contract runner, how to add fixtures
