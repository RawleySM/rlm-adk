"""Local REPL environment adapted for ADK.

Provides sandboxed Python code execution with:
- Safe builtins (blocks eval/exec/input)
- Context loading (context_0, context_1, ...)
- FINAL_VAR and SHOW_VARS helpers
- stdout/stderr capture
- Slots for llm_query/llm_query_batched closures (injected by orchestrator)
"""

import asyncio
import concurrent.futures
import contextvars
import io
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable

from rlm_adk.repl.ipython_executor import IPythonDebugExecutor, REPLDebugConfig
from rlm_adk.repl.trace import (
    REPLTrace,
)
from rlm_adk.types import REPLResult, RLMChatCompletion

# Task-local stdout/stderr capture (CRIT-3.4)
_capture_stdout: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar(
    "_capture_stdout", default=None
)
_capture_stderr: contextvars.ContextVar[io.StringIO | None] = contextvars.ContextVar(
    "_capture_stderr", default=None
)


class _TaskLocalStream:
    """Proxy stream that routes writes to a task-local ContextVar buffer when set,
    otherwise falls through to the original stream."""

    def __init__(self, original: io.TextIOBase, ctx_var: contextvars.ContextVar):
        self._original = original
        self._ctx_var = ctx_var

    @property
    def encoding(self):
        return self._original.encoding

    def isatty(self):
        return self._original.isatty()

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

    def fileno(self):
        raise io.UnsupportedOperation("fileno")


sys.stdout = _TaskLocalStream(sys.stdout, _capture_stdout)
sys.stderr = _TaskLocalStream(sys.stderr, _capture_stderr)

# Module-level lock protecting process-global state (os.chdir, sys.stdout/stderr)
# during synchronous execute_code. Ensures concurrent REPLs running in threads
# do not race on CWD or output capture.
_EXEC_LOCK = threading.Lock()

# Safe builtins - blocks dangerous operations like eval/exec/input
_SAFE_BUILTINS = {
    # Core types and functions
    "print": print,
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "bool": bool,
    "type": type,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "reversed": reversed,
    "range": range,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "any": any,
    "all": all,
    "pow": pow,
    "divmod": divmod,
    "chr": chr,
    "ord": ord,
    "hex": hex,
    "bin": bin,
    "oct": oct,
    "repr": repr,
    "ascii": ascii,
    "format": format,
    "hash": hash,
    "id": id,
    "iter": iter,
    "next": next,
    "slice": slice,
    "callable": callable,
    "hasattr": hasattr,
    "getattr": getattr,
    "setattr": setattr,
    "delattr": delattr,
    "dir": dir,
    "vars": vars,
    "bytes": bytes,
    "bytearray": bytearray,
    "memoryview": memoryview,
    "complex": complex,
    "object": object,
    "super": super,
    "property": property,
    "staticmethod": staticmethod,
    "classmethod": classmethod,
    "__import__": __import__,
    "__build_class__": __build_class__,
    "exec": exec,
    "open": open,
    # Exceptions
    "Exception": Exception,
    "BaseException": BaseException,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AttributeError": AttributeError,
    "FileNotFoundError": FileNotFoundError,
    "OSError": OSError,
    "IOError": IOError,
    "RuntimeError": RuntimeError,
    "NameError": NameError,
    "ImportError": ImportError,
    "StopIteration": StopIteration,
    "AssertionError": AssertionError,
    "NotImplementedError": NotImplementedError,
    "ArithmeticError": ArithmeticError,
    "LookupError": LookupError,
    "Warning": Warning,
    # Blocked
    "input": None,
    "eval": None,
    "compile": None,
    "globals": None,
    "locals": locals,
}


class LocalREPL:
    """Local REPL environment for ADK-based execution.

    Unlike the original LocalREPL which used socket-based llm_query,
    this version accepts callable closures for LM dispatch that are
    injected by the orchestrator.
    """

    def __init__(
        self,
        depth: int = 1,
        sync_timeout: float | None = None,
        executor_config: REPLDebugConfig | None = None,
    ):
        self.depth = depth
        self.sync_timeout = sync_timeout if sync_timeout is not None else float(
            os.environ.get("RLM_REPL_SYNC_TIMEOUT", "30")
        )
        self.temp_dir = tempfile.mkdtemp(prefix=f"repl_adk_{uuid.uuid4()}_")
        self.original_cwd = os.getcwd()
        self._pending_llm_calls: list[RLMChatCompletion] = []
        self._last_exec_error: str | None = None

        # Execution backend
        self._executor_config = executor_config or REPLDebugConfig.from_env()
        self._executor = IPythonDebugExecutor(config=self._executor_config)

        # Setup globals and locals
        self.globals: dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS.copy(),
            "__name__": "__main__",
        }
        self.locals: dict[str, Any] = {}

        # Register helper functions
        self.globals["FINAL_VAR"] = self._final_var
        self.globals["SHOW_VARS"] = self._show_vars

    def set_llm_query_fns(self, llm_query_fn: Callable, llm_query_batched_fn: Callable) -> None:
        """Set/update the sync LM query functions (called by orchestrator)."""
        self.globals["llm_query"] = llm_query_fn
        self.globals["llm_query_batched"] = llm_query_batched_fn

    def _final_var(self, variable_name: str) -> str:
        """Return the value of a variable as a final answer."""
        variable_name = variable_name.strip().strip("\"'")
        if variable_name in self.locals:
            return str(self.locals[variable_name])

        available = [k for k in self.locals.keys() if not k.startswith("_")]
        error_hint = ""
        if self._last_exec_error:
            error_hint = f" Last execution error: {self._last_exec_error}"
        if available:
            return (
                f"Error: Variable '{variable_name}' not found. "
                f"Available variables: {available}. "
                f"You must create and assign a variable BEFORE calling FINAL_VAR on it."
                f"{error_hint}"
            )
        return (
            f"Error: Variable '{variable_name}' not found. "
            f"No variables have been created yet. "
            f"You must create and assign a variable in a REPL block BEFORE calling FINAL_VAR on it."
            f"{error_hint}"
        )

    def _show_vars(self) -> str:
        """Show all available variables in the REPL environment."""
        available = {k: type(v).__name__ for k, v in self.locals.items() if not k.startswith("_")}
        if not available:
            return "No variables created yet. Use ```repl``` blocks to create variables."
        return f"Available variables: {available}"

    @contextmanager
    def _capture_output(self):
        """Context manager to capture stdout/stderr."""
        old_stdout, old_stderr = sys.stdout, sys.stderr
        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        try:
            sys.stdout, sys.stderr = stdout_buf, stderr_buf
            yield stdout_buf, stderr_buf
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    @contextmanager
    def _temp_cwd(self):
        """Temporarily change to temp directory for execution."""
        old_cwd = os.getcwd()
        try:
            os.chdir(self.temp_dir)
            yield
        finally:
            os.chdir(old_cwd)

    def _execute_code_inner(
        self, code: str, trace: REPLTrace | None = None,
    ) -> tuple[str, str, bool]:
        """Inner exec logic, runs under _EXEC_LOCK.

        Returns (stdout, stderr, success) where success=True means no exception.
        Side-effects: updates self.locals on success, self._last_exec_error on failure.
        Delegates actual execution to the IPythonDebugExecutor.

        Trace timing and optional tracemalloc are handled via IPython event
        callbacks (pre_run_cell / post_run_cell) instead of code injection,
        so user code line numbers are never shifted in error tracebacks.
        """
        trace_level = int(os.environ.get("RLM_REPL_TRACE", "0"))

        with _EXEC_LOCK, self._temp_cwd():
            combined = {**self.globals, **self.locals}

            # Register trace callbacks instead of injecting header/footer code
            pre_cb = post_cb = None
            if trace is not None and trace_level >= 1:
                pre_cb, post_cb = self._executor.register_trace_callbacks(
                    trace, trace_level,
                )

            try:
                stdout, stderr, success = self._executor.execute_sync(code, combined)
            finally:
                if pre_cb is not None:
                    self._executor.unregister_trace_callbacks(pre_cb, post_cb)

            if success:
                # Update locals with new variables (underscore filter hides _rlm_*)
                for key, value in combined.items():
                    if key not in self.globals and not key.startswith("_"):
                        self.locals[key] = value
                # Capture the last expression result (Feature 3) from IPython.
                # _last_expr is set by _execute_via_ipython when run_cell returns
                # a non-None result.result (the value of the last expression).
                last_expr = combined.get("_last_expr")
                if last_expr is not None:
                    self.locals["_last_expr"] = last_expr
                else:
                    self.locals.pop("_last_expr", None)
                self._last_exec_error = None
            else:
                self._last_exec_error = stderr.strip().split("\n")[-1] if stderr.strip() else None
                self.locals.pop("_last_expr", None)

            return stdout, stderr, success

    def _execute_code_threadsafe(
        self, code: str, trace: REPLTrace | None = None,
    ) -> tuple[str, str, bool]:
        """Lock-free execution for thread-bridge mode.

        Unlike ``_execute_code_inner`` this method does NOT acquire
        ``_EXEC_LOCK`` and does NOT call ``os.chdir()``.  Instead it
        uses ContextVar-based stdout/stderr capture and ``_make_cwd_open``
        for CWD-safe file access.  This prevents deadlocks when the REPL
        runs in a worker thread while the event loop holds the lock.

        Returns ``(stdout, stderr, success)`` -- same contract as
        ``_execute_code_inner``.
        """
        trace_level = int(os.environ.get("RLM_REPL_TRACE", "0"))

        combined = {**self.globals, **self.locals}
        # Inject CWD-safe open() directly into the namespace so that
        # user code calling open("file.txt", ...) resolves against
        # temp_dir rather than the process CWD.  We also patch __builtins__
        # so that code using builtins.open() is redirected as well.
        cwd_open = self._make_cwd_open()
        combined["open"] = cwd_open
        builtins = combined.get("__builtins__")
        if isinstance(builtins, dict):
            builtins["open"] = cwd_open

        # ContextVar-based stdout/stderr capture
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        stdout_token = _capture_stdout.set(stdout_buf)
        stderr_token = _capture_stderr.set(stderr_buf)

        # Register trace callbacks if needed
        pre_cb = post_cb = None
        if trace is not None and trace_level >= 1:
            pre_cb, post_cb = self._executor.register_trace_callbacks(
                trace, trace_level,
            )

        try:
            stdout, stderr, success = self._executor.execute_sync(code, combined)
        finally:
            _capture_stdout.reset(stdout_token)
            _capture_stderr.reset(stderr_token)
            if pre_cb is not None:
                self._executor.unregister_trace_callbacks(pre_cb, post_cb)

        # Merge any ContextVar-captured output with executor output
        cv_stdout = stdout_buf.getvalue()
        cv_stderr = stderr_buf.getvalue()
        if cv_stdout:
            stdout = cv_stdout + stdout
        if cv_stderr:
            stderr = cv_stderr + stderr

        if success:
            for key, value in combined.items():
                if key not in self.globals and not key.startswith("_"):
                    self.locals[key] = value
            last_expr = combined.get("_last_expr")
            if last_expr is not None:
                self.locals["_last_expr"] = last_expr
            else:
                self.locals.pop("_last_expr", None)
            self._last_exec_error = None
        else:
            self._last_exec_error = stderr.strip().split("\n")[-1] if stderr.strip() else None
            self.locals.pop("_last_expr", None)

        return stdout, stderr, success

    def execute_code(self, code: str, trace: REPLTrace | None = None) -> REPLResult:
        """Execute code synchronously in the sandboxed namespace.

        Uses _EXEC_LOCK to serialize access to process-global state
        (os.chdir, sys.stdout/stderr) so that concurrent REPLs in
        threads do not race.

        Enforces self.sync_timeout seconds via ThreadPoolExecutor.
        """
        start_time = time.perf_counter()
        self._pending_llm_calls.clear()
        timed_out = False

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._execute_code_inner, code, trace)
        try:
            stdout, stderr, _success = future.result(timeout=self.sync_timeout)
        except concurrent.futures.TimeoutError:
            timed_out = True
            stdout = ""
            stderr = (
                f"\nTimeoutError: Sync execution exceeded "
                f"{self.sync_timeout}s timeout"
            )
        finally:
            # Shut down without waiting for the timed-out thread to finish,
            # so it doesn't overwrite _last_exec_error.
            pool.shutdown(wait=not timed_out, cancel_futures=True)

        if timed_out:
            self._last_exec_error = stderr.strip()

        return REPLResult(
            stdout=stdout,
            stderr=stderr,
            locals=self.locals.copy(),
            execution_time=time.perf_counter() - start_time,
            llm_calls=self._pending_llm_calls.copy(),
            trace=trace.to_dict() if trace else None,
        )

    async def execute_code_threaded(
        self, code: str, trace: REPLTrace | None = None,
    ) -> REPLResult:
        """Execute code in a worker thread via the thread bridge.

        Creates a one-shot ``ThreadPoolExecutor`` and runs
        ``_execute_code_threadsafe`` in it via ``loop.run_in_executor``.
        This is the execution path used when the thread bridge is active
        (REPL code may call sync ``llm_query()`` which dispatches back
        to the event loop via ``run_coroutine_threadsafe``).

        Returns a ``REPLResult`` matching the contract of ``execute_code``.
        """
        start_time = time.perf_counter()
        self._pending_llm_calls.clear()

        if trace is not None:
            trace.execution_mode = "thread_bridge"

        loop = asyncio.get_running_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            stdout, stderr, _success = await asyncio.wait_for(
                loop.run_in_executor(
                    executor, self._execute_code_threadsafe, code, trace,
                ),
                timeout=self.sync_timeout,
            )
        except TimeoutError:
            stdout = ""
            stderr = (
                f"\nTimeoutError: Thread-bridge execution exceeded "
                f"{self.sync_timeout}s timeout"
            )
            self._last_exec_error = stderr.strip()
        finally:
            executor.shutdown(wait=False)

        return REPLResult(
            stdout=stdout,
            stderr=stderr,
            locals=self.locals.copy(),
            execution_time=time.perf_counter() - start_time,
            llm_calls=self._pending_llm_calls.copy(),
            trace=trace.to_dict() if trace else None,
        )

    def _make_cwd_open(self):
        """Return an open() wrapper that resolves relative paths against self.temp_dir.

        This avoids the need for os.chdir() which modifies process-global state
        and is unsafe when multiple async REPL instances run concurrently.
        """
        temp_dir = self.temp_dir
        builtin_open = open

        def _cwd_open(file, *args, **kwargs):
            if isinstance(file, str) and not os.path.isabs(file):
                file = os.path.join(temp_dir, file)
            return builtin_open(file, *args, **kwargs)

        return _cwd_open

    def cleanup(self) -> None:
        """Clean up temp directory, executor, and reset state."""
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass
        if self._executor is not None:
            self._executor.cleanup()
            self._executor = None
        self.globals.clear()
        self.locals.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()
