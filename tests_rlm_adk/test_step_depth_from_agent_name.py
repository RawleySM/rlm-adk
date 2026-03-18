"""Tests for StepModePlugin depth extraction from agent name (GAP-04)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from rlm_adk.step_gate import step_gate

pytestmark = pytest.mark.provider_fake_contract


@pytest.fixture(autouse=True)
def _reset_step_gate():
    """Ensure step gate is fully reset before and after every test."""
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


class TestStepDepthFromAgentName:
    """GAP-04: depth must be extracted from agent name, not state."""

    @pytest.mark.asyncio
    async def test_child_reasoning_d3_reports_depth_3(self):
        """child_reasoning_d3 must yield paused_depth == 3."""
        from rlm_adk.plugins.step_mode import StepModePlugin

        step_gate.set_step_mode(True)

        plugin = StepModePlugin()
        mock_ctx = MagicMock()
        mock_ctx._invocation_context.agent.name = "child_reasoning_d3"
        # Deliberately set state depth to 0 to prove it's NOT used
        mock_ctx.state = {"current_depth": 0}
        mock_request = MagicMock()

        task = asyncio.create_task(
            plugin.before_model_callback(
                callback_context=mock_ctx,
                llm_request=mock_request,
            )
        )

        await asyncio.sleep(0.05)
        assert step_gate.paused_agent_name == "child_reasoning_d3"
        assert step_gate.paused_depth == 3

        step_gate.advance()
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_reasoning_agent_reports_depth_0(self):
        """reasoning_agent (no _dN suffix) must yield paused_depth == 0."""
        from rlm_adk.plugins.step_mode import StepModePlugin

        step_gate.set_step_mode(True)

        plugin = StepModePlugin()
        mock_ctx = MagicMock()
        mock_ctx._invocation_context.agent.name = "reasoning_agent"
        mock_ctx.state = {"current_depth": 5}  # decoy — must not be used
        mock_request = MagicMock()

        task = asyncio.create_task(
            plugin.before_model_callback(
                callback_context=mock_ctx,
                llm_request=mock_request,
            )
        )

        await asyncio.sleep(0.05)
        assert step_gate.paused_agent_name == "reasoning_agent"
        assert step_gate.paused_depth == 0

        step_gate.advance()
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_child_reasoning_d1_reports_depth_1(self):
        """child_reasoning_d1 must yield paused_depth == 1."""
        from rlm_adk.plugins.step_mode import StepModePlugin

        step_gate.set_step_mode(True)

        plugin = StepModePlugin()
        mock_ctx = MagicMock()
        mock_ctx._invocation_context.agent.name = "child_reasoning_d1"
        mock_ctx.state = {"current_depth": 99}  # decoy
        mock_request = MagicMock()

        task = asyncio.create_task(
            plugin.before_model_callback(
                callback_context=mock_ctx,
                llm_request=mock_request,
            )
        )

        await asyncio.sleep(0.05)
        assert step_gate.paused_depth == 1

        step_gate.advance()
        await asyncio.wait_for(task, timeout=2.0)
