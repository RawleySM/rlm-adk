# ObservabilityPlugin: Ephemeral Key Persistence via after_agent_callback

*2026-03-03 by Showboat*
<!-- showboat-id: obs-key-persistence-demo -->

## Overview

ADK's `base_llm_flow.py` creates `CallbackContext` *without* `event_actions` for plugin `after_model_callback`. State writes in that callback hit the live session dict but never land in a `state_delta` Event -- so they vanish from `final_state` when the session is re-fetched.

The fix: `ObservabilityPlugin.after_agent_callback` re-reads ephemeral values from the live session dict and re-writes them through the properly-wired `CallbackContext`, which DOES produce `state_delta` events. Fixture `expected_state` blocks now declaratively validate these obs keys.

## Source: after_agent_callback persistence

The new `after_agent_callback` in `rlm_adk/plugins/observability.py` persists two categories of ephemeral keys:

1. **Fixed keys** -- known obs counters written by `after_model_callback`
2. **Dynamic keys** -- keys matching `obs:finish_*` and `obs:model_usage:*` prefixes

```bash
grep -n "_EPHEMERAL\|after_agent_callback" rlm_adk/plugins/observability.py
```

```output
79:    _EPHEMERAL_FIXED_KEYS: tuple[str, ...] = (
90:    _EPHEMERAL_DYNAMIC_PREFIXES: tuple[str, ...] = (
95:    async def after_agent_callback(
```

The fixed keys list:

```bash
grep -A 8 "_EPHEMERAL_FIXED_KEYS" rlm_adk/plugins/observability.py | head -9
```

```output
    _EPHEMERAL_FIXED_KEYS: tuple[str, ...] = (
        OBS_TOTAL_CALLS,
        OBS_TOTAL_INPUT_TOKENS,
        OBS_TOTAL_OUTPUT_TOKENS,
        OBS_PER_ITERATION_TOKEN_BREAKDOWN,
        OBS_FINISH_SAFETY_COUNT,
        OBS_FINISH_RECITATION_COUNT,
        OBS_FINISH_MAX_TOKENS_COUNT,
    )
```

The persistence mechanism reads from the live session dict and writes through the wired `CallbackContext.state`:

```bash
grep -A 14 "async def after_agent_callback" rlm_adk/plugins/observability.py | tail -12
```

```output
            state = callback_context.state
            # Read the live session dict to find ephemeral values
            session_state = callback_context._invocation_context.session.state

            # Persist fixed keys
            for key in self._EPHEMERAL_FIXED_KEYS:
                val = session_state.get(key)
                if val is not None:
                    state[key] = val

            # Persist dynamic keys (obs:finish_*, obs:model_usage:*)
            for sess_key in list(session_state.keys()):
```

## Fixture expected_state: Declarative Obs Key Validation

Fixture JSON files now include `expected_state` blocks that assert obs keys are present in `final_state`. The contract runner evaluates these using operator matchers (`$gt`, `$not_empty`, `$type`, etc.).

Example from `worker_429_mid_batch.json`:

```json
"expected_state": {
    "worker_dispatch_count": 3,
    "obs:worker_total_batch_dispatches": 1,
    "obs:worker_dispatch_latency_ms": {"$type": "list", "$not_empty": true},
    "obs:worker_error_counts": {"$not_none": true, "$not_empty": true},
    "last_repl_result": {"$not_none": true},
    "obs:total_calls": {"$gt": 0},
    "obs:total_input_tokens": {"$gt": 0},
    "obs:total_output_tokens": {"$gt": 0},
    "obs:per_iteration_token_breakdown": {"$type": "list", "$not_empty": true}
}
```

The last four keys (`obs:total_calls`, `obs:total_input_tokens`, `obs:total_output_tokens`, `obs:per_iteration_token_breakdown`) are the newly-persisted ephemeral keys. Without `after_agent_callback`, these would be absent from `final_state` and the assertions would fail.

## Demo: 3 Representative Fixtures Passing

Three fixtures covering distinct obs key categories:

| Fixture | Obs Keys Validated | Scenario |
|---|---|---|
| `worker_429_mid_batch` | `obs:total_calls`, `obs:total_input_tokens`, `obs:total_output_tokens`, `obs:per_iteration_token_breakdown`, plus worker dispatch/error keys | Worker 429 rate-limit mid-batch |
| `reasoning_safety_finish` | `obs:total_calls`, `obs:total_input_tokens`, `obs:total_output_tokens`, `obs:per_iteration_token_breakdown`, `obs:finish_safety_count` | Reasoning SAFETY finish reason |
| `fault_429_then_success` | `obs:total_calls`, `obs:total_input_tokens`, `obs:total_output_tokens`, `obs:per_iteration_token_breakdown` | Reasoning 429 then recovery |

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -v -k "worker_429_mid_batch or reasoning_safety_finish or fault_429_then_success" -s 2>&1 | grep -E "PASSED|FAILED|selected|passed"
```

```output
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[fault_429_then_success] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[reasoning_safety_finish] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_429_mid_batch] PASSED
3 passed, 35 deselected
```

## Why This Matters

Before this fix, `ObservabilityPlugin.after_model_callback` wrote keys like `obs:total_calls` and `obs:total_input_tokens` to the session state, but ADK never emitted them as `state_delta` events. The values existed transiently during the run but disappeared when `session_service.get_session()` was called after completion.

This had two consequences:
1. **No observability in final state** -- downstream consumers (dashboards, traces, audits) could not see token counts or call counts
2. **No declarative testing** -- fixture `expected_state` blocks could not assert on obs keys because they were absent from `final_state`

The `after_agent_callback` fix is minimal and non-invasive: it re-persists values that were already computed, using the properly-wired `CallbackContext` that ADK provides to agent-level (not model-level) callbacks.

## Fixture expected_state Operator Reference

The contract runner supports these declarative matchers in `expected_state`:

| Operator | Example | Meaning |
|---|---|---|
| (plain value) | `"worker_dispatch_count": 3` | Exact equality |
| `$gt` | `{"$gt": 0}` | Greater than |
| `$gte` | `{"$gte": 0}` | Greater than or equal |
| `$not_none` | `{"$not_none": true}` | Value is not None |
| `$not_empty` | `{"$not_empty": true}` | Value is not None and not empty |
| `$type` | `{"$type": "list"}` | Type check (list, dict, str, int, float, bool) |
| `$has_key` | `{"$has_key": "UNKNOWN"}` | Dict contains key |
| `$contains` | `{"$contains": "error"}` | String contains substring |
| `$absent` | `{"$absent": true}` | Key should not exist in state |

Operators can be combined: `{"$type": "list", "$not_empty": true}` requires the value to be a non-empty list.
