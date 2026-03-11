"""Tests for Phase 5: LiteLLM cost tracking plugin.

Validates that LiteLLMCostTrackingPlugin:
- Accumulates per-call and total costs via litellm.completion_cost()
- Handles errors gracefully (no crash, returns None)
- Is registered in _default_plugins() when LiteLLM is active
- Is absent from _default_plugins() when LiteLLM is inactive

LIMITATION (MED-2): This plugin only tracks costs for the root reasoning
agent's model calls. Child orchestrator costs are NOT tracked because ADK
gives child agents isolated invocation contexts that do not fire plugin
callbacks. For complete cost tracking, use litellm.success_callback at the
Router level.
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit_nondefault]


@pytest.fixture(autouse=True)
def _clear_litellm_env(monkeypatch):
    """Ensure RLM_ADK_LITELLM is unset by default in every test."""
    monkeypatch.delenv("RLM_ADK_LITELLM", raising=False)


class TestImport:
    def test_import(self):
        from rlm_adk.plugins.litellm_cost_tracking import LiteLLMCostTrackingPlugin

        assert LiteLLMCostTrackingPlugin is not None

    def test_is_base_plugin(self):
        from google.adk.plugins.base_plugin import BasePlugin

        from rlm_adk.plugins.litellm_cost_tracking import LiteLLMCostTrackingPlugin

        plugin = LiteLLMCostTrackingPlugin()
        assert isinstance(plugin, BasePlugin)


class TestCostAccumulation:
    @pytest.mark.asyncio
    async def test_cost_accumulation_two_calls(self):
        """Mock litellm.completion_cost to return 0.05, call twice, verify total == 0.10."""
        from rlm_adk.plugins.litellm_cost_tracking import LiteLLMCostTrackingPlugin

        plugin = LiteLLMCostTrackingPlugin()

        # Build mock callback_context with state dict
        state = {}
        callback_context = MagicMock()
        callback_context.state = state

        # Build mock llm_response with usage_metadata
        llm_response = MagicMock()
        llm_response.usage_metadata.prompt_token_count = 100
        llm_response.usage_metadata.candidates_token_count = 50
        llm_response.model_version = "gemini/gemini-2.5-pro"

        with patch("litellm.completion_cost", return_value=0.05) as mock_cost:
            result1 = await plugin.after_model_callback(
                callback_context=callback_context, llm_response=llm_response
            )
            result2 = await plugin.after_model_callback(
                callback_context=callback_context, llm_response=llm_response
            )

        assert result1 is None
        assert result2 is None
        assert mock_cost.call_count == 2
        assert state["obs:litellm_last_call_cost"] == 0.05
        assert state["obs:litellm_total_cost"] == 0.10
        assert plugin._total_cost == pytest.approx(0.10)

    @pytest.mark.asyncio
    async def test_cost_with_no_usage_metadata(self):
        """When usage_metadata is None, no cost is tracked."""
        from rlm_adk.plugins.litellm_cost_tracking import LiteLLMCostTrackingPlugin

        plugin = LiteLLMCostTrackingPlugin()

        state = {}
        callback_context = MagicMock()
        callback_context.state = state

        llm_response = MagicMock()
        llm_response.usage_metadata = None

        result = await plugin.after_model_callback(
            callback_context=callback_context, llm_response=llm_response
        )

        assert result is None
        assert "obs:litellm_last_call_cost" not in state
        assert "obs:litellm_total_cost" not in state

    @pytest.mark.asyncio
    async def test_cost_with_none_token_counts(self):
        """When token counts are None, they default to 0."""
        from rlm_adk.plugins.litellm_cost_tracking import LiteLLMCostTrackingPlugin

        plugin = LiteLLMCostTrackingPlugin()

        state = {}
        callback_context = MagicMock()
        callback_context.state = state

        llm_response = MagicMock()
        llm_response.usage_metadata.prompt_token_count = None
        llm_response.usage_metadata.candidates_token_count = None
        llm_response.model_version = "unknown"

        with patch("litellm.completion_cost", return_value=0.0):
            result = await plugin.after_model_callback(
                callback_context=callback_context, llm_response=llm_response
            )

        assert result is None
        assert state["obs:litellm_last_call_cost"] == 0.0
        assert state["obs:litellm_total_cost"] == 0.0


class TestGracefulFailure:
    @pytest.mark.asyncio
    async def test_completion_cost_raises(self):
        """When litellm.completion_cost raises, plugin returns None without crashing."""
        from rlm_adk.plugins.litellm_cost_tracking import LiteLLMCostTrackingPlugin

        plugin = LiteLLMCostTrackingPlugin()

        state = {}
        callback_context = MagicMock()
        callback_context.state = state

        llm_response = MagicMock()
        llm_response.usage_metadata.prompt_token_count = 100
        llm_response.usage_metadata.candidates_token_count = 50
        llm_response.model_version = "unknown-model"

        with patch("litellm.completion_cost", side_effect=Exception("model not found")):
            result = await plugin.after_model_callback(
                callback_context=callback_context, llm_response=llm_response
            )

        assert result is None
        # State should not have been written
        assert "obs:litellm_last_call_cost" not in state
        assert "obs:litellm_total_cost" not in state
        # Internal accumulator should not have changed
        assert plugin._total_cost == 0.0

    @pytest.mark.asyncio
    async def test_import_error_in_callback(self):
        """When litellm import fails inside callback, plugin returns None."""
        from rlm_adk.plugins.litellm_cost_tracking import LiteLLMCostTrackingPlugin

        plugin = LiteLLMCostTrackingPlugin()

        state = {}
        callback_context = MagicMock()
        callback_context.state = state

        llm_response = MagicMock()
        llm_response.usage_metadata.prompt_token_count = 100
        llm_response.usage_metadata.candidates_token_count = 50
        llm_response.model_version = "test"

        with patch(
            "rlm_adk.plugins.litellm_cost_tracking.litellm",
            new=None,
        ):
            # When litellm module ref is None, accessing .completion_cost raises
            result = await plugin.after_model_callback(
                callback_context=callback_context, llm_response=llm_response
            )

        assert result is None


class TestPluginRegistration:
    def test_plugin_registered_when_litellm_active(self, monkeypatch):
        """When RLM_ADK_LITELLM=1, LiteLLMCostTrackingPlugin is in _default_plugins()."""
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")

        from rlm_adk.agent import _default_plugins
        from rlm_adk.plugins.litellm_cost_tracking import LiteLLMCostTrackingPlugin

        plugins = _default_plugins(sqlite_tracing=False)
        cost_plugins = [p for p in plugins if isinstance(p, LiteLLMCostTrackingPlugin)]
        assert len(cost_plugins) == 1

    def test_plugin_absent_when_litellm_inactive(self, monkeypatch):
        """When RLM_ADK_LITELLM is not set, LiteLLMCostTrackingPlugin is absent."""
        monkeypatch.delenv("RLM_ADK_LITELLM", raising=False)

        from rlm_adk.agent import _default_plugins
        from rlm_adk.plugins.litellm_cost_tracking import LiteLLMCostTrackingPlugin

        plugins = _default_plugins(sqlite_tracing=False)
        cost_plugins = [p for p in plugins if isinstance(p, LiteLLMCostTrackingPlugin)]
        assert len(cost_plugins) == 0
