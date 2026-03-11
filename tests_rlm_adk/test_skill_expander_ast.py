"""AST integration tests: expanded skill code works with has_llm_calls + rewrite_for_async."""

from __future__ import annotations

import ast

import pytest

from rlm_adk.repl.ast_rewriter import has_llm_calls, rewrite_for_async
from rlm_adk.repl.skill_registry import _registry, expand_skill_imports


@pytest.fixture(autouse=True)
def register_ping_skill():
    """Register the real ping skill exports for AST tests."""
    import importlib

    import rlm_adk.skills.repl_skills.ping as ping_mod

    _registry.clear()
    importlib.reload(ping_mod)
    yield
    _registry.clear()


class TestExpandedLlmQueryTriggersHasLlmCalls:
    def test_expanded_llm_query_detected(self):
        code = (
            "from rlm_repl_skills.ping import run_recursive_ping\nresult = run_recursive_ping()\n"
        )
        expansion = expand_skill_imports(code)
        assert expansion.did_expand is True
        # The expanded code should contain llm_query call
        assert has_llm_calls(expansion.expanded_code) is True

    def test_unexpanded_code_no_llm_calls(self):
        code = (
            "from rlm_repl_skills.ping import PING_TERMINAL_PAYLOAD\nprint(PING_TERMINAL_PAYLOAD)\n"
        )
        expansion = expand_skill_imports(code)
        assert expansion.did_expand is True
        # Constants don't contain llm_query
        assert has_llm_calls(expansion.expanded_code) is False


class TestExpandedFunctionPromotedToAsync:
    def test_run_recursive_ping_promoted(self):
        code = (
            "from rlm_repl_skills.ping import run_recursive_ping\nresult = run_recursive_ping()\n"
        )
        expansion = expand_skill_imports(code)
        tree = rewrite_for_async(expansion.expanded_code)
        source = ast.unparse(tree)
        # run_recursive_ping should be promoted to async
        assert "async def run_recursive_ping" in source
        # The call should be awaited
        assert "await run_recursive_ping" in source


class TestExpandedNestedCallsAwaited:
    def test_nested_calls_awaited(self):
        code = (
            "from rlm_repl_skills.ping import run_recursive_ping, RecursivePingResult\n"
            "r = run_recursive_ping(max_layer=1)\n"
            "print(r.payload)\n"
        )
        expansion = expand_skill_imports(code)
        tree = rewrite_for_async(expansion.expanded_code)
        source = ast.unparse(tree)
        # llm_query should be rewritten to await llm_query_async
        assert "llm_query_async" in source
        assert "await" in source

    def test_expanded_code_compiles(self):
        code = (
            "from rlm_repl_skills.ping import run_recursive_ping\nresult = run_recursive_ping()\n"
        )
        expansion = expand_skill_imports(code)
        tree = rewrite_for_async(expansion.expanded_code)
        # Should compile without error
        compiled = compile(tree, "<test>", "exec")
        assert compiled is not None
