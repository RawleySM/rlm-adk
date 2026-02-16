"""DebugLoggingPlugin - Development-only detailed tracing.

Wraps/extends logging with full interaction traces.
Development only - not for production.
"""

import logging
import time
from pathlib import Path
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

from rlm_adk.state import TEMP_REQUEST_ID

logger = logging.getLogger(__name__)


class DebugLoggingPlugin(BasePlugin):
    """Full interaction trace logging for development.

    Records prompts, responses, tool calls, and state snapshots.
    Writes traces to YAML on after_run_callback.
    Not for production use.
    """

    def __init__(
        self,
        *,
        name: str = "debug_logging",
        output_path: str = "rlm_adk_debug.yaml",
        include_session_state: bool = True,
        include_system_instruction: bool = True,
    ):
        super().__init__(name=name)
        self._output_path = Path(output_path)
        self._include_session_state = include_session_state
        self._include_system_instruction = include_system_instruction
        self._traces: list[dict[str, Any]] = []

    async def before_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        """Record agent entry with state snapshot."""
        try:
            entry: dict[str, Any] = {
                "event": "before_agent",
                "timestamp": time.time(),
                "agent_name": getattr(agent, "name", "unknown"),
                "request_id": callback_context.state.get(TEMP_REQUEST_ID, "unknown"),
            }
            if self._include_session_state:
                entry["state_snapshot"] = _safe_state_snapshot(callback_context.state)
            self._traces.append(entry)
        except Exception as e:
            logger.debug("DebugLogging before_agent error: %s", e)
        return None

    async def after_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        """Record agent exit."""
        try:
            self._traces.append({
                "event": "after_agent",
                "timestamp": time.time(),
                "agent_name": getattr(agent, "name", "unknown"),
                "request_id": callback_context.state.get(TEMP_REQUEST_ID, "unknown"),
            })
        except Exception as e:
            logger.debug("DebugLogging after_agent error: %s", e)
        return None

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        """Record model request details."""
        try:
            entry: dict[str, Any] = {
                "event": "before_model",
                "timestamp": time.time(),
                "model": llm_request.model or "unknown",
                "request_id": callback_context.state.get(TEMP_REQUEST_ID, "unknown"),
                "num_contents": len(llm_request.contents),
            }
            # Record prompt text
            prompt_parts = []
            for content in llm_request.contents:
                if content.parts:
                    for part in content.parts:
                        if hasattr(part, "text") and part.text:
                            prompt_parts.append(part.text[:500])
            entry["prompt_preview"] = prompt_parts

            if self._include_system_instruction and llm_request.config:
                si = getattr(llm_request.config, "system_instruction", None)
                if si:
                    entry["system_instruction_preview"] = str(si)[:500]

            self._traces.append(entry)
        except Exception as e:
            logger.debug("DebugLogging before_model error: %s", e)
        return None

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> Optional[LlmResponse]:
        """Record model response details."""
        try:
            entry: dict[str, Any] = {
                "event": "after_model",
                "timestamp": time.time(),
                "request_id": callback_context.state.get(TEMP_REQUEST_ID, "unknown"),
            }
            # Record response text
            if llm_response.content and llm_response.content.parts:
                response_text = ""
                for part in llm_response.content.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text
                entry["response_preview"] = response_text[:1000]

            # Record usage metadata
            if llm_response.usage_metadata:
                entry["usage"] = {
                    "prompt_tokens": getattr(
                        llm_response.usage_metadata, "prompt_token_count", None
                    ),
                    "candidates_tokens": getattr(
                        llm_response.usage_metadata, "candidates_token_count", None
                    ),
                }

            if llm_response.error_code:
                entry["error_code"] = llm_response.error_code
                entry["error_message"] = llm_response.error_message

            self._traces.append(entry)
        except Exception as e:
            logger.debug("DebugLogging after_model error: %s", e)
        return None

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> Optional[LlmResponse]:
        """Record model error details."""
        try:
            self._traces.append({
                "event": "model_error",
                "timestamp": time.time(),
                "model": llm_request.model or "unknown",
                "request_id": callback_context.state.get(TEMP_REQUEST_ID, "unknown"),
                "error_type": type(error).__name__,
                "error_message": str(error),
            })
        except Exception as e:
            logger.debug("DebugLogging on_model_error error: %s", e)
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
            self._traces.append({
                "event": "before_tool",
                "timestamp": time.time(),
                "tool_name": getattr(tool, "name", str(tool)),
                "args": {k: str(v)[:200] for k, v in tool_args.items()},
                "request_id": tool_context.state.get(TEMP_REQUEST_ID, "unknown"),
            })
        except Exception as e:
            logger.debug("DebugLogging before_tool error: %s", e)
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict,
    ) -> Optional[dict]:
        """Record tool result."""
        try:
            self._traces.append({
                "event": "after_tool",
                "timestamp": time.time(),
                "tool_name": getattr(tool, "name", str(tool)),
                "result_preview": str(result)[:500],
                "request_id": tool_context.state.get(TEMP_REQUEST_ID, "unknown"),
            })
        except Exception as e:
            logger.debug("DebugLogging after_tool error: %s", e)
        return None

    async def on_event_callback(
        self,
        *,
        invocation_context: InvocationContext,
        event: Event,
    ) -> Optional[Event]:
        """Record events."""
        try:
            entry: dict[str, Any] = {
                "event": "on_event",
                "timestamp": time.time(),
                "author": event.author,
            }
            if event.actions and event.actions.state_delta:
                entry["state_delta_keys"] = list(event.actions.state_delta.keys())
            self._traces.append(entry)
        except Exception:
            pass
        return None

    async def after_run_callback(
        self,
        *,
        invocation_context: InvocationContext,
    ) -> None:
        """Write all traces to YAML file."""
        try:
            import yaml

            state_snapshot = None
            if self._include_session_state:
                state_snapshot = _safe_state_snapshot(
                    invocation_context.session.state
                )

            output = {
                "session_id": invocation_context.session.id,
                "user_id": invocation_context.session.user_id,
                "final_state": state_snapshot,
                "traces": self._traces,
            }

            with open(self._output_path, "w") as f:
                yaml.dump(output, f, default_flow_style=False, sort_keys=False)

            logger.info("Debug traces written to %s", self._output_path)
        except Exception as e:
            logger.warning("Failed to write debug traces: %s", e)
        finally:
            self._traces.clear()


def _safe_state_snapshot(state: Any) -> dict:
    """Create a JSON-safe snapshot of session state."""
    snapshot = {}
    try:
        # state may be a dict-like object
        items = state.items() if hasattr(state, "items") else {}
        for key, value in items:
            try:
                # Only include serializable values
                if isinstance(value, (str, int, float, bool, type(None))):
                    snapshot[key] = value
                elif isinstance(value, (list, dict)):
                    snapshot[key] = str(value)[:500]
                else:
                    snapshot[key] = f"<{type(value).__name__}>"
            except Exception:
                snapshot[key] = "<unserializable>"
    except Exception:
        pass
    return snapshot
