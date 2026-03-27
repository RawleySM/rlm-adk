"""Plan Review Bridge — shared state between PostToolUse and Stop hooks.

Bridge file lives at /tmp/plan_review_{session_id}.json.
Stdlib-only.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import time
from pathlib import Path

# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_MAX_ITERATIONS = 5
PLANS_DIR = Path.home() / ".claude" / "plans"


def bridge_path(session_id: str | None = None) -> Path:
    """Return the bridge file path for the given session."""
    if session_id is None:
        session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")
    return Path(f"/tmp/plan_review_{session_id}.json")


def read_bridge(path: Path) -> dict | None:
    """Read and parse bridge JSON. Returns None if missing/corrupt."""
    try:
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_bridge(path: Path, data: dict) -> None:
    """Atomically write bridge JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.rename(path)


def update_bridge(path: Path, updates: dict) -> dict:
    """Merge *updates* into the existing bridge file and return the result.

    Uses fcntl.flock to prevent concurrent read-modify-write races.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        existing = read_bridge(path) or {}
        existing.update(updates)
        write_bridge(path, existing)
    return existing


def clear_bridge(path: Path) -> None:
    """Remove the bridge file."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def new_bridge_state(plan_path: str) -> dict:
    """Create a fresh bridge state for a newly-written plan."""
    max_iter = int(os.environ.get("PLAN_REVIEW_MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS))
    return {
        "plan_path": plan_path,
        "plan_written": True,
        "review_approved": False,
        "iteration": 0,
        "max_iterations": max_iter,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def is_plan_file(file_path: str) -> bool:
    """Return True if *file_path* is inside the plans directory."""
    try:
        return Path(file_path).resolve().is_relative_to(PLANS_DIR.resolve())
    except (ValueError, OSError):
        return False


def log(msg: str) -> None:
    """Print a log line to stderr (visible to the supervising agent in test mode)."""
    verbose = os.environ.get("PLAN_REVIEW_VERBOSE", "0") == "1"
    test_mode = os.environ.get("PLAN_REVIEW_TEST_MODE", "0") == "1"
    if verbose or test_mode:
        print(msg, file=sys.stderr, flush=True)
