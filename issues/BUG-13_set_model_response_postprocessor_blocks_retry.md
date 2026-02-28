# BUG-13: ADK output schema postprocessor terminates worker even when tool callbacks signal retry

## Severity

**High** — structured output self-healing (retry via `WorkerRetryPlugin` / `ReflectAndRetryToolPlugin`) is dead code at the e2e level. Workers always terminate after the first `set_model_response` function call, regardless of callback results. Retry guidance never reaches the model.

## Symptom

When a worker's `set_model_response` function call has invalid args (empty fields or missing required fields), the tool callbacks correctly detect the error and return retry guidance (`ToolFailureResponse`). However, the worker still terminates after one API call — the model never gets a second turn to retry with corrected args.

At the FIFO-replay e2e level, the "corrected functionCall" response leaks from the worker's queue slot into the reasoning agent, causing:

```
ValueError: Tool 'set_model_response' not found. Available tools: []
```

The reasoning agent (which has no tools) receives the functionCall intended for the worker's retry turn.

## Location

`google/adk/flows/llm_flows/base_llm_flow.py` lines 848–858
`google/adk/flows/llm_flows/_output_schema_processor.py` lines 96–116

## Root Cause

The `_postprocess_handle_function_calls_async` method in `base_llm_flow.py` unconditionally checks the function response event for `set_model_response` **after** callbacks have run:

```python
# base_llm_flow.py:848-858
if json_response := _output_schema_processor.get_structured_model_response(
    function_response_event
):
    final_event = _output_schema_processor.create_final_model_response_event(
        invocation_context, json_response
    )
    yield final_event
```

The check in `get_structured_model_response` (`_output_schema_processor.py:112`) matches on `func_response.name == 'set_model_response'`. But `__build_response_event` (`functions.py:950`) always sets the name from `tool.name`, which is `'set_model_response'` regardless of whether callbacks altered the response content.

### The callback → postprocessor conflict:

1. Model sends `functionCall: set_model_response` with bad args
2. Tool executes → either succeeds (soft error) or raises `ValidationError` (hard error)
3. Callback intercepts: `after_tool_callback` returns `ToolFailureResponse`, or `on_tool_error_callback` returns error guidance
4. `__build_response_event` builds event with `name='set_model_response'` + **error response content**
5. `get_structured_model_response` matches `name == 'set_model_response'` → extracts JSON from the **error response**
6. `create_final_model_response_event` creates a text-only event with the error JSON
7. `is_final_response()` returns `True` (no function calls/responses, not partial) → **loop breaks**
8. Worker terminates with the error response as its "final answer" — model never gets a retry turn

### The design conflict:

`SetModelResponseTool` + output schema postprocessor assumes: any `set_model_response` function response = success = terminate.

`ReflectAndRetryToolPlugin` + tool callbacks assume: altering the function response = model gets another LLM turn in the agent loop.

These two mechanisms are incompatible. The postprocessor runs **after** callbacks and overrides their intent by forcing termination.

## Impact

- `WorkerRetryPlugin.extract_error_from_result` (soft error: empty fields) — correctly detects errors but retry guidance is discarded
- `on_tool_error_callback` (hard error: `ValidationError`) — correctly handles exceptions but error response triggers premature termination
- All structured output self-healing is effectively single-attempt at the agent-loop level
- Unit tests for `WorkerRetryPlugin` pass because they test callbacks in isolation, not through the full agent loop

## Potential Fixes

### Option A: Patch postprocessor to check response content (ADK-side fix)

`get_structured_model_response` should inspect the response content to detect error/retry signals before creating the final event:

```python
def get_structured_model_response(function_response_event: Event) -> str | None:
    for func_response in function_response_event.get_function_responses():
        if func_response.name == 'set_model_response':
            # Don't treat error/retry responses as final
            if isinstance(func_response.response, dict) and func_response.response.get('error'):
                return None  # Let the agent loop continue
            return json.dumps(func_response.response, ensure_ascii=False)
    return None
```

### Option B: Change response name in callbacks (our-side workaround)

Override the function response event's name in `after_tool_callback` / `on_tool_error_callback` so it no longer matches `'set_model_response'`, bypassing the postprocessor check.

### Option C: Monkey-patch `get_structured_model_response` at dispatch time

Temporarily replace the function during worker execution to suppress the early-termination behavior when callbacks signal retry.

### Option D: Accept single-attempt and rely on dispatch-level retry

Remove the callback-based retry mechanism for structured output workers. Instead, handle retry at the dispatch/orchestrator level: if the worker terminates with invalid data, re-dispatch the worker with updated context.

## Reproduction

Run the structured output retry e2e fixtures:

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_structured_output_e2e.py -k "retry" -v
```

Both `structured_output_retry_empty` and `structured_output_retry_validation` fixtures fail because the worker consumes only 1 API call (the bad functionCall) instead of the expected 2 (bad + corrected).

## Affected Tests

- `test_structured_output_contract[structured_output_retry_empty]`
- `test_structured_output_contract[structured_output_retry_validation]`
- `test_retry_empty_final_answer`
- `test_retry_empty_model_call_count`
- `test_retry_validation_final_answer`
- `test_retry_validation_model_call_count`
- `test_retry_validation_with_plugins`

## Related

- `rlm_adk/callbacks/worker_retry.py` — WorkerRetryPlugin + make_worker_tool_callbacks
- `rlm_adk/dispatch.py` lines 394–402 — structured output wiring
- `tests_rlm_adk/test_adk_worker_retry.py` — unit tests that pass (callback isolation)
- ADK `SetModelResponseTool` — `google/adk/tools/set_model_response_tool.py`
- ADK `ReflectAndRetryToolPlugin` — `google/adk/plugins/reflect_retry_tool_plugin.py`
