"""Reasoning agent header card for the flow transcript."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from rlm_adk.dashboard.flow_models import FlowAgentCard
    from rlm_adk.dashboard.live_models import LiveContextBannerItem

_SCOPE_ORDER = [
    "dynamic_instruction_param",
    "state_key",
    "observability",
    "completion_plane",
    "request_chunk",
]

_SCOPE_LABELS = {
    "dynamic_instruction_param": "DYNAMIC CONTEXT",
    "state_key": "STATE KEYS",
    "observability": "Observability",
    "completion_plane": "Completion Plane",
    "request_chunk": "REQUEST CHUNKS",
}

_STATUS_COLORS = {
    "running": "var(--accent-active)",
    "completed": "var(--accent-root)",
    "error": "var(--accent-child)",
    "cancelled": "var(--accent-warning)",
    "idle": "var(--text-1)",
}


def render_flow_reasoning_pane(
    card: FlowAgentCard,
    *,
    on_open_context=None,
) -> None:
    """Render the reasoning agent header card."""
    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.6rem; min-width: 0; "
        "padding: 0.85rem 1rem; border-radius: 14px; "
        "border: 1px solid var(--border-1); "
        "background: linear-gradient(180deg, rgba(19,26,43,0.96), rgba(11,16,32,0.96));"
    ):
        _header_row(card)
        _context_rows(card, on_open_context=on_open_context)


def _header_row(card: FlowAgentCard) -> None:
    with ui.element("div").style(
        "display: flex; flex-wrap: wrap; align-items: center; "
        "justify-content: space-between; gap: 0.65rem; min-width: 0;"
    ):
        with ui.element("div").style(
            "display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;"
        ):
            # Agent name
            ui.label(card.agent_name).style(
                "color: var(--text-0); font-size: 1rem; font-weight: 700;"
            )
            # Depth / fanout badge
            fanout = "root" if card.fanout_idx is None else f"f{card.fanout_idx}"
            ui.label(f"(d{card.depth})").style("color: var(--text-1); font-size: 0.78rem;")
            # Status chip
            status_color = _STATUS_COLORS.get(card.status, "var(--text-1)")
            with ui.element("div").style(
                f"display: inline-flex; align-items: center; border-radius: 999px; "
                f"padding: 0.2rem 0.52rem; border: 1px solid {status_color}; "
                f"background: color-mix(in srgb, {status_color} 12%, transparent);"
            ):
                ui.label(card.status).style(
                    f"color: {status_color}; font-size: 0.72rem; text-transform: uppercase;"
                )
        # Token summary + depth/fanout
        with ui.element("div").style("display: flex; align-items: center; gap: 0.5rem;"):
            ui.label(f"{card.total_context_tokens} tok / d{card.depth}:{fanout}").style(
                "color: var(--accent-active); font-size: 0.78rem; font-weight: 700;"
            )


def _context_rows(card: FlowAgentCard, *, on_open_context) -> None:
    """Render context items grouped by scope."""
    grouped: dict[str, list] = {}
    for item in card.context_items:
        grouped.setdefault(item.scope, []).append(item)

    for scope in _SCOPE_ORDER + [k for k in grouped if k not in _SCOPE_ORDER]:
        items = grouped.get(scope)
        if not items:
            continue
        with ui.element("div").style(
            "display: flex; flex-wrap: wrap; align-items: center; gap: 0.45rem; min-width: 0;"
        ):
            scope_color = {
                "observability": "var(--accent-root)",
                "completion_plane": "var(--accent-child)",
            }.get(scope, "var(--text-1)")
            ui.label(_SCOPE_LABELS.get(scope, scope.upper())).style(
                f"min-width: 9rem; color: {scope_color}; font-size: 0.72rem; "
                "font-weight: 700; letter-spacing: 0.08em;"
            )
            for item in items:
                _context_chip(
                    item,
                    scope=scope,
                    pane_id=card.pane_id,
                    invocation_id=card.invocation_id,
                    on_open_context=on_open_context,
                )


def _context_chip(
    item: LiveContextBannerItem,
    *,
    scope: str,
    pane_id: str,
    invocation_id: str = "",
    on_open_context,
) -> None:
    if scope in ("observability", "completion_plane"):
        chip_label = (
            f"{item.label}: {item.display_value_preview[:60]}"
            if item.display_value_preview
            else item.label
        )
        bg = {
            "observability": "rgba(87,199,255,0.10)",
            "completion_plane": "rgba(255,107,159,0.10)",
        }.get(scope, "rgba(159,176,209,0.08)")
        border = {
            "observability": "rgba(87,199,255,0.35)",
            "completion_plane": "rgba(255,107,159,0.35)",
        }.get(scope, "var(--border-1)")
        text_color = {
            "observability": "var(--accent-root)",
            "completion_plane": "var(--accent-child)",
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

    el = ui.element("div").style(
        "display: inline-flex; align-items: center; min-width: 0; cursor: pointer; "
        f"background: {bg}; border: 1px solid {border}; border-radius: 999px; "
        "padding: 0.26rem 0.56rem;"
    )
    if on_open_context:
        el.on(
            "click.stop",
            lambda _e, i=item, pid=pane_id, iid=invocation_id: on_open_context(pid, i, iid),
        )
    with el:
        ui.label(chip_label).style(f"color: {text_color}; font-size: 0.76rem;").tooltip(
            item.display_value_preview or item.raw_key
        )
