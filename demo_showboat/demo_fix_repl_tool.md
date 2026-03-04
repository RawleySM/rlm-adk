# REPLTool Fixes -- Showboat Demo

## BUG-C: RecursionError in Variable Serialization

**File:** `rlm_adk/tools/repl_tool.py:182`

**Problem:** Before the fix, `json.dumps()` on a circular dict raises `RecursionError`.
Since the except tuple only caught `(TypeError, ValueError, OverflowError)`, the
`RecursionError` propagated to the outer `except Exception` at line 144, which
discards ALL execution results (stdout, variables) and returns a generic error.
A successful REPL execution with `print("hello")` followed by `d = {}; d['self'] = d`
would lose the "hello" stdout entirely.

**Fix:** Added `RecursionError` to the except tuple at line 182:
```python
except (TypeError, ValueError, OverflowError, RecursionError):
    pass  # Skip non-serializable values (incl. circular refs)
```

### Inline Test

```python
"""BUG-C: RecursionError in variable serialization does not discard stdout."""
import asyncio
from unittest.mock import MagicMock
from rlm_adk.tools.repl_tool import REPLTool
from rlm_adk.repl.local_repl import LocalREPL


def _make_tool_context():
    tc = MagicMock()
    tc.state = {}
    return tc


async def test_bugc_circular_dict_preserves_stdout():
    """A circular dict in locals must not discard stdout from the execution."""
    repl = LocalREPL()
    tool = REPLTool(repl=repl)
    tc = _make_tool_context()

    # Code that prints output AND creates a circular reference
    code = "print('visible output')\nd = {}\nd['self'] = d"
    result = await tool.run_async(args={"code": code}, tool_context=tc)

    # Before the fix: result["stderr"] would contain "RecursionError: ..."
    # and result["stdout"] would be "" (all output discarded).
    # After the fix: stdout is preserved, circular var is silently skipped.
    assert result["stdout"].strip() == "visible output", (
        f"FAIL: stdout was '{result['stdout']}' instead of 'visible output'"
    )
    assert result["stderr"] == "", (
        f"FAIL: stderr was '{result['stderr']}' instead of empty"
    )
    # The circular dict 'd' should be excluded from variables
    assert "d" not in result["variables"], (
        f"FAIL: circular dict 'd' should not appear in variables, got {result['variables']}"
    )

    repl.cleanup()
    print("PASS: BUG-C circular dict preserves stdout")


async def test_bugc_non_circular_vars_still_returned():
    """Non-circular variables alongside a circular one are still returned."""
    repl = LocalREPL()
    tool = REPLTool(repl=repl)
    tc = _make_tool_context()

    code = "x = 42\ncircular = []\ncircular.append(circular)"
    result = await tool.run_async(args={"code": code}, tool_context=tc)

    assert result["variables"].get("x") == 42, (
        f"FAIL: x should be 42, got {result['variables'].get('x')}"
    )
    assert "circular" not in result["variables"], (
        f"FAIL: circular list should not appear in variables"
    )
    assert result["stderr"] == "", (
        f"FAIL: stderr should be empty, got '{result['stderr']}'"
    )

    repl.cleanup()
    print("PASS: BUG-C non-circular vars preserved alongside circular ones")


async def test_bugc_last_repl_result_written():
    """LAST_REPL_RESULT is written even when circular refs exist in locals."""
    repl = LocalREPL()
    tool = REPLTool(repl=repl)
    tc = _make_tool_context()

    code = "d = {}\nd['self'] = d\nprint('ok')"
    result = await tool.run_async(args={"code": code}, tool_context=tc)

    from rlm_adk.state import LAST_REPL_RESULT
    assert LAST_REPL_RESULT in tc.state, (
        f"FAIL: LAST_REPL_RESULT not written to tool_context.state"
    )
    lrr = tc.state[LAST_REPL_RESULT]
    assert lrr["has_output"] is True, (
        f"FAIL: has_output should be True, got {lrr['has_output']}"
    )
    assert lrr["has_errors"] is False, (
        f"FAIL: has_errors should be False, got {lrr['has_errors']}"
    )

    repl.cleanup()
    print("PASS: BUG-C LAST_REPL_RESULT correctly written with circular refs")


if __name__ == "__main__":
    asyncio.run(test_bugc_circular_dict_preserves_stdout())
    asyncio.run(test_bugc_non_circular_vars_still_returned())
    asyncio.run(test_bugc_last_repl_result_written())
```

---

## FM-13: CancelledError Accumulator Flush

**File:** `rlm_adk/tools/repl_tool.py:120-143`

**Problem:** Before the fix, `CancelledError` was caught by the combined
`except (Exception, asyncio.CancelledError)` handler at line 144 (old numbering).
That handler returned immediately with a generic error dict, skipping both:
1. `flush_fn()` -- dispatch accumulators (worker counts, latencies) were lost
2. `LAST_REPL_RESULT` write -- observability plugins received no data for that iteration

This caused "accumulator drift": if 3 worker dispatches happened before cancellation,
those 3 dispatches vanished from the session state.

**Fix:** Separated `CancelledError` into its own handler (lines 120-143) that:
1. Calls `self._flush_fn()` and writes accumulated state to `tool_context.state`
2. Writes `LAST_REPL_RESULT` with `cancelled: True` flag
3. Returns a tool result dict with `CancelledError` in stderr

### Inline Test

```python
"""FM-13: CancelledError handler flushes accumulators before returning."""
import asyncio
from unittest.mock import MagicMock
from rlm_adk.tools.repl_tool import REPLTool
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.state import LAST_REPL_RESULT, WORKER_DISPATCH_COUNT


def _make_tool_context():
    tc = MagicMock()
    tc.state = {}
    return tc


async def test_fm13_flush_fn_called_on_cancellation():
    """flush_fn must be called when CancelledError is raised during execution."""
    repl = LocalREPL()
    flush_calls = []

    def fake_flush():
        flush_calls.append(1)
        return {
            WORKER_DISPATCH_COUNT: 3,
            "obs:worker_dispatch_latency_ms": [50.1, 60.2, 70.3],
        }

    tool = REPLTool(repl=repl, flush_fn=fake_flush)

    # Patch execute_code to raise CancelledError (simulates task cancellation)
    def raise_cancelled(code, **kw):
        raise asyncio.CancelledError("task cancelled")
    repl.execute_code = raise_cancelled

    tc = _make_tool_context()
    result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)

    # flush_fn must have been called exactly once
    assert len(flush_calls) == 1, (
        f"FAIL: flush_fn called {len(flush_calls)} times, expected 1"
    )

    # Accumulated state must be written to tool_context.state
    assert tc.state[WORKER_DISPATCH_COUNT] == 3, (
        f"FAIL: WORKER_DISPATCH_COUNT should be 3, got {tc.state.get(WORKER_DISPATCH_COUNT)}"
    )
    assert tc.state["obs:worker_dispatch_latency_ms"] == [50.1, 60.2, 70.3], (
        f"FAIL: latencies not written correctly"
    )

    repl.cleanup()
    print("PASS: FM-13 flush_fn called on CancelledError, accumulators written")


async def test_fm13_last_repl_result_written_on_cancellation():
    """LAST_REPL_RESULT must be written with cancelled=True on CancelledError."""
    repl = LocalREPL()

    def fake_flush():
        return {WORKER_DISPATCH_COUNT: 2}

    tool = REPLTool(repl=repl, flush_fn=fake_flush)

    def raise_cancelled(code, **kw):
        raise asyncio.CancelledError()
    repl.execute_code = raise_cancelled

    tc = _make_tool_context()
    result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)

    assert LAST_REPL_RESULT in tc.state, (
        f"FAIL: LAST_REPL_RESULT not written to tool_context.state"
    )
    lrr = tc.state[LAST_REPL_RESULT]
    assert lrr["cancelled"] is True, (
        f"FAIL: cancelled flag should be True, got {lrr.get('cancelled')}"
    )
    assert lrr["has_errors"] is True, (
        f"FAIL: has_errors should be True for cancellation, got {lrr.get('has_errors')}"
    )
    assert lrr["total_llm_calls"] == 2, (
        f"FAIL: total_llm_calls should be 2 (from flush), got {lrr.get('total_llm_calls')}"
    )

    repl.cleanup()
    print("PASS: FM-13 LAST_REPL_RESULT written with cancelled=True")


async def test_fm13_cancelled_error_returns_correct_result_shape():
    """CancelledError handler must return a dict matching the normal return shape."""
    repl = LocalREPL()
    tool = REPLTool(repl=repl)

    def raise_cancelled(code, **kw):
        raise asyncio.CancelledError("test cancellation")
    repl.execute_code = raise_cancelled

    tc = _make_tool_context()
    result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)

    # Verify all required keys are present
    required_keys = {"stdout", "stderr", "variables", "llm_calls_made", "call_number"}
    assert required_keys.issubset(result.keys()), (
        f"FAIL: missing keys: {required_keys - result.keys()}"
    )

    assert result["stdout"] == "", (
        f"FAIL: stdout should be empty on cancellation"
    )
    assert "CancelledError" in result["stderr"], (
        f"FAIL: stderr should contain CancelledError, got '{result['stderr']}'"
    )
    assert result["variables"] == {}, (
        f"FAIL: variables should be empty dict on cancellation"
    )
    assert result["call_number"] == 1, (
        f"FAIL: call_number should be 1, got {result['call_number']}"
    )

    repl.cleanup()
    print("PASS: FM-13 CancelledError returns correct result shape")


async def test_fm13_no_flush_fn_still_works():
    """CancelledError handler must not crash when flush_fn is None."""
    repl = LocalREPL()
    tool = REPLTool(repl=repl)  # no flush_fn

    def raise_cancelled(code, **kw):
        raise asyncio.CancelledError()
    repl.execute_code = raise_cancelled

    tc = _make_tool_context()
    result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)

    assert "CancelledError" in result["stderr"], (
        f"FAIL: should still return CancelledError in stderr"
    )
    lrr = tc.state[LAST_REPL_RESULT]
    assert lrr["total_llm_calls"] == 0, (
        f"FAIL: total_llm_calls should be 0 when no flush_fn, got {lrr.get('total_llm_calls')}"
    )

    repl.cleanup()
    print("PASS: FM-13 CancelledError with no flush_fn does not crash")


if __name__ == "__main__":
    asyncio.run(test_fm13_flush_fn_called_on_cancellation())
    asyncio.run(test_fm13_last_repl_result_written_on_cancellation())
    asyncio.run(test_fm13_cancelled_error_returns_correct_result_shape())
    asyncio.run(test_fm13_no_flush_fn_still_works())
```

---

## Running All Tests

```bash
cd /home/rawley-stanhope/dev/rlm-adk
.venv/bin/python -c "
import asyncio, sys

# BUG-C tests
from demo_fix_repl_tool import (  # requires running as module
    test_bugc_circular_dict_preserves_stdout,
    test_bugc_non_circular_vars_still_returned,
    test_bugc_last_repl_result_written,
    test_fm13_flush_fn_called_on_cancellation,
    test_fm13_last_repl_result_written_on_cancellation,
    test_fm13_cancelled_error_returns_correct_result_shape,
    test_fm13_no_flush_fn_still_works,
)

async def main():
    tests = [
        test_bugc_circular_dict_preserves_stdout,
        test_bugc_non_circular_vars_still_returned,
        test_bugc_last_repl_result_written,
        test_fm13_flush_fn_called_on_cancellation,
        test_fm13_last_repl_result_written_on_cancellation,
        test_fm13_cancelled_error_returns_correct_result_shape,
        test_fm13_no_flush_fn_still_works,
    ]
    passed = 0
    for t in tests:
        try:
            await t()
            passed += 1
        except Exception as e:
            print(f'FAIL: {t.__name__}: {e}')
    print(f'\n{passed}/{len(tests)} tests passed')
    sys.exit(0 if passed == len(tests) else 1)

asyncio.run(main())
"
```
