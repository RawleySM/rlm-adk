"""LineageAssertionPlugin — test plugin for deep lineage/completion introspection.

Fires for ALL agents (parent + child orchestrators) since child_ctx preserves
plugin_manager via ctx.model_copy().  Captures lineage/completion data at
every callback point across all depths/fanouts.
"""

from __future__ import annotations

import logging
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class LineageAssertionPlugin(BasePlugin):
    """Test plugin capturing lineage/completion data at every callback point."""

    def __init__(self) -> None:
        super().__init__(name="lineage_assertion")
        self.model_events: list[dict[str, Any]] = []
        self.tool_events: list[dict[str, Any]] = []
        self.agent_events: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Agent callbacks
    # ------------------------------------------------------------------

    async def before_agent_callback(
        self, *, callback_context, agent, **_kw
    ) -> None:
        depth = getattr(agent, "_rlm_depth", None)
        fanout_idx = getattr(agent, "_rlm_fanout_idx", None)
        self.agent_events.append({
            "phase": "before",
            "agent_name": getattr(agent, "name", "unknown"),
            "depth": depth,
            "fanout_idx": fanout_idx,
        })
        return None

    async def after_agent_callback(
        self, *, callback_context, agent, **_kw
    ) -> None:
        depth = getattr(agent, "_rlm_depth", None)
        fanout_idx = getattr(agent, "_rlm_fanout_idx", None)
        completion = getattr(agent, "_rlm_terminal_completion", None)
        lineage_status = getattr(agent, "_rlm_lineage_status", None)

        entry: dict[str, Any] = {
            "phase": "after",
            "agent_name": getattr(agent, "name", "unknown"),
            "depth": depth,
            "fanout_idx": fanout_idx,
            "lineage_status": lineage_status,
        }

        if completion is not None and hasattr(completion, "model_dump"):
            entry["terminal_completion"] = completion.model_dump()
        elif completion is not None:
            entry["terminal_completion"] = completion

        self.agent_events.append(entry)
        return None

    # ------------------------------------------------------------------
    # Model callbacks
    # ------------------------------------------------------------------

    async def before_model_callback(
        self, *, callback_context, llm_request, **_kw
    ) -> None:
        inv = callback_context._invocation_context
        agent = inv.agent
        depth = getattr(agent, "_rlm_depth", None)
        fanout_idx = getattr(agent, "_rlm_fanout_idx", None)

        self.model_events.append({
            "phase": "before",
            "agent_name": getattr(agent, "name", "unknown"),
            "depth": depth,
            "fanout_idx": fanout_idx,
            "parent_depth": getattr(agent, "_rlm_parent_depth", None),
            "parent_fanout_idx": getattr(agent, "_rlm_parent_fanout_idx", None),
            "output_schema_name": getattr(agent, "_rlm_output_schema_name", None),
            "pending_request_meta": getattr(agent, "_rlm_pending_request_meta", None),
        })
        return None

    async def after_model_callback(
        self, *, callback_context, llm_response, **_kw
    ) -> None:
        inv = callback_context._invocation_context
        agent = inv.agent
        depth = getattr(agent, "_rlm_depth", None)
        fanout_idx = getattr(agent, "_rlm_fanout_idx", None)

        # Extract lineage from custom_metadata["rlm"] if present
        custom_meta = getattr(llm_response, "custom_metadata", None) or {}
        rlm_lineage = custom_meta.get("rlm")

        self.model_events.append({
            "phase": "after",
            "agent_name": getattr(agent, "name", "unknown"),
            "depth": depth,
            "fanout_idx": fanout_idx,
            "last_response_meta": getattr(agent, "_rlm_last_response_meta", None),
            "rlm_lineage": rlm_lineage,
        })
        return None

    # ------------------------------------------------------------------
    # Tool callbacks
    # ------------------------------------------------------------------

    async def before_tool_callback(
        self, *, tool, tool_args, tool_context, **_kw
    ) -> None:
        inv = tool_context._invocation_context
        agent = inv.agent
        depth = getattr(agent, "_rlm_depth", None)
        fanout_idx = getattr(agent, "_rlm_fanout_idx", None)

        self.tool_events.append({
            "phase": "before",
            "tool_name": getattr(tool, "name", "unknown"),
            "agent_name": getattr(agent, "name", "unknown"),
            "depth": depth,
            "fanout_idx": fanout_idx,
        })
        return None

    async def after_tool_callback(
        self, *, tool, tool_args, tool_context, result, **_kw
    ) -> None:
        inv = tool_context._invocation_context
        agent = inv.agent
        depth = getattr(agent, "_rlm_depth", None)
        fanout_idx = getattr(agent, "_rlm_fanout_idx", None)

        entry: dict[str, Any] = {
            "phase": "after",
            "tool_name": getattr(tool, "name", "unknown"),
            "agent_name": getattr(agent, "name", "unknown"),
            "depth": depth,
            "fanout_idx": fanout_idx,
        }

        # For set_model_response, capture completion data.
        # NOTE: Plugin fires BEFORE agent callbacks, so _rlm_terminal_completion
        # may not be set yet at this point.  Use after_agent_callback for
        # terminal completion assertions instead.
        if getattr(tool, "name", "") == "set_model_response":
            entry["tool_response_type"] = type(result).__name__
            if isinstance(result, dict):
                entry["tool_response_keys"] = sorted(result.keys())

        self.tool_events.append(entry)
        return None

    # ------------------------------------------------------------------
    # Query helpers for test assertions
    # ------------------------------------------------------------------

    def model_events_at(
        self,
        *,
        depth: int,
        fanout_idx: int | None = None,
        phase: str | None = None,
    ) -> list[dict[str, Any]]:
        """Filter model events by depth, fanout, and phase."""
        out = []
        for e in self.model_events:
            if e.get("depth") != depth:
                continue
            if fanout_idx is not None and e.get("fanout_idx") != fanout_idx:
                continue
            if phase is not None and e.get("phase") != phase:
                continue
            out.append(e)
        return out

    def tool_events_for(
        self,
        tool_name: str,
        *,
        depth: int | None = None,
        fanout_idx: int | None = None,
    ) -> list[dict[str, Any]]:
        """Filter tool events by tool name and optional depth/fanout."""
        out = []
        for e in self.tool_events:
            if e.get("tool_name") != tool_name:
                continue
            if depth is not None and e.get("depth") != depth:
                continue
            if fanout_idx is not None and e.get("fanout_idx") != fanout_idx:
                continue
            out.append(e)
        return out

    def completions(self) -> list[dict[str, Any]]:
        """Return all after-agent events that have a terminal_completion."""
        return [
            e for e in self.agent_events
            if e.get("phase") == "after" and e.get("terminal_completion")
        ]

    def completions_at(
        self, *, depth: int, fanout_idx: int | None = None
    ) -> list[dict[str, Any]]:
        """Return completions at a specific depth/fanout."""
        out = []
        for e in self.completions():
            if e.get("depth") != depth:
                continue
            if fanout_idx is not None and e.get("fanout_idx") != fanout_idx:
                continue
            out.append(e)
        return out
