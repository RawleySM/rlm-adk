"""Tests for session_transfer_monitor module — RED phase first."""

import json
import os
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.codex_transfer.session_transfer_monitor import (
    read_bridge_file,
    update_bridge_file,
    should_trigger_handoff,
    is_handoff_write,
    build_system_message,
    process_hook_input,
    DEFAULT_THRESHOLD,
)


class TestReadBridgeFile:
    """Test bridge file reading."""

    def test_reads_valid_bridge(self, bridge_path, sample_bridge_data):
        """Should read and parse bridge file."""
        bridge_path.write_text(json.dumps(sample_bridge_data))
        result = read_bridge_file(bridge_path)
        assert result["five_hour_pct"] == 7.0

    def test_returns_none_on_missing(self, tmp_path):
        """Should return None if bridge file doesn't exist."""
        result = read_bridge_file(tmp_path / "nonexistent.json")
        assert result is None

    def test_returns_none_on_corrupt(self, bridge_path):
        """Should return None on invalid JSON."""
        bridge_path.write_text("not json")
        result = read_bridge_file(bridge_path)
        assert result is None


class TestUpdateBridgeFile:
    """Test bridge file updating."""

    def test_updates_fields(self, bridge_path, sample_bridge_data):
        """Should update specified fields while preserving others."""
        bridge_path.write_text(json.dumps(sample_bridge_data))
        update_bridge_file(bridge_path, {"handoff_requested": True, "tool_calls_since_request": 1})
        data = json.loads(bridge_path.read_text())
        assert data["handoff_requested"] is True
        assert data["tool_calls_since_request"] == 1
        assert data["five_hour_pct"] == 7.0  # Preserved

    def test_creates_file_if_missing(self, bridge_path):
        """Should handle the case where bridge file is missing (no-op or create)."""
        # If bridge file is missing, update should still work
        update_bridge_file(bridge_path, {"handoff_requested": True})
        # File should now exist with at least the updated field
        assert bridge_path.exists()


class TestShouldTriggerHandoff:
    """Test threshold logic."""

    def test_returns_false_below_threshold(self, sample_bridge_data):
        """Should not trigger at 7% usage (default threshold 80)."""
        assert should_trigger_handoff(sample_bridge_data) is False

    def test_returns_true_at_threshold(self):
        """Should trigger at exactly 80%."""
        data = {"five_hour_pct": 80.0, "handoff_requested": False, "handoff_ready": False}
        assert should_trigger_handoff(data) is True

    def test_returns_true_above_threshold(self, high_usage_bridge_data):
        """Should trigger at 85%."""
        assert should_trigger_handoff(high_usage_bridge_data) is True

    def test_respects_custom_threshold(self, sample_bridge_data):
        """Should use custom threshold from parameter."""
        # 7% usage, threshold of 5 -> should trigger
        assert should_trigger_handoff(sample_bridge_data, threshold=5.0) is True

    def test_returns_false_if_already_requested(self, high_usage_bridge_data):
        """Should not re-trigger if handoff already requested."""
        high_usage_bridge_data["handoff_requested"] = True
        assert should_trigger_handoff(high_usage_bridge_data) is False

    def test_returns_false_if_already_ready(self, high_usage_bridge_data):
        """Should not trigger if handoff already ready."""
        high_usage_bridge_data["handoff_ready"] = True
        assert should_trigger_handoff(high_usage_bridge_data) is False


class TestIsHandoffWrite:
    """Test detection of handoff document writes."""

    def test_detects_write_to_handoffs_dir(self):
        """Should detect Write tool writing to .claude/handoffs/ path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/home/user/.claude/handoffs/abc123_handoff.md"
            },
        }
        assert is_handoff_write(hook_input) is True

    def test_ignores_write_to_other_path(self):
        """Should not trigger on writes to other paths."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/home/user/project/file.py"},
        }
        assert is_handoff_write(hook_input) is False

    def test_ignores_non_write_tools(self):
        """Should not trigger on non-Write tools."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/home/user/.claude/handoffs/abc123_handoff.md"},
        }
        assert is_handoff_write(hook_input) is False

    def test_handles_missing_tool_input(self):
        """Should handle missing tool_input gracefully."""
        hook_input = {"tool_name": "Write"}
        assert is_handoff_write(hook_input) is False

    def test_handles_missing_file_path(self):
        """Should handle missing file_path gracefully."""
        hook_input = {"tool_name": "Write", "tool_input": {}}
        assert is_handoff_write(hook_input) is False


class TestBuildSystemMessage:
    """Test system message construction."""

    def test_returns_dict_with_system_message(self):
        """Should return a dict with systemMessage key."""
        result = build_system_message()
        assert "systemMessage" in result
        assert isinstance(result["systemMessage"], str)

    def test_message_mentions_handoff(self):
        """System message should instruct about handoff doc."""
        result = build_system_message()
        msg = result["systemMessage"]
        assert "handoff" in msg.lower()

    def test_message_mentions_handoffs_dir(self):
        """System message should mention the .claude/handoffs directory."""
        result = build_system_message()
        msg = result["systemMessage"]
        assert "handoffs" in msg.lower()


class TestProcessHookInput:
    """Test the main hook processing logic."""

    def test_no_output_when_below_threshold(self, bridge_path, sample_bridge_data):
        """Should produce no output when usage is below threshold."""
        bridge_path.write_text(json.dumps(sample_bridge_data))
        result = process_hook_input(
            hook_input={"tool_name": "Bash", "tool_input": {"command": "ls"}},
            bridge_path=bridge_path,
        )
        assert result is None

    def test_returns_system_message_on_first_trigger(self, bridge_path, high_usage_bridge_data):
        """Should return systemMessage on first threshold crossing."""
        bridge_path.write_text(json.dumps(high_usage_bridge_data))
        result = process_hook_input(
            hook_input={"tool_name": "Bash", "tool_input": {"command": "ls"}},
            bridge_path=bridge_path,
        )
        assert result is not None
        assert "systemMessage" in result
        # Bridge should now have handoff_requested=True
        updated = json.loads(bridge_path.read_text())
        assert updated["handoff_requested"] is True

    def test_sets_handoff_ready_on_write_detection(self, bridge_path, high_usage_bridge_data):
        """Should set handoff_ready when Write to handoffs dir detected."""
        high_usage_bridge_data["handoff_requested"] = True
        bridge_path.write_text(json.dumps(high_usage_bridge_data))
        result = process_hook_input(
            hook_input={
                "tool_name": "Write",
                "tool_input": {"file_path": "/home/user/.claude/handoffs/s1_handoff.md"},
            },
            bridge_path=bridge_path,
        )
        updated = json.loads(bridge_path.read_text())
        assert updated["handoff_ready"] is True

    def test_increments_tool_calls_since_request(self, bridge_path, high_usage_bridge_data):
        """Should increment tool_calls_since_request when handoff_requested."""
        high_usage_bridge_data["handoff_requested"] = True
        high_usage_bridge_data["tool_calls_since_request"] = 2
        bridge_path.write_text(json.dumps(high_usage_bridge_data))
        process_hook_input(
            hook_input={"tool_name": "Bash", "tool_input": {"command": "ls"}},
            bridge_path=bridge_path,
        )
        updated = json.loads(bridge_path.read_text())
        assert updated["tool_calls_since_request"] == 3

    def test_re_sends_message_after_5_tool_calls(self, bridge_path, high_usage_bridge_data):
        """Should re-send systemMessage after 5 tool calls without handoff."""
        high_usage_bridge_data["handoff_requested"] = True
        high_usage_bridge_data["tool_calls_since_request"] = 5
        bridge_path.write_text(json.dumps(high_usage_bridge_data))
        result = process_hook_input(
            hook_input={"tool_name": "Bash", "tool_input": {"command": "ls"}},
            bridge_path=bridge_path,
        )
        assert result is not None
        assert "systemMessage" in result
        # Counter should reset
        updated = json.loads(bridge_path.read_text())
        assert updated["tool_calls_since_request"] == 0

    def test_no_output_when_bridge_missing(self, tmp_path):
        """Should return None when bridge file doesn't exist."""
        result = process_hook_input(
            hook_input={"tool_name": "Bash", "tool_input": {"command": "ls"}},
            bridge_path=tmp_path / "nonexistent.json",
        )
        assert result is None

    def test_no_output_when_handoff_ready(self, bridge_path, high_usage_bridge_data):
        """Should not send more messages once handoff_ready is True."""
        high_usage_bridge_data["handoff_requested"] = True
        high_usage_bridge_data["handoff_ready"] = True
        bridge_path.write_text(json.dumps(high_usage_bridge_data))
        result = process_hook_input(
            hook_input={"tool_name": "Bash", "tool_input": {"command": "ls"}},
            bridge_path=bridge_path,
        )
        assert result is None

    def test_respects_env_threshold(self, bridge_path, sample_bridge_data):
        """Should use SESSION_TRANSFER_THRESHOLD env var."""
        bridge_path.write_text(json.dumps(sample_bridge_data))
        with patch.dict(os.environ, {"SESSION_TRANSFER_THRESHOLD": "5"}):
            result = process_hook_input(
                hook_input={"tool_name": "Bash", "tool_input": {"command": "ls"}},
                bridge_path=bridge_path,
            )
            assert result is not None  # 7% > 5% threshold
