"""Worker retry plugin for structured output self-healing.

Provides:
- WorkerRetryPlugin: Extends ReflectAndRetryToolPlugin to detect empty
  responses from set_model_response and trigger retries.
- make_worker_tool_callbacks(): Factory returning (after_tool_cb, on_tool_error_cb)
  wrapper functions with positional-arg signatures compatible with LlmAgent
  tool callbacks. These capture validated structured results on the worker
  agent and delegate retry logic to the plugin.
- _patch_output_schema_postprocessor(): Module-level monkey-patch that
  suppresses ADK's premature worker termination when callbacks signal retry
  (BUG-13 workaround).

Wiring: dispatch.py sets these callbacks on workers when output_schema is provided.
"""

import json as _json
import logging
from typing import Any

from google.adk.plugins.reflect_retry_tool_plugin import (
    REFLECT_AND_RETRY_RESPONSE_TYPE,
    ReflectAndRetryToolPlugin,
)
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from rlm_adk.types import CompletionEnvelope, render_completion_text

logger = logging.getLogger(__name__)

# Observability counter for BUG-13 patch invocations (process-global).
# Tests can read this to verify the patch was actually invoked at runtime,
# not just installed. Reset between test runs if needed.
_bug13_stats: dict[str, int] = {"suppress_count": 0}

# Canonical tool name for ADK's synthesized set_model_response tool.
# Used as a guard so that retry/reflection logic only fires for structured
# output validation, not for other tools like execute_code (REPLTool).
_SET_MODEL_RESPONSE_TOOL_NAME = "set_model_response"


def _structured_obs(agent: Any) -> dict[str, Any]:
    """Return the mutable structured-output telemetry dict for a child agent."""
    obs = getattr(agent, "_structured_output_obs", None)
    if isinstance(obs, dict):
        return obs
    obs = {"attempts": 0, "retry_count": 0, "events": []}
    object.__setattr__(agent, "_structured_output_obs", obs)
    return obs


def _record_structured_event(
    agent: Any,
    *,
    outcome: str,
    args: dict[str, Any],
    tool_response: Any = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    """Append a structured-output attempt event to the agent-local telemetry."""
    obs = _structured_obs(agent)
    obs["attempts"] = int(obs.get("attempts", 0) or 0) + 1
    event: dict[str, Any] = {
        "attempt": obs["attempts"],
        "outcome": outcome,
        "args_keys": sorted(args.keys()),
    }
    if isinstance(tool_response, dict):
        event["response_keys"] = sorted(tool_response.keys())
    if error is not None:
        event["error_type"] = type(error).__name__
        event["error_message"] = str(error)
    obs.setdefault("events", []).append(event)
    if outcome == "retry_requested":
        obs["retry_count"] = int(obs.get("retry_count", 0) or 0) + 1
    obs["last_outcome"] = outcome
    return obs


class WorkerRetryPlugin(ReflectAndRetryToolPlugin):
    """Extends ReflectAndRetryToolPlugin for set_model_response validation.

    Detects empty values in set_model_response tool results and triggers
    retry via the parent class's reflection/retry mechanism.
    """

    def __init__(self, max_retries: int = 2):
        super().__init__(max_retries=max_retries)

    async def extract_error_from_result(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: Any,
    ) -> dict[str, Any] | None:
        """Detect empty responses in set_model_response tool output."""
        if tool.name != "set_model_response":
            return None

        # Check if any value in the tool args is empty
        for key, value in tool_args.items():
            if isinstance(value, str) and not value.strip():
                return {
                    "error": "Empty value",
                    "details": (
                        f"Empty string for field '{key}'."
                        " The response must contain"
                        " meaningful content."
                    ),
                }

        return None


def _set_lineage_status(agent: Any, **updates: Any) -> None:
    """Update lineage status on agent.

    Uses object.__setattr__ since agent is a Pydantic LlmAgent.
    """
    state = getattr(agent, "_rlm_lineage_status", {}) or {}
    state.update(updates)
    object.__setattr__(agent, "_rlm_lineage_status", state)


def make_worker_tool_callbacks(
    max_retries: int = 2,
) -> tuple[Any, Any]:
    """Create agent-level tool callback wrappers backed by WorkerRetryPlugin.

    Returns (after_tool_cb, on_tool_error_cb) with positional-arg signatures
    matching LlmAgent's AfterToolCallback and OnToolErrorCallback types.

    The after_tool_cb captures validated structured results on the worker
    agent's _structured_result attribute when set_model_response succeeds.

    The on_tool_error_cb delegates to the plugin for retry counting and
    reflection guidance generation.

    Args:
        max_retries: Maximum retry attempts for validation errors.

    Returns:
        Tuple of (after_tool_callback, on_tool_error_callback) callables.
    """
    plugin = WorkerRetryPlugin(max_retries=max_retries)

    async def after_tool_cb(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
        tool_response: Any,
    ) -> dict[str, Any] | None:
        """After-tool callback: capture structured result, delegate to plugin.

        Note: ADK calls this with ``args=`` and ``tool_response=`` kwargs
        (see google.adk.flows.llm_flows.functions line 540-545).
        The plugin's ``after_tool_callback`` expects ``tool_args=`` and
        ``result=``, so we translate between the two conventions here.
        """
        # Delegate to plugin for extract_error_from_result checks
        result = await plugin.after_tool_callback(
            tool=tool, tool_args=args,
            tool_context=tool_context, result=tool_response,
        )
        if tool.name == _SET_MODEL_RESPONSE_TOOL_NAME:
            agent = tool_context._invocation_context.agent
            is_reflect_retry_payload = (
                isinstance(tool_response, dict)
                and tool_response.get("response_type")
                == REFLECT_AND_RETRY_RESPONSE_TYPE
            )
            if is_reflect_retry_payload:
                _set_lineage_status(
                    agent,
                    decision_mode="set_model_response",
                    structured_outcome="retry_requested",
                    terminal=False,
                )
                return result
            # result is None means the plugin accepted the response
            # (validation passed). Capture for all response types:
            # dict, list-of-dicts, and raw primitives.
            if result is None:
                object.__setattr__(
                    agent, "_structured_result", tool_response,
                )
                logger.debug(
                    "Captured structured result on %s: %r",
                    getattr(agent, "name", "?"),
                    type(tool_response).__name__,
                )
                rs = (
                    tool_response.get("reasoning_summary", "")
                    if isinstance(tool_response, dict)
                    else ""
                )
                object.__setattr__(
                    agent,
                    "_rlm_terminal_completion",
                    CompletionEnvelope(
                        terminal=True,
                        mode="structured",
                        output_schema_name=getattr(
                            agent,
                            "_rlm_output_schema_name",
                            None,
                        ),
                        validated_output=tool_response,
                        raw_output=tool_response,
                        display_text=render_completion_text(
                            tool_response,
                        ),
                        reasoning_summary=str(rs or ""),
                        error=False,
                    ),
                )
                _set_lineage_status(
                    agent,
                    decision_mode="set_model_response",
                    structured_outcome="validated",
                    terminal=True,
                )
            _record_structured_event(
                agent,
                outcome=(
                    "retry_requested"
                    if result is not None
                    else "validated"
                ),
                args=args,
                tool_response=tool_response,
            )
        return result

    async def on_tool_error_cb(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> dict[str, Any] | None:
        """On-tool-error callback: delegate to plugin for retry/reflection.

        Only intercepts errors from set_model_response. Errors from other
        tools (e.g. execute_code / REPLTool) return None so that they
        propagate normally through ADK's error handling.

        Note: ADK calls this with ``args=`` (see
        google.adk.flows.llm_flows.functions line 443-447).
        """
        if tool.name != _SET_MODEL_RESPONSE_TOOL_NAME:
            return None
        agent = tool_context._invocation_context.agent
        try:
            result = await plugin.on_tool_error_callback(
                tool=tool, tool_args=args,
                tool_context=tool_context, error=error,
            )
        except Exception:
            _record_structured_event(
                agent,
                outcome="exhausted",
                args=args,
                error=error,
            )
            object.__setattr__(agent, "_rlm_terminal_completion",
                CompletionEnvelope(
                    terminal=True,
                    mode="error",
                    error=True,
                    error_category="SCHEMA_VALIDATION_EXHAUSTED",
                    display_text=(
                        "[RLM ERROR] Structured output validation"
                        " failed after all retries."
                    ),
                )
            )
            _set_lineage_status(agent,
                decision_mode="set_model_response",
                structured_outcome="retry_exhausted",
                terminal=True,
            )
            raise
        _record_structured_event(
            agent,
            outcome="retry_requested",
            args=args,
            error=error,
        )
        _set_lineage_status(agent,
            decision_mode="set_model_response",
            structured_outcome="retry_requested",
            terminal=False,
        )
        return result

    return after_tool_cb, on_tool_error_cb


# ---------------------------------------------------------------------------
# BUG-13 workaround: Patch ADK's output-schema postprocessor so that
# ToolFailureResponse dicts (retry guidance from ReflectAndRetryToolPlugin)
# are NOT treated as successful structured output.
#
# Without this patch, get_structured_model_response() matches any
# func_response with name=='set_model_response' and converts it to a
# text-only final event — terminating the worker loop before the model
# gets a second turn.  The patch inspects the response content for the
# REFLECT_AND_RETRY_RESPONSE_TYPE sentinel and returns None when found,
# allowing the agent loop to continue for retry.
#
# Call site in ADK (module-attribute lookup, patchable):
#   base_llm_flow.py:849  _output_schema_processor.get_structured_model_response(...)
# ---------------------------------------------------------------------------


def _patch_output_schema_postprocessor() -> None:
    """Install a retry-aware wrapper around get_structured_model_response.

    Idempotent — safe to call multiple times. Guarded with try/except
    ImportError so that a private ADK module restructure degrades gracefully
    (FM-21 fix: structured output retry disabled, all other functionality intact).
    """
    try:
        import google.adk.flows.llm_flows._output_schema_processor as _osp
    except ImportError:
        logger.warning(
            "BUG-13 patch: cannot import _output_schema_processor — "
            "structured output retry suppression disabled. "
            "ADK may have restructured private modules."
        )
        return

    # Guard against double-patching
    if getattr(_osp.get_structured_model_response, "_rlm_patched", False):
        return

    _original = _osp.get_structured_model_response

    def _retry_aware_get_structured_model_response(
        function_response_event,
    ) -> str | None:
        result = _original(function_response_event)
        if result is None:
            return None
        try:
            parsed = _json.loads(result)
        except (ValueError, TypeError):
            return result
        if (
            isinstance(parsed, dict)
            and parsed.get("response_type") == REFLECT_AND_RETRY_RESPONSE_TYPE
        ):
            _bug13_stats["suppress_count"] += 1
            logger.debug(
                "BUG-13 patch: suppressing postprocessor for ToolFailureResponse "
                "(suppress_count=%d)", _bug13_stats["suppress_count"],
            )
            return None
        return result

    _retry_aware_get_structured_model_response._rlm_patched = True  # type: ignore[attr-defined]
    _osp.get_structured_model_response = _retry_aware_get_structured_model_response


# Apply the patch at import time so it is active before any worker dispatch.
_patch_output_schema_postprocessor()
