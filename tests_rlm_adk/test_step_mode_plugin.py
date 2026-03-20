"""Tests for StepModePlugin."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from rlm_adk.step_gate import step_gate


@pytest.fixture(autouse=True)
def _reset_step_gate():
    """Ensure step gate is fully reset before and after every test.

    The singleton's asyncio.Event gets bound to a specific event loop,
    so we must reinitialize it for each test (each async test gets its
    own event loop with pytest-asyncio).
    """
    step_gate.set_step_mode(False)
    step_gate._event = asyncio.Event()
    step_gate._waiting = False
    step_gate._paused_agent_name = None
    step_gate._paused_depth = None
    yield
    step_gate.set_step_mode(False)
    step_gate._event = asyncio.Event()
    step_gate._waiting = False
    step_gate._paused_agent_name = None
    step_gate._paused_depth = None


class TestStepModePluginBasic:
    """Basic construction and interface tests."""

    def test_plugin_name_and_interface(self):
        from rlm_adk.plugins.step_mode import StepModePlugin

        plugin = StepModePlugin()
        assert plugin.name == "step_mode"
        assert hasattr(plugin, "before_model_callback")


class TestStepModeOff:
    """When step mode is off, the callback returns None immediately."""

    @pytest.mark.asyncio
    async def test_returns_none_when_off(self):
        from rlm_adk.plugins.step_mode import StepModePlugin

        step_gate.set_step_mode(False)

        plugin = StepModePlugin()
        mock_ctx = MagicMock()
        mock_ctx._invocation_context.agent.name = "reasoning_agent"
        mock_ctx.state = {"current_depth": 999}  # decoy — step_mode reads depth from agent name, not state
        mock_request = MagicMock()

        result = await plugin.before_model_callback(
            callback_context=mock_ctx,
            llm_request=mock_request,
        )
        assert result is None


class TestStepModeOn:
    """When step mode is on, the callback blocks until advance() is called."""

    @pytest.mark.asyncio
    async def test_blocks_until_advance(self):
        from rlm_adk.plugins.step_mode import StepModePlugin

        step_gate.set_step_mode(True)

        plugin = StepModePlugin()
        mock_ctx = MagicMock()
        mock_ctx._invocation_context.agent.name = "reasoning_agent"
        mock_ctx.state = {"current_depth": 999}  # decoy — step_mode reads depth from agent name, not state
        mock_request = MagicMock()

        # Launch the callback as a background task
        task = asyncio.create_task(
            plugin.before_model_callback(
                callback_context=mock_ctx,
                llm_request=mock_request,
            )
        )

        # Give the event loop a chance to start the task
        await asyncio.sleep(0.05)
        assert not task.done(), "Task should be blocked waiting for advance()"

        # Verify the gate reports it is waiting
        assert step_gate.waiting is True
        assert step_gate.paused_agent_name == "reasoning_agent"
        assert step_gate.paused_depth == 0

        # Advance the gate
        step_gate.advance()

        # Task should complete and return None
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_extracts_depth_from_state(self):
        from rlm_adk.plugins.step_mode import StepModePlugin

        step_gate.set_step_mode(True)

        plugin = StepModePlugin()
        mock_ctx = MagicMock()
        mock_ctx._invocation_context.agent.name = "worker_0"
        mock_ctx.state = {"current_depth": 3}
        mock_request = MagicMock()

        task = asyncio.create_task(
            plugin.before_model_callback(
                callback_context=mock_ctx,
                llm_request=mock_request,
            )
        )

        await asyncio.sleep(0.05)
        assert step_gate.paused_agent_name == "worker_0"
        assert step_gate.paused_depth == 3

        step_gate.advance()
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_survives_broken_context(self):
        """If _invocation_context raises, plugin still blocks and returns None."""
        from rlm_adk.plugins.step_mode import StepModePlugin

        step_gate.set_step_mode(True)

        plugin = StepModePlugin()

        # Use a plain object whose _invocation_context raises
        class _BrokenCtx:
            @property
            def _invocation_context(self):
                raise AttributeError("no context")

            state = {"current_depth": 0}

        mock_ctx = _BrokenCtx()
        mock_request = MagicMock()

        task = asyncio.create_task(
            plugin.before_model_callback(
                callback_context=mock_ctx,
                llm_request=mock_request,
            )
        )

        await asyncio.sleep(0.05)
        assert not task.done()
        # With broken context, agent_name/depth fall back to defaults
        assert step_gate.paused_agent_name == ""
        assert step_gate.paused_depth == 0

        step_gate.advance()
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result is None
