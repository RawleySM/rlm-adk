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

    def __exit__(self, *_exc: object) -> None:
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
        if self._conn is None:
            raise RuntimeError("TraceReader is closed")
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

    # ------------------------------------------------------------------
    # Helper: table existence check (for graceful degradation)
    # ------------------------------------------------------------------

    def _has_table(self, table_name: str) -> bool:
        """Check if a table exists in the attached SQLite schema."""
        try:
            rows = self.execute(
                "SELECT COUNT(*) AS cnt FROM duckdb_tables() "
                "WHERE database_name = 'sdb' AND table_name = $1",
                [table_name],
            )
            return rows[0]["cnt"] > 0
        except Exception:
            return False

    # ------------------------------------------------------------------
    # traces table methods
    # ------------------------------------------------------------------

    def list_traces(
        self,
        limit: Optional[int] = None,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List traces ordered by start_time DESC.

        Args:
            limit: Optional maximum number of traces to return.
            status: Optional status filter ('running', 'completed', etc.).

        Returns:
            List of trace dicts, or empty list if traces table is absent.
        """
        if not self._has_table("traces"):
            return []

        conditions: list[str] = []
        params: list[Any] = []

        if status:
            conditions.append(f"status = ${len(params) + 1}")
            params.append(status)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit_clause = f"LIMIT {limit}" if limit else ""

        sql = f"""
            SELECT * FROM sdb.traces
            {where}
            ORDER BY start_time DESC
            {limit_clause}
        """
        return self.execute(sql, params)

    def get_trace(self, trace_id: str) -> Optional[dict[str, Any]]:
        """Return a single trace dict by trace_id, or None.

        Args:
            trace_id: The trace identifier.

        Returns:
            Trace dict or None if not found.
        """
        if not self._has_table("traces"):
            return None

        sql = "SELECT * FROM sdb.traces WHERE trace_id = $1"
        rows = self.execute(sql, [trace_id])
        return rows[0] if rows else None

    def get_trace_summary(self, trace_id: str) -> Optional[dict[str, Any]]:
        """Return key metrics for a trace.

        Args:
            trace_id: The trace identifier.

        Returns:
            Dict with keys: trace_id, status, total_input_tokens,
            total_output_tokens, total_calls, iterations, duration_s,
            child_dispatch_count, structured_output_failures.
            Returns None if trace not found.
        """
        if not self._has_table("traces"):
            return None

        sql = """
            SELECT
                trace_id, status,
                total_input_tokens, total_output_tokens,
                total_calls, iterations,
                CASE WHEN end_time IS NOT NULL AND start_time IS NOT NULL
                     THEN end_time - start_time
                     ELSE NULL
                END AS duration_s,
                child_dispatch_count,
                structured_output_failures
            FROM sdb.traces
            WHERE trace_id = $1
        """
        rows = self.execute(sql, [trace_id])
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # telemetry table methods
    # ------------------------------------------------------------------

    def get_telemetry(
        self,
        trace_id: str,
        event_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return telemetry rows for a trace.

        Args:
            trace_id: The trace identifier.
            event_type: Optional filter ('model_call' or 'tool_call').

        Returns:
            List of telemetry dicts ordered by start_time,
            or empty list if telemetry table is absent.
        """
        if not self._has_table("telemetry"):
            return []

        conditions = ["trace_id = $1"]
        params: list[Any] = [trace_id]

        if event_type:
            conditions.append(f"event_type = ${len(params) + 1}")
            params.append(event_type)

        where = " AND ".join(conditions)
        sql = f"""
            SELECT * FROM sdb.telemetry
            WHERE {where}
            ORDER BY start_time
        """
        return self.execute(sql, params)

    def get_model_calls(self, trace_id: str) -> list[dict[str, Any]]:
        """Shorthand for get_telemetry filtered to model_call.

        Args:
            trace_id: The trace identifier.

        Returns:
            List of model_call telemetry dicts.
        """
        return self.get_telemetry(trace_id, event_type="model_call")

    def get_tool_calls(self, trace_id: str) -> list[dict[str, Any]]:
        """Shorthand for get_telemetry filtered to tool_call.

        Args:
            trace_id: The trace identifier.

        Returns:
            List of tool_call telemetry dicts.
        """
        return self.get_telemetry(trace_id, event_type="tool_call")

    def get_token_usage(self, trace_id: str) -> dict[str, Any]:
        """Return token usage totals and per-model breakdown from telemetry.

        Args:
            trace_id: The trace identifier.

        Returns:
            Dict with keys: total_input_tokens, total_output_tokens, per_model.
            per_model maps model name to {input_tokens, output_tokens, calls}.
        """
        if not self._has_table("telemetry"):
            return {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "per_model": {},
            }

        sql = """
            SELECT
                model,
                SUM(COALESCE(input_tokens, 0)) AS input_tokens,
                SUM(COALESCE(output_tokens, 0)) AS output_tokens,
                COUNT(*) AS calls
            FROM sdb.telemetry
            WHERE trace_id = $1 AND event_type = 'model_call'
            GROUP BY model
        """
        rows = self.execute(sql, [trace_id])

        total_in = 0
        total_out = 0
        per_model: dict[str, dict[str, int]] = {}
        for row in rows:
            model = row["model"] or "unknown"
            in_tok = row["input_tokens"]
            out_tok = row["output_tokens"]
            total_in += in_tok
            total_out += out_tok
            per_model[model] = {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "calls": row["calls"],
            }

        return {
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "per_model": per_model,
        }

    def get_iteration_timeline(self, trace_id: str) -> list[dict[str, Any]]:
        """Return per-iteration timing and token counts from telemetry.

        Args:
            trace_id: The trace identifier.

        Returns:
            List of dicts per iteration with keys: iteration,
            total_input_tokens, total_output_tokens, model_calls,
            tool_calls, total_duration_ms.
        """
        if not self._has_table("telemetry"):
            return []

        sql = """
            SELECT
                iteration,
                SUM(CASE WHEN event_type = 'model_call'
                         THEN COALESCE(input_tokens, 0) ELSE 0 END) AS total_input_tokens,
                SUM(CASE WHEN event_type = 'model_call'
                         THEN COALESCE(output_tokens, 0) ELSE 0 END) AS total_output_tokens,
                SUM(CASE WHEN event_type = 'model_call' THEN 1 ELSE 0 END) AS model_calls,
                SUM(CASE WHEN event_type = 'tool_call' THEN 1 ELSE 0 END) AS tool_calls,
                SUM(COALESCE(duration_ms, 0)) AS total_duration_ms
            FROM sdb.telemetry
            WHERE trace_id = $1 AND iteration IS NOT NULL
            GROUP BY iteration
            ORDER BY iteration
        """
        return self.execute(sql, [trace_id])

    # ------------------------------------------------------------------
    # session_state_events table methods
    # ------------------------------------------------------------------

    def get_state_events(
        self,
        trace_id: str,
        key_category: Optional[str] = None,
        state_key: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Return session state event rows for a trace.

        Args:
            trace_id: The trace identifier.
            key_category: Optional filter by key_category.
            state_key: Optional filter by exact state_key.

        Returns:
            List of state event dicts ordered by seq,
            or empty list if session_state_events table is absent.
        """
        if not self._has_table("session_state_events"):
            return []

        conditions = ["trace_id = $1"]
        params: list[Any] = [trace_id]

        if key_category:
            conditions.append(f"key_category = ${len(params) + 1}")
            params.append(key_category)
        if state_key:
            conditions.append(f"state_key = ${len(params) + 1}")
            params.append(state_key)

        where = " AND ".join(conditions)
        sql = f"""
            SELECT * FROM sdb.session_state_events
            WHERE {where}
            ORDER BY seq
        """
        return self.execute(sql, params)

    def get_state_key_history(
        self,
        trace_id: str,
        state_key: str,
    ) -> list[dict[str, Any]]:
        """Return ordered value changes for a specific state key.

        Args:
            trace_id: The trace identifier.
            state_key: The state key to track.

        Returns:
            List of state event dicts for that key, ordered by seq.
        """
        return self.get_state_events(trace_id, state_key=state_key)

    def get_error_summary(self, trace_id: str) -> dict[str, Any]:
        """Return error summary from telemetry and state events.

        Args:
            trace_id: The trace identifier.

        Returns:
            Dict with keys: telemetry_errors (count), error_types (list),
            worker_error_counts (dict or None).
        """
        # Telemetry errors
        telemetry_errors = 0
        error_types: list[str] = []
        if self._has_table("telemetry"):
            sql = """
                SELECT error_type, COUNT(*) AS cnt
                FROM sdb.telemetry
                WHERE trace_id = $1 AND status = 'error' AND error_type IS NOT NULL
                GROUP BY error_type
            """
            rows = self.execute(sql, [trace_id])
            for row in rows:
                telemetry_errors += row["cnt"]
                error_types.append(row["error_type"])

        # Worker error counts from SSE
        worker_error_counts: Optional[dict] = None
        if self._has_table("session_state_events"):
            sql = """
                SELECT value_json
                FROM sdb.session_state_events
                WHERE trace_id = $1 AND state_key = 'obs:worker_error_counts'
                ORDER BY seq DESC
                LIMIT 1
            """
            rows = self.execute(sql, [trace_id])
            if rows and rows[0]["value_json"]:
                try:
                    worker_error_counts = json.loads(rows[0]["value_json"])
                except (json.JSONDecodeError, TypeError):
                    pass

        return {
            "telemetry_errors": telemetry_errors,
            "error_types": error_types,
            "worker_error_counts": worker_error_counts,
        }
