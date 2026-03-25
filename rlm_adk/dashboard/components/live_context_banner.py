"""Pinned context banner for the live dashboard."""

from __future__ import annotations

from nicegui import ui

from rlm_adk.dashboard.live_models import LiveContextBannerItem

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


def render_live_context_banner(
    items: list[LiveContextBannerItem],
    *,
    invocation_id: str | None = None,
    depth: int | None = None,
    fanout_idx: int | None = None,
    iteration: int | None = None,
    on_open_text=None,
) -> None:
    """Render grouped banner chips for the active pane."""
    grouped: dict[str, list[LiveContextBannerItem]] = {}
    for item in items:
        grouped.setdefault(item.scope, []).append(item)

    with ui.element("div").style(
        "position: sticky; top: 4.5rem; z-index: 40; width: 100%; "
        "padding: 0.75rem 1rem 0.9rem 1rem; border-bottom: 1px solid var(--border-1); "
        "background: rgba(11,16,32,0.92); backdrop-filter: blur(14px);"
    ):
        ui.label(f"Invocation_id : {invocation_id or '-'}").style(
            "color: var(--text-0); font-size: 1rem; font-weight: 700; margin-bottom: 0.25rem;"
        )
        fanout = "root" if fanout_idx is None else str(fanout_idx)
        ui.label(
            f"depth {depth if depth is not None else '-'}  |  "
            f"fan-out {fanout}  |  "
            f"iteration {iteration if iteration is not None else '-'}"
        ).style("color: var(--text-1); font-size: 0.84rem; margin-bottom: 0.8rem;")
        if not items:
            ui.label("No active pane context available.").style("color: var(--text-1);")
            return

        with ui.element("div").style(
            "display: flex; flex-direction: column; width: 100%; gap: 0.55rem; min-width: 0;"
        ):
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
                        _chip(item, on_open_text=on_open_text)


def _chip(item: LiveContextBannerItem, *, on_open_text=None) -> None:
    token_text = (
        f"{item.token_count} tok" if item.token_count_is_exact else f"~{item.token_count} tok"
    )
    bg = "rgba(126,240,160,0.16)" if item.present else "rgba(159,176,209,0.08)"
    border = "var(--accent-active)" if item.present else "var(--border-1)"
    text = "var(--accent-active)" if item.present else "var(--text-1)"
    clickable = on_open_text is not None
    chip = ui.element("div").style(
        "display: inline-flex; align-items: center; min-width: 0; "
        f"background: {bg}; border: 1px solid {border}; border-radius: 999px; "
        f"padding: 0.3rem 0.62rem; {'cursor: pointer;' if clickable else ''}"
    )
    if clickable:
        chip.on("click.stop", lambda _e, current=item: on_open_text(current))
    with chip:
        ui.label(f"{item.label} ({token_text})").style(
            f"color: {text}; font-size: 0.78rem;"
        ).tooltip(item.display_value_preview or item.raw_key)
