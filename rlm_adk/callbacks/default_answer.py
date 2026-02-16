"""Default Answer Agent callbacks.

before_model_callback: Injects the full accumulated message_history plus a
    "provide your best final answer" suffix into the LlmRequest.

after_model_callback: Records the default answer and marks
    temp:used_default_answer = True for observability.
"""

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.state import TEMP_MESSAGE_HISTORY, TEMP_USED_DEFAULT_ANSWER

# Key where the default answer agent writes its output
DEFAULT_ANSWER_OUTPUT_KEY = "default_answer"


def default_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Inject the full message history for default answer generation.

    Reads temp:message_history from state and converts to Content objects.
    Appends a "provide final answer" prompt.
    """
    message_history = callback_context.state.get(TEMP_MESSAGE_HISTORY, [])

    contents = []
    system_parts = []

    for msg in message_history:
        role = msg.get("role", "user")
        content_text = msg.get("content", "")

        if role == "system":
            system_parts.append(content_text)
            continue

        adk_role = "model" if role == "assistant" else "user"
        contents.append(
            types.Content(
                role=adk_role,
                parts=[types.Part.from_text(text=content_text)],
            )
        )

    # Append the "provide final answer" instruction
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(
                text="You have used all your iterations. Please provide your best final answer "
                "to the user's question based on all the information gathered so far."
            )],
        )
    )

    llm_request.contents = contents

    if system_parts:
        llm_request.config = llm_request.config or types.GenerateContentConfig()
        llm_request.config.system_instruction = "\n\n".join(system_parts)

    return None


def default_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Record the default answer and mark it as used."""
    response_text = ""
    if llm_response.content and llm_response.content.parts:
        response_text = "".join(
            part.text for part in llm_response.content.parts if part.text and not part.thought
        )

    callback_context.state[DEFAULT_ANSWER_OUTPUT_KEY] = response_text
    callback_context.state[TEMP_USED_DEFAULT_ANSWER] = True

    return None
