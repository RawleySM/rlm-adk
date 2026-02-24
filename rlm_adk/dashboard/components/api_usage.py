"""Worker token usage panel -- horizontal badge bar."""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from rlm_adk.dashboard.controller import DashboardController


def build_workers_panel(
    controller: DashboardController,
    on_worker_click: Callable[[str], None] | None = None,
) -> None:
    """Render a horizontal workers bar: ``worker_1 <in><out> | worker_2 ...``

    Spans full width, sitting directly below the reasoning agent context bar.
    When *on_worker_click* is provided, the ``{N} in`` badges become
    clickable and trigger the callback with the worker's ``agent_name``.
    """
    it_data = controller.state.current_iteration_data
    if it_data is None or not it_data.worker_outputs:
        return

    with ui.element("div").style(
        "display: flex; flex-direction: row; align-items: center; "
        "gap: 0.25rem; flex-wrap: wrap; align-self: flex-end"
    ):
        ui.label("WORKERS").classes(
            "text-body2 text-weight-bold"
        ).style("color: #F43F5E; margin-right: 0.5rem")

        for i, wo in enumerate(it_data.worker_outputs):
            if i > 0:
                ui.label("|").classes("text-body2 text-grey-6").style(
                    "margin: 0 0.25rem"
                )
            ui.label(wo.agent_name).classes("text-body2").style(
                "color: #F43F5E"
            )
            if on_worker_click:
                with ui.element("span").style("cursor: pointer").on(
                    "click",
                    lambda _e, name=wo.agent_name: on_worker_click(name),
                ):
                    ui.badge(f"{wo.input_tokens:,} in", color="blue-7")
            else:
                ui.badge(f"{wo.input_tokens:,} in", color="blue-7")
            ui.badge(f"{wo.output_tokens:,} out", color="green-7")
            if wo.error:
                ui.badge("ERR", color="negative")
