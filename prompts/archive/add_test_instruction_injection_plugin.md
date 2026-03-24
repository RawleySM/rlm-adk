<!-- generated: 2026-03-18 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Add Test Instruction Injection Plugin for Depth/Iteration-Aware Fixture Steering

## Context

The current provider-fake fixture for recursive dispatch (`fake_recursive_ping.json`) embeds all lower-layer prompts (layer-1, layer-2) into the layer-0 code block. This is fragile, couples depth layers unnecessarily, and prevents independent evaluation of each recursion depth. The codebase has an unwired `{test_context?}` placeholder in `RLM_DYNAMIC_INSTRUCTION` (line 112 of `rlm_adk/utils/prompts.py`) and an existing `instruction_router: Callable[[int, int], str]` that fires once at orchestrator init — but nothing that injects per-model-call instructions keyed on `(depth, iteration, fanout_idx)`. A new `BasePlugin` subclass will fill this gap.

## Original Transcription

> Build a custom plugin based on the Google ADK plug in base model that allows me to in test mode, specifically replay and fake provider fixture test modes allows me to build different dynamic instruction injection state keys that would help us build different fixtures that can evaluate the system through different depths and iterations. Specifically, the callback would be tied to fire at various iterations based off of the current state key value for depth or fan out or number of turns whatever we want for that fixture. But essentially, it would allow us to inject certain prompts that would then move the test fixture or the test, execution different recursive layers or fan out layers or iterations based off of what we're trying to evaluate. For example, I would like to be able to more easily run a live API call that's similar to recursive ping, but not rely on delivering the code that the lower layers at layer two or layer three or four would need into the original layer zero prompt, which is what we're currently doing. So in this callback, we would be able to programmatically, inject a instruction for what code the model should run. Based on the depth that it currently is at, and thereby without exposing lower depths prompts into the, original prompt of the parent model can, have more control over steering the system.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn a `State-Key` teammate to wire the `test_context` state key constant and add it to `state.py`.**

   Add `DYN_TEST_CONTEXT = "test_context"` to `rlm_adk/state.py` in the "Dynamic Instruction State Keys" section (after line 41). This activates the already-present `{test_context?}` placeholder in `RLM_DYNAMIC_INSTRUCTION` (line 112 of `rlm_adk/utils/prompts.py`). No template changes needed — the placeholder is already there.

   **Constraint:** AR-CRIT-001 — only write this key via `callback_context.state` (in a plugin `before_model_callback`) or `EventActions(state_delta={})`. Never via `ctx.session.state[key] = value`.

2. **Spawn a `Plugin-Core` teammate to create `rlm_adk/plugins/test_instruction_injection.py` with a `TestInstructionInjectionPlugin(BasePlugin)` class.**

   The plugin accepts a `instruction_map` configuration: a dict keyed by `(depth: int, iteration: int | None, fanout_idx: int | None)` tuples mapping to instruction strings. `None` values act as wildcards (match any). The plugin implements `before_model_callback` which:

   a. Reads `CURRENT_DEPTH` from `callback_context.state` (state key `"current_depth"`)
   b. Reads `ITERATION_COUNT` from `callback_context.state` using `depth_key(ITERATION_COUNT, depth)` to get the depth-scoped iteration count
   c. Reads fanout index — the plugin stores it from `before_agent_callback` by inspecting the agent name suffix (`child_orchestrator_d{N}` naming convention) or from a dedicated state key
   d. Performs a lookup against `instruction_map` with cascading specificity: exact `(depth, iteration, fanout)` → `(depth, iteration, None)` → `(depth, None, None)` → no injection
   e. If a match is found, writes the instruction string to `callback_context.state["test_context"]` (the `DYN_TEST_CONTEXT` key)
   f. Returns `None` (observe-only, does not short-circuit)

   The plugin fires globally (on all agents including children at any depth) because `BasePlugin` callbacks apply to all agents in the runner. This is the key advantage over `instruction_router` which only fires once at orchestrator init.

   **Important design details:**
   - The plugin should also accept a plain `Callable[[int, int, int], str | None]` as an alternative to the dict, for programmatic instruction generation
   - Include a `verbose: bool = False` flag that logs each injection at DEBUG level for fixture debugging
   - The plugin name should be `"test_instruction_injection"`

3. **Spawn a `Factory-Wire` teammate to wire the plugin into the factory chain in `rlm_adk/agent.py`.**

   Add a `test_instruction_plugin` parameter to `create_rlm_runner()` (line 542) and `create_rlm_app()` (line 477). When provided, append the plugin to the plugins list. Thread the parameter through `_default_plugins()` as well, gated on `os.getenv("RLM_TEST_MODE")` or explicit parameter passing — this ensures the plugin is never accidentally active in production.

   *[Added — the transcription didn't mention factory wiring, but the plugin must be injectable through the standard `create_rlm_runner()` / `create_rlm_app()` factory chain to work in provider-fake tests, which use `create_rlm_runner()`.]*

4. **Spawn a `Fixture-Refactor` teammate to create a new provider-fake fixture `tests_rlm_adk/fixtures/provider_fake/recursive_ping_injected.json` that demonstrates the plugin.**

   This fixture replicates `fake_recursive_ping.json` but with a critical difference: the layer-0 code block dispatches `llm_query(prompt)` with a **generic** prompt (e.g., "Process the task according to your instructions") — NOT the full layer-1/layer-2 code. The `TestInstructionInjectionPlugin` injects depth-specific instructions via `{test_context?}` at each layer:

   - Depth 0: "You are the root layer. Dispatch one `llm_query()` to a child. Print the child's result."
   - Depth 1: "You are layer 1. Dispatch one `llm_query()` to a child. Forward the child's response."
   - Depth 2: "You are the terminal layer. Return JSON `{\"my_response\": \"pong\", \"your_response\": \"ping\"}`."

   The fixture's `config` section should include an `instruction_map` that the test's contract runner reads and passes to `TestInstructionInjectionPlugin`. The canned model responses should reference `_rlm_state` for state introspection, same as the existing `fake_recursive_ping.json` pattern.

5. **Spawn a `Contract-Test` teammate to write the contract test in `tests_rlm_adk/test_provider_fake_e2e.py` (or a new dedicated test file) that exercises the new fixture.**

   The test should:
   - Construct a `TestInstructionInjectionPlugin` with an instruction map matching the fixture
   - Pass it to `create_rlm_runner()` via the new parameter
   - Assert `final_answer` contains "pong" (same as `fake_recursive_ping`)
   - Assert the layer-0 code block does NOT contain layer-1 or layer-2 prompts (the whole point — verify isolation)
   - Assert `CURRENT_DEPTH` reaches 2 (3-layer recursion happened)
   - Assert `test_context` state key was populated at each depth

## Provider-Fake Fixture & TDD

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/recursive_ping_injected.json`

**Essential requirements the fixture must capture:**
- The layer-0 prompt dispatches `llm_query()` with a generic prompt, NOT embedded child code — this proves depth-layer isolation (the core value prop)
- Each layer's canned response references the injected `test_context` instruction, proving the dynamic instruction was visible to the model at each depth
- The fixture exercises 3 depths (0, 1, 2) to validate that plugin injection propagates through child orchestrator creation via `create_dispatch_closures()` → `create_child_orchestrator()`
- The terminal layer (depth 2) returns structured JSON without being told the schema by the parent — it gets the schema from the plugin's injected instruction

**TDD sequence:**
1. Red: Write test asserting `DYN_TEST_CONTEXT` exists in `state.py`. Run, confirm failure (constant doesn't exist yet).
2. Green: Add `DYN_TEST_CONTEXT = "test_context"` to `state.py`. Run, confirm pass.
3. Red: Write test instantiating `TestInstructionInjectionPlugin` with a simple instruction map and asserting its `before_model_callback` writes to `callback_context.state["test_context"]`. Run, confirm failure (plugin doesn't exist).
4. Green: Create the plugin with minimal `before_model_callback`. Run, confirm pass.
5. Red: Write the full e2e contract test with the `recursive_ping_injected` fixture. Run, confirm failure (fixture doesn't exist / responses not matched).
6. Green: Create the fixture JSON and wire the plugin in the test. Run, confirm pass.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the implementation works end-to-end.

## Considerations

- **Plugin fires globally including on workers:** `BasePlugin` callbacks fire on all agents in the runner, including child orchestrators spawned by dispatch. This means the plugin's `before_model_callback` will fire for depth-1 and depth-2 children automatically — no special threading needed. However, the `CURRENT_DEPTH` state key is set per-orchestrator in `_run_async_impl` (line 326 of `orchestrator.py`), so it should be readable at any depth.

- **Interaction with `instruction_router`:** The existing `instruction_router` writes to `DYN_SKILL_INSTRUCTION` (the `{skill_instruction?}` placeholder), while this plugin writes to `test_context` (the `{test_context?}` placeholder). They are orthogonal — both can be active simultaneously. The plugin should NOT write to `DYN_SKILL_INSTRUCTION` to avoid conflicts.

- **AR-CRIT-001 compliance:** The plugin writes state ONLY via `callback_context.state["test_context"]` in `before_model_callback`. This is a tracked mutation path. No `ctx.session.state` writes.

- **`depth_key()` for iteration reads:** At depth > 0, the iteration count is stored at `iteration_count@d{N}` (via `depth_key(ITERATION_COUNT, depth)`). The plugin must use `depth_key()` when reading iteration count, not the raw `ITERATION_COUNT` key.

- **Workers don't see plugins' before_model_callback for the reasoning agent:** Workers (child orchestrators) run their own `reasoning_agent` with their own `before_model_callback`. The *plugin's* `before_model_callback` fires globally for all agents though (plugin callbacks take precedence over agent callbacks per ADK docs). Verify that the plugin's `before_model_callback` fires on child reasoning agents, not just the root.

- **Live API compatibility:** While primarily designed for test mode, nothing prevents using this plugin with live API calls. The user mentioned wanting to "more easily run a live API call that's similar to recursive ping" — the plugin would work identically in live mode, steering each depth layer programmatically.

## NiceGUI Dashboard Integration: Interactive `test_context` Editing via StepModePlugin

> **Bret Victor "Inventing on Principle" extension:** Rather than treating the `TestInstructionInjectionPlugin` as a static config-driven tool, extend the existing `StepModePlugin` + NiceGUI dashboard so the user can **see, edit, and inject** `test_context` for any paused agent (parent or child, at any depth) before unpausing the ADK flow into the model call. This turns the dashboard from a read-only observer into a direct-manipulation steering wheel for recursive evaluation.

### Mechanism: `StepGate` State Handoff Buffer

The existing `StepGate` (`rlm_adk/step_gate.py`, L8-61) already blocks the ADK flow via `asyncio.Event.wait()` in `StepModePlugin.before_model_callback` (`rlm_adk/plugins/step_mode.py`, L18-39). NiceGUI runs in the **same Python process and event loop**, so the dashboard remains responsive while the agent is blocked.

The extension adds two new attributes to `StepGate`:
- `_pending_state_delta: dict[str, Any]` — the dashboard writes the user's edits here before calling `advance()`
- `_snapshot_state: dict[str, Any]` — the plugin snapshots readable state (depth, iteration, current `test_context`) here before blocking, so the dashboard can display it

**Data flow:**

```
StepModePlugin.before_model_callback
  ① Snapshot callback_context.state → step_gate._snapshot_state
     (test_context, current_depth, iteration_count@dN)
  ② await step_gate.wait_for_advance()  ← BLOCKED on asyncio.Event
        .
        . (same event loop, NiceGUI ui.timer fires every 0.25s)
        .
  Dashboard poll: reads step_gate.waiting == True
  Dashboard renders:
     ┌──────────────────────────────────────────────────────┐
     │ Paused: child_reasoning_d1 @ depth 1                │
     │ ──────────────────────────────────────────────────── │
     │ test_context (instruction for this agent):           │
     │ ┌──────────────────────────────────────────────────┐ │
     │ │ You are layer 1. Dispatch one llm_query() to a  │ │
     │ │ child. Forward the child's response.             │ │
     │ │ [editable ui.textarea, pre-filled from snapshot] │ │
     │ └──────────────────────────────────────────────────┘ │
     │                                                      │
     │  [Apply & Advance]   [Advance (no edit)]   [Skip]   │
     └──────────────────────────────────────────────────────┘
  User edits textarea, clicks "Apply & Advance"
        .
  ③ Dashboard: step_gate._pending_state_delta["test_context"] = new_text
  ④ Dashboard: step_gate.advance() → asyncio.Event.set()
        .
  StepModePlugin resumes:
  ⑤ pending = step_gate.consume_pending_state()
  ⑥ callback_context.state["test_context"] = pending["test_context"]
     ↑ AR-CRIT-001 compliant: only mutation path is callback_context.state
  ⑦ Returns None → ADK resolves {test_context?} → model call proceeds
```

### Files to Modify (No New Files)

6. **Spawn a `Gate-Extend` teammate to add `pending_state_delta` and `snapshot_state` to `rlm_adk/step_gate.py`.**

   Add to `StepGate.__init__` (L11-16):
   - `self._pending_state_delta: dict[str, Any] = {}`
   - `self._snapshot_state: dict[str, Any] = {}`

   Add methods:
   - `set_pending_state(key: str, value: Any)` — dashboard calls before `advance()`
   - `consume_pending_state() -> dict[str, Any]` — plugin calls after `_event.wait()` returns; returns dict and clears it
   - `set_snapshot_state(state: dict[str, Any])` — plugin calls when entering wait
   - Property `snapshot_state -> dict[str, Any]` — dashboard reads this

   ~20 lines. No behavioral change to existing `advance()` / `wait_for_advance()` signatures.

7. **Spawn a `Plugin-Pause` teammate to extend `StepModePlugin.before_model_callback` in `rlm_adk/plugins/step_mode.py`.**

   Before `await step_gate.wait_for_advance()` (L38), snapshot relevant state:
   ```
   step_gate.set_snapshot_state({
       "test_context": callback_context.state.get("test_context", ""),
       "current_depth": depth,
       "iteration_count": callback_context.state.get(depth_key(ITERATION_COUNT, depth), 0),
   })
   ```

   After `wait_for_advance()` returns, consume pending edits and write them via the tracked mutation path:
   ```
   pending = step_gate.consume_pending_state()
   for key, value in pending.items():
       callback_context.state[key] = value
   ```

   ~15 lines added. AR-CRIT-001 compliance: all state writes go through `callback_context.state[key]`, never `ctx.session.state`.

8. **Spawn a `Dashboard-UI` teammate to extend `_step_mode_controls()` in `rlm_adk/dashboard/live_app.py` (L540-561).**

   When `controller.state.step_mode_waiting` is True, render below the existing "Next Step" button:
   - `ui.textarea` pre-filled from `controller.state.step_mode_snapshot.get("test_context", "")`, bound to a local reactive variable
   - A read-only state panel (collapsible `ui.expansion`) showing depth, iteration, agent name from the snapshot
   - "Apply & Advance" button that calls `controller.apply_and_advance(textarea_value)` then `live_ui.refresh_all()`
   - Rename existing "Next Step" to "Advance (no edit)" for clarity when textarea is visible

   ~40 lines. The existing button remains as the no-edit fast path.

9. **Spawn a `Controller-Wire` teammate to add `apply_and_advance()` and snapshot sync to `rlm_adk/dashboard/live_controller.py`.**

   Add to `LiveDashboardController`:
   - `apply_and_advance(text: str)` method: writes `step_gate.set_pending_state("test_context", text)` then calls `step_gate.advance()`
   - In the poll method (L157-165), sync `step_gate.snapshot_state` into `self.state.step_mode_snapshot`

   Add to `LiveDashboardState` in `live_models.py` (after L343):
   - `step_mode_snapshot: dict[str, Any] = field(default_factory=dict)`

   ~15 lines across two files.

### Plugin Ordering: StepModePlugin Must Be Last

**Critical:** If both `TestInstructionInjectionPlugin` and `StepModePlugin` are active, `TestInstructionInjectionPlugin` runs first (writes `test_context` from its `instruction_map`), then `StepModePlugin` runs last (user can see what was injected and override it). Register `StepModePlugin` as the **last plugin** in the plugin list so its `before_model_callback` fires last and user edits take final precedence.

### AR-CRIT-001 Compliance

The dashboard **never** writes to ADK session state directly. It writes to a plain Python dict (`step_gate._pending_state_delta`) which is an out-of-band staging buffer. Only `StepModePlugin.before_model_callback` writes to `callback_context.state[key]` — one of the four approved mutation paths. The snapshot read (`callback_context.state.get(...)`) is always safe.

### Edge Cases

- **Child agents at depth > 0:** The plugin fires globally. When a depth-2 child pauses, the dashboard shows that child's depth, name, and `test_context`. The user injects a depth-specific instruction. Works correctly because `callback_context.state` is scoped to the paused agent's invocation context.
- **Empty textarea:** Writing `""` to `test_context` effectively removes the instruction for that model call — `{test_context?}` resolves to empty. This is valid behavior.
- **`TestInstructionInjectionPlugin` interaction:** If active, the user sees the instruction_map's value pre-filled in the textarea (since `TestInstructionInjectionPlugin` ran first and wrote to state). The user can accept it (click "Advance (no edit)") or override it (edit and click "Apply & Advance").
- **Long pause:** Safe — the ADK runner is blocked, no other agent activity occurs, snapshot state is frozen. NiceGUI remains responsive (same event loop, different coroutine).

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/state.py` | `CURRENT_DEPTH` | L14 | State key for current depth — plugin reads this |
| `rlm_adk/state.py` | `ITERATION_COUNT` | L15 | State key for iteration count — plugin reads this (depth-scoped) |
| `rlm_adk/state.py` | `DYN_SKILL_INSTRUCTION` | L41 | Existing dynamic instruction key — plugin must NOT write to this |
| `rlm_adk/state.py` | `depth_key()` | L214 | Depth-scoping helper — plugin uses for iteration reads |
| `rlm_adk/utils/prompts.py` | `RLM_DYNAMIC_INSTRUCTION` | L109 | Dynamic instruction template — already contains `{test_context?}` placeholder |
| `rlm_adk/plugins/observability.py` | `ObservabilityPlugin` | L50 | Reference implementation for BasePlugin subclass in this codebase |
| `rlm_adk/orchestrator.py` | `RLMOrchestratorAgent` | L199 | Orchestrator — seeds `CURRENT_DEPTH` at L326 |
| `rlm_adk/orchestrator.py` | `instruction_router` field | L227 | Existing instruction routing — orthogonal to plugin |
| `rlm_adk/orchestrator.py` | `_run_async_impl` | L230 | Where initial state (including CURRENT_DEPTH) is seeded |
| `rlm_adk/dispatch.py` | `create_dispatch_closures()` | L168 | Dispatch closure factory — threads `instruction_router` to children |
| `rlm_adk/agent.py` | `create_rlm_runner()` | L542 | Runner factory — needs new `test_instruction_plugin` parameter |
| `rlm_adk/agent.py` | `create_rlm_app()` | L477 | App factory — needs new parameter |
| `rlm_adk/agent.py` | `create_child_orchestrator()` | L339 | Child factory — plugin fires globally, no change needed here |
| `rlm_adk/callbacks/reasoning.py` | `reasoning_before_model()` | L105 | Production before_model callback — plugin fires BEFORE this (plugin precedence) |
| `rlm_adk/callbacks/reasoning.py` | `reasoning_test_state_hook()` | L221 | Existing test-only hook — similar pattern, writes to state in before_model |
| `tests_rlm_adk/fixtures/provider_fake/fake_recursive_ping.json` | fixture | L1 | Current fixture with embedded layer prompts — the problem being solved |
| `tests_rlm_adk/fixtures/provider_fake/instruction_router_fanout.json` | fixture | L1 | Existing instruction_router test fixture — reference for fixture structure |
| `ai_docs/adk_api_reference.md` | `BasePlugin` | L631 | ADK BasePlugin API — callback signatures |
| `rlm_adk/step_gate.py` | `StepGate` | L8 | Async gate primitive — extend with pending_state_delta and snapshot_state |
| `rlm_adk/step_gate.py` | `step_gate` (singleton) | L61 | Process-global gate instance shared by plugin and dashboard |
| `rlm_adk/plugins/step_mode.py` | `StepModePlugin` | L12 | Plugin that pauses before each model call — extend with snapshot/consume logic |
| `rlm_adk/plugins/step_mode.py` | `before_model_callback` | L18 | Where snapshot + consume pending state logic is added |
| `rlm_adk/dashboard/live_app.py` | `_step_mode_controls()` | L540 | NiceGUI function rendering step-mode UI — extend with textarea + Apply button |
| `rlm_adk/dashboard/live_controller.py` | `advance_step()` | L196 | Existing advance method — add `apply_and_advance()` alongside it |
| `rlm_adk/dashboard/live_controller.py` | poll step-gate sync | L157 | Where snapshot_state sync is added |
| `rlm_adk/dashboard/live_models.py` | `LiveDashboardState` | L341 | Add `step_mode_snapshot: dict` field after existing step_mode fields |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow branch links for **Observability**, **Testing**, and **Dispatch & State**)
3. `rlm_adk/plugins/observability.py` — reference BasePlugin implementation in this codebase
4. `rlm_adk/callbacks/reasoning.py:221` — `reasoning_test_state_hook()` for the existing test-only state injection pattern
5. `ai_docs/adk_api_reference.md:631` — BasePlugin callback signatures
6. `rlm_adk/step_gate.py` — existing async gate primitive (extend, don't replace)
7. `rlm_adk/plugins/step_mode.py` — existing step-mode plugin (extend with snapshot/consume)
8. `rlm_adk/dashboard/live_app.py:540` — `_step_mode_controls()` (extend with textarea UI)
9. `rlm_adk_docs/vision/inventing_on_principle_dashboard/NiceGUI_agent_dashboard_ideas.md` — Bret Victor design principles for direct manipulation
