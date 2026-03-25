# GAP-CB-003: `on_model_error_callback` not wired on child reasoning agents

**Severity**: MEDIUM
**Category**: callback-lifecycle
**Files**: `rlm_adk/orchestrator.py`, `rlm_adk/agent.py`

## Problem

The old worker architecture used `on_model_error_callback` for per-worker error isolation (noted in MEMORY.md). In the new architecture, `RLMOrchestratorAgent._run_async_impl()` wires `after_tool_callback` and `on_tool_error_callback` on the reasoning agent (lines 378-380), but does NOT wire `on_model_error_callback`.

`create_reasoning_agent()` in `agent.py` accepts `before_model_callback` and `after_model_callback` but does not set `on_model_error_callback` (line 254-271). The `LlmAgent` constructor does accept this parameter (confirmed in ADK API reference).

When a child reasoning agent encounters a model-level error (e.g., content safety block, malformed response), ADK's `base_llm_flow.py` calls `_handle_on_model_error_callback` (line 358-395). Without a callback wired, the error propagates as an unhandled exception, which is caught by `dispatch.py`'s `_run_child` exception handler (line 386). This works but loses the opportunity for error classification and structured error handling at the model level.

## Evidence

`rlm_adk/orchestrator.py` lines 378-380 wire tool callbacks but no model error callback:
```python
after_tool_cb, on_tool_error_cb = make_worker_tool_callbacks(max_retries=2)
object.__setattr__(self.reasoning_agent, "after_tool_callback", after_tool_cb)
object.__setattr__(self.reasoning_agent, "on_tool_error_callback", on_tool_error_cb)
```

`rlm_adk/agent.py` `create_reasoning_agent()` lines 254-271 -- no `on_model_error_callback` parameter.

ADK `LlmAgent` constructor signature shows `on_model_error_callback` is an accepted parameter.

## Impact

Model-level errors (safety blocks, recitation blocks, malformed responses) are not handled gracefully at the agent level. They propagate as raw exceptions to the orchestrator retry loop or dispatch error handler. The error is still caught and reported, but without the opportunity for structured retry or error classification at the model callback level.

For root orchestrators, the transient error retry loop in `_run_async_impl` (lines 511-559) provides retry for transient errors. For child orchestrators, `dispatch.py`'s `_run_child` exception handler (line 386) catches and classifies errors. So the system is resilient, but error handling is less granular than it could be.

## Suggested Fix

Wire `on_model_error_callback` on reasoning agents for structured error classification:

```python
def reasoning_on_model_error(
    callback_context: CallbackContext,
    error: Exception,
) -> LlmResponse | None:
    """Classify and optionally handle model-level errors."""
    inv, agent = _agent_runtime(callback_context)
    error_category = _classify_error(error)
    object.__setattr__(agent, "_rlm_last_model_error", {
        "category": error_category,
        "error": str(error),
    })
    return None  # Let error propagate for retry logic
```

Then in `create_reasoning_agent()`:
```python
on_model_error_callback=reasoning_on_model_error,
```
