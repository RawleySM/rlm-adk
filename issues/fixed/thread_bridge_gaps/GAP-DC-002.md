# GAP-DC-002: Dead AST rewrite keys in dashboard live_loader.py
**Severity**: HIGH
**Category**: dead-code
**Files**: `rlm_adk/dashboard/live_loader.py` (lines 62-64)

## Problem

The dashboard's `_KNOWN_OBS_KEYS` list references three AST rewrite state keys that will never be populated because the AST rewriter was deleted. These entries cause the dashboard to look for data that can never exist.

## Evidence

```python
# rlm_adk/dashboard/live_loader.py:62-64
    "obs:rewrite_count",
    "obs:rewrite_total_ms",
    "obs:rewrite_failure_count",
```

These string literals match the dead constants in `state.py` (GAP-DC-001). No code path writes these keys to session state.

## Suggested Fix

Remove all three entries from the `_KNOWN_OBS_KEYS` list in `live_loader.py`.
