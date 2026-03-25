# GAP-DC-016: Orchestrator import test is trivially true
**Severity**: LOW
**Category**: reward-hack
**Files**: `tests_rlm_adk/test_thread_bridge.py` (lines 648-658)

## Problem

`TestOrchestratorWiring::test_orchestrator_imports_thread_bridge` only verifies that `make_sync_llm_query` and `make_sync_llm_query_batched` can be imported. This tests Python's import system, not any thread bridge behavior. If the module exists and is syntactically valid, this test passes regardless of whether the functions work correctly.

## Evidence

```python
def test_orchestrator_imports_thread_bridge(self) -> None:
    """The orchestrator module can import thread bridge factories."""
    from rlm_adk.repl.thread_bridge import (  # noqa: F401
        make_sync_llm_query,
        make_sync_llm_query_batched,
    )
    assert callable(make_sync_llm_query)
    assert callable(make_sync_llm_query_batched)
```

Any Python function is callable. This test would pass even if both functions were replaced with `lambda: None`.

## Suggested Fix

Delete this test. Import validity is implicitly tested by every other test that uses these functions. If the import breaks, many tests fail immediately.
