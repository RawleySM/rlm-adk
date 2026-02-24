"""Chunk detail panel -- text preview with expand/collapse.

NiceGUI review corrections applied:
- ``ui.code`` only for REPL_CODE chunks; ``ui.html('<pre>...')`` for all others
- ``ui.badge`` uses constructor ``color=`` parameter
- ``ui.scroll_area`` uses ``max-height: 400px`` inside expansions
"""

from __future__ import annotations

import html as html_mod

from nicegui import ui

from rlm_adk.dashboard.controller import DashboardController
from rlm_adk.dashboard.data_models import ChunkCategory


def render_chunk_detail(controller: DashboardController) -> None:
    """Render the chunk detail panel (called from @ui.refreshable scope)."""
    chunk = controller.state.selected_chunk
    if chunk is None:
        ui.label("Click a segment to view details").classes(
            "text-body2 text-grey-7"
        )
        return

    is_code = chunk.category == ChunkCategory.REPL_CODE

    with ui.card().classes("w-full"):
        ui.label(chunk.title).classes("text-h6")

        # Stat badges (NiceGUI review: use color= constructor param)
        with ui.row().style("gap: 0.75rem"):
            ui.badge(f"{chunk.char_count:,} chars", color="grey-7")
            ui.badge(f"~{chunk.estimated_tokens:,} tokens", color="primary")

            # Percentage of iteration total
            it_data = controller.state.current_iteration_data
            if it_data and it_data.reasoning_window:
                total = it_data.reasoning_window.total_tokens
                if total > 0:
                    pct = chunk.estimated_tokens / total * 100
                    ui.badge(f"{pct:.1f}%", color="blue-grey-7")

        # Preview: head
        if is_code:
            ui.code(chunk.text_preview_head, language="python").classes("w-full")
        else:
            _render_text_preview(chunk.text_preview_head)

        # Ellipsis separator if head != tail
        if chunk.text_preview_tail != chunk.text_preview_head:
            ui.label("...").classes("text-center text-grey-6")
            if is_code:
                ui.code(chunk.text_preview_tail, language="python").classes("w-full")
            else:
                _render_text_preview(chunk.text_preview_tail)

        # Full text expansion (NiceGUI review: max-height, not height)
        with ui.expansion("Show full text").classes("w-full"):
            with ui.scroll_area().style("max-height: 400px; min-height: 100px"):
                if is_code:
                    ui.code(chunk.full_text, language="python").classes("w-full")
                else:
                    _render_text_preview(chunk.full_text)


def _render_text_preview(text: str) -> None:
    """Render arbitrary text faithfully without markdown interpretation.

    NiceGUI review: use ``ui.html('<pre>...')`` for non-code text,
    not ``ui.code()`` which processes through markdown rendering.
    """
    escaped = html_mod.escape(text)
    ui.html(
        f'<pre style="white-space: pre-wrap; word-wrap: break-word; '
        f'font-family: monospace; font-size: 0.85rem; padding: 0.75rem; '
        f'background: #1d1d1d; color: #e0e0e0; '
        f'border-radius: 4px; margin: 0; overflow-x: auto;">'
        f"{escaped}</pre>"
    ).classes("w-full")
