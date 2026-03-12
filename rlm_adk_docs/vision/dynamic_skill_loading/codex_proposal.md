I reviewed the vision doc and the current RLM-ADK instruction/skill wiring. The key reality is this:

Right now, skills are still static prompt text appended in `create_reasoning_agent()` via `build_skill_instruction_block()`, and only the root agent gets the repomix skill by default (`include_repomix=True` for parent, `False` for children) in [`rlm_adk/agent.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/agent.py). The real dynamic insertion point is the ADK `instruction=` template path backed by session state and merged by the reasoning callback, as documented in [`rlm_adk_docs/skills_and_prompts.md`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk_docs/skills_and_prompts.md) and implemented through [`rlm_adk/utils/prompts.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/utils/prompts.py). The envisioned source signals for mining successful workflows already exist: REPL trace artifacts and persisted code/artifacts, called out in [`dynamic_skill_loading.md`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk_docs/vision/dynamic_skill_loading.md), with trace persistence in [`rlm_adk/plugins/repl_tracing.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/plugins/repl_tracing.py) and REPL/runtime wiring in [`rlm_adk/orchestrator.py`](https://github.com/RawleySM/rlm-adk/blob/main/rlm_adk/orchestrator.py).

Below are 3 architectural implementations that fit your broader objective.

---

## Architecture 1 — Runtime-Retrieved Python Skills

### Best “ship this first” option

### What it is

Every successful task run that meets promotion criteria gets converted into:

1. a real Python helper function,
2. a `Skill(...)` object with ADK frontmatter,
3. a retrieval record in a local skill registry.

At the start of a new task, the system embeds the incoming prompt, retrieves matching promoted skills, injects their frontmatter/instructions into the dynamic instruction, and also injects the actual Python callables into the REPL globals for both parent and child agents.

### Why this fits your codebase

This is the least disruptive path because it matches how repomix already works:

* prompt-side discovery via ADK skill frontmatter/instructions,
* runtime REPL function injection in `orchestrator.py`,
* dynamic session-state-based prompt insertion via `RLM_DYNAMIC_INSTRUCTION`.

It is basically “repomix generalized.”

### How it works

#### A. Promotion step after successful run

Add a promotion pipeline that:

* reads the saved REPL code artifact for a successful run,
* finds the minimal successful code span,
* wraps it into a function like:

```python
def summarize_invoice_csv(path: str) -> str:
    ...
```

* emits a new file like:

```text
rlm_adk/skills/generated/summarize_invoice_csv_skill.py
```

with:

* generated Python helper,
* `Skill(frontmatter=..., instructions=...)`,
* `build_skill_instruction_block()` equivalent.

Also create/update a local registry table/jsonl, for example:

```text
.adk/skills/registry.sqlite
```

Fields:

* `skill_id`
* `name`
* `description`
* `embedding`
* `code_hash`
* `function_module`
* `function_name`
* `input_schema_json`
* `output_schema_json`
* `success_count`
* `last_validated_at`
* `depth_scope` (`root`, `child`, `both`)
* `status` (`draft`, `promoted`, `disabled`)

#### B. Retrieval at run start

Before the reasoning loop starts in `RLMOrchestratorAgent._run_async_impl()`:

* embed `root_prompt`
* query skill registry
* retrieve top-K promoted skills
* build:

  * `dynamic_skill_frontmatter`
  * `dynamic_skill_instructions`
  * `dynamic_skill_imports`

Write those to session state using `EventActions(state_delta=...)`.

Then extend `RLM_DYNAMIC_INSTRUCTION` to include:

```text
Relevant skills:
{dynamic_skill_frontmatter?}

Usage details:
{dynamic_skill_instructions?}
```

#### C. Runtime callable injection

Also in `_run_async_impl()`:

* import the retrieved helper modules dynamically,
* place the helper functions into `repl.globals[...]`.

So the model sees:

* ADK-style skill metadata in prompt,
* and the actual callable is really there.

That is the critical part. Otherwise you end up with “prompt lies.”

### Files to add/change

* `rlm_adk/skill_registry.py`
* `rlm_adk/skills/generated/`
* `rlm_adk/skill_promotion.py`
* `rlm_adk/skill_retrieval.py`
* `rlm_adk/utils/prompts.py` — add dynamic placeholders
* `rlm_adk/orchestrator.py` — retrieve/inject skills before reasoning
* `rlm_adk/agent.py` — optionally enable retrieval for children too

### Strengths

* Closest to current architecture
* Easy to reason about
* Works for parent and child agents
* Real Python functions, not vague recipes

### Weaknesses

* Synthesizing a safe general-purpose function from arbitrary REPL code is hard
* You will promote some brittle junk unless you validate hard
* Generated code modules can sprawl fast

### Best use case

When you want the promoted artifact to literally become a one-line callable like:

```python
result = reconcile_vendor_names(df)
```

---

## Architecture 2 — Draft/Promote Skill Factory with Offline Validation

### Best long-term maintainable option

### What it is

Instead of promoting successful runs directly during the live task, successful runs are turned into **draft skills** first. A separate evolution/promotion workflow validates, generalizes, and versions them before they ever become available to runtime agents.

This is the cleanest architecture if you want the skill library to keep getting better instead of getting polluted.

### Core idea

Use a two-lane pipeline:

#### Lane 1: Live execution lane

During a normal task run:

* trace REPL code
* capture success outcome
* save candidate skill artifacts as drafts

#### Lane 2: Skill-factory lane

A separate agent or job:

* reads new drafts
* clusters similar drafts
* canonicalizes parameters
* generates a reusable function signature
* creates tests from the original run context
* replays against new fixtures
* promotes only if it passes
* writes final ADK skill frontmatter + Python helper + embedding record

### Why this fits your roadmap

Your repo already has a strong deterministic testing mindset and provider-fake infrastructure in the docs. This architecture lines up with the “autonomous self-improvement” direction without contaminating the live execution loop.

### Implementation shape

#### Draft artifact format

On successful completion, store a draft object like:

```json
{
  "draft_id": "skill_draft_2026_03_11_001",
  "root_prompt": "...",
  "depth": 0,
  "code_text": "...",
  "trace_summary": {...},
  "inputs_observed": {...},
  "outputs_observed": {...},
  "reasoning_summary": "...",
  "success_signal": true,
  "source_artifacts": [...]
}
```

#### Promotion workflow

A skill-factory job then:

1. extracts repeated code motifs,
2. infers a stable function boundary,
3. generates:

   * Python helper
   * frontmatter description
   * usage instructions
   * unit tests / contract tests
4. executes validation
5. if passed, stores promoted version:

   * `skill_name@v1`
   * `skill_name@v2`
   * deprecates old versions later

### Retrieval path

Same retrieval pattern as Architecture 1, but only against promoted skills.

### Files to add/change

* `rlm_adk/skills/drafts/`
* `rlm_adk/skills/promoted/`
* `rlm_adk/skill_factory/cluster.py`
* `rlm_adk/skill_factory/generalize.py`
* `rlm_adk/skill_factory/validate.py`
* `rlm_adk/skill_factory/promote.py`
* `rlm_adk/skill_registry.py`
* optional: `tests_rlm_adk/generated_skills/`

### Strengths

* Much safer than direct auto-promotion
* Gives you versioning and deprecation
* Lets you test for generalization before surfacing a skill
* Prevents prompt bloat from junk skills

### Weaknesses

* More moving parts
* New skills are not instantly available after first success
* You need a real promotion policy

### Best use case

When you care about **durable reusable skills**, not just flashy retrieval.

### My blunt take

If you’re serious about this system and not just proving a demo, this is the right backbone.

---

## Architecture 3 — Recipe Graphs First, Python Wrapper Second

### Best if you want workflow reuse more than raw code reuse

### What it is

Instead of treating successful runs primarily as code to be promoted, treat them as **canonical workflow recipes** first.

A successful run becomes a structured graph:

* load data
* inspect shape
* choose chunk strategy
* batch child analysis
* aggregate
* finalize

Then the system auto-generates:

1. a recipe spec,
2. a thin Python one-line wrapper,
3. an ADK skill frontmatter block describing when to use it.

So the reusable unit is not “this exact code block,” but “this workflow topology.”

### Why this is different

This is stronger for RLM-ADK because a lot of your workflows are not just helper functions. They are recurring orchestration shapes:

* probe → branch on size
* shard → batched child calls → synthesize
* load → summarize each section → aggregate
* detect schema → map columns → validate

Those are recipes, not just functions.

### Example

A successful repo-analysis flow might become:

```yaml
name: analyze_repo_by_size
match_signals:
  - repository url present
  - codebase analysis requested
steps:
  - op: probe_repo
  - branch:
      if: total_tokens < 125000
      then:
        - op: pack_repo
        - op: llm_query
      else:
        - op: shard_repo
        - op: llm_query_batched
        - op: llm_query
returns:
  - final_analysis
```

Then generate a wrapper:

```python
def analyze_repo_by_size(source: str, query: str) -> str:
    return run_recipe("analyze_repo_by_size", source=source, query=query)
```

And frontmatter:

```python
Frontmatter(
    name="analyze-repo-by-size",
    description="Use when a task asks for codebase understanding from a local path or git URL..."
)
```

### Runtime behavior

At task start:

* retrieve relevant recipes by embedding + metadata
* inject recipe frontmatter/instructions into prompt
* inject wrapper functions into REPL
* wrapper delegates to a deterministic recipe executor

That means the agent still gets the “single code-line function” experience, but the implementation is standardized underneath.

### Why this may be better than direct code promotion

Because arbitrary REPL code is messy. Workflow shapes are much easier to generalize safely.

### Files to add/change

* `rlm_adk/recipes/`
* `rlm_adk/recipe_executor.py`
* `rlm_adk/recipe_promotion.py`
* `rlm_adk/recipe_retrieval.py`
* `rlm_adk/generated_wrappers/`
* `rlm_adk/utils/prompts.py`
* `rlm_adk/orchestrator.py`

### Strengths

* Reuses orchestration patterns, not brittle literal code
* Easier to validate and evolve
* Great fit for parent/child symmetry
* Makes child workflows first-class, not second-class

### Weaknesses

* More abstraction
* Harder to support arbitrary custom Python edge cases
* Requires a recipe DSL or graph schema

### Best use case

When what you actually want to preserve is “how the agent solved the class of problem,” not just a literal function body.

---

# Recommendation

## Best immediate choice: Architecture 1

Because it is the fastest route from your current repomix-only model to actual dynamic reusable skills.

## Best serious production choice: Architecture 2

Because uncontrolled auto-promotion will rot the system. Fast.

## Most aligned with RLM-ADK’s deeper strengths: Architecture 3

Because your system is inherently about recursive workflow patterns, not just helper methods.

---

# What I would build in your repo

I would do this in phases:

### Phase 1

Implement Architecture 1 in a constrained way:

* only promote runs explicitly marked successful,
* only for a narrow class of workflows,
* only if function signature inference is clean,
* only inject top 3 retrieved skills,
* enable for both parent and child agents.

### Phase 2

Wrap that with Architecture 2:

* draft → validate → promote
* versioned registry
* replay tests before promotion

### Phase 3

Add Architecture 3 for the recurring orchestration topologies:

* shard/summarize/synthesize
* load/classify/aggregate
* inspect/branch/fanout/merge

That gives you both:

* concrete one-line helper functions,
* and reusable multi-step workflow recipes.

---

# Concrete codebase-level changes I’d make first

1. Extend `RLM_DYNAMIC_INSTRUCTION` in `rlm_adk/utils/prompts.py` with placeholders for retrieved skills.

2. Add a `SkillRegistry` service and retrieval module.

3. In `RLMOrchestratorAgent._run_async_impl()`:

   * retrieve relevant skills before yielding initial prompt,
   * write their frontmatter/instructions into state,
   * import/inject their callables into `repl.globals`.

4. Remove the root-only limitation for dynamic skills.

   * repomix can stay parent-only if desired,
   * dynamic retrieved skills should support `depth_scope = both`.

5. Add a promotion pipeline that consumes:

   * REPL code artifacts,
   * `repl_traces.json`,
   * final success outcome,
   * observed inputs/outputs.

6. Add validation gates before promotion.

   * no gate = junk drawer.

---

# Bottom line

The objective is valid, but the system only works if **prompt retrieval and callable injection are coupled**. Frontmatter alone is not enough. The agent must see a discovered skill in prompt text and also find a matching callable already loaded in the REPL.

That is the non-negotiable design rule.

If you want, I’ll turn this into a concrete implementation spec with proposed modules, dataclasses, state keys, registry schema, and the exact edits to `agent.py`, `orchestrator.py`, and `prompts.py`.
