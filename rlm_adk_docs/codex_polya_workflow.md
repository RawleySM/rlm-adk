# Polya Workflow Proposals for `rlm_adk`

## Purpose

This document proposes three different implementations of Polya's method for `rlm_adk`, grounded in the current architecture's strengths:

- recursively called child orchestrators
- persistent REPL execution with tiny-step verification
- Google ADK callback and plugin interception surfaces
- rich state and event mutation semantics
- strong depth-aware observability

The goal is not to paste "understand, plan, carry out, look back" into prompts. The goal is to make those phases real runtime machinery.

## Architectural Baseline

The current system already has the right primitives for a strong Polya implementation:

- The orchestrator delegates to a reasoning agent and wires `execute_code` plus `set_model_response` at runtime in [rlm_adk/orchestrator.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L216).
- REPL execution is persistent, supports async child dispatch via AST rewrite, and records execution summaries in [rlm_adk/tools/repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L93).
- Child recursion already happens through full child orchestrators in [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L306), not thin worker calls.
- Reasoning callbacks already compose system instruction, token accounting, visible output, thought text, and finish reasons in [rlm_adk/callbacks/reasoning.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py#L109).
- Dispatch already emits per-child summaries, nested retry metrics, structured-output outcomes, and batch telemetry in [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L478).
- State keys are already depth-aware where it matters in [rlm_adk/state.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L137).

This means Polya should be implemented as a control layer over existing runtime surfaces, not as a replacement for them.

## Design Principle

Polya in a REPL system should mean:

1. `Understand` is explicit uncertainty and problem framing.
2. `Plan` is explicit decomposition into testable next steps.
3. `Carry Out` is execution in short REPL turns with observable evidence.
4. `Look Back` is enforced reflection over evidence, assumptions, and failure modes before finalization or recursion.

That maps naturally onto the existing `reasoning -> execute_code -> child dispatch -> reflection/final answer` loop described in [ai_docs/Polya_workflow_in_REPL.md](/home/rawley-stanhope/dev/rlm-adk/ai_docs/Polya_workflow_in_REPL.md#L7) and [rlm_adk_docs/architecture_summary.md](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/architecture_summary.md).

---

## Proposal 1: Phase-Tagged Single Orchestrator

### Core Idea

Keep the current collapsed orchestrator architecture, but make Polya explicit as depth-scoped runtime state, structured checkpoints, and mandatory reflection after each REPL turn.

### How It Works

- `Understand` becomes a required state object at the start of each reasoning turn.
  - Suggested fields: `task_restatement`, `knowns`, `unknowns`, `assumptions`, `candidate_test_inputs`.
  - Best insertion points:
    - [rlm_adk/callbacks/reasoning.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py#L109)
    - [rlm_adk/orchestrator.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L303)

- `Plan` becomes a structured plan contract rather than freeform hidden reasoning.
  - Suggested fields: `goal`, `substeps`, `expected_observations`, `stop_condition`, `dispatch_budget`, `repl_budget`.
  - The cleanest enforcement surface is the existing `set_model_response` path in:
    - [rlm_adk/orchestrator.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L282)
    - [rlm_adk/agent.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L151)

- `Carry Out` remains `execute_code`.
  - This already matches Polya's tiny verified steps.
  - Extend `LAST_REPL_RESULT` with:
    - `polya_phase`
    - `expected_result`
    - `observed_result`
    - `assumption_tested`
    - `phase_outcome`
  - Main surface:
    - [rlm_adk/tools/repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L239)

- `Look Back` becomes mandatory after every REPL turn before the next major action.
  - Suggested fields: `what_worked`, `what_failed`, `assumption_invalidated`, `next_adjustment`, `confidence_delta`.
  - Surfaces:
    - [rlm_adk/callbacks/reasoning.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py#L176)
    - [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L681)

### Why It Fits `rlm_adk`

- Minimal change to the current architecture.
- Preserves the current orchestrator and REPL tool flow.
- Reuses existing state, event, and tracing surfaces.
- Easy to query later through SQLite tracing and session-state events if phase keys are emitted through `state_delta`.

### Strengths

- Fastest implementation path.
- Lowest architectural risk.
- Best default production mode.

### Weaknesses

- Still mostly LLM-led.
- Improves discipline more than control.
- Reflection may become formulaic unless validated against execution evidence.

---

## Proposal 2: Recursive Phase Specialists

### Core Idea

Model each Polya phase as a recursive specialist with its own prompt, schema, and budget:

- `UnderstandAgent`
- `PlanAgent`
- `ExecuteAgent`
- `ReflectAgent`

### How It Works

- `UnderstandAgent`
  - clarifies ambiguity
  - surfaces missing context
  - identifies edge cases
  - emits a structured understanding payload

- `PlanAgent`
  - decomposes the problem into executable sub-questions
  - chooses between direct REPL execution and recursive child dispatch
  - emits a bounded execution plan

- `ExecuteAgent`
  - owns REPL code generation
  - uses `execute_code`, `llm_query_async`, and `llm_query_batched_async`
  - returns evidence, not just answer text

- `ReflectAgent`
  - evaluates evidence quality
  - checks whether assumptions were actually tested
  - decides whether to finalize, revise plan, or recurse deeper

### Best Extension Points

- Child creation and recursive orchestration already exist in:
  - [rlm_adk/agent.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L274)
  - [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L306)

- Batched phase dispatch already exists in:
  - [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L593)

- Structured phase outputs and self-healing are already partially supported through:
  - [rlm_adk/callbacks/worker_retry.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker_retry.py#L112)

### Why It Fits `rlm_adk`

- Matches the system's real strength: recursive child orchestrators with isolated REPL namespaces and shared session context.
- Makes `Understand` and `Look Back` first-class runtime agents instead of optional prose.
- Allows different models, budgets, or schemas per phase.

### Strengths

- Strong architectural alignment with recursive depth.
- Better decomposition quality on difficult tasks.
- Easier to tune phase-specific prompts and output contracts.

### Weaknesses

- More moving parts.
- Higher token and latency cost.
- More coordination pressure across depth levels.

### Best Use

- complex repo analysis
- debugging
- research tasks
- ambiguous prompts where bad framing is the main failure mode

---

## Proposal 3: Branch-and-Critique Polya Tree

### Core Idea

Turn Polya into a search process:

- produce multiple competing `Understand` framings
- generate a small executable plan for each
- execute them in parallel through child orchestrators
- reflectively prune or recurse based on evidence quality

This is the most novel option because it uses observability as part of reasoning quality, not just monitoring.

### How It Works

- `Understand`
  - generate 2 to 4 competing framings of the task
  - each framing includes assumptions and predicted evidence

- `Plan`
  - create a minimal REPL or child-dispatch plan per framing
  - include a hard budget for steps and recursion

- `Carry Out`
  - run the candidate framings in parallel using batched child dispatch
  - gather traces, errors, structured outputs, and execution summaries

- `Look Back`
  - score branches on:
    - evidence quality
    - assumption coverage
    - trace cleanliness
    - error rate
    - nested retry count
    - token and latency cost
  - either choose a winner or launch a second-round refinement

### Best Extension Points

- Parallel child execution:
  - [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L593)

- Per-child summary and scoring inputs:
  - [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L478)

- REPL trace persistence:
  - [rlm_adk/plugins/repl_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py#L39)

- Reasoning evidence:
  - [rlm_adk/callbacks/reasoning.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py#L176)

### Why It Fits `rlm_adk`

- Exploits the existing recursive fanout and observability stack more deeply than a linear planner can.
- Uses child summaries and traces as evidence for branch selection.
- Is well suited to tasks where the central problem is not execution, but choosing the right framing.

### Strengths

- Highest upside.
- Best use of recursive depth plus telemetry.
- Strongest defense against early framing errors.

### Weaknesses

- Most expensive design.
- Requires strong branch pruning and budgets.
- More difficult to stabilize.

### Best Use

- hard reasoning tasks
- open-ended synthesis
- tasks where multiple plausible framings compete

---

## Recommended Rollout

### Ship First

Start with **Proposal 1: Phase-Tagged Single Orchestrator**.

Reason:

- it is the lowest-risk way to make Polya real
- it preserves the current architecture
- it gives immediate observability wins
- it creates the phase/state scaffolding needed by the other two proposals

### Build Next

Add **Proposal 2: Recursive Phase Specialists** as a higher-quality mode.

Reason:

- it matches the recursive architecture most directly
- it makes phase discipline harder to skip
- it enables stronger phase-specific schemas and budgets

### Research Track

Prototype **Proposal 3: Branch-and-Critique Polya Tree** as an experimental mode.

Reason:

- it is the most distinctive design
- it best exploits recursive fanout plus observability
- it may produce the largest quality jump on complex reasoning tasks

---

## What Must Be Preserved

- REPL execution must remain the primary truth surface, not a cosmetic side tool.
  - [rlm_adk/tools/repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L93)

- Child recursion should continue to use full child orchestrators, not thin worker stubs.
  - [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L306)

- State mutation should stay event-driven and observable through `state_delta`.
  - [rlm_adk/orchestrator.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L221)

- Depth-aware state isolation must be preserved for all Polya metadata.
  - [rlm_adk/state.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L157)

- Structured-output retry and reflection mechanics should be reused, not reinvented.
  - [rlm_adk/callbacks/worker_retry.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker_retry.py#L79)

---

## Constraints and Risks

- Do not rely on direct session mutation outside the managed callback or tool context. Persistence is event-driven.
  - [ai_docs/adk_runtime_event_loop.md](/home/rawley-stanhope/dev/rlm-adk/ai_docs/adk_runtime_event_loop.md#L179)

- Plugin precedence is global. If Polya policy lives in a plugin, it can preempt local callbacks.
  - This is based on official ADK plugin docs.

- `flush_fn()` is a per-turn snapshot and reset boundary, not a cumulative ledger.
  - [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L681)

- Parent and child agents share invocation-scoped state in ADK, so Polya keys must be namespaced or depth-scoped.
  - This is based on official ADK state and multi-agent docs.

- SQLite tracing captures curated `state_delta` rows. If phase state never lands in emitted state deltas, it will be hard to analyze later.
  - [rlm_adk/plugins/sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L1)

- The AST rewrite bridge is execution plumbing, not a safety boundary.
  - [rlm_adk/tools/repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L143)

---

## Concrete Suggestion for Phase State

If Proposal 1 is implemented first, the minimum viable new depth-scoped keys should likely include:

- `polya_phase`
- `polya_understanding`
- `polya_plan`
- `polya_last_hypothesis`
- `polya_last_expectation`
- `polya_last_observation`
- `polya_reflection`
- `polya_confidence`
- `polya_next_action`

These should be emitted through real `state_delta` writes so they appear in:

- event history
- SQLite tracing
- child summaries
- later analysis dashboards

---

## Recommendation

The best practical sequence is:

1. implement **Phase-Tagged Single Orchestrator**
2. extend to **Recursive Phase Specialists**
3. experiment with **Branch-and-Critique Polya Tree**

That sequence respects the current architecture instead of fighting it, and it builds from the strongest existing assets in `rlm_adk`: recursive child orchestration, REPL-grounded verification, callback-driven control, and depth-aware telemetry.

## Sources

### Local Sources

- [ai_docs/Polya_workflow_in_REPL.md](/home/rawley-stanhope/dev/rlm-adk/ai_docs/Polya_workflow_in_REPL.md)
- [rlm_adk_docs/architecture_summary.md](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/architecture_summary.md)
- [rlm_adk/orchestrator.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py)
- [rlm_adk/dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py)
- [rlm_adk/tools/repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py)
- [rlm_adk/callbacks/reasoning.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py)
- [rlm_adk/callbacks/worker_retry.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker_retry.py)
- [rlm_adk/state.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py)
- [rlm_adk/plugins/repl_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py)

### Official ADK Sources

- https://google.github.io/adk-docs/callbacks/
- https://google.github.io/adk-docs/callbacks/design-patterns-and-best-practices/
- https://google.github.io/adk-docs/plugins/
- https://google.github.io/adk-docs/sessions/state/
- https://google.github.io/adk-docs/events/
- https://google.github.io/adk-docs/agents/multi-agents/
- https://google.github.io/adk-docs/agents/workflow-agents/loop-agents/
- https://google.github.io/adk-docs/integrations/reflect-and-retry/
- https://google.github.io/adk-docs/integrations/bigquery-agent-analytics/
- https://google.github.io/adk-docs/integrations/cloud-trace/
