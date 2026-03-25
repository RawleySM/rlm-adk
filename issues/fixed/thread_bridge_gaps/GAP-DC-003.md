# GAP-DC-003: Dead `execute_async` method in IPythonDebugExecutor
**Severity**: MEDIUM
**Category**: dead-code
**Files**: `rlm_adk/repl/ipython_executor.py` (lines 252-306)

## Problem

`IPythonDebugExecutor.execute_async()` is an async method that was used by the now-deleted AST rewriter path. It compiles and runs an `async def _repl_exec()` wrapper -- a pattern that only the AST rewriter produced. No code in the codebase calls this method.

## Evidence

Grep for `execute_async` across all `.py` files in `rlm_adk/` returns only the definition itself:
```
rlm_adk/repl/ipython_executor.py:252:    async def execute_async(
```

The method's docstring explicitly references the deleted system:
```python
"""Execute a compiled async wrapper (from AST rewriter).

The compiled code object should define an async function `_repl_exec`
which returns locals().
```

`_repl_exec` was the identifier created by `LlmCallRewriter` in the deleted `ast_rewriter.py`. No code path now produces compiled code objects containing `async def _repl_exec`.

The two callers are gone:
- `LocalREPL.execute_code_async()` was deleted in Phase 0.
- `REPLTool.run_async()` now calls `execute_code_threaded()` which uses `execute_sync()`.

## Suggested Fix

Delete the `execute_async` method (lines 252-306) from `IPythonDebugExecutor`. It is ~55 lines of dead code with associated dead import paths.
