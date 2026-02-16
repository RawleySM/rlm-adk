"""DepthGuardPlugin - Enforces max recursion depth and handles model errors.

Trigger points: before_model_callback, on_model_error_callback
Reads: temp:current_depth, app:max_depth
Writes: temp:depth_guard_blocked
"""

import logging
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from rlm_adk.state import (
    APP_MAX_DEPTH,
    TEMP_CURRENT_DEPTH,
    TEMP_DEPTH_GUARD_BLOCKED,
)

logger = logging.getLogger(__name__)


class DepthGuardPlugin(BasePlugin):
    """Enforces maximum recursion depth for LM calls.

    - before_model_callback: If temp:current_depth > app:max_depth,
      returns synthetic LlmResponse with error message (short-circuits the model call).
    - on_model_error_callback (HIGH-2): Catches rate limits, auth failures,
      transient HTTP errors. Logs error, returns fallback LlmResponse.
    """

    def __init__(self, *, name: str = "depth_guard"):
        super().__init__(name=name)

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Check depth before model call. Short-circuit if exceeded."""
        state = callback_context.state
        current_depth = state.get(TEMP_CURRENT_DEPTH, 0)
        max_depth = state.get(APP_MAX_DEPTH, 1)

        if current_depth > max_depth:
            state[TEMP_DEPTH_GUARD_BLOCKED] = True
            logger.warning(
                "Depth guard: blocking model call at depth %d (max: %d)",
                current_depth,
                max_depth,
            )
            return _create_error_response(
                f"Maximum recursion depth ({max_depth}) exceeded. "
                f"Current depth: {current_depth}."
            )
        return None

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> Optional[LlmResponse]:
        """Handle model errors: rate limits, auth failures, transient errors."""
        error_str = str(error)
        error_type = type(error).__name__

        logger.error("Model error (%s): %s", error_type, error_str)

        if "rate_limit" in error_str.lower() or "429" in error_str:
            return _create_error_response(f"Rate limit exceeded: {error_str}")
        if "auth" in error_str.lower() or "401" in error_str or "403" in error_str:
            return _create_error_response(f"Authentication error: {error_str}")
        if "timeout" in error_str.lower() or "504" in error_str:
            return _create_error_response(f"Request timeout: {error_str}")

        return _create_error_response(f"Model error ({error_type}): {error_str}")


def _create_error_response(message: str) -> LlmResponse:
    """Create a synthetic LlmResponse with an error message."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=message)],
        ),
    )
