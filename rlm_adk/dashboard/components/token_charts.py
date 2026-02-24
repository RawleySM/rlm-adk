"""Cumulative token line chart and per-iteration breakdown table.

NiceGUI review corrections applied:
- markLine inside series, NOT at top level of options dict
- Table row click uses ``table.on("rowClick", handler, [[], ["iter"], None])``
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from rlm_adk.dashboard.data_models import IterationData


def build_cumulative_chart_options(
    iterations: list[IterationData], current_iter: int
) -> dict:
    """Build ECharts options for the cumulative token line chart.

    NiceGUI review correction: markLine must be inside a series,
    not at the top level of the options dict.
    """
    cum_input: list[int] = []
    cum_output: list[int] = []
    running_in = 0
    running_out = 0
    for it in iterations:
        running_in += it.reasoning_input_tokens + it.worker_input_tokens
        running_out += it.reasoning_output_tokens + it.worker_output_tokens
        cum_input.append(running_in)
        cum_output.append(running_out)

    worker_iters = [i for i, it in enumerate(iterations) if it.has_workers]

    # Combine both markLines into the first series
    mark_line_data = [
        {
            "xAxis": current_iter,
            "lineStyle": {"type": "solid", "color": "#9CA3AF", "width": 2},
            "label": {"formatter": "current", "position": "end"},
        },
    ]
    for wi in worker_iters:
        mark_line_data.append({
            "xAxis": wi,
            "lineStyle": {"type": "dashed", "color": "#F43F5E", "width": 1},
            "label": {"show": False},
        })

    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"show": True, "bottom": 0},
        "xAxis": {
            "type": "category",
            "data": list(range(len(iterations))),
            "name": "Iteration",
        },
        "yAxis": {"type": "value", "name": "Tokens"},
        "series": [
            {
                "name": "Cumulative Input",
                "type": "line",
                "data": cum_input,
                "lineStyle": {"color": "#3B82F6"},
                "itemStyle": {"color": "#3B82F6"},
                "markLine": {
                    "data": mark_line_data,
                    "symbol": "none",
                    "silent": True,
                },
            },
            {
                "name": "Cumulative Output",
                "type": "line",
                "data": cum_output,
                "lineStyle": {"color": "#F97316"},
                "itemStyle": {"color": "#F97316"},
            },
        ],
        "grid": {"left": 60, "right": 20, "top": 20, "bottom": 40},
    }


def build_iteration_breakdown_table(
    iterations: list[IterationData],
    current_iter: int,
    on_row_click: Callable[[int], None],
) -> None:
    """Build a clickable per-iteration breakdown table.

    NiceGUI review correction: use ``table.on("rowClick", handler, ...)``
    with the ``args`` parameter to control which JS event arguments are
    forwarded to Python.
    """
    columns = [
        {"name": "iter", "label": "Iter", "field": "iter", "align": "left"},
        {"name": "input", "label": "Input Tokens", "field": "input", "align": "right"},
        {"name": "output", "label": "Output Tokens", "field": "output", "align": "right"},
        {"name": "delta", "label": "Delta", "field": "delta", "align": "right"},
        {"name": "workers", "label": "Workers", "field": "workers", "align": "right"},
    ]

    rows = []
    prev_total = 0
    for it in iterations:
        total_in = it.reasoning_input_tokens + it.worker_input_tokens
        total_out = it.reasoning_output_tokens + it.worker_output_tokens
        current_total = total_in + total_out
        delta = current_total - prev_total
        worker_count = len(it.worker_windows)
        rows.append({
            "iter": it.iteration_index,
            "input": f"{total_in:,}",
            "output": f"{total_out:,}",
            "delta": f"{delta:+,}" if it.iteration_index > 0 else "-",
            "workers": str(worker_count) if worker_count > 0 else "-",
        })
        prev_total = current_total

    ui.label("Per-Iteration Breakdown").classes("text-subtitle1")

    table = ui.table(
        columns=columns,
        rows=rows,
        row_key="iter",
    ).classes("w-full")

    # Highlight the current iteration row with a distinct background.
    # Custom body slot replaces Quasar's default <q-tr> which normally emits
    # row-click, so we re-emit it via @click on the <q-tr>.
    table.add_slot('body', f'''
        <q-tr :props="props"
               :class="props.row.iter === {current_iter} ? 'bg-blue-grey-9 cursor-pointer' : 'cursor-pointer'"
               @click="() => $parent.$emit('row-click', {{}}, props.row, props.rowIndex)">
            <q-td v-for="col in props.cols" :key="col.name" :props="props">
                {{{{ col.value }}}}
            </q-td>
        </q-tr>
    ''')

    # NiceGUI review: wire row click via Quasar's rowClick event.
    # With the custom body slot, args come from our explicit $emit above:
    # args[0] = {} (empty event placeholder), args[1] = row data, args[2] = rowIndex
    def handle_row_click(e) -> None:
        if e.args and len(e.args) >= 2:
            row_data = e.args[1]
            if isinstance(row_data, dict):
                iter_index = row_data.get("iter", 0)
                on_row_click(iter_index)

    table.on("row-click", handle_row_click)
