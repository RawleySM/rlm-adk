"""Shared dialog content for live context text inspection."""

from __future__ import annotations

from html import escape

from nicegui import ui

from rlm_adk.dashboard.live_models import LiveContextSelection


def render_live_context_viewer(
    selection: LiveContextSelection | None,
    *,
    on_close,
) -> None:
    """Render the single shared context viewer body."""
    with ui.card().classes("live-dashboard w-full").style(
        "width: 100%; height: 100%; "
        "background: linear-gradient(180deg, var(--bg-1), var(--bg-2)); "
        "border: 1px solid var(--border-1); box-shadow: 0 18px 48px rgba(0,0,0,0.32);"
    ):
        with ui.element("div").classes("live-context-viewer__header").style(
            "display: flex; justify-content: space-between; align-items: center; "
            "width: 100%; gap: 0.75rem; padding-bottom: 0.25rem;"
        ):
            with ui.element("div").style(
                "display: flex; flex-direction: column; min-width: 0;"
            ):
                ui.label("State Context Viewer").style(
                    "color: var(--text-0); font-size: 1.1rem; font-weight: 800;"
                )
                ui.label(selection.label if selection else "No state key selected").style(
                    "color: var(--text-0); font-size: 0.96rem; font-weight: 700;"
                )
                if selection is not None:
                    ui.label(selection.raw_key).style(
                        "color: var(--text-1); font-size: 0.76rem; margin-top: 0.18rem;"
                    )
                ui.label("Drag this header to move the viewer.").style(
                    "color: var(--text-1); font-size: 0.72rem; margin-top: 0.28rem;"
                )
            ui.button("Close", on_click=on_close).props("flat color=white")

        text = selection.text if selection is not None else "No state key selected."
        with ui.scroll_area().style(
            "height: calc(100% - 4.75rem); width: 100%; min-width: 0; margin-top: 0.35rem;"
        ):
            ui.html(
                "<pre style=\"white-space: pre-wrap; overflow-wrap: anywhere; "
                "font-family: ui-monospace, SFMono-Regular, monospace; "
                "font-size: 0.82rem; line-height: 1.45; color: var(--text-0); "
                "margin: 0; padding: 0.75rem 0.9rem;\">"
                f"{escape(text)}"
                "</pre>"
            )
