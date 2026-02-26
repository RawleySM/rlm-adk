"""Worker retry plugin for format validation and retry.

Provides a submit_answer FunctionTool and a WorkerRetryPlugin that extends
ReflectAndRetryToolPlugin to detect format/validation errors in worker
responses and trigger retries.

NOTE: Not yet wired into _create_worker() — the agent-level callback
signatures (AfterToolCallback, OnToolErrorCallback) need verification
against the plugin method signatures before integration.
"""

import logging
from typing import Any, Callable, Optional

from google.adk.plugins.reflect_retry_tool_plugin import ReflectAndRetryToolPlugin
from google.adk.tools import FunctionTool
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


def submit_answer(response: str) -> dict:
    """Submit the final answer.

    The response parameter must contain the complete answer text.
    """
    return {"status": "ok", "response": response}


SUBMIT_ANSWER_TOOL = FunctionTool(func=submit_answer)


class WorkerRetryPlugin(ReflectAndRetryToolPlugin):
    """Extends ReflectAndRetryToolPlugin for worker format validation.

    Override extract_error_from_result() to detect format errors in
    submit_answer tool results (e.g., empty response, truncated JSON).
    """

    def __init__(self, max_retries: int = 2):
        super().__init__(max_retries=max_retries)
        self._format_validator: Optional[Callable[[str], Optional[str]]] = None

    async def extract_error_from_result(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: Any,
    ) -> Optional[dict[str, Any]]:
        """Detect format errors in submit_answer tool output."""
        if tool.name != "submit_answer":
            return None

        response = tool_args.get("response", "")
        if not response or not response.strip():
            return {"error": "Empty response", "details": "The response must contain text."}

        # If a format validator is set, run it
        if self._format_validator is not None:
            validation_error = self._format_validator(response)
            if validation_error:
                return {"error": "Format error", "details": validation_error}

        return None
