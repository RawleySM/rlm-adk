"""PS-002: Observability plugin behavior.

- Must track total and per-model token usage/call counts.
- Must record total execution timing and tool invocation summary.
- Must not block execution on logging failures.
"""

import time
from unittest.mock import MagicMock

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.plugins.observability import ObservabilityPlugin
from rlm_adk.state import (
    INVOCATION_START_TIME,
    OBS_TOOL_INVOCATION_SUMMARY,
    OBS_TOTAL_CALLS,
    OBS_TOTAL_INPUT_TOKENS,
    OBS_TOTAL_OUTPUT_TOKENS,
    obs_model_usage_key,
)


def _make_callback_context(state: dict | None = None):
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    return ctx


def _make_invocation_context(state: dict | None = None):
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _make_llm_response(
    text: str = "hello",
    input_tokens: int = 10,
    output_tokens: int = 5,
    model_version: str = "test-model",
) -> LlmResponse:
    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        ),
    )
    usage = MagicMock()
    usage.prompt_token_count = input_tokens
    usage.candidates_token_count = output_tokens
    response.usage_metadata = usage
    response.model_version = model_version
    return response


class TestObservabilityCallCounting:
    """PS-002: Track total call counts."""

    @pytest.mark.asyncio
    async def test_increments_total_calls(self):
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_callback_context(state)
        response = _make_llm_response()

        await plugin.after_model_callback(callback_context=ctx, llm_response=response)

        assert state[OBS_TOTAL_CALLS] == 1

    @pytest.mark.asyncio
    async def test_multiple_calls_accumulate(self):
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_callback_context(state)

        for _ in range(3):
            await plugin.after_model_callback(
                callback_context=ctx, llm_response=_make_llm_response()
            )

        assert state[OBS_TOTAL_CALLS] == 3


class TestObservabilityTokenTracking:
    """PS-002: Track total and per-model token usage."""

    @pytest.mark.asyncio
    async def test_tracks_total_tokens(self):
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_callback_context(state)

        await plugin.after_model_callback(
            callback_context=ctx,
            llm_response=_make_llm_response(input_tokens=100, output_tokens=50),
        )

        assert state[OBS_TOTAL_INPUT_TOKENS] == 100
        assert state[OBS_TOTAL_OUTPUT_TOKENS] == 50

    @pytest.mark.asyncio
    async def test_accumulates_tokens(self):
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_callback_context(state)

        await plugin.after_model_callback(
            callback_context=ctx,
            llm_response=_make_llm_response(input_tokens=100, output_tokens=50),
        )
        await plugin.after_model_callback(
            callback_context=ctx,
            llm_response=_make_llm_response(input_tokens=200, output_tokens=100),
        )

        assert state[OBS_TOTAL_INPUT_TOKENS] == 300
        assert state[OBS_TOTAL_OUTPUT_TOKENS] == 150

    @pytest.mark.asyncio
    async def test_per_model_tracking(self):
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_callback_context(state)

        await plugin.after_model_callback(
            callback_context=ctx,
            llm_response=_make_llm_response(
                input_tokens=10, output_tokens=5, model_version="model-a"
            ),
        )
        await plugin.after_model_callback(
            callback_context=ctx,
            llm_response=_make_llm_response(
                input_tokens=20, output_tokens=10, model_version="model-b"
            ),
        )

        key_a = obs_model_usage_key("model-a")
        key_b = obs_model_usage_key("model-b")
        assert state[key_a]["calls"] == 1
        assert state[key_a]["input_tokens"] == 10
        assert state[key_b]["calls"] == 1
        assert state[key_b]["input_tokens"] == 20


class TestObservabilityToolTracking:
    """PS-002: Record tool invocation summary."""

    @pytest.mark.asyncio
    async def test_tracks_tool_invocations(self):
        plugin = ObservabilityPlugin()
        state = {}

        tool = MagicMock()
        tool.name = "code_exec"
        tool_ctx = MagicMock()
        tool_ctx.state = state

        await plugin.before_tool_callback(tool=tool, tool_args={}, tool_context=tool_ctx)
        await plugin.before_tool_callback(tool=tool, tool_args={}, tool_context=tool_ctx)

        assert state[OBS_TOOL_INVOCATION_SUMMARY]["code_exec"] == 2


class TestObservabilityTiming:
    """PS-002: Record total execution timing."""

    @pytest.mark.asyncio
    async def test_records_execution_time(self):
        plugin = ObservabilityPlugin()
        state = {INVOCATION_START_TIME: time.time() - 1.0}
        inv_ctx = _make_invocation_context(state)

        await plugin.after_run_callback(invocation_context=inv_ctx)

        # AR-CRIT-001: execution time stored on plugin instance, not session state
        assert plugin._total_execution_time is not None
        assert plugin._total_execution_time >= 0.9

    @pytest.mark.asyncio
    async def test_before_agent_sets_start_time(self):
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_callback_context(state)
        agent = MagicMock()

        await plugin.before_agent_callback(agent=agent, callback_context=ctx)

        assert INVOCATION_START_TIME in state


class TestObservabilityNonBlocking:
    """PS-002: Must not block execution on logging failures."""

    @pytest.mark.asyncio
    async def test_after_model_survives_bad_usage(self):
        """Plugin should not raise even if usage_metadata is malformed."""
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_callback_context(state)

        response = LlmResponse(content=None)
        response.usage_metadata = None
        response.model_version = None

        # Should not raise
        await plugin.after_model_callback(callback_context=ctx, llm_response=response)
        assert state[OBS_TOTAL_CALLS] == 1

    @pytest.mark.asyncio
    async def test_before_agent_survives_exception(self):
        plugin = ObservabilityPlugin()
        ctx = MagicMock()
        ctx.state = MagicMock(side_effect=RuntimeError("bad state"))
        agent = MagicMock()

        # Should not raise
        await plugin.before_agent_callback(agent=agent, callback_context=ctx)
