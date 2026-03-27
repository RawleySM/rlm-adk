"""Tests for codex_reviewer module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.plan_review_loop.codex_reviewer import (
    ReviewResult,
    _build_review_prompt,
    _parse_findings,
    _parse_verdict,
    run_review,
)


class TestParseVerdict:
    def test_approved(self) -> None:
        assert _parse_verdict("some text\nVERDICT: APPROVED\n") == "APPROVED"

    def test_needs_revision(self) -> None:
        assert _parse_verdict("text\nVERDICT: NEEDS_REVISION\n") == "NEEDS_REVISION"

    def test_verdict_in_code_block_still_matches(self) -> None:
        text = "```\nVERDICT: APPROVED\n```"
        assert _parse_verdict(text) == "APPROVED"

    def test_no_verdict_defaults_to_needs_revision(self) -> None:
        assert _parse_verdict("no verdict here") == "NEEDS_REVISION"

    def test_case_sensitive(self) -> None:
        # VERDICT pattern is case-sensitive for the verdict values
        assert _parse_verdict("VERDICT: approved") == "NEEDS_REVISION"

    def test_whitespace_tolerance(self) -> None:
        assert _parse_verdict("VERDICT:   APPROVED  ") == "APPROVED"


class TestParseFindings:
    def test_multiple_findings(self) -> None:
        text = (
            "**[High] Missing error handling**\n"
            "some details\n"
            "**[Medium] No tests**\n"
            "more details\n"
            "**[Low] Minor style issue**\n"
        )
        findings = _parse_findings(text)
        assert len(findings) == 3
        assert findings[0] == {"severity": "High", "title": "Missing error handling"}
        assert findings[1] == {"severity": "Medium", "title": "No tests"}
        assert findings[2] == {"severity": "Low", "title": "Minor style issue"}

    def test_no_findings(self) -> None:
        assert _parse_findings("clean review, no issues") == []

    def test_case_insensitive_severity(self) -> None:
        findings = _parse_findings("**[HIGH] Big problem**\n")
        assert findings[0]["severity"] == "High"


class TestBuildReviewPrompt:
    def test_template_substitution(self, tmp_path: Path) -> None:
        template = tmp_path / "template.md"
        template.write_text(
            "Plan: {{PLAN_FILE_PATH}}\n"
            "Iter: {{ITERATION}}/{{MAX_ITERATIONS}}\n"
            "Content: {{PLAN_CONTENT}}\n"
            "History: {{REVIEW_HISTORY}}\n"
            "Repo: {{REPO_DIR}}\n"
        )

        result = _build_review_prompt(
            plan_content="my plan",
            plan_file_path=Path("/tmp/plan.md"),
            iteration=2,
            review_history="prior review",
            template_path=template,
            repo_dir=Path("/repo"),
            max_iterations=5,
        )

        assert "Plan: /tmp/plan.md" in result
        assert "Iter: 2/5" in result
        assert "Content: my plan" in result
        assert "History: prior review" in result
        assert "Repo: /repo" in result

    def test_empty_history_gets_placeholder(self, tmp_path: Path) -> None:
        template = tmp_path / "t.md"
        template.write_text("{{REVIEW_HISTORY}}")

        result = _build_review_prompt(
            plan_content="p",
            plan_file_path=Path("/p.md"),
            iteration=1,
            review_history="",
            template_path=template,
            repo_dir=Path("/r"),
        )
        assert "First review" in result


class TestRunReview:
    def test_success_approved(
        self,
        tmp_path: Path,
        sample_review_approved: str,
    ) -> None:
        template = tmp_path / "template.md"
        template.write_text(
            "Review {{PLAN_CONTENT}} at {{PLAN_FILE_PATH}} iter {{ITERATION}}/{{MAX_ITERATIONS}} history={{REVIEW_HISTORY}} repo={{REPO_DIR}}"
        )

        output_path = tmp_path / "review.md"
        codex_bin = tmp_path / "fake_codex"

        def fake_run(cmd, **kwargs):
            output_path.write_text(sample_review_approved)

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with patch("scripts.plan_review_loop.codex_reviewer.subprocess.run", side_effect=fake_run):
            result = run_review(
                plan_content="test plan",
                plan_file_path=Path("/tmp/plan.md"),
                iteration=1,
                review_history="",
                output_path=output_path,
                template_path=template,
                codex_bin=codex_bin,
                model="test-model",
                repo_dir=tmp_path,
            )

        assert isinstance(result, ReviewResult)
        assert result.verdict == "APPROVED"
        assert len(result.findings) == 1
        assert result.findings[0]["severity"] == "Low"

    def test_success_needs_revision(
        self,
        tmp_path: Path,
        sample_review_needs_revision: str,
    ) -> None:
        template = tmp_path / "template.md"
        template.write_text(
            "{{PLAN_CONTENT}}{{PLAN_FILE_PATH}}{{ITERATION}}{{MAX_ITERATIONS}}{{REVIEW_HISTORY}}{{REPO_DIR}}"
        )

        output_path = tmp_path / "review.md"

        def fake_run(cmd, **kwargs):
            output_path.write_text(sample_review_needs_revision)

            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            return Result()

        with patch("scripts.plan_review_loop.codex_reviewer.subprocess.run", side_effect=fake_run):
            result = run_review(
                plan_content="test",
                plan_file_path=Path("/tmp/p.md"),
                iteration=1,
                review_history="",
                output_path=output_path,
                template_path=template,
                codex_bin=Path("/fake"),
                model="m",
                repo_dir=tmp_path,
            )

        assert result.verdict == "NEEDS_REVISION"
        assert len(result.findings) == 2

    def test_codex_failure_raises(self, tmp_path: Path) -> None:
        template = tmp_path / "t.md"
        template.write_text(
            "{{PLAN_CONTENT}}{{PLAN_FILE_PATH}}{{ITERATION}}{{MAX_ITERATIONS}}{{REVIEW_HISTORY}}{{REPO_DIR}}"
        )

        def fake_run(cmd, **kwargs):
            class Result:
                returncode = 1
                stdout = ""
                stderr = "error"

            return Result()

        with (
            patch("scripts.plan_review_loop.codex_reviewer.subprocess.run", side_effect=fake_run),
            pytest.raises(subprocess.CalledProcessError),
        ):
            run_review(
                plan_content="p",
                plan_file_path=Path("/p.md"),
                iteration=1,
                review_history="",
                output_path=tmp_path / "r.md",
                template_path=template,
                codex_bin=Path("/fake"),
                model="m",
                repo_dir=tmp_path,
            )
