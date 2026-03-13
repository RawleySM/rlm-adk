"""NiceGUI page for the live recursive dashboard."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from rlm_adk.dashboard.components.live_context_viewer import render_live_context_viewer
from rlm_adk.dashboard.components.live_invocation_tree import render_live_invocation_tree
from rlm_adk.dashboard.live_controller import LiveDashboardController, LiveDashboardUI
from rlm_adk.dashboard.live_loader import LiveDashboardLoader

_LIVE_PAGE_CSS = """
<style>
  .live-dashboard {
    --bg-0: #0b1020;
    --bg-1: #131a2b;
    --bg-2: #1a2338;
    --border-1: #2e3a57;
    --text-0: #e6edf7;
    --text-1: #9fb0d1;
    --accent-root: #57c7ff;
    --accent-child: #ff6b9f;
    --accent-active: #7ef0a0;
    --accent-warning: #ffd166;
  }
  .live-dashboard .q-toggle__label,
  .live-dashboard .q-field__label,
  .live-dashboard .q-field__native,
  .live-dashboard .q-placeholder {
    color: var(--text-0) !important;
  }
  .live-context-viewer {
    position: fixed;
    top: 6.25rem;
    left: 2rem;
    z-index: 120;
    width: min(56rem, calc(100vw - 4rem));
    height: min(68vh, 46rem);
    max-width: calc(100vw - 4rem);
    pointer-events: none;
  }
  .live-context-viewer__shell {
    width: 100%;
    height: 100%;
    pointer-events: auto;
  }
  .live-context-viewer__header {
    cursor: move;
    user-select: none;
  }
</style>
<script>
(() => {
  if (window.__rlmLiveViewerDragInstalled) return;
  window.__rlmLiveViewerDragInstalled = true;

  const initDrag = () => {
    document.querySelectorAll('.live-context-viewer').forEach(panel => {
      if (panel.dataset.dragInitialized === '1') return;
      panel.dataset.dragInitialized = '1';
      const header = panel.querySelector('.live-context-viewer__header');
      if (!header) return;

      header.addEventListener('pointerdown', event => {
        if (event.button !== 0) return;
        if (event.target.closest('button, .q-btn, input, textarea, a')) return;

        const rect = panel.getBoundingClientRect();
        const offsetX = event.clientX - rect.left;
        const offsetY = event.clientY - rect.top;

        const onMove = moveEvent => {
          const maxLeft = Math.max(0, window.innerWidth - rect.width);
          const maxTop = Math.max(0, window.innerHeight - 48);
          const nextLeft = Math.min(maxLeft, Math.max(0, moveEvent.clientX - offsetX));
          const nextTop = Math.min(maxTop, Math.max(0, moveEvent.clientY - offsetY));
          panel.style.left = `${nextLeft}px`;
          panel.style.top = `${nextTop}px`;
        };

        const onUp = () => {
          window.removeEventListener('pointermove', onMove);
          window.removeEventListener('pointerup', onUp);
        };

        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
        event.preventDefault();
      });
    });
  };

  new MutationObserver(initDrag).observe(document.documentElement, {
    childList: true,
    subtree: true,
  });
  window.addEventListener('load', initDrag);
  setTimeout(initDrag, 0);
})();
</script>
"""


@ui.page("/live")
async def live_dashboard_page() -> None:
    loader = LiveDashboardLoader()
    controller = LiveDashboardController(loader)
    live_ui = LiveDashboardUI(controller)

    await controller.initialize()

    ui.dark_mode(True)
    ui.page_title("RLM Live Recursive Dashboard")
    ui.add_head_html(_LIVE_PAGE_CSS)

    @ui.refreshable
    def text_panel_body() -> None:
        if not controller.state.context_viewer_open:
            return
        with ui.element("div").classes("live-dashboard live-context-viewer"):
            with ui.element("div").classes("live-context-viewer__shell"):
                render_live_context_viewer(
                    controller.state.context_selection,
                    on_close=lambda: _close_context_viewer(controller, text_panel_body),
                )

    @ui.refreshable
    def header_section() -> None:
        run_state = controller.state.run_state
        with ui.element("div").classes("live-dashboard").style(
            "position: sticky; top: 0; z-index: 50; width: 100%; "
            "padding: 0.9rem 1rem; border-bottom: 1px solid var(--border-1); "
            "background: rgba(11,16,32,0.96); backdrop-filter: blur(14px);"
        ):
            with ui.element("div").style(
                "display: flex; justify-content: space-between; align-items: flex-start; "
                "gap: 1rem; min-width: 0;"
            ):
                with ui.element("div").style(
                    "display: flex; flex-direction: column; gap: 0.45rem; min-width: 0;"
                ):
                    ui.label("RLM Live Recursive Dashboard").style(
                        "color: var(--text-0); font-size: 1.35rem; font-weight: 800;"
                    )
                    ui.label("Context-only live view").style(
                        "color: var(--text-1); font-size: 0.82rem;"
                    )

                with ui.element("div").style(
                    "display: flex; flex-direction: column; align-items: flex-end; "
                    "gap: 0.6rem; min-width: 18rem;"
                ):
                    with ui.element("div").style(
                        "display: flex; flex-wrap: wrap; justify-content: flex-end; "
                        "align-items: center; gap: 0.65rem;"
                    ):
                        _session_selector(controller, live_ui)
                        _status_badge(run_state.run_status if run_state else "idle")
                        _toggle(
                            "Auto-follow",
                            controller.state.auto_follow,
                            lambda value: _handle_auto_follow(value, controller, live_ui),
                        )
                        _toggle(
                            "Pause updates",
                            controller.state.pause_live_updates,
                            lambda value: _handle_pause(value, controller, live_ui),
                        )
                    with ui.element("div").style(
                        "display: flex; flex-wrap: wrap; justify-content: flex-end; "
                        "align-items: center; gap: 0.45rem;"
                    ):
                        total_calls = run_state.total_live_model_calls if run_state else 0
                        active_depth = run_state.active_depth if run_state else 0
                        active_children = run_state.active_children if run_state else 0
                        _metric_chip("model calls", str(total_calls))
                        _metric_chip("active depth", str(active_depth))
                        _metric_chip("active children", str(active_children))

    @ui.refreshable
    def invocation_section() -> None:
        with ui.element("div").classes("live-dashboard"):
            render_live_invocation_tree(
                controller.state.run_state.invocation_nodes if controller.state.run_state else [],
                on_open_context=lambda invocation, item, lineage: _open_invocation_context_viewer(
                    controller,
                    text_panel_body,
                    invocation,
                    item,
                    lineage,
                ),
                on_select_iteration=lambda pane_id, invocation_id: _select_iteration(
                    controller,
                    live_ui,
                    pane_id,
                    invocation_id,
                ),
                on_open_repl_output=lambda invocation_id, text, label: _open_repl_output_viewer(
                    controller,
                    text_panel_body,
                    invocation_id,
                    text,
                    label,
                ),
            )

    live_ui.register(header_section)
    live_ui.register(invocation_section)
    live_ui.register(text_panel_body)

    with ui.element("div").classes("live-dashboard").style(
        "min-height: 100vh; width: 100%; background: radial-gradient(circle at top left, "
        "rgba(87,199,255,0.12), transparent 24%), "
        "radial-gradient(circle at top right, rgba(255,107,159,0.12), transparent 24%), "
        "linear-gradient(180deg, var(--bg-0), #060912);"
    ):
        header_section()
        invocation_section()
        text_panel_body()

    async def _poll() -> None:
        changed = await controller.poll()
        if changed:
            live_ui.refresh_all()

    ui.timer(0.25, _poll)


def _session_selector(controller: LiveDashboardController, live_ui: LiveDashboardUI) -> None:
    async def on_session_change(e: Any) -> None:
        if e.value and e.value != controller.state.selected_session_id:
            await controller.select_session(e.value)
            live_ui.refresh_all()

    sessions = controller.state.available_sessions
    if not sessions:
        ui.label("No sessions found").style("color: var(--text-1);")
        return
    ui.select(
        options=sessions,
        value=controller.state.selected_session_id,
        label="Session",
        on_change=on_session_change,
        with_input=True,
    ).style("min-width: 16rem;")


def _toggle(label: str, value: bool, on_change) -> None:
    ui.switch(label, value=value, on_change=lambda e: on_change(bool(e.value))).style(
        "color: var(--text-0);"
    )


def _status_badge(status: str) -> None:
    color = {
        "running": "var(--accent-active)",
        "completed": "var(--accent-root)",
        "error": "var(--accent-child)",
        "idle": "var(--text-1)",
    }.get(status, "var(--text-1)")
    with ui.element("div").style(
        f"display: inline-flex; align-items: center; border-radius: 999px; "
        f"border: 1px solid {color}; background: color-mix(in srgb, {color} 16%, transparent); "
        "padding: 0.32rem 0.7rem;"
    ):
        ui.label(status).style(
            f"color: {color}; font-size: 0.78rem; text-transform: uppercase;"
        )


def _metric_chip(label: str, value: str) -> None:
    with ui.element("div").style(
        "display: inline-flex; align-items: center; gap: 0.35rem; "
        "padding: 0.28rem 0.56rem; border-radius: 999px; "
        "border: 1px solid var(--border-1); background: rgba(230,237,247,0.05);"
    ):
        ui.label(label).style("color: var(--text-1); font-size: 0.72rem;")
        ui.label(value).style("color: var(--text-0); font-size: 0.74rem;")


def _handle_auto_follow(
    value: bool,
    controller: LiveDashboardController,
    live_ui: LiveDashboardUI,
) -> None:
    controller.set_auto_follow(value)
    live_ui.refresh_all()


def _handle_pause(
    value: bool,
    controller: LiveDashboardController,
    live_ui: LiveDashboardUI,
) -> None:
    controller.set_pause_live_updates(value)
    live_ui.refresh_all()


def _open_invocation_context_viewer(
    controller: LiveDashboardController,
    refresh_viewer,
    invocation,
    item,
    lineage,
) -> None:
    controller.open_invocation_context_viewer(invocation, item, lineage)
    refresh_viewer.refresh()


def _open_repl_output_viewer(
    controller: LiveDashboardController,
    refresh_viewer,
    invocation_id: str,
    text: str,
    label: str,
) -> None:
    controller.open_repl_output_viewer(
        invocation_id=invocation_id,
        text=text,
        label=label,
    )
    refresh_viewer.refresh()


def _select_iteration(
    controller: LiveDashboardController,
    live_ui: LiveDashboardUI,
    pane_id: str,
    invocation_id: str,
) -> None:
    controller.select_iteration(pane_id, invocation_id)
    live_ui.refresh_all()


def _close_context_viewer(
    controller: LiveDashboardController,
    refresh_viewer,
) -> None:
    controller.close_context_viewer()
    refresh_viewer.refresh()
