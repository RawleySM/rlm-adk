# Gap Review: Observability

## Accuracy Check
Status: **Partially correct**.

Correct findings:
- Flat counter pollution and trace overwrite risks are valid (`rlm_adk/plugins/observability.py:152-233`, `rlm_adk/plugins/repl_tracing.py:38-45`).
- Worker event suppression currently blocks nested visibility (`rlm_adk/dispatch.py:216-219`).

Missing / under-specified findings:
- The synthesis doc does not define event-forwarding format for child events.
- It does not define how `after_agent_callback` dynamic prefix scanning avoids cross-lineage double counting (`rlm_adk/plugins/observability.py:120-127`).
- It does not define lineage rollup invariants (e.g., aggregate = sum(children)+root-local).

## Corrections Needed
- Add an explicit child-event envelope and forwarding policy.
- Add observability aggregation invariant and anti-double-counting rules.
- Define plugin migration order (observability plugin first or trace plugin first) to keep dashboards coherent.

## Required Edits for `recursive_repl.md`
1. Add `sub_agent_event` envelope schema and propagation rule.
2. Add rollup invariant definition and test assertions.
3. Add plugin migration sequencing notes.

## Priority Patch Recommendations
1. P0: Define and test rollup invariants.
2. P0: Define child event forwarding contract.
3. P1: Add plugin migration sequencing to rollout plan.
