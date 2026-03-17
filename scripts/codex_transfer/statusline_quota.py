#!/usr/bin/env python3
"""Status Line Quota — helper for statusline-command.sh.

Reads cached usage data and outputs a colored quota indicator.
Called from the shell statusline command to show ``[quota: N%]``.

Stdlib-only.
"""

import json
import os
import sys
import time
from pathlib import Path

# ANSI color codes
COLOR_GREEN = "\033[32m"
COLOR_YELLOW = "\033[33m"
COLOR_RED = "\033[31m"
COLOR_RESET = "\033[0m"


def read_cached_usage(cache_path: Path) -> dict | None:
    """Read cached usage data from disk.

    Unlike the quota_poller cache reader, this does NOT enforce TTL —
    the status line should always show the most recent data available.

    Args:
        cache_path: Path to the usage_cache.json file.

    Returns:
        The usage data dict, or None if unavailable/corrupt.
    """
    cache_path = Path(cache_path)
    if not cache_path.exists():
        return None
    try:
        with open(cache_path) as f:
            cache = json.load(f)
        return cache.get("data")
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def get_ansi_color(pct: float) -> str:
    """Return the ANSI color code for a given usage percentage.

    Args:
        pct: Usage percentage (0-100).

    Returns:
        ANSI color escape sequence.
    """
    if pct >= 80.0:
        return COLOR_RED
    if pct >= 50.0:
        return COLOR_YELLOW
    return COLOR_GREEN


def format_quota_display(data: dict | None) -> str:
    """Format usage data into a colored status line string.

    Reads from bridge file format (``five_hour_pct`` key) written by
    ``quota_poller.poll_quota()``.

    Args:
        data: Bridge file dict with ``five_hour_pct``, or None.

    Returns:
        Formatted string like ``[quota: 42%]`` with ANSI colors,
        or empty string if data is None.
    """
    if data is None:
        return ""

    pct = data.get("five_hour_pct", 0.0)
    color = get_ansi_color(pct)
    return f"{color}[quota: {round(pct)}%]{COLOR_RESET}"


def _find_bridge_file() -> Path | None:
    """Find the bridge file for the current session."""
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    if session_id:
        p = Path(f"/tmp/claude_quota_{session_id}.json")
        if p.exists():
            return p
    # Fallback: find most recent bridge file
    import glob
    bridges = sorted(glob.glob("/tmp/claude_quota_*.json"), key=os.path.getmtime, reverse=True)
    return Path(bridges[0]) if bridges else None


def main():
    """Main entry point — print quota status line."""
    bridge = _find_bridge_file()
    if bridge:
        data = read_cached_usage(bridge)
    else:
        data = None
    output = format_quota_display(data)
    if output:
        print(output, end="")


if __name__ == "__main__":
    main()
