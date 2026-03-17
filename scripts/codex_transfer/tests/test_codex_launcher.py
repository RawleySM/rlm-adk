"""Tests for codex_launcher module — RED phase first."""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from scripts.codex_transfer.codex_launcher import (
    read_handoff_doc,
    build_prompt,
    launch,
    PREAMBLE,
    PROJECT_DIR,
)


@pytest.fixture
def handoff_doc(tmp_home, session_id):
    """Create a sample handoff document."""
    handoffs_dir = tmp_home / ".claude" / "handoffs"
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    doc_path = handoffs_dir / f"{session_id}_handoff.md"
    content = (
        "# Session Handoff\n\n"
        "## Current Task\n"
        "Implementing session transfer system.\n\n"
        "## Files Modified\n"
        "- scripts/codex_transfer/quota_poller.py\n\n"
        "## Next Steps\n"
        "1. Complete codex_launcher tests\n"
        "2. Integrate with hooks\n"
    )
    doc_path.write_text(content)
    return doc_path


class TestReadHandoffDoc:
    """Test reading handoff documents."""

    def test_reads_existing_doc(self, handoff_doc):
        """Should read and return handoff doc content."""
        content = read_handoff_doc(handoff_doc)
        assert "Session Handoff" in content
        assert "session transfer system" in content

    def test_raises_on_missing_doc(self, tmp_path, session_id):
        """Should raise FileNotFoundError when doc doesn't exist."""
        missing = tmp_path / f"{session_id}_handoff.md"
        with pytest.raises(FileNotFoundError):
            read_handoff_doc(missing)


class TestBuildPrompt:
    """Test prompt construction for Codex."""

    def test_includes_preamble(self, handoff_doc):
        """Prompt should start with the preamble."""
        content = read_handoff_doc(handoff_doc)
        prompt = build_prompt(content, "test-session-1234")
        assert PREAMBLE in prompt

    def test_includes_handoff_content(self, handoff_doc):
        """Prompt should include the handoff document content."""
        content = read_handoff_doc(handoff_doc)
        prompt = build_prompt(content, "test-session-1234")
        assert "session transfer system" in prompt

    def test_includes_codebase_explorer_instructions(self, handoff_doc):
        """Prompt should instruct to spawn codebase-explorers."""
        content = read_handoff_doc(handoff_doc)
        prompt = build_prompt(content, "test-session-1234")
        assert "codebase-explorers" in prompt.lower() or "codebase-explorer" in prompt.lower()

    def test_includes_claude_project_dir(self, handoff_doc):
        """Prompt should reference Claude Code project dir for context."""
        content = read_handoff_doc(handoff_doc)
        prompt = build_prompt(content, "test-session-1234")
        assert "claude" in prompt.lower()
        assert "projects" in prompt.lower() or "session" in prompt.lower()

    def test_includes_session_id(self, handoff_doc):
        """Prompt should include the session ID."""
        content = read_handoff_doc(handoff_doc)
        prompt = build_prompt(content, "test-session-1234")
        assert "test-session-1234" in prompt


class TestLaunch:
    """Test the launch function."""

    def test_spawns_subprocess_with_correct_command(self, handoff_doc, session_id, tmp_home):
        """Should spawn codex with correct flags."""
        handoffs_dir = tmp_home / ".claude" / "handoffs"

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=12345)
            launch(session_id=session_id, handoffs_dir=handoffs_dir)

            mock_popen.assert_called_once()
            call_args = mock_popen.call_args
            cmd = call_args[0][0]  # First positional arg is the command list

            # Verify key command components
            assert "codex" in cmd[0]
            assert "exec" in cmd
            assert "--dangerously-bypass-approvals-and-sandbox" in cmd

    def test_uses_start_new_session(self, handoff_doc, session_id, tmp_home):
        """Should use start_new_session=True for fire-and-forget."""
        handoffs_dir = tmp_home / ".claude" / "handoffs"

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=12345)
            launch(session_id=session_id, handoffs_dir=handoffs_dir)

            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs.get("start_new_session") is True

    def test_writes_transfer_log(self, handoff_doc, session_id, tmp_home):
        """Should write transfer log JSON file."""
        handoffs_dir = tmp_home / ".claude" / "handoffs"

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=12345)
            launch(session_id=session_id, handoffs_dir=handoffs_dir)

            log_path = handoffs_dir / f"{session_id}_transfer.json"
            assert log_path.exists()
            log_data = json.loads(log_path.read_text())
            assert log_data["session_id"] == session_id
            assert "pid" in log_data
            assert log_data["pid"] == 12345
            assert "launched_at" in log_data

    def test_includes_multi_agent_flags(self, handoff_doc, session_id, tmp_home):
        """Should include multi_agent and child_agents_md enable flags."""
        handoffs_dir = tmp_home / ".claude" / "handoffs"

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=12345)
            launch(session_id=session_id, handoffs_dir=handoffs_dir)

            cmd = mock_popen.call_args[0][0]
            cmd_str = " ".join(cmd)
            assert "multi_agent" in cmd_str
            assert "child_agents_md" in cmd_str

    def test_includes_model_flag(self, handoff_doc, session_id, tmp_home):
        """Should specify the model as gpt-5.4."""
        handoffs_dir = tmp_home / ".claude" / "handoffs"

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=12345)
            launch(session_id=session_id, handoffs_dir=handoffs_dir)

            cmd = mock_popen.call_args[0][0]
            assert "-m" in cmd
            model_idx = cmd.index("-m")
            assert cmd[model_idx + 1] == "gpt-5.4"

    def test_includes_project_dir(self, handoff_doc, session_id, tmp_home):
        """Should use -C flag with project directory."""
        handoffs_dir = tmp_home / ".claude" / "handoffs"

        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=12345)
            launch(session_id=session_id, handoffs_dir=handoffs_dir)

            cmd = mock_popen.call_args[0][0]
            assert "-C" in cmd
            c_idx = cmd.index("-C")
            assert cmd[c_idx + 1] == PROJECT_DIR

    def test_raises_on_missing_handoff(self, session_id, tmp_home):
        """Should raise when handoff doc doesn't exist."""
        handoffs_dir = tmp_home / ".claude" / "handoffs"
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        # Don't create the handoff doc

        with pytest.raises(FileNotFoundError):
            launch(session_id=session_id, handoffs_dir=handoffs_dir)
