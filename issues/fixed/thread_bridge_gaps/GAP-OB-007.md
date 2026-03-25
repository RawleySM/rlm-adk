# GAP-OB-007: REPLTrace.start_time may be 0.0 in thread bridge timeout path
**Severity**: HIGH
**Category**: observability
**Files**: `rlm_adk/repl/local_repl.py`, `rlm_adk/repl/trace.py`, `rlm_adk/tools/repl_tool.py`

## Problem

When `execute_code_threaded` times out, the `REPLTrace.start_time` may still be `0.0` (its default) if the worker thread never ran far enough to trigger the trace callback. In this case, `trace.summary()` computes `wall_time_ms` as:

```python
round(max(0, self.end_time - self.start_time) * 1000, 2) if self.start_time and self.end_time else 0
```

If `start_time` is `0.0` (falsy in Python), this evaluates to `0` regardless of `end_time`. This is technically correct (returns 0 for an unmeasurable execution). However, the error path in `repl_tool.py` (lines 193-224) attempts to set `trace.end_time` for the CancelledError path:

```python
if trace is not None and trace.start_time and not trace.end_time:
    trace.end_time = time.perf_counter()
```

But `local_repl.py` line 461-467 does NOT set `trace.end_time` on timeout:
```python
except TimeoutError:
    stdout = ""
    stderr = "..."
    self._last_exec_error = stderr.strip()
```

The `trace` object is returned inside the `REPLResult` but its `execution_mode` was set to `"thread_bridge"` (line 450) while `start_time` and `end_time` are both `0.0`. The trace summary in `LAST_REPL_RESULT` will report `wall_time_ms: 0` for a timed-out execution that actually ran for `sync_timeout` seconds.

## Evidence

`local_repl.py` lines 449-477:
```python
if trace is not None:
    trace.execution_mode = "thread_bridge"   # Set before execution

# ... execution happens in thread ...

except TimeoutError:
    stdout = ""
    stderr = "..."
    # trace.end_time is never set here
```

`repl_tool.py` lines 193-196 (CancelledError handler):
```python
if trace is not None and trace.start_time and not trace.end_time:
    trace.end_time = time.perf_counter()
```

The condition `trace.start_time` is falsy when `start_time == 0.0`, so even the REPLTool error handler skips setting `end_time`.

## Suggested Fix

In `local_repl.py` `execute_code_threaded`, set `trace.end_time` in the `TimeoutError` handler:
```python
except TimeoutError:
    if trace is not None and not trace.end_time:
        trace.end_time = time.perf_counter()
    stdout = ""
    stderr = "..."
```

Also in `repl_tool.py` error handlers, change the guard from `trace.start_time and not trace.end_time` to `not trace.end_time` (or use `trace.start_time is not None` with a sentinel instead of `0.0`).
