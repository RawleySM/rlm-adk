#!/usr/bin/env python3
"""E2E test for the plan-review watchdog.

Exercises the full watchdog loop in PLAN_REVIEW_TEST_MODE=1:
  1. Creates temp directory structures (never touches ~/.claude/plans/)
  2. Writes a canned plan file
  3. Calls the watchdog processing functions directly (no inotifywait needed)
  4. Verifies plan copy, bridge state, iteration count, verdict, approval marker
  5. Prints tagged [WATCH]/[PLAN]/[REVIEW]/[RESUME]/[APPROVED] lines to stdout

Usage:
    python scripts/plan_review/test_watchdog_e2e.py

    # Verbose
    PLAN_REVIEW_VERBOSE=1 python scripts/plan_review/test_watchdog_e2e.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

# ── Bootstrap imports ───────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import bridge as bridge_mod  # noqa: E402
import watchdog as watchdog_mod  # noqa: E402
from bridge import clear_bridge, read_bridge  # noqa: E402
from codex_reviewer import TEST_RESPONSES  # noqa: E402
from watchdog import (  # noqa: E402
    copy_plan_to_proposals,
    run_review_loop,
    watch,
)

# ── Helpers ─────────────────────────────────────────────────────────────────

SEPARATOR = "=" * 72


def emit(tag: str, msg: str) -> None:
    """Print a tagged line to stdout."""
    print(f"[{tag:>8s}] {msg}", flush=True)


CANNED_PLAN = """\
# Plan: Watchdog Widget Pipeline

## Objective
Build a self-monitoring pipeline that detects plan files and runs review loops.

## Steps
1. Watch for new .md files in the plans directory
2. Copy each plan to proposals/plans/
3. Launch Codex review and iterate until approved
4. Write an approval marker when complete

## Edge Cases
- Handle missing directories gracefully
- Respect max iteration caps
- Atomic bridge file writes
"""


class _PatchContext:
    """Context manager that patches module-level globals for temp dirs."""

    def __init__(self, plans_dir: Path, proposals_dir: Path):
        self.plans_dir = plans_dir
        self.proposals_dir = proposals_dir
        self._originals: dict[str, object] = {}

    def __enter__(self) -> "_PatchContext":
        # Save originals
        self._originals["bridge_PLANS_DIR"] = bridge_mod.PLANS_DIR
        self._originals["watchdog_PLANS_DIR"] = watchdog_mod.PLANS_DIR
        self._originals["watchdog_PROPOSALS"] = watchdog_mod.PROPOSALS_PLANS_DIR
        # Patch
        bridge_mod.PLANS_DIR = self.plans_dir
        watchdog_mod.PLANS_DIR = self.plans_dir
        watchdog_mod.PROPOSALS_PLANS_DIR = self.proposals_dir
        return self

    def __exit__(self, *exc: object) -> None:
        bridge_mod.PLANS_DIR = self._originals["bridge_PLANS_DIR"]
        watchdog_mod.PLANS_DIR = self._originals["watchdog_PLANS_DIR"]
        watchdog_mod.PROPOSALS_PLANS_DIR = self._originals["watchdog_PROPOSALS"]


# ── Test: run_review_loop directly ──────────────────────────────────────────

def test_review_loop() -> list[str]:
    """Exercise run_review_loop() with deterministic test responses.

    Returns a list of error messages (empty = pass).
    """
    errors: list[str] = []

    emit("TEST", "--- test_review_loop: start ---")

    with tempfile.TemporaryDirectory(prefix="watchdog_test_rl_") as tmpdir:
        tmp = Path(tmpdir)
        plans_dir = tmp / "plans"
        plans_dir.mkdir()
        proposals_dir = tmp / "proposals" / "plans"

        with _PatchContext(plans_dir, proposals_dir):
            plan_path = plans_dir / "test_review_loop.md"
            plan_path.write_text(CANNED_PLAN)

            # Capture stdout for tag verification
            captured_lines: list[str] = []
            original_tag = watchdog_mod.tag
            def _capture_tag(label: str, msg: str) -> None:
                line = f"[{label}] {msg}"
                captured_lines.append(line)
                original_tag(label, msg)

            watchdog_mod.tag = _capture_tag
            try:
                approved = run_review_loop(
                    plan_path=plan_path,
                    session_id="test-review-loop",
                    max_iterations=5,
                )
            finally:
                watchdog_mod.tag = original_tag

            # 1. Should be approved
            if not approved:
                errors.append("run_review_loop returned False (expected True)")

            # 2. Should have taken exactly len(TEST_RESPONSES) iterations
            #    (2 REVISE + 1 APPROVED = 3)
            review_lines = [l for l in captured_lines if "[REVIEW]" in l and "Iteration" in l]
            expected_iters = len(TEST_RESPONSES)
            if len(review_lines) != expected_iters:
                errors.append(
                    f"Expected {expected_iters} review iterations, got {len(review_lines)}"
                )

            # 3. Approval marker should exist
            marker = plan_path.with_suffix(".approved")
            if not marker.exists():
                errors.append("Approval marker file not created")
            else:
                marker_data = json.loads(marker.read_text())
                if marker_data.get("iterations") != expected_iters:
                    errors.append(
                        f"Marker iterations={marker_data.get('iterations')}, "
                        f"expected {expected_iters}"
                    )
                emit("APPROVED", f"Marker: {json.dumps(marker_data)}")

            # 4. Bridge should be cleared
            from bridge import bridge_path
            bp = bridge_path("test-review-loop")
            if read_bridge(bp) is not None:
                errors.append("Bridge not cleared after approval")

            # 5. Verify tagged lines appeared
            all_output = "\n".join(captured_lines)
            required_tags = ["[REVIEW]", "[APPROVED]", "[RESUME]"]
            for rtag in required_tags:
                if rtag not in all_output:
                    errors.append(f"Missing required tag {rtag} in output")

    if errors:
        for e in errors:
            emit("FAIL", e)
    else:
        emit("PASS", "test_review_loop: all assertions passed")

    return errors


# ── Test: copy_plan_to_proposals ────────────────────────────────────────────

def test_plan_copy() -> list[str]:
    """Verify plan file is copied to proposals/plans/."""
    errors: list[str] = []

    emit("TEST", "--- test_plan_copy: start ---")

    with tempfile.TemporaryDirectory(prefix="watchdog_test_cp_") as tmpdir:
        tmp = Path(tmpdir)
        plans_dir = tmp / "plans"
        plans_dir.mkdir()
        proposals_dir = tmp / "proposals" / "plans"

        with _PatchContext(plans_dir, proposals_dir):
            plan_path = plans_dir / "test_copy.md"
            plan_path.write_text(CANNED_PLAN)

            dest = copy_plan_to_proposals(plan_path)

            # 1. Destination should exist
            if not dest.exists():
                errors.append("Copied plan file does not exist at destination")

            # 2. Content should match
            if dest.exists() and dest.read_text() != CANNED_PLAN:
                errors.append("Copied plan content does not match original")

            # 3. Should be in proposals_dir
            if dest.exists() and dest.parent != proposals_dir:
                errors.append(f"Dest parent {dest.parent} != expected {proposals_dir}")

            # 4. proposals_dir should have been created
            if not proposals_dir.exists():
                errors.append("proposals/plans/ directory not created")

    if errors:
        for e in errors:
            emit("FAIL", e)
    else:
        emit("PASS", "test_plan_copy: all assertions passed")

    return errors


# ── Test: watch() one_shot with file drop via thread ────────────────────────

def test_watch_one_shot() -> list[str]:
    """Exercise watch(one_shot=True) with a plan file dropped via a background thread.

    This tests the full pipeline: file detection -> copy -> review loop -> approval.
    """
    errors: list[str] = []

    emit("TEST", "--- test_watch_one_shot: start ---")

    with tempfile.TemporaryDirectory(prefix="watchdog_test_ws_") as tmpdir:
        tmp = Path(tmpdir)
        plans_dir = tmp / "plans"
        plans_dir.mkdir()
        proposals_dir = tmp / "proposals" / "plans"

        with _PatchContext(plans_dir, proposals_dir):
            plan_filename = "test_watch_one_shot.md"

            # Capture tagged output
            captured_lines: list[str] = []
            original_tag = watchdog_mod.tag
            def _capture_tag(label: str, msg: str) -> None:
                line = f"[{label}] {msg}"
                captured_lines.append(line)
                original_tag(label, msg)

            watchdog_mod.tag = _capture_tag

            # Drop a plan file after a short delay (watch needs to start first)
            def _drop_plan():
                time.sleep(0.3)  # let watch() start polling
                plan_path = plans_dir / plan_filename
                plan_path.write_text(CANNED_PLAN)

            dropper = threading.Thread(target=_drop_plan, daemon=True)
            dropper.start()

            try:
                watch(plans_dir=plans_dir, one_shot=True)
            finally:
                watchdog_mod.tag = original_tag
                dropper.join(timeout=5)

            # 1. Plan should have been copied to proposals/plans/
            copied = proposals_dir / plan_filename
            if not copied.exists():
                errors.append("Plan not copied to proposals/plans/")
            elif copied.read_text() != CANNED_PLAN:
                errors.append("Copied plan content mismatch")

            # 2. Approval marker should exist
            marker = plans_dir / plan_filename.replace(".md", ".approved")
            if not marker.exists():
                errors.append("Approval marker not written after watch loop")
            else:
                marker_data = json.loads(marker.read_text())
                if marker_data.get("iterations") != len(TEST_RESPONSES):
                    errors.append(
                        f"Watch loop iterations={marker_data.get('iterations')}, "
                        f"expected {len(TEST_RESPONSES)}"
                    )

            # 3. All required tags should have appeared
            all_output = "\n".join(captured_lines)
            required_tags = ["[WATCH]", "[PLAN]", "[REVIEW]", "[RESUME]", "[APPROVED]"]
            for rtag in required_tags:
                if rtag not in all_output:
                    errors.append(f"Missing required tag {rtag} in watch output")

            # 4. Bridge should be cleared
            # (bridge was created internally with session from _find_session_for_plan)
            # Just verify no stale bridge files in /tmp for our test prefix
            emit("TEST", f"Captured {len(captured_lines)} tagged lines")

    if errors:
        for e in errors:
            emit("FAIL", e)
    else:
        emit("PASS", "test_watch_one_shot: all assertions passed")

    return errors


# ── Test: bridge state progression ──────────────────────────────────────────

def test_bridge_state_progression() -> list[str]:
    """Verify bridge state is created, updated through iterations, and cleared."""
    errors: list[str] = []

    emit("TEST", "--- test_bridge_state_progression: start ---")

    with tempfile.TemporaryDirectory(prefix="watchdog_test_br_") as tmpdir:
        tmp = Path(tmpdir)
        plans_dir = tmp / "plans"
        plans_dir.mkdir()
        proposals_dir = tmp / "proposals" / "plans"

        with _PatchContext(plans_dir, proposals_dir):
            plan_path = plans_dir / "test_bridge.md"
            plan_path.write_text(CANNED_PLAN)

            session_id = "test-bridge-state"

            # Intercept bridge writes to track state progression
            states_seen: list[dict] = []
            original_update = watchdog_mod.update_bridge

            def _tracking_update(bp, updates):
                result = original_update(bp, updates)
                states_seen.append(dict(result))  # snapshot
                return result

            watchdog_mod.update_bridge = _tracking_update
            try:
                run_review_loop(
                    plan_path=plan_path,
                    session_id=session_id,
                    max_iterations=5,
                )
            finally:
                watchdog_mod.update_bridge = original_update

            # We expect 2 updates per iteration (iteration update + verdict-specific)
            # For 3 iterations: 2 REVISE updates + 2 APPROVED updates = varied count
            # But let's check the logical progression

            if len(states_seen) == 0:
                errors.append("No bridge state updates captured")
            else:
                # First state should have iteration=1
                first = states_seen[0]
                if first.get("iteration") != 1:
                    errors.append(f"First state iteration={first.get('iteration')}, expected 1")

                # Last state should have review_approved=True
                last = states_seen[-1]
                if not last.get("review_approved"):
                    errors.append("Final state missing review_approved=True")

                # Iteration should have progressed
                iterations = [s.get("iteration", 0) for s in states_seen]
                if max(iterations) != len(TEST_RESPONSES):
                    errors.append(
                        f"Max iteration={max(iterations)}, "
                        f"expected {len(TEST_RESPONSES)}"
                    )

                emit("TEST", f"Bridge states captured: {len(states_seen)}")
                for i, s in enumerate(states_seen):
                    emit("TEST", f"  state[{i}]: iter={s.get('iteration')} "
                         f"verdict={s.get('last_verdict', '-')} "
                         f"approved={s.get('review_approved', False)}")

            # Bridge should be fully cleared now
            from bridge import bridge_path
            bp = bridge_path(session_id)
            if read_bridge(bp) is not None:
                errors.append("Bridge not cleared after review loop")

    if errors:
        for e in errors:
            emit("FAIL", e)
    else:
        emit("PASS", "test_bridge_state_progression: all assertions passed")

    return errors


# ── Run all tests ───────────────────────────────────────────────────────────

def run_all() -> bool:
    """Run all E2E tests. Returns True if all pass."""
    all_errors: list[str] = []

    all_errors.extend(test_plan_copy())
    print()
    all_errors.extend(test_review_loop())
    print()
    all_errors.extend(test_bridge_state_progression())
    print()
    all_errors.extend(test_watch_one_shot())

    return len(all_errors) == 0


def main() -> None:
    # Force test mode and short poll interval
    os.environ["PLAN_REVIEW_TEST_MODE"] = "1"
    os.environ["PLAN_REVIEW_POLL_INTERVAL"] = "0.1"

    print()
    print(SEPARATOR)
    print("  Watchdog E2E Test [DETERMINISTIC / TEST_MODE=1]")
    print(SEPARATOR)
    print()

    success = run_all()

    print()
    print(SEPARATOR)
    if success:
        print("  Result: ALL PASS")
    else:
        print("  Result: FAILED")
    print(SEPARATOR)
    print()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
