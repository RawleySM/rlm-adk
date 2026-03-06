"""Tests for SQLite 3-table schema restructuring.

RED/GREEN TDD: These tests define the target 3-table schema
(traces enriched, telemetry, session_state_events) and callback write paths.
"""

import json
import sqlite3
import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_traces.db")


@pytest.fixture
def plugin(db_path):
    from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
    return SqliteTracingPlugin(db_path=db_path)


@pytest.fixture
def mock_invocation_context():
    ctx = MagicMock()
    ctx.session.id = "sess_1"
    ctx.session.user_id = "user_1"
    ctx.app_name = "test_app"
    ctx.session.state = {}
    return ctx


@pytest.fixture
def mock_callback_context():
    ctx = MagicMock()
    ctx.state = {}
    ctx._invocation_context = MagicMock()
    return ctx


# ---- Schema tests ----

class TestTelemetryTableExists:
    def test_telemetry_table_exists(self, db_path, plugin):
        conn = sqlite3.connect(db_path)
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "telemetry" in tables
        conn.close()


class TestSessionStateEventsTableExists:
    def test_session_state_events_table_exists(self, db_path, plugin):
        conn = sqlite3.connect(db_path)
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "session_state_events" in tables
        conn.close()


class TestTelemetryColumns:
    def test_telemetry_columns(self, db_path, plugin):
        conn = sqlite3.connect(db_path)
        columns = [
            row[1] for row in conn.execute("PRAGMA table_info(telemetry)").fetchall()
        ]
        expected = [
            "telemetry_id", "trace_id", "event_type", "agent_name",
            "iteration", "depth", "call_number", "start_time", "end_time",
            "duration_ms", "model", "input_tokens", "output_tokens",
            "finish_reason", "num_contents", "agent_type", "prompt_chars",
            "system_chars", "tool_name", "tool_args_keys", "result_preview",
            "repl_has_errors", "repl_has_output", "repl_llm_calls",
            "repl_trace_summary",
            "status", "error_type", "error_message",
        ]
        assert columns == expected
        conn.close()


class TestSessionStateEventsColumns:
    def test_session_state_events_columns(self, db_path, plugin):
        conn = sqlite3.connect(db_path)
        columns = [
            row[1] for row in conn.execute(
                "PRAGMA table_info(session_state_events)"
            ).fetchall()
        ]
        expected = [
            "event_id", "trace_id", "seq", "event_author", "event_time",
            "state_key", "key_category", "key_depth", "key_fanout",
            "value_type", "value_int", "value_float", "value_text", "value_json",
        ]
        assert columns == expected
        conn.close()


class TestTracesEnrichedColumns:
    def test_traces_enriched_columns(self, db_path, plugin):
        conn = sqlite3.connect(db_path)
        columns = [
            row[1] for row in conn.execute("PRAGMA table_info(traces)").fetchall()
        ]
        enriched = [
            "request_id", "repo_url", "root_prompt_preview",
            "total_execution_time_s", "child_dispatch_count",
            "child_error_counts", "structured_output_failures",
            "finish_safety_count", "finish_recitation_count",
            "finish_max_tokens_count", "tool_invocation_summary",
            "artifact_saves", "artifact_bytes_saved",
            "per_iteration_breakdown", "model_usage_summary",
        ]
        for col in enriched:
            assert col in columns, f"Missing enriched column: {col}"
        conn.close()


# ---- Callback write tests ----

class TestBeforeModelWritesTelemetry:
    @pytest.mark.asyncio
    async def test_before_model_writes_telemetry(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = [MagicMock(), MagicMock()]
        mock_callback_context.state = {"iteration_count": 2}
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM telemetry").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["event_type"] == "model_call"
        assert row["model"] == "gemini-2.5-flash"
        assert row["num_contents"] == 2
        assert row["iteration"] == 2
        assert row["start_time"] is not None
        assert row["status"] == "ok"
        conn.close()


class TestAfterModelUpdatesTelemetry:
    @pytest.mark.asyncio
    async def test_after_model_updates_telemetry(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
        mock_callback_context.state = {}
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )
        llm_response = MagicMock()
        llm_response.model_version = "gemini-2.5-flash"
        llm_response.usage_metadata = MagicMock()
        llm_response.usage_metadata.prompt_token_count = 100
        llm_response.usage_metadata.candidates_token_count = 50
        llm_response.error_code = None
        llm_response.finish_reason = MagicMock()
        llm_response.finish_reason.name = "STOP"
        await plugin.after_model_callback(
            callback_context=mock_callback_context, llm_response=llm_response
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM telemetry").fetchone()
        assert row["end_time"] is not None
        assert row["input_tokens"] == 100
        assert row["output_tokens"] == 50
        assert row["duration_ms"] is not None
        assert row["duration_ms"] >= 0
        assert row["finish_reason"] == "STOP"
        conn.close()


class TestBeforeToolWritesTelemetry:
    @pytest.mark.asyncio
    async def test_before_tool_writes_telemetry(
        self, plugin, db_path, mock_invocation_context
    ):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        tool = MagicMock()
        tool.name = "execute_code"
        tool_context = MagicMock()
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "print('hi')"},
            tool_context=tool_context,
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM telemetry").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["event_type"] == "tool_call"
        assert row["tool_name"] == "execute_code"
        assert json.loads(row["tool_args_keys"]) == ["code"]
        assert row["start_time"] is not None
        conn.close()


class TestAfterToolUpdatesTelemetry:
    @pytest.mark.asyncio
    async def test_after_tool_updates_telemetry(
        self, plugin, db_path, mock_invocation_context
    ):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        tool = MagicMock()
        tool.name = "execute_code"
        tool_context = MagicMock()
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "print('hi')"},
            tool_context=tool_context,
        )
        result = {"output": "hi\n"}
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"code": "print('hi')"},
            tool_context=tool_context,
            result=result,
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM telemetry").fetchone()
        assert row["end_time"] is not None
        assert row["result_preview"] is not None
        assert "hi" in row["result_preview"]
        assert row["duration_ms"] is not None
        conn.close()


class TestOnEventWritesSessionStateEvents:
    @pytest.mark.asyncio
    async def test_on_event_writes_session_state_events(
        self, plugin, db_path, mock_invocation_context
    ):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        event = MagicMock()
        event.actions.artifact_delta = None
        event.actions.state_delta = {"obs:total_calls": 5}
        event.author = "reasoning_agent"
        await plugin.on_event_callback(
            invocation_context=mock_invocation_context, event=event
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM session_state_events").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["state_key"] == "obs:total_calls"
        assert row["value_int"] == 5
        assert row["key_category"] == "obs_reasoning"
        assert row["event_author"] == "reasoning_agent"
        assert row["seq"] == 0
        conn.close()


class TestDepthKeyParsing:
    @pytest.mark.asyncio
    async def test_depth_key_parsing(
        self, plugin, db_path, mock_invocation_context
    ):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        event = MagicMock()
        event.actions.artifact_delta = None
        event.actions.state_delta = {"iteration_count@d2": 3}
        event.author = "reasoning_agent"
        await plugin.on_event_callback(
            invocation_context=mock_invocation_context, event=event
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM session_state_events").fetchone()
        assert row["key_depth"] == 2
        assert row["state_key"] == "iteration_count"
        assert row["value_int"] == 3
        assert row["key_category"] == "flow_control"
        conn.close()


class TestFanoutKeyParsing:
    @pytest.mark.asyncio
    async def test_fanout_key_parsing(
        self, plugin, db_path, mock_invocation_context
    ):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        event = MagicMock()
        event.actions.artifact_delta = None
        event.actions.state_delta = {
            "obs:child_summary@d1f0": {"calls": 2, "tokens": 100}
        }
        event.author = "orchestrator"
        await plugin.on_event_callback(
            invocation_context=mock_invocation_context, event=event
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM session_state_events").fetchone()
        assert row["key_depth"] == 1
        assert row["key_fanout"] == 0
        assert row["state_key"] == "obs:child_summary"
        assert row["key_category"] == "obs_dispatch"
        assert row["value_type"] == "dict"
        parsed = json.loads(row["value_json"])
        assert parsed["calls"] == 2
        conn.close()


class TestAfterRunEnrichedTraces:
    @pytest.mark.asyncio
    async def test_after_run_enriched_traces(
        self, plugin, db_path, mock_invocation_context
    ):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        mock_invocation_context.session.state = {
            "obs:total_input_tokens": 1000,
            "obs:total_output_tokens": 500,
            "obs:total_calls": 5,
            "iteration_count": 3,
            "final_answer": "The answer is 42.",
            "request_id": "req-abc-123",
            "repo_url": "https://github.com/example/repo",
            "root_prompt": "Analyze the repository structure and summarize the main components",
            "obs:total_execution_time": 12.5,
            "obs:child_dispatch_count": 2,
            "obs:child_error_counts": {"RATE_LIMIT": 1},
            "obs:structured_output_failures": 0,
            "obs:finish_safety_count": 1,
            "obs:finish_recitation_count": 0,
            "obs:finish_max_tokens_count": 2,
            "obs:tool_invocation_summary": {"execute_code": 3},
            "obs:artifact_saves": 4,
            "obs:artifact_bytes_saved": 8192,
            "obs:per_iteration_token_breakdown": [
                {"iteration": 0, "input_tokens": 200, "output_tokens": 100},
            ],
            "obs:model_usage:gemini-2.5-flash": {
                "calls": 5, "input_tokens": 1000, "output_tokens": 500,
            },
        }
        await plugin.after_run_callback(invocation_context=mock_invocation_context)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traces").fetchone()
        assert row["request_id"] == "req-abc-123"
        assert row["repo_url"] == "https://github.com/example/repo"
        assert row["root_prompt_preview"] is not None
        assert row["total_execution_time_s"] == 12.5
        assert row["child_dispatch_count"] == 2
        assert json.loads(row["child_error_counts"]) == {"RATE_LIMIT": 1}
        assert row["structured_output_failures"] == 0
        assert row["finish_safety_count"] == 1
        assert row["finish_recitation_count"] == 0
        assert row["finish_max_tokens_count"] == 2
        assert json.loads(row["tool_invocation_summary"]) == {"execute_code": 3}
        assert row["artifact_saves"] == 4
        assert row["artifact_bytes_saved"] == 8192
        assert row["per_iteration_breakdown"] is not None
        assert row["model_usage_summary"] is not None
        model_usage = json.loads(row["model_usage_summary"])
        assert "gemini-2.5-flash" in model_usage
        conn.close()
