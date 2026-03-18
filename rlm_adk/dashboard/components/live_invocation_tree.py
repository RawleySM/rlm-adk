"""Recursive invocation tree for the live dashboard."""

from __future__ import annotations

from nicegui import ui

from rlm_adk.dashboard.live_models import (
    LiveContextBannerItem,
    LiveInvocation,
    LiveInvocationNode,
)

_SCOPE_ORDER = [
    "dynamic_instruction_param",
    "state_key",
    "request_chunk",
]

_SCOPE_LABELS = {
    "dynamic_instruction_param": "Dynamic Context",
    "state_key": "State Keys",
    "request_chunk": "Request Chunks",
}


def _display_agent_name(invocation: LiveInvocation) -> str:
    return invocation.agent_name


def render_live_invocation_tree(
    nodes: list[LiveInvocationNode],
    *,
    on_open_context,
    on_select_iteration,
    on_open_repl_output,
) -> None:
    """Render the visible invocation tree."""
    if not nodes:
        ui.label("No live invocation context available.").style("color: var(--text-1);")
        return

    with ui.element("div").style(
        "display: flex; flex-direction: column; width: 100%; gap: 0.9rem; min-width: 0;"
    ):
        for node in nodes:
            _render_node(
                node,
                on_open_context=on_open_context,
                on_select_iteration=on_select_iteration,
                on_open_repl_output=on_open_repl_output,
            )


def _render_node(
    node: LiveInvocationNode,
    *,
    on_open_context,
    on_select_iteration,
    on_open_repl_output,
) -> None:
    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.7rem; min-width: 0; "
        "padding: 0.8rem 0.95rem; border-radius: 16px; "
        "border: 1px solid var(--border-1); "
        "background: linear-gradient(180deg, rgba(19,26,43,0.96), rgba(11,16,32,0.96));"
    ):
        _header(
            node,
            on_select_iteration=on_select_iteration,
        )
        _scope_groups(node, on_open_context=on_open_context)

    for child in node.child_nodes:
        _render_child_row(
            child,
            on_open_context=on_open_context,
            on_select_iteration=on_select_iteration,
            on_open_repl_output=on_open_repl_output,
        )


def _render_child_row(
    node: LiveInvocationNode,
    *,
    on_open_context,
    on_select_iteration,
    on_open_repl_output,
) -> None:
    with ui.element("div").style("display: flex; align-items: stretch; gap: 1rem; min-width: 0;"):
        _repl_panel(node, on_open_repl_output=on_open_repl_output)
        with ui.element("div").style("flex: 1; min-width: 0;"):
            _render_node(
                node,
                on_open_context=on_open_context,
                on_select_iteration=on_select_iteration,
                on_open_repl_output=on_open_repl_output,
            )


def _header(node: LiveInvocationNode, *, on_select_iteration) -> None:
    with ui.element("div").style(
        "display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; "
        "gap: 0.75rem; min-width: 0;"
    ):
        with ui.element("div").style(
            "display: flex; align-items: center; gap: 0.55rem; min-width: 0; flex-wrap: wrap;"
        ):
            ui.label(_display_agent_name(node.invocation)).style(
                "color: var(--text-0); font-size: 0.98rem; font-weight: 700;"
            )
            with ui.element("div").style(
                "display: inline-flex; align-items: center; border-radius: 999px; "
                "padding: 0.22rem 0.58rem; border: 1px solid var(--border-1); "
                "background: rgba(126,240,160,0.10);"
            ):
                ui.label(f"{node.invocation_context_tokens} tok").style(
                    "color: var(--accent-active); font-size: 0.76rem; font-weight: 700;"
                )
        _iteration_rail(node, on_select_iteration=on_select_iteration)


def _iteration_rail(node: LiveInvocationNode, *, on_select_iteration) -> None:
    with ui.element("div").style(
        "display: inline-flex; flex-wrap: wrap; align-items: center; gap: 0.15rem;"
    ):
        for invocation in node.available_invocations:
            active = invocation.invocation_id == node.invocation.invocation_id
            color = "var(--text-0)" if active else "var(--text-1)"
            weight = "700" if active else "500"
            label = f"|{invocation.iteration}|"
            ui.label(label).style(
                f"color: {color}; font-size: 0.88rem; font-weight: {weight}; cursor: pointer;"
            ).on(
                "click.stop",
                lambda _e,
                pane_id=node.pane_id,
                invocation_id=invocation.invocation_id: on_select_iteration(
                    pane_id,
                    invocation_id,
                ),
            )


def _scope_groups(node: LiveInvocationNode, *, on_open_context) -> None:
    grouped: dict[str, list[LiveContextBannerItem]] = {}
    for item in node.context_items:
        grouped.setdefault(item.scope, []).append(item)

    for scope in _SCOPE_ORDER + [key for key in grouped if key not in _SCOPE_ORDER]:
        scope_items = grouped.get(scope, [])
        if not scope_items:
            continue
        with ui.element("div").style(
            "display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; min-width: 0;"
        ):
            ui.label(_SCOPE_LABELS.get(scope, scope.replace("_", " "))).style(
                "min-width: 9rem; color: var(--text-1); font-size: 0.74rem; "
                "text-transform: uppercase; letter-spacing: 0.08em;"
            )
            for item in scope_items:
                _context_chip(
                    node.invocation,
                    node.lineage,
                    item,
                    on_open_context=on_open_context,
                )


def _repl_panel(node: LiveInvocationNode, *, on_open_repl_output) -> None:
    with ui.element("div").style(
        "flex: 0 0 6.4rem; width: 6.4rem; min-width: 6.4rem; "
        "display: flex; align-items: flex-start; justify-content: flex-end;"
    ):
        with ui.element("div").style(
            "display: flex; flex-direction: column; gap: 0.45rem; width: 100%; "
            "padding: 0.55rem 0.5rem; border-radius: 14px; "
            "border: 1px solid rgba(255,209,102,0.22); background: rgba(255,209,102,0.08);"
        ):
            ui.label("REPL").style(
                "color: var(--accent-warning); font-size: 0.72rem; "
                "font-weight: 700; letter-spacing: 0.08em;"
            )
            _action_chip(
                "code",
                lambda: on_open_repl_output(
                    node.invocation.invocation_id,
                    node.parent_code_text
                    if node.parent_code_text.strip()
                    else "No code captured yet",
                    f"code:{node.invocation.agent_name}",
                ),
            )
            _action_chip(
                "stdout",
                lambda: on_open_repl_output(
                    node.invocation.invocation_id,
                    node.parent_stdout_text,
                    f"stdout:{node.invocation.agent_name}",
                ),
            )
            _action_chip(
                "stderr",
                lambda: on_open_repl_output(
                    node.invocation.invocation_id,
                    node.parent_stderr_text,
                    f"stderr:{node.invocation.agent_name}",
                ),
            )


def _context_chip(
    invocation: LiveInvocation,
    lineage: list[LiveInvocation],
    item: LiveContextBannerItem,
    *,
    on_open_context,
) -> None:
    if item.token_count == 0 and not item.display_value_preview:
        token_text = "n/a"
    elif item.token_count_is_exact:
        token_text = f"{item.token_count} tok"
    else:
        token_text = f"~{item.token_count} tok"
    bg = "rgba(126,240,160,0.16)" if item.present else "rgba(159,176,209,0.08)"
    border = "var(--accent-active)" if item.present else "var(--border-1)"
    text = "var(--accent-active)" if item.present else "var(--text-1)"
    chip = (
        ui.element("div")
        .style(
            "display: inline-flex; align-items: center; min-width: 0; cursor: pointer; "
            f"background: {bg}; border: 1px solid {border}; border-radius: 999px; "
            "padding: 0.3rem 0.62rem;"
        )
        .on(
            "click.stop",
            lambda _e: on_open_context(invocation, item, lineage),
        )
    )
    with chip:
        ui.label(f"{item.label} ({token_text})").style(
            f"color: {text}; font-size: 0.78rem;"
        ).tooltip(item.display_value_preview or item.raw_key)


def _action_chip(label: str, on_click) -> None:
    with (
        ui.element("div")
        .style(
            "display: inline-flex; align-items: center; border-radius: 999px; cursor: pointer; "
            "padding: 0.28rem 0.62rem; border: 1px solid var(--accent-warning); "
            "background: rgba(255,209,102,0.12);"
        )
        .on("click.stop", lambda _e: on_click())
    ):
        ui.label(label).style("color: var(--accent-warning); font-size: 0.78rem; font-weight: 700;")
