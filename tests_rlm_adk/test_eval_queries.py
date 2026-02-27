"""Tests for evaluation query functions (Rec 7).

TDD: RED phase - defines expected behavior of get_session_traces,
get_divergence_points, and compare_sessions.
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


def _create_test_db_asymmetric(
    db_path: str,
    events_a: int = 4,
    events_b: int = 6,
    app_name: str = "test_app",
    user_id: str = "user_1",
):
    """Create a DB with two sessions having different event counts."""
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
    for session_id, num_events in [("session_a", events_a), ("session_b", events_b)]:
        state = json.dumps({"iteration_count": num_events})
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
            (app_name, user_id, session_id, state, now, now),
        )
        for e in range(num_events):
            inv_id = f"inv_{(e // 2) + 1}"
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


def _create_test_db_divergent_authors(
    db_path: str,
    app_name: str = "test_app",
    user_id: str = "user_1",
):
    """Create a DB with two sessions that diverge in author sequences."""
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

    # Session A: inv_1 has author sequence [reasoning_agent, rlm_orchestrator]
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
        (app_name, user_id, "session_a", json.dumps({}), now, now),
    )
    for i, author in enumerate(["reasoning_agent", "rlm_orchestrator"]):
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), app_name, user_id, "session_a",
             "inv_1", now + i, json.dumps({"author": author})),
        )

    # Session B: inv_1 has author sequence [worker_agent, rlm_orchestrator]
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
        (app_name, user_id, "session_b", json.dumps({}), now, now),
    )
    for i, author in enumerate(["worker_agent", "rlm_orchestrator"]):
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), app_name, user_id, "session_b",
             "inv_1", now + i, json.dumps({"author": author})),
        )

    conn.commit()
    conn.close()


# --- RED Tests ---


def test_get_session_traces_returns_invocation_traces(tmp_path):
    """get_session_traces extracts invocation-level traces from a session."""
    from rlm_adk.eval.queries import InvocationTrace, get_session_traces
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=6)  # 3 invocations
    with TraceReader(db_path) as reader:
        traces = get_session_traces(reader, "test_app", "user_1", "session_1")
    assert len(traces) > 0
    assert all(isinstance(t, InvocationTrace) for t in traces)
    assert all(t.invocation_id for t in traces)


def test_get_session_traces_groups_by_invocation(tmp_path):
    """Each invocation trace contains the correct number of events."""
    from rlm_adk.eval.queries import get_session_traces
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=6)
    with TraceReader(db_path) as reader:
        traces = get_session_traces(reader, "test_app", "user_1", "session_1")
    # Each invocation should have 2 events (events grouped in pairs)
    for t in traces:
        assert len(t.events) == 2


def test_get_session_traces_has_timestamps(tmp_path):
    """Traces have valid timestamp_start and timestamp_end."""
    from rlm_adk.eval.queries import get_session_traces
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=4)
    with TraceReader(db_path) as reader:
        traces = get_session_traces(reader, "test_app", "user_1", "session_1")
    for t in traces:
        assert t.timestamp_start <= t.timestamp_end
        assert t.timestamp_start > 0


def test_get_session_traces_has_author_sequence(tmp_path):
    """Traces contain author sequences extracted from event data."""
    from rlm_adk.eval.queries import get_session_traces
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=4)
    with TraceReader(db_path) as reader:
        traces = get_session_traces(reader, "test_app", "user_1", "session_1")
    for t in traces:
        assert len(t.author_sequence) == len(t.events)
        assert all(isinstance(a, str) for a in t.author_sequence)


def test_get_divergence_points_identical_sessions(tmp_path):
    """Two identical sessions should have no divergence points."""
    from rlm_adk.eval.queries import get_divergence_points
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=2, events_per_session=4)
    with TraceReader(db_path) as reader:
        divergences = get_divergence_points(
            reader, "test_app", "user_1", "session_1", "session_2"
        )
    assert isinstance(divergences, list)
    # Identical sessions -> no divergence
    assert len(divergences) == 0


def test_get_divergence_points_length_mismatch(tmp_path):
    """Sessions with different invocation counts report length mismatch."""
    from rlm_adk.eval.queries import get_divergence_points
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db_asymmetric(db_path, events_a=4, events_b=6)
    with TraceReader(db_path) as reader:
        divergences = get_divergence_points(
            reader, "test_app", "user_1", "session_a", "session_b"
        )
    length_mismatches = [d for d in divergences if d.reason == "invocation_count_mismatch"]
    assert len(length_mismatches) == 1


def test_get_divergence_points_author_mismatch(tmp_path):
    """Divergence detected when author sequences differ."""
    from rlm_adk.eval.queries import get_divergence_points
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db_divergent_authors(db_path)
    with TraceReader(db_path) as reader:
        divergences = get_divergence_points(
            reader, "test_app", "user_1", "session_a", "session_b"
        )
    author_mismatches = [d for d in divergences if d.reason == "author_sequence_mismatch"]
    assert len(author_mismatches) >= 1


def test_compare_sessions_returns_summary(tmp_path):
    """compare_sessions produces a SessionComparison with summary metrics."""
    from rlm_adk.eval.queries import SessionComparison, compare_sessions
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=2, events_per_session=4)
    with TraceReader(db_path) as reader:
        comparison = compare_sessions(
            reader, "test_app", "user_1", "session_1", "session_2"
        )
    assert isinstance(comparison, SessionComparison)
    assert "invocations_a" in comparison.summary
    assert "invocations_b" in comparison.summary
    assert "divergence_count" in comparison.summary


def test_compare_sessions_has_traces(tmp_path):
    """compare_sessions includes traces for both sessions."""
    from rlm_adk.eval.queries import compare_sessions
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=2, events_per_session=4)
    with TraceReader(db_path) as reader:
        comparison = compare_sessions(
            reader, "test_app", "user_1", "session_1", "session_2"
        )
    assert len(comparison.traces_a) > 0
    assert len(comparison.traces_b) > 0
    assert comparison.session_id_a == "session_1"
    assert comparison.session_id_b == "session_2"


def test_compare_sessions_divergence_list(tmp_path):
    """compare_sessions includes divergence points."""
    from rlm_adk.eval.queries import compare_sessions
    from rlm_adk.eval.trace_reader import TraceReader

    db_path = str(tmp_path / "test.db")
    _create_test_db_asymmetric(db_path, events_a=4, events_b=6)
    with TraceReader(db_path) as reader:
        comparison = compare_sessions(
            reader, "test_app", "user_1", "session_a", "session_b"
        )
    assert isinstance(comparison.divergence_points, list)
    assert comparison.summary["divergence_count"] == len(comparison.divergence_points)
