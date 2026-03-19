"""Tests for step-mode dashboard controls (Step 5)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from rlm_adk.dashboard.live_controller import LiveDashboardController
from rlm_adk.step_gate import step_gate


@pytest.fixture(autouse=True)
def _reset_step_gate():
    step_gate.set_step_mode(False)
    step_gate._waiting = False
    step_gate._paused_agent_name = None
    step_gate._paused_depth = None
    yield
    step_gate.set_step_mode(False)


def _make_controller() -> LiveDashboardController:
    mock_loader = MagicMock()
    mock_loader.list_session_labels.return_value = []
    return LiveDashboardController(mock_loader)


def test_set_step_mode_true_updates_state_and_gate():
    controller = _make_controller()

    controller.set_step_mode(True)

    assert controller.state.step_mode_enabled is True
    assert step_gate.step_mode_enabled is True


def test_set_step_mode_false_clears_state_and_releases_gate():
    controller = _make_controller()
    controller.set_step_mode(True)
    # Simulate the gate being in a waiting state
    controller.state.step_mode_waiting = True
    controller.state.step_mode_paused_label = "Paused: reasoning @ depth 0"

    controller.set_step_mode(False)

    assert controller.state.step_mode_enabled is False
    assert controller.state.step_mode_waiting is False
    assert controller.state.step_mode_paused_label == ""
    assert step_gate.step_mode_enabled is False


def test_advance_step_calls_gate_advance():
    controller = _make_controller()
    controller.set_step_mode(True)

    # Patch advance to verify it's called
    called = []
    original_advance = step_gate.advance

    def tracking_advance():
        called.append(True)
        original_advance()

    step_gate.advance = tracking_advance
    try:
        controller.advance_step()
        assert len(called) == 1
    finally:
        step_gate.advance = original_advance


@pytest.mark.asyncio
async def test_poll_sync_step_gate_waiting():
    controller = _make_controller()
    # Set up a minimal snapshot so poll doesn't short-circuit
    controller.state.selected_session_id = "test-session"
    mock_snapshot = MagicMock()
    mock_snapshot.watermark = MagicMock()
    mock_snapshot.panes = []
    mock_snapshot.pane_map = {}
    mock_snapshot.active_candidate_pane_id = None
    mock_snapshot.root_pane_id = None
    mock_snapshot.status = "running"
    mock_snapshot.stats = MagicMock()
    mock_snapshot.stats.total_live_model_calls = 0
    mock_snapshot.stats.active_depth = 0
    mock_snapshot.stats.active_children = 0
    controller.state.snapshot = mock_snapshot
    controller.loader.load_session.return_value = mock_snapshot

    # Simulate step gate in waiting state
    step_gate.set_step_mode(True)
    step_gate._waiting = True
    step_gate._paused_agent_name = "reasoning"
    step_gate._paused_depth = 0

    await controller.poll()

    assert controller.state.step_mode_enabled is True
    assert controller.state.step_mode_waiting is True
    assert controller.state.step_mode_paused_label == "Paused: reasoning @ depth 0"


@pytest.mark.asyncio
async def test_poll_sync_step_gate_not_waiting():
    controller = _make_controller()
    controller.state.selected_session_id = "test-session"
    mock_snapshot = MagicMock()
    mock_snapshot.watermark = MagicMock()
    mock_snapshot.panes = []
    mock_snapshot.pane_map = {}
    mock_snapshot.active_candidate_pane_id = None
    mock_snapshot.root_pane_id = None
    mock_snapshot.status = "running"
    mock_snapshot.stats = MagicMock()
    mock_snapshot.stats.total_live_model_calls = 0
    mock_snapshot.stats.active_depth = 0
    mock_snapshot.stats.active_children = 0
    controller.state.snapshot = mock_snapshot
    controller.loader.load_session.return_value = mock_snapshot

    step_gate.set_step_mode(True)
    # gate is NOT waiting

    await controller.poll()

    assert controller.state.step_mode_enabled is True
    assert controller.state.step_mode_waiting is False
    assert controller.state.step_mode_paused_label == ""
