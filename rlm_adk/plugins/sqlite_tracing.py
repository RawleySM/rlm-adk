"""SqliteTracingPlugin - Local SQLite-based telemetry.

Captures structured telemetry from ADK callbacks into a local traces.db file
using a 3-table schema: traces (enriched), telemetry, session_state_events.

No external dependencies beyond the Python standard library (sqlite3).
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import uuid
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
    CONTEXT_WINDOW_SNAPSHOT,
    DYN_SKILL_INSTRUCTION,
    FINAL_ANSWER,
    ITERATION_COUNT,
    LAST_REPL_RESULT,
    OBS_CHILD_TOTAL_BATCH_DISPATCHES,
    OBS_TOTAL_CALLS,
    OBS_TOTAL_INPUT_TOKENS,
    OBS_TOTAL_OUTPUT_TOKENS,
    REASONING_PARSED_OUTPUT,
    REASONING_RAW_OUTPUT,
    REASONING_THOUGHT_TEXT,
    REASONING_VISIBLE_OUTPUT_TEXT,
)

logger = logging.getLogger(__name__)

# ---- Depth/fanout key parser ----

_DEPTH_FANOUT_RE = re.compile(r'^(.+)@d(\d+)(?:f(\d+))?$')


def _parse_key(raw_key: str) -> tuple[str, int, int | None]:
    """Parse depth/fanout suffix from a state key.

    Returns (base_key, depth, fanout_or_None).
    """
    m = _DEPTH_FANOUT_RE.match(raw_key)
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3)) if m.group(3) else None
    return raw_key, 0, None


# ---- Key categorization ----

def _categorize_key(key: str) -> str:
    """Categorize a state key for the session_state_events table."""
    if key.startswith("obs:total_") or key.startswith("obs:per_iteration"):
        return "obs_reasoning"
    if key.startswith("obs:child_") or key.startswith("obs:worker_"):
        return "obs_dispatch"
    if key.startswith("obs:artifact_") or key.startswith("artifact_"):
        return "obs_artifact"
    if key.startswith("obs:finish_"):
        return "obs_finish"
    if key.startswith("obs:model_usage:"):
        return "obs_reasoning"
    if key.startswith("obs:tool_"):
        return "obs_reasoning"
    if key.startswith("obs:structured_"):
        return "obs_dispatch"
    if key in ("iteration_count", "should_stop", "final_answer", "policy_violation"):
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
    if key.startswith("reasoning_"):
        return "obs_reasoning"
    if key.startswith("cache:"):
        return "cache"
    if key in ("request_id", "idempotency_key", "repo_url", "root_prompt", "skill_instruction"):
        return "request_meta"
    return "other"


# ---- Curated capture set ----

_CURATED_PREFIXES = (
    "obs:",
    "artifact_",
    "last_repl_result",
    "repl_submitted_code",
    "repl_expanded_code",
    "repl_skill_expansion_meta",
    "repl_did_expand",
)

_CURATED_EXACT = {
    "iteration_count", "should_stop", "final_answer", "policy_violation",
    "request_id", "idempotency_key", "repo_url", "root_prompt", "skill_instruction",
    "cache:hit_count", "cache:miss_count", "cache:last_hit_key",
    "worker_dispatch_count",
    REASONING_VISIBLE_OUTPUT_TEXT,
    REASONING_THOUGHT_TEXT,
    REASONING_RAW_OUTPUT,
    REASONING_PARSED_OUTPUT,
}

_FULL_TEXT_SSE_KEYS = {
    REASONING_VISIBLE_OUTPUT_TEXT,
    REASONING_THOUGHT_TEXT,
    REASONING_RAW_OUTPUT,
}


def _should_capture(base_key: str) -> bool:
    """Return True if this key should be captured in session_state_events."""
    if base_key in _CURATED_EXACT:
        return True
    for prefix in _CURATED_PREFIXES:
        if base_key.startswith(prefix):
            return True
    return False


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
    """Return a typed row payload, preserving full text for live-inspection keys."""
    if base_key in _FULL_TEXT_SSE_KEYS and isinstance(value, str):
        return "str", None, None, value, None
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
                    row[1]
                    for row in self._conn.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                }
                for col_name, col_def in expected_cols:
                    if col_name not in existing:
                        self._conn.execute(
                            f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"
                        )
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

    async def after_run_callback(
        self, *, invocation_context: InvocationContext
    ) -> None:
        """Finalize the trace row with summary stats and enriched columns."""
        try:
            if self._conn is not None and self._trace_id is not None:
                state = invocation_context.session.state
                final_answer = state.get(FINAL_ANSWER, "")

                # Aggregate model usage from obs:model_usage:* keys
                model_usage: dict[str, Any] = {}
                for k, v in state.items():
                    if k.startswith("obs:model_usage:") and isinstance(v, dict):
                        model_name = k[len("obs:model_usage:"):]
                        model_usage[model_name] = v

                root_prompt = state.get("root_prompt", "")

                # Compute prompt hash
                prompt_hash = None
                if root_prompt:
                    prompt_hash = hashlib.sha256(root_prompt.encode()).hexdigest()

                # Compute max depth reached from telemetry agent_name patterns
                max_depth_reached = 0
                depth_re = re.compile(r'_d(\d+)')
                rows = self._conn.execute(
                    "SELECT DISTINCT agent_name FROM telemetry WHERE trace_id = ? AND agent_name IS NOT NULL",
                    (self._trace_id,),
                ).fetchall()
                for (agent_name,) in rows:
                    m = depth_re.search(agent_name)
                    if m:
                        d = int(m.group(1))
                        if d > max_depth_reached:
                            max_depth_reached = d

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
                        state.get(OBS_TOTAL_INPUT_TOKENS, 0),
                        state.get(OBS_TOTAL_OUTPUT_TOKENS, 0),
                        state.get(OBS_TOTAL_CALLS, 0),
                        state.get(ITERATION_COUNT, 0),
                        len(final_answer) if final_answer else 0,
                        state.get("request_id"),
                        state.get("repo_url"),
                        root_prompt[:500] if root_prompt else None,
                        state.get("obs:total_execution_time"),
                        state.get("obs:child_dispatch_count"),
                        state.get(OBS_CHILD_TOTAL_BATCH_DISPATCHES),
                        json.dumps(state.get("obs:child_error_counts")) if state.get("obs:child_error_counts") else None,
                        state.get("obs:structured_output_failures"),
                        state.get("obs:finish_safety_count"),
                        state.get("obs:finish_recitation_count"),
                        state.get("obs:finish_max_tokens_count"),
                        json.dumps(state.get("obs:tool_invocation_summary")) if state.get("obs:tool_invocation_summary") else None,
                        state.get("obs:artifact_saves"),
                        state.get("obs:artifact_bytes_saved"),
                        json.dumps(state.get("obs:per_iteration_token_breakdown")) if state.get("obs:per_iteration_token_breakdown") else None,
                        json.dumps(model_usage) if model_usage else None,
                        prompt_hash,
                        max_depth_reached,
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
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        """Insert a telemetry row for model_call and store ID for pairing."""
        try:
            model = llm_request.model or "unknown"
            num_contents = len(llm_request.contents) if llm_request.contents else 0
            iteration = callback_context.state.get(ITERATION_COUNT, 0)
            agent_name = self._agent_span_stack[-1] if self._agent_span_stack else None
            depth = getattr(
                getattr(callback_context, "_invocation_context", None),
                "agent",
                None,
            )
            depth = self._coerce_int(getattr(depth, "_rlm_depth", 0))

            # Extract agent_type, prompt_chars, system_chars from context snapshot
            context_snapshot = callback_context.state.get(CONTEXT_WINDOW_SNAPSHOT)
            agent_type = None
            prompt_chars = None
            system_chars = None
            if isinstance(context_snapshot, dict):
                agent_type = context_snapshot.get("agent_type")
                prompt_chars = context_snapshot.get("prompt_chars")
                system_chars = context_snapshot.get("system_chars")

            call_number = callback_context.state.get(OBS_TOTAL_CALLS)
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
                agent_type=agent_type,
                prompt_chars=prompt_chars,
                system_chars=system_chars,
                call_number=call_number,
                skill_instruction=skill_instruction,
                depth=depth,
            )
            self._pending_model_telemetry[self._pending_key(callback_context)] = (
                telemetry_id,
                start_time,
            )
        except Exception as e:
            logger.warning("SqliteTracingPlugin: before_model failed: %s", e)
        return None

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        """Update telemetry row with tokens, finish_reason, duration."""
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
                    getattr(llm_response.usage_metadata, "prompt_token_count", 0),
                )
                tokens_out = self._coerce_int(
                    getattr(llm_response.usage_metadata, "candidates_token_count", 0),
                )
                thought_tokens = self._coerce_int(
                    getattr(llm_response.usage_metadata, "thoughts_token_count", 0),
                )

            finish_reason = None
            if llm_response.finish_reason:
                finish_reason = llm_response.finish_reason.name if hasattr(llm_response.finish_reason, "name") else str(llm_response.finish_reason)

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
                if llm_response.error_code:
                    update_kwargs["status"] = "error"
                    update_kwargs["error_type"] = str(llm_response.error_code)
                    update_kwargs["error_message"] = str(llm_response.error_message or "")[:500]
                self._update_telemetry(telemetry_id, **update_kwargs)
            else:
                # Standalone telemetry row
                standalone_id = self._new_id()
                self._insert_telemetry(
                    standalone_id,
                    "model_call",
                    end_time,
                    end_time=end_time,
                    duration_ms=0,
                    model=llm_response.model_version or "unknown",
                    input_tokens=tokens_in,
                    output_tokens=tokens_out,
                    thought_tokens=thought_tokens,
                    finish_reason=finish_reason,
                    status="error" if llm_response.error_code else "ok",
                )
        except Exception as e:
            logger.warning("SqliteTracingPlugin: after_model failed: %s", e)
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
        """Insert a telemetry row for tool_call."""
        try:
            tool_name = getattr(tool, "name", str(tool))
            telemetry_id = self._new_id()
            start_time = time.time()
            agent_name = self._agent_span_stack[-1] if self._agent_span_stack else None
            tool_depth = self._coerce_int(getattr(tool, "_depth", 0))
            iteration = None
            state = getattr(tool_context, "state", None)
            if hasattr(state, "get"):
                depth_key_name = "iteration_count" if tool_depth == 0 else f"iteration_count@d{tool_depth}"
                iteration = state.get(depth_key_name)
            self._insert_telemetry(
                telemetry_id,
                "tool_call",
                start_time,
                tool_name=tool_name,
                tool_args_keys=json.dumps(list(tool_args.keys())),
                agent_name=agent_name,
                depth=tool_depth,
                iteration=self._coerce_int(iteration) if iteration is not None else None,
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
        """Update the tool telemetry row with result preview and duration."""
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
                            1 if result.get("llm_calls_made") else 0,
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
            logger.warning("SqliteTracingPlugin: after_tool failed: %s", e)
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
