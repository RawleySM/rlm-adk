"""Iteration navigation buttons and label."""

from __future__ import annotations

from nicegui import ui

from rlm_adk.dashboard.controller import DashboardController, DashboardUI


def build_navigator(
    controller: DashboardController,
    dashboard_ui: DashboardUI,
) -> None:
    """Render iteration navigation buttons and current-iteration label."""
    total = controller.state.total_iterations
    current = controller.state.current_iteration
    it_data = controller.state.current_iteration_data
    worker_count = len(it_data.worker_windows) if it_data else 0

    with ui.row().style("gap: 0.5rem; align-items: center"):
        ui.button(
            "<<",
            on_click=lambda: _nav(controller, dashboard_ui, "first"),
        ).props("flat dense")

        ui.button(
            "<",
            on_click=lambda: _nav(controller, dashboard_ui, "prev"),
        ).props("flat dense")

        label_parts = [f"Iteration {current} of {total - 1}" if total > 0 else "No iterations"]
        if worker_count > 0:
            label_parts.append(f"[{worker_count} workers]")
        ui.label(" ".join(label_parts)).classes("text-subtitle2")

        ui.button(
            ">",
            on_click=lambda: _nav(controller, dashboard_ui, "next"),
        ).props("flat dense")

        ui.button(
            ">>",
            on_click=lambda: _nav(controller, dashboard_ui, "last"),
        ).props("flat dense")


def _nav(
    controller: DashboardController,
    dashboard_ui: DashboardUI,
    direction: str,
) -> None:
    """Handle navigation button clicks."""
    if direction == "first":
        controller.navigate_to(0)
    elif direction == "prev":
        controller.navigate(-1)
    elif direction == "next":
        controller.navigate(1)
    elif direction == "last":
        if controller.state.iterations:
            controller.navigate_to(len(controller.state.iterations) - 1)
    dashboard_ui.refresh_all()
