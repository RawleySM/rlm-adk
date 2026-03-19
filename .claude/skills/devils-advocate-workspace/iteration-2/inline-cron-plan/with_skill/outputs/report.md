# Devil's Advocate Review: Cron-Based Auto-Retry Agent for Failed Runs

## Reference Key
| Prefix | Section | Source |
|--------|---------|--------|
| A | ADK Callback Opportunities | ADK Callback Expert |
| V | Vision Alignment Recommendations | Vision Alignment Challenger |
| P | Prior Art Findings | Prior-Art Researcher |
| X | Cross-Cutting Themes | Synthesis (multi-critic) |
| R | Prioritized Recommendations | Synthesis (all critics) |

> **Usage:** Reference any finding by its ID (e.g., "implement A2, V1, and R3") to direct follow-up work.

---

## ADK Callback Opportunities

The plan describes a cron job that: (1) reads the SQLite tracing DB for failed runs, (2) classifies the error type, (3) generates a fix hypothesis, and (4) resubmits with adjusted parameters. This analysis examines where ADK's callback and plugin system could replace or improve the proposed manual approach.

### A1. Error Classification Already Exists in dispatch.py -- The Cron Agent Would Reinvent It

- **What the plan does now** -- The cron agent would "classify the error type" by reading failure traces from SQLite after the fact. This implies building a post-hoc error taxonomy parser that reads `traces.db` columns like `error_type`, `error_message`, and `finish_reason`.
- **What ADK callback/plugin could replace it** -- The codebase already has a rich error classification pipeline that runs *during* execution: `_classify_error()` in `dispatch.py` (lines 62-100) categorizes errors into TIMEOUT, RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, and PARSE_ERROR. The `ObservabilityPlugin` tracks `obs:finish_safety_count`, `obs:finish_recitation_count`, `obs:finish_max_tokens_count`. The `SqliteTracingPlugin` persists these into `telemetry.error_type` and `telemetry.error_message`. A `BasePlugin.after_run_callback()` could capture the classified error at the exact moment it occurs, write a structured "retry recommendation" artifact, and even enqueue a retry -- all within the same process, with full access to `InvocationContext`.
- **Benefit** -- Real-time classification is strictly more accurate than post-hoc trace reading. The cron agent would be parsing serialized summaries of data that was already structured at the source. An `after_run_callback` eliminates the lossy serialization roundtrip entirely.

### A2. after_run_callback Is the Natural Retry Trigger -- Not a Cron Poll

- **What the plan does now** -- A cron job polls every 30 minutes, scanning the entire `traces.db` for `status != 'completed'` rows. This is a pull-based pattern.
- **What ADK callback/plugin could replace it** -- `BasePlugin.after_run_callback(*, invocation_context: InvocationContext)` fires after every invocation. A `RetrySchedulerPlugin` could inspect the completion state, decide whether the failure is retryable, and either (a) immediately re-invoke via `Runner.run_async()`, (b) write a structured retry record to a lightweight queue (SQLite table, file, or in-memory deque), or (c) emit an event that a separate long-running process consumes. This is push-based: retries happen within seconds of failure, not up to 30 minutes later.
- **Benefit** -- Push-based retry eliminates the 0-30 minute latency gap. It also avoids the cron agent needing to reconstruct invocation context from traces -- `after_run_callback` already has the live `InvocationContext` with full session state, the exact error, and the original prompt.

### A3. before_model_callback Could Inject Adjusted Parameters Instead of a New Invocation

- **What the plan does now** -- The plan re-dispatches with "adjusted parameters." This implies creating an entirely new invocation with modified configuration.
- **What ADK callback/plugin could replace it** -- For many failure classes (RATE_LIMIT, MAX_TOKENS, SAFETY), the fix is not a new invocation but an adjustment to the *next* model call within the same invocation. `before_model_callback(*, callback_context, llm_request, **_kw)` can mutate `LlmRequest` in-flight: reduce `max_output_tokens`, change the `model` to a fallback, modify system instructions to avoid safety triggers, or add retry context. The orchestrator already does this for transient errors (lines 454-496 of `orchestrator.py`) with exponential backoff. Extending this to cover more error classes within the existing invocation would be cheaper than a full re-dispatch.
- **Benefit** -- In-flight adjustment avoids the overhead of a new session, new REPL initialization, new dispatch closure wiring, and new artifact creation. For RATE_LIMIT and SERVER errors, the existing retry loop in the orchestrator is already the correct mechanism -- the cron agent would be duplicating it with worse latency.

### A4. on_event_callback Could Build the "Fix Hypothesis" Incrementally

- **What the plan does now** -- The cron agent reads completed traces and retroactively generates a "fix hypothesis" via LLM analysis of the failure.
- **What ADK callback/plugin could replace it** -- `BasePlugin.on_event_callback(*, event, invocation_context)` sees every event as it flows through the system. A `FailureAnalysisPlugin` could accumulate a running "failure narrative" during execution: noting when errors occur, which tools failed, what the error classification was, and what the model's last reasoning state was. By the time `after_run_callback` fires, the plugin already has a structured failure analysis without needing a post-hoc LLM call to reconstruct it.
- **Benefit** -- Eliminates the most expensive part of the cron agent: the LLM call to "generate a fix hypothesis." The real-time event stream contains richer information than what survives serialization into `traces.db`.

### A5. Missing: Session State Reconstruction for Re-dispatch Is Non-Trivial

- **What the plan does now** -- Implicitly assumes the cron agent can reconstruct enough context to re-dispatch. The plan does not address how the cron agent would obtain: the original `root_prompt`, `user_ctx` (which is loaded from `RLM_USER_CTX_DIR` at runtime and placed in REPL globals), `enabled_skills`, `instruction_router` configuration, `output_schema`, or the `worker_pool` / `DispatchConfig`. These are all wired at invocation time in `_run_async_impl()` and are not fully persisted in `traces.db`.
- **What ADK callback/plugin could replace it** -- An `after_run_callback` that captures a serialized "retry envelope" containing the full invocation configuration (not just the trace summary) into a dedicated retry queue table. This envelope would include everything needed to reconstruct the invocation without guessing.
- **Benefit** -- Without this, the cron agent will either produce incomplete re-dispatches or require a parallel persistence mechanism that duplicates what a plugin could capture natively.

**Confidence rating:** Significant restructuring opportunity. The plan's core loop (poll -> classify -> hypothesize -> retry) maps almost 1:1 to ADK callback hooks that would be more accurate, lower-latency, and cheaper to operate.

---

## Vision Alignment Assessment

| Vision Area | Alignment | Assessment |
|-------------|-----------|------------|
| Polya Topology | Neutral | The cron retry agent does not advance or conflict with topology selection -- it operates post-hoc on completed runs regardless of topology used. |
| Dynamic Skill Loading | Neutral/Missed Opportunity | Failure traces are a rich signal for what *not* to do, but the plan does not feed failure patterns into the skill loading pipeline as negative examples. |
| Continuous Runtime | Advances | This is the most directly aligned vision area -- the plan is an instance of "cron-triggered autonomous agents" described in `autonomous_self_improvement.md`. |
| Interactive Dashboard | Conflicts (mildly) | A 30-minute cron poll is invisible to the dashboard; Bret Victor's principle demands immediate feedback, not silent background recovery. |

### V1. Feed Failure Patterns Into Dynamic Skill Loading as Negative Examples

The Dynamic Skill Loading vision (`dynamic_skill_loading.md`, `codex_proposal_reframed.md`) focuses on promoting *successful* execution patterns into reusable skills. But failure patterns are equally valuable signal. When the cron agent classifies an error and generates a fix hypothesis, that hypothesis-fix pair should be captured as a "failure avoidance heuristic" in the skill registry. Future runs encountering similar contexts would receive the heuristic as part of their dynamic instruction, reducing the probability of the same failure class recurring. The vision documents do not currently address this -- the plan could pioneer the "negative skill" concept.

### V2. Use the Dashboard as the Retry Control Surface, Not Silent Cron

The Interactive Dashboard vision (`interactive_dashboard.md`, `NiceGUI_agent_dashboard_ideas.md`) explicitly calls for a "co-pilot holding the same steering wheel." A silent cron agent that re-dispatches in the background violates this. The dashboard should surface failed runs with a one-click "retry with adjustments" action. The cron agent's classification and hypothesis logic should feed *into* the dashboard as suggested actions, not bypass the human entirely. This aligns with the HITL async gates described in the dashboard vision (approve / reject / edit then resume). The cron component should be the *engine* behind a dashboard retry panel, not a standalone autonomous actor.

### V3. The Cron Interval Is Wrong for the Continuous Runtime Vision

`autonomous_self_improvement.md` describes cron-triggered agents for maintenance tasks (gap audit, doc staleness, test coverage expansion). These are daily/weekly tasks where 30-minute latency is irrelevant. But failure retry is a *real-time operational concern*. The plan should distinguish between "maintenance cron" (daily, scanning for patterns across many runs) and "failure response" (immediate, triggered by a single run's failure). Conflating them into a single 30-minute cron job underserves both: too frequent for maintenance analysis, too slow for failure recovery.

### V4. Align with the Capture Mode Architecture for Failure Topology Extraction

The Capture Mode meta-orchestration (`codex_proposal_reframed.md`) describes a system that studies its own successful behavior to extract reusable topology artifacts. The symmetric operation -- studying *failed* behavior to extract failure topology artifacts -- is equally valuable and directly synergistic. Instead of just retrying, the cron agent should also feed into a "Failure Mode Capture" that identifies recurring failure topologies: "rate limit cascades during batched dispatch," "safety filter triggers on medical context," "max tokens on large repo analysis." These become first-class objects alongside successful topology artifacts.

### V5. Respect the Worktree Constraint for Autonomous Agents

`autonomous_self_improvement.md` specifies that autonomous agents "must operate within a worktree" and "must create PRs, never push directly to main." If the cron agent generates adjusted parameters that include code changes (e.g., modified prompts, new skill text), those changes must go through the worktree workflow. The plan does not address this constraint.

**Overall verdict:** This plan is **partially aligned** with the project vision. It correctly instantiates the continuous runtime concept of cron-triggered autonomous agents, but it misses the dashboard integration opportunity, the negative skill loading opportunity, and the failure topology capture opportunity. Most critically, it conflates maintenance-cadence cron with real-time failure response, which serves neither use case well.

---

## Prior Art Findings

### P1. Error Classification from Agent Traces

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| arXiv | [Where LLM Agents Fail and How They can Learn From Failures](https://arxiv.org/abs/2509.25370) | AgentErrorTaxonomy: modular classification of failure modes spanning memory, reflection, planning, action, and system-level operations. AgentErrorBench dataset of annotated failure trajectories. | High | Adapt taxonomy as the classification schema rather than building one from scratch |
| arXiv | [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657) | MAST: Multi-Agent System Failure Taxonomy -- 14 failure modes in 3 categories (system design, inter-agent misalignment, task verification). Validated on 150 traces. | High | Use MAST categories for multi-agent failure classification in dispatch.py |
| arXiv | [When Agents Fail: Comprehensive Study of Bugs in LLM Agents](https://arxiv.org/html/2601.15232) | Shows LLM agents can identify and annotate bugs within agentic systems when appropriately designed -- validates the "LLM classifies its own failures" approach. | Medium | Validates the fix-hypothesis-generation concept, but see caveats below |
| Existing | `dispatch.py` `_classify_error()` (lines 62-100) | Already classifies TIMEOUT, RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, PARSE_ERROR | High | This is already built -- the cron agent would be duplicating it |

The plan's error classification capability has substantial prior art. The codebase already implements a production error classifier. Academic taxonomies (AgentErrorTaxonomy, MAST) offer richer classification schemas that could extend the existing `_classify_error()` function rather than requiring a separate cron-based classifier.

### P2. Self-Healing / Auto-Retry for Agent Failures

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| arXiv | [VIGIL: A Reflective Runtime for Self-Healing LLM Agents](https://arxiv.org/html/2512.07094v2) | Runtime that enables agents to observe their own behavior, summarize outcomes, and reflect on failure modes. Retries with jittered exponential backoff. Structured error toasts with stable reason codes. | High | Study VIGIL's architecture -- it is the closest prior art to the proposed plan |
| arXiv | [PALADIN: Self-Correcting Language Model Agents](https://arxiv.org/html/2509.25238v1) | Formalizes tool failures, constructs recovery-annotated training data, fine-tunes with recovery-aware objective. 55+ curated failure exemplars for taxonomy-driven retrieval at inference. | Medium | The failure exemplar retrieval pattern maps to dynamic skill loading |
| arXiv | [Graph-Based Self-Healing Tool Routing](https://arxiv.org/abs/2603.01548) | Cost-weighted tool graph with Dijkstra routing. When a tool fails, edges are reweighted and path is recomputed for automatic recovery. | Low | Interesting but architecturally different from RLM-ADK's approach |
| Google ADK | [Reflect and Retry Plugin](https://google.github.io/adk-docs/plugins/reflect-and-retry/) | Built-in ADK plugin that intercepts tool failures, provides structured guidance for reflection and correction, retries up to configurable limit. Concurrency-safe, per-tool tracking. | High | **Already in the codebase** -- `WorkerRetryPlugin` extends this. The plan should build on it, not replace it. |
| GitHub | [healing-agent](https://github.com/matebenyovszky/healing-agent) | AI-powered automatic software healing agent | Low | Generic concept, not directly applicable |
| Medium | [Self-Healing LangChain Agent](https://medium.com/@bhagyarana80/how-i-built-a-self-healing-langchain-agent-with-retry-logic-and-memory-isolation-b76044414de4) | Retry logic with memory isolation in LangChain | Low | LangChain-specific, but validates the pattern |

The auto-retry capability has significant prior art, and critically, the codebase already implements much of it. ADK's `ReflectAndRetryToolPlugin` (extended as `WorkerRetryPlugin` in `callbacks/worker_retry.py`) handles in-invocation tool failure recovery. The orchestrator's retry loop (lines 454-496) handles transient HTTP errors. What is genuinely novel in the plan is the *cross-invocation* retry: re-dispatching an entirely new invocation based on learning from a previous failure.

### P3. Fix Hypothesis Generation via LLM Trace Analysis

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| arXiv | [VIGIL](https://arxiv.org/html/2512.07094v2) | Agents summarize outcomes and reflect on failure modes using structured memory to generate better adaptations | Medium | Closest to "generate a fix hypothesis" concept |
| Medium | [LLM-Powered CI/CD Pipelines](https://medium.com/cloudops-insider/llm-powered-ci-cd-pipelines-when-pipelines-debug-themselves-a5b18d5d378b) | LLM-powered pipelines that understand why they failed, debug errors, suggest or apply fixes | Medium | Same concept applied to CI/CD rather than agents |
| ResearchGate | [Automated Remediation and Self-Healing Mechanisms for LLMs in Production](https://www.researchgate.net/publication/398941370_Automated_Remediation_and_Self-Healing_Mechanisms_for_Large_Language_Models_in_Production) | Production mechanisms for automated remediation | Medium | Academic validation of the approach |

Fix hypothesis generation is a less mature area. VIGIL is the closest prior art but operates within a single runtime, not as a post-hoc cron analysis. The plan's approach of reading SQLite traces to generate hypotheses is novel but carries risks (see X2).

### P4. Cron-Scheduled Agent Orchestration

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| Blog | [Engineering Autonomous AI Pipelines: Cron-Scheduled Agents](https://earezki.com/ai-news/2026-03-12-how-to-schedule-ai-agent-tasks-with-cron-the-missing-guide/) | Guide to scheduling AI agent tasks with cron, including retry policies | Medium | Practical reference for cron-agent patterns |
| GitHub | [Agent Zero Scheduler Issues](https://github.com/agent0ai/agent-zero/issues/1251) | Tasks stuck in error state permanently after transient LLM failures -- no recovery path | High (as cautionary tale) | The exact failure mode the plan would face without proper state management |
| GitHub | [OpenClaw Infinite Retry Loop](https://github.com/openclaw/openclaw/issues/8520) | Cron tasks without failure limit trigger infinite retry loops causing API cooldown | High (as cautionary tale) | The plan MUST include a retry budget/circuit breaker |
| Starkinsider | [Don't Let Your AI Agents Become Glorified Cron Jobs](https://www.starkinsider.com/2026/03/ai-agents-cron-job-trap-openclaw-nanoclaw.html) | Argues against reducing agents to simple cron patterns | Medium | Philosophical counterpoint worth considering |

**Summary:** 3 of 4 planned capabilities have substantial prior art. Error classification and auto-retry are well-covered by existing codebase code and ADK plugins. Fix hypothesis generation is the most novel component. Cron scheduling of agent tasks has significant cautionary tales about infinite retry loops and permanent error states that the plan must address.

---

## Cross-Cutting Themes

### X1. The Plan Duplicates Existing In-Process Capabilities as an Out-of-Process Cron Job (flagged by: A1, A2, A3, P2, P4)

This is the highest-confidence finding across all three critics. The codebase already has: `_classify_error()` for error classification (A1), the orchestrator retry loop for transient errors (A3), `WorkerRetryPlugin` / `ReflectAndRetryToolPlugin` for tool-level retry (P2), and `BasePlugin.after_run_callback` as a natural push-based retry trigger (A2). The plan proposes rebuilding all of these as an out-of-process cron job that reads SQLite traces -- a lossy, high-latency version of capabilities that already exist with full fidelity in-process. The prior art research (P4) further shows that cron-based agent retry has known failure modes (infinite loops, permanent error states) that in-process retry avoids.

### X2. The Trace-to-Hypothesis LLM Call Is the Riskiest Component (flagged by: A4, A5, P3)

The plan's most novel element -- having an LLM read failure traces and generate a "fix hypothesis" -- is also its riskiest. Three independent findings converge on this: (a) the trace data in `traces.db` is a *lossy summary* of what happened, not the full execution context (A5), so the LLM is reasoning from incomplete information; (b) real-time event-stream analysis via `on_event_callback` would produce richer failure narratives than post-hoc trace reading (A4); (c) prior art for this pattern (VIGIL, PALADIN) operates *within* the runtime, not from serialized traces (P3). The fix hypothesis generated from traces will be systematically worse than one generated from live execution context.

### X3. The 30-Minute Cron Interval Serves Neither Maintenance Nor Recovery Well (flagged by: V3, A2, P4)

The vision documents distinguish between maintenance tasks (daily/weekly cron) and operational response (immediate). The plan's 30-minute interval is a compromise that underserves both. For failure recovery, 30 minutes is too slow -- an `after_run_callback` could trigger within seconds (A2). For pattern analysis across many runs (identifying systemic failure modes), 30 minutes is too frequent and would waste LLM tokens on individual failures rather than aggregate patterns. The Agent Zero and OpenClaw issues (P4) show that frequent cron polling of agent state leads to cascading problems.

### X4. The Plan Misses the Dashboard Integration Opportunity (flagged by: V2, V4)

Both the vision alignment and the dashboard philosophy point to the same gap: the plan operates silently in the background. The Inventing on Principle philosophy demands that failure recovery be *visible* and *manipulable*. The cron agent's classification, hypothesis, and retry decision should be surfaced in the dashboard as a "suggested action" that the user can approve, modify, or reject -- not executed autonomously. This also connects to the HITL async gates described in the interactive dashboard vision.

---

## Prioritized Recommendations

### R1. Replace the Cron Polling Loop with a `RetrySchedulerPlugin` Using `after_run_callback`
**Traces to:** A1, A2, A5, X1, X3, P2

Build a `RetrySchedulerPlugin(BasePlugin)` that:
- Fires in `after_run_callback` after every failed invocation
- Has full access to `InvocationContext` (no lossy trace reconstruction)
- Captures a serialized "retry envelope" with the complete invocation config (root_prompt, user_ctx manifest, enabled_skills, output_schema, dispatch config)
- Writes the envelope to a `retry_queue` table in `traces.db` (or a separate `retry.db`)
- Applies a retry policy: max 2 retries per invocation, exponential backoff, circuit breaker after 5 consecutive failures across any invocations
- For transient errors (RATE_LIMIT, SERVER, TIMEOUT): schedule immediate retry with backoff
- For non-transient errors (SAFETY, SCHEMA_VALIDATION_EXHAUSTED): mark as "needs human review" and surface in dashboard

This replaces the entire cron-based polling loop with a push-based, low-latency, full-fidelity mechanism. The cron job, if kept at all, becomes a garbage collector for stale retry records -- not the primary retry trigger.

### R2. Surface Retry Decisions in the Dashboard, Not as Silent Background Actions
**Traces to:** V2, V4, X4

Wire the `RetrySchedulerPlugin`'s retry queue into the live dashboard (`live_app.py` / `live_loader.py`):
- Show a "Failed Runs" panel with classified errors, suggested retry actions, and the retry envelope
- Allow one-click "Retry with defaults" or "Edit parameters then retry"
- Show retry history (attempts, outcomes) per original invocation
- For non-transient errors, display the failure analysis as a structured card (error type, relevant telemetry, suggested parameter adjustments)

This turns the cron agent's best idea -- intelligent failure analysis -- into a dashboard feature aligned with the Inventing on Principle philosophy of immediate, visible feedback.

### R3. Extend `_classify_error()` with Academic Failure Taxonomies Instead of Building a Separate Classifier
**Traces to:** A1, P1, X1

The existing `_classify_error()` in `dispatch.py` covers HTTP-level errors well but misses higher-level failure modes. Extend it (or create a companion `classify_run_failure()`) using categories from the AgentErrorTaxonomy (arXiv:2509.25370) and MAST (arXiv:2503.13657):
- Memory failures (context overflow, stale state)
- Planning failures (wrong topology, scope creep)
- Inter-agent misalignment (child dispatch failures, schema validation exhaustion)
- Task verification failures (correct execution but wrong answer)

This gives the `RetrySchedulerPlugin` a richer classification without an LLM call, because the signals are already available in session state and telemetry.

### R4. Keep a Lightweight Cron Job for Aggregate Failure Pattern Analysis (Daily, Not Every 30 Minutes)
**Traces to:** V3, V4, X3

The plan's instinct to analyze failure patterns is correct -- but it should be a *daily maintenance task*, not a real-time retry mechanism. Build a separate `FailurePatternAnalysisAgent` that:
- Runs daily (not every 30 minutes)
- Reads all failure traces from the past 24 hours in aggregate
- Identifies systemic patterns (e.g., "all SAFETY failures involve medical context," "RATE_LIMIT failures cluster between 2-4 PM")
- Feeds patterns into the dynamic skill loading pipeline as "failure avoidance heuristics" (V1)
- Feeds patterns into the Capture Mode failure topology registry (V4)
- Produces a daily digest surfaced in the dashboard

This separates the two fundamentally different concerns: immediate failure recovery (R1) and long-term failure pattern learning (this recommendation).

### R5. Add a Retry Budget and Circuit Breaker to Prevent the Infinite Retry Loop Anti-Pattern
**Traces to:** P4, X1

The Agent Zero and OpenClaw issues demonstrate that cron-based agent retry without limits leads to infinite loops and API cooldown. Any retry mechanism (whether plugin or cron) MUST include:
- Per-invocation retry limit (max 2 retries)
- Global circuit breaker (if 5 consecutive retries across any invocations fail, pause all retries for 1 hour)
- Token budget per retry (retry attempts should not exceed the original invocation's token cost)
- Retry log with full audit trail
- Dashboard visibility into circuit breaker state

### R6. Feed Failure Classifications into the Skill Registry as Negative Examples
**Traces to:** V1, V4, P1

This is the plan's biggest missed opportunity. When a failure is classified and a fix is identified (either automatically or via human review in the dashboard), capture a "failure avoidance skill":
- Problem class: what kind of task triggered the failure
- Failure mode: the classified error type
- Avoidance heuristic: what to do differently (e.g., "for medical context, add safety disclaimer prefix," "for repos > 500K tokens, use chunked topology")
- Store in the skill registry alongside positive skills
- Surface via dynamic instruction when the next run matches the problem class

This turns every failure into a permanent improvement to the system, directly advancing the Dynamic Skill Loading and Continuous Runtime visions.

---

## Sources

- [VIGIL: A Reflective Runtime for Self-Healing LLM Agents](https://arxiv.org/html/2512.07094v2)
- [PALADIN: Self-Correcting Language Model Agents](https://arxiv.org/html/2509.25238v1)
- [Graph-Based Self-Healing Tool Routing](https://arxiv.org/abs/2603.01548)
- [Where LLM Agents Fail and How They can Learn From Failures](https://arxiv.org/abs/2509.25370)
- [Why Do Multi-Agent LLM Systems Fail? (MAST)](https://arxiv.org/abs/2503.13657)
- [When Agents Fail: Comprehensive Study of Bugs in LLM Agents](https://arxiv.org/html/2601.15232)
- [Google ADK Reflect and Retry Plugin](https://google.github.io/adk-docs/plugins/reflect-and-retry/)
- [Agent Zero Scheduler: Tasks Stuck in Error State](https://github.com/agent0ai/agent-zero/issues/1251)
- [OpenClaw: Infinite Retry Loop](https://github.com/openclaw/openclaw/issues/8520)
- [OpenClaw: Cron Jobs Silently Time Out](https://github.com/openclaw/openclaw/issues/45494)
- [Engineering Autonomous AI Pipelines: Cron-Scheduled Agents](https://earezki.com/ai-news/2026-03-12-how-to-schedule-ai-agent-tasks-with-cron-the-missing-guide/)
- [Don't Let Your AI Agents Become Glorified Cron Jobs](https://www.starkinsider.com/2026/03/ai-agents-cron-job-trap-openclaw-nanoclaw.html)
- [Self-Healing LangChain Agent with Retry Logic](https://medium.com/@bhagyarana80/how-i-built-a-self-healing-langchain-agent-with-retry-logic-and-memory-isolation-b76044414de4)
- [LLM-Powered CI/CD Pipelines](https://medium.com/cloudops-insider/llm-powered-ci-cd-pipelines-when-pipelines-debug-themselves-a5b18d5d378b)
- [Automated Remediation and Self-Healing Mechanisms for LLMs in Production](https://www.researchgate.net/publication/398941370_Automated_Remediation_and_Self-Healing_Mechanisms_for_Large_Language_Models_in_Production)
- [Google ADK Retry Discussion #2756](https://github.com/google/adk-python/discussions/2756)
- [Google ADK Retry Issue #3198](https://github.com/google/adk-python/issues/3198)
