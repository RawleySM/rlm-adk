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
    CONTEXT_WINDOW_SNAPSHOT,
    INVOCATION_START_TIME,
    ITERATION_COUNT,
    OBS_ARTIFACT_BYTES_SAVED,
    OBS_ARTIFACT_SAVES,
    OBS_FINISH_MAX_TOKENS_COUNT,
    OBS_FINISH_RECITATION_COUNT,
    OBS_FINISH_SAFETY_COUNT,
    OBS_PER_ITERATION_TOKEN_BREAKDOWN,
    OBS_TOOL_INVOCATION_SUMMARY,
    OBS_TOTAL_CALLS,
    OBS_TOTAL_EXECUTION_TIME,
    OBS_TOTAL_INPUT_TOKENS,
    OBS_TOTAL_OUTPUT_TOKENS,
    REASONING_PROMPT_CHARS,
    REASONING_SYSTEM_CHARS,
    REQUEST_ID,
    USER_LAST_SUCCESSFUL_CALL_ID,
    WORKER_PROMPT_CHARS,
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
            if not state.get(INVOCATION_START_TIME):
                state[INVOCATION_START_TIME] = time.time()

            agent_name = getattr(agent, "name", "unknown")
            request_id = state.get(REQUEST_ID, "unknown")
            logger.debug("[%s] Agent '%s' starting", request_id, agent_name)
        except Exception:
            pass
        return None

    # Keys written by after_model_callback that are ephemeral due to ADK
    # not wiring event_actions on plugin after_model CallbackContext
    # (base_llm_flow.py oversight).  We re-persist them here.
    _EPHEMERAL_FIXED_KEYS: tuple[str, ...] = (
        OBS_TOTAL_CALLS,
        OBS_TOTAL_INPUT_TOKENS,
        OBS_TOTAL_OUTPUT_TOKENS,
        OBS_PER_ITERATION_TOKEN_BREAKDOWN,
        OBS_FINISH_SAFETY_COUNT,
        OBS_FINISH_RECITATION_COUNT,
        OBS_FINISH_MAX_TOKENS_COUNT,
    )

    # Prefixes for dynamic keys generated in after_model_callback
    _EPHEMERAL_DYNAMIC_PREFIXES: tuple[str, ...] = (
        "obs:finish_",
        "obs:model_usage:",
    )

    async def after_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        """Persist ephemeral obs keys and record agent exit.

        ADK's base_llm_flow.py creates CallbackContext *without*
        event_actions for plugin after_model_callback, so state writes
        there hit the live session dict but never land in a state_delta
        Event.  This after_agent_callback re-writes those values through
        the properly-wired CallbackContext so they appear in final_state.
        """
        try:
            state = callback_context.state
            # Read the live session dict to find ephemeral values
            session_state = callback_context._invocation_context.session.state

            # Persist fixed keys
            for key in self._EPHEMERAL_FIXED_KEYS:
                val = session_state.get(key)
                if val is not None:
                    state[key] = val

            # Persist dynamic keys (obs:finish_*, obs:model_usage:*)
            for sess_key in list(session_state.keys()):
                for prefix in self._EPHEMERAL_DYNAMIC_PREFIXES:
                    if sess_key.startswith(prefix):
                        val = session_state.get(sess_key)
                        if val is not None:
                            state[sess_key] = val
                        break

            agent_name = getattr(agent, "name", "unknown")
            request_id = state.get(REQUEST_ID, "unknown")
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
            request_id = state.get(REQUEST_ID, "unknown")
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

            # --- Record finish_reason ---
            # Use .name to get "SAFETY" not "FinishReason.SAFETY" (BUG-A fix)
            finish_reason = llm_response.finish_reason.name if llm_response.finish_reason else None
            if finish_reason and finish_reason != "STOP":
                key = f"obs:finish_{finish_reason.lower()}_count"
                state[key] = state.get(key, 0) + 1

            # --- Per-iteration token breakdown ---
            # Read agent-specific token accounting written by before/after callbacks
            iteration = state.get(ITERATION_COUNT, 0)
            context_snapshot = state.get(CONTEXT_WINDOW_SNAPSHOT)

            breakdown_entry: dict[str, Any] = {
                "iteration": iteration,
                "call_number": state.get(OBS_TOTAL_CALLS, 0),
                "input_tokens": input_tokens if usage else 0,
                "output_tokens": output_tokens if usage else 0,
                "finish_reason": finish_reason,  # now .name (BUG-A fix)
            }

            # Include agent-type-specific prompt characterization
            reasoning_prompt_chars = state.get(REASONING_PROMPT_CHARS)
            if reasoning_prompt_chars is not None:
                breakdown_entry["agent_type"] = "reasoning"
                breakdown_entry["prompt_chars"] = reasoning_prompt_chars
                breakdown_entry["system_chars"] = state.get(
                    REASONING_SYSTEM_CHARS, 0
                )

            worker_prompt_chars = state.get(WORKER_PROMPT_CHARS)
            if worker_prompt_chars is not None:
                breakdown_entry["agent_type"] = "worker"
                breakdown_entry["prompt_chars"] = worker_prompt_chars

            if context_snapshot:
                breakdown_entry["context_snapshot"] = context_snapshot

            breakdowns: list = state.get(OBS_PER_ITERATION_TOKEN_BREAKDOWN, [])
            breakdowns.append(breakdown_entry)
            state[OBS_PER_ITERATION_TOKEN_BREAKDOWN] = breakdowns

            request_id = state.get(REQUEST_ID, "unknown")
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

    async def on_event_callback(
        self,
        *,
        invocation_context: InvocationContext,
        event: Event,
    ) -> Optional[Event]:
        """Enrich events with request ID for correlation and track artifact deltas."""
        try:
            state = invocation_context.session.state
            request_id = state.get(REQUEST_ID)
            if request_id and event.actions and event.actions.state_delta:
                # Log event for audit trail
                logger.debug(
                    "[%s] Event from '%s': %d state deltas",
                    request_id,
                    event.author,
                    len(event.actions.state_delta),
                )

            # Track artifact operations from event artifact_delta
            if event.actions and event.actions.artifact_delta:
                artifact_count = len(event.actions.artifact_delta)
                state[OBS_ARTIFACT_SAVES] = state.get(OBS_ARTIFACT_SAVES, 0) + artifact_count
                logger.debug(
                    "[%s] Event from '%s': %d artifact saves",
                    state.get(REQUEST_ID, "unknown"),
                    event.author,
                    artifact_count,
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
            start_time = state.get(INVOCATION_START_TIME, 0)
            if start_time:
                total_time = time.time() - start_time
                state[OBS_TOTAL_EXECUTION_TIME] = total_time

            request_id = state.get(REQUEST_ID, "unknown")

            # Store last successful call ID for cross-session reference
            if request_id != "unknown":
                state[USER_LAST_SUCCESSFUL_CALL_ID] = request_id

            breakdowns = state.get(OBS_PER_ITERATION_TOKEN_BREAKDOWN, [])
            reasoning_calls = sum(
                1 for b in breakdowns if b.get("agent_type") == "reasoning"
            )
            worker_calls = sum(
                1 for b in breakdowns if b.get("agent_type") == "worker"
            )

            artifact_saves = state.get(OBS_ARTIFACT_SAVES, 0)
            artifact_bytes = state.get(OBS_ARTIFACT_BYTES_SAVED, 0)

            log_msg = (
                "[%s] Run completed: calls=%d (reasoning=%d, worker=%d), "
                "input_tokens=%d, output_tokens=%d, time=%.2fs"
            )
            log_args = [
                request_id,
                state.get(OBS_TOTAL_CALLS, 0),
                reasoning_calls,
                worker_calls,
                state.get(OBS_TOTAL_INPUT_TOKENS, 0),
                state.get(OBS_TOTAL_OUTPUT_TOKENS, 0),
                state.get(OBS_TOTAL_EXECUTION_TIME, 0),
            ]

            if artifact_saves > 0:
                log_msg += ", artifact_saves=%d, artifact_bytes=%d"
                log_args.extend([artifact_saves, artifact_bytes])

            logger.info(log_msg, *log_args)
        except Exception as e:
            logger.debug("Observability after_run error: %s", e)
