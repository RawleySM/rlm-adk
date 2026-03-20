"""Experimental after_model_callback using LlmResponse.custom_metadata.

This callback proves that ADK's custom_metadata field on LlmResponse can carry
all the metadata currently encoded in LLMResult + depth-scoped state keys.

It writes ONLY to llm_response.custom_metadata (the new lineage path).
The old depth-scoped state-key channel has been removed — those constants
no longer exist in rlm_adk.state.

Returns None (observe-only, does not alter the response).
"""

from __future__ import annotations

from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.genai import types


def _extract_response_text(llm_response: LlmResponse) -> tuple[str, str]:
    """Split visible output text from hidden thought text.

    Mirrors the logic in rlm_adk/callbacks/reasoning.py _extract_response_text.
    """
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
    """Return the current reasoning depth tagged by the orchestrator.

    Mirrors the logic in rlm_adk/callbacks/reasoning.py _reasoning_depth.
    """
    agent = getattr(callback_context, "_invocation_context", None)
    agent_obj = getattr(agent, "agent", None) if agent else None
    depth = getattr(agent_obj, "_rlm_depth", 0)
    return depth if isinstance(depth, int) else 0


def _usage_int(usage: Any, attr: str) -> int:
    """Return an integer usage field, guarding against None/MagicMock values."""
    value = getattr(usage, attr, 0)
    return value if isinstance(value, int) else 0


def experimental_after_model_callback(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """Experimental after_model_callback using custom_metadata for metadata transport.

    Sets llm_response.custom_metadata with all fields previously carried by
    LLMResult and depth-scoped state keys.

    Returns None (observe-only).
    """
    # --- Extract depth ---
    depth = _reasoning_depth(callback_context)

    # --- Extract response text (visible + thought) ---
    visible_text, thought_text = _extract_response_text(llm_response)

    # --- Extract finish reason ---
    finish_reason = getattr(
        getattr(llm_response, "finish_reason", None), "name", None
    )

    # --- Extract token counts from usage_metadata ---
    usage = llm_response.usage_metadata
    if usage:
        input_tokens = _usage_int(usage, "prompt_token_count")
        output_tokens = _usage_int(usage, "candidates_token_count")
        thought_tokens = _usage_int(usage, "thoughts_token_count")
    else:
        input_tokens = 0
        output_tokens = 0
        thought_tokens = 0

    # --- custom_metadata on LlmResponse (sole transport channel) ---
    llm_response.custom_metadata = {
        "rlm_depth": depth,
        "visible_output_text": visible_text,
        "thought_text": thought_text,
        "finish_reason": finish_reason,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thoughts_tokens": thought_tokens,
    }

    return None
