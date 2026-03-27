"""Plan Review Loop — bidirectional Claude planner / Codex reviewer orchestration.

Usage:
    python -m scripts.plan_review_loop.plan_review_loop "Build feature X"
    python -m scripts.plan_review_loop.plan_review_loop "Build feature X" \\
        --max-iterations 3 --codex-model o3 --verbose

Environment variables:
    PRL_MAX_ITERATIONS          Max review cycles (default: 5)
    PRL_CLAUDE_BUDGET_PER_TURN  USD budget per Claude turn (default: 2.0)
    PRL_CLAUDE_BUDGET_TOTAL     Total USD budget for all Claude turns (default: 10.0)
    PRL_CODEX_MODEL             Codex model for reviews (default: o3)
    PRL_CODEX_TIMEOUT           Codex subprocess timeout in seconds (default: 300)
    PRL_LOG_DIR                 Log directory (default: scripts/plan_review_loop/logs/)
    PRL_REPO_DIR                Repository root (default: /home/rawley-stanhope/dev/rlm-adk)
    CODEX_BIN                   Path to codex binary

Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config
from .claude_planner import PlanResult, run_initial_plan, run_revision
from .codex_reviewer import ReviewResult, run_review

logger = logging.getLogger(__name__)


@dataclass
class LoopState:
    """Tracks orchestration state across iterations."""

    task_prompt: str
    session_id: str | None = None
    iteration: int = 0
    total_cost_usd: float = 0.0
    status: str = "pending"
    started_at: float = field(default_factory=time.time)
    plan_summaries: list[dict] = field(default_factory=list)
    review_summaries: list[dict] = field(default_factory=list)


def _build_review_history(review_results: list[ReviewResult]) -> str:
    """Concatenate previous reviews into a history block for context."""
    if not review_results:
        return ""
    parts = []
    for i, r in enumerate(review_results, 1):
        parts.append(f"### Review {i} (Verdict: {r.verdict})\n\n{r.review_text}")
    return "\n\n---\n\n".join(parts)


def _check_budget(state: LoopState, budget_total: float | None = None) -> bool:
    """Return True if total cost is within budget."""
    if budget_total is None:
        budget_total = config.CLAUDE_BUDGET_TOTAL
    return state.total_cost_usd < budget_total


def _log_event(events_path: Path, event: dict) -> None:
    """Append a JSON event to the JSONL log."""
    event["ts"] = time.time()
    with open(events_path, "a") as f:
        f.write(json.dumps(event) + "\n")


def _save_plan(log_dir: Path, iteration: int, plan_result: PlanResult) -> None:
    """Save plan content and raw JSON to the log directory."""
    (log_dir / f"plan_v{iteration}.md").write_text(plan_result.plan_content)
    (log_dir / f"claude_raw_iter{iteration}.json").write_text(
        json.dumps(plan_result.raw_json, indent=2)
    )


def _save_state(log_dir: Path, state: LoopState) -> None:
    """Serialize LoopState to JSON."""
    (log_dir / "state.json").write_text(json.dumps(asdict(state), indent=2, default=str))


def _write_summary(log_dir: Path, state: LoopState, final_plan: PlanResult | None) -> None:
    """Write a human-readable summary markdown file."""
    lines = [
        "# Plan Review Loop Summary\n",
        f"- **Task:** {state.task_prompt}",
        f"- **Status:** {state.status}",
        f"- **Iterations:** {state.iteration}",
        f"- **Total cost:** ${state.total_cost_usd:.4f}",
        f"- **Duration:** {time.time() - state.started_at:.1f}s",
        f"- **Session ID:** {state.session_id}",
    ]
    if final_plan:
        lines.append(f"- **Final plan:** {final_plan.plan_file_path}")
    lines.append("")
    (log_dir / "summary.md").write_text("\n".join(lines))


def run_loop(
    task_prompt: str,
    max_iterations: int | None = None,
    claude_budget: float | None = None,
    codex_model: str | None = None,
    system_prompt: str | None = None,
    log_dir: Path | None = None,
) -> LoopState:
    """Execute the full plan-review loop.

    Args:
        task_prompt: The user's task description.
        max_iterations: Override max iterations.
        claude_budget: Override per-turn Claude budget.
        codex_model: Override Codex model.
        system_prompt: Optional additional system prompt for Claude.
        log_dir: Override log directory for this run.

    Returns:
        Final LoopState with terminal status.
    """
    if max_iterations is None:
        max_iterations = config.MAX_ITERATIONS
    if claude_budget is None:
        claude_budget = config.CLAUDE_BUDGET_PER_TURN
    if codex_model is None:
        codex_model = config.CODEX_MODEL

    # Create run-specific log directory
    if log_dir is None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        log_dir = config.LOG_DIR / f"prl_{timestamp}"
    log_dir.mkdir(parents=True, exist_ok=True)
    events_path = log_dir / "events.jsonl"

    state = LoopState(task_prompt=task_prompt)
    review_results: list[ReviewResult] = []
    plan_result: PlanResult | None = None

    _log_event(events_path, {"event": "loop_start", "task": task_prompt})

    # -- Phase 1: Initial planning ------------------------------------------
    state.status = "planning"
    logger.info("Phase 1: Claude initial planning...")

    try:
        plan_result = run_initial_plan(
            task_prompt=task_prompt,
            budget_usd=claude_budget,
            system_prompt=system_prompt,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as exc:
        logger.error("Initial planning failed: %s", exc)
        state.status = "error"
        _log_event(events_path, {"event": "error", "phase": "initial_plan", "error": str(exc)})
        _save_state(log_dir, state)
        return state

    state.session_id = plan_result.session_id
    state.total_cost_usd += plan_result.cost_usd
    state.iteration = 1
    state.plan_summaries.append(
        {
            "iteration": 0,
            "plan_file": str(plan_result.plan_file_path),
            "cost_usd": plan_result.cost_usd,
        }
    )

    _save_plan(log_dir, 1, plan_result)
    _log_event(
        events_path,
        {
            "event": "claude_plan",
            "iteration": 0,
            "session_id": plan_result.session_id,
            "cost_usd": plan_result.cost_usd,
            "plan_file": str(plan_result.plan_file_path),
        },
    )

    logger.info("Plan generated: %s", plan_result.plan_file_path)

    # -- Review loop --------------------------------------------------------
    while state.iteration <= max_iterations:
        if not _check_budget(state):
            logger.warning("Budget exceeded ($%.2f). Stopping.", state.total_cost_usd)
            state.status = "budget_exceeded"
            break

        # Phase 2: Codex review
        state.status = "reviewing"
        logger.info("Phase 2: Codex review (iteration %d)...", state.iteration)

        review_history = _build_review_history(review_results)
        review_output_path = log_dir / f"review_iter{state.iteration}.md"

        try:
            review_result = run_review(
                plan_content=plan_result.plan_content,
                plan_file_path=plan_result.plan_file_path,
                iteration=state.iteration,
                review_history=review_history,
                output_path=review_output_path,
                model=codex_model,
            )
        except subprocess.TimeoutExpired:
            logger.error("Codex timed out at iteration %d", state.iteration)
            review_result = ReviewResult(
                verdict=config.VERDICT_NEEDS_REVISION,
                review_text="REVIEW ERROR: Codex timed out. Treating as NEEDS_REVISION.",
            )
        except subprocess.CalledProcessError as exc:
            logger.error("Codex failed at iteration %d: %s", state.iteration, exc)
            review_result = ReviewResult(
                verdict=config.VERDICT_NEEDS_REVISION,
                review_text=f"REVIEW ERROR: Codex exited {exc.returncode}. Treating as NEEDS_REVISION.",
            )

        review_results.append(review_result)
        state.review_summaries.append(
            {
                "iteration": state.iteration,
                "verdict": review_result.verdict,
                "findings_count": len(review_result.findings),
            }
        )

        _log_event(
            events_path,
            {
                "event": "codex_review",
                "iteration": state.iteration,
                "verdict": review_result.verdict,
                "findings_count": len(review_result.findings),
            },
        )

        logger.info(
            "Review verdict: %s (%d findings)",
            review_result.verdict,
            len(review_result.findings),
        )

        # Phase 3: Check convergence
        if review_result.verdict == config.VERDICT_APPROVED:
            state.status = "approved"
            logger.info("Plan APPROVED at iteration %d.", state.iteration)
            break

        # Phase 4: Claude revision
        if state.iteration >= max_iterations:
            state.status = "max_iterations"
            logger.warning("Max iterations (%d) reached.", max_iterations)
            break

        state.status = "planning"
        logger.info("Phase 4: Claude revision (iteration %d)...", state.iteration)

        try:
            plan_result = run_revision(
                session_id=state.session_id,
                review_feedback=review_result.review_text,
                iteration=state.iteration,
                budget_usd=claude_budget,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as exc:
            logger.error("Revision failed at iteration %d: %s", state.iteration, exc)
            state.status = "error"
            _log_event(
                events_path,
                {
                    "event": "error",
                    "phase": "revision",
                    "iteration": state.iteration,
                    "error": str(exc),
                },
            )
            break

        state.total_cost_usd += plan_result.cost_usd
        state.iteration += 1

        state.plan_summaries.append(
            {
                "iteration": state.iteration,
                "plan_file": str(plan_result.plan_file_path),
                "cost_usd": plan_result.cost_usd,
            }
        )

        _save_plan(log_dir, state.iteration, plan_result)
        _log_event(
            events_path,
            {
                "event": "claude_revision",
                "iteration": state.iteration,
                "session_id": plan_result.session_id,
                "cost_usd": plan_result.cost_usd,
            },
        )

        logger.info("Revised plan saved: %s", plan_result.plan_file_path)

    # -- Final logging ------------------------------------------------------
    _log_event(
        events_path,
        {
            "event": "loop_end",
            "status": state.status,
            "total_iterations": state.iteration,
            "total_cost_usd": state.total_cost_usd,
        },
    )
    _save_state(log_dir, state)
    _write_summary(log_dir, state, plan_result)

    return state


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Plan-review loop: Claude plans, Codex reviews, iterate to convergence.",
    )
    parser.add_argument("task", help="Task description for Claude to plan")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=config.MAX_ITERATIONS,
        help=f"Max review cycles (default: {config.MAX_ITERATIONS})",
    )
    parser.add_argument(
        "--claude-budget",
        type=float,
        default=config.CLAUDE_BUDGET_PER_TURN,
        help=f"USD budget per Claude turn (default: {config.CLAUDE_BUDGET_PER_TURN})",
    )
    parser.add_argument(
        "--codex-model",
        default=config.CODEX_MODEL,
        help=f"Codex model for reviews (default: {config.CODEX_MODEL})",
    )
    parser.add_argument(
        "--system-prompt",
        default=None,
        help="Additional system prompt for Claude",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    state = run_loop(
        task_prompt=args.task,
        max_iterations=args.max_iterations,
        claude_budget=args.claude_budget,
        codex_model=args.codex_model,
        system_prompt=args.system_prompt,
    )

    # Print final status
    print(f"\n{'=' * 60}")
    print(f"Status:     {state.status}")
    print(f"Iterations: {state.iteration}")
    print(f"Cost:       ${state.total_cost_usd:.4f}")
    print(f"Session:    {state.session_id}")
    if state.plan_summaries:
        print(f"Final plan: {state.plan_summaries[-1].get('plan_file', 'N/A')}")
    print(f"{'=' * 60}")

    sys.exit(0 if state.status == "approved" else 1)


if __name__ == "__main__":
    main()
