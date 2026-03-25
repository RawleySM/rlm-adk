# GAP-DC-017: Skill state key tests verify constants, not behavior
**Severity**: LOW
**Category**: reward-hack
**Files**: `tests_rlm_adk/test_skill_toolset_integration.py` (lines 194-222)

## Problem

The `TestSkillStateKeys` class (4 tests) tests properties of the `REPL_SKILL_GLOBALS_INJECTED` state constant (its string value, prefix matching, non-membership in DEPTH_SCOPED_KEYS, and `should_capture_state_key` result). These tests verify static module-level data structures, not runtime behavior. They would pass even if the key were never written to session state during actual orchestrator execution.

## Evidence

```python
def test_repl_skill_globals_injected_key_exists(self):
    from rlm_adk.state import REPL_SKILL_GLOBALS_INJECTED
    assert isinstance(REPL_SKILL_GLOBALS_INJECTED, str)
    assert REPL_SKILL_GLOBALS_INJECTED == "repl_skill_globals_injected"

def test_key_matched_by_curated_prefixes(self):
    from rlm_adk.state import CURATED_STATE_PREFIXES, REPL_SKILL_GLOBALS_INJECTED
    assert any(
        REPL_SKILL_GLOBALS_INJECTED.startswith(p) for p in CURATED_STATE_PREFIXES
    )
```

These tests pass because the constant equals its expected value and a prefix matches. If the orchestrator never actually wrote this key, the tests would still pass. The actual write behavior IS tested in `TestOrchestratorSkillGlobals::test_repl_skill_globals_injected_state_key` (in test_skill_loader.py), so these tests provide only marginal additional coverage.

## Suggested Fix

Keep these tests but note they are "contract tests for the state module" rather than "behavior tests for skill globals injection." The real behavior test is in test_skill_loader.py. No action required unless test count reduction is a goal.
