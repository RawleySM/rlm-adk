"""NiceGUI page for the live recursive dashboard."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from rlm_adk.dashboard.components.live_context_viewer import render_live_context_viewer
from rlm_adk.dashboard.components.live_invocation_tree import render_live_invocation_tree
from rlm_adk.dashboard.live_controller import LiveDashboardController, LiveDashboardUI
from rlm_adk.dashboard.live_loader import LiveDashboardLoader
from rlm_adk.skills import selected_skill_summaries

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
        session_summary = controller.session_summary()
        with (
            ui.element("div")
            .classes("live-dashboard")
            .style(
                "position: sticky; top: 0; z-index: 50; width: 100%; "
                "padding: 0.9rem 1rem; border-bottom: 1px solid var(--border-1); "
                "background: rgba(11,16,32,0.96); backdrop-filter: blur(14px);"
            )
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
                    ui.label("Live view plus replay launch controls").style(
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
                        _toggle(
                            "Step mode",
                            controller.state.step_mode_enabled,
                            lambda value: _handle_step_mode(value, controller, live_ui),
                        )
                        _step_mode_controls(controller, live_ui)
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
            with ui.element("div").style(
                "margin-top: 0.85rem; display: flex; flex-direction: column; "
                "gap: 0.55rem; min-width: 0; padding: 0.75rem 0.85rem; "
                "border-radius: 16px; border: 1px solid var(--border-1); "
                "background: rgba(26,35,56,0.52);"
            ):
                _launch_panel(controller, live_ui)
                _session_meta_row(
                    "User Query",
                    [
                        (
                            _truncate_chip_text(
                                session_summary.user_query, fallback="No query captured"
                            ),
                            session_summary.user_query or "No query captured.",
                            "user-query",
                        )
                    ],
                    controller=controller,
                    refresh_viewer=text_panel_body,
                )
                _session_meta_row(
                    "Skills in Prompt",
                    [
                        (name, description, f"skill:{name}")
                        for name, description in session_summary.registered_skills
                    ],
                    controller=controller,
                    refresh_viewer=text_panel_body,
                )
                _session_meta_row(
                    "Registered Plugins",
                    [
                        (name, description or name, f"plugin:{name}")
                        for name, description in session_summary.registered_plugins
                    ],
                    controller=controller,
                    refresh_viewer=text_panel_body,
                )

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

    with (
        ui.element("div")
        .classes("live-dashboard")
        .style(
            "min-height: 100vh; width: 100%; background: radial-gradient(circle at top left, "
            "rgba(87,199,255,0.12), transparent 24%), "
            "radial-gradient(circle at top right, rgba(255,107,159,0.12), transparent 24%), "
            "linear-gradient(180deg, var(--bg-0), #060912);"
        )
    ):
        header_section()
        invocation_section()
        text_panel_body()

    async def _poll() -> None:
        changed = await controller.poll()
        cancel_pending = controller.state.launch_cancelled and not controller.state.launch_in_progress
        if changed or controller.state.launch_in_progress or controller.state.launch_error or cancel_pending:
            live_ui.refresh_all()
            if cancel_pending:
                controller.state.launch_cancelled = False

    ui.timer(1.0, _poll)


def _session_selector(controller: LiveDashboardController, live_ui: LiveDashboardUI) -> None:
    async def on_session_change(e: Any) -> None:
        if e.value and e.value != controller.state.selected_session_id:
            await controller.select_session(e.value)
            live_ui.refresh_all()

    sessions = controller.state.available_sessions
    if not sessions:
        ui.label("No sessions found").style("color: var(--text-1);")
        return
    session_options = {
        session_id: controller.state.available_session_labels.get(session_id, session_id)
        for session_id in sessions
    }
    ui.select(
        options=session_options,
        value=controller.state.selected_session_id,
        label="Session",
        on_change=on_session_change,
        with_input=True,
    ).style("min-width: 28rem;")


def _launch_panel(controller: LiveDashboardController, live_ui: LiveDashboardUI) -> None:
    skill_options = [name for name, _ in selected_skill_summaries(None)]
    replay_options = controller.state.available_replay_fixtures
    pf_options = controller.state.available_provider_fake_fixtures

    if controller.state.selected_provider_fake_fixture:
        header_label = "Launch Fixture"
        launch_label = "Launch Fixture"
    elif controller.state.replay_path:
        header_label = "Launch Replay"
        launch_label = "Launch Replay"
    else:
        header_label = "Launch"
        launch_label = "Launch"

    async def on_launch() -> None:
        await controller.launch_replay()
        live_ui.refresh_all()

    async def on_cancel() -> None:
        await controller.cancel_launch()
        live_ui.refresh_all()

    with ui.element("div").style(
        "display: flex; flex-direction: column; gap: 0.7rem; min-width: 0; "
        "padding-bottom: 0.75rem; margin-bottom: 0.2rem; "
        "border-bottom: 1px solid var(--border-1);"
    ):
        ui.label(header_label).style(
            "color: var(--text-0); font-size: 0.86rem; font-weight: 700; "
            "text-transform: uppercase; letter-spacing: 0.06em;"
        )
        with ui.element("div").style(
            "display: flex; flex-wrap: wrap; align-items: flex-end; gap: 0.75rem; min-width: 0;"
        ):
            if controller.state.launch_in_progress:
                cancel_button = ui.button("Cancel", on_click=on_cancel)
                cancel_button.props("unelevated")
                cancel_button.style(
                    "height: 3.5rem; padding: 0 1.1rem; "
                    "background: var(--accent-child); color: #05111d; font-weight: 700;"
                )
            else:
                launch_button = ui.button(launch_label, on_click=on_launch)
                launch_button.props("unelevated")
                launch_button.style(
                    "height: 3.5rem; padding: 0 1.1rem; "
                    "background: var(--accent-root); color: #05111d; font-weight: 700;"
                )
                if (
                    not controller.state.replay_path
                    and not controller.state.selected_provider_fake_fixture
                ):
                    launch_button.disable()
            replay_select = ui.select(
                options=replay_options,
                value=controller.state.replay_path or None,
                label="Replay fixture",
                with_input=False,
                on_change=lambda e: controller.set_replay_path(str(e.value or "")),
            )
            replay_select.style("flex: 2 1 24rem; min-width: 18rem;")
            if not replay_options:
                replay_select.disable()
            ui.select(
                options=pf_options,
                value=controller.state.selected_provider_fake_fixture or None,
                label="Provider-fake fixture",
                with_input=False,
                on_change=lambda e: controller.set_provider_fake_fixture(str(e.value or "")),
            ).style("flex: 2 1 24rem; min-width: 18rem;")
            ui.select(
                options=skill_options,
                value=controller.state.selected_skills,
                label="Prompt-visible skills",
                multiple=True,
                with_input=False,
                on_change=lambda e: controller.set_selected_skills(list(e.value or [])),
            ).style("flex: 1 1 18rem; min-width: 16rem;")
        if not replay_options:
            ui.label("No replay fixtures found under tests_rlm_adk/replay/.").style(
                "color: var(--accent-warning); font-size: 0.82rem;"
            )
        with ui.element("div").style(
            "display: flex; flex-wrap: wrap; align-items: center; gap: 0.55rem;"
        ):
            if controller.state.replay_path:
                with ui.element("div").style(
                    "display: inline-flex; align-items: center; min-width: 0; "
                    "padding: 0.32rem 0.68rem; border-radius: 999px; "
                    "border: 1px solid var(--border-1); "
                    "background: rgba(87,199,255,0.12);"
                ):
                    ui.label(controller.state.replay_path).style(
                        "color: var(--text-0); font-size: 0.78rem;"
                    )
        with ui.element("div").style(
            "display: flex; flex-wrap: wrap; align-items: center; gap: 0.55rem;"
        ):
            for name, description in selected_skill_summaries(controller.state.selected_skills):
                with ui.element("div").style(
                    "display: inline-flex; align-items: center; min-width: 0; "
                    "padding: 0.32rem 0.68rem; border-radius: 999px; "
                    "border: 1px solid var(--border-1); "
                    "background: rgba(230,237,247,0.06);"
                ):
                    ui.label(name).style("color: var(--text-0); font-size: 0.78rem;").tooltip(
                        description
                    )
        if controller.state.launched_session_id:
            ui.label(f"Latest launched session: {controller.state.launched_session_id}").style(
                "color: var(--text-1); font-size: 0.78rem;"
            )
        if controller.state.run_status == "cancelled":
            ui.label("Run cancelled.").style(
                "color: var(--accent-warning); font-size: 0.82rem;"
            )
        if controller.state.launch_error:
            ui.label(controller.state.launch_error).style(
                "color: var(--accent-child); font-size: 0.82rem;"
            )


def _toggle(label: str, value: bool, on_change) -> None:
    ui.switch(label, value=value, on_change=lambda e: on_change(bool(e.value))).style(
        "color: var(--text-0);"
    )


def _status_badge(status: str) -> None:
    color = {
        "running": "var(--accent-active)",
        "completed": "var(--accent-root)",
        "error": "var(--accent-child)",
        "cancelled": "var(--accent-warning)",
        "idle": "var(--text-1)",
    }.get(status, "var(--text-1)")
    with ui.element("div").style(
        f"display: inline-flex; align-items: center; border-radius: 999px; "
        f"border: 1px solid {color}; background: color-mix(in srgb, {color} 16%, transparent); "
        "padding: 0.32rem 0.7rem;"
    ):
        ui.label(status).style(f"color: {color}; font-size: 0.78rem; text-transform: uppercase;")


def _metric_chip(label: str, value: str) -> None:
    with ui.element("div").style(
        "display: inline-flex; align-items: center; gap: 0.35rem; "
        "padding: 0.28rem 0.56rem; border-radius: 999px; "
        "border: 1px solid var(--border-1); background: rgba(230,237,247,0.05);"
    ):
        ui.label(label).style("color: var(--text-1); font-size: 0.72rem;")
        ui.label(value).style("color: var(--text-0); font-size: 0.74rem;")


def _truncate_chip_text(text: str, *, fallback: str, limit: int = 108) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return fallback
    return cleaned if len(cleaned) <= limit else f"{cleaned[: limit - 1].rstrip()}…"


def _session_meta_row(
    label: str,
    items: list[tuple[str, str, str]],
    *,
    controller: LiveDashboardController,
    refresh_viewer,
) -> None:
    with ui.element("div").style(
        "display: flex; flex-wrap: wrap; align-items: flex-start; gap: 0.55rem; min-width: 0;"
    ):
        ui.label(label).style(
            "min-width: 9rem; color: var(--text-1); font-size: 0.74rem; "
            "text-transform: uppercase; letter-spacing: 0.08em; padding-top: 0.3rem;"
        )
        with ui.element("div").style(
            "display: flex; flex-wrap: wrap; gap: 0.45rem; min-width: 0; flex: 1;"
        ):
            for chip_label, chip_text, raw_key in items:
                _session_chip(
                    chip_label,
                    chip_text,
                    raw_key=raw_key,
                    controller=controller,
                    refresh_viewer=refresh_viewer,
                )


def _session_chip(
    label: str,
    text: str,
    *,
    raw_key: str,
    controller: LiveDashboardController,
    refresh_viewer,
) -> None:
    with (
        ui.element("div")
        .style(
            "display: inline-flex; align-items: center; min-width: 0; cursor: pointer; "
            "padding: 0.32rem 0.68rem; border-radius: 999px; "
            "border: 1px solid var(--border-1); background: rgba(230,237,247,0.06);"
        )
        .on(
            "click.stop",
            lambda _e: _open_text_viewer(
                controller,
                refresh_viewer,
                label,
                text,
                raw_key,
            ),
        )
    ):
        ui.label(label).style("color: var(--text-0); font-size: 0.78rem;").tooltip(text)


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


def _handle_step_mode(
    value: bool,
    controller: LiveDashboardController,
    live_ui: LiveDashboardUI,
) -> None:
    controller.set_step_mode(value)
    live_ui.refresh_all()


def _step_mode_controls(controller: LiveDashboardController, live_ui: LiveDashboardUI) -> None:
    """Render the Next Step button and paused-agent label when step mode is active."""
    if not controller.state.step_mode_enabled:
        return

    async def on_advance() -> None:
        controller.advance_step()
        live_ui.refresh_all()

    btn = ui.button("Next Step", on_click=on_advance)
    btn.props("unelevated dense")
    btn.style(
        "height: 2rem; padding: 0 0.75rem; font-size: 0.78rem; font-weight: 700; "
        "background: var(--accent-active); color: #05111d;"
    )
    if not controller.state.step_mode_waiting:
        btn.disable()

    if controller.state.step_mode_paused_label:
        ui.label(controller.state.step_mode_paused_label).style(
            "color: var(--accent-warning); font-size: 0.78rem; font-weight: 600;"
        )


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


def _open_text_viewer(
    controller: LiveDashboardController,
    refresh_viewer,
    label: str,
    text: str,
    raw_key: str,
) -> None:
    controller.open_text_viewer(label=label, text=text, raw_key=raw_key)
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
