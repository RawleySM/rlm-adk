# GAP-DC-013: test_skill_arch_e2e.py not listed as deleted but should have been
**Severity**: MEDIUM
**Category**: dead-code
**Files**: `tests_rlm_adk/test_skill_arch_e2e.py`

## Problem

`rlm_adk_docs/thread_bridge.md` lists `tests_rlm_adk/test_skill_arch_e2e.py` as a deleted file:
```
### Deleted files:
- tests_rlm_adk/test_skill_arch_e2e.py — Old source-expansion tests
```

However, the file still exists on disk. It appears to be a DIFFERENT file from the one described as deleted. The current file tests "Architecture introspection skill via thread bridge" (not source-expansion). It was likely re-created after the deletion as part of the skill_arch_test fixture.

This file is excluded from the default contract runner via `_WORKER_FIXTURE_EXCLUSIONS` (the `skill_arch_test` entry), but it has its own `pytestmark` with `pytest.mark.provider_fake` (not `provider_fake_contract`), so it runs in the extended test suite.

## Evidence

The file exists:
```
tests_rlm_adk/test_skill_arch_e2e.py — 99 lines, not commented out
```

It imports from active modules and uses the `skill_arch_test.json` fixture (which is excluded from the contract runner). The test is structurally valid but the thread_bridge.md documentation incorrectly claims it was deleted.

## Suggested Fix

Update `rlm_adk_docs/thread_bridge.md` to remove `tests_rlm_adk/test_skill_arch_e2e.py` from the "Deleted files" list, since the current version is a valid test file for the new architecture.
