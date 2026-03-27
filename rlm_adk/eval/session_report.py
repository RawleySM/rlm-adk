"""Session Assessment Report - Consolidates session telemetry into machine-readable JSON.

Queries all 4 SQLite tables (traces, telemetry, session_state_events, spans)
for a given trace_id and produces a structured JSON report designed for
debugging, performance analysis, documentation, and code review personas.

Usage:
    python -m rlm_adk.eval.session_report --trace-id <trace_id> --db .adk/traces.db
"""

import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional


# ---- Value truncation ----

_MAX_VALUE_LEN = 200


def _trunc(value: Any, max_len: int = _MAX_VALUE_LEN) -> Any:
    """Truncate string/JSON values to max_len chars for compact output."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + f"...[{len(value)} chars]"
    return value


# ---- Agent name -> depth mapping ----

_AGENT_DEPTH_RE = re.compile(r'_d(\d+)(?:f\d+)?$')


def _agent_depth(agent_name: Optional[str]) -> int:
    """Extract depth from agent_name pattern (reasoning_agent=0, child_reasoning_d1f0=1, etc)."""
    if agent_name is None:
        return -1  # unknown
    if agent_name == "reasoning_agent":
        return 0
    m = _AGENT_DEPTH_RE.search(agent_name)
    if m:
        return int(m.group(1))
    return -1


# ---- Percentile helper ----

def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute percentile from a pre-sorted list. Returns 0 if empty."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


# ---- DB query helpers ----

def _query(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Execute SQL and return list of dicts."""
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(sql, params)
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _query_one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Optional[dict[str, Any]]:
    """Execute SQL and return first row as dict, or None."""
    rows = _query(conn, sql, params)
    return rows[0] if rows else None


def _parse_json_value(value: Any, default: Any) -> Any:
    """Parse JSON text into a Python value, returning default on failure."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _has_table(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if a table exists."""
    row = _query_one(
        conn,
        "SELECT COUNT(*) AS cnt FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return bool(row and row["cnt"] > 0)


# ---- Report sections ----

def _build_overview(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]:
    """Build the overview section from the traces table."""
    trace = _query_one(conn, "SELECT * FROM traces WHERE trace_id = ?", (trace_id,))
    if trace is None:
        return {"error": f"trace_id {trace_id} not found"}

    # Compute wall clock from telemetry if traces.end_time is missing
    wall_clock_s = None
    if trace.get("end_time") and trace.get("start_time"):
        wall_clock_s = round(trace["end_time"] - trace["start_time"], 2)
    elif _has_table(conn, "telemetry"):
        # Fallback: span from earliest to latest telemetry timestamp
        bounds = _query_one(
            conn,
            """SELECT MIN(start_time) AS t_min, MAX(COALESCE(end_time, start_time)) AS t_max
               FROM telemetry WHERE trace_id = ?""",
            (trace_id,),
        )
        if bounds and bounds["t_min"] and bounds["t_max"]:
            wall_clock_s = round(bounds["t_max"] - bounds["t_min"], 2)

    # Token totals from telemetry (more reliable than traces table for running traces)
    tok = None
    if _has_table(conn, "telemetry"):
        tok = _query_one(
            conn,
            """SELECT SUM(COALESCE(input_tokens, 0)) AS total_in,
                      SUM(COALESCE(output_tokens, 0)) AS total_out,
                      COUNT(*) AS total_model_calls
               FROM telemetry WHERE trace_id = ? AND event_type = 'model_call'""",
            (trace_id,),
        )

    # Iteration count from SSE
    iter_row = None
    if _has_table(conn, "session_state_events"):
        iter_row = _query_one(
            conn,
            """SELECT MAX(value_int) AS max_iter FROM session_state_events
               WHERE trace_id = ? AND state_key = 'iteration_count' AND key_depth = 0""",
            (trace_id,),
        )

    # Tool call count (guarded)
    tool_count_row = None
    if _has_table(conn, "telemetry"):
        tool_count_row = _query_one(
            conn,
            "SELECT COUNT(*) AS cnt FROM telemetry WHERE trace_id = ? AND event_type = 'tool_call'",
            (trace_id,),
        )

    return {
        "trace_id": trace["trace_id"],
        "session_id": trace["session_id"],
        "status": trace["status"],
        "app_name": trace.get("app_name"),
        "start_time": trace["start_time"],
        "end_time": trace.get("end_time"),
        "wall_clock_s": wall_clock_s,
        "total_input_tokens": tok["total_in"] if tok else 0,
        "total_output_tokens": tok["total_out"] if tok else 0,
        "total_model_calls": tok["total_model_calls"] if tok else 0,
        "total_tool_calls": tool_count_row["cnt"] if tool_count_row else 0,
        "iterations": iter_row["max_iter"] if iter_row and iter_row["max_iter"] is not None else trace.get("iterations", 0),
        "final_answer_length": trace.get("final_answer_length"),
    }


def _depth_key(depth: int) -> str:
    """Convert numeric depth to a display key (depth_unknown for -1)."""
    return "depth_unknown" if depth == -1 else f"depth_{depth}"


def _build_layer_tree(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]:
    """Build hierarchical layer view grouped by depth."""
    if not _has_table(conn, "telemetry"):
        return {}

    rows = _query(
        conn,
        """SELECT agent_name, event_type,
                  COUNT(*) AS cnt,
                  SUM(COALESCE(input_tokens, 0)) AS sum_in,
                  SUM(COALESCE(output_tokens, 0)) AS sum_out,
                  SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count
           FROM telemetry WHERE trace_id = ?
           GROUP BY agent_name, event_type
           ORDER BY agent_name, event_type""",
        (trace_id,),
    )

    layers: dict[int, dict[str, Any]] = {}
    for row in rows:
        depth = _agent_depth(row["agent_name"])
        if depth not in layers:
            layers[depth] = {
                "depth": depth,
                "agents": set(),
                "model_calls": 0,
                "tool_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "error_count": 0,
            }
        layer = layers[depth]
        if row["agent_name"]:
            layer["agents"].add(row["agent_name"])
        if row["event_type"] == "model_call":
            layer["model_calls"] += row["cnt"]
            layer["input_tokens"] += row["sum_in"]
            layer["output_tokens"] += row["sum_out"]
        elif row["event_type"] == "tool_call":
            layer["tool_calls"] += row["cnt"]
        layer["error_count"] += row["error_count"]

    # Convert sets to lists for JSON serialization
    result = {}
    for depth in sorted(layers.keys()):
        layer = layers[depth]
        layer["agents"] = sorted(layer["agents"])
        result[_depth_key(depth)] = layer

    return result


def _build_performance(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]:
    """Build performance section with per-layer latency stats."""
    if not _has_table(conn, "telemetry"):
        return {"model_call_latency_by_layer": {}, "rate_limit_errors": 0, "repl_execution": {}}

    # Per-layer model call latency stats
    model_rows = _query(
        conn,
        """SELECT agent_name, duration_ms
           FROM telemetry
           WHERE trace_id = ? AND event_type = 'model_call' AND duration_ms IS NOT NULL
           ORDER BY agent_name, duration_ms""",
        (trace_id,),
    )

    layer_durations: dict[int, list[float]] = {}
    for row in model_rows:
        depth = _agent_depth(row["agent_name"])
        layer_durations.setdefault(depth, []).append(row["duration_ms"])

    latency_by_layer = {}
    for depth in sorted(layer_durations.keys()):
        vals = sorted(layer_durations[depth])
        latency_by_layer[_depth_key(depth)] = {
            "count": len(vals),
            "min_ms": round(vals[0], 1) if vals else 0,
            "max_ms": round(vals[-1], 1) if vals else 0,
            "avg_ms": round(sum(vals) / len(vals), 1) if vals else 0,
            "p95_ms": round(_percentile(vals, 95), 1),
        }

    # Rate limit impact: error rows with RESOURCE in error_message
    rate_limit = _query_one(
        conn,
        """SELECT COUNT(*) AS cnt
           FROM telemetry
           WHERE trace_id = ? AND status = 'error'
             AND (error_type LIKE '%Resource%' OR error_message LIKE '%RESOURCE%'
                  OR error_type LIKE '%429%' OR error_message LIKE '%429%')""",
        (trace_id,),
    )

    # REPL execution times
    repl_rows = _query(
        conn,
        """SELECT duration_ms FROM telemetry
           WHERE trace_id = ? AND event_type = 'tool_call'
             AND tool_name = 'execute_code' AND duration_ms IS NOT NULL
           ORDER BY duration_ms""",
        (trace_id,),
    )
    repl_durations = [r["duration_ms"] for r in repl_rows]
    repl_stats = {}
    if repl_durations:
        repl_stats = {
            "count": len(repl_durations),
            "min_ms": round(repl_durations[0], 1),
            "max_ms": round(repl_durations[-1], 1),
            "avg_ms": round(sum(repl_durations) / len(repl_durations), 1),
            "p95_ms": round(_percentile(repl_durations, 95), 1),
        }

    return {
        "model_call_latency_by_layer": latency_by_layer,
        "rate_limit_errors": rate_limit["cnt"] if rate_limit else 0,
        "repl_execution": repl_stats,
    }


def _build_errors(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]:
    """Build errors section: telemetry errors + REPL stderr errors."""
    if not _has_table(conn, "telemetry"):
        return {"telemetry_errors": [], "repl_errors": [], "error_propagation_by_depth": {}, "total_error_count": 0}

    # Telemetry errors grouped by agent and error type
    error_rows = _query(
        conn,
        """SELECT agent_name, error_type, COUNT(*) AS cnt,
                  MIN(error_message) AS sample_message
           FROM telemetry
           WHERE trace_id = ? AND status = 'error' AND error_type IS NOT NULL
           GROUP BY agent_name, error_type
           ORDER BY cnt DESC""",
        (trace_id,),
    )

    telemetry_errors = []
    for row in error_rows:
        telemetry_errors.append({
            "agent_name": row["agent_name"],
            "error_type": row["error_type"],
            "count": row["cnt"],
            "sample_message": _trunc(row["sample_message"]),
            "depth": _agent_depth(row["agent_name"]),
        })

    # REPL errors from result_preview (stderr content)
    repl_error_rows = _query(
        conn,
        """SELECT result_preview, agent_name
           FROM telemetry
           WHERE trace_id = ? AND event_type = 'tool_call'
             AND tool_name = 'execute_code' AND repl_has_errors = 1
             AND result_preview IS NOT NULL""",
        (trace_id,),
    )

    repl_errors = []
    for row in repl_error_rows:
        repl_errors.append({
            "agent_name": row["agent_name"],
            "preview": _trunc(row["result_preview"]),
        })

    # Error chain: which depths had errors
    error_by_depth = {}
    for e in telemetry_errors:
        d = e["depth"]
        error_by_depth.setdefault(d, []).append(e["error_type"])

    return {
        "telemetry_errors": telemetry_errors,
        "repl_errors": repl_errors,
        "error_propagation_by_depth": error_by_depth,
        "total_error_count": sum(e["count"] for e in telemetry_errors),
    }


def _build_repl_outcomes(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]:
    """Build REPL outcomes section from tool_call telemetry."""
    if not _has_table(conn, "telemetry"):
        return {"total_executions": 0, "successful": 0, "with_errors": 0,
                "error_pattern_counts": {}, "by_depth": {}, "reasoning_agent_calls": []}

    tool_rows = _query(
        conn,
        """SELECT telemetry_id, agent_name, duration_ms,
                  repl_has_errors, repl_has_output, repl_llm_calls,
                  result_preview
           FROM telemetry
           WHERE trace_id = ? AND event_type = 'tool_call' AND tool_name = 'execute_code'
           ORDER BY start_time""",
        (trace_id,),
    )

    error_patterns: dict[str, int] = {}
    by_depth: dict[int, dict[str, int]] = {}
    reasoning_calls: list[dict[str, Any]] = []

    for row in tool_rows:
        depth = _agent_depth(row["agent_name"])
        if depth not in by_depth:
            by_depth[depth] = {"total": 0, "errors": 0, "with_output": 0, "with_llm_calls": 0}
        stats = by_depth[depth]
        stats["total"] += 1
        if row["repl_has_errors"]:
            stats["errors"] += 1
        if row["repl_has_output"]:
            stats["with_output"] += 1
        if row["repl_llm_calls"] and row["repl_llm_calls"] > 0:
            stats["with_llm_calls"] += 1

        # Only include per-call detail for depth-0 (reasoning agent) to keep output compact
        if depth == 0:
            reasoning_calls.append({
                "has_errors": bool(row["repl_has_errors"]),
                "has_output": bool(row["repl_has_output"]),
                "llm_calls_made": row["repl_llm_calls"] or 0,
                "duration_ms": round(row["duration_ms"], 1) if row["duration_ms"] else None,
            })

        # Extract Python error types from result_preview
        if row["repl_has_errors"] and row["result_preview"]:
            for match in re.finditer(r'(\w*Error|\w*Exception|\w*Warning)\b', row["result_preview"]):
                err_type = match.group(1)
                error_patterns[err_type] = error_patterns.get(err_type, 0) + 1

    total = sum(s["total"] for s in by_depth.values())
    total_errors = sum(s["errors"] for s in by_depth.values())

    return {
        "total_executions": total,
        "successful": total - total_errors,
        "with_errors": total_errors,
        "error_pattern_counts": error_patterns,
        "by_depth": {_depth_key(d): s for d, s in sorted(by_depth.items())},
        "reasoning_agent_calls": reasoning_calls,
    }


def _build_state_timeline(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]:
    """Build state timeline from session_state_events."""
    sse_rows = _query(
        conn,
        """SELECT seq, event_author, event_time, state_key, key_category,
                  key_depth, key_fanout, value_type, value_int, value_float,
                  value_text, value_json
           FROM session_state_events
           WHERE trace_id = ?
           ORDER BY seq""",
        (trace_id,),
    )

    events = []
    by_category: dict[str, list[dict[str, Any]]] = {}

    for row in sse_rows:
        # Resolve value
        value: Any = None
        if row["value_type"] == "int":
            value = row["value_int"]
        elif row["value_type"] == "float":
            value = row["value_float"]
        elif row["value_type"] == "str":
            value = _trunc(row["value_text"])
        elif row["value_type"] in ("dict", "list"):
            try:
                value = json.loads(row["value_json"]) if row["value_json"] else None
            except (json.JSONDecodeError, TypeError):
                value = _trunc(row["value_json"])
        elif row["value_type"] == "bool":
            value = bool(row["value_int"])
        elif row["value_type"] == "null":
            value = None

        # Truncate nested values
        if isinstance(value, (dict, list)):
            s = json.dumps(value)
            if len(s) > _MAX_VALUE_LEN:
                value = _trunc(s)

        entry = {
            "seq": row["seq"],
            "time": row["event_time"],
            "author": row["event_author"],
            "key": row["state_key"],
            "category": row["key_category"],
            "depth": row["key_depth"],
            "fanout": row["key_fanout"],
            "value": value,
        }
        events.append(entry)
        by_category.setdefault(row["key_category"], []).append(entry)

    return {
        "total_events": len(events),
        "categories": {cat: len(evts) for cat, evts in sorted(by_category.items())},
        "events": events,
    }


def _normalize_child_summary(
    row: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Flatten a persisted obs:child_summary payload for evaluator consumption."""
    structured_output = summary.get("structured_output", {})
    if not isinstance(structured_output, dict):
        structured_output = {}

    nested_dispatch = summary.get("nested_dispatch", {})
    if not isinstance(nested_dispatch, dict):
        nested_dispatch = {}

    return {
        "depth": row["key_depth"],
        "fanout": row["key_fanout"],
        "seq": row["seq"],
        "author": row["event_author"],
        "model": summary.get("model"),
        "elapsed_ms": summary.get("elapsed_ms"),
        "error": summary.get("error"),
        "error_category": summary.get("error_category"),
        "error_message": _trunc(summary.get("error_message")),
        "prompt_preview": _trunc(summary.get("prompt_preview")),
        "result_preview": _trunc(summary.get("result_preview")),
        "final_answer": _trunc(summary.get("final_answer")),
        "structured_output": {
            "expected": structured_output.get("expected", False),
            "schema_name": structured_output.get("schema_name"),
            "attempts": structured_output.get("attempts", 0),
            "retry_count": structured_output.get("retry_count", 0),
            "outcome": structured_output.get("outcome"),
            "validated_result": structured_output.get("validated_result"),
        },
        "nested_dispatch": {
            "count": nested_dispatch.get("count", 0),
            "batch_dispatches": nested_dispatch.get("batch_dispatches", 0),
            "error_counts": nested_dispatch.get("error_counts", {}),
            "structured_output_failures": nested_dispatch.get(
                "structured_output_failures",
                0,
            ),
        },
    }


def _build_child_outcomes(conn: sqlite3.Connection, trace_id: str) -> dict[str, Any]:
    """Build evaluator-facing child summary/error/structured-output outcomes."""
    trace = _query_one(conn, "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)) or {}
    child_error_counts = _parse_json_value(trace.get("child_error_counts"), {})
    if not isinstance(child_error_counts, dict):
        child_error_counts = {}

    latest_summaries: dict[tuple[int, int | None], dict[str, Any]] = {}
    if _has_table(conn, "session_state_events"):
        rows = _query(
            conn,
            """SELECT seq, event_author, event_time, key_depth, key_fanout,
                      value_type, value_json, value_text
               FROM session_state_events
               WHERE trace_id = ? AND state_key = 'obs:child_summary'
               ORDER BY seq""",
            (trace_id,),
        )
        for row in rows:
            summary = None
            if row["value_type"] == "dict" and row["value_json"]:
                summary = _parse_json_value(row["value_json"], None)
            elif row["value_type"] == "str" and row["value_text"]:
                summary = _parse_json_value(row["value_text"], None)
            if not isinstance(summary, dict):
                continue
            latest_summaries[(row["key_depth"], row["key_fanout"])] = _normalize_child_summary(
                row,
                summary,
            )

    summaries = sorted(
        latest_summaries.values(),
        key=lambda item: (item["depth"], item["fanout"] if item["fanout"] is not None else -1),
    )

    structured_output_outcomes: dict[str, int] = {}
    child_error_categories: dict[str, int] = {}
    for summary in summaries:
        outcome = summary["structured_output"].get("outcome")
        if outcome:
            structured_output_outcomes[outcome] = structured_output_outcomes.get(outcome, 0) + 1
        error_category = summary.get("error_category")
        if error_category:
            child_error_categories[error_category] = child_error_categories.get(error_category, 0) + 1

    return {
        "child_dispatch_count": trace.get("child_dispatch_count", 0) or 0,
        "child_total_batch_dispatches": trace.get("child_total_batch_dispatches", 0) or 0,
        "child_error_counts": child_error_counts,
        "structured_output_failures": trace.get("structured_output_failures", 0) or 0,
        "structured_output_outcomes": structured_output_outcomes,
        "child_error_categories": child_error_categories,
        "total_summaries": len(summaries),
        "children_with_errors": sum(1 for summary in summaries if summary.get("error")),
        "summaries": summaries,
    }


# ---- Main report builder ----

def build_session_report(trace_id: str, db_path: str = ".adk/traces.db") -> dict[str, Any]:
    """Build a complete session assessment report for a trace.

    Args:
        trace_id: The trace identifier to report on.
        db_path: Path to the SQLite traces database.

    Returns:
        Structured dict with sections: overview, layer_tree, performance,
        errors, repl_outcomes, state_timeline.

    Raises:
        FileNotFoundError: If db_path does not exist.
        sqlite3.Error: If the database cannot be opened.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_file))
    try:
        report: dict[str, Any] = {}
        report["overview"] = _build_overview(conn, trace_id)

        if report["overview"].get("error"):
            return report

        report["layer_tree"] = _build_layer_tree(conn, trace_id)
        report["performance"] = _build_performance(conn, trace_id)
        report["errors"] = _build_errors(conn, trace_id)
        report["repl_outcomes"] = _build_repl_outcomes(conn, trace_id)
        report["child_outcomes"] = _build_child_outcomes(conn, trace_id)

        if _has_table(conn, "session_state_events"):
            report["state_timeline"] = _build_state_timeline(conn, trace_id)
        else:
            report["state_timeline"] = {"error": "session_state_events table not found"}

        return report
    finally:
        conn.close()


# ---- CLI ----

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a session assessment report from SQLite telemetry.",
    )
    parser.add_argument(
        "--trace-id", required=True,
        help="The trace_id to generate a report for.",
    )
    parser.add_argument(
        "--db", default=".adk/traces.db",
        help="Path to the SQLite traces database (default: .adk/traces.db).",
    )
    args = parser.parse_args()

    try:
        report = build_session_report(args.trace_id, args.db)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except sqlite3.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
        sys.exit(1)

    json.dump(report, sys.stdout, indent=2, default=str)
    print()  # trailing newline


if __name__ == "__main__":
    main()
