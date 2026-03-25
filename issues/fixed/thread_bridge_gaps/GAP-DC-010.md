# GAP-DC-010: Stale agent_findings files reference deleted modules as active
**Severity**: LOW
**Category**: dead-code
**Files**: `rlm_adk/skills/agent_findings.md`, `rlm_adk/skills/agent_findings.json`, `rlm_adk/skills/skill_state.md`

## Problem

Three files in `rlm_adk/skills/` contain analysis/findings from a prior agent session that predates the thread bridge migration. They describe the source-expansion skill registry as "preserved" and "active", referencing `expand_skill_imports()`, `SkillRegistry`, `ReplSkillExport`, and `build_auto_import_lines()` as live code. This is misleading because:

1. `rlm_adk/repl/skill_registry.py` has been deleted
2. The source-expansion mechanism no longer exists
3. `REPLTool.run_async()` no longer calls `expand_skill_imports()`

## Evidence

`rlm_adk/skills/skill_state.md:72`:
```
- **`expand_skill_imports`**: Imported from `rlm_adk.repl.skill_registry` and called
  on every `execute_code` invocation (line 177). This is the **active** source-expansion
  mechanism.
```

`rlm_adk/skills/agent_findings.md:118`:
```
The skill files have been moved to rlm_adk/skills/obsolete/. The skill_registry.py at
rlm_adk/repl/skill_registry.py is PRESERVED (do NOT touch it).
```

`rlm_adk/skills/skill_state.md:205`:
```
1. **`SkillRegistry` singleton + `expand_skill_imports()`** (in `repl/skill_registry.py`):
   Called on every REPL execution.
```

All of these statements describe code that no longer exists.

## Suggested Fix

Delete all three files:
- `rlm_adk/skills/agent_findings.md`
- `rlm_adk/skills/agent_findings.json`
- `rlm_adk/skills/skill_state.md`

These are historical agent analysis artifacts, not documentation. Their content is outdated and actively misleading.
