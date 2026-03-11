"""Tests for IPythonDebugExecutor -- the execution backend for LocalREPL.

RED/GREEN TDD: These tests define the contract for the IPython-based execution
backend before the implementation exists.
"""

import ast

import pytest

from rlm_adk.repl.ipython_executor import IPythonDebugExecutor, REPLDebugConfig


class TestREPLDebugConfig:
    def test_defaults_are_non_interactive(self):
        cfg = REPLDebugConfig()
        assert cfg.backend == "ipython"
        assert cfg.debug is False
        assert cfg.debugpy_enabled is False
        assert cfg.debugpy_wait is False
        assert cfg.ipython_embed is False

    def test_from_env_defaults(self, monkeypatch):
        # Clear any env vars that might be set
        for key in (
            "RLM_REPL_BACKEND", "RLM_REPL_DEBUG", "RLM_REPL_DEBUGPY",
            "RLM_REPL_DEBUGPY_WAIT", "RLM_REPL_IPYTHON_EMBED",
            "RLM_REPL_DEBUGPY_HOST", "RLM_REPL_DEBUGPY_PORT",
        ):
            monkeypatch.delenv(key, raising=False)
        cfg = REPLDebugConfig.from_env()
        assert cfg.backend == "ipython"
        assert cfg.debug is False
        assert cfg.debugpy_enabled is False
        assert cfg.debugpy_wait is False
        assert cfg.ipython_embed is False

    def test_from_env_exec_backend(self, monkeypatch):
        monkeypatch.setenv("RLM_REPL_BACKEND", "exec")
        cfg = REPLDebugConfig.from_env()
        assert cfg.backend == "exec"


class TestIPythonDebugExecutorSync:
    def test_simple_print_captures_stdout(self):
        executor = IPythonDebugExecutor()
        ns = {"__builtins__": __builtins__}
        stdout, stderr, success = executor.execute_sync("print('hello')", ns)
        assert "hello" in stdout
        assert success is True

    def test_variable_persists_in_namespace(self):
        executor = IPythonDebugExecutor()
        ns = {"__builtins__": __builtins__}
        executor.execute_sync("x = 42", ns)
        assert ns["x"] == 42
        stdout, stderr, success = executor.execute_sync("print(x)", ns)
        assert "42" in stdout
        assert success is True

    def test_exception_reports_error(self):
        executor = IPythonDebugExecutor()
        ns = {"__builtins__": __builtins__}
        stdout, stderr, success = executor.execute_sync("1/0", ns)
        assert success is False
        assert "ZeroDivisionError" in stderr

    def test_syntax_error_reports_error(self):
        executor = IPythonDebugExecutor()
        ns = {"__builtins__": __builtins__}
        stdout, stderr, success = executor.execute_sync("def(", ns)
        assert success is False
        assert "SyntaxError" in stderr

    def test_multiple_executions_share_namespace(self):
        executor = IPythonDebugExecutor()
        ns = {"__builtins__": __builtins__}
        executor.execute_sync("import math", ns)
        stdout, _, success = executor.execute_sync("print(math.pi)", ns)
        assert success is True
        assert "3.14" in stdout


class TestIPythonDebugExecutorAsync:
    @pytest.mark.asyncio
    async def test_async_wrapper_execution(self):
        """Executor can run an already-compiled async wrapper function."""
        executor = IPythonDebugExecutor()
        ns = {"__builtins__": __builtins__}

        # Build a minimal async wrapper like the AST rewriter produces
        code = "x = 42\nprint('async hello')"
        tree = ast.parse(code)
        body = tree.body
        body.append(ast.Return(
            value=ast.Call(
                func=ast.Name(id="locals", ctx=ast.Load()),
                args=[], keywords=[],
            )
        ))
        async_func = ast.AsyncFunctionDef(
            name="_repl_exec",
            args=ast.arguments(
                posonlyargs=[], args=[], vararg=None,
                kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[],
            ),
            body=body, decorator_list=[], returns=None,
            type_comment=None, type_params=[],
        )
        module = ast.Module(body=[async_func], type_ignores=[])
        ast.fix_missing_locations(module)
        compiled = compile(module, "<test>", "exec")

        stdout, stderr, new_locals = await executor.execute_async(compiled, ns)
        assert "async hello" in stdout
        assert new_locals.get("x") == 42

    @pytest.mark.asyncio
    async def test_async_exception_reports_error(self):
        """Exceptions from async execution are captured in stderr (capture mode)."""
        executor = IPythonDebugExecutor()
        ns = {"__builtins__": __builtins__}

        code = "raise ValueError('boom')"
        tree = ast.parse(code)
        body = tree.body
        body.append(ast.Return(
            value=ast.Call(
                func=ast.Name(id="locals", ctx=ast.Load()),
                args=[], keywords=[],
            )
        ))
        async_func = ast.AsyncFunctionDef(
            name="_repl_exec",
            args=ast.arguments(
                posonlyargs=[], args=[], vararg=None,
                kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[],
            ),
            body=body, decorator_list=[], returns=None,
            type_comment=None, type_params=[],
        )
        module = ast.Module(body=[async_func], type_ignores=[])
        ast.fix_missing_locations(module)
        compiled = compile(module, "<test>", "exec")

        stdout, stderr, new_locals = await executor.execute_async(compiled, ns)
        assert "ValueError" in stderr
        assert new_locals is None

    @pytest.mark.asyncio
    async def test_async_exception_propagates_without_capture(self):
        """Without capture, exceptions propagate to the caller."""
        executor = IPythonDebugExecutor()
        ns = {"__builtins__": __builtins__}

        code = "raise ValueError('boom')"
        tree = ast.parse(code)
        body = tree.body
        body.append(ast.Return(
            value=ast.Call(
                func=ast.Name(id="locals", ctx=ast.Load()),
                args=[], keywords=[],
            )
        ))
        async_func = ast.AsyncFunctionDef(
            name="_repl_exec",
            args=ast.arguments(
                posonlyargs=[], args=[], vararg=None,
                kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[],
            ),
            body=body, decorator_list=[], returns=None,
            type_comment=None, type_params=[],
        )
        module = ast.Module(body=[async_func], type_ignores=[])
        ast.fix_missing_locations(module)
        compiled = compile(module, "<test>", "exec")

        with pytest.raises(ValueError, match="boom"):
            await executor.execute_async(compiled, ns, capture=False)


class TestIPythonDebugExecutorDebugMode:
    def test_no_interactive_when_debug_disabled(self):
        """Debug mode disabled should never call IPython.embed or debugpy."""
        cfg = REPLDebugConfig(debug=False, debugpy_enabled=False, ipython_embed=False)
        executor = IPythonDebugExecutor(config=cfg)
        ns = {"__builtins__": __builtins__}
        # Should run cleanly without any interactive behavior
        stdout, stderr, success = executor.execute_sync("x = 1", ns)
        assert success is True

    def test_exec_backend_uses_raw_exec(self):
        """When backend=exec, executor uses plain exec() without IPython."""
        cfg = REPLDebugConfig(backend="exec")
        executor = IPythonDebugExecutor(config=cfg)
        ns = {"__builtins__": __builtins__}
        stdout, stderr, success = executor.execute_sync("print('raw')", ns)
        assert "raw" in stdout
        assert success is True


class TestIPythonDebugExecutorOptionalDeps:
    def test_missing_ipython_degrades_gracefully(self, monkeypatch):
        """If IPython is not installed, executor still works with exec fallback."""
        import sys
        # Temporarily hide IPython from import
        original = sys.modules.get("IPython")
        sys.modules["IPython"] = None  # type: ignore
        try:
            cfg = REPLDebugConfig(backend="ipython")
            executor = IPythonDebugExecutor(config=cfg)
            ns = {"__builtins__": __builtins__}
            stdout, stderr, success = executor.execute_sync("print('fallback')", ns)
            assert "fallback" in stdout
            assert success is True
        finally:
            if original is not None:
                sys.modules["IPython"] = original
            else:
                sys.modules.pop("IPython", None)


class TestIPythonDebugExecutorCleanup:
    def test_cleanup_is_safe(self):
        executor = IPythonDebugExecutor()
        # Should not raise
        executor.cleanup()
        # Double cleanup should also be safe
        executor.cleanup()
