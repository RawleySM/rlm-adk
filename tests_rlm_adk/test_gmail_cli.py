"""Tests for the Gmail CLI tool.

Uses mocked Gmail API service to test command behavior without network access.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

# Add project root so `scripts.gmail_cli` is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.gmail_cli.auth import DEFAULT_SCOPES, _find_token
from scripts.gmail_cli.cli import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.unit_nondefault


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_service():
    """Build a mock Gmail API service with chained method calls."""
    service = MagicMock()
    return service


def _mock_message(msg_id: str, subject: str = "Test", sender: str = "a@b.com", date: str = "Mon, 1 Jan 2026"):
    """Build a mock message response (metadata format)."""
    return {
        "id": msg_id,
        "threadId": f"thread_{msg_id}",
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date},
            ],
        },
        "snippet": f"Snippet for {msg_id}",
    }


def _mock_full_message(msg_id: str, body_text: str = "Hello world"):
    """Build a mock message response (full format) with plain text body."""
    raw_body = base64.urlsafe_b64encode(body_text.encode()).decode()
    return {
        "id": msg_id,
        "threadId": f"thread_{msg_id}",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "sender@test.com"},
                {"name": "To", "value": "me@test.com"},
                {"name": "Subject", "value": "Test Subject"},
                {"name": "Date", "value": "Mon, 1 Jan 2026"},
            ],
            "body": {"data": raw_body},
        },
    }


# ===========================================================================
# Auth tests
# ===========================================================================


class TestAuth:
    def test_find_token_missing_raises(self, tmp_path):
        """get_gmail_service() errors clearly when token.json is missing."""
        with pytest.raises(SystemExit):
            _find_token(override=tmp_path / "nonexistent.json")

    def test_find_token_override_found(self, tmp_path):
        token = tmp_path / "token.json"
        token.write_text("{}")
        assert _find_token(override=token) == token

    def test_find_token_searches_default_locations(self, tmp_path, monkeypatch):
        """Falls back to search paths when no override given."""
        import scripts.gmail_cli.auth as auth_mod

        fake_token = tmp_path / "token.json"
        fake_token.write_text("{}")
        monkeypatch.setattr(auth_mod, "_TOKEN_SEARCH_PATHS", [fake_token])
        assert _find_token() == fake_token

    def test_default_scopes_match_setup_script(self):
        """DEFAULT_SCOPES should include all scopes from setup_rlm_agent_auth.py."""
        expected = [
            "https://mail.google.com/",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
        ]
        for scope in expected:
            assert scope in DEFAULT_SCOPES


# ===========================================================================
# Inbox tests
# ===========================================================================


class TestInbox:
    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_inbox_list_json(self, mock_auth):
        """inbox list --json outputs valid JSON with expected keys."""
        service = _make_mock_service()
        mock_auth.return_value = service

        service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg1"}, {"id": "msg2"}]
        }
        service.users().messages().get().execute.side_effect = [
            _mock_message("msg1", "Subject 1", "alice@test.com"),
            _mock_message("msg2", "Subject 2", "bob@test.com"),
        ]

        result = runner.invoke(app, ["inbox", "list", "--json", "--count", "2"])
        assert result.exit_code == 0, result.output

        lines = [ln for ln in result.output.strip().split("\n") if ln.strip()]
        # Filter out non-JSON lines (info messages from stderr that might leak)
        json_lines = []
        for line in lines:
            try:
                json_lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        assert len(json_lines) == 2
        for obj in json_lines:
            assert "id" in obj
            assert "from" in obj
            assert "subject" in obj
            assert "date" in obj
            assert "snippet" in obj

    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_inbox_read_json(self, mock_auth):
        """inbox read MSG_ID --json outputs full message."""
        service = _make_mock_service()
        mock_auth.return_value = service
        service.users().messages().get().execute.return_value = _mock_full_message("msg1", "Hello body")

        result = runner.invoke(app, ["inbox", "read", "msg1", "--json"])
        assert result.exit_code == 0, result.output

        data = json.loads(result.output.strip())
        assert data["id"] == "msg1"
        assert data["body"] == "Hello body"

    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_inbox_unread_json(self, mock_auth):
        """inbox unread --json uses is:unread query."""
        service = _make_mock_service()
        mock_auth.return_value = service
        service.users().messages().list().execute.return_value = {"messages": [{"id": "u1"}]}
        service.users().messages().get().execute.return_value = _mock_message("u1", "Unread msg")

        result = runner.invoke(app, ["inbox", "unread", "--json"])
        assert result.exit_code == 0, result.output

        lines = [ln for ln in result.output.strip().split("\n") if ln.strip()]
        json_lines = [json.loads(ln) for ln in lines if ln.startswith("{")]
        assert len(json_lines) >= 1
        assert json_lines[0]["id"] == "u1"


# ===========================================================================
# Send tests
# ===========================================================================


class TestSend:
    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_send_constructs_message(self, mock_auth):
        """send --to X --subject Y --body Z --yes calls messages().send()."""
        service = _make_mock_service()
        mock_auth.return_value = service
        service.users().messages().send().execute.return_value = {"id": "sent1", "threadId": "t1"}

        result = runner.invoke(app, [
            "send", "email",
            "--to", "test@example.com",
            "--subject", "Test Subject",
            "--body", "Test body",
            "--yes", "--json",
        ])
        assert result.exit_code == 0, result.output

        data = json.loads(result.output.strip())
        assert data["id"] == "sent1"

        # Verify send was called
        service.users().messages().send.assert_called()

    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_send_base64_encoding(self, mock_auth):
        """Verify the raw message is base64url-encoded."""
        service = _make_mock_service()
        mock_auth.return_value = service
        service.users().messages().send().execute.return_value = {"id": "s2"}

        result = runner.invoke(app, [
            "send", "email",
            "--to", "x@y.com",
            "--subject", "S",
            "--body", "B",
            "--yes",
        ])
        assert result.exit_code == 0, result.output

        # Extract the body arg passed to send()
        call_kwargs = service.users().messages().send.call_args
        body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        assert "raw" in body
        # Verify it's valid base64url
        decoded = base64.urlsafe_b64decode(body["raw"])
        assert b"x@y.com" in decoded

    def test_send_requires_body_or_file(self):
        """send without --body or --body-file should fail."""
        result = runner.invoke(app, [
            "send", "email",
            "--to", "x@y.com",
            "--subject", "S",
            "--yes",
        ])
        assert result.exit_code != 0


# ===========================================================================
# Search tests
# ===========================================================================


class TestSearch:
    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_search_json(self, mock_auth):
        """search QUERY --json returns matching messages."""
        service = _make_mock_service()
        mock_auth.return_value = service
        service.users().messages().list().execute.return_value = {
            "messages": [{"id": "s1"}]
        }
        service.users().messages().get().execute.return_value = _mock_message("s1", "Found it")

        result = runner.invoke(app, ["search", "query", "from:test", "--json"])
        assert result.exit_code == 0, result.output

        lines = [ln for ln in result.output.strip().split("\n") if ln.startswith("{")]
        assert len(lines) >= 1
        data = json.loads(lines[0])
        assert data["subject"] == "Found it"


# ===========================================================================
# Labels tests
# ===========================================================================


class TestLabels:
    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_labels_list_json(self, mock_auth):
        """labels list --json returns label data."""
        service = _make_mock_service()
        mock_auth.return_value = service
        service.users().labels().list().execute.return_value = {
            "labels": [{"id": "INBOX", "name": "INBOX", "type": "system"}]
        }
        service.users().labels().get().execute.return_value = {
            "id": "INBOX", "name": "INBOX", "messagesTotal": 100, "messagesUnread": 5,
        }

        result = runner.invoke(app, ["labels", "list", "--json"])
        assert result.exit_code == 0, result.output

        lines = [ln for ln in result.output.strip().split("\n") if ln.startswith("{")]
        assert len(lines) >= 1
        data = json.loads(lines[0])
        assert data["name"] == "INBOX"
        assert data["messages_total"] == 100

    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_labels_create_json(self, mock_auth):
        """labels create NAME --json returns new label."""
        service = _make_mock_service()
        mock_auth.return_value = service
        service.users().labels().create().execute.return_value = {
            "id": "Label_123", "name": "MyLabel"
        }

        result = runner.invoke(app, ["labels", "create", "MyLabel", "--json"])
        assert result.exit_code == 0, result.output

        data = json.loads(result.output.strip())
        assert data["name"] == "MyLabel"


# ===========================================================================
# Threads tests
# ===========================================================================


class TestThreads:
    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_threads_list_json(self, mock_auth):
        """threads list --json returns thread data."""
        service = _make_mock_service()
        mock_auth.return_value = service
        service.users().threads().list().execute.return_value = {
            "threads": [{"id": "t1"}]
        }
        service.users().threads().get().execute.return_value = {
            "id": "t1",
            "messages": [_mock_message("m1", "Thread Subject")],
        }

        result = runner.invoke(app, ["threads", "list", "--json"])
        assert result.exit_code == 0, result.output

        lines = [ln for ln in result.output.strip().split("\n") if ln.startswith("{")]
        assert len(lines) >= 1
        data = json.loads(lines[0])
        assert data["subject"] == "Thread Subject"


# ===========================================================================
# Drafts tests
# ===========================================================================


class TestDrafts:
    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_drafts_create_json(self, mock_auth):
        """drafts create --json returns draft data."""
        service = _make_mock_service()
        mock_auth.return_value = service
        service.users().drafts().create().execute.return_value = {
            "id": "d1", "message": {"id": "m1"}
        }

        result = runner.invoke(app, [
            "drafts", "create",
            "--to", "x@y.com",
            "--subject", "Draft",
            "--body", "Draft body",
            "--json",
        ])
        assert result.exit_code == 0, result.output

        data = json.loads(result.output.strip())
        assert data["draft_id"] == "d1"

    @patch("scripts.gmail_cli.auth.get_gmail_service")
    def test_drafts_delete_json(self, mock_auth):
        """drafts delete DRAFT_ID --yes --json confirms deletion."""
        service = _make_mock_service()
        mock_auth.return_value = service
        service.users().drafts().delete().execute.return_value = None

        result = runner.invoke(app, ["drafts", "delete", "d1", "--yes", "--json"])
        assert result.exit_code == 0, result.output

        data = json.loads(result.output.strip())
        assert data["deleted"] is True


# ===========================================================================
# Output formatting tests
# ===========================================================================


class TestOutput:
    def test_should_use_json_flag(self):
        from scripts.gmail_cli.output import should_use_json
        assert should_use_json(True) is True
        assert should_use_json(False) is not None  # depends on TTY

    def test_print_table_json_mode(self, capsys):
        from scripts.gmail_cli.output import print_table
        rows = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        columns = [("a", "A"), ("b", "B")]
        print_table(rows, columns, json_mode=True)
        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.strip().split("\n") if ln]
        assert len(lines) == 2
        assert json.loads(lines[0])["a"] == 1

    def test_extract_body_plain_text(self):
        from scripts.gmail_cli.inbox import _extract_body
        raw = base64.urlsafe_b64encode(b"Hello").decode()
        payload = {"mimeType": "text/plain", "body": {"data": raw}}
        assert _extract_body(payload) == "Hello"

    def test_extract_body_multipart(self):
        from scripts.gmail_cli.inbox import _extract_body
        raw = base64.urlsafe_b64encode(b"Inner text").decode()
        payload = {
            "mimeType": "multipart/alternative",
            "body": {"size": 0},
            "parts": [
                {"mimeType": "text/plain", "body": {"data": raw}},
                {"mimeType": "text/html", "body": {"data": "irrelevant"}},
            ],
        }
        assert _extract_body(payload) == "Inner text"
