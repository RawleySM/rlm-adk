# GAP-CB-001: `_extract_adk_dynamic_instruction` reads entire conversation history, not just dynamic instruction

**Severity**: HIGH
**Category**: callback-lifecycle
**Files**: `rlm_adk/callbacks/reasoning.py` (lines 49-63)

## Problem

`_extract_adk_dynamic_instruction()` iterates over ALL `llm_request.contents` and concatenates ALL text from ALL parts. Its docstring says it extracts "the resolved instruction template that ADK placed in contents" but it actually extracts the entire conversation history.

By the time `reasoning_before_model` fires, `llm_request.contents` has been fully populated by the `contents.py` request processor (which runs during `_preprocess_async`). The contents processor:
1. Saves the instruction-related contents that `instructions.py` added
2. Replaces `llm_request.contents` with the full session event history
3. Re-inserts the instruction contents at the proper position

So `_extract_adk_dynamic_instruction` reads ALL of that -- every prior model response, every tool call/response, every user message, plus the dynamic instruction. It then appends this gigantic blob to `system_instruction` via `append_instructions()`.

This means the dynamic instruction text is **duplicated** (once in contents where ADK put it, once in system_instruction where the callback puts it), AND the entire conversation history is **also duplicated into system_instruction**.

## Evidence

`rlm_adk/callbacks/reasoning.py` lines 56-63:
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
```

ADK `contents.py` processor (runs before `before_model_callback`):
- Line 57: `instruction_related_contents = llm_request.contents`
- Line 61-66: `llm_request.contents = _get_contents(...)` (full history)
- Line 77-79: `_add_instructions_to_user_content(...)` (re-inserts instruction contents)

Then `reasoning_before_model` at line 144:
```python
if dynamic_instruction:
    llm_request.append_instructions([dynamic_instruction])
```

This appends concatenated text of ALL contents (history + dynamic instruction) into `system_instruction`.

## Impact

On the first turn with minimal history, this is nearly invisible -- the only content is the initial user prompt + dynamic instruction, so the duplication is small. On later turns with accumulated tool call/response history, the `dynamic_instruction` variable could be enormous (megabytes of concatenated text), all duplicated into `system_instruction`. This wastes tokens and may hit context window limits.

## Suggested Fix

Either:
1. **Remove the extraction + append entirely.** The dynamic instruction is already in contents where ADK placed it. The callback should only do token accounting, not relocate instructions. The original motivation (relocating dynamic instruction from contents to system_instruction for Gemini role alternation) may no longer be necessary since ADK 1.27's `_add_instructions_to_user_content` handles positioning.

2. **If relocation is still needed**, identify the dynamic instruction content specifically (e.g., by position -- it's the last user content added by `instructions.py`, inserted before the conversation history) rather than concatenating all content text. The instruction-related contents have a specific structure that can be identified.
