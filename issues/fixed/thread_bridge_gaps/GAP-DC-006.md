# GAP-DC-006: Legacy fixture files for deleted skill expansion system
**Severity**: LOW
**Category**: dead-code
**Files**: `tests_rlm_adk/fixtures/provider_fake/skill_expansion.json`, `tests_rlm_adk/fixtures/provider_fake/skill_helper.json`

## Problem

Two provider-fake fixture files were created for the source-expansion skill system that was deleted in Phase 0B. They are excluded from the contract runner via `_WORKER_FIXTURE_EXCLUSIONS` but remain as dead files on disk.

## Evidence

The exclusion in `test_provider_fake_e2e.py`:
```python
# Legacy skill fixtures from pre-thread-bridge era (AST rewriter).
# skill_expansion used source expansion which was removed in Phase 0B.
# skill_helper used old skill system patterns also removed.
"skill_expansion",
"skill_helper",
```

The fixtures exist on disk but no test file imports or uses them outside the excluded parametrize path.

## Suggested Fix

Delete both files:
- `tests_rlm_adk/fixtures/provider_fake/skill_expansion.json`
- `tests_rlm_adk/fixtures/provider_fake/skill_helper.json`

Remove the two exclusion entries from `_WORKER_FIXTURE_EXCLUSIONS` (the comment and the two names).
