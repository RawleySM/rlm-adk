# Provider-Fake + FMEA Coverage And Trace/Span Substantiation Assessment

Date: 2026-03-03
Scope: `tests_rlm_adk/provider_fake`, `tests_rlm_adk/fixtures/provider_fake/index.json`, `tests_rlm_adk/test_provider_fake_e2e.py`, `tests_rlm_adk/test_fmea_e2e.py`, `rlm_adk_docs/FMEA/rlm_adk_FMEA.md`, runtime trace/span plugins.

## 1. Why This Document Exists
This documents how fixture-driven pass/fail is actually computed, how that ties to FMEA failure modes, and whether trace/span evidence is strong enough to claim those failure modes are addressed.

## 2. Repomix-Explorer Scan Snapshot
Repomix was run on the fixture, REPL, dispatch, tracing, and FMEA slice.

- Files packed: 73
- Total tokens: 112,986
- Largest files by tokens:
  - `tests_rlm_adk/fixtures/provider_fake/index.json`
  - `rlm_adk_docs/FMEA/rlm_adk_FMEA.md`
  - `tests_rlm_adk/fixtures/provider_fake/multi_turn_repl_session.json`

This confirms the two documents the request asked to reconcile (`index.json` and `rlm_adk_FMEA.md`) are the dominant sources in this slice.

## 3. Exact Pass/Fail Mechanics In Python

### 3.1 Fixture replay engine
- `ScenarioRouter` requires `scenario_id` and uses FIFO replay over `responses` with optional call-index fault overlay: `tests_rlm_adk/provider_fake/fixtures.py:87-201`.
- Every call increments `_call_index`, and request metadata is logged (`call_index`, model, systemInstruction presence): `tests_rlm_adk/provider_fake/fixtures.py:136-150`.
- Faults are injected before normal response consumption (`malformed_json`, HTTP status/body): `tests_rlm_adk/provider_fake/fixtures.py:152-170`.
- If responses are exhausted, router returns a fallback `FINAL(fixture-exhausted)` payload (important for false-positive risk if fixture call plan is wrong): `tests_rlm_adk/provider_fake/fixtures.py:171-191`.

### 3.2 Fake provider server
- Binds local HTTP endpoint `/v1beta/models/{model}:generateContent`: `tests_rlm_adk/provider_fake/server.py:33-36`.
- Validates API key header and JSON body, then delegates to router: `tests_rlm_adk/provider_fake/server.py:78-117`.

### 3.3 Contract runner
- `run_fixture_contract()` lifecycle: load fixture -> start fake server -> set env -> run real app/runner -> compare expectations -> teardown: `tests_rlm_adk/provider_fake/contract_runner.py:135-168`.
- `run_fixture_contract_with_plugins()` adds `ObservabilityPlugin`, optional `SqliteTracingPlugin`, optional `REPLTracingPlugin`: `tests_rlm_adk/provider_fake/contract_runner.py:171-274`.

### 3.4 The contract itself (what determines PASS/FAIL)
`ScenarioRouter.check_expectations()` only evaluates keys present in fixture `expected`:
- `final_answer`
- `total_iterations`
- `total_model_calls` (`router._call_index`)

Implementation: `tests_rlm_adk/provider_fake/fixtures.py:203-260`.

Important implication:
- No direct contract check for `OBS_*` keys, `LAST_REPL_RESULT` shape, span correctness, error category correctness, or per-worker result semantics.
- A fixture can pass contract while observability/tracing is weak or misleading.

### 3.5 Test suites layered on top of contract

#### Baseline provider-fake e2e
- Parametrized contract test over `FIXTURE_DIR.glob("*.json")`: `tests_rlm_adk/test_provider_fake_e2e.py:39-56`.
- Plugin/trace assertions are broad (for example, `model_spans > 0`, `total_calls >= 3`): `tests_rlm_adk/test_provider_fake_e2e.py:159-217`.

#### FMEA-focused e2e
- Dedicated FM classes with behavior assertions (stdout/stderr text, iteration counts, state keys, dispatch counts): `tests_rlm_adk/test_fmea_e2e.py`.
- Example FM-08 note already acknowledges classification degradation: fake 429 path often ends up `UNKNOWN` instead of `RATE_LIMIT`: `tests_rlm_adk/test_fmea_e2e.py:133-148`.

#### Structured-output-specific e2e
- Contract + scenario checks for retry and validation paths: `tests_rlm_adk/test_structured_output_e2e.py`.

## 4. Runtime Verification Executed (2026-03-03)

Commands executed:
- `.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py -q`
- `.venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -q`
- `.venv/bin/python -m pytest tests_rlm_adk/test_structured_output_e2e.py -q`
- `.venv/bin/python -m pytest tests_rlm_adk/test_skill_helper_e2e.py -q`
- `.venv/bin/python -m tests_rlm_adk.trace_demo_runner`
- Additional direct fixture+trace DB inspection scripts via `run_fixture_contract_with_plugins()`.

Observed outcomes:
- `test_fmea_e2e.py`: 170 passed.
- `test_structured_output_e2e.py`: 12 passed.
- `test_skill_helper_e2e.py`: 5 passed.
- `test_provider_fake_e2e.py`: 53 passed, 1 failed.

The one failure is structural:
- `test_fixture_contract[index]` fails because `index.json` is included by `glob("*.json")` but is not a scenario fixture (`scenario_id` missing), causing `KeyError`: `tests_rlm_adk/provider_fake/fixtures.py:88`.

## 5. FMEA vs Index Reconciliation (Current Reality)

### 5.1 `rlm_adk_FMEA.md` is stale relative to fixture reality
`rlm_adk_FMEA.md` still reports many modes as `Gap` and even recommends creating fixtures that already exist:
- Example matrix still shows FM-08/FM-14/FM-17/FM-25 as `Gap`: `rlm_adk_docs/FMEA/rlm_adk_FMEA.md:428-455`.
- Recommended fixtures include `worker_429_mid_batch.json`, `repl_error_then_retry.json`, etc., now present in fixtures: `rlm_adk_docs/FMEA/rlm_adk_FMEA.md:485-489`.

### 5.2 `index.json` is also internally inconsistent (partially indexed)

Documented inconsistencies found:
- `summary` says covered=16/partial=4/gap=8, but deriving directly from `failure_modes` entries yields covered=13/partial=4/gap=11.
- FM-24 and FM-28 are marked `gap` in `failure_modes`, but fixture map links them to concrete fixtures/tests:
  - FM-24 linked from `empty_reasoning_output_safety.json`, `reasoning_safety_finish.json`.
  - FM-28 linked from `worker_auth_error_401.json`.
- 14 fixture->FM links exist in `fixtures` section but are missing from corresponding `failure_modes[*].fixtures` list (examples include `repl_exception_then_retry.json`, `worker_max_tokens_naive.json`, `structured_output_batched_k3_multi_retry.json`).

Key references:
- FM-28 marked gap: `tests_rlm_adk/fixtures/provider_fake/index.json:867-875`.
- FM-28 mapped fixture exists: `tests_rlm_adk/fixtures/provider_fake/index.json:1202-1208`.
- FM-24 marked gap: `tests_rlm_adk/fixtures/provider_fake/index.json` (FM block), yet mapped fixtures at `1174-1187`.
- Summary block: `tests_rlm_adk/fixtures/provider_fake/index.json:1211-1258`.

## 6. Trace/Span Evidence Quality: Honest Assessment

## 6.1 What is solid
- Behavioral mitigations are strongly exercised by tests for many high-risk modes (FM-08, FM-14, FM-17, FM-25) through final answer, stderr/stdout, state counters, and retry outcomes.
- `WORKER_DISPATCH_COUNT` and `OBS_WORKER_ERROR_COUNTS` are flushed from dispatch closures and asserted repeatedly: `rlm_adk/dispatch.py:625-659`, `tests_rlm_adk/test_fmea_e2e.py` (many assertions).
- `LAST_REPL_RESULT` persistence on exception/cancellation is explicitly tested and aligns with code paths in `REPLTool.run_async`: `rlm_adk/tools/repl_tool.py:120-166`.

## 6.2 Where trace/span evidence is not sufficient

### A) Model span pairing is not concurrency-safe
`SqliteTracingPlugin` tracks pending model spans by model name (`dict[str, str]`), so concurrent workers using same model overwrite each other:
- data structure: `rlm_adk/plugins/sqlite_tracing.py:103-106`
- write on before_model: `rlm_adk/plugins/sqlite_tracing.py:306`
- pop on after_model: `rlm_adk/plugins/sqlite_tracing.py:317-323`

Observed consequence in `worker_429_mid_batch` runtime sample:
- router calls: 6
- model spans: 7
- all model spans status `ok`

This means span counts and per-span attributes are not a reliable one-to-one evidence source for parallel worker FMs.

### B) Worker error spans can look `ok`
`SqliteTracingPlugin.after_model_callback` marks error only when `llm_response.error_code` exists: `rlm_adk/plugins/sqlite_tracing.py:335-355`.
But `worker_on_model_error` returns a synthetic `LlmResponse` with plain text and no `error_code`: `rlm_adk/callbacks/worker.py:191-195`.

Observed consequence:
- FM-08 (429 mid-batch) had `obs_worker_error_counts={'UNKNOWN': 1}` in state, but model span statuses were all `ok`.

### C) Trace `total_calls` is derived from state counters, not raw router call count
`traces.total_calls` comes from `OBS_TOTAL_CALLS` in session state: `rlm_adk/plugins/sqlite_tracing.py:241-244`.
For worker-heavy error paths this can undercount vs actual HTTP calls (`router.call_index`).

Observed examples:
- `worker_429_mid_batch`: router=6, traces.total_calls=5
- `worker_500_retry_exhausted`: router=4, traces.total_calls=3

### D) Error categorization for 429/401 frequently degrades to `UNKNOWN`
Error classification requires integer `error.code`: `rlm_adk/callbacks/worker.py:30-40`.
Fake-provider SDK exceptions do not always expose that field as expected, so FM tests intentionally assert non-empty counts rather than exact category (for example FM-08 note): `tests_rlm_adk/test_fmea_e2e.py:133-148`.

### E) REPL trace artifact only stores summary, not full causal detail
`REPLTracingPlugin` stores only `trace_summary` from `LAST_REPL_RESULT`, not full `llm_calls`/exceptions: `rlm_adk/plugins/repl_tracing.py:39-45`.
That is useful telemetry but weak forensic evidence for proving specific FM mitigations end-to-end.

### F) Demo runner expects stale trace_summary field names
`trace_demo_runner.py` expects keys `total_llm_calls_traced` and `total_wall_time_ms`: `tests_rlm_adk/trace_demo_runner.py:93-96`.
Actual `REPLTrace.summary()` provides `llm_call_count` and `wall_time_ms`: `rlm_adk/repl/trace.py:101-109`.
Observed output showed `None/False` for those stale key lookups.

## 7. FM-by-FM Judgment (Addressed vs Evidence Strength)

Legend:
- Addressing status: `Addressed`, `Partially Addressed`, `Not Addressed`.
- Evidence quality: `Strong` (behavior + instrumentation aligned), `Medium` (behavior strong, trace/span weak), `Weak` (limited direct evidence).

| FM | Index status | Current assessment | Evidence quality | Notes |
|---|---|---|---|---|
| FM-01 | partial | Partially Addressed | Medium | Only single-retry recovery fixture; no true exhaustion scenario. |
| FM-02 | gap | Not Addressed | Weak | No fixture/test path for non-transient reasoning failure. |
| FM-03 | covered | Addressed | Strong | Max-call limit + persistent-ignoring variant tested. |
| FM-04 | covered | Addressed | Strong | Syntax error + correction tested. |
| FM-05 | covered | Addressed | Strong | Runtime error + partial-state variant tested. |
| FM-06 | gap | Not Addressed | Weak | No alias-blindness fixture. |
| FM-07 | gap | Not Addressed | Weak | No list-comprehension async rewrite fixture. |
| FM-08 | covered | Partially Addressed | Medium | Behavior covered; spans do not reliably prove 429 path due `UNKNOWN` and `ok` span statuses. |
| FM-09 | covered | Partially Addressed | Medium | Behavior covered; span/error accounting undercounts in some paths. |
| FM-10 | gap | Not Addressed | Weak | No timeout fixture proving dispatch timeout behavior. |
| FM-11 | gap | Partially Addressed | Weak | Unit-level pool exhaustion tests exist; no fixture e2e mapping. |
| FM-12 | partial | Partially Addressed | Medium | Multi-worker reuse exercised but index linkage incomplete. |
| FM-13 | partial | Partially Addressed | Medium | Injection tests verify handler behavior; still marked partial in index. |
| FM-14 | covered | Addressed | Strong | Exception+retry and flush behavior extensively tested. |
| FM-15 | covered | Addressed | Medium | Behavior is tested; observability for finish-reason nuance remains limited. |
| FM-16 | covered | Addressed | Medium | Multiple variants exist, but index missing several links. |
| FM-17 | covered | Addressed | Medium | Batched structured output paths tested, span pairing still weak under concurrency. |
| FM-18 | covered | Addressed | Medium | Malformed JSON path tested behaviorally. |
| FM-19 | covered | Addressed | Medium | All-workers-fail behavior tested. |
| FM-20 | gap | Not Addressed | Weak | No direct e2e fixture for callback exception blast-radius path. |
| FM-21 | partial | Partially Addressed | Weak | Patch presence/invocation tested; import-failure resilience not fully validated as failure injection. |
| FM-22 | gap | Not Addressed | Weak | No recursion serialization fixture. |
| FM-23 | covered | Addressed | Strong | Cross-iteration/partial-state handling tested in multiple fixtures. |
| FM-24 | gap (inconsistent) | Partially Addressed | Medium | Fixtures/tests exist but index/failure_modes block not updated; trace counters for SAFETY reasoning still weak. |
| FM-25 | covered | Addressed | Medium | Rich fixture set including naive variants; span semantics still imperfect. |
| FM-26 | gap | Not Addressed | Weak | No infinite-loop under lock fixture. |
| FM-27 | gap | Partially Addressed | Medium | Provider-fake gap, but separate concurrency safety tests and async CWD design mitigation exist. |
| FM-28 | gap (inconsistent) | Partially Addressed | Medium | Fixture/tests exist; index still marks gap and categorization often `UNKNOWN`. |

## 8. Direct Answers To The Request

### How pass/fail is established
1. Fixture replay pass/fail is strict equality on up to three expected fields (`final_answer`, `total_iterations`, `total_model_calls`) via `check_expectations()`.
2. FMEA confidence comes from additional test assertions in `test_fmea_e2e.py`, not from contract checks.
3. Trace/span checks in baseline e2e are mostly threshold/presence checks (`>0`, `>=3`), not strict causal validation.

### Do traces/spans substantiate that failure modes are addressed?
Short answer: only partially.

- For many modes, behavioral evidence is strong, so mitigations likely work.
- But trace/span telemetry is not strong enough to be the primary proof for high-concurrency worker failure modes.
- Current span implementation can overcount, undercount, and mask worker errors as `ok` depending on callback/error path.

### Which failure modes need more than current trace/span criteria?
High priority to strengthen evidence:
- FM-08, FM-09, FM-17, FM-24, FM-28.

Reason:
- They rely on parallel worker behavior and/or error classification where current span pairing and status semantics are weakest.

## 9. Concrete Next Actions (If You Want This Tightened)
1. Make model span pairing key unique per invocation/worker, not per model string (`sqlite_tracing.py`).
2. Persist explicit worker error status/category into span attributes from `_call_record` instead of relying on `llm_response.error_code` alone.
3. Add strict assertions that `router.call_index == traces.total_calls` (or document intentional difference and rename field).
4. Exclude `index.json` from fixture contract parametrization in `test_provider_fake_e2e.py`.
5. Reconcile `index.json` so `failure_modes`, `fixtures`, and `summary` are internally consistent.
6. Refresh `rlm_adk_FMEA.md` coverage matrix to current fixture/test reality.
