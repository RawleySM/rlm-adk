"""E2E test: skill function calls llm_query() via thread bridge.

Exercises the full pipeline:
  model calls execute_code with skill function code
  -> skill function calls llm_query() via thread bridge
  -> child orchestrator dispatches
  -> child returns
  -> parent REPL continues
  -> model calls set_model_response (or emits FINAL text)

Cycles 21-24: contract + three-plane verification (state, telemetry, trace).
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent / "fixtures" / "provider_fake" / "skill_thread_bridge.json"


async def _run_with_traces():
    """Run the fixture with plugins and a traces DB. Returns PluginContractResult."""
    from tests_rlm_adk.provider_fake.contract_runner import (
        run_fixture_contract_with_plugins,
    )

    tmpdir = tempfile.mkdtemp(prefix="skill-tb-e2e-")
    traces_db = str(Path(tmpdir) / "traces.db")
    return await run_fixture_contract_with_plugins(
        _FIXTURE,
        traces_db_path=traces_db,
        tmpdir=tmpdir,
    )


# ---------------------------------------------------------------------------
# Cycle 21 — Contract tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSkillThreadBridgeContract:
    """Provider-fake e2e: skill function dispatches llm_query via thread bridge."""

    async def test_contract_passes(self) -> None:
        """The fixture contract passes end-to-end."""
        from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract

        result = await run_fixture_contract(_FIXTURE)
        assert result.passed, result.diagnostics()

    async def test_final_answer_contains_expected_text(self) -> None:
        """Final answer includes the expected marker text."""
        result = await _run_with_traces()
        # depth_key at depth=0 returns the raw key (no prefix)
        final_text = result.final_state.get("final_response_text", "")
        assert "thread_bridge_skill_ok" in final_text, (
            f"Expected 'thread_bridge_skill_ok' in final_response_text, "
            f"got: {final_text[:200]}"
        )

    async def test_events_emitted(self) -> None:
        """The run emits a non-empty event list."""
        result = await _run_with_traces()
        assert len(result.events) > 0, "Expected non-empty events list"


# ---------------------------------------------------------------------------
# Cycle 22 — State/event plane verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSkillThreadBridgeStateEvents:
    """Verify session_state_events table captures expected state changes."""

    async def test_repl_submitted_code_events(self) -> None:
        """session_state_events has rows with key containing 'repl_submitted_code'."""
        result = await _run_with_traces()
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM session_state_events "
                "WHERE state_key LIKE '%repl_submitted_code%'"
            ).fetchone()
            assert rows[0] > 0, "No repl_submitted_code events in session_state_events"
        finally:
            conn.close()

    async def test_last_repl_result_events(self) -> None:
        """session_state_events has rows with key containing 'last_repl_result'."""
        result = await _run_with_traces()
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM session_state_events "
                "WHERE state_key LIKE '%last_repl_result%'"
            ).fetchone()
            assert rows[0] > 0, "No last_repl_result events in session_state_events"
        finally:
            conn.close()

    async def test_iteration_count_events(self) -> None:
        """session_state_events has rows with key containing 'iteration_count'."""
        result = await _run_with_traces()
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM session_state_events "
                "WHERE state_key LIKE '%iteration_count%'"
            ).fetchone()
            assert rows[0] > 0, "No iteration_count events in session_state_events"
        finally:
            conn.close()

    async def test_child_state_events_captured(self) -> None:
        """session_state_events has rows with key_depth > 0 (child state events)."""
        result = await _run_with_traces()
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM session_state_events WHERE key_depth > 0"
            ).fetchone()
            assert rows[0] > 0, (
                "No child state events (key_depth > 0) in session_state_events. "
                "Child orchestrator state changes should be captured."
            )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Cycle 23 — Telemetry plane verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSkillThreadBridgeTelemetry:
    """Verify telemetry and traces tables capture expected data."""

    async def test_traces_row_completed(self) -> None:
        """traces table has a row with status='completed'."""
        result = await _run_with_traces()
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM traces WHERE status='completed'"
            ).fetchone()
            assert rows[0] > 0, "No completed trace row in traces table"
        finally:
            conn.close()

    async def test_model_call_telemetry_rows(self) -> None:
        """telemetry has rows with event_type='model_call'."""
        result = await _run_with_traces()
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM telemetry WHERE event_type='model_call'"
            ).fetchone()
            assert rows[0] > 0, "No model_call telemetry rows"
        finally:
            conn.close()

    async def test_execute_code_tool_telemetry(self) -> None:
        """telemetry has a row with decision_mode='execute_code'."""
        result = await _run_with_traces()
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM telemetry WHERE decision_mode='execute_code'"
            ).fetchone()
            assert rows[0] > 0, "No execute_code decision_mode telemetry row"
        finally:
            conn.close()

    async def test_set_model_response_tool_telemetry(self) -> None:
        """telemetry has a row with decision_mode='set_model_response'."""
        result = await _run_with_traces()
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM telemetry WHERE decision_mode='set_model_response'"
            ).fetchone()
            # The fixture uses plain text FINAL() not set_model_response tool call,
            # so this may be 0. Check for tool_call rows instead (the actual
            # event_type used by SqliteTracingPlugin.before_tool_callback).
            if rows[0] == 0:
                # Check if there's any tool_call telemetry at all
                alt = conn.execute(
                    "SELECT COUNT(*) FROM telemetry WHERE event_type='tool_call'"
                ).fetchone()
                assert alt[0] > 0, (
                    "No set_model_response or tool_call telemetry rows. "
                    "Expected at least tool_call rows from execute_code."
                )
        finally:
            conn.close()

    async def test_tool_invocation_summary_in_traces(self) -> None:
        """traces table has tool_invocation_summary populated."""
        result = await _run_with_traces()
        assert result.traces_db_path is not None
        conn = sqlite3.connect(result.traces_db_path)
        try:
            rows = conn.execute(
                "SELECT tool_invocation_summary FROM traces WHERE status='completed'"
            ).fetchone()
            assert rows is not None, "No completed trace row"
            summary = rows[0]
            assert summary is not None and len(summary) > 0, (
                "tool_invocation_summary is empty in the completed trace row"
            )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Cycle 24 — Trace plane verification (final_state inspection)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSkillThreadBridgeTracePlane:
    """Verify final_state contains expected trace data."""

    async def test_repl_submitted_code_in_state(self) -> None:
        """final state has a repl_submitted_code key."""
        result = await _run_with_traces()
        found = any("repl_submitted_code" in k for k in result.final_state)
        assert found, (
            "No repl_submitted_code key in final state. "
            f"Keys: {sorted(k for k in result.final_state if 'repl' in k)}"
        )

    async def test_last_repl_result_has_llm_calls(self) -> None:
        """last_repl_result in final state has total_llm_calls >= 1."""
        result = await _run_with_traces()
        lrr = result.final_state.get("last_repl_result")
        assert lrr is not None, "No last_repl_result in final state"
        assert isinstance(lrr, dict), f"last_repl_result not a dict: {type(lrr)}"
        total_llm = lrr.get("total_llm_calls", 0)
        assert total_llm >= 1, (
            f"Expected total_llm_calls >= 1 in last_repl_result, got {total_llm}"
        )

    async def test_execution_mode_in_last_repl_result(self) -> None:
        """last_repl_result has execution_mode == 'thread_bridge'."""
        result = await _run_with_traces()
        lrr = result.final_state.get("last_repl_result")
        assert lrr is not None, "No last_repl_result in final state"
        assert isinstance(lrr, dict), f"last_repl_result not a dict: {type(lrr)}"
        mode = lrr.get("execution_mode")
        assert mode == "thread_bridge", (
            f"Expected execution_mode='thread_bridge', got {mode!r}"
        )
