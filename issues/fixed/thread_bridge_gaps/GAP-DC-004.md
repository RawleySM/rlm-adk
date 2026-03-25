# GAP-DC-004: Obsolete skills directory imports from deleted module
**Severity**: LOW
**Category**: dead-code
**Files**: `rlm_adk/skills/obsolete/*.py` (8 files)

## Problem

All 8 Python files in `rlm_adk/skills/obsolete/` import from `rlm_adk.repl.skill_registry`, which was deleted in Phase 0B. If any code ever imports one of these modules (even accidentally), it will crash with `ModuleNotFoundError`.

## Evidence

```
rlm_adk/skills/obsolete/polya_understand_t2_flat.py:26:from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export
rlm_adk/skills/obsolete/polya_understand.py:30:from rlm_adk.repl.skill_registry import ReplSkillExport, register_skill_export
rlm_adk/skills/obsolete/polya_understand_t1_workflow.py:26:from rlm_adk.repl.skill_registry import ...
rlm_adk/skills/obsolete/polya_understand_t3_adaptive.py:30:from rlm_adk.repl.skill_registry import ...
rlm_adk/skills/obsolete/polya_understand_t4_debate.py:30:from rlm_adk.repl.skill_registry import ...
rlm_adk/skills/obsolete/polya_narrative_skill.py:26:from rlm_adk.repl.skill_registry import ...
rlm_adk/skills/obsolete/repl_skills/ping.py:10:from rlm_adk.repl.skill_registry import ...
rlm_adk/skills/obsolete/repl_skills/repomix.py:12:from rlm_adk.repl.skill_registry import ...
```

The file `rlm_adk/repl/skill_registry.py` no longer exists (confirmed DELETED).

The `loader.py` skill discovery skips the `obsolete` directory (`_SKIP_DIRS`), so no runtime path reaches these files. However, they remain as import-time landmines and add confusion to codebase searches.

## Suggested Fix

Delete the entire `rlm_adk/skills/obsolete/` directory. Nothing imports from it, and the `_SKIP_DIRS` set in `loader.py` already excludes it from discovery. The content is historical reference that belongs in git history, not in the working tree.
