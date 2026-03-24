"""Tests for scripts/gdrive_cli — Drive CLI tool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from scripts.gdrive_cli.cli import app
from scripts.gdrive_cli.formatting import (
    friendly_mime,
    human_size,
    is_google_workspace_file,
    resolve_mime_type,
)

runner = CliRunner()

# ─── Fixtures ───


@pytest.fixture()
def mock_service():
    """Return a mocked Drive v3 service."""
    svc = MagicMock()
    return svc


SAMPLE_FILES = [
    {
        "id": "abc123",
        "name": "My Document.docx",
        "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "modifiedTime": "2026-03-20T10:00:00.000Z",
        "size": "51200",
    },
    {
        "id": "def456",
        "name": "Spreadsheet",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "modifiedTime": "2026-03-19T08:30:00.000Z",
        "size": None,
    },
    {
        "id": "ghi789",
        "name": "Photos",
        "mimeType": "application/vnd.google-apps.folder",
        "modifiedTime": "2026-03-18T12:00:00.000Z",
        "size": None,
    },
]

# ─── Unit tests: formatting helpers ───


class TestFormattingHelpers:
    def test_friendly_mime_google_doc(self):
        assert friendly_mime("application/vnd.google-apps.document") == "Google Doc"

    def test_friendly_mime_pdf(self):
        assert friendly_mime("application/pdf") == "PDF"

    def test_friendly_mime_unknown(self):
        assert friendly_mime("application/octet-stream") == "OCTET-STREAM"

    def test_human_size_bytes(self):
        assert human_size(500) == "500 B"

    def test_human_size_kb(self):
        assert human_size(51200) == "50.0 KB"

    def test_human_size_mb(self):
        assert human_size(5242880) == "5.0 MB"

    def test_human_size_none(self):
        assert human_size(None) == "—"

    def test_resolve_mime_doc(self):
        assert resolve_mime_type("doc") == "application/vnd.google-apps.document"

    def test_resolve_mime_sheet(self):
        assert resolve_mime_type("sheet") == "application/vnd.google-apps.spreadsheet"

    def test_resolve_mime_raw(self):
        assert resolve_mime_type("application/json") == "application/json"

    def test_is_google_workspace_true(self):
        assert is_google_workspace_file("application/vnd.google-apps.document")

    def test_is_google_workspace_false(self):
        assert not is_google_workspace_file("application/pdf")


# ─── Auth tests ───


class TestAuth:
    def test_missing_token_raises(self, tmp_path):
        """get_drive_service() raises SystemExit when token.json is missing."""
        from scripts.gdrive_cli.auth import get_drive_service

        with pytest.raises(SystemExit):
            get_drive_service(token_path=str(tmp_path / "nonexistent.json"))


# ─── Search command tests ───


class TestSearchCommand:
    @patch("scripts.gdrive_cli.search_cmd.get_drive_service")
    def test_search_json_output(self, mock_get_svc):
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.files().list().execute.return_value = {"files": SAMPLE_FILES}

        result = runner.invoke(app, ["search", "test", "--json"])
        assert result.exit_code == 0

        lines = [line for line in result.output.strip().split("\n") if line.strip()]
        assert len(lines) == 3
        first = json.loads(lines[0])
        assert "id" in first
        assert "name" in first
        assert "mimeType" in first

    @patch("scripts.gdrive_cli.search_cmd.get_drive_service")
    def test_search_recent(self, mock_get_svc):
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.files().list().execute.return_value = {"files": SAMPLE_FILES[:1]}

        result = runner.invoke(app, ["search", "--recent", "--json"])
        assert result.exit_code == 0

    def test_search_no_query_no_recent(self):
        result = runner.invoke(app, ["search"])
        assert result.exit_code == 1


# ─── ls command tests ───


class TestLsCommand:
    @patch("scripts.gdrive_cli.ls_cmd.get_drive_service")
    def test_ls_json_output(self, mock_get_svc):
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.files().list().execute.return_value = {"files": SAMPLE_FILES}

        result = runner.invoke(app, ["ls", "--json"])
        assert result.exit_code == 0

        lines = [line for line in result.output.strip().split("\n") if line.strip()]
        assert len(lines) == 3
        first = json.loads(lines[0])
        assert first["id"] == "ghi789"  # Folder sorted first

    @patch("scripts.gdrive_cli.ls_cmd.get_drive_service")
    def test_ls_empty_folder(self, mock_get_svc):
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.files().list().execute.return_value = {"files": []}

        result = runner.invoke(app, ["ls", "--json"])
        assert result.exit_code == 0


# ─── File commands tests ───


class TestInfoCommand:
    @patch("scripts.gdrive_cli.file_cmds.get_drive_service")
    def test_info_json(self, mock_get_svc):
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.files().get().execute.return_value = {
            "id": "abc123",
            "name": "test.txt",
            "mimeType": "text/plain",
            "size": "1024",
            "createdTime": "2026-03-20T10:00:00Z",
            "modifiedTime": "2026-03-20T10:00:00Z",
            "owners": [{"emailAddress": "test@test.com"}],
            "shared": False,
            "parents": ["root"],
            "webViewLink": "https://drive.google.com/file/d/abc123",
        }

        result = runner.invoke(app, ["info", "abc123", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "abc123"


class TestUploadCommand:
    @patch("scripts.gdrive_cli.file_cmds.get_drive_service")
    def test_upload_constructs_media(self, mock_get_svc, tmp_path):
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.files().create().execute.return_value = {
            "id": "new123",
            "name": "test.txt",
            "mimeType": "text/plain",
            "size": "5",
        }

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")

        result = runner.invoke(app, ["upload", str(test_file), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "new123"


class TestDownloadCommand:
    @patch("scripts.gdrive_cli.file_cmds.get_drive_service")
    def test_download_workspace_file(self, mock_get_svc, tmp_path):
        import os

        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.files().get().execute.return_value = {
            "name": "My Doc",
            "mimeType": "application/vnd.google-apps.document",
            "size": None,
        }
        svc.files().export().execute.return_value = b"Exported content"

        # Run from tmp_path so output goes there
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = runner.invoke(app, ["download", "abc123", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["exported_as"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        finally:
            os.chdir(old_cwd)


# ─── Files management tests ───


class TestFilesCommands:
    @patch("scripts.gdrive_cli.files_cmd.get_drive_service")
    def test_files_move(self, mock_get_svc):
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.files().get().execute.return_value = {"parents": ["old_folder"]}
        svc.files().update().execute.return_value = {
            "id": "abc123",
            "name": "test.txt",
            "mimeType": "text/plain",
            "parents": ["new_folder"],
        }

        result = runner.invoke(app, ["files", "move", "abc123", "new_folder", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["parents"] == ["new_folder"]

    @patch("scripts.gdrive_cli.files_cmd.get_drive_service")
    def test_files_trash(self, mock_get_svc):
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.files().update().execute.return_value = {
            "id": "abc123",
            "name": "test.txt",
            "trashed": True,
        }

        result = runner.invoke(app, ["files", "trash", "abc123", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["trashed"] is True

    def test_files_delete_requires_yes(self):
        result = runner.invoke(app, ["files", "delete", "abc123"])
        assert result.exit_code == 1

    @patch("scripts.gdrive_cli.files_cmd.get_drive_service")
    def test_files_list_trashed(self, mock_get_svc):
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.files().list().execute.return_value = {"files": SAMPLE_FILES[:1]}

        result = runner.invoke(app, ["files", "list-trashed", "--json"])
        assert result.exit_code == 0


# ─── MIME shorthand mapping test ───


class TestMimeShorthands:
    @pytest.mark.parametrize(
        "shorthand,expected",
        [
            ("doc", "application/vnd.google-apps.document"),
            ("sheet", "application/vnd.google-apps.spreadsheet"),
            ("slide", "application/vnd.google-apps.presentation"),
            ("pdf", "application/pdf"),
            ("folder", "application/vnd.google-apps.folder"),
            ("zip", "application/zip"),
        ],
    )
    def test_mime_shorthand_resolves(self, shorthand, expected):
        assert resolve_mime_type(shorthand) == expected
