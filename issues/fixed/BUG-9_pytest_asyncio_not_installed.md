# BUG-9: pytest-asyncio not installed — all async tests fail

## Location

`pyproject.toml` lines 57-61 (`[dependency-groups] test`) and line 85 (`asyncio_mode = "auto"`)

Affected test files (34 tests total):
- `tests_rlm_adk/test_adk_ast_rewriter.py` (2 tests)
- `tests_rlm_adk/test_adk_dispatch_worker_pool.py` (5 tests)
- `tests_rlm_adk/test_adk_plugins_cache.py` (7 tests)
- `tests_rlm_adk/test_adk_plugins_depth_guard.py` (10 tests)
- `tests_rlm_adk/test_adk_plugins_observability.py` (10 tests)

## Description

`pytest-asyncio` is declared in the `[dependency-groups] test` group but is **not** installed in the project virtualenv. Every `async def` test function fails immediately with:

```
Failed: async def functions are not natively supported.
You need to install a suitable plugin for your async framework, for example:
  - pytest-asyncio
```

The `pyproject.toml` also configures `asyncio_mode = "auto"` under `[tool.pytest.ini_options]`, which triggers a warning since the plugin isn't present:

```
PytestConfigWarning: Unknown config option: asyncio_mode
```

## Root Cause

The dependency group `test` is not installed. Running `uv sync` or `pip install` against the main `dependencies` list does not pull in `pytest-asyncio`. The dependency group must be explicitly installed, e.g.:

```bash
uv sync --group test
# or
pip install -e ".[test]"   # if test were an optional-dependency
```

Since `test` is a `[dependency-groups]` entry (PEP 735), not a `[project.optional-dependencies]` entry, standard `pip install -e .` won't include it.

## Fix

Either:

1. Install the test dependency group explicitly:
   ```bash
   uv sync --group test
   ```

2. Or move `pytest-asyncio` into `[project.optional-dependencies] test` so `pip install -e ".[test]"` works.

3. Or add `pytest-asyncio` to the main `dependencies` list (not recommended for production).

## Impact

34 of 233 tests are skipped/failed. All async plugin, dispatch, and AST rewriter tests are untestable until resolved.
