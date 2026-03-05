"""Tests for SqliteTracingPlugin (3-table schema).

Tests that the SqliteTracingPlugin correctly captures structured telemetry
from ADK callbacks and writes them to a local SQLite database with tables:
traces (enriched), telemetry, session_state_events, and spans (legacy).
"""

import json
import sqlite3
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def db_path(tmp_path):
    """Return a path to a temporary database file."""
    return str(tmp_path / "test_traces.db")


@pytest.fixture
def plugin(db_path):
    """Create a SqliteTracingPlugin with a temporary database."""
    from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

    return SqliteTracingPlugin(db_path=db_path)


@pytest.fixture
def mock_invocation_context():
    """Create a mock InvocationContext with session state."""
    ctx = MagicMock()
    ctx.session.id = "sess_1"
    ctx.session.user_id = "user_1"
    ctx.app_name = "test_app"
    ctx.session.state = {}
    return ctx


@pytest.fixture
def mock_callback_context():
    """Create a mock CallbackContext with state dict."""
    ctx = MagicMock()
    ctx.state = {}
    ctx._invocation_context = MagicMock()
    return ctx


class TestSchemaCreation:
    """Test 1: Database schema creation on plugin instantiation."""

    def test_schema_creation(self, db_path, plugin):
        """Instantiating SqliteTracingPlugin creates all expected tables."""
        conn = sqlite3.connect(db_path)
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "traces" in tables
        assert "spans" in tables  # Legacy, kept for backward compat
        assert "telemetry" in tables
        assert "session_state_events" in tables
        conn.close()

    def test_wal_mode_enabled(self, db_path, plugin):
        """Database should use WAL journal mode for concurrent reads."""
        conn = sqlite3.connect(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_traces_table_has_enriched_columns(self, db_path, plugin):
        """Traces table has original + enriched columns."""
        conn = sqlite3.connect(db_path)
        columns = [
            row[1]
            for row in conn.execute("PRAGMA table_info(traces)").fetchall()
        ]
        # Original columns still present
        for col in ["trace_id", "session_id", "user_id", "app_name",
                     "start_time", "end_time", "status", "total_input_tokens",
                     "total_output_tokens", "total_calls", "iterations",
                     "final_answer_length", "metadata"]:
            assert col in columns
        # Enriched columns present
        for col in ["request_id", "repo_url", "root_prompt_preview",
                     "total_execution_time_s", "child_dispatch_count",
                     "child_error_counts", "structured_output_failures",
                     "finish_safety_count", "finish_recitation_count",
                     "finish_max_tokens_count", "tool_invocation_summary",
                     "artifact_saves", "artifact_bytes_saved",
                     "per_iteration_breakdown", "model_usage_summary"]:
            assert col in columns
        conn.close()

    def test_spans_table_columns(self, db_path, plugin):
        """Legacy spans table has all expected columns."""
        conn = sqlite3.connect(db_path)
        columns = [
            row[1]
            for row in conn.execute("PRAGMA table_info(spans)").fetchall()
        ]
        expected = [
            "span_id", "trace_id", "parent_span_id", "operation_name",
            "agent_name", "start_time", "end_time", "status",
            "attributes", "events",
        ]
        assert columns == expected
        conn.close()


class TestTraceLifecycle:
    """Tests 2-3: Trace creation and completion."""

    @pytest.mark.asyncio
    async def test_before_run_creates_trace(
        self, plugin, db_path, mock_invocation_context
    ):
        """Calling before_run_callback inserts a row into traces with status='running'."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM traces").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "running"
        assert row["session_id"] == "sess_1"
        assert row["user_id"] == "user_1"
        assert row["app_name"] == "test_app"
        assert row["start_time"] is not None
        conn.close()

    @pytest.mark.asyncio
    async def test_after_run_updates_trace(
        self, plugin, db_path, mock_invocation_context
    ):
        """Calling after_run_callback updates trace with status='completed' and end_time."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        mock_invocation_context.session.state = {
            "obs:total_input_tokens": 500,
            "obs:total_output_tokens": 250,
            "obs:total_calls": 3,
            "iteration_count": 2,
            "final_answer": "The answer is 42.",
        }
        await plugin.after_run_callback(
            invocation_context=mock_invocation_context
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traces").fetchone()
        assert row["status"] == "completed"
        assert row["end_time"] is not None
        assert row["total_input_tokens"] == 500
        assert row["total_output_tokens"] == 250
        assert row["total_calls"] == 3
        assert row["iterations"] == 2
        assert row["final_answer_length"] == len("The answer is 42.")
        conn.close()


class TestAgentCallbacks:
    """Tests 4-5: Agent callback tracking (no longer writes spans)."""

    @pytest.mark.asyncio
    async def test_before_agent_pushes_name(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """before_agent_callback pushes agent name onto context stack."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        agent = MagicMock()
        agent.name = "test_agent"
        await plugin.before_agent_callback(
            agent=agent, callback_context=mock_callback_context
        )
        assert plugin._agent_span_stack == ["test_agent"]

    @pytest.mark.asyncio
    async def test_after_agent_pops_name(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """after_agent_callback pops agent name from context stack."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        agent = MagicMock()
        agent.name = "test_agent"
        await plugin.before_agent_callback(
            agent=agent, callback_context=mock_callback_context
        )
        await plugin.after_agent_callback(
            agent=agent, callback_context=mock_callback_context
        )
        assert plugin._agent_span_stack == []


class TestModelTelemetry:
    """Tests 6-8: Model telemetry creation, closing, and error handling."""

    @pytest.mark.asyncio
    async def test_before_model_creates_telemetry(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """before_model_callback inserts a telemetry row with event_type='model_call'."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM telemetry").fetchall()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "model_call"
        assert rows[0]["model"] == "gemini-2.5-flash"
        conn.close()

    @pytest.mark.asyncio
    async def test_after_model_updates_telemetry(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """after_model_callback updates telemetry row with token counts and end_time."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
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
        conn.close()

    @pytest.mark.asyncio
    async def test_model_error_marks_telemetry_error(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """on_model_error_callback sets status='error' on the telemetry row."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )
        error = RuntimeError("API rate limit exceeded")
        await plugin.on_model_error_callback(
            callback_context=mock_callback_context,
            llm_request=llm_request,
            error=error,
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM telemetry").fetchone()
        assert row["status"] == "error"
        assert row["error_type"] == "RuntimeError"
        assert "rate limit" in row["error_message"]
        conn.close()


class TestToolTelemetry:
    """Tests 9-10: Tool telemetry creation and closing."""

    @pytest.mark.asyncio
    async def test_before_tool_creates_telemetry(
        self, plugin, db_path, mock_invocation_context
    ):
        """before_tool_callback inserts a telemetry row with event_type='tool_call'."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        tool = MagicMock()
        tool.name = "code_executor"
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
        assert rows[0]["event_type"] == "tool_call"
        assert rows[0]["tool_name"] == "code_executor"
        assert "code" in json.loads(rows[0]["tool_args_keys"])
        conn.close()

    @pytest.mark.asyncio
    async def test_after_tool_updates_telemetry(
        self, plugin, db_path, mock_invocation_context
    ):
        """after_tool_callback updates the telemetry row with result preview."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        tool = MagicMock()
        tool.name = "code_executor"
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


class TestEventCallback:
    """Test 11: Event callback with artifact delta and state delta."""

    @pytest.mark.asyncio
    async def test_on_event_artifact_delta(
        self, plugin, db_path, mock_invocation_context
    ):
        """on_event_callback with artifact_delta creates session_state_events rows."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        event = MagicMock()
        event.actions.artifact_delta = {"output.txt": 0}
        event.actions.state_delta = None
        event.author = "reasoning_agent"
        await plugin.on_event_callback(
            invocation_context=mock_invocation_context, event=event
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM session_state_events").fetchall()
        assert len(rows) == 1
        assert rows[0]["state_key"] == "artifact_output.txt"
        assert rows[0]["event_author"] == "reasoning_agent"
        conn.close()

    @pytest.mark.asyncio
    async def test_on_event_without_artifact_delta_no_sse(
        self, plugin, db_path, mock_invocation_context
    ):
        """on_event_callback without artifact_delta or state_delta does NOT create rows."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        event = MagicMock()
        event.actions.artifact_delta = None
        event.actions.state_delta = None
        event.author = "reasoning_agent"
        await plugin.on_event_callback(
            invocation_context=mock_invocation_context, event=event
        )
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM session_state_events").fetchall()
        assert len(rows) == 0
        conn.close()


class TestAgentNameInTelemetry:
    """Test 12: Agent name is captured in telemetry rows."""

    @pytest.mark.asyncio
    async def test_model_telemetry_captures_agent_name(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """Model telemetry within an agent captures that agent's name."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        agent = MagicMock()
        agent.name = "reasoning_agent"
        await plugin.before_agent_callback(
            agent=agent, callback_context=mock_callback_context
        )
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM telemetry").fetchone()
        assert row["agent_name"] == "reasoning_agent"
        conn.close()

    @pytest.mark.asyncio
    async def test_nested_agent_captures_innermost_name(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """Nested agents: telemetry captures the innermost agent name."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        outer_agent = MagicMock()
        outer_agent.name = "orchestrator"
        await plugin.before_agent_callback(
            agent=outer_agent, callback_context=mock_callback_context
        )
        inner_agent = MagicMock()
        inner_agent.name = "worker"
        await plugin.before_agent_callback(
            agent=inner_agent, callback_context=mock_callback_context
        )
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM telemetry").fetchone()
        assert row["agent_name"] == "worker"
        conn.close()


class TestDirectoryCreation:
    """Test 13: Plugin creates parent directories for db_path."""

    def test_db_path_directory_creation(self, tmp_path):
        """Plugin creates parent directories for db_path if they don't exist."""
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

        nested_path = str(tmp_path / "deep" / "nested" / "dir" / "traces.db")
        plugin = SqliteTracingPlugin(db_path=nested_path)
        assert plugin._conn is not None
        import os
        assert os.path.isdir(str(tmp_path / "deep" / "nested" / "dir"))


class TestCallbackReturnValues:
    """Test 14: All callbacks return None (observe-only)."""

    @pytest.mark.asyncio
    async def test_all_callbacks_return_none(
        self, plugin, mock_invocation_context, mock_callback_context
    ):
        """Every callback returns None so the plugin never short-circuits execution."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )

        agent = MagicMock()
        agent.name = "a"
        assert (
            await plugin.before_agent_callback(
                agent=agent, callback_context=mock_callback_context
            )
            is None
        )
        assert (
            await plugin.after_agent_callback(
                agent=agent, callback_context=mock_callback_context
            )
            is None
        )

        llm_request = MagicMock()
        llm_request.model = "m"
        llm_request.contents = []
        assert (
            await plugin.before_model_callback(
                callback_context=mock_callback_context,
                llm_request=llm_request,
            )
            is None
        )

        llm_response = MagicMock()
        llm_response.model_version = "m"
        llm_response.usage_metadata = None
        llm_response.error_code = None
        llm_response.finish_reason = None
        assert (
            await plugin.after_model_callback(
                callback_context=mock_callback_context,
                llm_response=llm_response,
            )
            is None
        )

        error = RuntimeError("test")
        assert (
            await plugin.on_model_error_callback(
                callback_context=mock_callback_context,
                llm_request=llm_request,
                error=error,
            )
            is None
        )

        tool = MagicMock()
        tool.name = "t"
        tool_context = MagicMock()
        assert (
            await plugin.before_tool_callback(
                tool=tool, tool_args={}, tool_context=tool_context
            )
            is None
        )
        assert (
            await plugin.after_tool_callback(
                tool=tool,
                tool_args={},
                tool_context=tool_context,
                result={},
            )
            is None
        )

        event = MagicMock()
        event.actions.artifact_delta = None
        event.actions.state_delta = None
        assert (
            await plugin.on_event_callback(
                invocation_context=mock_invocation_context, event=event
            )
            is None
        )


class TestErrorResilience:
    """Tests 15-16: Graceful degradation and connection cleanup."""

    @pytest.mark.asyncio
    async def test_db_error_does_not_crash(
        self, mock_invocation_context, mock_callback_context
    ):
        """Setting self._conn = None (simulating broken DB) and calling callbacks does not raise."""
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

        plugin = SqliteTracingPlugin(db_path="/dev/null/impossible/path.db")
        assert plugin._conn is None

        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        agent = MagicMock()
        agent.name = "a"
        await plugin.before_agent_callback(
            agent=agent, callback_context=mock_callback_context
        )
        await plugin.after_agent_callback(
            agent=agent, callback_context=mock_callback_context
        )

        llm_request = MagicMock()
        llm_request.model = "m"
        llm_request.contents = []
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )
        llm_response = MagicMock()
        llm_response.model_version = "m"
        llm_response.usage_metadata = None
        llm_response.error_code = None
        llm_response.finish_reason = None
        await plugin.after_model_callback(
            callback_context=mock_callback_context, llm_response=llm_response
        )

        await plugin.after_run_callback(
            invocation_context=mock_invocation_context
        )

    @pytest.mark.asyncio
    async def test_close_closes_connection(self, plugin):
        """After close(), the connection is None."""
        assert plugin._conn is not None
        await plugin.close()
        assert plugin._conn is None

    @pytest.mark.asyncio
    async def test_close_idempotent(self, plugin):
        """Calling close() twice does not raise."""
        await plugin.close()
        await plugin.close()
        assert plugin._conn is None

    @pytest.mark.asyncio
    async def test_callbacks_after_close_do_not_crash(
        self, plugin, mock_invocation_context, mock_callback_context
    ):
        """Calling callbacks after close() does not raise."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        await plugin.close()
        agent = MagicMock()
        agent.name = "a"
        await plugin.before_agent_callback(
            agent=agent, callback_context=mock_callback_context
        )
        await plugin.after_run_callback(
            invocation_context=mock_invocation_context
        )
