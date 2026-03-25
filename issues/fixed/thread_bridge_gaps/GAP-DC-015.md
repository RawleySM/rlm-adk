# GAP-DC-015: Orchestrator wiring test asserts callable, not actual dispatch
**Severity**: LOW
**Category**: reward-hack
**Files**: `tests_rlm_adk/test_thread_bridge.py` (lines 594-605)

## Problem

`TestOrchestratorWiring::test_sync_llm_query_wired_to_repl_globals` asserts only that `make_sync_llm_query` returns a callable. This is trivially true for any function. The test does not verify that calling the closure actually dispatches to the event loop.

## Evidence

```python
def test_sync_llm_query_wired_to_repl_globals(self) -> None:
    """After make_sync_llm_query, the returned closure is callable."""
    from rlm_adk.repl.thread_bridge import make_sync_llm_query

    async def fake_async(prompt, **kw):
        return f"result:{prompt}"

    loop = asyncio.new_event_loop()
    llm_query = make_sync_llm_query(fake_async, loop)
    # Simulate what orchestrator does: wire into repl globals
    assert callable(llm_query)
    loop.close()
```

If `make_sync_llm_query` returned `lambda *a, **k: None`, this test would pass. The real dispatch behavior IS tested in `test_sync_llm_query_dispatches_from_worker_thread` (the next test), so this test is redundant and misleading about what it verifies.

## Suggested Fix

Either delete this test (since the next test fully covers the behavior) or strengthen it to actually call the closure and verify a result returns.
