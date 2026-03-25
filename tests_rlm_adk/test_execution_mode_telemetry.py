"""Tests for GAP-OB-003: execution_mode captured in telemetry.

Verifies that:
1. REPLTool includes ``execution_mode`` in ``_final_result`` at all 3 return paths.
2. SqliteTracingPlugin's ``telemetry`` table has an ``execution_mode`` column.
3. ``after_tool_callback`` extracts ``execution_mode`` from ``repl_state``.
4. ``make_telemetry_finalizer`` ``_finalize`` closure extracts ``execution_mode``
   from the result dict.
"""

from __future__ import annotations

import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
from rlm_adk.repl.local_repl import LocalREPL
from rlm_adk.state import LAST_REPL_RESULT
from rlm_adk.tools.repl_tool import REPLTool

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake_contract]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_context(state: dict | None = None) -> MagicMock:
    """Build a mock ToolContext with a dict-backed .state property."""
    ctx = MagicMock()
    ctx.state = dict(state or {})
    ctx.actions = MagicMock()
    return ctx


# ===========================================================================
# Part 1: REPLTool._final_result includes execution_mode
# ===========================================================================


class TestREPLToolFinalResultExecutionMode:
    """REPLTool must include ``execution_mode`` in _final_result at every path."""

    async def test_normal_path_has_execution_mode(self):
        """Normal (success) return path includes execution_mode in result."""
        repl = LocalREPL(depth=0)
        captured = {}

        def _capture_finalizer(tc_id, result):
            captured.update(result)

        tool = REPLTool(
            repl,
            max_calls=10,
            depth=0,
            telemetry_finalizer=_capture_finalizer,
        )
        tc = _make_tool_context()
        result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)

        # The result dict returned by run_async IS _final_result
        assert "execution_mode" in result, (
            f"_final_result missing 'execution_mode' key. Keys: {list(result.keys())}"
        )
        assert result["execution_mode"] in ("sync", "thread_bridge"), (
            f"Expected 'sync' or 'thread_bridge', got {result['execution_mode']!r}"
        )
        # Also verify the telemetry finalizer received it
        assert "execution_mode" in captured, (
            "Telemetry finalizer did not receive execution_mode"
        )
        repl.cleanup()

    async def test_exception_path_has_execution_mode(self):
        """Exception return path includes execution_mode in result."""
        repl = LocalREPL(depth=0)
        captured = {}

        def _capture_finalizer(tc_id, result):
            captured.update(result)

        tool = REPLTool(
            repl,
            max_calls=10,
            depth=0,
            telemetry_finalizer=_capture_finalizer,
        )
        tc = _make_tool_context()

        # Patch execute_code_threaded to raise an exception
        with patch.object(repl, "execute_code_threaded", side_effect=RuntimeError("boom")):
            result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)

        assert "execution_mode" in result, (
            f"Exception-path _final_result missing 'execution_mode'. Keys: {list(result.keys())}"
        )
        assert result["execution_mode"] in ("sync", "thread_bridge")
        assert "execution_mode" in captured
        repl.cleanup()

    async def test_cancelled_path_has_execution_mode(self):
        """CancelledError return path includes execution_mode in result."""
        import asyncio

        repl = LocalREPL(depth=0)
        captured = {}

        def _capture_finalizer(tc_id, result):
            captured.update(result)

        tool = REPLTool(
            repl,
            max_calls=10,
            depth=0,
            telemetry_finalizer=_capture_finalizer,
        )
        tc = _make_tool_context()

        with patch.object(repl, "execute_code_threaded", side_effect=asyncio.CancelledError("cancel")):
            result = await tool.run_async(args={"code": "x = 1"}, tool_context=tc)

        assert "execution_mode" in result, (
            f"CancelledError-path _final_result missing 'execution_mode'. Keys: {list(result.keys())}"
        )
        assert result["execution_mode"] in ("sync", "thread_bridge")
        assert "execution_mode" in captured
        repl.cleanup()


# ===========================================================================
# Part 2: telemetry table schema has execution_mode column
# ===========================================================================


class TestTelemetrySchemaHasExecutionMode:
    """The telemetry table must have an execution_mode TEXT column."""

    def test_execution_mode_column_exists_in_fresh_db(self, tmp_path):
        """A freshly created traces.db has execution_mode in telemetry."""
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        assert plugin._conn is not None

        cols = plugin._conn.execute("PRAGMA table_info(telemetry)").fetchall()
        col_names = [c[1] for c in cols]
        assert "execution_mode" in col_names, (
            f"execution_mode column missing from telemetry table. Columns: {col_names}"
        )

    def test_execution_mode_column_in_expected_columns(self, tmp_path):
        """Migration adds execution_mode to an existing DB lacking the column."""
        # Create a DB missing the column, then let migration add it
        db_path = str(tmp_path / "traces_old.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE telemetry (telemetry_id TEXT PRIMARY KEY, "
            "trace_id TEXT NOT NULL, event_type TEXT NOT NULL, "
            "start_time REAL NOT NULL)"
        )
        conn.commit()
        conn.close()

        plugin = SqliteTracingPlugin(db_path=db_path)
        cols = plugin._conn.execute("PRAGMA table_info(telemetry)").fetchall()
        col_names = [c[1] for c in cols]
        assert "execution_mode" in col_names, (
            f"Migration did not add execution_mode column. Columns: {col_names}"
        )


# ===========================================================================
# Part 3: after_tool_callback propagates execution_mode
# ===========================================================================


class TestAfterToolCallbackExecutionMode:
    """after_tool_callback must extract execution_mode from repl_state."""

    async def test_after_tool_propagates_execution_mode(self, tmp_path):
        """When repl_state has execution_mode, after_tool_callback writes it."""
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        plugin._trace_id = "test-trace-001"

        # Create a mock tool that looks like execute_code
        tool = MagicMock()
        tool.name = "execute_code"
        tool._depth = 0

        # Create tool_context with state containing LAST_REPL_RESULT
        tc = MagicMock()
        tc.state = {
            LAST_REPL_RESULT: {
                "has_errors": False,
                "has_output": True,
                "total_llm_calls": 0,
                "execution_mode": "thread_bridge",
            }
        }
        inv_ctx = MagicMock()
        agent_mock = MagicMock()
        agent_mock._rlm_fanout_idx = None
        agent_mock._rlm_parent_depth = None
        agent_mock._rlm_parent_fanout_idx = None
        agent_mock._rlm_output_schema_name = None
        inv_ctx.agent = agent_mock
        inv_ctx.branch = None
        inv_ctx.invocation_id = "inv-001"
        session_mock = MagicMock()
        session_mock.id = "sess-001"
        inv_ctx.session = session_mock
        tc._invocation_context = inv_ctx

        # Simulate before_tool to insert a pending entry
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "x = 1"},
            tool_context=tc,
        )

        result = {
            "stdout": "hello",
            "stderr": "",
            "variables": {},
            "llm_calls_made": False,
            "call_number": 1,
            "execution_mode": "thread_bridge",
        }

        # Call after_tool
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"code": "x = 1"},
            tool_context=tc,
            result=result,
        )

        # Query the DB to see if execution_mode was stored
        row = plugin._conn.execute(
            "SELECT execution_mode FROM telemetry WHERE event_type='tool_call'"
        ).fetchone()
        assert row is not None, "No telemetry row found"
        assert row[0] == "thread_bridge", (
            f"Expected execution_mode='thread_bridge', got {row[0]!r}"
        )


# ===========================================================================
# Part 4: _finalize closure propagates execution_mode
# ===========================================================================


class TestFinalizerExecutionMode:
    """make_telemetry_finalizer closure must extract execution_mode from result."""

    def test_finalizer_propagates_execution_mode(self, tmp_path):
        """_finalize writes execution_mode from result dict to telemetry."""
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        plugin._trace_id = "test-trace-002"

        # Insert a telemetry row to update
        telemetry_id = "tel-001"
        plugin._insert_telemetry(
            telemetry_id,
            "tool_call",
            time.time(),
            tool_name="execute_code",
        )

        # Seed pending entry keyed by a fake tool_context id
        fake_tc_id = 99999
        plugin._pending_tool_telemetry[fake_tc_id] = (
            telemetry_id,
            time.time(),
        )

        finalizer = plugin.make_telemetry_finalizer()

        result = {
            "stdout": "out",
            "stderr": "",
            "variables": {},
            "llm_calls_made": False,
            "call_number": 1,
            "execution_mode": "sync",
        }

        finalizer(fake_tc_id, result)

        row = plugin._conn.execute(
            "SELECT execution_mode FROM telemetry WHERE telemetry_id=?",
            (telemetry_id,),
        ).fetchone()
        assert row is not None, "No telemetry row found"
        assert row[0] == "sync", (
            f"Expected execution_mode='sync', got {row[0]!r}"
        )
