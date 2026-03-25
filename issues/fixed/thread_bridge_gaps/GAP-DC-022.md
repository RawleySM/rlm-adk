# GAP-DC-022: `_execute_code_inner` and `execute_code` are used only by pytest fixture and unit tests
**Severity**: LOW
**Category**: unwired
**Files**: `rlm_adk/repl/local_repl.py`

## Problem

`_execute_code_inner()` and `execute_code()` form the sync execution path in `LocalREPL`. The production pipeline exclusively uses `execute_code_threaded()` -> `_execute_code_threadsafe()`. The sync path is only used by:

1. The `repl` pytest fixture in `conftest.py` (which provides a `LocalREPL` for unit tests)
2. Direct unit tests that call `repl.execute_code()` or `repl._execute_code_inner()`
3. No production code path

This is not necessarily a problem -- the sync path serves as a simpler test interface. However, if a bug exists in `_execute_code_threadsafe()` that does not exist in `_execute_code_inner()` (or vice versa), unit tests using the sync path would not catch it.

## Evidence

Production path (REPLTool):
```python
# repl_tool.py:192
result = await self.repl.execute_code_threaded(exec_code, trace=trace)
```

The sync `execute_code()` is never called by `REPLTool` or `RLMOrchestratorAgent`.

## Suggested Fix

This is a design observation, not a bug. The two execution paths are intentionally different (one uses `_EXEC_LOCK` + `os.chdir`, the other uses ContextVar capture + `_make_cwd_open`). Tests that need to verify production behavior should use `execute_code_threaded`. Tests that only need simple REPL state verification can continue using the sync path. Consider adding a comment in `execute_code` noting it is not the production execution path.
