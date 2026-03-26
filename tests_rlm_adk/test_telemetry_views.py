"""Tests for telemetry schema refactor: drop spans DDL, completion columns, SQL views.

Validates:
- Fresh DBs no longer create a ``spans`` table.
- Pre-upgrade DBs retain their existing ``spans`` table + data.
- Three new SQL views are queryable: ``execution_observations``,
  ``telemetry_completions``, ``lineage_records``.
- Four new completion columns exist on the ``telemetry`` table.

RED/GREEN TDD:
  - RED:  Tests fail before schema changes in sqlite_tracing.py.
  - GREEN: They pass once the schema is updated.
"""

from __future__ import annotations

import sqlite3

from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal set of columns needed for a valid telemetry INSERT.
_TELEMETRY_BASE_COLS = (
    "telemetry_id, trace_id, event_type, agent_name, start_time, "
    "depth, fanout_idx, decision_mode, structured_outcome, "
    "terminal_completion, output_schema_name, validated_output_json, "
    "result_preview, result_payload, finish_reason, "
    "input_tokens, output_tokens, thought_tokens, duration_ms, "
    "model, num_contents, prompt_chars, system_chars, status, "
    "error_type, error_message, execution_mode, call_number, "
    "tool_name, tool_args_keys, repl_has_errors, repl_has_output, "
    "repl_llm_calls, repl_stdout_len, repl_stderr_len, repl_trace_summary, "
    "invocation_id, session_id, parent_depth, parent_fanout_idx, branch, "
    "end_time, iteration, agent_type"
)


def _insert_telemetry_row(
    conn: sqlite3.Connection,
    telemetry_id: str,
    trace_id: str = "trace-001",
    event_type: str = "model_call",
    agent_name: str = "reasoning_agent",
    start_time: float = 1000.0,
    depth: int = 0,
    fanout_idx: int | None = None,
    decision_mode: str | None = None,
    structured_outcome: str = "not_applicable",
    terminal_completion: int | None = None,
    output_schema_name: str | None = None,
    validated_output_json: str | None = None,
    result_preview: str | None = None,
    result_payload: str | None = None,
    finish_reason: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    thought_tokens: int | None = None,
    duration_ms: float | None = None,
    model: str | None = None,
    num_contents: int | None = None,
    prompt_chars: int | None = None,
    system_chars: int | None = None,
    status: str = "ok",
    error_type: str | None = None,
    error_message: str | None = None,
    execution_mode: str | None = None,
    call_number: int | None = None,
    tool_name: str | None = None,
    tool_args_keys: str | None = None,
    repl_has_errors: int | None = None,
    repl_has_output: int | None = None,
    repl_llm_calls: int | None = None,
    repl_stdout_len: int | None = None,
    repl_stderr_len: int | None = None,
    repl_trace_summary: str | None = None,
    invocation_id: str | None = None,
    session_id: str | None = None,
    parent_depth: int | None = None,
    parent_fanout_idx: int | None = None,
    branch: str | None = None,
    end_time: float | None = None,
    iteration: int | None = None,
    agent_type: str | None = None,
) -> None:
    """Insert a row directly into the telemetry table for testing."""
    conn.execute(
        f"INSERT INTO telemetry ({_TELEMETRY_BASE_COLS}) "
        f"VALUES ({', '.join('?' for _ in _TELEMETRY_BASE_COLS.split(', '))})",
        (
            telemetry_id,
            trace_id,
            event_type,
            agent_name,
            start_time,
            depth,
            fanout_idx,
            decision_mode,
            structured_outcome,
            terminal_completion,
            output_schema_name,
            validated_output_json,
            result_preview,
            result_payload,
            finish_reason,
            input_tokens,
            output_tokens,
            thought_tokens,
            duration_ms,
            model,
            num_contents,
            prompt_chars,
            system_chars,
            status,
            error_type,
            error_message,
            execution_mode,
            call_number,
            tool_name,
            tool_args_keys,
            repl_has_errors,
            repl_has_output,
            repl_llm_calls,
            repl_stdout_len,
            repl_stderr_len,
            repl_trace_summary,
            invocation_id,
            session_id,
            parent_depth,
            parent_fanout_idx,
            branch,
            end_time,
            iteration,
            agent_type,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Test 1: Fresh DB no longer creates spans table
# ---------------------------------------------------------------------------


def test_fresh_db_no_spans(tmp_path):
    """A fresh SqliteTracingPlugin DB must NOT contain a spans table."""
    db_path = str(tmp_path / "traces.db")
    plugin = SqliteTracingPlugin(db_path=db_path)
    assert plugin._conn is not None

    tables = {
        row[0]
        for row in plugin._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "spans" not in tables, (
        f"spans table should not exist in fresh DB, found tables: {tables}"
    )


# ---------------------------------------------------------------------------
# Test 2: Pre-upgrade DB retains existing spans table + data
# ---------------------------------------------------------------------------


def test_preupgrade_db_retains_spans(tmp_path):
    """A pre-upgrade DB with spans table keeps it intact after plugin init."""
    db_path = str(tmp_path / "traces.db")

    # Build a pre-upgrade DB inline with explicit SQL
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE spans (
            span_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            parent_span_id TEXT,
            operation_name TEXT NOT NULL,
            agent_name TEXT,
            start_time REAL NOT NULL,
            end_time REAL,
            status TEXT DEFAULT 'ok',
            attributes TEXT,
            events TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO spans (span_id, trace_id, operation_name, start_time) "
        "VALUES ('s1', 't1', 'test_op', 1000.0)"
    )
    # Create a minimal telemetry table (base columns only, no new completion cols)
    conn.execute(
        """CREATE TABLE telemetry (
            telemetry_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            start_time REAL NOT NULL
        )"""
    )
    # Create minimal traces table
    conn.execute(
        """CREATE TABLE traces (
            trace_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            start_time REAL NOT NULL
        )"""
    )
    # Create minimal session_state_events table
    conn.execute(
        """CREATE TABLE session_state_events (
            event_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event_time REAL NOT NULL,
            state_key TEXT NOT NULL,
            key_category TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()

    # Now instantiate the plugin against this pre-upgrade DB
    plugin = SqliteTracingPlugin(db_path=db_path)
    assert plugin._conn is not None

    # Spans table should still exist with data intact
    tables = {
        row[0]
        for row in plugin._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "spans" in tables, "Pre-existing spans table should be retained"

    count = plugin._conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
    assert count == 1, f"Expected 1 row in spans, got {count}"


# ---------------------------------------------------------------------------
# Test 3: execution_observations view is queryable
# ---------------------------------------------------------------------------


def test_execution_observations_queryable(tmp_path):
    """The execution_observations view returns rows from telemetry."""
    db_path = str(tmp_path / "traces.db")
    plugin = SqliteTracingPlugin(db_path=db_path)
    conn = plugin._conn
    assert conn is not None

    _insert_telemetry_row(conn, "t1", event_type="model_call", duration_ms=100.5)
    _insert_telemetry_row(conn, "t2", event_type="tool_use", duration_ms=50.0)

    count = conn.execute("SELECT COUNT(*) FROM execution_observations").fetchone()[0]
    assert count == 2, f"Expected 2 rows in execution_observations, got {count}"


# ---------------------------------------------------------------------------
# Test 4: telemetry_completions view filters to set_model_response
# ---------------------------------------------------------------------------


def test_telemetry_completions_queryable(tmp_path):
    """telemetry_completions returns only set_model_response rows."""
    db_path = str(tmp_path / "traces.db")
    plugin = SqliteTracingPlugin(db_path=db_path)
    conn = plugin._conn
    assert conn is not None

    # Insert various decision_mode rows
    _insert_telemetry_row(conn, "t1", decision_mode="execute_code")
    _insert_telemetry_row(conn, "t2", decision_mode="set_model_response")
    _insert_telemetry_row(conn, "t3", decision_mode="set_model_response")
    _insert_telemetry_row(conn, "t4", decision_mode=None)
    _insert_telemetry_row(conn, "t5", decision_mode="load_skill")

    count = conn.execute("SELECT COUNT(*) FROM telemetry_completions").fetchone()[0]
    assert count == 2, f"Expected 2 set_model_response rows in telemetry_completions, got {count}"


# ---------------------------------------------------------------------------
# Test 5: telemetry_completions excludes finish_reason by design
# ---------------------------------------------------------------------------


def test_telemetry_completions_finish_reason_excluded(tmp_path):
    """finish_reason is NOT in telemetry_completions (populated on model_call, not tool rows)."""
    db_path = str(tmp_path / "traces.db")
    plugin = SqliteTracingPlugin(db_path=db_path)
    conn = plugin._conn
    assert conn is not None

    # Insert a model_call row WITH finish_reason (not in view)
    _insert_telemetry_row(
        conn,
        "t1",
        event_type="model_call",
        decision_mode="execute_code",
        finish_reason="STOP",
    )
    # Insert set_model_response rows (in view) - finish_reason is NULL on tool rows
    _insert_telemetry_row(
        conn,
        "t2",
        event_type="tool_use",
        decision_mode="set_model_response",
        finish_reason=None,
    )

    # First verify the view exists
    views = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
    }
    assert "telemetry_completions" in views, (
        "telemetry_completions view must exist before checking columns"
    )

    # The view should not have a finish_reason column at all
    col_names = {
        row[1] for row in conn.execute("PRAGMA table_info(telemetry_completions)").fetchall()
    }
    assert "finish_reason" not in col_names, (
        "finish_reason should be excluded from telemetry_completions by design"
    )


# ---------------------------------------------------------------------------
# Test 6: lineage_records view is queryable
# ---------------------------------------------------------------------------


def test_lineage_records_queryable(tmp_path):
    """The lineage_records view returns rows with tree-structure columns."""
    db_path = str(tmp_path / "traces.db")
    plugin = SqliteTracingPlugin(db_path=db_path)
    conn = plugin._conn
    assert conn is not None

    _insert_telemetry_row(
        conn,
        "t1",
        agent_name="orchestrator_d0",
        depth=0,
        decision_mode="execute_code",
    )
    _insert_telemetry_row(
        conn,
        "t2",
        agent_name="reasoning_d1",
        depth=1,
        fanout_idx=0,
        parent_depth=0,
        decision_mode="set_model_response",
    )

    count = conn.execute("SELECT COUNT(*) FROM lineage_records").fetchone()[0]
    assert count == 2, f"Expected 2 rows in lineage_records, got {count}"

    # Verify tree-structure columns are present
    col_names = {row[1] for row in conn.execute("PRAGMA table_info(lineage_records)").fetchall()}
    expected_cols = {
        "telemetry_id",
        "trace_id",
        "event_type",
        "agent_name",
        "agent_type",
        "iteration",
        "depth",
        "fanout_idx",
        "parent_depth",
        "parent_fanout_idx",
        "branch",
        "invocation_id",
        "session_id",
        "output_schema_name",
        "decision_mode",
        "structured_outcome",
        "terminal_completion",
    }
    missing = expected_cols - col_names
    assert not missing, f"lineage_records missing columns: {missing}"


# ---------------------------------------------------------------------------
# Test 7: Pre-upgrade DB gains views after two-pass init
# ---------------------------------------------------------------------------


def test_upgrade_db_views_queryable(tmp_path):
    """A pre-refactor DB (base columns only) gains views after plugin init."""
    db_path = str(tmp_path / "traces.db")

    # Build a pre-refactor DB with base telemetry columns (no views, no new cols)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE traces (
            trace_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            start_time REAL NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE telemetry (
            telemetry_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            start_time REAL NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE session_state_events (
            event_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event_time REAL NOT NULL,
            state_key TEXT NOT NULL,
            key_category TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()

    # Instantiate plugin - two-pass init should migrate + create views
    plugin = SqliteTracingPlugin(db_path=db_path)
    assert plugin._conn is not None

    views = {
        row[0]
        for row in plugin._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        ).fetchall()
    }

    expected_views = {
        "execution_observations",
        "telemetry_completions",
        "lineage_records",
        "session_state_events_unified",
    }
    missing = expected_views - views
    assert not missing, f"Missing views after upgrade: {missing}"

    # Verify views are actually queryable (not just created)
    for view in expected_views:
        count = plugin._conn.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
        assert count == 0, f"Expected 0 rows in {view} on empty DB, got {count}"
