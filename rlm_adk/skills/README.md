# Skills

Skills are domain-specific helper functions pre-loaded into the REPL
so the reasoning agent can call them with zero imports. Each skill has
two integration surfaces:

1. **Runtime globals** -- the actual Python functions injected into
   `repl.globals` by the orchestrator (`orchestrator.py:129-134`).
2. **Prompt instructions** -- an ADK `Skill` object whose `.instructions`
   markdown is appended to the reasoning agent's `static_instruction`
   via `build_skill_instruction_block()` (`agent.py`).

The model sees the instructions in its system prompt and the functions
are available when ```` ```repl ```` blocks execute.

## Directory layout

```
rlm_adk/skills/
  __init__.py              # Re-exports helpers + REPOMIX_SKILL
  repomix_helpers.py       # probe_repo, pack_repo, shard_repo implementations
  repomix_skill.py         # Skill definition + build_skill_instruction_block()
  README.md                # This file
```

## How a skill reaches the REPL

```
agent.py
  create_reasoning_agent()
    build_skill_instruction_block()
      format_skills_as_xml([REPOMIX_SKILL.frontmatter])   # XML discovery tag
      + REPOMIX_SKILL.instructions                         # full markdown docs
    -> appended to static_instruction for LlmAgent

orchestrator.py
  _run_async_impl()
    repl = LocalREPL(depth=1)
    llm_query_async, llm_query_batched_async = create_dispatch_closures(...)
    repl.set_async_llm_query_fns(...)              # dispatch closures first
    repl.globals["probe_repo"]  = probe_repo       # then skill helpers
    repl.globals["pack_repo"]   = pack_repo
    repl.globals["shard_repo"]  = shard_repo
```

When the model emits a ```` ```repl ```` block the orchestrator checks
whether it contains `llm_query` / `llm_query_batched` calls. If so the
AST rewriter (`repl/ast_rewriter.py`):

1. Transforms `llm_query(...)` to `await llm_query_async(...)`.
2. Promotes any user-defined `def` that now contains `await` into
   `async def` and wraps its call sites with `await` (transitive).
3. Wraps the entire body in `async def _repl_exec(): ... return locals()`.

The rewritten code runs via `execute_code_async`. Blocks without LM
calls take the sync path through `execute_code`.

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

1. **Create the helper module** in `rlm_adk/skills/` (e.g.
   `my_skill_helpers.py`) with the functions to inject.

2. **Create the skill definition** (e.g. `my_skill.py`) using
   `google.adk.skills.models.Skill` and `Frontmatter`. Write a
   `build_*_instruction_block()` function that returns the XML
   discovery block + instructions string.

3. **Inject helpers into REPL globals** in `orchestrator.py` alongside
   the existing repomix helpers.

4. **Append instructions to the system prompt** by calling your build
   function in `agent.py:create_reasoning_agent()`.

5. **Export from `__init__.py`** so tests can import cleanly.

6. **Write coverage tests** following the pattern in
   `test_skill_helper_e2e.py::TestSkillInstructionCoverage`:
   - Instructions have `>= N` repl blocks
   - All helpers appear in examples
   - All blocks parse as valid Python

7. **Write a provider-fake fixture** and an e2e test that validates
   per-iteration REPL snapshots.

8. **Register** the fixture in `_LLM_QUERY_FIXTURE_NAMES`.
