# Devil's Advocate Review: Add Step-Mode Plugin with Dashboard Async Gate

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

The plan already makes strong use of ADK's `BasePlugin` architecture. It correctly identifies `before_model_callback` as the right hook, correctly avoids returning an `LlmResponse` (which would short-circuit), and places `StepModePlugin` in registration order before `ObservabilityPlugin`. This is well-informed callback usage.

That said, several opportunities are under-utilized or carry hidden risk:

### A1. Missing `after_model_callback` for Step-Mode Timing Compensation

- **What the plan does now** -- The plan places `StepModePlugin` before `ObservabilityPlugin` to "preserve accurate timing." But it only implements `before_model_callback`. The pause duration is still included in the wall-clock time between `before_model_callback` and `after_model_callback` as measured by ObservabilityPlugin.
- **What ADK callback/plugin could replace it** -- `StepModePlugin` should also implement `after_model_callback` (or a paired timing mechanism). Before blocking, record `time.monotonic()`. After release, record elapsed pause time. Write `step:pause_duration_ms` to `callback_context.state`. ObservabilityPlugin (or a post-hoc analysis step) can then subtract pause duration from total model-call latency.
- **Benefit** -- Without this, every observability metric (per-iteration token breakdown timing, total execution time, child dispatch latency) will be polluted by human think-time whenever step mode is active. This makes step-mode runs useless for performance analysis -- the exact use case where you would want step-mode most (debugging slow runs).

### A2. `before_agent_callback` Could Provide Richer Pause Context Than Gate Metadata

- **What the plan does now** -- The plan writes `paused_agent_name` and `paused_depth` to the `StepGate` singleton's metadata fields before blocking in `before_model_callback`. This metadata is read by the dashboard poll loop.
- **What ADK callback/plugin could replace it** -- Implement `before_agent_callback` on `StepModePlugin` to capture richer context: the agent's current iteration count, the number of tools available, the contents of the last REPL result, and whether this is a reasoning agent vs. a worker. Write this to `callback_context.state` under `step:agent_context`. The `before_model_callback` then only needs to set `_waiting = True` and reference the already-populated context.
- **Benefit** -- Decouples "what are we about to pause" (agent-level context, captured in `before_agent_callback`) from "pause now" (model-level gate, in `before_model_callback`). The dashboard gets much richer status display without cramming everything into the gate primitive. This also follows the separation of concerns that `ObservabilityPlugin` already demonstrates between its `before_agent_callback` (records agent entry) and `before_model_callback` (records model timing).

### A3. `on_event_callback` Could Track Step-Mode Advance History

- **What the plan does now** -- The plan defines `STEP_MODE_ADVANCE_COUNT` as a state key but does not describe how it gets incremented. The `advance()` method on `StepGate` sets the event but does not write to ADK state.
- **What ADK callback/plugin could replace it** -- Implement `on_event_callback` on `StepModePlugin`. On each event, if the gate just transitioned from waiting to released, increment `STEP_MODE_ADVANCE_COUNT` via `callback_context.state`. This creates an auditable event-tracked record of every advance, visible in session replay and traces.
- **Benefit** -- Without this, the advance count lives only in the `StepGate` singleton (runtime memory). If the session is replayed or inspected post-hoc via `.adk/traces.db`, there is no record that step-mode was active or how many advances occurred. Event-tracked state mutation (per AR-CRIT-001) ensures the step-mode interaction history survives into observability artifacts.

### A4. `LongRunningFunctionTool` Is ADK's Native HITL Primitive -- Plan Ignores It

- **What the plan does now** -- The plan builds a custom `asyncio.Event` gate with a module-level singleton, manually wired between the plugin and the dashboard controller.
- **What ADK provides natively** -- ADK has [`LongRunningFunctionTool`](https://google.github.io/adk-docs/tools-custom/function-tools/) and `tool_context.request_confirmation()` as built-in HITL primitives. These use ADK's event system to pause execution and wait for external confirmation. There is also an open issue ([google/adk-python#3184](https://github.com/google/adk-python/issues/3184)) where HITL does not correctly pause in custom agent workflows -- the exact architecture RLM-ADK uses.
- **Why the plan's approach may still be correct** -- The native HITL primitives are tool-level (they pause before/after tool execution), not model-level (they don't pause before LLM calls). The plan explicitly wants model-call-granularity pausing. Additionally, issue #3184 confirms that ADK's native HITL has bugs with custom `_run_async_impl` agents -- exactly what `RLMOrchestratorAgent` is. So the custom gate is defensible.
- **Benefit of acknowledging this** -- The plan should explicitly document *why* it does not use `LongRunningFunctionTool` / `request_confirmation()`. Future maintainers (or ADK upgrades) may wonder why a custom gate exists when ADK has native HITL. A comment or doc note citing issue #3184 and the model-vs-tool granularity distinction would prevent someone from "fixing" this by switching to the native primitive and breaking it.

### A5. Plugin Ordering Risk: WorkerRetryPlugin Interaction

- **What the plan does now** -- The plan correctly notes that BUG-13 (WorkerRetryPlugin's `set_model_response` causing premature worker termination) is unrelated because StepModePlugin never returns an `LlmResponse`. However, it does not address plugin execution ordering between `StepModePlugin` and `WorkerRetryPlugin`.
- **What could go wrong** -- `WorkerRetryPlugin` also implements `before_model_callback` (inherited from `ReflectAndRetryToolPlugin`). If `StepModePlugin` is registered first (as the plan specifies), it blocks in `before_model_callback`. While blocked, no other plugin's `before_model_callback` runs (ADK executes them sequentially). This means `WorkerRetryPlugin` cannot prepare schema validation state until after the step-mode pause releases. This is likely harmless but should be explicitly verified: does `WorkerRetryPlugin.before_model_callback` depend on timing-sensitive state that could go stale during a long pause?
- **Benefit** -- Explicit ordering analysis prevents a subtle timing bug where schema validation state prepared before a multi-minute human pause becomes invalid by the time the model call actually fires.

**Confidence rating:** Moderate improvement. The plan's core callback usage is sound. A1 (timing compensation) and A3 (event-tracked advance history) are the highest-impact additions. A4 (documenting why not native HITL) is important for maintainability. A2 and A5 are polish.

---

## Vision Alignment Assessment

| Vision Area | Alignment | Assessment |
|-------------|-----------|------------|
| Polya Topology | Neutral | Step-mode does not advance or conflict with the Polya topology engine; it operates at a lower abstraction layer (runtime control, not reasoning structure). |
| Dynamic Skill Loading | Neutral | Step-mode does not produce artifacts that feed into the skill promotion pipeline, nor does it consume skills. |
| Continuous Runtime | Neutral | Step-mode is explicitly scoped to in-process dashboard runs, not autonomous cron-triggered agents. No conflict, but no advancement either. |
| Interactive Dashboard | **Advances** | This is a direct implementation of HITL Async Gates from `interactive_dashboard.md` (lines 169-186) and the "pause at checkpoint" primitive from the studio shell requirements. |

### V1. Step-Mode Is the First Write-Path -- Treat It as the Studio Shell Beachhead

The interactive dashboard vision document (`rlm_adk_docs/vision/inventing_on_principle_dashboard/interactive_dashboard.md`) calls for a "second NiceGUI runtime shell" with four primitives: control plane, live object handles, UI bridge, and async HITL gates. The step-mode plan implements only the fourth primitive (async HITL gates). The plan should explicitly position itself as the beachhead for the studio shell architecture, not just a standalone debugging feature.

Concretely: the `StepGate` singleton API should be designed as the first member of a `rlm_adk/studio/` package (or at minimum, a `rlm_adk/control_plane.py` module) rather than a standalone `rlm_adk/step_gate.py`. This makes it architecturally clear that step-mode is the first control-plane primitive, and future primitives (prompt override, skill selection changes, context masking) will be siblings, not ad-hoc additions.

### V2. Missing "Edit Then Resume" -- Step-Mode Could Enable State Mutation at Pause Points

The vision document lists four HITL primitives: approve/reject, **edit then resume**, choose among branches, and pause at checkpoint. The step-mode plan implements "pause at checkpoint" but misses "edit then resume." When the agent is paused at a step-mode gate, the user can currently only click "Next Step" (approve) or toggle off (reject/skip). There is no mechanism to modify state before resuming.

Adding even a minimal state-edit capability at the pause point (e.g., a text input that writes to `callback_context.state` before releasing the gate) would cover two of four vision primitives instead of one. This turns step-mode from "debugger stepping" into "interactive steering" -- a much closer match to the Bret Victor "direct manipulation" philosophy.

### V3. Step-Mode Runs Should Feed Into Dynamic Skill Loading as High-Quality Training Data

The dynamic skill loading vision (`rlm_adk_docs/vision/dynamic_skill_loading/dynamic_skill_loading.md`) calls for embedding every REPL execution into a vector store with metadata including "execution outcome" and "task context." A step-mode run where a human actively inspected and approved each model call is a significantly higher-quality training signal than an unsupervised run. The plan should add a `step:human_verified` flag to the session state (or to the REPL trace metadata) so that the future skill promotion pipeline can weight step-mode runs more heavily.

This is a one-line addition that creates a bridge between two vision areas (Interactive Dashboard and Dynamic Skill Loading) that are currently treated as independent.

### V4. The Provider-Fake Fixture Launcher Advances Dashboard Vision but Risks Architectural Drift

Step 4 of the plan (provider-fake fixture drop-down) adds a second launch path to the dashboard alongside replay fixtures. This advances the dashboard vision by making more of the test infrastructure accessible from the UI. However, the vision document warns against "stretching the current trace-reader dashboard into a live co-resident studio" (line 17). The fixture launcher is fine as an incremental step, but it should be clearly labeled as a "debug/test" panel, not confused with the future studio shell's control plane. The `_launch_panel()` in `live_app.py` is already getting crowded (replay drop-down, skill multi-select, and now provider-fake drop-down). Consider grouping these under a collapsible "Test Launches" section to keep the UI organized and architecturally honest.

### V5. Step-Mode Should Record "Why I Paused Here" to Support Future Topology Learning

The Polya topology engine and the capture-mode meta-orchestration (from the codex proposal reframed) both need signal about which steps in a workflow are decision-critical. A step-mode pause is exactly that signal: the human chose to inspect at this point because something was uncertain or interesting. If step-mode logged not just *that* a pause occurred but also an optional annotation ("why did you pause?"), that becomes valuable training data for the topology engine's invariant-finding step. Even without the annotation, the bare fact of "human paused before model call N at depth D" is a useful feature for the topology extractor.

**Overall verdict:** This plan is **well-aligned** with the project vision because it directly implements the HITL async gate primitive that the interactive dashboard vision document explicitly calls for. It is the first write-path from the dashboard into the agent runtime, which is a significant milestone. The main missed opportunities are treating it as a standalone feature rather than the first control-plane primitive (V1), and not bridging it to dynamic skill loading (V3). Neither of these is a flaw -- they are opportunities to get more strategic value from the same implementation effort.

---

## Prior Art Findings

### P1. Agent Execution Step-Mode / Interactive Debugger

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| arXiv | [AgentStepper (arXiv 2602.06593)](https://arxiv.org/html/2602.06593v1) | Interactive debugger for software dev agents with pause/step/run states and breakpoints at LLM and tool interaction boundaries | **High** | Study design; different runtime (not ADK), but the state-machine model (paused/stepping/running) is directly applicable |
| arXiv | [Interactive Debugging and Steering of Multi-Agent AI Systems (arXiv 2503.02068)](https://arxiv.org/html/2503.02068v1) | Fine-grained conversation control with ability to pause execution and send messages to particular agents mid-conversation | **High** | Covers "edit then resume" (V2) that the plan misses |
| GitHub | [elizaOS/agentloop](https://github.com/elizaOS/agentloop) | Lightweight agent loop with pause/unpause/step functions and keyboard listener for stepping | **Medium** | Simple reference implementation; TypeScript, but the API shape (pause, unpause, step) maps cleanly to StepGate |
| GitHub | [humanlayer/12-factor-agents, Factor 6](https://github.com/humanlayer/12-factor-agents/blob/main/content/factor-06-launch-pause-resume.md) | Design pattern document: "Launch, Pause, Resume" as a first-class agent architecture principle | **Medium** | Validates the architectural pattern; useful for documentation |
| PDF | [LADYBUG (EDBT 2025)](https://openproceedings.org/2025/conf/edbt/paper-313.pdf) | Framework for tracing, modifying, and re-executing intermediate steps of LLM agents | **Medium** | Covers re-execution after modification, relevant to V2 |

**AgentStepper** is the most directly relevant prior art. It introduces a three-state model (paused, stepping, running) that maps almost exactly to the plan's design: step_mode_enabled=True + waiting=True is "paused," step_mode_enabled=True + waiting=False is "stepping," and step_mode_enabled=False is "running." The plan could adopt this explicit state-machine vocabulary for clarity.

AgentStepper also structures agent trajectories into interleaved LLM-conversations and tool-conversations, which provides a richer debugging view than the plan's "paused agent name + depth" status indicator. However, AgentStepper targets general software development agents, not ADK specifically, so its implementation cannot be reused directly.

### P2. HITL Interrupt / Checkpoint Primitives

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| LangGraph | [LangGraph interrupt()](https://docs.langchain.com/oss/python/langgraph/interrupts) | `interrupt()` function pauses graph execution at any node, saves state via checkpointer, resumes with `Command(resume=value)` | **High** | Mature, production-tested HITL primitive; different framework but same concept |
| ADK (native) | [google/adk-python#3184](https://github.com/google/adk-python/issues/3184) | Reports that ADK's native HITL (`request_confirmation`) does not correctly pause in custom agent workflows | **High** | Confirms plan's decision to build custom gate; cite this explicitly |
| ADK (native) | [google/adk-python#1797](https://github.com/google/adk-python/issues/1797) | Feature request for proper human-in-the-loop event support in ADK | **Medium** | Track this; if ADK ships native HITL for plugins, the custom gate becomes tech debt |
| GitHub | [debugmcp/mcp-debugger](https://github.com/debugmcp/mcp-debugger) | MCP server providing step-through debugging with breakpoints for LLM agents | **Low** | Different paradigm (MCP protocol); not directly usable |

LangGraph's `interrupt()` is the most mature prior art for HITL pausing. Key design decisions the plan could learn from:
- LangGraph saves full graph state at the interrupt point, enabling "resume from checkpoint" even after process restart. The plan's `asyncio.Event` gate is in-memory only -- if the process dies during a pause, the run is lost. This is acceptable for the plan's scoped use case (in-process dashboard runs only), but worth documenting as a known limitation.
- LangGraph's `Command(resume=value)` pattern passes data back into the interrupted node. The plan's `advance()` passes no data -- it is a bare signal. This limits step-mode to "go/no-go" and prevents the "edit then resume" pattern (V2).

### P3. Dashboard + Agent Real-Time Control UI

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| LangSmith | [Debugging Deep Agents (blog.langchain.com)](https://blog.langchain.com/debugging-deep-agents-with-langsmith/) | LangSmith + Polly for trace analysis and agent debugging via chat interface | **Low** | Post-hoc debugging, not real-time stepping; different approach |
| Braintrust | [5 Best LLM Monitoring Tools 2026](https://www.braintrust.dev/articles/best-llm-monitoring-tools-2026) | Survey of monitoring tools (LangSmith, Braintrust, Arize, etc.) | **Low** | None offer real-time step-mode; validates novelty |
| NiceGUI | [NiceGUI Documentation](https://nicegui.io/documentation) | Python UI framework with same-process backend, full async support | **N/A** | Already in use; confirms `asyncio.Event` sharing is architecturally sound |

No existing tool provides a NiceGUI-based step-mode debugger for ADK agents. The closest equivalent is LangSmith's trace viewer, but that is post-hoc, not real-time. The plan's approach of building step-mode directly into the existing NiceGUI dashboard is genuinely novel for the ADK ecosystem.

### P4. Provider-Fake Fixture Execution from Dashboard UI

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| (none found) | -- | -- | -- | Build from scratch |

No prior art was found for launching deterministic provider-fake test fixtures from a dashboard UI. This is a novel capability specific to RLM-ADK's testing infrastructure. The closest analog is LangSmith's "playground" for re-running traces, but that uses real LLM calls, not deterministic fakes.

### P5. Async Gate / Signaling Primitive for Agent Coordination

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| Python stdlib | [asyncio.Event](https://docs.python.org/3/library/asyncio-sync.html#asyncio.Event) | Built-in async signaling primitive; set/wait/clear | **High** | Plan already uses this correctly |
| GitHub | [AgentScope (arXiv 2508.16279)](https://arxiv.org/html/2508.16279v1) | "Real-time steering by gracefully pausing the ongoing ReAct loop upon receiving an external interruption signal" | **Medium** | Similar concept; uses external signal to pause agent loop |

The plan's use of `asyncio.Event` as the core signaling primitive is the standard approach. No framework provides a better primitive for in-process async coordination. The plan's wrapper (`StepGate`) adds the right metadata (agent name, depth, waiting state) that raw `asyncio.Event` lacks.

**Summary:** 2 of 5 planned capabilities have substantial prior art (P1: step-mode debugging pattern via AgentStepper; P2: HITL interrupt via LangGraph). 1 capability validates the plan's approach while confirming a framework bug (P2: ADK native HITL is broken for custom agents). 2 capabilities are genuinely novel (P3: NiceGUI-based real-time step-mode dashboard; P4: provider-fake fixture launcher from UI). The signaling primitive (P5) is standard library usage.

---

## Cross-Cutting Themes

### X1. Timing and Observability Pollution from Human Pause Duration (flagged by: A1, V4)

Both the ADK callback analysis (A1) and the vision alignment review (V4) converge on the same problem: step-mode introduces human think-time into execution metrics. The ADK expert identified that `ObservabilityPlugin`'s timing will include pause duration; the vision challenger noted that step-mode runs need to be distinguishable from normal runs for the skill promotion pipeline. This is a high-confidence issue because two independent critics identified it from different angles. The fix is straightforward: record pause duration in state (A1) and tag the session as human-verified (V3).

### X2. "Pause and Inspect" Is Insufficient -- "Pause, Edit, Resume" Is the Real Vision Target (flagged by: V2, P1, P2)

The vision alignment critic (V2) identified that the plan implements only 1 of 4 HITL primitives (pause at checkpoint) while missing "edit then resume." The prior-art researcher found that both AgentStepper (P1) and LangGraph interrupts (P2) support passing data back into the paused execution. The convergence is clear: the industry has moved beyond "go/no-go stepping" toward "interactive steering at pause points." The plan's `advance()` method takes no arguments, which architecturally prevents this. Designing `advance(resume_data: dict | None = None)` from the start would future-proof the gate for V2 without requiring a breaking API change later.

### X3. ADK Native HITL Is Broken for This Use Case -- Document Why (flagged by: A4, P2)

The ADK callback expert (A4) flagged that ADK has native HITL primitives (`LongRunningFunctionTool`, `request_confirmation`). The prior-art researcher (P2) found ADK issue #3184 confirming these primitives do not work with custom `_run_async_impl` agents. Both critics agree the custom gate is the right approach, but both also agree it needs explicit documentation explaining *why* the native path was rejected. This prevents a future maintainer from "upgrading" to the native primitive and reintroducing the bug.

### X4. Module Placement Signals Architectural Intent (flagged by: V1, P3)

The vision critic (V1) argued that `rlm_adk/step_gate.py` should be in a `studio/` or `control_plane/` package to signal its role as the first control-plane primitive. The prior-art researcher (P3) found no existing NiceGUI-based agent control dashboard, confirming this is genuinely novel. Together, these findings suggest the module placement decision carries more weight than usual: it sets the precedent for where future control-plane primitives live. A flat `step_gate.py` in the package root communicates "one-off feature"; a `rlm_adk/studio/gate.py` communicates "first primitive in a planned system."

---

## Prioritized Recommendations

### R1. Add Pause-Duration Tracking to Prevent Observability Corruption

**Traces to:** A1, X1, V3

Record `time.monotonic()` before and after each `wait_for_advance()` call. Write the pause duration to `callback_context.state["step:pause_duration_ms"]`. Also write a `step:human_verified` boolean to session state so that observability pipelines and the future skill promotion pipeline can distinguish step-mode runs from autonomous runs. This is the highest-impact change because without it, every metric from every step-mode run is unreliable, and the plan's primary purpose (debugging via stepping) is undermined by corrupt timing data.

### R2. Design `advance()` to Accept Optional Resume Data

**Traces to:** V2, X2, P1, P2

Change the `StepGate.advance()` signature to `advance(resume_data: dict | None = None)`. Store the resume data on the gate so that `wait_for_advance()` can return it. This does not require implementing the full "edit then resume" dashboard UI now -- it just ensures the gate API does not need a breaking change when that capability is added. Both AgentStepper and LangGraph's `Command(resume=value)` demonstrate that passing data back at resume time is essential for production HITL. The cost is minimal (one optional parameter + one attribute); the benefit is avoiding a future API redesign.

### R3. Document Why Native ADK HITL Is Not Used

**Traces to:** A4, X3, P2

Add a comment block in `StepModePlugin` and a note in the plan's "Considerations" section explicitly citing ADK issue #3184 (custom agent HITL broken) and the model-vs-tool granularity distinction. Also add a tracking note: if ADK issue #1797 (native HITL event support) ships, re-evaluate whether the custom gate can be replaced. This costs nothing but prevents a future "why don't we just use the native thing" refactor that would break step-mode.

### R4. Place StepGate in a Studio/Control-Plane Package

**Traces to:** V1, X4

Create `rlm_adk/studio/__init__.py` and `rlm_adk/studio/gate.py` instead of `rlm_adk/step_gate.py`. The module-level singleton import path becomes `from rlm_adk.studio.gate import step_gate`. This signals that the gate is the first member of the studio shell's control plane, not a standalone utility. Future primitives (prompt override signals, context masking, state-edit-at-pause) will be siblings in the same package. The vision document explicitly calls for "explicit runtime plumbing, not an ad hoc collection of UI hacks" -- package placement is the cheapest way to enforce that principle.

### R5. Add `before_agent_callback` for Richer Pause Context

**Traces to:** A2

Implement `before_agent_callback` on `StepModePlugin` to capture agent-level context (iteration count, agent type, last REPL result summary) before `before_model_callback` fires. Write this to `callback_context.state["step:agent_context"]`. The dashboard can then display richer status than just "Paused: reasoning_agent @ depth 0" -- for example, "Paused: reasoning_agent @ depth 0, iteration 3, last REPL: 'loaded 450 files'". This makes step-mode significantly more useful for debugging without changing the gate primitive.

### R6. Verify WorkerRetryPlugin Interaction Under Long Pauses

**Traces to:** A5

Write a targeted test: enable step-mode, run a provider-fake fixture that triggers schema validation retries, pause for a simulated long duration (e.g., asyncio.sleep(5) replacing human interaction), then advance and verify that WorkerRetryPlugin's schema validation still works correctly. This test can be part of the TDD sequence (between steps 11 and 12 in the plan). If the interaction is clean (likely), the test serves as a regression guard. If it is not, it catches a subtle timing bug before it reaches production.

### R7. Group Dashboard Launch UI Under Collapsible Test Section

**Traces to:** V4

As the fixture drop-down (Step 4) is added, wrap the replay fixture drop-down, provider-fake fixture drop-down, and associated launch controls in a collapsible `ui.expansion("Test Launches")` container. This keeps the launch panel organized as it grows and architecturally separates "test infrastructure" from the future "studio control plane" that the vision document calls for. Without this, the `_launch_panel()` method will become an undifferentiated list of controls that blurs the line between debugging tools and production steering -- exactly the "ad hoc collection of UI hacks" the vision warns against.
