"""Worker context window panel with collapse at >=6 workers."""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from rlm_adk.dashboard.components.context_bar import build_context_bar_options
from rlm_adk.dashboard.controller import DashboardController
from rlm_adk.dashboard.data_models import ContextWindow


COLLAPSE_THRESHOLD = 6


def render_worker_panel(
    worker_windows: list[ContextWindow],
    controller: DashboardController,
    on_chunk_selected: Callable[[], None],
) -> None:
    """Render worker context window bars.

    Collapse rules:
    - 0 workers: panel hidden (caller checks)
    - 1-5 workers: individual bars shown
    - 6+ workers: collapsed summary with ui.expansion toggle
    """
    if not worker_windows:
        return

    count = len(worker_windows)
    total_tokens = sum(w.total_tokens for w in worker_windows)

    ui.label(f"Worker Context Windows ({count} workers)").classes("text-subtitle1")

    if count < COLLAPSE_THRESHOLD:
        # Show individual bars
        for window in worker_windows:
            _render_worker_bar(window, controller, on_chunk_selected)
    else:
        # Collapsed summary with expansion toggle
        with ui.card().classes("w-full q-pa-sm"):
            ui.label(
                f"{count} workers: {total_tokens:,} total input tokens"
            ).classes("text-subtitle2")

            with ui.expansion("Show individual workers").classes("w-full"):
                for window in worker_windows:
                    _render_worker_bar(window, controller, on_chunk_selected)


def _render_worker_bar(
    window: ContextWindow,
    controller: DashboardController,
    on_chunk_selected: Callable[[], None],
) -> None:
    """Render a single worker's stacked horizontal bar."""
    options = build_context_bar_options(window)

    def on_bar_click(e) -> None:
        chunk_id = e.series_name
        # Search in worker windows
        for chunk in window.chunks:
            if chunk.chunk_id == chunk_id:
                controller.select_chunk(chunk)
                on_chunk_selected()
                return

    ui.echart(options, on_point_click=on_bar_click).classes("w-full").style(
        "height: 60px"
    )
