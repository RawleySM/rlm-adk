# BUG-4: Worker agents created without before/after model callbacks

## Location

- `rlm_adk/dispatch.py` lines 71-97 (`WorkerPool._create_worker`)
- `rlm_adk/callbacks/worker.py` (defines `worker_before_model`, `worker_after_model`)

## Description

`WorkerPool._create_worker()` creates `LlmAgent` workers with `include_contents='none'` (per HIGH-3), meaning the agent deliberately receives no conversation contents from the ADK framework. The design intent is for prompts to be injected via `worker_before_model` callback reading from `worker._pending_prompt`.

However, the workers are created without attaching these callbacks:

```python
worker = LlmAgent(
    name=worker_name,
    model=model_name,
    description=f"Sub-LM worker for {model_name}",
    instruction="Answer the user's query directly and concisely.",
    include_contents="none",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_key=f"{worker_name}_output",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.0,
    ),
)
# Missing:
#   before_model_callback=worker_before_model,
#   after_model_callback=worker_after_model,
```

The callback functions exist and are correctly defined in `rlm_adk/callbacks/worker.py`, and are properly exported from `rlm_adk/callbacks/__init__.py`, but they are never attached to the worker agents.

## Impact

Even if BUG-3 were fixed and workers were dispatched:

1. **Empty prompts**: `include_contents='none'` means no contents from ADK. Without `worker_before_model` to inject the prompt from `_pending_prompt`, the LLM receives an empty request.
2. **Lost responses**: Without `worker_after_model` to extract the response and write it to the worker's `output_key` in state, `create_dispatch_closures.llm_query_batched_async` reads empty strings from `ctx.session.state.get(output_key, "")`.

Workers are effectively deaf (can't receive prompts) and mute (can't return responses).

## Fix

Add callback parameters to the `LlmAgent` constructor in `_create_worker`:

```python
from rlm_adk.callbacks.worker import worker_before_model, worker_after_model

worker = LlmAgent(
    name=worker_name,
    model=model_name,
    # ... existing params ...
    before_model_callback=worker_before_model,
    after_model_callback=worker_after_model,
)
```

## Affected SRS requirements

- FR-011 (Sub-LM Query Support)
- AR-HIGH-003 (Worker Agent Isolation)
- AR-HIGH-006 (Callback Completeness)
