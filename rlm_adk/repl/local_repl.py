"""Local REPL environment adapted for ADK.

Provides sandboxed Python code execution with:
- Safe builtins (blocks eval/exec/input)
- Context loading (context_0, context_1, ...)
- FINAL_VAR and SHOW_VARS helpers
- stdout/stderr capture
- Slots for async llm_query/llm_query_batched closures (injected by orchestrator)
"""

import contextvars
import copy
import io
import os
import shutil
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable

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
        llm_query_fn: Callable | None = None,
        llm_query_batched_fn: Callable | None = None,
    ):
        self.depth = depth
        self.temp_dir = tempfile.mkdtemp(prefix=f"repl_adk_{uuid.uuid4()}_")
        self.original_cwd = os.getcwd()
        self._history_count: int = 0
        self._pending_llm_calls: list[RLMChatCompletion] = []
        self._last_exec_error: str | None = None

        # Setup globals and locals
        self.globals: dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS.copy(),
            "__name__": "__main__",
        }
        self.locals: dict[str, Any] = {}

        # Register helper functions
        self.globals["FINAL_VAR"] = self._final_var
        self.globals["SHOW_VARS"] = self._show_vars

        # Register LM query functions
        if llm_query_fn:
            self.globals["llm_query"] = llm_query_fn
        if llm_query_batched_fn:
            self.globals["llm_query_batched"] = llm_query_batched_fn

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

    def add_history(
        self, message_history: list[dict[str, Any]], history_index: int | None = None
    ) -> int:
        """Store conversation history as a versioned variable.

        Args:
            message_history: The list of message dicts from a completion call
            history_index: Optional explicit index. If None, auto-increments.

        Returns:
            The history index used.
        """
        if history_index is None:
            history_index = self._history_count

        var_name = f"history_{history_index}"
        self.locals[var_name] = copy.deepcopy(message_history)

        # Alias history_0 as 'history' for convenience
        if history_index == 0:
            self.locals["history"] = self.locals[var_name]

        self._history_count = max(self._history_count, history_index + 1)
        return history_index

    def get_history_count(self) -> int:
        """Return the number of conversation histories stored."""
        return self._history_count

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

    def execute_code(self, code: str, trace: REPLTrace | None = None) -> REPLResult:
        """Execute code synchronously in the sandboxed namespace."""
        start_time = time.perf_counter()
        self._pending_llm_calls.clear()
        trace_level = int(os.environ.get("RLM_REPL_TRACE", "0"))

        with self._capture_output() as (stdout_buf, stderr_buf), self._temp_cwd():
            try:
                combined = {**self.globals, **self.locals}

                if trace is not None:
                    combined["_rlm_trace"] = trace
                    if trace_level >= 2:
                        instrumented = TRACE_HEADER_MEMORY + "\n" + code + "\n" + TRACE_FOOTER_MEMORY
                    else:
                        instrumented = TRACE_HEADER + "\n" + code + "\n" + TRACE_FOOTER
                else:
                    instrumented = code

                exec(instrumented, combined, combined)

                # Update locals with new variables (underscore filter hides _rlm_*)
                for key, value in combined.items():
                    if key not in self.globals and not key.startswith("_"):
                        self.locals[key] = value

                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue()
                self._last_exec_error = None
            except Exception as e:
                stdout = stdout_buf.getvalue()
                stderr = stderr_buf.getvalue() + f"\n{type(e).__name__}: {e}"
                self._last_exec_error = f"{type(e).__name__}: {e}"

        return REPLResult(
            stdout=stdout,
            stderr=stderr,
            locals=self.locals.copy(),
            execution_time=time.perf_counter() - start_time,
            llm_calls=self._pending_llm_calls.copy(),
            trace=trace.to_dict() if trace else None,
        )

    async def execute_code_async(
        self, code: str, repl_exec_fn: Any, trace: REPLTrace | None = None,
    ) -> REPLResult:
        """Execute AST-rewritten async code.

        Args:
            code: The original code (before AST rewriting -- for reference/logging)
            repl_exec_fn: The compiled async function from AST rewriter
            trace: Optional REPLTrace accumulator for this code block
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
        old_cwd = os.getcwd()
        try:
            sys.stdout, sys.stderr = stdout_buf, stderr_buf
            os.chdir(self.temp_dir)

            if trace is not None:
                # Inject trace into the globals the compiled function sees
                self.globals["_rlm_trace"] = trace
                trace.start_time = time.perf_counter()
                trace.execution_mode = "async"

            # Run the async _repl_exec function
            new_locals = await repl_exec_fn()

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
            os.chdir(old_cwd)
            # Clean up trace from globals to avoid leaking between blocks
            self.globals.pop("_rlm_trace", None)

        return REPLResult(
            stdout=stdout,
            stderr=stderr,
            locals=self.locals.copy(),
            execution_time=time.perf_counter() - start_time,
            llm_calls=self._pending_llm_calls.copy(),
            trace=trace.to_dict() if trace else None,
        )

    def cleanup(self) -> None:
        """Clean up temp directory and reset state."""
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass
        self.globals.clear()
        self.locals.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def __del__(self):
        self.cleanup()
