#!/usr/bin/env python3
"""Attach to an already-running Chrome instance with the RLM dashboard.

Connects via CDP (Chrome DevTools Protocol) to the existing Chrome browser
that was launched with ``--remote-debugging-port``.  Finds the dashboard tab
and returns a Playwright ``Page`` handle for scripting against the paused run.

Usage
-----
Interactive (keep browser attached, Ctrl-C to detach)::

    python scripts/attach_dashboard_playwright.py

Print page title + URL and exit::

    python scripts/attach_dashboard_playwright.py --probe

Environment variables
---------------------
- ``RLM_PLAYWRIGHT_CHROME_REMOTE_DEBUGGING_PORT``: CDP port (default 9222).
- ``RLM_DASHBOARD_URL``: expected dashboard URL prefix (default ``http://127.0.0.1:8080/live``).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import Browser, Page, sync_playwright

DEFAULT_CDP_PORT = 9222
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:8080/live"


def get_cdp_ws_endpoint(port: int) -> str:
    """Fetch the browser-level WebSocket debugger URL from the CDP /json/version endpoint."""
    version_url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(version_url, timeout=3.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            ws_url = payload.get("webSocketDebuggerUrl")
            if isinstance(ws_url, str) and ws_url:
                return ws_url
    except (OSError, TimeoutError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Chrome CDP endpoint not reachable on port {port}. "
            "Is Chrome running with --remote-debugging-port?"
        ) from exc
    raise RuntimeError(f"CDP /json/version on port {port} did not return webSocketDebuggerUrl.")


def find_dashboard_page(browser: Browser, dashboard_url_prefix: str) -> Page:
    """Find the dashboard page among all open browser contexts/pages."""
    for context in browser.contexts:
        for page in context.pages:
            if page.url.startswith(dashboard_url_prefix):
                return page
    raise RuntimeError(
        f"No open tab found matching {dashboard_url_prefix!r}. "
        f"Open tabs: {[p.url for ctx in browser.contexts for p in ctx.pages]}"
    )


def read_dashboard_state(page: Page) -> dict:
    """Read key dashboard state from the paused run via DOM queries."""
    state: dict = {"url": page.url, "title": page.title()}

    # Step mode status badge (the yellow "Paused: ..." text near NEXT STEP)
    paused_badge = page.query_selector("text=/Paused:/")
    if paused_badge:
        state["paused_status"] = paused_badge.text_content().strip()

    # Step mode toggle state
    step_toggle = page.query_selector("text=Step mode")
    if step_toggle:
        # The toggle switch is typically a nearby Quasar q-toggle
        toggle_el = page.query_selector(".q-toggle[aria-checked]")
        if toggle_el:
            state["step_mode_enabled"] = toggle_el.get_attribute("aria-checked") == "true"

    # Session ID
    session_el = page.query_selector("text=/^Session$/")
    if session_el:
        # Session value is typically in a sibling/nearby element
        session_input = page.query_selector("input[value*='-']")
        if session_input:
            state["session_id"] = session_input.get_attribute("value")

    return state


def keep_attached(page: Page) -> None:
    """Block until Ctrl-C, keeping the Playwright connection alive."""
    stop = False

    def _handle_signal(_signum, _frame):
        nonlocal stop
        stop = True

    prev_int = signal.signal(signal.SIGINT, _handle_signal)
    prev_term = signal.signal(signal.SIGTERM, _handle_signal)
    try:
        print("Attached to dashboard. Press Ctrl-C to detach.")
        while not stop:
            time.sleep(0.5)
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Print dashboard state and exit (don't stay attached).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("RLM_PLAYWRIGHT_CHROME_REMOTE_DEBUGGING_PORT", str(DEFAULT_CDP_PORT))),
        help=f"Chrome remote debugging port (default: {DEFAULT_CDP_PORT}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dashboard_url = os.getenv("RLM_DASHBOARD_URL", DEFAULT_DASHBOARD_URL)

    ws_endpoint = get_cdp_ws_endpoint(args.port)
    print(f"CDP endpoint: {ws_endpoint}")

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(ws_endpoint)
        print(f"Connected — {len(browser.contexts)} context(s)")

        page = find_dashboard_page(browser, dashboard_url)
        print(f"Found dashboard: {page.title()} @ {page.url}")

        if args.probe:
            state = read_dashboard_state(page)
            print(json.dumps(state, indent=2))
            return 0

        keep_attached(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
