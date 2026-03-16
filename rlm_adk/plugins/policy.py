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
    IDEMPOTENCY_KEY,
    POLICY_VIOLATION,
    REQUEST_ID,
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
        # AR-CRIT-001: pending values stashed by on_user_message_callback,
        # persisted via delta-tracked callback_context in before_agent_callback.
        self._pending_request_id: str | None = None
        self._pending_idempotency_key: str | None = None

    async def on_user_message_callback(
        self,
        *,
        invocation_context: InvocationContext,
        user_message: types.Content,
    ) -> Optional[types.Content]:
        """Capture user message for idempotency key generation.

        AR-CRIT-001: on_user_message_callback only receives invocation_context
        (no callback_context), so we cannot write to delta-tracked state here.
        We stash the computed values on the plugin instance and persist them in
        before_agent_callback which has a properly-wired callback_context.
        """
        # Generate unique request ID
        self._pending_request_id = f"req-{uuid.uuid4().hex[:12]}"

        # Generate idempotency key from message content
        message_text = ""
        if user_message.parts:
            for part in user_message.parts:
                if hasattr(part, "text") and part.text:
                    message_text += part.text

        user_id = invocation_context.session.user_id or ""
        session_id = invocation_context.session.id or ""
        idem_source = f"{user_id}:{session_id}:{message_text}"
        self._pending_idempotency_key = (
            f"idem-{hashlib.sha256(idem_source.encode()).hexdigest()[:16]}"
        )

        logger.debug("[%s] Policy: request initialized (pending)", self._pending_request_id)
        return None

    async def before_agent_callback(
        self,
        *,
        agent: Any,
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        """Persist pending request_id and idempotency_key via delta-tracked state.

        This fires on every agent entry, but we only write the pending values
        once (the first time after on_user_message_callback stashes them).
        """
        if self._pending_request_id is not None:
            callback_context.state[REQUEST_ID] = self._pending_request_id
            self._pending_request_id = None
        if self._pending_idempotency_key is not None:
            callback_context.state[IDEMPOTENCY_KEY] = self._pending_idempotency_key
            self._pending_idempotency_key = None
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
                request_id = callback_context.state.get(REQUEST_ID, "unknown")
                violation = f"blocked: pattern '{pattern.pattern}' matched"
                callback_context.state[POLICY_VIOLATION] = violation

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
            request_id = state.get(REQUEST_ID, "unknown")
            tool_name = getattr(tool, "name", str(tool))
            violation = (
                f"Unauthorized: tool '{tool_name}' requires '{required_level}', "
                f"user has '{user_auth_level}'"
            )
            state[POLICY_VIOLATION] = violation

            logger.warning("[%s] Policy violation: %s", request_id, violation)

            return {"error": "Unauthorized", "required_level": required_level}

        return None
