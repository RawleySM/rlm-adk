<!-- validated: 2026-03-12 -->

# Polya State Scope Mapping

**Status:** Proposed

## Thesis

RLM-ADK should treat Polya phases as a workflow dimension carried through ADK
state scopes, not as a substitute identity axis.

The important distinction is:

- `app:` answers "what defaults does this application want"
- `user:` answers "what durable preferences or learned bias belong to this user"
- unprefixed session keys answer "what is true for this task/session"
- `temp:` answers "what is true only for this invocation and its sub-agents"

That makes `user_id = <phase>` the wrong abstraction. It would collapse the
real user identity into a transient workflow step and misuse ADK's persistence
model.

## Grounding In The Current Runtime

The current codebase already has safe tracked state mutation seams:

- `RLMOrchestratorAgent._run_async_impl()` yields `EventActions(state_delta=...)`
  at invocation start
- `reasoning_before_model()` and `reasoning_after_model()` write through
  `callback_context.state`
- `REPLTool.run_async()` writes through `tool_context.state`
- `dispatch.py` intentionally avoids direct session writes and uses local
  accumulators plus `flush_fn()`

Those are the right places to introduce Polya keys. Direct mutation of
`ctx.session.state[...]` inside dispatch-style code remains the wrong pattern.

## Recommended Scope Split

### `app:` Phase Policy

Use `app:` for house defaults that should apply to every user and every
session unless overridden.

Suggested keys:

- `app:polya:enabled`
- `app:polya:default_phase`
- `app:polya:phase_order`
- `app:polya:instruction_style`
- `app:polya:skill_defaults`
- `app:polya:transition_thresholds`

These keys belong in bootstrap configuration and should usually be written
before runs begin, not mutated frequently mid-run.

### `user:` Phase Preferences

Use `user:` for durable cross-session preferences or distilled carryover about
how this user tends to work.

Suggested keys:

- `user:polya:preferred_entry_phase`
- `user:polya:phase_bias`
- `user:polya:understand:style`
- `user:polya:plan:default_topology`
- `user:polya:implement:verification_bias`
- `user:polya:reflect:retrospective_depth`
- `user:polya:carryover`

These should store stable preferences or learned bias, not raw task history.

### Session-Scoped Task Phase State

Use unprefixed keys for the current task's chapter state.

Suggested keys:

- `polya:current_phase`
- `polya:phase_objective`
- `polya:phase_narrative_summary`
- `polya:phase_skill`
- `polya:chapter:understand`
- `polya:chapter:plan`
- `polya:chapter:implement`
- `polya:chapter:reflect`
- `polya:ledger`

This is the canonical place for the current task's narrative and control
artifacts.

### `temp:` Invocation Routing State

Use `temp:` for invocation-local transition and fanout data that should be
shared with sub-agents during the current run and then discarded.

Suggested keys:

- `temp:polya:active_phase`
- `temp:polya:phase_transition_reason`
- `temp:polya:proposed_next_phase`
- `temp:polya:child_contracts`
- `temp:polya:active_child_phase`
- `temp:polya:phase_checkpoint`

This fits ADK's invocation semantics well because sub-agents inherit the same
invocation context and therefore the same `temp:` state.

## Recommended State Model

The cleanest mental model is:

1. `app:` sets the policy envelope.
2. `user:` modifies that envelope with persistent preference.
3. session keys hold the task's current chapter state.
4. `temp:` carries the current invocation's routing and handoff details.

In practice this gives RLM-ADK a stable precedence order without having to
invent a second state system.

## Hazards And Constraints

### Do Not Rebind `user_id`

Do not assign ADK `user_id` to `understand`, `plan`, `implement`, or
`reflect`.

That would:

- destroy the semantic meaning of user-scoped persistence
- blend together unrelated users if phase names repeat
- make tracing and session history harder to interpret
- turn a workflow axis into an identity axis

The correct move is phase-qualified `user:` keys, not phase-valued `user_id`.

### Avoid Mixing Prefix Scope With `depth_key()`

The codebase already uses `depth_key(key, depth)` to create keys like
`reasoning_summary@d2`.

That mechanism is appropriate for recursion-local session telemetry, but it is
not a good default for `user:` or `app:` keys.

Recommended rule:

- allow `depth_key()` for unprefixed session keys and selective `temp:` keys
- avoid `depth_key()` for `user:` keys
- avoid `depth_key()` for `app:` keys
- if depth matters for a durable value, encode depth inside the value rather
  than in the key name

### Keep Dispatch Reads Explicit

`dispatch.py` and its child normalization helpers currently know how to read
depth-scoped session telemetry keys. They do not automatically understand new
Polya-prefixed keys.

If future dispatch logic depends on Polya state, that read path should be
extended explicitly instead of assuming new keys will be discovered by
existing helper functions.

## First Concrete Rollout

The lowest-risk first slice is:

1. Add Polya constants in `rlm_adk/state.py`.
2. Seed app/session defaults in `RLMOrchestratorAgent._run_async_impl()`.
3. Add session and `temp:` phase updates through `reasoning` callbacks and
   `REPLTool`.
4. Reserve `user:` keys for distilled preferences and carryover only after the
   phase model stabilizes.

That sequence keeps the first rollout aligned with the existing ADK-tracked
state mutation paths.
