"""ObservabilityPlugin - Usage tracking, timings, and audit trail.

Trigger points: ALL (before/after agent, model, tool; on_event, after_run)
Observe only - never returns a value, never blocks execution.
"""

import logging
import time
from typing import Any, Optional

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from rlm_adk.state import (
    OBS_ITERATION_TIMES,
    OBS_TOOL_INVOCATION_SUMMARY,
    OBS_TOTAL_CALLS,
    OBS_TOTAL_EXECUTION_TIME,
    OBS_TOTAL_INPUT_TOKENS,
    OBS_TOTAL_OUTPUT_TOKENS,
    TEMP_INVOCATION_START_TIME,
    TEMP_ITERATION_COUNT,
    TEMP_REQUEST_ID,
    USER_LAST_SUCCESSFUL_CALL_ID,
    obs_model_usage_key,
)

logger = logging.getLogger(__name__)


class ObservabilityPlugin(BasePlugin):
    """Tracks usage metrics, timings, and provides structured audit trail.

    Observe-only: never returns a value, never blocks execution.
    Logging errors are caught and suppressed.
    """

    def __init__(self, *, name: str = "observability"):
        super().__init__(name=name)

    async def before_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        """Record agent entry."""
        try:
            state = callback_context.state
            if not state.get(TEMP_INVOCATION_START_TIME):
                state[TEMP_INVOCATION_START_TIME] = time.time()

            agent_name = getattr(agent, "name", "unknown")
            request_id = state.get(TEMP_REQUEST_ID, "unknown")
            logger.debug("[%s] Agent '%s' starting", request_id, agent_name)
        except Exception:
            pass
        return None

    async def after_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        """Record agent exit."""
        try:
            agent_name = getattr(agent, "name", "unknown")
            request_id = callback_context.state.get(TEMP_REQUEST_ID, "unknown")
            logger.debug("[%s] Agent '%s' completed", request_id, agent_name)
        except Exception:
            pass
        return None

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Record pre-model call metrics."""
        try:
            state = callback_context.state
            request_id = state.get(TEMP_REQUEST_ID, "unknown")
            model = llm_request.model or "unknown"
            logger.debug("[%s] Model call to '%s' starting", request_id, model)
        except Exception:
            pass
        return None

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> Optional[LlmResponse]:
        """Record post-model call metrics: token usage, call counts."""
        try:
            state = callback_context.state

            # Increment total calls
            state[OBS_TOTAL_CALLS] = state.get(OBS_TOTAL_CALLS, 0) + 1

            # Extract token usage from response
            usage = llm_response.usage_metadata
            if usage:
                input_tokens = getattr(usage, "prompt_token_count", 0) or 0
                output_tokens = getattr(usage, "candidates_token_count", 0) or 0

                state[OBS_TOTAL_INPUT_TOKENS] = (
                    state.get(OBS_TOTAL_INPUT_TOKENS, 0) + input_tokens
                )
                state[OBS_TOTAL_OUTPUT_TOKENS] = (
                    state.get(OBS_TOTAL_OUTPUT_TOKENS, 0) + output_tokens
                )

                # Per-model tracking via agent_name as proxy since after_model
                # does not receive llm_request
                model = "unknown"
                # Try to get model from response's model_version field
                if llm_response.model_version:
                    model = llm_response.model_version
                model_key = obs_model_usage_key(model)
                model_usage = state.get(
                    model_key,
                    {"calls": 0, "input_tokens": 0, "output_tokens": 0},
                )
                model_usage["calls"] += 1
                model_usage["input_tokens"] += input_tokens
                model_usage["output_tokens"] += output_tokens
                state[model_key] = model_usage

            request_id = state.get(TEMP_REQUEST_ID, "unknown")
            logger.debug("[%s] Model call completed", request_id)

        except Exception as e:
            logger.debug("Observability after_model error: %s", e)

        return None

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[dict]:
        """Record tool invocation."""
        try:
            tool_name = getattr(tool, "name", str(tool))
            state = tool_context.state
            summary: dict = state.get(OBS_TOOL_INVOCATION_SUMMARY, {})
            summary[tool_name] = summary.get(tool_name, 0) + 1
            state[OBS_TOOL_INVOCATION_SUMMARY] = summary
        except Exception:
            pass
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict,
    ) -> Optional[dict]:
        """Record tool completion."""
        return None

    async def on_event_callback(
        self,
        *,
        invocation_context: InvocationContext,
        event: Event,
    ) -> Optional[Event]:
        """Enrich events with request ID for correlation."""
        try:
            state = invocation_context.session.state
            request_id = state.get(TEMP_REQUEST_ID)
            if request_id and event.actions and event.actions.state_delta:
                # Log event for audit trail
                logger.debug(
                    "[%s] Event from '%s': %d state deltas",
                    request_id,
                    event.author,
                    len(event.actions.state_delta),
                )
        except Exception:
            pass
        return None

    async def after_run_callback(
        self,
        *,
        invocation_context: InvocationContext,
    ) -> None:
        """Record final execution summary."""
        try:
            state = invocation_context.session.state
            start_time = state.get(TEMP_INVOCATION_START_TIME, 0)
            if start_time:
                total_time = time.time() - start_time
                state[OBS_TOTAL_EXECUTION_TIME] = total_time

            request_id = state.get(TEMP_REQUEST_ID, "unknown")

            # Store last successful call ID for cross-session reference
            if request_id != "unknown":
                state[USER_LAST_SUCCESSFUL_CALL_ID] = request_id

            logger.info(
                "[%s] Run completed: calls=%d, input_tokens=%d, "
                "output_tokens=%d, time=%.2fs",
                request_id,
                state.get(OBS_TOTAL_CALLS, 0),
                state.get(OBS_TOTAL_INPUT_TOKENS, 0),
                state.get(OBS_TOTAL_OUTPUT_TOKENS, 0),
                state.get(OBS_TOTAL_EXECUTION_TIME, 0),
            )
        except Exception as e:
            logger.debug("Observability after_run error: %s", e)
