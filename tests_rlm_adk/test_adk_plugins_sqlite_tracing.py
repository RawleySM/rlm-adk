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
                     "child_error_counts", "child_total_batch_dispatches",
                     "structured_output_failures",
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
            "obs:child_total_batch_dispatches": 1,
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
        assert row["child_total_batch_dispatches"] == 1
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

    @pytest.mark.asyncio
    async def test_same_model_calls_pair_by_callback_context_not_model_name(
        self, plugin, db_path, mock_invocation_context
    ):
        """Out-of-order same-model completions should update the correct rows."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        first_ctx = MagicMock()
        first_ctx.state = {}
        first_ctx._invocation_context = MagicMock()
        second_ctx = MagicMock()
        second_ctx.state = {}
        second_ctx._invocation_context = MagicMock()

        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []

        await plugin.before_model_callback(
            callback_context=first_ctx,
            llm_request=llm_request,
        )
        await plugin.before_model_callback(
            callback_context=second_ctx,
            llm_request=llm_request,
        )

        second_response = MagicMock()
        second_response.model_version = "gemini-2.5-flash"
        second_response.usage_metadata = MagicMock()
        second_response.usage_metadata.prompt_token_count = 200
        second_response.usage_metadata.candidates_token_count = 100
        second_response.usage_metadata.thoughts_token_count = 20
        second_response.error_code = None
        second_response.finish_reason = MagicMock()
        second_response.finish_reason.name = "STOP"

        first_response = MagicMock()
        first_response.model_version = "gemini-2.5-flash"
        first_response.usage_metadata = MagicMock()
        first_response.usage_metadata.prompt_token_count = 100
        first_response.usage_metadata.candidates_token_count = 50
        first_response.usage_metadata.thoughts_token_count = 10
        first_response.error_code = None
        first_response.finish_reason = MagicMock()
        first_response.finish_reason.name = "STOP"

        await plugin.after_model_callback(
            callback_context=second_ctx,
            llm_response=second_response,
        )
        await plugin.after_model_callback(
            callback_context=first_ctx,
            llm_response=first_response,
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT input_tokens, output_tokens, thought_tokens
            FROM telemetry
            WHERE event_type = 'model_call'
            ORDER BY rowid
            """
        ).fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0]["input_tokens"] == 100
        assert rows[0]["output_tokens"] == 50
        assert rows[0]["thought_tokens"] == 10
        assert rows[1]["input_tokens"] == 200
        assert rows[1]["output_tokens"] == 100
        assert rows[1]["thought_tokens"] == 20


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

    @pytest.mark.asyncio
    async def test_same_tool_calls_pair_by_tool_context_not_tool_name(
        self, plugin, db_path, mock_invocation_context
    ):
        """Out-of-order same-tool completions should update the correct rows."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        tool = MagicMock()
        tool.name = "execute_code"
        tool._depth = 0
        first_tool_context = MagicMock()
        first_tool_context.state = {
            "last_repl_result": {
                "has_errors": False,
                "has_output": True,
                "total_llm_calls": 1,
            }
        }
        second_tool_context = MagicMock()
        second_tool_context.state = {
            "last_repl_result": {
                "has_errors": True,
                "has_output": False,
                "total_llm_calls": 2,
            }
        }

        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "print('first')"},
            tool_context=first_tool_context,
        )
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"code": "print('second')"},
            tool_context=second_tool_context,
        )

        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"code": "print('second')"},
            tool_context=second_tool_context,
            result={"stdout": "", "stderr": "boom", "llm_calls_made": True},
        )
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"code": "print('first')"},
            tool_context=first_tool_context,
            result={"stdout": "ok\n", "stderr": "", "llm_calls_made": False},
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT repl_has_errors, repl_has_output, repl_llm_calls,
                   repl_stdout_len, repl_stderr_len
            FROM telemetry
            WHERE event_type = 'tool_call'
            ORDER BY rowid
            """
        ).fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0]["repl_has_errors"] == 0
        assert rows[0]["repl_has_output"] == 1
        assert rows[0]["repl_llm_calls"] == 1
        assert rows[0]["repl_stdout_len"] == 3
        assert rows[0]["repl_stderr_len"] == 0
        assert rows[1]["repl_has_errors"] == 1
        assert rows[1]["repl_has_output"] == 0
        assert rows[1]["repl_llm_calls"] == 2
        assert rows[1]["repl_stdout_len"] == 0
        assert rows[1]["repl_stderr_len"] == 4


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

    @pytest.mark.asyncio
    async def test_on_event_persists_child_summary_contract_for_sql_queries(
        self, plugin, db_path, mock_invocation_context
    ):
        """obs:child_summary payloads retain depth/fanout and structured-output fields."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        event = MagicMock()
        event.actions.artifact_delta = None
        event.actions.state_delta = {
            "obs:child_summary@d1f2": {
                "model": "gemini-2.5-flash",
                "error": True,
                "error_category": "SCHEMA_VALIDATION_EXHAUSTED",
                "structured_output": {
                    "expected": True,
                    "schema_name": "SentimentResult",
                    "attempts": 3,
                    "retry_count": 2,
                    "outcome": "retry_exhausted",
                    "validated_result": None,
                },
            }
        }
        event.author = "orchestrator"
        await plugin.on_event_callback(
            invocation_context=mock_invocation_context, event=event
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT state_key, key_depth, key_fanout, value_json
            FROM session_state_events
            WHERE state_key = 'obs:child_summary'
            """
        ).fetchone()
        conn.close()

        payload = json.loads(row["value_json"])
        assert row["state_key"] == "obs:child_summary"
        assert row["key_depth"] == 1
        assert row["key_fanout"] == 2
        assert payload["error_category"] == "SCHEMA_VALIDATION_EXHAUSTED"
        assert payload["structured_output"]["outcome"] == "retry_exhausted"
        assert payload["structured_output"]["attempts"] == 3


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


class TestSchemaMigration:
    """Test schema migration adds missing columns to existing tables."""

    def test_migrate_adds_enriched_columns_to_old_schema(self, tmp_path):
        """Opening a plugin against a DB with only base columns adds enriched columns."""
        db_file = str(tmp_path / "old_traces.db")
        # Create a DB with only the 13 base columns (simulates old schema)
        conn = sqlite3.connect(db_file)
        conn.executescript("""
            CREATE TABLE traces (
                trace_id                TEXT PRIMARY KEY,
                session_id              TEXT NOT NULL,
                user_id                 TEXT,
                app_name                TEXT,
                start_time              REAL NOT NULL,
                end_time                REAL,
                status                  TEXT DEFAULT 'running',
                total_input_tokens      INTEGER DEFAULT 0,
                total_output_tokens     INTEGER DEFAULT 0,
                total_calls             INTEGER DEFAULT 0,
                iterations              INTEGER DEFAULT 0,
                final_answer_length     INTEGER,
                metadata                TEXT
            );
            CREATE TABLE telemetry (
                telemetry_id    TEXT PRIMARY KEY,
                trace_id        TEXT NOT NULL,
                event_type      TEXT NOT NULL,
                start_time      REAL NOT NULL
            );
            CREATE TABLE session_state_events (
                event_id        TEXT PRIMARY KEY,
                trace_id        TEXT NOT NULL,
                seq             INTEGER NOT NULL,
                state_key       TEXT NOT NULL,
                key_category    TEXT NOT NULL,
                event_time      REAL NOT NULL
            );
            CREATE TABLE spans (
                span_id         TEXT PRIMARY KEY,
                trace_id        TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()

        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
        plugin = SqliteTracingPlugin(db_path=db_file)

        # Verify enriched columns were added to traces
        verify_conn = sqlite3.connect(db_file)
        columns = [
            row[1]
            for row in verify_conn.execute("PRAGMA table_info(traces)").fetchall()
        ]
        for col in ["request_id", "repo_url", "root_prompt_preview",
                     "total_execution_time_s", "child_dispatch_count",
                     "child_total_batch_dispatches", "child_error_counts",
                     "structured_output_failures",
                     "finish_safety_count", "finish_recitation_count",
                     "finish_max_tokens_count", "tool_invocation_summary",
                     "artifact_saves", "artifact_bytes_saved",
                     "per_iteration_breakdown", "model_usage_summary"]:
            assert col in columns, f"Missing enriched column: {col}"
        verify_conn.close()

    @pytest.mark.asyncio
    async def test_after_run_succeeds_on_migrated_schema(self, tmp_path):
        """after_run_callback successfully writes enriched columns after migration."""
        db_file = str(tmp_path / "old_traces.db")
        # Create old-schema DB
        conn = sqlite3.connect(db_file)
        conn.executescript("""
            CREATE TABLE traces (
                trace_id                TEXT PRIMARY KEY,
                session_id              TEXT NOT NULL,
                user_id                 TEXT,
                app_name                TEXT,
                start_time              REAL NOT NULL,
                end_time                REAL,
                status                  TEXT DEFAULT 'running',
                total_input_tokens      INTEGER DEFAULT 0,
                total_output_tokens     INTEGER DEFAULT 0,
                total_calls             INTEGER DEFAULT 0,
                iterations              INTEGER DEFAULT 0,
                final_answer_length     INTEGER,
                metadata                TEXT
            );
            CREATE TABLE telemetry (
                telemetry_id TEXT PRIMARY KEY, trace_id TEXT, event_type TEXT, start_time REAL
            );
            CREATE TABLE session_state_events (
                event_id TEXT PRIMARY KEY, trace_id TEXT, seq INTEGER, state_key TEXT,
                key_category TEXT, event_time REAL
            );
            CREATE TABLE spans (span_id TEXT PRIMARY KEY, trace_id TEXT);
        """)
        conn.commit()
        conn.close()

        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
        plugin = SqliteTracingPlugin(db_path=db_file)

        inv_ctx = MagicMock()
        inv_ctx.session.id = "sess_1"
        inv_ctx.session.user_id = "user_1"
        inv_ctx.app_name = "test_app"
        inv_ctx.session.state = {}

        await plugin.before_run_callback(invocation_context=inv_ctx)

        inv_ctx.session.state = {
            "obs:total_input_tokens": 1000,
            "obs:total_output_tokens": 500,
            "obs:total_calls": 5,
            "iteration_count": 3,
            "final_answer": "done",
            "request_id": "req-123",
            "obs:total_execution_time": 12.5,
            "obs:child_dispatch_count": 7,
            "obs:child_total_batch_dispatches": 2,
        }
        await plugin.after_run_callback(invocation_context=inv_ctx)

        verify_conn = sqlite3.connect(db_file)
        verify_conn.row_factory = sqlite3.Row
        row = verify_conn.execute("SELECT * FROM traces").fetchone()
        assert row["status"] == "completed"
        assert row["total_input_tokens"] == 1000
        assert row["request_id"] == "req-123"
        assert row["child_dispatch_count"] == 7
        assert row["child_total_batch_dispatches"] == 2
        verify_conn.close()

    def test_migrate_adds_missing_telemetry_columns(self, tmp_path):
        """Migration adds missing columns to telemetry table too."""
        db_file = str(tmp_path / "old_traces.db")
        conn = sqlite3.connect(db_file)
        conn.executescript("""
            CREATE TABLE traces (
                trace_id TEXT PRIMARY KEY, session_id TEXT, start_time REAL
            );
            CREATE TABLE telemetry (
                telemetry_id TEXT PRIMARY KEY, trace_id TEXT, event_type TEXT, start_time REAL
            );
            CREATE TABLE session_state_events (
                event_id TEXT PRIMARY KEY, trace_id TEXT, seq INTEGER, state_key TEXT,
                key_category TEXT, event_time REAL
            );
            CREATE TABLE spans (span_id TEXT PRIMARY KEY, trace_id TEXT);
        """)
        conn.commit()
        conn.close()

        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
        plugin = SqliteTracingPlugin(db_path=db_file)

        verify_conn = sqlite3.connect(db_file)
        columns = [
            row[1]
            for row in verify_conn.execute("PRAGMA table_info(telemetry)").fetchall()
        ]
        for col in ["agent_name", "model", "input_tokens", "output_tokens",
                     "thought_tokens", "agent_type", "prompt_chars",
                     "system_chars", "call_number", "repl_stdout_len",
                     "repl_stderr_len"]:
            assert col in columns, f"Missing telemetry column: {col}"
        verify_conn.close()


class TestTelemetryColumnPopulation:
    """Test that agent_type, prompt_chars, system_chars, call_number are populated."""

    @pytest.mark.asyncio
    async def test_agent_type_populated_from_context_snapshot(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """agent_type is populated from CONTEXT_WINDOW_SNAPSHOT in state."""
        await plugin.before_run_callback(invocation_context=mock_invocation_context)

        mock_callback_context.state = {
            "iteration_count": 1,
            "context_window_snapshot": {"agent_type": "reasoning", "prompt_chars": 500, "system_chars": 200},
        }
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = [MagicMock()]
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM telemetry").fetchone()
        assert row["agent_type"] == "reasoning"
        assert row["prompt_chars"] == 500
        assert row["system_chars"] == 200
        conn.close()

    @pytest.mark.asyncio
    async def test_call_number_populated_from_obs_total_calls(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """call_number is populated from OBS_TOTAL_CALLS in state."""
        await plugin.before_run_callback(invocation_context=mock_invocation_context)

        mock_callback_context.state = {
            "iteration_count": 0,
            "obs:total_calls": 5,
        }
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM telemetry").fetchone()
        assert row["call_number"] == 5
        conn.close()


class TestConfigPersistence:
    """Tests for config_json column in traces table."""

    @pytest.mark.asyncio
    async def test_config_json_column_exists(self, db_path, plugin):
        """traces table has a config_json column."""
        conn = sqlite3.connect(db_path)
        columns = [
            row[1]
            for row in conn.execute("PRAGMA table_info(traces)").fetchall()
        ]
        assert "config_json" in columns
        conn.close()

    @pytest.mark.asyncio
    async def test_before_run_stores_config_from_state(
        self, plugin, db_path, mock_invocation_context
    ):
        """before_run_callback stores config_json with max_depth and max_iterations from state."""
        mock_invocation_context.session.state = {
            "app:max_depth": 3,
            "app:max_iterations": 10,
        }
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traces").fetchone()
        config = json.loads(row["config_json"])
        assert config["max_depth"] == 3
        assert config["max_iterations"] == 10
        conn.close()

    @pytest.mark.asyncio
    async def test_before_run_stores_config_from_env(
        self, plugin, db_path, mock_invocation_context, monkeypatch
    ):
        """before_run_callback captures env vars in config_json."""
        monkeypatch.setenv("RLM_MAX_DEPTH", "4")
        monkeypatch.setenv("RLM_MAX_CONCURRENT_CHILDREN", "8")
        monkeypatch.setenv("RLM_WORKER_TIMEOUT", "30")
        monkeypatch.setenv("RLM_ADK_MODEL", "gemini-3-pro")
        mock_invocation_context.session.state = {}
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traces").fetchone()
        config = json.loads(row["config_json"])
        assert config["env_RLM_MAX_DEPTH"] == "4"
        assert config["env_RLM_MAX_CONCURRENT_CHILDREN"] == "8"
        assert config["env_RLM_WORKER_TIMEOUT"] == "30"
        assert config["env_RLM_ADK_MODEL"] == "gemini-3-pro"
        conn.close()

    @pytest.mark.asyncio
    async def test_config_json_none_when_no_config(
        self, plugin, db_path, mock_invocation_context
    ):
        """config_json is still valid JSON even when no config keys are set."""
        mock_invocation_context.session.state = {}
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traces").fetchone()
        config = json.loads(row["config_json"])
        assert isinstance(config, dict)
        conn.close()


class TestPromptHash:
    """Tests for prompt_hash column in traces table."""

    @pytest.mark.asyncio
    async def test_prompt_hash_column_exists(self, db_path, plugin):
        """traces table has a prompt_hash column."""
        conn = sqlite3.connect(db_path)
        columns = [
            row[1]
            for row in conn.execute("PRAGMA table_info(traces)").fetchall()
        ]
        assert "prompt_hash" in columns
        conn.close()

    @pytest.mark.asyncio
    async def test_after_run_stores_prompt_hash(
        self, plugin, db_path, mock_invocation_context
    ):
        """after_run_callback computes sha256 of root_prompt and stores as prompt_hash."""
        import hashlib

        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        mock_invocation_context.session.state = {
            "root_prompt": "Analyze this repository",
            "final_answer": "done",
        }
        await plugin.after_run_callback(
            invocation_context=mock_invocation_context
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traces").fetchone()
        expected_hash = hashlib.sha256("Analyze this repository".encode()).hexdigest()
        assert row["prompt_hash"] == expected_hash
        conn.close()

    @pytest.mark.asyncio
    async def test_prompt_hash_null_when_no_prompt(
        self, plugin, db_path, mock_invocation_context
    ):
        """prompt_hash is NULL when root_prompt is not in state."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        mock_invocation_context.session.state = {}
        await plugin.after_run_callback(
            invocation_context=mock_invocation_context
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traces").fetchone()
        assert row["prompt_hash"] is None
        conn.close()

    @pytest.mark.asyncio
    async def test_same_prompt_same_hash(
        self, plugin, db_path, mock_invocation_context
    ):
        """Two runs with the same root_prompt produce the same prompt_hash."""
        import hashlib

        prompt = "Analyze this repo for bugs"

        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        mock_invocation_context.session.state = {"root_prompt": prompt}
        await plugin.after_run_callback(
            invocation_context=mock_invocation_context
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT prompt_hash FROM traces").fetchone()
        expected = hashlib.sha256(prompt.encode()).hexdigest()
        assert row["prompt_hash"] == expected
        conn.close()


class TestMaxDepthReached:
    """Tests for max_depth_reached column in traces table."""

    @pytest.mark.asyncio
    async def test_max_depth_reached_column_exists(self, db_path, plugin):
        """traces table has a max_depth_reached column."""
        conn = sqlite3.connect(db_path)
        columns = [
            row[1]
            for row in conn.execute("PRAGMA table_info(traces)").fetchall()
        ]
        assert "max_depth_reached" in columns
        conn.close()

    @pytest.mark.asyncio
    async def test_max_depth_from_telemetry_agent_names(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """after_run computes max_depth_reached from telemetry agent_name patterns."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        # Simulate model calls at different depths via agent name stack
        for agent_name in ["reasoning_agent", "child_reasoning_d1", "child_reasoning_d2"]:
            plugin._agent_span_stack.clear()
            plugin._agent_span_stack.append(agent_name)
            llm_request = MagicMock()
            llm_request.model = "gemini-2.5-flash"
            llm_request.contents = []
            await plugin.before_model_callback(
                callback_context=mock_callback_context, llm_request=llm_request
            )
            llm_response = MagicMock()
            llm_response.model_version = "gemini-2.5-flash"
            llm_response.usage_metadata = None
            llm_response.error_code = None
            llm_response.finish_reason = None
            await plugin.after_model_callback(
                callback_context=mock_callback_context, llm_response=llm_response
            )

        mock_invocation_context.session.state = {}
        await plugin.after_run_callback(
            invocation_context=mock_invocation_context
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traces").fetchone()
        assert row["max_depth_reached"] == 2
        conn.close()

    @pytest.mark.asyncio
    async def test_max_depth_zero_when_no_children(
        self, plugin, db_path, mock_invocation_context, mock_callback_context
    ):
        """max_depth_reached is 0 when only reasoning_agent (depth 0) ran."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        plugin._agent_span_stack.append("reasoning_agent")
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
        await plugin.before_model_callback(
            callback_context=mock_callback_context, llm_request=llm_request
        )
        llm_response = MagicMock()
        llm_response.model_version = "gemini-2.5-flash"
        llm_response.usage_metadata = None
        llm_response.error_code = None
        llm_response.finish_reason = None
        await plugin.after_model_callback(
            callback_context=mock_callback_context, llm_response=llm_response
        )

        mock_invocation_context.session.state = {}
        await plugin.after_run_callback(
            invocation_context=mock_invocation_context
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traces").fetchone()
        assert row["max_depth_reached"] == 0
        conn.close()

    @pytest.mark.asyncio
    async def test_max_depth_null_when_no_telemetry(
        self, plugin, db_path, mock_invocation_context
    ):
        """max_depth_reached is 0 when no telemetry rows exist."""
        await plugin.before_run_callback(
            invocation_context=mock_invocation_context
        )
        mock_invocation_context.session.state = {}
        await plugin.after_run_callback(
            invocation_context=mock_invocation_context
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traces").fetchone()
        assert row["max_depth_reached"] == 0
        conn.close()


class TestMigrationNewColumns:
    """Test that schema migration picks up the new columns."""

    def test_migrate_adds_config_prompt_depth_columns(self, tmp_path):
        """Migration adds config_json, prompt_hash, max_depth_reached to old schema."""
        db_file = str(tmp_path / "old_traces.db")
        conn = sqlite3.connect(db_file)
        conn.executescript("""
            CREATE TABLE traces (
                trace_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                user_id TEXT, app_name TEXT, start_time REAL NOT NULL,
                end_time REAL, status TEXT DEFAULT 'running',
                total_input_tokens INTEGER DEFAULT 0,
                total_output_tokens INTEGER DEFAULT 0,
                total_calls INTEGER DEFAULT 0, iterations INTEGER DEFAULT 0,
                final_answer_length INTEGER, metadata TEXT
            );
            CREATE TABLE telemetry (
                telemetry_id TEXT PRIMARY KEY, trace_id TEXT, event_type TEXT, start_time REAL
            );
            CREATE TABLE session_state_events (
                event_id TEXT PRIMARY KEY, trace_id TEXT, seq INTEGER,
                state_key TEXT, key_category TEXT, event_time REAL
            );
            CREATE TABLE spans (span_id TEXT PRIMARY KEY, trace_id TEXT);
        """)
        conn.commit()
        conn.close()

        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
        plugin = SqliteTracingPlugin(db_path=db_file)

        verify_conn = sqlite3.connect(db_file)
        columns = [
            row[1]
            for row in verify_conn.execute("PRAGMA table_info(traces)").fetchall()
        ]
        assert "config_json" in columns
        assert "prompt_hash" in columns
        assert "max_depth_reached" in columns
        verify_conn.close()
