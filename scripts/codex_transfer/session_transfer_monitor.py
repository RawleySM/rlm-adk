#!/usr/bin/env python3
"""Session Transfer Monitor — PostToolUse hook script.

Reads the bridge file written by quota_poller and, when usage exceeds the
threshold, instructs Claude Code to write a handoff document.

Stdlib-only. Reads JSON from stdin (Claude Code hook protocol).
"""

import json
import os
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 80.0

HANDOFF_SYSTEM_MESSAGE = (
    "URGENT: Your usage quota is approaching its limit. "
    "Please write a comprehensive handoff document to "
    ".claude/handoffs/<session_id>_handoff.md that includes:\n"
    "1. Current task description and progress\n"
    "2. Key files modified and their purposes\n"
    "3. Remaining work items and next steps\n"
    "4. Any important context or decisions made\n"
    "5. Known issues or blockers\n\n"
    "Use the Write tool to create this file now. "
    "The session will be transferred to Codex CLI once the handoff document is ready."
)


def read_bridge_file(bridge_path: Path) -> dict | None:
    """Read and parse the bridge file.

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


def update_bridge_file(bridge_path: Path, updates: dict) -> None:
    """Update specific fields in the bridge file.

    Args:
        bridge_path: Path to the bridge JSON file.
        updates: Dict of fields to update.
    """
    bridge_path = Path(bridge_path)
    existing = read_bridge_file(bridge_path)
    if existing is None:
        existing = {}
    existing.update(updates)
    bridge_path.parent.mkdir(parents=True, exist_ok=True)
    with open(bridge_path, "w") as f:
        json.dump(existing, f, indent=2)


def should_trigger_handoff(bridge_data: dict, threshold: float | None = None) -> bool:
    """Determine if handoff should be triggered.

    Args:
        bridge_data: Current bridge file data.
        threshold: Usage percentage threshold. Defaults to DEFAULT_THRESHOLD.

    Returns:
        True if handoff should be triggered (first time).
    """
    if threshold is None:
        threshold = DEFAULT_THRESHOLD

    # Don't re-trigger if already requested or ready
    if bridge_data.get("handoff_requested", False):
        return False
    if bridge_data.get("handoff_ready", False):
        return False

    five_hour_pct = bridge_data.get("five_hour_pct", 0.0)
    return five_hour_pct >= threshold


def is_handoff_write(hook_input: dict) -> bool:
    """Check if this hook event is a Write to the handoffs directory.

    Args:
        hook_input: Hook input data from Claude Code.

    Returns:
        True if a Write tool wrote to .claude/handoffs/.
    """
    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Write":
        return False

    tool_input = hook_input.get("tool_input", {})
    if not tool_input:
        return False

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return False

    # Check if path contains handoffs directory and ends with _handoff.md
    return "/handoffs/" in file_path and file_path.endswith("_handoff.md")


def build_system_message() -> dict:
    """Build the systemMessage JSON for Claude Code hook response.

    Returns:
        Dict with systemMessage key.
    """
    return {"systemMessage": HANDOFF_SYSTEM_MESSAGE}


def process_hook_input(
    hook_input: dict,
    bridge_path: Path,
    threshold: float | None = None,
) -> dict | None:
    """Process a PostToolUse hook input and determine response.

    Args:
        hook_input: Hook input JSON from Claude Code.
        bridge_path: Path to the bridge file.
        threshold: Override threshold (otherwise uses env var or default).

    Returns:
        Dict to output as JSON (with systemMessage), or None for no response.
    """
    bridge_data = read_bridge_file(bridge_path)
    if bridge_data is None:
        return None

    # Determine threshold from env or parameter
    if threshold is None:
        env_threshold = os.environ.get("SESSION_TRANSFER_THRESHOLD")
        if env_threshold is not None:
            threshold = float(env_threshold)
        else:
            threshold = DEFAULT_THRESHOLD

    # If handoff is already complete, do nothing
    if bridge_data.get("handoff_ready", False):
        return None

    # Check if this is a handoff write
    if bridge_data.get("handoff_requested", False) and is_handoff_write(hook_input):
        update_bridge_file(bridge_path, {"handoff_ready": True})
        return None

    # First-time trigger
    if should_trigger_handoff(bridge_data, threshold=threshold):
        update_bridge_file(bridge_path, {
            "handoff_requested": True,
            "tool_calls_since_request": 0,
        })
        return build_system_message()

    # If handoff requested but not yet written, track tool calls
    if bridge_data.get("handoff_requested", False):
        calls = bridge_data.get("tool_calls_since_request", 0) + 1
        if calls > 5:
            # Re-send system message and reset counter
            update_bridge_file(bridge_path, {"tool_calls_since_request": 0})
            return build_system_message()
        else:
            update_bridge_file(bridge_path, {"tool_calls_since_request": calls})
            return None

    return None


def main():
    """Main entry point for PostToolUse hook."""
    try:
        hook_input = json.load(sys.stdin)

        session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")
        bridge_path = Path(f"/tmp/claude_quota_{session_id}.json")

        result = process_hook_input(hook_input, bridge_path)

        if result is not None:
            json.dump(result, sys.stdout)

        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
