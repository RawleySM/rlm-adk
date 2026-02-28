"""Tests for REPLTool -- ADK BaseTool wrapping LocalREPL.

RED/GREEN TDD Phase 2: These tests define the contract for REPLTool
before the implementation exists.
"""

import asyncio

import pytest
from unittest.mock import MagicMock

from rlm_adk.tools.repl_tool import REPLTool
from rlm_adk.repl.local_repl import LocalREPL


def _make_tool_context(state=None):
    """Create a minimal mock ToolContext with a dict-like state."""
    tc = MagicMock()
    tc.state = state if state is not None else {}
    return tc


@pytest.fixture
def repl_tool():
    repl = LocalREPL()
    tool = REPLTool(repl=repl)
    yield tool
    repl.cleanup()


class TestREPLToolDeclaration:
    def test_tool_name_is_execute_code(self, repl_tool):
        decl = repl_tool._get_declaration()
        assert decl.name == "execute_code"

    def test_declaration_has_code_parameter(self, repl_tool):
        decl = repl_tool._get_declaration()
        props = decl.parameters.properties
        assert "code" in props
        # google.genai.types.Schema uses .type (not .type_)
        from google.genai.types import Type
        assert props["code"].type == Type.STRING

    def test_declaration_requires_code(self, repl_tool):
        decl = repl_tool._get_declaration()
        assert "code" in decl.parameters.required


class TestREPLToolSyncExecution:
    @pytest.mark.asyncio
    async def test_simple_print_returns_stdout(self, repl_tool):
        tc = _make_tool_context()
        result = await repl_tool.run_async(args={"code": "print('hello')"}, tool_context=tc)
        assert result["stdout"].strip() == "hello"
        assert result["stderr"] == ""

    @pytest.mark.asyncio
    async def test_syntax_error_returns_stderr(self, repl_tool):
        tc = _make_tool_context()
        result = await repl_tool.run_async(args={"code": "def("}, tool_context=tc)
        assert "SyntaxError" in result["stderr"]

    @pytest.mark.asyncio
    async def test_variable_persistence_across_calls(self, repl_tool):
        tc = _make_tool_context()
        await repl_tool.run_async(args={"code": "x = 42"}, tool_context=tc)
        result = await repl_tool.run_async(args={"code": "print(x)"}, tool_context=tc)
        assert "42" in result["stdout"]

    @pytest.mark.asyncio
    async def test_runtime_error_returns_stderr(self, repl_tool):
        tc = _make_tool_context()
        result = await repl_tool.run_async(args={"code": "1/0"}, tool_context=tc)
        assert "ZeroDivisionError" in result["stderr"]


class TestREPLToolCallLimit:
    @pytest.mark.asyncio
    async def test_call_limit_returns_error_after_threshold(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, max_calls=2)
        tc = _make_tool_context()
        await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        await tool.run_async(args={"code": "x = 2"}, tool_context=tc)
        result = await tool.run_async(args={"code": "x = 3"}, tool_context=tc)
        assert "call limit reached" in result["stderr"].lower()
        assert result["stdout"] == ""
        repl.cleanup()

    @pytest.mark.asyncio
    async def test_call_count_tracked_in_result(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl, max_calls=60)
        tc = _make_tool_context()
        r1 = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        r2 = await tool.run_async(args={"code": "x = 2"}, tool_context=tc)
        assert r1["call_number"] == 1
        assert r2["call_number"] == 2
        repl.cleanup()


class TestREPLToolTraceRecording:
    @pytest.mark.asyncio
    async def test_trace_holder_receives_trace_data(self):
        repl = LocalREPL()
        traces = []
        tool = REPLTool(repl=repl, trace_holder=traces)
        tc = _make_tool_context()
        await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        repl.cleanup()
        assert len(traces) == 1


class TestREPLToolTelemetryFlush:
    @pytest.mark.asyncio
    async def test_flush_fn_writes_accumulators_to_tool_context_state(self):
        repl = LocalREPL()
        flush_calls = []

        def fake_flush():
            flush_calls.append(1)
            return {"worker_dispatch_count": 5, "obs:worker_dispatch_latency_ms": [12.3]}

        tool = REPLTool(repl=repl, flush_fn=fake_flush)
        tc = _make_tool_context()
        await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        repl.cleanup()
        assert len(flush_calls) == 1
        assert tc.state["worker_dispatch_count"] == 5
        assert tc.state["obs:worker_dispatch_latency_ms"] == [12.3]

    @pytest.mark.asyncio
    async def test_no_flush_fn_is_noop(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl)  # no flush_fn
        tc = _make_tool_context()
        result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        repl.cleanup()
        assert result["stdout"] == ""  # no crash


class TestREPLToolExceptionSafety:
    @pytest.mark.asyncio
    async def test_cancelled_error_returns_stderr(self):
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        # Patch execute_code to raise CancelledError
        def raise_cancelled(code, **kw):
            raise asyncio.CancelledError()
        repl.execute_code = raise_cancelled
        tc = _make_tool_context()
        result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)
        assert "CancelledError" in result["stderr"]
        repl.cleanup()
