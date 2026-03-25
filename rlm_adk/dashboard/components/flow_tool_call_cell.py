"""Renderer for non-execute_code tool call blocks in the flow transcript."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from rlm_adk.dashboard.flow_models import FlowToolCallCell


def render_flow_tool_call_cell(cell: FlowToolCallCell) -> None:
    """Dispatch to the appropriate per-tool renderer."""
    if cell.tool_name == "set_model_response":
        _render_set_model_response(cell)
    elif cell.tool_name == "load_skill":
        _render_load_skill(cell)
    elif cell.tool_name == "list_skills":
        _render_list_skills(cell)
    else:
        _render_generic(cell)


def _render_set_model_response(cell: FlowToolCallCell) -> None:
    """Render the populated output schema from set_model_response."""
    # The tool result/args contain the schema fields (final_answer, reasoning_summary, etc.)
    schema = cell.tool_result or cell.tool_args
    if not schema:
        return

    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.35rem; min-width: 0; "
        "padding: 0.7rem 0.9rem; border-radius: 12px; "
        "border: 1px solid var(--accent-child); "
        "background: rgba(255,107,159,0.06);"
    ):
        # Header
        ui.label("Output Schema").style(
            "color: var(--accent-child); font-size: 0.74rem; font-weight: 700; "
            "letter-spacing: 0.06em; text-transform: uppercase;"
        )
        # Schema fields as key-value rows
        for key, value in schema.items():
            with ui.element("div").style(
                "display: flex; flex-direction: column; gap: 0.15rem; "
                "padding: 0.35rem 0.55rem; border-radius: 8px; "
                "background: rgba(255,107,159,0.04); "
                "border-left: 3px solid var(--accent-child);"
            ):
                ui.label(key).style(
                    "color: var(--accent-child); font-size: 0.72rem; font-weight: 700;"
                )
                display_value = _format_value(value)
                ui.label(display_value).style(
                    "color: var(--text-0); font-size: 0.78rem; "
                    "white-space: pre-wrap; word-break: break-word;"
                )


def _render_load_skill(cell: FlowToolCallCell) -> None:
    """Render skill name + collapsible instruction text (expanded by default)."""
    skill_name = (cell.tool_args or {}).get("name", "unknown")
    # The instruction text comes from the tool result
    instruction = _extract_instruction(cell)

    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.35rem; min-width: 0; "
        "padding: 0.7rem 0.9rem; border-radius: 12px; "
        "border: 1px solid var(--accent-active); "
        "background: rgba(126,240,160,0.06);"
    ):
        ui.label(f"Skill: {skill_name}").style(
            "color: var(--accent-active); font-size: 0.82rem; font-weight: 700;"
        )
        if instruction:
            with (
                ui.expansion("Skill Instructions", value=True)
                .style("width: 100%;")
                .classes("flow-skill-expansion")
            ):
                ui.label(instruction).style(
                    "color: var(--text-0); font-size: 0.76rem; "
                    "white-space: pre-wrap; word-break: break-word; "
                    "padding: 0.4rem 0.5rem; border-radius: 8px; "
                    "background: rgba(126,240,160,0.04); "
                    "border-left: 3px solid var(--accent-active);"
                )


def _render_list_skills(cell: FlowToolCallCell) -> None:
    """Render collapsible skill list text (expanded by default)."""
    result_text = _format_value(cell.tool_result) if cell.tool_result else cell.result_text

    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.35rem; min-width: 0; "
        "padding: 0.7rem 0.9rem; border-radius: 12px; "
        "border: 1px solid var(--accent-root); "
        "background: rgba(87,199,255,0.06);"
    ):
        with (
            ui.expansion("Available Skills", value=True)
            .style("width: 100%;")
            .classes("flow-skill-expansion")
        ):
            ui.label(result_text).style(
                "color: var(--text-0); font-size: 0.76rem; "
                "white-space: pre-wrap; word-break: break-word; "
                "padding: 0.4rem 0.5rem; border-radius: 8px; "
                "background: rgba(87,199,255,0.04); "
                "border-left: 3px solid var(--accent-root);"
            )


def _render_generic(cell: FlowToolCallCell) -> None:
    """Fallback renderer for unknown tool types."""
    with ui.element("div").style(
        "padding: 0.5rem 0.7rem; border-radius: 10px; "
        "border: 1px solid var(--border-1); "
        "background: rgba(159,176,209,0.06);"
    ):
        ui.label(f"Tool: {cell.tool_name}").style(
            "color: var(--text-1); font-size: 0.74rem; font-weight: 700;"
        )
        if cell.result_text:
            ui.label(cell.result_text[:500]).style(
                "color: var(--text-0); font-size: 0.74rem; "
                "white-space: pre-wrap; word-break: break-word;"
            )


def _extract_instruction(cell: FlowToolCallCell) -> str:
    """Extract instruction text from a load_skill tool result."""
    result = cell.tool_result
    if not result:
        return cell.result_text or ""
    # ADK load_skill returns the instruction as a string or in a structured field
    if isinstance(result, dict):
        for key in ("instruction", "instructions", "text", "content"):
            if key in result:
                return str(result[key])
        # If the result is a dict with a single string value, use that
        if "raw" in result:
            return str(result["raw"])
    return cell.result_text or ""


def _format_value(value: object) -> str:
    """Format a value for display."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        try:
            return json.dumps(value, indent=2, default=str)
        except Exception:
            return str(value)
    return str(value)
