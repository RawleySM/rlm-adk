"""Tests for session_transfer_gate module — RED phase first."""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scripts.codex_transfer.session_transfer_gate import (
    read_bridge_state,
    should_launch_codex,
    build_confirm_response,
    process_stop_hook,
)


class TestReadBridgeState:
    """Test reading handoff state from bridge file."""

    def test_reads_handoff_ready(self, bridge_path, sample_bridge_data):
        """Should correctly read handoff_ready flag."""
        sample_bridge_data["handoff_ready"] = True
        bridge_path.write_text(json.dumps(sample_bridge_data))
        state = read_bridge_state(bridge_path)
        assert state["handoff_ready"] is True

    def test_reads_handoff_not_ready(self, bridge_path, sample_bridge_data):
        """Should correctly read handoff_ready=False."""
        bridge_path.write_text(json.dumps(sample_bridge_data))
        state = read_bridge_state(bridge_path)
        assert state["handoff_ready"] is False

    def test_returns_none_on_missing(self, tmp_path):
        """Should return None if bridge file doesn't exist."""
        result = read_bridge_state(tmp_path / "nonexistent.json")
        assert result is None

    def test_returns_none_on_corrupt(self, bridge_path):
        """Should return None on invalid JSON."""
        bridge_path.write_text("corrupt")
        result = read_bridge_state(bridge_path)
        assert result is None


class TestShouldLaunchCodex:
    """Test launch decision logic."""

    def test_returns_true_when_ready_and_auto(self):
        """Should launch when handoff_ready and mode is auto."""
        assert should_launch_codex(handoff_ready=True, mode="auto") is True

    def test_returns_false_when_not_ready(self):
        """Should not launch when handoff_ready is False."""
        assert should_launch_codex(handoff_ready=False, mode="auto") is False

    def test_returns_false_when_confirm_mode(self):
        """Should not auto-launch in confirm mode."""
        assert should_launch_codex(handoff_ready=True, mode="confirm") is False


class TestBuildConfirmResponse:
    """Test confirm mode response construction."""

    def test_returns_continue_true(self):
        """Should return continue=True for confirm mode."""
        result = build_confirm_response()
        assert result["continue"] is True

    def test_includes_system_message(self):
        """Should include systemMessage with transfer instructions."""
        result = build_confirm_response()
        assert "systemMessage" in result
        assert "TRANSFER" in result["systemMessage"]


class TestProcessStopHook:
    """Test the main stop hook processing logic."""

    def test_normal_exit_when_no_bridge(self, tmp_path):
        """Should return None (normal exit) when bridge file missing."""
        result = process_stop_hook(
            hook_input={},
            bridge_path=tmp_path / "nonexistent.json",
        )
        assert result is None

    def test_normal_exit_when_not_ready(self, bridge_path, sample_bridge_data):
        """Should return None when handoff not ready."""
        bridge_path.write_text(json.dumps(sample_bridge_data))
        result = process_stop_hook(
            hook_input={},
            bridge_path=bridge_path,
        )
        assert result is None

    def test_launches_codex_in_auto_mode(self, bridge_path, sample_bridge_data, tmp_home):
        """Should launch codex and return None in auto mode."""
        sample_bridge_data["handoff_ready"] = True
        bridge_path.write_text(json.dumps(sample_bridge_data))

        with patch(
            "scripts.codex_transfer.session_transfer_gate.launch_codex"
        ) as mock_launch:
            result = process_stop_hook(
                hook_input={},
                bridge_path=bridge_path,
                mode="auto",
                session_id="test-session-1234",
                handoffs_dir=tmp_home / ".claude" / "handoffs",
            )
            mock_launch.assert_called_once()
            assert result is None

    def test_returns_confirm_in_confirm_mode(self, bridge_path, sample_bridge_data):
        """Should return confirm response in confirm mode."""
        sample_bridge_data["handoff_ready"] = True
        bridge_path.write_text(json.dumps(sample_bridge_data))

        result = process_stop_hook(
            hook_input={},
            bridge_path=bridge_path,
            mode="confirm",
        )
        assert result is not None
        assert result["continue"] is True
        assert "TRANSFER" in result["systemMessage"]

    def test_respects_env_mode(self, bridge_path, sample_bridge_data):
        """Should use SESSION_TRANSFER_MODE env var."""
        sample_bridge_data["handoff_ready"] = True
        bridge_path.write_text(json.dumps(sample_bridge_data))

        with patch.dict(os.environ, {"SESSION_TRANSFER_MODE": "confirm"}):
            result = process_stop_hook(
                hook_input={},
                bridge_path=bridge_path,
            )
            assert result is not None
            assert result["continue"] is True

    def test_default_mode_is_auto(self, bridge_path, sample_bridge_data, tmp_home):
        """Default mode should be auto when no env var set."""
        sample_bridge_data["handoff_ready"] = True
        bridge_path.write_text(json.dumps(sample_bridge_data))

        with patch.dict(os.environ, {}, clear=False):
            # Ensure SESSION_TRANSFER_MODE is not set
            os.environ.pop("SESSION_TRANSFER_MODE", None)
            with patch(
                "scripts.codex_transfer.session_transfer_gate.launch_codex"
            ) as mock_launch:
                result = process_stop_hook(
                    hook_input={},
                    bridge_path=bridge_path,
                    session_id="test-session-1234",
                    handoffs_dir=tmp_home / ".claude" / "handoffs",
                )
                mock_launch.assert_called_once()
                assert result is None
