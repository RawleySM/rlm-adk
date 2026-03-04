"""E2E tests for structured output with provider-fake.

Validates the full structured output self-healing pipeline end-to-end:

- **Happy path**: llm_query + output_schema with valid functionCall on first try.
- **Batched K=1**: llm_query_batched with K=1 + output_schema (exercises batched
  code path without ParallelAgent ordering issues).
- **Retry (empty field)**: WorkerRetryPlugin detects empty string in
  set_model_response args, model retries with valid data.
- **Retry (ValidationError)**: SetModelResponseTool raises ValidationError for
  missing required field, on_tool_error_callback returns reflection guidance,
  model retries with corrected args.

Each fixture scripts Gemini API responses in FIFO order via ScenarioRouter.
Structured output workers receive functionCall responses (not text).
SetModelResponseTool terminates the worker after successful tool execution —
no confirmation text step needed. Happy path: 1 worker API call (functionCall).
Retry adds 1 API call per retry attempt (bad functionCall + corrected functionCall).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rlm_adk.state import FINAL_ANSWER, LAST_REPL_RESULT

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import (
    PluginContractResult,
    run_fixture_contract,
    run_fixture_contract_with_plugins,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STRUCTURED_FIXTURES = [
    "agent_challenge/structured_output_happy_path",
    "agent_challenge/structured_output_batched_k1",
    "structured_output_retry_empty",
    "structured_output_retry_validation",
]


async def _run_with_plugins(
    fixture_name: str, tmp_path: Path,
) -> PluginContractResult:
    """Run a named structured output fixture through the plugin-enabled pipeline."""
    fixture_path = FIXTURE_DIR / f"{fixture_name}.json"
    traces_db = str(tmp_path / "traces.db")
    return await run_fixture_contract_with_plugins(
        fixture_path,
        traces_db_path=traces_db,
        repl_trace_level=1,
    )


# ===========================================================================
# Contract validation — all structured output fixtures
# ===========================================================================


@pytest.mark.parametrize("fixture_name", _STRUCTURED_FIXTURES)
async def test_structured_output_contract(fixture_name: str):
    """Validate structured output fixture against expected values.

    Checks final_answer, total_iterations, and total_model_calls.
    The model call count implicitly verifies:
    - Happy path: 1 worker API call (functionCall only)
    - Retry: 2 worker API calls (bad functionCall + corrected functionCall)
    """
    fixture_path = FIXTURE_DIR / f"{fixture_name}.json"
    result = await run_fixture_contract(fixture_path)
    if not result.passed:
        print(result.diagnostics())
    assert result.passed, (
        f"Structured output fixture contract failed: {fixture_name}\n"
        f"{result.diagnostics()}"
    )


# ===========================================================================
# Happy path — llm_query with output_schema
# ===========================================================================


async def test_happy_path_final_answer():
    """llm_query + output_schema: worker responds with valid functionCall."""
    result = await run_fixture_contract(
        FIXTURE_DIR / "agent_challenge" / "structured_output_happy_path.json"
    )
    assert result.passed, result.diagnostics()
    # Verify the specific final answer from the parsed structured output
    fa_check = next(c for c in result.checks if c["field"] == "final_answer")
    assert fa_check["actual"] == "Market trending up with strong momentum"


async def test_happy_path_with_plugins(tmp_path: Path):
    """Plugin pipeline works correctly with structured output workers."""
    result = await _run_with_plugins("structured_output_happy_path", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.final_state.get(FINAL_ANSWER) == "Market trending up with strong momentum"
    assert len(result.events) > 0

    # REPL snapshots should show llm_calls from the structured output dispatch
    repl_snapshots = [
        (getattr(getattr(ev, "actions", None), "state_delta", None) or {}).get(LAST_REPL_RESULT)
        for ev in result.events
    ]
    repl_snapshots = [s for s in repl_snapshots if s is not None]
    assert len(repl_snapshots) >= 1, "Expected at least one REPL snapshot"

    # The iteration with code blocks should have recorded llm_calls
    iterations_with_calls = [
        s for s in repl_snapshots
        if isinstance(s, dict) and s.get("total_llm_calls", 0) > 0
    ]
    assert len(iterations_with_calls) >= 1, (
        f"No iteration recorded llm_calls — repl_snapshots: {repl_snapshots}"
    )

    # Trace verification: repl_trace_level=1 should produce trace_summary
    for i, snap in enumerate(repl_snapshots):
        assert "trace_summary" in snap, (
            f"snapshot[{i}] missing trace_summary (repl_trace_level=1) — keys: {list(snap.keys())}"
        )
        ts = snap["trace_summary"]
        assert ts["wall_time_ms"] >= 0, f"snapshot[{i}] wall_time_ms < 0"


# ===========================================================================
# Batched K=1 — llm_query_batched with output_schema
# ===========================================================================


async def test_batched_k1_final_answer():
    """llm_query_batched K=1 + output_schema: exercises batched code path."""
    result = await run_fixture_contract(
        FIXTURE_DIR / "agent_challenge" / "structured_output_batched_k1.json"
    )
    assert result.passed, result.diagnostics()
    fa_check = next(c for c in result.checks if c["field"] == "final_answer")
    assert fa_check["actual"] == "positive"


# ===========================================================================
# Retry (empty field) — WorkerRetryPlugin soft error detection
# ===========================================================================


async def test_retry_empty_final_answer():
    """Empty field triggers WorkerRetryPlugin, retry succeeds with valid data."""
    result = await run_fixture_contract(
        FIXTURE_DIR / "structured_output_retry_empty.json"
    )
    assert result.passed, result.diagnostics()
    fa_check = next(c for c in result.checks if c["field"] == "final_answer")
    assert fa_check["actual"] == "Market shows steady upward trend"


async def test_retry_empty_model_call_count():
    """Empty field retry consumes 2 worker API calls (bad + corrected)."""
    result = await run_fixture_contract(
        FIXTURE_DIR / "structured_output_retry_empty.json"
    )
    assert result.passed, result.diagnostics()
    calls_check = next(c for c in result.checks if c["field"] == "total_model_calls")
    assert calls_check["actual"] == 4, (
        f"Expected 4 total calls (1 reasoning + 2 worker + 1 FINAL), got {calls_check['actual']}"
    )


# ===========================================================================
# Retry (ValidationError) — hard error via on_tool_error_callback
# ===========================================================================


async def test_retry_validation_final_answer():
    """Missing required field triggers ValidationError, retry succeeds."""
    result = await run_fixture_contract(
        FIXTURE_DIR / "structured_output_retry_validation.json"
    )
    assert result.passed, result.diagnostics()
    fa_check = next(c for c in result.checks if c["field"] == "final_answer")
    assert fa_check["actual"] == "Market recovering with moderate gains"


async def test_retry_validation_model_call_count():
    """ValidationError retry consumes 2 worker API calls (bad + corrected)."""
    result = await run_fixture_contract(
        FIXTURE_DIR / "structured_output_retry_validation.json"
    )
    assert result.passed, result.diagnostics()
    calls_check = next(c for c in result.checks if c["field"] == "total_model_calls")
    assert calls_check["actual"] == 4, (
        f"Expected 4 total calls (1 reasoning + 2 worker + 1 FINAL), got {calls_check['actual']}"
    )


async def test_retry_validation_with_plugins(tmp_path: Path):
    """Retry fixture ends with correct final_answer despite initial failure."""
    result = await _run_with_plugins("structured_output_retry_validation", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.final_state.get(FINAL_ANSWER) == "Market recovering with moderate gains"
    assert len(result.events) > 0

    # Trace verification: every REPL snapshot should have trace_summary
    repl_snapshots = [
        (getattr(getattr(ev, "actions", None), "state_delta", None) or {}).get(LAST_REPL_RESULT)
        for ev in result.events
    ]
    repl_snapshots = [s for s in repl_snapshots if s is not None]
    assert len(repl_snapshots) >= 1, "Expected at least one REPL snapshot"
    for i, snap in enumerate(repl_snapshots):
        assert "trace_summary" in snap, (
            f"snapshot[{i}] missing trace_summary (repl_trace_level=1) — keys: {list(snap.keys())}"
        )
        ts = snap["trace_summary"]
        assert ts["wall_time_ms"] >= 0, f"snapshot[{i}] wall_time_ms < 0"
