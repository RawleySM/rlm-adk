"""Main flow transcript renderer — dispatches to component render functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from rlm_adk.dashboard.flow_models import FlowBlock, FlowTranscript

# Graceful imports — works with partial merges
try:
    from rlm_adk.dashboard.components.flow_reasoning_pane import render_flow_reasoning_pane
except ImportError:  # pragma: no cover
    render_flow_reasoning_pane = None  # type: ignore[assignment]

try:
    from rlm_adk.dashboard.components.flow_code_pane import render_flow_code_pane
except ImportError:  # pragma: no cover
    render_flow_code_pane = None  # type: ignore[assignment]

try:
    from rlm_adk.dashboard.components.flow_connectors import (
        render_flow_arrow,
        render_flow_child_card,
    )
except ImportError:  # pragma: no cover
    render_flow_arrow = None  # type: ignore[assignment]
    render_flow_child_card = None  # type: ignore[assignment]

try:
    from rlm_adk.dashboard.components.flow_output_cell import render_flow_output_cell
except ImportError:  # pragma: no cover
    render_flow_output_cell = None  # type: ignore[assignment]

try:
    from rlm_adk.dashboard.components.flow_context_inspector import (
        render_flow_context_inspector,
    )
except ImportError:  # pragma: no cover
    render_flow_context_inspector = None  # type: ignore[assignment]


def render_flow_transcript(
    transcript: FlowTranscript,
    *,
    on_open_context=None,
    on_click_llm_query_line=None,
    on_expand_child=None,
    on_open_child_window=None,
    on_click_inspector_item=None,
) -> None:
    """Render the complete flow transcript as a scrollable notebook."""
    if not transcript.blocks:
        ui.label("No flow transcript available.").style("color: var(--text-1);")
        return

    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.4rem; "
        "width: 100%; min-width: 0; padding: 0.75rem 0;"
    ):
        for block in transcript.blocks:
            _render_block(
                block,
                on_open_context=on_open_context,
                on_click_llm_query_line=on_click_llm_query_line,
                on_expand_child=on_expand_child,
                on_open_child_window=on_open_child_window,
            )


def _render_block(
    block: FlowBlock,
    *,
    on_open_context,
    on_click_llm_query_line,
    on_expand_child,
    on_open_child_window,
) -> None:
    """Dispatch to the appropriate component render function."""
    kind = block.kind

    if kind == "agent_card" and render_flow_reasoning_pane is not None:
        render_flow_reasoning_pane(
            block,  # type: ignore[arg-type]
            on_open_context=on_open_context,
        )
    elif kind == "arrow" and render_flow_arrow is not None:
        render_flow_arrow(block)  # type: ignore[arg-type]
    elif kind == "code_cell" and render_flow_code_pane is not None:
        render_flow_code_pane(
            block,  # type: ignore[arg-type]
            on_click_llm_query_line=on_click_llm_query_line,
        )
    elif kind == "child_card" and render_flow_child_card is not None:
        render_flow_child_card(
            block,  # type: ignore[arg-type]
            on_expand_child=on_expand_child,
            on_open_child_window=on_open_child_window,
        )
    elif kind == "output_cell" and render_flow_output_cell is not None:
        render_flow_output_cell(block)  # type: ignore[arg-type]
    else:
        # Fallback: show block kind label
        ui.label(f"[{kind}]").style("color: var(--text-1); font-size: 0.72rem;")
