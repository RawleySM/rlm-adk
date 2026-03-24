"""Dedicated child transcript page at /live/session/{session_id}/pane/{pane_id}."""

from __future__ import annotations

from nicegui import ui

from rlm_adk.dashboard.components.child_window_header import render_child_window_header
from rlm_adk.dashboard.components.flow_transcript import render_flow_transcript
from rlm_adk.dashboard.flow_builder import build_flow_transcript

# Import the CSS constant from live_app to reuse the same theme
from rlm_adk.dashboard.live_app import _LIVE_PAGE_CSS
from rlm_adk.dashboard.live_controller import LiveDashboardController
from rlm_adk.dashboard.live_loader import LiveDashboardLoader
from rlm_adk.dashboard.live_models import LiveInvocationNode


def _find_subtree_node(
    nodes: list[LiveInvocationNode],
    target_pane_id: str,
) -> LiveInvocationNode | None:
    """Find a node by pane_id in the invocation tree (DFS)."""
    for node in nodes:
        if node.pane_id == target_pane_id:
            return node
        found = _find_subtree_node(node.child_nodes, target_pane_id)
        if found is not None:
            return found
    return None


@ui.page("/live/session/{session_id}/pane/{pane_id}")
async def child_transcript_page(session_id: str, pane_id: str) -> None:
    """Render a child agent's flow transcript rooted at the given pane."""
    loader = LiveDashboardLoader()
    controller = LiveDashboardController(loader)

    await controller.initialize()

    # Load the specific session
    try:
        await controller.select_session(session_id)
    except Exception:
        ui.label(f"Session not found: {session_id}").style("color: var(--accent-child);")
        return

    ui.dark_mode(True)
    ui.page_title(f"RLM Child: {pane_id}")
    ui.add_head_html(_LIVE_PAGE_CSS)

    # Find the target pane in the invocation tree
    tree = controller.invocation_tree()
    target_node = _find_subtree_node(tree, pane_id)

    with (
        ui.element("div")
        .classes("live-dashboard")
        .style(
            "min-height: 100vh; width: 100%; "
            "background: radial-gradient(circle at top left, "
            "rgba(87,199,255,0.12), transparent 24%), "
            "radial-gradient(circle at top right, rgba(255,107,159,0.12), transparent 24%), "
            "linear-gradient(180deg, var(--bg-0), #060912);"
        )
    ):
        if target_node is None:
            render_child_window_header(
                session_id=session_id,
                pane_id=pane_id,
            )
            ui.label(f"Pane not found: {pane_id}").style(
                "color: var(--accent-child); padding: 1rem;"
            )
            return

        inv = target_node.invocation
        render_child_window_header(
            session_id=session_id,
            pane_id=pane_id,
            agent_name=inv.agent_name,
            depth=inv.depth,
            fanout_idx=inv.fanout_idx,
            parent_label=f"d{max(0, inv.depth - 1)}:froot",
        )

        # Build transcript rooted at this node
        transcript = build_flow_transcript([target_node])

        with ui.element("div").style("padding: 0.75rem 1rem;"):
            ui.label(f"Child Transcript: {inv.agent_name}").style(
                "color: var(--text-0); font-size: 1.1rem; font-weight: 800; margin-bottom: 0.65rem;"
            )
            render_flow_transcript(transcript)
