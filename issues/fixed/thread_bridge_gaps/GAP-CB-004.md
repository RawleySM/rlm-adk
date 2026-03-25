# GAP-CB-004: `_finalize_telemetry` skipped when pre-execution code raises

**Severity**: LOW
**Category**: callback-lifecycle
**Files**: `rlm_adk/tools/repl_tool.py` (lines 109-311)

## Problem

`REPLTool.run_async()` has code between the method entry (line 109) and the `try` block that guards `_finalize_telemetry` (line 190). If any of the pre-execution code raises an exception, the `finally` block at line 308 fires but `_final_result` is `None`, so `_finalize_telemetry` is never called.

The pre-execution code that could raise includes:
- `save_repl_code()` at line 120 (artifact service I/O)
- `tool_context.state[...]` writes at lines 114-117 (unlikely but possible with corrupted state)

If `save_repl_code` fails, the tool state has already been partially written (submitted code metadata at lines 114-117) but the telemetry finalizer won't fire, leaving an incomplete telemetry row in the traces database.

## Evidence

```python
async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> dict:
    code = args["code"]
    # ... state writes at lines 114-117 ...
    await save_repl_code(...)  # line 120 -- could raise
    self._call_count += 1      # line 129
    # ... more pre-execution code ...

    _final_result: dict | None = None  # line 189
    try:
        # ... execution code ...
    finally:
        if _final_result is not None:  # line 309 -- False if pre-exec raised
            self._finalize_telemetry(tool_context, _final_result)
```

## Impact

Minor. The `save_repl_code` artifact save is the most likely failure point (disk full, permissions). If it fails, the exception propagates to ADK's tool error handling, and the tool call is reported as failed through ADK's normal error path. The missing telemetry row is an observability gap, not a correctness bug.

## Suggested Fix

Move the `_final_result` declaration and `try/finally` to wrap the entire method body including pre-execution code, or catch `save_repl_code` failures separately so execution can still proceed:

```python
async def run_async(self, *, args, tool_context):
    _final_result = None
    try:
        # ... all existing code ...
    finally:
        if _final_result is not None:
            self._finalize_telemetry(tool_context, _final_result)
```
