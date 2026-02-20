"""Tests for Rec 4: SqliteTracingPlugin.

Tests that the SqliteTracingPlugin correctly captures span-like telemetry data
from ADK callbacks and writes them to a local SQLite database.
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
        """Instantiating SqliteTracingPlugin creates both traces and spans tables."""
        conn = sqlite3.connect(db_path)
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "traces" in tables
        assert "spans" in tables
        conn.close()

    def test_wal_mode_enabled(self, db_path, plugin):
        """Database should use WAL journal mode for concurrent reads."""
        conn = sqlite3.connect(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_traces_table_columns(self, db_path, plugin):
        """Traces table has all expected columns."""
        conn = sqlite3.connect(db_path)
        columns = [
            row[1]
            for row in conn.execute("PRAGMA table_info(traces)").fetchall()
        ]
        expected = [
            "trace_id",
            "session_id",
            "user_id",
            "app_name",
            "start_time",
            "end_time",
            "status",
            "total_input_tokens",
            "total_output_tokens",
            "total_calls",
            "iterations",
            "final_answer_length",
            "metadata",
        ]
        assert columns == expected
        conn.close()

    def test_spans_table_columns(self, db_path, plugin):
        """Spans table has all expected columns."""
        conn = sqlite3.connect(db_path)
        columns = [
            row[1]
            for row in conn.execute("PRAGMA table_info(spans)").fetchall()
        ]
        expected = [
            "span_id",
            "trace_id",
            "parent_span_id",
            "operation_name",
            "agent_name",
            "start_time",
            "end_time",
            "status",
            "attributes",
            "events",
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
        rows = conn.execute("SELECT * FROM traces").fetchall()
        assert len(rows) == 1
        # Check status column (index 6 based on schema)
        assert rows[0][6] == "running"
        # Check session_id
        assert rows[0][1] == "sess_1"
        # Check user_id
        assert rows[0][2] == "user_1"
        # Check app_name
        assert rows[0][3] == "test_app"
        # Check start_time is set
        assert rows[0][4] is not None
        conn.close()

    @pytest.mark.asyncio
    async def test_after_run_updates_trace(
        self, plugin, db_path, mock_invocation_context
    ):
        """Calling after_run_callback updates trace with status='completed' and end_time."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        # Set some state values that after_run reads
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
        row = conn.execute(
            "SELECT status, end_time, total_input_tokens, total_output_tokens, "
            "total_calls, iterations, final_answer_length FROM traces"
        ).fetchone()
        assert row[0] == "completed"
        assert row[1] is not None  # end_time set
        assert row[2] == 500  # total_input_tokens
        assert row[3] == 250  # total_output_tokens
        assert row[4] == 3  # total_calls
        assert row[5] == 2  # iterations
        assert row[6] == len("The answer is 42.")  # final_answer_length
        conn.close()


class TestAgentSpans:
    """Tests 4-5: Agent span creation and closing."""

    @pytest.mark.asyncio
    async def test_before_agent_creates_span(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """before_agent_callback inserts a span with operation_name='agent'."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        agent = MagicMock()
        agent.name = "test_agent"
        await plugin.before_agent_callback(
            agent=agent, callback_context=mock_callback_context
        )
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT operation_name, agent_name FROM spans"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "agent"
        assert rows[0][1] == "test_agent"
        conn.close()

    @pytest.mark.asyncio
    async def test_after_agent_closes_span(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """after_agent_callback sets end_time on the matching agent span."""
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
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT end_time FROM spans").fetchone()
        assert row[0] is not None
        conn.close()


class TestModelSpans:
    """Tests 6-8: Model span creation, closing, and error handling."""

    @pytest.mark.asyncio
    async def test_before_model_creates_span(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """before_model_callback inserts a span with operation_name='model_call'."""
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
        rows = conn.execute(
            "SELECT operation_name, attributes FROM spans"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "model_call"
        attrs = json.loads(rows[0][1])
        assert attrs["model"] == "gemini-2.5-flash"
        conn.close()

    @pytest.mark.asyncio
    async def test_after_model_closes_span(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """after_model_callback updates the model span with token counts and end_time."""
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
        await plugin.after_model_callback(
            callback_context=mock_callback_context, llm_response=llm_response
        )
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT end_time, attributes FROM spans").fetchone()
        assert row[0] is not None
        attrs = json.loads(row[1])
        assert attrs["input_tokens"] == 100
        assert attrs["output_tokens"] == 50
        conn.close()

    @pytest.mark.asyncio
    async def test_model_error_marks_span_error(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """on_model_error_callback sets status='error' on the model span."""
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
        row = conn.execute("SELECT status, attributes FROM spans").fetchone()
        assert row[0] == "error"
        attrs = json.loads(row[1])
        assert attrs["error_type"] == "RuntimeError"
        assert "rate limit" in attrs["error_message"]
        conn.close()


class TestToolSpans:
    """Tests 9-10: Tool span creation and closing."""

    @pytest.mark.asyncio
    async def test_before_tool_creates_span(
        self, plugin, db_path, mock_invocation_context
    ):
        """before_tool_callback inserts a span with operation_name='tool_call'."""
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
        rows = conn.execute(
            "SELECT operation_name, attributes FROM spans"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "tool_call"
        attrs = json.loads(rows[0][1])
        assert attrs["tool_name"] == "code_executor"
        assert "code" in attrs["args_keys"]
        conn.close()

    @pytest.mark.asyncio
    async def test_after_tool_closes_span(
        self, plugin, db_path, mock_invocation_context
    ):
        """after_tool_callback updates the tool span with result preview."""
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
        row = conn.execute("SELECT end_time, attributes FROM spans").fetchone()
        assert row[0] is not None
        attrs = json.loads(row[1])
        assert "result_preview" in attrs
        conn.close()


class TestEventCallback:
    """Test 11: Event callback with artifact delta."""

    @pytest.mark.asyncio
    async def test_on_event_artifact_delta(
        self, plugin, db_path, mock_invocation_context
    ):
        """on_event_callback with artifact_delta creates an 'artifact_save' span."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        event = MagicMock()
        event.actions.artifact_delta = {"output.txt": 0}
        event.author = "reasoning_agent"
        await plugin.on_event_callback(
            invocation_context=mock_invocation_context, event=event
        )
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT operation_name, agent_name, attributes FROM spans"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "artifact_save"
        assert rows[0][1] == "reasoning_agent"
        attrs = json.loads(rows[0][2])
        assert "artifact_delta" in attrs
        assert attrs["artifact_delta"]["output.txt"] == 0
        conn.close()

    @pytest.mark.asyncio
    async def test_on_event_without_artifact_delta_no_span(
        self, plugin, db_path, mock_invocation_context
    ):
        """on_event_callback without artifact_delta does NOT create a span."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        event = MagicMock()
        event.actions.artifact_delta = None
        event.author = "reasoning_agent"
        await plugin.on_event_callback(
            invocation_context=mock_invocation_context, event=event
        )
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM spans").fetchall()
        assert len(rows) == 0
        conn.close()


class TestParentTracking:
    """Test 12: Agent span is parent of nested model/tool spans."""

    @pytest.mark.asyncio
    async def test_span_parent_tracking(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """Model spans within an agent span have that agent's span_id as parent."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        # Start agent span
        agent = MagicMock()
        agent.name = "reasoning_agent"
        await plugin.before_agent_callback(
            agent=agent, callback_context=mock_callback_context
        )
        # Start model span within agent
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )

        conn = sqlite3.connect(db_path)
        # Get the agent span_id
        agent_span = conn.execute(
            "SELECT span_id FROM spans WHERE operation_name='agent'"
        ).fetchone()
        # Get the model span's parent_span_id
        model_span = conn.execute(
            "SELECT parent_span_id FROM spans WHERE operation_name='model_call'"
        ).fetchone()
        assert model_span[0] == agent_span[0]
        conn.close()

    @pytest.mark.asyncio
    async def test_nested_agent_parent_tracking(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """Nested agents produce correct parent-child span relationships."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        # Outer agent
        outer_agent = MagicMock()
        outer_agent.name = "orchestrator"
        await plugin.before_agent_callback(
            agent=outer_agent, callback_context=mock_callback_context
        )
        # Inner agent
        inner_agent = MagicMock()
        inner_agent.name = "worker"
        await plugin.before_agent_callback(
            agent=inner_agent, callback_context=mock_callback_context
        )

        conn = sqlite3.connect(db_path)
        outer_span = conn.execute(
            "SELECT span_id FROM spans WHERE agent_name='orchestrator'"
        ).fetchone()
        inner_span = conn.execute(
            "SELECT parent_span_id FROM spans WHERE agent_name='worker'"
        ).fetchone()
        assert inner_span[0] == outer_span[0]
        conn.close()


class TestDirectoryCreation:
    """Test 13: Plugin creates parent directories for db_path."""

    def test_db_path_directory_creation(self, tmp_path):
        """Plugin creates parent directories for db_path if they don't exist."""
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

        nested_path = str(tmp_path / "deep" / "nested" / "dir" / "traces.db")
        plugin = SqliteTracingPlugin(db_path=nested_path)
        assert plugin._conn is not None
        # Verify the directory was created
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
        # _conn should be None due to init failure
        assert plugin._conn is None

        # All callbacks should silently succeed even with broken DB
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
        # These should silently no-op since conn is None
        agent = MagicMock()
        agent.name = "a"
        await plugin.before_agent_callback(
            agent=agent, callback_context=mock_callback_context
        )
        await plugin.after_run_callback(
            invocation_context=mock_invocation_context
        )
