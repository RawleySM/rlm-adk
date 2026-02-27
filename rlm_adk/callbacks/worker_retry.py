"""Worker retry plugin for structured output self-healing.

Provides:
- WorkerRetryPlugin: Extends ReflectAndRetryToolPlugin to detect empty
  responses from set_model_response and trigger retries.
- make_worker_tool_callbacks(): Factory returning (after_tool_cb, on_tool_error_cb)
  wrapper functions with positional-arg signatures compatible with LlmAgent
  tool callbacks. These capture validated structured results on the worker
  agent and delegate retry logic to the plugin.

Wiring: dispatch.py sets these callbacks on workers when output_schema is provided.
"""

import logging
from typing import Any, Optional

from google.adk.plugins.reflect_retry_tool_plugin import ReflectAndRetryToolPlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


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
    ) -> Optional[dict[str, Any]]:
        """Detect empty responses in set_model_response tool output."""
        if tool.name != "set_model_response":
            return None

        # Check if any value in the tool args is empty
        for key, value in tool_args.items():
            if isinstance(value, str) and not value.strip():
                return {
                    "error": "Empty value",
                    "details": f"Empty string for field '{key}'. The response must contain meaningful content.",
                }

        return None


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
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: Any,
    ) -> Optional[dict[str, Any]]:
        """After-tool callback: capture structured result, delegate to plugin."""
        # On set_model_response success, store validated dict on the agent
        if tool.name == "set_model_response" and isinstance(result, dict):
            agent = tool_context._invocation_context.agent
            agent._structured_result = result  # type: ignore[attr-defined]
            logger.debug(
                "Captured structured result on %s: %s",
                getattr(agent, "name", "?"),
                list(result.keys()),
            )

        # Delegate to plugin for extract_error_from_result checks
        return await plugin.after_tool_callback(
            tool=tool, tool_args=tool_args,
            tool_context=tool_context, result=result,
        )

    async def on_tool_error_cb(
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> Optional[dict[str, Any]]:
        """On-tool-error callback: delegate to plugin for retry/reflection."""
        return await plugin.on_tool_error_callback(
            tool=tool, tool_args=tool_args,
            tool_context=tool_context, error=error,
        )

    return after_tool_cb, on_tool_error_cb
