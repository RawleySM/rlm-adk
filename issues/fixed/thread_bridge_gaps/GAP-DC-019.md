# GAP-DC-019: Skill loader orchestrator tests use incomplete mock InvocationContext
**Severity**: LOW
**Category**: reward-hack
**Files**: `tests_rlm_adk/test_skill_loader.py` (lines 371-476), `tests_rlm_adk/test_skill_toolset_integration.py` (lines 234-631)

## Problem

Multiple tests in both files create an `RLMOrchestratorAgent`, start its `_run_async_impl()` generator, collect a few events, then stop. The `mock_ctx` used is a minimal `MagicMock()` that triggers early termination when `reasoning_agent.run_async(ctx)` fails due to incomplete mock context. The tests rely on the orchestrator's setup code (before the delegation to reasoning_agent) running to completion, but the actual delegation and thread bridge dispatch are never exercised.

This is acceptable for testing that skill globals are injected (which happens before delegation), but the test names and docstrings sometimes imply broader coverage ("orchestrator injects skill globals", "children get REPL globals") than what is actually verified.

## Evidence

```python
async def _collect_orch_events(orch, mock_ctx, max_events=3):
    events = []
    try:
        async for event in orch._run_async_impl(mock_ctx):
            events.append(event)
            if len(events) >= max_events:
                break
    except Exception:
        pass  # Expected — mock ctx is incomplete for full run
    return events
```

The `except Exception: pass` suppresses all failures from the mock context being incomplete. If the orchestrator's setup code crashed (e.g., due to a bug in skill globals injection), the test would still collect 0 events and might pass or fail depending on what assertions follow.

## Suggested Fix

The tests are structurally adequate for their narrow purpose (verifying setup-phase state writes). However:
1. Consider asserting `len(events) >= 1` to ensure the orchestrator at least emitted the initial state delta event
2. Document in the test class docstring that these tests verify orchestrator setup phase only, not end-to-end dispatch

Note: The e2e tests in `test_skill_thread_bridge_e2e.py` and `test_skill_toolset_integration.py::TestSkillToolsetE2E` DO exercise the full pipeline, so the overall test suite covers the end-to-end path.
