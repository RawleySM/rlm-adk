# GAP-DC-009: Five broken fixtures not excluded from CI
**Severity**: CRITICAL
**Category**: fixture-integrity
**Files**: `tests_rlm_adk/test_provider_fake_e2e.py`, 5 fixture JSON files

## Problem

Five provider-fake fixtures are known to be broken due to thread bridge execution semantics changes (documented in `rlm_adk_docs/thread_bridge.md` and `MEMORY.md`) but are NOT excluded from the contract runner's `_WORKER_FIXTURE_EXCLUSIONS` set. They will be discovered by `_all_fixture_paths()` and run via `test_fixture_contract[<name>]`.

If these fixtures fail silently (e.g., the test runner marks them as errors but CI does not gate on them), they represent untested regressions. If they actually pass now, they should be documented as fixed and removed from the "known remaining work" list.

## Evidence

The 5 fixtures exist on disk:
```
tests_rlm_adk/fixtures/provider_fake/adaptive_confidence_gating.json
tests_rlm_adk/fixtures/provider_fake/deterministic_guardrails.json
tests_rlm_adk/fixtures/provider_fake/full_pipeline.json
tests_rlm_adk/fixtures/provider_fake/structured_control_plane.json
tests_rlm_adk/fixtures/provider_fake/fake_polya_t4_debate.json
```

The `_WORKER_FIXTURE_EXCLUSIONS` set does NOT contain any of these names:
```python
_WORKER_FIXTURE_EXCLUSIONS = {
    "all_workers_fail_batch",
    "worker_429_mid_batch",
    ...
    "skill_expansion",
    "skill_helper",
}
```

No `xfail` or `skip` markers reference these fixtures anywhere in the test suite (confirmed by grep).

From `rlm_adk_docs/thread_bridge.md`:
```
## Known Remaining Work
- 5 old provider-fake fixtures need updating for thread bridge execution semantics
  (adaptive_confidence_gating, deterministic_guardrails, full_pipeline,
   structured_control_plane, fake_polya_t4_debate)
```

## Suggested Fix

Either:
1. **Add to exclusion set**: Add all 5 names to `_WORKER_FIXTURE_EXCLUSIONS` with a comment explaining they need thread bridge updates. This prevents silent failures.
2. **Fix the fixtures**: Update each fixture's response sequences to work with the thread bridge execution path, then remove from the "known remaining work" list.
3. **Mark xfail**: Add `pytest.mark.xfail` for these specific parametrize IDs with a `reason` string referencing the thread bridge migration.

Option 1 is the minimum safe action. Option 2 is the correct long-term fix.
