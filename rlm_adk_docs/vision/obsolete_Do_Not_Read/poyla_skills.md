<!-- validated: 2026-03-10 -->

# Polya Skills Plan: Single-Phase REPL Skill

## Goal

Define one REPL skill function, `polya_phase(...)`, that executes exactly one
Polya phase at a time:

- `understand`
- `plan`
- `implement`
- `reflect`

The function should accept a **narrative memo from the parent**, use
**phase-specific typed schemas**, render **prompt templates for child
`llm_query` calls**, and return a **narrative-first phase result** with a small
control envelope.

This is intended as a practical evolution of the current repomix-style skill
system, not a replacement of the existing orchestrator or dispatch stack.

---

## What The Current System Already Gives Us

Reviewing the current implementation suggests that most of the needed runtime
machinery already exists:

- `rlm_adk/skills/repomix_skill.py` shows the current skill pattern:
  `Skill(frontmatter=..., instructions=...)` plus
  `build_skill_instruction_block()`.
- `rlm_adk/agent.py` appends the repomix skill instructions to
  `RLM_STATIC_INSTRUCTION` in `create_reasoning_agent(...)` when
  `include_repomix=True`.
- `rlm_adk/orchestrator.py` injects runtime helpers into `repl.globals`, which
  is the real execution surface for skills.
- `rlm_adk/utils/prompts.py` keeps `RLM_DYNAMIC_INSTRUCTION` very small:
  `{repo_url?}`, `{root_prompt?}`, `{test_context?}`. That means memo-carrying
  should initially happen through function arguments, not new callback-heavy
  state plumbing.
- `rlm_adk/dispatch.py` already supports `llm_query(..., output_schema=...)`
  and `llm_query_batched(..., output_schema=...)`, and child orchestrators
  already preserve validated structured output in `LLMResult.parsed`.
- `rlm_adk/agent.py:create_child_orchestrator(...)` already wires condensed
  child prompts and an optional `output_schema`, so a Polya skill can reuse the
  existing child-orchestrator path instead of inventing a separate worker layer.

The main gap is not child recursion. The main gap is packaging it behind a
single REPL-facing phase helper.

---

## Hard Constraints From The Existing Code

### 1. A fully encapsulated phase helper must be async-capable

Today, `rlm_adk/repl/ast_rewriter.py` only switches REPL code into the async
path when it sees literal calls to:

- `llm_query(...)`
- `llm_query_batched(...)`

That means a helper injected into `repl.globals` cannot internally perform
child dispatch unless one of these happens:

- the AST rewriter is extended to recognize `polya_phase(...)`, or
- the helper is reduced to a prompt-bundle builder instead of a true executor.

If the goal is a single function that actually encapsulates one phase, the
recommended path is to extend the AST trigger/rewriter and make
`polya_phase(...)` a first-class async-capable REPL helper.

### 2. Batched child calls must share one schema

`llm_query_batched(..., output_schema=...)` accepts one schema for the whole
batch. So a single `polya_phase(...)` run can batch only **homogeneous child
work packets**.

That is acceptable and even desirable for a phase-oriented design:

- one `understand` fanout should return one `UnderstandArtifact` shape
- one `plan` fanout should return one `PlanArtifact` shape
- one `implement` fanout should return one `ImplementArtifact` shape
- one `reflect` fanout should return one `ReflectArtifact` shape

### 3. REPL-visible return values should stay JSON-friendly

`rlm_adk/tools/repl_tool.py` only returns variables that are JSON-serializable
primitives, lists, or dicts. Pydantic models can live in REPL locals, but they
will not reliably surface through the tool result unless converted.

So the skill should:

- use Pydantic internally for validation
- return `model_dump()` payloads to the REPL by default

This preserves typed contracts without fighting the existing tool boundary.

### 4. Root-only prompt injection is enough for the first slice

The current repomix skill is injected only at the parent level. That is fine
for the first Polya skill iteration too. The parent needs the helper; children
only need the rendered prompts and schemas.

---

## Proposed User-Facing API

The model-facing surface should be one helper:

```python
phase_result = polya_phase(
    phase="understand",
    memo=ParentPhaseMemo(
        phase="understand",
        task="Map the failure surface before proposing a fix.",
        memo_text="We know the bug reproduces in provider-fake tests, but we do not yet know whether the fault is in dispatch, callbacks, or prompt wiring.",
        constraints=["Prefer grounded inspection over speculative fanout."],
        success_criteria=["Identify likely fault boundaries", "Surface blockers"],
    ),
    topology="vertical",
    work_packets=packets,
)
```

Design intent:

- one call runs one phase
- the parent passes a narrative memo, not raw fragmented fields
- the function chooses the correct prompt templates and schemas for that phase
- the function may execute horizontally or vertically
- the function returns a narrative artifact plus a small control envelope

---

## Typed Schema Stack

The thin-structure / thick-prose split from
`vision/narrative_polya_topology_engine.md` should be the default.

### Input schema

```python
from typing import Literal
from pydantic import BaseModel, Field

PolyaPhase = Literal["understand", "plan", "implement", "reflect"]


class ParentPhaseMemo(BaseModel):
    phase: PolyaPhase
    task: str
    memo_text: str
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    prior_artifact_refs: list[str] = Field(default_factory=list)
    topology_hint: str | None = None


class PhaseWorkPacket(BaseModel):
    packet_id: str
    assignment: str
    evidence: str | None = None
    artifact_ref: str | None = None
```

### Shared narrative/control base

```python
class PhaseNarrative(BaseModel):
    phase: PolyaPhase
    memo_title: str | None = None
    memo_text: str
    trajectory_summary: str = ""


class PhaseControlEnvelope(BaseModel):
    phase: PolyaPhase
    status: str
    confidence: float | None = None
    blockers: list[str] = Field(default_factory=list)
    missing_prerequisites: list[str] = Field(default_factory=list)
    recommended_topology: str | None = None
    next_action: str | None = None
```

### Phase result schemas

The first implementation can use the same schema for child returns and final
phase synthesis:

| Phase | Child schema | Final phase schema |
|------|------|------|
| `understand` | `UnderstandArtifact` | `UnderstandArtifact` |
| `plan` | `PlanArtifact` | `PlanArtifact` |
| `implement` | `ImplementArtifact` | `ImplementArtifact` |
| `reflect` | `ReflectArtifact` | `ReflectArtifact` |

Suggested shape:

```python
class UnderstandArtifact(BaseModel):
    narrative: PhaseNarrative
    control: PhaseControlEnvelope
    findings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class PlanArtifact(BaseModel):
    narrative: PhaseNarrative
    control: PhaseControlEnvelope
    work_packets: list[PhaseWorkPacket] = Field(default_factory=list)
    merge_strategy: str = ""
    verification_requirements: list[str] = Field(default_factory=list)


class ImplementArtifact(BaseModel):
    narrative: PhaseNarrative
    control: PhaseControlEnvelope
    actions_taken: list[str] = Field(default_factory=list)
    evidence_collected: list[str] = Field(default_factory=list)
    unresolved_risks: list[str] = Field(default_factory=list)


class ReflectArtifact(BaseModel):
    narrative: PhaseNarrative
    control: PhaseControlEnvelope
    what_worked: list[str] = Field(default_factory=list)
    what_failed: list[str] = Field(default_factory=list)
    next_cycle_advice: list[str] = Field(default_factory=list)
```

The single helper does not need one generic mega-schema. It should select the
phase schema internally and return a JSON-friendly dict representation.

---

## Prompt Template Strategy

The prompt templates should live in code, not in the static system prompt.
`REPOMIX_SKILL.instructions` works as human-facing API documentation, but
Polya child templates are runtime assets and should stay versioned in Python
constants.

### Child prompt template

```text
You are executing the {phase} phase of a Polya workflow.

Task:
{task}

Narrative memo from parent:
{memo_text}

Constraints:
{constraints_block}

Success criteria:
{success_block}

Assigned work packet:
{work_packet_block}

Write a rich narrative memo first, then distill only the minimum structure
needed for control. Return only data matching the {schema_name} schema.
```

### Synthesis prompt template

```text
You are synthesizing {phase} phase outputs from child workers.

Original task:
{task}

Parent narrative memo:
{memo_text}

Child artifacts:
{child_artifacts_block}

Produce one unified narrative memo plus one minimal control envelope.
Return only data matching the {schema_name} schema.
```

### Why this matches the current runtime

- child work still flows through `llm_query` / `llm_query_batched`
- typed validation still uses the existing `output_schema` argument
- final synthesis still uses one more structured `llm_query`
- no new agent type is required

---

## Execution Model Inside `polya_phase(...)`

Recommended runtime algorithm:

1. Validate `memo` and optional `work_packets`.
2. Select the phase profile:
   - child schema
   - final schema
   - child prompt template
   - synthesis prompt template
3. If `topology == "horizontal"`:
   - render one prompt from the parent memo
   - call `llm_query(prompt, output_schema=final_schema)`
4. If `topology in {"vertical", "hybrid"}`:
   - render one child prompt per work packet
   - call `llm_query_batched(prompts, output_schema=child_schema)`
   - synthesize child artifacts with one final
     `llm_query(synthesis_prompt, output_schema=final_schema)`
5. Return `final_result.model_dump()`.

This keeps the skill narrow:

- it is a phase executor, not a full topology engine
- it does not own phase transitions
- it does not own long-lived state mutation
- it simply turns a parent memo into one validated phase artifact

---

## Practical Migration Path From The Current Repomix Skill

### Stage 1: Mirror the repomix integration pattern

Add one new skill module that looks structurally like `repomix_skill.py`:

- `Skill(frontmatter=..., instructions=...)`
- `build_polya_skill_instruction_block()`

Keep the skill instructions short. Document the public helper, not the full
child prompt templates.

### Stage 2: Inject one runtime helper into the REPL

Follow the same injection seam used in `orchestrator.py` for repomix helpers,
but inject:

- `polya_phase`
- any internal schema classes needed by the helper

This keeps the existing skill model intact: prompt instructions plus a real
callable in `repl.globals`.

### Stage 3: Extend the REPL async bridge

This is the key enabling change for real encapsulation.

Update `rlm_adk/repl/ast_rewriter.py` so that:

- `has_llm_calls(...)` also treats `polya_phase(...)` as an async-trigger name
- the rewriter maps `polya_phase(...)` to `await polya_phase_async(...)`, or
  otherwise treats it as an awaitable helper

Without this step, the helper cannot honestly encapsulate child `llm_query`
calls.

### Stage 4: Reuse existing structured child dispatch

Do not add a new worker abstraction. Internally, the helper should call the
existing:

- `llm_query(..., output_schema=...)`
- `llm_query_batched(..., output_schema=...)`

That lets `dispatch.py`, child orchestrators, structured-output retry logic,
and observability keep working unchanged.

### Stage 5: Add minimal dynamic-instruction support

Once the helper exists, extend `RLM_DYNAMIC_INSTRUCTION` with only a few
optional placeholders:

- `{polya_phase?}`
- `{polya_topology?}`
- `{parent_memo_digest?}`

This should be additive. The memo itself should still travel as function input.
Dynamic instruction should carry lightweight situational hints, not the full
artifact body.

### Stage 6: Reframe repomix as a subordinate capability

Do not replace `probe_repo`, `pack_repo`, or `shard_repo`.

Instead:

- `polya_phase(phase="understand", ...)` may use repomix-derived work packets
- `polya_phase(phase="plan", ...)` may consume understanding artifacts built
  from repomix shards

This keeps repomix as an evidence-acquisition helper and moves coordination
into the Polya skill.

---

## Recommended First Slice

The first implemented phase should be `understand`.

Reason:

- it matches the current repomix workflow most naturally
- it benefits immediately from narrative memo input
- it exercises typed child schemas and synthesis without requiring code-edit
  execution contracts yet
- it gives the topology engine a strong artifact boundary for later `plan`
  routing

A practical first release can therefore ship:

- one public helper: `polya_phase(...)`
- one fully implemented phase profile: `understand`
- stubs or explicit `NotImplementedError` for `plan`, `implement`, `reflect`

That is enough to prove the pattern before broadening it.

---

## Acceptance Criteria

The design is successful when all of these are true:

- the parent can call one REPL helper with a narrative memo and get back one
  validated phase artifact
- vertical execution uses existing child orchestrators through
  `llm_query` / `llm_query_batched`
- phase outputs are narrative-first but also machine-routable
- the helper returns JSON-friendly payloads that survive the current REPL tool
  boundary
- the change coexists with repomix rather than replacing it
- the implementation requires only incremental changes to the current
  `Skill` + `repl.globals` + dispatch architecture

---

## Main Risk To Watch

The highest-risk failure mode is pretending the helper is encapsulated while it
still depends on literal `llm_query(...)` calls in user-authored REPL code.

If that constraint is not addressed in the AST bridge, the system will drift
back toward a prompt-only skill that merely suggests a Polya workflow instead
of actually executing one.

That is the architectural line to hold.
