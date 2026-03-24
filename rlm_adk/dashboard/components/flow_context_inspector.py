"""Right sidebar context inspector for the flow transcript."""

from __future__ import annotations

import json
from html import escape
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from rlm_adk.dashboard.flow_models import FlowInspectorData


def render_flow_context_inspector(
    data: FlowInspectorData,
    *,
    on_click_item=None,
) -> None:
    """Render the right sidebar Context Inspector."""
    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.75rem; "
        "width: 22rem; min-width: 22rem; max-width: 22rem; "
        "padding: 0.85rem 0.75rem; "
        "position: sticky; top: 0; height: 100vh; overflow-y: auto; "
        "border-left: 1px solid var(--border-1); "
        "background: rgba(11,16,32,0.96);"
    ):
        ui.label("Context Inspector").style(
            "color: var(--text-0); font-size: 1.05rem; font-weight: 800;"
        )

        _state_items_section(data, on_click_item=on_click_item)
        _skills_section(data)
        _return_value_section(data)


def _state_items_section(data: FlowInspectorData, *, on_click_item) -> None:
    """Render the State/Context Items key-value table."""
    ui.label("State/Context Items").style(
        "color: var(--text-0); font-size: 0.82rem; font-weight: 700; margin-top: 0.5rem;"
    )

    if not data.state_items:
        ui.label("No state items").style(
            "color: var(--text-1); font-size: 0.76rem; font-style: italic;"
        )
        return

    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.1rem; "
        "border-radius: 8px; overflow: hidden; "
        "border: 1px solid var(--border-1); background: var(--bg-2);"
    ):
        # Header row
        with ui.element("div").style(
            "display: flex; gap: 0.5rem; padding: 0.35rem 0.55rem; "
            "background: rgba(26,35,56,0.6); border-bottom: 1px solid var(--border-1);"
        ):
            ui.label("Key").style(
                "flex: 1; color: var(--text-1); font-size: 0.68rem; "
                "font-weight: 700; text-transform: uppercase;"
            )
            ui.label("Value").style(
                "flex: 1; color: var(--text-1); font-size: 0.68rem; "
                "font-weight: 700; text-transform: uppercase;"
            )

        # Data rows (cap at 20 to keep DOM small)
        for item in data.state_items[:20]:
            cursor = "pointer" if on_click_item else "default"
            el = ui.element("div").style(
                f"display: flex; gap: 0.5rem; padding: 0.3rem 0.55rem; cursor: {cursor}; "
                "border-bottom: 1px solid rgba(46,58,87,0.3);"
            )
            if on_click_item:
                el.on("click.stop", lambda _e, i=item: on_click_item(i))
            with el:
                # Key with depth annotation
                key_text = item.base_key
                depth_label = f"d{item.depth}"
                if item.fanout_idx is not None:
                    depth_label += f":f{item.fanout_idx}"
                with ui.element("div").style("flex: 1; min-width: 0;"):
                    ui.label(key_text).style(
                        "color: var(--text-0); font-size: 0.72rem; "
                        "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
                    )
                    ui.label(depth_label).style("color: var(--text-1); font-size: 0.62rem;")
                # Value preview
                ui.label(
                    item.value_preview[:40]
                    if hasattr(item, "value_preview")
                    else str(item.value)[:40]
                ).style(
                    "flex: 1; color: var(--text-1); font-size: 0.72rem; "
                    "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
                )


def _skills_section(data: FlowInspectorData) -> None:
    """Render enabled skills as green-tinted chips."""
    ui.label("Enabled Skills").style(
        "color: var(--text-0); font-size: 0.82rem; font-weight: 700; margin-top: 0.5rem;"
    )

    if not data.skills:
        ui.label("No skills loaded").style(
            "color: var(--text-1); font-size: 0.76rem; font-style: italic;"
        )
        return

    with ui.element("div").style("display: flex; flex-wrap: wrap; gap: 0.35rem;"):
        for name, description in data.skills:
            with ui.element("div").style(
                "display: inline-flex; align-items: center; "
                "padding: 0.22rem 0.5rem; border-radius: 999px; "
                "border: 1px solid var(--accent-active); "
                "background: rgba(126,240,160,0.12);"
            ):
                ui.label(name).style(
                    "color: var(--accent-active); font-size: 0.72rem; font-weight: 600;"
                ).tooltip(description)


def _return_value_section(data: FlowInspectorData) -> None:
    """Render the return value preview as syntax-highlighted JSON."""
    ui.label("Return Value (Preview)").style(
        "color: var(--text-0); font-size: 0.82rem; font-weight: 700; margin-top: 0.5rem;"
    )

    if not data.return_value_json:
        ui.label("(n/a)").style("color: var(--text-1); font-size: 0.76rem; font-style: italic;")
        return

    # Try to pretty-print JSON
    try:
        parsed = json.loads(data.return_value_json)
        formatted = json.dumps(parsed, indent=2)
    except (json.JSONDecodeError, TypeError):
        formatted = data.return_value_json

    ui.html(
        '<pre style="white-space: pre-wrap; overflow-wrap: anywhere; '
        "font-family: ui-monospace, SFMono-Regular, monospace; "
        "font-size: 0.74rem; line-height: 1.4; color: var(--text-0); "
        "margin: 0; padding: 0.55rem 0.65rem; border-radius: 8px; "
        'background: var(--bg-2); border: 1px solid var(--border-1);">'
        f"{escape(formatted)}"
        "</pre>"
    )
