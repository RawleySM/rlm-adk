# Devil's Advocate Review: Add Step-Mode Plugin with Dashboard Async Gate

## ADK Callback Opportunities

After reviewing the plan against the comprehensive ADK callback documentation (`ai_docs/adk_callbacks.md`) and the current plugin stack in `rlm_adk/agent.py`, here are the findings:

### 1. The plan correctly chooses `BasePlugin` with `before_model_callback` -- no under-utilization there

**What the plan does:** Implements `StepModePlugin(BasePlugin)` with a `before_model_callback` that awaits an async gate.

**Assessment:** This is the right callback choice. The plan explicitly considered `before_tool_callback` and rejected it with sound reasoning (user wants to pause before model calls, not tool executions). The plan also correctly identifies that `BasePlugin` provides global scope across all agents, including parallel workers -- which is essential since per-agent `before_model_callback` on `LlmAgent` would miss workers created dynamically in `dispatch.py`.

**Verdict:** No callback under-utilization. Well-designed.

### 2. Missing `after_model_callback` for step-mode observability enrichment

**What the plan does:** Only implements `before_model_callback`. There is no `after_model_callback`.

**What ADK could provide:** An `after_model_callback` on the same plugin could capture the model's response immediately after the pause-and-advance cycle, enabling the dashboard to show **what the model decided** at each step -- not just that a step happened. This would let the step-mode UI display a "just completed" summary (e.g., "Model requested execute_code with 15 lines of Python" or "Model produced final answer") alongside the "now paused before next call" indicator.

**Benefit:** Richer step-mode debugging experience. The current plan gives you pause/advance but no "what just happened" feedback between steps. An `after_model_callback` writing to the gate's metadata (e.g., `last_model_action: str`) would close this gap with ~10 lines of code. The `ObservabilityPlugin` already demonstrates this pattern at line 168 of `observability.py`.

**Impact:** Moderate improvement.

### 3. Missing `before_agent_callback` for conditional step-mode scoping

**What the plan does:** The gate fires for **every** agent's model call globally -- reasoning agent, every worker in a parallel batch, any future sub-agents.

**What ADK could provide:** A `before_agent_callback` on the same plugin could implement **selective step-mode scoping** -- e.g., "only step through the reasoning agent, let workers run freely" or "only step through depth-0 agents." Per the ADK docs, `before_agent_callback` fires once per agent invocation and receives the agent instance and `CallbackContext`, which includes depth information. The plugin could use this to set a thread-local or gate-level flag that `before_model_callback` checks before deciding to await.

**Benefit:** Finer-grained control. Stepping through 8 workers one-by-one in a batch dispatch may be useful sometimes but tedious at other times. A scope selector on the dashboard ("Step: all agents / reasoning only / depth 0 only") would make step-mode dramatically more usable for different debugging scenarios. This is a natural extension point the plan does not mention.

**Impact:** Moderate improvement.

### 4. `on_event_callback` could track step-mode audit trail without manual state management

**What the plan does:** Defines state keys `STEP_MODE_ADVANCE_COUNT`, `STEP_MODE_PAUSED_AGENT`, `STEP_MODE_PAUSED_DEPTH` in `state.py`, and the plan implies these are managed manually in the plugin.

**What ADK could provide:** `BasePlugin.on_event_callback` fires for every event in the session. The plugin could use this hook to automatically build an audit trail of step-mode interactions (which agents were paused, how long each pause lasted, which advance freed which agent) as structured event metadata, rather than relying on the plugin to manually write state keys from `before_model_callback`. This would produce a replayable step-mode timeline automatically.

**Benefit:** Better separation of concerns. The pause logic stays in `before_model_callback`; the audit/history logic lives in `on_event_callback`. This also means step-mode history survives in the event stream and is visible in `traces.db` without additional wiring.

**Impact:** Minor polish -- the manual approach works, but the event-driven approach is more ADK-idiomatic.

### 5. Plugin ordering concern is correctly identified but incompletely resolved

**What the plan does:** States `StepModePlugin` should be registered **before** `ObservabilityPlugin` so pause duration does not skew timing metrics.

**Assessment:** This is correct and important. However, the plan does not address the interaction with `DashboardAutoLaunchPlugin`, which is currently first in the list (line 418 of `agent.py`). If `DashboardAutoLaunchPlugin` has any `before_model_callback`, the ordering matters there too. Additionally, the plan should explicitly document that `StepModePlugin` must come **after** any request-modifying plugins (there are none currently, but future plugins that modify `LlmRequest` in `before_model_callback` should run before the pause, so the paused state shows the final request). The ADK docs state: "Plugin and Agent Callbacks are executed sequentially, with Plugins taking precedence... modifications will be visible and passed to the next callback in the chain."

**Impact:** Minor polish -- the plan is on the right track but should specify exact insertion index.

### Overall Callback Confidence Rating: **Minor polish**

The plan already makes excellent use of the callback system. The core architecture decision (BasePlugin + before_model_callback + asyncio.Event gate) is correct and well-reasoned. The opportunities above are enhancements, not restructuring.

---

## Vision Alignment Assessment

After reading all 12 vision documents across the four vision areas, here is the alignment evaluation:

| Vision Area | Alignment | Assessment |
|-------------|-----------|------------|
| Polya Topology | Neutral | Step-mode does not advance or conflict with topology selection; it is orthogonal infrastructure that could eventually help debug topology execution, but the plan does not connect to topology concepts. |
| Dynamic Skill Loading | Neutral | Step-mode does not contribute to REPL embedding, skill promotion, or workflow capture; however, it does not block these features either. |
| Continuous Runtime | Neutral-to-Conflicts | Step-mode is inherently interactive (human in the loop), which is the opposite of autonomous cron-triggered agents. The module-level singleton pattern makes the gate process-global, which could interfere with headless autonomous runs if not carefully scoped. |
| Interactive Dashboard | **Advances** | This plan is a direct, concrete implementation of the "HITL Async Gates" described in `interactive_dashboard.md` (lines 169-186). It is the first write-path from the dashboard into the agent runtime, which the vision doc explicitly calls for. |

### Specific Recommendations for Tighter Alignment

**1. Connect step-mode to Polya topology debugging (missed opportunity).**
The vision calls for the agent to "optimize its own topology" based on phase outcomes (`evolution_principles.md`). Step-mode could be the tool that lets the user observe topology decisions in real time. The plan should at minimum note that step-mode pauses at model calls will naturally expose Polya phase transitions (REFRAME -> PROBE -> SYNTHESIZE) when running polya_understand skills, making step-mode a topology debugging tool. This connection is free -- it just needs to be documented as a use case.

**2. Guard against continuous runtime interference.**
The `autonomous_self_improvement.md` vision describes cron-triggered agents running in headless mode. The `StepGate` module-level singleton is process-global. If a future autonomous agent runs in the same process as the dashboard (which the vision implies -- same kernel, different shells per `interactive_dashboard.md`), the gate must be scoped to specific runner invocations, not process-global. The plan says "in-process only, no cross-process mode" but does not address the multi-runner-same-process scenario that the continuous runtime vision implies. **Recommendation:** Add a `runner_id` or `invocation_id` scope to the gate, or make the gate instance per-runner rather than per-module.

**3. The provider-fake fixture launcher (Step 4) is a significant enabler for multiple vision areas but is underscoped.**
The plan adds a fixture dropdown for provider-fake fixtures in the dashboard. This is a powerful primitive that serves not just step-mode testing but also: (a) topology comparison (run different Polya topologies as fixtures, compare in dashboard), (b) skill validation (run skill-generated fixtures to validate promoted skills), (c) regression testing from the dashboard. The plan treats it as a step-mode prerequisite. It should be elevated to a first-class dashboard capability with its own scope and design attention, because it serves the broader vision.

**4. The "second NiceGUI runtime shell" architecture is correctly followed.**
The plan operates within the existing dashboard shell, adds controls to the existing `live_app.py`, and shares the kernel's plugin stack. This is exactly what `interactive_dashboard.md` calls for. The step-mode toggle is a control plane primitive, and the gate is an async HITL primitive -- both listed as studio shell requirements.

**5. The plan correctly identifies this as the "first HITL write-path."**
The vision doc (`interactive_dashboard.md` lines 169-186) lists approve/reject, edit-then-resume, choose-among-branches, and pause-at-checkpoint as target HITL primitives. Step-mode implements "pause at checkpoint." The plan should explicitly note which remaining HITL primitives it lays groundwork for and which will require additional gate types. For example, "approve/reject" would need a `before_tool_callback` gate (not `before_model_callback`), and "edit then resume" would need request mutation in the gate. Naming these next steps would strengthen the plan's vision alignment.

### Overall Verdict

**This plan is well-aligned with the Interactive Dashboard vision area and neutral toward the other three vision areas.** It is the correct first step for HITL infrastructure. The main risk is that the module-level singleton design may conflict with the continuous runtime vision if not scoped to specific runner invocations. The missed opportunity is connecting step-mode explicitly to Polya topology debugging, which would advance alignment with the topology vision at zero additional implementation cost.

---

## Prior Art Findings

### Core Capabilities Extracted from the Plan

1. **Step-mode async gate** -- An `asyncio.Event`-based synchronization primitive that pauses agent execution at model call boundaries, allowing a human to advance one step at a time.
2. **Global plugin for model-call interception** -- A framework plugin that intercepts all model calls across all agents (including parallel workers) to inject pause behavior.
3. **Dashboard step-mode UI controls** -- Toggle switch, advance button, and status indicator in a NiceGUI dashboard for controlling and visualizing step-mode state.
4. **In-process fixture launcher** -- A dashboard dropdown that selects and runs provider-fake test fixtures in-process with the full plugin stack, sharing runtime primitives (like the gate) with the dashboard.

### Capability 1: Step-Mode Async Gate

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| LangGraph `interrupt_before` | [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) | Pauses graph execution at specified nodes using static breakpoints (`interrupt_before`/`interrupt_after`). Supports resumption via `Command`. Requires a checkpointer for state persistence. | **High** | Study the API design, but **build from scratch** -- LangGraph's interrupt system is graph-node-oriented (pause before a node), not model-call-oriented (pause before any LLM invocation). Different granularity. Also, LangGraph is a separate framework; the ADK plugin system is the correct integration point for this codebase. |
| AgentStepper (arXiv 2602.06593) | [AgentStepper Paper](https://arxiv.org/abs/2602.06593) | Interactive debugger for software dev agents with breakpoints, stepwise execution, live editing of prompts/tool invocations at breakpoints. Supports paused/stepping/running states. 39-42 lines of integration code. | **High** | **Study carefully before building.** AgentStepper's design is the closest prior art to this plan. Key ideas to borrow: (1) distinct paused/stepping/running execution states (the plan only has on/off), (2) ability to edit the LLM request at a breakpoint before advancing (the plan only delays, never modifies), (3) post-hoc trajectory replay mode alongside live stepping. AgentStepper targets SWE-Agent/RepairAgent, not Google ADK, so direct code reuse is unlikely, but the UX design is highly relevant. |
| AutoGen `asyncio.Event` HITL pattern | [AutoGen Discussion #5324](https://github.com/microsoft/autogen/discussions/5324) | Uses `asyncio.Event` to pause `UserProxyAgent` execution and wait for UI input via a separate coroutine. Exactly the same synchronization primitive as the plan. | **Medium** | **Validate pattern.** The plan's `StepGate` implementation is essentially the same pattern. This confirms the `asyncio.Event` approach is established. However, AutoGen's version is per-agent (UserProxyAgent), not global-plugin-level. The plan's global approach is better for this codebase. |
| Open WebUI HITL approval | [Open WebUI Discussion #16701](https://github.com/open-webui/open-webui/discussions/16701) | Generates unique approval IDs and creates `asyncio.Event` objects to pause specific tool executions until user approval. | **Medium** | **Adapt pattern.** The approval-ID-per-pause concept could improve the plan's gate design. Currently, the plan's gate is a single `asyncio.Event` that serializes all pauses. Open WebUI's per-pause-ID approach would allow independent pausing of parallel workers. See Cross-Cutting Theme #1. |
| Google ADK `before_model_callback` example | [ADK Docs Example](https://github.com/google/adk-docs/blob/main/examples/python/snippets/callbacks/before_model_callback.py) | Official ADK example showing how to inspect and modify LLM requests in `before_model_callback`. Does not implement stepping/pausing but confirms the callback signature and return semantics. | **Low** | **Use as-is** for callback signature reference. The plan already references this correctly. |

### Capability 2: Global Plugin for Model-Call Interception

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| ADK `BasePlugin` architecture | [ADK Plugins Docs](https://github.com/google/adk-docs/blob/main/docs/plugins/index.md) | Documents the plugin callback lifecycle, execution order, short-circuit semantics, and change propagation. Plugins fire globally for all agents in the runner. | **High** | **Use as-is.** The plan correctly leverages this architecture. No reinvention here. |
| ADK Plugin callback invocation issue #4464 | [ADK Issue #4464](https://github.com/google/adk-python/issues/4464) | Reports that plugin callbacks are not invoked by `InMemoryRunner`. | **Low (but important risk)** | **Verify.** If the dashboard's fixture launcher uses `InMemoryRunner` (which it should not per project convention), plugin callbacks will not fire. The plan says to use full `create_rlm_runner()` with real services, which is correct. But this issue is worth noting as a known ADK footgun. |

### Capability 3: Dashboard Step-Mode UI Controls

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| LangGraph Studio | [LangGraph Studio](https://github.com/changegc/langgraph-studio2) | Desktop app for prototyping and debugging LangGraph applications with visual breakpoints, state inspection, and step-through execution. | **High** | **Study UX, build from scratch.** LangGraph Studio is a standalone Electron app, not a NiceGUI component. But its UX patterns (visual breakpoint markers, state diff between steps, timeline scrubber) are directly relevant to the dashboard step-mode UI design. The plan's "paused agent name + depth" indicator is minimal compared to Studio's rich visualization. |
| AgentStepper UI | [AgentStepper](https://arxiv.org/html/2602.06593v1) | Provides a web-based debugging interface with execution state visualization, breakpoint management, prompt editing, and repository diff display at each step. | **High** | **Study UX.** The plan's dashboard controls (toggle + button + label) are a minimal viable version of what AgentStepper provides. Consider the plan as MVP and AgentStepper as the north star for future iteration. |
| NiceGUI Dashboard Template | [nicegui_dashboard](https://github.com/s71m/nicegui_dashboard) | Generic NiceGUI dashboard template with module reloading. | **Low** | **Not directly useful.** The existing `live_app.py` is already more sophisticated. |

### Capability 4: In-Process Fixture Launcher

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| No direct prior art found | -- | No existing tool combines a NiceGUI dashboard dropdown with in-process provider-fake fixture execution for an ADK agent. | **None** | **Build from scratch.** This is genuinely novel. The combination of (a) provider-fake fixture selection UI, (b) in-process runner creation with full plugin stack, and (c) shared singleton gate for step-mode is specific to this codebase's architecture. The plan's design for `list_provider_fake_fixtures()` following the `list_replay_fixtures()` pattern is clean. |

### Summary

**3 of 4 planned capabilities have substantial prior art that should inform design, but none can be directly reused as libraries.** The `asyncio.Event` gate pattern is well-established (AutoGen, Open WebUI). The step-mode debugging UX has strong prior art in AgentStepper and LangGraph Studio. The global plugin approach is native ADK and correctly leveraged. The in-process fixture launcher is genuinely novel.

**What the plan could adopt:**
- AgentStepper's three execution states (paused/stepping/running) instead of binary on/off
- AgentStepper's prompt-editing-at-breakpoint capability as a future extension
- Open WebUI's per-pause-ID pattern for better parallel worker handling
- LangGraph Studio's state-diff-between-steps UX as a design reference

**What still needs custom development:** All of it. The prior art exists in different frameworks with different plugin architectures. The ADK `BasePlugin` + `asyncio.Event` + NiceGUI integration is specific to this codebase.

---

## Cross-Cutting Themes

### Theme 1: The single-Event gate design will serialize parallel worker pauses (flagged by Callback Expert + Prior-Art Researcher)

The callback expert noted that the gate fires for every worker's model call individually. The prior-art researcher found that Open WebUI uses per-pause-ID events for independent pausing. The plan's current design uses a single `asyncio.Event`, which means when multiple workers in a `ParallelAgent` batch hit the gate simultaneously, they will serialize: worker 1 pauses -> advance -> worker 1 continues -> worker 2 pauses -> advance -> etc. This is because `asyncio.Event.clear()` in `wait_for_advance()` clears the event for all waiters.

**The problem:** If 8 workers hit the gate at roughly the same time, only one will be "paused" at a time. The others will either: (a) queue up waiting on the cleared event (but `event.set()` releases ALL waiters simultaneously, not just one), or (b) the implementation needs to re-clear the event after each advance, creating a one-at-a-time stepping pattern.

**The `asyncio.Event` semantics issue:** `asyncio.Event.set()` wakes ALL coroutines waiting on `event.wait()`. So if 8 workers are all awaiting the same event, a single `advance()` call releases ALL 8 simultaneously, not just one. To get one-at-a-time stepping, you need either an `asyncio.Semaphore`, an `asyncio.Queue`, or per-waiter events. The plan's described API (`advance()` releases "one blocked waiter") does not match `asyncio.Event` semantics.

**This is a real design bug in the plan that needs resolution before implementation.**

### Theme 2: Step-mode is the first of several HITL primitives; the gate abstraction should be designed for extensibility (flagged by Vision Challenger + Callback Expert)

The vision doc lists four HITL primitives: approve/reject, edit-then-resume, choose-among-branches, pause-at-checkpoint. AgentStepper implements all four. The plan implements only pause-at-checkpoint. The callback expert noted that `before_tool_callback` would serve approve/reject, and request mutation in the gate would serve edit-then-resume.

**Recommendation:** Design the `StepGate` interface to accommodate future HITL gate types. For example, instead of a single `StepGate` class, consider a `HITLGate` base class with `StepGate`, `ApprovalGate`, and `EditGate` subclasses. Or at minimum, design `wait_for_advance()` to return an optional payload (the user's edit or approval decision) rather than returning `None`.

### Theme 3: The module-level singleton pattern creates two forward-compatibility risks (flagged by Vision Challenger + Callback Expert)

1. **Multi-runner conflict:** If the continuous runtime vision puts autonomous agents and interactive dashboard in the same process, they share the gate singleton. An autonomous agent would block at the gate if step-mode is enabled from the dashboard. The vision doc explicitly describes "same kernel, different shells."

2. **Test isolation:** Module-level singletons are notoriously hard to reset between test cases. The plan's TDD sequence does not address how tests will isolate gate state. Each test that imports `step_gate` gets the same instance.

**Recommendation:** Use a registry pattern (gate instances keyed by runner_id or invocation_id) or make the gate injectable via the plugin constructor rather than imported at module level.

### Theme 4: The plan's scope is large -- 6 steps with 6 teammates -- but the dependencies are not fully mapped (flagged by all three critics)

Steps 1-3 (gate, plugin, state keys) are tightly coupled and could be one PR. Step 4 (fixture launcher) is a significant standalone feature with its own test surface. Step 5 (dashboard UI) depends on Steps 1-4. Step 6 (wiring) is trivial. The plan presents these as parallel teammate tasks but does not map the dependency graph. Steps 1 and 2 cannot be tested without Step 6 (wiring). Step 5 cannot be tested without Step 4. The TDD sequence at the bottom partially addresses this but does not match the teammate assignment.

---

## Prioritized Recommendations

1. **Fix the asyncio.Event semantics mismatch for parallel workers.** The plan says `advance()` releases "one blocked waiter," but `asyncio.Event.set()` releases ALL waiters. This is a design bug. Switch to `asyncio.Queue` (put a token, each waiter gets one), `asyncio.Semaphore`, or per-waiter `asyncio.Event` instances. Resolve this before implementation. *(Flagged by: Callback Expert, Prior-Art Researcher)*

2. **Scope the gate to runner/invocation instances, not module-level singleton.** The module-level singleton conflicts with the continuous runtime vision (multiple runners in one process) and hinders test isolation. Use a registry keyed by invocation ID, or make the gate injectable via the plugin constructor. *(Flagged by: Vision Challenger, Callback Expert)*

3. **Study AgentStepper (arXiv 2602.06593) before finalizing the UX design.** It is the closest prior art, validated by a 12-person user study. Key design elements to consider adopting: three execution states (paused/stepping/running), prompt editing at breakpoints, and post-hoc trajectory replay alongside live stepping. *(Flagged by: Prior-Art Researcher)*

4. **Add `after_model_callback` to the plugin for step-mode enrichment.** Without it, the step-mode UI shows "paused before model call" but cannot show "what the model just did." Adding a `last_model_action` summary to the gate metadata after each model call would make step-mode dramatically more useful for debugging. ~10 lines of code. *(Flagged by: Callback Expert)*

5. **Design `wait_for_advance()` to return an optional payload for future HITL extensibility.** Returning `None` locks the API into pause-only mode. Returning `Optional[dict]` allows future approve/reject and edit-then-resume gates to pass user decisions back through the same interface. Zero cost now, high value later. *(Flagged by: Vision Challenger, Callback Expert)*

6. **Elevate the provider-fake fixture launcher (Step 4) to a first-class dashboard feature with its own design scope.** The plan treats it as a step-mode prerequisite, but it enables topology comparison, skill validation, and dashboard-driven regression testing -- all of which serve multiple vision areas. Give it its own design attention rather than burying it in the step-mode plan. *(Flagged by: Vision Challenger)*

7. **Add step-mode scope selector to the dashboard UI.** "Step: all agents / reasoning only / depth 0 only" implemented via `before_agent_callback` flag setting. Without this, stepping through 8 workers in a batch dispatch one-by-one will be tedious for common debugging scenarios. *(Flagged by: Callback Expert)*

8. **Collapse Steps 1-3 and 6 into a single PR** with a clear dependency on Step 4 (fixture launcher) and Step 5 (dashboard UI) as follow-on PRs. The current 6-teammate parallelism does not match the actual dependency graph. *(Flagged by: all three critics)*
