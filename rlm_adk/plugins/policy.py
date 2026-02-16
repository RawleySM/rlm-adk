"""PolicyPlugin - Auth/safety guardrails.

Trigger points: before_model_callback, before_tool_callback, on_user_message_callback
Intervene pattern: blocks when policy violated.
Fail fast, fail loud per rlm culture.
"""

import hashlib
import logging
import re
import uuid
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from rlm_adk.state import (
    TEMP_IDEMPOTENCY_KEY,
    TEMP_POLICY_VIOLATION,
    TEMP_REQUEST_ID,
)

logger = logging.getLogger(__name__)


class PolicyPlugin(BasePlugin):
    """Enforces auth/safety policies.

    - on_user_message_callback: Generate request_id and idempotency_key.
    - before_model_callback: Check blocked patterns against prompt.
    - before_tool_callback: Check auth level against tool requirements.
    """

    def __init__(
        self,
        *,
        name: str = "policy",
        blocked_patterns: list[str] | None = None,
    ):
        super().__init__(name=name)
        self._blocked_patterns = [re.compile(p) for p in (blocked_patterns or [])]

    async def on_user_message_callback(
        self,
        *,
        invocation_context: InvocationContext,
        user_message: types.Content,
    ) -> Optional[types.Content]:
        """Generate request_id and idempotency_key for the invocation."""
        state = invocation_context.session.state

        # Generate unique request ID
        request_id = f"req-{uuid.uuid4().hex[:12]}"
        state[TEMP_REQUEST_ID] = request_id

        # Generate idempotency key from message content
        message_text = ""
        if user_message.parts:
            for part in user_message.parts:
                if hasattr(part, "text") and part.text:
                    message_text += part.text

        user_id = invocation_context.session.user_id or ""
        session_id = invocation_context.session.id or ""
        idem_source = f"{user_id}:{session_id}:{message_text}"
        state[TEMP_IDEMPOTENCY_KEY] = (
            f"idem-{hashlib.sha256(idem_source.encode()).hexdigest()[:16]}"
        )

        logger.debug("[%s] Policy: request initialized", request_id)
        return None

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Check blocked patterns against prompt content."""
        if not self._blocked_patterns:
            return None

        # Extract text from request contents
        prompt_text = ""
        for content in llm_request.contents:
            if content.parts:
                for part in content.parts:
                    if hasattr(part, "text") and part.text:
                        prompt_text += part.text

        # Check each blocked pattern
        for pattern in self._blocked_patterns:
            match = pattern.search(prompt_text)
            if match:
                request_id = callback_context.state.get(TEMP_REQUEST_ID, "unknown")
                violation = f"blocked: pattern '{pattern.pattern}' matched"
                callback_context.state[TEMP_POLICY_VIOLATION] = violation

                logger.warning(
                    "[%s] Policy violation: %s", request_id, violation
                )

                return LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(
                                text=f"Policy violation: request blocked. {violation}"
                            )
                        ],
                    ),
                )

        return None

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[dict]:
        """Check auth level against tool requirements."""
        state = tool_context.state

        # Check if tool has an auth_level requirement (convention: tool attribute)
        required_level = getattr(tool, "required_auth_level", None)
        if required_level is None:
            return None

        user_auth_level = state.get("user:auth_level", "user")
        # Simple level hierarchy: admin > user > guest
        level_order = {"guest": 0, "user": 1, "admin": 2}
        user_rank = level_order.get(user_auth_level, 0)
        required_rank = level_order.get(required_level, 0)

        if user_rank < required_rank:
            request_id = state.get(TEMP_REQUEST_ID, "unknown")
            tool_name = getattr(tool, "name", str(tool))
            violation = (
                f"Unauthorized: tool '{tool_name}' requires '{required_level}', "
                f"user has '{user_auth_level}'"
            )
            state[TEMP_POLICY_VIOLATION] = violation

            logger.warning("[%s] Policy violation: %s", request_id, violation)

            return {"error": "Unauthorized", "required_level": required_level}

        return None
