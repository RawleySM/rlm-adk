"""Tests for ADK CLI service registry + plugins-on-App.

RED/GREEN TDD:
- test_plugins_attached_to_app: create_rlm_app() returns App with plugins
- test_runner_inherits_app_plugins: Runner gets plugins from App
- test_services_py_registers_session_factory: importing services.py registers session factory
- test_services_py_registers_artifact_factory: importing services.py registers artifact factory
- test_session_factory_applies_wal_pragmas: session factory creates WAL-mode SQLite
- test_create_rlm_runner_still_works: programmatic entrypoint produces correct Runner
- test_module_level_app_has_plugins: module-level app has plugins attached
"""

import importlib
import sqlite3
from unittest.mock import MagicMock, patch

from google.adk.apps.app import App
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import Runner
from google.adk.sessions.base_session_service import BaseSessionService


class TestPluginsAttachedToApp:
    """Verify create_rlm_app() attaches plugins to the App object."""

    def test_plugins_attached_to_app(self):
        """create_rlm_app() returns an App with plugins in app.plugins."""
        from rlm_adk.agent import create_rlm_app
        from rlm_adk.plugins.observability import ObservabilityPlugin

        app = create_rlm_app(model="gemini-2.5-flash")
        assert isinstance(app, App)
        assert len(app.plugins) >= 1
        plugin_types = [type(p) for p in app.plugins]
        assert ObservabilityPlugin in plugin_types

    def test_plugins_explicit_override(self):
        """Passing plugins= overrides the default plugin list entirely."""
        from rlm_adk.agent import create_rlm_app

        custom_plugin = MagicMock(spec=BasePlugin)
        app = create_rlm_app(model="gemini-2.5-flash", plugins=[custom_plugin])
        assert len(app.plugins) == 1
        assert app.plugins[0] is custom_plugin


class TestRunnerInheritsAppPlugins:
    """Verify Runner gets plugins from App, not passed separately."""

    def test_runner_inherits_app_plugins(self):
        """Runner created via create_rlm_runner() gets plugins from App."""
        from rlm_adk.agent import create_rlm_runner
        from rlm_adk.plugins.observability import ObservabilityPlugin

        mock_session = MagicMock(spec=BaseSessionService)
        runner = create_rlm_runner(
            model="gemini-2.5-flash",
            session_service=mock_session,
        )
        assert isinstance(runner, Runner)
        # Runner's plugin_manager should have plugins from App
        assert runner.plugin_manager is not None
        plugin_types = [type(p) for p in runner.plugin_manager.plugins]
        assert ObservabilityPlugin in plugin_types

    def test_runner_does_not_accept_separate_plugins(self):
        """create_rlm_runner() passes plugins via App, not Runner's plugins param."""
        from rlm_adk.agent import create_rlm_runner

        mock_session = MagicMock(spec=BaseSessionService)
        # This should work fine - plugins are on the App
        runner = create_rlm_runner(
            model="gemini-2.5-flash",
            session_service=mock_session,
        )
        # Verify the Runner was created with an App object
        assert runner.app is not None
        assert isinstance(runner.app, App)


class TestServiceRegistryRegistration:
    """Verify services.py registers factories in the ADK service registry."""

    def test_services_py_registers_session_factory(self):
        """Importing services.py overrides the built-in 'sqlite' session factory."""
        from google.adk.cli.service_registry import ServiceRegistry

        from rlm_adk.services import _rlm_session_factory, register_services

        # Create a fresh registry to avoid cross-test pollution
        registry = ServiceRegistry()
        register_services(registry)
        assert registry._session_factories.get("sqlite") is _rlm_session_factory

    def test_services_py_registers_artifact_factory(self):
        """Importing services.py overrides the built-in 'file' artifact factory."""
        from google.adk.cli.service_registry import ServiceRegistry

        from rlm_adk.services import _rlm_artifact_factory, register_services

        registry = ServiceRegistry()
        register_services(registry)
        assert registry._artifact_factories.get("file") is _rlm_artifact_factory

    def test_services_module_auto_registers_on_import(self):
        """When services.py is imported (as ADK CLI does), it auto-registers."""
        from google.adk.cli.service_registry import get_service_registry

        # Force reimport to trigger module-level registration
        if "rlm_adk.services" in importlib.sys.modules:
            del importlib.sys.modules["rlm_adk.services"]

        registry = get_service_registry()
        mod = importlib.import_module("rlm_adk.services")

        # Should override the built-in factories with our versions
        assert registry._session_factories.get("sqlite") is mod._rlm_session_factory
        assert registry._artifact_factories.get("file") is mod._rlm_artifact_factory


class TestSessionFactoryWALPragmas:
    """Verify the registered session factory creates SQLite with WAL mode."""

    def test_session_factory_applies_wal_pragmas(self, tmp_path):
        """The sqlite:// session factory (overridden) creates a SqliteSessionService with WAL mode."""
        from google.adk.cli.service_registry import ServiceRegistry
        from google.adk.sessions.sqlite_session_service import SqliteSessionService

        registry = ServiceRegistry()

        from rlm_adk.services import register_services

        register_services(registry)

        db_path = str(tmp_path / "test_wal.db")
        uri = f"sqlite://{db_path}"
        service = registry.create_session_service(uri)

        assert isinstance(service, SqliteSessionService)

        # Verify WAL mode was applied
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA journal_mode").fetchone()
        conn.close()
        assert result[0] == "wal"

    def test_artifact_factory_creates_file_service(self, tmp_path):
        """The file:// artifact factory (overridden) creates a FileArtifactService."""
        from google.adk.artifacts import FileArtifactService
        from google.adk.cli.service_registry import ServiceRegistry

        registry = ServiceRegistry()

        from rlm_adk.services import register_services

        register_services(registry)

        artifact_root = str(tmp_path / "artifacts")
        uri = f"file://{artifact_root}"
        service = registry.create_artifact_service(uri)

        assert isinstance(service, FileArtifactService)


class TestCreateRlmRunnerStillWorks:
    """Verify programmatic entrypoint still produces a working Runner."""

    def test_create_rlm_runner_still_works(self, tmp_path):
        """create_rlm_runner() still returns a Runner with correct services."""
        from google.adk.artifacts import FileArtifactService

        from rlm_adk.agent import create_rlm_runner

        mock_session = MagicMock(spec=BaseSessionService)

        with patch("rlm_adk.agent.create_rlm_app") as mock_app:
            mock_app.return_value = MagicMock(spec=App)
            mock_app.return_value.name = "rlm_adk"
            mock_app.return_value.root_agent = MagicMock()
            mock_app.return_value.plugins = []
            mock_app.return_value.context_cache_config = None
            mock_app.return_value.resumability_config = None
            runner = create_rlm_runner(
                model="gemini-2.5-flash",
                session_service=mock_session,
            )

        assert isinstance(runner, Runner)
        assert runner.session_service is mock_session
        assert isinstance(runner.artifact_service, FileArtifactService)

    def test_create_rlm_runner_default_session_is_sqlite(self):
        """When session_service is not provided, default is SqliteSessionService."""
        from google.adk.sessions.sqlite_session_service import SqliteSessionService

        from rlm_adk.agent import create_rlm_runner

        with patch("rlm_adk.agent.create_rlm_app") as mock_app:
            mock_app.return_value = MagicMock(spec=App)
            mock_app.return_value.name = "rlm_adk"
            mock_app.return_value.root_agent = MagicMock()
            mock_app.return_value.plugins = []
            mock_app.return_value.context_cache_config = None
            mock_app.return_value.resumability_config = None
            runner = create_rlm_runner(model="gemini-2.5-flash")

        assert isinstance(runner.session_service, SqliteSessionService)


class TestModuleLevelAppHasPlugins:
    """Verify the module-level app export has plugins attached."""

    def test_module_level_app_has_plugins(self):
        """The module-level app from agent.py has plugins attached."""
        from rlm_adk.agent import app
        from rlm_adk.plugins.observability import ObservabilityPlugin

        assert isinstance(app, App)
        assert len(app.plugins) >= 1
        plugin_types = [type(p) for p in app.plugins]
        assert ObservabilityPlugin in plugin_types

    def test_module_level_app_via_init(self):
        """The app exported from rlm_adk.__init__ has plugins."""
        import rlm_adk

        assert isinstance(rlm_adk.app, App)
        assert len(rlm_adk.app.plugins) >= 1
