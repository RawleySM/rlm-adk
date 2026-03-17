#!/usr/bin/env python3
"""Session Transfer Gate — Stop hook script.

Checks bridge file for handoff_ready flag and either auto-launches Codex
or returns a confirm prompt, depending on SESSION_TRANSFER_MODE.

Stdlib-only. Reads JSON from stdin (Claude Code hook protocol).
"""

import json
import os
import sys
from pathlib import Path


def read_bridge_state(bridge_path: Path) -> dict | None:
    """Read handoff state from bridge file.

    Args:
        bridge_path: Path to the bridge JSON file.

    Returns:
        Parsed dict or None if file missing/invalid.
    """
    bridge_path = Path(bridge_path)
    if not bridge_path.exists():
        return None
    try:
        with open(bridge_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def should_launch_codex(handoff_ready: bool, mode: str) -> bool:
    """Determine if Codex should be auto-launched.

    Args:
        handoff_ready: Whether the handoff document is ready.
        mode: Transfer mode ('auto' or 'confirm').

    Returns:
        True if Codex should be launched now.
    """
    return handoff_ready and mode == "auto"


def build_confirm_response() -> dict:
    """Build the confirm-mode response for Claude Code.

    Returns:
        Dict with continue=True and systemMessage instructing user to confirm.
    """
    return {
        "continue": True,
        "systemMessage": (
            "Session transfer is ready. Type TRANSFER to confirm "
            "the handoff to Codex CLI, or continue working."
        ),
    }


def launch_codex(session_id: str, handoffs_dir: Path) -> None:
    """Launch Codex CLI with the handoff document.

    This is a thin wrapper that imports and calls codex_launcher.
    Separated for testability (can be mocked).

    Args:
        session_id: Session identifier.
        handoffs_dir: Path to the handoffs directory.
    """
    from scripts.codex_transfer.codex_launcher import launch

    launch(session_id=session_id, handoffs_dir=handoffs_dir)


def process_stop_hook(
    hook_input: dict,
    bridge_path: Path,
    mode: str | None = None,
    session_id: str | None = None,
    handoffs_dir: Path | None = None,
) -> dict | None:
    """Process a Stop hook input and determine response.

    Args:
        hook_input: Hook input JSON from Claude Code.
        bridge_path: Path to the bridge file.
        mode: Transfer mode override. Uses env var or defaults to 'auto'.
        session_id: Session ID for codex launch.
        handoffs_dir: Path to handoffs directory.

    Returns:
        Dict to output as JSON, or None for normal exit.
    """
    state = read_bridge_state(bridge_path)
    if state is None:
        return None

    handoff_ready = state.get("handoff_ready", False)
    if not handoff_ready:
        return None

    # Determine mode
    if mode is None:
        mode = os.environ.get("SESSION_TRANSFER_MODE", "auto")

    if mode == "confirm":
        return build_confirm_response()

    # Auto mode — launch codex
    if session_id is None:
        session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")
    if handoffs_dir is None:
        handoffs_dir = Path.home() / ".claude" / "handoffs"

    launch_codex(session_id, handoffs_dir)
    return None


def main():
    """Main entry point for Stop hook."""
    try:
        hook_input = json.load(sys.stdin)

        session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")
        bridge_path = Path(f"/tmp/claude_quota_{session_id}.json")

        result = process_stop_hook(hook_input, bridge_path)

        if result is not None:
            json.dump(result, sys.stdout)

        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
