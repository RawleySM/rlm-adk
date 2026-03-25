# GAP-DC-001: Dead AST rewrite observability constants in state.py
**Severity**: HIGH
**Category**: dead-code
**Files**: `rlm_adk/state.py` (lines 64-68)

## Problem

Four state key constants for AST rewrite instrumentation remain defined in `rlm_adk/state.py` but are never written or read by any active code. The AST rewriter was deleted in Phase 0A, and REPLTool no longer has `_rewrite_count`, `_rewrite_total_ms`, or `_rewrite_failure_count` instance attributes. These constants are pure dead code.

## Evidence

```python
# rlm_adk/state.py:64-68
# AST Rewrite Instrumentation (written by REPLTool)
OBS_REWRITE_COUNT = "obs:rewrite_count"
OBS_REWRITE_TOTAL_MS = "obs:rewrite_total_ms"
OBS_REWRITE_FAILURE_COUNT = "obs:rewrite_failure_count"
OBS_REWRITE_FAILURE_CATEGORIES = "obs:rewrite_failure_categories"
```

- No code in `rlm_adk/tools/repl_tool.py` references these constants (confirmed by grep).
- No code in `rlm_adk/callbacks/` or `rlm_adk/plugins/` references these constants.
- The comment "written by REPLTool" is false -- REPLTool no longer contains rewrite logic.

## Suggested Fix

Delete lines 63-68 from `rlm_adk/state.py` (the comment and all four constants).
