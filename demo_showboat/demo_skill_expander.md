# Skill Expander: Source-Expandable REPL Imports

*2026-03-10 by Showboat*

## Summary

The Skill Expander enables the reasoning LLM to import pre-authored "skill" functions via synthetic `from rlm_repl_skills.<mod> import <sym>` statements that expand into inline source before execution. This allows complex multi-step behaviors (like recursive ping) to be packaged as importable skills while remaining compatible with the AST rewriter's `has_llm_calls()` detection and `rewrite_for_async()` promotion pipeline.

The submitted code never leaves the REPL -- synthetic imports are replaced with topologically sorted inline source blocks, so `llm_query()` calls inside skill functions are visible to the AST rewriter and correctly promoted to async.

## Architecture

```
submitted code
    |
    v
expand_skill_imports()          # SkillRegistry resolves synthetic imports
    |                           # into inline source (topo-sorted, deduped)
    v
has_llm_calls()                 # AST scan now sees llm_query() inside
    |                           # expanded function bodies
    v
rewrite_for_async()             # Promotes expanded functions to async,
    |                           # rewrites llm_query -> await llm_query_async
    v
execute in LocalREPL
```

The expansion step runs inside `REPLTool.run_async()` (line 159 of `repl_tool.py`) immediately after recording the submitted code for observability. If expansion occurs, four additional state keys are written before execution begins.

## Key Components

### SkillRegistry and ReplSkillExport (`rlm_adk/repl/skill_registry.py`)

- **`ReplSkillExport`** -- dataclass holding module name, symbol name, inline source, dependency list (`requires`), and kind (const/class/function).
- **`SkillRegistry`** -- manages a `dict[module -> dict[name -> export]]`. Core methods:
  - `register(export)` -- adds an export at import time
  - `resolve(module, names)` -- looks up exports, raises `RuntimeError` for unknown module/symbol
  - `expand(code)` -- parses AST, finds `from rlm_repl_skills.*` imports, resolves + topo-sorts deps, checks name conflicts, assembles expanded code
  - `_topo_sort(exports)` -- DFS topological sort by `requires` edges
  - `_collect_user_defined_names(tree)` -- detects name conflicts between skill exports and user code
- **Module-level singleton** `_registry` with convenience functions `register_skill_export()` and `expand_skill_imports()`.

### expand_skill_imports() -- the expansion function

Returns an `ExpandedSkillCode` dataclass with:
- `original_code` / `expanded_code` -- before/after
- `expanded_symbols` -- list of inlined symbol names
- `expanded_modules` -- list of synthetic module names referenced
- `did_expand` -- boolean flag for observability branching

### Ping skill module (`rlm_adk/skills/repl_skills/ping.py`)

First expandable skill. Registers 6 exports at import time:
- `PING_TERMINAL_PAYLOAD`, `PING_REASONING_LAYER_1`, `PING_REASONING_LAYER_2` (constants)
- `RecursivePingResult` (class)
- `build_recursive_ping_prompt` (function, depends on 3 constants)
- `run_recursive_ping` (function, depends on all 5 others, contains `llm_query()` call)

### REPLTool integration (`rlm_adk/tools/repl_tool.py:158-169`)

```python
# Expand synthetic skill imports before AST analysis
expansion = expand_skill_imports(code)
exec_code = expansion.expanded_code
if expansion.did_expand:
    exec_code_hash = hashlib.sha256(exec_code.encode()).hexdigest()
    tool_context.state[depth_key(REPL_EXPANDED_CODE, self._depth)] = exec_code
    tool_context.state[depth_key(REPL_EXPANDED_CODE_HASH, self._depth)] = exec_code_hash
    tool_context.state[depth_key(REPL_SKILL_EXPANSION_META, self._depth)] = {
        "symbols": expansion.expanded_symbols,
        "modules": expansion.expanded_modules,
    }
    tool_context.state[depth_key(REPL_DID_EXPAND, self._depth)] = True
```

### Observability state keys (`rlm_adk/state.py:101-105`)

```python
REPL_EXPANDED_CODE = "repl_expanded_code"
REPL_EXPANDED_CODE_HASH = "repl_expanded_code_hash"
REPL_SKILL_EXPANSION_META = "repl_skill_expansion_meta"
REPL_DID_EXPAND = "repl_did_expand"
```

All four are included in `DEPTH_SCOPED_KEYS` for nested reasoning agent isolation.

## Test Evidence

### Unit tests: 13 passed

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_skill_expander.py -v -m "" 2>&1
```

```output
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /home/rawley-stanhope/dev/rlm-adk/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/rawley-stanhope/dev/rlm-adk
configfile: pyproject.toml
plugins: asyncio-1.3.0, anyio-4.12.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 13 items

tests_rlm_adk/test_skill_expander.py::TestExpandKnownSymbol::test_expand_known_symbol PASSED [  7%]
tests_rlm_adk/test_skill_expander.py::TestExpandWithDependencies::test_expand_with_dependencies PASSED [ 15%]
tests_rlm_adk/test_skill_expander.py::TestExpandWithDependencies::test_transitive_dependencies PASSED [ 23%]
tests_rlm_adk/test_skill_expander.py::TestExpandDuplicateImport::test_expand_duplicate_import PASSED [ 30%]
tests_rlm_adk/test_skill_expander.py::TestExpandUnknownModuleFails::test_expand_unknown_module_fails PASSED [ 38%]
tests_rlm_adk/test_skill_expander.py::TestExpandUnknownSymbolFails::test_expand_unknown_symbol_fails PASSED [ 46%]
tests_rlm_adk/test_skill_expander.py::TestExpandNameConflictFails::test_expand_name_conflict_fails PASSED [ 53%]
tests_rlm_adk/test_skill_expander.py::TestNoSyntheticImportsUnchanged::test_no_synthetic_imports_unchanged PASSED [ 61%]
tests_rlm_adk/test_skill_expander.py::TestPreservesNormalImports::test_preserves_normal_imports PASSED [ 69%]
tests_rlm_adk/test_skill_expander.py::TestExpansionMetadata::test_expansion_metadata PASSED [ 76%]
tests_rlm_adk/test_skill_expander.py::TestExpandEmptyCode::test_expand_empty_code PASSED [ 84%]
tests_rlm_adk/test_skill_expander.py::TestExpandEmptyCode::test_expand_syntax_error_code PASSED [ 92%]
tests_rlm_adk/test_skill_expander.py::TestRegisterSkillExport::test_module_level_register PASSED [100%]

======================== 13 passed, 1 warning in 0.05s =========================
```

### AST integration tests: 5 passed

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_skill_expander_ast.py -v -m "" 2>&1
```

```output
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /home/rawley-stanhope/dev/rlm-adk/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/rawley-stanhope/dev/rlm-adk
configfile: pyproject.toml
plugins: asyncio-1.3.0, anyio-4.12.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 5 items

tests_rlm_adk/test_skill_expander_ast.py::TestExpandedLlmQueryTriggersHasLlmCalls::test_expanded_llm_query_detected PASSED [ 20%]
tests_rlm_adk/test_skill_expander_ast.py::TestExpandedLlmQueryTriggersHasLlmCalls::test_unexpanded_code_no_llm_calls PASSED [ 40%]
tests_rlm_adk/test_skill_expander_ast.py::TestExpandedFunctionPromotedToAsync::test_run_recursive_ping_promoted PASSED [ 60%]
tests_rlm_adk/test_skill_expander_ast.py::TestExpandedNestedCallsAwaited::test_nested_calls_awaited PASSED [ 80%]
tests_rlm_adk/test_skill_expander_ast.py::TestExpandedNestedCallsAwaited::test_expanded_code_compiles PASSED [100%]

========================= 5 passed, 1 warning in 0.06s =========================
```

### Regression: existing contract tests still pass

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -v 2>&1 | tail -5
```

```output
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=============== 28 passed, 22 deselected, 138 warnings in 22.76s ===============
```

## Code Walkthrough

### 1. Synthetic import expands into inline source

When the LLM submits code containing `from rlm_repl_skills.ping import run_recursive_ping`, the registry's `expand()` method (`skill_registry.py:58-169`):

1. Parses the code AST and finds `ImportFrom` nodes where `module.startswith("rlm_repl_skills.")`
2. Calls `resolve()` to look up each symbol in the registry
3. Walks `requires` transitively to collect all dependencies
4. Topologically sorts so dependencies appear before dependents
5. Strips the synthetic import node, preserves normal imports, and inserts inline source blocks annotated with `# --- skill: <module>.<name> ---` headers

The test `TestExpandWithDependencies::test_expand_with_dependencies` verifies topo ordering:

```python
# DEMO_CONST must appear before demo_helper (topo order)
const_pos = result.expanded_code.index('DEMO_CONST = "hello"')
helper_pos = result.expanded_code.index("def demo_helper")
assert const_pos < helper_pos
```

### 2. Expanded llm_query() detected by has_llm_calls()

Before expansion, the submitted code is just `from rlm_repl_skills.ping import run_recursive_ping` -- no visible `llm_query()` call. After expansion, `run_recursive_ping`'s source is inlined and contains `child_response = llm_query(prompt)` (ping.py line 123).

The test `TestExpandedLlmQueryTriggersHasLlmCalls::test_expanded_llm_query_detected` verifies:

```python
expansion = expand_skill_imports(code)
assert expansion.did_expand is True
assert has_llm_calls(expansion.expanded_code) is True
```

### 3. Expanded function promoted to async by rewrite_for_async()

The AST rewriter sees `llm_query(prompt)` inside the expanded `run_recursive_ping` function body and promotes it to `async def`, rewriting the call to `await llm_query_async(prompt)`.

The test `TestExpandedFunctionPromotedToAsync::test_run_recursive_ping_promoted` verifies:

```python
tree = rewrite_for_async(expansion.expanded_code)
source = ast.unparse(tree)
assert "async def run_recursive_ping" in source
assert "await run_recursive_ping" in source
```

### 4. Observability state keys track expansion

In `REPLTool.run_async()` (repl_tool.py:161-169), when `expansion.did_expand` is true, four depth-scoped state keys are written:

| State Key | Value |
|---|---|
| `repl_expanded_code` | Full expanded source string |
| `repl_expanded_code_hash` | SHA-256 hex digest of expanded code |
| `repl_skill_expansion_meta` | `{"symbols": [...], "modules": [...]}` |
| `repl_did_expand` | `True` |

These are depth-scoped via `depth_key()` so nested reasoning agents at different depths maintain independent expansion state.

## Feature Verification Checklist

- [x] Registry registers exports at import time -- ping.py registers 6 exports via `register_skill_export()` at module load
- [x] Known symbols expand correctly -- `TestExpandKnownSymbol` PASSED
- [x] Dependencies are topologically sorted -- `TestExpandWithDependencies::test_expand_with_dependencies` PASSED (asserts const_pos < helper_pos)
- [x] Duplicate imports are deduplicated -- `TestExpandDuplicateImport` PASSED (count == 1)
- [x] Unknown modules fail with clear errors -- `TestExpandUnknownModuleFails` PASSED (RuntimeError: "Unknown synthetic module")
- [x] Unknown symbols fail with clear errors -- `TestExpandUnknownSymbolFails` PASSED (RuntimeError: "Unknown symbol")
- [x] Name conflicts fail with clear errors -- `TestExpandNameConflictFails` PASSED (RuntimeError: "Name conflict")
- [x] Code without synthetic imports passes through unchanged -- `TestNoSyntheticImportsUnchanged` PASSED (did_expand=False, code unchanged)
- [x] Normal imports are preserved -- `TestPreservesNormalImports` PASSED ("import json" present in expanded code)
- [x] Expanded llm_query() detected by has_llm_calls() -- `TestExpandedLlmQueryTriggersHasLlmCalls::test_expanded_llm_query_detected` PASSED
- [x] Expanded functions promoted to async -- `TestExpandedFunctionPromotedToAsync::test_run_recursive_ping_promoted` PASSED ("async def run_recursive_ping" in output)
- [x] Existing contract tests pass (no regressions) -- 28 passed in test_provider_fake_e2e.py
- [x] New observability state keys populated on expansion -- `REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND` written in REPLTool when did_expand=True
