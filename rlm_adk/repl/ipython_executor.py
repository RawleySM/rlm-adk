"""IPython/debugpy-backed execution backend for LocalREPL.

Provides a lightweight execution engine that:
- Owns the actual code execution (sync)
- Optionally uses IPython's InteractiveShell for execution
- Optionally arms debugpy for remote debugging
- Never activates interactive features unless explicitly enabled
- Falls back to raw exec() if IPython is unavailable

No ADK-specific behavior lives here.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import time
import tracemalloc
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class REPLDebugConfig:
    """Configuration for the IPython/debugpy execution backend.

    All interactive features default to OFF for safety in CI/tests.
    """

    backend: str = "ipython"  # "exec" | "ipython"
    debug: bool = False
    debugpy_enabled: bool = False
    debugpy_host: str = "127.0.0.1"
    debugpy_port: int = 5678
    debugpy_wait: bool = False
    ipython_embed: bool = False
    xmode: str = "Context"  # "Verbose" | "Context" | "Minimal"

    @classmethod
    def from_env(cls) -> REPLDebugConfig:
        """Create config from environment variables."""
        return cls(
            backend=os.environ.get("RLM_REPL_BACKEND", "ipython"),
            debug=os.environ.get("RLM_REPL_DEBUG", "0") == "1",
            debugpy_enabled=os.environ.get("RLM_REPL_DEBUGPY", "0") == "1",
            debugpy_host=os.environ.get("RLM_REPL_DEBUGPY_HOST", "127.0.0.1"),
            debugpy_port=int(os.environ.get("RLM_REPL_DEBUGPY_PORT", "5678")),
            debugpy_wait=os.environ.get("RLM_REPL_DEBUGPY_WAIT", "0") == "1",
            ipython_embed=os.environ.get("RLM_REPL_IPYTHON_EMBED", "0") == "1",
            xmode=os.environ.get("RLM_REPL_XMODE", "Context"),
        )


def _try_import_ipython():
    """Lazily import IPython's InteractiveShell. Returns None if unavailable."""
    try:
        from IPython.core.interactiveshell import InteractiveShell
        return InteractiveShell
    except (ImportError, TypeError):
        return None


def _try_import_debugpy():
    """Lazily import debugpy. Returns None if unavailable."""
    try:
        import debugpy
        return debugpy
    except (ImportError, TypeError):
        return None


class IPythonDebugExecutor:
    """Execution engine that delegates to IPython or raw exec().

    Responsibilities:
    - Execute sync code and capture stdout/stderr
    - Optionally arm debugpy (only when explicitly enabled)
    - Optionally open embedded IPython shell on exceptions (only when enabled)
    - Surface stdout, stderr, exception text, and namespace updates
    """

    def __init__(self, config: REPLDebugConfig | None = None):
        self._config = config or REPLDebugConfig()
        self._shell = None  # Lazy-initialized IPython shell
        self._debugpy_armed = False
        self._use_ipython = self._config.backend == "ipython"

        # Attempt to get IPython if backend=ipython
        if self._use_ipython:
            shell_cls = _try_import_ipython()
            if shell_cls is not None:
                self._shell = shell_cls.instance()
                # Apply traceback mode (Verbose/Context/Minimal)
                try:
                    self._shell.InteractiveTB.set_mode(mode=self._config.xmode)
                except Exception:
                    pass
            else:
                # IPython unavailable, fall back to exec
                self._use_ipython = False

        # Arm debugpy if explicitly enabled
        if self._config.debugpy_enabled:
            self._arm_debugpy()

    def _arm_debugpy(self) -> None:
        """Arm debugpy for remote debugging if enabled and available."""
        debugpy = _try_import_debugpy()
        if debugpy is None:
            return
        try:
            debugpy.listen((self._config.debugpy_host, self._config.debugpy_port))
            self._debugpy_armed = True
            if self._config.debugpy_wait:
                debugpy.wait_for_client()
        except Exception as e:
            logger.warning(
                "Failed to arm debugpy on %s:%s: %s",
                self._config.debugpy_host, self._config.debugpy_port, e,
            )

    def execute_sync(
        self, code: str, namespace: dict[str, Any],
        *, capture_output: bool = True,
    ) -> tuple[str, str, bool]:
        """Execute code synchronously, capturing stdout/stderr.

        Args:
            code: Python source code to execute.
            namespace: Combined globals+locals namespace. Modified in-place.
            capture_output: When True (default), replace sys.stdout/sys.stderr
                with StringIO buffers and return their contents.  When False,
                skip the sys.stdout/sys.stderr swap so that an external
                capture mechanism (e.g. the ``_TaskLocalStream`` ContextVar
                proxy used by ``_execute_code_threadsafe``) remains intact.
                In this mode stdout/stderr are returned as empty strings --
                the caller is responsible for reading from its own buffers.

        Returns:
            (stdout, stderr, success) where success=True means no exception.
        """
        if capture_output:
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            old_stdout, old_stderr = sys.stdout, sys.stderr
        else:
            stdout_buf = stderr_buf = None  # Not used in this path

        try:
            if capture_output:
                sys.stdout, sys.stderr = stdout_buf, stderr_buf

            if self._use_ipython and self._shell is not None:
                # Temporarily suppress IPython's own traceback printing;
                # we will format it ourselves so normal stdout is preserved.
                shell = self._shell
                orig_showtraceback = shell.showtraceback
                _captured_tb_args: list[tuple] = []

                def _capture_showtraceback(*args, **kwargs):
                    """Intercept IPython's showtraceback to capture the
                    formatted traceback text without polluting stdout."""
                    _captured_tb_args.append((args, kwargs))

                shell.showtraceback = _capture_showtraceback
                try:
                    success, ipy_result = self._execute_via_ipython(code, namespace)
                finally:
                    shell.showtraceback = orig_showtraceback

                stdout = stdout_buf.getvalue() if capture_output else ""
                stderr = stderr_buf.getvalue() if capture_output else ""
                if not success:
                    error = ipy_result.error_in_exec or ipy_result.error_before_exec
                    # Format the traceback using IPython's InteractiveTB
                    # which respects the configured xmode (Verbose/Context/Minimal)
                    tb_text = ""
                    if error is not None:
                        try:
                            stb = shell.InteractiveTB.structured_traceback(
                                type(error), error, error.__traceback__,
                            )
                            tb_text = "\n".join(stb)
                        except Exception:
                            tb_text = f"\n{type(error).__name__}: {error}"
                    if tb_text:
                        stderr = stderr + tb_text
                    elif error is not None:
                        stderr = stderr + f"\n{type(error).__name__}: {error}"

                    if self._config.debug and self._config.ipython_embed:
                        self._embed_on_exception(namespace, error)

                return stdout, stderr, success
            else:
                exec(code, namespace, namespace)

                stdout = stdout_buf.getvalue() if capture_output else ""
                stderr = stderr_buf.getvalue() if capture_output else ""

                return stdout, stderr, True

        except Exception as e:
            stdout = stdout_buf.getvalue() if capture_output else ""
            stderr = (stderr_buf.getvalue() if capture_output else "") + f"\n{type(e).__name__}: {e}"

            # Optionally open embedded shell on exception
            if self._config.debug and self._config.ipython_embed:
                self._embed_on_exception(namespace, e)

            return stdout, stderr, False
        finally:
            if capture_output:
                sys.stdout, sys.stderr = old_stdout, old_stderr

    def _execute_via_ipython(
        self, code: str, namespace: dict[str, Any],
    ) -> tuple[bool, Any]:
        """Execute code using IPython's run_cell machinery.

        Uses IPython as an execution engine (NOT as an interactive shell).
        The shell's user_ns is temporarily set to our namespace.

        Returns:
            (success, result) where result is the IPython ExecutionResult.
            On error, IPython has already printed the formatted traceback
            to the captured stdout stream (including local vars in Verbose mode).
            The caller should move that output to stderr.
        """
        shell = self._shell
        # Save and swap namespace
        old_ns = shell.user_ns
        # Ensure IPython internal keys exist in the namespace to prevent
        # KeyError from output caching (e.g. _oh, _ih, _dh).
        for key in ("_oh", "_ih", "_dh", "_", "__", "___"):
            if key not in namespace:
                if key == "_oh":
                    namespace[key] = {}
                elif key in ("_ih", "_dh"):
                    namespace[key] = []
                else:
                    namespace[key] = ""
        shell.user_ns = namespace

        try:
            result = shell.run_cell(code, silent=False, store_history=False)
            error = result.error_in_exec or result.error_before_exec
            # Capture the last expression value (Feature 3).
            # result.result holds the value of the last expression in the cell
            # (e.g. `42 + 1` yields 43). Store it in the namespace as _last_expr
            # so it's available for data flow tracking without explicit print().
            if error is None and result.result is not None:
                namespace["_last_expr"] = result.result
            else:
                namespace["_last_expr"] = None
            return (error is None, result)
        finally:
            shell.user_ns = old_ns

    def _embed_on_exception(
        self, namespace: dict[str, Any], exc: Exception,
    ) -> None:
        """Optionally open an embedded IPython shell for debugging.

        Only called when both debug and ipython_embed are enabled.
        """
        if not self._config.ipython_embed:
            return
        try:
            from IPython import embed
            embed(user_ns=namespace, banner1=f"Debug: {type(exc).__name__}: {exc}")
        except (ImportError, TypeError):
            pass

    # ── Trace callbacks (Feature 2) ──────────────────────────────────────

    def register_trace_callbacks(self, trace: Any, trace_level: int) -> tuple[Any, Any]:
        """Register IPython pre_run_cell / post_run_cell callbacks for tracing.

        Replaces the old code-injection approach (TRACE_HEADER/FOOTER) with
        IPython event callbacks.  This preserves correct line numbers in error
        tracebacks because no code is prepended/appended to user code.

        Args:
            trace: REPLTrace instance to populate with timing/memory data.
            trace_level: 0=off, 1=timing, 2=timing+tracemalloc.

        Returns:
            (pre_cb, post_cb) — the registered callback callables, needed by
            ``unregister_trace_callbacks`` for cleanup.
        """
        _mem_was_tracing = [False]

        def _pre_run_cell(info=None):
            trace.start_time = time.perf_counter()
            if trace_level >= 2:
                _mem_was_tracing[0] = tracemalloc.is_tracing()
                if not _mem_was_tracing[0]:
                    tracemalloc.start()

        def _post_run_cell(result=None):
            if trace_level >= 2:
                if not _mem_was_tracing[0]:
                    _current, _peak = tracemalloc.get_traced_memory()
                    trace.peak_memory_bytes = _peak
                    tracemalloc.stop()
            trace.end_time = time.perf_counter()

        if self._shell is not None:
            self._shell.events.register("pre_run_cell", _pre_run_cell)
            self._shell.events.register("post_run_cell", _post_run_cell)

        return _pre_run_cell, _post_run_cell

    def unregister_trace_callbacks(self, pre_cb: Any, post_cb: Any) -> None:
        """Unregister previously registered trace callbacks."""
        if self._shell is not None:
            try:
                self._shell.events.unregister("pre_run_cell", pre_cb)
            except ValueError:
                pass
            try:
                self._shell.events.unregister("post_run_cell", post_cb)
            except ValueError:
                pass

    def cleanup(self) -> None:
        """Release executor resources.

        Does NOT destroy the InteractiveShell singleton since other executors
        (e.g. parent REPL in recursive dispatch) may still reference it.
        We only drop our local reference.
        """
        self._shell = None
        self._debugpy_armed = False
