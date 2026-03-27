"""Tests for the main plan_review_loop orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.plan_review_loop.claude_planner import PlanResult
from scripts.plan_review_loop.codex_reviewer import ReviewResult
from scripts.plan_review_loop.plan_review_loop import (
    LoopState,
    _build_review_history,
    _check_budget,
    run_loop,
)


class TestBuildReviewHistory:
    def test_empty(self) -> None:
        assert _build_review_history([]) == ""

    def test_single_review(self) -> None:
        reviews = [ReviewResult(verdict="APPROVED", review_text="Looks good.")]
        result = _build_review_history(reviews)
        assert "Review 1" in result
        assert "APPROVED" in result
        assert "Looks good." in result

    def test_multiple_reviews(self) -> None:
        reviews = [
            ReviewResult(verdict="NEEDS_REVISION", review_text="Fix X."),
            ReviewResult(verdict="APPROVED", review_text="All fixed."),
        ]
        result = _build_review_history(reviews)
        assert "Review 1" in result
        assert "Review 2" in result
        assert "---" in result


class TestCheckBudget:
    def test_within_budget(self) -> None:
        state = LoopState(task_prompt="t", total_cost_usd=5.0)
        assert _check_budget(state, budget_total=10.0)

    def test_over_budget(self) -> None:
        state = LoopState(task_prompt="t", total_cost_usd=11.0)
        assert not _check_budget(state, budget_total=10.0)

    def test_exact_boundary(self) -> None:
        state = LoopState(task_prompt="t", total_cost_usd=10.0)
        assert not _check_budget(state, budget_total=10.0)


class TestRunLoopApprovedFirstTry:
    def test_approved_on_first_review(self, tmp_path: Path) -> None:
        plan_result = PlanResult(
            session_id="sess-123",
            plan_content="# Test Plan",
            plan_file_path=tmp_path / "plan.md",
            cost_usd=0.15,
            raw_json={"session_id": "sess-123", "total_cost_usd": 0.15},
        )
        review_result = ReviewResult(
            verdict="APPROVED",
            review_text="Plan is sound.\nVERDICT: APPROVED",
            findings=[],
        )

        with (
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_initial_plan",
                return_value=plan_result,
            ),
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_review",
                return_value=review_result,
            ),
        ):
            state = run_loop(
                task_prompt="Test task",
                max_iterations=3,
                log_dir=tmp_path / "logs",
            )

        assert state.status == "approved"
        assert state.iteration == 1
        assert state.session_id == "sess-123"

        # Check logs were written
        log_dir = tmp_path / "logs"
        assert (log_dir / "events.jsonl").exists()
        assert (log_dir / "state.json").exists()
        assert (log_dir / "summary.md").exists()
        assert (log_dir / "plan_v1.md").exists()


class TestRunLoopRevisionThenApproved:
    def test_two_iterations(self, tmp_path: Path) -> None:
        plan_v1 = PlanResult(
            session_id="sess-1",
            plan_content="# V1",
            plan_file_path=tmp_path / "v1.md",
            cost_usd=0.15,
            raw_json={"session_id": "sess-1", "total_cost_usd": 0.15},
        )
        plan_v2 = PlanResult(
            session_id="sess-1",
            plan_content="# V2 (revised)",
            plan_file_path=tmp_path / "v2.md",
            cost_usd=0.18,
            raw_json={"session_id": "sess-1", "total_cost_usd": 0.18},
        )
        review_reject = ReviewResult(
            verdict="NEEDS_REVISION",
            review_text="Fix errors.\nVERDICT: NEEDS_REVISION",
            findings=[{"severity": "High", "title": "Missing error handling"}],
        )
        review_approve = ReviewResult(
            verdict="APPROVED",
            review_text="All good.\nVERDICT: APPROVED",
            findings=[],
        )

        with (
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_initial_plan",
                return_value=plan_v1,
            ),
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_revision",
                return_value=plan_v2,
            ),
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_review",
                side_effect=[review_reject, review_approve],
            ),
        ):
            state = run_loop(
                task_prompt="Test",
                max_iterations=5,
                log_dir=tmp_path / "logs",
            )

        assert state.status == "approved"
        assert state.iteration == 2
        assert state.total_cost_usd == pytest.approx(0.33, abs=0.01)


class TestRunLoopMaxIterations:
    def test_cap_reached(self, tmp_path: Path) -> None:
        plan = PlanResult(
            session_id="sess-1",
            plan_content="# Plan",
            plan_file_path=tmp_path / "p.md",
            cost_usd=0.10,
            raw_json={"session_id": "sess-1", "total_cost_usd": 0.10},
        )
        reject = ReviewResult(
            verdict="NEEDS_REVISION",
            review_text="Still needs work.\nVERDICT: NEEDS_REVISION",
            findings=[{"severity": "High", "title": "Issue"}],
        )

        with (
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_initial_plan",
                return_value=plan,
            ),
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_revision",
                return_value=plan,
            ),
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_review",
                return_value=reject,
            ),
        ):
            state = run_loop(
                task_prompt="Test",
                max_iterations=2,
                log_dir=tmp_path / "logs",
            )

        assert state.status == "max_iterations"


class TestRunLoopBudgetExceeded:
    def test_budget_stops_loop(self, tmp_path: Path) -> None:
        expensive_plan = PlanResult(
            session_id="sess-1",
            plan_content="# Expensive",
            plan_file_path=tmp_path / "p.md",
            cost_usd=8.0,  # High cost
            raw_json={"session_id": "sess-1", "total_cost_usd": 8.0},
        )
        reject = ReviewResult(
            verdict="NEEDS_REVISION",
            review_text="Needs work.\nVERDICT: NEEDS_REVISION",
            findings=[{"severity": "High", "title": "Issue"}],
        )

        with (
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_initial_plan",
                return_value=expensive_plan,
            ),
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_revision",
                return_value=expensive_plan,
            ),
            patch(
                "scripts.plan_review_loop.plan_review_loop.run_review",
                return_value=reject,
            ),
            patch(
                "scripts.plan_review_loop.plan_review_loop.config.CLAUDE_BUDGET_TOTAL",
                9.0,
            ),
        ):
            state = run_loop(
                task_prompt="Test",
                max_iterations=10,
                log_dir=tmp_path / "logs",
            )

        # After initial plan ($8) + one revision ($8) = $16 > $9 budget
        assert state.status == "budget_exceeded"


class TestRunLoopInitialPlanError:
    def test_error_on_initial_plan(self, tmp_path: Path) -> None:
        import subprocess

        with patch(
            "scripts.plan_review_loop.plan_review_loop.run_initial_plan",
            side_effect=subprocess.CalledProcessError(1, "claude"),
        ):
            state = run_loop(
                task_prompt="Fail",
                log_dir=tmp_path / "logs",
            )

        assert state.status == "error"
