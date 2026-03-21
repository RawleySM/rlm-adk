"""SqliteTracingPlugin - Local SQLite-based telemetry.

Captures structured telemetry from ADK callbacks into a local traces.db file
using a 3-table schema: traces (enriched), telemetry, session_state_events.

No external dependencies beyond the Python standard library (sqlite3).
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from rlm_adk.state import (
    DYN_SKILL_INSTRUCTION,
    FINAL_RESPONSE_TEXT,
    INVOCATION_START_TIME,
    ITERATION_COUNT,
    LAST_REPL_RESULT,
    parse_depth_key,
    should_capture_state_key,
)

logger = logging.getLogger(__name__)

# Thin aliases so the rest of the file needs minimal changes.
_parse_key = parse_depth_key
_should_capture = should_capture_state_key


# ---- Key categorization (plugin-specific, not shared) ----


def _categorize_key(key: str) -> str:
    """Categorize a state key for the session_state_events table.

    Only categorizes keys that actually flow through state_delta.
    Per-model-call lineage is captured directly in the telemetry table,
    not via session_state_events.
    """
    if key.startswith("obs:artifact_") or key.startswith("artifact_"):
        return "obs_artifact"
    if key in (
        "iteration_count",
        "should_stop",
        "final_response_text",
        "current_depth",
        "policy_violation",
    ):
        return "flow_control"
    if key.startswith("repl_submitted_code"):
        return "repl"
    if key.startswith("repl_expanded_code"):
        return "repl"
    if key.startswith("repl_skill_expansion_meta"):
        return "repl"
    if key.startswith("repl_did_expand"):
        return "repl"
    if key.startswith("last_repl_result"):
        return "repl"
    if key.startswith("cache:"):
        return "cache"
    if key in (
        "request_id",
        "idempotency_key",
        "repo_url",
        "root_prompt",
        "skill_instruction",
        "enabled_skills",
    ):
        return "request_meta"
    return "other"


# ---- Value typing helper ----


def _typed_value(value: Any) -> tuple[str, int | None, float | None, str | None, str | None]:
    """Return (value_type, value_int, value_float, value_text, value_json)."""
    if value is None:
        return "null", None, None, None, None
    if isinstance(value, bool):
        return "bool", int(value), None, None, None
    if isinstance(value, int):
        return "int", value, None, None, None
    if isinstance(value, float):
        return "float", None, value, None, None
    if isinstance(value, str):
        return "str", None, None, value, None
    if isinstance(value, list):
        return "list", None, None, None, json.dumps(value, default=str)
    if isinstance(value, dict):
        return "dict", None, None, None, json.dumps(value, default=str)
    return "other", None, None, str(value), None


def _typed_value_for_key(
    base_key: str,
    value: Any,
) -> tuple[str, int | None, float | None, str | None, str | None]:
    """Return a typed row payload."""
    return _typed_value(value)


def _serialize_payload(value: Any) -> str | None:
    """Serialize arbitrary telemetry payloads without truncation."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


# ---- Schema SQL ----

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
    child_total_batch_dispatches INTEGER,
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
    thought_tokens  INTEGER,
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
    repl_stdout_len     INTEGER,
    repl_stderr_len     INTEGER,
    repl_trace_summary  TEXT,
    skill_instruction   TEXT,
    result_payload      TEXT,
    repl_stdout         TEXT,
    repl_stderr         TEXT,
    fanout_idx          INTEGER,
    parent_depth        INTEGER,
    parent_fanout_idx   INTEGER,
    branch              TEXT,
    invocation_id       TEXT,
    session_id          TEXT,
    output_schema_name  TEXT,
    decision_mode       TEXT,
    structured_outcome  TEXT,
    terminal_completion INTEGER,
    custom_metadata_json TEXT,
    validated_output_json TEXT,
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

CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_operation ON spans(operation_name);
CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id);
CREATE INDEX IF NOT EXISTS idx_traces_start ON traces(start_time);
CREATE INDEX IF NOT EXISTS idx_telemetry_trace ON telemetry(trace_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_type ON telemetry(event_type);
CREATE INDEX IF NOT EXISTS idx_sse_trace ON session_state_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_sse_key ON session_state_events(state_key);
CREATE INDEX IF NOT EXISTS idx_sse_trace_seq ON session_state_events(trace_id, seq);
"""


class SqliteTracingPlugin(BasePlugin):
    """ADK Plugin that writes structured telemetry to a local SQLite database.

    Uses a 3-table schema:
    - traces: One row per invocation, enriched with OBS keys at run end.
    - telemetry: One row per model call or tool invocation (structured columns).
    - session_state_events: One row per curated state key change from events.

    The legacy ``spans`` table is retained for backward compatibility but
    no longer receives new writes.

    The plugin is observe-only: all callbacks return None and never block
    execution. Database write errors are caught and logged as warnings.

    Args:
        name: Plugin name (default "sqlite_tracing").
        db_path: Path to the SQLite database file (default ".adk/traces.db").
            Created if it does not exist. Parent directories are created.
    """

    def __init__(
        self,
        *,
        name: str = "sqlite_tracing",
        db_path: str = ".adk/traces.db",
    ):
        super().__init__(name=name)
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._trace_id: str | None = None
        # Pending telemetry: callback/tool context id -> (telemetry_id, start_time)
        self._pending_model_telemetry: dict[int, tuple[str, float]] = {}
        self._pending_tool_telemetry: dict[int, tuple[str, float]] = {}
        # Instance-local counters (no longer read from obs: session state)
        self._model_call_count: int = 0
        self._artifact_saves_count: int = 0
        # Monotonic counter for session_state_events per trace
        self._sse_seq: int = 0
        # Legacy: kept for backward compat in agent span tracking
        self._agent_span_stack: list[str] = []
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database connection and create tables."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path))
            # Try full schema creation (works for fresh DBs).
            # On existing DBs, CREATE TABLE IF NOT EXISTS is a no-op for
            # tables that already exist, but CREATE INDEX may fail if
            # referenced columns are missing. We catch and continue.
            try:
                self._conn.executescript(_SCHEMA_SQL)
            except Exception:
                pass
            # Always run migration to add missing columns to existing tables.
            self._migrate_schema()
            # Re-run CREATE INDEX statements after migration has added columns.
            try:
                self._conn.executescript(_SCHEMA_SQL)
            except Exception:
                pass
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: failed to initialize DB: %s", e)
            self._conn = None

    def _migrate_schema(self) -> None:
        """Add missing columns to existing tables.

        CREATE TABLE IF NOT EXISTS is a no-op for tables that already exist
        but have fewer columns than the current schema. This method inspects
        existing columns via PRAGMA table_info and adds any missing ones.
        """
        if self._conn is None:
            return

        # Expected columns per table: (column_name, column_def)
        _EXPECTED_COLUMNS: dict[str, list[tuple[str, str]]] = {
            "traces": [
                ("request_id", "TEXT"),
                ("repo_url", "TEXT"),
                ("root_prompt_preview", "TEXT"),
                ("total_execution_time_s", "REAL"),
                ("child_dispatch_count", "INTEGER"),
                ("child_total_batch_dispatches", "INTEGER"),
                ("child_error_counts", "TEXT"),
                ("structured_output_failures", "INTEGER"),
                ("finish_safety_count", "INTEGER"),
                ("finish_recitation_count", "INTEGER"),
                ("finish_max_tokens_count", "INTEGER"),
                ("tool_invocation_summary", "TEXT"),
                ("artifact_saves", "INTEGER"),
                ("artifact_bytes_saved", "INTEGER"),
                ("per_iteration_breakdown", "TEXT"),
                ("model_usage_summary", "TEXT"),
                ("config_json", "TEXT"),
                ("prompt_hash", "TEXT"),
                ("max_depth_reached", "INTEGER"),
            ],
            "telemetry": [
                ("agent_name", "TEXT"),
                ("iteration", "INTEGER"),
                ("depth", "INTEGER DEFAULT 0"),
                ("call_number", "INTEGER"),
                ("end_time", "REAL"),
                ("duration_ms", "REAL"),
                ("model", "TEXT"),
                ("input_tokens", "INTEGER"),
                ("output_tokens", "INTEGER"),
                ("thought_tokens", "INTEGER"),
                ("finish_reason", "TEXT"),
                ("num_contents", "INTEGER"),
                ("agent_type", "TEXT"),
                ("prompt_chars", "INTEGER"),
                ("system_chars", "INTEGER"),
                ("tool_name", "TEXT"),
                ("tool_args_keys", "TEXT"),
                ("result_preview", "TEXT"),
                ("repl_has_errors", "INTEGER"),
                ("repl_has_output", "INTEGER"),
                ("repl_llm_calls", "INTEGER"),
                ("repl_stdout_len", "INTEGER"),
                ("repl_stderr_len", "INTEGER"),
                ("repl_trace_summary", "TEXT"),
                ("skill_instruction", "TEXT"),
                ("result_payload", "TEXT"),
                ("repl_stdout", "TEXT"),
                ("repl_stderr", "TEXT"),
                ("fanout_idx", "INTEGER"),
                ("parent_depth", "INTEGER"),
                ("parent_fanout_idx", "INTEGER"),
                ("branch", "TEXT"),
                ("invocation_id", "TEXT"),
                ("session_id", "TEXT"),
                ("output_schema_name", "TEXT"),
                ("decision_mode", "TEXT"),
                ("structured_outcome", "TEXT"),
                ("terminal_completion", "INTEGER"),
                ("custom_metadata_json", "TEXT"),
                ("validated_output_json", "TEXT"),
                ("status", "TEXT DEFAULT 'ok'"),
                ("error_type", "TEXT"),
                ("error_message", "TEXT"),
            ],
            "session_state_events": [
                ("event_author", "TEXT"),
                ("key_depth", "INTEGER DEFAULT 0"),
                ("key_fanout", "INTEGER"),
                ("value_type", "TEXT"),
                ("value_int", "INTEGER"),
                ("value_float", "REAL"),
                ("value_text", "TEXT"),
                ("value_json", "TEXT"),
            ],
            "spans": [
                ("parent_span_id", "TEXT"),
                ("operation_name", "TEXT"),
                ("agent_name", "TEXT"),
                ("start_time", "REAL"),
                ("end_time", "REAL"),
                ("status", "TEXT DEFAULT 'ok'"),
                ("attributes", "TEXT"),
                ("events", "TEXT"),
            ],
        }

        try:
            for table, expected_cols in _EXPECTED_COLUMNS.items():
                existing = {
                    row[1] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for col_name, col_def in expected_cols:
                    if col_name not in existing:
                        self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
            self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: schema migration failed: %s", e)

    def _new_id(self) -> str:
        """Generate a new unique ID."""
        return uuid.uuid4().hex

    @staticmethod
    def _pending_key(obj: Any) -> int:
        """Return a stable in-process key for pairing before/after callbacks."""
        return id(obj)

    def make_telemetry_finalizer(self) -> "Callable[[int, dict], None]":
        """Create a closure that finalizes pending tool telemetry rows.

        The returned callable uses the same ``id(tool_context)`` key as
        ``_pending_key()`` to look up the pending telemetry row inserted by
        ``before_tool_callback``.  REPLTool calls this at every return path
        so that tool rows are finalized even when ADK's ``after_tool_callback``
        does not fire (GAP-06).

        The finalizer is idempotent: if ``after_tool_callback`` already
        consumed the pending entry, the finalizer is a no-op.
        """
        pending = self._pending_tool_telemetry
        update = self._update_telemetry
        coerce_int = self._coerce_int

        def _finalize(tool_context_id: int, result: dict) -> None:
            entry = pending.pop(tool_context_id, None)
            if entry is None:
                return  # Already finalized by after_tool_callback
            telemetry_id, start_time = entry
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000
            update_kwargs: dict[str, Any] = {
                "end_time": end_time,
                "duration_ms": duration_ms,
                "result_preview": str(result)[:500],
                "result_payload": _serialize_payload(result),
            }
            if isinstance(result, dict) and result.get("call_number") is not None:
                update_kwargs["call_number"] = coerce_int(result.get("call_number"))
            # REPL enrichment from result dict
            if isinstance(result, dict):
                stdout = result.get("stdout")
                stderr = result.get("stderr")
                update_kwargs["repl_has_errors"] = int(bool(result.get("has_errors") or stderr))
                update_kwargs["repl_has_output"] = int(
                    bool(result.get("has_output") or stdout or result.get("output"))
                )
                update_kwargs["repl_llm_calls"] = coerce_int(
                    result.get("total_llm_calls", 1 if result.get("llm_calls_made") else 0)
                )
                update_kwargs["repl_stdout_len"] = len(stdout or "")
                update_kwargs["repl_stderr_len"] = len(stderr or "")
                update_kwargs["repl_stdout"] = stdout or ""
                update_kwargs["repl_stderr"] = stderr or ""
            try:
                update(telemetry_id, **update_kwargs)
            except Exception as e:
                logger.warning("SqliteTracingPlugin: telemetry finalizer failed: %s", e)

        return _finalize

    @staticmethod
    def _coerce_int(value: Any, default: int = 0) -> int:
        """Best-effort integer coercion for callback payloads and mocks."""
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _resolve_repl_state(
        state: Any,
        *,
        tool_depth: int | None,
    ) -> dict[str, Any] | None:
        """Select the best-matching last_repl_result payload from tool state."""
        if not hasattr(state, "items"):
            return None

        exact_match: dict[str, Any] | None = None
        fallback: dict[str, Any] | None = None
        for raw_key, value in state.items():
            if not isinstance(value, dict):
                continue
            base_key, depth, _ = _parse_key(raw_key)
            if base_key != LAST_REPL_RESULT:
                continue
            if raw_key == LAST_REPL_RESULT:
                exact_match = value
            if tool_depth is not None and depth == tool_depth:
                return value
            if fallback is None:
                fallback = value
        return exact_match or fallback

    # ---- Telemetry write helpers ----

    def _insert_telemetry(
        self,
        telemetry_id: str,
        event_type: str,
        start_time: float,
        **kwargs: Any,
    ) -> None:
        """Insert a telemetry row."""
        if self._conn is None or self._trace_id is None:
            return
        try:
            cols = ["telemetry_id", "trace_id", "event_type", "start_time"]
            vals: list[Any] = [telemetry_id, self._trace_id, event_type, start_time]
            for col, val in kwargs.items():
                cols.append(col)
                vals.append(val)
            placeholders = ", ".join("?" for _ in cols)
            col_str = ", ".join(cols)
            self._conn.execute(
                f"INSERT INTO telemetry ({col_str}) VALUES ({placeholders})",
                vals,
            )
            self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: telemetry insert failed: %s", e)

    def _update_telemetry(self, telemetry_id: str, **kwargs: Any) -> None:
        """Update a telemetry row with additional fields."""
        if self._conn is None or not kwargs:
            return
        try:
            set_clauses = ", ".join(f"{col} = ?" for col in kwargs)
            vals = list(kwargs.values()) + [telemetry_id]
            self._conn.execute(
                f"UPDATE telemetry SET {set_clauses} WHERE telemetry_id = ?",
                vals,
            )
            self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: telemetry update failed: %s", e)

    # ---- Session state events write helper ----

    def _insert_sse(
        self,
        raw_key: str,
        value: Any,
        author: str | None,
        event_time: float,
    ) -> None:
        """Insert a session_state_events row for a curated key."""
        if self._conn is None or self._trace_id is None:
            return
        base_key, depth, fanout = _parse_key(raw_key)
        if not _should_capture(base_key):
            return
        category = _categorize_key(base_key)
        vtype, vint, vfloat, vtext, vjson = _typed_value_for_key(base_key, value)
        try:
            self._conn.execute(
                """INSERT INTO session_state_events
                   (event_id, trace_id, seq, event_author, event_time,
                    state_key, key_category, key_depth, key_fanout,
                    value_type, value_int, value_float, value_text, value_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._new_id(),
                    self._trace_id,
                    self._sse_seq,
                    author,
                    event_time,
                    base_key,
                    category,
                    depth,
                    fanout,
                    vtype,
                    vint,
                    vfloat,
                    vtext,
                    vjson,
                ),
            )
            self._sse_seq += 1
            self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: SSE insert failed: %s", e)

    # ---- Lifecycle callbacks ----

    async def before_run_callback(
        self, *, invocation_context: InvocationContext
    ) -> types.Content | None:
        """Create a new trace row for this invocation."""
        try:
            self._trace_id = uuid.uuid4().hex
            self._agent_span_stack.clear()
            self._pending_model_telemetry.clear()
            self._pending_tool_telemetry.clear()
            self._sse_seq = 0
            if self._conn is not None:
                # Build config snapshot from state and env vars
                state = invocation_context.session.state
                config: dict[str, Any] = {}
                if state.get("app:max_depth") is not None:
                    config["max_depth"] = state["app:max_depth"]
                if state.get("app:max_iterations") is not None:
                    config["max_iterations"] = state["app:max_iterations"]
                for env_key in (
                    "RLM_MAX_DEPTH",
                    "RLM_MAX_CONCURRENT_CHILDREN",
                    "RLM_WORKER_TIMEOUT",
                    "RLM_ADK_MODEL",
                ):
                    val = os.environ.get(env_key)
                    if val is not None:
                        config[f"env_{env_key}"] = val

                self._conn.execute(
                    """INSERT INTO traces
                       (trace_id, session_id, user_id, app_name, start_time, config_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        self._trace_id,
                        invocation_context.session.id,
                        invocation_context.session.user_id,
                        invocation_context.app_name,
                        time.time(),
                        json.dumps(config),
                    ),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: before_run failed: %s", e)
        return None

    def _build_trace_summary_from_telemetry(
        self,
    ) -> dict[str, Any]:
        """Build trace summary stats by querying the telemetry table.

        Returns a dict of column values for the traces UPDATE.
        This replaces the old approach of reading obs:* session-state
        keys, making the telemetry table the authoritative source.
        """
        summary: dict[str, Any] = {}
        if self._conn is None or self._trace_id is None:
            return summary
        tid = self._trace_id

        # Aggregate model-call telemetry
        row = self._conn.execute(
            """SELECT
                 COUNT(*) AS total_calls,
                 COALESCE(SUM(input_tokens), 0),
                 COALESCE(SUM(output_tokens), 0)
               FROM telemetry
               WHERE trace_id = ? AND event_type = 'model_call'
            """,
            (tid,),
        ).fetchone()
        if row:
            summary["total_calls"] = row[0]
            summary["total_input_tokens"] = row[1]
            summary["total_output_tokens"] = row[2]

        # Per-model usage breakdown
        model_rows = self._conn.execute(
            """SELECT model,
                 COUNT(*) AS calls,
                 COALESCE(SUM(input_tokens), 0),
                 COALESCE(SUM(output_tokens), 0)
               FROM telemetry
               WHERE trace_id = ? AND event_type = 'model_call'
                 AND model IS NOT NULL
               GROUP BY model
            """,
            (tid,),
        ).fetchall()
        if model_rows:
            mu: dict[str, Any] = {}
            for m_name, calls, inp, outp in model_rows:
                mu[m_name] = {
                    "calls": calls,
                    "input_tokens": inp,
                    "output_tokens": outp,
                }
            summary["model_usage_summary"] = json.dumps(mu)

        # Finish-reason counts (non-STOP)
        fr_rows = self._conn.execute(
            """SELECT finish_reason, COUNT(*)
               FROM telemetry
               WHERE trace_id = ? AND event_type = 'model_call'
                 AND finish_reason IS NOT NULL
                 AND finish_reason != 'STOP'
               GROUP BY finish_reason
            """,
            (tid,),
        ).fetchall()
        fr_map = {r.lower(): c for r, c in fr_rows}
        summary["finish_safety_count"] = fr_map.get("safety")
        summary["finish_recitation_count"] = fr_map.get("recitation")
        summary["finish_max_tokens_count"] = fr_map.get("max_tokens")

        # Tool invocation summary
        tool_rows = self._conn.execute(
            """SELECT tool_name, COUNT(*)
               FROM telemetry
               WHERE trace_id = ? AND event_type = 'tool_call'
                 AND tool_name IS NOT NULL
               GROUP BY tool_name
            """,
            (tid,),
        ).fetchall()
        if tool_rows:
            tool_summary = {name: cnt for name, cnt in tool_rows}
            summary["tool_invocation_summary"] = json.dumps(tool_summary)

        # Max depth reached from telemetry depth column
        depth_row = self._conn.execute(
            """SELECT MAX(depth)
               FROM telemetry
               WHERE trace_id = ? AND depth IS NOT NULL
            """,
            (tid,),
        ).fetchone()
        summary["max_depth_reached"] = depth_row[0] if depth_row and depth_row[0] else 0

        # Child dispatch counts from tool_call rows at depth > 0
        child_row = self._conn.execute(
            """SELECT COUNT(*)
               FROM telemetry
               WHERE trace_id = ?
                 AND event_type = 'tool_call'
                 AND depth > 0
            """,
            (tid,),
        ).fetchone()
        if child_row and child_row[0]:
            summary["child_dispatch_count"] = child_row[0]

        # Structured output failures (set_model_response with
        # structured_outcome = 'retry_exhausted')
        sf_row = self._conn.execute(
            """SELECT COUNT(*)
               FROM telemetry
               WHERE trace_id = ?
                 AND decision_mode = 'set_model_response'
                 AND structured_outcome = 'retry_exhausted'
            """,
            (tid,),
        ).fetchone()
        if sf_row and sf_row[0]:
            summary["structured_output_failures"] = sf_row[0]

        return summary

    async def after_run_callback(self, *, invocation_context: InvocationContext) -> None:
        """Finalize the trace row with summary stats from telemetry."""
        try:
            if self._conn is None or self._trace_id is None:
                return
            state = invocation_context.session.state
            final_answer = state.get(FINAL_RESPONSE_TEXT, "")
            root_prompt = state.get("root_prompt", "")
            prompt_hash = None
            if root_prompt:
                prompt_hash = hashlib.sha256(root_prompt.encode()).hexdigest()

            # Build summary from telemetry table rows
            summary = self._build_trace_summary_from_telemetry()

            self._conn.execute(
                """UPDATE traces SET
                   end_time = ?,
                   status = 'completed',
                   total_input_tokens = ?,
                   total_output_tokens = ?,
                   total_calls = ?,
                   iterations = ?,
                   final_answer_length = ?,
                   request_id = ?,
                   repo_url = ?,
                   root_prompt_preview = ?,
                   total_execution_time_s = ?,
                   child_dispatch_count = ?,
                   child_total_batch_dispatches = ?,
                   child_error_counts = ?,
                   structured_output_failures = ?,
                   finish_safety_count = ?,
                   finish_recitation_count = ?,
                   finish_max_tokens_count = ?,
                   tool_invocation_summary = ?,
                   artifact_saves = ?,
                   artifact_bytes_saved = ?,
                   per_iteration_breakdown = ?,
                   model_usage_summary = ?,
                   prompt_hash = ?,
                   max_depth_reached = ?
                   WHERE trace_id = ?""",
                (
                    time.time(),
                    summary.get("total_input_tokens", 0),
                    summary.get("total_output_tokens", 0),
                    summary.get("total_calls", 0),
                    state.get(ITERATION_COUNT, 0),
                    len(final_answer) if final_answer else 0,
                    state.get("request_id"),
                    state.get("repo_url"),
                    root_prompt[:500] if root_prompt else None,
                    (time.time() - state.get(INVOCATION_START_TIME, 0))
                    if state.get(INVOCATION_START_TIME)
                    else None,
                    summary.get("child_dispatch_count"),
                    None,  # child_total_batch_dispatches
                    None,  # child_error_counts
                    summary.get("structured_output_failures"),
                    summary.get("finish_safety_count"),
                    summary.get("finish_recitation_count"),
                    summary.get("finish_max_tokens_count"),
                    summary.get("tool_invocation_summary"),
                    self._artifact_saves_count or None,
                    None,  # artifact_bytes_saved: no longer tracked via state
                    None,  # per_iteration_breakdown
                    summary.get("model_usage_summary"),
                    prompt_hash,
                    summary.get("max_depth_reached", 0),
                    self._trace_id,
                ),
            )
            self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: after_run failed: %s", e)

    # ---- Agent callbacks ----

    async def before_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> types.Content | None:
        """Track agent name for parent context (no span write)."""
        try:
            agent_name = getattr(agent, "name", "unknown")
            self._agent_span_stack.append(agent_name)
        except Exception as e:
            logger.warning("SqliteTracingPlugin: before_agent failed: %s", e)
        return None

    async def after_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> types.Content | None:
        """Pop agent from context stack."""
        try:
            if self._agent_span_stack:
                self._agent_span_stack.pop()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: after_agent failed: %s", e)
        return None

    # ---- Model callbacks ----

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        """Insert a telemetry row for model_call and store ID for pairing."""
        try:
            model = llm_request.model or "unknown"
            num_contents = len(llm_request.contents) if llm_request.contents else 0
            iteration = callback_context.state.get(ITERATION_COUNT, 0)
            agent_name = self._agent_span_stack[-1] if self._agent_span_stack else None

            # Resolve agent from invocation context
            inv_ctx = getattr(
                callback_context,
                "_invocation_context",
                None,
            )
            agent = getattr(inv_ctx, "agent", None)

            # Compute depth/fanout/parent from agent attrs
            depth = self._coerce_int(getattr(agent, "_rlm_depth", 0))
            fanout_idx = getattr(agent, "_rlm_fanout_idx", None)
            parent_depth = getattr(agent, "_rlm_parent_depth", None)
            parent_fanout_idx = getattr(agent, "_rlm_parent_fanout_idx", None)
            output_schema_name = getattr(agent, "_rlm_output_schema_name", None)

            # Compute prompt/system chars directly from
            # llm_request instead of CONTEXT_WINDOW_SNAPSHOT
            prompt_chars = 0
            system_chars = 0
            if llm_request.contents:
                for content in llm_request.contents:
                    parts = getattr(content, "parts", None)
                    if parts:
                        for part in parts:
                            t = getattr(part, "text", None)
                            if t:
                                prompt_chars += len(t)
            config = getattr(llm_request, "config", None)
            sys_inst = getattr(config, "system_instruction", None)
            if sys_inst:
                si_parts = getattr(sys_inst, "parts", None)
                if si_parts:
                    for part in si_parts:
                        t = getattr(part, "text", None)
                        if t:
                            system_chars += len(t)

            # Branch / invocation / session identifiers
            branch = getattr(inv_ctx, "branch", None)
            invocation_id = getattr(inv_ctx, "invocation_id", None)
            session = getattr(inv_ctx, "session", None)
            session_id = getattr(session, "id", None)

            self._model_call_count += 1
            call_number = self._model_call_count
            skill_instruction = callback_context.state.get(DYN_SKILL_INSTRUCTION)

            telemetry_id = self._new_id()
            start_time = time.time()
            self._insert_telemetry(
                telemetry_id,
                "model_call",
                start_time,
                model=model,
                num_contents=num_contents,
                iteration=iteration,
                agent_name=agent_name,
                prompt_chars=prompt_chars or None,
                system_chars=system_chars or None,
                call_number=call_number,
                skill_instruction=skill_instruction,
                depth=depth,
                fanout_idx=fanout_idx,
                parent_depth=parent_depth,
                parent_fanout_idx=parent_fanout_idx,
                branch=branch,
                invocation_id=invocation_id,
                session_id=session_id,
                output_schema_name=output_schema_name,
            )
            self._pending_model_telemetry[self._pending_key(callback_context)] = (
                telemetry_id,
                start_time,
            )
        except Exception as e:
            logger.warning(
                "SqliteTracingPlugin: before_model failed: %s",
                e,
            )
        return None

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        """Update telemetry row with tokens, finish_reason, duration,
        and custom_metadata['rlm'] lineage."""
        try:
            pending = self._pending_model_telemetry.pop(
                self._pending_key(callback_context),
                None,
            )
            if pending is None and self._pending_model_telemetry:
                _, pending = self._pending_model_telemetry.popitem()

            tokens_in = 0
            tokens_out = 0
            thought_tokens = 0
            if llm_response.usage_metadata:
                tokens_in = self._coerce_int(
                    getattr(
                        llm_response.usage_metadata,
                        "prompt_token_count",
                        0,
                    ),
                )
                tokens_out = self._coerce_int(
                    getattr(
                        llm_response.usage_metadata,
                        "candidates_token_count",
                        0,
                    ),
                )
                thought_tokens = self._coerce_int(
                    getattr(
                        llm_response.usage_metadata,
                        "thoughts_token_count",
                        0,
                    ),
                )

            finish_reason = None
            if llm_response.finish_reason:
                finish_reason = (
                    llm_response.finish_reason.name
                    if hasattr(llm_response.finish_reason, "name")
                    else str(llm_response.finish_reason)
                )

            # Extract custom_metadata["rlm"] lineage
            rlm_meta = None
            custom_meta = getattr(llm_response, "custom_metadata", None)
            if isinstance(custom_meta, dict):
                rlm_meta = custom_meta.get("rlm")
            custom_metadata_json = None
            if rlm_meta is not None:
                try:
                    custom_metadata_json = json.dumps(rlm_meta, default=str)
                except (TypeError, ValueError):
                    pass

            # Project lineage fields from rlm metadata
            # into dedicated telemetry columns.
            lineage_kwargs: dict[str, Any] = {}
            if isinstance(rlm_meta, dict):
                dm = rlm_meta.get("decision_mode")
                if dm:
                    lineage_kwargs["decision_mode"] = dm
                so = rlm_meta.get("structured_outcome")
                if so and so != "not_applicable":
                    lineage_kwargs["structured_outcome"] = so
                if rlm_meta.get("terminal"):
                    lineage_kwargs["terminal_completion"] = 1

            end_time = time.time()

            if pending:
                telemetry_id, start_time = pending
                duration_ms = (end_time - start_time) * 1000
                update_kwargs: dict[str, Any] = {
                    "end_time": end_time,
                    "duration_ms": duration_ms,
                    "input_tokens": tokens_in,
                    "output_tokens": tokens_out,
                    "thought_tokens": thought_tokens,
                    "finish_reason": finish_reason,
                }
                if custom_metadata_json:
                    update_kwargs["custom_metadata_json"] = custom_metadata_json
                update_kwargs.update(lineage_kwargs)
                if llm_response.error_code:
                    update_kwargs["status"] = "error"
                    update_kwargs["error_type"] = str(llm_response.error_code)
                    update_kwargs["error_message"] = str(llm_response.error_message or "")[:500]
                self._update_telemetry(telemetry_id, **update_kwargs)
            else:
                # Standalone telemetry row
                standalone_id = self._new_id()
                insert_kw: dict[str, Any] = {
                    "end_time": end_time,
                    "duration_ms": 0,
                    "model": (llm_response.model_version or "unknown"),
                    "input_tokens": tokens_in,
                    "output_tokens": tokens_out,
                    "thought_tokens": thought_tokens,
                    "finish_reason": finish_reason,
                    "status": ("error" if llm_response.error_code else "ok"),
                }
                if custom_metadata_json:
                    insert_kw["custom_metadata_json"] = custom_metadata_json
                insert_kw.update(lineage_kwargs)
                self._insert_telemetry(
                    standalone_id,
                    "model_call",
                    end_time,
                    **insert_kw,
                )
        except Exception as e:
            logger.warning(
                "SqliteTracingPlugin: after_model failed: %s",
                e,
            )
        return None

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> LlmResponse | None:
        """Mark the pending model telemetry row as an error."""
        try:
            pending = self._pending_model_telemetry.pop(
                self._pending_key(callback_context),
                None,
            )
            if pending is None and self._pending_model_telemetry:
                _, pending = self._pending_model_telemetry.popitem()
            if pending:
                telemetry_id, start_time = pending
                end_time = time.time()
                self._update_telemetry(
                    telemetry_id,
                    end_time=end_time,
                    duration_ms=(end_time - start_time) * 1000,
                    status="error",
                    error_type=type(error).__name__,
                    error_message=str(error)[:500],
                )
        except Exception as e:
            logger.warning("SqliteTracingPlugin: on_model_error failed: %s", e)
        return None

    # ---- Tool callbacks ----

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict | None:
        """Insert a telemetry row for tool_call with full scope."""
        try:
            tool_name = getattr(tool, "name", str(tool))
            telemetry_id = self._new_id()
            start_time = time.time()
            agent_name = self._agent_span_stack[-1] if self._agent_span_stack else None
            tool_depth = self._coerce_int(getattr(tool, "_depth", 0))
            iteration = None
            state = getattr(tool_context, "state", None)
            if hasattr(state, "get"):
                depth_key_name = (
                    "iteration_count" if tool_depth == 0 else f"iteration_count@d{tool_depth}"
                )
                iteration = state.get(depth_key_name)

            # Resolve agent for scope fields
            inv_ctx = getattr(tool_context, "_invocation_context", None)
            agent = getattr(inv_ctx, "agent", None)
            fanout_idx = getattr(agent, "_rlm_fanout_idx", None)
            parent_depth = getattr(agent, "_rlm_parent_depth", None)
            parent_fanout_idx = getattr(agent, "_rlm_parent_fanout_idx", None)
            output_schema_name = getattr(agent, "_rlm_output_schema_name", None)
            branch = getattr(inv_ctx, "branch", None)
            invocation_id = getattr(inv_ctx, "invocation_id", None)
            session = getattr(inv_ctx, "session", None)
            session_id = getattr(session, "id", None)

            self._insert_telemetry(
                telemetry_id,
                "tool_call",
                start_time,
                tool_name=tool_name,
                tool_args_keys=json.dumps(list(tool_args.keys())),
                agent_name=agent_name,
                depth=tool_depth,
                iteration=(self._coerce_int(iteration) if iteration is not None else None),
                fanout_idx=fanout_idx,
                parent_depth=parent_depth,
                parent_fanout_idx=parent_fanout_idx,
                branch=branch,
                invocation_id=invocation_id,
                session_id=session_id,
                output_schema_name=output_schema_name,
            )
            self._pending_tool_telemetry[self._pending_key(tool_context)] = (
                telemetry_id,
                start_time,
            )
        except Exception as e:
            logger.warning("SqliteTracingPlugin: before_tool failed: %s", e)
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict,
    ) -> dict | None:
        """Update the tool telemetry row with result preview,
        duration, and lineage status."""
        try:
            tool_name = getattr(tool, "name", str(tool))
            pending = self._pending_tool_telemetry.pop(
                self._pending_key(tool_context),
                None,
            )
            if pending:
                telemetry_id, start_time = pending
                end_time = time.time()
                duration_ms = (end_time - start_time) * 1000
                update_kwargs: dict[str, Any] = {
                    "end_time": end_time,
                    "duration_ms": duration_ms,
                    "result_preview": str(result)[:500],
                    "result_payload": _serialize_payload(result),
                }
                if isinstance(result, dict) and result.get("call_number") is not None:
                    update_kwargs["call_number"] = self._coerce_int(result.get("call_number"))

                # Persist decision_mode / lineage from
                # _rlm_lineage_status on the agent
                inv_ctx = getattr(
                    tool_context,
                    "_invocation_context",
                    None,
                )
                agent = getattr(inv_ctx, "agent", None)
                lineage_status = (
                    getattr(
                        agent,
                        "_rlm_lineage_status",
                        None,
                    )
                    or {}
                )

                if tool_name == "set_model_response":
                    update_kwargs["decision_mode"] = "set_model_response"
                    update_kwargs["structured_outcome"] = lineage_status.get("structured_outcome")
                    is_terminal = bool(lineage_status.get("terminal"))
                    update_kwargs["terminal_completion"] = int(is_terminal)
                    # Only persist validated_output_json for
                    # terminal validated payloads, not retries.
                    if is_terminal:
                        update_kwargs["validated_output_json"] = json.dumps(result, default=str)
                elif tool_name == "execute_code":
                    update_kwargs["decision_mode"] = "execute_code"

                # REPL enrichment
                if tool_name == "execute_code" and isinstance(result, dict):
                    state = getattr(tool_context, "state", None)
                    repl_state = self._resolve_repl_state(
                        state,
                        tool_depth=getattr(tool, "_depth", None),
                    )
                    stdout = result.get("stdout")
                    stderr = result.get("stderr")
                    if repl_state is not None:
                        update_kwargs["repl_has_errors"] = int(
                            bool(repl_state.get("has_errors", False))
                        )
                        update_kwargs["repl_has_output"] = int(
                            bool(repl_state.get("has_output", False))
                        )
                        update_kwargs["repl_llm_calls"] = repl_state.get(
                            "total_llm_calls",
                            0,
                        )
                        trace_summary = repl_state.get("trace_summary")
                        if trace_summary is not None:
                            update_kwargs["repl_trace_summary"] = json.dumps(trace_summary)
                    else:
                        update_kwargs["repl_has_errors"] = int(
                            bool(result.get("has_errors") or stderr)
                        )
                        update_kwargs["repl_has_output"] = int(
                            bool(result.get("has_output") or stdout or result.get("output"))
                        )
                        update_kwargs["repl_llm_calls"] = result.get(
                            "total_llm_calls",
                            (1 if result.get("llm_calls_made") else 0),
                        )
                    update_kwargs["repl_llm_calls"] = self._coerce_int(
                        update_kwargs["repl_llm_calls"],
                    )
                    update_kwargs["repl_stdout_len"] = len(stdout or "")
                    update_kwargs["repl_stderr_len"] = len(stderr or "")
                    update_kwargs["repl_stdout"] = stdout or ""
                    update_kwargs["repl_stderr"] = stderr or ""
                self._update_telemetry(telemetry_id, **update_kwargs)
        except Exception as e:
            logger.warning(
                "SqliteTracingPlugin: after_tool failed: %s",
                e,
            )
        return None

    # ---- Event callback ----

    async def on_event_callback(
        self, *, invocation_context: InvocationContext, event: Event
    ) -> Event | None:
        """Capture curated state_delta keys as session_state_events rows."""
        try:
            now = time.time()
            author = event.author

            # Capture curated state_delta keys
            if event.actions and event.actions.state_delta:
                for raw_key, value in event.actions.state_delta.items():
                    self._insert_sse(raw_key, value, author, now)

            # Keep artifact_delta tracking (backward compat via SSE)
            if event.actions and event.actions.artifact_delta:
                self._artifact_saves_count += len(event.actions.artifact_delta)
                for art_key, art_ver in event.actions.artifact_delta.items():
                    self._insert_sse(
                        f"artifact_{art_key}",
                        art_ver,
                        author,
                        now,
                    )
        except Exception as e:
            logger.warning("SqliteTracingPlugin: on_event failed: %s", e)
        return None

    # ---- Cleanup ----

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
