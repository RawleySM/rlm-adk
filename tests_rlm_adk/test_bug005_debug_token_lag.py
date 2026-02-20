"""Bug 005: per_agent_tokens in debug logging must reflect current call, not stale state.

The DebugLoggingPlugin.after_model_callback reads REASONING_INPUT_TOKENS and
REASONING_OUTPUT_TOKENS from state to populate per_agent_tokens. Because the
agent's reasoning_after_model callback has not yet run when the plugin fires,
these values are stale (from the previous iteration).

The fix: read token counts directly from llm_response.usage_metadata, matching
what ObservabilityPlugin already does correctly.
"""

from unittest.mock import MagicMock

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.plugins.debug_logging import DebugLoggingPlugin
from rlm_adk.state import (
    REASONING_INPUT_TOKENS,
    REASONING_OUTPUT_TOKENS,
    WORKER_INPUT_TOKENS,
    WORKER_OUTPUT_TOKENS,
)


def _make_callback_context(state: dict | None = None):
    """Build a mock CallbackContext with .state dict."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    return ctx


def _make_llm_response(
    text: str = "hello",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> LlmResponse:
    """Build an LlmResponse with known usage_metadata values."""
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
    return response


class TestPerAgentTokensReflectsCurrentCall:
    """Bug 005: per_agent_tokens must match the CURRENT call's usage_metadata."""

    @pytest.mark.asyncio
    async def test_reasoning_tokens_match_current_response(self):
        """per_agent_tokens should reflect the current llm_response, not stale state.

        Simulates the bug scenario: state has stale values from a previous call
        (input=50, output=25) while the current response has (input=100, output=50).
        The per_agent_tokens entry must show the current values.
        """
        plugin = DebugLoggingPlugin()

        # State has STALE values from a previous iteration
        state = {
            REASONING_INPUT_TOKENS: 50,   # stale: previous call's value
            REASONING_OUTPUT_TOKENS: 25,  # stale: previous call's value
        }
        ctx = _make_callback_context(state)

        # Current response has DIFFERENT (correct) values
        response = _make_llm_response(input_tokens=100, output_tokens=50)

        await plugin.after_model_callback(
            callback_context=ctx, llm_response=response
        )

        # Find the after_model trace entry
        after_model_entries = [
            t for t in plugin._traces if t["event"] == "after_model"
        ]
        assert len(after_model_entries) == 1
        entry = after_model_entries[0]

        # per_agent_tokens MUST reflect the current call, not stale state
        assert "per_agent_tokens" in entry
        assert entry["per_agent_tokens"]["reasoning_input_tokens"] == 100
        assert entry["per_agent_tokens"]["reasoning_output_tokens"] == 50

    @pytest.mark.asyncio
    async def test_worker_tokens_match_current_response(self):
        """Same lag bug applies to worker tokens."""
        plugin = DebugLoggingPlugin()

        # State has STALE worker token values
        state = {
            WORKER_INPUT_TOKENS: [30],   # stale (list per bug-002 fix)
            WORKER_OUTPUT_TOKENS: [15],  # stale (list per bug-002 fix)
        }
        ctx = _make_callback_context(state)

        # Current response has different values
        response = _make_llm_response(input_tokens=200, output_tokens=80)

        await plugin.after_model_callback(
            callback_context=ctx, llm_response=response
        )

        after_model_entries = [
            t for t in plugin._traces if t["event"] == "after_model"
        ]
        assert len(after_model_entries) == 1
        entry = after_model_entries[0]

        assert "per_agent_tokens" in entry
        assert entry["per_agent_tokens"]["worker_input_tokens"] == 200
        assert entry["per_agent_tokens"]["worker_output_tokens"] == 80

    @pytest.mark.asyncio
    async def test_per_agent_tokens_matches_usage_field(self):
        """per_agent_tokens and usage must always agree on token counts."""
        plugin = DebugLoggingPlugin()

        # Stale state to trigger the mismatch
        state = {
            REASONING_INPUT_TOKENS: 999,
            REASONING_OUTPUT_TOKENS: 888,
        }
        ctx = _make_callback_context(state)
        response = _make_llm_response(input_tokens=5000, output_tokens=1200)

        await plugin.after_model_callback(
            callback_context=ctx, llm_response=response
        )

        entry = [t for t in plugin._traces if t["event"] == "after_model"][0]

        # usage field comes from llm_response.usage_metadata (always correct)
        assert entry["usage"]["prompt_tokens"] == 5000
        assert entry["usage"]["candidates_tokens"] == 1200

        # per_agent_tokens MUST agree with usage
        assert entry["per_agent_tokens"]["reasoning_input_tokens"] == 5000
        assert entry["per_agent_tokens"]["reasoning_output_tokens"] == 1200

    @pytest.mark.asyncio
    async def test_no_usage_metadata_no_per_agent_tokens(self):
        """When there is no usage_metadata, per_agent_tokens should be empty or absent."""
        plugin = DebugLoggingPlugin()

        # State has stale tokens but response has no usage_metadata
        state = {
            REASONING_INPUT_TOKENS: 999,
            REASONING_OUTPUT_TOKENS: 888,
        }
        ctx = _make_callback_context(state)
        response = LlmResponse(content=None)
        response.usage_metadata = None

        await plugin.after_model_callback(
            callback_context=ctx, llm_response=response
        )

        entry = [t for t in plugin._traces if t["event"] == "after_model"][0]

        # Should NOT have per_agent_tokens populated from stale state
        # when there is no current usage_metadata to source from
        if "per_agent_tokens" in entry:
            # If present, values must not be the stale ones
            pat = entry["per_agent_tokens"]
            for val in pat.values():
                assert val != 999
                assert val != 888
