# BUG-10: reasoning_before_model prepends `\n\n` to empty system_instruction

## Location

`rlm_adk/callbacks/reasoning.py` line 114 (inside `reasoning_before_model`)

## Description

When a `system` role message exists in `message_history`, the callback appends it to `system_instruction_text` unconditionally with a `"\n\n"` prefix:

```python
if role == "system":
    if content_text:
        system_instruction_text += "\n\n" + content_text
    continue
```

When `system_instruction_text` is empty (no static instruction or dynamic instruction was set by ADK), the result is `"\n\nYou are helpful."` instead of `"You are helpful."`.

## Failing Test

`tests_rlm_adk/test_adk_callbacks.py::TestReasoningBeforeModel::test_system_messages_become_system_instruction`

```python
def test_system_messages_become_system_instruction(self):
    state = {
        TEMP_MESSAGE_HISTORY: [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ],
    }
    ctx = _make_callback_context(state)
    request = LlmRequest(model="test", contents=[])

    reasoning_before_model(ctx, request)

    assert len(request.contents) == 1  # only user, system is separate
    assert request.config.system_instruction == "You are helpful."
    #      actual: "\n\nYou are helpful."
```

## Fix

Guard the `"\n\n"` separator on whether `system_instruction_text` is non-empty:

```python
if role == "system":
    if content_text:
        if system_instruction_text:
            system_instruction_text += "\n\n" + content_text
        else:
            system_instruction_text = content_text
    continue
```

The same pattern is already correctly used at line 94-98 for `dynamic_instruction` appending.

## Impact

Low in practice — in normal operation, `static_instruction` is always set (to `RLM_STATIC_INSTRUCTION`), so `system_instruction_text` is never empty when a system message arrives. The bug only manifests when the callback is invoked without ADK having set a static instruction first, which is the test's scenario.
