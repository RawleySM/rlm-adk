# Demo: OpenRouter LiteLLM Provider Integration

## Summary

Added OpenRouter as a LiteLLM Router provider with configurable models, provider filtering, and native server-side fallback support. Implemented via Red/Green TDD (12 tests).

## Features Implemented

### 1. OpenRouter Provider Config (Dynamic)

`_build_openrouter_config()` builds the OpenRouter entry at runtime from env vars, unlike static `_PROVIDER_CONFIGS` entries.

**Default models:**
- Reasoning: `openrouter/google/gemini-2.5-pro-preview`
- Worker: `openrouter/google/gemini-2.5-flash-preview`

**Override via env vars:**
- `RLM_OPENROUTER_REASONING_MODEL=anthropic/claude-sonnet-4`
- `RLM_OPENROUTER_WORKER_MODEL=meta-llama/llama-3.3-70b`

### 2. Provider Filter (`RLM_LITELLM_PROVIDER`)

Pins all Router deployments to a single provider:
- `RLM_LITELLM_PROVIDER=openrouter` -- only openrouter/ deployments
- `RLM_LITELLM_PROVIDER=gemini` -- only gemini/ deployments
- Unset -- all providers with valid API keys included
- Case-insensitive matching

### 3. OpenRouter Native Fallback (`RLM_OPENROUTER_FALLBACK_MODELS`)

Comma-separated model list passed as `extra_body={"models": [...]}` in litellm_params, enabling OpenRouter's server-side model fallback.

Example: `RLM_OPENROUTER_FALLBACK_MODELS=google/gemini-2.5-pro,anthropic/claude-sonnet-4,deepseek/deepseek-r1`

### 4. Error Message Update

`_get_or_create_client()` RuntimeError now lists `OPENROUTER_API_KEY` alongside other provider keys.

## Test Results

### RED Phase (10 failures, 2 pass)

```
FAILED test_openrouter_config_included_when_key_set
FAILED test_openrouter_default_models
FAILED test_openrouter_reasoning_model_override
FAILED test_openrouter_worker_model_override
FAILED test_provider_filter_openrouter_only
FAILED test_provider_filter_unset_includes_all
FAILED test_provider_filter_case_insensitive
FAILED test_pinned_openrouter_single_deployment_per_tier
FAILED test_error_message_includes_openrouter
FAILED test_fallback_models_env_var
PASSED test_openrouter_config_excluded_when_key_missing
PASSED test_provider_filter_gemini_only
```

### GREEN Phase (12/12 pass)

```
tests_rlm_adk/test_litellm_openrouter.py::TestOpenRouterConfig::test_openrouter_config_included_when_key_set PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestOpenRouterConfig::test_openrouter_config_excluded_when_key_missing PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestOpenRouterModels::test_openrouter_default_models PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestOpenRouterModels::test_openrouter_reasoning_model_override PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestOpenRouterModels::test_openrouter_worker_model_override PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestProviderFilter::test_provider_filter_openrouter_only PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestProviderFilter::test_provider_filter_gemini_only PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestProviderFilter::test_provider_filter_unset_includes_all PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestProviderFilter::test_provider_filter_case_insensitive PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestProviderFilter::test_pinned_openrouter_single_deployment_per_tier PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestErrorMessage::test_error_message_includes_openrouter PASSED
tests_rlm_adk/test_litellm_openrouter.py::TestFallbackModels::test_fallback_models_env_var PASSED
======================== 12 passed, 1 warning in 0.06s =========================
```

### Regression Suite (78/78 pass)

```
tests_rlm_adk/test_litellm_foundation.py      -- 25 passed
tests_rlm_adk/test_litellm_errors.py           -- 11 passed
tests_rlm_adk/test_litellm_factory.py          -- 20 passed
tests_rlm_adk/test_litellm_cost_tracking.py    -- 10 passed
tests_rlm_adk/test_litellm_openrouter.py       -- 12 passed
======================== 78 passed, 1 warning in 2.36s =========================
```

## Files Changed

| File | Change |
|------|--------|
| `rlm_adk/models/litellm_router.py` | Added `_build_openrouter_config()`, provider filter in `build_model_list()`, fallback models support, updated error message |
| `tests_rlm_adk/test_litellm_openrouter.py` | New: 12 unit tests |
| `tests_rlm_adk/test_litellm_foundation.py` | Added `OPENROUTER_API_KEY` to key-clearing lists (regression fix) |
