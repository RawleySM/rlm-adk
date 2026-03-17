<!-- validated: 2026-03-09 -->

# Narrative Polya Topology Engine

**Status:** Proposed

**Thesis:** RLM-ADK should preserve natural language as its primary medium of
reasoning while using only minimal structure to steer topology, coordination,
and control flow. The topology engine should therefore be built as a
**thin control plane around a rich narrative reasoning plane**.

This is a companion to [polya_topology_engine.md](./polya_topology_engine.md).
That document focuses on topology selection and phase routing. This document
focuses on how to preserve the strengths of language models while still
directing work through a Polya workflow.

---

## Core Principle

The system should not try to force the most valuable parts of reasoning into a
rigid state machine.

Language models are strongest when they can:

- map a problem as a causal story
- describe competing interpretations
- articulate uncertainty in nuanced language
- explain why a next move is promising
- revise the narrative when reality pushes back

If the topology engine over-structures that process, it will likely degrade the
very intelligence we are trying to harness.

So the intended division of labor is:

- **Narrative plane**: the agent thinks, reflects, explains, and carries
  forward a rich evolving story of the work
- **Control plane**: the system extracts only the small amount of structure
  needed to coordinate phases, topology, retrieval, and handoffs

In short:

- **prose is for thinking**
- **schemas are for coordination**

---

## Chaptered Polya

Polya phases should not be treated as sterile workflow boxes. They should feel
like chapters in one ongoing investigation.

Suggested chapter roles:

- **Understand**: write the current world-model of the problem
- **Plan**: write the intended path through that world-model
- **Implement**: write what happened when the plan met reality
- **Reflect**: write the revised story of the work and what it implies next

This creates continuity across phases. Each phase hands the next not only a
task state, but a narrative trajectory.

The goal is not just to know what the agent decided. It is to preserve why that
decision made sense inside the evolving story of the work.

---

## Thin Structure, Thick Prose

Each phase should produce two layers of output:

1. A **rich narrative artifact**
2. A **small control envelope**

The narrative artifact is the canonical reasoning output. The control envelope
is a lossy operational projection used for routing and coordination.

This keeps the system from making the mistake of treating structure as the
reasoning itself.

### Narrative Artifact

The narrative artifact should be reflective, explanatory, and phase-aware. It
should sound more like a field memo, lab notebook entry, or engineering brief
than a form being filled out.

Typical qualities:

- explains the causal story, not just the conclusion
- names the most plausible alternatives
- states what changed in the agent's understanding
- describes remaining uncertainty
- justifies the next move as a continuation of the current trajectory

### Control Envelope

The control envelope should stay intentionally small. It exists to answer only
questions like:

- are we ready to proceed
- are we blocked
- do we need retrieval
- what topology should come next
- what outputs should children return

The control envelope should never be allowed to crowd out the narrative layer.

---

## Proposed Artifact Model

### Phase Narrative Artifact

Each Polya phase produces a memo-like narrative artifact.

Suggested shape:

```python
class PhaseNarrativeArtifact(BaseModel):
    phase: Literal["understand", "plan", "implement", "reflect"]
    title: str | None = None
    memo_text: str
    trajectory_summary: str | None = None
    predecessor_refs: list[str] = []
```

`memo_text` is the main body. It should contain the actual reflective prose.

### Phase Control Envelope

The control envelope is derived from the narrative rather than replacing it.

Suggested shape:

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

This envelope should remain phase-specific and minimal.

---

## Narrative-First Distillation

The key implementation pattern is:

```text
Narrative first
  → distill small control structure
  → route topology and phase transitions
  → pass narrative forward as primary context
```

This is preferable to asking the primary agent to think directly inside a
rigid schema.

### Distiller Agent

The control envelope can be derived by a dedicated stateless follow-up agent.

Suggested role:

- **NarrativeDistiller**

Its job is narrow:

- read the predecessor's narrative artifact
- read the current Polya phase
- populate a phase-specific schema
- avoid re-solving the task
- preserve ambiguity rather than invent certainty

This agent should be treated as a reducer, not a second problem solver.

### Why This Is Useful

This pattern preserves the main model's ability to reason richly while still
giving the topology engine typed state for routing and coordination.

It also lets the system vary the degree of structure by phase:

- `Understand`: blockers, missing prerequisites, confidence, topology advice
- `Plan`: work packets, merge strategy, child schemas, verification contracts
- `Implement`: execution status, deviations from plan, emerging risks
- `Reflect`: failure modes, lessons, topology effectiveness, next-cycle advice

---

## Planning as Schema Design

The planning phase is a special case.

In some tasks, the planning distiller should not merely populate a fixed
schema. It should derive a new schema that defines the expected outputs of
child `llm_query` or `llm_query_batched` calls to recursive
`RLMOrchestratorAgent`s.

This is important because planning is not only about choosing actions. It is
also about defining **information contracts** that make child work composable.

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
```

In this design, planning can generate:

- the decomposition
- the output contract for children
- the synthesis contract for the parent
- the review burden required before finalization

That gives the topology engine structure exactly where structure is most useful:
at boundaries between agents and at aggregation points.

---

## Authority Rule

The narrative remains authoritative.

The control envelope is only a derived operational summary. If the envelope and
the narrative disagree, the system should not blindly trust the structured
projection.

Instead it should:

- re-distill
- escalate to a reflective pass
- preserve the ambiguity explicitly

This protects the system from flattening the most important insights into a
misleading schema.

---

## Prompting for Rich Narrative Output

To encourage better phase memos, prompts should ask for reflective prose rather
than bureaucratic field filling.

Examples of prompt pressure that should help:

- Explain the causal story, not just the conclusion.
- Name the most plausible alternative framings.
- Describe what changed in your understanding during this phase.
- State what remains unclear and what evidence would reduce that uncertainty.
- Describe the next move as a continuation of the story so far.
- Note what would falsify your current interpretation.

This produces outputs that are better suited for both human inspection and
topology-aware continuation.

---

## Relationship to Topology

The topology engine should route on distilled structure, but it should pass the
narrative forward as the main semantic payload.

That means:

- topology selection uses the control envelope
- retrieval and blocker handling use the control envelope
- child tasking may use schemas derived during planning
- child prompts and parent synthesis should still inherit narrative context

This is especially important for recursive work. Children should not receive
only task fragments and schemas. They should also inherit the narrative frame
that explains why their task exists inside the broader investigation.

---

## Horizontal and Vertical Narrative Flow

### Horizontal

In a horizontal topology, the parent keeps a running sequence of chaptered
memos across repeated root-level REPL turns.

This is well-suited for:

- tightly coupled investigations
- high-ambiguity work
- tasks where the narrative benefits from continuity inside one persistent REPL
  workspace

### Vertical

In a vertical topology, the parent can issue child assignments that include:

- a local task
- a narrative frame
- a requested output schema if needed

Each child returns:

- a narrative memo
- a distilled envelope

The parent then synthesizes both:

- envelopes for routing and control
- memos for semantic understanding

This preserves reflective richness while still allowing recursive fanout.

---

## Callback and State Mapping

This approach fits the current RLM-ADK seams if kept lightweight.

### Suggested Flow

1. `before_agent_callback`
   - choose initial phase and provisional topology
   - write minimal control state

2. main reasoning agent
   - produces narrative chapter text

3. `after_model_callback`
   - captures and persists the narrative artifact
   - optionally marks that a distillation pass is needed

4. phase-transition step
   - invokes a stateless `NarrativeDistiller`
   - passes the phase, narrative text, and target schema or schema-generation
     instruction
   - persists the returned control envelope

5. topology engine
   - uses the envelope to choose next routing behavior
   - uses the narrative as semantic carry-forward context

This keeps callbacks mostly observational while locating orchestration in an
explicit phase-transition layer rather than in hidden callback side effects.

### Suggested State Categories

- current phase
- current topology
- current narrative artifact
- current control envelope
- topology revision reason
- blocker status
- retrieval status
- generated child schema references

The system should store the narrative artifacts as first-class session state or
artifacts, not treat them as disposable intermediate text.

---

## Retrieval and Narrative Continuity

The retrieval-aware `Understand` loop described in
[polya_topology_engine.md](./polya_topology_engine.md) becomes stronger under a
narrative-first design.

When `Understand` discovers missing evidence, the system should not just set a
blocker flag. It should write a short narrative account of:

- what was discovered
- why the current understanding is incomplete
- what evidence is missing
- why the current topology may need to change

That memo then becomes the context for the retrieval step and the later
reclassification step.

This creates continuity instead of phase amnesia.

---

## Failure Modes

This design still has risks.

- Over-distillation may flatten important nuance into bad control signals.
- The distiller may hallucinate stronger certainty than the narrative supports.
- Excessively long memos may become hard to reuse across recursive layers.
- If every phase produces prose with no discipline, the system can become
  verbose without being clearer.
- If child schemas are over-specified, planning can still become bureaucratic.

These are reasons to keep the control layer thin, the distiller narrow, and the
prompts disciplined.

---

## Design Summary

The intended architecture is:

- rich natural-language reasoning as the primary problem-solving substrate
- small typed envelopes for routing and coordination
- phase outputs treated as chaptered narrative memos
- a stateless distillation layer that turns prose into topology-relevant
  structure
- planning empowered to generate child output schemas when decomposition
  requires stronger information contracts

This gives the Polya topology engine a stronger foundation than a heavy state
machine. It preserves the expressive and reflective strengths of language
models while still enabling disciplined information flow through recursive
agent topologies.

