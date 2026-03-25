# GAP-DC-018: Telemetry finalizer tests mock out execute_code_threaded entirely
**Severity**: MEDIUM
**Category**: reward-hack
**Files**: `tests_rlm_adk/test_thread_bridge.py` (lines 539-583)

## Problem

Two tests for the `_finalize_telemetry` in-finally behavior (`test_finalize_telemetry_called_on_exception` and `test_finalize_telemetry_called_on_cancel`) replace `execute_code_threaded` with a lambda that raises. This means they do NOT test the real execution path at all -- they test the exception handling and finalizer logic in isolation from actual REPL execution.

If the thread bridge itself was broken (e.g., deadlock, wrong method called), these tests would still pass because the real thread bridge is never invoked.

## Evidence

```python
async def test_finalize_telemetry_called_on_exception(self) -> None:
    ...
    async def _raise(*a, **kw):
        raise RuntimeError("injected error")
    repl.execute_code_threaded = _raise  # <-- replaces real method
    ...

async def test_finalize_telemetry_called_on_cancel(self) -> None:
    ...
    async def _cancel(*a, **kw):
        raise asyncio.CancelledError("test cancel")
    repl.execute_code_threaded = _cancel  # <-- replaces real method
    ...
```

## Suggested Fix

These tests are structurally correct for their stated purpose (verifying finalizer fires in error paths). However, their names should clarify they test the REPLTool error-handling harness, not the thread bridge. Consider renaming to `test_finalize_telemetry_called_on_repl_exception` and `test_finalize_telemetry_called_on_repl_cancel` to make clear that the thread bridge is not under test.

The real thread bridge IS tested by `test_dispatches_from_worker_thread`, `test_sync_llm_query_dispatches_from_worker_thread`, and the e2e tests, so the overall test suite is sound. This is an accuracy-of-naming issue, not a coverage gap.
