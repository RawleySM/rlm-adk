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
from rlm_adk.dashboard.components.chunk_detail import (
    render_chunk_detail,
    render_worker_detail,
)
from rlm_adk.dashboard.components.token_charts import (
    build_cumulative_chart_options,
    build_iteration_breakdown_table,
)
from rlm_adk.dashboard.components.color_legend import build_color_legend
from rlm_adk.dashboard.components.api_usage import build_workers_panel
from rlm_adk.dashboard.components.output_panel import render_output_panel


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
    def cumulative_chart_section() -> None:
        if controller.state.iterations:
            options = build_cumulative_chart_options(
                controller.state.iterations,
                controller.state.current_iteration,
            )
            ui.label("Cumulative Token Usage").classes("text-subtitle1")
            ui.echart(options).classes("w-full").style("height: 200px")

    @ui.refreshable
    def iter_table_section() -> None:
        if controller.state.iterations:
            build_iteration_breakdown_table(
                controller.state.iterations,
                controller.state.current_iteration,
                on_row_click=lambda idx: _navigate_to_iter(idx),
            )

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
                # Navigate to origin iteration if it differs from current
                if (
                    chunk.iteration_origin >= 0
                    and chunk.iteration_origin != controller.state.current_iteration
                ):
                    controller.navigate_to(chunk.iteration_origin)
                    dashboard_ui.refresh_all()
                else:
                    controller.select_chunk(chunk)
                    chunk_detail_section.refresh()

        # Token summary computed for title row
        cum_input = sum(
            it.reasoning_input_tokens + it.worker_input_tokens
            for it in controller.state.iterations[: controller.state.current_iteration + 1]
        )
        cum_output = sum(
            it.reasoning_output_tokens + it.worker_output_tokens
            for it in controller.state.iterations[: controller.state.current_iteration + 1]
        )
        session_total = 0
        if controller.state.session_summary:
            session_total = (
                controller.state.session_summary.total_input_tokens
                + controller.state.session_summary.total_output_tokens
            )

        # Title row: label + token summaries on same line
        with ui.element("div").style(
            "display: flex; align-items: baseline; gap: 1.5rem"
        ):
            ui.label("Reasoning Agent Context Window").classes("text-subtitle1")
            ui.label(f"{cum_input + cum_output:,} tokens (sum to iteration)").classes(
                "text-caption text-grey-5"
            )
            ui.label(f"{session_total:,} tokens (session total)").classes(
                "text-caption text-grey-5"
            )

        ui.echart(options, on_point_click=on_bar_click).classes("w-full").style(
            "height: 80px"
        )

        # Color legend below bar chart
        build_color_legend()

    @ui.refreshable
    def workers_bar_section() -> None:
        build_workers_panel(
            controller,
            on_worker_click=_handle_worker_badge_click,
        )

    @ui.refreshable
    def output_section() -> None:
        render_output_panel(controller)

    @ui.refreshable
    def chunk_detail_section() -> None:
        render_chunk_detail(controller)

    @ui.refreshable
    def worker_detail_section() -> None:
        render_worker_detail(controller)

    @ui.refreshable
    def summary_section() -> None:
        build_summary_bar(controller)

    @ui.refreshable
    def nav_section() -> None:
        build_navigator(controller, dashboard_ui)

    # Register all refreshables
    dashboard_ui.register(cumulative_chart_section)
    dashboard_ui.register(iter_table_section)
    dashboard_ui.register(reasoning_chart_section)
    dashboard_ui.register(workers_bar_section)
    dashboard_ui.register(output_section)
    dashboard_ui.register(chunk_detail_section)
    dashboard_ui.register(worker_detail_section)
    dashboard_ui.register(summary_section)
    dashboard_ui.register(nav_section)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _navigate_to_iter(idx: int) -> None:
        controller.navigate_to(idx)
        dashboard_ui.refresh_all()

    def _handle_worker_badge_click(agent_name: str) -> None:
        """Select a worker's first context chunk for the worker detail panel."""
        it_data = controller.state.current_iteration_data
        if it_data is None:
            return
        for ww in it_data.worker_windows:
            if ww.agent_name == agent_name:
                if ww.chunks:
                    controller.select_worker_chunk(ww.chunks[0])
                    worker_detail_section.refresh()
                return

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

    # Top row: summary cards + cumulative chart + per-iteration table
    with ui.element("div").style(
        "display: flex; flex-direction: row; width: 100%; gap: 1rem; "
        "align-items: stretch"
    ):
        with ui.element("div"):
            summary_section()
        with ui.element("div").style("flex: 1; min-width: 200px"):
            cumulative_chart_section()
        with ui.element("div").style("flex: 1; min-width: 200px"):
            iter_table_section()

    nav_section()

    # Reasoning agent context bar (full width)
    reasoning_chart_section()

    # Workers horizontal bar (right-aligned via align-self in component)
    workers_bar_section()

    # Three equal panels: chunk detail | output | worker detail
    with ui.element("div").style(
        "display: flex; flex-direction: row; width: 100%; gap: 1rem"
    ):
        with ui.element("div").style("flex: 1; min-width: 0"):
            chunk_detail_section()
        with ui.element("div").style("flex: 1; min-width: 0"):
            output_section()
        with ui.element("div").style("flex: 1; min-width: 0"):
            worker_detail_section()

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
