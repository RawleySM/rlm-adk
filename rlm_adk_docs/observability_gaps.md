# Observability Gaps: Identified but Never Closed

Audit of all items identified by Phase 1-2 big-picture agents (docs 01-05) that were
neither fixed nor explicitly dismissed in `06_gap_fixes.md`. Deduplicated across documents
where the same underlying gap was described from multiple angles.

**Source documents:**
- `01_debugging_requirements.md` — Debugging gaps
- `02_performance_requirements.md` — Performance gaps
- `03_documentation_requirements.md` — Documentation / multi-session gaps
- `04_code_review_requirements.md` — Code review / REPL outcome gaps
- `issues/fixed/REPL_gaps.md` — Independent reviewer findings

---

## Cluster A: Code / Prompt / Response Persistence (THE critical gap)

These all describe the same fundamental problem: the actual content flowing through
the dispatch system is transient and never persisted.

| # | ID(s) | Gap | Source |
|---|-------|-----|--------|
| 1 | DEBUG-3.4, DEBUG-6.1, CODE-4, REPL-2 | **Child dispatch prompt text** — prompt string sent via `llm_query()` / `llm_query_batched()` is transient, cleared in finally block | doc 01 §3.4/6.1, doc 04 §4, REPL_gaps #2 |
| 2 | DEBUG-6.2, CODE-5, REPL-3 | **Child dispatch response text** — `LLMResult` content consumed by closure, `_result` cleared in finally | doc 01 §6.2, doc 04 §5, REPL_gaps #3 |
| 3 | DEBUG-8.1, DEBUG-8.2, CODE-6 | **Pre-rewrite and post-rewrite source code** — original model-generated Python and AST-rewritten async version not persisted | doc 01 §8.1/8.2, doc 04 §6 |
| 4 | CODE-1 | **Generated code string per execute_code** — `telemetry.tool_args_keys` stores only key names `["code"]`, not the actual code value. Dismissed as "privacy/size concern" in 06_gap_fixes.md | doc 04 §1 |

> **Note:** Item 4 was the only one in this cluster given an explicit "by design" dismissal.
> Items 1-3 were silently skipped — never dismissed, never fixed.

---

## Cluster B: Cross-Depth Trace Linkage

| # | ID(s) | Gap | Source |
|---|-------|-----|--------|
| 5 | DEBUG-1.2, DOC-4.1 | **Parent-child trace linkage** — no `parent_trace_id` column, no `dispatch_tree` table. Child runs at depth N cannot be linked back to their parent at depth N-1 | doc 01 §1.2, doc 03 §4.1 |

---

## Cluster C: Per-Child Granularity (beyond aggregates)

| # | ID(s) | Gap | Source |
|---|-------|-----|--------|
| 6 | DEBUG-3.2 | **Per-child error detail in batches** — `OBS_CHILD_ERROR_COUNTS` is flat aggregate (`{"RATE_LIMIT": 2}`), no per-position failure map | doc 01 §3.2 |
| 7 | REPL-1 | **`REPLResult.llm_calls` always empty** — dispatch closures have no reference to REPL object, list never appended to | REPL_gaps #1 |
| 8 | REPL-4 | **Token counts written but never read** — `WORKER_INPUT_TOKENS` etc. appear in zero `state_delta` writes | REPL_gaps #4 |

---

## Cluster D: SDK-Opaque Retry Behavior

| # | ID(s) | Gap | Source |
|---|-------|-----|--------|
| 9 | DEBUG-5.1 | **HTTP retry count inside genai SDK** — `HttpRetryOptions(attempts=3)` retries handled entirely inside SDK, no callback surfaces retry count or backoff delays | doc 01 §5.1 |
| 10 | PERF-2d | **Rate-limit backoff duration** — total time spent in 429 retry loops invisible | doc 02 §PERF-2d |
| 11 | PERF-5b/c | **Rate limit temporal pattern** — successful retries after initial 429 completely invisible, no timestamps for 429 events | doc 02 §PERF-5b/c |

---

## Cluster E: Concurrency / Semaphore Instrumentation

| # | ID(s) | Gap | Source |
|---|-------|-----|--------|
| 12 | PERF-2e | **Semaphore wait time** — `async with _child_semaphore` not instrumented | doc 02 §PERF-2e |
| 13 | PERF-3a | **Effective parallelism** — no semaphore acquire/release instrumentation, can't measure actual concurrency vs configured limit | doc 02 §PERF-3a |

---

## Cluster F: Child Orchestrator Lifecycle Timing

| # | ID(s) | Gap | Source |
|---|-------|-----|--------|
| 14 | PERF-8a | **Child orchestrator creation overhead** — `create_child_orchestrator()` time not separated from execution time | doc 02 §PERF-8a |
| 15 | PERF-8c | **Child cleanup overhead** — finally block time not instrumented, delays semaphore release | doc 02 §PERF-8c |

---

## Cluster G: REPL Execution Quality Signals

| # | ID(s) | Gap | Source |
|---|-------|-----|--------|
| 16 | CODE-3 | **Variable state evolution** — no namespace diff (added/modified/removed) between consecutive `execute_code` calls | doc 04 §3 |
| 17 | CODE-7 | **Code retry patterns** — no tracking of consecutive errored-then-corrected `execute_code` calls | doc 04 §7 |
| 18 | CODE-8 | **REPL error classification** — no classification by exception type (NameError, TypeError, SyntaxError etc), only worker-level `_classify_error()` exists | doc 04 §8 |
| 19 | REPL-5 | **`format_execution_result()` drops variable values** — only variable names listed, not their values | REPL_gaps #5 |
| 20 | REPL-6 | **`REPLResult.execution_time` populated but never read** — orchestrator and formatting functions ignore it | REPL_gaps #6 |
| 21 | PERF-9c | **Error-recovery turns** — reasoning turns spent recovering from REPL errors not counted | doc 02 §PERF-9c |

---

## Cluster H: AST Rewrite Gaps (beyond timing)

| # | ID(s) | Gap | Source |
|---|-------|-----|--------|
| 22 | DEBUG-8.4 | **Rewrite failure count** — no counter distinguishing failed AST rewrites from successful ones | doc 01 §8.4 |

> **Note:** Rewrite *timing* (OBS_REWRITE_COUNT, OBS_REWRITE_TOTAL_MS) was closed.
> Rewrite *failure classification* and *source persistence* were not.

---

## Cluster I: Documentation / Multi-Session Infrastructure

| # | ID(s) | Gap | Source |
|---|-------|-----|--------|
| 23 | DOC-1.1d | **Run ordinal within session** — no monotonic counter distinguishing retry vs fresh run | doc 03 §1.1 |
| 24 | DOC-1.2i | **Total batch dispatches not in traces enrichment** — obs key exists but not written to traces table | doc 03 §1.2 |
| 25 | DOC-1.3d | **Policy violation key not captured in traces** — `POLICY_VIOLATION` defined in state.py but never written to traces | doc 03 §1.3 |
| 26 | DOC-2.3 | **No normalized iteration table** — `per_iteration_breakdown` is opaque JSON blob, not SQL-queryable | doc 03 §2.3 |
| 27 | DOC-5.2 | **No cost estimation metadata** — no `model_pricing` reference table for dollar cost | doc 03 §5.2 |
| 28 | DOC-6.1b | **System instruction not stored** — assembled at runtime, not persisted or hashed | doc 03 §6.1 |
| 29 | DOC-7.1 | **No artifact content hashing** — no `artifact_versions` table with `content_hash` | doc 03 §7.2 |
| 30 | DOC-3.2 | **No baseline infrastructure** — no mechanism for baseline run sets, regression comparison, or alerts | doc 03 §3.2 |

---

## Cluster J: Miscellaneous

| # | ID(s) | Gap | Source |
|---|-------|-----|--------|
| 31 | DEBUG-4.3 | **Parallel dispatch race condition visibility** — object-carrier fields transient, intra-batch race conditions invisible to persistence layer | doc 01 §4.3 |
| 32 | DEBUG-7.3 | **Exception vs error-value distinction** — dispatch raises exceptions for depth-limit but returns `LLMResult(error=True)` for API errors, dual behavior undocumented in telemetry | doc 01 §7.3 |
| 33 | PERF-10b/c/d | **Time breakdown / critical path / time-to-first-output** — no single wall-clock decomposition into reasoning / REPL / dispatch / rate-limit / overhead | doc 02 §PERF-10 |

---

## Summary

| Cluster | Count | Severity | Feasibility |
|---------|-------|----------|-------------|
| A: Code/Prompt/Response Persistence | 4 | CRITICAL | Straightforward — persist `args["code"]`, child prompt/response to telemetry columns |
| B: Cross-Depth Trace Linkage | 1 | HIGH | Medium — requires `parent_trace_id` plumbing through `InvocationContext` |
| C: Per-Child Granularity | 3 | HIGH | Medium — requires dispatch closure refactoring |
| D: SDK-Opaque Retry | 3 | MEDIUM | Hard — requires SDK instrumentation hooks or monkey-patching |
| E: Concurrency Instrumentation | 2 | MEDIUM | Easy — wrap semaphore acquire with timer |
| F: Child Lifecycle Timing | 2 | MEDIUM | Easy — add `time.perf_counter()` around create/cleanup |
| G: REPL Quality Signals | 6 | MEDIUM | Mixed — error classification easy, namespace diff harder |
| H: AST Rewrite Gaps | 1 | LOW | Easy — add failure counter to existing rewrite path |
| I: Multi-Session Infrastructure | 8 | LOW-MEDIUM | Hard — new tables, new tooling, design decisions |
| J: Miscellaneous | 3 | LOW | Mixed |
| **Total** | **33** | | |
