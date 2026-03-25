# GAP-CB-006: `reasoning_before_model` token accounting counts duplicated content

**Severity**: MEDIUM
**Category**: callback-lifecycle
**Files**: `rlm_adk/callbacks/reasoning.py` (lines 113-172)

## Problem

`reasoning_before_model` computes `total_prompt_chars` by summing all text parts in `llm_request.contents` (lines 152-157). It then computes `system_chars` from the system_instruction (line 158). But by this point, `reasoning_before_model` has already appended the extracted dynamic instruction (which is actually ALL contents text, per GAP-CB-001) to system_instruction.

This means:
1. `system_chars` includes the duplicated content text (since it was just appended)
2. `total_prompt_chars` includes the original content text
3. The sum `system_chars + total_prompt_chars` double-counts a significant portion

Even ignoring GAP-CB-001, the accounting calls `_extract_system_instruction_text` AFTER `append_instructions` has already modified system_instruction, so the system_chars value includes any text appended by the callback itself -- a self-referential measurement.

## Evidence

```python
def reasoning_before_model(callback_context, llm_request):
    dynamic_instruction = _extract_adk_dynamic_instruction(llm_request)  # ALL contents text
    # ...
    if dynamic_instruction:
        llm_request.append_instructions([dynamic_instruction])  # Appends to system_instruction

    # --- Token accounting AFTER modification ---
    system_instruction_text = _extract_system_instruction_text(llm_request)  # Includes appended text
    total_prompt_chars = sum(...)  # Original contents still there
    system_chars = len(system_instruction_text)  # Includes duplicated text
```

## Impact

Token accounting metadata (`prompt_chars`, `system_chars`) stored on the agent via `_rlm_pending_request_meta` is inflated. This affects:
- ObservabilityPlugin readings
- SqliteTracingPlugin telemetry rows
- Any cost estimation based on these values

The actual LLM request is unaffected (ADK sends what's in llm_request to the model), so this is a telemetry accuracy issue, not a correctness bug.

## Suggested Fix

Compute token accounting BEFORE modifying `llm_request`:

```python
def reasoning_before_model(callback_context, llm_request):
    # --- Token accounting BEFORE modification ---
    system_instruction_text = _extract_system_instruction_text(llm_request)
    contents = llm_request.contents or []
    total_prompt_chars = sum(
        len(part.text or "")
        for content in contents if content.parts
        for part in content.parts
    )
    system_chars = len(system_instruction_text)

    # --- Then modify ---
    dynamic_instruction = _extract_adk_dynamic_instruction(llm_request)
    if dynamic_instruction:
        llm_request.append_instructions([dynamic_instruction])

    # ... store accounting ...
```

Or, better yet, fix GAP-CB-001 first (stop extracting/appending all content text), then the accounting naturally becomes accurate.
