"""Tests for lineage telemetry columns in traces.db.

Verifies that the 5 lineage columns (decision_mode, structured_outcome,
terminal_completion, custom_metadata_json, validated_output_json) are
populated in production data via the SqliteTracingPlugin.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import (
    run_fixture_contract_with_plugins,
)
from tests_rlm_adk.provider_fake.lineage_assertion_plugin import LineageAssertionPlugin

pytestmark = [pytest.mark.asyncio, pytest.mark.agent_challenge]

_LINEAGE_FIXTURE = "lineage_completion_planes"


async def _run_lineage_fixture(
    tmp_path: Path,
    monkeypatch,
) -> tuple:
    """Run the lineage_completion_planes fixture with sqlite tracing."""
    monkeypatch.setenv("RLM_MAX_CONCURRENT_CHILDREN", "1")

    plugin = LineageAssertionPlugin()
    fixture_path = FIXTURE_DIR / f"{_LINEAGE_FIXTURE}.json"
    traces_db = str(tmp_path / "traces.db")
    result = await run_fixture_contract_with_plugins(
        fixture_path,
        traces_db_path=traces_db,
        repl_trace_level=1,
        tmpdir=str(tmp_path),
        extra_plugins=[plugin],
    )
    return result, plugin


async def test_execute_code_decision_mode(tmp_path: Path, monkeypatch):
    """All execute_code tool_call rows have decision_mode='execute_code'."""
    result, _ = await _run_lineage_fixture(tmp_path, monkeypatch)
    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        rows = conn.execute(
            "SELECT decision_mode FROM telemetry "
            "WHERE event_type='tool_call' AND tool_name='execute_code'"
        ).fetchall()
        assert len(rows) >= 1, "No execute_code tool_call rows found"
        for row in rows:
            assert row[0] == "execute_code", (
                f"Expected decision_mode='execute_code', got {row[0]!r}"
            )
    finally:
        conn.close()


async def test_set_model_response_decision_mode_and_outcome(
    tmp_path: Path, monkeypatch
):
    """set_model_response rows have decision_mode; at least 1 validated+terminal."""
    result, _ = await _run_lineage_fixture(tmp_path, monkeypatch)
    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        rows = conn.execute(
            "SELECT decision_mode, structured_outcome, terminal_completion "
            "FROM telemetry "
            "WHERE event_type='tool_call' AND tool_name='set_model_response'"
        ).fetchall()
        assert len(rows) >= 1, "No set_model_response tool_call rows found"

        for dm, _so, _tc in rows:
            assert dm == "set_model_response", (
                f"Expected decision_mode='set_model_response', got {dm!r}"
            )

        validated_terminal = [
            r for r in rows if r[1] == "validated" and r[2] == 1
        ]
        assert len(validated_terminal) >= 1, (
            f"Expected >= 1 set_model_response row with "
            f"structured_outcome='validated' and terminal_completion=1, "
            f"got 0. Rows: {rows}"
        )
    finally:
        conn.close()


async def test_validated_output_json_populated(tmp_path: Path, monkeypatch):
    """Terminal set_model_response rows have non-null validated_output_json."""
    result, _ = await _run_lineage_fixture(tmp_path, monkeypatch)
    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        rows = conn.execute(
            "SELECT validated_output_json FROM telemetry "
            "WHERE event_type='tool_call' AND tool_name='set_model_response' "
            "AND terminal_completion=1"
        ).fetchall()
        assert len(rows) >= 1, "No terminal set_model_response rows found"

        for (val_json,) in rows:
            assert val_json is not None, (
                "validated_output_json is NULL for terminal row"
            )
            parsed = json.loads(val_json)
            assert isinstance(parsed, dict), (
                f"Expected dict, got {type(parsed).__name__}"
            )
            assert len(parsed) > 0, (
                "validated_output_json is empty dict"
            )
    finally:
        conn.close()


async def test_model_call_custom_metadata_json(tmp_path: Path, monkeypatch):
    """Model call rows at depth>=1 have custom_metadata_json with lineage fields."""
    result, _ = await _run_lineage_fixture(tmp_path, monkeypatch)
    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        rows = conn.execute(
            "SELECT custom_metadata_json, depth FROM telemetry "
            "WHERE event_type='model_call' AND depth >= 1"
        ).fetchall()
        assert len(rows) >= 1, "No model_call rows at depth >= 1"

        for meta_json, depth in rows:
            assert meta_json is not None, (
                f"custom_metadata_json is NULL for model_call at depth={depth}"
            )
            parsed = json.loads(meta_json)
            assert "agent_name" in parsed, (
                f"Missing 'agent_name' in custom_metadata_json at depth={depth}"
            )
            assert "depth" in parsed, (
                f"Missing 'depth' in custom_metadata_json at depth={depth}"
            )
            assert "output_schema_name" in parsed, (
                f"Missing 'output_schema_name' in custom_metadata_json at depth={depth}"
            )
    finally:
        conn.close()


async def test_all_tool_calls_have_decision_mode(tmp_path: Path, monkeypatch):
    """Every tool_call row has non-null decision_mode in the expected set."""
    result, _ = await _run_lineage_fixture(tmp_path, monkeypatch)
    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        rows = conn.execute(
            "SELECT tool_name, decision_mode FROM telemetry "
            "WHERE event_type='tool_call'"
        ).fetchall()
        assert len(rows) >= 1, "No tool_call rows found"

        expected_modes = {"execute_code", "set_model_response"}
        for tool_name, decision_mode in rows:
            assert decision_mode is not None, (
                f"decision_mode is NULL for tool_name={tool_name!r}"
            )
            assert decision_mode in expected_modes, (
                f"decision_mode={decision_mode!r} not in {expected_modes} "
                f"for tool_name={tool_name!r}"
            )
    finally:
        conn.close()
