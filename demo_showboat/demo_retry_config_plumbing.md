# retry_config Plumbing Fix — Red/Green TDD

*2026-03-17T11:10:14Z by Showboat 0.6.0*
<!-- showboat-id: 3d534a4d-dc72-4903-bb42-5fe137ee99cb -->

## Bug: retry_config silently dropped

`create_rlm_app()` and `create_rlm_runner()` accepted no `retry_config` parameter, so custom retry configuration passed by callers was silently ignored. The default 3-attempt retry still worked (via `_DEFAULT_RETRY_OPTIONS`), but customization was impossible from the top-level factory functions.

**Fix:** Wire `retry_config: dict[str, Any] | None = None` through both factories to `create_rlm_orchestrator()`, which already correctly forwards it to `create_reasoning_agent()` → `_build_generate_content_config()`.

## The full retry_config chain (after fix)

```bash
grep -n "retry_config" rlm_adk/agent.py | grep -E "retry_config: dict|retry_config=retry_config"
```

```output
168:    retry_config: dict[str, Any] | None,
200:    retry_config: dict[str, Any] | None = None,
292:    retry_config: dict[str, Any] | None = None,
303:        retry_config=retry_config,
481:    retry_config: dict[str, Any] | None = None,
519:        retry_config=retry_config,
548:    retry_config: dict[str, Any] | None = None,
615:        retry_config=retry_config,
```

The chain flows: `create_rlm_runner` (L548) → `create_rlm_app` (L481) → `create_rlm_orchestrator` (L292) → `create_reasoning_agent` (L200) → `_build_generate_content_config` (L168). Lines 519 and 615 are the two new pass-through additions.

## Default: 3-attempt exponential backoff

```bash
sed -n "109,114p" rlm_adk/agent.py
```

```output
_DEFAULT_RETRY_OPTIONS = HttpRetryOptions(
    attempts=3,
    initial_delay=1.0,
    max_delay=60.0,
    exp_base=2.0,
)
```

When `retry_config=None` (the default), `_build_generate_content_config` uses these defaults — 3 attempts with exponential backoff. Custom dicts (e.g. `{"attempts": 5}`) override these values.

## TDD tests: 3 new assertions

```bash
grep -n "def test_retry_config_flows_through\|def test_default_retry_config" tests_rlm_adk/test_bug001_orchestrator_retry.py
```

```output
204:    def test_retry_config_flows_through_create_rlm_app(self):
221:    def test_retry_config_flows_through_create_rlm_runner(self):
245:    def test_default_retry_config_has_3_attempts(self):
```

- **test_retry_config_flows_through_create_rlm_app** (L204): passes `retry_config={"attempts": 5}` to `create_rlm_app()`, asserts reasoning agent gets `attempts == 5`
- **test_retry_config_flows_through_create_rlm_runner** (L221): same via `create_rlm_runner()` 
- **test_default_retry_config_has_3_attempts** (L245): no custom config, asserts default `attempts == 3`

## Green: all 3 retry_config tests pass

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 RLM_ADK_LITELLM=0 .venv/bin/python -m pytest tests_rlm_adk/test_bug001_orchestrator_retry.py -q -k "retry_config_flows_through or default_retry_config" -o "addopts=" 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
3 passed, 20 deselected
```

## Regression: full test file passes

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 RLM_ADK_LITELLM=0 .venv/bin/python -m pytest tests_rlm_adk/test_bug001_orchestrator_retry.py -q -o "addopts=" 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
23 passed
```
