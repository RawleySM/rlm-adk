# BUG-5: AST rewriter generates `return locals()` but `locals` is blocked in REPL builtins

## Location

- `rlm_adk/repl/local_repl.py` line 123 (`"locals": None` in `_SAFE_BUILTINS`)
- `rlm_adk/repl/ast_rewriter.py` lines 100-107 (`return locals()` injected into wrapper)
- `rlm_adk/orchestrator.py` lines 148-153 (AST rewrite and exec path)

## Description

The `_SAFE_BUILTINS` dict intentionally blocks dangerous builtins by setting them to `None`:

```python
_SAFE_BUILTINS = {
    # ...
    "locals": None,
    "globals": None,
    "compile": None,
    # ...
}
```

The AST rewriter (`rewrite_for_async`) wraps LM-generated code in an `async def _repl_exec()` function and appends `return locals()` so the caller can extract variables created during execution:

```python
return_locals = ast.Return(
    value=ast.Call(
        func=ast.Name(id="locals", ctx=ast.Load()),
        args=[],
        keywords=[],
    )
)
```

When the orchestrator executes the rewritten code, it runs in a namespace derived from the REPL:

```python
ns = {**repl.globals, **repl.locals}
exec(compile(rewritten, "<repl>", "exec"), ns)
repl_exec_fn = ns["_repl_exec"]
result = await repl.execute_code_async(code_str, repl_exec_fn)
```

The namespace `ns` inherits `__builtins__` from `repl.globals`, where `locals` is `None`. When `_repl_exec()` hits `return locals()`, Python resolves `locals` through the builtins chain and finds `None`, causing:

```
TypeError: 'NoneType' object is not callable
```

Note: the `compile()` call on the orchestrator side (line 150) uses Python's real `compile` builtin from the orchestrator's own scope, so it works. But `locals()` inside the generated function runs in the REPL's restricted namespace and fails.

## Reproduction

```python
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.repl.ast_rewriter import rewrite_for_async

repl = LocalREPL()
code = "x = 42"  # simple code that the rewriter would wrap
rewritten = rewrite_for_async(code)
ns = {**repl.globals, **repl.locals}
exec(compile(rewritten, "<repl>", "exec"), ns)
import asyncio
result = asyncio.run(ns["_repl_exec"]())
# TypeError: 'NoneType' object is not callable
```

## Fix options

**Option A (minimal):** Remove `locals` from the blocked list:

```python
# In _SAFE_BUILTINS, change:
"locals": None,
# To:
"locals": locals,
```

This is safe because `locals()` in a sandboxed exec only exposes the exec namespace, not the host process.

**Option B (avoid `locals()` entirely):** Have the AST rewriter explicitly capture named variables instead of calling `locals()`. For example, collect all assignment targets from the AST and generate a dict return:

```python
return {"x": x, "y": y}  # instead of return locals()
```

Option A is simpler and sufficient.

## Affected SRS requirements

- AR-CRIT-002 (Async Bridge via AST Rewrite)
- FR-005 (REPL Execution Core Behavior)
- FR-011 (Sub-LM Query Support)
