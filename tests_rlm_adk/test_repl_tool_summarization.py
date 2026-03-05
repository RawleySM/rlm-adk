"""Tests for REPLTool skip_summarization behavior.

RED/GREEN TDD: These tests define the contract for the skip_summarization
feature before the implementation exists.
"""

import pytest
from unittest.mock import MagicMock

from rlm_adk.tools.repl_tool import REPLTool
from rlm_adk.repl.local_repl import LocalREPL


class _FakeActions:
    """Minimal stand-in for ADK EventActions."""

    def __init__(self):
        self.skip_summarization = False


def _make_tool_context(state=None):
    """Create a minimal mock ToolContext with a real-ish actions object."""
    tc = MagicMock()
    tc.state = state if state is not None else {}
    tc.actions = _FakeActions()
    return tc


class TestREPLToolSkipSummarization:
    @pytest.mark.asyncio
    async def test_small_output_does_not_set_skip_summarization(self):
        """Output below threshold should leave skip_summarization unchanged (False)."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        tc = _make_tool_context()
        await tool.run_async(args={"code": "print('hello')"}, tool_context=tc)
        assert tc.actions.skip_summarization is False
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_large_output_sets_skip_summarization_true(self):
        """Output >= default 5000-char threshold should set skip_summarization=True."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        tc = _make_tool_context()
        # 'x' * 5000 plus newline = 5001 chars total stdout
        await tool.run_async(args={"code": "print('x' * 5000)"}, tool_context=tc)
        assert tc.actions.skip_summarization is True
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_custom_threshold_triggers_skip_at_lower_size(self):
        """A custom threshold of 100 should trigger skip when output >= 100 chars."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl, summarization_threshold=100)
        tc = _make_tool_context()
        # 'y' * 100 plus newline = 101 chars
        await tool.run_async(args={"code": "print('y' * 100)"}, tool_context=tc)
        assert tc.actions.skip_summarization is True
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_custom_threshold_does_not_skip_when_output_below(self):
        """A custom threshold of 100 should NOT skip when output < 100 chars."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl, summarization_threshold=100)
        tc = _make_tool_context()
        await tool.run_async(args={"code": "print('hi')"}, tool_context=tc)
        assert tc.actions.skip_summarization is False
        repl.cleanup()

    def test_default_summarization_threshold_is_5000(self):
        """REPLTool should expose its threshold as _summarization_threshold = 5000."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        assert tool._summarization_threshold == 5000
        repl.cleanup()
