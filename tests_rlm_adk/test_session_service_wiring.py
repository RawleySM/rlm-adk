"""Tests for Recs 1 & 2: Session service wiring and SQLite defaults.

Rec 2: _default_session_service() returns a SqliteSessionService with WAL mode.
Rec 1: create_rlm_runner() accepts session_service parameter.
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.adk.sessions.base_session_service import BaseSessionService


# ---- Rec 2 tests: _default_session_service() ----


class TestDefaultSessionService:
    """Rec 2: _default_session_service() creates a properly configured SqliteSessionService."""

    def test_default_session_service_creates_sqlite(self, tmp_path):
        """_default_session_service() returns a SqliteSessionService."""
        from rlm_adk.agent import _default_session_service
        from google.adk.sessions.sqlite_session_service import SqliteSessionService

        db_path = str(tmp_path / "test.db")
        service = _default_session_service(db_path=db_path)
        assert isinstance(service, SqliteSessionService)

    def test_default_session_service_creates_parent_dir(self, tmp_path):
        """_default_session_service() creates the parent directory if missing."""
        from rlm_adk.agent import _default_session_service

        db_path = str(tmp_path / "nested" / "dir" / "session.db")
        _default_session_service(db_path=db_path)
        assert Path(db_path).parent.exists()

    def test_default_session_service_enables_wal_mode(self, tmp_path):
        """_default_session_service() sets WAL journal mode on the database."""
        from rlm_adk.agent import _default_session_service

        db_path = str(tmp_path / "test.db")
        _default_session_service(db_path=db_path)

        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA journal_mode").fetchone()
        conn.close()
        assert result[0] == "wal"

    def test_default_session_service_env_override(self, tmp_path, monkeypatch):
        """RLM_SESSION_DB env var overrides the default path."""
        from rlm_adk.agent import _default_session_service

        custom_path = str(tmp_path / "custom.db")
        monkeypatch.setenv("RLM_SESSION_DB", custom_path)
        _default_session_service()
        assert Path(custom_path).exists()

    def test_default_session_service_idempotent(self, tmp_path):
        """Calling _default_session_service() twice on same db_path does not fail."""
        from rlm_adk.agent import _default_session_service
        from google.adk.sessions.sqlite_session_service import SqliteSessionService

        db_path = str(tmp_path / "test.db")
        s1 = _default_session_service(db_path=db_path)
        s2 = _default_session_service(db_path=db_path)
        assert isinstance(s1, SqliteSessionService)
        assert isinstance(s2, SqliteSessionService)


# ---- Rec 1 tests: create_rlm_runner() session_service parameter ----


class TestSessionServiceWiring:
    """Rec 1: create_rlm_runner() accepts and uses session_service parameter."""

    def test_create_rlm_runner_accepts_session_service(self):
        """create_rlm_runner() accepts a custom session_service and uses it."""
        from rlm_adk.agent import create_rlm_runner

        custom_service = MagicMock(spec=BaseSessionService)
        with patch("rlm_adk.agent.create_rlm_app") as mock_app:
            mock_app.return_value = MagicMock()
            runner = create_rlm_runner(
                model="gemini-2.5-flash",
                session_service=custom_service,
            )
        assert runner.session_service is custom_service

    def test_create_rlm_runner_returns_runner_not_inmemoryrunner(self):
        """Return type is Runner (not InMemoryRunner) when session_service is provided."""
        from rlm_adk.agent import create_rlm_runner
        from google.adk.runners import Runner

        custom_service = MagicMock(spec=BaseSessionService)
        with patch("rlm_adk.agent.create_rlm_app") as mock_app:
            mock_app.return_value = MagicMock()
            runner = create_rlm_runner(
                model="gemini-2.5-flash",
                session_service=custom_service,
            )
        assert isinstance(runner, Runner)

    def test_create_rlm_runner_default_session_service_is_sqlite(self, tmp_path):
        """When session_service=None, default is SqliteSessionService."""
        from rlm_adk.agent import create_rlm_runner
        from google.adk.sessions.sqlite_session_service import SqliteSessionService

        db_path = str(tmp_path / "test_session.db")
        with patch("rlm_adk.agent.create_rlm_app") as mock_app, \
             patch("rlm_adk.agent._default_session_service") as mock_default:
            mock_app.return_value = MagicMock()
            mock_svc = MagicMock(spec=SqliteSessionService)
            mock_default.return_value = mock_svc
            runner = create_rlm_runner(model="gemini-2.5-flash")
        assert runner.session_service is mock_svc
        mock_default.assert_called_once()

    def test_create_rlm_runner_artifact_service_override(self):
        """artifact_service parameter still works after refactor."""
        from rlm_adk.agent import create_rlm_runner
        from google.adk.artifacts import BaseArtifactService

        custom_artifact = MagicMock(spec=BaseArtifactService)
        custom_session = MagicMock(spec=BaseSessionService)
        with patch("rlm_adk.agent.create_rlm_app") as mock_app:
            mock_app.return_value = MagicMock()
            runner = create_rlm_runner(
                model="gemini-2.5-flash",
                artifact_service=custom_artifact,
                session_service=custom_session,
            )
        assert runner.artifact_service is custom_artifact
