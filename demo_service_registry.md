# ADK CLI Service Registry & Plugins-on-App

*2026-03-13T17:39:25Z by Showboat 0.6.0*
<!-- showboat-id: 2c07f156-192f-48e4-b268-cc6b35efaa05 -->

## What was implemented

Closed the gap between `adk run rlm_adk` (CLI entrypoint) and `create_rlm_runner()` (programmatic entrypoint):

1. **`rlm_adk/services.py`** — Auto-discovered by ADK CLI's `load_services_module()`. Registers custom session (`rlm-sqlite://`) and artifact (`rlm-file://`) service factories so the CLI-created Runner gets the same WAL-pragma'd SQLite session service.
2. **Plugins on App** — Verified that `create_rlm_app()` attaches plugins to the `App` object, so Runner extracts them automatically.
3. **13 new TDD tests** — Red/green cycle covering registration, WAL pragmas, plugin wiring, and backward compatibility.

## services.py — ADK CLI auto-discovery module

```bash
grep -n "def \|class " rlm_adk/services.py
```

```output
22:def _rlm_session_factory(uri: str, **kwargs):
41:def _rlm_artifact_factory(uri: str, **kwargs):
56:def register_services(registry: ServiceRegistry | None = None) -> None:
```

```bash
sed -n "56,71p" rlm_adk/services.py
```

```output
def register_services(registry: ServiceRegistry | None = None) -> None:
    """Register RLM-ADK service factories in the given (or global) registry.

    Args:
        registry: The ServiceRegistry to register on.  When ``None``,
            uses the global singleton from ``get_service_registry()``.
    """
    if registry is None:
        registry = get_service_registry()
    registry.register_session_service("rlm-sqlite", _rlm_session_factory)
    registry.register_artifact_service("rlm-file", _rlm_artifact_factory)
    logger.info("RLM-ADK service factories registered (rlm-sqlite, rlm-file)")


# Auto-register when this module is imported (ADK CLI discovery path).
register_services()
```

## Test structure — 6 classes, 13 tests

```bash
grep -n "class \|def test_" tests_rlm_adk/test_service_registry.py
```

```output
23:class TestPluginsAttachedToApp:
26:    def test_plugins_attached_to_app(self):
37:    def test_plugins_explicit_override(self):
47:class TestRunnerInheritsAppPlugins:
50:    def test_runner_inherits_app_plugins(self):
66:    def test_runner_does_not_accept_separate_plugins(self):
81:class TestServiceRegistryRegistration:
84:    def test_services_py_registers_session_factory(self):
98:    def test_services_py_registers_artifact_factory(self):
110:    def test_services_module_auto_registers_on_import(self):
126:class TestSessionFactoryWALPragmas:
129:    def test_session_factory_applies_wal_pragmas(self, tmp_path):
152:    def test_artifact_factory_creates_file_service(self, tmp_path):
170:class TestCreateRlmRunnerStillWorks:
173:    def test_create_rlm_runner_still_works(self, tmp_path):
197:    def test_create_rlm_runner_default_session_is_sqlite(self):
215:class TestModuleLevelAppHasPlugins:
218:    def test_module_level_app_has_plugins(self):
228:    def test_module_level_app_via_init(self):
```

## All 13 service registry tests pass

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_service_registry.py -v -m "" 2>&1 | grep -E "PASSED|FAILED|ERROR|passed|failed" | sed "s/ in [0-9.]*s//"
```

```output
tests_rlm_adk/test_service_registry.py::TestPluginsAttachedToApp::test_plugins_attached_to_app PASSED [  7%]
tests_rlm_adk/test_service_registry.py::TestPluginsAttachedToApp::test_plugins_explicit_override PASSED [ 15%]
tests_rlm_adk/test_service_registry.py::TestRunnerInheritsAppPlugins::test_runner_inherits_app_plugins PASSED [ 23%]
tests_rlm_adk/test_service_registry.py::TestRunnerInheritsAppPlugins::test_runner_does_not_accept_separate_plugins PASSED [ 30%]
tests_rlm_adk/test_service_registry.py::TestServiceRegistryRegistration::test_services_py_registers_session_factory PASSED [ 38%]
tests_rlm_adk/test_service_registry.py::TestServiceRegistryRegistration::test_services_py_registers_artifact_factory PASSED [ 46%]
tests_rlm_adk/test_service_registry.py::TestServiceRegistryRegistration::test_services_module_auto_registers_on_import PASSED [ 53%]
tests_rlm_adk/test_service_registry.py::TestSessionFactoryWALPragmas::test_session_factory_applies_wal_pragmas PASSED [ 61%]
tests_rlm_adk/test_service_registry.py::TestSessionFactoryWALPragmas::test_artifact_factory_creates_file_service PASSED [ 69%]
tests_rlm_adk/test_service_registry.py::TestCreateRlmRunnerStillWorks::test_create_rlm_runner_still_works PASSED [ 76%]
tests_rlm_adk/test_service_registry.py::TestCreateRlmRunnerStillWorks::test_create_rlm_runner_default_session_is_sqlite PASSED [ 84%]
tests_rlm_adk/test_service_registry.py::TestModuleLevelAppHasPlugins::test_module_level_app_has_plugins PASSED [ 92%]
tests_rlm_adk/test_service_registry.py::TestModuleLevelAppHasPlugins::test_module_level_app_via_init PASSED [100%]
============================== 13 passed ==============================
```

## No regressions — default provider-fake contract suite

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/ -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
34 passed, 2 skipped, 1171 deselected
```

## WAL pragma verification — journal_mode persists to new connections

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
from rlm_adk.services import _rlm_session_factory
import tempfile, os, sqlite3
db = os.path.join(tempfile.mkdtemp(), \"test.db\")
_rlm_session_factory(f\"rlm-sqlite://{db}\")
conn = sqlite3.connect(db)
mode = conn.execute(\"PRAGMA journal_mode\").fetchone()[0]
conn.close()
print(f\"journal_mode={mode}\")
os.unlink(db)
" 2>&1
```

```output
journal_mode=wal
```

## Module-level app has plugins attached

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
from rlm_adk.agent import app
print(f\"app.name={app.name}\")
print(f\"plugin_count={len(app.plugins)}\")
for p in app.plugins:
    print(f\"  plugin: {type(p).__name__}\")
" 2>&1
```

```output
app.name=rlm_adk
plugin_count=2
  plugin: ObservabilityPlugin
  plugin: SqliteTracingPlugin
```

## Summary

All objectives met:
- **13/13** new service registry tests pass (red/green TDD)
- **34/34** default contract tests pass, **0 regressions**
- `services.py` auto-registers `rlm-sqlite://` and `rlm-file://` factories via ADK's `ServiceRegistry`
- WAL pragmas verified: `journal_mode=wal` persists across connections
- Module-level `app` carries 2 plugins (ObservabilityPlugin, SqliteTracingPlugin) — Runner extracts them automatically

Usage: `adk run rlm_adk --session_service_uri rlm-sqlite://.adk/session.db --artifact_service_uri rlm-file://.adk/artifacts`
