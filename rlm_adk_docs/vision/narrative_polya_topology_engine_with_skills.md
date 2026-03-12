<!-- validated: 2026-03-12 -->

# Narrative Polya Topology Engine With Skills

**Status:** Proposed

**Thesis:** RLM-ADK should preserve natural language as its primary medium of
reasoning while using only minimal structure to steer topology, coordination,
and control flow. Skills should be integrated into that design as
**chapter-aware operators**: thin reusable workflow helpers that act on a
chaptered narrative without replacing it.

This document updates
[narrative_polya_topology_engine.md](./narrative_polya_topology_engine.md) with
a concrete skill-oriented implementation direction that fits the current
RLM-ADK runtime.

It should be read alongside:

- [polya_topology_engine.md](./polya_topology_engine.md)
- [../skills_and_prompts.md](../skills_and_prompts.md)
- [../core_loop.md](../core_loop.md)

---

## Core Principle

The system should not try to force the most valuable parts of reasoning into a
rigid state machine or a pile of opaque helper functions.

Language models are strongest when they can:

- map a problem as a causal story
- describe competing interpretations
- articulate uncertainty in nuanced language
- explain why a next move is promising
- revise the narrative when reality pushes back

Skills should therefore not become a second reasoning substrate. They should
remain a thin execution layer around the narrative.

So the intended division of labor is:

- **Narrative plane**: the agent thinks, reflects, explains, and carries
  forward a rich evolving story of the work
- **Control plane**: the system extracts the small amount of structure needed
  to coordinate phases, topology, retrieval, and handoffs
- **Skill plane**: reusable chapter-aware workflow helpers execute recurring
  processing patterns against the current REPL context

In short:

- **prose is for thinking**
- **schemas are for coordination**
- **skills are for reusable workflow**

---

## Why Skills Belong In The Chapter Model

The existing narrative-first Polya design already treats each phase as a
chapter in one investigation. The missing piece is that chapter transitions
should also be able to:

- activate a skill
- retire a skill
- hand off a skill to a child
- explain why that skill is relevant to the current narrative

That matters because many useful workflows are not one-off prompt patterns.
They are recurring operators such as:

- extract a world-model from the current chapter
- derive work packets from a planning chapter
- run per-chapter fanout analysis over loaded context
- synthesize chapter outputs into a reflective memo

Those are good candidates for skills precisely because they are reusable, but
they should still be parameterized by the active chapter narrative rather than
treated as context-free tools.

---

## Chaptered Polya With Skill Arcs

Polya phases should feel like chapters in one investigation, and each chapter
may carry a skill arc.

Suggested chapter roles:

- **Understand**: write the current world-model of the problem
- **Plan**: write the intended path through that world-model
- **Implement**: write what happened when the plan met reality
- **Reflect**: write the revised story of the work and what it implies next

Suggested skill-role overlay:

- **Understand**: identify whether a reusable interpretation or retrieval skill
  should be activated
- **Plan**: define which skills should operate on which parts of the narrative
  and which child contracts they should satisfy
- **Implement**: run the selected skills against the active context and record
  where skill output diverged from expectation
- **Reflect**: decide whether the skill improved the investigation, should be
  revised, or should be retired for the next cycle

This preserves chapter continuity. Each phase hands the next not only a task
state, but also a narrative trajectory and a skill trajectory.

---

## UnderstandProbe As Prologue

`UnderstandProbe` should be incorporated as a **one-time prologue**, not as a
fifth recurring Polya phase.

The recurring chapter model should remain:

- `Understand`
- `Plan`
- `Implement`
- `Reflect`

But the initial prompt usually justifies only a **provisional understanding
topology**, not a confident downstream workflow decision. So the system should
begin with a non-recurring `UnderstandProbe` task whose job is to answer:

- what evidence surface likely matters
- whether critical prerequisites are missing
- whether understanding should begin horizontally, vertically, or via an
  evidence-acquisition loop
- which skill family, if any, should activate first

The probe should therefore act as an entry gate into Chapter 1, not as a new
chapter that recurs throughout the run.

### Probe Outcome Rule

After `UnderstandProbe`, the system should choose among:

- enter `Understand` under the recommended topology
- acquire evidence and resume `Understand`
- stop and request user-provided artifacts
- revise the provisional topology before any deeper fanout

Later topology invalidation should normally mean:

- resume or rework `Understand`
- re-plan from improved evidence
- reflect on why the prior topology was unsound

It should not usually mean re-running the initial probe as if the task were
new.

### Probe Narrative Form

Even though `UnderstandProbe` is a control-oriented startup task, it should
still produce a short narrative artifact.

That prologue memo should capture:

- what appears to matter
- what is still unknown
- why the recommended `Understand` topology is justified
- whether retrieval or evidence acquisition must happen first

The probe memo should be shorter and more diagnostic than a full `Understand`
chapter memo.

---

## ADK State Scope Model

The Polya design should be mapped onto ADK's existing state scopes rather than
inventing a separate persistence model.

The key rule is:

- phases are a workflow dimension
- ADK prefixes are a lifetime and sharing dimension

So the system should not assign `user_id` to `understand`, `plan`,
`implement`, or `reflect`. That would overload identity with workflow state and
misuse ADK's `user:` persistence semantics.

Instead the intended split should be:

- `app:` for app-wide Polya defaults and policy
- `user:` for durable phase preferences and learned bias
- unprefixed session keys for the current task's chapter state and active
  execution context

Suggested key families:

### `app:` defaults

- `app:polya:enabled`
- `app:polya:default_phase`
- `app:polya:phase_order`
- `app:polya:instruction_style`
- `app:polya:skill_defaults`
- `app:polya:transition_thresholds`

### `user:` preferences

- `user:polya:preferred_entry_phase`
- `user:polya:phase_bias`
- `user:polya:understand:style`
- `user:polya:plan:default_topology`
- `user:polya:implement:verification_bias`
- `user:polya:reflect:retrospective_depth`

### session chapter state

- `polya:current_phase`
- `polya:phase_objective`
- `polya:phase_narrative_summary`
- `polya:phase_skill`
- `polya:phase_transition_reason`
- `polya:proposed_next_phase`
- `polya:child_contracts`
- `polya:merge_strategy`
- `polya:chapter:understand`
- `polya:chapter:plan`
- `polya:chapter:implement`
- `polya:chapter:reflect`
- `polya:ledger`

This yields a useful precedence order:

1. `app:` policy sets the default envelope
2. `user:` preferences personalize that envelope
3. session keys define the current task chapter and current execution context

### Depth And Prefix Rules

The existing runtime already uses `depth_key(...)` for recursion-local session
telemetry. That should remain mostly separate from ADK prefix scope.

Recommended rule:

- allow `depth_key(...)` for recursion-local session telemetry
- avoid `depth_key(...)` for `user:` keys
- avoid `depth_key(...)` for `app:` keys
- avoid introducing depth-suffixed Polya control keys unless a concrete read
  path requires them

If depth matters for a durable Polya value, put depth inside the stored value
rather than in the key name.

---

## Thin Structure, Thick Prose, Thin Skills

Each phase should produce three layers of output:

1. A **rich narrative artifact**
2. A **small control envelope**
3. A **small skill envelope**

The narrative artifact remains canonical. The control envelope and skill
envelope are lossy operational projections.

### Narrative Artifact

The narrative artifact should remain reflective, explanatory, and phase-aware.
It should sound more like a field memo, lab notebook entry, or engineering
brief than a form being filled out.

Typical qualities:

- explains the causal story, not just the conclusion
- names the most plausible alternatives
- states what changed in the agent's understanding
- describes remaining uncertainty
- justifies the next move as a continuation of the current trajectory

### Control Envelope

The control envelope should answer only questions like:

- are we ready to proceed
- are we blocked
- do we need retrieval
- what topology should come next
- what outputs should children return

### Skill Envelope

The skill envelope should answer only questions like:

- which skill, if any, should become active
- why is that skill justified by the narrative
- what inputs should the skill consume
- should the skill run locally or through child fanout
- what contract should the skill satisfy

The skill envelope should not crowd out the narrative layer.

---

## Proposed Artifact Model

### Understand Probe Artifact

```python
class UnderstandProbeArtifact(BaseModel):
    probe_status: Literal["sufficient", "partial", "blocked", "invalidated"]
    probe_summary: str
    evidence_surface: list[str] = []
    missing_prerequisites: list[str] = []
    retrieval_candidates: list[str] = []
    shardability_assessment: str | None = None
    recommended_understand_topology: str | None = None
    recommended_initial_skill: str | None = None
    replan_reason: str | None = None
```

This artifact is not a recurring phase output. It is the startup control
boundary that determines how the first real `Understand` chapter should begin.

### Phase Narrative Artifact

```python
class PhaseNarrativeArtifact(BaseModel):
    phase: Literal["understand", "plan", "implement", "reflect"]
    title: str | None = None
    memo_text: str
    trajectory_summary: str | None = None
    predecessor_refs: list[str] = []
    active_skills: list[str] = []
```

`memo_text` remains the primary reasoning artifact.

### Phase Control Envelope

```python
class PhaseControlEnvelope(BaseModel):
    phase: Literal["understand", "plan", "implement", "reflect"]
    status: str
    confidence: float | None = None
    blockers: list[str] = []
    missing_prerequisites: list[str] = []
    recommended_topology: str | None = None
    next_action: str | None = None
```

### Phase Skill Envelope

```python
class PhaseSkillEnvelope(BaseModel):
    phase: Literal["understand", "plan", "implement", "reflect"]
    active_skill: str | None = None
    candidate_skills: list[str] = []
    skill_activation_reason: str | None = None
    required_inputs: list[str] = []
    execution_mode: Literal["local", "fanout", "hybrid"] | None = None
    child_output_schema_name: str | None = None
    child_output_schema_spec: dict | None = None
```

The control envelope and skill envelope are derived from the narrative rather
than replacing it.

The intended lifecycle is:

1. `UnderstandProbeArtifact`
2. recurring `PhaseNarrativeArtifact` / `PhaseControlEnvelope` /
   `PhaseSkillEnvelope`

---

## Narrative-First Distillation

The implementation pattern should be:

```text
Narrative first
  -> distill small control structure
  -> distill small skill structure
  -> route topology and phase transitions
  -> pass narrative forward as primary context
```

This is preferable to asking the primary agent to think directly inside a
rigid schema or a pre-selected skill script.

### Distiller Roles

The current design can support one narrow distillation pass with two outputs,
or two narrow passes:

- **Topology distillation**: derive routing and phase-transition structure
- **Skill distillation**: derive which skill should activate, with what inputs
  and output contract

The skill distiller should:

- read the current chapter narrative
- identify whether a reusable workflow is justified
- propose the minimal skill activation needed
- avoid re-solving the task
- preserve ambiguity rather than invent certainty

It should be treated as a reducer, not a second problem solver.

---

## Planning As Schema And Skill Design

Planning is the special case where stronger structure is justified.

In the narrative-first design, planning does not merely choose the next moves.
It also defines:

- the decomposition
- the output contract for children
- the synthesis contract for the parent
- the skill bundle required for each work packet

Suggested planning outputs:

```python
class PlanControlEnvelope(BaseModel):
    status: str
    recommended_topology: str
    work_packets: list[dict]
    merge_strategy: str
    verification_requirements: list[str]
    child_output_schema_name: str | None = None
    child_output_schema_spec: dict | None = None
    required_skills: list[str] = []
```

This gives the topology engine structure exactly where structure is most
useful: at boundaries between agents, at aggregation points, and at skill
activation points.

---

## Implemented Skill Form In The Current Runtime

The current RLM-ADK runtime has a hard implementation boundary:

- skills injected directly into `repl.globals` are appropriate for pure Python
  helpers
- skills that internally call `llm_query()` or `llm_query_batched()` must be
  **source-expandable REPL skills**

This follows from the current execution path:

1. `RLMOrchestratorAgent` installs async dispatch closures into the REPL
2. `REPLTool` expands synthetic skill imports before AST analysis
3. `REPLTool` detects `llm_query` / `llm_query_batched`
4. `rewrite_for_async()` rewrites those calls to async equivalents
5. execution runs against the merged REPL globals and persisted locals

The practical consequence is simple:

- a live injected helper that calls `llm_query()` will fail in ADK mode
- an expanded skill source block that calls `llm_query()` will be rewritten and
  work correctly

So the implemented skill shape for this design should be:

```python
from rlm_repl_skills.narrative_polya import run_narrative_polya_skill
```

where `run_narrative_polya_skill(...)` is registered as a `ReplSkillExport`
whose source is inlined before rewrite.

---

## Skill Function Contract

The core helper should accept the chaptered narrative of the model activating
the skill.

Suggested shape:

```python
def run_narrative_polya_skill(
    chaptered_narrative: str,
    phase: str | None = None,
    objective: str | None = None,
    output_schema: type[BaseModel] | None = None,
    model: str | None = None,
):
    ...
```

Expected behavior:

- `chaptered_narrative` is the primary semantic input
- `phase` constrains which Polya chapter logic to run
- `objective` lets the caller bind the narrative to a concrete local task
- `output_schema` may be forwarded into child `llm_query` calls when planning
  needs structured sub-results
- `model` allows optional model override for child work

The helper should return either:

- a rich Python result object, or
- a dict with narrative result, control result, and skill execution metadata

---

## Prompt-Building Inside The Skill

The helper should not treat the chaptered narrative as the only input. It
should compose prompts from four things:

1. the chaptered narrative argument
2. phase-specific instructions
3. explicitly referenced current REPL context
4. optional child output-schema requirements

Suggested internal exports:

```python
CHAPTER_UNDERSTAND_INSTRUCTIONS = "..."
CHAPTER_PLAN_INSTRUCTIONS = "..."
CHAPTER_IMPLEMENT_INSTRUCTIONS = "..."
CHAPTER_REFLECT_INSTRUCTIONS = "..."

def build_understand_prompt(chaptered_narrative, context_snapshot, objective=None): ...
def build_plan_prompts(chaptered_narrative, context_snapshot, objective=None): ...
def build_implement_prompt(chaptered_narrative, context_snapshot, objective=None): ...
def build_reflect_prompt(chaptered_narrative, context_snapshot, objective=None): ...
```

The important detail is that the helper may use the currently loaded REPL
environment, but there is no dedicated ambient context object today. So the
robust pattern is:

- pass required context explicitly as arguments, or
- read explicitly named REPL variables that are already loaded

The doc should not assume a hidden `current_context` API that does not exist.

---

## Execution Patterns

The imported skill function's source should string together a series of
`llm_query()` or `llm_query_batched()` calls that pair the narrative with
instructions for processing the current context loaded into the REPL
environment.

Recommended patterns:

### Sequential chapter refinement

Use sequential `llm_query()` calls when each step depends on the prior result.

```python
world_model = llm_query(understand_prompt, model=model)
plan = llm_query(plan_prompt_with(world_model), model=model, output_schema=output_schema)
reflection = llm_query(reflect_prompt_with(plan), model=model)
```

### Per-chapter fanout

Use `llm_query_batched()` when independent chapter slices or work packets can
be processed concurrently.

```python
child_prompts = [build_packet_prompt(packet, chaptered_narrative, context_snapshot) for packet in work_packets]
child_results = llm_query_batched(child_prompts, model=model, output_schema=output_schema)
summary = llm_query(build_merge_prompt(child_results, chaptered_narrative), model=model)
```

### Hybrid planning flow

Planning is the most natural place for:

- `llm_query()` to derive a decomposition
- `llm_query_batched()` to run packet-level children
- `llm_query()` again to synthesize and verify

This fits the current dispatch path, which already supports
`output_schema`-constrained child calls.

---

## Skill Registration Model

The new doc should describe the implemented workflow in terms of the current
skill registry contract.

Suggested shape:

```python
register_skill_export(
    ReplSkillExport(
        module="rlm_repl_skills.narrative_polya",
        name="run_narrative_polya_skill",
        source=_RUN_NARRATIVE_POLYA_SKILL_SRC,
        requires=[
            "CHAPTER_UNDERSTAND_INSTRUCTIONS",
            "CHAPTER_PLAN_INSTRUCTIONS",
            "build_understand_prompt",
            "build_plan_prompts",
        ],
        kind="function",
    )
)
```

Important current constraints:

- only `from rlm_repl_skills.<module> import <symbol>` is supported
- no aliasing
- no wildcard imports
- no plain `import rlm_repl_skills.foo`
- exports must be valid standalone source when inlined
- `llm_query` detection is lexical and only catches direct calls by name

So the skill source should avoid hiding calls behind aliases, attributes, or
runtime-generated code strings.

---

## Cross-Turn Constraint

The rewrite is per submitted code block.

That implies a sharp edge for reusable helper definitions across turns:

- if a helper with `llm_query()` is defined in one turn and called in a later
  turn without re-expansion, the later call site may not be rewritten
- that later turn can fall back to sync execution and return a coroutine object
  instead of actually running the helper

So the intended usage pattern should be:

- import the expandable skill in the same submitted code block where it is
  called, or
- ensure the call site itself is part of the rewritten block

The doc should explicitly call this out so the design does not assume
cross-turn async helper reuse that the current runtime does not guarantee.

---

## Prompt And Instruction Integration

This design should connect to the existing instruction pipeline rather than
replacing it.

The main integration points are:

- dynamic instruction fields for scoped Polya state
- prompt-side skill discoverability
- runtime-side source expansion for LLM-aware skill helpers

The lowest-risk operational path is to extend the current dynamic instruction
template rather than redesign the prompt system first.

Suggested dynamic instruction additions:

```text
Repository URL: {repo_url?}
Original query: {root_prompt?}

Probe bootstrap:
- probe_status: {polya:probe_status?}
- probe_summary: {polya:probe_summary?}
- probe_topology: {polya:probe_topology?}

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
- transition_reason: {polya:phase_transition_reason?}
- proposed_next_phase: {polya:proposed_next_phase?}
```

This preserves the current design in
[../skills_and_prompts.md](../skills_and_prompts.md):

- root prompt assembly remains the main discoverability path
- children still use condensed prompts by default
- source-expandable skills remain the runtime mechanism for helpers that call
  `llm_query`

The important constraint is that the dynamic instruction should stay compact.
It should summarize scoped Polya state, not duplicate whole chapter memos or
large child contracts. Those belong in session state, REPL variables, or
explicit skill-built prompts.

This is also where the design should stay conservative about short-lived
scoped state. Given prior issues with `temp:` keys in the REPL environment,
the spec should not depend on `temp:`-scoped Polya control keys for core
behavior.

The probe fields should be treated as bootstrap hints. Once the first real
`Understand` chapter is established, the chapter state should become primary.

---

## Child Inheritance Rules

Children should not receive only task fragments and schemas. They should also
inherit the narrative frame that explains why their task exists.

Suggested child inheritance package:

- local task
- relevant chapter excerpt
- narrative frame
- requested output schema if needed
- required active skill name if the child must use a specific skill
- child phase or transition reason passed explicitly in the prompt or contract

In practice, the cleanest split is:

- session keys carry the shared chapter state
- explicit prompt text carries the exact work packet, child phase framing, and
  success contract

However, children should not automatically inherit all root-level skill prompt
blocks. The current runtime intentionally keeps child prompts lighter. So the
inheritance rule should be selective:

- pass the narrative and the required skill contract
- pass only the minimal skill instruction needed
- rely on source-expandable imports for execution-time helper code
- pass short-lived fanout coordination explicitly in the child prompt or child
  contract instead of relying on hidden scoped state

---

## Callback And State Mapping

This approach fits the current RLM-ADK seams if kept lightweight.

### Suggested Flow

1. startup step
   - seed app/session defaults if needed
   - choose provisional `UnderstandProbe` topology
   - write only through tracked state channels

2. probe step
   - run `UnderstandProbe`
   - emit `UnderstandProbeArtifact`
   - persist bootstrap fields such as probe status, summary, and recommended
     `Understand` topology

3. evidence gate
   - if blocked, acquire evidence or ask the user for missing artifacts
   - if topology is invalidated, revise the initial `Understand` plan

4. first chapter entry
   - enter the real `Understand` chapter under the selected topology
   - produce chapter narrative text

5. narrative capture step
   - persist the chapter artifact
   - mark whether distillation and skill selection are needed

6. phase-transition step
   - derive control envelope
   - derive skill envelope
   - persist selected skill contract

7. execution step
   - imports the selected source-expandable skill into the REPL block
   - calls the skill helper with the current chaptered narrative

8. topology engine
   - uses the control envelope for routing
   - uses the narrative as semantic carry-forward context
   - uses the skill envelope for execution strategy

### Suggested Mutation Sites

- `RLMOrchestratorAgent._run_async_impl()`
  - initial `EventActions(state_delta=...)`
  - seed `root_prompt`, repo context, probe bootstrap fields, and initial
    Polya session keys
- `reasoning_before_model()` / `reasoning_after_model()`
  - update probe summaries, compact phase summaries, and chapter state via
    `callback_context.state`
- `REPLTool.run_async()`
  - record invocation-local execution and phase-adjacent telemetry via
    `tool_context.state`
- dispatch closures
  - continue using local accumulators and `flush_fn()`
  - do not directly mutate session state for Polya control

### Suggested State Categories

- `app:polya:*` policy and defaults
- `user:polya:*` durable user preferences
- probe bootstrap state such as `polya:probe_completed`,
  `polya:probe_status`, `polya:probe_summary`, and `polya:probe_topology`
- session chapter state such as `polya:current_phase`, `polya:chapter:*`,
  `polya:ledger`, transition reasons, child contracts, merge strategies, and
  skill selection

Narrative artifacts should remain first-class state or artifacts, not
disposable intermediate text.

### Observability Note

New Polya keys written through tracked state channels are safe, but the current
observability stack will not automatically surface them semantically.

In particular:

- prompt and context snapshots will only reflect Polya state if it is injected
  into instructions or prompts
- `sqlite_tracing.py` will need explicit extension if Polya-specific columns or
  state-event capture are desired

So Polya state should be introduced first for behavior, and only then elevated
into specialized tracing if the model proves useful.

---

## Retrieval And Narrative Continuity

The retrieval-aware `Understand` loop becomes stronger under a skill-aware
narrative-first design.

When `Understand` discovers missing evidence, the system should not just set a
blocker flag. It should write a short narrative account of:

- what was discovered
- why the current understanding is incomplete
- what evidence is missing
- whether a retrieval-oriented skill should activate
- why the current topology may need to change

That memo then becomes the context for retrieval and later reclassification.

This creates continuity instead of phase amnesia.

---

## Authority Rule

The narrative remains authoritative.

The control envelope and skill envelope are derived operational summaries. If
either derived layer disagrees with the narrative, the system should not
blindly trust the structured projection.

Instead it should:

- re-distill
- escalate to a reflective pass
- preserve the ambiguity explicitly

This protects the system from flattening important insights into a misleading
schema or a premature skill activation.

---

## Failure Modes

This design still has risks.

- over-distillation may flatten important nuance into bad control signals
- the skill distiller may hallucinate stronger certainty than the narrative
  supports
- excessive skill activation may create prompt bloat and workflow churn
- a helper may hide `llm_query` behind an unsupported pattern and miss rewrite
- cross-turn helper reuse may fail because rewrite is per-block
- child skill contracts may become bureaucratic or overspecified
- long memos may become hard to reuse across recursive layers

These are reasons to keep the control layer thin, the skill layer thin, the
distiller narrow, and the execution contract explicit.

---

## Design Summary

The intended architecture is:

- rich natural-language reasoning as the primary problem-solving substrate
- small typed envelopes for routing and coordination
- small skill envelopes for reusable workflow activation
- phase outputs treated as chaptered narrative memos
- source-expandable REPL skills for any helper that internally calls
  `llm_query()` or `llm_query_batched()`
- planning empowered to generate child output schemas and skill contracts when
  decomposition requires stronger information boundaries

This gives the Polya topology engine a stronger foundation than a heavy state
machine or a bag of opaque helper functions. It preserves the expressive and
reflective strengths of language models while still enabling disciplined
information flow through recursive agent topologies and reusable chapter-aware
skills.
