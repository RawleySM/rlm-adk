"""Lineage header component for child drill-down pages."""

from __future__ import annotations

from nicegui import ui


def render_child_window_header(
    *,
    session_id: str,
    pane_id: str,
    agent_name: str = "",
    depth: int = 0,
    fanout_idx: int | None = None,
    parent_label: str = "",
) -> None:
    """Render the lineage header with back-link for a child window."""
    fanout = "root" if fanout_idx is None else f"f{fanout_idx}"
    child_label = f"d{depth}:{fanout}"
    if agent_name:
        child_label = f"{agent_name} ({child_label})"

    with ui.element("div").style(
        "display: flex; align-items: center; gap: 0.75rem; "
        "padding: 0.65rem 1rem; "
        "border-bottom: 1px solid var(--border-1); "
        "background: rgba(11,16,32,0.96);"
    ):
        # Back link to parent session
        parent_url = "/live"
        ui.link("\u2190 Back to session", parent_url).style(
            "color: var(--accent-root); font-size: 0.82rem; text-decoration: none;"
        )

        # Lineage breadcrumb
        if parent_label:
            ui.label("\u2192").style("color: var(--text-1); font-size: 0.82rem;")
            ui.label(parent_label).style("color: var(--text-1); font-size: 0.82rem;")

        ui.label("\u2192").style("color: var(--text-1); font-size: 0.82rem;")
        with ui.element("div").style(
            "display: inline-flex; align-items: center; gap: 0.3rem; "
            "padding: 0.22rem 0.58rem; border-radius: 999px; "
            "border: 1px solid var(--accent-child); "
            "background: rgba(255,107,159,0.12);"
        ):
            ui.label(child_label).style(
                "color: var(--accent-child); font-size: 0.78rem; font-weight: 700;"
            )
