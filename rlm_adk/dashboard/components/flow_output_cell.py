"""Output cell component for the flow transcript."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from rlm_adk.dashboard.flow_models import FlowOutputCell


def render_flow_output_cell(cell: FlowOutputCell) -> None:
    """Render the output cell below the code cell in notebook tradition."""
    has_content = cell.stdout.strip() or cell.stderr.strip() or cell.child_returns
    if not has_content:
        return

    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0; min-width: 0; "
        "margin-left: 1.2rem; border-left: 2px solid var(--border-1); "
        "padding-left: 0.9rem;"
    ):
        if cell.stdout.strip():
            _output_section("STDOUT", cell.stdout, accent="var(--text-1)")
        if cell.stderr.strip():
            _output_section("STDERR", cell.stderr, accent="var(--accent-child)", error=True)
        if cell.child_returns:
            _child_returns_section(cell.child_returns)


def _output_section(
    label: str,
    text: str,
    *,
    accent: str = "var(--text-1)",
    error: bool = False,
) -> None:
    """Render a collapsible output section."""
    bg = "rgba(255,107,159,0.06)" if error else "rgba(26,35,56,0.4)"
    border_color = "var(--accent-child)" if error else "var(--border-1)"

    with (
        ui.expansion(label)
        .style(
            f"width: 100%; border-radius: 8px; margin-top: 0.4rem; "
            f"background: {bg}; border: 1px solid {border_color};"
        )
        .props("dense default-opened")
    ):
        lines = text.strip().splitlines()
        preview = "\n".join(lines[:50])
        if len(lines) > 50:
            preview += f"\n... ({len(lines) - 50} more lines)"
        ui.html(
            '<pre style="white-space: pre-wrap; overflow-wrap: anywhere; '
            "font-family: ui-monospace, SFMono-Regular, monospace; "
            f"font-size: 0.78rem; line-height: 1.45; color: {accent}; "
            'margin: 0; padding: 0.5rem 0.65rem;">'
            f"{escape(preview)}"
            "</pre>"
        )


def _child_returns_section(child_returns: list) -> None:
    """Render compact child return summary cards."""
    with (
        ui.expansion("CHILD RETURNS")
        .style(
            "width: 100%; border-radius: 8px; margin-top: 0.4rem; "
            "background: rgba(26,35,56,0.4); border: 1px solid var(--border-1);"
        )
        .props("dense default-opened")
    ):
        with ui.element("div").style(
            "display: flex; flex-wrap: wrap; gap: 0.4rem; padding: 0.4rem 0.5rem;"
        ):
            for child in child_returns:
                color = "var(--accent-child)" if child.error else "var(--accent-active)"
                bg = "rgba(255,107,159,0.10)" if child.error else "rgba(126,240,160,0.10)"
                with ui.element("div").style(
                    f"display: inline-flex; align-items: center; gap: 0.3rem; "
                    f"padding: 0.22rem 0.52rem; border-radius: 999px; "
                    f"border: 1px solid {color}; background: {bg};"
                ):
                    ui.label(f"d{child.depth}:f{child.fanout_idx}").style(
                        f"color: {color}; font-size: 0.72rem; font-weight: 700;"
                    )
                    status = "ERR" if child.error else "OK"
                    ui.label(status).style(f"color: {color}; font-size: 0.68rem;")
                    ui.label(f"{child.input_tokens}in/{child.output_tokens}out").style(
                        "color: var(--text-1); font-size: 0.68rem;"
                    )
