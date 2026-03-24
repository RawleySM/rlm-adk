<!-- validated: 2026-03-22 -->

# Watchdog & Circuit Breaker Patterns

**Status:** Conceptual — no implementation yet

**What it does:** Detects when an unattended agent session is stuck, looping, burning tokens without progress, or trapped in an error recovery spiral — and intervenes before the damage compounds. The watchdog is the difference between waking up to a finished analysis and waking up to a $200 bill for 10,000 retries of the same failing prompt.

---

## The Core Problem

The current RLM runtime is designed for attended sessions where a human notices problems. Overnight runs have no human observer. Without a watchdog:

- A transient 429 retry loop can exhaust the entire API budget in minutes
- A model that writes correct-looking but unproductive REPL code can spin for hours
- A child dispatch that consistently fails and retries can silently consume the iteration budget without progressing the root task
- A structured output validation loop (BUG-13 territory) can oscillate indefinitely
- The agent can "succeed" at subtasks that don't converge toward the root objective

These are not hypothetical. The existing FMEA test suite already models several of these failure modes. The difference is that in an attended session, a human pulls the plug. In an overnight session, the system must pull its own plug.

---

## Watchdog Architecture

The watchdog should be a plugin (`WatchdogPlugin`) that observes the same event stream the existing ObservabilityPlugin and SqliteTracingPlugin consume — but its job is intervention, not recording.

### What It Watches

| Signal | Source | Interpretation |
|--------|--------|----------------|
| Token velocity | `after_model_callback` token counts | Tokens consumed per wall-clock minute. A spike followed by no new artifacts = probable loop. |
| Progress markers | `on_event_callback` state deltas | Meaningful state keys advancing (new REPL results, new artifacts saved, child dispatches completing). Absence of progress over N minutes = stall. |
| Error density | `on_model_error_callback` + child dispatch errors | Error rate exceeding threshold within a window = systemic failure, not transient. |
| Iteration budget consumption rate | `ITERATION_COUNT` state key | If 80% of the iteration budget is consumed without a final answer forming, the run is likely not converging. |
| Code repetition | `REPL_SUBMITTED_CODE_HASH` state keys | Same code hash submitted more than K times = the model is stuck in a loop. |
| Child dispatch fan-out ratio | Dispatch telemetry | Ratio of child dispatches to useful results. A high ratio with low useful output = wasted recursion. |

### Intervention Tiers

The watchdog should not just kill the run. It should escalate through tiers:

**Tier 1 — Soft Warning (inject into dynamic instruction)**

Write a warning into the dynamic instruction state so the reasoning agent sees it on its next model call. Example: "You have consumed 75% of your iteration budget. Focus on producing a final answer rather than exploring further."

This uses the existing `instruction_router` / dynamic instruction merge path. No new plumbing needed.

**Tier 2 — Budget Throttle**

Reduce the remaining iteration budget or child dispatch concurrency. The orchestrator already reads `RLM_MAX_ITERATIONS` at construction time, but a mid-run cap could be applied by the watchdog writing a `watchdog:max_remaining_iterations` state key that the REPLTool checks.

**Tier 3 — Forced Synthesis**

If the agent has accumulated substantial intermediate results but is not converging on a final answer, the watchdog can inject a "synthesize now" instruction that overrides the normal reasoning flow. This is analogous to a human saying "just give me what you have."

**Tier 4 — Hard Kill**

Terminate the run. Write a watchdog artifact explaining why the run was killed, including the accumulated telemetry at the time of termination. Save all intermediate work so it can be resumed or reviewed.

---

## Circuit Breaker Patterns

Circuit breakers are narrower than the watchdog — they protect specific subsystems from cascading failure.

### API Circuit Breaker

The existing `RLM_LLM_MAX_RETRIES` + exponential backoff handles transient errors. But a circuit breaker adds a window-based dimension: if N of the last M API calls failed, trip the circuit and stop calling the API entirely for a cooldown period.

This matters overnight because the difference between "API is temporarily slow" and "API is down for maintenance" is unknowable from a single retry. A circuit breaker with a 5-minute cooldown and progressive backoff (5m → 15m → 30m) lets the run survive a maintenance window without burning retry budget.

### Child Dispatch Circuit Breaker

If child dispatches at a given depth are consistently failing, stop dispatching more children at that depth. The parent should synthesize from whatever partial results it has rather than continuing to throw children at a failing model endpoint.

This directly extends the existing `_classify_error` taxonomy in `dispatch.py`.

### Structured Output Circuit Breaker

If schema validation retries exceed a threshold within a single iteration, the circuit breaker should force a fallback to unstructured output rather than exhausting the retry budget. The existing `WorkerRetryPlugin` / BUG-13 patch already handles individual validation failures, but there's no aggregate threshold that says "this schema is not going to work for this prompt — give up on structured output."

---

## State Keys

| Key | Type | Purpose |
|-----|------|---------|
| `watchdog:status` | `str` | `green` / `yellow` / `red` / `killed` |
| `watchdog:last_progress_time` | `float` | Epoch timestamp of last meaningful progress |
| `watchdog:token_velocity_1m` | `float` | Tokens/minute over last rolling window |
| `watchdog:error_density_5m` | `float` | Errors/minute over last 5-minute window |
| `watchdog:intervention_count` | `int` | Number of watchdog interventions this run |
| `watchdog:kill_reason` | `str` | Populated on Tier 4 kill |

---

## Open Design Questions

- What defines "meaningful progress"? New artifacts? New state keys? Changed REPL locals? The progress definition must be tight enough to catch loops but loose enough to allow legitimate exploration.
- Should the watchdog be configurable per-run, or should it use conservative defaults that the user can override? Overnight runs might warrant different thresholds than attended runs.
- Should the watchdog have its own telemetry table in traces.db, or should it write to the existing telemetry table with a `watchdog` event_type?
- How does the watchdog interact with Capture Mode? If a run is killed by the watchdog, should it still attempt topology capture of the partial work?

---

## Relationship to Existing Infrastructure

- **ObservabilityPlugin**: The watchdog reads many of the same signals but acts on them rather than just recording them. It should consume ObservabilityPlugin's instance-local counters, not duplicate the counting logic.
- **SqliteTracingPlugin**: The watchdog should write its own intervention events to the telemetry table so post-mortem analysis can see exactly when and why interventions occurred.
- **REPLTool call limit**: The existing `max_calls` enforcement is a primitive version of Tier 4. The watchdog generalizes this to multi-dimensional health assessment.
- **AR-CRIT-001**: Watchdog state writes must go through `callback_context.state` or `EventActions(state_delta={})`, never direct session state mutation.
