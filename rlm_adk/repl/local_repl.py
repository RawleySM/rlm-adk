"""Local REPL environment adapted for ADK.

Provides sandboxed Python code execution with:
- Safe builtins (blocks eval/exec/input)
- Context loading (context_0, context_1, ...)
- FINAL_VAR and SHOW_VARS helpers
- stdout/stderr capture
- Slots for async llm_query/llm_query_batched closures (injected by orchestrator)
"""

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
    TRACE_HEADER,
    TRACE_HEADER_MEMORY,
    TRACE_FOOTER,
    TRACE_FOOTER_MEMORY,
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

    def set_async_llm_query_fns(
        self,
        llm_query_async_fn: Callable,
        llm_query_batched_async_fn: Callable,
    ) -> None:
        """Set async LM query functions for AST-rewritten code."""
        self.globals["llm_query_async"] = llm_query_async_fn
        self.globals["llm_query_batched_async"] = llm_query_batched_async_fn

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
        """
        trace_level = int(os.environ.get("RLM_REPL_TRACE", "0"))

        with _EXEC_LOCK, self._temp_cwd():
            combined = {**self.globals, **self.locals}

            if trace is not None:
                combined["_rlm_trace"] = trace
                if trace_level >= 2:
                    instrumented = TRACE_HEADER_MEMORY + "\n" + code + "\n" + TRACE_FOOTER_MEMORY
                else:
                    instrumented = TRACE_HEADER + "\n" + code + "\n" + TRACE_FOOTER
            else:
                instrumented = code

            stdout, stderr, success = self._executor.execute_sync(instrumented, combined)

            if success:
                # Update locals with new variables (underscore filter hides _rlm_*)
                for key, value in combined.items():
                    if key not in self.globals and not key.startswith("_"):
                        self.locals[key] = value
                self._last_exec_error = None
            else:
                self._last_exec_error = stderr.strip().split("\n")[-1] if stderr.strip() else None

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

    async def execute_code_async(
        self,
        code: str,
        repl_exec_fn: Any = None,
        trace: REPLTrace | None = None,
        *,
        compiled: Any = None,
    ) -> REPLResult:
        """Execute AST-rewritten async code.

        Does NOT call os.chdir() to avoid modifying process-global state.
        Instead, injects a custom open() that resolves relative paths against
        self.temp_dir, and sets _repl_cwd for code that needs the working dir.

        Args:
            code: The original code (before AST rewriting -- for reference/logging)
            repl_exec_fn: Legacy: pre-extracted async function from AST rewriter.
                Deprecated in favor of ``compiled``.
            trace: Optional REPLTrace accumulator for this code block
            compiled: Compiled code object containing async def _repl_exec().
                When provided, the executor installs and runs _repl_exec from
                the compiled code object, replacing the old exec()-in-REPLTool path.
        """
        start_time = time.perf_counter()
        self._pending_llm_calls.clear()

        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        tok_out = _capture_stdout.set(stdout_buf)
        tok_err = _capture_stderr.set(stderr_buf)
        # Also replace sys.stdout/stderr directly: the _TaskLocalStream proxy
        # installed at module load may have been displaced (e.g. by pytest
        # capture), so the ContextVar route alone is not reliable.
        old_stdout, old_stderr = sys.stdout, sys.stderr
        # Inject cwd-aware open() and _repl_cwd into REPL namespace
        # instead of calling os.chdir() (FM-27: avoid process-global state).
        old_open = self.globals.get("__builtins__", {}).get("open")
        self.globals.setdefault("__builtins__", {})["open"] = self._make_cwd_open()
        self.globals["_repl_cwd"] = self.temp_dir
        try:
            sys.stdout, sys.stderr = stdout_buf, stderr_buf

            if trace is not None:
                # Inject trace into the globals the compiled function sees
                self.globals["_rlm_trace"] = trace
                trace.start_time = time.perf_counter()
                trace.execution_mode = "async"

            if compiled is not None:
                # New path: delegate to executor for the async wrapper.
                # capture=False because we already redirect sys.stdout/stderr.
                ns = {**self.globals, **self.locals}
                _, _, new_locals = await self._executor.execute_async(
                    compiled, ns, capture=False,
                )
            elif repl_exec_fn is not None:
                # Legacy path: caller already extracted the async function
                new_locals = await repl_exec_fn()
            else:
                raise ValueError("Either compiled or repl_exec_fn must be provided")

            if trace is not None:
                trace.end_time = time.perf_counter()

            # Update locals with results
            if isinstance(new_locals, dict):
                for key, value in new_locals.items():
                    if not key.startswith("_"):
                        self.locals[key] = value

            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue()
            self._last_exec_error = None
        except Exception as e:
            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue() + f"\n{type(e).__name__}: {e}"
            self._last_exec_error = f"{type(e).__name__}: {e}"
            if trace is not None:
                trace.end_time = time.perf_counter()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            _capture_stdout.reset(tok_out)
            _capture_stderr.reset(tok_err)
            # Restore original open() builtin
            if old_open is not None:
                self.globals.setdefault("__builtins__", {})["open"] = old_open
            # Clean up trace and _repl_cwd from globals
            self.globals.pop("_rlm_trace", None)
            self.globals.pop("_repl_cwd", None)

        return REPLResult(
            stdout=stdout,
            stderr=stderr,
            locals=self.locals.copy(),
            execution_time=time.perf_counter() - start_time,
            llm_calls=self._pending_llm_calls.copy(),
            trace=trace.to_dict() if trace else None,
        )

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
