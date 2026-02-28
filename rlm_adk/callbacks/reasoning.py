"""Reasoning Agent callbacks.

before_model_callback: Merges the ADK-resolved dynamic instruction into
    system_instruction (from static_instruction).  Sets reasoning_call_start
    timestamp and per-invocation token accounting.

    Dual-mode behavior:
    - Legacy mode (include_contents='none'): Injects message_history from
      state into llm_request.contents.  The orchestrator writes
      MESSAGE_HISTORY to state each iteration.
    - Tool-calling mode (include_contents='default'): ADK manages contents
      (tool call/response history) automatically.  The callback detects
      this by checking whether the agent's tools list is non-empty and
      leaves contents untouched.

after_model_callback: Extracts text response to LAST_REASONING_RESPONSE
    for backward compatibility with the legacy orchestrator loop.
    Records per-invocation token accounting from usage_metadata.
"""

import time

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.state import (
    CONTEXT_WINDOW_SNAPSHOT,
    LAST_REASONING_RESPONSE,
    MESSAGE_HISTORY,
    REASONING_CALL_START,
    REASONING_CONTENT_COUNT,
    REASONING_HISTORY_MSG_COUNT,
    REASONING_INPUT_TOKENS,
    REASONING_OUTPUT_TOKENS,
    REASONING_PROMPT_CHARS,
    REASONING_SYSTEM_CHARS,
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


def _is_tool_calling_mode(callback_context: CallbackContext) -> bool:
    """Detect whether the reasoning agent is in tool-calling mode.

    In tool-calling mode the agent has tools configured and ADK manages
    conversation history via include_contents='default'.  The callback
    should NOT overwrite llm_request.contents.

    In legacy mode the agent has no tools, uses include_contents='none',
    and the callback must inject message_history into contents.
    """
    try:
        agent = callback_context._invocation_context.agent
        tools = getattr(agent, "tools", None)
        # Check that tools is an actual list (not a MagicMock) and non-empty
        return isinstance(tools, list) and len(tools) > 0
    except (AttributeError, TypeError):
        return False


def reasoning_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Merge dynamic instruction into system_instruction, optionally inject contents.

    ADK has already set:
      - system_instruction from static_instruction (the stable system prompt)
      - resolved instruction template in contents (dynamic context metadata)

    This callback:
      1. Preserves system_instruction from static_instruction
      2. Extracts the resolved dynamic instruction from contents
      3. Appends the dynamic metadata to system_instruction
      4. In legacy mode: injects conversation messages from message_history
         into contents (Phase 3 deprecation -- will be removed in Phase 4)
      5. In tool-calling mode: leaves contents as ADK set them
      6. Records per-invocation token accounting
    """
    callback_context.state[REASONING_CALL_START] = time.perf_counter()

    tool_calling = _is_tool_calling_mode(callback_context)

    # --- Extract what ADK set ---
    # static_instruction -> system_instruction (stable system prompt)
    static_si = _extract_system_instruction_text(llm_request)
    # instruction template -> resolved and placed in contents as user content
    dynamic_instruction = _extract_adk_dynamic_instruction(llm_request)

    # --- Build system_instruction: static prompt + dynamic metadata ---
    system_instruction_text = static_si
    if dynamic_instruction:
        if system_instruction_text:
            system_instruction_text += "\n\n" + dynamic_instruction
        else:
            system_instruction_text = dynamic_instruction

    # --- Build contents (legacy mode only) ---
    # In legacy mode (no tools), the orchestrator writes MESSAGE_HISTORY
    # to state each iteration.  This callback reads it and builds contents.
    # In tool-calling mode, ADK manages contents -- leave them as-is.
    message_history = callback_context.state.get(MESSAGE_HISTORY, [])

    if not tool_calling:
        contents = []
        for msg in message_history:
            role = msg.get("role", "user")
            content_text = msg.get("content", "")

            if role == "system":
                # Legacy safety: if a system message is still present in
                # message_history, append it to system_instruction.
                if content_text:
                    system_instruction_text += "\n\n" + content_text
                continue

            adk_role = "model" if role == "assistant" else "user"
            contents.append(
                types.Content(
                    role=adk_role,
                    parts=[types.Part.from_text(text=content_text)],
                )
            )
        llm_request.contents = contents
    else:
        # Tool-calling mode: ADK manages contents, don't overwrite
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
    history_msg_count = sum(1 for msg in message_history if msg.get("role") != "system") if not tool_calling else content_count

    callback_context.state[REASONING_PROMPT_CHARS] = total_prompt_chars
    callback_context.state[REASONING_SYSTEM_CHARS] = system_chars
    callback_context.state[REASONING_CONTENT_COUNT] = content_count
    callback_context.state[REASONING_HISTORY_MSG_COUNT] = history_msg_count
    callback_context.state[CONTEXT_WINDOW_SNAPSHOT] = {
        "agent_type": "reasoning",
        "content_count": content_count,
        "prompt_chars": total_prompt_chars,
        "system_chars": system_chars,
        "history_msg_count": history_msg_count,
        "total_chars": total_prompt_chars + system_chars,
    }

    return None


def reasoning_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Extract text response and record per-invocation token accounting.

    Writes LAST_REASONING_RESPONSE for backward compatibility with the
    legacy orchestrator loop (which reads it to extract code blocks and
    FINAL answers).  In tool-calling mode (Phase 4+) the orchestrator
    will read the output_key instead, and this write can be removed.
    """
    # Extract text response for legacy orchestrator compatibility
    response_text = ""
    if llm_response.content and llm_response.content.parts:
        response_text = "".join(
            part.text for part in llm_response.content.parts if part.text and not part.thought
        )

    callback_context.state[LAST_REASONING_RESPONSE] = response_text

    # --- Per-invocation token accounting from usage_metadata ---
    usage = llm_response.usage_metadata
    if usage:
        callback_context.state[REASONING_INPUT_TOKENS] = (
            getattr(usage, "prompt_token_count", 0) or 0
        )
        callback_context.state[REASONING_OUTPUT_TOKENS] = (
            getattr(usage, "candidates_token_count", 0) or 0
        )

    # Return None -- observe only, don't alter the response
    return None
