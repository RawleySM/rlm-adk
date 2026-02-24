"""Reasoning output panel -- model response text + worker details."""

from __future__ import annotations

import html as html_mod

from nicegui import ui

from rlm_adk.dashboard.controller import DashboardController
from rlm_adk.dashboard.data_models import ModelOutput


def render_output_panel(controller: DashboardController) -> None:
    """Render the model output panel for the current iteration.

    Shows reasoning agent output text with preview/expansion,
    token badges, and per-worker output summary.
    """
    it_data = controller.state.current_iteration_data
    if it_data is None:
        return

    reasoning_out = it_data.reasoning_output
    worker_outs = it_data.worker_outputs

    if reasoning_out is None and not worker_outs:
        ui.label("No model output captured for this iteration").classes(
            "text-body2 text-grey-7"
        )
        return

    # --- Reasoning output ---
    if reasoning_out is not None:
        with ui.card().classes("w-full").style(
            "border-left: 4px solid #10B981"
        ):
            ui.label("REASONING_AGENT OUTPUT").classes(
                "text-subtitle1 text-weight-bold"
            )

            # Token badges
            with ui.row().style("gap: 0.75rem"):
                ui.badge(
                    f"{reasoning_out.output_tokens:,} output tokens",
                    color="green-8",
                )
                ui.badge(
                    f"{reasoning_out.output_chars:,} chars",
                    color="grey-7",
                )
                if reasoning_out.thoughts_tokens > 0:
                    ui.badge(
                        f"{reasoning_out.thoughts_tokens:,} thought tokens",
                        color="purple-7",
                    )
                if reasoning_out.error:
                    ui.badge("ERROR", color="negative")

            # Worker summary line
            if worker_outs:
                total_worker_input = sum(w.input_tokens for w in worker_outs)
                ui.label(
                    f"{len(worker_outs)} workers: "
                    f"{total_worker_input:,} total input tokens"
                ).classes("text-body2 text-grey-5")

            # Error message
            if reasoning_out.error and reasoning_out.error_message:
                ui.label(reasoning_out.error_message).classes(
                    "text-body2 text-negative"
                )

            # Output text preview
            if reasoning_out.output_text:
                _render_output_preview(
                    reasoning_out.text_preview_head,
                    reasoning_out.text_preview_tail,
                )

                # Full output expansion
                with ui.expansion("Show full output").classes("w-full"):
                    with ui.scroll_area().style(
                        "max-height: 500px; min-height: 100px"
                    ):
                        _render_output_text(reasoning_out.output_text)
            elif not reasoning_out.error:
                ui.label("(empty response)").classes(
                    "text-body2 text-grey-7"
                )

            # Per-worker details expansion
            if worker_outs:
                with ui.expansion(
                    "Show individual workers"
                ).classes("w-full"):
                    for wo in worker_outs:
                        _render_worker_output_row(wo)


def _render_output_preview(head: str, tail: str) -> None:
    """Render head/tail preview with ellipsis."""
    _render_output_text(head)
    if tail != head:
        ui.label("...").classes("text-center text-grey-6")
        _render_output_text(tail)


def _render_output_text(text: str) -> None:
    """Render output text in a styled pre block."""
    escaped = html_mod.escape(text)
    ui.html(
        f'<pre style="white-space: pre-wrap; word-wrap: break-word; '
        f'font-family: monospace; font-size: 0.85rem; padding: 0.75rem; '
        f'background: #2a2a1a; color: #e8d44d; '
        f'border-radius: 4px; margin: 0; overflow-x: auto;">'
        f"{escaped}</pre>"
    ).classes("w-full")


def _render_worker_output_row(wo: ModelOutput) -> None:
    """Render a single worker output row with badges."""
    with ui.element("div").style(
        "display: flex; align-items: center; gap: 0.5rem; "
        "padding: 0.25rem 0; border-bottom: 1px solid #333"
    ):
        ui.label(wo.agent_name).classes("text-body2").style("min-width: 140px")
        ui.badge(f"{wo.input_tokens:,} in", color="blue-7")
        ui.badge(f"{wo.output_tokens:,} out", color="green-7")
        if wo.error:
            ui.badge("ERR", color="negative")
