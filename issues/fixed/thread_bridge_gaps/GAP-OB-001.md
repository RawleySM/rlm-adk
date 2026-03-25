# GAP-OB-001: AST rewrite observability keys are defined but never written
**Severity**: MEDIUM
**Category**: observability
**Files**: `rlm_adk/state.py`, `rlm_adk/dashboard/live_loader.py`

## Problem

Four AST rewrite instrumentation state keys are defined in `state.py` (lines 64-68) and monitored by the dashboard (`live_loader.py` lines 62-64), but no code in the codebase writes to them. The AST rewriter that previously populated these keys was deleted as part of the thread bridge migration. The keys are:

- `OBS_REWRITE_COUNT` (`obs:rewrite_count`)
- `OBS_REWRITE_TOTAL_MS` (`obs:rewrite_total_ms`)
- `OBS_REWRITE_FAILURE_COUNT` (`obs:rewrite_failure_count`)
- `OBS_REWRITE_FAILURE_CATEGORIES` (`obs:rewrite_failure_categories`)

These keys are included in `CURATED_STATE_PREFIXES` (via the `obs:` prefix) so `should_capture_state_key()` would capture them if they were written, and they appear in the dashboard's `_KNOWN_OBS_KEYS` list. But since no writer exists, they are perpetually NULL/absent in session state, traces.db session_state_events, and the dashboard display.

## Evidence

Grep for `OBS_REWRITE_COUNT`, `OBS_REWRITE_TOTAL_MS`, `OBS_REWRITE_FAILURE_COUNT`, and `OBS_REWRITE_FAILURE_CATEGORIES` across `rlm_adk/` (excluding `state.py` definitions) returns zero write-site hits. The only files containing these constants are `state.py` (definition) and `dashboard/live_loader.py` (monitoring list).

`state.py` lines 64-68:
```python
# AST Rewrite Instrumentation (written by REPLTool)
OBS_REWRITE_COUNT = "obs:rewrite_count"
OBS_REWRITE_TOTAL_MS = "obs:rewrite_total_ms"
OBS_REWRITE_FAILURE_COUNT = "obs:rewrite_failure_count"
OBS_REWRITE_FAILURE_CATEGORIES = "obs:rewrite_failure_categories"
```

The comment "written by REPLTool" is stale -- REPLTool no longer writes these.

## Suggested Fix

Remove the four dead constants from `state.py` and the corresponding entries from `live_loader.py`'s `_KNOWN_OBS_KEYS`. Update the comment. These keys are vestiges of the deleted AST rewriter and will never be populated in the thread bridge architecture.
