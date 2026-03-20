"""LiteLLMCostTrackingPlugin - Per-call and cumulative cost tracking.

Uses ``litellm.completion_cost()`` to estimate costs from usage metadata
on each model response.  Writes state key:

- ``obs:litellm_total_cost`` — running total across all model calls

Per-call cost is stored on the plugin instance (``last_call_cost``)
for programmatic access, not in session state (per-call provenance
belongs in the lineage plane, not the state plane).

LIMITATION (MED-2): This plugin only tracks costs for the root reasoning
agent's model calls.  Child orchestrator costs (from llm_query /
llm_query_batched) are NOT tracked because ADK gives child agents isolated
invocation contexts that do not fire plugin callbacks.  For complete cost
tracking across all agents (including workers and child orchestrators),
configure ``litellm.success_callback`` at the Router level — this hooks
into every LiteLLM completion call regardless of which ADK agent initiated
it.
"""

import logging

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from rlm_adk.state import OBS_LITELLM_TOTAL_COST

try:
    import litellm
except ImportError:
    litellm = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class LiteLLMCostTrackingPlugin(BasePlugin):
    """Track per-model-call costs via litellm.completion_cost().

    LIMITATION: This plugin only tracks costs for the root reasoning agent's
    model calls. Child orchestrator costs (from llm_query/llm_query_batched)
    are NOT tracked because ADK gives child agents isolated invocation contexts
    that do not fire plugin callbacks. For complete cost tracking, use
    litellm.success_callback at the Router level.
    """

    def __init__(self):
        super().__init__(name="litellm_cost_tracking")
        self._total_cost = 0.0
        self.last_call_cost: float = 0.0

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        """Record per-call cost from litellm.completion_cost()."""
        try:
            if litellm is None:
                return None

            usage = llm_response.usage_metadata
            if not usage:
                return None

            cost = litellm.completion_cost(
                model=getattr(llm_response, "model_version", "unknown"),
                prompt_tokens=usage.prompt_token_count or 0,
                completion_tokens=usage.candidates_token_count or 0,
            )
            self._total_cost += cost
            self.last_call_cost = round(cost, 6)
            # Session aggregate — state plane
            callback_context.state[OBS_LITELLM_TOTAL_COST] = round(self._total_cost, 6)
        except Exception as e:
            logger.debug("LiteLLM cost tracking error: %s", e)
        return None
