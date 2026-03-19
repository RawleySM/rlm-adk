# Devil's Advocate Review: add_step_mode_plugin_and_dashboard_gate.md

## Summary

The plan proposes a step-mode execution feature for the RLM agent: a `StepGate` async primitive, a `StepModePlugin` that pauses before model calls, dashboard UI controls, and a provider-fake fixture launcher in the dashboard. Several pieces are already partially implemented (`step_gate.py`, `step_mode.py`, state keys in `state.py`). The plan is well-structured and shows deep familiarity with the codebase. However, it contains one critical architectural blind spot, several significant gaps, and a number of lesser issues that should be addressed before implementation proceeds.

---

## CRITICAL: Plugin Does Not Fire for Child Dispatches

**Severity: Blocks the stated goal of pausing "across the board, including parallel calls."**

The plan states (Step 2):

> Since `BasePlugin` callbacks fire globally for all agents (per ADK docs: "plugins applies globally to all agents added in the runner"), the step-mode gate will fire for every worker's model call in a `ParallelAgent` batch.

This is **incorrect for the RLM-ADK child dispatch architecture**. The plan conflates two different dispatch paths:

1. **ADK's ParallelAgent** -- plugins fire because the Runner drives execution and invokes plugin callbacks before each LLM call.
2. **RLM child orchestrators** -- `dispatch.py` line 436 calls `child.run_async(child_ctx)` **directly on the agent**, not through `runner.run_async()`. The `InvocationContext` is copied via `ctx.model_copy()`, but the Runner's plugin callback invocation happens in the Runner's event loop, not inside `agent.run_async()`.

Looking at the actual dispatch code in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py`:

```python
child_ctx = ctx.model_copy()
async for _event in child.run_async(child_ctx):
    ...
```

The child orchestrator's `reasoning_agent` is an `LlmAgent`. When ADK's `BaseLlmFlow` runs its LLM call loop for the child, it checks the `InvocationContext` for registered plugins. Whether those plugin callbacks actually fire depends on how ADK's internal `_run_live_callbacks` / `_invoke_callbacks` resolves plugins from the copied context. This is a private implementation detail that **must be verified empirically**, not assumed.

**The MEMORY.md explicitly documents this gap**: "ObservabilityPlugin does NOT fire for workers -- ParallelAgent gives workers isolated invocation contexts." The plan even acknowledges this in the Considerations section but then contradicts itself by claiming plugins fire for parallel workers.

**Recommendation:** Before implementing, write a verification test: register a plugin with `before_model_callback`, dispatch a child orchestrator, and assert the callback fires. If it does not fire (the likely outcome based on the observability precedent), the step gate must be injected at the dispatch level -- either inside `_run_child()` in `dispatch.py` or by setting the `before_model_callback` directly on the child's reasoning agent, not via a global plugin.

---

## HIGH: asyncio.Event Semantics Allow Only One Waiter Safely

**Severity: Correctness bug under parallel dispatch.**

The `StepGate` in `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/step_gate.py` uses a single `asyncio.Event`. The plan says:

> Step mode pauses *each worker individually* before its model call. The user can step through workers one at a time.

But `asyncio.Event.set()` **wakes ALL waiters simultaneously**, not one at a time. If 3 workers in a batch all call `wait_for_advance()` concurrently:

1. All 3 clear the event and block.
2. But only one can set `_waiting = True` and the metadata -- the other 2 overwrite it immediately.
3. When `advance()` calls `event.set()`, ALL 3 are released, not just one.

The current implementation has a single `_waiting` flag and single `_paused_agent_name`/`_paused_depth`. This is a race condition: with concurrent waiters, the metadata is meaningless (last writer wins), and a single advance releases all waiters.

**Recommendation:** Replace the single `asyncio.Event` with an `asyncio.Queue` or `asyncio.Condition`-based mechanism that supports multiple independent waiters. Each waiter should get its own ticket that must be individually released. The metadata should be a collection (e.g., a list or dict of waiting agents), not a single scalar.

---

## HIGH: `step:` Prefix -- Verify ADK Does Not Strip It

**Severity: Potential silent data loss (BUG-11 repeat).**

The state keys use the `step:` prefix (e.g., `step:mode_enabled`). The codebase has a documented history of ADK stripping prefixed keys (BUG-11: `temp:` prefix). While `step:` is not a known ADK-reserved prefix today, the ADK `BaseSessionService._trim_temp_delta_state()` method strips keys matching `State.TEMP_PREFIX`. The project has been burned by this exact pattern before.

The `step:` keys are already in `state.py` on the working branch and `STEP_MODE_ENABLED` is in `EXPOSED_STATE_KEYS`. If ADK introduces additional prefix filtering in a future version, or if `step:` collides with some internal convention, these keys will silently vanish.

**Recommendation:** Add an explicit integration test that writes a `step:*` key via `callback_context.state`, then reads it back from `session.state` after the event is committed. This is a 5-line test that permanently guards against the prefix-stripping class of bugs.

---

## HIGH: StepModePlugin Not Wired into `_default_plugins()`

**Severity: Feature will not activate without manual wiring.**

The plan's Step 6 says to add `StepModePlugin()` to `_default_plugins()` in `agent.py`. However, inspecting `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py` (the current working tree), there is no import or instantiation of `StepModePlugin` anywhere in `_default_plugins()`. The plugin file exists (`rlm_adk/plugins/step_mode.py`) and the gate exists (`rlm_adk/step_gate.py`), but **the wiring step has not been done**. The plan correctly identifies this as a step, but since the implementation files already exist, an implementer might assume the wiring is already done and skip Step 6.

**Recommendation:** Step 6 should be a prerequisite check in the TDD sequence, not the last step. A red test should assert that `StepModePlugin` appears in `create_rlm_app(...).plugins` before any green implementation. This catches the wiring gap at the start, not the end.

---

## MEDIUM: Module-Level Singleton Creates Testing Friction

**Severity: Test isolation concern.**

The `StepGate` singleton at module level (`step_gate = StepGate()`) is process-global. This means:

1. Tests that enable step mode must remember to disable it in teardown, or they poison subsequent tests.
2. Parallel test execution (`pytest-xdist`) would share the singleton across workers in the same process (though `xdist` typically uses subprocesses, so this may be fine in practice).
3. The gate's `asyncio.Event` is created at import time. If the module is imported before an event loop exists (common in test collection), the event may be bound to the wrong loop or raise `DeprecationWarning` in Python 3.12+ where `asyncio.Event()` outside a running loop was deprecated.

**Recommendation:**
- Use `asyncio.Event()` lazily (create on first `wait_for_advance()` call, not in `__init__`).
- Add a `reset()` method to `StepGate` for test teardown.
- Consider a `get_step_gate()` factory that returns the singleton but allows tests to replace it via a `set_step_gate()` for injection.

---

## MEDIUM: Plugin Ordering Claim Contradicts Current Code

The plan says (Step 6):

> It should be registered **before** `ObservabilityPlugin` so step-mode pauses happen before obs metrics are recorded (preserving accurate timing).

But looking at `_default_plugins()` in `agent.py` (line 417-418):

```python
plugins: list[BasePlugin] = [
    DashboardAutoLaunchPlugin(),
    ObservabilityPlugin(verbose=_debug_env),
]
```

The `DashboardAutoLaunchPlugin` is first. The plan says "before ObservabilityPlugin" but does not mention `DashboardAutoLaunchPlugin`. If step-mode is added between `DashboardAutoLaunchPlugin` and `ObservabilityPlugin`, the dashboard auto-launch plugin's `before_model_callback` (if any) would fire before the step-mode pause. This may or may not matter, but the plan should explicitly state the target position in the list.

More importantly, the plan's reasoning about obs timing is correct but incomplete: the `ObservabilityPlugin.before_model_callback` only logs a debug message. The actual timing concern is `after_model_callback`, which runs after the model returns. Since step-mode delays the model call start, the wall-clock time between `before_model` and `after_model` would include the pause duration regardless of plugin order. To get accurate timing, the `ObservabilityPlugin` would need to record a start timestamp in `before_model_callback` and subtract the step-mode wait duration -- which is not proposed.

**Recommendation:** Either accept that obs timing will include step-mode pause duration (and document this), or add a `step_pause_duration_ms` field to the gate that `ObservabilityPlugin.after_model_callback` can subtract.

---

## MEDIUM: Provider-Fake Fixture Launcher (Step 4) Is Under-Specified

Step 4 introduces `launch_provider_fake()` in `LiveDashboardController`. The plan says:

> Import and call the provider-fake contract runner programmatically (like `run_service.py` does for replay).

But the provider-fake contract runner is a pytest-based system (`tests_rlm_adk/provider_fake/`). It starts an `aiohttp` `FakeGeminiServer`, sets up environment variables for the fake server URL, and runs through fixtures using `create_rlm_runner()`. Running this from the dashboard means:

1. **Starting `FakeGeminiServer` in-process** alongside the NiceGUI dashboard. The fake server binds to a TCP port. If the dashboard is already running its own event loop, this adds a second `aiohttp` server to the same loop. Port conflicts and lifecycle management are non-trivial.
2. **Environment variable pollution**: The fake server requires `GOOGLE_API_KEY=fake` and the fake server URL set as the base URL. These are currently process-level env vars. Setting them from the dashboard would affect the entire process, including any concurrent replay runs.
3. **No `ReplayLaunchHandle` equivalent**: The plan references `prepare_replay_launch()` as a pattern but does not define the equivalent `prepare_provider_fake_launch()` function. The fixture runner has a fundamentally different API (it reads fixture JSON, creates fake server routes, then runs the agent) vs. replay (which just feeds queries).

**Recommendation:** Step 4 needs a concrete design for the `ProviderFakeLaunchHandle` equivalent. Key decisions: Does it start/stop the `FakeGeminiServer` per fixture? How does it isolate env vars? Does it use a dedicated port range? The plan should either scope this to a follow-up task or provide these details.

---

## MEDIUM: Missing Timeout on Gate Wait

The `wait_for_advance()` method awaits `self._event.wait()` with no timeout. If the user starts a step-mode run, pauses it, then navigates away from the dashboard (or the dashboard tab crashes), the agent coroutine is blocked indefinitely. There is no watchdog or timeout mechanism.

**Recommendation:** Add an optional `timeout` parameter to `wait_for_advance()` with a generous default (e.g., 300 seconds). On timeout, either auto-advance and log a warning, or cancel the invocation. Also consider an `after_run_callback` on the plugin that resets the gate state to prevent stale pauses across invocations.

---

## MEDIUM: Dashboard Polling Interval May Feel Sluggish

The plan says:

> The poll loop at line 262 (`ui.timer(0.25, _poll)`) already refreshes at 250ms, which is sufficient to pick up gate state changes.

250ms is the poll interval for *detecting* that the gate entered the waiting state. From the user's perspective: they click "Next Step", the gate releases, the model call runs, the next `before_model_callback` fires and the gate blocks again, then the dashboard must detect the new waiting state. The total round-trip latency is:

- Gate release: ~0ms
- Model call: variable (100ms to 5s for Gemini)
- Gate re-block: ~0ms
- Dashboard poll detects it: up to 250ms

So after clicking "Next Step", the user waits up to `model_call_time + 250ms` to see the next "Paused" status. For fast provider-fake calls (~5ms), the user could be clicking and seeing stale state for up to 250ms. This is fine for demos but could feel laggy for rapid stepping.

**Recommendation:** Consider adding a `WebSocket` push notification from the gate (via NiceGUI's `ui.notify` or `app.storage`) when the gate enters waiting state, rather than relying solely on polling.

---

## LOW: Plan References Non-Existent Line Numbers

The plan references specific line numbers in source files (e.g., "`_default_plugins()` in `rlm_adk/agent.py` (line 681)", "`LiveDashboardState` in `rlm_adk/dashboard/live_models.py` (line 319)"). Verified against the current working tree:

- `_default_plugins()` is at line 398, not 681.
- `LiveDashboardState` is at line 318-319 (close but the class definition starts at 318).
- `_launch_panel()` is at line 293 (correct).
- `list_replay_fixtures()` is at line 44 (correct).

Some of these are off, likely due to code changes between when the plan was drafted and the current state. This is low severity but can mislead implementers.

**Recommendation:** Use function/class names as anchors, not line numbers, or regenerate the appendix from the current source.

---

## LOW: `STEP_MODE_ADVANCE_COUNT` Has No Writer

The plan defines `STEP_MODE_ADVANCE_COUNT = "step:advance_count"` in state keys (and it is already in `state.py`), but neither the existing `StepModePlugin` nor the `StepGate` writes this value to session state. The gate's `advance()` method does not increment any counter. The plugin's `before_model_callback` does not write it either.

If the intent is to track how many advances the user has clicked (useful for debugging), something must write this key via a proper state mutation channel.

**Recommendation:** Either remove the key if it is aspirational, or add a write in the plugin's `before_model_callback` (after the gate releases, write `callback_context.state[STEP_MODE_ADVANCE_COUNT] = current + 1`).

---

## LOW: `STEP_MODE_PAUSED_AGENT` and `STEP_MODE_PAUSED_DEPTH` Are Never Written to State

Similarly, `STEP_MODE_PAUSED_AGENT` and `STEP_MODE_PAUSED_DEPTH` are defined in `state.py` but the plugin only writes metadata to the `StepGate` object (in-memory), not to `callback_context.state`. The dashboard reads from the gate singleton, not from session state. This means:

1. These keys are dead -- nothing writes them, nothing reads them.
2. The SQLite tracing plugin will not capture step-mode pause events (no state delta for pause/resume transitions).

**Recommendation:** If these keys are intended for tracing/audit, the plugin should write them to `callback_context.state` before blocking and clear them after release. If they are only for dashboard display (which reads from the gate), remove them from `state.py` to avoid confusion.

---

## LOW: TDD Step 9 Integration Test Is Fragile

The TDD sequence says:

> Red: Write integration test -- create runner with plugin, run a 1-turn fixture, toggle step mode on mid-run, assert pause and advance cycle completes.

"Toggle step mode on mid-run" requires precise timing: the test must set `step_gate.set_step_mode(True)` after the run starts but before the first model call. In a provider-fake run with a fast fake server, the model call might complete before the toggle is set. This is a classic race condition in tests.

**Recommendation:** Enable step mode *before* launching the run, not mid-run. Test the "toggle off mid-pause" scenario in a separate test (TDD step 3-4 already covers this at the unit level for the gate). For the integration test, pre-enable step mode and use a background task to call `advance()` after detecting the gate is waiting.

---

## OBSERVATIONS (Not Defects)

1. **Step 3 is already done**: The state keys are already in `state.py` (lines 156-160) and `STEP_MODE_ENABLED` is already in `EXPOSED_STATE_KEYS` (line 188). An implementer following the plan linearly would attempt to create something that already exists.

2. **Steps 1 and 2 are already done**: `step_gate.py` and `plugins/step_mode.py` already exist in the working tree. The plan reads as a from-scratch implementation guide but the code is partially landed. The plan should note what already exists vs. what still needs to be built.

3. **The vision doc moved**: The plan references `rlm_adk_docs/vision/interactive_dashboard.md` (lines 169-186) but the file has moved to `rlm_adk_docs/vision/inventing_on_principle_dashboard/interactive_dashboard.md`. The reference should be updated.

4. **Step 4 is the real risk**: Steps 1-3 and 5-6 are relatively mechanical (gate, plugin, UI controls, wiring). Step 4 -- the provider-fake fixture launcher -- is the most complex and under-specified piece. It touches testing infrastructure, server lifecycle, and environment isolation. Consider splitting it into its own plan.

5. **No `after_model_callback` for step-mode**: The plan only implements `before_model_callback`. An `after_model_callback` that records the completion of each step (writing to state or logging) would be valuable for the dashboard to show what happened at each step, not just that a pause occurred.
