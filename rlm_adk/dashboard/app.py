"""NiceGUI dashboard entry point.

Defines the ``/dashboard`` page with layout, refreshable sections,
keyboard navigation, and the ``launch_dashboard()`` function that
calls ``ui.run()``.
"""

from __future__ import annotations

from nicegui import ui
from nicegui.events import KeyEventArguments

from rlm_adk.dashboard.controller import (
    DashboardController,
    DashboardUI,
)
from rlm_adk.dashboard.data_loader import DashboardDataLoader
from rlm_adk.dashboard.data_models import ChunkCategory

from rlm_adk.dashboard.components.header import build_header
from rlm_adk.dashboard.components.summary_bar import build_summary_bar
from rlm_adk.dashboard.components.navigator import build_navigator
from rlm_adk.dashboard.components.context_bar import build_context_bar_options
from rlm_adk.dashboard.components.chunk_detail import render_chunk_detail
from rlm_adk.dashboard.components.worker_panel import render_worker_panel
from rlm_adk.dashboard.components.token_charts import (
    build_cumulative_chart_options,
    build_iteration_breakdown_table,
)
from rlm_adk.dashboard.components.color_legend import build_color_legend
from rlm_adk.dashboard.components.api_usage import build_api_usage_card


@ui.page("/dashboard")
async def dashboard_page() -> None:
    """Main dashboard page -- each browser tab gets its own instance."""
    loader = DashboardDataLoader()
    controller = DashboardController(loader=loader)
    dashboard_ui = DashboardUI(controller)

    # Initialize available sessions
    controller.state.available_sessions = loader.list_sessions()
    if controller.state.available_sessions:
        await controller.select_session(controller.state.available_sessions[0])

    # Page settings
    ui.dark_mode(True)
    ui.page_title("RLM Context Window Dashboard")

    # ------------------------------------------------------------------
    # Define @ui.refreshable functions INSIDE page scope (NiceGUI review)
    # ------------------------------------------------------------------

    @ui.refreshable
    def reasoning_chart_section() -> None:
        it_data = controller.state.current_iteration_data
        if it_data is None or it_data.reasoning_window is None:
            ui.label("No reasoning data for this iteration").classes(
                "text-body2 text-grey-7"
            )
            return

        window = it_data.reasoning_window
        options = build_context_bar_options(window)

        def on_bar_click(e) -> None:
            chunk_id = e.series_name
            chunk = controller.find_chunk_by_id(chunk_id)
            if chunk:
                controller.select_chunk(chunk)
                chunk_detail_section.refresh()

        ui.label("Reasoning Agent Context Window").classes("text-subtitle1")
        ui.echart(options, on_point_click=on_bar_click).classes("w-full").style(
            "height: 80px"
        )

    @ui.refreshable
    def worker_charts_section() -> None:
        it_data = controller.state.current_iteration_data
        if it_data is None or not it_data.has_workers:
            return
        render_worker_panel(
            it_data.worker_windows,
            controller,
            on_chunk_selected=lambda: chunk_detail_section.refresh(),
        )

    @ui.refreshable
    def chunk_detail_section() -> None:
        render_chunk_detail(controller)

    @ui.refreshable
    def right_panel_section() -> None:
        build_api_usage_card(controller)
        if controller.state.iterations:
            build_iteration_breakdown_table(
                controller.state.iterations,
                controller.state.current_iteration,
                on_row_click=lambda idx: _navigate_to_iter(idx),
            )
            options = build_cumulative_chart_options(
                controller.state.iterations,
                controller.state.current_iteration,
            )
            ui.label("Cumulative Token Usage").classes("text-subtitle1")
            ui.echart(options).classes("w-full").style("height: 250px")

    @ui.refreshable
    def summary_section() -> None:
        build_summary_bar(controller)

    @ui.refreshable
    def nav_section() -> None:
        build_navigator(controller, dashboard_ui)

    # Register all refreshables
    dashboard_ui.register(reasoning_chart_section)
    dashboard_ui.register(worker_charts_section)
    dashboard_ui.register(chunk_detail_section)
    dashboard_ui.register(right_panel_section)
    dashboard_ui.register(summary_section)
    dashboard_ui.register(nav_section)

    # ------------------------------------------------------------------
    # Helper for table row click navigation
    # ------------------------------------------------------------------

    def _navigate_to_iter(idx: int) -> None:
        controller.navigate_to(idx)
        dashboard_ui.refresh_all()

    # ------------------------------------------------------------------
    # Session change handler
    # ------------------------------------------------------------------

    async def on_session_change(session_id: str) -> None:
        if session_id and session_id != controller.state.selected_session_id:
            await controller.select_session(session_id)
            dashboard_ui.refresh_all()

    # ------------------------------------------------------------------
    # Build page layout
    # ------------------------------------------------------------------

    build_header(controller, on_session_change)
    summary_section()
    nav_section()

    # Main 70/30 layout (NiceGUI review: single .style() call, min-width: 0)
    with ui.element("div").style(
        "display: flex; flex-direction: row; width: 100%; gap: 1.5rem"
    ):
        # Left panel (charts)
        with ui.element("div").style(
            "flex: 7; min-width: 0; display: flex; flex-direction: column; gap: 1rem"
        ):
            reasoning_chart_section()
            worker_charts_section()
            chunk_detail_section()

        # Right panel (stats + line chart)
        with ui.element("div").style(
            "flex: 3; min-width: 0; display: flex; flex-direction: column; gap: 1rem"
        ):
            right_panel_section()

    build_color_legend()

    # ------------------------------------------------------------------
    # Keyboard navigation (NiceGUI review: use e.key.arrow_left property)
    # ------------------------------------------------------------------

    def handle_key(e: KeyEventArguments) -> None:
        if not e.action.keydown:
            return
        if e.key.arrow_left:
            controller.navigate(-1)
            dashboard_ui.refresh_all()
        elif e.key.arrow_right:
            controller.navigate(1)
            dashboard_ui.refresh_all()
        elif e.key.home:
            controller.navigate_to(0)
            dashboard_ui.refresh_all()
        elif e.key.end:
            if controller.state.iterations:
                controller.navigate_to(len(controller.state.iterations) - 1)
                dashboard_ui.refresh_all()

    ui.keyboard(on_key=handle_key)


def launch_dashboard(
    host: str = "0.0.0.0",
    port: int = 8080,
    reload: bool = False,
) -> None:
    """Entry point for launching the dashboard.

    Usage:
        python -m rlm_adk.dashboard
        # or
        from rlm_adk.dashboard import launch_dashboard
        launch_dashboard()
    """
    ui.run(
        host=host,
        port=port,
        title="RLM Context Window Dashboard",
        dark=True,
        reload=reload,
    )
