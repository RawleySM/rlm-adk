"""AR-HIGH-002/004: Depth guard and model error handling.

AR-HIGH-004: Depth is invocation-level. Depth guard must block calls above
max depth and record block state.

AR-HIGH-002: Model errors (rate limits/auth/timeouts/other) must be surfaced
via structured fallback behavior in plugin callbacks.
"""

from unittest.mock import MagicMock

import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from rlm_adk.plugins.depth_guard import DepthGuardPlugin
from rlm_adk.state import APP_MAX_DEPTH, TEMP_CURRENT_DEPTH, TEMP_DEPTH_GUARD_BLOCKED


def _make_callback_context(state: dict | None = None):
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    return ctx


def _make_request(text: str = "hello") -> LlmRequest:
    return LlmRequest(
        model="test-model",
        contents=[
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=text)],
            )
        ],
    )


# ── AR-HIGH-004 Depth Semantics ──────────────────────────────────────────


class TestDepthGuardBlocking:
    """Depth guard blocks model calls that exceed max_depth."""

    @pytest.mark.asyncio
    async def test_allows_within_depth(self):
        plugin = DepthGuardPlugin()
        state = {TEMP_CURRENT_DEPTH: 1, APP_MAX_DEPTH: 2}
        ctx = _make_callback_context(state)

        result = await plugin.before_model_callback(
            callback_context=ctx, llm_request=_make_request()
        )

        assert result is None  # Allowed to proceed

    @pytest.mark.asyncio
    async def test_allows_at_exact_depth(self):
        plugin = DepthGuardPlugin()
        state = {TEMP_CURRENT_DEPTH: 2, APP_MAX_DEPTH: 2}
        ctx = _make_callback_context(state)

        result = await plugin.before_model_callback(
            callback_context=ctx, llm_request=_make_request()
        )

        assert result is None  # depth == max is allowed

    @pytest.mark.asyncio
    async def test_blocks_above_max_depth(self):
        plugin = DepthGuardPlugin()
        state = {TEMP_CURRENT_DEPTH: 3, APP_MAX_DEPTH: 2}
        ctx = _make_callback_context(state)

        result = await plugin.before_model_callback(
            callback_context=ctx, llm_request=_make_request()
        )

        assert result is not None  # Short-circuited
        assert state[TEMP_DEPTH_GUARD_BLOCKED] is True
        assert (
            "exceeded" in result.content.parts[0].text.lower()
            or "depth" in result.content.parts[0].text.lower()
        )

    @pytest.mark.asyncio
    async def test_default_max_depth_is_1(self):
        """When APP_MAX_DEPTH is not set, default is 1."""
        plugin = DepthGuardPlugin()
        state = {TEMP_CURRENT_DEPTH: 2}
        ctx = _make_callback_context(state)

        result = await plugin.before_model_callback(
            callback_context=ctx, llm_request=_make_request()
        )

        assert result is not None  # Blocked at depth 2 with default max=1

    @pytest.mark.asyncio
    async def test_default_depth_is_0(self):
        """When TEMP_CURRENT_DEPTH is not set, default is 0."""
        plugin = DepthGuardPlugin()
        state = {APP_MAX_DEPTH: 1}
        ctx = _make_callback_context(state)

        result = await plugin.before_model_callback(
            callback_context=ctx, llm_request=_make_request()
        )

        assert result is None  # depth 0 <= max 1


# ── AR-HIGH-002 Model Error Handling ─────────────────────────────────────


class TestModelErrorHandling:
    """Model errors surfaced via structured fallback response."""

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        plugin = DepthGuardPlugin()
        state = {}
        ctx = _make_callback_context(state)
        error = Exception("rate_limit exceeded (429)")

        result = await plugin.on_model_error_callback(
            callback_context=ctx,
            llm_request=_make_request(),
            error=error,
        )

        assert result is not None
        assert "rate limit" in result.content.parts[0].text.lower()

    @pytest.mark.asyncio
    async def test_auth_error(self):
        plugin = DepthGuardPlugin()
        state = {}
        ctx = _make_callback_context(state)
        error = Exception("authentication failed (401)")

        result = await plugin.on_model_error_callback(
            callback_context=ctx,
            llm_request=_make_request(),
            error=error,
        )

        assert result is not None
        assert "auth" in result.content.parts[0].text.lower()

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        plugin = DepthGuardPlugin()
        state = {}
        ctx = _make_callback_context(state)
        error = Exception("Request timeout (504)")

        result = await plugin.on_model_error_callback(
            callback_context=ctx,
            llm_request=_make_request(),
            error=error,
        )

        assert result is not None
        assert "timeout" in result.content.parts[0].text.lower()

    @pytest.mark.asyncio
    async def test_generic_error(self):
        plugin = DepthGuardPlugin()
        state = {}
        ctx = _make_callback_context(state)
        error = ValueError("Something unexpected")

        result = await plugin.on_model_error_callback(
            callback_context=ctx,
            llm_request=_make_request(),
            error=error,
        )

        assert result is not None
        assert "ValueError" in result.content.parts[0].text

    @pytest.mark.asyncio
    async def test_error_response_is_llm_response(self):
        """Returned error should be a valid LlmResponse."""
        from google.adk.models.llm_response import LlmResponse

        plugin = DepthGuardPlugin()
        ctx = _make_callback_context({})
        error = Exception("error")

        result = await plugin.on_model_error_callback(
            callback_context=ctx,
            llm_request=_make_request(),
            error=error,
        )

        assert isinstance(result, LlmResponse)
        assert result.content.role == "model"
