# GAP-OB-008: Observability docs reference deleted REPL expansion state keys
**Severity**: LOW
**Category**: observability
**Files**: `rlm_adk_docs/observability.md`

## Problem

The observability documentation (`rlm_adk_docs/observability.md`) still documents the following state keys and features that were removed as part of the thread bridge migration:

- Lines 153-154: `repl_expanded_code`, `repl_skill_expansion_meta`, `repl_did_expand` listed as curated state prefixes
- Lines 382-400: Full table documenting `REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND` as active keys with descriptions
- Line 398: Documents "Expanded executed code" vs "Original submitted code" split

None of these constants exist in `state.py`. The skill system now uses direct function injection into REPL globals via `collect_skill_repl_globals()` + `set_llm_query_fns()` rather than source-level expansion. There is no expanded code concept in the thread bridge architecture.

## Evidence

Grep for `REPL_EXPANDED_CODE`, `REPL_DID_EXPAND`, `REPL_SKILL_EXPANSION` in `rlm_adk/*.py` returns zero hits.

`rlm_adk_docs/observability.md` line 384:
```
| `repl_expanded_code` | `REPL_EXPANDED_CODE` | `str` | Full expanded source text (with skill source inlined) |
```

## Suggested Fix

Update `rlm_adk_docs/observability.md`:
1. Remove the REPL expansion keys table (lines 382-400)
2. Remove `repl_expanded_code`, `repl_skill_expansion_meta`, `repl_did_expand` from the curated prefixes list
3. Add documentation for the thread bridge execution model and `execution_mode` field in LAST_REPL_RESULT
