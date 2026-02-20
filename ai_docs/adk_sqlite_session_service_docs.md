# SqliteSessionService Reference

> Source: `google.adk.sessions.sqlite_session_service` (ADK v1.25.0)
> Installed at: `.venv/lib/python3.11/site-packages/google/adk/sessions/sqlite_session_service.py`

## Overview

`SqliteSessionService` is a lightweight, file-based session service that uses SQLite via `aiosqlite` for persistent storage. Unlike `DatabaseSessionService` (which uses SQLAlchemy and supports PostgreSQL, MySQL, MariaDB, and SQLite), `SqliteSessionService` talks directly to SQLite through raw SQL and the `aiosqlite` async driver. It stores event data as JSON for schema flexibility.

**Key distinction**: `SqliteSessionService` is a newer, SQLite-only implementation that does NOT use SQLAlchemy. `DatabaseSessionService` is the older, multi-database implementation that uses SQLAlchemy's async engine. Both can target SQLite, but they use different table schemas and different connection strategies.

## Import

```python
from google.adk.sessions.sqlite_session_service import SqliteSessionService
```

Note: `SqliteSessionService` is NOT exported from `google.adk.sessions.__init__`, so you must import it from its module directly. The `__init__.py` exports `DatabaseSessionService` (lazily) but not `SqliteSessionService`.

## Constructor

```python
class SqliteSessionService(BaseSessionService):
    def __init__(self, db_path: str):
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `db_path` | `str` | (required) | Path to the SQLite database file. Supports plain file paths, SQLAlchemy-style URLs (`sqlite:///relative.db`, `sqlite:////absolute.db`), and URI query parameters. |

### Path Parsing (`_parse_db_path`)

The constructor parses `db_path` through `_parse_db_path()`, which normalizes the path according to these conventions:

| Input Format | Filesystem Path | Connect Path | URI Mode |
|---|---|---|---|
| `./my_data.db` | `./my_data.db` | `./my_data.db` | `False` |
| `sqlite:///relative.db` | `relative.db` | `relative.db` | `False` |
| `sqlite:////absolute.db` | `/absolute.db` | `/absolute.db` | `False` |
| `sqlite:///data.db?mode=ro` | `data.db` | `file:data.db?mode=ro` | `True` |
| `sqlite+aiosqlite:///data.db` | `data.db` | `data.db` | `False` |

When query parameters are present, the path is converted to a `file:` URI so that `sqlite3` interprets them correctly.

### Migration Check

On construction, `_is_migration_needed()` is called synchronously (using `sqlite3`, not `aiosqlite`). It checks whether an existing database uses the old schema (has an `events` table but no `event_data` column). If migration is needed, a `RuntimeError` is raised with instructions to run:

```
python -m google.adk.sessions.migration.migrate_from_sqlalchemy_sqlite \
    --source_db_path <old_db> --dest_db_path <old_db>.new
```

## Database Schema

Four tables are created on every connection via `CREATE TABLE IF NOT EXISTS`:

### `app_states`
```sql
CREATE TABLE IF NOT EXISTS app_states (
    app_name TEXT PRIMARY KEY,
    state TEXT NOT NULL,       -- JSON-encoded state dict
    update_time REAL NOT NULL  -- Unix timestamp (float)
);
```

### `user_states`
```sql
CREATE TABLE IF NOT EXISTS user_states (
    app_name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    state TEXT NOT NULL,       -- JSON-encoded state dict
    update_time REAL NOT NULL,
    PRIMARY KEY (app_name, user_id)
);
```

### `sessions`
```sql
CREATE TABLE IF NOT EXISTS sessions (
    app_name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    id TEXT NOT NULL,
    state TEXT NOT NULL,       -- JSON-encoded session-scoped state
    create_time REAL NOT NULL,
    update_time REAL NOT NULL,
    PRIMARY KEY (app_name, user_id, id)
);
```

### `events`
```sql
CREATE TABLE IF NOT EXISTS events (
    id TEXT NOT NULL,
    app_name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    invocation_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    event_data TEXT NOT NULL,   -- Full Event serialized as JSON
    PRIMARY KEY (app_name, user_id, session_id, id),
    FOREIGN KEY (app_name, user_id, session_id)
        REFERENCES sessions(app_name, user_id, id) ON DELETE CASCADE
);
```

## SQLite Pragmas

On every connection (inside `_get_db_connection()`):

```sql
PRAGMA foreign_keys = ON
```

This is the **only** pragma applied. Notably, there is **no WAL mode** and **no busy_timeout** configured in `SqliteSessionService`. Each connection opens in SQLite's default journal mode (DELETE/rollback journal).

**Comparison with `DatabaseSessionService`**: The SQLAlchemy-based service also sets `PRAGMA foreign_keys=ON` via an engine event listener (`_set_sqlite_pragma`), but similarly does not configure WAL mode or busy_timeout.

## Connection Management

```python
@asynccontextmanager
async def _get_db_connection(self):
    async with aiosqlite.connect(
        self._db_connect_path, uri=self._db_connect_uri
    ) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(PRAGMA_FOREIGN_KEYS)
        await db.executescript(CREATE_SCHEMA_SQL)
        yield db
```

Key characteristics:
- **No connection pooling**: Every operation opens a fresh `aiosqlite.connect()` and closes it when the context manager exits.
- **Schema creation on every call**: `CREATE TABLE IF NOT EXISTS` runs on every connection. This is idempotent but adds overhead.
- **Row factory**: `aiosqlite.Row` enables dict-like access to result rows (e.g., `row["state"]`).
- **No WAL mode**: Default SQLite journal mode applies.

## Session CRUD API

### `create_session`

```python
async def create_session(
    self,
    *,
    app_name: str,
    user_id: str,
    state: Optional[dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Session:
```

**Parameters**:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `app_name` | `str` | (required) | Application identifier |
| `user_id` | `str` | (required) | User identifier |
| `state` | `dict[str, Any]` | `None` | Initial state. Keys prefixed with `app:` go to app_states, `user:` to user_states, others to session state. `temp:` prefixed keys are excluded from persistence. |
| `session_id` | `str` | `None` | Client-provided session ID. If empty/None, a `uuid.uuid4()` is generated. |

**Behavior**:
1. Strips whitespace from `session_id` if provided; generates UUID4 if empty/None.
2. Checks for duplicate session ID; raises `AlreadyExistsError` if exists.
3. Extracts state deltas via `_session_util.extract_state_delta()`:
   - `app:key` -> app state (stored in `app_states` table, stripped of prefix)
   - `user:key` -> user state (stored in `user_states` table, stripped of prefix)
   - Other keys (except `temp:`) -> session state (stored in `sessions.state`)
4. Upserts app and user states atomically using `json_patch()`.
5. Inserts session row.
6. Returns a `Session` object with merged state (app + user + session, prefixes restored).

**Raises**: `AlreadyExistsError` if `session_id` already exists.

### `get_session`

```python
async def get_session(
    self,
    *,
    app_name: str,
    user_id: str,
    session_id: str,
    config: Optional[GetSessionConfig] = None,
) -> Optional[Session]:
```

**`GetSessionConfig` options**:

| Field | Type | Description |
|-------|------|-------------|
| `num_recent_events` | `Optional[int]` | Limit to N most recent events |
| `after_timestamp` | `Optional[float]` | Only events at or after this Unix timestamp |

**Behavior**:
1. Fetches session row; returns `None` if not found.
2. Queries events with optional `after_timestamp` filter and `num_recent_events` limit.
3. Events are queried `ORDER BY timestamp DESC` with optional `LIMIT`, then reversed to chronological order.
4. Fetches app and user states from their respective tables.
5. Merges all three state tiers into a unified dict with prefixes restored.
6. Deserializes events from JSON via `Event.model_validate_json()`.

**Returns**: `Session` with full merged state and filtered events, or `None`.

### `list_sessions`

```python
async def list_sessions(
    self,
    *,
    app_name: str,
    user_id: Optional[str] = None,
) -> ListSessionsResponse:
```

**Behavior**:
- If `user_id` is provided, lists sessions for that user only.
- If `user_id` is `None`, lists all sessions for the app across all users.
- Sessions are returned **without events** (empty events list).
- State is fully merged (app + user + session) for each returned session.

### `delete_session`

```python
async def delete_session(
    self,
    *,
    app_name: str,
    user_id: str,
    session_id: str,
) -> None:
```

**Behavior**: Deletes the session row. Due to `ON DELETE CASCADE` on the foreign key, all associated events are automatically deleted.

**Note**: App states and user states are NOT deleted, as they may be shared across sessions.

### `append_event`

```python
async def append_event(self, session: Session, event: Event) -> Event:
```

**Behavior**:
1. **Partial events**: If `event.partial` is `True`, returns immediately without persisting.
2. **Temp state trimming**: Removes any `temp:` prefixed keys from `event.actions.state_delta`.
3. **Staleness check**: Compares `session.last_update_time` against the stored `update_time`. Raises `ValueError` if the storage timestamp is newer (stale session detection).
4. **State delta application**: Extracts and applies state deltas using `json_patch()`:
   - App state deltas: upserted to `app_states`
   - User state deltas: upserted to `user_states`
   - Session state deltas: patched on `sessions.state`
5. **Event insertion**: Stores the event with full JSON serialization (`event.model_dump_json(exclude_none=True)`).
6. **Timestamp update**: If no session state delta was applied, explicitly updates `sessions.update_time`.
7. **In-memory update**: Calls `super().append_event()` which updates the in-memory `session.state` and appends the event to `session.events`.

**Raises**: `ValueError` if session not found or if session is stale.

## State Management

### Three-Tier State Architecture

State is stored at three levels, each in its own table:

| Tier | Prefix | Storage | Scope |
|------|--------|---------|-------|
| App | `app:` | `app_states` table | Shared across all sessions and users for an app |
| User | `user:` | `user_states` table | Shared across all sessions for a user within an app |
| Session | (no prefix) | `sessions.state` column | Private to a single session |
| Temp | `temp:` | Not persisted | Stripped before storage |

### State Delta Application

State updates use SQLite's built-in `json_patch()` function for atomic merge operations:

```sql
-- App state upsert
INSERT INTO app_states (app_name, state, update_time) VALUES (?, ?, ?)
ON CONFLICT(app_name) DO UPDATE SET
    state=json_patch(state, excluded.state),
    update_time=excluded.update_time

-- Session state patch
UPDATE sessions SET state=json_patch(state, ?), update_time=?
WHERE app_name=? AND user_id=? AND id=?
```

`json_patch()` performs a shallow merge of the JSON objects, so setting a key to `null` in the delta removes it from the stored state.

### State Merging (Read Path)

When reading sessions, the three state tiers are merged into a single dict:

```python
def _merge_state(app_state, user_state, session_state):
    merged_state = copy.deepcopy(session_state)
    for key, value in app_state.items():
        merged_state[State.APP_PREFIX + key] = value  # "app:" prefix restored
    for key, value in user_state.items():
        merged_state[State.USER_PREFIX + key] = value  # "user:" prefix restored
    return merged_state
```

## Thread/Async Safety

### SqliteSessionService

- **No connection pooling**: Each operation creates its own `aiosqlite` connection. This means concurrent async tasks each get their own connection.
- **No per-session locking**: Unlike `DatabaseSessionService`, there are no `asyncio.Lock` guards around `append_event`. Concurrent appends to the same session could race.
- **No row-level locking**: SQLite does not support `SELECT ... FOR UPDATE`.
- **aiosqlite thread safety**: `aiosqlite` runs SQLite operations in a background thread, so the async operations do not block the event loop.
- **Schema idempotency**: `CREATE TABLE IF NOT EXISTS` on every connection is safe for concurrent access.

### Comparison: DatabaseSessionService Safety Features

`DatabaseSessionService` provides additional safety mechanisms not present in `SqliteSessionService`:

- **Per-session `asyncio.Lock`** with reference counting (`_with_session_lock`) serializes `append_event` calls within the same process.
- **Row-level locking** (`SELECT ... FOR UPDATE`) on PostgreSQL/MySQL/MariaDB.
- **Stale session reload**: When a stale timestamp is detected, `DatabaseSessionService` reloads state and events from storage. `SqliteSessionService` raises `ValueError` instead.
- **Connection pooling** via SQLAlchemy's engine pool with `pool_pre_ping=True` for non-SQLite databases.
- **Async context manager** support (`async with` / `close()`) for graceful pool shutdown.

## Usage Examples

### Basic Usage

```python
from google.adk.sessions.sqlite_session_service import SqliteSessionService

# Create service with a file path
session_service = SqliteSessionService(db_path="./agent_sessions.db")

# Create a session with initial state
session = await session_service.create_session(
    app_name="my_agent",
    user_id="user_123",
    state={
        "app:model_version": "v2",      # Stored in app_states
        "user:preference": "dark_mode",  # Stored in user_states
        "context_window": 4096,          # Stored in sessions.state
        "temp:scratch": "ignored",       # Not persisted
    },
)

# Retrieve session with event filtering
from google.adk.sessions.base_session_service import GetSessionConfig

session = await session_service.get_session(
    app_name="my_agent",
    user_id="user_123",
    session_id=session.id,
    config=GetSessionConfig(num_recent_events=10),
)

# List all sessions for a user
response = await session_service.list_sessions(
    app_name="my_agent",
    user_id="user_123",
)
for s in response.sessions:
    print(s.id, s.last_update_time)

# Delete a session (cascades to events)
await session_service.delete_session(
    app_name="my_agent",
    user_id="user_123",
    session_id=session.id,
)
```

### SQLAlchemy-Style URL

```python
# Relative path
service = SqliteSessionService(db_path="sqlite:///./data/sessions.db")

# Absolute path
service = SqliteSessionService(db_path="sqlite:////var/data/sessions.db")

# With query parameters (e.g., read-only mode)
service = SqliteSessionService(db_path="sqlite:///sessions.db?mode=ro")
```

### With Runner

```python
from google.adk.runners import Runner

runner = Runner(
    agent=my_agent,
    app_name="my_app",
    session_service=session_service,
    artifact_service=artifact_service,  # optional
)
```

## Caveats and Limitations

1. **No WAL mode**: The service does not set `PRAGMA journal_mode=WAL`. For concurrent read/write workloads, you may want to subclass and add WAL mode in `_get_db_connection()`.

2. **No busy_timeout**: Without a busy timeout, concurrent writers will get `SQLITE_BUSY` errors immediately rather than retrying. Consider adding `PRAGMA busy_timeout=5000` for production use.

3. **No connection pooling**: Every CRUD operation opens and closes a new connection. For high-throughput scenarios, this adds overhead.

4. **Schema recreation on every connection**: `CREATE TABLE IF NOT EXISTS` runs on each connection open. While idempotent, this is unnecessary overhead after the first call.

5. **No concurrent append protection**: Unlike `DatabaseSessionService`, there is no per-session locking. If multiple async tasks call `append_event` on the same session concurrently, race conditions are possible.

6. **Stale session raises instead of reloading**: `SqliteSessionService` raises `ValueError` on stale sessions, while `DatabaseSessionService` reloads from storage and continues.

7. **Not exported from package `__init__`**: Must import directly from the module path.

8. **Migration requirement**: If upgrading from an older ADK version that used `DatabaseSessionService` with SQLite, a migration step is required before `SqliteSessionService` can open the database.

9. **`json_patch()` dependency**: Relies on SQLite's `json_patch()` function, which is available in SQLite 3.38.0+ (March 2022). Older SQLite builds will fail.

## Comparison: SqliteSessionService vs DatabaseSessionService

| Feature | SqliteSessionService | DatabaseSessionService |
|---------|---------------------|----------------------|
| Backend | `aiosqlite` (raw SQL) | SQLAlchemy async engine |
| Databases | SQLite only | SQLite, PostgreSQL, MySQL, MariaDB |
| Connection pooling | None (new connection per op) | SQLAlchemy pool (`StaticPool` for in-memory SQLite) |
| Per-session locking | None | `asyncio.Lock` with ref counting |
| Row-level locking | N/A | `FOR UPDATE` on PostgreSQL/MySQL/MariaDB |
| Stale session handling | Raises `ValueError` | Reloads from storage |
| State delta writes | `json_patch()` SQL function | Python dict merge (`\|` operator) |
| Schema management | `CREATE TABLE IF NOT EXISTS` per connection | SQLAlchemy `metadata.create_all()` with lock |
| Schema versioning | Column-level check (`event_data`) | `StorageMetadata` table with version key |
| WAL mode | Not configured | Not configured |
| busy_timeout | Not configured | Not configured |
| Context manager | No | Yes (`async with`, `close()`) |
| Package export | Not in `__init__.py` | Lazy import in `__init__.py` |
