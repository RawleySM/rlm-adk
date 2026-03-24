# Research Prompt: Imported Skill Helper Capabilities And Limits

You are investigating the **current implementation limits** of imported REPL skill helper scripts in this repository.

Your job is to produce a **research memo**, not a patch. Do not implement a fix. Do not propose code changes beyond identifying the exact seams where a future implementation would have to hook in. Ground every conclusion in the current code.

## Core Question

When a skill helper is abstracted behind a single-line function call in REPL-authored code, what can that helper contain today?

Specifically investigate:

1. Can the abstracted helper contain `llm_query(...)` or `llm_query_batched(...)`?
2. If yes, under what delivery mode and lifecycle conditions?
3. Can the helper rely on source expansion, and if so, what exact import forms are supported?
4. Can the helper read pre-defined state keys?
5. Can the helper create new state key-value pairs that persist through ADK-tracked channels?
6. Can the helper influence dynamic instruction variables?
7. Can the helper carry or forward `output_schema` into child calls?
8. What differs between:
   - a helper injected directly into `repl.globals`
   - a helper delivered through source-expanded synthetic imports
   - a helper defined in one REPL turn and called in a later turn
9. What current limitations are hard runtime constraints versus just undocumented or unimplemented extension points?

## Output Requirements

Produce a memo with these sections:

1. `Short Answer`
2. `What Imported Skill Helpers Can Contain Today`
3. `What They Cannot Safely Contain Today`
4. `State And Dynamic Instruction Boundaries`
5. `Single-Turn vs Cross-Turn Behavior`
6. `Parent vs Child Orchestrator Behavior`
7. `Open Extension Seams`
8. `Evidence Table`

For the `Evidence Table`, include:

- file path
- class/function name
- line numbers
- what that location proves

## Research Constraints

- Do not write code.
- Do not modify files.
- Do not provide code solutions or patches.
- Do not rely on memory or docs alone when the source code is available.
- Use docs only to frame intent; source code is the authority.
- Distinguish carefully between:
  - what is implemented
  - what is documented as planned
  - what is only possible with future plumbing
- If you infer behavior rather than reading it directly, label it explicitly as an inference.

## Primary Files To Inspect

Start with these exact code paths and line ranges.

### Skill expansion and import contract

- `rlm_adk/repl/skill_registry.py`
  - `ReplSkillExport` and `ExpandedSkillCode`: lines 14-29
  - `SkillRegistry.expand()`: lines 58-169
  - `_collect_user_defined_names()`: lines 190-209

Questions to answer from this file:

- What import shapes are supported?
- What gets expanded into executable source?
- What conflicts or unsupported forms are rejected?
- Does expansion operate on arbitrary runtime globals, or only on parsed submitted code?

### REPL execution pipeline

- `rlm_adk/tools/repl_tool.py`
  - skill expansion pass: lines 158-181
  - `has_llm_calls()` / `rewrite_for_async()` execution path: lines 183-213
  - `tool_context.state[...]` writes for REPL metadata: lines 111-116, 130, 175-181, 195-205
  - accumulator flush into `tool_context.state`: later in `run_async`, especially the flush path after execution

Questions to answer from this file:

- At what exact stage does source expansion happen?
- What source string does the AST rewriter inspect?
- What state writes are possible from this layer?
- Are those writes originating from the helper itself, or from `REPLTool` infrastructure?

### AST rewrite behavior

- `rlm_adk/repl/ast_rewriter.py`
  - `has_llm_calls()`: lines 15-36
  - `LlmCallRewriter.visit_Call()`: lines 55-67
  - `_promote_functions_to_async()`: lines 82-119
  - `rewrite_for_async()`: lines 161-228

Questions to answer from this file:

- What exact call patterns are detected?
- Does the rewriter inspect runtime function objects?
- Under what circumstances will helper-contained `llm_query(...)` be seen and rewritten?
- What are the lexical limitations?

### REPL namespace wiring

- `rlm_adk/repl/local_repl.py`
  - REPL globals/locals initialization: lines 204-213
  - `set_llm_query_fns()`: lines 215-218
  - `set_async_llm_query_fns()`: lines 220-227
  - async execution namespace merge: lines 421-427 in `execute_code_async()`

- `rlm_adk/orchestrator.py`
  - REPL setup and globals injection: lines 231-275
  - `sync_llm_query_unsupported`: lines 258-265
  - initial state seeding for dynamic instruction vars: lines 309-320

Questions to answer from these files:

- What lives in `repl.globals` versus `repl.locals`?
- Can an injected helper in `repl.globals` contain `llm_query(...)` safely?
- Is there any mechanism that expands or rewrites code hidden inside a runtime-injected Python callable?
- What does the parent orchestrator write into state before reasoning begins?

### Dynamic instruction resolution

- `rlm_adk/utils/prompts.py`
  - `RLM_DYNAMIC_INSTRUCTION`: lines 82-86

- `rlm_adk/agent.py`
  - `create_reasoning_agent()` and `instruction=dynamic_instruction`: lines 188-270

- `rlm_adk/callbacks/reasoning.py`
  - `reasoning_before_model()`: lines 109-170

- `rlm_adk/state.py`
  - dynamic instruction keys: lines 35-39
  - state key catalog: lines 31-105
  - depth-scoping rules: lines 143-176

Questions to answer from these files:

- Where do dynamic instruction variables come from?
- Which state keys are already wired into dynamic instruction resolution?
- Can an imported helper create new dynamic instruction variables directly?
- If not directly, what tracked state channels would a future implementation need to use?

### Child dispatch and structured output

- `rlm_adk/dispatch.py`
  - `create_dispatch_closures()`: lines 105-142
  - child completion reading: lines 199-311
  - `_run_child(...)`: lines 313-560

Questions to answer from this file:

- Can a helper forward `output_schema` into child `llm_query(...)` calls?
- What does the child inherit from the parent?
- How are child results normalized back into `LLMResult`?
- Does dispatch expose a path for helper-authored state creation, or only for child query execution and observability accumulation?

## Secondary Context Files

Use these only after reading source:

- `rlm_adk_docs/skills_and_prompts.md`
- `rlm_adk_docs/core_loop.md`
- `rlm_adk_docs/dispatch_and_state.md`
- `rlm_adk_docs/vision/narrative_polya_topology_engine_with_skills.md`

In particular, compare docs against current code for:

- the stated split between `repl.globals` injection and source-expandable imports
- any documented cross-turn limitations
- any planned but not yet implemented narrative/dynamic-instruction state expansion

## Specific Issues To Resolve

Your memo must explicitly resolve each of these:

1. Is this statement true, false, or only partially true?
   `A zero-import helper preloaded into repl.globals cannot safely contain llm_query() today.`

2. Is this statement true, false, or only partially true?
   `Code expansion lets the AST rewriter catch llm_query() inside imported skill helpers.`

3. If #2 is true, define the exact boundary:
   - same-block import + call?
   - later-block call after a prior import?
   - helper already present in `repl.globals`?

4. Can a helper create:
   - a plain REPL local variable?
   - a `tool_context.state[...]` write?
   - a `callback_context.state[...]` write?
   - an `EventActions(state_delta=...)` write?

5. Can a helper mint new state keys that later appear in dynamic instruction template resolution without changes outside the helper?

6. If not, identify the specific classes/functions that would have to participate in such a bridge, using file names and line numbers only.

## Deliverable Standard

Your final memo should read like a technical adjudication of the current runtime behavior. Favor precise statements such as:

- `Implemented and safe today`
- `Implemented but constrained`
- `Possible only through existing infrastructure outside the helper body`
- `Not implemented`
- `Documented as future design only`

Do not end with a patch. End with a crisp boundary statement summarizing:

- what a single-line imported helper can abstract today
- what still requires orchestrator / REPLTool / callback / state-template plumbing outside the helper
