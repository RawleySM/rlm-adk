# Demo: GAP-OB-007 -- REPLTrace falsy sentinel causes wall_time_ms: 0 on timeout/error paths

## What was fixed

`REPLTrace` used `0.0` as the default sentinel for `start_time` and `end_time`. Because `0.0` is falsy in Python, all truthiness guards (`if self.start_time and self.end_time`) silently skipped timing computation on timeout and error paths. This caused `wall_time_ms: 0` for timed-out executions that actually ran for the full timeout duration. Additionally, neither `TimeoutError` handler in `local_repl.py` recorded `end_time` at all. 7 defect locations across 4 files.

## Before (the problem)

### Falsy sentinel in trace.py

```python
@dataclass
class REPLTrace:
    start_time: float = 0.0   # 0.0 is falsy in Python
    end_time: float = 0.0     # bool(0.0) is False
```

### Broken truthiness guards in trace.py

```python
# to_dict() and summary() both used this pattern:
round(max(0, self.end_time - self.start_time) * 1000, 2) if self.start_time and self.end_time else 0
# When start_time == 0.0 (falsy), guard evaluates to False -> always returns 0
```

### Missing end_time in timeout handlers (local_repl.py)

```python
# execute_code_threaded:
except TimeoutError:
    stdout = ""
    stderr = "..."
    # trace.end_time never set -> remains 0.0

# execute_code (sync):
except concurrent.futures.TimeoutError:
    stdout = ""
    stderr = "..."
    # trace.end_time never set -> remains 0.0
```

### Falsy guards in repl_tool.py

```python
# CancelledError and Exception handlers both used:
if trace is not None and trace.start_time and not trace.end_time:
    trace.end_time = time.perf_counter()
# When start_time == 0.0, "trace.start_time" is False -> repair skipped
```

## After (the fix)

### None sentinel in trace.py

```python
@dataclass
class REPLTrace:
    start_time: float | None = None   # None is unambiguously "not set"
    end_time: float | None = None
```

### Explicit is-not-None guards in trace.py

```python
# to_dict() and summary():
round(max(0, self.end_time - self.start_time) * 1000, 2) if self.start_time is not None and self.end_time is not None else 0
```

### Timeout handlers now record end_time (local_repl.py)

```python
# execute_code_threaded:
except TimeoutError:
    if trace is not None:
        trace.end_time = time.perf_counter()
    stdout = ""
    stderr = "..."

# execute_code (sync):
except concurrent.futures.TimeoutError:
    if trace is not None:
        trace.end_time = time.perf_counter()
    stdout = ""
    stderr = "..."
```

### Fixed guards in repl_tool.py

```python
# CancelledError and Exception handlers:
if trace is not None and trace.end_time is None:
    trace.end_time = time.perf_counter()
```

## Verification commands

### 1. Run the 21 new trace timing tests

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_repl_trace_timing.py -x -q -o "addopts="
```

All 21 tests should pass. These cover: sentinel defaults, wall_time_ms computation with None, timeout path end_time recording, truthiness-vs-identity guard behavior, and edge cases (both times None, start set but end not, etc.).

### 2. Run thread bridge / skill regression suite

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_thread_bridge.py tests_rlm_adk/test_skill_loader.py tests_rlm_adk/test_skill_toolset_integration.py tests_rlm_adk/test_skill_thread_bridge_e2e.py -x -q -o "addopts="
```

No regressions expected -- the sentinel change is internal to `REPLTrace` and does not affect execution semantics.

## Verification Checklist

- [ ] `test_repl_trace_timing.py`: all 21 tests pass
- [ ] Thread bridge + skill test suites pass with no regressions
- [ ] `trace.py`: `start_time` and `end_time` default to `None` with type `float | None`
- [ ] `trace.py`: `to_dict()` and `summary()` use `is not None` guards
- [ ] `local_repl.py`: both `TimeoutError` handlers set `trace.end_time = time.perf_counter()`
- [ ] `repl_tool.py`: CancelledError and Exception handlers use `trace.end_time is None` (not truthiness)
- [ ] `wall_time_ms` is `0` when trace_level == 0 (start_time remains None)
- [ ] `wall_time_ms` is positive when timeout occurs after trace callback set start_time
