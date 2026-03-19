# Devil's Advocate Review: Cron-Based Auto-Retry Agent for Failed Runs

**Subject:** A proposed cron job running every 30 minutes that reads the SQLite tracing DB for failed runs, classifies error types, generates fix hypotheses via LLM, and re-dispatches with adjusted parameters.

---

## ADK Callback Opportunities

The proposed plan describes building a standalone cron agent that manually reads traces, classifies errors, generates fixes, and re-dispatches. Several components of this plan duplicate or under-utilize capabilities already present in the ADK callback and plugin system.

### 1. Error classification belongs in `after_model_callback` or `on_event_callback`, not in a post-hoc cron scan

**What the plan does:** The cron agent reads failure traces from SQLite after the fact, then classifies the error type by analyzing trace data.

**What ADK provides:** The codebase already has `_classify_error()` in `dispatch.py` (lines 62-100) that classifies errors into RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, PARSE_ERROR, TIMEOUT, and UNKNOWN at the moment of failure. The `SqliteTracingPlugin` already writes structured telemetry with finish reasons, error counts, and token data into `traces.db` via `after_model_callback`, `after_tool_callback`, and `on_event_callback`. The `ObservabilityPlugin` already tracks `obs:finish_safety_count`, `obs:finish_recitation_count`, `obs:finish_max_tokens_count`, and `OBS_CHILD_ERROR_COUNTS` in real time.

**What the callback approach would replace:** Instead of a cron agent that reconstructs error classification from cold traces, a `BasePlugin.on_event_callback` could emit a structured "failure record" with error class, context snapshot, and hypothesis metadata at the moment of failure. This keeps classification hot (immediate, with full context) rather than cold (30 minutes later, from serialized traces). The existing `_classify_error` taxonomy is already richer than most post-hoc classifiers could reconstruct.

**Benefit:** Real-time error classification is more accurate than post-hoc trace analysis. The full `InvocationContext`, error object with `.code` attribute, and live session state are all available at failure time but lost or degraded in the SQLite trace.

### 2. Re-dispatch logic should use `before_agent_callback` for conditional retry, not a separate cron agent

**What the plan does:** A separate cron process reads failure records and spawns new agent runs with adjusted parameters.

**What ADK provides:** `before_agent_callback` can inspect session state (including prior failure metadata written by `on_event_callback`) and decide whether to modify the invocation -- adjusting the model, temperature, system instruction, or available tools. The existing `WorkerRetryPlugin` (extending `ReflectAndRetryToolPlugin`) already implements a reflect-and-retry pattern for structured output failures within a single invocation.

**What the callback approach would replace:** For transient errors (RATE_LIMIT, SERVER, TIMEOUT), the retry should happen within the same invocation via ADK's built-in retry mechanisms or a plugin, not via a 30-minute delayed cron re-dispatch. For systematic errors (wrong model, bad prompt), a `before_run_callback` on the next invocation could check a "retry queue" in session state and apply parameter adjustments, keeping the retry logic inside the ADK lifecycle rather than in an external process.

**Benefit:** Tighter feedback loop (seconds vs. 30 minutes), no external process to maintain, retry metadata flows through ADK's event tracking automatically, and state mutations follow AR-CRIT-001 via `callback_context.state`.

### 3. Fix hypothesis generation duplicates what `after_model_callback` could do with reflection

**What the plan does:** The cron agent uses an LLM to analyze failure traces and generate a "fix hypothesis."

**What ADK provides:** `after_model_callback` receives the full `LlmResponse` and can detect failure patterns (safety blocks, max tokens, malformed output). It can then modify the response or set state that guides the next iteration. The existing `WorkerRetryPlugin` already does exactly this for structured output failures -- it detects empty/invalid responses and triggers a reflect-and-retry cycle within the same agent turn.

**Benefit:** Hypothesizing fixes while the full context is still in memory is fundamentally more effective than hypothesizing from a trace summary 30 minutes later.

### 4. Missing: A `BasePlugin` for cross-cutting failure aggregation

**What the plan does not address:** The plan describes per-run failure analysis but does not discuss cross-run pattern detection (e.g., "the last 5 runs all failed with RATE_LIMIT on the same model").

**What ADK provides:** A `BasePlugin` with `after_run_callback` could aggregate failure patterns across runs into a persistent store and trigger alerts or parameter adjustments when patterns emerge. This is more powerful than periodic cron polling because it fires immediately after each run.

**Overall callback adoption impact:** **Significant restructuring opportunity.** The plan builds an external retry system that fights the framework rather than leveraging it. Most of the proposed capabilities already exist as fragments in the codebase (`_classify_error`, `WorkerRetryPlugin`, `SqliteTracingPlugin`, `ObservabilityPlugin`). The missing piece is not a cron agent but a `FailureRecoveryPlugin` that wires these fragments together within the ADK lifecycle.

---

## Vision Alignment Assessment

| Vision Area | Alignment | Assessment |
|-------------|-----------|------------|
| Polya Topology | Neutral | The plan does not advance or conflict with topology selection; it operates entirely at the infrastructure/retry layer, orthogonal to how reasoning workflows are structured. |
| Dynamic Skill Loading | Partially Advances | Analyzing failure traces and generating fix hypotheses could feed into the skill promotion pipeline -- successful recovery patterns could become reusable "recovery skills" -- but the plan does not mention this connection. |
| Continuous Runtime | **Advances** | This plan is directly aligned with the autonomous self-improvement vision documented in `autonomous_self_improvement.md`, which explicitly lists cron-triggered agents for maintenance and improvement tasks. The plan's error classification and re-dispatch are a concrete instance of the "REPL Pattern Mining" and "Gap Audit" task types from the vision doc. |
| Interactive Dashboard | Partially Conflicts | The plan describes a fully autonomous background process with no interactive component. The "Inventing on Principle" vision emphasizes immediate feedback and direct manipulation. A cron job that silently retries in the background is the opposite of transparency. The dashboard should show failed runs, proposed fixes, and let the user approve/reject/modify the re-dispatch -- not do it silently. |

### Specific Recommendations for Tighter Alignment

1. **Connect to Dynamic Skill Loading:** When a fix hypothesis succeeds, the recovery pattern (error class + parameter adjustment + success) should be captured as a draft skill artifact per Architecture 2 (Draft/Promote Skill Factory). This turns failure recovery into a learning loop, not just a retry loop.

2. **Surface in the Dashboard:** Every proposed re-dispatch should appear in the NiceGUI live dashboard with: the original failure trace, the classified error type, the generated fix hypothesis, and approve/reject/modify controls. This transforms the cron agent from a black-box retry into a transparent "Inventing on Principle"-aligned HITL tool.

3. **Feed topology selection:** If certain Polya topologies consistently fail on certain task types, that signal should flow into the topology selection mechanism. The cron agent currently treats all failures as parameter-adjustment problems, but some failures indicate the wrong topology was chosen.

4. **Respect the Capture Mode vision:** The `codex_proposal_reframed.md` describes a Capture Mode that runs after successful workflows to extract reusable topology artifacts. The cron retry agent should be a sibling to Capture Mode -- running after *failed* workflows to extract *failure* patterns -- not a standalone system unaware of the capture pipeline.

**Overall verdict:** This plan is **partially aligned** with the project vision. It advances the Continuous Runtime goal but misses opportunities to connect with Dynamic Skill Loading and conflicts with the Interactive Dashboard philosophy by operating as an opaque background process.

---

## Prior Art Findings

The plan proposes building five core capabilities. Here is what already exists for each.

### Capability 1: Cron-Triggered Failure Detection from Trace DB

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| Temporal.io | [Durable AI Agent Tutorial](https://learn.temporal.io/tutorials/ai/durable-ai-agent/) | Durable execution engine that automatically detects failures, replays state, and retries -- no cron needed | **High** | Evaluate Temporal as the orchestration layer instead of building cron polling |
| DEV Community | [Cron-Based AI Agent Monitoring](https://dev.to/operationalneuralnetwork/cron-based-ai-agent-monitoring-building-self-healing-workflows-1gm6) | Tutorial on building cron-based monitoring for AI agent workflows with self-healing | **High** | Reference implementation for the exact pattern proposed |
| Substack | [AI Agent Scheduling System](https://codingchallenges.substack.com/p/coding-challenge-111-ai-agent-scheduling) | Cron-scheduled agents with retry logic, backoff, and failure detection | **Medium** | Pattern reference for scheduling and retry backoff |
| Medium | [LLM-Backed Cron Jobs: Self-Healing Playbooks](https://medium.com/@hadiyolworld007/llm-backed-cron-jobs-self-healing-playbooks-for-incident-response-4e90fb07142b) | LLM-backed cron jobs that automate incident response with self-healing playbooks | **Medium** | Architectural pattern reference |

### Capability 2: Automatic Error Classification from Failure Traces

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| arXiv (PALADIN) | [PALADIN: Self-Correcting Language Model Agents](https://arxiv.org/html/2509.25238v1) | Taxonomy-guided error classification with retrieval-based matching of runtime failures to recovery examples; 89.68% recovery rate | **High** | Study PALADIN's failure taxonomy -- it is more sophisticated than the proposed ad-hoc classification |
| arXiv (SHIELDA) | [Structured Handling of Exceptions in LLM-Driven Agentic Workflows](https://arxiv.org/pdf/2508.07935) | Structured, runtime-compatible exception handling framework for agentic workflows | **Medium** | Reference for structured exception handling patterns |
| Existing codebase | `rlm_adk/dispatch.py:_classify_error()` | Already classifies errors into 8 categories (RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, PARSE_ERROR, TIMEOUT, UNKNOWN) at failure time | **High** | You already have this -- extend it rather than rebuilding from cold traces |

### Capability 3: LLM-Based Fix Hypothesis Generation

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| arXiv (VIGIL) | [VIGIL: A Reflective Runtime for Self-Healing LLM Agents](https://arxiv.org/html/2512.07094v2) | Reflective runtime that supervises agents, ingests behavioral logs, and derives Roses/Buds/Thorns diagnosis mapping behavior into strengths, opportunities, and failures | **High** | VIGIL's reflective supervision pattern is very close to what is proposed -- study before building |
| arXiv (AutoRefine) | [AutoRefine: From Trajectories to Reusable Expertise](https://arxiv.org/html/2601.22758) | Extracts reusable expertise from agent execution trajectories for continual refinement | **Medium** | Relevant for the "learn from failures" aspect |
| GitHub (ADK Discussion) | [Tool and LLM retry mechanisms and checkpoints](https://github.com/google/adk-python/discussions/3187) | ADK community discussion on retry mechanisms and checkpoint-based recovery | **Medium** | Check if ADK is adding native support for this |

### Capability 4: Automatic Re-Dispatch with Adjusted Parameters

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| Temporal.io | [Temporal for AI](https://temporal.io/solutions/ai) | Automatic retry with configurable backoff, timeout, and parameter adjustment for LLM calls and tool executions -- all without custom retry code | **High** | Temporal handles this natively; evaluate before building custom |
| Temporal + OpenAI | [Temporal and OpenAI Integration](https://www.infoq.com/news/2025/09/temporal-aiagent/) | Production integration for durable AI agent execution with automatic failure recovery | **High** | Industry-standard approach to this exact problem |
| Substack | [Fail-Safe Patterns for AI Agent Workflows](https://engineersmeetai.substack.com/p/fail-safe-patterns-for-ai-agent-workflows) | Retry patterns with exponential backoff and circuit breakers for agent workflows | **Medium** | Pattern reference |

### Capability 5: End-to-End Self-Healing Loop (Detect-Classify-Hypothesize-Retry)

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| arXiv (VIGIL) | [VIGIL Paper](https://arxiv.org/html/2512.07094v2) | Full self-healing loop: supervise, diagnose (RBT), remediate, verify convergence | **High** | Closest prior art to the full proposed system |
| arXiv (PALADIN) | [PALADIN Paper](https://arxiv.org/html/2509.25238v1) | Failure injection + taxonomy-guided recovery + retrieval-based matching | **High** | Complementary to VIGIL -- focuses on the classification/recovery matching piece |
| GitHub (open_ei) | [OpenEI Self-Healing Intelligence](https://github.com/ValedL/open_ei) | Runtime autonomous self-healing for software components with agent-based monitoring and fixing | **Medium** | Architecture reference for agent-alongside-software pattern |
| Seth Server | [Self-Healing Agents That Fix Their Own Bugs](https://www.sethserver.com/ai/next-level-self-healing-building-agents-that-fix-their-own-bugs.html) | Tutorial on building agents that detect, diagnose, and fix their own bugs | **Medium** | Implementation walkthrough |

### Prior Art Summary

**4 of 5 planned capabilities have substantial prior art that could save development time.** The most significant finding is VIGIL (arXiv 2512.07094), which implements essentially the entire proposed system as a reflective runtime for self-healing LLM agents. PALADIN (arXiv 2509.25238) provides a more rigorous error classification and recovery framework than the ad-hoc classification proposed. Temporal.io provides the entire durable execution / retry / re-dispatch layer as infrastructure, eliminating the need for custom cron-based polling.

The one area where the plan is genuinely novel is its integration with the RLM-ADK-specific SQLite tracing schema and the project's particular dispatch/REPL architecture. That integration work is real and necessary, but the core algorithmic components (error taxonomy, reflective diagnosis, retry with parameter adjustment) have been well-studied.

---

## Cross-Cutting Themes

Three patterns emerged across multiple critics:

### 1. Cold vs. Hot Analysis (flagged by ADK Expert + Prior-Art Researcher)

Both the callback expert and the prior-art research (VIGIL, PALADIN) converge on the same insight: **analyzing failures from cold traces is fundamentally inferior to analyzing them at failure time.** The cron agent reconstructs context from serialized SQLite rows 30 minutes after the fact. The ADK callback system, VIGIL's reflective runtime, and PALADIN's runtime matching all operate with full context available. The 30-minute cron interval is not just a latency problem -- it is an information loss problem. Error objects, session state, REPL globals, and invocation context are all richer at failure time than their trace representations.

### 2. Framework Fight (flagged by ADK Expert + Vision Challenger)

The plan builds an external process (cron agent) that reimplements capabilities the ADK framework already provides hooks for. The ADK callback expert identified that `_classify_error`, `WorkerRetryPlugin`, and `SqliteTracingPlugin` already contain the building blocks. The vision challenger identified that the plan operates outside the ADK lifecycle, making it invisible to the interactive dashboard and disconnected from the skill promotion pipeline. Both critics point to the same root issue: the plan treats ADK as a black box to be monitored externally, rather than as an extensible framework to be enhanced from within.

### 3. Opacity vs. Transparency (flagged by Vision Challenger + ADK Expert)

The vision documents emphasize "Inventing on Principle" -- immediate feedback, direct manipulation, no hidden state. A background cron agent that silently retries failed runs is the antithesis of this philosophy. The ADK expert noted that `BasePlugin` callbacks provide natural integration points for surfacing retry decisions to the dashboard. The vision challenger noted that the plan conflicts with the interactive dashboard vision. Both point to the same fix: retry decisions should be visible and steerable, not autonomous and opaque.

---

## Prioritized Recommendations

### 1. Build a `FailureRecoveryPlugin` instead of a cron agent (ADK Expert + Vision Challenger)

**What to change:** Replace the external cron polling architecture with a `BasePlugin` that hooks into `after_agent_callback` (or `on_event_callback`) to detect failures at invocation time. The plugin writes a structured failure record (error class from `_classify_error`, context snapshot, parameter state, trace reference) to a recovery queue in SQLite or session state.

**Why:** Eliminates the 30-minute latency, preserves full context at failure time, keeps retry logic inside the ADK lifecycle (event tracking, state mutation rules, dashboard visibility), and avoids maintaining a separate cron process.

**Flagged by:** ADK Callback Expert (findings 1, 2, 3), Vision Challenger (dashboard alignment)

### 2. Study VIGIL and PALADIN before designing the recovery algorithm (Prior-Art Researcher)

**What to change:** Before implementing fix hypothesis generation, read VIGIL (arXiv 2512.07094) for the reflective supervision pattern (Roses/Buds/Thorns diagnosis) and PALADIN (arXiv 2509.25238) for taxonomy-guided recovery with retrieval-based matching. Both are 2025 papers with implementation details directly applicable to this problem.

**Why:** The proposed "classify error, generate fix hypothesis" pipeline is exactly what these papers formalize. PALADIN achieves 89.68% recovery rate using a retrieval-based approach that matches runtime failures to similar past recoveries -- which maps perfectly to RLM-ADK's existing trace infrastructure. Building without studying these risks reinventing a weaker version.

**Flagged by:** Prior-Art Researcher (capabilities 2, 3, 5)

### 3. Evaluate Temporal for durable execution before building custom retry infrastructure (Prior-Art Researcher)

**What to change:** Assess whether Temporal (or a similar durable execution engine) could replace the custom cron + SQLite polling + re-dispatch pipeline. Temporal provides automatic retry with configurable backoff, state persistence across crashes, and replay-based recovery -- all without custom code.

**Why:** The cron-based re-dispatch is essentially a hand-rolled durable execution system. Temporal is purpose-built for this and has a 2025 integration with the OpenAI Agents SDK. If the RLM-ADK runner could be wrapped in a Temporal Activity, the entire retry/recovery infrastructure comes for free. Even if Temporal is too heavy, understanding its model will improve the custom design.

**Flagged by:** Prior-Art Researcher (capabilities 1, 4)

### 4. Surface retry decisions in the NiceGUI dashboard with HITL controls (Vision Challenger)

**What to change:** Every proposed re-dispatch (whether from a plugin or a cron agent) should appear in the live dashboard with: the original failure trace, the classified error type, the generated fix hypothesis, and approve/reject/modify controls. Default to HITL approval for the first N retries until confidence in the fix hypothesis generator is established.

**Why:** The project's north star is "Inventing on Principle" -- immediate feedback and direct manipulation. A silent autonomous retry loop violates this principle. The dashboard already has the infrastructure (`LiveDashboardLoader`, `live_app.py`) to display trace data; adding a "retry queue" panel is incremental.

**Flagged by:** Vision Challenger (Interactive Dashboard alignment)

### 5. Connect successful recoveries to the skill promotion pipeline (Vision Challenger)

**What to change:** When a retry succeeds after parameter adjustment, capture the (error_class, original_params, adjusted_params, success) tuple as a recovery pattern. Feed it into the Draft/Promote Skill Factory (Architecture 2 from `codex_proposal_reframed.md`) so the system learns which parameter adjustments fix which error classes.

**Why:** Without this connection, the retry system is stateless -- it re-learns the same fixes every time. With it, the system evolves: common failure modes get pre-emptive parameter adjustments before they even occur. This closes the loop between the Continuous Runtime vision and the Dynamic Skill Loading vision.

**Flagged by:** Vision Challenger (Dynamic Skill Loading alignment)

### 6. Extend `_classify_error()` rather than building a new classifier (ADK Expert)

**What to change:** The existing `_classify_error()` in `dispatch.py` already handles 8 error categories. Extend it with additional categories relevant to the retry system (e.g., CONTEXT_OVERFLOW, TOPOLOGY_MISMATCH, SKILL_MISSING) rather than building a separate LLM-based classifier from cold traces.

**Why:** Classification at failure time has access to the full error object, HTTP status codes, response headers, and session state. Classification from SQLite traces has access only to what was serialized. The existing classifier is the right foundation; it just needs more categories.

**Flagged by:** ADK Callback Expert (finding 1)
