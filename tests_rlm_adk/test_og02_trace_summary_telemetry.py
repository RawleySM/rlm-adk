"""Tests for OG-02: repl_trace_summary landing in tool telemetry."""
import json
import sqlite3
import time
from unittest.mock import MagicMock

import pytest

from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
from rlm_adk.state import LAST_REPL_RESULT


@pytest.fixture
def plugin_and_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    plugin = SqliteTracingPlugin(db_path=db_path)
    return plugin, db_path


def _make_invocation_context():
    ctx = MagicMock()
    ctx.session.id = "sess_1"
    ctx.session.user_id = "user_1"
    ctx.app_name = "test"
    ctx.session.state = {}
    return ctx


class TestTraceSummaryInTelemetry:
    @pytest.mark.asyncio
    async def test_repl_trace_summary_written_to_telemetry(self, plugin_and_db):
        plugin, db_path = plugin_and_db
        inv_ctx = _make_invocation_context()
        await plugin.before_run_callback(invocation_context=inv_ctx)

        # Simulate before_tool
        tool = MagicMock()
        tool.name = "execute_code"
        tool._depth = 0
        tool_context = MagicMock()
        tool_context.state = {
            LAST_REPL_RESULT: {
                "has_errors": False,
                "has_output": True,
                "total_llm_calls": 1,
                "trace_summary": {
                    "wall_time_ms": 42.5,
                    "llm_call_count": 1,
                    "submitted_code_hash": "abc123",
                },
            }
        }
        tool_args = {"code": "print('hi')"}

        await plugin.before_tool_callback(
            tool=tool, tool_args=tool_args, tool_context=tool_context
        )

        result = {"stdout": "hi\n", "stderr": "", "variables": {}}
        await plugin.after_tool_callback(
            tool=tool, tool_args=tool_args, tool_context=tool_context, result=result
        )

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT repl_trace_summary FROM telemetry WHERE tool_name='execute_code'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] is not None, "repl_trace_summary should not be NULL"
        summary = json.loads(rows[0][0])
        assert summary["wall_time_ms"] == 42.5

    @pytest.mark.asyncio
    async def test_repl_trace_summary_null_when_no_trace(self, plugin_and_db):
        plugin, db_path = plugin_and_db
        inv_ctx = _make_invocation_context()
        await plugin.before_run_callback(invocation_context=inv_ctx)

        tool = MagicMock()
        tool.name = "execute_code"
        tool._depth = 0
        tool_context = MagicMock()
        # No trace_summary in LAST_REPL_RESULT
        tool_context.state = {
            LAST_REPL_RESULT: {
                "has_errors": False,
                "has_output": True,
                "total_llm_calls": 0,
            }
        }

        await plugin.before_tool_callback(
            tool=tool, tool_args={"code": "x=1"}, tool_context=tool_context
        )
        await plugin.after_tool_callback(
            tool=tool, tool_args={"code": "x=1"}, tool_context=tool_context,
            result={"stdout": "", "stderr": "", "variables": {"x": 1}},
        )

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT repl_trace_summary FROM telemetry WHERE tool_name='execute_code'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][0] is None  # No trace_summary = NULL is expected
