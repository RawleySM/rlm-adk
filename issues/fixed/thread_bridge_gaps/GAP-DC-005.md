# GAP-DC-005: Fully commented-out test file test_catalog_activation.py
**Severity**: LOW
**Category**: dead-code
**Files**: `tests_rlm_adk/test_catalog_activation.py`

## Problem

`test_catalog_activation.py` is 82 lines of entirely commented-out tests. Every test is wrapped in `#` comments. The file contains only a comment header explaining the tests are "DISABLED" because they depend on the obsolete catalog skill system. This contributes zero test coverage and adds noise to search results.

## Evidence

```python
# DISABLED: skill system reset — all skill registration/catalog tests suspended
#
# This file tested catalog-driven runtime activation: activate_side_effect_modules
# and auto-import. All tests depend on the obsolete catalog skill system
# (catalog.py moved to rlm_adk/skills/obsolete/).
```

All 82 lines are either comments or blank. The commented code references deleted modules: `rlm_adk.skills.catalog`, `rlm_adk.repl.skill_registry`.

## Suggested Fix

Delete `tests_rlm_adk/test_catalog_activation.py`. The test file has no executable content and tests functionality that no longer exists.
