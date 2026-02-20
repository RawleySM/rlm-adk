"""Tests for TraceReader - DuckDB analytical overlay on SQLite session data.

TDD: RED phase - these tests define the expected behavior of TraceReader.
"""

import json
import sqlite3
import time
import uuid

import pytest


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
