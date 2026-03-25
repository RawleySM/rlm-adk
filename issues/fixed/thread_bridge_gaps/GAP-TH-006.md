# GAP-TH-006: `executor.shutdown(wait=False)` after timeout leaves orphaned thread that may mutate `self.locals`

**Severity**: MEDIUM
**Category**: threading
**Files**: `rlm_adk/repl/local_repl.py`

## Problem

In `execute_code_threaded` (lines 461-469), when a timeout occurs:

```python
except TimeoutError:
    stdout = ""
    stderr = "TimeoutError: ..."
    self._last_exec_error = stderr.strip()
finally:
    executor.shutdown(wait=False)
```

`executor.shutdown(wait=False)` returns immediately without waiting for the worker thread to finish. The worker thread continues running `_execute_code_threadsafe` in the background. If that thread eventually completes, it executes lines 376-388:

```python
if success:
    for key, value in combined.items():
        if key not in self.globals and not key.startswith("_"):
            self.locals[key] = value
    ...
    self._last_exec_error = None
```

This mutates `self.locals` and `self._last_exec_error` from the orphaned thread AFTER the timeout has been reported. If the next `execute_code_threaded` call is already running (it builds `combined` from `self.locals` at line 336), the orphaned thread's writes can corrupt the new execution's namespace.

Timeline:
1. T=0: `execute_code_threaded` starts, creates executor, submits `_execute_code_threadsafe`
2. T=30s: Timeout fires, `execute_code_threaded` returns error to caller
3. T=30s: `executor.shutdown(wait=False)` -- thread T1 still running
4. T=31s: Next `execute_code_threaded` call starts, creates new `combined` from `self.locals`
5. T=35s: Orphaned T1 finishes, writes to `self.locals` -- corrupts the snapshot that T2 already built

## Evidence

```python
# local_repl.py lines 461-469
except TimeoutError:
    stdout = ""
    stderr = (
        f"\nTimeoutError: Thread-bridge execution exceeded "
        f"{self.sync_timeout}s timeout"
    )
    self._last_exec_error = stderr.strip()
finally:
    executor.shutdown(wait=False)  # <-- Thread still running!

# local_repl.py lines 376-385 (_execute_code_threadsafe -- still running in orphaned thread)
if success:
    for key, value in combined.items():
        if key not in self.globals and not key.startswith("_"):
            self.locals[key] = value   # <-- Mutates shared state after timeout
    ...
    self._last_exec_error = None       # <-- Clears the timeout error!
```

Note that `_last_exec_error = None` on line 385 would clear the timeout error that was just set on line 467, making the timeout appear to have succeeded.

## Suggested Fix

Two options:

**Option A**: Track a generation counter. Increment a counter before each execution. In `_execute_code_threadsafe`, check the counter at the end before writing to `self.locals`. If it doesn't match, skip the write (execution was superseded):

```python
async def execute_code_threaded(self, code, trace=None):
    self._exec_generation += 1
    gen = self._exec_generation
    ...

def _execute_code_threadsafe(self, code, trace=None, generation=0):
    ...
    if success and self._exec_generation == generation:
        # Safe to write
```

**Option B**: Use `executor.shutdown(wait=True)` with `cancel_futures=True`. In Python 3.9+, `cancel_futures=True` cancels pending futures but does not interrupt running ones. For running threads, there is no safe way to interrupt them, but at least waiting prevents the next execution from racing.

**Option C** (pragmatic): Set a flag `self._timed_out = True` before the timeout return. In `_execute_code_threadsafe`, check this flag at the post-execution write point and skip the `self.locals` mutation if set.
