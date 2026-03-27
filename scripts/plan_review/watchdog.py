#!/usr/bin/env python3
"""Plan Review Watchdog — watches for new plan files and orchestrates review.

Operating Modes
===============

Mode A: Hook-driven (existing)
  The Claude Code hook chain handles review inline during a Claude session.
  - PostToolUse hook (plan_write_monitor.py) detects Write calls to ~/.claude/plans/
    and initialises the bridge file.
  - Stop hook (plan_review_gate.py) intercepts session stop, launches Codex review,
    and blocks the stop with a systemMessage containing review feedback.
  - Claude revises the plan in the same session; the loop repeats at the next stop.
  - Requires PLAN_REVIEW_ENABLED=1 in Claude Code settings.
  - No external process needed — everything runs inside Claude Code hooks.

Mode B: Watchdog-driven (this script)
  An external process watches the filesystem and orchestrates review independently.
  - Watches ~/.claude/plans/ for new .md files (inotifywait or polling fallback).
  - When a plan lands: copies to proposals/plans/, launches Codex review, and
    either resumes the Claude session (--resume) or spawns a headless Claude (-p)
    to deliver revision feedback.
  - Can run alongside or instead of the hook chain.
  - Launch via: scripts/plan_review/start_watchdog.sh
  - Useful for: lights-out operation, external CI/CD pipelines, or when hooks
    are not configured.

Pipeline
--------
  plan write -> watchdog detects -> copy to proposals/ -> Codex reviews
  -> REVISE: Claude resumes/spawns with feedback -> plan revised -> loop
  -> APPROVED: approval marker written, bridge cleared

Stdout tags: [WATCH], [PLAN], [REVIEW], [RESUME], [APPROVED]

Environment:
  PLAN_REVIEW_TEST_MODE=1     Deterministic test responses (no live Codex/Claude)
  PLAN_REVIEW_VERBOSE=1       Detailed stdout logging
  PLAN_REVIEW_MAX_ITERATIONS  Max review iterations (default 5)
  PLAN_REVIEW_SESSION_ID      Claude session ID for --resume (optional)
  PLAN_REVIEW_POLL_INTERVAL   Polling interval in seconds (default 2)

Stdlib-only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from bridge import (  # noqa: E402
    DEFAULT_MAX_ITERATIONS,
    PLANS_DIR,
    bridge_path,
    clear_bridge,
    new_bridge_state,
    update_bridge,
    write_bridge,
)
from codex_reviewer import parse_verdict, review_plan  # noqa: E402

# ── Constants ──────────────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
PROPOSALS_PLANS_DIR = PROJECT_DIR / "proposals" / "plans"
CLAUDE_BIN = shutil.which("claude") or "claude"
SESSION_DIR = Path.home() / ".claude" / "projects" / "-home-rawley-stanhope-dev-rlm-adk"


# ── Logging ────────────────────────────────────────────────────────────────

def _verbose() -> bool:
    return os.environ.get("PLAN_REVIEW_VERBOSE", "0") == "1"


def _test_mode() -> bool:
    return os.environ.get("PLAN_REVIEW_TEST_MODE", "0") == "1"


def tag(label: str, msg: str) -> None:
    """Print a tagged log line to stdout."""
    print(f"[{label}] {msg}", flush=True)


def debug(label: str, msg: str) -> None:
    """Print a tagged log line only when verbose or test mode."""
    if _verbose() or _test_mode():
        print(f"[{label}] {msg}", flush=True)


# ── File watching ──────────────────────────────────────────────────────────

def _inotifywait_available() -> bool:
    """Check if inotifywait is on PATH."""
    return shutil.which("inotifywait") is not None


def _watch_inotify(plans_dir: Path) -> str | None:
    """Block until a new .md file appears; return the filename or None on error."""
    try:
        proc = subprocess.run(
            [
                "inotifywait",
                "-q",                       # quiet
                "-e", "close_write",         # fires after write completes
                "--format", "%f",            # just the filename
                str(plans_dir),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        filename = proc.stdout.strip()
        if filename.endswith(".md"):
            return filename
        return None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _watch_poll(plans_dir: Path, known: set[str], interval: float) -> str | None:
    """Poll for new .md files. Returns the first new filename found, or None."""
    try:
        current = {f.name for f in plans_dir.iterdir() if f.suffix == ".md"}
    except OSError:
        return None
    new_files = current - known
    if new_files:
        # Return the most recently modified new file
        newest = max(new_files, key=lambda f: (plans_dir / f).stat().st_mtime)
        return newest
    return None


def _snapshot_plans(plans_dir: Path) -> set[str]:
    """Return a set of current .md filenames in the plans directory."""
    try:
        return {f.name for f in plans_dir.iterdir() if f.suffix == ".md"}
    except OSError:
        return set()


# ── Plan copy ──────────────────────────────────────────────────────────────

def copy_plan_to_proposals(plan_path: Path, version: int | None = None) -> Path:
    """Copy a plan file into proposals/plans/ and return the destination path.

    If *version* is given, the copy is named ``{stem}_v{version}.md``.
    """
    PROPOSALS_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    if version is not None:
        dest = PROPOSALS_PLANS_DIR / f"{plan_path.stem}_v{version}.md"
    else:
        dest = PROPOSALS_PLANS_DIR / plan_path.name
    shutil.copy2(plan_path, dest)
    tag("PLAN", f"Copied {plan_path.name} -> {dest}")
    return dest


def save_review(plan_path: Path, iteration: int, review_text: str) -> Path:
    """Persist a Codex review to proposals/plans/{stem}_review_{iteration}.md."""
    PROPOSALS_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    review_path = PROPOSALS_PLANS_DIR / f"{plan_path.stem}_review_{iteration}.md"
    review_path.write_text(
        f"# Codex Review — Iteration {iteration}\n"
        f"**Plan:** `{plan_path.name}`\n"
        f"**Timestamp:** {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n\n"
        f"---\n\n"
        f"{review_text}\n"
    )
    tag("REVIEW", f"Saved review -> {review_path}")
    return review_path


# ── Claude session interaction ─────────────────────────────────────────────

RESUME_PROMPT_TEMPLATE = """\
## Codex Plan Review Feedback (iteration {iteration})

Your plan at `{plan_path}` has been reviewed by Codex. Here is the feedback:

---
{review_text}
---

**Action required:** Revise your plan to address the feedback above. \
The file is at `{plan_path}`. After revising, save the updated plan."""


def _find_session_for_plan(plan_filename: str) -> str | None:
    """Try to find a Claude session ID associated with this plan.

    Checks PLAN_REVIEW_SESSION_ID env first, then bridge state.
    """
    sid = os.environ.get("PLAN_REVIEW_SESSION_ID")
    if sid:
        return sid
    return None


def resume_claude_session(
    session_id: str,
    plan_path: str,
    review_text: str,
    iteration: int,
) -> bool:
    """Resume a Claude Code session with review feedback via --resume -p.

    Returns True if the command succeeded, False otherwise.
    """
    prompt = RESUME_PROMPT_TEMPLATE.format(
        iteration=iteration,
        plan_path=plan_path,
        review_text=review_text,
    )

    cmd = [
        CLAUDE_BIN,
        "--resume", session_id,
        "--print",
        "--output-format", "json",
        "--permission-mode", "auto",
        prompt,
    ]

    tag("RESUME", f"Resuming session {session_id[:12]}... (iteration {iteration})")
    debug("RESUME", f"cmd: {' '.join(cmd[:6])}...")

    if _test_mode():
        tag("RESUME", f"[TEST] Would resume session {session_id} with review feedback")
        return True

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(PROJECT_DIR),
        )
        debug("RESUME", f"exit={proc.returncode} stdout_len={len(proc.stdout)}")
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as exc:
        tag("RESUME", f"Failed: {exc}")
        return False


HEADLESS_PROMPT_TEMPLATE = """\
## Plan Revision Request

A plan has been reviewed by Codex and needs revisions.

### Plan Location
`{plan_path}`

### Current Plan Content
{plan_content}

### Codex Review Feedback (iteration {iteration})
{review_text}

### Instructions
1. Read the plan carefully
2. Address every issue raised in the review
3. Write the revised plan back to `{plan_path}`
4. Ensure the plan is complete, addresses edge cases, and is ready for implementation"""


def spawn_headless_claude(
    plan_path: str,
    review_text: str,
    iteration: int,
) -> bool:
    """Spawn a fresh headless Claude to revise the plan.

    Returns True if the command succeeded, False otherwise.
    """
    try:
        plan_content = Path(plan_path).read_text()
    except OSError:
        plan_content = "(could not read plan)"

    prompt = HEADLESS_PROMPT_TEMPLATE.format(
        plan_path=plan_path,
        plan_content=plan_content,
        review_text=review_text,
        iteration=iteration,
    )

    cmd = [
        CLAUDE_BIN,
        "-p",
        "--output-format", "json",
        "--permission-mode", "auto",
        prompt,
    ]

    tag("RESUME", f"Spawning headless Claude for revision (iteration {iteration})")

    if _test_mode():
        tag("RESUME", "[TEST] Would spawn headless Claude with review feedback")
        return True

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(PROJECT_DIR),
        )
        debug("RESUME", f"exit={proc.returncode} stdout_len={len(proc.stdout)}")
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as exc:
        tag("RESUME", f"Failed: {exc}")
        return False


def send_feedback_to_claude(
    plan_path: str,
    review_text: str,
    iteration: int,
    session_id: str | None,
) -> bool:
    """Send review feedback to Claude via resume or headless spawn.

    Tries --resume first if session_id is available, falls back to headless.
    """
    if session_id:
        ok = resume_claude_session(session_id, plan_path, review_text, iteration)
        if ok:
            return True
        tag("RESUME", "Session resume failed, falling back to headless")

    return spawn_headless_claude(plan_path, review_text, iteration)


# ── Review loop ────────────────────────────────────────────────────────────

def run_review_loop(
    plan_path: Path,
    session_id: str | None = None,
    max_iterations: int | None = None,
) -> bool:
    """Run the review loop for a single plan file.

    Returns True if plan was approved, False if max iterations hit.
    """
    if max_iterations is None:
        max_iterations = int(
            os.environ.get("PLAN_REVIEW_MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS)
        )

    loop_session_id = session_id or os.environ.get("CLAUDE_SESSION_ID", "watchdog")
    bp = bridge_path(loop_session_id)
    state = new_bridge_state(str(plan_path))
    state["max_iterations"] = max_iterations
    write_bridge(bp, state)

    previous_feedback = ""

    # Save initial plan as v0
    try:
        copy_plan_to_proposals(plan_path, version=0)
    except OSError as exc:
        debug("PLAN", f"Failed to save v0: {exc}")

    for iteration in range(max_iterations):
        tag("REVIEW", f"Iteration {iteration + 1}/{max_iterations} for {plan_path.name}")

        # ── Launch Codex review ──────────────────────────────────────────
        try:
            review_text = review_plan(
                plan_path=str(plan_path),
                iteration=iteration,
                session_id=loop_session_id,
                previous_feedback=previous_feedback,
            )
        except Exception as exc:
            tag("REVIEW", f"Codex review failed: {exc}")
            break

        verdict = parse_verdict(review_text)
        tag("REVIEW", f"Verdict: {verdict}")
        debug("REVIEW", f"Review text:\n{review_text[:300]}...")

        # ── Persist review to proposals/plans/ ────────────────────────────
        try:
            save_review(plan_path, iteration + 1, review_text)
        except OSError as exc:
            debug("REVIEW", f"Failed to save review: {exc}")

        # ── Update bridge state ──────────────────────────────────────────
        update_bridge(bp, {
            "iteration": iteration + 1,
            "last_feedback": review_text,
            "last_verdict": verdict,
        })

        # ── Handle verdict ───────────────────────────────────────────────
        if verdict == "APPROVED":
            tag("APPROVED", f"Plan {plan_path.name} approved after {iteration + 1} iteration(s)")
            update_bridge(bp, {"review_approved": True})

            # Write approval marker
            marker_path = plan_path.with_suffix(".approved")
            marker_path.write_text(
                json.dumps({
                    "plan": str(plan_path),
                    "iterations": iteration + 1,
                    "approved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }, indent=2)
            )
            tag("APPROVED", f"Marker written: {marker_path}")
            clear_bridge(bp)
            return True

        # REVISE — send feedback to Claude
        previous_feedback = review_text

        plan_session_id = _find_session_for_plan(plan_path.name)
        ok = send_feedback_to_claude(
            plan_path=str(plan_path),
            review_text=review_text,
            iteration=iteration + 1,
            session_id=plan_session_id,
        )

        if not ok:
            tag("RESUME", "Could not deliver feedback to Claude — continuing review loop")

        # Wait for Claude to revise the plan
        if not _test_mode():
            debug("WATCH", "Waiting for plan revision...")
            _wait_for_plan_update(plan_path, timeout=300)
        else:
            debug("WATCH", "[TEST] Skipping wait for plan revision")

        # ── Save revised plan as v{n} ─────────────────────────────────────
        try:
            copy_plan_to_proposals(plan_path, version=iteration + 1)
        except OSError as exc:
            debug("PLAN", f"Failed to save v{iteration + 1}: {exc}")

    # Max iterations exhausted
    tag("REVIEW", f"Max iterations ({max_iterations}) reached for {plan_path.name}")
    clear_bridge(bp)
    return False


def _wait_for_plan_update(plan_path: Path, timeout: float = 300) -> bool:
    """Wait for the plan file to be modified. Returns True if modified."""
    try:
        original_mtime = plan_path.stat().st_mtime
    except OSError:
        return False

    deadline = time.monotonic() + timeout
    poll_interval = float(os.environ.get("PLAN_REVIEW_POLL_INTERVAL", "2"))

    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        try:
            if plan_path.stat().st_mtime > original_mtime:
                debug("WATCH", f"Plan {plan_path.name} updated")
                return True
        except OSError:
            continue

    debug("WATCH", f"Timed out waiting for {plan_path.name} update")
    return False


# ── Main watch loop ────────────────────────────────────────────────────────

def watch(plans_dir: Path | None = None, one_shot: bool = False) -> None:
    """Main watch loop. Blocks until terminated.

    Args:
        plans_dir: Directory to watch (default ~/.claude/plans/).
        one_shot: If True, process one plan and exit (useful for testing).
    """
    if plans_dir is None:
        plans_dir = PLANS_DIR

    plans_dir.mkdir(parents=True, exist_ok=True)
    use_inotify = _inotifywait_available() and not _test_mode()

    tag("WATCH", f"Watching {plans_dir} for new plan files")
    if use_inotify:
        debug("WATCH", "Using inotifywait for file detection")
    else:
        debug("WATCH", "Using polling fallback for file detection")

    known_files = _snapshot_plans(plans_dir)
    debug("WATCH", f"Known plans: {len(known_files)}")

    poll_interval = float(os.environ.get("PLAN_REVIEW_POLL_INTERVAL", "2"))

    while True:
        new_filename: str | None = None

        if use_inotify:
            new_filename = _watch_inotify(plans_dir)
            # Verify it's actually new (inotifywait fires for overwrites too)
            if new_filename and new_filename in known_files:
                debug("WATCH", f"Ignoring known file: {new_filename}")
                new_filename = None
        else:
            new_filename = _watch_poll(plans_dir, known_files, poll_interval)
            if new_filename is None:
                time.sleep(poll_interval)
                continue

        if new_filename is None:
            continue

        plan_path = plans_dir / new_filename
        if not plan_path.exists():
            continue

        known_files.add(new_filename)

        tag("PLAN", f"New plan detected: {new_filename}")

        # Run review loop (saves v0 + reviews + versioned revisions to proposals/plans/)
        session_id = _find_session_for_plan(new_filename)
        approved = run_review_loop(
            plan_path=plan_path,
            session_id=session_id,
        )

        if approved:
            tag("APPROVED", f"Plan {new_filename} review complete — approved")
        else:
            tag("REVIEW", f"Plan {new_filename} review complete — not approved (max iterations)")

        if one_shot:
            return


# ── CLI entry point ────────────────────────────────────────────────────────

def main() -> None:
    """Entry point for standalone execution."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Plan Review Watchdog — watches for new plan files and orchestrates review",
    )
    parser.add_argument(
        "--plans-dir",
        type=Path,
        default=None,
        help=f"Directory to watch (default: {PLANS_DIR})",
    )
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="Process one plan and exit",
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=None,
        help="Skip watching; directly review the given plan file",
    )
    args = parser.parse_args()

    if args.review:
        # Direct review mode — skip watching, just run the review loop
        plan = args.review.resolve()
        if not plan.exists():
            print(f"Error: Plan file not found: {plan}", file=sys.stderr)
            sys.exit(1)

        tag("PLAN", f"Direct review: {plan.name}")
        approved = run_review_loop(plan_path=plan)
        sys.exit(0 if approved else 1)

    try:
        watch(plans_dir=args.plans_dir, one_shot=args.one_shot)
    except KeyboardInterrupt:
        tag("WATCH", "Interrupted — shutting down")
        sys.exit(0)


if __name__ == "__main__":
    main()
