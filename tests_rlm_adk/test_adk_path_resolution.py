"""Tests for absolute path resolution of all .adk/ output paths.

Ensures _package_dir() anchors all storage paths to the rlm_adk/ package
directory — matching where ADK CLI roots its .adk/ folder — regardless of
the working directory.
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


class TestPackageDir:
    """_package_dir() resolves to rlm_adk/ package directory."""

    def test_returns_absolute_path(self):
        from rlm_adk.agent import _package_dir

        assert _package_dir().is_absolute()

    def test_is_rlm_adk_package(self):
        from rlm_adk.agent import _package_dir

        pkg = _package_dir()
        assert pkg.name == "rlm_adk"
        assert (pkg / "agent.py").exists()

    def test_is_child_of_project_root(self):
        from rlm_adk.agent import _package_dir, _project_root

        assert _package_dir() == _project_root() / "rlm_adk"

    def test_independent_of_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rlm_adk.agent import _package_dir

        assert (_package_dir() / "agent.py").exists()


class TestDefaultPathsResolveAbsolute:
    """All .adk/ defaults resolve to absolute paths under _package_dir()."""

    def test_session_db_path_is_absolute(self):
        from rlm_adk.agent import _DEFAULT_DB_PATH

        assert Path(_DEFAULT_DB_PATH).is_absolute()

    def test_artifact_root_is_absolute(self):
        from rlm_adk.agent import _DEFAULT_ARTIFACT_ROOT

        assert Path(_DEFAULT_ARTIFACT_ROOT).is_absolute()

    def test_session_db_under_package_dir(self):
        from rlm_adk.agent import _DEFAULT_DB_PATH, _package_dir

        assert Path(_DEFAULT_DB_PATH).parent.parent == _package_dir()

    def test_artifact_root_under_package_dir(self):
        from rlm_adk.agent import _DEFAULT_ARTIFACT_ROOT, _package_dir

        assert Path(_DEFAULT_ARTIFACT_ROOT).parent == _package_dir() / ".adk"

    def test_adk_dir_under_package_dir(self):
        from rlm_adk.agent import _DEFAULT_DB_PATH, _package_dir

        assert str(Path(_DEFAULT_DB_PATH)).startswith(str(_package_dir() / ".adk"))


class TestDefaultSessionServicePath:
    """_default_session_service() uses absolute path when no override given."""

    def test_no_arg_uses_absolute_path(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("RLM_SESSION_DB", raising=False)
        from rlm_adk.agent import _default_session_service, _package_dir

        svc = _default_session_service()
        expected = _package_dir() / ".adk" / "session.db"
        assert Path(svc._db_path).resolve() == expected.resolve()

    def test_env_override_still_works(self, tmp_path, monkeypatch):
        custom = str(tmp_path / "custom.db")
        monkeypatch.setenv("RLM_SESSION_DB", custom)
        from rlm_adk.agent import _default_session_service

        svc = _default_session_service()
        assert str(Path(svc._db_path).resolve()) == str(Path(custom).resolve())


class TestPluginPathsResolveAbsolute:
    """Plugins created by _default_plugins() use absolute paths under _package_dir()."""

    def test_sqlite_tracing_plugin_path_absolute(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from rlm_adk.agent import _default_plugins

        plugins = _default_plugins(sqlite_tracing=True)
        sqlite_plugin = [
            p for p in plugins if type(p).__name__ == "SqliteTracingPlugin"
        ][0]
        assert Path(sqlite_plugin._db_path).is_absolute()

    def test_sqlite_tracing_plugin_under_package_dir(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        from rlm_adk.agent import _default_plugins, _package_dir

        plugins = _default_plugins(sqlite_tracing=True)
        sqlite_plugin = [
            p for p in plugins if type(p).__name__ == "SqliteTracingPlugin"
        ][0]
        assert Path(sqlite_plugin._db_path).parent == _package_dir() / ".adk"

    def test_traces_db_collocated_with_session_db(self):
        from rlm_adk.agent import _DEFAULT_DB_PATH, _default_plugins

        plugins = _default_plugins(sqlite_tracing=True)
        sqlite_plugin = next(
            p for p in plugins if type(p).__name__ == "SqliteTracingPlugin"
        )
        assert Path(sqlite_plugin._db_path).parent == Path(_DEFAULT_DB_PATH).parent


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
