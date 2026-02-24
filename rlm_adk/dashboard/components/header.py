"""Header bar with title and session selector."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from nicegui import ui

from rlm_adk.dashboard.controller import DashboardController


def build_header(
    controller: DashboardController,
    on_session_change: Callable[[str], Awaitable[None]],
) -> None:
    """Render the header bar with title and session selector dropdown.

    NiceGUI review corrections applied:
    - ui.select uses ``on_change``, ``with_input=True``, ``value=current``
    """
    with ui.element("div").style(
        "display: flex; flex-direction: row; align-items: center; "
        "justify-content: space-between; width: 100%; padding: 0.5rem 0"
    ):
        ui.label("RLM Context Window Dashboard").classes("text-h5 text-weight-bold")

        sessions = controller.state.available_sessions
        current = controller.state.selected_session_id

        if sessions:
            async def handle_change(e: Any) -> None:
                if e.value and e.value != controller.state.selected_session_id:
                    await on_session_change(e.value)

            ui.select(
                options=sessions,
                value=current,
                label="Session",
                on_change=handle_change,
                with_input=True,
            ).classes("w-64")
        else:
            ui.label("No sessions found").classes("text-body2 text-grey-7")
