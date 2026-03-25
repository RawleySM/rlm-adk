"""Flow connectors: directional arrows and inline child agent cards."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from rlm_adk.dashboard.flow_models import FlowArrow, FlowChildCard

# Arrow unicode + color by kind/direction
_ARROW_UNICODE = {
    "down": "\u2193",
    "right": "\u2192",
    "left": "\u2190",
}

_ARROW_COLORS = {
    "execute_code": "var(--accent-warning)",
    "llm_query": "var(--accent-root)",
    "return_value": "var(--accent-active)",
    "set_model_response": "var(--accent-child)",
    "load_skill": "var(--accent-active)",
    "list_skills": "var(--accent-root)",
}

_STATUS_COLORS = {
    "running": "var(--accent-active)",
    "completed": "var(--accent-root)",
    "error": "var(--accent-child)",
    "cancelled": "var(--accent-warning)",
    "idle": "var(--text-1)",
}


def render_flow_arrow(arrow: FlowArrow) -> None:
    """Render a directional arrow connector between flow blocks."""
    color = _ARROW_COLORS.get(arrow.arrow_kind, "var(--text-1)")
    unicode_arrow = _ARROW_UNICODE.get(arrow.direction, "\u2193")

    justify = "center"
    if arrow.direction == "right":
        justify = "flex-start"
    elif arrow.direction == "left":
        justify = "flex-end"

    padding_left = "3.5rem" if arrow.direction == "right" else "0"
    padding_right = "3.5rem" if arrow.direction == "left" else "0"

    with ui.element("div").style(
        f"display: flex; align-items: center; justify-content: {justify}; "
        f"padding: 0.25rem 0; padding-left: {padding_left}; padding-right: {padding_right}; "
        "min-width: 0;"
    ):
        with ui.element("div").style(
            f"display: inline-flex; align-items: center; gap: 0.35rem; "
            f"padding: 0.22rem 0.62rem; border-radius: 999px; "
            f"border: 1px solid {color}; "
            f"background: color-mix(in srgb, {color} 10%, transparent);"
        ):
            ui.label(unicode_arrow).style(f"color: {color}; font-size: 1rem; font-weight: 700;")
            if arrow.label:
                ui.label(arrow.label).style(
                    f"color: {color}; font-size: 0.74rem; font-weight: 600;"
                )


def render_flow_child_card(
    child: FlowChildCard,
    *,
    on_expand_child=None,
    on_open_child_window=None,
) -> None:
    """Render a compact inline child agent card."""
    error_border = "var(--accent-child)" if child.error else "var(--border-1)"
    error_bg = "rgba(255,107,159,0.10)" if child.error else "rgba(159,176,209,0.06)"

    with ui.element("div").style(
        f"display: flex; flex-direction: column; gap: 0.25rem; "
        f"padding: 0.55rem 0.8rem; border-radius: 12px; "
        f"margin-left: 3.5rem; max-width: 36rem; "
        f"border: 1px solid {error_border}; background: {error_bg};"
    ):
        # Header: Child Agent label + depth/fanout + status + tokens + elapsed
        with ui.element("div").style(
            "display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;"
        ):
            ui.label("Child Agent").style(
                "color: var(--text-0); font-size: 0.78rem; font-weight: 700;"
            )
            ui.label(f"(d{child.depth}:f{child.fanout_idx})").style(
                "color: var(--accent-child); font-size: 0.72rem; font-weight: 700;"
            )
            status_color = _STATUS_COLORS.get(child.status, "var(--text-1)")
            status_text = "ERROR" if child.error else child.status.upper()
            ui.label(status_text).style(
                f"color: {status_color}; font-size: 0.68rem; font-weight: 700;"
            )
            ui.label(f"{child.input_tokens}in / {child.output_tokens}out").style(
                "color: var(--text-1); font-size: 0.68rem;"
            )
            if child.thought_tokens:
                ui.label(f"{child.thought_tokens}think").style(
                    "color: var(--text-1); font-size: 0.68rem;"
                )
            if child.elapsed_ms:
                ui.label(f"{child.elapsed_ms:.0f}ms").style(
                    "color: var(--text-1); font-size: 0.68rem;"
                )

        # Prompt preview
        if child.prompt_preview:
            ui.label(child.prompt_preview).style(
                "color: var(--text-0); font-size: 0.74rem; "
                "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
            )

        # Result preview
        if child.result_preview:
            ui.label(child.result_preview).style(
                "color: var(--text-1); font-size: 0.72rem; "
                "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
            )

        # Error message
        if child.error_message:
            ui.label(child.error_message[:160]).style(
                "color: var(--accent-child); font-size: 0.72rem;"
            )

        # Action buttons
        with ui.element("div").style(
            "display: flex; align-items: center; gap: 0.4rem; margin-top: 0.15rem;"
        ):
            if on_expand_child:
                ui.button(
                    "Expand",
                    on_click=lambda: on_expand_child(child),
                ).props("flat dense size=xs").style(
                    "color: var(--accent-root); font-size: 0.68rem;"
                )
            if on_open_child_window and child.pane_id:
                ui.button(
                    "Open window",
                    on_click=lambda: on_open_child_window(child),
                ).props("flat dense size=xs").style(
                    "color: var(--accent-root); font-size: 0.68rem;"
                )
