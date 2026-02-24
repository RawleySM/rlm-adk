"""API token usage and reconciliation card."""

from __future__ import annotations

from nicegui import ui

from rlm_adk.dashboard.controller import DashboardController


def build_api_usage_card(controller: DashboardController) -> None:
    """Render the API token usage and reconciliation panel.

    Three states:
    1. Credentials available, data available: Full reconciliation table
    2. Credentials available, no data: Info message
    3. No credentials (default): Shows local metrics only
    """
    summary = controller.state.session_summary
    reconciliation = controller.state.reconciliation

    with ui.card().classes("w-full"):
        ui.label("API Token Usage").classes("text-subtitle1")

        if summary is None:
            ui.label("No session loaded").classes("text-body2 text-grey-7")
            return

        # Always show local metrics
        with ui.element("div").style(
            "display: flex; flex-direction: column; gap: 0.25rem"
        ):
            ui.label(f"Local Input: {summary.total_input_tokens:,}").classes(
                "text-body2"
            )
            ui.label(f"Local Output: {summary.total_output_tokens:,}").classes(
                "text-body2"
            )
            ui.label(f"Total Calls: {summary.total_calls}").classes("text-body2")

        if reconciliation is None:
            ui.label(
                "Cloud usage data unavailable -- showing local metrics only"
            ).classes("text-body2 text-grey-7 q-mt-sm")
            return

        if reconciliation.error_message:
            ui.label(reconciliation.error_message).classes(
                "text-body2 text-grey-7 q-mt-sm"
            )
            return

        # Full reconciliation display
        ui.separator().classes("q-my-sm")

        with ui.element("div").style(
            "display: flex; flex-direction: column; gap: 0.25rem"
        ):
            ui.label(
                f"GCloud Input: {reconciliation.api_input_tokens:,}"
            ).classes("text-body2")
            ui.label(f"GCloud Output: N/A (not tracked)").classes(
                "text-body2 text-grey-7"
            )

            delta_str = f"{reconciliation.input_delta:+,}"
            if reconciliation.input_match:
                ui.label(f"Delta: {delta_str} input").classes(
                    "text-body2 text-positive"
                )
                ui.badge("MATCH", color="positive")
            else:
                ui.label(f"Delta: {delta_str} input").classes(
                    "text-body2 text-negative"
                )
                ui.badge("MISMATCH", color="negative")
