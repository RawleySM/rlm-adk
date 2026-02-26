"""AR-CRIT-002: Async bridge via AST rewrite.

Covers:
- Code containing llm_query/llm_query_batched shall be rewritten to async awaits
- Rewritten code shall execute under async wrapper and preserve locals
- Timeout handling shall wrap coroutine consumption, not async generator object
- stdout/stderr capture shall be task-local to avoid cross-task leakage
"""

import ast

import pytest

from rlm_adk.repl.ast_rewriter import (
    LlmCallRewriter,
    _contains_await,
    _promote_functions_to_async,
    compile_repl_code,
    has_llm_calls,
    rewrite_for_async,
)
from rlm_adk.repl.local_repl import LocalREPL


class TestHasLlmCalls:
    """Detect llm_query / llm_query_batched calls via AST."""

    def test_detects_llm_query(self):
        assert has_llm_calls("result = llm_query('hello')")

    def test_detects_llm_query_batched(self):
        assert has_llm_calls("results = llm_query_batched(['a', 'b'])")

    def test_no_calls(self):
        assert not has_llm_calls("x = 1 + 2")

    def test_string_literal_not_matched(self):
        """String containing 'llm_query' should not trigger detection."""
        assert not has_llm_calls("x = 'llm_query is a function'")

    def test_comment_not_matched(self):
        assert not has_llm_calls("# llm_query(prompt)")

    def test_syntax_error_returns_false(self):
        assert not has_llm_calls("def broken(")

    def test_nested_call(self):
        assert has_llm_calls("x = process(llm_query('inner'))")

    def test_both_calls(self):
        code = "a = llm_query('x')\nb = llm_query_batched(['y'])"
        assert has_llm_calls(code)


class TestLlmCallRewriter:
    """AST node transformer: sync -> async await."""

    def _get_rewritten_source(self, code: str) -> str:
        tree = ast.parse(code)
        rewriter = LlmCallRewriter()
        new_tree = rewriter.visit(tree)
        ast.fix_missing_locations(new_tree)
        return ast.unparse(new_tree)

    def test_llm_query_rewritten_to_await(self):
        src = self._get_rewritten_source("result = llm_query('hello')")
        assert "await" in src
        assert "llm_query_async" in src

    def test_llm_query_batched_rewritten(self):
        src = self._get_rewritten_source("results = llm_query_batched(['a'])")
        assert "await" in src
        assert "llm_query_batched_async" in src

    def test_keyword_args_preserved(self):
        src = self._get_rewritten_source("r = llm_query('p', model='gpt-4')")
        assert "model=" in src
        assert "llm_query_async" in src

    def test_non_llm_calls_unchanged(self):
        src = self._get_rewritten_source("x = print('hello')")
        assert "await" not in src
        assert "print" in src

    def test_nested_calls_both_rewritten(self):
        src = self._get_rewritten_source("x = llm_query(llm_query('inner'))")
        assert src.count("await") == 2
        assert src.count("llm_query_async") == 2


class TestRewriteForAsync:
    """Full rewrite pipeline: parse -> transform -> wrap in async def."""

    def test_produces_async_function_def(self):
        module = rewrite_for_async("x = llm_query('hello')")
        assert isinstance(module, ast.Module)
        assert len(module.body) == 1
        func_def = module.body[0]
        assert isinstance(func_def, ast.AsyncFunctionDef)
        assert func_def.name == "_repl_exec"

    def test_function_ends_with_return_locals(self):
        module = rewrite_for_async("x = 1")
        func_def = module.body[0]
        last_stmt = func_def.body[-1]
        assert isinstance(last_stmt, ast.Return)

    def test_compilable(self):
        module = rewrite_for_async("x = llm_query('p')")
        code_obj = compile(module, "<repl>", "exec")
        assert code_obj is not None

    def test_syntax_error_propagates(self):
        with pytest.raises(SyntaxError):
            rewrite_for_async("def broken(")


class TestCompileReplCode:
    """compile_repl_code dispatches between sync and async."""

    def test_sync_code_not_async(self):
        code_obj, is_async = compile_repl_code("x = 1 + 2")
        assert not is_async
        assert code_obj is not None

    def test_async_code_detected(self):
        code_obj, is_async = compile_repl_code("r = llm_query('p')")
        assert is_async
        assert code_obj is not None


class TestAsyncExecution:
    """AR-CRIT-002: Rewritten code executes under async wrapper, preserves locals."""

    @pytest.mark.asyncio
    async def test_async_exec_preserves_locals(self):
        """Rewritten code should return locals via _repl_exec()."""

        async def mock_llm_query_async(prompt, model=None):
            return f"response to: {prompt}"

        module = rewrite_for_async("result = llm_query('hello')")
        ns = {"llm_query_async": mock_llm_query_async}
        exec(compile(module, "<repl>", "exec"), ns)
        repl_exec = ns["_repl_exec"]
        new_locals = await repl_exec()
        assert "result" in new_locals
        assert "response to: hello" in new_locals["result"]

    @pytest.mark.asyncio
    async def test_repl_execute_code_async(self):
        """Full integration: LocalREPL.execute_code_async with mocked LM."""

        async def mock_llm_query_async(prompt, model=None):
            return "mocked response"

        async def mock_batched(prompts, model=None):
            return [f"batch_{i}" for i in range(len(prompts))]

        repl = LocalREPL()
        repl.set_async_llm_query_fns(mock_llm_query_async, mock_batched)

        code = "result = llm_query('test')"
        module = rewrite_for_async(code)
        ns = {**repl.globals, **repl.locals}
        exec(compile(module, "<repl>", "exec"), ns)
        repl_exec_fn = ns["_repl_exec"]

        result = await repl.execute_code_async(code, repl_exec_fn)
        assert result.stderr == ""
        assert "result" in repl.locals
        assert repl.locals["result"] == "mocked response"
        repl.cleanup()


# ---------------------------------------------------------------------------
# Bug-fix tests: _contains_await scope pruning
# ---------------------------------------------------------------------------


class TestContainsAwait:
    """_contains_await must not descend into nested function/class scopes."""

    @staticmethod
    def _parse_func(code: str) -> ast.FunctionDef:
        """Parse code and return the first FunctionDef node."""
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                return node
        raise AssertionError("No FunctionDef found")

    def test_direct_await_detected(self):
        code = "def foo():\n    await something()"
        func = self._parse_func(code)
        assert _contains_await(func) is True

    def test_await_in_if_block_detected(self):
        code = "def foo():\n    if True:\n        x = await something()"
        func = self._parse_func(code)
        assert _contains_await(func) is True

    def test_nested_async_def_not_detected(self):
        code = (
            "def outer():\n"
            "    async def inner():\n"
            "        await x\n"
            "    y = 1\n"
        )
        func = self._parse_func(code)
        assert _contains_await(func) is False

    def test_nested_sync_def_not_detected(self):
        code = (
            "def outer():\n"
            "    def inner():\n"
            "        await x\n"
            "    y = 1\n"
        )
        func = self._parse_func(code)
        assert _contains_await(func) is False

    def test_class_scope_not_descended(self):
        code = (
            "def outer():\n"
            "    class C:\n"
            "        async def m(self):\n"
            "            await x\n"
            "    y = 1\n"
        )
        func = self._parse_func(code)
        assert _contains_await(func) is False

    def test_no_await_returns_false(self):
        code = "def foo():\n    return 1"
        func = self._parse_func(code)
        assert _contains_await(func) is False


# ---------------------------------------------------------------------------
# Bug-fix tests: promotion and double-await prevention
# ---------------------------------------------------------------------------


class TestPromotionAndDoubleAwait:
    """_promote_functions_to_async must not produce double-await."""

    @staticmethod
    def _rewrite_source(code: str) -> str:
        """Run the full rewrite pipeline and return unparsed source."""
        module = rewrite_for_async(code)
        return ast.unparse(module)

    def test_single_promoted_function_no_double_await(self):
        code = (
            "def helper(t):\n"
            "    return llm_query(t)\n"
            "result = helper('x')\n"
        )
        src = self._rewrite_source(code)
        assert "await (await" not in src

    def test_transitive_chain_no_double_await(self):
        code = (
            "def bar(t):\n"
            "    return llm_query(t)\n"
            "def foo(t):\n"
            "    return bar(t)\n"
            "result = foo('x')\n"
        )
        src = self._rewrite_source(code)
        # Three awaits: llm_query_async, bar(), foo()
        assert src.count("await") == 3
        assert "await (await" not in src

    def test_promoted_in_gather_args_no_double_await(self):
        code = (
            "def helper(t):\n"
            "    return llm_query(t)\n"
            "results = [helper('a'), helper('b')]\n"
        )
        src = self._rewrite_source(code)
        assert "await (await" not in src

    def test_multi_round_promotion_compiles(self):
        code = (
            "def bar(t):\n"
            "    return llm_query(t)\n"
            "def foo(t):\n"
            "    return bar(t)\n"
            "result = foo('x')\n"
        )
        module = rewrite_for_async(code)
        # Must compile without error
        compile(module, "<repl>", "exec")

    def test_simple_llm_query_still_works(self):
        code = "result = llm_query('hello')\n"
        src = self._rewrite_source(code)
        assert "await llm_query_async" in src

    def test_promoted_returns_correct_names(self):
        code = (
            "def bar(t):\n"
            "    return llm_query(t)\n"
            "def foo(t):\n"
            "    return bar(t)\n"
            "result = foo('x')\n"
        )
        tree = ast.parse(code)
        # First apply the LlmCallRewriter so llm_query becomes await llm_query_async
        LlmCallRewriter().visit(tree)
        ast.fix_missing_locations(tree)
        promoted = _promote_functions_to_async(tree)
        assert promoted == {"bar", "foo"}


# ---------------------------------------------------------------------------
# Bug-fix tests: promoted function execution (end-to-end)
# ---------------------------------------------------------------------------


class TestPromotedFunctionExecution:
    """Promoted (transitive) functions must execute without double-await TypeError."""

    @pytest.mark.asyncio
    async def test_transitive_chain_executes(self):
        """Transitive chain: foo -> bar -> llm_query should execute correctly."""

        async def mock_llm_query_async(prompt, model=None):
            return f"echo:{prompt}"

        code = (
            "def bar(t):\n"
            "    return llm_query(t)\n"
            "def foo(t):\n"
            "    return bar(t)\n"
            "result = foo('ping')\n"
        )
        module = rewrite_for_async(code)
        ns: dict = {"llm_query_async": mock_llm_query_async}
        exec(compile(module, "<repl>", "exec"), ns)
        new_locals = await ns["_repl_exec"]()
        assert new_locals["result"] == "echo:ping"
