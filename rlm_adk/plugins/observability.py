"""ObservabilityPlugin - Usage tracking, timings, and audit trail.

Trigger points: ALL (before/after agent, model, tool; on_event, after_run)
Observe only - never returns a value, never blocks execution.

All counters are tracked on plugin instance attributes. Session state is
NOT used as an observability bus — SQLite telemetry is the sole lineage sink.
"""

import logging
import time
from typing import Any

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
    FINAL_RESPONSE_TEXT,
    INVOCATION_START_TIME,
    REQUEST_ID,
)

logger = logging.getLogger(__name__)


class ObservabilityPlugin(BasePlugin):
    """Tracks usage metrics, timings, and provides structured audit trail.

    All counters live on the plugin instance — no obs keys are written to
    session state. SQLite telemetry is the authoritative lineage sink.

    Observe-only: never returns a value, never blocks execution.
    Logging errors are caught and suppressed.
    """

    def __init__(self, *, name: str = "observability", verbose: bool = False):
        super().__init__(name=name)
        self._verbose = verbose
        # Instance-local counters (not written to session state)
        self._total_calls: int = 0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._model_usage: dict[str, dict[str, int]] = {}
        self._finish_reason_counts: dict[str, int] = {}
        self._tool_invocation_summary: dict[str, int] = {}
        self._artifact_saves_acc: int = 0
        self._total_execution_time: float | None = None
        self._last_successful_call_id: str | None = None
        # Consumed from agent._rlm_pending_request_meta
        self._last_prompt_chars: int | None = None
        self._last_system_chars: int | None = None

    async def before_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> types.Content | None:
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

    async def after_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> types.Content | None:
        """Record agent exit."""
        try:
            state = callback_context.state
            agent_name = getattr(agent, "name", "unknown")
            request_id = state.get(REQUEST_ID, "unknown")
            logger.debug(
                "[%s] Agent '%s' completed",
                request_id,
                agent_name,
            )
        except Exception:
            pass
        return None

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
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
    ) -> LlmResponse | None:
        """Record post-model call metrics on instance (not session state).

        Consumes ``_rlm_pending_request_meta`` from the agent
        (set by ``reasoning_before_model``) for prompt/system
        char counts alongside response-side token accounting.
        """
        try:
            state = callback_context.state

            # Increment total calls on instance
            self._total_calls += 1

            # Extract token usage from response
            usage = llm_response.usage_metadata
            if usage:
                input_tokens = (
                    getattr(usage, "prompt_token_count", 0) or 0
                )
                output_tokens = (
                    getattr(usage, "candidates_token_count", 0)
                    or 0
                )

                self._total_input_tokens += input_tokens
                self._total_output_tokens += output_tokens

                model = "unknown"
                if llm_response.model_version:
                    model = llm_response.model_version
                mu = self._model_usage.setdefault(
                    model,
                    {"calls": 0, "input_tokens": 0, "output_tokens": 0},
                )
                mu["calls"] += 1
                mu["input_tokens"] += input_tokens
                mu["output_tokens"] += output_tokens

            # --- Consume request-side metadata from agent ---
            inv_ctx = getattr(
                callback_context, "_invocation_context", None
            )
            agent = getattr(inv_ctx, "agent", None) if inv_ctx else None
            request_meta = (
                getattr(agent, "_rlm_pending_request_meta", None)
                if agent
                else None
            )
            if isinstance(request_meta, dict):
                prompt_chars = request_meta.get("prompt_chars")
                system_chars = request_meta.get("system_chars")
                if prompt_chars is not None:
                    self._last_prompt_chars = prompt_chars
                if system_chars is not None:
                    self._last_system_chars = system_chars

            # --- Record finish_reason on instance ---
            finish_reason = (
                llm_response.finish_reason.name
                if llm_response.finish_reason
                else None
            )
            if finish_reason and finish_reason != "STOP":
                key = finish_reason.lower()
                self._finish_reason_counts[key] = (
                    self._finish_reason_counts.get(key, 0) + 1
                )

            request_id = state.get(REQUEST_ID, "unknown")
            logger.debug(
                "[%s] Model call completed", request_id
            )

        except Exception as e:
            logger.debug("Observability after_model error: %s", e)

        return None

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict | None:
        """Record tool invocation on instance (not session state)."""
        try:
            tool_name = getattr(tool, "name", str(tool))
            self._tool_invocation_summary[tool_name] = (
                self._tool_invocation_summary.get(tool_name, 0) + 1
            )
        except Exception:
            pass
        return None

    async def on_event_callback(
        self,
        *,
        invocation_context: InvocationContext,
        event: Event,
    ) -> Event | None:
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

            # Track artifact operations from event artifact_delta.
            if event.actions and event.actions.artifact_delta:
                artifact_count = len(event.actions.artifact_delta)
                self._artifact_saves_acc += artifact_count
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
        """Record final execution summary from instance counters."""
        try:
            # AR-CRIT-001: after_run_callback only has invocation_context
            # (no callback_context).  Reads are fine; writes must NOT go
            # to invocation_context.session.state (bypasses delta tracking).
            state = invocation_context.session.state  # read-only usage below
            start_time = state.get(INVOCATION_START_TIME, 0)
            total_time = 0.0
            if start_time:
                total_time = time.time() - start_time
            self._total_execution_time = total_time

            request_id = state.get(REQUEST_ID, "unknown")

            # Store last successful call ID on instance (not session state)
            if request_id != "unknown":
                self._last_successful_call_id = request_id

            artifact_saves = self._artifact_saves_acc
            final_answer = state.get(FINAL_RESPONSE_TEXT, "")
            answer_len = len(final_answer) if final_answer else 0

            log_msg = (
                "[%s] Run completed: calls=%d, "
                "input_tokens=%d, output_tokens=%d, time=%.2fs, "
                "answer_len=%d"
            )
            log_args: list = [
                request_id,
                self._total_calls,
                self._total_input_tokens,
                self._total_output_tokens,
                total_time,
                answer_len,
            ]

            if artifact_saves > 0:
                log_msg += ", artifact_saves=%d"
                log_args.append(artifact_saves)

            logger.info(log_msg, *log_args)

            # Verbose mode: also print to stdout (replaces DebugLoggingPlugin)
            if self._verbose:
                print(
                    "[RLM] " + (log_msg % tuple(log_args)),
                    flush=True,
                )
        except Exception as e:
            logger.debug("Observability after_run error: %s", e)
