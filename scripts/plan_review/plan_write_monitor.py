#!/usr/bin/env python3
"""Plan Write Monitor — PostToolUse hook script.

Detects Write tool calls that target ~/.claude/plans/*.md and updates the
plan-review bridge file so the Stop hook knows a plan is pending review.

Stdlib-only. Reads JSON from stdin (Claude Code hook protocol).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Inline imports to stay stdlib-only and avoid package installs.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from bridge import (
    bridge_path,
    is_plan_file,
    log,
    new_bridge_state,
    read_bridge,
    write_bridge,
)


def process_hook_input(hook_input: dict, bp: Path) -> dict | None:
    """Process a PostToolUse hook event.

    Returns a dict to write to stdout (systemMessage), or None for no-op.
    """
    # Feature gate — cheapest check first
    if os.environ.get("PLAN_REVIEW_ENABLED", "0") != "1":
        return None

    # Only care about Write tool calls
    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Write":
        return None

    # Check if the written file is a plan
    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path or not is_plan_file(file_path):
        return None

    # Check if we already have an active review cycle for this plan
    existing = read_bridge(bp)
    if existing and existing.get("plan_path") == file_path and not existing.get("review_approved"):
        # Same plan rewritten (revision) — bump doesn't reset iteration
        log(f"[MONITOR] Plan revision detected: {file_path} (iteration {existing.get('iteration', 0)})")
        return None

    # New plan — initialise bridge
    state = new_bridge_state(file_path)
    write_bridge(bp, state)
    log(f"[MONITOR] New plan detected: {file_path} — bridge initialised")

    return None  # No systemMessage needed; the Stop hook does the work


def main() -> None:
    """Entry point for PostToolUse hook."""
    try:
        hook_input = json.load(sys.stdin)
        bp = bridge_path()
        result = process_hook_input(hook_input, bp)
        if result is not None:
            json.dump(result, sys.stdout)
        sys.exit(0)
    except Exception as exc:
        # Hooks must never crash Claude Code — but log for debuggability
        print(f"[HOOK ERROR] plan_write_monitor: {exc}", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
