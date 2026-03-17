"""Reasoning Agent callbacks.

before_model_callback: Merges the ADK-resolved dynamic instruction into
    system_instruction (from static_instruction).  Records per-invocation
    token accounting.  ADK manages contents (tool call/response history)
    via include_contents='default'.

after_model_callback: Records per-invocation token accounting from
    usage_metadata.  The collapsed orchestrator reads the final answer
    from the output_key ("reasoning_output").

reasoning_test_state_hook: Test-only before_model_callback that writes a
    guillemet-marked dict to callback_context.state under the key
    ``cb_reasoning_context``.  Compose with reasoning_before_model in
    provider-fake fixtures to verify the state → systemInstruction path.
"""

from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.state import (
    CB_REASONING_CONTEXT,
    CB_TOOL_CONTEXT,
    CONTEXT_WINDOW_SNAPSHOT,
    ITERATION_COUNT,
    REASONING_FINISH_REASON,
    REASONING_INPUT_TOKENS,
    REASONING_OUTPUT_TOKENS,
    REASONING_PROMPT_CHARS,
    REASONING_SUMMARY,
    REASONING_SYSTEM_CHARS,
    REASONING_THOUGHT_TEXT,
    REASONING_THOUGHT_TOKENS,
    REASONING_VISIBLE_OUTPUT_TEXT,
    depth_key,
)


def _extract_system_instruction_text(llm_request: LlmRequest) -> str:
    """Extract system_instruction text that ADK set from static_instruction."""
    if not llm_request.config or not llm_request.config.system_instruction:
        return ""
    si = llm_request.config.system_instruction
    if isinstance(si, str):
        return si
    # system_instruction may be a Content object with parts
    if isinstance(si, types.Content) and si.parts:
        return "".join(
            p.text for p in si.parts
            if isinstance(p, types.Part) and p.text
        )
    return str(si)


def _extract_adk_dynamic_instruction(llm_request: LlmRequest) -> str:
    """Extract the resolved instruction template that ADK placed in contents.

    When both static_instruction and instruction are set, ADK resolves the
    instruction template and appends it to contents as a user Content.
    We extract and remove it so it can be relocated to system_instruction.
    """
    dynamic_text = ""
    if llm_request.contents:
        for content in llm_request.contents:
            if content.parts:
                for part in content.parts:
                    if part.text:
                        dynamic_text += part.text
    return dynamic_text.strip()


def _extract_response_text(llm_response: LlmResponse) -> tuple[str, str]:
    """Split visible output text from hidden thought text."""
    output_parts: list[str] = []
    thought_parts: list[str] = []
    if llm_response.content and llm_response.content.parts:
        for part in llm_response.content.parts:
            if not isinstance(part, types.Part) or not part.text:
                continue
            if getattr(part, "thought", False):
                thought_parts.append(part.text)
            else:
                output_parts.append(part.text)
    return "".join(output_parts), "".join(thought_parts)


def _reasoning_depth(callback_context: CallbackContext) -> int:
    """Return the current reasoning depth tagged by the orchestrator."""
    agent = getattr(callback_context, "_invocation_context", None)
    agent_obj = getattr(agent, "agent", None) if agent else None
    depth = getattr(agent_obj, "_rlm_depth", 0)
    return depth if isinstance(depth, int) else 0


def _usage_int(usage: Any, attr: str) -> int:
    """Return an integer usage field, guarding against MagicMock values in tests."""
    value = getattr(usage, attr, 0)
    return value if isinstance(value, int) else 0


def reasoning_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Merge dynamic instruction into system_instruction.

    ADK has already set:
      - system_instruction from static_instruction (the stable system prompt)
      - resolved instruction template in contents (dynamic context metadata)

    This callback:
      1. Preserves system_instruction from static_instruction
      2. Extracts the resolved dynamic instruction from contents
      3. Appends the dynamic metadata to system_instruction
      4. Leaves contents as ADK manages them (include_contents='default')
      5. Records per-invocation token accounting
    """
    # --- Extract what ADK set ---
    static_si = _extract_system_instruction_text(llm_request)
    dynamic_instruction = _extract_adk_dynamic_instruction(llm_request)

    # --- Build system_instruction: static prompt + dynamic metadata ---
    system_instruction_text = static_si
    if dynamic_instruction:
        if system_instruction_text:
            system_instruction_text += "\n\n" + dynamic_instruction
        else:
            system_instruction_text = dynamic_instruction

    # ADK manages contents via include_contents='default'
    contents = llm_request.contents or []

    if system_instruction_text:
        llm_request.config = llm_request.config or types.GenerateContentConfig()
        llm_request.config.system_instruction = system_instruction_text

    # --- Per-invocation token accounting ---
    total_prompt_chars = sum(
        len(part.text or "")
        for content in contents
        if content.parts
        for part in content.parts
    )
    system_chars = len(system_instruction_text)
    content_count = len(contents)

    callback_context.state[REASONING_PROMPT_CHARS] = total_prompt_chars
    callback_context.state[REASONING_SYSTEM_CHARS] = system_chars
    # Read depth tag set by orchestrator (default 0)
    _depth = _reasoning_depth(callback_context)

    callback_context.state[CONTEXT_WINDOW_SNAPSHOT] = {
        "agent_type": "reasoning",
        "depth": _depth,
        "content_count": content_count,
        "prompt_chars": total_prompt_chars,
        "system_chars": system_chars,
        "history_msg_count": content_count,
        "total_chars": total_prompt_chars + system_chars,
    }

    return None


def reasoning_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Record per-invocation token accounting from usage_metadata.

    The collapsed orchestrator reads the final answer from the output_key
    ("reasoning_output") instead of LAST_REASONING_RESPONSE state.
    """
    # --- Per-invocation token accounting from usage_metadata ---
    usage = llm_response.usage_metadata
    depth = _reasoning_depth(callback_context)
    visible_text, thought_text = _extract_response_text(llm_response)
    callback_context.state[depth_key(REASONING_VISIBLE_OUTPUT_TEXT, depth)] = visible_text
    callback_context.state[depth_key(REASONING_THOUGHT_TEXT, depth)] = thought_text
    finish_reason = getattr(getattr(llm_response, "finish_reason", None), "name", None)
    if finish_reason is not None:
        callback_context.state[depth_key(REASONING_FINISH_REASON, depth)] = finish_reason
    if usage:
        callback_context.state[depth_key(REASONING_INPUT_TOKENS, depth)] = (
            _usage_int(usage, "prompt_token_count")
        )
        callback_context.state[depth_key(REASONING_OUTPUT_TOKENS, depth)] = (
            _usage_int(usage, "candidates_token_count")
        )
        callback_context.state[depth_key(REASONING_THOUGHT_TOKENS, depth)] = (
            _usage_int(usage, "thoughts_token_count")
        )
    else:
        callback_context.state[depth_key(REASONING_THOUGHT_TOKENS, depth)] = 0
        callback_context.state[depth_key(REASONING_INPUT_TOKENS, depth)] = 0
        callback_context.state[depth_key(REASONING_OUTPUT_TOKENS, depth)] = 0

    if visible_text.lstrip().startswith("{"):
        try:
            import json

            parsed = json.loads(visible_text)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            callback_context.state[depth_key(REASONING_SUMMARY, depth)] = (
                parsed.get("reasoning_summary", "") or ""
            )

    # Return None -- observe only, don't alter the response
    return None


# ---------------------------------------------------------------------------
# Test-only hook: state dict → systemInstruction verification
# ---------------------------------------------------------------------------


def reasoning_test_state_hook(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Write a guillemet-marked dict to state for provider-fake verification.

    Writes ``CB_REASONING_CONTEXT`` to ``callback_context.state`` containing
    a structured dict with markers.  When the fixture's dynamic instruction
    includes ``{cb_reasoning_context?}``, ADK resolves the template and the
    dict's ``str()`` repr flows into systemInstruction — verifiable in
    captured request bodies.

    Compose with the production callback by setting both as a chain::

        # In contract_runner or test setup:
        agent.before_model_callback = reasoning_test_state_hook
        # Then call reasoning_before_model manually, or chain them.

    Or use as a standalone before_model_callback for isolated testing.
    """
    iteration = callback_context.state.get(ITERATION_COUNT, 0)
    context_dict = {
        "«CB_REASONING_STATE_START»": True,
        "hook": "reasoning_test_state_hook",
        "iteration": iteration,
        "agent": "reasoning_agent",
        "«CB_REASONING_STATE_END»": True,
    }
    callback_context.state[CB_REASONING_CONTEXT] = context_dict

    # Patch the already-resolved template text in contents so the dict
    # appears on the FIRST iteration too (ADK resolves {cb_reasoning_context?}
    # before before_model_callback fires, so iter 0 would otherwise be empty).
    # reasoning_before_model runs next and extracts all content text into
    # systemInstruction, so this patch flows through automatically.
    dict_str = str(context_dict)
    placeholder = "Callback state: \n"
    if llm_request.contents:
        for content in llm_request.contents:
            if content.parts:
                for part in content.parts:
                    if part.text and placeholder in part.text:
                        part.text = part.text.replace(
                            placeholder, f"Callback state: {dict_str}\n", 1,
                        )
    return None


# ---------------------------------------------------------------------------
# Test-only hook: tool state dict → systemInstruction verification
# ---------------------------------------------------------------------------


def tool_test_state_hook(
    tool: Any, args: dict, tool_context: Any,
) -> dict | None:
    """Write a guillemet-marked dict to state before each REPL tool execution.

    Writes ``CB_TOOL_CONTEXT`` to ``tool_context.state`` containing a
    structured dict with markers.  When the fixture's dynamic instruction
    includes ``{cb_tool_context?}``, ADK resolves the template on the *next*
    reasoning LLM call and the dict's ``str()`` repr flows into
    systemInstruction — verifiable in captured request bodies.

    The dict is available starting from the reasoning call *after* the first
    tool execution (call 2 in the comprehensive fixture, since call 0 has no
    prior tool execution).

    Wire on the reasoning agent as ``before_tool_callback``::

        object.__setattr__(reasoning_agent, "before_tool_callback", tool_test_state_hook)
    """
    tool_name = getattr(tool, "name", "unknown")
    tool_context.state[CB_TOOL_CONTEXT] = {
        "«CB_TOOL_STATE_START»": True,
        "hook": "tool_test_state_hook",
        "tool_name": tool_name,
        "args_keys": sorted(args.keys()) if args else [],
        "«CB_TOOL_STATE_END»": True,
    }
    return None  # Proceed with normal tool execution
