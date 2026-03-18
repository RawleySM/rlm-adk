<!-- completed: 2026-03-09 -->

# Phase 2: Factory Integration — Results

## Status: COMPLETE

All 15 tests pass. Default test suite (28 pass, 2 skip) unaffected.

## Changes Made

### `rlm_adk/agent.py` (modified)

Added two functions after `logger` definition:

1. **`_is_litellm_active() -> bool`** — Checks `RLM_ADK_LITELLM` env var for `"1"`, `"true"`, or `"yes"`.

2. **`_resolve_model(model_str, tier=None)`** — When LiteLLM active, creates a `LiteLlm` object via `create_litellm_model()`. Includes CRIT-1 guard: `if not isinstance(model_str, str): return model_str` to prevent double-wrapping on recursive dispatch.

Modified `create_reasoning_agent`:
- **BuiltInPlanner**: gated with `if thinking_budget > 0 and not litellm_active`
- **GenerateContentConfig**: `gcc = ... if not litellm_active else None`
- **Model resolution**: `resolved_model = _resolve_model(model) if litellm_active else model`

### `tests_rlm_adk/test_litellm_factory.py` (created)

15 tests across 3 test classes, marked `unit_nondefault`:

| Class | Test | What it verifies |
|-------|------|------------------|
| `TestIsLiteLLMActive` | 5 tests | Flag parsing: off by default, on with 1/true/yes, off with 0 |
| `TestResolveModel` | 4 tests | Passthrough when off, LiteLlm when on, CRIT-1 no double-wrap, tier param |
| `TestFactoryLiteLLMGating` | 6 tests | Agent model type, planner=None, no HttpOptions, regression for Gemini path |

## Review Fixes Incorporated

| ID | Fix | How |
|----|-----|-----|
| CRIT-1 | Guard against double-wrapping | `if not isinstance(model_str, str): return model_str` in `_resolve_model` |
| MED-4 | Mock `create_litellm_model` | Fixture uses `LiteLlm(model="reasoning", llm_client=MagicMock(spec=LiteLLMClient))` and patches `rlm_adk.models.litellm_router.create_litellm_model` |

## Design Note: GenerateContentConfig

Pydantic's `LlmAgent` coerces `generate_content_config=None` to a default `GenerateContentConfig()`. The test asserts `gcc.http_options is None` rather than `gcc is None`, which correctly verifies that Gemini-specific `HttpOptions`/`HttpRetryOptions` are not applied when LiteLLM is active.

## Test Commands

```bash
# Phase 2 tests only
.venv/bin/python -m pytest tests_rlm_adk/test_litellm_factory.py -m "" -v

# Default suite (regression)
.venv/bin/python -m pytest tests_rlm_adk/ -x -q
```
