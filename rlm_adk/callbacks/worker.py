"""Worker LlmAgent callbacks for sub-LM dispatch.

worker_before_model: AMEND - Injects the single prompt from the dispatch closure
    into LlmRequest. Sets model override if model= was specified in llm_query().

worker_after_model: OBSERVE - Extracts text response, writes to worker's output_key.
"""

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.state import (
    TEMP_WORKER_CONTENT_COUNT,
    TEMP_WORKER_INPUT_TOKENS,
    TEMP_WORKER_OUTPUT_TOKENS,
    TEMP_WORKER_PROMPT_CHARS,
)


def worker_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Inject prompt from dispatch closure into LlmRequest.

    The dispatch closure sets worker._pending_prompt before running the agent.
    This callback reads it and sets it as the LlmRequest contents.
    """
    agent = callback_context.agent
    pending_prompt = getattr(agent, "_pending_prompt", None)

    if pending_prompt:
        if isinstance(pending_prompt, str):
            llm_request.contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=pending_prompt)],
                )
            ]
        elif isinstance(pending_prompt, list):
            # Message list format [{role: ..., content: ...}, ...]
            contents = []
            for msg in pending_prompt:
                role = msg.get("role", "user")
                adk_role = "model" if role == "assistant" else "user"
                contents.append(
                    types.Content(
                        role=adk_role,
                        parts=[types.Part.from_text(text=msg.get("content", ""))],
                    )
                )
            llm_request.contents = contents

    # --- Per-invocation token accounting ---
    total_prompt_chars = sum(
        len(part.text or "")
        for content in llm_request.contents
        if content.parts
        for part in content.parts
    )
    content_count = len(llm_request.contents)

    callback_context.state[TEMP_WORKER_PROMPT_CHARS] = total_prompt_chars
    callback_context.state[TEMP_WORKER_CONTENT_COUNT] = content_count

    return None  # Proceed with model call


def worker_after_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Extract response text and store in state under output_key, with token accounting."""
    response_text = ""
    if llm_response.content and llm_response.content.parts:
        response_text = "".join(
            part.text for part in llm_response.content.parts if part.text and not part.thought
        )

    # Write to the worker's output_key in state
    agent = callback_context.agent
    output_key = getattr(agent, "output_key", None)
    if output_key:
        callback_context.state[output_key] = response_text

    # --- Per-invocation token accounting from usage_metadata ---
    usage = llm_response.usage_metadata
    if usage:
        callback_context.state[TEMP_WORKER_INPUT_TOKENS] = (
            getattr(usage, "prompt_token_count", 0) or 0
        )
        callback_context.state[TEMP_WORKER_OUTPUT_TOKENS] = (
            getattr(usage, "candidates_token_count", 0) or 0
        )

    return None
