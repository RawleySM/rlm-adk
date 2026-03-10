<!-- validated: 2026-03-09 -->

# Polya Topology Engine (Dynamic Instruction Injection)

**Status:** Planned — research complete (`ai_docs/codebase_documentation_research/progressive_disclosure_patterns.md`, `rlm_adk_docs/codex_polya_workflow.md`)

**What it does:** Every agent run is structured as a Polya-inspired workflow: **Understand → Plan → Implement → Reflect**. The topology (how these phases map to agent turns and recursion depth) is configured per-task via dynamic instructions.

---

## Three Topology Variants

| Topology | How Polya Phases Execute | Best For |
|----------|-------------------------|----------|
| **Horizontal** | Each phase is a sequential REPL iteration at the same depth. Parent handles everything. | Simple tasks, code generation, quick analysis |
| **Vertical** | Each phase delegates to a child orchestrator at depth+1. Parent synthesizes. | Complex tasks requiring focused sub-agents per phase |
| **Hybrid** | Horizontal parent loop with vertical delegation at specific phases (e.g., Understand horizontally, Implement vertically) | Large tasks with mixed complexity |

## Integration Points

- **Dynamic instruction** (`instructions` parameter on `LlmAgent`) — currently empty template, will carry topology configuration
- **`before_agent_callback`** — inspect incoming prompt, classify task, select topology
- **`before_model_callback`** — inject phase-specific instructions based on current state (which Polya phase, what depth)
- **State keys** — new keys for phase tracking: `polya_phase`, `polya_topology`, `polya_phase_history`
- **Depth scoping** — vertical topology uses existing `depth_key()` mechanism for per-phase state isolation

## Task Classification → Topology Selection (Planned)

```
User prompt arrives
  → before_agent_callback fires
  → Classify prompt only enough to choose an initial Understand topology
  → Inject provisional Understand config into dynamic instruction
  → Agent executes Understand under selected topology
  → If Understand discovers missing prerequisites, enter evidence-acquisition sub-loop
  → Understand emits structured findings / uncertainty / decomposition hints
  → Select topology for Plan → Implement → Reflect from those findings
  → Agent executes downstream phases under the derived topology
  → Reflect phase evaluates: was this topology effective?
  → Log topology choice + outcome for future classification improvement
```

## Explorer Synthesis: Understand Topology Selection

Two independent explorer reviews converged on the same design constraint: the
initial user prompt rarely justifies choosing the full `Understand → Plan →
Implement → Reflect` topology up front. It usually justifies only a
**provisional topology for Understand**.

This is especially important for RLM-ADK because the current architecture is
already topology-capable but not yet topology-explicit:

- **Horizontal Understand** already maps cleanly to repeated parent
  `execute_code` turns at depth 0 with state carried in persistent REPL locals.
- **Vertical Understand** already maps cleanly to `llm_query` /
  `llm_query_batched` fanout through child orchestrators with depth-scoped
  state and per-child summaries.

The recommended control flow is therefore:

```
User prompt
  → choose provisional Understand topology
  → run Understand
  → emit Understand artifact
  → choose Plan / Implement / Reflect topology from that artifact
  → execute downstream topology
```

### Variables That Should Influence Understand Topology

The explorer reviews grouped the relevant variables into four broad buckets.

#### 1. Task + Prompt Structure

- Problem type: bugfix, explanation, design, repo exploration, root-cause,
  scientific synthesis, novelty search
- Scope claim: single file, named subsystem, whole repo, mixed artifacts,
  unknown breadth
- Deliverable type: explanation, decomposition, hypothesis inventory, plan,
  implementation
- Ambiguity level: precise ask vs underspecified exploratory request
- Coupling implied by the prompt: isolated surface vs cross-cutting behavior
- Decomposability from prompt alone: whether credible shard boundaries are
  already visible before inspection
- Association to active projects: whether the query belongs to an ongoing
  project for which prior Understand groundwork, artifact inventories,
  decomposition notes, or stable terminology already exist
- Continuity value: whether reusing prior project understanding is likely to be
  more valuable than re-deriving context from scratch

#### 2. Evidence Surface

- Breadth of likely evidence surface: one file, several files, subsystem,
  whole repo, code + tests + traces + docs
- Evidence heterogeneity: whether artifacts are uniform enough for parallel
  summarization or require cross-artifact interpretation
- Need for probing: whether the first move should be measuring corpus size,
  shape, and candidate shard boundaries
- Need for local causal continuity: whether understanding depends on tracing a
  tightly coupled mechanism end to end

#### 3. Epistemic / Scientific Variables

- Epistemic uncertainty: how much of the problem is still undefined
- Hypothesis-space width: how many plausible explanations or framings exist
- Exploration vs exploitation pressure: whether to broaden the search space or
  refine one candidate explanation
- Expected value of diversity: whether multiple perspectives are likely to
  surface meaningfully different hypotheses
- Novelty pressure: whether the goal is frontier mapping / breakthrough seeking
  or explanation of known structure
- Out-of-distribution domain risk: whether the query extends into knowledge
  domains, formalisms, or frontier problem areas that are likely weakly
  represented in the model's training distribution
- External-grounding pressure: whether the task likely requires heavier
  grounding in local artifacts, prior project materials, experiments, or
  specialized references because pretrained priors are less trustworthy
- Risk of false convergence or mode collapse: whether parallel children are
  likely to return the same framing in different words

#### 4. Runtime + Control Variables

- Root iteration budget
- Depth budget (`RLM_MAX_DEPTH`)
- Child concurrency budget
- Synthesis burden on the parent
- Cost of wrong early decomposition
- Need for transparent, auditable root-level investigation
- Tolerance for partial child failure during exploratory fanout

### Heuristics

Favor **Horizontal Understand** when:

- the task is narrow or tightly coupled
- ambiguity is high and decomposition is not yet trustworthy
- the likely insight depends on preserving causal continuity
- the query is attached to an active project with substantial prior
  understanding already available and the main need is to reactivate or refine
  that context
- the domain appears likely to be outside the model's training comfort zone, so
  careful local grounding is more trustworthy than fast fanout
- the parent needs to accumulate notes, buffers, and hypotheses in REPL locals
- the cost of wrong early fanout is high

Favor **Vertical Understand** when:

- the evidence surface is broad
- credible shard or perspective boundaries are already visible
- understanding work is independently parallelizable
- the parent's main job is exploration design plus synthesis
- prior groundwork exists but is itself broad enough to support trustworthy
  shard assignments or perspective-based exploratory fanout
- diverse subsystem or perspective summaries are likely to surface useful
  distinctions early

### Architecture-Mapped Examples

**Horizontal example:** a multi-turn depth-0 parent investigation of a narrow
failure path. The reasoning agent repeatedly calls `execute_code`, inspects a
fixture, test, and callback/dispatch code, and carries forward intermediate
hypotheses in REPL locals. No child orchestrators are spawned.

**Vertical example:** a breadth-first repo understanding pass where the parent
bootstraps shard or perspective assignments, then calls
`llm_query_batched(prompts)`. AST rewriting converts this to async child
dispatch, child orchestrators at depth+1 produce shard summaries, and the
parent synthesizes them into an Understand artifact.

### Failure Modes

- Choosing vertical too early and sharding on the wrong axes
- Choosing horizontal when breadth is high and burning too many root turns
- Mistaking repo size for safe decomposability
- Mistaking ambiguity for a reason to fan out rather than inspect locally
- Ignoring prior project groundwork and redundantly re-deriving an existing
  understanding base
- Failing to detect probable out-of-distribution domains, leading the system to
  over-trust pretrained intuition instead of grounding harder in artifacts and
  evidence
- False convergence from many children sharing the same framing error
- Mode collapse where parallel prompts create only superficial diversity

The key conclusion from both explorer reviews is that **Understand topology
selection should be provisional, epistemically cautious, and explicitly
revisable after the Understand artifact is produced**.

## Retrieval-Aware Understand

One major failure mode is treating `Understand` as if it only needs to analyze
what is already in prompt context. In practice, `Understand` often discovers
that critical evidence is missing and must be retrieved before downstream
planning or implementation is valid.

Example: a user asks for a model estimating how a new tax-code change will
affect this year's liability. An initial `Understand` pass may successfully
retrieve and interpret the new tax code, yet still discover that prior-year
W-2 data or other user-specific tax records are required before the task is
actually understandable in the sense needed for accurate planning or
implementation.

This means `Understand` must be modeled as an **elastic control loop**, not a
single bounded phase:

```
UnderstandProbe
  → DetectMissingPrereqs
  → AcquireEvidence
  → ReclassifyTopology
  → ContinueUnderstand
```

The topology engine therefore needs to support **topology invalidation**.
Missing prerequisites are not just observations; they can prove that the
currently selected topology is unsound.

### Design Principle

The initial prompt should classify only an **Understand probe topology**. It
should not assume the system already knows whether downstream understanding can
remain local, needs recursive retrieval, or must pause for user-provided
evidence.

After the probe, the system should decide among:

- continue current topology
- launch an evidence-acquisition sub-loop
- collapse a vertical topology back toward horizontal or parent-mediated hybrid
- escalate from horizontal probe to vertical deep understanding
- stop and ask the user for missing artifacts

### Understand Artifact Schema

Every `Understand` worker, whether parent-local or recursive child, should
emit a structured artifact. This is the control boundary that lets the parent
distinguish "I understand enough to continue" from "I discovered blockers that
change the topology decision."

Suggested shape:

```python
class UnderstandArtifact(BaseModel):
    understanding_status: Literal[
        "sufficient",
        "partial",
        "blocked",
        "invalidated",
    ]
    findings: list[str]
    assumptions_made: list[str]
    confidence: float | None = None
    missing_prerequisites: list[str]
    prerequisite_scope: Literal[
        "local",
        "shared",
        "user_provided",
        "external_reference",
    ] | None = None
    can_continue_without_it: bool = False
    retrieval_candidates: list[str]
    recommended_next_topology: str | None = None
    replan_reason: str | None = None
```

Interpretation:

- `sufficient`: enough evidence exists to choose downstream topology
- `partial`: understanding is progressing but further retrieval or inspection
  would materially improve confidence
- `blocked`: a prerequisite is missing and forward progress should pause
- `invalidated`: the current topology itself has been shown to be unsound

### Retrieval Classes

Not all missing prerequisites should trigger the same recovery behavior. The
parent should classify blockers by source:

- **Local/project retrieval**: search active-project files, session artifacts,
  prior notes, saved outputs, or known data directories
- **External retrieval**: fetch statutes, docs, datasets, APIs, or other
  authoritative references
- **User-provided evidence**: ask the user for documents, values, credentials,
  or decisions that cannot be safely inferred
- **Derived evidence**: run intermediate computations or transformations to
  construct missing inputs

This is where the "active project continuity" variable becomes operational:
queries associated with an ongoing project may already have groundwork or
artifact inventories that can satisfy newly discovered prerequisites with no
user interruption.

### Topology Safety Rule

Vertical `Understand` should be split into two sub-modes:

- **`vertical_probe`**: children map the evidence surface, shardability,
  dependency edges, and blockers
- **`vertical_deep_understand`**: children perform substantive understanding
  only after shared prerequisites are present or explicitly waived

This distinction matters because deep vertical fanout is unsafe when recursive
layers unknowingly depend on the same missing prerequisite. In that case,
children either generate low-quality work under hidden assumptions or stall on
the same blocker independently.

### Reclassification Rules

The parent should aggregate all child `UnderstandArtifact`s into a dependency
view before authorizing deeper fanout or transitioning to `Plan`.

Recommended rules:

- If blockers are **shared across many shards**, collapse toward horizontal or
  parent-mediated hybrid retrieval.
- If blockers are **user-provided**, suspend topology progression and request
  the missing inputs from the user.
- If blockers are **local to a shard**, keep the vertical structure and acquire
  per-shard evidence.
- If acquisition resolves the main uncertainty and shard boundaries become
  clearer, escalate from horizontal probe to vertical deep understanding.
- If acquisition reveals tighter coupling than expected, collapse vertical work
  back to horizontal or hybrid synthesis.
- If the domain appears out-of-distribution and evidence remains thin, bias
  toward slower grounded understanding instead of broad speculative fanout.

### Proposed State + Instruction Wiring

This can be built on the existing extension seams already identified in the
architecture docs.

Suggested new state keys:

- `polya_phase`
- `polya_topology`
- `polya_topology_version`
- `understand_status`
- `understand_artifact`
- `understand_missing_prereqs`
- `understand_retrieval_queue`
- `understand_blockers`
- `understand_dependency_graph`
- `polya_replan_reason`

Suggested dynamic-instruction placeholders:

- `{polya_phase?}`
- `{polya_topology?}`
- `{understand_status?}`
- `{understand_blockers?}`
- `{retrieval_policy?}`
- `{polya_replan_reason?}`

Callback behavior:

- `before_agent_callback`: choose only the initial Understand probe topology
- `before_model_callback`: inject phase-specific guidance about whether the
  agent is probing, acquiring evidence, resuming Understand, or executing a
  reclassified topology
- REPL/dispatch flush path: persist child blocker summaries and retrieval
  outcomes through tracked state channels

### Practical Control Flow

```text
User prompt
  → Select provisional UnderstandProbe topology
  → Run UnderstandProbe
  → Emit parent/child UnderstandArtifact(s)
  → Any blockers?
      no  → choose Plan / Implement / Reflect topology
      yes → classify blocker source + scope
           → run acquisition loop
           → update UnderstandArtifact
           → reclassify topology
           → resume Understand or proceed downstream
```

The key implementation point is that **missing-information discovery must be
able to invalidate the current topology**. Topology selection is therefore not
just a startup decision; it is a revisable control policy coupled to the
system's evolving evidence state.

## Related Docs

- [skills_and_prompts.md](../skills_and_prompts.md) — dynamic instruction slot
- [dispatch_and_state.md](../dispatch_and_state.md) — depth scoping, state keys
- [core_loop.md](../core_loop.md) — callback chain, orchestrator lifecycle

## Research References

- `ai_docs/codebase_documentation_research/progressive_disclosure_patterns.md`
- `rlm_adk_docs/codex_polya_workflow.md`
