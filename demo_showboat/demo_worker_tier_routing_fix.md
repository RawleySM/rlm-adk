# Worker Tier Routing Fix (LiteLLM Child Dispatch)

## Bug

When LiteLLM is active (`RLM_ADK_LITELLM=1`), all child dispatch calls via
`llm_query()` routed through the **reasoning** tier instead of the **worker**
tier. In a recursive ping replay, all 22 LLM calls went to
`openrouter/google/gemini-3.1-pro-preview` (reasoning) -- zero went to
`anthropic/claude-sonnet-4.6` (worker).

## Root Cause

In `dispatch.py:_run_child()`, line 321:

```python
target_model = str(model or dispatch_config.other_model)
```

`dispatch_config.other_model` is a `LiteLlm` Pydantic object (created by
`create_litellm_model("worker")`). The real `LiteLlm` class does NOT override
`__str__`, so `str()` produces Pydantic's default repr:

```
model='worker' llm_client=RouterLiteLlmClient(...)
```

This garbage string was passed to `create_child_orchestrator(model=...)`, which
called `_resolve_model()`. Since the string is not recognized as a `LiteLlm`
object (CRIT-1 check: `not isinstance(model_str, str)`), it fell through to
`create_litellm_model(tier)` where `tier` defaulted to `"reasoning"` via
`os.getenv("RLM_LITELLM_TIER", "reasoning")`.

## Fix

**`dispatch.py`** -- Separate the raw model object from its string representation:

```python
# Before (bug):
target_model = str(model or dispatch_config.other_model)
child = create_child_orchestrator(model=target_model, ...)

# After (fix):
raw_model = model if model is not None else dispatch_config.other_model
target_model = str(raw_model)  # for logging/dict keys/LLMResult.model only
child = create_child_orchestrator(model=raw_model, ...)
```

`create_child_orchestrator` passes the raw model to `create_reasoning_agent`,
which calls `_resolve_model()`. The existing CRIT-1 guard returns non-string
objects as-is:

```python
if not isinstance(model_str, str):
    return model_str  # Already a LiteLlm object (CRIT-1)
```

**`agent.py`** -- Updated `create_child_orchestrator` type hint from `model: str`
to `model: "str | Any"` to reflect that it can receive model objects.

## Tests

4 new tests in `test_dispatch_litellm_model.py::TestWorkerTierRouting`:

| Test | What it verifies |
|------|-----------------|
| `test_child_orchestrator_receives_model_object_not_string` | `create_child_orchestrator` receives the actual LiteLlm object, not `str(LiteLlm(...))` |
| `test_worker_tier_model_not_reasoning_tier` | Single + batched dispatch all use worker model, not reasoning |
| `test_build_call_log_still_uses_string_key` | Regression guard: `_build_call_log` still uses `str()` for dict keys (unhashable-type fix preserved) |
| `test_dispatch_config_other_model_preserved_through_child` | `DispatchConfig.other_model` survives as raw object, `str()` of it is NOT a clean model name |

## Test Results

```
tests_rlm_adk/test_dispatch_litellm_model.py   6 passed
tests_rlm_adk/test_litellm_openrouter.py       17 passed, 1 failed (pre-existing)
tests_rlm_adk/test_litellm_foundation.py       15 passed
tests_rlm_adk/test_litellm_factory.py          18 passed
                                         TOTAL: 55 passed, 1 pre-existing failure
```

## Files Changed

- `rlm_adk/dispatch.py` -- Split `target_model` into `raw_model` (object) + `target_model` (string)
- `rlm_adk/agent.py` -- Widened `create_child_orchestrator` model param type hint
- `tests_rlm_adk/test_dispatch_litellm_model.py` -- Added `RealisticFakeLiteLlm` + 4 new tests
