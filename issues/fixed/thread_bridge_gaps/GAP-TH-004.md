# GAP-TH-004: `__builtins__` dict shared by reference -- `_execute_code_threadsafe` mutates it across all LocalREPL instances

**Severity**: MEDIUM
**Category**: threading
**Files**: `rlm_adk/repl/local_repl.py`

## Problem

In `LocalREPL.__init__` (line 203), the globals dict is initialized with:

```python
self.globals: dict[str, Any] = {
    "__builtins__": _SAFE_BUILTINS.copy(),
    ...
}
```

This correctly creates a copy of `_SAFE_BUILTINS`. However, in `_execute_code_threadsafe` (lines 343-345):

```python
builtins = combined.get("__builtins__")
if isinstance(builtins, dict):
    builtins["open"] = cwd_open
```

The `combined` dict is constructed as `{**self.globals, **self.locals}` (line 336). The `**` spread for dicts performs a shallow copy -- the top-level keys are copied, but `__builtins__` value (itself a dict) is shared by reference. So `builtins["open"] = cwd_open` mutates the ORIGINAL `self.globals["__builtins__"]` dict.

This means:
1. Every call to `_execute_code_threadsafe` permanently mutates `self.globals["__builtins__"]["open"]` to point to the latest `_make_cwd_open()` result
2. If two threads are executing concurrently on the same `LocalREPL` instance (shouldn't happen in normal flow, but could under edge conditions), the `open` builtin could be swapped mid-execution
3. More subtly: the `combined["open"] = cwd_open` (line 342) sets a top-level key that shadows the builtin, but the `builtins["open"]` mutation (line 345) is permanent and persists after `_execute_code_threadsafe` returns

In practice, within a single `LocalREPL` instance, `self.temp_dir` doesn't change, so the `cwd_open` closure always resolves to the same directory. But the mutation pattern is incorrect -- the builtins dict should not be permanently modified by what is supposed to be a per-execution setup.

## Evidence

```python
# local_repl.py line 336
combined = {**self.globals, **self.locals}
# combined["__builtins__"] is the SAME dict object as self.globals["__builtins__"]

# local_repl.py lines 343-345
builtins = combined.get("__builtins__")
if isinstance(builtins, dict):
    builtins["open"] = cwd_open  # Mutates self.globals["__builtins__"] permanently
```

## Suggested Fix

Copy the builtins dict before mutating it:

```python
combined = {**self.globals, **self.locals}
cwd_open = self._make_cwd_open()
combined["open"] = cwd_open
builtins = combined.get("__builtins__")
if isinstance(builtins, dict):
    builtins = builtins.copy()              # Defensive copy
    builtins["open"] = cwd_open
    combined["__builtins__"] = builtins     # Use the copy
```

This is low-impact today because `temp_dir` is stable per REPL instance, but it prevents a class of bugs if the code is ever modified to handle multiple concurrent executions or if `temp_dir` changes.
