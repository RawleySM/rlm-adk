"""Split-panel recursive notebook for the event-driven dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from rlm_adk.dashboard.event_reader import InvocationTree, StepEvent


def render_notebook_panel(
    tree: InvocationTree,
    inv_id: str,
    *,
    is_child: bool = False,
) -> None:
    """Render invocation steps as a notebook-style panel.

    Args:
        tree: The full invocation tree from build_tree()
        inv_id: The invocation_id to render
        is_child: If True, render horizontally (child panel)
    """
    from rlm_adk.dashboard.event_reader import children_of_tool_event

    steps = tree.steps.get(inv_id, [])
    if not steps:
        ui.label("No events for this invocation").style("color: var(--text-1); font-style: italic;")
        return

    if is_child:
        # Child invocations: vertical scroll
        with ui.element("div").style(
            "display: flex; flex-direction: column; gap: 0.5rem; "
            "overflow-y: auto; min-width: 0; width: 100%;"
        ):
            for idx, (model_event, tool_event) in enumerate(steps, 1):
                _render_model_banner(model_event, iteration=idx)
                if tool_event is not None:
                    _render_tool_cell(tool_event)
        return

    # Root invocation: vertical steps, with side-by-side child panels
    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.75rem; "
        "overflow-y: auto; min-width: 0; width: 100%;"
    ):
        for idx, (model_event, tool_event) in enumerate(steps, 1):
            # Model banner (always full width)
            _render_model_banner(model_event, iteration=idx)

            if tool_event is not None:
                child_inv_ids = children_of_tool_event(tree, tool_event.event_id)
                if child_inv_ids:
                    # Tool has children: render side-by-side
                    with ui.element("div").style(
                        "display: flex; flex-direction: row; gap: 0.75rem; "
                        "min-width: 0; width: 100%; align-items: flex-start;"
                    ):
                        # Left: execute_code cell
                        with ui.element("div").style(
                            "flex: 1; min-width: 0; overflow-y: auto; "
                            "max-height: 50vh;"
                        ):
                            _render_tool_cell(tool_event)
                        # Right: child panel
                        with ui.element("div").style(
                            "flex: 1; min-width: 0; overflow-y: auto; "
                            "max-height: 50vh;"
                        ):
                            _render_child_panel(tree, tool_event.event_id, child_inv_ids)
                else:
                    # No children: render tool cell full width
                    _render_tool_cell(tool_event)


def _render_model_banner(event: StepEvent, *, iteration: int = 0) -> None:
    """Render the LlmRequest banner for a model event."""
    with ui.element("div").style(
        "display: flex; align-items: center; gap: 0.75rem; "
        "padding: 0.5rem 0.75rem; border-radius: 8px; "
        "background: rgba(87,199,255,0.08); "
        "border: 1px solid rgba(87,199,255,0.2);"
    ):
        ui.label(event.agent_name or "agent").style(
            "color: var(--accent-root); font-size: 0.78rem; font-weight: 700;"
        )
        iter_label = f"i{iteration}" if iteration else f"d{event.depth}"
        ui.label(iter_label).style("color: var(--text-1); font-size: 0.72rem;")
        tokens_str = f"in:{event.input_tokens} out:{event.output_tokens}"
        if event.thought_tokens:
            tokens_str += f" think:{event.thought_tokens}"
        ui.label(tokens_str).style("color: var(--text-1); font-size: 0.72rem; margin-left: auto;")
        if event.model:
            ui.label(event.model).style("color: var(--text-1); font-size: 0.68rem; opacity: 0.7;")


def _render_tool_cell(event: StepEvent) -> None:
    """Render a tool event cell based on tool_name."""
    tool_name = event.tool_name or ""

    if tool_name == "execute_code":
        _render_execute_code_cell(event)
    elif tool_name == "set_model_response":
        _render_set_model_response_cell(event)
    elif tool_name in ("list_skills", "load_skill"):
        _render_skill_tool_cell(event)
    else:
        _render_generic_tool_cell(event)


def _render_execute_code_cell(event: StepEvent) -> None:
    """Render execute_code with code + stdout panes."""
    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.35rem; "
        "padding: 0.5rem; border-radius: 8px; "
        "background: rgba(19,26,43,0.9); "
        "border: 1px solid var(--border-1);"
    ):
        # Code header
        with ui.element("div").style("display: flex; align-items: center; gap: 0.5rem;"):
            ui.label("execute_code").style(
                "color: var(--accent-active); font-size: 0.72rem; font-weight: 700;"
            )
            if event.duration_ms is not None:
                ui.label(f"{event.duration_ms:.0f}ms").style(
                    "color: var(--text-1); font-size: 0.68rem; margin-left: auto;"
                )
            if event.llm_query_detected:
                ui.label(f"llm_query x{event.llm_query_count}").style(
                    "color: var(--accent-child); font-size: 0.68rem;"
                )

        # Code block with syntax highlighting
        if event.code:
            from rlm_adk.dashboard.components.flow_code_pane import _highlight_line

            highlighted_lines = "\n".join(
                _highlight_line(line) for line in event.code.splitlines()
            )
            ui.html(
                f'<pre style="color: var(--text-0); font-size: 0.76rem; '
                f'margin: 0; white-space: pre-wrap; overflow-x: auto;">'
                f"{highlighted_lines}</pre>"
            )

        # Stdout
        if event.stdout:
            with ui.element("div").style(
                "padding: 0.35rem 0.5rem; border-radius: 6px; "
                "background: rgba(126,240,160,0.06); "
                "border-left: 3px solid var(--accent-active);"
            ):
                ui.html(
                    f'<pre style="color: var(--accent-active); font-size: 0.72rem; '
                    f'margin: 0; white-space: pre-wrap;">{_escape_html(event.stdout)}</pre>'
                )

        # Stderr
        if event.stderr:
            with ui.element("div").style(
                "padding: 0.35rem 0.5rem; border-radius: 6px; "
                "background: rgba(255,60,60,0.06); "
                "border-left: 3px solid #ff3c3c;"
            ):
                ui.html(
                    f'<pre style="color: #ff3c3c; font-size: 0.72rem; '
                    f'margin: 0; white-space: pre-wrap;">{_escape_html(event.stderr)}</pre>'
                )


def _render_set_model_response_cell(event: StepEvent) -> None:
    """Render set_model_response with the output schema."""
    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.25rem; "
        "padding: 0.5rem 0.75rem; border-radius: 8px; "
        "border: 1px solid var(--accent-child); "
        "background: rgba(255,107,159,0.06);"
    ):
        ui.label("set_model_response").style(
            "color: var(--accent-child); font-size: 0.72rem; font-weight: 700;"
        )
        if event.tool_result and isinstance(event.tool_result, dict):
            import json

            ui.html(
                f'<pre style="color: var(--text-0); font-size: 0.72rem; '
                f'margin: 0; white-space: pre-wrap;">'
                f"{_escape_html(json.dumps(event.tool_result, indent=2, default=str)[:2000])}</pre>"
            )


def _render_skill_tool_cell(event: StepEvent) -> None:
    """Render list_skills / load_skill cells."""
    color = "var(--accent-warning)"
    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.2rem; "
        "padding: 0.4rem 0.6rem; border-radius: 8px; "
        "background: rgba(255,209,102,0.06); "
        "border: 1px solid rgba(255,209,102,0.2);"
    ):
        ui.label(event.tool_name or "").style(
            f"color: {color}; font-size: 0.72rem; font-weight: 700;"
        )
        if event.tool_result:
            import json

            result_str = json.dumps(event.tool_result, default=str)[:500]
            ui.label(result_str).style(
                "color: var(--text-1); font-size: 0.7rem; word-break: break-all;"
            )


def _render_generic_tool_cell(event: StepEvent) -> None:
    """Render any other tool call."""
    with ui.element("div").style(
        "padding: 0.4rem 0.6rem; border-radius: 8px; "
        "background: rgba(255,255,255,0.03); "
        "border: 1px solid var(--border-1);"
    ):
        ui.label(event.tool_name or "unknown").style(
            "color: var(--text-1); font-size: 0.72rem; font-weight: 600;"
        )


def _render_child_panel(
    tree: InvocationTree,
    tool_event_id: str,
    child_inv_ids: list[str],
) -> None:
    """Render child invocations panel with compact fanout selector."""
    with ui.element("div").style(
        "margin-left: 1rem; padding: 0.5rem; "
        "border-left: 2px solid var(--accent-child); "
        "background: rgba(255,107,159,0.03); "
        "border-radius: 0 8px 8px 0;"
    ):
        # Compact fanout selector — sticky at top of scroll
        with ui.tabs().style(
            "background: rgb(17,22,35); min-height: 0; "
            "position: sticky; top: 0; z-index: 2;"
        ) as tabs:
            for idx in range(len(child_inv_ids)):
                ui.tab(f"f{idx}", label=f"F{idx}").style(
                    "min-height: 0; padding: 0.1rem 0.5rem; "
                    "font-size: 0.68rem; font-weight: 700;"
                )
        with ui.tab_panels(tabs, value="f0").style(
            "background: transparent; padding: 0;"
        ):
            for idx, child_id in enumerate(child_inv_ids):
                with ui.tab_panel(f"f{idx}").style("padding: 0.25rem 0 0 0;"):
                    render_notebook_panel(tree, child_id, is_child=True)


def _escape_html(text: str) -> str:
    """Escape HTML entities."""
    from html import escape

    return escape(str(text))
