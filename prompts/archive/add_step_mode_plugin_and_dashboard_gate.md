<!-- generated: 2026-03-18 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Add Step-Mode Plugin with Dashboard Async Gate

## Context

The RLM agent needs a "step mode" that pauses execution before each model call, allowing the user to inspect state and advance one step at a time from the dashboard UI. This requires a new global `BasePlugin` with a `before_model_callback` that blocks on an async gate, a shared `asyncio.Event` signaling primitive between the plugin and the dashboard controller (in-process only), and a dashboard UI toggle + "Next Step" button. The pause must work globally across all agents — reasoning agent and parallel workers alike. This feature is scoped to in-process dashboard runs only (i.e., replay and provider-fake fixture launches from `run_service.py`), not cross-process CLI runs.

## Original Transcription

> Generate a callback that allows me to pause the rlm agent with a pause button built into the dashboard application. This should be a Implemented as a step mode where I can trigger the next series of actions that lead up to the next model call. So I think this needs to be a either a before model or after model callback, but please, look into the child dispatch code to know whether this is going to be challenging, considering how we flush keys or the bug 13 issue we had with the the schema's tied to a before model callback. That might be totally unrelated. But regardless, I I want a a step mode button in the dashboard that when I have activated in that state allows me to go step by step, not with every single action on the session event loop, but rather one's, that allow me to pause before, model calls. And this would be across the board, including parallel calls with the batched, agent. So that actually might have to be a yeah. It's gonna have to be a global think, plug in. So it's gonna this is gonna have to be a plug in callback. Cause it needs to be global in scope.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

### Step 1 — Signaling Primitive

1. **Spawn a `Step-Gate` teammate to create `rlm_adk/step_gate.py` with a shared in-process async gate primitive.**

   The gate uses a shared `asyncio.Event` object that both the `StepModePlugin` and the `LiveDashboardController` reference directly. The plugin awaits the event; the dashboard sets it. There is no cross-process mode — step mode is scoped to in-process dashboard runs only.

   The gate API should expose:
   ```python
   class StepGate:
       async def wait_for_advance(self) -> None:
           """Block until the user advances. No-op if step mode is off."""
       def set_step_mode(self, enabled: bool) -> None:
           """Toggle step mode on/off. If disabling while a waiter is blocked, release it."""
       def advance(self) -> None:
           """Signal the gate to release one blocked waiter."""
       @property
       def step_mode_enabled(self) -> bool: ...
       @property
       def waiting(self) -> bool:
           """True if the gate is currently blocked (plugin is paused)."""
       @property
       def paused_agent_name(self) -> str | None:
           """Name of the agent currently blocked at the gate."""
       @property
       def paused_depth(self) -> int | None:
           """Depth of the agent currently blocked at the gate."""
   ```

   Implementation uses `asyncio.Event`:
   - `wait_for_advance()`: clear the event, set `_waiting = True` + metadata, await `event.wait()`, then reset `_waiting = False`.
   - `advance()`: call `event.set()` to release one waiter.
   - `set_step_mode(False)`: set the event to release any blocked waiter (graceful disable).

   **Constraint:** The `StepGate` must be a module-level singleton so the plugin and dashboard controller can share it without passing references through ADK's plugin constructor limitations. Use `step_gate = StepGate()` at module level in `rlm_adk/step_gate.py`, imported by both the plugin and the controller.

### Step 2 — Plugin Implementation

2. **Spawn a `Step-Plugin` teammate to create `rlm_adk/plugins/step_mode.py` implementing `StepModePlugin(BasePlugin)`.**

   The plugin must implement `before_model_callback`:

   ```python
   async def before_model_callback(
       self,
       *,
       callback_context: CallbackContext,
       llm_request: LlmRequest,
   ) -> Optional[LlmResponse]:
       """If step mode is active, block here until the user advances."""
   ```

   Key behaviors:
   - When step mode is **off**, return `None` immediately (zero overhead).
   - When step mode is **on**, call `await step_gate.wait_for_advance()` which blocks until the dashboard user clicks "Next Step".
   - Before blocking, write the current agent name and depth to the gate's metadata so the dashboard can display what's paused.
   - **Always return `None`** — never return an `LlmResponse`. This avoids the short-circuit behavior that caused BUG-13 issues with `set_model_response`. The purpose is to *delay*, not to *replace* the model call.
   - Catch `asyncio.CancelledError` and re-raise (don't swallow cancellation).

   **Why `before_model_callback` and not `before_tool_callback`:** The user wants to pause before *model calls*, not before tool executions. `before_model_callback` fires once per LLM invocation across all agents globally (reasoning agent, workers in ParallelAgent). `before_tool_callback` would fire before REPL execution, which is a different granularity.

   **BUG-13 concern is unrelated:** BUG-13 was about `_output_schema_processor.get_structured_model_response()` terminating workers when `set_model_response` was called. Step-mode never returns an `LlmResponse` from `before_model_callback` — it only delays execution. The `WorkerRetryPlugin` schema validation pipeline is orthogonal and unaffected.

   **flush_fn concern is unrelated:** `flush_fn()` in `rlm_adk/dispatch.py` (line 790) runs *after* REPL execution, not before model calls. Step-mode pauses *before* the model generates a response, so local accumulators are not in a partially-flushed state.

   **Parallel worker concern:** Since `BasePlugin` callbacks fire globally for all agents (per ADK docs: "plugins applies globally to all agents added in the runner"), the step-mode gate will fire for every worker's model call in a `ParallelAgent` batch. This means step mode pauses *each worker individually* before its model call. The user can step through workers one at a time. This is the correct granularity — pausing *all* workers at once would require blocking at the dispatch level (inside `llm_query_batched_async`), which would be more invasive and less useful for debugging.

   Wire the plugin into `_default_plugins()` in `rlm_adk/agent.py` (line 681). The plugin is always present but dormant until toggled from the dashboard (zero overhead when off).

### Step 3 — State Keys

3. **Spawn a `Step-State` teammate to add step-mode state keys to `rlm_adk/state.py`.**

   Add:
   ```python
   STEP_MODE_ENABLED = "step:mode_enabled"       # bool — is step mode active?
   STEP_MODE_PAUSED_AGENT = "step:paused_agent"   # str — name of agent currently paused
   STEP_MODE_PAUSED_DEPTH = "step:paused_depth"   # int — depth of paused agent
   STEP_MODE_ADVANCE_COUNT = "step:advance_count"  # int — number of advances taken
   ```

   Add `STEP_MODE_ENABLED` to `EXPOSED_STATE_KEYS` (line 160) so the REPL `_rlm_state` snapshot includes it. *[Added — the transcription didn't mention this, but exposing the flag in REPL state lets the model's generated code be aware it's in step mode and adapt behavior if needed.]*

### Step 4 — Provider-Fake Fixture Drop-Down in Dashboard

4. **Spawn a `Fixture-Selector` teammate to add a provider-fake fixture drop-down to the dashboard launch panel in `rlm_adk/dashboard/live_app.py`.**

   Add a new `ui.select` drop-down in `_launch_panel()` (line 293), placed **between** the existing "Replay fixture" drop-down (line 313) and the "Prompt-visible skills" multi-select (line 323). The new drop-down should:

   - **Label:** `"Provider-fake fixture"`
   - **Options:** List all `.json` fixture stems from `tests_rlm_adk/fixtures/provider_fake/`. Populate via a new `list_provider_fake_fixtures()` function in `rlm_adk/dashboard/run_service.py`, following the pattern of `list_replay_fixtures()` (line 44). Scan `tests_rlm_adk/fixtures/provider_fake/*.json`, return sorted stem names (e.g., `"step_mode_pause"`, `"polymorphic_dag_routing"`).
   - **Binding:** `controller.set_provider_fake_fixture(value)` stores the selected fixture stem on `LiveDashboardState`.
   - **Mutual exclusion with Replay fixture:** When a provider-fake fixture is selected, clear the replay fixture selection (and vice versa). Only one launch source can be active. The "Launch" button label should reflect which type is selected (e.g., "Launch Replay" vs "Launch Fixture").
   - **Launch path:** Add `launch_provider_fake()` to `LiveDashboardController` (alongside `launch_replay()` at line 80). This method should:
     1. Import and call the provider-fake contract runner programmatically (like `run_service.py` does for replay). Use the existing `tests_rlm_adk.provider_fake` module's API to run a single fixture in-process with the full plugin stack (including `StepModePlugin`).
     2. Write traces to `.adk/traces.db` so the dashboard's existing observability views pick up the run.
     3. The `StepGate` singleton is shared in-process, so step-mode works automatically.

   Add to `LiveDashboardState` (line 319):
   ```python
   available_provider_fake_fixtures: list[str] = field(default_factory=list)
   selected_provider_fake_fixture: str = ""
   ```

   Add to `LiveDashboardController.initialize()` (line 56):
   ```python
   self.state.available_provider_fake_fixtures = list_provider_fake_fixtures()
   ```

   *[Added — the transcription didn't include this step, but the user wants to test step-mode from the dashboard with provider-fake fixtures. The dashboard currently only launches replay fixtures. Extending it to launch provider-fake fixtures in-process is the prerequisite for dashboard-driven step-mode testing.]*

### Step 5 — Dashboard Step-Mode UI Controls

5. **Spawn a `Step-Dashboard` teammate to add step-mode controls to `rlm_adk/dashboard/live_app.py`.**

   Add a new toggle and button next to the existing "Pause updates" toggle (line 168-171):

   - **"Step mode" toggle** — calls `controller.set_step_mode(value)` which updates the `StepGate` singleton.
   - **"Next Step" button** — enabled only when step mode is active AND the gate is in `waiting` state. Calls `controller.advance_step()`.
   - **Status indicator** — when the gate is waiting, display the paused agent name and depth (e.g., "Paused: reasoning_agent @ depth 0" or "Paused: worker_3 @ depth 1"). Read from `step_gate.paused_agent_name` and `step_gate.paused_depth`.

   Follow the existing pattern in `live_app.py` for the `_toggle()` helper and `_handle_pause()` callback (line 483). The poll loop at line 262 (`ui.timer(0.25, _poll)`) already refreshes at 250ms, which is sufficient to pick up gate state changes.

   Add `set_step_mode()` and `advance_step()` methods to `LiveDashboardController` in `rlm_adk/dashboard/live_controller.py`, following the pattern of `set_live_updates_paused()` (line 158). Both methods should import and operate on the `step_gate` singleton from `rlm_adk.step_gate`.

   Add `step_mode_enabled: bool = False`, `step_mode_waiting: bool = False`, and `step_mode_paused_label: str = ""` fields to `LiveDashboardState` in `rlm_adk/dashboard/live_models.py` (line 319). The controller's `poll()` method should sync these fields from the `step_gate` singleton on each tick.

### Step 6 — Plugin Wiring

6. **Spawn a `Step-Wiring` teammate to wire `StepModePlugin` into the default plugin stack in `rlm_adk/agent.py`.**

   In `_default_plugins()` (line 681), add `StepModePlugin()` to the returned list. It should be registered **before** `ObservabilityPlugin` so step-mode pauses happen before obs metrics are recorded (preserving accurate timing). The plugin should always be instantiated (it's dormant when step mode is off — zero overhead), not gated by an env var.

   *[Added — always-present is better than env-var-gated because step mode needs to be toggled at runtime from the dashboard, not at process start time.]*

## Provider-Fake Fixture & TDD

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/step_mode_pause.json`

**Essential requirements the fixture must capture:**
- Step-mode gate blocks `before_model_callback` and releases on `advance()` — verifiable by checking that the model call does not proceed until advance is called.
- Step-mode toggle off mid-pause releases the gate immediately (no stuck coroutine).
- Multiple workers in a parallel batch each pause independently — verify by counting the number of `wait_for_advance()` calls matching the batch size.
- Step-mode off has zero overhead — `before_model_callback` returns `None` without awaiting.

**TDD sequence:**
1. Red: Write unit test for `StepGate` — toggle on, call `wait_for_advance()` in a task, assert it blocks, call `advance()`, assert it completes. Run, confirm failure (class doesn't exist).
2. Green: Implement `StepGate` with `asyncio.Event`. Run, confirm pass.
3. Red: Write unit test for `StepGate` disable-while-waiting — toggle on, block a waiter, toggle off, assert waiter is released.
4. Green: Implement `set_step_mode(False)` releasing blocked waiters. Run, confirm pass.
5. Red: Write unit test for `StepModePlugin.before_model_callback` — mock `CallbackContext`, assert it awaits gate when enabled. Run, confirm failure.
6. Green: Implement `StepModePlugin`. Run, confirm pass.
7. Red: Write unit test for `list_provider_fake_fixtures()` — assert it returns sorted stems from `tests_rlm_adk/fixtures/provider_fake/`. Run, confirm failure.
8. Green: Implement `list_provider_fake_fixtures()` in `run_service.py`. Run, confirm pass.
9. Red: Write integration test — create runner with plugin, run a 1-turn fixture, toggle step mode on mid-run, assert pause and advance cycle completes. Run, confirm failure.
10. Green: Wire plugin into `_default_plugins()`. Run, confirm pass.
11. Red: Write test for parallel workers — run a batched dispatch fixture with 3 workers, assert 3 independent `wait_for_advance()` calls.
12. Green: Verify plugin fires for each worker (should work automatically via global plugin registration).

**E2E demo via `/chrome`:** After all unit/integration tests pass, use Claude Code's browser automation (`mcp__claude-in-chrome__*`) to drive the full dashboard flow: select fixture -> enable step mode -> launch -> verify pause -> advance -> verify completion. See the "E2E Testing via Claude Code `/chrome`" section below for the detailed test script.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the step-mode gate works end-to-end with the dashboard toggle.

## Considerations

- **AR-CRIT-001 compliance:** The `StepModePlugin` writes to `callback_context.state` (proper channel). The `StepGate` is a runtime coordination primitive, not a state mutation — it does not touch `ctx.session.state` directly.
- **ADK plugin execution order:** Plugins execute in registration order. `StepModePlugin` should be early in the list so the pause happens before other plugins record metrics. If it were after `ObservabilityPlugin`, the obs timing would include the pause duration, skewing metrics.
- **Vision doc alignment:** The `StepGate` is a concrete implementation of the "HITL Async Gates" described in `rlm_adk_docs/vision/interactive_dashboard.md` (lines 169-186). It is modeled as an "awaited runtime primitive from the agent's perspective" per the vision spec.
- **In-process only — no cross-process mode:** The `StepGate` is a module-level `asyncio.Event` singleton shared between the plugin and the dashboard controller within the same Python process. This works for dashboard-launched runs (replay and provider-fake fixtures via `run_service.py`). CLI `adk run` sessions do not share the event loop with the dashboard and are out of scope for step-mode. This is the first HITL write-path into the agent runtime from the dashboard.
- **`before_model_callback` return semantics:** Per ADK docs, returning a non-None `LlmResponse` from `before_model_callback` short-circuits the model call AND all remaining plugins/callbacks. Step-mode must NEVER return a value — only delay via `await`. This is safe and idiomatic.
- **Cancellation safety:** If the ADK Runner cancels the invocation while the plugin is blocked on the gate, `asyncio.CancelledError` propagates naturally through `asyncio.Event.wait()`. The plugin must not catch and suppress this.
- **Provider-fake fixture launcher:** The new in-process provider-fake fixture launcher must create a `Runner` with the full default plugin stack (including `StepModePlugin`), matching what `create_rlm_runner()` produces. Do not strip plugins or use `InMemory*` services — benchmarks and fixture runs must use real persistent services per project convention.

## E2E Testing via Claude Code `/chrome`

The step-mode incremental stepping functionality should be tested end-to-end using Claude Code's browser automation tools (`/chrome` / `mcp__claude-in-chrome__*`). The test flow is:

1. **Launch the dashboard** — start the NiceGUI dashboard in a browser tab.
2. **Select the step-mode provider-fake fixture** — use the new "Provider-fake fixture" drop-down (Step 4) to select the `step_mode_pause` fixture.
3. **Enable step mode** — toggle the "Step mode" switch on.
4. **Launch the fixture** — click the launch button.
5. **Verify pause** — assert the status indicator shows "Paused: reasoning_agent @ depth 0" (or equivalent). Verify the dashboard's observability pane shows the run is in-flight but not advancing.
6. **Advance** — click "Next Step". Verify the status updates to the next pause point (e.g., a worker model call).
7. **Advance through completion** — click "Next Step" repeatedly until the run completes. Verify the final state in the session pane matches the fixture's expected output.
8. **Toggle off mid-pause** — re-run the fixture, pause at a model call, then toggle step mode off. Verify the run completes without further manual advancing (the gate releases immediately).

This e2e test agent should use `mcp__claude-in-chrome__navigate` to open the dashboard, `mcp__claude-in-chrome__find` / `mcp__claude-in-chrome__form_input` to interact with the drop-downs and buttons, and `mcp__claude-in-chrome__get_page_text` / `mcp__claude-in-chrome__read_page` to verify status indicators and final state. The `/chrome` approach exercises the full stack: NiceGUI UI -> controller -> StepGate singleton -> plugin -> ADK model call boundary.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/plugins/observability.py` | `ObservabilityPlugin` | L50 | Model plugin to follow for `before_model_callback` / `after_model_callback` pattern |
| `rlm_adk/plugins/observability.py` | `before_model_callback` | L152 | Exact callback signature to replicate |
| `rlm_adk/plugins/observability.py` | `after_model_callback` | L168 | Shows how callback_context.state is used in callbacks |
| `rlm_adk/agent.py` | `_default_plugins()` | L681 | Where to wire StepModePlugin into the plugin stack |
| `rlm_adk/agent.py` | `create_rlm_app()` | L698 | App factory that passes plugins to Runner |
| `rlm_adk/state.py` | `EXPOSED_STATE_KEYS` | L160 | Where to add STEP_MODE_ENABLED for REPL visibility |
| `rlm_adk/state.py` | `SHOULD_STOP` | L16 | Existing flow-control key pattern to follow |
| `rlm_adk/dispatch.py` | `flush_fn()` | L790 | Flush runs after REPL exec, not before model — no conflict |
| `rlm_adk/dispatch.py` | `create_dispatch_closures()` | L168 | Dispatch closure factory — step-mode does not modify this |
| `rlm_adk/dispatch.py` | `llm_query_batched_async()` | L964 | Parallel batch dispatch — workers get individual pauses via global plugin |
| `rlm_adk/callbacks/worker_retry.py` | `WorkerRetryPlugin` | L134 | BUG-13 context — unrelated to step-mode (schema validation, not pause) |
| `rlm_adk/tools/repl_tool.py` | `REPLTool.run_async()` | L110 | Tool execution path — step-mode pauses before this, not during |
| `rlm_adk/orchestrator.py` | `RLMOrchestratorAgent._run_async_impl()` | L230 | Orchestrator entry — delegates to reasoning_agent, plugin fires globally |
| `rlm_adk/dashboard/live_app.py` | `_poll()` | L262 | Dashboard poll loop (250ms) — picks up gate state changes |
| `rlm_adk/dashboard/live_app.py` | `"Pause updates"` toggle | L168 | Existing toggle pattern to replicate for step-mode |
| `rlm_adk/dashboard/live_app.py` | `_handle_pause()` | L483 | Existing pause handler pattern |
| `rlm_adk/dashboard/live_controller.py` | `set_live_updates_paused()` | L158 | Controller method pattern for toggle |
| `rlm_adk/dashboard/live_models.py` | `LiveDashboardState` | L319 | State dataclass — add step_mode fields here |
| `rlm_adk/dashboard/live_models.py` | `live_updates_paused` | L335 | Existing boolean toggle field to replicate |
| `rlm_adk/dashboard/run_service.py` | `prepare_replay_launch()` | L115 | In-process runner creation — StepGate singleton shared here |
| `rlm_adk/dashboard/run_service.py` | `list_replay_fixtures()` | L44 | Pattern to replicate for `list_provider_fake_fixtures()` |
| `rlm_adk/dashboard/live_app.py` | `_launch_panel()` | L293 | Launch panel — insert provider-fake drop-down between replay and skills selects |
| `rlm_adk/dashboard/live_app.py` | Replay fixture `ui.select` | L313 | Existing drop-down pattern to replicate |
| `rlm_adk/dashboard/live_app.py` | Prompt-visible skills `ui.select` | L323 | New drop-down goes before this |
| `tests_rlm_adk/fixtures/provider_fake/` | Fixture directory | — | Source for provider-fake fixture stems |
| `tests_rlm_adk/provider_fake/` | Contract runner module | — | Programmatic API for in-process fixture execution |
| `rlm_adk_docs/vision/interactive_dashboard.md` | HITL Async Gates | L169 | Vision spec for this exact feature pattern |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow Observability and Core Loop branches)
3. `rlm_adk_docs/vision/interactive_dashboard.md` — vision spec establishing HITL async gates as the canonical pattern
