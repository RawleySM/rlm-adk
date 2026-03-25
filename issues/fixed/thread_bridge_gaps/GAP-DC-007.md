# GAP-DC-007: Stale documentation references to deleted AST rewriter and skill registry
**Severity**: MEDIUM
**Category**: dead-code
**Files**: `rlm_adk_docs/UNDERSTAND.md`, `rlm_adk_docs/core_loop.md`, `rlm_adk_docs/observability.md`, `rlm_adk_docs/dispatch_and_state.md`

## Problem

The core documentation files, including the primary orientation guide `UNDERSTAND.md`, still reference deleted modules and concepts as if they are active:

1. **UNDERSTAND.md:48** still shows `llm_query() -> AST-rewritten to async` in the architecture diagram
2. **UNDERSTAND.md:154** lists `rlm_adk/repl/ast_rewriter.py` in the key source files table
3. **UNDERSTAND.md:160** lists `rlm_adk/repl/skill_registry.py` in the key source files table
4. **core_loop.md** (lines 110-142, 218-241) documents the AST rewriter flow as current architecture
5. **observability.md** (lines 384-400) documents `REPL_EXPANDED_CODE`, `REPL_EXPANDED_CODE_HASH`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND` as active state keys
6. **dispatch_and_state.md** (lines 243-246) lists the 4 expansion keys in the state key table

## Evidence

The `UNDERSTAND.md` key files table currently says:
```
| `rlm_adk/repl/ast_rewriter.py` | Sync-to-async llm_query transform |
| `rlm_adk/repl/skill_registry.py` | Synthetic REPL skill import expansion |
```

Both files are confirmed DELETED. The table also does not list the new key files:
- `rlm_adk/repl/thread_bridge.py`
- `rlm_adk/skills/loader.py`

## Suggested Fix

Update all four documentation files to reflect the thread bridge architecture:
1. Replace AST rewriter references in UNDERSTAND.md with thread bridge flow
2. Update key source files table (remove deleted, add new)
3. Remove expansion state key documentation from observability.md and dispatch_and_state.md
4. Update core_loop.md to reflect `execute_code_threaded` path instead of `has_llm_calls`/`rewrite_for_async`/`execute_code_async`
