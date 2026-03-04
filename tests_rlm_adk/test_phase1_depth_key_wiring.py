"""Tests for Phase 1: Activate depth_key() in state reads/writes.

Verifies that the orchestrator and REPLTool use depth_key() for all
DEPTH_SCOPED_KEYS, and that depth=0 produces identical keys to the
current behavior (transparent refactor).
"""

import asyncio
import inspect
import textwrap

import pytest
from unittest.mock import MagicMock

from rlm_adk.orchestrator import RLMOrchestratorAgent
from rlm_adk.tools.repl_tool import REPLTool
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.state import (
    depth_key,
    ITERATION_COUNT,
    LAST_REPL_RESULT,
    FINAL_ANSWER,
    SHOULD_STOP,
)


def _get_orchestrator_source() -> str:
    return textwrap.dedent(
        inspect.getsource(RLMOrchestratorAgent._run_async_impl)
    )


def _make_tool_context(state=None):
    tc = MagicMock()
    tc.state = state if state is not None else {}
    return tc


class TestDepthZeroKeysUnchanged:
    """Orchestrator at depth=0 produces state keys without @d suffix."""

    def test_depth_key_zero_is_identity(self):
        assert depth_key(FINAL_ANSWER, 0) == FINAL_ANSWER
        assert depth_key(SHOULD_STOP, 0) == SHOULD_STOP
        assert depth_key(ITERATION_COUNT, 0) == ITERATION_COUNT
        assert depth_key(LAST_REPL_RESULT, 0) == LAST_REPL_RESULT

    def test_orchestrator_source_uses_depth_key(self):
        source = _get_orchestrator_source()
        assert "depth_key(FINAL_ANSWER, self.depth)" in source
        assert "depth_key(SHOULD_STOP, self.depth)" in source
        assert "depth_key(ITERATION_COUNT, self.depth)" in source


class TestDepthOneKeysScoped:
    """Orchestrator at depth=1 produces final_answer@d1, should_stop@d1, etc."""

    def test_depth_key_one_suffixed(self):
        assert depth_key(FINAL_ANSWER, 1) == "final_answer@d1"
        assert depth_key(SHOULD_STOP, 1) == "should_stop@d1"
        assert depth_key(ITERATION_COUNT, 1) == "iteration_count@d1"
        assert depth_key(LAST_REPL_RESULT, 1) == "last_repl_result@d1"


class TestREPLToolDepthScopedIteration:
    """REPLTool at depth=N writes iteration_count@dN."""

    @pytest.mark.asyncio
    async def test_depth_zero_writes_iteration_count(self):
        repl = LocalREPL()
        try:
            tool = REPLTool(repl, depth=0)
            tc = _make_tool_context()
            await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
            assert tc.state[ITERATION_COUNT] == 1
            assert tc.state[LAST_REPL_RESULT]["code_blocks"] == 1
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_depth_two_writes_scoped_keys(self):
        repl = LocalREPL()
        try:
            tool = REPLTool(repl, depth=2)
            tc = _make_tool_context()
            await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
            # Should write to depth-scoped keys
            assert tc.state["iteration_count@d2"] == 1
            assert tc.state["last_repl_result@d2"]["code_blocks"] == 1
            # Should NOT write to depth-0 keys
            assert ITERATION_COUNT not in tc.state
            assert LAST_REPL_RESULT not in tc.state
        finally:
            repl.cleanup()

    @pytest.mark.asyncio
    async def test_depth_parameter_defaults_to_zero(self):
        repl = LocalREPL()
        try:
            tool = REPLTool(repl)  # no depth= parameter
            assert tool._depth == 0
        finally:
            repl.cleanup()


class TestOrchestratorDepthField:
    """RLMOrchestratorAgent has a depth field that defaults to 0."""

    def test_default_depth_is_zero(self):
        from google.adk.agents import LlmAgent
        agent = LlmAgent(name="test", model="test")
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=agent,
            sub_agents=[agent],
        )
        assert orch.depth == 0

    def test_custom_depth(self):
        from google.adk.agents import LlmAgent
        agent = LlmAgent(name="test", model="test")
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=agent,
            sub_agents=[agent],
            depth=3,
        )
        assert orch.depth == 3

    def test_orchestrator_passes_depth_to_repl_tool(self):
        """The orchestrator source should pass depth=self.depth to REPLTool."""
        source = _get_orchestrator_source()
        assert "depth=self.depth" in source
