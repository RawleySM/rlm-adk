"""REPLTracingPlugin - Persists REPL traces as JSON artifacts per iteration.

Captures trace summaries from LAST_REPL_RESULT events and saves accumulated
traces as a single JSON artifact at the end of the run.

Enabled via RLM_REPL_TRACE > 0 env var.
"""

import json
import logging
import re
from typing import Any, Optional

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from rlm_adk.state import ITERATION_COUNT, LAST_REPL_RESULT

logger = logging.getLogger(__name__)
_DEPTH_SUFFIX_RE = re.compile(r"@d(\d+)$")


class REPLTracingPlugin(BasePlugin):
    """Persists REPL traces as JSON artifacts per iteration."""

    def __init__(self, name: str = "repl_tracing"):
        super().__init__(name=name)
        self._traces_by_iteration: dict[str, Any] = {}

    @staticmethod
    def _parse_depth(raw_key: str) -> int:
        match = _DEPTH_SUFFIX_RE.search(raw_key)
        if match:
            return int(match.group(1))
        return 0

    async def on_event_callback(
        self,
        *,
        invocation_context: InvocationContext,
        event: Event,
    ) -> Optional[Event]:
        """Capture LAST_REPL_RESULT events that contain trace data."""
        try:
            sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
            for raw_key, repl_result in sd.items():
                if not raw_key.startswith(LAST_REPL_RESULT):
                    continue
                if not repl_result or not isinstance(repl_result, dict):
                    continue
                trace_summary = repl_result.get("trace_summary")
                if not trace_summary:
                    continue

                depth = self._parse_depth(raw_key)
                iteration_key = ITERATION_COUNT if depth == 0 else f"{ITERATION_COUNT}@d{depth}"
                iteration = sd.get(iteration_key, 0)
                trace_key = f"d{depth}:i{iteration}"
                self._traces_by_iteration[trace_key] = {
                    "depth": depth,
                    "iteration": iteration,
                    "state_key": raw_key,
                    "trace_summary": trace_summary,
                }
        except Exception:
            pass
        return None

    async def after_run_callback(
        self,
        *,
        invocation_context: InvocationContext,
    ) -> None:
        """Save accumulated traces as artifact."""
        if not self._traces_by_iteration:
            return

        artifact_service = invocation_context.artifact_service
        if artifact_service is None:
            return

        trace_data = json.dumps(self._traces_by_iteration, indent=2)
        artifact = types.Part.from_bytes(
            data=trace_data.encode("utf-8"),
            mime_type="application/json",
        )
        try:
            await artifact_service.save_artifact(
                app_name=invocation_context.app_name,
                user_id=invocation_context.session.user_id,
                session_id=invocation_context.session.id,
                filename="repl_traces.json",
                artifact=artifact,
            )
        except Exception as e:
            logger.warning("Failed to save REPL traces: %s", e)
