"""Codex Launcher — spawns a detached Codex CLI with the handoff document.

Stdlib-only. Fire-and-forget subprocess launch.
"""

import json
import subprocess
import time
from pathlib import Path

PROJECT_DIR = "/home/rawley-stanhope/dev/rlm-adk"

PREAMBLE = (
    "You are continuing a development session that was transferred from "
    "Claude Code due to approaching usage quota limits. Below is the handoff "
    "document from the previous session.\n\n"
    "IMPORTANT: Before starting any work, spawn agent codebase-explorers to "
    "review the codebase AND the Claude Code session in "
    "~/.claude/projects/-home-rawley-stanhope-dev-rlm-adk/ to understand "
    "the full context of the project and the previous session's work.\n\n"
)


def read_handoff_doc(doc_path: Path) -> str:
    """Read a handoff document.

    Args:
        doc_path: Path to the handoff markdown file.

    Returns:
        The document content as a string.

    Raises:
        FileNotFoundError: If the document does not exist.
    """
    doc_path = Path(doc_path)
    if not doc_path.exists():
        raise FileNotFoundError(f"Handoff document not found: {doc_path}")
    return doc_path.read_text()


def build_prompt(handoff_content: str, session_id: str) -> str:
    """Construct the full prompt for Codex CLI.

    Args:
        handoff_content: Content of the handoff document.
        session_id: Session identifier from the transferring session.

    Returns:
        Complete prompt string.
    """
    return (
        f"{PREAMBLE}"
        f"## Transferred Session: {session_id}\n\n"
        f"## Handoff Document\n\n"
        f"{handoff_content}\n\n"
        f"## Instructions\n\n"
        f"1. Spawn agent codebase-explorers to review the codebase at "
        f"{PROJECT_DIR}\n"
        f"2. Review the Claude Code projects directory at "
        f"~/.claude/projects/-home-rawley-stanhope-dev-rlm-adk/ for "
        f"session context\n"
        f"3. Continue the work described in the handoff document\n"
        f"4. Follow the same coding standards and patterns used in the "
        f"existing codebase\n"
    )


def launch(
    session_id: str,
    handoffs_dir: Path,
) -> None:
    """Launch Codex CLI with the handoff document.

    Spawns a detached process using ``subprocess.Popen(start_new_session=True)``
    for fire-and-forget execution. Writes a transfer log JSON file.

    Args:
        session_id: Session identifier.
        handoffs_dir: Path to the handoffs directory.

    Raises:
        FileNotFoundError: If the handoff document does not exist.
    """
    handoffs_dir = Path(handoffs_dir)
    doc_path = handoffs_dir / f"{session_id}_handoff.md"

    handoff_content = read_handoff_doc(doc_path)
    prompt = build_prompt(handoff_content, session_id)

    cmd = [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--enable", "multi_agent",
        "--enable", "child_agents_md",
        "-C", PROJECT_DIR,
        "-m", "gpt-5.4",
        prompt,
    ]

    proc = subprocess.Popen(
        cmd,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )

    # Write transfer log
    log_path = handoffs_dir / f"{session_id}_transfer.json"
    log_data = {
        "session_id": session_id,
        "pid": proc.pid,
        "launched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "command": cmd,
        "handoff_doc": str(doc_path),
    }
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2)
