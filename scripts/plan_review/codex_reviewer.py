"""Codex Reviewer — runs codex exec to review a plan file.

In test mode (PLAN_REVIEW_TEST_MODE=1), substitutes a deterministic
ping/pong responder instead of calling the live codex binary.

Stdlib-only.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

CODEX_BIN = os.environ.get("CODEX_BIN", str(Path.home() / ".npm-global/bin/codex"))
PROJECT_DIR = os.environ.get(
    "CODEX_REPO_DIR",
    str(Path(__file__).resolve().parent.parent.parent),
)
MODEL = os.environ.get("CODEX_MODEL", "gpt-5.4")

REVIEW_PROMPT_TEMPLATE = """\
You are a plan reviewer. Read the plan below and provide a concise review.

## Rules
- If the plan is complete, addresses edge cases, and is ready for implementation,
  end your review with exactly: VERDICT: APPROVED
- If the plan needs revisions, list the specific issues and end with exactly:
  VERDICT: REVISE

## Plan
{plan_content}

## Previous Review Feedback (if any)
{previous_feedback}
"""

# ── Deterministic test responder ────────────────────────────────────────────

TEST_RESPONSES: list[dict[str, str]] = [
    {
        "feedback": "The plan lacks error handling for edge cases. "
                    "What happens when the bridge file is corrupted mid-write? "
                    "Add atomic write semantics and recovery logic.",
        "verdict": "VERDICT: REVISE",
    },
    {
        "feedback": "Error handling addressed. However, there are no tests for "
                    "the timeout path when Codex takes longer than the hook timeout. "
                    "Add a test case for timeout behavior.",
        "verdict": "VERDICT: REVISE",
    },
    {
        "feedback": "All issues have been addressed. The plan covers error handling, "
                    "timeout behavior, and the full hook chain. Implementation looks solid.",
        "verdict": "VERDICT: APPROVED",
    },
]


def _test_review(iteration: int) -> str:
    """Return a deterministic review for the given iteration (0-indexed)."""
    idx = min(iteration, len(TEST_RESPONSES) - 1)
    resp = TEST_RESPONSES[idx]
    return f"{resp['feedback']}\n\n{resp['verdict']}"


# ── Live Codex reviewer ────────────────────────────────────────────────────

def _live_review(
    plan_content: str,
    previous_feedback: str,
    output_path: Path,
    timeout: int = 240,
) -> str:
    """Run codex exec and return the review text."""
    prompt = REVIEW_PROMPT_TEMPLATE.format(
        plan_content=plan_content,
        previous_feedback=previous_feedback or "(first review — no prior feedback)",
    )

    cmd = [
        CODEX_BIN,
        "exec",
        "--sandbox", "read-only",
        "-m", MODEL,
        "-o", str(output_path),
        "-C", PROJECT_DIR,
        prompt,
    ]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    # Prefer the -o file if it was written; fall back to stdout
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path.read_text()
    if proc.stdout.strip():
        return proc.stdout.strip()

    raise RuntimeError(
        f"Codex exited with code {proc.returncode} and produced no output. "
        f"stderr: {proc.stderr[:500]}"
    )


# ── Public API ──────────────────────────────────────────────────────────────

def review_plan(
    plan_path: str,
    iteration: int,
    session_id: str,
    previous_feedback: str = "",
) -> str:
    """Review a plan and return the review text including a VERDICT line.

    In test mode, returns a deterministic response.
    In live mode, calls codex exec.
    """
    test_mode = os.environ.get("PLAN_REVIEW_TEST_MODE", "0") == "1"

    if test_mode:
        return _test_review(iteration)

    plan_content = Path(plan_path).read_text()
    output_path = Path(f"/tmp/plan_review_result_{session_id}_{iteration}.md")

    try:
        return _live_review(plan_content, previous_feedback, output_path)
    finally:
        # Clean up temp result file
        output_path.unlink(missing_ok=True)


def parse_verdict(review_text: str) -> str:
    """Extract the verdict from review text. Returns 'APPROVED', 'REVISE', or 'UNKNOWN'."""
    # Scan from the end for the last VERDICT line
    for line in reversed(review_text.strip().splitlines()):
        stripped = line.strip()
        if stripped.startswith("VERDICT:"):
            verdict = stripped.split(":", 1)[1].strip().upper()
            if "APPROVED" in verdict:
                return "APPROVED"
            if "REVISE" in verdict:
                return "REVISE"
    return "UNKNOWN"
