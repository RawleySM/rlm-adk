# Devil's Advocate Review: Auto-Retry Cron Agent for Failed Runs

**Proposal under review:** A cron job running every 30 minutes that reads the SQLite tracing DB (`traces.db`), identifies failed runs, classifies errors, generates fix hypotheses, and automatically re-dispatches with adjusted parameters.

**Reviewer method:** Examined the `SqliteTracingPlugin` schema, dispatch closures, error classification system, observability pipeline, orchestrator retry logic, `MigrationPlugin`, the data janitor prompt, and the autonomous self-improvement vision doc. Findings are grounded in what the codebase actually records vs. what the proposal assumes it can read.

---

## 1. The traces.db Does Not Record "Failed Runs"

This is the single biggest blind spot. The `traces` table `status` column has exactly two values: `'running'` (set at insert in `before_run_callback`, line 660) and `'completed'` (set in `after_run_callback`, line 716). There is no `'failed'` or `'error'` status.

What happens when a run actually crashes?

- If the process dies (OOM, SIGKILL, unhandled exception before `after_run_callback`), the trace row stays `status='running'` forever. It is an orphan, not a "failed run."
- If an error is caught within ADK's loop (transient HTTP errors, safety filters, schema validation exhaustion), the run still completes normally and the trace gets `status='completed'`. The error is buried inside `child_error_counts` (JSON), `structured_output_failures` (integer), or `finish_safety_count` / `finish_recitation_count` columns.
- There is no `error_message` or `error_type` column on the `traces` table. Those columns exist only on the `telemetry` table (per-model-call granularity).

**Consequence:** The cron agent has no clean `WHERE status = 'failed'` query to write. It would need a multi-table heuristic: orphaned `running` traces older than some timeout, plus `completed` traces where `child_error_counts IS NOT NULL` or `structured_output_failures > 0` or `finish_safety_count > 0`. That heuristic is fragile and version-coupled.

**Recommendation:** Before building the cron agent, add an explicit failure classification to `after_run_callback`. A `completion_quality` column (values: `success`, `partial`, `error`, `timeout`) computed from the existing observability counters would give the cron agent a reliable query target.

---

## 2. You Cannot Reconstruct the Original Prompt from traces.db

The proposal says the cron agent would "re-dispatch with adjusted parameters." Re-dispatch requires the original prompt. What `traces.db` actually stores:

- `root_prompt_preview`: truncated to 500 characters (line 750: `root_prompt[:500]`)
- `prompt_hash`: SHA-256 of the full prompt (useful for deduplication, not reconstruction)

The full prompt lives in `session.db` (in the events table as conversation history), not in `traces.db`. The cron agent would need to cross-reference `traces.session_id` against `session.db` to reconstruct the original input. But `MigrationPlugin` and the planned data janitor both prune old sessions by count (default 50). If the failed run's session has already been pruned, the original prompt is gone.

**Consequence:** The cron agent has a race condition against session pruning. After 50 subsequent runs, the failed run's session (and its full prompt) may no longer exist.

**Recommendation:** If auto-retry is the goal, persist the full `root_prompt` (not just the 500-char preview) in the `traces` table, or save a dedicated retry manifest artifact. Alternatively, change session retention policy to exempt sessions with unresolved failures.

---

## 3. Error Classification is Insufficient for "Generate a Fix Hypothesis"

The proposal envisions classifying error type and generating a fix. The existing error categories (from `_classify_error` in `dispatch.py`) are:

| Category | What you can do about it |
|----------|-------------------------|
| RATE_LIMIT (429) | Wait and retry (already handled by `HttpRetryOptions`) |
| SERVER (5xx) | Wait and retry (already handled) |
| TIMEOUT | Increase timeout or retry (already handled) |
| AUTH (401/403) | Fix credentials -- no LLM can do this |
| NETWORK | Fix network -- no LLM can do this |
| PARSE_ERROR | Retry with different prompt framing (maybe actionable) |
| SCHEMA_VALIDATION_EXHAUSTED | Retry with loosened schema or different prompt (maybe actionable) |
| UNKNOWN | Cannot classify, cannot fix |

Most retryable errors (429, 5xx, timeout) are already handled by the `HttpRetryOptions` with 3 attempts and exponential backoff (lines 109-114 in `agent.py`) plus the orchestrator's own `is_transient_error` retry logic. If a run still failed after those retries, retrying again 30 minutes later with "adjusted parameters" is unlikely to help unless the root cause was sustained provider outage.

The truly interesting failures -- bad REPL code, incorrect reasoning, wrong final answer -- are not classified as errors at all. They produce `status='completed'` with a `final_answer` that happens to be wrong. Detecting those requires evaluating the answer quality, which is a completely separate (and much harder) problem than reading error counters from traces.db.

**Consequence:** The cron agent's "classify error -> generate fix hypothesis -> resubmit" pipeline has a very narrow useful band. Provider errors are already retried. Logic errors are not detectable from traces.db. The middle ground (PARSE_ERROR, SCHEMA_VALIDATION_EXHAUSTED) could benefit from retry, but these represent a small fraction of failures.

**Recommendation:** Scope the first version to only the errors it can actually help with: orphaned `running` traces (process crash -- simple resubmit) and `SCHEMA_VALIDATION_EXHAUSTED` (resubmit with prompt adjustments). Do not pretend it can handle arbitrary failure types.

---

## 4. "Adjusted Parameters" -- What Parameters?

The proposal is vague about what "adjusted parameters" means. The RLM-ADK dispatch system has very few knobs:

- **Model:** Hardcoded from `RLM_ADK_MODEL` env var or `DispatchConfig.default_model`. Not per-run adjustable.
- **Max iterations:** `RLM_MAX_ITERATIONS` env var. Increasing this for a retry means the cron agent needs to set env vars before spawning, which is process-global.
- **Max depth:** `RLM_MAX_DEPTH` env var. Same issue.
- **Thinking budget:** Set at reasoning agent creation time (constructor param `thinking_budget`, default 1024). Not adjustable per-run.
- **HTTP timeout:** `RLM_REASONING_HTTP_TIMEOUT` env var. Process-global.
- **Prompt wording:** The only truly adjustable parameter.

The cron agent cannot "adjust parameters" without either: (a) setting env vars and spawning a new process (fragile, hard to track), or (b) programmatically calling `create_rlm_runner()` with modified arguments (requires understanding the full factory API).

**Recommendation:** Define the specific parameter adjustments the cron agent would make. If it is just "retry with the same parameters after a delay" (hoping a transient outage resolved), call it what it is: a retry queue, not an intelligent self-healing system. If it is "modify the prompt based on failure analysis," that is a research problem, not a cron job.

---

## 5. Concurrency and Locking with SqliteTracingPlugin

`SqliteTracingPlugin` holds a long-lived `self._conn` (line 368) for the entire plugin lifetime. The existing data janitor prompt (`prompts/add_adk_data_janitor_cron.md`) already documents this risk extensively and mandates `incremental_vacuum` instead of full `VACUUM` to avoid invalidating the open connection.

The cron agent proposal goes further: it would not just read from `traces.db` but also *write* to it (marking retried traces, updating status). If RLM-ADK is actively running while the cron fires:

- **Read contention:** WAL mode handles concurrent reads fine. No issue.
- **Write contention:** Both the running agent's `SqliteTracingPlugin` and the cron agent would write. WAL handles this, but `busy_timeout = 5000` (line 386) means one writer blocks the other for up to 5 seconds. The cron agent's DB operations (reading failed traces, classifying, writing retry markers) could take longer than 5 seconds if there are many traces.
- **Schema coupling:** The cron agent would hardcode knowledge of the `traces` schema, which `_migrate_schema()` evolves over time. The data janitor prompt (step 4, "Schema-Inspector" teammate) already addresses this with runtime introspection, but this proposal does not mention it.

**Recommendation:** The cron agent should open its own connection with `PRAGMA busy_timeout = 30000` (30s) and use read-only transactions for the analysis phase. Any writes (retry markers) should be batched into a single short transaction. Better yet, write retry state to a separate file (`retry_queue.json`) rather than modifying `traces.db`.

---

## 6. You Already Have Prior Art That Solves Part of This

### Existing retry infrastructure
The orchestrator (`orchestrator.py`) already has transient error retry logic with `is_transient_error()`, configurable retry count via `RLM_REASONING_MAX_RETRIES` env var, and exponential backoff. The `HttpRetryOptions` provide SDK-level retry for 429/5xx. The `WorkerRetryPlugin` retries schema validation failures with reflection. A cron-based retry is a third layer on top of two existing retry layers.

### The autonomous self-improvement vision doc
`rlm_adk_docs/vision/continous_runtime/autonomous_self_improvement.md` already defines this concept at a higher level. It envisions cron-triggered agents for gap auditing, doc staleness, test coverage, REPL pattern mining, dependency auditing, and performance baselines. The "auto-retry failed runs" use case is *not* listed there. The vision doc also specifies constraints: worktree isolation, PR creation (never direct push), tests before proposing changes, action logging. The proposal does not mention any of these safety constraints.

### The data janitor prompt
`prompts/add_adk_data_janitor_cron.md` is a thoroughly red-teamed prompt for a cron job that operates on the same `.adk/` data. It provides a detailed template for how to build cron infrastructure in this codebase: standalone script + ADK plugin + cron installer + schema introspection. The auto-retry proposal should follow the same architecture rather than inventing a new one.

**Recommendation:** Treat the auto-retry cron as an instance of the autonomous self-improvement framework, not as a standalone feature. Follow the data janitor's architectural pattern (standalone script + plugin + cron installer). Adopt the vision doc's safety constraints (worktree, PR creation, test-before-merge, action logging).

---

## 7. Runaway Retry Amplification

The proposal does not mention retry limits. If a run fails because of a systematic issue (bad API key, model deprecation, prompt that always triggers safety filters), the cron agent would:

1. See the failed trace at T+30 min
2. Resubmit
3. Fail again
4. See *two* failed traces at T+60 min
5. Resubmit both
6. Both fail, creating two more failed traces
7. Now four failed traces at T+90 min

This is exponential retry amplification. Every 30-minute cycle doubles the retry load.

**Recommendation:** Mandatory design requirements:
- **Max retry count per trace:** Store a `retry_count` and cap at 2-3 attempts.
- **Deduplication by `prompt_hash`:** If the same prompt has failed N times, stop retrying it.
- **Circuit breaker:** If the failure rate over the last hour exceeds a threshold (e.g., >50% of runs failed), pause all retries and alert.
- **Cost budget:** Each retry consumes API tokens. Cap the cron agent's spend per cycle.

---

## 8. The "Fix Hypothesis" Step Requires Its Own LLM Call

The proposal says the cron agent would "generate a fix hypothesis." This is itself an LLM inference call. It requires:

- A model (which model? the same one that failed?)
- API credentials (does the cron environment have them?)
- A prompt (who writes and maintains the meta-prompt for failure analysis?)
- Token budget (analyzing a failure trace could be expensive)

If the failure was caused by a provider outage, the fix-hypothesis LLM call will also fail. If the failure was caused by rate limiting, the fix-hypothesis call adds to the rate limit pressure.

**Recommendation:** The simplest useful version has no LLM in the loop. It is a deterministic retry queue: orphaned traces get resubmitted as-is after a cooldown, schema-validation failures get resubmitted with a slightly loosened prompt suffix, and everything else gets logged for human review. Adding LLM-based failure analysis is a separate, later feature.

---

## 9. Session Identity and State Continuity

When the cron agent "re-dispatches," does it create a new session or resume the old one? This matters because:

- **New session:** Loses all accumulated state (iteration count, dispatch metrics, cache hits). The retry starts from scratch, which is the safest option but means no learning from the failed attempt.
- **Resume old session:** The session contains stale state from the failed run (partial results, error counters, potentially corrupted REPL globals). Resuming into this state could cause cascading failures.

The ADK `Runner` expects a `session_service` and creates/resumes sessions by ID. The cron agent would need to either call `create_rlm_runner()` programmatically (pulling in the full dependency graph) or shell out to `adk run` with a crafted input.

**Recommendation:** Always create a new session for retries. Carry forward only the original prompt (not accumulated state). Link the retry to the original trace via a `retry_of_trace_id` field for traceability.

---

## 10. Missing: Observability of the Cron Agent Itself

The proposal does not mention how to observe the cron agent. If it runs every 30 minutes, you need:

- Logs of what it decided (which traces it considered, why it retried or skipped each one)
- Metrics: retries attempted, retries succeeded, retries failed again, total tokens spent on retries
- Alerting: if the cron agent itself crashes, who notices?
- Audit trail: which traces were auto-retried and what the outcome was

The existing `SqliteTracingPlugin` would capture the cron agent's own runs if it uses the standard ADK pipeline, but that creates a recursive problem: the cron agent's traces appear in `traces.db` alongside the runs it is monitoring. It could retry *its own* failed retry attempts.

**Recommendation:** Tag cron-initiated runs with a `source='cron_retry'` marker in session state (captured by SqliteTracingPlugin in `session_state_events`). Exclude `source='cron_retry'` traces from the cron agent's failure scan query. Log cron decisions to a separate `.adk/cron_retry.log` file.

---

## Summary: What You Are Missing

| # | Blind Spot | Severity |
|---|-----------|----------|
| 1 | `traces.db` has no `'failed'` status -- only `'running'` and `'completed'` | **Blocking** -- cannot query for failures without schema changes |
| 2 | Full prompt not stored in `traces.db` (truncated to 500 chars) | **Blocking** -- cannot resubmit without the original prompt |
| 3 | Most retryable errors are already retried by existing infrastructure | **Design** -- narrow useful band for a third retry layer |
| 4 | "Adjusted parameters" are undefined and mostly not per-run adjustable | **Design** -- vague mechanism |
| 5 | SQLite write contention with running SqliteTracingPlugin | **Risk** -- needs mitigation strategy |
| 6 | Prior art exists (janitor pattern, vision doc, existing retry layers) | **Efficiency** -- should build on existing patterns |
| 7 | No retry amplification limits | **Critical** -- exponential blowup without caps |
| 8 | Fix hypothesis requires its own LLM call (cost, availability, meta-prompt) | **Design** -- adds complexity and failure modes |
| 9 | Session identity question (new vs. resume) is unaddressed | **Design** -- wrong choice causes cascading failures |
| 10 | No observability for the cron agent itself; recursive retry risk | **Risk** -- cron agent could retry its own failures |

## Recommended Minimum Viable Version

Instead of the full proposal, build this:

1. **Add a `completion_quality` column to `traces`** (`success` / `partial` / `orphaned` / `error`) computed in `after_run_callback` from existing counters. Mark stale `running` traces as `orphaned` via a standalone janitor script (following the data janitor pattern).
2. **Persist the full `root_prompt`** in `traces` (or as an artifact linked by `trace_id`).
3. **Build a deterministic retry queue** (no LLM in the loop): resubmit orphaned traces as-is, resubmit schema-validation-exhausted traces with a standard prompt suffix. Cap at 2 retries per `prompt_hash`. Circuit breaker on failure rate.
4. **Follow the data janitor architecture:** standalone script + optional ADK plugin + cron installer + schema introspection.
5. **Tag and exclude** cron-initiated retries from the retry scan.

This gets you 80% of the value with 20% of the risk. The LLM-based failure analysis ("generate a fix hypothesis") can be layered on later as part of the autonomous self-improvement framework once the deterministic foundation is proven.
