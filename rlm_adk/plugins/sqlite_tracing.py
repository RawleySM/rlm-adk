"""SqliteTracingPlugin - Local SQLite-based span tracing.

Captures span-like telemetry from ADK callbacks into a local traces.db file.
Provides a lightweight alternative to Langfuse for local development and
evaluation agent queries.

No external dependencies beyond the Python standard library (sqlite3).
"""

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from rlm_adk.state import (
    FINAL_ANSWER,
    ITERATION_COUNT,
    OBS_TOTAL_CALLS,
    OBS_TOTAL_INPUT_TOKENS,
    OBS_TOTAL_OUTPUT_TOKENS,
)

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS traces (
    trace_id            TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    user_id             TEXT,
    app_name            TEXT,
    start_time          REAL NOT NULL,
    end_time            REAL,
    status              TEXT DEFAULT 'running',
    total_input_tokens  INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_calls         INTEGER DEFAULT 0,
    iterations          INTEGER DEFAULT 0,
    final_answer_length INTEGER,
    metadata            TEXT
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

CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_operation ON spans(operation_name);
CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id);
CREATE INDEX IF NOT EXISTS idx_traces_start ON traces(start_time);
"""


class SqliteTracingPlugin(BasePlugin):
    """ADK Plugin that writes span-like telemetry to a local SQLite database.

    Each invocation (runner.run_async call) creates one trace row.
    Each callback event (before/after model, tool, agent) creates one span row.

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
        self._conn: Optional[sqlite3.Connection] = None
        self._trace_id: Optional[str] = None
        # Stack of active span IDs for parent tracking.
        # before_agent pushes, after_agent pops.
        self._agent_span_stack: list[str] = []
        # Map of model key -> span_id for pairing before_model -> after_model spans.
        self._pending_model_spans: dict[str, str] = {}
        # Map of tool_name -> span_id for pairing before_tool -> after_tool spans.
        self._pending_tool_spans: dict[str, str] = {}
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database connection and create tables."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: failed to initialize DB: %s", e)
            self._conn = None

    def _new_span_id(self) -> str:
        """Generate a new unique span ID."""
        return uuid.uuid4().hex

    def _current_parent_span_id(self) -> Optional[str]:
        """Return the span_id of the most recent unfinished agent span."""
        return self._agent_span_stack[-1] if self._agent_span_stack else None

    def _write_span(
        self,
        span_id: str,
        operation_name: str,
        agent_name: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        status: str = "ok",
        attributes: Optional[dict] = None,
        parent_span_id: Optional[str] = None,
    ) -> None:
        """Insert a span row into the database."""
        if self._conn is None or self._trace_id is None:
            return
        try:
            self._conn.execute(
                """INSERT OR REPLACE INTO spans
                   (span_id, trace_id, parent_span_id, operation_name,
                    agent_name, start_time, end_time, status, attributes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    span_id,
                    self._trace_id,
                    parent_span_id if parent_span_id is not None else self._current_parent_span_id(),
                    operation_name,
                    agent_name,
                    start_time or time.time(),
                    end_time,
                    status,
                    json.dumps(attributes) if attributes else None,
                ),
            )
            self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: span write failed: %s", e)

    def _update_span_end(
        self,
        span_id: str,
        end_time: float,
        status: str = "ok",
        attributes: Optional[dict] = None,
    ) -> None:
        """Update a span row with end_time and optional attributes."""
        if self._conn is None:
            return
        try:
            if attributes:
                self._conn.execute(
                    "UPDATE spans SET end_time = ?, status = ?, attributes = ? WHERE span_id = ?",
                    (end_time, status, json.dumps(attributes), span_id),
                )
            else:
                self._conn.execute(
                    "UPDATE spans SET end_time = ?, status = ? WHERE span_id = ?",
                    (end_time, status, span_id),
                )
            self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: span update failed: %s", e)

    # ---- Lifecycle callbacks ----

    async def before_run_callback(
        self, *, invocation_context: InvocationContext
    ) -> Optional[types.Content]:
        """Create a new trace row for this invocation."""
        try:
            self._trace_id = uuid.uuid4().hex
            self._agent_span_stack.clear()
            self._pending_model_spans.clear()
            self._pending_tool_spans.clear()
            if self._conn is not None:
                self._conn.execute(
                    """INSERT INTO traces
                       (trace_id, session_id, user_id, app_name, start_time)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        self._trace_id,
                        invocation_context.session.id,
                        invocation_context.session.user_id,
                        invocation_context.app_name,
                        time.time(),
                    ),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: before_run failed: %s", e)
        return None

    async def after_run_callback(
        self, *, invocation_context: InvocationContext
    ) -> None:
        """Finalize the trace row with summary stats."""
        try:
            if self._conn is not None and self._trace_id is not None:
                state = invocation_context.session.state
                final_answer = state.get(FINAL_ANSWER, "")
                self._conn.execute(
                    """UPDATE traces SET
                       end_time = ?,
                       status = 'completed',
                       total_input_tokens = ?,
                       total_output_tokens = ?,
                       total_calls = ?,
                       iterations = ?,
                       final_answer_length = ?
                       WHERE trace_id = ?""",
                    (
                        time.time(),
                        state.get(OBS_TOTAL_INPUT_TOKENS, 0),
                        state.get(OBS_TOTAL_OUTPUT_TOKENS, 0),
                        state.get(OBS_TOTAL_CALLS, 0),
                        state.get(ITERATION_COUNT, 0),
                        len(final_answer) if final_answer else 0,
                        self._trace_id,
                    ),
                )
                self._conn.commit()
        except Exception as e:
            logger.warning("SqliteTracingPlugin: after_run failed: %s", e)

    # ---- Agent callbacks ----

    async def before_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        """Create an agent span and push it onto the parent stack."""
        try:
            agent_name = getattr(agent, "name", "unknown")
            span_id = self._new_span_id()
            self._write_span(
                span_id=span_id,
                operation_name="agent",
                agent_name=agent_name,
                attributes={"phase": "start"},
            )
            self._agent_span_stack.append(span_id)
        except Exception as e:
            logger.warning("SqliteTracingPlugin: before_agent failed: %s", e)
        return None

    async def after_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        """Close the most recent agent span by setting its end_time."""
        try:
            if self._agent_span_stack:
                span_id = self._agent_span_stack.pop()
                self._update_span_end(span_id, time.time())
        except Exception as e:
            logger.warning("SqliteTracingPlugin: after_agent failed: %s", e)
        return None

    # ---- Model callbacks ----

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> Optional[LlmResponse]:
        """Create a model_call span and store its ID for pairing with after_model."""
        try:
            model = llm_request.model or "unknown"
            num_contents = len(llm_request.contents) if llm_request.contents else 0
            span_id = self._new_span_id()
            self._write_span(
                span_id=span_id,
                operation_name="model_call",
                agent_name=None,
                attributes={
                    "model": model,
                    "num_contents": num_contents,
                    "iteration": callback_context.state.get(ITERATION_COUNT, 0),
                },
            )
            # Store span_id to pair with after_model
            self._pending_model_spans[model] = span_id
        except Exception as e:
            logger.warning("SqliteTracingPlugin: before_model failed: %s", e)
        return None

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> Optional[LlmResponse]:
        """Close the model_call span with token usage and end_time."""
        try:
            model = llm_response.model_version or "unknown"
            span_id = self._pending_model_spans.pop(model, None)
            # Also try popping with "unknown" if model_version not set
            if span_id is None:
                span_id = self._pending_model_spans.pop("unknown", None)
            # Fallback: pop any remaining span
            if span_id is None and self._pending_model_spans:
                _, span_id = self._pending_model_spans.popitem()

            tokens_in = 0
            tokens_out = 0
            if llm_response.usage_metadata:
                tokens_in = getattr(llm_response.usage_metadata, "prompt_token_count", 0) or 0
                tokens_out = getattr(llm_response.usage_metadata, "candidates_token_count", 0) or 0

            attributes = {
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
            }
            if llm_response.error_code:
                attributes["error_code"] = llm_response.error_code
                attributes["error_message"] = llm_response.error_message

            if span_id:
                self._update_span_end(
                    span_id,
                    time.time(),
                    status="error" if llm_response.error_code else "ok",
                    attributes=attributes,
                )
            else:
                # No matching before_model span -- write a standalone span
                standalone_id = self._new_span_id()
                self._write_span(
                    span_id=standalone_id,
                    operation_name="model_call",
                    start_time=time.time(),
                    end_time=time.time(),
                    status="error" if llm_response.error_code else "ok",
                    attributes=attributes,
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
    ) -> Optional[LlmResponse]:
        """Mark the pending model span as an error."""
        try:
            model = llm_request.model or "unknown"
            span_id = self._pending_model_spans.pop(model, None)
            if span_id is None and self._pending_model_spans:
                _, span_id = self._pending_model_spans.popitem()
            if span_id:
                self._update_span_end(
                    span_id,
                    time.time(),
                    status="error",
                    attributes={
                        "error_type": type(error).__name__,
                        "error_message": str(error)[:500],
                    },
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
    ) -> Optional[dict]:
        """Create a tool_call span and store its ID for pairing with after_tool."""
        try:
            tool_name = getattr(tool, "name", str(tool))
            span_id = self._new_span_id()
            self._write_span(
                span_id=span_id,
                operation_name="tool_call",
                attributes={
                    "tool_name": tool_name,
                    "args_keys": list(tool_args.keys()),
                },
            )
            self._pending_tool_spans[tool_name] = span_id
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
    ) -> Optional[dict]:
        """Close the tool_call span with result preview and end_time."""
        try:
            tool_name = getattr(tool, "name", str(tool))
            span_id = self._pending_tool_spans.pop(tool_name, None)
            if span_id:
                self._update_span_end(
                    span_id,
                    time.time(),
                    attributes={"result_preview": str(result)[:200]},
                )
        except Exception as e:
            logger.warning("SqliteTracingPlugin: after_tool failed: %s", e)
        return None

    # ---- Event callback ----

    async def on_event_callback(
        self, *, invocation_context: InvocationContext, event: Event
    ) -> Optional[Event]:
        """Capture artifact delta events as artifact_save spans."""
        try:
            if event.actions and event.actions.artifact_delta:
                span_id = self._new_span_id()
                self._write_span(
                    span_id=span_id,
                    operation_name="artifact_save",
                    agent_name=event.author,
                    start_time=time.time(),
                    end_time=time.time(),
                    attributes={
                        "artifact_delta": {
                            k: v for k, v in event.actions.artifact_delta.items()
                        }
                    },
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
