"""Tests for claude_planner module."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.plan_review_loop.claude_planner import (
    PlanResult,
    _detect_new_plan,
    _snapshot_plans,
    run_initial_plan,
    run_revision,
)


class TestSnapshotPlans:
    def test_empty_dir(self, tmp_plans_dir: Path) -> None:
        assert _snapshot_plans(tmp_plans_dir) == set()

    def test_with_files(self, tmp_plans_dir: Path) -> None:
        (tmp_plans_dir / "plan1.md").write_text("a")
        (tmp_plans_dir / "plan2.md").write_text("b")
        result = _snapshot_plans(tmp_plans_dir)
        assert len(result) == 2

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert _snapshot_plans(tmp_path / "nope") == set()


class TestDetectNewPlan:
    def test_new_file_detected(self, tmp_plans_dir: Path) -> None:
        old = tmp_plans_dir / "old.md"
        old.write_text("old plan")
        before = {old}

        new = tmp_plans_dir / "new.md"
        new.write_text("new plan")
        after = {old, new}

        result = _detect_new_plan(before, after, tmp_plans_dir)
        assert result == new

    def test_fallback_to_most_recent(self, tmp_plans_dir: Path) -> None:
        """When no new files, picks most recently modified."""
        p1 = tmp_plans_dir / "first.md"
        p1.write_text("first")

        time.sleep(0.05)  # ensure different mtime

        p2 = tmp_plans_dir / "second.md"
        p2.write_text("second")

        both = {p1, p2}
        result = _detect_new_plan(both, both, tmp_plans_dir)
        assert result == p2

    def test_empty_dir_raises(self, tmp_plans_dir: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _detect_new_plan(set(), set(), tmp_plans_dir)

    def test_multiple_new_picks_latest(self, tmp_plans_dir: Path) -> None:
        before = set()

        p1 = tmp_plans_dir / "a.md"
        p1.write_text("a")

        time.sleep(0.05)

        p2 = tmp_plans_dir / "b.md"
        p2.write_text("b")

        after = {p1, p2}
        result = _detect_new_plan(before, after, tmp_plans_dir)
        assert result == p2


class TestRunInitialPlan:
    def test_success(
        self,
        tmp_plans_dir: Path,
        sample_claude_json: dict,
        sample_plan_content: str,
    ) -> None:
        plan_file = tmp_plans_dir / "test-plan.md"

        def fake_run(cmd, **kwargs):
            # Write plan file to simulate Claude writing it
            plan_file.write_text(sample_plan_content)

            class Result:
                returncode = 0
                stdout = json.dumps(sample_claude_json)
                stderr = ""

            return Result()

        with patch("scripts.plan_review_loop.claude_planner.subprocess.run", side_effect=fake_run):
            result = run_initial_plan(
                task_prompt="Build test feature",
                budget_usd=1.0,
                plans_dir=tmp_plans_dir,
            )

        assert isinstance(result, PlanResult)
        assert result.session_id == sample_claude_json["session_id"]
        assert result.plan_content == sample_plan_content
        assert result.plan_file_path == plan_file
        assert result.cost_usd == 0.15

    def test_claude_failure_raises(self, tmp_plans_dir: Path) -> None:
        def fake_run(cmd, **kwargs):
            class Result:
                returncode = 1
                stdout = ""
                stderr = "error"

            return Result()

        with (
            patch("scripts.plan_review_loop.claude_planner.subprocess.run", side_effect=fake_run),
            pytest.raises(subprocess.CalledProcessError),
        ):
            run_initial_plan(
                task_prompt="fail",
                plans_dir=tmp_plans_dir,
            )


class TestRunRevision:
    def test_success(
        self,
        tmp_plans_dir: Path,
        session_id: str,
        sample_claude_json: dict,
    ) -> None:
        # Pre-existing plan
        old_plan = tmp_plans_dir / "old.md"
        old_plan.write_text("old plan")

        revised_content = "# Revised Plan\n\nRevised content."
        revised_file = tmp_plans_dir / "revised.md"

        def fake_run(cmd, **kwargs):
            revised_file.write_text(revised_content)

            class Result:
                returncode = 0
                stdout = json.dumps(sample_claude_json)
                stderr = ""

            return Result()

        with patch("scripts.plan_review_loop.claude_planner.subprocess.run", side_effect=fake_run):
            result = run_revision(
                session_id=session_id,
                review_feedback="Fix the error handling.",
                iteration=1,
                budget_usd=1.0,
                plans_dir=tmp_plans_dir,
            )

        assert result.plan_content == revised_content
        assert result.plan_file_path == revised_file
        assert "--resume" in str(result.raw_json) or result.session_id == session_id
