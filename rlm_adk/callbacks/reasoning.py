"""Reasoning Agent callbacks.

before_model_callback: Injects the current message_history from temp:message_history
    into the LlmRequest contents. Sets temp:reasoning_call_start timestamp.
    The agent's include_contents='none' means prompts are injected entirely here.

after_model_callback: Extracts the text response and writes it to
    temp:last_reasoning_response in the state.
"""

import time

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.state import TEMP_LAST_REASONING_RESPONSE, TEMP_MESSAGE_HISTORY, TEMP_REASONING_CALL_START


def reasoning_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Inject the current message_history into the LlmRequest.

    Reads temp:message_history (list of dicts with role/content) from state
    and converts them into google.genai.types.Content objects for the LLM.
    """
    callback_context.state[TEMP_REASONING_CALL_START] = time.perf_counter()

    message_history = callback_context.state.get(TEMP_MESSAGE_HISTORY, [])

    contents = []
    system_parts = []

    for msg in message_history:
        role = msg.get("role", "user")
        content_text = msg.get("content", "")

        if role == "system":
            system_parts.append(content_text)
            continue

        # Map "assistant" to "model" for Gemini API
        adk_role = "model" if role == "assistant" else "user"
        contents.append(
            types.Content(
                role=adk_role,
                parts=[types.Part.from_text(text=content_text)],
            )
        )

    llm_request.contents = contents

    # Set system instruction from accumulated system messages
    if system_parts:
        llm_request.config = llm_request.config or types.GenerateContentConfig()
        llm_request.config.system_instruction = "\n\n".join(system_parts)

    # Return None to proceed with the LLM call (amend pattern)
    return None


def reasoning_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Extract the text response and store in state."""
    response_text = ""
    if llm_response.content and llm_response.content.parts:
        response_text = "".join(
            part.text for part in llm_response.content.parts if part.text and not part.thought
        )

    callback_context.state[TEMP_LAST_REASONING_RESPONSE] = response_text

    # Return None -- observe only, don't alter the response
    return None
