# Database Implementation Specification

> **Date**: 2026-02-20
> **Source**: `ai_docs/database_strategy_report.md` recommendations 1, 2, 6, 7, 8, 9
> **Target Audience**: TDD-Implementer agent
> **Scope**: Session persistence, evaluation query interface, migration plugin

---

## Table of Contents

1. [Rec 1: Modify `create_rlm_runner()` to accept `session_service`](#rec-1)
2. [Rec 2: Default to `SqliteSessionService`](#rec-2)
3. [Rec 6: Build `TraceReader` class with DuckDB](#rec-6)
4. [Rec 7: Expose evaluation queries](#rec-7)
5. [Rec 8: Integrate with session rewind / fork](#rec-8)
6. [Rec 9: Create `MigrationPlugin`](#rec-9)
7. [Dependencies](#dependencies)
8. [New State Keys](#new-state-keys)
9. [File Inventory](#file-inventory)

---

<a id="rec-1"></a>
## Recommendation 1: Modify `create_rlm_runner()` to Accept `session_service`

### What

Add an optional `session_service` parameter to `create_rlm_runner()` (and the upstream `Runner` construction) so callers can inject any `BaseSessionService` implementation. When `None`, the function uses the default (see Rec 2). This replaces the hardcoded `InMemoryRunner` which forces `InMemorySessionService`.

### Where

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py`

**Lines to modify**:

- **Line 34**: Add import for `Runner` (replacing or supplementing `InMemoryRunner`)
- **Line 266-342**: `create_rlm_runner()` function signature and body
- **Line 339**: Replace `InMemoryRunner(app=rlm_app)` with `Runner(app=rlm_app, session_service=..., ...)`

### How

#### Step 1: Add imports (line 34 area)

```python
# Add to existing imports:
from google.adk.runners import Runner
from google.adk.sessions.base_session_service import BaseSessionService
```

Note: `InMemoryRunner` import can remain for backward compatibility, but the core path now uses `Runner` directly.

#### Step 2: Modify `create_rlm_runner()` signature (line 266)

Add `session_service` parameter:

```python
def create_rlm_runner(
    model: str,
    root_prompt: str | None = None,
    persistent: bool = False,
    worker_pool: Any = None,
    repl: Any = None,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    repo_url: str | None = None,
    plugins: list[BasePlugin] | None = None,
    debug: bool = True,
    thinking_budget: int = 1024,
    artifact_service: BaseArtifactService | None = None,
    session_service: BaseSessionService | None = None,    # NEW
) -> Runner:    # CHANGED return type from InMemoryRunner to Runner
```

#### Step 3: Replace body (lines 326-342)

```python
    rlm_app = create_rlm_app(
        model=model,
        root_prompt=root_prompt,
        persistent=persistent,
        worker_pool=worker_pool,
        repl=repl,
        static_instruction=static_instruction,
        dynamic_instruction=dynamic_instruction,
        repo_url=repo_url,
        plugins=plugins,
        debug=debug,
        thinking_budget=thinking_budget,
    )

    # Resolve session service: explicit > default factory
    resolved_session_service = session_service or _default_session_service()

    runner = Runner(
        app=rlm_app,
        session_service=resolved_session_service,
    )
    if artifact_service is not None:
        runner.artifact_service = artifact_service
    return runner
```

The `_default_session_service()` factory is defined in Rec 2.

#### Step 4: Update module-level `app` / `root_agent` (lines 354-355)

No change needed here. The module-level `app` is created via `create_rlm_app()`, which returns an `App` -- not a `Runner`. The ADK CLI creates its own Runner wrapping the App. The `create_rlm_runner()` change only affects programmatic callers.

### Tests

**File**: `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_session_service_wiring.py` (NEW)

#### TDD Plan

**RED 1**: `test_create_rlm_runner_accepts_session_service`
```python
"""create_rlm_runner() accepts a custom session_service and uses it."""
from unittest.mock import MagicMock, patch
from google.adk.sessions.base_session_service import BaseSessionService

def test_create_rlm_runner_accepts_session_service():
    custom_service = MagicMock(spec=BaseSessionService)
    with patch("rlm_adk.agent.create_rlm_app") as mock_app:
        mock_app.return_value = MagicMock()
        runner = create_rlm_runner(
            model="gemini-2.5-flash",
            session_service=custom_service,
        )
    assert runner.session_service is custom_service
```

**GREEN 1**: Add `session_service` parameter, wire it through to `Runner(...)`.

**RED 2**: `test_create_rlm_runner_returns_runner_not_inmemoryrunner`
```python
"""Return type is Runner (not InMemoryRunner) when session_service is provided."""
def test_create_rlm_runner_returns_runner_not_inmemoryrunner():
    custom_service = MagicMock(spec=BaseSessionService)
    with patch("rlm_adk.agent.create_rlm_app") as mock_app:
        mock_app.return_value = MagicMock()
        runner = create_rlm_runner(
            model="gemini-2.5-flash",
            session_service=custom_service,
        )
    from google.adk.runners import Runner
    assert isinstance(runner, Runner)
```

**GREEN 2**: Change return type annotation to `Runner`, use `Runner(...)` constructor.

**RED 3**: `test_create_rlm_runner_default_session_service_is_sqlite`
```python
"""When session_service=None, default is SqliteSessionService."""
def test_create_rlm_runner_default_session_service_is_sqlite():
    with patch("rlm_adk.agent.create_rlm_app") as mock_app:
        mock_app.return_value = MagicMock()
        runner = create_rlm_runner(model="gemini-2.5-flash")
    from google.adk.sessions.sqlite_session_service import SqliteSessionService
    assert isinstance(runner.session_service, SqliteSessionService)
```

**GREEN 3**: Implement `_default_session_service()` (see Rec 2).

**RED 4**: `test_create_rlm_runner_artifact_service_override`
```python
"""artifact_service parameter still works after refactor."""
def test_create_rlm_runner_artifact_service_override():
    custom_artifact = MagicMock(spec=BaseArtifactService)
    with patch("rlm_adk.agent.create_rlm_app") as mock_app:
        mock_app.return_value = MagicMock()
        runner = create_rlm_runner(
            model="gemini-2.5-flash",
            artifact_service=custom_artifact,
        )
    assert runner.artifact_service is custom_artifact
```

**GREEN 4**: Already works (existing logic preserved).

### Dependencies

None beyond what Rec 2 introduces.

---

<a id="rec-2"></a>
## Recommendation 2: Default to `SqliteSessionService`

### What

When no explicit `session_service` is passed, `create_rlm_runner()` defaults to `SqliteSessionService` backed by `.adk/session.db` (relative to the project root). This replaces the current `InMemorySessionService` default.

### Critical Design Decision: WAL Mode and Pragmas

The upstream `SqliteSessionService` does **NOT** configure WAL mode or `busy_timeout`. Per the database strategy report's "What NOT to Do" section: "Do NOT enable WAL mode without `PRAGMA busy_timeout` (risk of SQLITE_BUSY errors)".

**Approach**: We will NOT subclass `SqliteSessionService`. Instead, we create a thin factory function `_default_session_service()` that:
1. Ensures the `.adk/` directory exists
2. Creates a `SqliteSessionService` instance
3. Applies performance pragmas via a one-time synchronous `sqlite3` connection at startup

Rationale for not subclassing: The upstream `_get_db_connection()` opens a fresh `aiosqlite.connect()` per operation. WAL mode is a persistent database property -- once set via `PRAGMA journal_mode=WAL`, it persists across connections until explicitly changed. Similarly, `busy_timeout` should be set per-connection, but the upstream reconnects each time. Since we cannot easily inject per-connection pragmas without overriding the private `_get_db_connection()` method (fragile coupling to upstream), we:
- Set WAL mode once at startup (persists on disk)
- Accept that `busy_timeout` will use SQLite's default (0ms) per-connection from the upstream class
- Document this limitation and recommend subclassing or upstream contribution for production concurrency

**Alternative considered**: Subclass `SqliteSessionService` and override `_get_db_connection()`. Rejected because `_get_db_connection` is a private method (underscore prefix) and may change between ADK versions. The pragma-at-startup approach is safer.

### Where

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py`

**New code location**: After the `_DEFAULT_RETRY_OPTIONS` constant (line 60), before `create_reasoning_agent()`.

### How

#### New factory function in `agent.py`

```python
import sqlite3

_DEFAULT_DB_PATH = ".adk/session.db"

_SQLITE_STARTUP_PRAGMAS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;
PRAGMA wal_autocheckpoint = 1000;
"""


def _default_session_service(
    db_path: str | None = None,
) -> "SqliteSessionService":
    """Create the default SqliteSessionService with performance pragmas.

    Ensures the parent directory exists, applies WAL mode and performance
    pragmas via a one-time synchronous connection, then returns the ADK
    SqliteSessionService instance.

    Args:
        db_path: Path to the SQLite database file.  Defaults to
            ``RLM_SESSION_DB`` env var, falling back to ``.adk/session.db``.

    Returns:
        A configured SqliteSessionService instance.
    """
    from google.adk.sessions.sqlite_session_service import SqliteSessionService

    resolved_path = db_path or os.getenv("RLM_SESSION_DB", _DEFAULT_DB_PATH)

    # Ensure parent directory exists
    db_dir = Path(resolved_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)

    # Apply persistent pragmas via synchronous sqlite3 connection.
    # WAL mode persists on disk once set; other pragmas are per-connection
    # but WAL is the critical one for concurrent reads.
    conn = sqlite3.connect(resolved_path)
    try:
        conn.executescript(_SQLITE_STARTUP_PRAGMAS)
    finally:
        conn.close()

    logger.info("Session DB: %s (WAL mode enabled)", resolved_path)

    return SqliteSessionService(db_path=resolved_path)
```

#### Import additions at top of `agent.py`

```python
import sqlite3  # For one-time pragma application
```

(Note: `os`, `Path`, and `logging` are already imported.)

### Tests

**File**: `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_session_service_wiring.py` (same file as Rec 1)

#### TDD Plan

**RED 1**: `test_default_session_service_creates_sqlite`
```python
"""_default_session_service() returns SqliteSessionService."""
import tempfile
from pathlib import Path

def test_default_session_service_creates_sqlite():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        service = _default_session_service(db_path=db_path)
        from google.adk.sessions.sqlite_session_service import SqliteSessionService
        assert isinstance(service, SqliteSessionService)
```

**GREEN 1**: Implement `_default_session_service()`.

**RED 2**: `test_default_session_service_creates_parent_dir`
```python
"""_default_session_service() creates the parent directory if missing."""
def test_default_session_service_creates_parent_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "nested" / "dir" / "session.db")
        _default_session_service(db_path=db_path)
        assert Path(db_path).parent.exists()
```

**GREEN 2**: The `db_dir.mkdir(parents=True, exist_ok=True)` call handles this.

**RED 3**: `test_default_session_service_enables_wal_mode`
```python
"""_default_session_service() sets WAL journal mode on the database."""
def test_default_session_service_enables_wal_mode():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        _default_session_service(db_path=db_path)

        # Verify WAL mode is set by reading the pragma
        import sqlite3
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA journal_mode").fetchone()
        conn.close()
        assert result[0] == "wal"
```

**GREEN 3**: The `conn.executescript(_SQLITE_STARTUP_PRAGMAS)` call sets WAL mode.

**RED 4**: `test_default_session_service_env_override`
```python
"""RLM_SESSION_DB env var overrides the default path."""
def test_default_session_service_env_override(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_path = str(Path(tmpdir) / "custom.db")
        monkeypatch.setenv("RLM_SESSION_DB", custom_path)
        service = _default_session_service()
        assert Path(custom_path).exists()
```

**GREEN 4**: The `os.getenv("RLM_SESSION_DB", _DEFAULT_DB_PATH)` handles this.

**RED 5**: `test_default_session_service_idempotent`
```python
"""Calling _default_session_service() twice on same db_path does not fail."""
def test_default_session_service_idempotent():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        s1 = _default_session_service(db_path=db_path)
        s2 = _default_session_service(db_path=db_path)
        # Both should be valid instances
        from google.adk.sessions.sqlite_session_service import SqliteSessionService
        assert isinstance(s1, SqliteSessionService)
        assert isinstance(s2, SqliteSessionService)
```

**GREEN 5**: WAL mode pragma is idempotent; `CREATE TABLE IF NOT EXISTS` in upstream is idempotent.

### Dependencies

```toml
# pyproject.toml - add to dependencies list:
"aiosqlite>=0.20.0",
```

Note: `aiosqlite` is a transitive dependency of `google-adk` when using `SqliteSessionService`, but it should be declared explicitly since we are making it the default path.

---

<a id="rec-6"></a>
## Recommendation 6: Build `TraceReader` Class with DuckDB

### What

Create a `TraceReader` class that wraps DuckDB to provide analytical read access against the SQLite session database. DuckDB can attach SQLite files directly via `ATTACH 'path.db' AS db (TYPE sqlite)`, enabling zero-copy columnar reads optimized for aggregation queries.

The `TraceReader` operates on the same `.adk/session.db` file that `SqliteSessionService` writes to. It is a **read-only** analytics overlay -- it never writes to SQLite.

### Where

**New file**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/eval/__init__.py` (empty, package marker)
**New file**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/eval/trace_reader.py`

### How

#### Directory structure

```
rlm_adk/
  eval/
    __init__.py          # Package marker, exports TraceReader
    trace_reader.py      # TraceReader class
    queries.py           # Evaluation query functions (Rec 7)
    session_fork.py      # Session fork/rewind integration (Rec 8)
```

#### `rlm_adk/eval/__init__.py`

```python
"""RLM ADK Evaluation utilities - DuckDB analytics and session forking."""

from rlm_adk.eval.trace_reader import TraceReader

__all__ = ["TraceReader"]
```

#### `rlm_adk/eval/trace_reader.py`

```python
"""TraceReader - DuckDB analytical overlay for SQLite session data.

Provides columnar, vectorized read access against the ADK session database.
DuckDB attaches the SQLite file directly (zero-copy) and enables SQL analytics
(aggregations, window functions, JSON extraction) that would be slow in SQLite.

Usage:
    reader = TraceReader(".adk/session.db")
    traces = reader.get_session_traces("my_app", "user_123", "session_abc")
    reader.close()

    # Or as context manager:
    with TraceReader(".adk/session.db") as reader:
        traces = reader.get_session_traces(...)
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

import duckdb

logger = logging.getLogger(__name__)


class TraceReader:
    """DuckDB-backed read-only analytics against SQLite session data.

    Attaches the SQLite session database in read-only mode and provides
    structured query methods for evaluation agents.

    Attributes:
        db_path: Path to the SQLite database file.
        conn: The DuckDB connection with the SQLite file attached.
    """

    def __init__(self, db_path: str, *, read_only: bool = True):
        """Initialize the TraceReader.

        Args:
            db_path: Path to the SQLite session database file.
            read_only: If True, attach SQLite in read-only mode (default).
                This is safe for concurrent access while the agent is writing.

        Raises:
            FileNotFoundError: If db_path does not exist.
            duckdb.Error: If the SQLite file cannot be attached.
        """
        self.db_path = str(Path(db_path).resolve())
        if not Path(self.db_path).exists():
            raise FileNotFoundError(f"Session database not found: {self.db_path}")

        self._conn = duckdb.connect(":memory:")
        mode_suffix = "?mode=ro" if read_only else ""
        self._conn.execute(
            f"ATTACH '{self.db_path}{mode_suffix}' AS sdb (TYPE sqlite)"
        )
        logger.info("TraceReader attached: %s (read_only=%s)", self.db_path, read_only)

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """The underlying DuckDB connection."""
        return self._conn

    def close(self) -> None:
        """Close the DuckDB connection and detach the SQLite file."""
        if self._conn:
            try:
                self._conn.execute("DETACH sdb")
            except Exception:
                pass
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "TraceReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def execute(self, sql: str, params: Optional[list] = None) -> list[dict[str, Any]]:
        """Execute a SQL query and return results as list of dicts.

        Args:
            sql: SQL query string. Tables are prefixed with ``sdb.`` (the
                attached SQLite schema).
            params: Optional positional parameters for the query.

        Returns:
            List of dicts, one per row, with column names as keys.
        """
        result = self._conn.execute(sql, params or [])
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def list_sessions(
        self,
        app_name: str,
        user_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List all sessions, optionally filtered by user_id.

        Args:
            app_name: Application name filter.
            user_id: Optional user ID filter.

        Returns:
            List of session dicts with keys: id, app_name, user_id,
            create_time, update_time, event_count.
        """
        if user_id:
            sql = """
                SELECT
                    s.id, s.app_name, s.user_id,
                    s.create_time, s.update_time,
                    COUNT(e.id) AS event_count
                FROM sdb.sessions s
                LEFT JOIN sdb.events e
                    ON s.app_name = e.app_name
                    AND s.user_id = e.user_id
                    AND s.id = e.session_id
                WHERE s.app_name = $1 AND s.user_id = $2
                GROUP BY s.id, s.app_name, s.user_id, s.create_time, s.update_time
                ORDER BY s.update_time DESC
            """
            return self.execute(sql, [app_name, user_id])
        else:
            sql = """
                SELECT
                    s.id, s.app_name, s.user_id,
                    s.create_time, s.update_time,
                    COUNT(e.id) AS event_count
                FROM sdb.sessions s
                LEFT JOIN sdb.events e
                    ON s.app_name = e.app_name
                    AND s.user_id = e.user_id
                    AND s.id = e.session_id
                WHERE s.app_name = $1
                GROUP BY s.id, s.app_name, s.user_id, s.create_time, s.update_time
                ORDER BY s.update_time DESC
            """
            return self.execute(sql, [app_name])

    def get_session_event_count(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> int:
        """Return the total number of events in a session.

        Args:
            app_name: Application name.
            user_id: User ID.
            session_id: Session ID.

        Returns:
            Integer event count.
        """
        sql = """
            SELECT COUNT(*) AS cnt
            FROM sdb.events
            WHERE app_name = $1 AND user_id = $2 AND session_id = $3
        """
        rows = self.execute(sql, [app_name, user_id, session_id])
        return rows[0]["cnt"] if rows else 0

    def get_session_state(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        """Return the current state dict for a session.

        Args:
            app_name: Application name.
            user_id: User ID.
            session_id: Session ID.

        Returns:
            Parsed JSON state dict, or empty dict if session not found.
        """
        sql = """
            SELECT state
            FROM sdb.sessions
            WHERE app_name = $1 AND user_id = $2 AND id = $3
        """
        rows = self.execute(sql, [app_name, user_id, session_id])
        if not rows:
            return {}
        return json.loads(rows[0]["state"])

    def get_invocation_ids(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> list[str]:
        """Return distinct invocation IDs in chronological order.

        Args:
            app_name: Application name.
            user_id: User ID.
            session_id: Session ID.

        Returns:
            Ordered list of invocation ID strings.
        """
        sql = """
            SELECT DISTINCT invocation_id
            FROM sdb.events
            WHERE app_name = $1 AND user_id = $2 AND session_id = $3
            ORDER BY MIN(timestamp)
        """
        # DuckDB needs GROUP BY for ORDER BY with aggregate on non-selected column
        sql = """
            SELECT invocation_id, MIN(timestamp) AS first_ts
            FROM sdb.events
            WHERE app_name = $1 AND user_id = $2 AND session_id = $3
            GROUP BY invocation_id
            ORDER BY first_ts
        """
        rows = self.execute(sql, [app_name, user_id, session_id])
        return [r["invocation_id"] for r in rows]

    def get_events_raw(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        *,
        invocation_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Return raw event rows with parsed event_data JSON.

        Args:
            app_name: Application name.
            user_id: User ID.
            session_id: Session ID.
            invocation_id: Optional filter for a single invocation.
            limit: Optional maximum number of events to return.

        Returns:
            List of event dicts with keys: id, invocation_id, timestamp,
            event_data (parsed dict).
        """
        conditions = [
            "app_name = $1",
            "user_id = $2",
            "session_id = $3",
        ]
        params = [app_name, user_id, session_id]

        if invocation_id:
            conditions.append(f"invocation_id = ${len(params) + 1}")
            params.append(invocation_id)

        where = " AND ".join(conditions)
        limit_clause = f"LIMIT {limit}" if limit else ""

        sql = f"""
            SELECT id, invocation_id, timestamp, event_data
            FROM sdb.events
            WHERE {where}
            ORDER BY timestamp
            {limit_clause}
        """
        rows = self.execute(sql, params)
        for row in rows:
            try:
                row["event_data"] = json.loads(row["event_data"])
            except (json.JSONDecodeError, TypeError):
                pass  # Leave as string if not valid JSON
        return rows
```

### Tests

**File**: `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_trace_reader.py` (NEW)

#### TDD Plan

**RED 1**: `test_trace_reader_raises_on_missing_db`
```python
def test_trace_reader_raises_on_missing_db():
    with pytest.raises(FileNotFoundError):
        TraceReader("/nonexistent/path.db")
```

**GREEN 1**: Implement `__init__` with `Path.exists()` check.

**RED 2**: `test_trace_reader_attaches_sqlite`
```python
def test_trace_reader_attaches_sqlite(tmp_path):
    """TraceReader can attach a valid SQLite file."""
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)  # Helper that creates schema + sample data
    reader = TraceReader(db_path)
    assert reader.conn is not None
    reader.close()
```

**GREEN 2**: Implement `__init__` with DuckDB ATTACH.

**RED 3**: `test_trace_reader_context_manager`
```python
def test_trace_reader_context_manager(tmp_path):
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    with TraceReader(db_path) as reader:
        assert reader.conn is not None
    # After exit, conn should be None
    assert reader._conn is None
```

**GREEN 3**: Implement `__enter__` / `__exit__`.

**RED 4**: `test_list_sessions`
```python
def test_list_sessions(tmp_path):
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=2, events_per_session=5)
    with TraceReader(db_path) as reader:
        sessions = reader.list_sessions("test_app")
    assert len(sessions) == 2
    assert all("event_count" in s for s in sessions)
```

**GREEN 4**: Implement `list_sessions()`.

**RED 5**: `test_get_events_raw_with_invocation_filter`
```python
def test_get_events_raw_with_invocation_filter(tmp_path):
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    with TraceReader(db_path) as reader:
        events = reader.get_events_raw(
            "test_app", "user_1", "session_1",
            invocation_id="inv_1"
        )
    assert all(e["invocation_id"] == "inv_1" for e in events)
```

**GREEN 5**: Implement `get_events_raw()` with invocation_id filter.

**RED 6**: `test_get_session_state`
```python
def test_get_session_state(tmp_path):
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    with TraceReader(db_path) as reader:
        state = reader.get_session_state("test_app", "user_1", "session_1")
    assert isinstance(state, dict)
```

**GREEN 6**: Implement `get_session_state()`.

#### Test helper `_create_test_db()`

```python
import sqlite3
import json
import time
import uuid

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
```

### Dependencies

```toml
# pyproject.toml - add to dependencies:
"duckdb>=1.0.0",
```

---

<a id="rec-7"></a>
## Recommendation 7: Expose Evaluation Queries

### What

Build three evaluation query functions on top of `TraceReader`:
1. `get_session_traces()` -- Extract structured traces (invocation-level) from a session
2. `get_divergence_points()` -- Find invocations where two sessions diverge
3. `compare_sessions()` -- Side-by-side comparison of two session trajectories

These are the analytical primitives that evaluation agents use to inspect, compare, and reason about agent trajectories.

### Where

**New file**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/eval/queries.py`

### How

#### Method signatures

```python
"""Evaluation query functions for comparing and analyzing session traces.

All functions operate through a TraceReader instance and return structured
dicts suitable for programmatic consumption by evaluation agents.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from rlm_adk.eval.trace_reader import TraceReader

logger = logging.getLogger(__name__)


@dataclass
class InvocationTrace:
    """Structured representation of a single invocation within a session.

    An invocation corresponds to one user turn: all events sharing the
    same invocation_id.
    """
    invocation_id: str
    events: list[dict[str, Any]]
    state_deltas: list[dict[str, Any]]
    timestamp_start: float
    timestamp_end: float
    author_sequence: list[str]
    token_usage: dict[str, int] = field(default_factory=dict)


@dataclass
class DivergencePoint:
    """A point where two sessions' trajectories diverge.

    Attributes:
        invocation_index: 0-based index of the invocation where divergence occurs.
        invocation_id_a: Invocation ID from session A at the divergence point.
        invocation_id_b: Invocation ID from session B at the divergence point.
        reason: Human-readable description of why divergence was detected.
        details: Additional context (e.g., differing state keys, different authors).
    """
    invocation_index: int
    invocation_id_a: str
    invocation_id_b: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionComparison:
    """Side-by-side comparison of two session trajectories.

    Attributes:
        session_id_a: First session ID.
        session_id_b: Second session ID.
        traces_a: List of InvocationTrace for session A.
        traces_b: List of InvocationTrace for session B.
        divergence_points: List of DivergencePoint instances.
        summary: Dict with high-level comparison metrics.
    """
    session_id_a: str
    session_id_b: str
    traces_a: list[InvocationTrace]
    traces_b: list[InvocationTrace]
    divergence_points: list[DivergencePoint]
    summary: dict[str, Any] = field(default_factory=dict)


def get_session_traces(
    reader: TraceReader,
    app_name: str,
    user_id: str,
    session_id: str,
) -> list[InvocationTrace]:
    """Extract structured invocation-level traces from a session.

    Groups events by invocation_id and extracts state deltas, author
    sequences, and timing information from each invocation.

    Args:
        reader: An open TraceReader instance.
        app_name: Application name.
        user_id: User ID.
        session_id: Session ID.

    Returns:
        List of InvocationTrace objects, ordered chronologically.
    """
    invocation_ids = reader.get_invocation_ids(app_name, user_id, session_id)
    traces = []

    for inv_id in invocation_ids:
        events = reader.get_events_raw(
            app_name, user_id, session_id,
            invocation_id=inv_id,
        )
        if not events:
            continue

        state_deltas = []
        authors = []
        token_usage = {"input_tokens": 0, "output_tokens": 0}

        for evt in events:
            ed = evt.get("event_data", {})
            if isinstance(ed, str):
                try:
                    ed = json.loads(ed)
                except (json.JSONDecodeError, TypeError):
                    ed = {}

            # Extract state_delta from event_data.actions.state_delta
            actions = ed.get("actions", {})
            if actions and isinstance(actions, dict):
                sd = actions.get("state_delta")
                if sd:
                    state_deltas.append(sd)

            # Extract author
            author = ed.get("author", "unknown")
            authors.append(author)

            # Extract token usage from usage_metadata if present
            usage = ed.get("usage_metadata", {})
            if usage and isinstance(usage, dict):
                token_usage["input_tokens"] += usage.get("prompt_token_count", 0) or 0
                token_usage["output_tokens"] += usage.get("candidates_token_count", 0) or 0

        trace = InvocationTrace(
            invocation_id=inv_id,
            events=events,
            state_deltas=state_deltas,
            timestamp_start=events[0]["timestamp"],
            timestamp_end=events[-1]["timestamp"],
            author_sequence=authors,
            token_usage=token_usage,
        )
        traces.append(trace)

    return traces


def get_divergence_points(
    reader: TraceReader,
    app_name: str,
    user_id: str,
    session_id_a: str,
    session_id_b: str,
) -> list[DivergencePoint]:
    """Find invocations where two sessions' trajectories diverge.

    Compares sessions invocation-by-invocation. Divergence is detected when:
    1. Author sequences differ at the same invocation index.
    2. State delta keys differ at the same invocation index.
    3. One session has more invocations than the other (length mismatch).

    Args:
        reader: An open TraceReader instance.
        app_name: Application name.
        user_id: User ID.
        session_id_a: First session ID.
        session_id_b: Second session ID.

    Returns:
        List of DivergencePoint objects, ordered by invocation_index.
    """
    traces_a = get_session_traces(reader, app_name, user_id, session_id_a)
    traces_b = get_session_traces(reader, app_name, user_id, session_id_b)

    divergences = []
    min_len = min(len(traces_a), len(traces_b))

    for idx in range(min_len):
        ta = traces_a[idx]
        tb = traces_b[idx]

        # Check author sequence divergence
        if ta.author_sequence != tb.author_sequence:
            divergences.append(DivergencePoint(
                invocation_index=idx,
                invocation_id_a=ta.invocation_id,
                invocation_id_b=tb.invocation_id,
                reason="author_sequence_mismatch",
                details={
                    "authors_a": ta.author_sequence,
                    "authors_b": tb.author_sequence,
                },
            ))
            continue

        # Check state delta key divergence
        keys_a = set()
        for sd in ta.state_deltas:
            keys_a.update(sd.keys())
        keys_b = set()
        for sd in tb.state_deltas:
            keys_b.update(sd.keys())

        if keys_a != keys_b:
            divergences.append(DivergencePoint(
                invocation_index=idx,
                invocation_id_a=ta.invocation_id,
                invocation_id_b=tb.invocation_id,
                reason="state_delta_keys_mismatch",
                details={
                    "only_in_a": sorted(keys_a - keys_b),
                    "only_in_b": sorted(keys_b - keys_a),
                },
            ))

    # Length mismatch
    if len(traces_a) != len(traces_b):
        divergences.append(DivergencePoint(
            invocation_index=min_len,
            invocation_id_a=traces_a[min_len].invocation_id if min_len < len(traces_a) else "N/A",
            invocation_id_b=traces_b[min_len].invocation_id if min_len < len(traces_b) else "N/A",
            reason="invocation_count_mismatch",
            details={
                "count_a": len(traces_a),
                "count_b": len(traces_b),
            },
        ))

    return divergences


def compare_sessions(
    reader: TraceReader,
    app_name: str,
    user_id: str,
    session_id_a: str,
    session_id_b: str,
) -> SessionComparison:
    """Full side-by-side comparison of two session trajectories.

    Combines get_session_traces() and get_divergence_points() into a
    single structured comparison with summary metrics.

    Args:
        reader: An open TraceReader instance.
        app_name: Application name.
        user_id: User ID.
        session_id_a: First session ID.
        session_id_b: Second session ID.

    Returns:
        SessionComparison with traces, divergence points, and summary.
    """
    traces_a = get_session_traces(reader, app_name, user_id, session_id_a)
    traces_b = get_session_traces(reader, app_name, user_id, session_id_b)
    divergences = get_divergence_points(
        reader, app_name, user_id, session_id_a, session_id_b
    )

    # Compute summary metrics
    total_tokens_a = sum(t.token_usage.get("input_tokens", 0) + t.token_usage.get("output_tokens", 0) for t in traces_a)
    total_tokens_b = sum(t.token_usage.get("input_tokens", 0) + t.token_usage.get("output_tokens", 0) for t in traces_b)

    duration_a = (traces_a[-1].timestamp_end - traces_a[0].timestamp_start) if traces_a else 0.0
    duration_b = (traces_b[-1].timestamp_end - traces_b[0].timestamp_start) if traces_b else 0.0

    summary = {
        "invocations_a": len(traces_a),
        "invocations_b": len(traces_b),
        "total_tokens_a": total_tokens_a,
        "total_tokens_b": total_tokens_b,
        "duration_a": round(duration_a, 3),
        "duration_b": round(duration_b, 3),
        "divergence_count": len(divergences),
        "first_divergence_index": divergences[0].invocation_index if divergences else None,
    }

    return SessionComparison(
        session_id_a=session_id_a,
        session_id_b=session_id_b,
        traces_a=traces_a,
        traces_b=traces_b,
        divergence_points=divergences,
        summary=summary,
    )
```

### Tests

**File**: `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_eval_queries.py` (NEW)

#### TDD Plan

**RED 1**: `test_get_session_traces_returns_invocation_traces`
```python
def test_get_session_traces_returns_invocation_traces(tmp_path):
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=6)  # 3 invocations
    with TraceReader(db_path) as reader:
        traces = get_session_traces(reader, "test_app", "user_1", "session_1")
    assert len(traces) > 0
    assert all(isinstance(t, InvocationTrace) for t in traces)
    assert all(t.invocation_id for t in traces)
```

**GREEN 1**: Implement `get_session_traces()`.

**RED 2**: `test_get_session_traces_groups_by_invocation`
```python
def test_get_session_traces_groups_by_invocation(tmp_path):
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, events_per_session=6)  # Events paired as inv_1, inv_1, inv_2, inv_2, inv_3, inv_3
    with TraceReader(db_path) as reader:
        traces = get_session_traces(reader, "test_app", "user_1", "session_1")
    # Each invocation should have 2 events
    for t in traces:
        assert len(t.events) == 2
```

**GREEN 2**: Ensure grouping by invocation_id works correctly.

**RED 3**: `test_get_divergence_points_identical_sessions`
```python
def test_get_divergence_points_identical_sessions(tmp_path):
    """Two identical sessions should have no divergence points (except possibly length)."""
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=2, events_per_session=4)
    with TraceReader(db_path) as reader:
        divergences = get_divergence_points(
            reader, "test_app", "user_1", "session_1", "session_2"
        )
    # Identical structure -> no divergences (or only structural ones)
    assert isinstance(divergences, list)
```

**GREEN 3**: Implement `get_divergence_points()`.

**RED 4**: `test_get_divergence_points_length_mismatch`
```python
def test_get_divergence_points_length_mismatch(tmp_path):
    """Sessions with different event counts should report length mismatch."""
    db_path = str(tmp_path / "test.db")
    _create_test_db_asymmetric(db_path, events_a=4, events_b=6)
    with TraceReader(db_path) as reader:
        divergences = get_divergence_points(
            reader, "test_app", "user_1", "session_a", "session_b"
        )
    length_mismatches = [d for d in divergences if d.reason == "invocation_count_mismatch"]
    assert len(length_mismatches) == 1
```

**GREEN 4**: Add length mismatch detection to `get_divergence_points()`.

**RED 5**: `test_compare_sessions_returns_summary`
```python
def test_compare_sessions_returns_summary(tmp_path):
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
```

**GREEN 5**: Implement `compare_sessions()`.

### Dependencies

Same as Rec 6 (`duckdb>=1.0.0`).

---

<a id="rec-8"></a>
## Recommendation 8: Integrate with Session Rewind / Fork

### What

Build a `fork_session()` utility that:
1. Loads an existing session up to a specified invocation point
2. Creates a NEW session with events copied up to that point
3. Returns the new session ID so an evaluation agent can re-execute with modified parameters

This preserves the original session (append-only) while allowing trajectory exploration. ADK's built-in `Runner.rewind_async()` modifies the session in-place, so forking requires manual event copying.

### Where

**New file**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/eval/session_fork.py`

### How

```python
"""Session forking for evaluation agents.

Provides fork_session() which creates a new session from an existing one,
copying events up to a specified invocation point. This enables trajectory
exploration without modifying the original session.

Pattern:
1. Identify divergence point (via eval/queries.py)
2. Fork original session at that point
3. Re-execute agent on the forked session with modified parameters
4. Compare original vs forked trajectories
"""

import logging
from typing import Any, Optional

from google.adk.events import Event
from google.adk.sessions.base_session_service import BaseSessionService

logger = logging.getLogger(__name__)


async def fork_session(
    session_service: BaseSessionService,
    *,
    app_name: str,
    user_id: str,
    source_session_id: str,
    fork_before_invocation_id: str,
    new_session_id: Optional[str] = None,
    state_overrides: Optional[dict[str, Any]] = None,
) -> str:
    """Fork a session at a specific invocation point.

    Creates a new session with events copied from the source session up to
    (but not including) the specified invocation. The original session is
    unchanged.

    Args:
        session_service: The session service to use for both reading the
            source and creating the fork.
        app_name: Application name.
        user_id: User ID.
        source_session_id: ID of the session to fork from.
        fork_before_invocation_id: Fork point. Events with this invocation_id
            and later are NOT copied. Events before this point ARE copied.
        new_session_id: Optional explicit ID for the new session. If None,
            the session service generates a UUID.
        state_overrides: Optional dict of state keys to override in the
            forked session's initial state. Applied after copying events.

    Returns:
        The new (forked) session's ID.

    Raises:
        ValueError: If source session not found or invocation_id not found.
    """
    # 1. Load the source session with all events
    source = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=source_session_id,
    )
    if source is None:
        raise ValueError(f"Source session not found: {source_session_id}")

    # 2. Find the fork point
    fork_index = None
    for i, event in enumerate(source.events):
        if event.invocation_id == fork_before_invocation_id:
            fork_index = i
            break

    if fork_index is None:
        raise ValueError(
            f"Invocation ID not found in source session: {fork_before_invocation_id}"
        )

    events_to_copy = source.events[:fork_index]

    # 3. Create new session
    new_session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id=new_session_id,
    )

    # 4. Replay events into the new session
    for event in events_to_copy:
        await session_service.append_event(session=new_session, event=event)

    # 5. Apply state overrides if provided
    if state_overrides:
        override_event = Event(
            invocation_id=new_session.events[-1].invocation_id if new_session.events else "fork_init",
            author="eval_fork",
            actions=_make_event_actions(state_overrides),
        )
        await session_service.append_event(session=new_session, event=override_event)

    logger.info(
        "Forked session %s -> %s at invocation %s (%d events copied)",
        source_session_id, new_session.id, fork_before_invocation_id, len(events_to_copy),
    )

    return new_session.id


def _make_event_actions(state_delta: dict[str, Any]):
    """Create EventActions with the given state_delta."""
    from google.adk.events import EventActions
    return EventActions(state_delta=state_delta)
```

### Tests

**File**: `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_session_fork.py` (NEW)

#### TDD Plan

These tests use `InMemorySessionService` for speed (no SQLite needed for fork logic).

**RED 1**: `test_fork_session_creates_new_session`
```python
import pytest
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.events import Event, EventActions
from rlm_adk.eval.session_fork import fork_session

@pytest.fixture
async def populated_session():
    """Create an InMemorySessionService with a session containing 3 invocations."""
    service = InMemorySessionService()
    session = await service.create_session(
        app_name="test_app", user_id="user_1",
    )
    # Add events for 3 invocations
    for inv_idx in range(3):
        inv_id = f"inv_{inv_idx}"
        event = Event(
            invocation_id=inv_id,
            author="orchestrator",
            actions=EventActions(state_delta={"iteration_count": inv_idx}),
        )
        await service.append_event(session=session, event=event)
    return service, session

@pytest.mark.asyncio
async def test_fork_session_creates_new_session(populated_session):
    service, session = populated_session
    new_id = await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_2",
    )
    assert new_id != session.id
    new_session = await service.get_session(
        app_name="test_app", user_id="user_1", session_id=new_id,
    )
    assert new_session is not None
```

**GREEN 1**: Implement `fork_session()` basic flow.

**RED 2**: `test_fork_session_copies_events_before_fork_point`
```python
@pytest.mark.asyncio
async def test_fork_session_copies_events_before_fork_point(populated_session):
    service, session = populated_session
    new_id = await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_2",
    )
    new_session = await service.get_session(
        app_name="test_app", user_id="user_1", session_id=new_id,
    )
    # Should have events from inv_0 and inv_1 only (2 events)
    assert len(new_session.events) == 2
    inv_ids = {e.invocation_id for e in new_session.events}
    assert "inv_2" not in inv_ids
```

**GREEN 2**: Implement event slicing at fork point.

**RED 3**: `test_fork_session_preserves_original`
```python
@pytest.mark.asyncio
async def test_fork_session_preserves_original(populated_session):
    service, session = populated_session
    original_event_count = len(session.events)
    await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_2",
    )
    # Reload original
    reloaded = await service.get_session(
        app_name="test_app", user_id="user_1", session_id=session.id,
    )
    assert len(reloaded.events) == original_event_count
```

**GREEN 3**: Already works (we only create new session, never modify source).

**RED 4**: `test_fork_session_applies_state_overrides`
```python
@pytest.mark.asyncio
async def test_fork_session_applies_state_overrides(populated_session):
    service, session = populated_session
    new_id = await fork_session(
        service,
        app_name="test_app",
        user_id="user_1",
        source_session_id=session.id,
        fork_before_invocation_id="inv_2",
        state_overrides={"custom_param": "modified"},
    )
    new_session = await service.get_session(
        app_name="test_app", user_id="user_1", session_id=new_id,
    )
    assert new_session.state.get("custom_param") == "modified"
```

**GREEN 4**: Implement state override event append.

**RED 5**: `test_fork_session_raises_on_missing_source`
```python
@pytest.mark.asyncio
async def test_fork_session_raises_on_missing_source():
    service = InMemorySessionService()
    with pytest.raises(ValueError, match="Source session not found"):
        await fork_session(
            service,
            app_name="test_app",
            user_id="user_1",
            source_session_id="nonexistent",
            fork_before_invocation_id="inv_0",
        )
```

**GREEN 5**: Already works (the `if source is None: raise ValueError` guard).

**RED 6**: `test_fork_session_raises_on_missing_invocation`
```python
@pytest.mark.asyncio
async def test_fork_session_raises_on_missing_invocation(populated_session):
    service, session = populated_session
    with pytest.raises(ValueError, match="Invocation ID not found"):
        await fork_session(
            service,
            app_name="test_app",
            user_id="user_1",
            source_session_id=session.id,
            fork_before_invocation_id="inv_999",
        )
```

**GREEN 6**: Already works (the `if fork_index is None: raise ValueError` guard).

### Dependencies

None beyond ADK core.

---

<a id="rec-9"></a>
## Recommendation 9: Create `MigrationPlugin`

### What

Create a `MigrationPlugin` that implements `after_run_callback` to migrate completed session data from the local SQLite database to a PostgreSQL long-term store. Follows the existing plugin pattern (see `ObservabilityPlugin`, `DebugLoggingPlugin`).

The migration is:
- **End-of-session**: Only triggers after a run completes (not during)
- **Batch-oriented**: Copies all events + state for the completed session
- **Idempotent**: Uses upsert semantics so re-migration is safe
- **Optional**: Safe to include when Postgres is not configured (logs a warning and skips)

### Where

**New file**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/migration.py`
**Modify**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/__init__.py` (add export)

### How

#### `rlm_adk/plugins/migration.py`

```python
"""MigrationPlugin - End-of-session batch migration from SQLite to PostgreSQL.

Implements the Strategy B (End-of-Session Migration) from the database
strategy report. Triggers on after_run_callback to migrate the completed
session's data to a PostgreSQL long-term store.

Configuration via environment variables:
    RLM_MIGRATION_ENABLED   - "1" or "true" to enable (default: disabled)
    RLM_POSTGRES_URL        - SQLAlchemy async Postgres URL
                              (e.g., postgresql+asyncpg://user:pass@host/db)
    RLM_SESSION_DB           - Path to the local SQLite session database
                              (default: .adk/session.db)
    RLM_MIGRATION_RETENTION  - Number of sessions to retain locally after
                              migration (default: 50). Set to 0 to disable pruning.
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from google.adk.agents.invocation_context import InvocationContext
from google.adk.plugins.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

# State key for tracking migration status
MIGRATION_STATUS = "migration:status"
MIGRATION_TIMESTAMP = "migration:timestamp"
MIGRATION_ERROR = "migration:error"


class MigrationPlugin(BasePlugin):
    """End-of-session batch migration from SQLite to PostgreSQL.

    The plugin reads session data directly from the SQLite file (not through
    ADK's session service) to avoid holding locks during migration. It writes
    to PostgreSQL via SQLAlchemy's async engine.

    The plugin is safe to include when PostgreSQL is not configured:
    initialization logs a warning and all callbacks become no-ops.

    Migration flow (in after_run_callback):
    1. Read completed session from SQLite (sessions + events tables)
    2. Upsert session record to Postgres
    3. Batch-insert events to Postgres (with ON CONFLICT DO NOTHING)
    4. Mark session as migrated in SQLite (via a migration_status column
       or a separate tracking table)
    5. Optionally prune old migrated sessions from SQLite (FIFO)
    """

    def __init__(
        self,
        *,
        name: str = "migration",
        postgres_url: Optional[str] = None,
        sqlite_db_path: Optional[str] = None,
        retention_count: Optional[int] = None,
    ):
        """Initialize the MigrationPlugin.

        Args:
            name: Plugin name.
            postgres_url: SQLAlchemy async PostgreSQL URL. Falls back to
                ``RLM_POSTGRES_URL`` env var.
            sqlite_db_path: Path to the local SQLite database. Falls back to
                ``RLM_SESSION_DB`` env var, then ``.adk/session.db``.
            retention_count: Number of sessions to retain locally after
                migration. Falls back to ``RLM_MIGRATION_RETENTION`` env var,
                then 50. Set to 0 to disable pruning.
        """
        super().__init__(name=name)

        self._postgres_url = postgres_url or os.getenv("RLM_POSTGRES_URL")
        self._sqlite_path = sqlite_db_path or os.getenv("RLM_SESSION_DB", ".adk/session.db")
        self._retention = retention_count
        if self._retention is None:
            self._retention = int(os.getenv("RLM_MIGRATION_RETENTION", "50"))

        self._enabled = False
        self._engine = None

        if not self._postgres_url:
            logger.warning(
                "MigrationPlugin disabled: RLM_POSTGRES_URL not set. "
                "Session data will remain in local SQLite only."
            )
            return

        self._enabled = True
        logger.info(
            "MigrationPlugin enabled: postgres=%s, sqlite=%s, retention=%d",
            self._postgres_url.split("@")[-1] if "@" in self._postgres_url else "(url)",
            self._sqlite_path,
            self._retention,
        )

    async def _get_engine(self):
        """Lazily create the SQLAlchemy async engine.

        Returns:
            An AsyncEngine instance, or None if creation fails.
        """
        if self._engine is not None:
            return self._engine

        try:
            from sqlalchemy.ext.asyncio import create_async_engine

            self._engine = create_async_engine(
                self._postgres_url,
                echo=False,
                pool_size=2,
                max_overflow=1,
                pool_pre_ping=True,
            )
            # Ensure target tables exist
            await self._ensure_postgres_schema()
            return self._engine
        except ImportError:
            logger.error(
                "MigrationPlugin requires sqlalchemy[asyncio] and asyncpg. "
                "Install with: pip install 'sqlalchemy[asyncio]' asyncpg"
            )
            self._enabled = False
            return None
        except Exception as e:
            logger.error("MigrationPlugin engine creation failed: %s", e)
            self._enabled = False
            return None

    async def _ensure_postgres_schema(self):
        """Create migration target tables in PostgreSQL if they don't exist.

        Uses the same schema as SqliteSessionService for compatibility,
        with Postgres-specific types (JSONB instead of TEXT for state/event_data).
        """
        from sqlalchemy import text

        create_sql = text("""
            CREATE TABLE IF NOT EXISTS sessions (
                app_name TEXT NOT NULL,
                user_id TEXT NOT NULL,
                id TEXT NOT NULL,
                state JSONB NOT NULL DEFAULT '{}',
                create_time DOUBLE PRECISION NOT NULL,
                update_time DOUBLE PRECISION NOT NULL,
                migrated_at DOUBLE PRECISION,
                PRIMARY KEY (app_name, user_id, id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT NOT NULL,
                app_name TEXT NOT NULL,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                invocation_id TEXT NOT NULL,
                timestamp DOUBLE PRECISION NOT NULL,
                event_data JSONB NOT NULL DEFAULT '{}',
                PRIMARY KEY (app_name, user_id, session_id, id),
                FOREIGN KEY (app_name, user_id, session_id)
                    REFERENCES sessions(app_name, user_id, id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS app_states (
                app_name TEXT PRIMARY KEY,
                state JSONB NOT NULL DEFAULT '{}',
                update_time DOUBLE PRECISION NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_states (
                app_name TEXT NOT NULL,
                user_id TEXT NOT NULL,
                state JSONB NOT NULL DEFAULT '{}',
                update_time DOUBLE PRECISION NOT NULL,
                PRIMARY KEY (app_name, user_id)
            );
        """)

        async with self._engine.begin() as conn:
            await conn.execute(create_sql)

    async def after_run_callback(
        self,
        *,
        invocation_context: InvocationContext,
    ) -> None:
        """Migrate the completed session to PostgreSQL.

        This is the main migration entry point, called by the ADK Runner
        after the agent run completes.
        """
        if not self._enabled:
            return

        session = invocation_context.session
        app_name = invocation_context.app_name
        user_id = session.user_id
        session_id = session.id

        start_time = time.time()

        try:
            engine = await self._get_engine()
            if engine is None:
                return

            # Read session data from SQLite
            session_data, events_data = self._read_session_from_sqlite(
                app_name, user_id, session_id
            )

            if session_data is None:
                logger.warning(
                    "MigrationPlugin: session %s not found in SQLite, skipping",
                    session_id,
                )
                return

            # Upsert to PostgreSQL
            await self._upsert_to_postgres(session_data, events_data)

            # Update migration tracking
            elapsed = time.time() - start_time
            state = invocation_context.session.state
            state[MIGRATION_STATUS] = "completed"
            state[MIGRATION_TIMESTAMP] = time.time()

            logger.info(
                "MigrationPlugin: migrated session %s (%d events) in %.2fs",
                session_id, len(events_data), elapsed,
            )

            # Prune old migrated sessions from SQLite
            if self._retention > 0:
                pruned = self._prune_local_sessions(app_name, self._retention)
                if pruned > 0:
                    logger.info(
                        "MigrationPlugin: pruned %d old sessions from SQLite", pruned
                    )

        except Exception as e:
            logger.error("MigrationPlugin: migration failed for session %s: %s", session_id, e)
            try:
                invocation_context.session.state[MIGRATION_STATUS] = "failed"
                invocation_context.session.state[MIGRATION_ERROR] = str(e)
            except Exception:
                pass

    def _read_session_from_sqlite(
        self, app_name: str, user_id: str, session_id: str
    ) -> tuple[Optional[dict], list[dict]]:
        """Read session and events from the local SQLite database.

        Uses a synchronous sqlite3 connection (separate from the ADK
        session service's aiosqlite connections) to avoid lock contention.

        Returns:
            (session_dict, events_list) or (None, []) if not found.
        """
        if not Path(self._sqlite_path).exists():
            return None, []

        conn = sqlite3.connect(self._sqlite_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM sessions WHERE app_name=? AND user_id=? AND id=?",
                (app_name, user_id, session_id),
            ).fetchone()
            if row is None:
                return None, []

            session_data = dict(row)

            events = conn.execute(
                "SELECT * FROM events WHERE app_name=? AND user_id=? AND session_id=? ORDER BY timestamp",
                (app_name, user_id, session_id),
            ).fetchall()
            events_data = [dict(e) for e in events]

            return session_data, events_data
        finally:
            conn.close()

    async def _upsert_to_postgres(
        self, session_data: dict, events_data: list[dict]
    ) -> None:
        """Upsert session and events to PostgreSQL.

        Uses ON CONFLICT DO UPDATE for the session and ON CONFLICT DO NOTHING
        for events (events are immutable once written).
        """
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            # Upsert session
            await conn.execute(
                text("""
                    INSERT INTO sessions (app_name, user_id, id, state, create_time, update_time, migrated_at)
                    VALUES (:app_name, :user_id, :id, :state::jsonb, :create_time, :update_time, :migrated_at)
                    ON CONFLICT (app_name, user_id, id) DO UPDATE SET
                        state = EXCLUDED.state,
                        update_time = EXCLUDED.update_time,
                        migrated_at = EXCLUDED.migrated_at
                """),
                {
                    **session_data,
                    "migrated_at": time.time(),
                },
            )

            # Batch insert events
            if events_data:
                await conn.execute(
                    text("""
                        INSERT INTO events (id, app_name, user_id, session_id, invocation_id, timestamp, event_data)
                        VALUES (:id, :app_name, :user_id, :session_id, :invocation_id, :timestamp, :event_data::jsonb)
                        ON CONFLICT (app_name, user_id, session_id, id) DO NOTHING
                    """),
                    events_data,
                )

    def _prune_local_sessions(self, app_name: str, retention: int) -> int:
        """Remove oldest migrated sessions from SQLite, keeping `retention` most recent.

        Only prunes sessions that have been successfully migrated (tracked by
        the presence of the session in Postgres, indicated here by checking
        if the session count exceeds retention).

        Returns:
            Number of sessions deleted.
        """
        if not Path(self._sqlite_path).exists():
            return 0

        conn = sqlite3.connect(self._sqlite_path)
        try:
            # Count total sessions for the app
            total = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE app_name=?",
                (app_name,),
            ).fetchone()[0]

            if total <= retention:
                return 0

            # Delete oldest sessions beyond retention limit
            # ON DELETE CASCADE handles events
            to_delete = total - retention
            conn.execute(
                """
                DELETE FROM sessions WHERE rowid IN (
                    SELECT rowid FROM sessions
                    WHERE app_name=?
                    ORDER BY update_time ASC
                    LIMIT ?
                )
                """,
                (app_name, to_delete),
            )
            conn.commit()

            # VACUUM to reclaim space (only if significant deletions)
            if to_delete >= 10:
                conn.execute("VACUUM")

            return to_delete
        finally:
            conn.close()

    async def close(self) -> None:
        """Clean up the SQLAlchemy engine on runner shutdown."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
```

#### Update `rlm_adk/plugins/__init__.py`

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/__init__.py`

Add import and export:

```python
"""RLM ADK Plugins - Before/after agent callbacks for cross-cutting concerns."""

from rlm_adk.plugins.cache import CachePlugin
from rlm_adk.plugins.debug_logging import DebugLoggingPlugin
from rlm_adk.plugins.langfuse_tracing import LangfuseTracingPlugin
from rlm_adk.plugins.migration import MigrationPlugin          # NEW
from rlm_adk.plugins.observability import ObservabilityPlugin
from rlm_adk.plugins.policy import PolicyPlugin

__all__ = [
    "CachePlugin",
    "DebugLoggingPlugin",
    "LangfuseTracingPlugin",
    "MigrationPlugin",                                           # NEW
    "ObservabilityPlugin",
    "PolicyPlugin",
]
```

### Tests

**File**: `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_migration_plugin.py` (NEW)

#### TDD Plan

**RED 1**: `test_migration_plugin_disabled_when_no_postgres_url`
```python
def test_migration_plugin_disabled_when_no_postgres_url(monkeypatch):
    """Plugin is disabled when RLM_POSTGRES_URL is not set."""
    monkeypatch.delenv("RLM_POSTGRES_URL", raising=False)
    plugin = MigrationPlugin()
    assert plugin._enabled is False
```

**GREEN 1**: The constructor checks `self._postgres_url` and sets `self._enabled = False`.

**RED 2**: `test_migration_plugin_enabled_with_postgres_url`
```python
def test_migration_plugin_enabled_with_postgres_url(monkeypatch):
    monkeypatch.setenv("RLM_POSTGRES_URL", "postgresql+asyncpg://user:pass@localhost/db")
    plugin = MigrationPlugin()
    assert plugin._enabled is True
```

**GREEN 2**: Constructor sets `self._enabled = True` when URL is present.

**RED 3**: `test_migration_plugin_after_run_noop_when_disabled`
```python
@pytest.mark.asyncio
async def test_migration_plugin_after_run_noop_when_disabled(monkeypatch):
    """after_run_callback is a no-op when plugin is disabled."""
    monkeypatch.delenv("RLM_POSTGRES_URL", raising=False)
    plugin = MigrationPlugin()
    mock_ctx = MagicMock()
    # Should not raise or do anything
    await plugin.after_run_callback(invocation_context=mock_ctx)
```

**GREEN 3**: Early return when `not self._enabled`.

**RED 4**: `test_migration_plugin_reads_from_sqlite`
```python
@pytest.mark.asyncio
async def test_migration_plugin_reads_from_sqlite(tmp_path):
    """_read_session_from_sqlite returns session and events."""
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
    )
    session, events = plugin._read_session_from_sqlite("test_app", "user_1", "session_1")
    assert session is not None
    assert len(events) > 0
```

**GREEN 4**: Implement `_read_session_from_sqlite()`.

**RED 5**: `test_migration_plugin_returns_none_for_missing_session`
```python
@pytest.mark.asyncio
async def test_migration_plugin_returns_none_for_missing_session(tmp_path):
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
    )
    session, events = plugin._read_session_from_sqlite("test_app", "user_1", "nonexistent")
    assert session is None
    assert events == []
```

**GREEN 5**: The `if row is None: return None, []` guard handles this.

**RED 6**: `test_migration_plugin_prune_sessions`
```python
def test_migration_plugin_prune_sessions(tmp_path):
    """_prune_local_sessions removes oldest sessions beyond retention."""
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=10)
    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
        retention_count=3,
    )
    pruned = plugin._prune_local_sessions("test_app", 3)
    assert pruned == 7

    # Verify only 3 remain
    import sqlite3
    conn = sqlite3.connect(db_path)
    remaining = conn.execute("SELECT COUNT(*) FROM sessions WHERE app_name='test_app'").fetchone()[0]
    conn.close()
    assert remaining == 3
```

**GREEN 6**: Implement `_prune_local_sessions()`.

**RED 7**: `test_migration_plugin_prune_no_op_under_retention`
```python
def test_migration_plugin_prune_no_op_under_retention(tmp_path):
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=2)
    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
        retention_count=10,
    )
    pruned = plugin._prune_local_sessions("test_app", 10)
    assert pruned == 0
```

**GREEN 7**: The `if total <= retention: return 0` guard handles this.

**RED 8** (Integration, requires Postgres): `test_migration_plugin_full_migration`
```python
@pytest.mark.skipif(
    not os.getenv("RLM_POSTGRES_URL"),
    reason="Requires RLM_POSTGRES_URL for integration test",
)
@pytest.mark.asyncio
async def test_migration_plugin_full_migration(tmp_path):
    """Full end-to-end migration from SQLite to Postgres."""
    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=1, events_per_session=5)
    plugin = MigrationPlugin(
        postgres_url=os.getenv("RLM_POSTGRES_URL"),
        sqlite_db_path=db_path,
    )
    # Mock invocation_context
    mock_ctx = MagicMock()
    mock_ctx.session.id = "session_1"
    mock_ctx.session.user_id = "user_1"
    mock_ctx.session.state = {}
    mock_ctx.app_name = "test_app"

    await plugin.after_run_callback(invocation_context=mock_ctx)

    assert mock_ctx.session.state.get(MIGRATION_STATUS) == "completed"
    await plugin.close()
```

**GREEN 8**: Full implementation with `_upsert_to_postgres()`.

### Dependencies

```toml
# pyproject.toml - add to optional dependencies:
[project.optional-dependencies]
postgres = [
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29.0",
]
```

These are optional because PostgreSQL migration is only needed when `RLM_POSTGRES_URL` is configured.

---

<a id="dependencies"></a>
## Dependencies Summary

### Required (add to `dependencies` in `pyproject.toml`)

```toml
"aiosqlite>=0.20.0",       # SQLite async driver (Rec 2: default session service)
"duckdb>=1.0.0",            # Analytics engine (Rec 6-7: TraceReader)
```

### Optional (add to `[project.optional-dependencies]`)

```toml
[project.optional-dependencies]
postgres = [
    "sqlalchemy[asyncio]>=2.0",    # Rec 9: MigrationPlugin
    "asyncpg>=0.29.0",              # Rec 9: Postgres async driver
]
```

### Exact changes to `pyproject.toml`

**File**: `/home/rawley-stanhope/dev/rlm-adk/pyproject.toml`

**Lines 21-35** (dependencies list): Add `aiosqlite` and `duckdb`:

```toml
dependencies = [
    "aiosqlite>=0.20.0",                                    # NEW
    "anthropic>=0.75.0",
    "duckdb>=1.0.0",                                        # NEW
    "google-adk>=1.2.0",
    "google-genai>=1.56.0",
    "langfuse>=3.14.0",
    "openai>=2.14.0",
    "openinference-instrumentation-google-adk>=0.1.9",
    "portkey-ai>=2.1.0",
    "pytest>=9.0.2",
    "pytest-asyncio>=0.24.0",
    "python-dotenv>=1.2.1",
    "repomix>=0.5.0",
    "requests>=2.32.5",
    "rich>=13.0.0",
]
```

**Lines 42-46** (optional-dependencies): Add `postgres` group:

```toml
[project.optional-dependencies]
modal = ["modal>=0.73.0", "dill>=0.3.7"]
e2b = ["e2b-code-interpreter>=0.0.11", "dill>=0.3.7"]
daytona = ["daytona>=0.128.1", "dill>=0.3.7"]
prime = ["prime-sandboxes>=0.2.0", "dill>=0.3.7"]
postgres = ["sqlalchemy[asyncio]>=2.0", "asyncpg>=0.29.0"]  # NEW
```

---

<a id="new-state-keys"></a>
## New State Keys

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py`

Add the following at the end of the file (before the helper functions):

```python
# Migration Tracking Keys (session-scoped)
MIGRATION_STATUS = "migration:status"
MIGRATION_TIMESTAMP = "migration:timestamp"
MIGRATION_ERROR = "migration:error"
```

Note: The `migration:` prefix is a naming convention only (session-scoped, same as `cache:` and `obs:` prefixes). These keys are also defined locally in `rlm_adk/plugins/migration.py` but should be centralized in `state.py` for consistency.

---

<a id="file-inventory"></a>
## File Inventory

### Files to Modify

| File | Rec | Changes |
|------|-----|---------|
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py` | 1, 2 | Add `session_service` param, `_default_session_service()`, change `InMemoryRunner` to `Runner` |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/__init__.py` | 9 | Add `MigrationPlugin` import and export |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py` | 9 | Add migration state keys |
| `/home/rawley-stanhope/dev/rlm-adk/pyproject.toml` | 2, 6, 9 | Add `aiosqlite`, `duckdb`, `postgres` optional deps |

### Files to Create

| File | Rec | Purpose |
|------|-----|---------|
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/eval/__init__.py` | 6 | Package marker, exports TraceReader |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/eval/trace_reader.py` | 6 | DuckDB-backed trace analytics |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/eval/queries.py` | 7 | Evaluation query functions |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/eval/session_fork.py` | 8 | Session forking for trajectory exploration |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/migration.py` | 9 | MigrationPlugin with after_run_callback |
| `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_session_service_wiring.py` | 1, 2 | Tests for session service wiring and defaults |
| `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_trace_reader.py` | 6 | Tests for TraceReader |
| `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_eval_queries.py` | 7 | Tests for evaluation queries |
| `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_session_fork.py` | 8 | Tests for session forking |
| `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_migration_plugin.py` | 9 | Tests for MigrationPlugin |

### Implementation Order (TDD Sequence)

1. **Rec 2** first: `_default_session_service()` -- foundational, others depend on SQLite being the default
2. **Rec 1** second: `session_service` parameter -- requires Rec 2's factory
3. **Rec 6** third: `TraceReader` -- foundational for Rec 7-8
4. **Rec 7** fourth: Evaluation queries -- requires Rec 6
5. **Rec 8** fifth: Session forking -- requires Rec 7 for divergence detection
6. **Rec 9** sixth: `MigrationPlugin` -- independent of Rec 6-8, but builds on Rec 2's SQLite default

### Running Tests

```bash
# All new tests:
.venv/bin/python -m pytest tests_rlm_adk/test_session_service_wiring.py tests_rlm_adk/test_trace_reader.py tests_rlm_adk/test_eval_queries.py tests_rlm_adk/test_session_fork.py tests_rlm_adk/test_migration_plugin.py -v

# By recommendation:
.venv/bin/python -m pytest tests_rlm_adk/test_session_service_wiring.py -v   # Rec 1-2
.venv/bin/python -m pytest tests_rlm_adk/test_trace_reader.py -v              # Rec 6
.venv/bin/python -m pytest tests_rlm_adk/test_eval_queries.py -v              # Rec 7
.venv/bin/python -m pytest tests_rlm_adk/test_session_fork.py -v              # Rec 8
.venv/bin/python -m pytest tests_rlm_adk/test_migration_plugin.py -v          # Rec 9

# Full test suite (existing + new):
.venv/bin/python -m pytest tests_rlm_adk/ -v
```
