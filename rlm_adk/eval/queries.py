"""Evaluation query functions for comparing and analyzing session traces.

All functions operate through a TraceReader instance and return structured
dataclass instances suitable for programmatic consumption by evaluation agents.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

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
            app_name,
            user_id,
            session_id,
            invocation_id=inv_id,
        )
        if not events:
            continue

        state_deltas: list[dict[str, Any]] = []
        authors: list[str] = []
        token_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

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
                token_usage["output_tokens"] += (
                    usage.get("candidates_token_count", 0) or 0
                )

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

    divergences: list[DivergencePoint] = []
    min_len = min(len(traces_a), len(traces_b))

    for idx in range(min_len):
        ta = traces_a[idx]
        tb = traces_b[idx]

        # Check author sequence divergence
        if ta.author_sequence != tb.author_sequence:
            divergences.append(
                DivergencePoint(
                    invocation_index=idx,
                    invocation_id_a=ta.invocation_id,
                    invocation_id_b=tb.invocation_id,
                    reason="author_sequence_mismatch",
                    details={
                        "authors_a": ta.author_sequence,
                        "authors_b": tb.author_sequence,
                    },
                )
            )
            continue

        # Check state delta key divergence
        keys_a: set[str] = set()
        for sd in ta.state_deltas:
            keys_a.update(sd.keys())
        keys_b: set[str] = set()
        for sd in tb.state_deltas:
            keys_b.update(sd.keys())

        if keys_a != keys_b:
            divergences.append(
                DivergencePoint(
                    invocation_index=idx,
                    invocation_id_a=ta.invocation_id,
                    invocation_id_b=tb.invocation_id,
                    reason="state_delta_keys_mismatch",
                    details={
                        "only_in_a": sorted(keys_a - keys_b),
                        "only_in_b": sorted(keys_b - keys_a),
                    },
                )
            )

    # Length mismatch
    if len(traces_a) != len(traces_b):
        divergences.append(
            DivergencePoint(
                invocation_index=min_len,
                invocation_id_a=(
                    traces_a[min_len].invocation_id if min_len < len(traces_a) else "N/A"
                ),
                invocation_id_b=(
                    traces_b[min_len].invocation_id if min_len < len(traces_b) else "N/A"
                ),
                reason="invocation_count_mismatch",
                details={
                    "count_a": len(traces_a),
                    "count_b": len(traces_b),
                },
            )
        )

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
    total_tokens_a = sum(
        t.token_usage.get("input_tokens", 0) + t.token_usage.get("output_tokens", 0)
        for t in traces_a
    )
    total_tokens_b = sum(
        t.token_usage.get("input_tokens", 0) + t.token_usage.get("output_tokens", 0)
        for t in traces_b
    )

    duration_a = (
        (traces_a[-1].timestamp_end - traces_a[0].timestamp_start) if traces_a else 0.0
    )
    duration_b = (
        (traces_b[-1].timestamp_end - traces_b[0].timestamp_start) if traces_b else 0.0
    )

    summary = {
        "invocations_a": len(traces_a),
        "invocations_b": len(traces_b),
        "total_tokens_a": total_tokens_a,
        "total_tokens_b": total_tokens_b,
        "duration_a": round(duration_a, 3),
        "duration_b": round(duration_b, 3),
        "divergence_count": len(divergences),
        "first_divergence_index": (
            divergences[0].invocation_index if divergences else None
        ),
    }

    return SessionComparison(
        session_id_a=session_id_a,
        session_id_b=session_id_b,
        traces_a=traces_a,
        traces_b=traces_b,
        divergence_points=divergences,
        summary=summary,
    )
