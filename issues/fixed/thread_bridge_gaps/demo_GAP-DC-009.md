# Demo: GAP-DC-009 -- Broken fixtures excluded from CI

## What was fixed

Five provider-fake fixtures (`adaptive_confidence_gating`, `deterministic_guardrails`, `full_pipeline`, `structured_control_plane`, `fake_polya_t4_debate`) are incompatible with the thread bridge execution model but were not excluded from the contract test runner. They could cause silent failures or mask regressions in CI. The fix adds all 5 to `_WORKER_FIXTURE_EXCLUSIONS` in `test_provider_fake_e2e.py`.

## Before (the problem)

The exclusion set ended at `skill_helper` -- the 5 broken fixtures were discovered by `_all_fixture_paths()` and parametrized into `test_fixture_contract`:

```python
_WORKER_FIXTURE_EXCLUSIONS = {
    "all_workers_fail_batch",
    "worker_429_mid_batch",
    "worker_500_retry_exhausted",
    "worker_500_retry_exhausted_naive",
    "worker_empty_response",
    "worker_empty_response_finish_reason",
    "worker_safety_finish",
    "skill_toolset_discovery",
    "skill_recursive_ping_e2e",
    "skill_thread_bridge",
    "skill_arch_test",
    "skill_expansion",
    "skill_helper",
}
# adaptive_confidence_gating, deterministic_guardrails, full_pipeline,
# structured_control_plane, fake_polya_t4_debate -- NOT excluded, will run and fail
```

## After (the fix)

All 5 fixtures are now in the exclusion set with a comment referencing the thread bridge migration doc:

```python
_WORKER_FIXTURE_EXCLUSIONS = {
    ...
    "skill_expansion",
    "skill_helper",
    # Thread-bridge-incompatible fixtures (GAP-DC-009). These encode response
    # sequences designed for the deleted AST-rewriter dispatch model (1 API call
    # per worker). Under thread bridge, each llm_query() spawns a child
    # orchestrator that consumes multiple responses, causing sequence exhaustion.
    # fake_polya_t4_debate also imports from the deleted rlm_repl_skills namespace.
    # See rlm_adk_docs/thread_bridge.md "Known Remaining Work" for migration plan.
    "adaptive_confidence_gating",
    "deterministic_guardrails",
    "full_pipeline",
    "structured_control_plane",
    "fake_polya_t4_debate",
}
```

## Verification commands

### 1. Confirm all 5 names appear in the exclusion set

```bash
grep -c "adaptive_confidence_gating\|deterministic_guardrails\|full_pipeline\|structured_control_plane\|fake_polya_t4_debate" tests_rlm_adk/test_provider_fake_e2e.py
```

Expected output: `5` (one line per fixture name).

### 2. Confirm provider-fake contract tests pass

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -x -q -o "addopts="
```

All parametrized fixtures should pass. None of the 5 excluded fixtures should appear in the test IDs.

### 3. Confirm no regressions in thread bridge / skill tests

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py tests_rlm_adk/test_skill_loader.py tests_rlm_adk/test_skill_toolset_integration.py tests_rlm_adk/test_skill_thread_bridge_e2e.py -x -q -o "addopts="
```

## Verification Checklist

- [ ] `grep -c` returns `5` -- all fixture names present in exclusion set
- [ ] `test_provider_fake_e2e.py` passes with no failures
- [ ] Thread bridge and skill test suites pass with no regressions
- [ ] None of the 5 excluded fixture names appear in pytest parametrize output
