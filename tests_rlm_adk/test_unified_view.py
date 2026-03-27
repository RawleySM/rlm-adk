"""Tests for the session_state_events_unified SQL view (BUG-015 fix).

The view exposes a unified ``value`` column via COALESCE across all
typed columns so that ad-hoc queries never miss int/bool/float/json values
that live outside ``value_text``.

RED/GREEN TDD:
  - RED:  These tests fail before the CREATE VIEW is added to _SCHEMA_SQL.
  - GREEN: They pass once the view is present.
"""

from __future__ import annotations

import sqlite3

import pytest

from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin, _typed_value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_sse_row(
    conn: sqlite3.Connection,
    seq: int,
    state_key: str,
    value_type: str,
    value_int: int | None,
    value_float: float | None,
    value_text: str | None,
    value_json: str | None,
    key_depth: int = 1,
    author: str = "child_orchestrator_d1f0",
) -> None:
    """Insert a row directly into session_state_events for testing."""
    conn.execute(
        """INSERT INTO session_state_events
           (event_id, trace_id, seq, event_author, event_time,
            state_key, key_category, key_depth, key_fanout,
            value_type, value_int, value_float, value_text, value_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            f"evt-{seq}",
            "trace-001",
            seq,
            author,
            1000.0 + seq,
            state_key,
            "orchestrator",
            key_depth,
            None,
            value_type,
            value_int,
            value_float,
            value_text,
            value_json,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Test 1: View exists after plugin initialization
# ---------------------------------------------------------------------------


class TestUnifiedViewExists:
    """The unified view must be created by _SCHEMA_SQL."""

    def test_view_present_in_fresh_db(self, tmp_path):
        """SqliteTracingPlugin creates the session_state_events_unified view."""
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        assert plugin._conn is not None

        rows = plugin._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view' "
            "AND name='session_state_events_unified'"
        ).fetchall()
        assert len(rows) == 1, (
            "session_state_events_unified view not found in sqlite_master"
        )


# ---------------------------------------------------------------------------
# Test 2: Unified value column resolves all Python types
# ---------------------------------------------------------------------------


class TestUnifiedValueResolution:
    """The unified ``value`` column must COALESCE across typed columns."""

    @pytest.fixture()
    def db(self, tmp_path):
        """Create a fresh DB via the plugin and return the connection."""
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        assert plugin._conn is not None
        return plugin._conn

    def _query_unified(self, conn: sqlite3.Connection, state_key: str) -> str | None:
        """Query the unified view for a single key and return value."""
        row = conn.execute(
            "SELECT value FROM session_state_events_unified "
            "WHERE state_key = ?",
            (state_key,),
        ).fetchone()
        return row[0] if row else None

    def test_int_value_visible(self, db):
        """Integer stored in value_int is visible through unified view."""
        _insert_sse_row(db, 0, "current_depth", "int", 2, None, None, None)
        val = self._query_unified(db, "current_depth")
        assert val is not None, "int value should be non-NULL in unified view"
        assert val == "2", f"Expected '2', got {val!r}"

    def test_bool_true_visible(self, db):
        """Bool True stored as value_int=1 is visible through unified view."""
        _insert_sse_row(db, 0, "should_stop", "bool", 1, None, None, None)
        val = self._query_unified(db, "should_stop")
        assert val is not None, "bool value should be non-NULL in unified view"
        assert val == "1", f"Expected '1', got {val!r}"

    def test_bool_false_visible(self, db):
        """Bool False stored as value_int=0 is visible through unified view."""
        _insert_sse_row(db, 0, "should_stop", "bool", 0, None, None, None)
        val = self._query_unified(db, "should_stop")
        assert val is not None, "bool(False) should be non-NULL in unified view"
        assert val == "0", f"Expected '0', got {val!r}"

    def test_float_value_visible(self, db):
        """Float stored in value_float is visible through unified view."""
        _insert_sse_row(db, 0, "confidence", "float", None, 0.95, None, None)
        val = self._query_unified(db, "confidence")
        assert val is not None, "float value should be non-NULL in unified view"
        assert float(val) == pytest.approx(0.95)

    def test_str_value_visible(self, db):
        """String stored in value_text is still visible through unified view."""
        _insert_sse_row(db, 0, "final_response_text", "str", None, None, "hello world", None)
        val = self._query_unified(db, "final_response_text")
        assert val == "hello world"

    def test_json_dict_visible(self, db):
        """Dict stored in value_json is visible through unified view."""
        _insert_sse_row(db, 0, "reasoning_output", "dict", None, None, None, '{"answer": "yes"}')
        val = self._query_unified(db, "reasoning_output")
        assert val is not None, "dict/json value should be non-NULL in unified view"
        assert '"answer"' in val

    def test_json_list_visible(self, db):
        """List stored in value_json is visible through unified view."""
        _insert_sse_row(db, 0, "batch_results", "list", None, None, None, '[1, 2, 3]')
        val = self._query_unified(db, "batch_results")
        assert val is not None, "list/json value should be non-NULL in unified view"
        assert val == "[1, 2, 3]"

    def test_null_value_remains_null(self, db):
        """None value (all columns NULL) returns NULL through unified view."""
        _insert_sse_row(db, 0, "empty_key", "null", None, None, None, None)
        val = self._query_unified(db, "empty_key")
        assert val is None, "null value should remain NULL in unified view"


# ---------------------------------------------------------------------------
# Test 3: Unified view preserves all original columns
# ---------------------------------------------------------------------------


class TestUnifiedViewColumns:
    """The view must expose the original typed columns alongside the unified value."""

    def test_view_has_expected_columns(self, tmp_path):
        """Verify the unified view schema includes all expected columns."""
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        conn = plugin._conn
        assert conn is not None

        cursor = conn.execute("PRAGMA table_info(session_state_events_unified)")
        col_names = {row[1] for row in cursor.fetchall()}

        expected = {
            "event_id", "trace_id", "seq", "event_author", "event_time",
            "state_key", "key_category", "key_depth", "key_fanout",
            "value_type", "value",
            "value_int", "value_float", "value_text", "value_json",
        }
        missing = expected - col_names
        assert not missing, f"Unified view missing columns: {missing}"


# ---------------------------------------------------------------------------
# Test 4: _typed_value round-trips through unified view
# ---------------------------------------------------------------------------


class TestTypedValueRoundTrip:
    """Verify _typed_value() outputs are correctly resolved by the unified view.

    This exercises the REAL _typed_value function and the REAL SQL view
    together -- no mocks, no fakes. The test inserts rows using _typed_value
    output and reads them back through the unified view.
    """

    @pytest.fixture()
    def db(self, tmp_path):
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        assert plugin._conn is not None
        return plugin._conn

    @pytest.mark.parametrize(
        "python_value, expected_text",
        [
            (42, "42"),
            (0, "0"),
            (-1, "-1"),
            (True, "1"),
            (False, "0"),
            (3.14, "3.14"),
            ("hello", "hello"),
            ([1, 2], "[1, 2]"),
            ({"a": 1}, '{"a": 1}'),
            (None, None),
        ],
        ids=["int_42", "int_0", "int_neg1", "bool_true", "bool_false",
             "float_pi", "str_hello", "list", "dict", "none"],
    )
    def test_typed_value_roundtrip(self, db, python_value, expected_text):
        """Insert via _typed_value, read via unified view, compare."""
        vtype, vint, vfloat, vtext, vjson = _typed_value(python_value)
        _insert_sse_row(
            db, 0, "test_key", vtype, vint, vfloat, vtext, vjson,
        )
        row = db.execute(
            "SELECT value, value_type FROM session_state_events_unified "
            "WHERE state_key = 'test_key'"
        ).fetchone()
        assert row is not None, "Row not found in unified view"
        actual_value, actual_type = row
        assert actual_type == vtype
        if expected_text is None:
            assert actual_value is None
        elif isinstance(python_value, float):
            assert float(actual_value) == pytest.approx(python_value)
        else:
            assert actual_value == expected_text


# ---------------------------------------------------------------------------
# Test 5: COALESCE priority — value_text wins over value_int when both set
# ---------------------------------------------------------------------------


class TestCoalescePriority:
    """COALESCE order must be: value_text, value_int, value_float, value_json.

    This matches the designed type-dispatch: exactly one column is non-NULL
    per row. But if somehow multiple are set, value_text takes priority
    (the most human-readable representation).
    """

    def test_text_wins_over_int(self, tmp_path):
        """When both value_text and value_int are set, value_text wins."""
        db_path = str(tmp_path / "traces.db")
        plugin = SqliteTracingPlugin(db_path=db_path)
        conn = plugin._conn
        assert conn is not None

        conn.execute(
            """INSERT INTO session_state_events
               (event_id, trace_id, seq, event_author, event_time,
                state_key, key_category, key_depth, key_fanout,
                value_type, value_int, value_float, value_text, value_json)
               VALUES ('e1', 'tr1', 0, 'test', 1000.0,
                       'dual_key', 'other', 0, NULL,
                       'str', 99, NULL, 'text_wins', NULL)""",
        )
        conn.commit()

        row = conn.execute(
            "SELECT value FROM session_state_events_unified WHERE state_key = 'dual_key'"
        ).fetchone()
        assert row[0] == "text_wins", (
            f"COALESCE should prefer value_text. Got: {row[0]!r}"
        )
