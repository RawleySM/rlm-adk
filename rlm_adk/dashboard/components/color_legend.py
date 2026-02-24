"""Horizontal color legend for chunk categories.

NiceGUI review: use ``ui.badge`` with ``color=`` constructor parameter.
"""

from __future__ import annotations

from nicegui import ui

from rlm_adk.dashboard.data_models import (
    CATEGORY_COLORS,
    CATEGORY_TEXT_COLORS,
    ChunkCategory,
)


def build_color_legend() -> None:
    """Render a horizontal row of color swatches for each chunk category."""
    with ui.element("div").style(
        "display: flex; flex-direction: row; flex-wrap: wrap; "
        "align-items: center; padding: 0.5rem 0; gap: 0.5rem"
    ):
        for category in ChunkCategory:
            hex_color = CATEGORY_COLORS[category]
            text_color = CATEGORY_TEXT_COLORS[category]
            label = category.value.replace("_", " ").title()
            ui.badge(label, color=hex_color, text_color=text_color)
