# Skills

Skills are domain-specific helper functions available to the reasoning
agent inside the REPL.  There are **two distinct injection mechanisms**
and each determines whether usage examples should show an import.

## Two injection mechanisms

### Kind 1: Globals-injected (no import needed)

Functions injected directly into `repl.globals` by the orchestrator at
startup.  The model calls them by bare name — no import statement.

**Examples:** `probe_repo()`, `pack_repo()`, `shard_repo()`, `llm_query()`,
`llm_query_batched()`, `LLMResult`, `FINAL_VAR`, `SHOW_VARS`.

Usage example in instructions:
```repl
info = probe_repo("https://github.com/org/repo")
print(info.total_tokens)
```

### Kind 2: Source-expandable (synthetic import required)

Functions registered as `ReplSkillExport` objects in the `SkillRegistry`
singleton at import time.  They are **not** pre-loaded into REPL globals.
Instead, the model writes a synthetic import:

```repl
from rlm_repl_skills.polya_narrative import run_polya_narrative
result = run_polya_narrative(story, max_cycles=2)
```

The `REPLTool` intercepts the `from rlm_repl_skills.*` import before
execution, resolves it via the registry, topologically sorts all
transitive `requires` dependencies, and **replaces the import statement
with the inlined source code** of the function and its dependencies.
The synthetic import is removed from the output — it is a trigger, not
a real Python import.

This mechanism avoids injecting large function bodies into every REPL
call.  The source only expands when the model explicitly imports it.

**Examples:** `run_polya_narrative()`, `run_polya_understand()`,
`run_recursive_ping()`.

### Both mechanisms share prompt instructions

Both kinds use ADK `Skill` objects whose `.instructions` markdown is
appended to the reasoning agent's `static_instruction` via
`build_*_instruction_block()` (wired through `catalog.py`).  The model
sees these instructions in its system prompt.

### Import rule for usage examples

| Injection kind | Example shows import? | Why |
|---|---|---|
| Globals-injected | **No** — bare name call | Already in `repl.globals` |
| Source-expandable | **Yes** — `from rlm_repl_skills.<mod> import <fn>` | Import triggers source expansion |

## Directory layout

```
rlm_adk/skills/
  __init__.py              # Re-exports helpers + skill objects
  catalog.py               # PROMPT_SKILL_REGISTRY, build_enabled_skill_instruction_blocks()
  repomix_helpers.py       # probe_repo, pack_repo, shard_repo implementations
  repomix_skill.py         # Skill definition (globals-injected)
  polya_narrative_skill.py # Skill definition + source-expandable exports
  polya_understand.py      # Skill definition + source-expandable exports
  repl_skills/
    __init__.py
    ping.py                # Source-expandable exports only (no Skill object)
  README.md                # This file
```

## How a skill reaches the REPL

### Prompt injection (both kinds)

```
catalog.py
  PROMPT_SKILL_REGISTRY = {name: PromptSkillRegistration(...)}
  build_enabled_skill_instruction_blocks(enabled_skills)
    -> list of XML discovery + instruction strings

agent.py
  create_reasoning_agent(enabled_skills=...)
    for block in build_enabled_skill_instruction_blocks(enabled_skills):
        static_instruction += block
    -> appended to LlmAgent(static_instruction=...)
```

### Globals injection (Kind 1)

```
orchestrator.py
  _run_async_impl()
    repl = LocalREPL(depth=1)
    llm_query_async, llm_query_batched_async, flush_fn = create_dispatch_closures(...)
    repl.set_async_llm_query_fns(...)              # dispatch closures
    repl.globals.update(collect_repl_globals(self.enabled_skills))  # catalog-driven
    repl.globals["LLMResult"]   = LLMResult
```

### Source expansion (Kind 2)

```
orchestrator.py
  _run_async_impl()
    activate_side_effect_modules(self.enabled_skills)  # catalog-driven

repl/skill_registry.py
  _registry = SkillRegistry()                      # process-global singleton
  register_skill_export(ReplSkillExport(...))       # called at import time

tools/repl_tool.py  (per execute_code call)
  expansion = expand_skill_imports(code)            # intercept before execution
    -> ast.parse(code)
    -> find ImportFrom nodes matching "rlm_repl_skills.*"
    -> resolve via _registry.resolve(module, names)
    -> walk requires graph transitively
    -> topological sort (dependencies first)
    -> replace import with inlined source blocks
  exec_code = expansion.expanded_code
```

### AST rewriting (both kinds)

When the model emits a ```` ```repl ```` block the `REPLTool` checks
whether it contains `llm_query` / `llm_query_batched` calls. If so the
AST rewriter (`repl/ast_rewriter.py`):

1. Transforms `llm_query(...)` to `await llm_query_async(...)`.
2. Promotes any user-defined `def` that now contains `await` into
   `async def` and wraps its call sites with `await` (transitive).
3. Wraps the entire body in `async def _repl_exec(): ... return locals()`.

The rewritten code runs via `execute_code_async`. Blocks without LM
calls take the sync path through `execute_code`.

Source expansion happens **before** AST rewriting, so `llm_query()`
calls inside expanded skill source are correctly rewritten to async.

REPL locals persist across iterations within a single invocation, so a
variable assigned in iteration 1 is available in iteration 2.

## Writing skill instructions

`REPOMIX_SKILL.instructions` is a markdown string containing usage docs
and code examples. The examples serve two purposes:

- They teach the model how to use the helpers.
- They are parsed and validated by the test suite.

### Requirements for ```` ```repl ```` examples

1. **Fence with ```` ```repl ````**, not ```` ```python ````.
   The extraction regex is:
   ```
   re.findall(r"```repl\n(.*?)```", text, re.DOTALL)
   ```
   Blocks fenced any other way will not be found.

2. **Each block must be valid Python** (`ast.parse` must succeed).
   The coverage test `test_fixture_repl_blocks_are_valid_python` parses
   every extracted block. Syntax errors fail the build.

3. **Call helpers by their bare name** (`probe_repo(...)`, not
   `repomix_helpers.probe_repo(...)`). The test
   `test_skill_instructions_cover_all_helpers` does AST-based function
   call extraction and checks that all registered helpers appear:

   ```python
   for node in ast.walk(tree):
       if isinstance(node, ast.Call):
           if isinstance(node.func, ast.Name):
               names.add(node.func.id)
           elif isinstance(node.func, ast.Attribute):
               names.add(node.func.attr)
   ```

   Both bare calls (`probe_repo()`) and dotted calls (`obj.method()`)
   are extracted. The canonical check is against the bare name.

4. **Every helper must appear in at least one example.** Currently the
   three required names are `probe_repo`, `pack_repo`, `shard_repo`.

5. **There must be at least 3 ```` ```repl ```` blocks** in the
   instructions (one per helper at minimum).

### Summary of enforced constraints

| Check | Test |
|-------|------|
| >= 3 repl blocks in instructions | `test_skill_instructions_have_repl_examples` |
| All helpers called in instruction examples | `test_skill_instructions_cover_all_helpers` |
| All helpers called in fixture REPL code | `test_fixture_covers_all_helpers` |
| All fixture REPL blocks parse as Python | `test_fixture_repl_blocks_are_valid_python` |

## Writing a provider-fake fixture for a skill

Fixtures live in `tests_rlm_adk/fixtures/provider_fake/` and are JSON
files consumed by `ScenarioRouter`. A skill fixture scripts the exact
model responses across iterations.

### Structure

```json
{
  "scenario_id": "skill_helper",
  "config": { "model": "gemini-fake", "thinking_budget": 0, "max_iterations": 5, "retry_delay": 0.0 },
  "responses": [
    { "call_index": 0, "caller": "reasoning", "body": { ... } },
    { "call_index": 1, "caller": "reasoning", "body": { ... } },
    { "call_index": 2, "caller": "worker",    "body": { ... } },
    ...
  ],
  "expected": {
    "final_answer": "...",
    "total_iterations": 3,
    "total_model_calls": 5
  }
}
```

### REPL code in fixture JSON

Reasoning responses contain ```` ```repl ```` blocks inside the `text`
field. JSON escaping rules:

| In Python code | JSON string |
|----------------|-------------|
| newline between statements | `\n` (literal escape) |
| `\n` inside a Python string like `"x = 1\n"` | `\\n` |
| double quote `"` | `\"` |

### Call ordering

Responses are consumed sequentially. Workers dispatched by
`llm_query_batched` in iteration N consume the next `call_index` slots
after that iteration's reasoning response. Example for the
`skill_helper` fixture:

| call_index | caller | What happens |
|-----------|--------|--------------|
| 0 | reasoning | Iter 1: `probe_repo` + `pack_repo` (no workers) |
| 1 | reasoning | Iter 2: `shard_repo` + `llm_query_batched(2 prompts)` |
| 2 | worker | Worker response for prompt 1 |
| 3 | worker | Worker response for prompt 2 |
| 4 | reasoning | Iter 3: emits `FINAL(...)` |

### Per-iteration REPL introspection

The orchestrator emits a `LAST_REPL_RESULT` state delta per iteration
(`orchestrator.py:391-399`):

```python
{
    "code_blocks": int,        # count of blocks executed
    "has_output": bool,        # any stdout produced
    "has_errors": bool,        # any stderr/exceptions
    "total_llm_calls": int,    # worker dispatch count
}
```

Tests extract these snapshots from the event stream and assert per-
iteration correctness. If a skill helper raises or an assert fails
inside the REPL, `has_errors` becomes `True` and the test fails on
the actual execution result.

### Registering a fixture for TEST 8

Add the fixture name (stem, no `.json`) to `_LLM_QUERY_FIXTURE_NAMES`
in `test_provider_fake_e2e.py` to get automatic validation of:

1. Total model calls match
2. Worker events present in stream
3. At least one iteration had code blocks
4. At least one iteration recorded `llm_query` dispatches
5. At least one iteration produced clean output (stdout without errors),
   or alternatively confirmed worker calls as proof of pipeline health
6. Final answer matches expected (only checked if `expected.final_answer`
   is present in the fixture)

## Adding a new skill

Choose the injection mechanism based on function size and frequency:

- **Globals-injected** — best for small, frequently-used helpers that
  should always be available (like `probe_repo`).
- **Source-expandable** — best for large functions with many dependencies
  that are only needed occasionally (like `run_polya_narrative`).

### Path A: Globals-injected skill

1. **Create the helper module** in `rlm_adk/skills/` (e.g.
   `my_skill_helpers.py`) with the functions to inject.

2. **Create the skill definition** (e.g. `my_skill.py`) using
   `google.adk.skills.models.Skill` and `Frontmatter`. Write a
   `build_*_instruction_block()` function.

3. **Register a `repl_globals_factory`** in `catalog.py` that lazily
   imports and returns the helper functions as a dict.

4. **Register in `catalog.py`** — add to `PROMPT_SKILL_REGISTRY`.

5. **Export from `__init__.py`** so tests can import cleanly.

6. **Usage examples must NOT show imports** — the functions are globals.

### Path B: Source-expandable skill

1. **Create the skill file** (e.g. `my_skill.py`) with both:
   - An ADK `Skill` object + `build_*_instruction_block()` for prompt
     instructions.
   - `ReplSkillExport` registrations via `register_skill_export()` at
     module level (side-effect at import time). Store function source
     as string constants. Use `requires=[...]` for dependency ordering.

2. **Import the module** in `orchestrator.py` for the side-effect
   registration (the import seeds the `SkillRegistry` singleton).

3. **Register in `catalog.py`** — add to `PROMPT_SKILL_REGISTRY`.

4. **Usage examples MUST show the synthetic import**:
   ```repl
   from rlm_repl_skills.my_module import my_function
   result = my_function(args)
   ```
   This import is the trigger for source expansion — without it the
   function does not exist in the REPL namespace.

### Common steps (both paths)

5. **Write coverage tests** following the pattern in
   `test_skill_helper_e2e.py::TestSkillInstructionCoverage`:
   - Instructions have `>= N` repl blocks
   - All helpers appear in examples
   - All blocks parse as valid Python

6. **Write a provider-fake fixture** and an e2e test that validates
   per-iteration REPL snapshots.

7. **Register** the fixture in `_LLM_QUERY_FIXTURE_NAMES`.
