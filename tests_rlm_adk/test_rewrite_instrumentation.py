"""Tests for AST rewrite instrumentation and REPL observability keys.

TDD RED phase: Tests for:
1. AST rewrite timing in REPLTool (OBS_REWRITE_COUNT, OBS_REWRITE_TOTAL_MS)
2. Reasoning retry count persistence (OBS_REASONING_RETRY_COUNT)
3. BUG-13 stats persistence in flush_fn
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.state import (
    OBS_BUG13_SUPPRESS_COUNT,
    OBS_REWRITE_COUNT,
    OBS_REWRITE_FAILURE_CATEGORIES,
    OBS_REWRITE_FAILURE_COUNT,
    OBS_REWRITE_TOTAL_MS,
    OBS_REASONING_RETRY_COUNT,
    REPL_SUBMITTED_CODE_CHARS,
    REPL_SUBMITTED_CODE_HASH,
    REPL_SUBMITTED_CODE_PREVIEW,
)
from rlm_adk.tools.repl_tool import REPLTool


def _make_tool_context(state=None):
    tc = MagicMock()
    tc.state = state if state is not None else {}
    return tc


# ---------------------------------------------------------------------------
# 1. AST rewrite instrumentation in REPLTool
# ---------------------------------------------------------------------------

class TestRewriteInstrumentation:
    """OBS_REWRITE_COUNT and OBS_REWRITE_TOTAL_MS should be written to
    tool_context.state when code contains llm_query calls that trigger rewrite."""

    @pytest.mark.asyncio
    async def test_no_rewrite_for_plain_code(self):
        """Plain code (no llm_query) should NOT increment rewrite count."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        tc = _make_tool_context()
        await tool.run_async(args={"code": "x = 1 + 2"}, tool_context=tc)
        repl.cleanup()
        # No rewrite keys should be written for plain code
        assert tc.state.get(OBS_REWRITE_COUNT, 0) == 0

    @pytest.mark.asyncio
    async def test_rewrite_count_increments_for_llm_query_code(self):
        """Code with llm_query() should increment rewrite count."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        tc = _make_tool_context()

        # Patch has_llm_calls to return True and rewrite_for_async to return
        # a valid AST that won't actually call anything
        with patch("rlm_adk.tools.repl_tool.has_llm_calls", return_value=True), \
             patch("rlm_adk.tools.repl_tool.rewrite_for_async") as mock_rewrite:
            import ast
            # Return a simple AST that defines _repl_exec as an async no-op
            tree = ast.parse(
                "async def _repl_exec():\n    pass",
                mode="exec",
            )
            ast.fix_missing_locations(tree)
            mock_rewrite.return_value = tree

            # Patch execute_code_async to return a simple result
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_result.locals = {}
            async def _fake_exec(*a, **kw):
                return mock_result
            repl.execute_code_async = _fake_exec

            await tool.run_async(
                args={"code": "result = llm_query('hello')"},
                tool_context=tc,
            )
        repl.cleanup()
        assert tc.state.get(OBS_REWRITE_COUNT) == 1

    @pytest.mark.asyncio
    async def test_rewrite_total_ms_is_positive(self):
        """OBS_REWRITE_TOTAL_MS should be a positive float after rewrite."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        tc = _make_tool_context()

        with patch("rlm_adk.tools.repl_tool.has_llm_calls", return_value=True), \
             patch("rlm_adk.tools.repl_tool.rewrite_for_async") as mock_rewrite:
            import ast
            tree = ast.parse(
                "async def _repl_exec():\n    pass",
                mode="exec",
            )
            ast.fix_missing_locations(tree)
            mock_rewrite.return_value = tree

            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_result.locals = {}
            async def _fake_exec(*a, **kw):
                return mock_result
            repl.execute_code_async = _fake_exec

            await tool.run_async(
                args={"code": "result = llm_query('hello')"},
                tool_context=tc,
            )
        repl.cleanup()
        ms = tc.state.get(OBS_REWRITE_TOTAL_MS)
        assert ms is not None
        assert isinstance(ms, float)
        assert ms >= 0.0

    @pytest.mark.asyncio
    async def test_rewrite_counts_written_on_execution_error(self):
        """OBS_REWRITE_COUNT should be written even when execution raises."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        tc = _make_tool_context()

        with patch("rlm_adk.tools.repl_tool.has_llm_calls", return_value=True), \
             patch("rlm_adk.tools.repl_tool.rewrite_for_async") as mock_rewrite:
            import ast
            tree = ast.parse(
                "async def _repl_exec():\n    pass",
                mode="exec",
            )
            ast.fix_missing_locations(tree)
            mock_rewrite.return_value = tree

            # execute_code_async raises RuntimeError after rewrite
            async def _exploding_exec(*a, **kw):
                raise RuntimeError("boom")
            repl.execute_code_async = _exploding_exec

            result = await tool.run_async(
                args={"code": "result = llm_query('hello')\nraise RuntimeError('boom')"},
                tool_context=tc,
            )
        repl.cleanup()
        # Rewrite happened before execution, so count must be recorded
        assert tc.state.get(OBS_REWRITE_COUNT) == 1
        assert tc.state.get(OBS_REWRITE_TOTAL_MS) is not None
        assert tc.state[OBS_REWRITE_TOTAL_MS] >= 0.0
        # Confirm the error was still returned
        assert "RuntimeError" in result["stderr"]

    @pytest.mark.asyncio
    async def test_rewrite_count_accumulates_across_calls(self):
        """Multiple rewrite-triggering calls should accumulate."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl)

        with patch("rlm_adk.tools.repl_tool.has_llm_calls", return_value=True), \
             patch("rlm_adk.tools.repl_tool.rewrite_for_async") as mock_rewrite:
            import ast
            tree = ast.parse(
                "async def _repl_exec():\n    pass",
                mode="exec",
            )
            ast.fix_missing_locations(tree)
            mock_rewrite.return_value = tree

            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_result.locals = {}
            async def _fake_exec(*a, **kw):
                return mock_result
            repl.execute_code_async = _fake_exec

            tc1 = _make_tool_context()
            await tool.run_async(args={"code": "a = llm_query('q1')"}, tool_context=tc1)
            tc2 = _make_tool_context()
            await tool.run_async(args={"code": "b = llm_query('q2')"}, tool_context=tc2)

        repl.cleanup()
        # Second call should show accumulated count = 2
        assert tc2.state.get(OBS_REWRITE_COUNT) == 2

    @pytest.mark.asyncio
    async def test_rewrite_failure_records_count_and_category(self):
        """Rewrite failures should be counted separately from runtime failures."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        tc = _make_tool_context()

        with patch("rlm_adk.tools.repl_tool.has_llm_calls", return_value=True), \
             patch("rlm_adk.tools.repl_tool.rewrite_for_async", side_effect=SyntaxError("bad rewrite")):
            result = await tool.run_async(
                args={"code": "result = llm_query('hello')"},
                tool_context=tc,
            )

        repl.cleanup()
        assert "SyntaxError" in result["stderr"]
        assert tc.state[OBS_REWRITE_FAILURE_COUNT] == 1
        assert tc.state[OBS_REWRITE_FAILURE_CATEGORIES]["SyntaxError"] == 1
        assert tc.state.get(OBS_REWRITE_COUNT, 0) == 0

    @pytest.mark.asyncio
    async def test_submitted_code_metrics_written_before_execution(self):
        """Submitted-code observability should be persisted even when execution fails."""
        repl = LocalREPL()
        tool = REPLTool(repl=repl)
        tc = _make_tool_context()
        code = "result = llm_query('hello')"

        with patch("rlm_adk.tools.repl_tool.has_llm_calls", return_value=True), \
             patch("rlm_adk.tools.repl_tool.rewrite_for_async", side_effect=RuntimeError("rewrite boom")):
            await tool.run_async(args={"code": code}, tool_context=tc)

        repl.cleanup()
        assert tc.state[REPL_SUBMITTED_CODE_CHARS] == len(code)
        assert tc.state[REPL_SUBMITTED_CODE_PREVIEW] == code
        assert len(tc.state[REPL_SUBMITTED_CODE_HASH]) == 64


# ---------------------------------------------------------------------------
# 2. Reasoning retry count (orchestrator)
# ---------------------------------------------------------------------------

class TestReasoningRetryCount:
    """OBS_REASONING_RETRY_COUNT should be yielded as state_delta when retries occur."""

    @pytest.mark.asyncio
    async def test_state_key_constant_exists(self):
        """The OBS_REASONING_RETRY_COUNT constant should be defined."""
        assert OBS_REASONING_RETRY_COUNT == "obs:reasoning_retry_count"


# ---------------------------------------------------------------------------
# 3. BUG-13 stats persistence in flush_fn
# ---------------------------------------------------------------------------

class TestBug13StatsPersistence:
    """flush_fn should include _bug13_stats['suppress_count'] when > 0."""

    def test_flush_fn_includes_bug13_when_positive(self):
        """When _bug13_stats has suppress_count > 0, flush_fn should include it."""
        from rlm_adk.dispatch import create_dispatch_closures, DispatchConfig
        from rlm_adk.callbacks.worker_retry import _bug13_stats

        # Save and set bug13 stats
        original = _bug13_stats["suppress_count"]
        _bug13_stats["suppress_count"] = 3

        try:
            config = DispatchConfig(default_model="test-model")
            ctx = MagicMock()
            ctx.session = MagicMock()
            ctx.session.state = {}
            ctx.invocation_id = "test-inv"

            _, _, flush_fn = create_dispatch_closures(config, ctx)
            delta = flush_fn()
            assert delta.get(OBS_BUG13_SUPPRESS_COUNT) == 3
        finally:
            _bug13_stats["suppress_count"] = original

    def test_flush_fn_omits_bug13_when_zero(self):
        """When _bug13_stats has suppress_count == 0, flush_fn should omit it."""
        from rlm_adk.dispatch import create_dispatch_closures, DispatchConfig
        from rlm_adk.callbacks.worker_retry import _bug13_stats

        original = _bug13_stats["suppress_count"]
        _bug13_stats["suppress_count"] = 0

        try:
            config = DispatchConfig(default_model="test-model")
            ctx = MagicMock()
            ctx.session = MagicMock()
            ctx.session.state = {}
            ctx.invocation_id = "test-inv"

            _, _, flush_fn = create_dispatch_closures(config, ctx)
            delta = flush_fn()
            assert OBS_BUG13_SUPPRESS_COUNT not in delta
        finally:
            _bug13_stats["suppress_count"] = original
