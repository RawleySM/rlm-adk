"""Tests for OG-01: REPL stdout preview in state."""
import asyncio
from unittest.mock import MagicMock
import pytest
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.state import LAST_REPL_RESULT
from rlm_adk.tools.repl_tool import REPLTool


def _make_tool_context():
    ctx = MagicMock()
    ctx.state = {}
    return ctx


class TestStdoutPreview:
    @pytest.mark.asyncio
    async def test_stdout_preview_present_on_success(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, trace_holder=[])
        ctx = _make_tool_context()
        try:
            await tool.run_async(args={"code": "print('hello world')"}, tool_context=ctx)
        finally:
            repl.cleanup()
        result = ctx.state[LAST_REPL_RESULT]
        assert "stdout_preview" in result
        assert "hello world" in result["stdout_preview"]

    @pytest.mark.asyncio
    async def test_stdout_preview_bounded_at_500_chars(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, trace_holder=[])
        ctx = _make_tool_context()
        try:
            await tool.run_async(args={"code": "print('x' * 1000)"}, tool_context=ctx)
        finally:
            repl.cleanup()
        result = ctx.state[LAST_REPL_RESULT]
        assert len(result["stdout_preview"]) <= 500

    @pytest.mark.asyncio
    async def test_stdout_preview_empty_on_exception(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, trace_holder=[])
        ctx = _make_tool_context()
        try:
            await tool.run_async(args={"code": "raise ValueError('boom')"}, tool_context=ctx)
        finally:
            repl.cleanup()
        result = ctx.state[LAST_REPL_RESULT]
        assert "stdout_preview" in result
        # Exception path has no stdout
        assert result["stdout_preview"] == ""

    @pytest.mark.asyncio
    async def test_no_stdout_preview_on_call_limit(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, max_calls=0, trace_holder=[])
        ctx = _make_tool_context()
        try:
            await tool.run_async(args={"code": "print('blocked')"}, tool_context=ctx)
        finally:
            repl.cleanup()
        # Call limit path does not write LAST_REPL_RESULT
        assert LAST_REPL_RESULT not in ctx.state
