"""Focused tests for submitted-code REPL observability."""

from unittest.mock import MagicMock

import pytest

from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.state import (
    LAST_REPL_RESULT,
    REPL_SUBMITTED_CODE,
    REPL_SUBMITTED_CODE_CHARS,
    REPL_SUBMITTED_CODE_HASH,
    REPL_SUBMITTED_CODE_PREVIEW,
)
from rlm_adk.tools.repl_tool import REPLTool


def _make_tool_context() -> MagicMock:
    ctx = MagicMock()
    ctx.state = {}
    return ctx


class TestSubmittedCodeObservability:
    @pytest.mark.asyncio
    async def test_last_repl_result_includes_submitted_code_metrics(self):
        repl = LocalREPL()
        traces: list = []
        tool = REPLTool(repl=repl, trace_holder=traces)
        tool_context = _make_tool_context()
        code = "print('hello world')"

        try:
            await tool.run_async(args={"code": code}, tool_context=tool_context)
        finally:
            repl.cleanup()

        repl_result = tool_context.state[LAST_REPL_RESULT]
        assert tool_context.state[REPL_SUBMITTED_CODE] == code
        assert tool_context.state[REPL_SUBMITTED_CODE_CHARS] == len(code)
        assert tool_context.state[REPL_SUBMITTED_CODE_PREVIEW] == code
        assert repl_result["submitted_code_chars"] == len(code)
        assert repl_result["submitted_code_hash"] == tool_context.state[REPL_SUBMITTED_CODE_HASH]
        assert repl_result["trace_summary"]["submitted_code_chars"] == len(code)
        assert repl_result["trace_summary"]["submitted_code_hash"] == tool_context.state[REPL_SUBMITTED_CODE_HASH]

    @pytest.mark.asyncio
    async def test_call_limit_rejection_still_persists_submitted_code_metrics(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, max_calls=0)
        tool_context = _make_tool_context()
        code = "print('blocked')"

        try:
            result = await tool.run_async(args={"code": code}, tool_context=tool_context)
        finally:
            repl.cleanup()

        assert "call limit reached" in result["stderr"].lower()
        assert tool_context.state[REPL_SUBMITTED_CODE] == code
        assert tool_context.state[REPL_SUBMITTED_CODE_CHARS] == len(code)
        assert tool_context.state[REPL_SUBMITTED_CODE_PREVIEW] == code
        assert len(tool_context.state[REPL_SUBMITTED_CODE_HASH]) == 64
