"""Tests for absolute path resolution of all .adk/ output paths.

Ensures _project_root() anchors all file paths to the repo root regardless
of the working directory, fixing the dual .adk/ session directory bug.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestProjectRoot:
    """_project_root() resolves to repo root regardless of CWD."""

    def test_returns_absolute_path(self):
        from rlm_adk.agent import _project_root

        assert _project_root().is_absolute()

    def test_contains_pyproject_toml(self):
        from rlm_adk.agent import _project_root

        assert (_project_root() / "pyproject.toml").exists()

    def test_independent_of_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rlm_adk.agent import _project_root

        assert (_project_root() / "pyproject.toml").exists()


class TestDefaultPathsResolveAbsolute:
    """All .adk/ defaults resolve to absolute paths under project root."""

    def test_session_db_path_is_absolute(self):
        from rlm_adk.agent import _DEFAULT_DB_PATH

        assert Path(_DEFAULT_DB_PATH).is_absolute()

    def test_artifact_root_is_absolute(self):
        from rlm_adk.agent import _DEFAULT_ARTIFACT_ROOT

        assert Path(_DEFAULT_ARTIFACT_ROOT).is_absolute()

    def test_session_db_under_project_root(self):
        from rlm_adk.agent import _DEFAULT_DB_PATH, _project_root

        assert Path(_DEFAULT_DB_PATH).parent.parent == _project_root()

    def test_artifact_root_under_project_root(self):
        from rlm_adk.agent import _DEFAULT_ARTIFACT_ROOT, _project_root

        assert Path(_DEFAULT_ARTIFACT_ROOT).parent == _project_root() / ".adk"


class TestDefaultSessionServicePath:
    """_default_session_service() uses absolute path when no override given."""

    def test_no_arg_uses_absolute_path(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("RLM_SESSION_DB", raising=False)
        from rlm_adk.agent import _default_session_service, _project_root

        svc = _default_session_service()
        expected = _project_root() / ".adk" / "session.db"
        assert Path(svc._db_path).resolve() == expected.resolve()

    def test_env_override_still_works(self, tmp_path, monkeypatch):
        custom = str(tmp_path / "custom.db")
        monkeypatch.setenv("RLM_SESSION_DB", custom)
        from rlm_adk.agent import _default_session_service

        svc = _default_session_service()
        assert str(Path(svc._db_path).resolve()) == str(Path(custom).resolve())


class TestPluginPathsResolveAbsolute:
    """Plugins created by _default_plugins() use absolute paths."""

    def test_debug_plugin_output_path_absolute(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from rlm_adk.agent import _default_plugins

        plugins = _default_plugins(debug=True, sqlite_tracing=False)
        debug_plugin = [
            p for p in plugins if type(p).__name__ == "DebugLoggingPlugin"
        ][0]
        assert Path(debug_plugin._output_path).is_absolute()

    def test_sqlite_tracing_plugin_path_absolute(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from rlm_adk.agent import _default_plugins

        plugins = _default_plugins(debug=False, sqlite_tracing=True)
        sqlite_plugin = [
            p for p in plugins if type(p).__name__ == "SqliteTracingPlugin"
        ][0]
        assert Path(sqlite_plugin._db_path).is_absolute()


class TestCreateRlmRunnerPaths:
    """create_rlm_runner() uses absolute paths for services."""

    def test_artifact_root_absolute(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from google.adk.sessions.base_session_service import BaseSessionService

        from rlm_adk.agent import create_rlm_runner

        mock_svc = MagicMock(spec=BaseSessionService)
        with patch("rlm_adk.agent.create_rlm_app") as mock_app:
            mock_app.return_value = MagicMock()
            runner = create_rlm_runner(
                model="gemini-fake",
                session_service=mock_svc,
            )
        root_dir = runner.artifact_service.root_dir
        assert Path(root_dir).is_absolute()
