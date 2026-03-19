<!-- validated: 2026-03-15 -->

# Interactive Dashboard Vision

This document records the current architectural resolution for an interactive
dashboard / studio environment.

## Resolution

The interactive dashboard should be implemented as a **second NiceGUI runtime
shell** over the same core RLM runtime kernel.

It should **not** be implemented by:

- overloading the ADK service registry
- forking the agent logic into a separate execution engine
- stretching the current trace-reader dashboard into a live co-resident studio

The intended split is:

- **Kernel**: orchestrator/app/runner factories, REPL construction, dispatch,
  plugins, services, state rules
- **Shells**:
  - ADK CLI shell for canonical headless runs
  - NiceGUI studio shell for interactive co-resident control

## Why This Resolution

### 1. The codebase already separates shell and kernel reasonably well

The existing runtime boundary is already close to usable:

- [`create_rlm_app()`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L459)
- [`create_rlm_runner()`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L522)
- [`RLMOrchestratorAgent._run_async_impl()`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L221)

That gives us a strong foundation for “same kernel, different shell” instead of
creating a second agent implementation.

### 2. The ADK service registry is intentionally narrow

[`services.py`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/services.py) is the
right place for session/artifact service registration, but not for dashboard
behavior or studio orchestration.

The service registry is a storage/service factory mechanism, not a UI/runtime
shell mechanism. Keeping it narrow avoids configuration drift and keeps
session/artifact services runner-agnostic.

### 3. The current live dashboard is observability-oriented

The current live dashboard is built around reconstructed snapshots from:

- `.adk/traces.db`
- `.adk/context_snapshots.jsonl`
- `.adk/model_outputs.jsonl`

See:

- [`LiveDashboardLoader`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_loader.py)
- [`live_app.py`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py)
- [`live_models.py`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_models.py)

That is the right substrate for replay/debugging, but the wrong substrate for:

- direct manipulation of live Python objects
- synchronous-feeling HITL pauses
- interactive mutation of agent-owned runtime objects
- rendering generated sub-apps into the agent’s active execution context

So the studio shell should be a sibling shell, not an incremental mutation of
the current trace-reader.

## Why CLI Remains Canonical For Headless Runs

The primary headless entrypoint remains:

```bash
.venv/bin/adk run rlm_adk
```

Reasons:

- it is the documented primary entrypoint
- the CLI auto-discovers [`services.py`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/services.py)
- the CLI path is the cleanest canonical runtime for automation, replay,
  testing, and non-interactive use

The studio shell should not replace that path. It should add a co-resident
interactive mode on top of the same kernel.

## Current Replay Caveat

The current dashboard replay launcher is **in-process**, not CLI-based.

See:

- [`run_service.py`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/run_service.py)

It creates a `Runner` programmatically and executes replay queries through
`runner.run_async(...)`.

That is a real run, but it is not necessarily identical to:

```bash
.venv/bin/adk run --replay <file>.json rlm_adk
```

So there is currently a **parity caveat**:

- dashboard replay uses an in-process runner path
- canonical replay semantics are still defined by `adk run --replay`

This is not necessarily wrong, but it must be documented clearly.

## Studio Shell Requirements

The interactive NiceGUI studio shell will likely need the following runtime
primitives.

### 1. Control Plane

A studio-aware control plane should carry user steering decisions such as:

- prompt overrides
- skill selection changes
- state-key highlights
- context masking / deselection
- next-invocation earmarks
- approval / resume signals

This should be explicit runtime plumbing, not an ad hoc collection of UI hacks.

The narrowest existing seam is alongside `instruction_router` and related
runtime wiring in:

- [`create_rlm_orchestrator()`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L279)
- [`RLMOrchestratorAgent`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L208)

### 2. Live Object Handles

Direct manipulation requires object identity, but the current REPL tool boundary
only exposes JSON-serializable locals.

See:

- [`LocalREPL`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/local_repl.py)
- [`REPLTool`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py)

The studio shell will need a persistent object-handle registry so that:

- the REPL can keep real Python objects alive
- the UI can bind to handles
- traces/state can store summaries and IDs rather than raw mutable objects

### 3. UI Bridge

The REPL should not be given raw unrestricted access to NiceGUI globals.

Instead, the studio shell should expose a narrow bridge such as:

- render preview
- mount object editor
- update known surface
- publish inspectable object handle

This keeps UI lifecycle and REPL lifecycle separated cleanly.

### 4. HITL Async Gates

Human-in-the-loop pauses should be implemented as explicit async gates, not by
trying to block arbitrary sync execution.

The current async REPL path is the right substrate:

- [`LocalREPL.execute_code_async(...)`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/local_repl.py)

The studio shell should offer primitives equivalent to:

- approve / reject
- edit then resume
- choose among branches
- pause at checkpoint

These should be modeled as awaited runtime primitives from the agent’s
perspective, even if the implementation is an async future resolved by the UI.

## State And Replayability Constraints

The studio must respect AR-CRIT-001:

- do not mutate `ctx.session.state[...]` directly in dispatch closures
- use `tool_context.state[...]`
- use `callback_context.state[...]`
- use `EventActions(state_delta=...)`

See:

- [`dispatch.py`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py)
- [`state.py`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py)
- [`rlm_adk_docs/dispatch_and_state.md`](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/dispatch_and_state.md)

For the studio, this means:

- user steering should be append-only and traceable
- “remove from context” should usually mean **mask**, not delete
- state edits should be applied at explicit boundaries or checkpoints
- current-invocation vs next-invocation semantics must be explicit

## Major Gotchas Discovered This Session

### 1. Shared mutable app/orchestrator instances are risky

The orchestrator mutates the live reasoning agent’s tools/callbacks at runtime.
That is fine per invocation, but a co-resident studio shell should avoid sharing
singleton runtime instances casually.

### 2. The current live dashboard is snapshot-oriented

Its models are shaped for observation, not mutation. A studio shell will need
its own mutable controller state and likely a different data provider boundary.

### 3. Prompt-visible skill selection is not full runtime isolation

The current `enabled_skills` work controls prompt injection and traced display,
but does not fully sandbox runtime helper availability. That distinction should
remain clear.

### 4. Mid-dispatch mutation is dangerous

Changing active prompt/context state while child dispatch is in flight risks
split-brain behavior between root state, child state, and later REPL turns.

### 5. Empty-state / fallback semantics need care

Loaders that treat empty values as “missing” may accidentally erase intentional
user choices such as an empty selected-skill set.

## Practical Design Direction

The practical direction is:

1. keep the CLI shell canonical for headless runs
2. keep one shared runtime kernel
3. add a second NiceGUI studio shell for co-resident interaction
4. introduce explicit studio primitives:
   - control plane
   - live object handles
   - UI bridge
   - async HITL gates
5. keep observability dashboards read-oriented
6. avoid collapsing service registration, runtime kernel, and UI shell into one
   abstraction

## Bottom Line

The interactive dashboard should become a **second NiceGUI runtime shell over
the same core kernel**.

This preserves:

- one execution model
- one set of core factories
- one headless canonical path

while making room for:

- direct manipulation
- co-resident editing
- async HITL control
- object-aware UI bindings

without overloading the ADK service registry or forking the agent logic.
