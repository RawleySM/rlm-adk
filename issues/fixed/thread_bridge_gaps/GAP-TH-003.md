# GAP-TH-003: `execute_sync` overwrites `sys.stdout`/`sys.stderr` to raw `StringIO`, bypassing `_TaskLocalStream` proxy

**Severity**: HIGH
**Category**: threading
**Files**: `rlm_adk/repl/ipython_executor.py`, `rlm_adk/repl/local_repl.py`

## Problem

`local_repl.py` installs process-wide `_TaskLocalStream` proxies at module load time (lines 72-73):

```python
sys.stdout = _TaskLocalStream(sys.stdout, _capture_stdout)
sys.stderr = _TaskLocalStream(sys.stderr, _capture_stderr)
```

These proxies check the `_capture_stdout`/`_capture_stderr` ContextVars to route output to the correct per-thread buffer. This is the mechanism that makes `_execute_code_threadsafe` safe: it sets the ContextVar to a `StringIO` buffer, and all `print()` calls in that thread route to that buffer via the proxy.

However, `IPythonDebugExecutor.execute_sync` (lines 141-206) does this:

```python
old_stdout, old_stderr = sys.stdout, sys.stderr
sys.stdout, sys.stderr = stdout_buf, stderr_buf   # <-- Replaces the proxy!
try:
    ...
finally:
    sys.stdout, sys.stderr = old_stdout, old_stderr
```

This **replaces the process-wide `_TaskLocalStream` proxy** with a raw `StringIO` for the duration of execution. While this thread is executing:

1. Any OTHER thread that calls `print()` will write to the raw `StringIO` owned by this thread (since `sys.stdout` is process-global)
2. The `_TaskLocalStream` proxy that enables ContextVar-based routing is gone
3. The `_capture_stdout` ContextVar set by `_execute_code_threadsafe` becomes useless because `sys.stdout` is no longer the `_TaskLocalStream` proxy

In the thread bridge architecture, `_execute_code_threadsafe` carefully sets up ContextVar-based capture (lines 347-351), then calls `self._executor.execute_sync(code, combined)` which immediately destroys the proxy. The ContextVar capture becomes a dead path -- all output goes to `execute_sync`'s own `StringIO` instead.

This is why lines 368-374 merge ContextVar-captured output with executor output:
```python
cv_stdout = stdout_buf.getvalue()
cv_stderr = stderr_buf.getvalue()
if cv_stdout:
    stdout = cv_stdout + stdout
```

In practice, `cv_stdout` will always be empty because `execute_sync` replaced the proxy before any user code ran. The ContextVar capture in `_execute_code_threadsafe` is dead code.

The real danger: when two REPL threads run concurrently (e.g., parent paused on `llm_query()` while child executes), the child's `execute_sync` replaces `sys.stdout` process-wide. If the parent thread somehow produces output during this window (e.g., a timer callback, or the parent thread resumes after `llm_query()` returns), that output goes to the child's `StringIO` buffer.

## Evidence

```python
# ipython_executor.py lines 141-144 (execute_sync)
old_stdout, old_stderr = sys.stdout, sys.stderr
try:
    sys.stdout, sys.stderr = stdout_buf, stderr_buf  # Kills proxy

# local_repl.py lines 347-361 (_execute_code_threadsafe)
stdout_token = _capture_stdout.set(stdout_buf)       # Sets ContextVar
stderr_token = _capture_stderr.set(stderr_buf)       # Sets ContextVar
try:
    stdout, stderr, success = self._executor.execute_sync(code, combined)
    # ^ execute_sync immediately replaces sys.stdout, making ContextVar useless
```

## Suggested Fix

Modify `execute_sync` to detect whether `sys.stdout` is already a `_TaskLocalStream` and, if so, skip the raw replacement. Instead, rely on the ContextVar mechanism:

**Option A**: Add a parameter to `execute_sync` that disables the stdout/stderr swap:

```python
def execute_sync(self, code, namespace, *, capture_output=True):
    if capture_output:
        # Swap sys.stdout/stderr (legacy path for _execute_code_inner)
        ...
    else:
        # Caller handles capture (thread-bridge path)
        ...
```

`_execute_code_threadsafe` would call `execute_sync(code, combined, capture_output=False)`.

**Option B**: Make `execute_sync` aware of `_TaskLocalStream`: if `sys.stdout` is already a `_TaskLocalStream`, don't swap it -- just let the ContextVar routing work. This is simpler but couples the executor to the REPL's output infrastructure.

**Option C** (minimal): Since the executor's own `StringIO` capture works correctly in practice (it's what actually captures the output), document that the ContextVar-based capture in `_execute_code_threadsafe` is a secondary mechanism. The real fix for cross-thread output bleeding is to NOT replace `sys.stdout` process-wide in `execute_sync` when called from a worker thread.
