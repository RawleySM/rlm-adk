"""Session summary bar -- stat cards for model, iterations, tokens, time."""

from __future__ import annotations

import time as _time

from nicegui import ui

from rlm_adk.dashboard.controller import DashboardController


def build_summary_bar(controller: DashboardController) -> None:
    """Render a row of stat cards summarizing the current session."""
    summary = controller.state.session_summary
    if summary is None:
        ui.label("No session loaded").classes("text-body2 text-grey-7")
        return

    duration = summary.end_time - summary.start_time if summary.end_time > summary.start_time else 0
    if duration >= 60:
        time_str = f"{duration / 60:.1f}m"
    else:
        time_str = f"{duration:.1f}s"

    cards = [
        ("Model", summary.model),
        ("Iterations", str(summary.total_iterations)),
        ("Input Tokens", f"{summary.total_input_tokens:,}"),
        ("Output Tokens", f"{summary.total_output_tokens:,}"),
        ("Duration", time_str),
        ("Calls", f"{summary.reasoning_calls}R / {summary.worker_calls}W"),
    ]

    with ui.row().style("gap: 0.75rem; flex-wrap: wrap"):
        for label, value in cards:
            with ui.card().classes("q-pa-sm"):
                ui.label(label).classes("text-caption text-grey-7")
                ui.label(value).classes("text-subtitle1 text-weight-bold")
