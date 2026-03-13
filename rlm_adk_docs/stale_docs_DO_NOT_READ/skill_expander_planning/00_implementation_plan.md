# Skill Expander Implementation Plan

## Overview

Add a pre-AST-rewrite expansion layer for REPL skills so `from rlm_repl_skills.<module> import <symbol>` imports get expanded into inline source before `has_llm_calls()` and `rewrite_for_async()` run.

## Architecture

```
submitted code
    │
    ▼
expand_skill_imports()        ← NEW: Phase 1 (registry + expander)
    │
    ├─ original_code preserved for observability
    ├─ expanded_code with inline source replacing synthetic imports
    │
    ▼
has_llm_calls(expanded_code)  ← existing (unchanged)
    │
    ▼
rewrite_for_async(expanded_code)  ← existing (unchanged)
    │
    ▼
execute expanded code         ← existing (unchanged)
```

## Files to Create

| File | Purpose |
|------|---------|
| `rlm_adk/repl/skill_registry.py` | `ReplSkillExport`, `ExpandedSkillCode`, registry, `expand_skill_imports()` |
| `rlm_adk/skills/repl_skills/ping.py` | First expandable skill module: `run_recursive_ping`, constants |
| `tests_rlm_adk/test_skill_expander.py` | Unit tests for registry + expansion |
| `tests_rlm_adk/test_skill_expander_ast.py` | AST rewrite integration tests |
| `tests_rlm_adk/test_skill_expander_e2e.py` | Provider-fake e2e tests |

## Files to Modify

| File | Line Range | Change |
|------|-----------|--------|
| `rlm_adk/tools/repl_tool.py` | L128-213 (`run_async`) | Insert expansion pass between code receipt and `has_llm_calls()` |
| `rlm_adk/state.py` | New keys | Add `REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND` |
| `rlm_adk_docs/skills_and_prompts.md` | New section | Document expandable skill authoring |
| `rlm_adk_docs/core_loop.md` | REPL pipeline section | Document expansion pass in pipeline |

## Implementation Phases

### Phase 1: Registry + Expander (Red/Green TDD)

**New: `rlm_adk/repl/skill_registry.py`**

```python
@dataclass
class ReplSkillExport:
    module: str        # e.g. "rlm_repl_skills.ping"
    name: str          # e.g. "run_recursive_ping"
    source: str        # full Python source to inline
    requires: list[str]  # ordered dependency names
    kind: str          # "class" | "const" | "function" | "source_block"

@dataclass
class ExpandedSkillCode:
    original_code: str
    expanded_code: str
    expanded_symbols: list[str]
    expanded_modules: list[str]
    did_expand: bool

class SkillRegistry:
    def register(self, export: ReplSkillExport) -> None
    def resolve(self, module: str, names: list[str]) -> list[ReplSkillExport]
    def expand(self, code: str) -> ExpandedSkillCode

# Module-level singleton
_registry = SkillRegistry()

def register_skill_export(export: ReplSkillExport) -> None
def expand_skill_imports(code: str) -> ExpandedSkillCode
```

**Algorithm for `expand()`:**
1. Parse code to AST
2. Find `ImportFrom` nodes where `module` starts with `rlm_repl_skills.`
3. Collect all requested (module, name) pairs
4. Resolve each to `ReplSkillExport` — fail clearly on unknown module/symbol
5. Topologically sort by `requires` dependencies
6. Check for name conflicts with user-defined names in the same block — fail if any
7. Remove synthetic import nodes from AST
8. Insert inline source blocks before first non-import statement
9. Deduplicate (same symbol imported twice → inline once)
10. Return `ExpandedSkillCode` with metadata

### Phase 2: Ping Skill Module

**New: `rlm_adk/skills/repl_skills/ping.py`**

Exports registered at import time:
- `PING_TERMINAL_PAYLOAD` (const)
- `PING_REASONING_LAYER_1` (const)
- `PING_REASONING_LAYER_2` (const)
- `RecursivePingResult` (class)
- `build_recursive_ping_prompt` (function)
- `run_recursive_ping` (function, requires: `RecursivePingResult`, `build_recursive_ping_prompt`, `PING_*` consts)

The `run_recursive_ping()` source calls `llm_query()` directly → visible to AST rewriter after expansion.

### Phase 3: REPLTool Integration

**Modify: `rlm_adk/tools/repl_tool.py:128-213`**

In `run_async()`, after receiving `code` and before `has_llm_calls()`:

```python
from rlm_adk.repl.skill_registry import expand_skill_imports

expansion = expand_skill_imports(code)
exec_code = expansion.expanded_code  # use this for has_llm_calls + execution

# Write expansion observability
if expansion.did_expand:
    tool_context.state[depth_key(REPL_EXPANDED_CODE, self._depth)] = exec_code
    tool_context.state[depth_key(REPL_EXPANDED_CODE_HASH, self._depth)] = hashlib.sha256(exec_code.encode()).hexdigest()
    tool_context.state[depth_key(REPL_SKILL_EXPANSION_META, self._depth)] = {
        "symbols": expansion.expanded_symbols,
        "modules": expansion.expanded_modules,
    }
    tool_context.state[depth_key(REPL_DID_EXPAND, self._depth)] = True
```

Then pass `exec_code` to `has_llm_calls()`, `rewrite_for_async()`, and execution.
Preserve original `code` for observability (already written to state at L135-138).

### Phase 4: Skill Registration Wiring

**Modify: `rlm_adk/orchestrator.py:281-286`**

After injecting repomix helpers, register the ping skill:

```python
# Register expandable skill modules
from rlm_adk.skills.repl_skills import ping  # noqa: F401 — registration side-effect
```

### Phase 5: State Keys + Observability

**Modify: `rlm_adk/state.py`**

Add new keys:
```python
# Skill Expansion Observability Keys
REPL_EXPANDED_CODE = "repl_expanded_code"
REPL_EXPANDED_CODE_HASH = "repl_expanded_code_hash"
REPL_SKILL_EXPANSION_META = "repl_skill_expansion_meta"
REPL_DID_EXPAND = "repl_did_expand"
```

Add to `DEPTH_SCOPED_KEYS`:
```python
REPL_EXPANDED_CODE, REPL_EXPANDED_CODE_HASH, REPL_SKILL_EXPANSION_META, REPL_DID_EXPAND,
```

### Phase 6: Documentation Updates

- `rlm_adk_docs/skills_and_prompts.md` — New section on expandable skills
- `rlm_adk_docs/core_loop.md` — Update REPL pipeline description
- `rlm_adk_docs/observability.md` — New expansion observability keys

## Test Plan (Red/Green Sequence)

### Unit Tests (`test_skill_expander.py`) — Write RED first

1. `test_expand_known_symbol` — import resolves, source inlined
2. `test_expand_with_dependencies` — deps included in topo order
3. `test_expand_duplicate_import` — same symbol imported twice → inlined once
4. `test_expand_unknown_module_fails` — clear error
5. `test_expand_unknown_symbol_fails` — clear error
6. `test_expand_name_conflict_fails` — user defines same name → error
7. `test_no_synthetic_imports_unchanged` — code without synthetic imports passes through
8. `test_preserves_normal_imports` — non-synthetic imports kept
9. `test_expansion_metadata` — ExpandedSkillCode fields populated correctly

### AST Integration Tests (`test_skill_expander_ast.py`) — Write RED first

10. `test_expanded_llm_query_triggers_has_llm_calls` — expanded code detected
11. `test_expanded_function_promoted_to_async` — rewrite_for_async works
12. `test_expanded_nested_calls_awaited` — helper calls properly awaited

### E2E Tests (`test_skill_expander_e2e.py`) — Write RED first

13. `test_ping_skill_expansion_e2e` — full pipeline with provider-fake
14. `test_expansion_observability_state` — state keys populated
15. `test_repomix_globals_still_work` — regression: existing helpers unchanged
16. `test_direct_llm_query_still_works` — regression: handwritten code unchanged

## Key Constraints

- AST rewriter is UNCHANGED — expansion makes `llm_query` visible to it
- `repl.globals` path is UNCHANGED for non-expanding skills
- All expansion errors are hard errors (no silent fallbacks)
- Inlined source assumes REPL globals (`llm_query`, `LLMResult`, builtins) are available
- v1: only `from rlm_repl_skills.<mod> import <sym>` — no wildcard, no alias, no plain import
