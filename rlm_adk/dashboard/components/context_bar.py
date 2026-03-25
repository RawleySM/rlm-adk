"""ECharts stacked horizontal bar for context window visualization.

NiceGUI review corrections applied:
- One series per chunk (not per category) for click identification
- ``:formatter`` (colon prefix) with JS function for tooltip
- ``on_point_click`` constructor parameter on ``ui.echart``
"""

from __future__ import annotations

from rlm_adk.dashboard.data_models import (
    CATEGORY_COLORS,
    ContextWindow,
)


def build_context_bar_options(window: ContextWindow) -> dict:
    """Build ECharts options for a stacked horizontal bar.

    One series per chunk so that ``on_point_click`` can identify
    individual chunks via ``e.series_name`` (= chunk_id).
    """
    series = []
    total_tokens = sum(c.estimated_tokens for c in window.chunks)

    for chunk in window.chunks:
        series.append(
            {
                "name": chunk.chunk_id,
                "type": "bar",
                "stack": "total",
                "data": [chunk.estimated_tokens],
                "itemStyle": {"color": CATEGORY_COLORS.get(chunk.category, "#888888")},
                "emphasis": {"itemStyle": {"borderWidth": 2, "borderColor": "#fff"}},
            }
        )

    # NiceGUI review: use ':formatter' for JS function (colon prefix)
    formatter_js = (
        """(params) => {
        const total = %d;
        const pct = total > 0 ? (params.value / total * 100).toFixed(1) : '0.0';
        return params.seriesName + ': ' + params.value.toLocaleString()
            + ' tokens (' + pct + '%%' + ')';
    }"""
        % total_tokens
    )

    return {
        "tooltip": {
            "trigger": "item",
            ":formatter": formatter_js,
        },
        "xAxis": {"type": "value", "show": False},
        "yAxis": {
            "type": "category",
            "data": [window.agent_name],
            "axisLabel": {"show": True},
        },
        "series": series,
        "grid": {"left": 120, "right": 20, "top": 10, "bottom": 10},
    }
