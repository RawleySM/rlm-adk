# Bug: Provider-fake tests silently route to real LLM when `.env` sets `RLM_ADK_LITELLM=1`

## Summary

The provider-fake contract runner's `_set_env()` method configures env vars to
route LLM calls through the `FakeGeminiServer`, but it never unsets
`RLM_ADK_LITELLM`. Since `rlm_adk/agent.py` calls `load_dotenv()` at import
time, `RLM_ADK_LITELLM=1` from the project `.env` file is already present in
`os.environ`. This causes `_is_litellm_active()` to return `True`, and
`_resolve_model()` creates a LiteLLM Router model instead of a plain Gemini
model string -- bypassing the fake server entirely.

All non-LiteLLM provider-fake tests silently route LLM calls to the real model
(e.g., `z-ai/glm-5-20260211`) instead of the `FakeGeminiServer`. The
`ScenarioRouter` captures 0 requests, fixture responses are never consumed, and
the LLM generates real responses.

## Affected Code

**File:** `tests_rlm_adk/provider_fake/contract_runner.py`

### `_set_env()` (non-LiteLLM path)

The method sets `GOOGLE_API_KEY` and `GOOGLE_GENAI_USE_VERTEXAI` to configure
the fake Gemini endpoint, but does not clear LiteLLM-related env vars that were
loaded from `.env` at import time:

```python
def _set_env(self):
    os.environ["GOOGLE_API_KEY"] = "fake-key"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "0"
    # RLM_ADK_LITELLM remains "1" from load_dotenv() -- _is_litellm_active() returns True
```

### `_save_env()` / `_restore_env()`

These correctly snapshot and restore all env vars, so post-test cleanup was not
the issue. The problem is that `_set_env()` failed to neutralize LiteLLM vars
during the test.

## Symptom

The `fake_recursive_ping` fixture test fails:

- Expected 6 model calls captured by `ScenarioRouter`
- Got 0 captured (all calls went to the real LLM via LiteLLM Router)
- Fixture responses were never consumed
- Test assertions on captured request counts failed

## Root Cause

`_set_env()` in `contract_runner.py` did not clear LiteLLM-related env vars for
the non-LiteLLM test path. The env var `RLM_ADK_LITELLM=1`, loaded by
`load_dotenv()` in `agent.py` at import time, persisted through the test setup,
causing `_is_litellm_active()` to select the LiteLLM code path instead of the
plain Gemini path that targets the fake server.

## Resolution

**Fixed in:** `tests_rlm_adk/provider_fake/contract_runner.py`, method `_set_env()`

**Approach:** Added three lines to explicitly clear LiteLLM-related env vars
before configuring the fake Gemini server endpoint:

```python
os.environ.pop("RLM_ADK_LITELLM", None)
os.environ.pop("OPENAI_API_KEY", None)
os.environ.pop("OPENAI_API_BASE", None)
```

The existing `_restore_env()` correctly restores all three vars after the test
completes, so LiteLLM mode is properly re-enabled for subsequent code that
needs it.

## Impact

All provider-fake e2e tests now correctly route through the `FakeGeminiServer`.
The `fake_recursive_ping` test that was previously failing now passes (29
passed, 0 failed).

## Files Changed

- `tests_rlm_adk/provider_fake/contract_runner.py` -- Added LiteLLM env cleanup to `_set_env()`

## Related

This was discovered while investigating branch isolation for recursive child
dispatch in `dispatch.py`. The test appeared to fail due to the isolation
change, but the real problem was that the fake server was never being hit.
