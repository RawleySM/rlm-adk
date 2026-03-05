"""Tests for TraceReader - DuckDB analytical overlay on SQLite session data.

TDD: RED phase - these tests define the expected behavior of TraceReader.
"""

import json
import sqlite3
import time
import uuid

import pytest

pytest.importorskip("duckdb", reason="duckdb not installed")


def _create_test_db(
    db_path: str,
    sessions: int = 1,
    events_per_session: int = 3,
    app_name: str = "test_app",
    user_id: str = "user_1",
):
    """Create a SQLite database with the SqliteSessionService schema and sample data."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS app_states (
            app_name TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            update_time REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_states (
            app_name TEXT NOT NULL,
            user_id TEXT NOT NULL,
            state TEXT NOT NULL,
            update_time REAL NOT NULL,
            PRIMARY KEY (app_name, user_id)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            app_name TEXT NOT NULL,
            user_id TEXT NOT NULL,
            id TEXT NOT NULL,
            state TEXT NOT NULL,
            create_time REAL NOT NULL,
            update_time REAL NOT NULL,
            PRIMARY KEY (app_name, user_id, id)
        );
        CREATE TABLE IF NOT EXISTS events (
            id TEXT NOT NULL,
            app_name TEXT NOT NULL,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            invocation_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            event_data TEXT NOT NULL,
            PRIMARY KEY (app_name, user_id, session_id, id),
            FOREIGN KEY (app_name, user_id, session_id)
                REFERENCES sessions(app_name, user_id, id) ON DELETE CASCADE
        );
    """)

    now = time.time()
    for s in range(sessions):
        session_id = f"session_{s + 1}"
        state = json.dumps({"iteration_count": events_per_session})
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
            (app_name, user_id, session_id, state, now, now),
        )
        for e in range(events_per_session):
            inv_id = f"inv_{(e // 2) + 1}"  # Group events by invocation
            event_data = json.dumps({
                "author": "reasoning_agent" if e % 2 == 0 else "rlm_orchestrator",
                "content": {"parts": [{"text": f"event {e}"}]},
            })
            conn.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), app_name, user_id, session_id,
                 inv_id, now + e, event_data),
            )

    conn.commit()
    conn.close()


# --- RED Tests ---


def test_trace_reader_raises_on_missing_db():
    """TraceReader raises FileNotFoundError for a non-existent database."""
    from rlm_adk.eval.trace_reader import TraceReader

    with pytest.raises(FileNotFoundError):
        TraceReader("/nonexistent/path.db")


def test_trace_reader_attaches_sqlite(tmp_path):
    """TraceReader can attach a valid SQLite file."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    reader = TraceReader(db_path)
    assert reader.conn is not None
    reader.close()


def test_trace_reader_context_manager(tmp_path):
    """TraceReader supports context manager protocol."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    with TraceReader(db_path) as reader:
        assert reader.conn is not None
    # After exit, conn should be None
    assert reader._conn is None


def test_trace_reader_list_sessions(tmp_path):
    """list_sessions returns session data with event counts."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=2, events_per_session=5)
    with TraceReader(db_path) as reader:
        sessions = reader.list_sessions("test_app")
    assert len(sessions) == 2
    assert all("event_count" in s for s in sessions)
    assert all(s["event_count"] == 5 for s in sessions)


def test_trace_reader_list_sessions_with_user_filter(tmp_path):
    """list_sessions filters by user_id when provided."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=1, user_id="user_1")
    with TraceReader(db_path) as reader:
        sessions = reader.list_sessions("test_app", user_id="user_1")
        assert len(sessions) == 1
        sessions_empty = reader.list_sessions("test_app", user_id="user_999")
        assert len(sessions_empty) == 0


def test_trace_reader_get_session_event_count(tmp_path):
    """get_session_event_count returns the correct count."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=7)
    with TraceReader(db_path) as reader:
        count = reader.get_session_event_count("test_app", "user_1", "session_1")
    assert count == 7


def test_trace_reader_get_session_state(tmp_path):
    """get_session_state returns parsed state dict."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=4)
    with TraceReader(db_path) as reader:
        state = reader.get_session_state("test_app", "user_1", "session_1")
    assert isinstance(state, dict)
    assert state["iteration_count"] == 4


def test_trace_reader_get_session_state_missing(tmp_path):
    """get_session_state returns empty dict for non-existent session."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    with TraceReader(db_path) as reader:
        state = reader.get_session_state("test_app", "user_1", "nonexistent")
    assert state == {}


def test_trace_reader_get_invocation_ids(tmp_path):
    """get_invocation_ids returns distinct invocation IDs in chronological order."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=6)  # inv_1 x2, inv_2 x2, inv_3 x2
    with TraceReader(db_path) as reader:
        inv_ids = reader.get_invocation_ids("test_app", "user_1", "session_1")
    assert inv_ids == ["inv_1", "inv_2", "inv_3"]


def test_trace_reader_get_events_raw(tmp_path):
    """get_events_raw returns all event data for a session."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=4)
    with TraceReader(db_path) as reader:
        events = reader.get_events_raw("test_app", "user_1", "session_1")
    assert len(events) == 4
    assert all("invocation_id" in e for e in events)
    # event_data should be parsed to dict
    assert all(isinstance(e["event_data"], dict) for e in events)


def test_trace_reader_get_events_raw_with_invocation_filter(tmp_path):
    """get_events_raw filters by invocation_id when provided."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=6)  # inv_1 x2, inv_2 x2, inv_3 x2
    with TraceReader(db_path) as reader:
        events = reader.get_events_raw(
            "test_app", "user_1", "session_1",
            invocation_id="inv_1"
        )
    assert all(e["invocation_id"] == "inv_1" for e in events)
    assert len(events) == 2


def test_trace_reader_get_events_raw_with_limit(tmp_path):
    """get_events_raw respects the limit parameter."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=10)
    with TraceReader(db_path) as reader:
        events = reader.get_events_raw(
            "test_app", "user_1", "session_1",
            limit=3
        )
    assert len(events) == 3


def test_trace_reader_execute_custom_query(tmp_path):
    """execute() returns results as list of dicts for custom SQL."""
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    with TraceReader(db_path) as reader:
        result = reader.execute("SELECT COUNT(*) AS cnt FROM sdb.sessions")
    assert result[0]["cnt"] == 1


# ---------------------------------------------------------------------------
# 3-table schema fixture (traces / telemetry / session_state_events)
# ---------------------------------------------------------------------------

_TRACING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS traces (
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
    metadata                TEXT,
    request_id              TEXT,
    repo_url                TEXT,
    root_prompt_preview     TEXT,
    total_execution_time_s  REAL,
    child_dispatch_count    INTEGER,
    child_error_counts      TEXT,
    structured_output_failures INTEGER,
    finish_safety_count     INTEGER,
    finish_recitation_count INTEGER,
    finish_max_tokens_count INTEGER,
    tool_invocation_summary TEXT,
    artifact_saves          INTEGER,
    artifact_bytes_saved    INTEGER,
    per_iteration_breakdown TEXT,
    model_usage_summary     TEXT
);

CREATE TABLE IF NOT EXISTS telemetry (
    telemetry_id    TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    agent_name      TEXT,
    iteration       INTEGER,
    depth           INTEGER DEFAULT 0,
    call_number     INTEGER,
    start_time      REAL NOT NULL,
    end_time        REAL,
    duration_ms     REAL,
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    finish_reason   TEXT,
    num_contents    INTEGER,
    agent_type      TEXT,
    prompt_chars    INTEGER,
    system_chars    INTEGER,
    tool_name       TEXT,
    tool_args_keys  TEXT,
    result_preview  TEXT,
    repl_has_errors     INTEGER,
    repl_has_output     INTEGER,
    repl_llm_calls      INTEGER,
    status          TEXT DEFAULT 'ok',
    error_type      TEXT,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS session_state_events (
    event_id        TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    event_author    TEXT,
    event_time      REAL NOT NULL,
    state_key       TEXT NOT NULL,
    key_category    TEXT NOT NULL,
    key_depth       INTEGER DEFAULT 0,
    key_fanout      INTEGER,
    value_type      TEXT,
    value_int       INTEGER,
    value_float     REAL,
    value_text      TEXT,
    value_json      TEXT
);
"""

# Fixed timestamps for deterministic tests
_T0 = 1700000000.0


def _create_tracing_db(db_path: str) -> str:
    """Create a SQLite database with the 3-table tracing schema and fixture data.

    Returns the trace_id used for all fixture rows.
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(_TRACING_SCHEMA_SQL)

    trace_id = "trace_abc123"

    # -- traces table: 2 traces (one completed, one running) --
    conn.execute(
        """INSERT INTO traces
           (trace_id, session_id, user_id, app_name, start_time, end_time,
            status, total_input_tokens, total_output_tokens, total_calls,
            iterations, final_answer_length, request_id, repo_url,
            total_execution_time_s, child_dispatch_count,
            child_error_counts, structured_output_failures,
            finish_safety_count, finish_recitation_count, finish_max_tokens_count,
            per_iteration_breakdown, model_usage_summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trace_id, "sess_1", "user_1", "rlm_app",
            _T0, _T0 + 120.0,
            "completed", 5000, 3000, 10,
            3, 1500, "req_001", "https://github.com/example/repo",
            120.0, 5,
            json.dumps({"RATE_LIMIT": 1, "SERVER": 2}), 1,
            0, 0, 1,
            json.dumps([
                {"iteration": 1, "input_tokens": 2000, "output_tokens": 1000, "duration_s": 40.0},
                {"iteration": 2, "input_tokens": 1500, "output_tokens": 1000, "duration_s": 35.0},
                {"iteration": 3, "input_tokens": 1500, "output_tokens": 1000, "duration_s": 45.0},
            ]),
            json.dumps({"gemini-3-pro": {"input_tokens": 5000, "output_tokens": 3000, "calls": 10}}),
        ),
    )
    conn.execute(
        """INSERT INTO traces
           (trace_id, session_id, user_id, app_name, start_time, status,
            total_input_tokens, total_output_tokens, total_calls, iterations)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("trace_running_1", "sess_2", "user_1", "rlm_app",
         _T0 + 200.0, "running", 0, 0, 0, 0),
    )

    # -- telemetry table: 5 model_call rows + 3 tool_call rows --
    for i in range(5):
        conn.execute(
            """INSERT INTO telemetry
               (telemetry_id, trace_id, event_type, agent_name, iteration,
                start_time, end_time, duration_ms, model,
                input_tokens, output_tokens, finish_reason, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"tel_model_{i}", trace_id, "model_call", "reasoning_agent",
                i // 2,  # iterations 0, 0, 1, 1, 2
                _T0 + i * 10, _T0 + i * 10 + 5, 5000.0,
                "gemini-3-pro" if i < 3 else "gemini-3-flash",
                1000, 600, "STOP", "ok",
            ),
        )
    # One model_call with error status
    conn.execute(
        """INSERT INTO telemetry
           (telemetry_id, trace_id, event_type, agent_name, iteration,
            start_time, end_time, duration_ms, model,
            input_tokens, output_tokens, finish_reason, status,
            error_type, error_message)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "tel_model_err", trace_id, "model_call", "reasoning_agent",
            2, _T0 + 55, _T0 + 56, 1000.0,
            "gemini-3-pro", 500, 0, None, "error",
            "ServerError", "503 Service Unavailable",
        ),
    )

    for i in range(3):
        conn.execute(
            """INSERT INTO telemetry
               (telemetry_id, trace_id, event_type, agent_name, iteration,
                start_time, end_time, duration_ms, tool_name,
                tool_args_keys, result_preview,
                repl_has_errors, repl_has_output, repl_llm_calls, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"tel_tool_{i}", trace_id, "tool_call", "reasoning_agent",
                i, _T0 + i * 10 + 6, _T0 + i * 10 + 8, 2000.0,
                "execute_code", '["code"]', f"result_{i}",
                0, 1, i, "ok",
            ),
        )

    # -- session_state_events table --
    sse_rows = [
        ("sse_1", trace_id, 0, "reasoning_agent", _T0 + 1,
         "iteration_count", "flow_control", 0, None,
         "int", 1, None, None, None),
        ("sse_2", trace_id, 1, "reasoning_agent", _T0 + 10,
         "iteration_count", "flow_control", 0, None,
         "int", 2, None, None, None),
        ("sse_3", trace_id, 2, "reasoning_agent", _T0 + 20,
         "iteration_count", "flow_control", 0, None,
         "int", 3, None, None, None),
        ("sse_4", trace_id, 3, "rlm_orchestrator", _T0 + 5,
         "obs:total_input_tokens", "obs_reasoning", 0, None,
         "int", 2000, None, None, None),
        ("sse_5", trace_id, 4, "rlm_orchestrator", _T0 + 15,
         "obs:total_input_tokens", "obs_reasoning", 0, None,
         "int", 3500, None, None, None),
        ("sse_6", trace_id, 5, "rlm_orchestrator", _T0 + 25,
         "obs:total_input_tokens", "obs_reasoning", 0, None,
         "int", 5000, None, None, None),
        ("sse_7", trace_id, 6, "worker_0", _T0 + 7,
         "obs:worker_error_counts", "obs_dispatch", 1, 0,
         "dict", None, None, None,
         json.dumps({"RATE_LIMIT": 1})),
        ("sse_8", trace_id, 7, "reasoning_agent", _T0 + 30,
         "final_answer", "flow_control", 0, None,
         "str", None, None, "The analysis shows...", None),
    ]
    conn.executemany(
        """INSERT INTO session_state_events
           (event_id, trace_id, seq, event_author, event_time,
            state_key, key_category, key_depth, key_fanout,
            value_type, value_int, value_float, value_text, value_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        sse_rows,
    )

    conn.commit()
    conn.close()
    return trace_id


# ---------------------------------------------------------------------------
# traces table tests
# ---------------------------------------------------------------------------


class TestListTraces:
    """Tests for TraceReader.list_traces()."""

    def test_list_traces_returns_all(self, tmp_path):
        """list_traces returns all traces ordered by start_time DESC."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            traces = reader.list_traces()
        assert len(traces) == 2
        # Most recent first
        assert traces[0]["trace_id"] == "trace_running_1"
        assert traces[1]["trace_id"] == "trace_abc123"

    def test_list_traces_with_limit(self, tmp_path):
        """list_traces respects limit parameter."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            traces = reader.list_traces(limit=1)
        assert len(traces) == 1

    def test_list_traces_with_status_filter(self, tmp_path):
        """list_traces filters by status."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            completed = reader.list_traces(status="completed")
            running = reader.list_traces(status="running")
        assert len(completed) == 1
        assert completed[0]["status"] == "completed"
        assert len(running) == 1
        assert running[0]["status"] == "running"


class TestGetTrace:
    """Tests for TraceReader.get_trace()."""

    def test_get_trace_returns_dict(self, tmp_path):
        """get_trace returns a single trace dict."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            trace = reader.get_trace(trace_id)
        assert trace is not None
        assert trace["trace_id"] == trace_id
        assert trace["status"] == "completed"
        assert trace["total_input_tokens"] == 5000

    def test_get_trace_returns_none_for_missing(self, tmp_path):
        """get_trace returns None for non-existent trace_id."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            trace = reader.get_trace("nonexistent_trace")
        assert trace is None


class TestGetTraceSummary:
    """Tests for TraceReader.get_trace_summary()."""

    def test_get_trace_summary_metrics(self, tmp_path):
        """get_trace_summary returns key metrics dict."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            summary = reader.get_trace_summary(trace_id)
        assert summary is not None
        assert summary["total_input_tokens"] == 5000
        assert summary["total_output_tokens"] == 3000
        assert summary["total_calls"] == 10
        assert summary["iterations"] == 3
        assert summary["status"] == "completed"
        assert summary["duration_s"] == pytest.approx(120.0)

    def test_get_trace_summary_returns_none_for_missing(self, tmp_path):
        """get_trace_summary returns None for non-existent trace_id."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            summary = reader.get_trace_summary("nonexistent")
        assert summary is None


# ---------------------------------------------------------------------------
# telemetry table tests
# ---------------------------------------------------------------------------


class TestGetTelemetry:
    """Tests for TraceReader.get_telemetry()."""

    def test_get_telemetry_all(self, tmp_path):
        """get_telemetry returns all telemetry rows for a trace."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            rows = reader.get_telemetry(trace_id)
        # 5 model_call + 1 error model_call + 3 tool_call = 9
        assert len(rows) == 9

    def test_get_telemetry_filter_model_call(self, tmp_path):
        """get_telemetry filters by event_type='model_call'."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            rows = reader.get_telemetry(trace_id, event_type="model_call")
        assert len(rows) == 6
        assert all(r["event_type"] == "model_call" for r in rows)

    def test_get_telemetry_filter_tool_call(self, tmp_path):
        """get_telemetry filters by event_type='tool_call'."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            rows = reader.get_telemetry(trace_id, event_type="tool_call")
        assert len(rows) == 3
        assert all(r["event_type"] == "tool_call" for r in rows)


class TestGetModelCalls:
    """Tests for TraceReader.get_model_calls()."""

    def test_get_model_calls(self, tmp_path):
        """get_model_calls returns only model_call telemetry."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            rows = reader.get_model_calls(trace_id)
        assert len(rows) == 6
        assert all(r["event_type"] == "model_call" for r in rows)


class TestGetToolCalls:
    """Tests for TraceReader.get_tool_calls()."""

    def test_get_tool_calls(self, tmp_path):
        """get_tool_calls returns only tool_call telemetry."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            rows = reader.get_tool_calls(trace_id)
        assert len(rows) == 3
        assert all(r["event_type"] == "tool_call" for r in rows)
        assert all(r["tool_name"] == "execute_code" for r in rows)


class TestGetTokenUsage:
    """Tests for TraceReader.get_token_usage()."""

    def test_get_token_usage_totals(self, tmp_path):
        """get_token_usage returns total and per-model token breakdown."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            usage = reader.get_token_usage(trace_id)
        # 5 ok model_calls: 1000 input each + 1 error: 500 input = 5500
        assert usage["total_input_tokens"] == 5500
        # 5 ok model_calls: 600 output each + 1 error: 0 output = 3000
        assert usage["total_output_tokens"] == 3000
        # Per-model breakdown
        assert "per_model" in usage
        assert "gemini-3-pro" in usage["per_model"]
        assert "gemini-3-flash" in usage["per_model"]
        # gemini-3-pro: 3 ok calls (1000 each) + 1 error (500) = 3500 input
        assert usage["per_model"]["gemini-3-pro"]["input_tokens"] == 3500
        # gemini-3-flash: 2 ok calls (1000 each) = 2000 input
        assert usage["per_model"]["gemini-3-flash"]["input_tokens"] == 2000


class TestGetIterationTimeline:
    """Tests for TraceReader.get_iteration_timeline()."""

    def test_get_iteration_timeline(self, tmp_path):
        """get_iteration_timeline returns per-iteration timing and token counts."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            timeline = reader.get_iteration_timeline(trace_id)
        # Iterations 0, 1, 2
        assert len(timeline) == 3
        assert timeline[0]["iteration"] == 0
        assert timeline[1]["iteration"] == 1
        assert timeline[2]["iteration"] == 2
        # Each iteration should have token sums and call counts
        for entry in timeline:
            assert "total_input_tokens" in entry
            assert "total_output_tokens" in entry
            assert "model_calls" in entry
            assert "tool_calls" in entry


# ---------------------------------------------------------------------------
# session_state_events table tests
# ---------------------------------------------------------------------------


class TestGetStateEvents:
    """Tests for TraceReader.get_state_events()."""

    def test_get_state_events_all(self, tmp_path):
        """get_state_events returns all state events for a trace."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            events = reader.get_state_events(trace_id)
        assert len(events) == 8

    def test_get_state_events_filter_by_category(self, tmp_path):
        """get_state_events filters by key_category."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            flow = reader.get_state_events(trace_id, key_category="flow_control")
            obs = reader.get_state_events(trace_id, key_category="obs_reasoning")
            dispatch = reader.get_state_events(trace_id, key_category="obs_dispatch")
        # 3 iteration_count + 1 final_answer = 4 flow_control
        assert len(flow) == 4
        # 3 obs:total_input_tokens = 3 obs_reasoning
        assert len(obs) == 3
        # 1 obs:worker_error_counts = 1 obs_dispatch
        assert len(dispatch) == 1

    def test_get_state_events_filter_by_state_key(self, tmp_path):
        """get_state_events filters by specific state_key."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            events = reader.get_state_events(trace_id, state_key="iteration_count")
        assert len(events) == 3
        assert all(e["state_key"] == "iteration_count" for e in events)


class TestGetStateKeyHistory:
    """Tests for TraceReader.get_state_key_history()."""

    def test_get_state_key_history_ordered(self, tmp_path):
        """get_state_key_history returns ordered value changes."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            history = reader.get_state_key_history(trace_id, "iteration_count")
        assert len(history) == 3
        # Values should be in chronological order (seq order)
        assert history[0]["value_int"] == 1
        assert history[1]["value_int"] == 2
        assert history[2]["value_int"] == 3

    def test_get_state_key_history_empty_for_unknown_key(self, tmp_path):
        """get_state_key_history returns empty list for non-existent key."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            history = reader.get_state_key_history(trace_id, "nonexistent_key")
        assert history == []


class TestGetErrorSummary:
    """Tests for TraceReader.get_error_summary()."""

    def test_get_error_summary(self, tmp_path):
        """get_error_summary returns error counts from telemetry and state events."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        trace_id = _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            errors = reader.get_error_summary(trace_id)
        # 1 telemetry error (ServerError)
        assert errors["telemetry_errors"] == 1
        assert "ServerError" in errors["error_types"]
        # worker_error_counts from SSE
        assert "worker_error_counts" in errors

    def test_get_error_summary_empty_for_clean_trace(self, tmp_path):
        """get_error_summary returns zeros for a trace with no errors."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "traces.db")
        _create_tracing_db(db_path)
        with TraceReader(db_path) as reader:
            errors = reader.get_error_summary("trace_running_1")
        assert errors["telemetry_errors"] == 0


# ---------------------------------------------------------------------------
# Graceful handling: DB with only session tables (no tracing tables)
# ---------------------------------------------------------------------------


class TestMissingTablesGraceful:
    """New methods should handle missing tracing tables gracefully."""

    def test_list_traces_on_session_only_db(self, tmp_path):
        """list_traces returns empty list when traces table does not exist."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "session_only.db")
        _create_test_db(db_path)  # Only session/events tables
        with TraceReader(db_path) as reader:
            traces = reader.list_traces()
        assert traces == []

    def test_get_telemetry_on_session_only_db(self, tmp_path):
        """get_telemetry returns empty list when telemetry table does not exist."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "session_only.db")
        _create_test_db(db_path)
        with TraceReader(db_path) as reader:
            rows = reader.get_telemetry("any_trace")
        assert rows == []

    def test_get_state_events_on_session_only_db(self, tmp_path):
        """get_state_events returns empty list when session_state_events table does not exist."""
        from rlm_adk.eval.trace_reader import TraceReader

        db_path = str(tmp_path / "session_only.db")
        _create_test_db(db_path)
        with TraceReader(db_path) as reader:
            events = reader.get_state_events("any_trace")
        assert events == []
