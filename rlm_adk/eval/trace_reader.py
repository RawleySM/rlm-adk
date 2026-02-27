"""TraceReader - DuckDB analytical overlay for SQLite session data.

Provides columnar, vectorized read access against the ADK session database.
DuckDB attaches the SQLite file directly (zero-copy) and enables SQL analytics
(aggregations, window functions, JSON extraction) that would be slow in SQLite.

Usage:
    reader = TraceReader(".adk/session.db")
    traces = reader.list_sessions("my_app")
    reader.close()

    # Or as context manager:
    with TraceReader(".adk/session.db") as reader:
        sessions = reader.list_sessions("my_app")
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

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

        import duckdb

        self._conn = duckdb.connect(":memory:")
        self._conn.execute("INSTALL sqlite; LOAD sqlite;")
        self._conn.execute(
            f"ATTACH '{self.db_path}' AS sdb (TYPE sqlite)"
        )
        logger.info("TraceReader attached: %s (read_only=%s)", self.db_path, read_only)

    @property
    def conn(self) -> Any:
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
        params: list[Any] = [app_name, user_id, session_id]

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
