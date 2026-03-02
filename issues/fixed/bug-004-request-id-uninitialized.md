# BUG-004: REQUEST_ID never initialized in session state

## Summary

The `REQUEST_ID` state key (defined as `"request_id"` in `state.py` line 88) is never set
before the orchestrator run begins. Every plugin callback that reads `REQUEST_ID` falls
through to the default value `"unknown"`, which breaks cross-log correlation and prevents
the observability plugin from recording a meaningful `user:last_successful_call_id`.

## Affected Files

| File | Role |
|------|------|
| `rlm_adk/state.py:88` | Defines `REQUEST_ID = "request_id"` constant |
| `rlm_adk/orchestrator.py:119-123` | Builds `initial_state` dict -- `REQUEST_ID` is absent |
| `rlm_adk/plugins/debug_logging.py` | Reads `state.get(REQUEST_ID, "unknown")` in 7 callbacks |
| `rlm_adk/plugins/observability.py` | Reads `state.get(REQUEST_ID, "unknown")` in 6 callbacks; guards `user:last_successful_call_id` write behind `request_id != "unknown"` |

## Root Cause

In `orchestrator.py`, the `_run_async_impl` method builds an `initial_state` dictionary
(lines 119-123) and yields it as the first `EventActions(state_delta=...)`. This dictionary
includes `MESSAGE_HISTORY`, `CURRENT_DEPTH`, and `ITERATION_COUNT`, but does **not** include
`REQUEST_ID`. No other code path sets `REQUEST_ID` before the first plugin callback fires.

As a result, every `state.get(REQUEST_ID, "unknown")` call returns `"unknown"` for the
entire duration of the run.

## Evidence from Debug YAML

The file `rlm_adk_debug.yaml` contains **64 occurrences** of `request_id: unknown` across
all trace entries (before_agent, after_agent, before_model, after_model, before_tool,
after_tool, model_error). Every single trace entry shows the fallback value:

```
  request_id: unknown
```

No entry in the YAML has a non-"unknown" request_id value.

## Downstream Impact

### 1. debug_logging.py -- broken trace correlation
All trace entries (before_agent, after_agent, before_model, after_model, before_tool,
after_tool, on_model_error) record `request_id: "unknown"`. When multiple concurrent
sessions write to the same debug YAML, it is impossible to distinguish which trace entries
belong to which invocation.

### 2. observability.py -- `user:last_successful_call_id` never written
In `after_run_callback` (lines 254-258), the plugin checks:
```python
request_id = state.get(REQUEST_ID, "unknown")
if request_id != "unknown":
    state[USER_LAST_SUCCESSFUL_CALL_ID] = request_id
```
Since `request_id` is always `"unknown"`, the guard condition is never satisfied, and
`USER_LAST_SUCCESSFUL_CALL_ID` is never stored. This is confirmed by the absence of any
`user:last_successful_call_id` key in the debug YAML's `final_state` section.

### 3. observability.py -- logger.debug messages useless
All structured log messages use the request_id for correlation:
```python
logger.debug("[%s] Agent '%s' starting", request_id, agent_name)
```
These all emit `[unknown]` as the prefix, making log grep/filtering by request impossible.

## Reproduction

1. Run any RLM orchestrator invocation.
2. Inspect the generated `rlm_adk_debug.yaml`.
3. Observe that every `request_id` field is `"unknown"`.
4. Observe that `user:last_successful_call_id` is absent from `final_state`.

## Resolution

**Fixed** by adding `REQUEST_ID: str(uuid.uuid4())` to the `initial_state` dictionary in
`orchestrator.py:_run_async_impl`, ensuring a unique UUID v4 is generated and emitted in
the first `state_delta` event before any plugin callback fires.

### Changes

| File | Change |
|------|--------|
| `rlm_adk/orchestrator.py` | Added `import uuid` (line 13) |
| `rlm_adk/orchestrator.py` | Added `REQUEST_ID` to the import from `rlm_adk.state` (line 36) |
| `rlm_adk/orchestrator.py` | Added `REQUEST_ID: str(uuid.uuid4())` to the `initial_state` dict (line 142) |
| `tests_rlm_adk/test_bug004_request_id.py` | New test file with 2 tests |

### Test Results

- `test_initial_state_contains_request_id` -- verifies REQUEST_ID is present in the first state_delta event
- `test_request_id_is_valid_uuid` -- verifies the REQUEST_ID value is a non-empty UUID v4 string

Both tests confirmed RED before the fix and GREEN after. Full test suite: 253 passed,
8 failed (pre-existing failures in test_bug001 and test_bug002, unrelated to this change).
