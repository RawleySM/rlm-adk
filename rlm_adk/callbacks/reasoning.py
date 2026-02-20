"""Reasoning Agent callbacks.

before_model_callback: Injects the current message_history from state
    into the LlmRequest contents.  Preserves ADK-set system_instruction (from
    static_instruction) and relocates the ADK-resolved dynamic instruction
    (from instruction= template) into system_instruction to maintain proper
    Gemini user/model role alternation in contents.
    Sets reasoning_call_start timestamp.
    The agent's include_contents='none' means conversation is injected here.

after_model_callback: Extracts the text response and writes it to
    last_reasoning_response in the state.
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


def reasoning_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Inject the current message_history into the LlmRequest.

    ADK has already set:
      - system_instruction from static_instruction (the stable system prompt)
      - resolved instruction template in contents (dynamic context metadata)

    This callback:
      1. Preserves system_instruction from static_instruction
      2. Extracts the resolved dynamic instruction from contents
      3. Appends the dynamic metadata to system_instruction
      4. Injects conversation messages from message_history into contents
    """
    callback_context.state[REASONING_CALL_START] = time.perf_counter()

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

    # --- Build contents from message_history ---
    # message_history now contains only conversation messages (user prompts,
    # model responses, REPL output).  System prompt and metadata are handled
    # above via ADK's static_instruction and instruction parameters.
    message_history = callback_context.state.get(MESSAGE_HISTORY, [])
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
    history_msg_count = sum(1 for msg in message_history if msg.get("role") != "system")

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
    """Extract the text response and store in state, with token accounting."""
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
