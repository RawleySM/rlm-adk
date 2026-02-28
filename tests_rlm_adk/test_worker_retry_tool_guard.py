"""Tests for tool-name guard on WorkerRetryPlugin (W2/W9 fixes).

Ensures that WorkerRetryPlugin and the callbacks from make_worker_tool_callbacks
only inspect/intercept results from the set_model_response tool and ignore
results from other tools (especially execute_code / REPLTool).

Covers:
- _SET_MODEL_RESPONSE_TOOL_NAME constant existence and value
- extract_error_from_result ignores non-set_model_response tools
- extract_error_from_result catches set_model_response validation errors
- on_tool_error_cb ignores execute_code errors (returns None)
- on_tool_error_cb handles set_model_response errors (returns reflection)
"""

from unittest.mock import MagicMock

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_tool(name: str) -> MagicMock:
    """Create a mock tool with a given name."""
    tool = MagicMock()
    tool.name = name
    return tool


def _make_tool_context(invocation_id: str = "test-inv") -> MagicMock:
    """Create a mock ToolContext with minimal fields."""
    tc = MagicMock()
    tc.invocation_id = invocation_id
    tc.state = {}
    return tc


# ── Constant Tests ───────────────────────────────────────────────────────


class TestSetModelResponseToolNameConstant:
    """Verify the _SET_MODEL_RESPONSE_TOOL_NAME constant."""

    def test_constant_exists(self):
        from rlm_adk.callbacks.worker_retry import _SET_MODEL_RESPONSE_TOOL_NAME

        assert isinstance(_SET_MODEL_RESPONSE_TOOL_NAME, str)

    def test_constant_matches_expected_name(self):
        from rlm_adk.callbacks.worker_retry import _SET_MODEL_RESPONSE_TOOL_NAME

        assert _SET_MODEL_RESPONSE_TOOL_NAME == "set_model_response"


# ── Plugin extract_error_from_result Tests ───────────────────────────────


class TestWorkerRetryPluginToolNameGuard:
    """WorkerRetryPlugin.extract_error_from_result tool-name guard."""

    @pytest.mark.asyncio
    async def test_extract_error_ignores_execute_code_tool(self):
        """extract_error_from_result should return None for execute_code tool
        (the REPLTool), even if tool_args contain empty strings."""
        from rlm_adk.callbacks.worker_retry import WorkerRetryPlugin

        plugin = WorkerRetryPlugin(max_retries=2)
        tool = _make_tool("execute_code")

        error = await plugin.extract_error_from_result(
            tool=tool,
            tool_args={"code": ""},  # empty -- would trigger for set_model_response
            tool_context=_make_tool_context(),
            result={"output": ""},
        )
        assert error is None

    @pytest.mark.asyncio
    async def test_extract_error_ignores_arbitrary_tool(self):
        """extract_error_from_result should return None for any non-set_model_response tool."""
        from rlm_adk.callbacks.worker_retry import WorkerRetryPlugin

        plugin = WorkerRetryPlugin(max_retries=2)
        tool = _make_tool("google_search")

        error = await plugin.extract_error_from_result(
            tool=tool,
            tool_args={"query": ""},
            tool_context=_make_tool_context(),
            result={"results": []},
        )
        assert error is None

    @pytest.mark.asyncio
    async def test_extract_error_catches_set_model_response_empty_value(self):
        """extract_error_from_result should detect empty values for set_model_response."""
        from rlm_adk.callbacks.worker_retry import WorkerRetryPlugin

        plugin = WorkerRetryPlugin(max_retries=2)
        tool = _make_tool("set_model_response")

        error = await plugin.extract_error_from_result(
            tool=tool,
            tool_args={"summary": "", "title": "ok"},
            tool_context=_make_tool_context(),
            result={"summary": "", "title": "ok"},
        )
        assert error is not None
        assert "empty" in error["details"].lower()

    @pytest.mark.asyncio
    async def test_extract_error_passes_valid_set_model_response(self):
        """extract_error_from_result should return None for valid set_model_response."""
        from rlm_adk.callbacks.worker_retry import WorkerRetryPlugin

        plugin = WorkerRetryPlugin(max_retries=2)
        tool = _make_tool("set_model_response")

        error = await plugin.extract_error_from_result(
            tool=tool,
            tool_args={"summary": "All good", "title": "Title"},
            tool_context=_make_tool_context(),
            result={"summary": "All good", "title": "Title"},
        )
        assert error is None


# ── Error Callback Tool-Name Guard Tests ─────────────────────────────────


class TestWorkerErrorCallbackToolNameGuard:
    """on_tool_error_cb from make_worker_tool_callbacks: tool-name guard."""

    @pytest.mark.asyncio
    async def test_error_cb_ignores_execute_code_errors(self):
        """Error callback should return None for execute_code tool errors,
        allowing them to propagate normally instead of being captured by retry."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        _, error_cb = make_worker_tool_callbacks(max_retries=2)
        tool = _make_tool("execute_code")
        tc = _make_tool_context()

        result = await error_cb(tool, {"code": "bad"}, tc, RuntimeError("exec failed"))
        assert result is None

    @pytest.mark.asyncio
    async def test_error_cb_ignores_arbitrary_tool_errors(self):
        """Error callback should return None for any non-set_model_response tool."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        _, error_cb = make_worker_tool_callbacks(max_retries=2)
        tool = _make_tool("google_search")
        tc = _make_tool_context()

        result = await error_cb(tool, {"q": "test"}, tc, ValueError("bad search"))
        assert result is None

    @pytest.mark.asyncio
    async def test_error_cb_handles_set_model_response_errors(self):
        """Error callback should return reflection guidance for set_model_response errors."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        _, error_cb = make_worker_tool_callbacks(max_retries=2)
        tool = _make_tool("set_model_response")
        tc = _make_tool_context()

        result = await error_cb(tool, {"bad": "data"}, tc, ValueError("schema error"))
        assert result is not None
        assert "reflection_guidance" in result

    @pytest.mark.asyncio
    async def test_after_cb_ignores_execute_code_results(self):
        """After-tool callback should not store _structured_result for execute_code tool."""
        from rlm_adk.callbacks.worker_retry import make_worker_tool_callbacks

        after_cb, _ = make_worker_tool_callbacks(max_retries=2)
        tool = _make_tool("execute_code")
        agent = MagicMock()
        agent._structured_result = None
        tc = _make_tool_context()
        tc._invocation_context.agent = agent

        await after_cb(tool, {"code": "print(1)"}, tc, {"output": "1"})
        # Should NOT have set _structured_result
        assert agent._structured_result is None
