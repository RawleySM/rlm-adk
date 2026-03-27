"""Shared fixtures for plan_review_loop tests.

Mirrors the pattern from scripts/codex_transfer/tests/conftest.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_plans_dir(tmp_path: Path) -> Path:
    """Provide a temporary plans directory."""
    plans = tmp_path / "plans"
    plans.mkdir()
    return plans


@pytest.fixture
def tmp_log_dir(tmp_path: Path) -> Path:
    """Provide a temporary log directory."""
    logs = tmp_path / "logs"
    logs.mkdir()
    return logs


@pytest.fixture
def session_id() -> str:
    """Return a fixed session ID for testing."""
    return "test-session-abcd-1234"


@pytest.fixture
def sample_claude_json(session_id: str) -> dict:
    """Return sample Claude CLI JSON output from plan mode."""
    return {
        "type": "result",
        "subtype": None,
        "duration_ms": 15000,
        "duration_api_ms": 6000,
        "is_error": False,
        "num_turns": 2,
        "stop_reason": "tool_use",
        "session_id": session_id,
        "total_cost_usd": 0.15,
        "usage": {
            "input_tokens": 5000,
            "output_tokens": 800,
        },
        "permission_denials": [],
        "errors": [],
    }


@pytest.fixture
def sample_plan_content() -> str:
    """Return sample plan markdown content."""
    return (
        "# Plan: Test Feature\n\n"
        "## Context\n\n"
        "Adding a test feature.\n\n"
        "## Steps\n\n"
        "1. Create module\n"
        "2. Write tests\n"
        "3. Verify\n"
    )


@pytest.fixture
def sample_review_approved() -> str:
    """Return sample Codex review text with APPROVED verdict."""
    return (
        "### Findings\n\n"
        "**[Low] Minor naming inconsistency**\n"
        "- Severity: Low\n"
        "- Section: Steps\n"
        "- Problem: Step 1 could be more specific\n"
        "- Suggestion: Name the module explicitly\n\n"
        "### Summary\n\n"
        "The plan is well-structured and feasible.\n\n"
        "### Verdict\n\n"
        "VERDICT: APPROVED\n"
    )


@pytest.fixture
def sample_review_needs_revision() -> str:
    """Return sample Codex review text with NEEDS_REVISION verdict."""
    return (
        "### Findings\n\n"
        "**[High] Missing error handling**\n"
        "- Severity: High\n"
        "- Section: Steps\n"
        "- Problem: No error handling strategy defined\n"
        "- Suggestion: Add error handling section\n\n"
        "**[Medium] No test coverage plan**\n"
        "- Severity: Medium\n"
        "- Section: Steps\n"
        "- Problem: Step 2 lacks specifics\n"
        "- Suggestion: Define test cases\n\n"
        "### Summary\n\n"
        "The plan has a critical gap in error handling.\n\n"
        "### Verdict\n\n"
        "VERDICT: NEEDS_REVISION\n"
    )
