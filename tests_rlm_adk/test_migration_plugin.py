"""Tests for MigrationPlugin (Rec 9).

TDD: RED phase - defines expected behavior of MigrationPlugin.
PostgreSQL is mocked; SQLite operations tested against real temp files.
"""

import json
import os
import sqlite3
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
        PRAGMA foreign_keys = ON;
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
            (app_name, user_id, session_id, state, now + s, now + s),
        )
        for e in range(events_per_session):
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


# --- RED Tests ---


def test_migration_plugin_disabled_when_no_postgres_url(monkeypatch):
    """Plugin is disabled when RLM_POSTGRES_URL is not set."""
    monkeypatch.delenv("RLM_POSTGRES_URL", raising=False)
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin()
    assert plugin._enabled is False


def test_migration_plugin_enabled_with_postgres_url(monkeypatch):
    """Plugin is enabled when RLM_POSTGRES_URL is set."""
    monkeypatch.setenv("RLM_POSTGRES_URL", "postgresql+asyncpg://user:pass@localhost/db")
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin()
    assert plugin._enabled is True


def test_migration_plugin_accepts_explicit_postgres_url(monkeypatch):
    """Plugin accepts explicit postgres_url parameter."""
    monkeypatch.delenv("RLM_POSTGRES_URL", raising=False)
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin(postgres_url="postgresql+asyncpg://user:pass@localhost/db")
    assert plugin._enabled is True


def test_migration_plugin_name():
    """Plugin has default name 'migration'."""
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin()
    assert plugin.name == "migration"


def test_migration_plugin_custom_name():
    """Plugin accepts custom name."""
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin(name="custom_migration")
    assert plugin.name == "custom_migration"


@pytest.mark.asyncio
async def test_migration_plugin_after_run_noop_when_disabled(monkeypatch):
    """after_run_callback is a no-op when plugin is disabled."""
    monkeypatch.delenv("RLM_POSTGRES_URL", raising=False)
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin()
    mock_ctx = MagicMock()
    # Should not raise or do anything
    await plugin.after_run_callback(invocation_context=mock_ctx)


def test_migration_plugin_reads_from_sqlite(tmp_path):
    """_read_session_from_sqlite returns session and events."""
    from rlm_adk.plugins.migration import MigrationPlugin

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
    )
    session, events = plugin._read_session_from_sqlite("test_app", "user_1", "session_1")
    assert session is not None
    assert len(events) > 0


def test_migration_plugin_returns_none_for_missing_session(tmp_path):
    """_read_session_from_sqlite returns (None, []) for non-existent session."""
    from rlm_adk.plugins.migration import MigrationPlugin

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path)
    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
    )
    session, events = plugin._read_session_from_sqlite("test_app", "user_1", "nonexistent")
    assert session is None
    assert events == []


def test_migration_plugin_returns_none_for_missing_db(tmp_path):
    """_read_session_from_sqlite returns (None, []) when SQLite file does not exist."""
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=str(tmp_path / "nonexistent.db"),
    )
    session, events = plugin._read_session_from_sqlite("test_app", "user_1", "session_1")
    assert session is None
    assert events == []


def test_migration_plugin_prune_sessions(tmp_path):
    """_prune_local_sessions removes oldest sessions beyond retention."""
    from rlm_adk.plugins.migration import MigrationPlugin

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=10)
    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
        retention_count=3,
    )
    pruned = plugin._prune_local_sessions("test_app", 3)
    assert pruned == 7

    # Verify only 3 sessions remain
    conn = sqlite3.connect(db_path)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE app_name='test_app'"
    ).fetchone()[0]
    assert remaining == 3

    # Verify events for pruned sessions were cascade-deleted
    orphaned = conn.execute(
        """SELECT COUNT(*) FROM events e
           WHERE e.app_name='test_app'
             AND NOT EXISTS (
               SELECT 1 FROM sessions s
               WHERE s.app_name = e.app_name
                 AND s.user_id = e.user_id
                 AND s.id = e.session_id
             )"""
    ).fetchone()[0]
    conn.close()
    assert orphaned == 0, f"Found {orphaned} orphaned event rows after pruning"


def test_migration_plugin_prune_no_op_under_retention(tmp_path):
    """_prune_local_sessions is a no-op when total is within retention."""
    from rlm_adk.plugins.migration import MigrationPlugin

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=2)
    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
        retention_count=10,
    )
    pruned = plugin._prune_local_sessions("test_app", 10)
    assert pruned == 0


def test_migration_plugin_prune_missing_db(tmp_path):
    """_prune_local_sessions returns 0 when SQLite file does not exist."""
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=str(tmp_path / "nonexistent.db"),
        retention_count=3,
    )
    pruned = plugin._prune_local_sessions("test_app", 3)
    assert pruned == 0


def test_migration_plugin_retention_from_env(monkeypatch):
    """retention_count defaults from RLM_MIGRATION_RETENTION env var."""
    monkeypatch.setenv("RLM_MIGRATION_RETENTION", "25")
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin(postgres_url="postgresql+asyncpg://fake")
    assert plugin._retention == 25


def test_migration_plugin_retention_default(monkeypatch):
    """retention_count defaults to 50 when env var is not set."""
    monkeypatch.delenv("RLM_MIGRATION_RETENTION", raising=False)
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin(postgres_url="postgresql+asyncpg://fake")
    assert plugin._retention == 50


def test_migration_plugin_sqlite_path_from_env(monkeypatch):
    """sqlite_db_path defaults from RLM_SESSION_DB env var."""
    monkeypatch.setenv("RLM_SESSION_DB", "/tmp/custom.db")
    from rlm_adk.plugins.migration import MigrationPlugin

    plugin = MigrationPlugin(postgres_url="postgresql+asyncpg://fake")
    assert plugin._sqlite_path == "/tmp/custom.db"


@pytest.mark.asyncio
async def test_migration_plugin_after_run_skips_missing_session(tmp_path):
    """after_run_callback skips gracefully when session is not in SQLite."""
    from rlm_adk.plugins.migration import MigrationPlugin

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=0)
    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
    )
    # Mock the engine creation to avoid actual Postgres connection
    plugin._enabled = True
    plugin._engine = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.session.id = "nonexistent"
    mock_ctx.session.user_id = "user_1"
    mock_ctx.session.state = {}
    mock_ctx.app_name = "test_app"

    # Mock _get_engine to return the mock engine
    plugin._get_engine = AsyncMock(return_value=plugin._engine)

    # Should not raise
    await plugin.after_run_callback(invocation_context=mock_ctx)


@pytest.mark.asyncio
async def test_migration_plugin_after_run_success_path(tmp_path):
    """after_run_callback reads from SQLite, calls _upsert_to_postgres, and sets MIGRATION_STATUS."""
    from rlm_adk.plugins.migration import MigrationPlugin
    from rlm_adk.state import MIGRATION_STATUS, MIGRATION_TIMESTAMP

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=1, events_per_session=3)

    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
        retention_count=0,  # disable pruning for this test
    )
    plugin._enabled = True

    # Mock _get_engine and _upsert_to_postgres to avoid real Postgres
    mock_engine = MagicMock()
    plugin._get_engine = AsyncMock(return_value=mock_engine)
    plugin._upsert_to_postgres = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.session.id = "session_1"
    mock_ctx.session.user_id = "user_1"
    mock_ctx.session.state = {}
    mock_ctx.app_name = "test_app"

    await plugin.after_run_callback(invocation_context=mock_ctx)

    # Verify _upsert_to_postgres was called with session data and events
    plugin._upsert_to_postgres.assert_awaited_once()
    args = plugin._upsert_to_postgres.call_args
    session_data, events_data = args[0]
    assert session_data["id"] == "session_1"
    assert len(events_data) == 3

    # Verify migration state was set
    assert mock_ctx.session.state[MIGRATION_STATUS] == "completed"
    assert MIGRATION_TIMESTAMP in mock_ctx.session.state


@pytest.mark.asyncio
async def test_migration_plugin_after_run_sets_failed_on_error(tmp_path):
    """after_run_callback sets MIGRATION_STATUS='failed' when upsert raises."""
    from rlm_adk.plugins.migration import MigrationPlugin
    from rlm_adk.state import MIGRATION_ERROR, MIGRATION_STATUS

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=1, events_per_session=1)

    plugin = MigrationPlugin(
        postgres_url="postgresql+asyncpg://fake",
        sqlite_db_path=db_path,
        retention_count=0,
    )
    plugin._enabled = True

    mock_engine = MagicMock()
    plugin._get_engine = AsyncMock(return_value=mock_engine)
    plugin._upsert_to_postgres = AsyncMock(side_effect=RuntimeError("pg down"))

    mock_ctx = MagicMock()
    mock_ctx.session.id = "session_1"
    mock_ctx.session.user_id = "user_1"
    mock_ctx.session.state = {}
    mock_ctx.app_name = "test_app"

    await plugin.after_run_callback(invocation_context=mock_ctx)

    assert mock_ctx.session.state[MIGRATION_STATUS] == "failed"
    assert "pg down" in mock_ctx.session.state[MIGRATION_ERROR]


@pytest.mark.skipif(
    not os.getenv("RLM_POSTGRES_URL"),
    reason="Requires RLM_POSTGRES_URL for integration test",
)
@pytest.mark.asyncio
async def test_migration_plugin_full_migration(tmp_path):
    """Full end-to-end migration from SQLite to Postgres (integration)."""
    from rlm_adk.plugins.migration import MigrationPlugin, MIGRATION_STATUS

    db_path = str(tmp_path / "test.db")
    _create_test_db(db_path, sessions=1, events_per_session=5)
    plugin = MigrationPlugin(
        postgres_url=os.getenv("RLM_POSTGRES_URL"),
        sqlite_db_path=db_path,
    )
    mock_ctx = MagicMock()
    mock_ctx.session.id = "session_1"
    mock_ctx.session.user_id = "user_1"
    mock_ctx.session.state = {}
    mock_ctx.app_name = "test_app"

    await plugin.after_run_callback(invocation_context=mock_ctx)

    assert mock_ctx.session.state.get(MIGRATION_STATUS) == "completed"
    await plugin.close()
