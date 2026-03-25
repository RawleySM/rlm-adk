"""RLM Context Window Dashboard.

NiceGUI-based visualization of context window token composition
across reasoning and worker agent iterations.

Usage:
    python -m rlm_adk.dashboard
    # or
    from rlm_adk.dashboard import launch_dashboard
    launch_dashboard()
"""


def launch_dashboard(
    host: str = "0.0.0.0",
    port: int = 8080,
    reload: bool = False,
) -> None:
    """Launch the NiceGUI dashboard (lazy import to avoid requiring NiceGUI at import time)."""
    from rlm_adk.dashboard.app import launch_dashboard as _launch

    _launch(host=host, port=port, reload=reload)


__all__ = ["launch_dashboard"]
