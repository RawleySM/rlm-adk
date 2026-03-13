# Skill Import Expansion For `llm_query`-Aware REPL Modules

## Summary

RLM-ADK uses a distinctive skill pattern: when a skill is activated for the
agent, the prompt-layer skill definition describes the I/O contract and example
usage of one or more Python functions or classes, while backend orchestrator
code injects those skill functions into the REPL environment through
`repl.globals`. The agent then uses those skill functions directly inside its
`execute_code` submissions, allowing REPL-authored Python to compose one or
more functions defined across one or more skill scripts.

Implement a pre-AST-rewrite expansion layer for activated REPL skills so the
model can write import-style skill usage in `execute_code`, while any hidden
`llm_query(...)` / `llm_query_batched(...)` calls inside those imported skill
functions are expanded into plain source before the existing AST rewriter runs.

This preserves the current REPL authoring ergonomics and skill abstraction
model, while removing the current limitation that `llm_query` is only
rewrite-visible when it appears directly in the submitted code block.

The implementation should keep two distinct skill delivery modes:

- `repl.globals` injection for simple helper functions that do not need AST rewriting
- source-expanding synthetic imports for skills whose implementation contains `llm_query(...)` or `llm_query_batched(...)`

## Key Changes

### 1. Add a new synthetic REPL skill import system

Create a skill-export registry for source-expandable REPL imports.

- Add a new internal abstraction, `ReplSkillExport`, with at least:
  - `module`: synthetic module path, e.g. `rlm_repl_skills.ping`
  - `name`: exported symbol name
  - `source`: full source text to inline into submitted code
  - `requires`: ordered dependencies by exported symbol name
  - `kind`: one of `class`, `const`, `function`, or `source_block`
- Add a registry module that can:
  - register exports by synthetic module path
  - resolve `from rlm_repl_skills.<skill> import ...`
  - return a topologically sorted expansion set based on requested names plus dependencies
- Use explicit source strings or dedicated source-template builders as the canonical export format. Do not use `inspect.getsource()` as the primary mechanism.

Default assumption:

- Only `from ... import ...` form is supported in v1.
- Plain `import rlm_repl_skills.ping as ping` is out of scope for v1.
- Wildcard imports are out of scope for v1.

### 2. Add a pre-rewrite skill expansion pass in `REPLTool`

Update the `execute_code` pipeline so expansion happens before `has_llm_calls()`.

Required order:

1. receive submitted code
2. expand synthetic skill imports into inline source
3. run `has_llm_calls()` on expanded code
4. run `rewrite_for_async()` on expanded code when needed
5. execute expanded code
6. preserve original submitted code separately for observability

Behavior requirements:

- Parse submitted code to AST and detect `ImportFrom` nodes targeting the synthetic namespace, e.g. `rlm_repl_skills.*`
- Remove those import nodes and replace them with inline source blocks for the requested exports and their dependencies
- Insert expansions before the first non-import statement, preserving normal import-leading module shape
- If the same export is imported multiple times in a block, inline it once
- If an unknown synthetic module or symbol is referenced, fail with a clear execution error naming the missing module/symbol
- If expansion would create duplicate top-level names conflicting with user-defined names already in the same submitted block, fail with a clear error rather than silently overwrite
- The expansion pass should return:
  - expanded source text
  - metadata describing which synthetic modules/symbols were expanded

Default assumption:

- Inlined exports must be valid standalone Python with their own dependencies already represented in the expansion order.
- Exported source may assume normal REPL globals like `llm_query`, `llm_query_batched`, `LLMResult`, and any safe builtins already present in `LocalREPL`.

### 3. Preserve current AST rewriter behavior unchanged

Do not redesign the current async rewrite model in v1.

- Keep `has_llm_calls()` and `rewrite_for_async()` semantics the same
- Rely on the new expansion pass to make imported `llm_query(...)` calls visible to the existing rewriter
- Ensure function promotion and await wrapping continue to work on expanded source exactly as they do today for handwritten REPL code

This means imported skill wrappers must expand to ordinary top-level Python
definitions and calls, not runtime wrappers or import hooks.

### 4. Introduce a first source-expandable ping skill module

Add a new synthetic skill module for a wrapped recursive ping workflow that
mimics the provider-fake fixture in
`tests_rlm_adk/fixtures/provider_fake/fake_recursive_ping.json`, but is
implemented as ordinary Python source with explicit debug print statements.

Target module:

- `rlm_repl_skills.ping`

Minimum exported symbols for v1:

- `run_recursive_ping`
- `RecursivePingResult`
- `build_recursive_ping_prompt`
- `PING_TERMINAL_PAYLOAD`
- `PING_REASONING_LAYER_1`
- `PING_REASONING_LAYER_2`

The expanded `run_recursive_ping(...)` implementation should be REPL-safe and
AST-rewriter-friendly.

Expected signature:

- `max_layer`
- `starting_layer`
- `terminal_layer`
- `emit_debug`
- `terminal_payload`
- `layer1_reasoning_summary`
- `layer2_reasoning_summary`

Behavior:

- emit debug-oriented `print(...)` statements before and after each recursive step
- build the same three-layer recursive ping contract as the provider-fake fixture: root layer 0, worker layer 1, and terminal worker layer 2
- call `llm_query(...)` directly in expanded source
- keep the terminal layer payload aligned with the provider-fake fixture:
  `{"my_response": "pong", "your_response": "ping"}`
- keep the wrapper aligned with the provider-fake execution split where child layers finalize via `set_model_response` outside REPL execution because `set_model_response` is not a REPL global
- parse the recursive child response in Python and return a stable REPL-level result object
- stay wrapper-oriented: the point of the first module is proving source expansion plus rewrite visibility, not introducing a broader orchestration framework

Default assumption:

- The first implementation mirrors the provider-fake workflow closely rather than generalizing into a topology engine.
- `llm_query_batched(...)` is out of scope for the first ping module.
- The wrapper is intentionally verbose in its debug output so expansion and recursion are easy to inspect in traces.

### 5. Keep existing `repl.globals` helpers for non-expanding skills

Do not replace the current injected helper model.

Continue using `repl.globals` injection for helpers like:

- `probe_repo`
- `pack_repo`
- `shard_repo`

Rule for skill delivery:

- If a helper is pure Python utility and does not need AST rewriting, keep it as a normal injected global
- If a helper contains or is expected to contain `llm_query(...)` / `llm_query_batched(...)`, expose it through the synthetic import expansion system

This split should be explicit in the code and docs.

### 6. Add observability for original vs expanded REPL code

Observability must make expansion debuggable.

Persist both:

- original submitted code
- expanded code actually executed

Add state/artifact support for:

- expanded code preview
- expanded code hash
- expanded synthetic imports metadata
- whether skill expansion occurred

Default assumption:

- Existing observability keys for submitted code remain unchanged
- New keys are additive, not replacements

### 7. Update skill documentation and authoring guidance

Extend the skill system docs to describe the new authoring path for expandable
skills.

Document:

- how to define a synthetic REPL skill module
- how to register exports
- when to choose expansion versus `repl.globals`
- constraints on exported source
- prohibition on relying on runtime imports for `llm_query`-containing helpers

Also update future source-expandable skill guidance so it aligns with the synthetic
import model:

- imported abstraction for the model
- expanded source for the runtime

## Interfaces / Types

Add these internal interfaces.

### `ReplSkillExport`

A registry entry describing one expandable symbol.

Required fields:

- `module: str`
- `name: str`
- `source: str`
- `requires: list[str]`
- `kind: str`

### `ExpandedSkillCode`

Return value from the expansion pass.

Required fields:

- `original_code: str`
- `expanded_code: str`
- `expanded_symbols: list[str]`
- `expanded_modules: list[str]`
- `did_expand: bool`

### Synthetic module contract

The only supported import contract in v1 is:

```python
from rlm_repl_skills.<module> import <symbol>[, <symbol>...]
```

## Test Plan

Add non-mutating planning assumptions as implementation targets.

### Unit tests

- import expansion resolves known module/symbol pairs
- dependency ordering is stable and deterministic
- duplicate imports do not duplicate emitted source
- unknown modules/symbols fail clearly
- conflicting emitted names fail clearly
- code without synthetic imports is unchanged
- expanded code preserves non-skill imports and user code ordering

### AST rewrite integration tests

- imported expanded function containing `llm_query(...)` triggers `has_llm_calls()`
- expanded function is promoted to async correctly
- nested helper calls inside expanded source are awaited correctly
- batched child calls in expanded source rewrite correctly

### End-to-end provider-fake tests

- a REPL block using `from rlm_repl_skills.ping import run_recursive_ping, RecursivePingResult` executes successfully
- the expanded `run_recursive_ping(...)` performs the recursive ping workflow from `tests_rlm_adk/fixtures/provider_fake/fake_recursive_ping.json`
- the expanded ping wrapper emits the expected debug prints for layer 0, layer 1, and layer 2
- the child/finalization flow remains compatible with the provider-fake split where `set_model_response` happens after `execute_code`
- final REPL locals contain the expected ping result object and terminal payload
- observability shows both original and expanded code
- existing repomix global helpers still work unchanged in the same invocation

### Regression tests

- current direct handwritten `llm_query(...)` REPL code still works unchanged
- current `repl.globals` skills like repomix helpers still work unchanged
- submitted code with no `llm_query(...)` still takes the sync path unless expansion introduces one

## Assumptions And Defaults

- v1 supports only `from rlm_repl_skills.<module> import ...`
- v1 does not support wildcard imports, aliasing, or generic runtime import-hook behavior
- expanded source is the only supported way to make imported `llm_query(...)` visible to the existing AST rewriter
- the current AST rewriter remains unchanged except for consuming expanded code
- `repl.globals` remains the delivery path for simple non-`llm_query` helpers
- the first expandable skill module is `rlm_repl_skills.ping`
- the first expandable wrapper intentionally tracks the provider-fake recursive ping fixture and adds debug-print-heavy behavior instead of introducing Polya envelopes or templates
- any source expansion name collision is a hard error, not an implicit overwrite
