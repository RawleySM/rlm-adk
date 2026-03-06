"""Tests for OG-04: no negative wall_time_ms on failed REPL runs."""
import time
from unittest.mock import MagicMock

import pytest

from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.repl.trace import REPLTrace
from rlm_adk.state import LAST_REPL_RESULT
from rlm_adk.tools.repl_tool import REPLTool


def _make_tool_context():
    ctx = MagicMock()
    ctx.state = {}
    return ctx


class TestREPLTraceWallTime:
    def test_summary_non_negative_when_end_time_zero(self):
        """end_time=0 with start_time>0 should yield wall_time_ms >= 0."""
        trace = REPLTrace()
        trace.start_time = time.perf_counter()
        # end_time stays at default 0.0
        summary = trace.summary()
        assert summary["wall_time_ms"] >= 0, f"Got negative wall_time_ms: {summary['wall_time_ms']}"

    def test_to_dict_non_negative_when_end_time_zero(self):
        trace = REPLTrace()
        trace.start_time = time.perf_counter()
        d = trace.to_dict()
        assert d["wall_time_ms"] >= 0, f"Got negative wall_time_ms: {d['wall_time_ms']}"

    def test_summary_non_negative_when_end_before_start(self):
        """Pathological case: end_time < start_time."""
        trace = REPLTrace()
        trace.start_time = 100.0
        trace.end_time = 50.0
        summary = trace.summary()
        assert summary["wall_time_ms"] >= 0

    def test_summary_zero_when_no_start_time(self):
        """No timing at all should give 0."""
        trace = REPLTrace()
        summary = trace.summary()
        assert summary["wall_time_ms"] == 0


class TestREPLToolErrorPathTiming:
    @pytest.mark.asyncio
    async def test_exception_path_has_non_negative_wall_time(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, trace_holder=[])
        ctx = _make_tool_context()
        try:
            await tool.run_async(
                args={"code": "raise ValueError('boom')"},
                tool_context=ctx,
            )
        finally:
            repl.cleanup()
        result = ctx.state.get(LAST_REPL_RESULT)
        assert result is not None
        if "trace_summary" in result:
            assert result["trace_summary"]["wall_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_successful_run_has_positive_wall_time(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, trace_holder=[])
        ctx = _make_tool_context()
        try:
            await tool.run_async(
                args={"code": "x = 42"},
                tool_context=ctx,
            )
        finally:
            repl.cleanup()
        result = ctx.state[LAST_REPL_RESULT]
        assert "trace_summary" in result
        assert result["trace_summary"]["wall_time_ms"] >= 0
