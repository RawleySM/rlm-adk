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
    "observability",
    "completion_plane",
    "request_chunk",
]

_SCOPE_LABELS = {
    "dynamic_instruction_param": "Dynamic Context",
    "state_key": "State Keys",
    "skill_plane": "Skill System",
    "observability": "Observability",
    "completion_plane": "Completion Plane",
    "request_chunk": "Request Chunks",
}


def _display_agent_name(invocation: LiveInvocation) -> str:
    return invocation.agent_name


def render_live_invocation_tree(
    nodes: list[LiveInvocationNode],
    *,
    on_open_context,
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
                on_open_repl_output=on_open_repl_output,
            )


def _render_node(
    node: LiveInvocationNode,
    *,
    on_open_context,
    on_open_repl_output,
) -> None:
    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.7rem; min-width: 0; "
        "padding: 0.8rem 0.95rem; border-radius: 16px; "
        "border: 1px solid var(--border-1); "
        "background: linear-gradient(180deg, rgba(19,26,43,0.96), rgba(11,16,32,0.96));"
    ):
        _header(node)
        _loop_detection_warning(node)
        _child_summary_bar(node, on_open_repl_output=on_open_repl_output)
        _model_call_detail(node)
        _scope_groups(node, on_open_context=on_open_context)

    for child in node.child_nodes:
        _render_child_row(
            child,
            on_open_context=on_open_context,
            on_open_repl_output=on_open_repl_output,
        )


def _render_child_row(
    node: LiveInvocationNode,
    *,
    on_open_context,
    on_open_repl_output,
) -> None:
    with ui.element("div").style("display: flex; align-items: stretch; gap: 1rem; min-width: 0;"):
        _repl_panel(node, on_open_repl_output=on_open_repl_output)
        with ui.element("div").style("flex: 1; min-width: 0;"):
            _render_node(
                node,
                on_open_context=on_open_context,
                on_open_repl_output=on_open_repl_output,
            )


def _header(node: LiveInvocationNode) -> None:
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
            # Status chip
            status = node.invocation.status
            status_color = {
                "running": "var(--accent-active)",
                "completed": "var(--accent-root)",
                "error": "var(--accent-child)",
                "cancelled": "var(--accent-warning)",
                "idle": "var(--text-1)",
            }.get(status, "var(--text-1)")
            with ui.element("div").style(
                f"display: inline-flex; align-items: center; border-radius: 999px; "
                f"padding: 0.22rem 0.58rem; border: 1px solid {status_color}; "
                f"background: color-mix(in srgb, {status_color} 12%, transparent);"
            ):
                ui.label(status).style(
                    f"color: {status_color}; font-size: 0.72rem; text-transform: uppercase;"
                )
            # Depth / fanout chip
            fanout = (
                "root" if node.invocation.fanout_idx is None else f"f{node.invocation.fanout_idx}"
            )
            ui.label(f"d{node.invocation.depth}/{fanout}").style(
                "color: var(--text-1); font-size: 0.72rem;"
            )


def _loop_detection_warning(node: LiveInvocationNode) -> None:
    """Detect repeated code submissions across iterations and show a warning."""
    if len(node.available_invocations) < 2:
        return
    hashes: list[tuple[int, str]] = []
    for inv in node.available_invocations:
        for si in inv.state_items:
            if si.base_key == "repl_submitted_code_hash" and si.depth == inv.depth:
                hashes.append((inv.iteration, str(si.value)))
                break
    if len(hashes) < 2:
        return
    # Find consecutive runs of identical hashes
    run_start = 0
    loops: list[tuple[int, int]] = []
    for i in range(1, len(hashes)):
        if hashes[i][1] != hashes[run_start][1]:
            if i - run_start >= 2:
                loops.append((hashes[run_start][0], hashes[i - 1][0]))
            run_start = i
    if len(hashes) - run_start >= 2:
        loops.append((hashes[run_start][0], hashes[-1][0]))
    for loop_start, loop_end in loops:
        with ui.element("div").style(
            "display: inline-flex; align-items: center; gap: 0.4rem; "
            "padding: 0.3rem 0.7rem; border-radius: 999px; "
            "border: 1px solid var(--accent-warning); "
            "background: rgba(255,209,102,0.15);"
        ):
            ui.label(f"LOOP: iterations {loop_start}-{loop_end} submitted identical code").style(
                "color: var(--accent-warning); font-size: 0.78rem; font-weight: 700;"
            )


def _child_summary_bar(node: LiveInvocationNode, *, on_open_repl_output) -> None:
    """Render compact child summary cards when children exist."""
    summaries = node.invocation.child_summaries
    if not summaries:
        return
    with ui.element("div").style(
        "display: flex; flex-wrap: wrap; gap: 0.5rem; min-width: 0; "
        "padding: 0.5rem 0; border-top: 1px solid var(--border-1);"
    ):
        ui.label("CHILDREN").style(
            "min-width: 9rem; color: var(--accent-child); font-size: 0.72rem; "
            "font-weight: 700; letter-spacing: 0.08em;"
        )
        for child in summaries:
            error_border = "var(--accent-child)" if child.error else "var(--border-1)"
            error_bg = "rgba(255,107,159,0.10)" if child.error else "rgba(159,176,209,0.06)"
            with (
                ui.element("div")
                .style(
                    f"display: flex; flex-direction: column; gap: 0.2rem; "
                    f"padding: 0.4rem 0.65rem; border-radius: 12px; min-width: 14rem; max-width: 28rem; "
                    f"border: 1px solid {error_border}; background: {error_bg}; cursor: pointer;"
                )
                .on(
                    "click.stop",
                    lambda _e, c=child: on_open_repl_output(
                        f"child:d{c.depth}:f{c.fanout_idx}",
                        f"Prompt:\n{c.prompt}\n\nResult:\n{c.result_text}\n\n"
                        f"Thought:\n{c.thought_text}\n\nVisible Output:\n{c.visible_output_text}",
                        f"child d{c.depth}/f{c.fanout_idx}",
                    ),
                )
            ):
                # Header row
                with ui.element("div").style(
                    "display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;"
                ):
                    ui.label(f"d{child.depth}/f{child.fanout_idx}").style(
                        "color: var(--accent-child); font-size: 0.76rem; font-weight: 700;"
                    )
                    status_text = "ERROR" if child.error else "OK"
                    status_color = "var(--accent-child)" if child.error else "var(--accent-active)"
                    ui.label(status_text).style(
                        f"color: {status_color}; font-size: 0.68rem; font-weight: 700;"
                    )
                    if child.elapsed_ms:
                        ui.label(f"{child.elapsed_ms:.0f}ms").style(
                            "color: var(--text-1); font-size: 0.68rem;"
                        )
                    if child.finish_reason:
                        ui.label(child.finish_reason).style(
                            "color: var(--text-1); font-size: 0.68rem;"
                        )
                # Token row
                with ui.element("div").style("display: flex; align-items: center; gap: 0.35rem;"):
                    ui.label(f"{child.input_tokens}in").style(
                        "color: var(--text-1); font-size: 0.68rem;"
                    )
                    ui.label(f"{child.output_tokens}out").style(
                        "color: var(--text-1); font-size: 0.68rem;"
                    )
                    if child.thought_tokens:
                        ui.label(f"{child.thought_tokens}think").style(
                            "color: var(--text-1); font-size: 0.68rem;"
                        )
                # Prompt preview
                prompt_preview = child.prompt_preview[:100] if child.prompt_preview else ""
                if prompt_preview:
                    ui.label(prompt_preview).style(
                        "color: var(--text-0); font-size: 0.72rem; "
                        "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
                    )
                # Error message
                if child.error_message:
                    ui.label(child.error_message[:120]).style(
                        "color: var(--accent-child); font-size: 0.72rem;"
                    )


def _model_call_detail(node: LiveInvocationNode) -> None:
    """Render compact model call summary when model events exist."""
    events = node.invocation.model_events
    if not events:
        return
    with ui.element("div").style(
        "display: flex; flex-wrap: wrap; gap: 0.4rem; min-width: 0; align-items: center;"
    ):
        ui.label("MODEL CALLS").style(
            "min-width: 9rem; color: var(--accent-root); font-size: 0.72rem; "
            "font-weight: 700; letter-spacing: 0.08em;"
        )
        for me in events:
            finish = me.finish_reason or "?"
            dur = f"{me.duration_ms:.0f}ms" if me.duration_ms else "?"
            error = me.status == "error"
            border = "var(--accent-child)" if error else "var(--border-1)"
            bg = "rgba(255,107,159,0.08)" if error else "rgba(87,199,255,0.06)"
            with ui.element("div").style(
                f"display: inline-flex; align-items: center; gap: 0.3rem; "
                f"padding: 0.22rem 0.52rem; border-radius: 999px; "
                f"border: 1px solid {border}; background: {bg};"
            ):
                ui.label(f"i{me.iteration}").style(
                    "color: var(--text-0); font-size: 0.68rem; font-weight: 700;"
                )
                ui.label(f"{me.input_tokens}in/{me.output_tokens}out").style(
                    "color: var(--text-1); font-size: 0.68rem;"
                )
                finish_color = (
                    "var(--accent-child)" if finish not in ("STOP", "?") else "var(--text-1)"
                )
                ui.label(finish).style(f"color: {finish_color}; font-size: 0.68rem;")
                ui.label(dur).style("color: var(--text-1); font-size: 0.68rem;")


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
            scope_color = {
                "observability": "var(--accent-root)",
                "completion_plane": "var(--accent-child)",
            }.get(scope, "var(--text-1)")
            ui.label(_SCOPE_LABELS.get(scope, scope.replace("_", " "))).style(
                f"min-width: 9rem; color: {scope_color}; font-size: 0.74rem; "
                "text-transform: uppercase; letter-spacing: 0.08em;"
            )
            for item in scope_items:
                _context_chip(
                    node.invocation,
                    node.lineage,
                    item,
                    on_open_context=on_open_context,
                    scope=scope,
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
    scope: str = "",
) -> None:
    # For obs/completion scopes, show value preview instead of token count
    if scope in ("observability", "completion_plane", "skill_plane"):
        chip_label = (
            f"{item.label}: {item.display_value_preview[:60]}"
            if item.display_value_preview
            else item.label
        )
        bg = {
            "observability": "rgba(87,199,255,0.10)",
            "completion_plane": "rgba(255,107,159,0.10)",
            "skill_plane": "rgba(126,240,160,0.10)",
        }.get(scope, "rgba(159,176,209,0.08)")
        border = {
            "observability": "rgba(87,199,255,0.35)",
            "completion_plane": "rgba(255,107,159,0.35)",
            "skill_plane": "rgba(126,240,160,0.35)",
        }.get(scope, "var(--border-1)")
        text_color = {
            "observability": "var(--accent-root)",
            "completion_plane": "var(--accent-child)",
            "skill_plane": "var(--accent-active)",
        }.get(scope, "var(--text-1)")
    else:
        if item.token_count == 0 and not item.display_value_preview:
            token_text = "n/a"
        elif item.token_count_is_exact:
            token_text = f"{item.token_count} tok"
        else:
            token_text = f"~{item.token_count} tok"
        chip_label = f"{item.label} ({token_text})"
        bg = "rgba(126,240,160,0.16)" if item.present else "rgba(159,176,209,0.08)"
        border = "var(--accent-active)" if item.present else "var(--border-1)"
        text_color = "var(--accent-active)" if item.present else "var(--text-1)"

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
        ui.label(chip_label).style(f"color: {text_color}; font-size: 0.78rem;").tooltip(
            item.display_value_preview or item.raw_key
        )


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
