# FileService Implementation Specification

**Date:** 2026-02-20
**Author:** FileService-Spec-Planning Agent
**Status:** Ready for TDD Implementation
**Scope:** Recommendations 3, 4, 5 from database strategy report + REPL auto-save + create-artifact decision

---

## Table of Contents

1. [Rec 3: Switch to FileArtifactService](#rec-3-switch-to-fileartifactservice)
2. [Rec 4: SqliteTracingPlugin](#rec-4-sqlitetracingplugin)
3. [Rec 5: LangfuseTracingPlugin Optional](#rec-5-langfusetracingplugin-optional)
4. [REPL Code Auto-Save](#repl-code-auto-save)
5. [Create-Artifact Tool Decision](#create-artifact-tool-decision)
6. [TDD Test Plan](#tdd-test-plan)
7. [Dependencies](#dependencies)

---

## Rec 3: Switch to FileArtifactService

### What

Change the default artifact service in `create_rlm_runner()` from `InMemoryArtifactService` (volatile, lost on exit) to `FileArtifactService` (persisted to `.adk/artifacts/`). This enables session rewind to restore artifact versions, and preserves REPL outputs and final answers across restarts.

### Where

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py`
- **Line 33:** Add import for `FileArtifactService`
- **Lines 266-342:** Modify `create_rlm_runner()` to default to `FileArtifactService`

### How

#### 3.1 Add Import

At `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py`, line 33, change:

```python
from google.adk.artifacts import BaseArtifactService
```

to:

```python
from google.adk.artifacts import BaseArtifactService, FileArtifactService
```

#### 3.2 Add Default Artifact Root Constant

After the `_DEFAULT_RETRY_OPTIONS` block (after line 60), add:

```python
_DEFAULT_ARTIFACT_ROOT = ".adk/artifacts"
```

#### 3.3 Modify `create_rlm_runner()`

The current implementation at lines 339-342 is:

```python
runner = InMemoryRunner(app=rlm_app)
if artifact_service is not None:
    runner.artifact_service = artifact_service
return runner
```

Change to:

```python
if artifact_service is None:
    artifact_service = FileArtifactService(root_dir=_DEFAULT_ARTIFACT_ROOT)
runner = InMemoryRunner(app=rlm_app)
runner.artifact_service = artifact_service
return runner
```

This means:
- When `artifact_service=None` (the default), we create a `FileArtifactService` rooted at `.adk/artifacts/` relative to cwd.
- When the caller passes an explicit `artifact_service` (including `InMemoryArtifactService()` for testing), that is used instead.
- The `FileArtifactService` constructor automatically creates the directory tree (`mkdir(parents=True, exist_ok=True)`), so no separate directory creation logic is needed.

#### 3.4 Update Docstring

Update the `artifact_service` parameter docstring in `create_rlm_runner()` from:

```
artifact_service: Optional artifact service to use.  When ``None``
    (default), ``InMemoryRunner`` creates its own
    ``InMemoryArtifactService``.  Pass a custom service to override.
```

to:

```
artifact_service: Optional artifact service to use.  When ``None``
    (default), creates a ``FileArtifactService`` rooted at
    ``.adk/artifacts/`` for persistent storage with rewind support.
    Pass ``InMemoryArtifactService()`` for volatile in-memory storage,
    or any other ``BaseArtifactService`` implementation.
```

### Tests

**File:** `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_adk_fileservice.py` (new file)

| # | Test Case | Description |
|---|-----------|-------------|
| 1 | `test_default_runner_uses_file_artifact_service` | `create_rlm_runner(model=...)` without `artifact_service` kwarg returns a runner whose `.artifact_service` is an instance of `FileArtifactService` |
| 2 | `test_default_artifact_root_is_adk_artifacts` | The default `FileArtifactService` has `root_dir` resolving to a path ending in `.adk/artifacts` |
| 3 | `test_explicit_artifact_service_overrides_default` | Passing `artifact_service=InMemoryArtifactService()` to `create_rlm_runner()` uses that instead of `FileArtifactService` |
| 4 | `test_file_artifact_service_creates_directory` | After creating the default runner, the `.adk/artifacts/` directory exists on disk |
| 5 | `test_file_artifact_service_save_and_load_roundtrip` | Save a text artifact via the runner's artifact service, load it back, verify content matches |

### Dependencies

None new -- `FileArtifactService` is already in `google-adk`.

---

## Rec 4: SqliteTracingPlugin

### What

Create a new ADK plugin that captures span-like telemetry data from ADK callbacks and writes them to a local SQLite database (`traces.db`). This provides a lightweight, zero-infrastructure alternative to Langfuse for local development and evaluation agent queries.

### Where

**New file:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py`
**Modified file:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/__init__.py` (add export)

### How

#### 4.1 Database Schema

The SQLite database has two tables: `traces` (one row per invocation/run) and `spans` (one row per callback event within a trace).

```sql
-- traces.db schema
CREATE TABLE IF NOT EXISTS traces (
    trace_id        TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    user_id         TEXT,
    app_name        TEXT,
    start_time      REAL NOT NULL,      -- Unix timestamp (seconds)
    end_time        REAL,               -- NULL until after_run_callback
    status          TEXT DEFAULT 'running',  -- running | completed | error
    total_input_tokens  INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_calls     INTEGER DEFAULT 0,
    iterations      INTEGER DEFAULT 0,
    final_answer_length INTEGER,
    metadata        TEXT                -- JSON blob for extensible data
);

CREATE TABLE IF NOT EXISTS spans (
    span_id         TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL REFERENCES traces(trace_id),
    parent_span_id  TEXT,               -- NULL for root spans
    operation_name  TEXT NOT NULL,       -- e.g. 'before_model', 'after_model', 'before_tool'
    agent_name      TEXT,
    start_time      REAL NOT NULL,
    end_time        REAL,               -- NULL for before_* spans (paired with after_*)
    status          TEXT DEFAULT 'ok',  -- ok | error
    attributes      TEXT,               -- JSON blob
    events          TEXT                -- JSON blob for sub-events
);

CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_operation ON spans(operation_name);
CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id);
CREATE INDEX IF NOT EXISTS idx_traces_start ON traces(start_time);
```

#### 4.2 Trace/Span ID Generation

Use `uuid.uuid4().hex` for both trace IDs and span IDs. The trace ID is generated once in `before_run_callback` and stored as an instance variable. Each callback generates its own span ID.

#### 4.3 Plugin Implementation

```python
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
    REQUEST_ID,
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
        # Map of (operation_name, agent_name) -> span_id for pairing
        # before_model -> after_model spans.
        self._pending_model_spans: dict[str, str] = {}
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
        return uuid.uuid4().hex

    def _current_parent_span_id(self) -> Optional[str]:
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
                    parent_span_id or self._current_parent_span_id(),
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

    def _update_span_end(self, span_id: str, end_time: float, status: str = "ok", attributes: Optional[dict] = None) -> None:
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
        agent_name = getattr(agent, "name", "unknown")
        span_id = self._new_span_id()
        self._write_span(
            span_id=span_id,
            operation_name="agent",
            agent_name=agent_name,
            attributes={"phase": "start"},
        )
        self._agent_span_stack.append(span_id)
        return None

    async def after_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        if self._agent_span_stack:
            span_id = self._agent_span_stack.pop()
            self._update_span_end(span_id, time.time())
        return None

    # ---- Model callbacks ----

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> Optional[LlmResponse]:
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
```

#### 4.4 Update `__init__.py`

In `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/__init__.py`, add:

```python
from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
```

And add `"SqliteTracingPlugin"` to `__all__`.

#### 4.5 Register in `_default_plugins()`

In `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py`, modify `_default_plugins()` (line 189):

Add a parameter `sqlite_tracing: bool = True` and the corresponding logic:

```python
def _default_plugins(
    *,
    debug: bool = True,
    langfuse: bool = True,
    sqlite_tracing: bool = True,
) -> list[BasePlugin]:
    plugins: list[BasePlugin] = [ObservabilityPlugin()]
    _debug_env = os.getenv("RLM_ADK_DEBUG", "").lower() in ("1", "true", "yes")
    if debug or _debug_env:
        plugins.append(DebugLoggingPlugin())
    _sqlite_env = os.getenv("RLM_ADK_SQLITE_TRACING", "").lower() in ("1", "true", "yes")
    if sqlite_tracing or _sqlite_env:
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
        plugins.append(SqliteTracingPlugin())
    _langfuse_env = os.getenv("RLM_ADK_LANGFUSE", "").lower() in ("1", "true", "yes")
    if langfuse or _langfuse_env:
        plugins.append(LangfuseTracingPlugin())
    return plugins
```

Also add `sqlite_tracing: bool = True` parameter to `create_rlm_app()` and `create_rlm_runner()` and thread it through to `_default_plugins()`.

### Tests

**File:** `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_adk_plugins_sqlite_tracing.py` (new file)

| # | Test Case | Description |
|---|-----------|-------------|
| 1 | `test_schema_creation` | Instantiating `SqliteTracingPlugin(db_path=tmpfile)` creates both `traces` and `spans` tables |
| 2 | `test_before_run_creates_trace` | Calling `before_run_callback` inserts a row into `traces` with `status='running'` |
| 3 | `test_after_run_updates_trace` | Calling `after_run_callback` updates the trace row with `status='completed'`, end_time, and stats |
| 4 | `test_before_agent_creates_span` | `before_agent_callback` inserts a span with `operation_name='agent'` |
| 5 | `test_after_agent_closes_span` | `after_agent_callback` sets `end_time` on the matching agent span |
| 6 | `test_before_model_creates_span` | `before_model_callback` inserts a span with `operation_name='model_call'` |
| 7 | `test_after_model_closes_span` | `after_model_callback` updates the model span with token counts and end_time |
| 8 | `test_model_error_marks_span_error` | `on_model_error_callback` sets `status='error'` on the model span |
| 9 | `test_before_tool_creates_span` | `before_tool_callback` inserts a span with `operation_name='tool_call'` |
| 10 | `test_after_tool_closes_span` | `after_tool_callback` updates the tool span with result preview |
| 11 | `test_on_event_artifact_delta` | `on_event_callback` with artifact_delta creates an `artifact_save` span |
| 12 | `test_span_parent_tracking` | Agent span is parent of nested model/tool spans |
| 13 | `test_db_path_directory_creation` | Plugin creates parent directories for `db_path` if they don't exist |
| 14 | `test_all_callbacks_return_none` | Every callback returns None (observe-only, no short-circuiting) |
| 15 | `test_db_error_does_not_crash` | Setting `self._conn = None` and calling callbacks does not raise |
| 16 | `test_close_closes_connection` | After `close()`, the connection is None |
| 17 | `test_default_plugins_includes_sqlite_tracing` | `_default_plugins()` includes `SqliteTracingPlugin` by default |
| 18 | `test_sqlite_tracing_disabled_by_flag` | `_default_plugins(sqlite_tracing=False)` excludes it |

### Dependencies

None new -- `sqlite3` is in the Python standard library.

---

## Rec 5: LangfuseTracingPlugin Optional

### What

Ensure `LangfuseTracingPlugin` remains optional and can coexist with `SqliteTracingPlugin`. Both plugins should be able to run simultaneously without interference.

### Current State Analysis

**This is already the case.** Looking at the current code:

1. **`_default_plugins()` at `agent.py:189-208`**: LangfuseTracingPlugin is included by default (`langfuse=True`), but it gracefully degrades:
   - If `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, or `LANGFUSE_BASE_URL` env vars are missing, `_init_langfuse_instrumentation()` logs a warning and returns `False`.
   - The plugin's `self._enabled` is set to `False`, and it has no active callbacks -- it's a no-op.

2. **No callback conflicts**: `LangfuseTracingPlugin` uses OTel auto-instrumentation (`GoogleADKInstrumentor`), which adds separate OTel middleware. It does not implement any `BasePlugin` callbacks itself. `SqliteTracingPlugin` implements callbacks directly. They operate on completely independent code paths.

3. **Import safety**: `LangfuseTracingPlugin.__init__()` catches `ImportError` for `langfuse` and `openinference-instrumentation-google-adk`, so missing packages don't crash the application.

### What Needs to Change

Only two minor changes:

#### 5.1 Change Default `langfuse` Parameter to `False`

To make Langfuse truly opt-in (not included unless explicitly requested or env var set):

In `_default_plugins()`, change `langfuse: bool = True` to `langfuse: bool = False`.

This means:
- Langfuse is NOT included by default in the plugin list.
- Setting `RLM_ADK_LANGFUSE=1` env var still enables it.
- Passing `langfuse=True` to `_default_plugins()` still enables it.

**Rationale**: With `SqliteTracingPlugin` providing local tracing by default, Langfuse should only activate when the user explicitly opts in. The current default of `langfuse=True` means every developer run attempts Langfuse initialization and logs a warning when env vars are missing, which is noisy.

#### 5.2 Thread `langfuse` Parameter Through

Ensure `create_rlm_app()` and `create_rlm_runner()` have a `langfuse: bool = False` parameter (changing from the current implicit `True` via `_default_plugins`). Currently, these functions don't expose `langfuse` directly -- they rely on `plugins` kwarg or `_default_plugins(debug=debug)`. We need to add it:

In `create_rlm_app()` signature, add `langfuse: bool = False`.
In `create_rlm_runner()` signature, add `langfuse: bool = False`.

Pass through:
```python
resolved_plugins = plugins if plugins is not None else _default_plugins(
    debug=debug, langfuse=langfuse, sqlite_tracing=sqlite_tracing
)
```

### Tests

**File:** `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_adk_plugins_langfuse_optional.py` (new file)

| # | Test Case | Description |
|---|-----------|-------------|
| 1 | `test_default_plugins_excludes_langfuse` | `_default_plugins()` does NOT include `LangfuseTracingPlugin` by default |
| 2 | `test_langfuse_enabled_by_flag` | `_default_plugins(langfuse=True)` includes `LangfuseTracingPlugin` |
| 3 | `test_langfuse_enabled_by_env_var` | With `RLM_ADK_LANGFUSE=1`, `_default_plugins()` includes `LangfuseTracingPlugin` |
| 4 | `test_both_plugins_coexist` | `_default_plugins(langfuse=True, sqlite_tracing=True)` includes both plugins |
| 5 | `test_langfuse_graceful_without_env_vars` | `LangfuseTracingPlugin()` with no env vars sets `enabled=False` and doesn't crash |

### Dependencies

None new.

---

## REPL Code Auto-Save

### What

Every code block submitted to the REPL by the reasoning_agent should be automatically saved as a file artifact. This captures the code itself (not just its output) for rewind, evaluation, and audit purposes.

### Analysis of Where Code Is Submitted

In `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py`, the REPL execution happens at **lines 236-267**:

```python
# --- Extract and execute code blocks ---
code_block_strs = find_code_blocks(response)     # line 236
code_blocks: list[CodeBlock] = []                 # line 237

for code_str in code_block_strs:                  # line 239
    # ... AST rewriter check ...
    # ... execute code ...
    code_blocks.append(CodeBlock(code=code_str, result=result))  # line 267
```

The loop at line 239 iterates over each extracted code block, executes it, and appends the result. The code string (`code_str`) and the execution result (`result.stdout`, `result.stderr`) are both available after each iteration.

### Implementation Approach: Orchestrator Integration (NOT Callback)

A callback-based approach is NOT feasible here because:
- The REPL execution happens inside `_run_async_impl()` of `RLMOrchestratorAgent`, which is a `BaseAgent`.
- ADK plugin callbacks fire for `LlmAgent` model calls and tool calls, but NOT for arbitrary code within a `BaseAgent`'s `_run_async_impl()`.
- The `after_model_callback` fires after the reasoning LLM responds, but BEFORE the orchestrator parses and executes code blocks.
- There is no `after_repl_execution` callback in the ADK callback system.

Therefore, the auto-save must be wired directly into the orchestrator loop, calling the existing `save_repl_output()` helper from `artifacts.py` and a new `save_repl_code()` helper.

### Where

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/artifacts.py` -- add `save_repl_code()` function
**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py` -- wire in after code execution (after line 267)

### How

#### REPL-1: New `save_repl_code()` Function in `artifacts.py`

Add this function after `save_repl_output()`:

```python
async def save_repl_code(
    ctx: Union[InvocationContext, CallbackContext],
    iteration: int,
    turn: int,
    code: str,
) -> Optional[int]:
    """Save REPL code block as a versioned artifact.

    The artifact is named ``repl_code_iter_{iteration}_turn_{turn}.py``.

    Args:
        ctx: InvocationContext or CallbackContext.
        iteration: The current orchestrator iteration number.
        turn: The code block index within this iteration (0-based).
        code: The Python source code to save.

    Returns:
        Version number (int), or None if no artifact service configured
        or if the save operation fails.
    """
    inv_ctx = get_invocation_context(ctx)
    if inv_ctx.artifact_service is None:
        logger.debug("No artifact service configured, skipping save_repl_code")
        return None

    filename = f"repl_code_iter_{iteration}_turn_{turn}.py"

    try:
        artifact = types.Part(text=code)
        version = await inv_ctx.artifact_service.save_artifact(
            app_name=inv_ctx.app_name,
            user_id=inv_ctx.session.user_id,
            session_id=inv_ctx.session.id,
            filename=filename,
            artifact=artifact,
        )
        _update_save_tracking(inv_ctx, filename, version, len(code.encode("utf-8")))
        return version
    except Exception as e:
        logger.warning("Failed to save REPL code artifact: %s", e)
        return None
```

**Design note on `types.Part(text=code)` vs `types.Part.from_bytes()`**: Using `text=` stores the artifact as a text file (`write_text` in FileArtifactService) with `mime_type=None`. This is correct for Python source code, and makes it easier to load and inspect. The existing `save_repl_output()` uses `from_bytes()` with `mime_type="text/plain"` which stores as binary -- we choose text mode for code files.

#### REPL-2: Wire Auto-Save into Orchestrator Loop

In `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py`:

**Add import** (after line 22, with the other `from rlm_adk` imports):

```python
from rlm_adk.artifacts import save_repl_code, save_repl_output
```

**Add auto-save after each code block execution** (after line 267, inside the `for code_str in code_block_strs:` loop):

The current code at lines 239-267 is:

```python
for code_str in code_block_strs:
    # ... (lines 240-266: check AST, execute code)
    code_blocks.append(CodeBlock(code=code_str, result=result))
```

Insert AFTER `code_blocks.append(...)` (new lines after 267):

```python
                    code_blocks.append(CodeBlock(code=code_str, result=result))

                    # Auto-save REPL code as artifact
                    turn_idx = len(code_blocks) - 1
                    await save_repl_code(ctx, iteration=i, turn=turn_idx, code=code_str)
```

**Add auto-save of REPL output after the code blocks loop** (after the existing line 273, after the print statement):

After the existing code at lines 269-273:

```python
print(
    f"[RLM] iter={i} code_blocks={len(code_blocks)} "
    f"has_output={any(cb.result.stdout for cb in code_blocks)}",
    flush=True,
)
```

Insert:

```python
                # Auto-save REPL outputs as artifacts
                for cb_idx, cb in enumerate(code_blocks):
                    if cb.result.stdout or cb.result.stderr:
                        await save_repl_output(
                            ctx,
                            iteration=i,
                            stdout=cb.result.stdout,
                            stderr=cb.result.stderr,
                        )
```

**Note:** `save_repl_output()` already exists in `artifacts.py` and uses the naming convention `repl_output_iter_{N}.txt`. For multiple code blocks per iteration, the versioning system handles it -- each call to `save_repl_output()` with the same iteration produces a new version (0, 1, 2...) of the same artifact filename.

### Artifact Naming Convention

| Artifact | Filename Pattern | Content |
|----------|-----------------|---------|
| REPL code | `repl_code_iter_{N}_turn_{M}.py` | Python source code submitted to REPL |
| REPL output | `repl_output_iter_{N}.txt` | stdout + stderr from execution |
| Final answer | `final_answer.md` | The final deliverable text |
| Worker result | `worker_{name}_iter_{N}.txt` | Worker agent response |

Where:
- `N` = orchestrator iteration (0-based)
- `M` = code block index within iteration (0-based)

### Tests

**File:** `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_adk_repl_autosave.py` (new file)

| # | Test Case | Description |
|---|-----------|-------------|
| 1 | `test_save_repl_code_writes_artifact` | `save_repl_code(ctx, 0, 0, "print('hi')")` saves and load returns the code text |
| 2 | `test_save_repl_code_naming_convention` | Artifact filename matches `repl_code_iter_0_turn_0.py` |
| 3 | `test_save_repl_code_multiple_turns` | Saving code for turns 0, 1, 2 in same iteration creates distinct artifacts |
| 4 | `test_save_repl_code_no_service_returns_none` | When `artifact_service=None`, `save_repl_code()` returns None without error |
| 5 | `test_save_repl_code_updates_tracking_state` | After save, `ARTIFACT_SAVE_COUNT` and `ARTIFACT_LAST_SAVED_FILENAME` are updated |
| 6 | `test_orchestrator_autosaves_code` | Integration test: run orchestrator with mock reasoning agent that returns a code block; verify the code artifact is saved |
| 7 | `test_orchestrator_autosaves_output` | Integration test: verify REPL output artifact is saved after code execution |
| 8 | `test_autosave_does_not_block_on_error` | If artifact service save raises, the orchestrator continues without crashing |

### Dependencies

None new.

---

## Create-Artifact Tool Decision

### Analysis

**Question:** Does the reasoning_agent need a `create-artifact` tool to save its final deliverable, or does the existing architecture handle this automatically?

#### How the Final Answer is Currently Detected

In `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py`, lines 276-307:

```python
# --- Check for final answer ---
final_answer = find_final_answer(response, environment=repl)

if final_answer is not None:
    # ... yield state delta with FINAL_ANSWER ...
    # ... yield content event ...
    return
```

The `find_final_answer()` function (in `utils/parsing.py`) detects `FINAL(...)` or `FINAL_VAR(...)` patterns in the reasoning agent's response text. When detected, the orchestrator stores the answer in session state (`FINAL_ANSWER`) and terminates.

#### Does FileArtifactService Automatically Save the Final Answer?

**No.** The `FileArtifactService` only saves artifacts when explicitly called via `save_artifact()`. The orchestrator currently stores the final answer in session state only -- it never calls any artifact save function.

The `save_final_answer()` helper already exists in `artifacts.py` but is never called (AC-4 in the implementation review: "NOT IMPL").

#### Recommendation: Callback in Orchestrator, NOT a Tool

**We do NOT need a `create-artifact` tool.** The correct approach is to wire `save_final_answer()` into the orchestrator at the point where `FINAL_ANSWER` is detected.

Rationale:
1. **The reasoning agent does not have tools.** It uses `include_contents='none'` and communicates via the `FINAL(...)` text pattern. Adding a tool would require changing the fundamental agent architecture.
2. **The detection point already exists.** Lines 278-307 of `orchestrator.py` already detect the final answer and have access to both `ctx` and the answer text.
3. **A tool would be unreliable.** The reasoning agent might forget to call the tool, but the orchestrator always detects `FINAL(...)`.
4. **Consistency.** REPL code auto-save also happens in the orchestrator, not via a tool.

### Implementation

In `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py`, after the final answer is detected (line 278), add:

**Add import** (with the other artifact imports):

```python
from rlm_adk.artifacts import save_repl_code, save_repl_output, save_final_answer
```

**Insert after line 283** (after the `print` statement, before the `yield Event` for state delta):

```python
                if final_answer is not None:
                    print(
                        f"[RLM] FINAL_ANSWER detected at iter={i + 1} "
                        f"length={len(final_answer)}",
                        flush=True,
                    )

                    # Auto-save final answer as artifact
                    await save_final_answer(ctx, answer=final_answer)

                    yield Event(
                        # ... existing state delta yield ...
```

This way:
- The final answer is saved as `final_answer.md` with `mime_type="text/markdown"`.
- If the artifact service is not configured (None), `save_final_answer()` returns None gracefully.
- If the save fails, it logs a warning but does not crash the orchestrator.
- Each invocation creates a new version of `final_answer.md` (version 0, 1, 2...).

### Tests

| # | Test Case | Description |
|---|-----------|-------------|
| 1 | `test_final_answer_saved_as_artifact` | Integration test: orchestrator detects FINAL, calls `save_final_answer()`, artifact is loadable |
| 2 | `test_final_answer_not_saved_when_no_service` | With `artifact_service=None`, no error occurs and no artifact is created |

These can be added to the `test_adk_repl_autosave.py` file.

---

## TDD Test Plan

### Execution Order

All test files should be run with:
```bash
.venv/bin/python -m pytest tests_rlm_adk/ -v
```

### Phase 1: RED -- Write Failing Tests First

#### File 1: `tests_rlm_adk/test_adk_fileservice.py`

```python
"""Tests for Rec 3: FileArtifactService as default."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from google.adk.artifacts import FileArtifactService, InMemoryArtifactService
from google.genai import types


class TestFileArtifactServiceDefault:
    """Rec 3: create_rlm_runner() defaults to FileArtifactService."""

    def test_default_runner_uses_file_artifact_service(self):
        """Runner created without artifact_service kwarg uses FileArtifactService."""
        from rlm_adk.agent import create_rlm_runner
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("rlm_adk.agent._DEFAULT_ARTIFACT_ROOT", os.path.join(tmpdir, "artifacts")):
                runner = create_rlm_runner(model="gemini-2.5-flash")
                assert isinstance(runner.artifact_service, FileArtifactService)

    def test_default_artifact_root_is_adk_artifacts(self):
        """Default FileArtifactService root resolves to .adk/artifacts."""
        from rlm_adk.agent import _DEFAULT_ARTIFACT_ROOT
        assert _DEFAULT_ARTIFACT_ROOT == ".adk/artifacts"

    def test_explicit_artifact_service_overrides_default(self):
        """Passing explicit artifact_service uses that instead."""
        from rlm_adk.agent import create_rlm_runner
        mem_service = InMemoryArtifactService()
        runner = create_rlm_runner(model="gemini-2.5-flash", artifact_service=mem_service)
        assert runner.artifact_service is mem_service

    def test_file_artifact_service_creates_directory(self):
        """FileArtifactService creates the root directory on init."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = os.path.join(tmpdir, "nested", "artifacts")
            service = FileArtifactService(root_dir=root)
            assert os.path.isdir(root)

    @pytest.mark.asyncio
    async def test_file_artifact_service_save_and_load_roundtrip(self):
        """Save and load a text artifact through FileArtifactService."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = FileArtifactService(root_dir=tmpdir)
            artifact = types.Part(text="hello world")
            version = await service.save_artifact(
                app_name="test", user_id="user1", session_id="sess1",
                filename="test.txt", artifact=artifact,
            )
            assert version == 0
            loaded = await service.load_artifact(
                app_name="test", user_id="user1", session_id="sess1",
                filename="test.txt",
            )
            assert loaded is not None
            assert loaded.text == "hello world"
```

#### File 2: `tests_rlm_adk/test_adk_plugins_sqlite_tracing.py`

```python
"""Tests for Rec 4: SqliteTracingPlugin."""

import json
import os
import sqlite3
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_traces.db")


@pytest.fixture
def plugin(db_path):
    from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
    return SqliteTracingPlugin(db_path=db_path)


@pytest.fixture
def mock_invocation_context():
    ctx = MagicMock()
    ctx.session.id = "sess_1"
    ctx.session.user_id = "user_1"
    ctx.app_name = "test_app"
    ctx.session.state = {}
    return ctx


@pytest.fixture
def mock_callback_context():
    ctx = MagicMock()
    ctx.state = {}
    ctx._invocation_context = MagicMock()
    return ctx


class TestSchemaCreation:
    def test_schema_creation(self, db_path, plugin):
        conn = sqlite3.connect(db_path)
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "traces" in tables
        assert "spans" in tables
        conn.close()


class TestTraceLifecycle:
    @pytest.mark.asyncio
    async def test_before_run_creates_trace(self, plugin, db_path, mock_invocation_context):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM traces").fetchall()
        assert len(rows) == 1
        assert rows[0][6] == "running"  # status column
        conn.close()

    @pytest.mark.asyncio
    async def test_after_run_updates_trace(self, plugin, db_path, mock_invocation_context):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        await plugin.after_run_callback(invocation_context=mock_invocation_context)
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT status, end_time FROM traces").fetchone()
        assert row[0] == "completed"
        assert row[1] is not None
        conn.close()


class TestSpanCallbacks:
    @pytest.mark.asyncio
    async def test_before_agent_creates_span(self, plugin, db_path, mock_invocation_context, mock_callback_context):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        agent = MagicMock()
        agent.name = "test_agent"
        await plugin.before_agent_callback(agent=agent, callback_context=mock_callback_context)
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT operation_name, agent_name FROM spans").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "agent"
        assert rows[0][1] == "test_agent"
        conn.close()

    @pytest.mark.asyncio
    async def test_after_agent_closes_span(self, plugin, db_path, mock_invocation_context, mock_callback_context):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        agent = MagicMock()
        agent.name = "test_agent"
        await plugin.before_agent_callback(agent=agent, callback_context=mock_callback_context)
        await plugin.after_agent_callback(agent=agent, callback_context=mock_callback_context)
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT end_time FROM spans").fetchone()
        assert row[0] is not None
        conn.close()

    @pytest.mark.asyncio
    async def test_before_model_creates_span(self, plugin, db_path, mock_invocation_context, mock_callback_context):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
        await plugin.before_model_callback(callback_context=mock_callback_context, llm_request=llm_request)
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT operation_name, attributes FROM spans").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "model_call"
        attrs = json.loads(rows[0][1])
        assert attrs["model"] == "gemini-2.5-flash"
        conn.close()

    @pytest.mark.asyncio
    async def test_after_model_closes_span(self, plugin, db_path, mock_invocation_context, mock_callback_context):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        llm_request = MagicMock()
        llm_request.model = "gemini-2.5-flash"
        llm_request.contents = []
        await plugin.before_model_callback(callback_context=mock_callback_context, llm_request=llm_request)
        llm_response = MagicMock()
        llm_response.model_version = "gemini-2.5-flash"
        llm_response.usage_metadata = MagicMock()
        llm_response.usage_metadata.prompt_token_count = 100
        llm_response.usage_metadata.candidates_token_count = 50
        llm_response.error_code = None
        await plugin.after_model_callback(callback_context=mock_callback_context, llm_response=llm_response)
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT end_time, attributes FROM spans").fetchone()
        assert row[0] is not None
        attrs = json.loads(row[1])
        assert attrs["input_tokens"] == 100
        assert attrs["output_tokens"] == 50
        conn.close()


class TestErrorResilience:
    @pytest.mark.asyncio
    async def test_all_callbacks_return_none(self, plugin, mock_invocation_context, mock_callback_context):
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        agent = MagicMock()
        agent.name = "a"
        assert await plugin.before_agent_callback(agent=agent, callback_context=mock_callback_context) is None
        assert await plugin.after_agent_callback(agent=agent, callback_context=mock_callback_context) is None
        llm_request = MagicMock()
        llm_request.model = "m"
        llm_request.contents = []
        assert await plugin.before_model_callback(callback_context=mock_callback_context, llm_request=llm_request) is None
        llm_response = MagicMock()
        llm_response.model_version = "m"
        llm_response.usage_metadata = None
        llm_response.error_code = None
        assert await plugin.after_model_callback(callback_context=mock_callback_context, llm_response=llm_response) is None

    @pytest.mark.asyncio
    async def test_db_error_does_not_crash(self, mock_invocation_context, mock_callback_context):
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
        plugin = SqliteTracingPlugin(db_path="/dev/null/impossible/path.db")
        # All callbacks should silently succeed even with broken DB
        await plugin.before_run_callback(invocation_context=mock_invocation_context)
        agent = MagicMock()
        agent.name = "a"
        await plugin.before_agent_callback(agent=agent, callback_context=mock_callback_context)

    @pytest.mark.asyncio
    async def test_close_closes_connection(self, plugin):
        assert plugin._conn is not None
        await plugin.close()
        assert plugin._conn is None
```

#### File 3: `tests_rlm_adk/test_adk_plugins_langfuse_optional.py`

```python
"""Tests for Rec 5: LangfuseTracingPlugin is optional."""

import os
from unittest.mock import patch

import pytest


class TestLangfuseOptional:
    def test_default_plugins_excludes_langfuse(self):
        from rlm_adk.agent import _default_plugins
        from rlm_adk.plugins.langfuse_tracing import LangfuseTracingPlugin
        with patch.dict(os.environ, {}, clear=True):
            plugins = _default_plugins(langfuse=False, sqlite_tracing=False)
            assert not any(isinstance(p, LangfuseTracingPlugin) for p in plugins)

    def test_langfuse_enabled_by_flag(self):
        from rlm_adk.agent import _default_plugins
        from rlm_adk.plugins.langfuse_tracing import LangfuseTracingPlugin
        plugins = _default_plugins(langfuse=True, sqlite_tracing=False)
        assert any(isinstance(p, LangfuseTracingPlugin) for p in plugins)

    def test_langfuse_enabled_by_env_var(self):
        from rlm_adk.agent import _default_plugins
        from rlm_adk.plugins.langfuse_tracing import LangfuseTracingPlugin
        with patch.dict(os.environ, {"RLM_ADK_LANGFUSE": "1"}):
            plugins = _default_plugins(langfuse=False, sqlite_tracing=False)
            assert any(isinstance(p, LangfuseTracingPlugin) for p in plugins)

    def test_both_plugins_coexist(self):
        from rlm_adk.agent import _default_plugins
        from rlm_adk.plugins.langfuse_tracing import LangfuseTracingPlugin
        from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
        plugins = _default_plugins(langfuse=True, sqlite_tracing=True)
        has_langfuse = any(isinstance(p, LangfuseTracingPlugin) for p in plugins)
        has_sqlite = any(isinstance(p, SqliteTracingPlugin) for p in plugins)
        assert has_langfuse
        assert has_sqlite

    def test_langfuse_graceful_without_env_vars(self):
        from rlm_adk.plugins.langfuse_tracing import LangfuseTracingPlugin
        with patch.dict(os.environ, {}, clear=True):
            plugin = LangfuseTracingPlugin()
            assert not plugin.enabled
```

#### File 4: `tests_rlm_adk/test_adk_repl_autosave.py`

```python
"""Tests for REPL code auto-save and final answer auto-save."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from google.adk.artifacts import InMemoryArtifactService
from google.genai import types


@pytest.fixture
def artifact_service():
    return InMemoryArtifactService()


@pytest.fixture
def mock_invocation_context(artifact_service):
    ctx = MagicMock()
    ctx.artifact_service = artifact_service
    ctx.app_name = "test_app"
    ctx.session = MagicMock()
    ctx.session.id = "test_session"
    ctx.session.user_id = "test_user"
    ctx.session.state = {}
    ctx.invocation_id = "test_invocation"
    return ctx


class TestSaveReplCode:
    @pytest.mark.asyncio
    async def test_save_repl_code_writes_artifact(self, mock_invocation_context, artifact_service):
        from rlm_adk.artifacts import save_repl_code
        code = "print('hello world')"
        version = await save_repl_code(mock_invocation_context, iteration=0, turn=0, code=code)
        assert version == 0
        loaded = await artifact_service.load_artifact(
            app_name="test_app", user_id="test_user",
            session_id="test_session", filename="repl_code_iter_0_turn_0.py",
        )
        assert loaded is not None
        assert loaded.text == code

    @pytest.mark.asyncio
    async def test_save_repl_code_naming_convention(self, mock_invocation_context, artifact_service):
        from rlm_adk.artifacts import save_repl_code
        await save_repl_code(mock_invocation_context, iteration=2, turn=1, code="x = 1")
        keys = await artifact_service.list_artifact_keys(
            app_name="test_app", user_id="test_user", session_id="test_session",
        )
        assert "repl_code_iter_2_turn_1.py" in keys

    @pytest.mark.asyncio
    async def test_save_repl_code_multiple_turns(self, mock_invocation_context, artifact_service):
        from rlm_adk.artifacts import save_repl_code
        await save_repl_code(mock_invocation_context, iteration=0, turn=0, code="a = 1")
        await save_repl_code(mock_invocation_context, iteration=0, turn=1, code="b = 2")
        await save_repl_code(mock_invocation_context, iteration=0, turn=2, code="c = 3")
        keys = await artifact_service.list_artifact_keys(
            app_name="test_app", user_id="test_user", session_id="test_session",
        )
        assert "repl_code_iter_0_turn_0.py" in keys
        assert "repl_code_iter_0_turn_1.py" in keys
        assert "repl_code_iter_0_turn_2.py" in keys

    @pytest.mark.asyncio
    async def test_save_repl_code_no_service_returns_none(self):
        from rlm_adk.artifacts import save_repl_code
        ctx = MagicMock()
        ctx.artifact_service = None
        result = await save_repl_code(ctx, iteration=0, turn=0, code="x = 1")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_repl_code_updates_tracking_state(self, mock_invocation_context):
        from rlm_adk.artifacts import save_repl_code
        from rlm_adk.state import ARTIFACT_SAVE_COUNT, ARTIFACT_LAST_SAVED_FILENAME
        await save_repl_code(mock_invocation_context, iteration=0, turn=0, code="x = 1")
        state = mock_invocation_context.session.state
        assert state[ARTIFACT_SAVE_COUNT] == 1
        assert state[ARTIFACT_LAST_SAVED_FILENAME] == "repl_code_iter_0_turn_0.py"


class TestFinalAnswerAutoSave:
    @pytest.mark.asyncio
    async def test_final_answer_saved_as_artifact(self, mock_invocation_context, artifact_service):
        from rlm_adk.artifacts import save_final_answer
        version = await save_final_answer(mock_invocation_context, answer="The answer is 42.")
        assert version == 0
        loaded = await artifact_service.load_artifact(
            app_name="test_app", user_id="test_user",
            session_id="test_session", filename="final_answer.md",
        )
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_final_answer_not_saved_when_no_service(self):
        from rlm_adk.artifacts import save_final_answer
        ctx = MagicMock()
        ctx.artifact_service = None
        result = await save_final_answer(ctx, answer="test")
        assert result is None
```

### Phase 2: GREEN -- Implementation Order

1. **Rec 3 (FileArtifactService)**: Modify `agent.py` -- make tests in `test_adk_fileservice.py` pass.
2. **REPL auto-save helper**: Add `save_repl_code()` to `artifacts.py` -- make unit tests in `test_adk_repl_autosave.py::TestSaveReplCode` pass.
3. **Final answer auto-save**: Wire `save_final_answer()` into `orchestrator.py` -- make `test_adk_repl_autosave.py::TestFinalAnswerAutoSave` pass.
4. **REPL code auto-save in orchestrator**: Wire `save_repl_code()` and `save_repl_output()` into `orchestrator.py` loop.
5. **SqliteTracingPlugin**: Create `sqlite_tracing.py` -- make all tests in `test_adk_plugins_sqlite_tracing.py` pass.
6. **Langfuse optional**: Modify `_default_plugins()` -- make tests in `test_adk_plugins_langfuse_optional.py` pass.
7. **Plugin registration**: Update `__init__.py` and `agent.py` for new plugin registration.

### Phase 3: REFACTOR

- Ensure all 333+ existing tests still pass.
- Run `ruff check` and `ruff format` for code style.
- Verify no import cycles.

---

## Dependencies

### New Dependencies

None. All required packages are already available:

| Package | Source | Already Available |
|---------|--------|-------------------|
| `FileArtifactService` | `google-adk` | Yes (v1.25.0+) |
| `sqlite3` | Python stdlib | Yes |
| `uuid` | Python stdlib | Yes |
| `json` | Python stdlib | Yes |

### pyproject.toml

No changes needed to `pyproject.toml`.

---

## Summary of Changes

| Change | Files Modified | Files Created | Tests Created |
|--------|---------------|---------------|---------------|
| Rec 3: FileArtifactService | `rlm_adk/agent.py` | -- | `tests_rlm_adk/test_adk_fileservice.py` |
| Rec 4: SqliteTracingPlugin | `rlm_adk/agent.py`, `rlm_adk/plugins/__init__.py` | `rlm_adk/plugins/sqlite_tracing.py` | `tests_rlm_adk/test_adk_plugins_sqlite_tracing.py` |
| Rec 5: Langfuse optional | `rlm_adk/agent.py` | -- | `tests_rlm_adk/test_adk_plugins_langfuse_optional.py` |
| REPL auto-save | `rlm_adk/artifacts.py`, `rlm_adk/orchestrator.py` | -- | `tests_rlm_adk/test_adk_repl_autosave.py` |
| Final answer auto-save | `rlm_adk/orchestrator.py` | -- | (in `test_adk_repl_autosave.py`) |

### Total: 4 new files, 4 modified files, 4 new test files (~40 test cases)
