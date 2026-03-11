"""Gemini-to-OpenAI response format translator.

Translates Gemini ``generateContent`` response bodies (used in fixture JSON)
into OpenAI ``/v1/chat/completions`` format so the same fixtures can drive
both native Gemini and LiteLLM test paths.

Format references:
- Gemini: candidates[].content.parts[] with text/functionCall
- OpenAI: choices[].message with content/tool_calls
"""

from __future__ import annotations

import uuid
from typing import Any

# Gemini finishReason -> OpenAI finish_reason mapping
_FINISH_REASON_MAP: dict[str, str] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "OTHER": "stop",
}


def gemini_response_to_openai(
    gemini_body: dict[str, Any],
    model: str = "fake-model",
) -> dict[str, Any]:
    """Convert a Gemini generateContent response to OpenAI chat completions format.

    Args:
        gemini_body: The Gemini response body (with ``candidates``, ``usageMetadata``).
        model: Model name to include in the response.

    Returns:
        An OpenAI-compatible chat completions response dict.
    """
    candidates = gemini_body.get("candidates", [])
    usage_meta = gemini_body.get("usageMetadata", {})

    choices: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates):
        content_obj = candidate.get("content", {})
        parts = content_obj.get("parts", [])
        finish_reason_raw = candidate.get("finishReason", "STOP")
        finish_reason = _FINISH_REASON_MAP.get(finish_reason_raw, "stop")

        # Collect text parts and function calls
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(
                    {
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": fc.get("name", ""),
                            "arguments": _serialize_args(fc.get("args", {})),
                        },
                    }
                )

        message: dict[str, Any] = {"role": "assistant"}
        if text_parts:
            message["content"] = "".join(text_parts)
        else:
            message["content"] = None

        if tool_calls:
            message["tool_calls"] = tool_calls
            # When tool_calls present and no text, OpenAI convention is
            # finish_reason = "tool_calls"
            if not text_parts:
                finish_reason = "tool_calls"

        choices.append(
            {
                "index": idx,
                "message": message,
                "finish_reason": finish_reason,
            }
        )

    # Build usage block
    usage = {
        "prompt_tokens": usage_meta.get("promptTokenCount", 0),
        "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
        "total_tokens": usage_meta.get("totalTokenCount", 0),
    }

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "model": model,
        "choices": choices,
        "usage": usage,
    }


def gemini_error_to_openai(
    gemini_error: dict[str, Any],
    status_code: int,
) -> dict[str, Any]:
    """Convert a Gemini error response to OpenAI error format.

    Args:
        gemini_error: The Gemini error body (with ``error.code``, ``error.message``).
        status_code: HTTP status code.

    Returns:
        An OpenAI-compatible error response dict.
    """
    error = gemini_error.get("error", {})
    return {
        "error": {
            "message": error.get("message", "Unknown error"),
            "type": _status_to_openai_type(status_code),
            "code": str(error.get("code", status_code)),
        },
    }


def _serialize_args(args: Any) -> str:
    """Serialize function call arguments to JSON string."""
    import json

    if isinstance(args, str):
        return args
    return json.dumps(args)


def _status_to_openai_type(status: int) -> str:
    """Map HTTP status to OpenAI error type."""
    if status == 401:
        return "authentication_error"
    if status == 429:
        return "rate_limit_error"
    if status >= 500:
        return "server_error"
    return "invalid_request_error"
