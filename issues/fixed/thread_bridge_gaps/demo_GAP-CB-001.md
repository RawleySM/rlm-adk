# Demo: GAP-CB-001 -- Conversation history duplicated into system_instruction

## What was fixed

`_extract_adk_dynamic_instruction()` in `rlm_adk/callbacks/reasoning.py` iterated ALL `llm_request.contents` (the full conversation history) and appended the entire blob to `system_instruction` via `append_instructions()`. This duplicated every prior model response, tool call/response, and user message into the system prompt, wasting tokens and risking context window limits on later turns. The fix deletes the function entirely and makes `reasoning_before_model` a pure token-accounting callback.

## Before (the problem)

The callback extracted all content text and injected it into system_instruction:

```python
def _extract_adk_dynamic_instruction(llm_request: LlmRequest) -> str:
    dynamic_text = ""
    if llm_request.contents:
        for content in llm_request.contents:
            if content.parts:
                for part in content.parts:
                    if part.text:
                        dynamic_text += part.text
    return dynamic_text.strip()


def reasoning_before_model(callback_context, llm_request):
    ...
    dynamic_instruction = _extract_adk_dynamic_instruction(llm_request)
    if dynamic_instruction:
        llm_request.append_instructions([dynamic_instruction])
    ...
```

On turn N, `llm_request.contents` contains the full session event history (placed there by ADK's `contents.py` request processor before `before_model_callback` fires). So `dynamic_instruction` was the concatenation of every user message, model response, and tool result -- potentially megabytes of text -- all duplicated into `system_instruction`.

## After (the fix)

`_extract_adk_dynamic_instruction` is deleted. `reasoning_before_model` is now observe-only -- it reads system_instruction length and content count for token accounting, stores request metadata on the agent, and returns `None` without modifying the request:

```python
def reasoning_before_model(callback_context, llm_request):
    """Record per-invocation token accounting.

    This callback does NOT modify system_instruction or contents. It only
    reads them for token accounting and stores request metadata on the agent
    for the ObservabilityPlugin.
    """
    llm_request.config = llm_request.config or types.GenerateContentConfig()
    contents = llm_request.contents or []

    system_instruction_text = _extract_system_instruction_text(llm_request)
    total_prompt_chars = sum(...)
    system_chars = len(system_instruction_text)
    content_count = len(contents)

    # Store on agent, not session state
    inv, agent = _agent_runtime(callback_context)
    request_meta = { ... }
    object.__setattr__(agent, "_rlm_pending_request_meta", request_meta)
    return None
```

`reasoning_test_state_hook` comment updated to clarify that the patched dict stays in contents where the model reads it directly -- not relocated to system_instruction.

## Verification commands

### 1. Run the 5 new no-duplication tests

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_reasoning_callback_no_duplication.py -x -q -o "addopts="
```

Expected: 5 passed.

### 2. Confirm `_extract_adk_dynamic_instruction` no longer exists in reasoning.py

```bash
grep -c "_extract_adk_dynamic_instruction" rlm_adk/callbacks/reasoning.py
```

Expected output: `0`.

### 3. Confirm `append_instructions` is not called in reasoning_before_model

```bash
grep -c "append_instructions" rlm_adk/callbacks/reasoning.py
```

Expected output: `0`.

## Verification Checklist

- [ ] 5 new tests in `test_reasoning_callback_no_duplication.py` pass
- [ ] `_extract_adk_dynamic_instruction` does not exist in `reasoning.py` (grep returns 0)
- [ ] `append_instructions` is not called in `reasoning.py` (grep returns 0)
- [ ] `reasoning_before_model` returns `None` (observe-only, no request mutation)
- [ ] `system_chars` in token accounting reflects only the static instruction, not inflated by content duplication
