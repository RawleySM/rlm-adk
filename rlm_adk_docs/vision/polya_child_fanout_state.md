<!-- validated: 2026-03-12 -->

# Polya Child And Fanout State

**Status:** Proposed

## Thesis

The strongest place to use ADK's scoped state for Polya is not just the parent
phase label. It is the handoff boundary between planning, child dispatch, and
reflection.

RLM-ADK already has a natural separation:

- the parent carries the narrative and phase state
- planning produces work packets and child contracts
- dispatch runs children concurrently
- reflection synthesizes their outputs

Scoped state should reinforce that structure.

## Grounding In The Current Runtime

Relevant properties of the current runtime:

- `dispatch.py` uses local accumulators and `flush_fn()` to avoid unsafe
  direct session mutation
- `REPLTool` flushes those accumulators into `tool_context.state`
- child orchestrators run under the same invocation context
- ADK `temp:` state is shared across sub-agents in the same invocation
- child result normalization reads explicit output and observability keys, not
  arbitrary new prefixes

This means the easiest place to thread Polya child state is through:

- `temp:` keys for invocation-local contracts and routing
- session keys for parent chapter state
- explicit prompt payloads for child-specific work

## Recommended Split

### Session Keys For Parent Chapter State

Keep the parent's active chapter and durable task narrative in session state:

- `polya:current_phase`
- `polya:phase_objective`
- `polya:phase_narrative_summary`
- `polya:chapter:*`
- `polya:ledger`

Children may read these keys as shared task context.

### `temp:` Keys For Planning Output

Use `temp:` for per-invocation planning artifacts that are only needed during
the current dispatch wave:

- `temp:polya:child_contracts`
- `temp:polya:merge_strategy`
- `temp:polya:verification_requirements`
- `temp:polya:active_child_phase`
- `temp:polya:fanout_reason`

These keys are especially attractive because they automatically disappear after
the invocation and are visible to all sub-agents in that invocation tree.

### Explicit Child Prompt Material

Do not assume children will discover all needed Polya information by reading
shared state indirectly.

The parent should still assemble explicit child prompts that include:

- the local work packet
- the required output contract
- the relevant narrative chapter summary
- the current child phase or transition reason

Shared state should support that handoff, not replace it.

## Recommended Planning Pattern

### Plan Phase

During planning:

- write `polya:current_phase = "plan"`
- write a session-scoped chapter summary
- write `temp:polya:child_contracts`
- write `temp:polya:merge_strategy`
- optionally write `temp:polya:active_child_phase = "implement"`

### Child Dispatch

When `llm_query()` or `llm_query_batched()` fans out:

- children inherit the invocation's `temp:` routing state
- children also see the session chapter state
- child-specific prompt text supplies exact local instructions

### Reflect Phase

After child results return:

- parent reads normalized child outputs
- parent updates `polya:chapter:reflect`
- parent clears or overwrites invocation-local routing hints on the next run

This yields a clean contract boundary:

- session state records the task's story
- `temp:` state records the current dispatch wave

## Observability Implications

The current observability and tracing stack will not automatically understand
new Polya keys semantically, but the state values will still exist in session
state if written through tracked channels.

Practical implications:

- new Polya keys written through `tool_context.state` or `callback_context.state`
  are safe
- direct writes in ad hoc session-mutation paths should be avoided for core
  phase control
- if trace summaries need Polya-specific columns later, `sqlite_tracing.py`
  should be extended explicitly rather than relying on generic state dumps

## Depth And Recursion Guidance

Avoid making prefixed Polya keys depth-suffixed by default.

Recommended rule:

- shared session chapter keys stay unscoped by depth
- shared `temp:` routing keys stay unscoped by depth unless there is a proven
  collision problem
- recursion-specific telemetry remains in the existing `depth_key(...)` family

If depth-specific Polya state becomes necessary, prefer storing depth inside a
structured value:

```python
{
    "phase": "implement",
    "child_depth": 2,
    "fanout_idx": 1,
    "contract_id": "packet-3"
}
```

That preserves readability and avoids overloading key syntax.

## First Concrete Rollout

The cleanest first implementation path is:

1. introduce session keys for chapter state
2. introduce `temp:` keys for child contracts and transition reasons
3. surface a short Polya summary in the dynamic instruction
4. keep child prompt assembly explicit
5. add Polya-specific tracing columns only if the state model proves useful

That rollout gives immediate leverage in planning and fanout without forcing a
premature redesign of dispatch internals.
