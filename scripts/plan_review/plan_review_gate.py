#!/usr/bin/env python3
"""Plan Review Gate — Stop hook script.

When Claude stops and a plan is pending review, this hook:
1. Launches Codex (or the test responder) to review the plan.
2. If VERDICT: REVISE — blocks the stop and injects the review as a systemMessage.
3. If VERDICT: APPROVED — clears bridge and allows stop.
4. Respects stop_hook_active and max_iterations safety caps.

Stdlib-only. Reads JSON from stdin (Claude Code hook protocol).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from bridge import (
    bridge_path,
    clear_bridge,
    log,
    read_bridge,
    update_bridge,
)
from codex_reviewer import parse_verdict, review_plan

SYSTEM_MESSAGE_TEMPLATE = """\
## Codex Plan Review (iteration {iteration})

{review_text}

---

**Action required:** Revise your plan at `{plan_path}` to address the feedback \
above, then stop again. The review loop will continue until the plan is approved \
or {max_iterations} iterations are reached."""


def process_stop_hook(hook_input: dict, bp: Path) -> dict | None:
    """Process a Stop hook event.

    Returns:
        dict with ``continue`` + ``systemMessage`` to block stop and inject review,
        or None to allow normal stop (exit 0).
    """
    # ── Feature gate ────────────────────────────────────────────────────
    if os.environ.get("PLAN_REVIEW_ENABLED", "0") != "1":
        return None

    # ── Infinite-loop breaker ───────────────────────────────────────────
    stop_hook_active = hook_input.get("stop_hook_active", False)
    if stop_hook_active:
        log("[GATE] stop_hook_active=true — allowing exit to prevent loop")
        return None

    # ── Read bridge state ───────────────────────────────────────────────
    state = read_bridge(bp)
    if state is None:
        return None

    if not state.get("plan_written", False):
        return None

    if state.get("review_approved", False):
        log("[GATE] Plan already approved — allowing stop")
        clear_bridge(bp)
        return None

    # ── Iteration cap ───────────────────────────────────────────────────
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 5)

    if iteration >= max_iterations:
        log(f"[GATE] Max iterations ({max_iterations}) reached — allowing stop")
        clear_bridge(bp)
        return None

    # ── Launch reviewer ─────────────────────────────────────────────────
    plan_path = state["plan_path"]
    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")
    previous_feedback = state.get("last_feedback", "")

    log(f"[GATE] Launching Codex review for {plan_path} (iteration {iteration})")

    try:
        review_text = review_plan(
            plan_path=plan_path,
            iteration=iteration,
            session_id=session_id,
            previous_feedback=previous_feedback,
        )
    except Exception as exc:
        log(f"[GATE] Codex review failed: {exc}")
        # Don't block Claude on reviewer failure — allow stop
        return None

    verdict = parse_verdict(review_text)
    log(f"[GATE] Verdict: {verdict}")

    # ── Update bridge ───────────────────────────────────────────────────
    if verdict == "APPROVED":
        update_bridge(bp, {
            "review_approved": True,
            "iteration": iteration + 1,
            "last_feedback": review_text,
            "last_verdict": verdict,
        })
        clear_bridge(bp)
        return None  # Allow stop

    # REVISE or UNKNOWN — block stop, inject feedback
    update_bridge(bp, {
        "iteration": iteration + 1,
        "last_feedback": review_text,
        "last_verdict": verdict,
    })

    system_msg = SYSTEM_MESSAGE_TEMPLATE.format(
        iteration=iteration + 1,
        review_text=review_text,
        plan_path=plan_path,
        max_iterations=max_iterations,
    )

    return {
        "decision": "block",
        "reason": review_text,
        "systemMessage": system_msg,
    }


def main() -> None:
    """Entry point for Stop hook."""
    try:
        hook_input = json.load(sys.stdin)
        bp = bridge_path()
        result = process_stop_hook(hook_input, bp)

        if result is not None:
            json.dump(result, sys.stdout)
            sys.exit(0)  # Exit 0 + decision:"block" JSON = block stop with parsed output

        sys.exit(0)
    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
