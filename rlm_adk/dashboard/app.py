"""NiceGUI dashboard entry point.

Registers the ``/live`` page (via live_app import) and provides
the ``launch_dashboard()`` function that calls ``ui.run()``.
"""

from __future__ import annotations

import os

from nicegui import app, ui
from starlette.responses import RedirectResponse

from rlm_adk.dashboard import flow_child_page as _flow_child_page  # noqa: F401

# Register the live dashboard page before ui.run().
from rlm_adk.dashboard import live_app as _live_app  # noqa: F401
from rlm_adk.plugins.dashboard_auto_launch import DASHBOARD_ACTIVE_ENV


@app.get("/")
async def _root_redirect() -> RedirectResponse:
    """Redirect ``/`` to ``/live`` so bare-URL visits don't 404."""
    return RedirectResponse("/live")


def launch_dashboard(
    host: str = "0.0.0.0",
    port: int = 8080,
    reload: bool = False,
) -> None:
    """Entry point for launching the dashboard.

    Usage:
        python -m rlm_adk.dashboard
        # or
        from rlm_adk.dashboard import launch_dashboard
        launch_dashboard()
    """
    os.environ[DASHBOARD_ACTIVE_ENV] = "1"
    ui.run(
        host=host,
        port=port,
        title="RLM Context Window Dashboard",
        dark=True,
        reload=reload,
        show=False,
    )
