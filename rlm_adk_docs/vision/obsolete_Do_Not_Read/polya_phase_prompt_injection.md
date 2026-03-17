<!-- validated: 2026-03-12 -->

# Polya Phase Prompt Injection

**Status:** Proposed

## Thesis

The lowest-risk way to make Polya phases operational in RLM-ADK is to use the
dynamic instruction channel that already exists.

Today the runtime already works like this:

1. `RLMOrchestratorAgent` seeds initial state through `EventActions(state_delta=...)`
2. `LlmAgent(instruction=RLM_DYNAMIC_INSTRUCTION)` asks ADK to resolve
   `{key?}` placeholders from session state
3. `reasoning_before_model()` extracts the resolved dynamic instruction from
   `contents` and relocates it into `system_instruction`

That means Polya phase steering can be added without rewriting the basic agent
architecture.

## Existing Seam

Current dynamic instruction placeholders are minimal:

- `{repo_url?}`
- `{root_prompt?}`
- `{test_context?}`

This is a good sign. The seam is already narrow and can absorb Polya metadata
incrementally.

## Proposed Dynamic Instruction Expansion

Extend `RLM_DYNAMIC_INSTRUCTION` with optional Polya placeholders such as:

- `{app:polya:instruction_style?}`
- `{app:polya:default_phase?}`
- `{app:polya:phase_order?}`
- `{user:polya:preferred_entry_phase?}`
- `{user:polya:phase_bias?}`
- `{polya:current_phase?}`
- `{polya:phase_objective?}`
- `{polya:phase_narrative_summary?}`
- `{polya:phase_skill?}`
- `{temp:polya:phase_transition_reason?}`
- `{temp:polya:proposed_next_phase?}`

These values should stay short. The narrative itself should remain in chapter
artifacts and REPL state, not be duplicated wholesale into the dynamic
instruction.

## Recommended Prompt Shape

The dynamic instruction should communicate four layers:

1. app defaults
2. user preference
3. current session phase
4. current invocation transition hint

An example shape:

```text
Repository URL: {repo_url?}
Original query: {root_prompt?}

Polya app defaults:
- enabled: {app:polya:enabled?}
- default_phase: {app:polya:default_phase?}
- phase_order: {app:polya:phase_order?}
- instruction_style: {app:polya:instruction_style?}

Polya user preferences:
- preferred_entry_phase: {user:polya:preferred_entry_phase?}
- phase_bias: {user:polya:phase_bias?}

Polya session chapter:
- current_phase: {polya:current_phase?}
- objective: {polya:phase_objective?}
- narrative_summary: {polya:phase_narrative_summary?}
- active_skill: {polya:phase_skill?}

Polya invocation transition:
- transition_reason: {temp:polya:phase_transition_reason?}
- proposed_next_phase: {temp:polya:proposed_next_phase?}
```

## Why This Fits The Current Code

This proposal aligns with existing behavior:

- the orchestrator already seeds initial state before the first reasoning turn
- the reasoning callback already re-reads the resolved dynamic instruction on
  each model call
- session or `temp:` keys written between calls will therefore affect the next
  model turn automatically

This avoids inventing a new instruction transport path.

## Recommended Mutation Flow

### Invocation Start

At invocation start, seed:

- `app:polya:*` defaults if they are not already present
- `polya:current_phase`
- `polya:phase_objective`
- `temp:polya:phase_transition_reason = "initial invocation"`

This belongs in `RLMOrchestratorAgent._run_async_impl()`.

### Phase Change During Reasoning

When the reasoning loop transitions phases, write updated values through a
tracked state channel:

- `callback_context.state[...]` in callbacks
- `tool_context.state[...]` in tools
- `EventActions(state_delta=...)` when the orchestrator itself emits a phase
  transition event

The next reasoning call will see the new values through the existing dynamic
instruction template.

### Child Runs

Children will inherit session and `temp:` state unless the parent explicitly
changes it before dispatch. That is useful, but it should be deliberate.

For child-specific phase context, prefer:

- shared session chapter state for the common narrative
- `temp:polya:active_child_phase` for the invocation-local child task
- child contract payloads for exact output requirements

## What Should Not Go Into The Dynamic Instruction

Do not use the dynamic instruction as a dumping ground for:

- entire chapter memos
- full work packet arrays
- large child contract schemas
- deep observability payloads

Those belong in session state, REPL variables, or explicit prompt assembly by
skills, not in the lightweight instruction template.

## Follow-On Step

If the team later wants more control than `{key?}` placeholders provide, the
next step is to replace the string template with an `InstructionProvider`.

That would allow:

- custom formatting
- precedence resolution in Python
- selective omission of noisy keys
- richer formatting of user/app/session/temp overlays

But it is not required for the first Polya state rollout. The existing dynamic
instruction path is sufficient.
