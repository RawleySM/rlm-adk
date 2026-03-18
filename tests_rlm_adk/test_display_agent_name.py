"""Tests for _display_agent_name in live_invocation_tree (GAP-03)."""

from __future__ import annotations

import pytest

from rlm_adk.dashboard.components.live_invocation_tree import _display_agent_name
from rlm_adk.dashboard.live_models import LiveInvocation

pytestmark = pytest.mark.provider_fake_contract


def _make_invocation(*, agent_name: str, depth: int) -> LiveInvocation:
    """Minimal LiveInvocation with only the fields needed by _display_agent_name."""
    return LiveInvocation(
        invocation_id="inv-0",
        pane_id="d0:root",
        depth=depth,
        fanout_idx=None,
        agent_name=agent_name,
        model="gemini-3-pro-preview",
        model_version=None,
        status="running",
        iteration=0,
        input_tokens=0,
        output_tokens=0,
        thought_tokens=0,
        elapsed_ms=0.0,
        request_chunks=[],
        state_items=[],
        child_summaries=[],
        repl_submission="",
        repl_expanded_code="",
        repl_stdout="",
        repl_stderr="",
        reasoning_visible_text="",
        reasoning_thought_text="",
        structured_output=None,
        raw_payload={},
    )


class TestDisplayAgentName:
    """GAP-03: _display_agent_name must return invocation.agent_name directly."""

    def test_depth_zero_returns_reasoning_agent(self):
        inv = _make_invocation(agent_name="reasoning_agent", depth=0)
        assert _display_agent_name(inv) == "reasoning_agent"

    def test_depth_one_returns_child_reasoning_d1(self):
        inv = _make_invocation(agent_name="child_reasoning_d1", depth=1)
        assert _display_agent_name(inv) == "child_reasoning_d1"

    def test_depth_two_returns_child_reasoning_d2(self):
        inv = _make_invocation(agent_name="child_reasoning_d2", depth=2)
        assert _display_agent_name(inv) == "child_reasoning_d2"
