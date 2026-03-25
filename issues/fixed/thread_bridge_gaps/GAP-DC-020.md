# GAP-DC-020: No test verifies that breaking the thread bridge causes test failures
**Severity**: MEDIUM
**Category**: unwired
**Files**: `tests_rlm_adk/test_thread_bridge.py`, `tests_rlm_adk/test_skill_thread_bridge_e2e.py`

## Problem

The audit question "If I broke the thread bridge, would this test actually fail?" reveals a gap: while individual tests verify components, no unit test explicitly verifies the negative case (that removing/breaking the bridge causes failure in REPL code that calls `llm_query()`).

The strongest coverage comes from the e2e tests (`test_skill_thread_bridge_e2e.py`) which run a fixture through the full pipeline. These WOULD fail if the thread bridge broke, because the fixture's REPL code calls `llm_query()` and expects a child dispatch result.

However, the unit tests (`test_thread_bridge.py`) use fake async functions and manual event loops. If someone replaced `run_coroutine_threadsafe` with a direct function call, many of these tests would still pass because the fake async functions don't require a real event loop.

## Evidence

`test_dispatches_from_worker_thread` is the strongest unit test -- it creates a real event loop, calls from a worker thread, and verifies the result. This WOULD fail if `run_coroutine_threadsafe` were broken.

`test_sync_llm_query_dispatches_from_worker_thread` in `TestOrchestratorWiring` is even stronger -- it wires the bridge to a real `LocalREPL`, executes code that calls `llm_query()`, and verifies the REPL stdout contains the dispatched result. This WOULD fail if the bridge were broken.

The gap is that there is no test with a NEGATIVE assertion: "if llm_query is NOT wired, calling it from REPL raises RuntimeError."

## Suggested Fix

This is more of an observation than a critical gap. The e2e tests provide the strongest guarantee. Consider adding one negative test:

```python
async def test_llm_query_without_bridge_raises(self):
    """Calling llm_query from REPL code without wired bridge fails."""
    repl = LocalREPL(depth=1)
    result = await repl.execute_code_threaded("llm_query('hello')")
    assert "NameError" in result.stderr or "not defined" in result.stderr
```

This verifies that `llm_query` does not magically exist without explicit wiring.
