"""Claude Code CLI wrapper for plan-mode invocations.

Stdlib-only. Handles initial planning and revision turns.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)


@dataclass
class PlanResult:
    """Result from a Claude planning invocation."""

    session_id: str
    plan_content: str
    plan_file_path: Path
    cost_usd: float
    raw_json: dict


def _snapshot_plans(plans_dir: Path) -> set[Path]:
    """Return the current set of plan files."""
    if not plans_dir.exists():
        return set()
    return set(plans_dir.glob("*.md"))


def _detect_new_plan(before: set[Path], after: set[Path], plans_dir: Path) -> Path:
    """Compare plan dir listings before/after to find the new file.

    Falls back to the most recently modified file if no new files detected
    (handles the case where Claude overwrites an existing plan on revision).
    """
    new_files = after - before
    if new_files:
        return max(new_files, key=lambda p: p.stat().st_mtime)
    # Fallback: most recently modified file in the directory
    all_plans = list(plans_dir.glob("*.md"))
    if not all_plans:
        raise FileNotFoundError(f"No plan files found in {plans_dir}")
    return max(all_plans, key=lambda p: p.stat().st_mtime)


def _invoke_claude(cmd: list[str]) -> dict:
    """Run claude CLI and parse JSON output.

    Raises:
        subprocess.CalledProcessError: If claude exits non-zero.
        json.JSONDecodeError: If output is not valid JSON.
    """
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,  # 10 min max for a planning turn
    )
    if result.returncode != 0:
        logger.error("Claude stderr: %s", result.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return json.loads(result.stdout)


def run_initial_plan(
    task_prompt: str,
    budget_usd: float | None = None,
    system_prompt: str | None = None,
    plans_dir: Path | None = None,
) -> PlanResult:
    """Run Claude in plan mode to generate an initial plan.

    Args:
        task_prompt: The user's task description.
        budget_usd: Max USD per turn. Defaults to config value.
        system_prompt: Optional additional system prompt.
        plans_dir: Override plans directory. Defaults to config value.

    Returns:
        PlanResult with session_id, plan content, file path, and cost.
    """
    if budget_usd is None:
        budget_usd = config.CLAUDE_BUDGET_PER_TURN
    if plans_dir is None:
        plans_dir = config.PLANS_DIR

    before = _snapshot_plans(plans_dir)

    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        "--max-budget-usd",
        str(budget_usd),
    ]
    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])
    cmd.append(task_prompt)

    raw = _invoke_claude(cmd)

    after = _snapshot_plans(plans_dir)
    plan_file = _detect_new_plan(before, after, plans_dir)
    plan_content = plan_file.read_text()

    return PlanResult(
        session_id=raw.get("session_id", ""),
        plan_content=plan_content,
        plan_file_path=plan_file,
        cost_usd=raw.get("total_cost_usd", 0.0) or 0.0,
        raw_json=raw,
    )


def run_revision(
    session_id: str,
    review_feedback: str,
    iteration: int,
    budget_usd: float | None = None,
    plans_dir: Path | None = None,
) -> PlanResult:
    """Resume a Claude plan session with review feedback.

    Args:
        session_id: Session ID from the initial plan run.
        review_feedback: Full text of the Codex review.
        iteration: Current iteration number (for prompt framing).
        budget_usd: Max USD per turn. Defaults to config value.
        plans_dir: Override plans directory. Defaults to config value.

    Returns:
        PlanResult with the revised plan.
    """
    if budget_usd is None:
        budget_usd = config.CLAUDE_BUDGET_PER_TURN
    if plans_dir is None:
        plans_dir = config.PLANS_DIR

    before = _snapshot_plans(plans_dir)

    revision_prompt = (
        f"REVIEW FEEDBACK (Iteration {iteration}):\n\n"
        f"{review_feedback}\n\n"
        f"Please revise the plan to address the findings above. "
        f"Focus on High and Medium severity issues."
    )

    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--resume",
        session_id,
        "--max-budget-usd",
        str(budget_usd),
        revision_prompt,
    ]

    raw = _invoke_claude(cmd)

    after = _snapshot_plans(plans_dir)
    plan_file = _detect_new_plan(before, after, plans_dir)
    plan_content = plan_file.read_text()

    return PlanResult(
        session_id=raw.get("session_id", session_id),
        plan_content=plan_content,
        plan_file_path=plan_file,
        cost_usd=raw.get("total_cost_usd", 0.0) or 0.0,
        raw_json=raw,
    )
