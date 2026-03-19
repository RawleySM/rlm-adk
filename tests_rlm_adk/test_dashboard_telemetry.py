"""Dashboard telemetry completeness tests.

Validates the P0 fixes for GAP-06, GAP-02, and GAP-07:
- GAP-06: Tool call telemetry finalization (end_time, result_payload non-NULL)
- GAP-02: Child state propagation (session_state_events at key_depth > 0)
- GAP-07: Trace lifecycle finalization (status=completed, total_calls > 0)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import (
    PluginContractResult,
    run_fixture_contract_with_plugins,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

_FIXTURE = FIXTURE_DIR / "dashboard_telemetry_completeness.json"


async def _run(tmp_path: Path) -> PluginContractResult:
    """Run the dashboard telemetry fixture through the full plugin pipeline."""
    return await run_fixture_contract_with_plugins(
        _FIXTURE,
        traces_db_path=str(tmp_path / "traces.db"),
        repl_trace_level=1,
        tmpdir=str(tmp_path),
    )


# ---------------------------------------------------------------------------
# GAP-06: Tool call telemetry finalization
# ---------------------------------------------------------------------------


@pytest.mark.provider_fake_contract
async def test_tool_calls_have_end_time(tmp_path: Path):
    """All execute_code tool call rows in telemetry must have end_time IS NOT NULL."""
    result = await _run(tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        rows = conn.execute(
            "SELECT agent_name, depth, end_time, duration_ms, result_preview "
            "FROM telemetry WHERE event_type = 'tool_call' AND tool_name = 'execute_code'"
        ).fetchall()

        assert len(rows) > 0, "No execute_code tool_call rows found in telemetry"

        for agent_name, depth, end_time, duration_ms, result_preview in rows:
            assert end_time is not None, (
                f"GAP-06: execute_code at depth={depth} agent={agent_name} "
                f"has end_time=NULL (tool call never finalized)"
            )
            assert duration_ms is not None, (
                f"GAP-06: execute_code at depth={depth} agent={agent_name} has duration_ms=NULL"
            )
            assert result_preview is not None, (
                f"GAP-06: execute_code at depth={depth} agent={agent_name} has result_preview=NULL"
            )
            print(
                f"  tool_call: agent={agent_name} depth={depth} "
                f"end_time={end_time:.2f} duration_ms={duration_ms:.1f} "
                f"result_preview={result_preview[:80] if result_preview else 'NULL'}"
            )
    finally:
        conn.close()


@pytest.mark.provider_fake_contract
async def test_tool_calls_have_repl_enrichment(tmp_path: Path):
    """execute_code tool call rows should have REPL enrichment columns populated."""
    result = await _run(tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        rows = conn.execute(
            "SELECT agent_name, depth, repl_stdout, repl_stderr, result_payload "
            "FROM telemetry WHERE event_type = 'tool_call' AND tool_name = 'execute_code'"
        ).fetchall()

        assert len(rows) > 0, "No execute_code tool_call rows found"

        for agent_name, depth, repl_stdout, repl_stderr, result_payload in rows:
            # result_payload should be non-NULL for all finalized tool calls
            assert result_payload is not None, (
                f"GAP-06: execute_code at depth={depth} agent={agent_name} "
                f"has result_payload=NULL (REPL enrichment missing)"
            )
            print(
                f"  repl_enrichment: agent={agent_name} depth={depth} "
                f"stdout_len={len(repl_stdout or '')} stderr_len={len(repl_stderr or '')} "
                f"payload_len={len(result_payload or '')}"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# GAP-02: Child state propagation
# ---------------------------------------------------------------------------


@pytest.mark.provider_fake_contract
async def test_state_events_at_child_depths(tmp_path: Path):
    """Child agent activity should appear in telemetry rows at depth > 0.

    After the lineage refactor, child state deltas no longer propagate
    through session_state_events.  Instead, child lineage is tracked
    via telemetry rows with depth > 0 and distinct agent_name values.
    """
    result = await _run(tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        # Check for telemetry rows at depth > 0 (child agents)
        child_rows = conn.execute(
            "SELECT agent_name, depth, event_type, tool_name "
            "FROM telemetry WHERE depth > 0"
        ).fetchall()

        print(f"  child depth telemetry rows: {len(child_rows)}")
        for agent, depth, etype, tool in child_rows:
            print(
                f"    agent={agent} depth={depth} "
                f"type={etype} tool={tool}"
            )

        assert len(child_rows) > 0, (
            "GAP-02: telemetry has zero rows at depth > 0. "
            "Child agent activity is not being recorded."
        )

        # Verify child agents have model_call and tool_call rows
        child_model = conn.execute(
            "SELECT COUNT(*) FROM telemetry "
            "WHERE depth > 0 AND event_type = 'model_call'"
        ).fetchone()[0]
        child_tool = conn.execute(
            "SELECT COUNT(*) FROM telemetry "
            "WHERE depth > 0 AND event_type = 'tool_call'"
        ).fetchone()[0]

        print(f"  child model_calls: {child_model}")
        print(f"  child tool_calls: {child_tool}")

        assert child_model > 0, (
            "GAP-02: No child model_call telemetry rows at depth > 0."
        )
        assert child_tool > 0, (
            "GAP-02: No child tool_call telemetry rows at depth > 0."
        )

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# GAP-07: Trace lifecycle finalization
# ---------------------------------------------------------------------------


@pytest.mark.provider_fake_contract
async def test_trace_finalized_after_run(tmp_path: Path):
    """Trace row should have status='completed', end_time set, total_calls > 0."""
    result = await _run(tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        row = conn.execute(
            "SELECT status, end_time, total_calls, total_input_tokens FROM traces LIMIT 1"
        ).fetchone()

        assert row is not None, "No trace row found in traces table"
        status, end_time, total_calls, total_input_tokens = row

        assert status == "completed", f"GAP-07: Trace status should be 'completed', got {status!r}"
        assert end_time is not None, "GAP-07: Trace end_time should be set, got None"
        assert total_calls > 0, f"GAP-07: Trace total_calls should be > 0, got {total_calls}"

        print(
            f"  trace: status={status} end_time={end_time} "
            f"total_calls={total_calls} input_tokens={total_input_tokens}"
        )
    finally:
        conn.close()
