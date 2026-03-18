"""Plugin that pauses before each model call when step mode is active."""

from __future__ import annotations

import re

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from rlm_adk.step_gate import step_gate


class StepModePlugin(BasePlugin):
    """Global plugin that pauses before each model call when step mode is active."""

    def __init__(self) -> None:
        super().__init__(name="step_mode")

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        """If step mode is active, block here until the user advances."""
        if not step_gate.step_mode_enabled:
            return None

        # Extract agent name and depth from callback context
        agent_name = ""
        depth = 0
        try:
            agent = callback_context._invocation_context.agent
            agent_name = getattr(agent, "name", "")
            match = re.search(r"_d(\d+)", agent_name)
            depth = int(match.group(1)) if match else 0
        except Exception:
            pass

        await step_gate.wait_for_advance(agent_name=agent_name, depth=depth)
        return None
