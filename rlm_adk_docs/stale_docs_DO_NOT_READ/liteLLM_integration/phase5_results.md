<!-- validated: 2026-03-09 -->

# Phase 5: Observability — Results

## Summary

Phase 5 adds cost tracking for LiteLLM model calls via `LiteLLMCostTrackingPlugin`.
Token accounting required **no changes** — ADK's `LiteLlm.generate_content_async`
already converts `response.usage` to `GenerateContentResponseUsageMetadata`,
which the existing `ObservabilityPlugin.after_model_callback` reads correctly.

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `rlm_adk/plugins/litellm_cost_tracking.py` | **CREATE** | ~70-line `LiteLLMCostTrackingPlugin(BasePlugin)` |
| `rlm_adk/agent.py` | **MODIFY** | Register cost plugin in `_default_plugins()` when `_is_litellm_active()` |
| `tests_rlm_adk/test_litellm_cost_tracking.py` | **CREATE** | 9 tests covering import, accumulation, graceful failure, registration |

## Plugin Behavior

- **after_model_callback**: Calls `litellm.completion_cost()` with model name and
  token counts from `llm_response.usage_metadata`. Writes:
  - `obs:litellm_last_call_cost` — cost of the most recent call (rounded to 6 decimal places)
  - `obs:litellm_total_cost` — running cumulative total (rounded to 6 decimal places)
- **Error handling**: All exceptions caught and logged at DEBUG level. Never crashes,
  never blocks execution.
- **AR-CRIT-001 compliant**: All state writes use `callback_context.state[key]`.

## MED-2 Limitation (Documented)

**Cost tracking only covers the root reasoning agent's model calls.** Child
orchestrator costs (from `llm_query` / `llm_query_batched`) are NOT tracked
because ADK gives child agents isolated invocation contexts that do not fire
plugin callbacks. This means `obs:litellm_total_cost` reflects only a fraction
of actual spend.

**Workaround for complete cost tracking**: Configure `litellm.success_callback`
at the Router level. This hooks into every LiteLLM completion call regardless
of which ADK agent initiated it, providing global cost visibility.

## Test Results

```
9 passed (unit_nondefault marker)
```

| Test | What it validates |
|------|-------------------|
| `test_import` | Module imports successfully |
| `test_is_base_plugin` | Instance is a `BasePlugin` subclass |
| `test_cost_accumulation_two_calls` | Two calls at $0.05 each yield total $0.10 |
| `test_cost_with_no_usage_metadata` | No state written when `usage_metadata` is None |
| `test_cost_with_none_token_counts` | None token counts default to 0 |
| `test_completion_cost_raises` | Exception in `completion_cost()` does not crash |
| `test_import_error_in_callback` | Plugin survives when litellm module ref is None |
| `test_plugin_registered_when_litellm_active` | Present in `_default_plugins()` when `RLM_ADK_LITELLM=1` |
| `test_plugin_absent_when_litellm_inactive` | Absent from `_default_plugins()` when flag is off |

## Default Suite Impact

Default test suite (28 passed, 2 skipped) is unaffected — the plugin is only
registered when `RLM_ADK_LITELLM=1`, which is not set in the default test
environment.
