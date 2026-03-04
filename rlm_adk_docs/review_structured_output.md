# Structured Output & BUG-13 Review

Review of the plan's structured output proposal (Phases 0 and 3) and investigation of BUG-13 monkey-patch alternatives.

**ADK version**: 1.25.0
**Reviewer**: structured-output-expert
**Date**: 2026-03-04

---

## 1. BUG-13 Analysis

### Root Cause (confirmed by ADK source inspection)

BUG-13 occurs in `base_llm_flow.py:848-858` (`_postprocess_handle_function_calls_async`). After ANY function call response is yielded, ADK unconditionally checks:

```python
if json_response := _output_schema_processor.get_structured_model_response(
    function_response_event
):
    final_event = _output_schema_processor.create_final_model_response_event(
        invocation_context, json_response
    )
    yield final_event
```

`get_structured_model_response` matches ANY function_response with `name == 'set_model_response'`, regardless of content. When `ReflectAndRetryToolPlugin` returns a `ToolFailureResponse` (retry guidance) via `set_model_response`, this code creates a `final_event` with `is_final_response() == True`. The main loop (`run_async` line 430) then breaks:

```python
if not last_event or last_event.is_final_response() or last_event.partial:
    break
```

This terminates the agent loop before the model gets its retry turn.

### Why the monkey-patch works

The current patch in `worker_retry.py` wraps `_osp.get_structured_model_response` to detect the `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel in the response JSON. When found, it returns `None` instead of the JSON string, preventing the `final_event` from being created. The agent loop continues and the model gets another turn to fix its output.

### Has ADK 1.25.0 fixed this?

**No.** The exact same pattern exists in `base_llm_flow.py` lines 848-858 (and the live variant at lines 802-812). There is no special handling for `ReflectAndRetryToolPlugin` retry responses. The `get_structured_model_response` function blindly matches on `func_response.name == 'set_model_response'` without inspecting response content.

---

## 2. ADK Documentation Evidence: output_schema + tools Coexistence

### Official ADK docs (confirmed)

The ADK docs (`adk_input_output_schema.md`) explicitly state:
> `# Cannot use tools=[get_capital_city] effectively here`

When `output_schema` is set on an `LlmAgent`.

### ADK source analysis (adk 1.25.0)

The `LlmAgent` API reference comment says:
> `output_schema: Optional[type[BaseModel]] = None   # Structured output (disables tools)`

However, ADK 1.25.0 has evolved. `_OutputSchemaRequestProcessor` (line 46) now checks:

```python
if (
    not agent.output_schema
    or not agent.tools
    or can_use_output_schema_with_tools(agent.canonical_model)
):
    return  # Do nothing
```

If the agent has BOTH `output_schema` and `tools`, and the model does NOT natively support output_schema+tools, the processor automatically adds `SetModelResponseTool` and injects an instruction. If the model DOES support it (Gemini 2.0+ on Vertex AI), the processor skips entirely.

### The `can_use_output_schema_with_tools` gate

```python
def can_use_output_schema_with_tools(model):
    return (
        get_google_llm_variant() == GoogleLLMVariant.VERTEX_AI
        and is_gemini_2_or_above(model_string)
    )
```

This returns `True` only on Vertex AI with Gemini 2.0+. For non-Vertex (AI Studio / direct API), it returns `False`, meaning the processor activates and adds `SetModelResponseTool` automatically.

**Implication for RLM-ADK**: If using Gemini 3 Pro Preview via AI Studio (not Vertex AI), `can_use_output_schema_with_tools` returns `False`. The processor would add `SetModelResponseTool` automatically if `output_schema` is set. But the BUG-13 termination in `_postprocess_handle_function_calls_async` still fires regardless.

---

## 3. Plan's Approach: Tool-Only, No output_schema Field

### What the plan proposes

Phase 0: Add `SetModelResponseTool(ReasoningOutput)` to reasoning_agent's `tools` list alongside `REPLTool`. Do NOT set `output_schema` on the LlmAgent constructor.

Phase 3: For children with caller schema, add `SetModelResponseTool(CallerSchema)` instead.

### Does this avoid BUG-13?

**No.** The `_postprocess_handle_function_calls_async` check (lines 848-858) runs on ALL function responses, checking `func_response.name == 'set_model_response'`. It does NOT check whether `agent.output_schema` is set. So:

1. Reasoning agent calls `set_model_response` with valid data → `get_structured_model_response` matches → creates `final_event` → loop terminates correctly (intended behavior).

2. Reasoning agent calls `set_model_response` with invalid data → `WorkerRetryPlugin` returns `ToolFailureResponse` with `name='set_model_response'` → `get_structured_model_response` matches → creates `final_event` → **loop terminates prematurely** (BUG-13).

**The monkey-patch is still required** regardless of whether `output_schema` is set on the LlmAgent or not. The bug is in the postprocessor, not the preprocessor.

### Is the tool-only approach still correct?

**Yes**, for a different reason. The plan's approach of NOT setting `output_schema` is correct because:

1. **`output_schema` blocks tool use for non-Vertex models**: When `output_schema` is set and `can_use_output_schema_with_tools` returns `False`, the `_OutputSchemaRequestProcessor` adds its own `SetModelResponseTool` AND an instruction telling the model to use it for final output. This could conflict with the manually-added `SetModelResponseTool` (duplicate tool).

2. **`output_key` validation behavior changes**: At `llm_agent.py:830-838`, when `output_schema` is set, ADK validates the final response text against the schema via `model_validate_json()`. If the model produces a plain text response (via REPLTool, not set_model_response), this validation would fail. Without `output_schema`, the raw text is stored as-is.

3. **Model can freely choose between tools**: Without `output_schema`, the model can call `execute_code` multiple times, then call `set_model_response` when ready. With `output_schema`, ADK injects an instruction biasing toward immediate structured output.

### What gets stored in output_key?

Without `output_schema` on the LlmAgent:
- When model calls `set_model_response` → `get_structured_model_response` creates final_event with JSON text → `output_key` stores the raw JSON string
- When model produces plain text (e.g., after exhausting REPL calls) → `output_key` stores the raw text

The orchestrator already handles both cases (`orchestrator.py:588-601`): tries dict, then JSON parse, then plain text, then regex fallback.

---

## 4. after_tool_callback on Reasoning Agent (vs Workers)

### Current worker behavior

`make_worker_tool_callbacks` returns `(after_tool_cb, on_tool_error_cb)`. The `after_tool_cb`:
1. Checks `tool.name == "set_model_response"` before storing structured result
2. Stores validated dict on `agent._structured_result`
3. Delegates to `WorkerRetryPlugin.after_tool_callback` for error detection

### Will this work on reasoning_agent?

**Yes, with a caveat.** The callback checks `tool.name` before acting, so it correctly ignores `execute_code` (REPLTool) calls. For `set_model_response` calls, it captures the structured result. However:

**Caveat**: The `after_tool_cb` stores the result on `tool_context._invocation_context.agent._structured_result`. For workers, this was read by dispatch.py after the worker completed. For the reasoning_agent, nobody reads `_structured_result` — the orchestrator reads from `output_key` state instead.

This means `_structured_result` on the reasoning_agent is harmless but unused. The actual data flow is:
1. Model calls `set_model_response` → ADK runs the tool
2. `after_tool_cb` fires → stores on `_structured_result` (unused) + checks for errors
3. `get_structured_model_response` creates `final_event` with JSON text
4. `output_key` mechanism stores JSON text in `state["reasoning_output"]`
5. Orchestrator reads `state["reasoning_output"]`

This is correct. The `after_tool_cb` serves two purposes on the reasoning_agent:
- Error detection (empty values) → triggers retry via `WorkerRetryPlugin`
- Structured result capture → unused but harmless

### on_tool_error_cb on reasoning_agent

The `on_tool_error_cb` only intercepts errors from `set_model_response` (line 140: `if tool.name != _SET_MODEL_RESPONSE_TOOL_NAME: return None`). Errors from `execute_code` (REPLTool) are passed through normally. This is correct.

---

## 5. output_key + set_model_response Interaction

**Question**: Does ADK automatically write the structured response to `output_key`?

**Answer**: Yes, but as a JSON string, not a dict. The flow:

1. `set_model_response` tool is called → function response yielded
2. `get_structured_model_response` extracts JSON string from function response
3. `create_final_model_response_event` creates a text Content event with JSON string
4. `_maybe_save_output_to_state` (llm_agent.py:818-839) fires on the final event
5. Since `output_schema` is NOT set on the agent, the text is stored as-is (raw JSON string)
6. If `output_schema` WERE set, it would parse via `model_validate_json` and store as dict

For the plan's approach (no `output_schema`), `state["reasoning_output"]` will contain a JSON string like `'{"final_answer": "...", "reasoning_summary": "..."}'`. The orchestrator already handles this case at line 593-595:

```python
parsed = json.loads(raw)
final_answer = parsed.get('final_answer', raw)
```

---

## 6. Specific Recommendations for Plan Amendments

### R1: Keep the monkey-patch (REQUIRED)

The BUG-13 monkey-patch in `worker_retry.py` is **still required** under the plan's approach. The postprocessor termination bug exists at the `_postprocess_handle_function_calls_async` level, independent of whether `output_schema` is set on the LlmAgent. The plan should explicitly state this dependency.

### R2: Confirm tool-only approach is correct (VALIDATED)

The plan's approach of adding `SetModelResponseTool` as a tool without setting `output_schema` on the LlmAgent is correct. This prevents:
- Duplicate `SetModelResponseTool` injection by `_OutputSchemaRequestProcessor`
- `model_validate_json` failure on plain text responses
- Instruction injection biasing the model toward immediate structured output

### R3: Orchestrator output parsing handles both paths (VALIDATED)

The existing orchestrator parsing logic (`orchestrator.py:586-601`) already handles:
- Dict (if `output_schema` were set → validated dict stored)
- JSON string (plan's approach → `json.loads` + `get('final_answer')`)
- Plain text (fallback → `find_final_answer` regex)

The plan's suggestion to use `ctx.session.state.get(self.reasoning_agent.output_key or "reasoning_output", "")` is a good improvement for robustness.

### R4: Phase 3 child output_schema wiring needs care

When `llm_query_async(prompt, output_schema=MySchema)` creates a child orchestrator:
- The child's reasoning_agent should get `SetModelResponseTool(MySchema)` (not `ReasoningOutput`)
- The child's `output_key` state will contain a JSON string of `MySchema`
- The parent dispatch reads this and creates `LLMResult(json_text, parsed=json.loads(json_text))`
- The monkey-patch must handle retry responses from children too (it does — it's process-global)

### R5: No changes needed for `_structured_result` on reasoning_agent

The `_structured_result` attribute set by `after_tool_cb` is harmless on the reasoning_agent. The orchestrator reads from `output_key` state, not from `_structured_result`. No cleanup needed.

### R6: Verify Gemini model compatibility

`can_use_output_schema_with_tools` returns `True` only on Vertex AI + Gemini 2.0+. If RLM-ADK is used on Vertex AI with a qualifying model AND `output_schema` is set, ADK would skip `_OutputSchemaRequestProcessor` and set `output_schema` directly on the model config. This would cause Gemini to return structured JSON as regular text (not via tool call), bypassing `set_model_response` entirely. The plan's tool-only approach avoids this ambiguity.

---

## 7. Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| BUG-13 monkey-patch breaks with ADK update | Medium | Medium | Guard with `_rlm_patched` flag + ImportError fallback. Pin ADK version in requirements. |
| Duplicate SetModelResponseTool if output_schema accidentally set | Low | Low | Plan explicitly says not to set output_schema. Add assertion in orchestrator. |
| output_key stores JSON string instead of dict | Low | N/A | Orchestrator already handles both. No change needed. |
| ReflectAndRetryToolPlugin retry fires for execute_code errors | None | None | `on_tool_error_cb` guards on `tool.name != "set_model_response"`. |
| Process-global monkey-patch affects unrelated ADK agents in same process | Low | Low | Patch only suppresses REFLECT_AND_RETRY sentinel responses. Normal set_model_response calls pass through. |
| ADK future version adds native retry-aware postprocessor | Low | Medium | Would make patch a no-op (idempotent check on `_rlm_patched`). |

---

## 8. Summary

1. **BUG-13 monkey-patch is still required** — the plan's tool-only approach does not avoid it
2. **Tool-only approach (no output_schema field) is correct** — avoids duplicate tools, validation failures, and instruction conflicts
3. **after_tool_callback works correctly on reasoning_agent** — guards on tool.name, harmless _structured_result storage
4. **output_key interaction is correct** — stores JSON string, orchestrator parses it
5. **No ADK version-specific blockers** — ADK 1.25.0 behavior is consistent with the plan's assumptions
6. **Phase 3 child wiring is sound** — process-global patch covers children, output_key state isolation via depth_key works
