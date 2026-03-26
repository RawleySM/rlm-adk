#!/usr/bin/env python3
"""E2E test for the plan-review hook chain.

Exercises the full PostToolUse → Stop → Codex review → inject → revise loop
using the deterministic test-mode responder.  All state transitions are printed
to stdout with [PING]/[PONG]/[STOP]/[DONE] markers so a supervising agent can
watch the process converge.

Usage:
    python scripts/plan_review/test_plan_review_e2e.py

    # Verbose — also prints bridge state at each step
    PLAN_REVIEW_VERBOSE=1 python scripts/plan_review/test_plan_review_e2e.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# ── Bootstrap imports ───────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from bridge import clear_bridge, read_bridge, write_bridge  # noqa: E402
from codex_reviewer import TEST_RESPONSES, parse_verdict  # noqa: E402
from plan_write_monitor import process_hook_input as monitor_hook  # noqa: E402
from plan_review_gate import process_stop_hook as gate_hook  # noqa: E402

# ── Helpers ─────────────────────────────────────────────────────────────────

SEPARATOR = "─" * 72


def emit(tag: str, msg: str) -> None:
    """Print a tagged line to stdout."""
    print(f"[{tag:>4s}] {msg}", flush=True)


def emit_bridge(bp: Path) -> None:
    """Print bridge state if PLAN_REVIEW_VERBOSE is set."""
    if os.environ.get("PLAN_REVIEW_VERBOSE", "0") != "1":
        return
    state = read_bridge(bp)
    print(f"       bridge = {json.dumps(state, indent=2)}", flush=True)


def make_plan_content(revision: int | None = None, feedback: str = "") -> str:
    """Generate canned plan content."""
    base = (
        "# Plan: Implement Widget Factory\n\n"
        "## Objective\n"
        "Build a widget factory with configurable output types.\n\n"
        "## Steps\n"
        "1. Define WidgetConfig schema\n"
        "2. Implement factory function\n"
        "3. Add CLI entry point\n"
    )
    if revision is not None:
        base += f"\n## Revision {revision}\n"
        base += f"Addressed: {feedback}\n"
    return base


# ── Test harness ────────────────────────────────────────────────────────────

def run_e2e() -> bool:
    """Run the full ping-pong e2e test.  Returns True on success."""

    # Respect caller's PLAN_REVIEW_TEST_MODE; default to test mode if unset
    os.environ.setdefault("PLAN_REVIEW_TEST_MODE", "1")
    os.environ["PLAN_REVIEW_ENABLED"] = "1"
    os.environ["PLAN_REVIEW_MAX_ITERATIONS"] = "5"

    live_mode = os.environ.get("PLAN_REVIEW_TEST_MODE", "1") == "0"

    # Use a temp directory for the plan file so we don't pollute ~/.claude/plans
    with tempfile.TemporaryDirectory(prefix="plan_review_test_") as tmpdir:
        plan_dir = Path(tmpdir) / ".claude" / "plans"
        plan_dir.mkdir(parents=True)

        # Patch bridge.PLANS_DIR and bridge.is_plan_file for the test
        import bridge as bridge_mod
        original_plans_dir = bridge_mod.PLANS_DIR
        bridge_mod.PLANS_DIR = plan_dir

        ts = int(time.time())
        plan_path = plan_dir / f"test_ping_{ts}.md"
        bp = Path(tmpdir) / f"plan_review_test_{ts}.json"

        try:
            # ── Initial plan write ──────────────────────────────────────
            plan_content = make_plan_content()
            plan_path.write_text(plan_content)

            print(SEPARATOR)
            emit("PING", f"Claude writes plan: {plan_path.name} (iteration 0)")
            print(SEPARATOR)

            # Simulate PostToolUse hook
            hook_input = {
                "tool_name": "Write",
                "tool_input": {"file_path": str(plan_path)},
            }
            monitor_hook(hook_input, bp)
            emit("HOOK", "PostToolUse: bridge updated")
            emit_bridge(bp)

            # ── Review loop ─────────────────────────────────────────────
            max_expected = len(TEST_RESPONSES)
            actual_iterations = 0

            for i in range(max_expected + 2):  # +2 safety margin
                print(SEPARATOR)
                emit("STOP", f"Stop hook fired (iteration {i})")

                stop_input = {"stop_hook_active": False}
                result = gate_hook(stop_input, bp)

                state = read_bridge(bp)

                if result is None:
                    # Gate allowed stop — either approved or cap reached
                    verdict_str = (state or {}).get("last_verdict", "APPROVED")
                    emit("DONE", f"Stop allowed — verdict: {verdict_str}")
                    emit_bridge(bp)
                    actual_iterations = i + 1  # count the approval round
                    break

                # Gate blocked stop — extract review
                sys_msg = result.get("systemMessage", "")
                # Find the verdict in the system message
                verdict = "REVISE"
                if "VERDICT: APPROVED" in sys_msg:
                    verdict = "APPROVED"

                # Extract just the feedback portion for display
                review_lines = []
                for line in sys_msg.splitlines():
                    if line.startswith("VERDICT:") or line.startswith("**Action required"):
                        continue
                    if line.strip() and not line.startswith("##") and not line.startswith("---"):
                        review_lines.append(line.strip())
                feedback_summary = " ".join(review_lines[:2])[:120]

                emit("PONG", f"Codex review (iteration {i + 1}): VERDICT: {verdict}")
                emit("    ", f"Feedback: {feedback_summary}...")
                emit("    ", 'Stop hook returns {continue: true, systemMessage: "..."}')
                emit_bridge(bp)

                # Simulate Claude revising the plan (append, not overwrite)
                print(SEPARATOR)
                existing_plan = plan_path.read_text()
                revision_section = (
                    f"\n## Revision {i + 1}\n"
                    f"Addressed: {feedback_summary[:80]}\n"
                )
                plan_path.write_text(existing_plan + revision_section)
                emit("PING", f"Claude revises plan (iteration {i + 1})")

                actual_iterations = i + 1
            else:
                emit("FAIL", "Loop did not converge within safety margin")
                return False

            # ── Assertions ──────────────────────────────────────────────
            print(SEPARATOR)
            print()
            errors = []

            if not live_mode:
                # Deterministic: exact iteration count must match canned responses
                if actual_iterations != len(TEST_RESPONSES):
                    errors.append(
                        f"Expected {len(TEST_RESPONSES)} iterations, got {actual_iterations}"
                    )
            else:
                # Live: just verify it converged within the cap
                emit("INFO", f"Live mode: converged in {actual_iterations} iteration(s)")

            # Bridge should be cleared after approval
            final_state = read_bridge(bp)
            if final_state is not None:
                errors.append(f"Bridge not cleared after approval: {final_state}")

            # Plan file should have revision sections (at least 1 if >1 iteration)
            final_plan = plan_path.read_text()
            revision_count = final_plan.count("## Revision")
            if not live_mode:
                expected_revisions = len(TEST_RESPONSES) - 1
                if revision_count < expected_revisions:
                    errors.append(
                        f"Expected >= {expected_revisions} revision sections, "
                        f"found {revision_count}"
                    )
            else:
                emit("INFO", f"Live mode: plan has {revision_count} revision section(s)")

            if errors:
                for err in errors:
                    emit("FAIL", err)
                return False

            emit("PASS", f"Plan approved after {actual_iterations} iterations")
            emit("PASS", f"Bridge cleared: {final_state is None}")
            emit("PASS", f"Plan has {revision_count} revision section(s)")
            print()
            print(f"Final plan: {plan_path}")
            return True

        finally:
            # Restore original PLANS_DIR
            bridge_mod.PLANS_DIR = original_plans_dir
            # Clean up bridge file
            clear_bridge(bp)


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    live = os.environ.get("PLAN_REVIEW_TEST_MODE", "1") == "0"
    mode_label = "LIVE (codex exec)" if live else "DETERMINISTIC (ping/pong)"
    print()
    print("=" * 72)
    print(f"  Plan-Review Hook Chain — E2E Test [{mode_label}]")
    print("=" * 72)
    print()

    success = run_e2e()

    print()
    if success:
        print("Result: ALL PASS")
        sys.exit(0)
    else:
        print("Result: FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
