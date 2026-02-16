# BUG-7: ContextVar stdout/stderr capture declared but never used

## Location

`rlm_adk/repl/local_repl.py` lines 27-31 (module-level declarations) and lines 284-293 (`_capture_output`)

## Description

The module declares task-local `ContextVar` instances for stdout/stderr capture, intended to satisfy CRIT-3.4 (task-local capture to avoid cross-task leakage):

```python
# Task-local stdout/stderr capture (CRIT-3.4)
_capture_stdout: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar(
    "_capture_stdout", default=None
)
_capture_stderr: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar(
    "_capture_stderr", default=None
)
```

However, these `ContextVar` instances are never read or written anywhere in the codebase. The actual capture in `_capture_output` and `execute_code_async` replaces `sys.stdout` / `sys.stderr` globally:

```python
@contextmanager
def _capture_output(self):
    old_stdout, old_stderr = sys.stdout, sys.stderr
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    try:
        sys.stdout, sys.stderr = stdout_buf, stderr_buf
        yield stdout_buf, stderr_buf
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
```

Global `sys.stdout`/`sys.stderr` replacement is not task-local -- concurrent asyncio tasks sharing the same event loop will write to whichever buffer was most recently installed, causing cross-task output leakage.

## Impact

- When multiple async REPL executions run concurrently (e.g., batched sub-LM calls that each produce output), stdout/stderr from one task can bleed into another task's capture buffer
- AR-CRIT-002 requirement "stdout/stderr capture shall be task-local to avoid cross-task leakage" is not satisfied
- The `contextvars` import and the two `ContextVar` declarations are dead code

## Fix

Replace the global `sys.stdout`/`sys.stderr` swap with a `ContextVar`-based approach. One pattern:

```python
import contextvars
import io

_capture_stdout: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar(
    "_capture_stdout", default=None
)
_capture_stderr: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar(
    "_capture_stderr", default=None
)

class _TaskLocalStream:
    """Write proxy that routes to the task-local ContextVar buffer if set,
    otherwise falls through to the original stream."""

    def __init__(self, original, ctx_var: contextvars.ContextVar):
        self._original = original
        self._ctx_var = ctx_var

    def write(self, s):
        buf = self._ctx_var.get(None)
        if buf is not None:
            return buf.write(s)
        return self._original.write(s)

    def flush(self):
        buf = self._ctx_var.get(None)
        if buf is not None:
            buf.flush()
        else:
            self._original.flush()
```

Install the proxies once at module load time:

```python
sys.stdout = _TaskLocalStream(sys.stdout, _capture_stdout)
sys.stderr = _TaskLocalStream(sys.stderr, _capture_stderr)
```

Then in `execute_code_async`, set/reset the `ContextVar` tokens instead of replacing `sys.stdout`:

```python
stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
tok_out = _capture_stdout.set(stdout_buf)
tok_err = _capture_stderr.set(stderr_buf)
try:
    # ... execute code ...
finally:
    _capture_stdout.reset(tok_out)
    _capture_stderr.reset(tok_err)
```

## Affected SRS requirements

- AR-CRIT-002 (Async Bridge via AST Rewrite -- task-local capture clause)
