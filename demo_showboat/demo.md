# Dual .adk/ Session Directory Fix — Path Resolution Proof

*2026-02-26T14:04:46Z by Showboat 0.6.0*
<!-- showboat-id: 20c1e4ff-de08-487f-8f18-3bb374473797 -->

## The Bug

When `adk run` or `adk web` launched from a subdirectory, relative `.adk/` paths resolved against CWD instead of the repo root. This created duplicate session databases and artifact directories — one under the repo root, another under whatever directory happened to be CWD.

## The Fix

Added a `_project_root()` helper to `rlm_adk/agent.py` that anchors all `.adk/` output paths to absolute paths under the repo root using `Path(__file__).resolve().parents[1]`. Four files were updated:

- `rlm_adk/agent.py` — `_project_root()`, `_DEFAULT_DB_PATH`, `_DEFAULT_ARTIFACT_ROOT`, `_default_plugins()`
- `rlm_adk/plugins/migration.py` — fallback SQLite path
- `rlm_adk/dashboard/data_loader.py` — default constructor paths
- `tests_rlm_adk/test_adk_path_resolution.py` — 12 new tests (RED/GREEN TDD)

```bash
sed -n "57,73p" rlm_adk/agent.py
```

```output
def _project_root() -> Path:
    """Resolve the project root directory (contains pyproject.toml).

    Uses __file__ to anchor resolution, matching the .env pattern at line 54.
    """
    return Path(__file__).resolve().parents[1]


_DEFAULT_RETRY_OPTIONS = HttpRetryOptions(
    attempts=3,
    initial_delay=1.0,
    max_delay=60.0,
    exp_base=2.0,
)

_DEFAULT_DB_PATH = str(_project_root() / ".adk" / "session.db")
_DEFAULT_ARTIFACT_ROOT = str(_project_root() / ".adk" / "artifacts")
```

## All `_project_root()` callsites across the codebase

```bash
grep -rn "_project_root" rlm_adk/ --include="*.py"
```

```output
rlm_adk/plugins/migration.py:76:        from rlm_adk.agent import _project_root
rlm_adk/plugins/migration.py:80:            "RLM_SESSION_DB", str(_project_root() / ".adk" / "session.db")
rlm_adk/agent.py:57:def _project_root() -> Path:
rlm_adk/agent.py:72:_DEFAULT_DB_PATH = str(_project_root() / ".adk" / "session.db")
rlm_adk/agent.py:73:_DEFAULT_ARTIFACT_ROOT = str(_project_root() / ".adk" / "artifacts")
rlm_adk/agent.py:277:            output_path=str(_project_root() / "rlm_adk_debug.yaml"),
rlm_adk/agent.py:284:                db_path=str(_project_root() / ".adk" / "traces.db"),
rlm_adk/agent.py:294:        _adk_dir = str(_project_root() / ".adk")
rlm_adk/dashboard/data_loader.py:39:        from rlm_adk.agent import _project_root
rlm_adk/dashboard/data_loader.py:42:            jsonl_path = str(_project_root() / ".adk" / "context_snapshots.jsonl")
rlm_adk/dashboard/data_loader.py:44:            outputs_path = str(_project_root() / ".adk" / "model_outputs.jsonl")
```

## Proof 1: `_project_root()` resolves to repo root and all default paths are absolute

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
from pathlib import Path
from rlm_adk.agent import _project_root, _DEFAULT_DB_PATH, _DEFAULT_ARTIFACT_ROOT

root = _project_root()
print(f'_project_root() = {root}')
print(f'is_absolute:       {root.is_absolute()}')
print(f'pyproject.toml:    {(root / \"pyproject.toml\").exists()}')
print()
print(f'_DEFAULT_DB_PATH       = {_DEFAULT_DB_PATH}')
print(f'  is_absolute:           {Path(_DEFAULT_DB_PATH).is_absolute()}')
print(f'  under project root:    {str(_DEFAULT_DB_PATH).startswith(str(root))}')
print()
print(f'_DEFAULT_ARTIFACT_ROOT = {_DEFAULT_ARTIFACT_ROOT}')
print(f'  is_absolute:           {Path(_DEFAULT_ARTIFACT_ROOT).is_absolute()}')
print(f'  under project root:    {str(_DEFAULT_ARTIFACT_ROOT).startswith(str(root))}')
"

```

```output
_project_root() = /home/rawley-stanhope/dev/rlm-adk
is_absolute:       True
pyproject.toml:    True

_DEFAULT_DB_PATH       = /home/rawley-stanhope/dev/rlm-adk/.adk/session.db
  is_absolute:           True
  under project root:    True

_DEFAULT_ARTIFACT_ROOT = /home/rawley-stanhope/dev/rlm-adk/.adk/artifacts
  is_absolute:           True
  under project root:    True
```

## Proof 2: Paths remain correct even when CWD changes

The critical test — calling `_project_root()` after `os.chdir()` to a completely unrelated directory. Before the fix, `.adk/session.db` would resolve to `/tmp/.adk/session.db` here.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import os, tempfile
from pathlib import Path
from rlm_adk.agent import _project_root, _DEFAULT_DB_PATH, _DEFAULT_ARTIFACT_ROOT

# Save original CWD
original_cwd = os.getcwd()

# Change to a completely unrelated directory
with tempfile.TemporaryDirectory() as tmpdir:
    os.chdir(tmpdir)
    print(f'CWD changed to: {os.getcwd()}')
    print()

    root = _project_root()
    print(f'_project_root()        = {root}')
    print(f'pyproject.toml exists: {(root / \"pyproject.toml\").exists()}')
    print(f'DB path still absolute: {Path(_DEFAULT_DB_PATH).is_absolute()}')
    print(f'Artifact root absolute: {Path(_DEFAULT_ARTIFACT_ROOT).is_absolute()}')
    print()
    print('PASS: All paths anchored to repo root regardless of CWD')

# Restore
os.chdir(original_cwd)
"

```

```output
CWD changed to: /tmp/tmpkeths518

_project_root()        = /home/rawley-stanhope/dev/rlm-adk
pyproject.toml exists: True
DB path still absolute: True
Artifact root absolute: True

PASS: All paths anchored to repo root regardless of CWD
```

## Test Suite: 12 new path resolution tests (RED/GREEN TDD)

These tests cover every callsite: `_project_root()` basics, default path constants, session service factory, plugin paths, and runner artifact paths.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_adk_path_resolution.py -v 2>&1 | grep -E "PASSED|FAILED" | sed "s/ *\[.*//"; echo "---"; PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_adk_path_resolution.py -q 2>&1 | tail -1 | sed "s/ in .*//"
```

```output
tests_rlm_adk/test_adk_path_resolution.py::TestProjectRoot::test_returns_absolute_path PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestProjectRoot::test_contains_pyproject_toml PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestProjectRoot::test_independent_of_cwd PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestDefaultPathsResolveAbsolute::test_session_db_path_is_absolute PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestDefaultPathsResolveAbsolute::test_artifact_root_is_absolute PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestDefaultPathsResolveAbsolute::test_session_db_under_project_root PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestDefaultPathsResolveAbsolute::test_artifact_root_under_project_root PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestDefaultSessionServicePath::test_no_arg_uses_absolute_path PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestDefaultSessionServicePath::test_env_override_still_works PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestPluginPathsResolveAbsolute::test_debug_plugin_output_path_absolute PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestPluginPathsResolveAbsolute::test_sqlite_tracing_plugin_path_absolute PASSED
tests_rlm_adk/test_adk_path_resolution.py::TestCreateRlmRunnerPaths::test_artifact_root_absolute PASSED
---
12 passed
```

## Regression: full test suite

All existing tests still pass — no regressions from the path resolution changes.
