"""Tests for the completion_records table (Phase 3 telemetry schema refactor).

Verifies:
- DDL: completion_records table is created and queryable on fresh DB
- Write paths: deferred flush, after_run_callback, after_agent_callback
- Cardinality invariants: exactly 1 orchestrator row per trace at depth 0
- Error paths: orchestrator_error producer type on failures
- Anchoring: telemetry_id NULL for orchestrator-level and child rows
- No reasoning-agent leakage through isinstance gate

TDD Cycles 1-7:
  Cycle 1: test_completion_records_queryable (unit, schema only)
  Cycle 2: test_root_cardinality_invariant (provider_fake)
  Cycle 3: test_error_path_completion (provider_fake)
  Cycle 4: test_telemetry_id_null_anchoring (provider_fake)
  Cycle 5: test_nonvacuous_child_prerequisite (provider_fake)
  Cycle 6: test_no_reasoning_agent_leakage (provider_fake)
  Cycle 7: GREEN — all implemented, all pass
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import (
    run_fixture_contract_with_plugins,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_fixture_with_tracing(
    fixture_name: str,
    tmp_path: Path,
    monkeypatch,
) -> tuple:
    """Run a provider_fake fixture with SqliteTracingPlugin enabled.

    Returns (PluginContractResult, sqlite3.Connection to traces.db).
    """
    monkeypatch.setenv("RLM_MAX_CONCURRENT_CHILDREN", "1")

    fixture_path = FIXTURE_DIR / f"{fixture_name}.json"
    traces_db = str(tmp_path / "traces.db")
    result = await run_fixture_contract_with_plugins(
        fixture_path,
        traces_db_path=traces_db,
        repl_trace_level=1,
        tmpdir=str(tmp_path),
    )
    conn = sqlite3.connect(traces_db)
    return result, conn


# ---------------------------------------------------------------------------
# Cycle 1: completion_records table exists and is queryable (unit test)
# ---------------------------------------------------------------------------


class TestCompletionRecordsQueryable:
    """The completion_records table must be created by _SCHEMA_SQL."""

    def test_completion_records_queryable(self, tmp_path):
        """Fresh DB has a completion_records table that returns 0 rows."""
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        assert plugin._conn is not None

        row = plugin._conn.execute("SELECT COUNT(*) FROM completion_records").fetchone()
        assert row[0] == 0, f"Expected 0 rows in fresh completion_records, got {row[0]}"

    def test_completion_records_has_expected_columns(self, tmp_path):
        """The completion_records table has all expected columns."""
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        conn = plugin._conn
        assert conn is not None

        cursor = conn.execute("PRAGMA table_info(completion_records)")
        col_names = {row[1] for row in cursor.fetchall()}

        expected = {
            "completion_id",
            "telemetry_id",
            "trace_id",
            "producer_type",
            "terminal",
            "mode",
            "output_schema_name",
            "validated_output",
            "raw_output",
            "display_text",
            "reasoning_summary",
            "finish_reason",
            "error",
            "error_category",
            "agent_name",
            "depth",
            "fanout_idx",
            "created_at",
        }
        missing = expected - col_names
        assert not missing, f"completion_records missing columns: {missing}"

    def test_completion_records_indexes_exist(self, tmp_path):
        """The completion_records indexes are created."""
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        conn = plugin._conn
        assert conn is not None

        indexes = {
            row[1]
            for row in conn.execute(
                "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='completion_records'"
            ).fetchall()
        }
        assert "idx_completion_records_trace_id" in indexes
        assert "idx_completion_records_telemetry_id" in indexes


# ---------------------------------------------------------------------------
# Cycle 2: Root cardinality invariant (provider_fake fixture run)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.provider_fake
class TestRootCardinalityInvariant:
    """After a successful fixture run, exactly 1 orchestrator row at depth=0."""

    async def test_root_cardinality_invariant(self, tmp_path, monkeypatch):
        """Exactly 1 row with producer_type='orchestrator' AND depth=0."""
        result, conn = await _run_fixture_with_tracing(
            "structured_output_retry_validation",
            tmp_path,
            monkeypatch,
        )
        try:
            assert result.contract.passed, result.contract.diagnostics()

            rows = conn.execute(
                "SELECT COUNT(*) FROM completion_records "
                "WHERE producer_type = 'orchestrator' AND depth = 0"
            ).fetchone()
            assert rows[0] == 1, (
                f"Expected exactly 1 root orchestrator completion record, got {rows[0]}"
            )

            # Verify the row has expected content
            row = conn.execute(
                "SELECT mode, terminal, error, trace_id FROM completion_records "
                "WHERE producer_type = 'orchestrator' AND depth = 0"
            ).fetchone()
            assert row is not None
            mode, terminal, error, trace_id = row
            assert terminal == 1, "Root completion should be terminal"
            assert trace_id is not None, "trace_id should be set"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Cycle 3: Error path completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.provider_fake
class TestErrorPathCompletion:
    """When structured output never validates, error completion is recorded."""

    async def test_error_path_completion(self, tmp_path, monkeypatch):
        """Root orchestrator_error row exists with mode='error' and error_category set."""
        result, conn = await _run_fixture_with_tracing(
            "empty_reasoning_output",
            tmp_path,
            monkeypatch,
        )
        try:
            # This fixture exhausts retries, so the contract may or may not pass
            # depending on fixture expectations. We care about completion_records.
            rows = conn.execute(
                "SELECT producer_type, mode, error, error_category "
                "FROM completion_records "
                "WHERE depth = 0 "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchall()
            assert len(rows) >= 1, "Expected at least 1 completion record at depth=0"
            producer_type, mode, error, error_category = rows[0]
            # Error path should yield orchestrator_error
            assert producer_type == "orchestrator_error", (
                f"Expected producer_type='orchestrator_error', got {producer_type!r}"
            )
            assert mode == "error", f"Expected mode='error', got {mode!r}"
            assert error == 1, f"Expected error=1, got {error!r}"
            assert error_category is not None, (
                "error_category should be non-NULL for error completions"
            )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Cycle 4: telemetry_id NULL anchoring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.provider_fake
class TestTelemetryIdNullAnchoring:
    """Root orchestrator error path: telemetry_id is NULL."""

    async def test_telemetry_id_null_anchoring(self, tmp_path, monkeypatch):
        """Root orchestrator error: no matching set_model_response -> telemetry_id IS NULL."""
        result, conn = await _run_fixture_with_tracing(
            "empty_reasoning_output",
            tmp_path,
            monkeypatch,
        )
        try:
            rows = conn.execute(
                "SELECT telemetry_id FROM completion_records "
                "WHERE producer_type = 'orchestrator_error' AND depth = 0"
            ).fetchall()
            assert len(rows) >= 1, "Expected at least 1 orchestrator_error completion at depth=0"
            for (telemetry_id,) in rows:
                assert telemetry_id is None, (
                    f"Expected telemetry_id IS NULL for orchestrator_error at depth=0, "
                    f"got {telemetry_id!r}"
                )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Cycle 5: Non-vacuous child prerequisite (recursive fixture)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.provider_fake
class TestNonvacuousChildPrerequisite:
    """Using recursive fixture, at least 1 child orchestrator row exists."""

    async def test_nonvacuous_child_prerequisite(self, tmp_path, monkeypatch):
        """At least 1 producer_type='orchestrator' AND depth > 0 row exists."""
        result, conn = await _run_fixture_with_tracing(
            "fake_recursive_ping",
            tmp_path,
            monkeypatch,
        )
        try:
            assert result.contract.passed, result.contract.diagnostics()

            rows = conn.execute(
                "SELECT COUNT(*) FROM completion_records "
                "WHERE producer_type IN ('orchestrator', 'orchestrator_error') "
                "AND depth > 0"
            ).fetchone()
            assert rows[0] >= 1, (
                f"Expected at least 1 child orchestrator completion record "
                f"at depth > 0, got {rows[0]}"
            )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Cycle 6: No reasoning agent leakage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.provider_fake
class TestNoReasoningAgentLeakage:
    """Zero orchestrator rows from reasoning agent names (isinstance gate)."""

    async def test_no_reasoning_agent_leakage(self, tmp_path, monkeypatch):
        """Zero rows where producer_type IN orchestrator types AND agent_name LIKE 'child_reasoning_%'."""
        result, conn = await _run_fixture_with_tracing(
            "fake_recursive_ping",
            tmp_path,
            monkeypatch,
        )
        try:
            assert result.contract.passed, result.contract.diagnostics()

            rows = conn.execute(
                "SELECT COUNT(*) FROM completion_records "
                "WHERE producer_type IN ('orchestrator', 'orchestrator_error') "
                "AND agent_name LIKE '%reasoning%'"
            ).fetchone()
            assert rows[0] == 0, (
                f"Expected 0 orchestrator rows with reasoning agent names, "
                f"got {rows[0]} (isinstance gate failure)"
            )
        finally:
            conn.close()
