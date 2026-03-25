# GAP-DC-012: `_execute_code_inner` and sync `execute_code` are unused dead paths
**Severity**: MEDIUM
**Category**: dead-code
**Files**: `rlm_adk/repl/local_repl.py` (lines 269-431)

## Problem

`LocalREPL._execute_code_inner()` and `LocalREPL.execute_code()` (the synchronous execution path) are no longer called by any active code in the production pipeline. REPLTool exclusively calls `execute_code_threaded()` (the thread bridge path), which uses `_execute_code_threadsafe()`.

The sync path (`_execute_code_inner`) acquires `_EXEC_LOCK` and calls `os.chdir()`, both of which are specifically avoided by the thread bridge design for deadlock prevention.

## Evidence

Grep for `execute_code\b` (not `execute_code_threaded` or `execute_code_threadsafe`) in `rlm_adk/` production code:

`REPLTool.run_async()` at line 192:
```python
result = await self.repl.execute_code_threaded(exec_code, trace=trace)
```

No production code calls `repl.execute_code()` (the sync method). It is only used by the `repl` pytest fixture and some unit tests that test the REPL in isolation.

The `_capture_output` context manager (lines 248-257) and `_temp_cwd` context manager (lines 259-267) are also only used by `_execute_code_inner`.

## Suggested Fix

Retain `execute_code()` as it serves as a simpler sync interface for direct REPL testing. However, consider:
1. Adding a deprecation docstring noting that `execute_code_threaded()` is the production path
2. Removing the `_EXEC_LOCK` import and `_capture_output`/`_temp_cwd` if no tests depend on them
3. At minimum, document in the class docstring that `execute_code_threaded` is the primary execution method
