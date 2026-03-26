#!/usr/bin/env python3
"""Stop hook: detect when branch documentation may need updating after code changes.

Scans recently-modified .py files under rlm_adk/ and tests_rlm_adk/, checks
whether the corresponding branch doc is older, and prints a structured message
if staleness is detected.

As a Claude Code Stop hook, this script:
- Reads JSON from stdin (includes stop_hook_active flag)
- If stop_hook_active is true, the agent already tried once — let it stop (exit 0)
- If staleness found, exits with code 2 to BLOCK the stop and feed the message
  back to the agent as its next instruction, giving it a chance to update docs
- If no staleness, exits 0 silently (agent stops normally)

Usage:
    uv run python ai_docs/scripts/check_doc_staleness.py [--project-root PATH]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# How far back to look for recently-modified source files (seconds).
RECENCY_WINDOW = 5 * 60  # 5 minutes

# Explicit file -> branch-doc mapping.  Values are lists so a single file can
# map to multiple branch docs.
FILE_TO_BRANCHES: dict[str, list[str]] = {
    # Core Loop
    "rlm_adk/orchestrator.py": ["rlm_adk_docs/core_loop.md"],
    "rlm_adk/tools/repl_tool.py": ["rlm_adk_docs/core_loop.md"],
    "rlm_adk/repl/local_repl.py": ["rlm_adk_docs/core_loop.md"],
    "rlm_adk/repl/ast_rewriter.py": ["rlm_adk_docs/core_loop.md"],
    "rlm_adk/types.py": ["rlm_adk_docs/core_loop.md"],
    # agent.py maps to BOTH configuration and core_loop
    "rlm_adk/agent.py": [
        "rlm_adk_docs/configuration.md",
        "rlm_adk_docs/core_loop.md",
    ],
    # Dispatch & State
    "rlm_adk/dispatch.py": ["rlm_adk_docs/dispatch_and_state.md"],
    "rlm_adk/state.py": ["rlm_adk_docs/dispatch_and_state.md"],
    # Observability
    "rlm_adk/plugins/observability.py": ["rlm_adk_docs/observability.md"],
    "rlm_adk/plugins/sqlite_tracing.py": ["rlm_adk_docs/observability.md"],
    "rlm_adk/plugins/repl_tracing.py": ["rlm_adk_docs/observability.md"],
    "rlm_adk/plugins/langfuse_tracing.py": ["rlm_adk_docs/observability.md"],
    "rlm_adk/callbacks/worker.py": ["rlm_adk_docs/observability.md"],
    "rlm_adk/callbacks/worker_retry.py": ["rlm_adk_docs/observability.md"],
    "rlm_adk/callbacks/reasoning.py": ["rlm_adk_docs/observability.md"],
    "rlm_adk/repl/trace.py": ["rlm_adk_docs/observability.md"],
    "rlm_adk/plugins/debug_logging.py": ["rlm_adk_docs/observability.md"],
    # Testing
    "tests_rlm_adk/provider_fake/server.py": ["rlm_adk_docs/testing.md"],
    "tests_rlm_adk/provider_fake/contract_runner.py": ["rlm_adk_docs/testing.md"],
    "tests_rlm_adk/provider_fake/fixtures.py": ["rlm_adk_docs/testing.md"],
    "tests_rlm_adk/provider_fake/conftest.py": ["rlm_adk_docs/testing.md"],
    # Artifacts & Session
    "rlm_adk/artifacts.py": ["rlm_adk_docs/artifacts_and_session.md"],
    # Skills & Prompts
    "rlm_adk/utils/prompts.py": ["rlm_adk_docs/skills_and_prompts.md"],
}


def _find_project_root(start: Path) -> Path:
    """Walk up from *start* until we find pyproject.toml.

    Falls back to ``git rev-parse --show-toplevel`` when the walk fails
    (e.g. when invoked from a git worktree whose checkout doesn't include
    this script's parent directories).
    """
    cur = start.resolve()
    while cur != cur.parent:
        if (cur / "pyproject.toml").exists():
            return cur
        cur = cur.parent

    # Fallback: ask git for the repo root (handles worktree contexts).
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            candidate = Path(result.stdout.strip())
            if (candidate / "pyproject.toml").exists():
                return candidate
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    raise SystemExit("Could not locate project root (no pyproject.toml found)")


def _human_age(seconds: float) -> str:
    """Return a human-readable age string like '2m ago' or '3d ago'."""
    s = int(seconds)
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _branches_for(rel: str) -> list[str]:
    """Return branch doc paths for a relative source path.

    Checks the explicit ``FILE_TO_BRANCHES`` map first, then falls back to
    pattern-based rules (e.g. any file under ``rlm_adk/skills/`` maps to
    ``skills_and_prompts.md``).  Returns an empty list for unmapped files.

    Args:
        rel: Project-root-relative path to a Python source file
             (e.g. ``"rlm_adk/dispatch.py"``).

    Returns:
        A list of project-root-relative paths to the branch documentation
        files that cover *rel*, or an empty list if the file is not mapped.
    """
    if rel in FILE_TO_BRANCHES:
        return FILE_TO_BRANCHES[rel]

    # Any .py under rlm_adk/skills/ -> skills_and_prompts.md
    if rel.startswith("rlm_adk/skills/"):
        return ["rlm_adk_docs/skills_and_prompts.md"]

    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect stale branch documentation")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (default: auto-detect via pyproject.toml)",
    )
    args = parser.parse_args()

    # Read hook input from stdin (Claude Code passes JSON with stop_hook_active).
    # If stop_hook_active is true, the agent already attempted a doc update on a
    # previous stop — let it finish this time to avoid an infinite loop.
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        hook_input = {}

    if hook_input.get("stop_hook_active", False):
        return  # exit 0 — agent already tried, let it stop

    if args.project_root is not None:
        root = args.project_root.resolve()
    else:
        root = _find_project_root(Path(__file__))

    now = time.time()
    cutoff = now - RECENCY_WINDOW

    # Collect recently-modified source files from both trees.
    stale_pairs: list[tuple[str, float, str, float]] = []
    # (src_rel, src_age, doc_rel, doc_age)

    scan_patterns = ["rlm_adk/**/*.py", "tests_rlm_adk/**/*.py"]

    for pattern in scan_patterns:
        for py_path in root.glob(pattern):
            if not py_path.is_file():
                continue
            py_mtime = py_path.stat().st_mtime
            if py_mtime < cutoff:
                continue

            rel = str(py_path.relative_to(root))
            branches = _branches_for(rel)
            if not branches:
                continue

            for doc_rel in branches:
                doc_path = root / doc_rel
                if not doc_path.exists():
                    # Doc doesn't exist yet -- always flag.
                    stale_pairs.append((rel, now - py_mtime, doc_rel, float("inf")))
                    continue
                doc_mtime = doc_path.stat().st_mtime
                if py_mtime > doc_mtime:
                    stale_pairs.append(
                        (rel, now - py_mtime, doc_rel, now - doc_mtime)
                    )

    if not stale_pairs:
        return  # silent exit

    # Deduplicate and sort by source file name.
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, float, str, float]] = []
    for entry in sorted(stale_pairs, key=lambda e: e[0]):
        key = (entry[0], entry[2])
        if key not in seen:
            seen.add(key)
            unique.append(entry)

    lines = ["STALENESS_DETECTED"]
    lines.append(
        "The following source files were modified more recently "
        "than their branch documentation:"
    )
    lines.append("")
    for src_rel, src_age, doc_rel, doc_age in unique:
        doc_age_str = (
            "does not exist yet" if doc_age == float("inf") else _human_age(doc_age)
        )
        lines.append(
            f"  {src_rel} (modified {_human_age(src_age)}) "
            f"\u2192 {doc_rel} (last updated {doc_age_str})"
        )
    lines.append("")
    lines.append(
        'If you modified these files, please append your changes to the '
        '"## Recent Changes" section at the bottom of the affected branch doc(s). '
        "Use the format (date AND time are REQUIRED, plus your session_id):"
    )
    lines.append("")
    lines.append(
        "  - **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed"
        " `[session: <first-8-chars-of-session-id>]`"
    )
    lines.append("")
    lines.append(
        "IMPORTANT: Always include the current time (HH:MM in 24h format) alongside "
        "the date. Omitting the time makes it impossible to distinguish multiple "
        "updates on the same day. Include your Claude Code session_id (first 8 chars) "
        "so we can trace which session made the change."
    )
    lines.append("")
    lines.append(
        "If you did NOT modify these files, notify the user that branch "
        "documentation may be stale."
    )

    print("\n".join(lines))

    # Exit code 2 tells Claude Code to BLOCK the stop — the message above
    # becomes the agent's next instruction, giving it a chance to update docs.
    sys.exit(2)


if __name__ == "__main__":
    main()
