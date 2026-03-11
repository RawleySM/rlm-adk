"""IPython/debugpy-backed execution backend for LocalREPL.

Provides a lightweight execution engine that:
- Owns the actual code execution (sync and async)
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
    - Execute compiled async wrapper code objects
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
    ) -> tuple[str, str, bool]:
        """Execute code synchronously, capturing stdout/stderr.

        Args:
            code: Python source code to execute.
            namespace: Combined globals+locals namespace. Modified in-place.

        Returns:
            (stdout, stderr, success) where success=True means no exception.
        """
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr

        try:
            sys.stdout, sys.stderr = stdout_buf, stderr_buf

            if self._use_ipython and self._shell is not None:
                self._execute_via_ipython(code, namespace)
            else:
                exec(code, namespace, namespace)

            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue()

            # Handle embed on success (no-op if not enabled)
            return stdout, stderr, True

        except Exception as e:
            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue() + f"\n{type(e).__name__}: {e}"

            # Optionally open embedded shell on exception
            if self._config.debug and self._config.ipython_embed:
                self._embed_on_exception(namespace, e)

            return stdout, stderr, False
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    def _execute_via_ipython(
        self, code: str, namespace: dict[str, Any],
    ) -> None:
        """Execute code using IPython's run_cell machinery.

        Uses IPython as an execution engine (NOT as an interactive shell).
        The shell's user_ns is temporarily set to our namespace.
        """
        shell = self._shell
        # Save and swap namespace
        old_ns = shell.user_ns
        shell.user_ns = namespace

        try:
            result = shell.run_cell(code, silent=False, store_history=False)
            # Propagate exceptions from the cell
            if result.error_in_exec is not None:
                raise result.error_in_exec
            if result.error_before_exec is not None:
                raise result.error_before_exec
        finally:
            shell.user_ns = old_ns

    async def execute_async(
        self, compiled: Any, namespace: dict[str, Any],
        *, capture: bool = True,
    ) -> tuple[str, str, dict[str, Any] | None]:
        """Execute a compiled async wrapper (from AST rewriter).

        The compiled code object should define an async function `_repl_exec`
        which returns locals().

        Args:
            compiled: Compiled code object containing async def _repl_exec().
            namespace: Combined globals+locals namespace.
            capture: If True, capture stdout/stderr. If False, assume the
                caller already redirected stdout/stderr (e.g. LocalREPL).

        Returns:
            (stdout, stderr, new_locals) where new_locals is the return value
            of _repl_exec(), or None on exception.
        """
        if capture:
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = stdout_buf, stderr_buf
        else:
            stdout_buf = stderr_buf = None
            old_stdout = old_stderr = None

        try:
            # Install the async wrapper into the namespace
            exec(compiled, namespace)
            repl_exec_fn = namespace["_repl_exec"]

            # Run the async function
            new_locals = await repl_exec_fn()

            if capture and stdout_buf is not None and stderr_buf is not None:
                return stdout_buf.getvalue(), stderr_buf.getvalue(), (
                    new_locals if isinstance(new_locals, dict) else None
                )
            return "", "", new_locals if isinstance(new_locals, dict) else None

        except Exception as e:
            if self._config.debug and self._config.ipython_embed:
                self._embed_on_exception(namespace, e)
            if capture:
                # When capturing, return error info instead of re-raising
                stdout = stdout_buf.getvalue() if stdout_buf else ""
                stderr = (stderr_buf.getvalue() if stderr_buf else "") + f"\n{type(e).__name__}: {e}"
                return stdout, stderr, None
            # When not capturing, re-raise so the caller's handler captures it
            raise
        finally:
            if capture and old_stdout is not None:
                sys.stdout, sys.stderr = old_stdout, old_stderr

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

    def cleanup(self) -> None:
        """Release executor resources.

        Does NOT destroy the InteractiveShell singleton since other executors
        (e.g. parent REPL in recursive dispatch) may still reference it.
        We only drop our local reference.
        """
        self._shell = None
        self._debugpy_armed = False
