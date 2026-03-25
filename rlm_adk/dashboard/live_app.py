"""NiceGUI page for the live recursive dashboard."""

from __future__ import annotations

from typing import Any

from nicegui import ui

from rlm_adk.dashboard.components.flow_context_inspector import render_flow_context_inspector
from rlm_adk.dashboard.components.flow_transcript import render_flow_transcript
from rlm_adk.dashboard.components.live_context_viewer import render_live_context_viewer
from rlm_adk.dashboard.components.live_invocation_tree import render_live_invocation_tree
from rlm_adk.dashboard.live_controller import LiveDashboardController, LiveDashboardUI
from rlm_adk.dashboard.live_loader import LiveDashboardLoader
from rlm_adk.dashboard.run_service import resolve_fixture_file_path

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
  .flow-nav-rail {
    width: 4rem;
    min-width: 4rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 0;
    border-right: 1px solid var(--border-1);
    background: rgba(11,16,32,0.96);
    position: sticky;
    top: 0;
    height: 100vh;
  }
  .flow-nav-btn {
    width: 2.8rem;
    height: 2.8rem;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 10px;
    border: 1px solid var(--border-1);
    cursor: pointer;
    transition: background 0.15s;
  }
  .flow-nav-btn:hover {
    background: rgba(87,199,255,0.12);
  }
  .flow-nav-btn--active {
    background: rgba(87,199,255,0.18);
    border-color: var(--accent-root);
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
<script>
/* ── Dev overlay: hold Ctrl+Shift+Z/X/C to show element labels at 3 abstraction levels ── */
(() => {
  if (window.__rlmDevOverlayInstalled) return;
  window.__rlmDevOverlayInstalled = true;

  const OV = 'rlm-dev-overlay';
  const OV_BOX = 'rlm-dev-overlay-box';
  let active = null;

  /* ── Level definitions ── */
  const LEVELS = {
    /* Z — Sections & panes: structural regions + bordered container panes */
    z: {
      tag: 'Section',
      bg: '#2196F3',
      outline: 'rgba(33,150,243,0.5)',
      select() {
        const hits = new Set();
        /* Known structural classes */
        document.querySelectorAll(
          '.live-dashboard, .flow-nav-rail, .live-context-viewer, .live-context-viewer__shell'
        ).forEach(el => hits.add(el));
        /* Sticky header */
        document.querySelectorAll('[style*="position: sticky"]').forEach(el => hits.add(el));
        /* NiceGUI containers with child NiceGUI IDs (structural parents) */
        document.querySelectorAll('[id^="c"]').forEach(el => {
          if (el.querySelector('[id^="c"]') && el.getBoundingClientRect().height > 80) {
            const depth = _niceguiDepth(el);
            if (depth <= 3) hits.add(el);
          }
        });
        /* Bordered panes: containers with border styling, child IDs, and meaningful size */
        document.querySelectorAll('[id][style*="border"]').forEach(el => {
          const s = el.getAttribute('style') || '';
          if (s.indexOf('border-radius: 999px') > -1) return; /* skip pill chips */
          if (!el.querySelector('[id^="c"]')) return;          /* must be a container */
          const r = el.getBoundingClientRect();
          if (r.height > 100 && r.width > 200) hits.add(el);  /* meaningful pane size */
        });
        return [...hits].filter(_visible);
      },
    },
    /* X — Widgets: interactive Quasar components + pill-shaped chips */
    x: {
      tag: 'Widget',
      bg: '#FF9800',
      outline: 'rgba(255,152,0,0.45)',
      select() {
        const hits = new Set();
        document.querySelectorAll(
          '.q-btn, .q-toggle, .q-select, .q-field, ' +
          '[role="switch"], [role="combobox"], [role="button"], ' +
          'button, .flow-nav-btn'
        ).forEach(el => hits.add(el));
        /* All pill-shaped chips (clickable or display-only) */
        document.querySelectorAll('[style*="border-radius: 999px"]')
          .forEach(el => hits.add(el));
        return [...hits].filter(_visible);
      },
    },
    /* C — Non-widget elements: text leaves + structural containers, excluding widgets */
    c: {
      tag: 'Text',
      bg: '#f44336',
      outline: null,
      select() {
        return [...document.querySelectorAll('[id]')].filter(el => {
          if (!_visible(el)) return false;
          /* Skip if this element IS or is INSIDE a widget or pill chip */
          if (el.closest('.q-btn, .q-toggle, .q-select, .q-field, [role="switch"], [role="combobox"], [role="button"], button, .flow-nav-btn')) return false;
          if (el.closest('[style*="border-radius: 999px"]') || el.matches('[style*="border-radius: 999px"]')) return false;
          const text = el.textContent?.trim();
          return text && text.length > 0;
        });
      },
    },
  };

  function _visible(el) {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function _niceguiDepth(el) {
    let d = 0, node = el.parentElement;
    while (node) {
      if (node.id && /^c\d+$/.test(node.id)) d++;
      node = node.parentElement;
    }
    return d;
  }

  function show(level) {
    if (active === level) return;
    clear();
    active = level;
    const cfg = LEVELS[level];
    const els = cfg.select();
    const scrollY = window.scrollY;

    els.forEach(el => {
      const rect = el.getBoundingClientRect();
      const id = el.id ? '#' + el.id : (el.className?.split?.(' ')[0] || el.tagName.toLowerCase());

      /* Label badge */
      const lbl = document.createElement('div');
      lbl.className = OV;
      lbl.textContent = cfg.tag + ': ' + id;
      lbl.style.cssText =
        'position:absolute;z-index:100000;pointer-events:none;border-radius:2px;' +
        'font:bold 10px/1.3 monospace;padding:1px 4px;white-space:nowrap;opacity:0.92;' +
        'background:' + cfg.bg + ';color:#fff;';
      lbl.style.top = (rect.top + scrollY) + 'px';
      lbl.style.left = rect.left + 'px';
      document.body.appendChild(lbl);

      /* Outline box (sections & widgets only) */
      if (cfg.outline) {
        const box = document.createElement('div');
        box.className = OV_BOX;
        box.style.cssText =
          'position:absolute;z-index:99999;pointer-events:none;' +
          'border:2px solid ' + cfg.outline + ';border-radius:4px;' +
          'background:' + cfg.outline.replace(/[\d.]+\)$/, '0.08)') + ';';
        box.style.top = (rect.top + scrollY) + 'px';
        box.style.left = rect.left + 'px';
        box.style.width = rect.width + 'px';
        box.style.height = rect.height + 'px';
        document.body.appendChild(box);
      }
    });
  }

  function clear() {
    document.querySelectorAll('.' + OV + ',.' + OV_BOX).forEach(n => n.remove());
    active = null;
  }

  /* Capture-phase listener: toggle on press (not hold-to-show).
     Press Ctrl+Shift+Z to show sections, press again to hide.
     Pressing a different level while one is active switches to the new level. */
  document.addEventListener('keydown', e => {
    if (e.repeat) return;  /* ignore key-repeat while held */
    if (!e.ctrlKey || !e.shiftKey) return;
    const k = e.key.toLowerCase();
    if (k in LEVELS) {
      e.preventDefault();
      e.stopPropagation();
      if (active === k) {
        clear();           /* same key again → toggle off */
      } else {
        show(k);           /* different key or none active → show */
      }
    }
  }, true);
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
                if session_summary.user_query:
                    _query_chips = [
                        (
                            _truncate_chip_text(session_summary.user_query, fallback=""),
                            session_summary.user_query,
                            "user-query",
                        )
                    ]
                else:
                    _fixture_queries = _on_deck_fixture_queries(controller)
                    if _fixture_queries:
                        _query_chips = [
                            (
                                _truncate_chip_text(q, fallback=""),
                                q,
                                f"fixture-query-{i}",
                            )
                            for i, q in enumerate(_fixture_queries)
                        ]
                    else:
                        _query_chips = [("No query captured", "No query captured.", "user-query")]
                _session_meta_row(
                    "User Query",
                    _query_chips,
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
            if controller.state.view_mode == "flow":
                _render_flow_view(controller, live_ui, text_panel_body)
            else:
                render_live_invocation_tree(
                    controller.state.run_state.invocation_nodes
                    if controller.state.run_state
                    else [],
                    on_open_context=lambda invocation,
                    item,
                    lineage: _open_invocation_context_viewer(
                        controller,
                        text_panel_body,
                        invocation,
                        item,
                        lineage,
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
            "min-height: 100vh; width: 100%; display: flex; flex-direction: column; "
            "background: radial-gradient(circle at top left, "
            "rgba(87,199,255,0.12), transparent 24%), "
            "radial-gradient(circle at top right, rgba(255,107,159,0.12), transparent 24%), "
            "linear-gradient(180deg, var(--bg-0), #060912);"
        )
    ):
        header_section()
        with ui.element("div").style("display: flex; flex: 1; min-height: 0; width: 100%;"):
            # Nav rail
            _nav_rail(controller, live_ui)
            # Main content area
            with ui.element("div").style("flex: 1; min-width: 0; overflow-y: auto;"):
                invocation_section()
        text_panel_body()

    async def _poll() -> None:
        changed = await controller.poll()
        cancel_pending = (
            controller.state.launch_cancelled and not controller.state.launch_in_progress
        )
        if (
            changed
            or controller.state.launch_in_progress
            or controller.state.launch_error
            or cancel_pending
        ):
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


def _on_deck_fixture_queries(controller: LiveDashboardController) -> list[str]:
    """Read the ``queries`` list from the on-deck replay/provider-fake fixture."""
    import json as _json

    if controller.state.replay_path:
        kind, value = "replay", controller.state.replay_path
    elif controller.state.selected_provider_fake_fixture:
        kind, value = "provider_fake", controller.state.selected_provider_fake_fixture
    else:
        return []
    path = resolve_fixture_file_path(kind, value)
    if path is None or not path.exists():
        return []
    try:
        with path.open() as fh:
            data = _json.load(fh)
        return list(data.get("queries") or [])
    except Exception:
        return []


def _launch_panel(controller: LiveDashboardController, live_ui: LiveDashboardUI) -> None:
    replay_options = controller.state.available_replay_fixtures
    pf_options = controller.state.available_provider_fake_fixtures

    # ── Derive on-deck fixture state ──
    if controller.state.replay_path:
        on_deck_label = controller.state.replay_path.split("/")[-1].replace(".json", "")
        on_deck_kind = "replay"
        header_label = "Launch Replay"
        launch_label = "Launch Replay"
    elif controller.state.selected_provider_fake_fixture:
        on_deck_label = controller.state.selected_provider_fake_fixture
        on_deck_kind = "provider-fake"
        header_label = "Launch Fixture"
        launch_label = "Launch Fixture"
    else:
        on_deck_label = ""
        on_deck_kind = ""
        header_label = "Launch"
        launch_label = "Launch"

    async def on_launch() -> None:
        await controller.launch_replay()
        live_ui.refresh_all()

    async def on_cancel() -> None:
        await controller.cancel_launch()
        live_ui.refresh_all()

    def on_replay_change(e) -> None:
        controller.set_replay_path(str(e.value or ""))
        live_ui.refresh_all()

    def on_pf_change(e) -> None:
        controller.set_provider_fake_fixture(str(e.value or ""))
        live_ui.refresh_all()

    def on_open_on_deck() -> None:
        controller.open_on_deck_fixture_viewer()
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
            "display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; min-width: 0;"
        ):
            # ── Launch / Cancel button ──
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
                if not on_deck_label:
                    launch_button.disable()

            # ── On-deck fixture chip ──
            if on_deck_label:
                with (
                    ui.element("div")
                    .style(
                        "display: inline-flex; align-items: center; gap: 0.45rem; "
                        "padding: 0.4rem 0.85rem; border-radius: 999px; cursor: pointer; "
                        "border: 1.5px solid var(--accent-root); "
                        "background: rgba(87,199,255,0.15); height: 2.4rem;"
                    )
                    .on("click", on_open_on_deck)
                ):
                    ui.label(on_deck_kind).style(
                        "color: var(--accent-root); font-size: 0.72rem; font-weight: 700; "
                        "text-transform: uppercase; letter-spacing: 0.06em;"
                    )
                    ui.label(on_deck_label).style(
                        "color: var(--text-0); font-size: 0.82rem; font-weight: 600;"
                    )
            else:
                with ui.element("div").style(
                    "display: inline-flex; align-items: center; "
                    "padding: 0.4rem 0.85rem; border-radius: 999px; "
                    "border: 1px dashed var(--border-1); "
                    "background: transparent; height: 2.4rem;"
                ):
                    ui.label("No fixture on deck").style(
                        "color: var(--text-1); font-size: 0.78rem; font-style: italic;"
                    )

            # ── Spacer pushes dropdowns right ──
            ui.element("div").style("flex: 1 1 0;")

            # ── Fixture selection dropdowns (right-aligned) ──
            replay_select = ui.select(
                options=replay_options,
                value=controller.state.replay_path or None,
                label="Select live replay",
                with_input=False,
                on_change=on_replay_change,
            )
            replay_select.style("flex: 1 1 14rem; min-width: 14rem;")
            if not replay_options:
                replay_select.disable()
            ui.select(
                options=pf_options,
                value=controller.state.selected_provider_fake_fixture or None,
                label="Select provider-fake",
                with_input=False,
                on_change=on_pf_change,
            ).style("flex: 1 1 14rem; min-width: 14rem;")
        if not replay_options:
            ui.label("No replay fixtures found under tests_rlm_adk/replay/.").style(
                "color: var(--accent-warning); font-size: 0.82rem;"
            )
        if controller.state.launched_session_id:
            ui.label(f"Latest launched session: {controller.state.launched_session_id}").style(
                "color: var(--text-1); font-size: 0.78rem;"
            )
        if controller.state.run_status == "cancelled":
            ui.label("Run cancelled.").style("color: var(--accent-warning); font-size: 0.82rem;")
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


def _close_context_viewer(
    controller: LiveDashboardController,
    refresh_viewer,
) -> None:
    controller.close_context_viewer()
    refresh_viewer.refresh()


def _nav_rail(controller: LiveDashboardController, live_ui: LiveDashboardUI) -> None:
    """Render the left nav rail with view toggle icons."""
    with ui.element("div").classes("flow-nav-rail"):
        # Flow view button
        flow_active = "flow-nav-btn--active" if controller.state.view_mode == "flow" else ""
        with (
            ui.element("div")
            .classes(f"flow-nav-btn {flow_active}")
            .on("click", lambda: _set_view_mode("flow", controller, live_ui))
        ):
            ui.label("\u2261").style(
                "color: var(--text-0); font-size: 1.3rem; font-weight: 700;"
            ).tooltip("Transcript")

        # Tree view button
        tree_active = "flow-nav-btn--active" if controller.state.view_mode == "tree" else ""
        with (
            ui.element("div")
            .classes(f"flow-nav-btn {tree_active}")
            .on("click", lambda: _set_view_mode("tree", controller, live_ui))
        ):
            ui.label("\u25e8").style(
                "color: var(--text-0); font-size: 1.3rem; font-weight: 700;"
            ).tooltip("Tree")


def _set_view_mode(
    mode: str,
    controller: LiveDashboardController,
    live_ui: LiveDashboardUI,
) -> None:
    controller.state.view_mode = mode
    live_ui.refresh_all()


def _render_flow_view(
    controller: LiveDashboardController,
    live_ui: LiveDashboardUI,
    text_panel_body,
) -> None:
    """Render the flow transcript with optional context inspector sidebar."""
    transcript = controller.flow_transcript()

    with ui.element("div").style("display: flex; flex: 1; min-width: 0; width: 100%;"):
        # Main transcript column
        with ui.element("div").style(
            "flex: 1; min-width: 0; padding: 0.75rem 1rem; overflow-y: auto;"
        ):
            ui.label("Recursive Notebook Flow").style(
                "color: var(--text-0); font-size: 1.1rem; font-weight: 800; margin-bottom: 0.65rem;"
            )
            render_flow_transcript(
                transcript,
                on_open_context=lambda pane_id, item, inv_id="": _open_flow_context(
                    controller, text_panel_body, pane_id, item, inv_id
                ),
                on_open_child_window=lambda child: _open_child_window(controller, child),
            )

        # Context inspector sidebar
        if transcript.inspector is not None:
            inspector = transcript.inspector
            # Enrich with session skills
            session_summary = controller.session_summary()
            from rlm_adk.dashboard.flow_models import FlowInspectorData

            enriched = FlowInspectorData(
                state_items=inspector.state_items,
                skills=session_summary.registered_skills,
                return_value_json=inspector.return_value_json,
                selected_pane_id=inspector.selected_pane_id,
                context_items=inspector.context_items,
            )
            render_flow_context_inspector(
                enriched,
                on_click_item=lambda item: _open_flow_state_item(controller, text_panel_body, item),
            )


def _open_flow_context(
    controller: LiveDashboardController,
    refresh_viewer,
    pane_id: str,
    item,
    invocation_id: str = "",
) -> None:
    """Open context viewer for a flow context chip, using the clicked card's invocation."""
    pane = controller._pane_by_id(pane_id)
    invocation = _find_invocation_by_id(pane, invocation_id) or controller.selected_invocation(pane)
    lineage = controller.selected_invocation_lineage()
    if invocation is not None:
        controller.open_invocation_context_viewer(invocation, item, lineage)
        refresh_viewer.refresh()


def _find_invocation_by_id(pane, invocation_id: str):
    """Find a specific invocation by ID within a pane."""
    if not pane or not invocation_id or not pane.invocations:
        return None
    for inv in pane.invocations:
        if inv.invocation_id == invocation_id:
            return inv
    return None


def _open_flow_state_item(
    controller: LiveDashboardController,
    refresh_viewer,
    item,
) -> None:
    """Open context viewer for a state item from the inspector."""
    value_text = item.value if isinstance(item.value, str) else repr(item.value)
    controller.open_text_viewer(
        label=item.base_key,
        text=value_text,
        raw_key=item.raw_key,
    )
    refresh_viewer.refresh()


def _open_child_window(
    controller: LiveDashboardController,
    child,
) -> None:
    """Open a child pane in a new browser window."""
    if not child.pane_id or not controller.state.selected_session_id:
        return
    url = f"/live/session/{controller.state.selected_session_id}/pane/{child.pane_id}"
    ui.run_javascript(f'window.open("{url}", "_blank")')
