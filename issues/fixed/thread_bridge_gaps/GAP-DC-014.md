# GAP-DC-014: Thread bridge test_uses_thread_bridge_for_execution does not verify the bridge path
**Severity**: MEDIUM
**Category**: reward-hack
**Files**: `tests_rlm_adk/test_thread_bridge.py` (lines 488-500)

## Problem

`TestREPLToolThreadBridge::test_uses_thread_bridge_for_execution` claims to verify that "REPLTool calls repl.execute_code_threaded(), not repl.execute_code()." However, the test does not actually verify WHICH method is called. It executes code via `tool.run_async()`, checks the output contains "42", and checks stderr is empty. These assertions would also pass if `execute_code()` (the sync path) were used instead.

If someone changed REPLTool to call `repl.execute_code()` instead of `repl.execute_code_threaded()`, this test would still pass.

## Evidence

```python
async def test_uses_thread_bridge_for_execution(self) -> None:
    """REPLTool calls repl.execute_code_threaded(), not repl.execute_code()."""
    repl, tool = self._make_repl_tool()
    try:
        tc = _make_tool_context()
        result = await tool.run_async(
            args={"code": "x = 42\nprint(x)"},
            tool_context=tc,
        )
        assert "42" in result["stdout"]
        assert result["stderr"] == ""
    finally:
        repl.cleanup()
```

The test name and docstring promise path verification, but the assertions only check output correctness. A stronger test would mock or spy on `execute_code_threaded` vs `execute_code` to prove which path is taken.

## Suggested Fix

Add a spy or assertion that specifically detects the threaded path was used. For example:
1. Check that `execution_mode` in `LAST_REPL_RESULT` is `"thread_bridge"` (this IS checked in the next test, so this test is partially redundant)
2. OR: monkey-patch `repl.execute_code` to raise `AssertionError("sync path called")` and verify it does not fire
