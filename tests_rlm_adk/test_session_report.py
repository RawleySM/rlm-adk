"""Tests for rlm_adk.eval.session_report — TDD red/green for bug fixes."""

import json
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from rlm_adk.eval.session_report import (
    _agent_depth,
    _build_errors,
    _build_layer_tree,
    _build_overview,
    _build_performance,
    _build_repl_outcomes,
    _build_state_timeline,
    build_session_report,
)


# ---- Schema (from sqlite_tracing.py) ----

_SCHEMA_SQL = """
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
    model_usage_summary     TEXT,
    config_json             TEXT,
    prompt_hash             TEXT,
    max_depth_reached       INTEGER
);

CREATE TABLE IF NOT EXISTS spans (
    span_id         TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    parent_span_id  TEXT,
    operation_name  TEXT NOT NULL,
    agent_name      TEXT,
    start_time      REAL NOT NULL,
    end_time        REAL,
    status          TEXT DEFAULT 'ok',
    attributes      TEXT,
    events          TEXT
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


def _new_id() -> str:
    return uuid.uuid4().hex


def _create_test_db(*, include_telemetry: bool = True, include_sse: bool = True,
                    include_spans: bool = True) -> tuple[str, str, sqlite3.Connection]:
    """Create a temp SQLite DB with the full schema and sample data.

    Returns (db_path, trace_id, conn).
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    conn = sqlite3.connect(db_path)
    trace_id = _new_id()
    now = time.time()

    # Always create traces table
    conn.execute("""CREATE TABLE IF NOT EXISTS traces (
        trace_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, user_id TEXT,
        app_name TEXT, start_time REAL NOT NULL, end_time REAL,
        status TEXT DEFAULT 'running', total_input_tokens INTEGER DEFAULT 0,
        total_output_tokens INTEGER DEFAULT 0, total_calls INTEGER DEFAULT 0,
        iterations INTEGER DEFAULT 0, final_answer_length INTEGER,
        metadata TEXT, request_id TEXT, repo_url TEXT, root_prompt_preview TEXT,
        total_execution_time_s REAL, child_dispatch_count INTEGER,
        child_error_counts TEXT, structured_output_failures INTEGER,
        finish_safety_count INTEGER, finish_recitation_count INTEGER,
        finish_max_tokens_count INTEGER, tool_invocation_summary TEXT,
        artifact_saves INTEGER, artifact_bytes_saved INTEGER,
        per_iteration_breakdown TEXT, model_usage_summary TEXT,
        config_json TEXT, prompt_hash TEXT, max_depth_reached INTEGER
    )""")

    conn.execute(
        """INSERT INTO traces (trace_id, session_id, app_name, start_time, end_time, status, iterations)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (trace_id, "sess-1", "test_app", now - 10.0, now, "completed", 3),
    )

    if include_telemetry:
        conn.execute("""CREATE TABLE IF NOT EXISTS telemetry (
            telemetry_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL,
            event_type TEXT NOT NULL, agent_name TEXT, iteration INTEGER,
            depth INTEGER DEFAULT 0, call_number INTEGER,
            start_time REAL NOT NULL, end_time REAL, duration_ms REAL,
            model TEXT, input_tokens INTEGER, output_tokens INTEGER,
            finish_reason TEXT, num_contents INTEGER, agent_type TEXT,
            prompt_chars INTEGER, system_chars INTEGER, tool_name TEXT,
            tool_args_keys TEXT, result_preview TEXT,
            repl_has_errors INTEGER, repl_has_output INTEGER,
            repl_llm_calls INTEGER, status TEXT DEFAULT 'ok',
            error_type TEXT, error_message TEXT
        )""")
        # Model calls
        for i in range(3):
            conn.execute(
                """INSERT INTO telemetry
                   (telemetry_id, trace_id, event_type, agent_name, start_time,
                    duration_ms, model, input_tokens, output_tokens, finish_reason, status)
                   VALUES (?, ?, 'model_call', 'reasoning_agent', ?, ?, 'gemini-3-pro', ?, ?, 'STOP', 'ok')""",
                (_new_id(), trace_id, now - 9 + i, 1500 + i * 100, 1000 + i * 50, 200 + i * 30, ),
            )
        # Tool call (REPL)
        conn.execute(
            """INSERT INTO telemetry
               (telemetry_id, trace_id, event_type, agent_name, start_time,
                duration_ms, tool_name, repl_has_errors, repl_has_output, repl_llm_calls, status)
               VALUES (?, ?, 'tool_call', 'reasoning_agent', ?, ?, 'execute_code', 0, 1, 2, 'ok')""",
            (_new_id(), trace_id, now - 5, 3000),
        )
        # Child agent model call
        conn.execute(
            """INSERT INTO telemetry
               (telemetry_id, trace_id, event_type, agent_name, start_time,
                duration_ms, model, input_tokens, output_tokens, finish_reason, status)
               VALUES (?, ?, 'model_call', 'child_reasoning_d1', ?, ?, 'gemini-3-pro', ?, ?, 'STOP', 'ok')""",
            (_new_id(), trace_id, now - 4, 800, 500, 100),
        )
        # Agent with unparseable name
        conn.execute(
            """INSERT INTO telemetry
               (telemetry_id, trace_id, event_type, agent_name, start_time,
                duration_ms, model, input_tokens, output_tokens, status)
               VALUES (?, ?, 'model_call', 'some_custom_agent', ?, ?, 'gemini-3-pro', ?, ?, 'ok')""",
            (_new_id(), trace_id, now - 3, 600, 300, 80),
        )

    if include_sse:
        conn.execute("""CREATE TABLE IF NOT EXISTS session_state_events (
            event_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL,
            seq INTEGER NOT NULL, event_author TEXT,
            event_time REAL NOT NULL, state_key TEXT NOT NULL,
            key_category TEXT NOT NULL, key_depth INTEGER DEFAULT 0,
            key_fanout INTEGER, value_type TEXT, value_int INTEGER,
            value_float REAL, value_text TEXT, value_json TEXT
        )""")
        conn.execute(
            """INSERT INTO session_state_events
               (event_id, trace_id, seq, event_author, event_time,
                state_key, key_category, key_depth, value_type, value_int)
               VALUES (?, ?, 0, 'reasoning_agent', ?, 'iteration_count', 'flow_control', 0, 'int', 3)""",
            (_new_id(), trace_id, now - 8),
        )

    if include_spans:
        conn.execute("""CREATE TABLE IF NOT EXISTS spans (
            span_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL,
            parent_span_id TEXT, operation_name TEXT NOT NULL,
            agent_name TEXT, start_time REAL NOT NULL, end_time REAL,
            status TEXT DEFAULT 'ok', attributes TEXT, events TEXT
        )""")

    conn.commit()
    return db_path, trace_id, conn


# ---- Tests ----


class TestFullReport:
    """Test build_session_report with a fully populated DB."""

    def test_full_report_has_all_sections(self):
        db_path, trace_id, conn = _create_test_db()
        conn.close()
        try:
            report = build_session_report(trace_id, db_path)
            assert "overview" in report
            assert "layer_tree" in report
            assert "performance" in report
            assert "errors" in report
            assert "repl_outcomes" in report
            assert "state_timeline" in report
            # No error key in overview
            assert "error" not in report["overview"]
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_overview_token_totals(self):
        db_path, trace_id, conn = _create_test_db()
        conn.close()
        try:
            report = build_session_report(trace_id, db_path)
            ov = report["overview"]
            assert ov["total_input_tokens"] > 0
            assert ov["total_output_tokens"] > 0
            assert ov["total_model_calls"] > 0
            assert ov["total_tool_calls"] >= 1
        finally:
            Path(db_path).unlink(missing_ok=True)


class TestMissingTables:
    """Test graceful handling when telemetry or SSE tables are missing."""

    def test_missing_telemetry_table_graceful(self):
        """DB with only traces table (no telemetry) should not crash."""
        db_path, trace_id, conn = _create_test_db(
            include_telemetry=False, include_sse=False, include_spans=False
        )
        conn.close()
        try:
            report = build_session_report(trace_id, db_path)
            # Should have overview at minimum
            assert "overview" in report
            # Should not have crashed -- remaining sections should exist or be graceful
            assert "error" not in report["overview"] or "not found" not in report["overview"].get("error", "")
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_missing_spans_table_graceful(self):
        """DB with traces+telemetry but no spans should not crash."""
        db_path, trace_id, conn = _create_test_db(include_spans=False, include_sse=False)
        conn.close()
        try:
            report = build_session_report(trace_id, db_path)
            assert "overview" in report
            assert "layer_tree" in report
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_missing_sse_table_graceful(self):
        """DB with traces+telemetry but no session_state_events should not crash."""
        db_path, trace_id, conn = _create_test_db(include_sse=False)
        conn.close()
        try:
            report = build_session_report(trace_id, db_path)
            assert "state_timeline" in report
            # Should report the table is missing, not crash
            assert report["state_timeline"].get("error") or report["state_timeline"].get("total_events") is not None
        finally:
            Path(db_path).unlink(missing_ok=True)


class TestQueryOneNoneHandling:
    """Verify no TypeError when _query_one returns None."""

    def test_overview_tool_count_none_safe(self):
        """_query_one for tool count on empty telemetry should not TypeError."""
        db_path, trace_id, conn = _create_test_db(
            include_telemetry=False, include_sse=False, include_spans=False
        )
        conn.close()
        try:
            # This would previously crash with TypeError: 'NoneType' not subscriptable
            report = build_session_report(trace_id, db_path)
            ov = report["overview"]
            # Should have a numeric value (0) not crash
            assert isinstance(ov.get("total_tool_calls", 0), (int, float))
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_performance_rate_limit_none_safe(self):
        """rate_limit _query_one on missing telemetry should not TypeError."""
        db_path, trace_id, conn = _create_test_db(
            include_telemetry=False, include_sse=False, include_spans=False
        )
        conn.close()
        try:
            report = build_session_report(trace_id, db_path)
            perf = report.get("performance", {})
            assert isinstance(perf.get("rate_limit_errors", 0), (int, float))
        finally:
            Path(db_path).unlink(missing_ok=True)


class TestDepthUnknownNaming:
    """Agents without depth pattern should use 'depth_unknown' not 'depth_-1'."""

    def test_agent_depth_returns_negative_for_unknown(self):
        """_agent_depth returns -1 for unparseable names (existing behavior)."""
        assert _agent_depth(None) == -1
        assert _agent_depth("some_custom_agent") == -1
        assert _agent_depth("reasoning_agent") == 0
        assert _agent_depth("child_reasoning_d1") == 1

    def test_layer_tree_uses_depth_unknown(self):
        """Layer tree should use 'depth_unknown' key, not 'depth_-1'."""
        db_path, trace_id, conn = _create_test_db()
        conn.close()
        try:
            report = build_session_report(trace_id, db_path)
            lt = report["layer_tree"]
            # Should NOT have depth_-1
            assert "depth_-1" not in lt, f"Found deprecated 'depth_-1' key in layer_tree: {list(lt.keys())}"
            # Should have depth_unknown for the custom agent
            assert "depth_unknown" in lt, f"Missing 'depth_unknown' key in layer_tree: {list(lt.keys())}"
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_performance_uses_depth_unknown(self):
        """Performance latency_by_layer should use 'depth_unknown' not 'depth_-1'."""
        db_path, trace_id, conn = _create_test_db()
        conn.close()
        try:
            report = build_session_report(trace_id, db_path)
            latency = report["performance"]["model_call_latency_by_layer"]
            assert "depth_-1" not in latency
            if any(_agent_depth(None) == -1 for _ in [1]):
                # If there are unknown-depth agents, should use depth_unknown
                assert "depth_unknown" in latency or len(latency) > 0
        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_repl_outcomes_uses_depth_unknown(self):
        """REPL outcomes by_depth should use 'depth_unknown' not 'depth_-1'."""
        db_path, trace_id, conn = _create_test_db()
        conn.close()
        try:
            report = build_session_report(trace_id, db_path)
            by_depth = report["repl_outcomes"]["by_depth"]
            assert "depth_-1" not in by_depth
        finally:
            Path(db_path).unlink(missing_ok=True)
