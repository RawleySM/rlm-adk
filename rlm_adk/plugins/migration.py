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

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from google.adk.agents.invocation_context import InvocationContext
from google.adk.plugins.base_plugin import BasePlugin

from rlm_adk.state import (
    MIGRATION_ERROR,
    MIGRATION_STATUS,
    MIGRATION_TIMESTAMP,
)

logger = logging.getLogger(__name__)


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
    4. Mark session as migrated in state
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
        self._sqlite_path = sqlite_db_path or os.getenv(
            "RLM_SESSION_DB", ".adk/session.db"
        )
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
            (
                self._postgres_url.split("@")[-1]
                if "@" in self._postgres_url
                else "(url)"
            ),
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

        create_sql = text(
            """
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
        """
        )

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
                session_id,
                len(events_data),
                elapsed,
            )

            # Prune old migrated sessions from SQLite
            if self._retention > 0:
                pruned = self._prune_local_sessions(app_name, self._retention)
                if pruned > 0:
                    logger.info(
                        "MigrationPlugin: pruned %d old sessions from SQLite",
                        pruned,
                    )

        except Exception as e:
            logger.error(
                "MigrationPlugin: migration failed for session %s: %s",
                session_id,
                e,
            )
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
                text(
                    """
                    INSERT INTO sessions (app_name, user_id, id, state, create_time, update_time, migrated_at)
                    VALUES (:app_name, :user_id, :id, :state::jsonb, :create_time, :update_time, :migrated_at)
                    ON CONFLICT (app_name, user_id, id) DO UPDATE SET
                        state = EXCLUDED.state,
                        update_time = EXCLUDED.update_time,
                        migrated_at = EXCLUDED.migrated_at
                """
                ),
                {
                    **session_data,
                    "migrated_at": time.time(),
                },
            )

            # Batch insert events
            if events_data:
                await conn.execute(
                    text(
                        """
                        INSERT INTO events (id, app_name, user_id, session_id, invocation_id, timestamp, event_data)
                        VALUES (:id, :app_name, :user_id, :session_id, :invocation_id, :timestamp, :event_data::jsonb)
                        ON CONFLICT (app_name, user_id, session_id, id) DO NOTHING
                    """
                    ),
                    events_data,
                )

    def _prune_local_sessions(self, app_name: str, retention: int) -> int:
        """Remove oldest sessions from SQLite, keeping ``retention`` most recent.

        Prunes any sessions beyond the retention count for the given app,
        ordered by ``update_time`` ascending (oldest first). Associated events
        are cascade-deleted via foreign key constraints.

        Returns:
            Number of sessions deleted.
        """
        if not Path(self._sqlite_path).exists():
            return 0

        conn = sqlite3.connect(self._sqlite_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            # Count total sessions for the app
            total = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE app_name=?",
                (app_name,),
            ).fetchone()[0]

            if total <= retention:
                return 0

            # Delete oldest sessions beyond retention limit
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
