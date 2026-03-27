"""RED test: event_reader.read_events must filter by session_id.

Without session filtering, read_events reads ALL events from the JSONL file
across ALL sessions.  build_tree groups by agent_name, so all sessions'
reasoning_agent events merge — 12 sessions × 5 root calls = 60 steps
displayed as ``reasoning_agent i60`` instead of ``i5``.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from rlm_adk.dashboard.event_reader import build_tree, read_events

pytestmark = [pytest.mark.unit_nondefault]

# ── Helpers ──────────────────────────────────────────────────────────


def _make_event(
    *,
    session_id: str,
    event_id: str,
    phase: str = "model",
    agent_name: str = "reasoning_agent",
    depth: int = 0,
    model_event_id: str | None = None,
    tool_name: str | None = None,
) -> dict:
    return {
        "session_id": session_id,
        "event_id": event_id,
        "phase": phase,
        "agent_name": agent_name,
        "depth": depth,
        "model_event_id": model_event_id,
        "tool_name": tool_name,
        "invocation_id": f"inv-{session_id[:8]}",
    }


def _write_multi_session_jsonl(path: Path, n_sessions: int = 3, root_calls: int = 5) -> list[str]:
    """Write a JSONL with n_sessions each producing root_calls model+tool pairs.

    Returns the list of session_ids.
    """
    session_ids = [f"session-{i:04d}" for i in range(n_sessions)]
    with path.open("w") as f:
        for sid in session_ids:
            for call in range(root_calls):
                model_eid = f"{sid}-model-{call}"
                tool_eid = f"{sid}-tool-{call}"
                f.write(json.dumps(_make_event(
                    session_id=sid, event_id=model_eid, phase="model",
                )) + "\n")
                f.write(json.dumps(_make_event(
                    session_id=sid, event_id=tool_eid, phase="tool",
                    model_event_id=model_eid, tool_name="execute_code",
                )) + "\n")
    return session_ids


# ── Tests ────────────────────────────────────────────────────────────


class TestReadEventsSessionFilter:
    """read_events must support session_id filtering."""

    def test_unfiltered_returns_all_sessions(self, tmp_path):
        """Without session_id, read_events returns everything (baseline)."""
        jsonl = tmp_path / "events.jsonl"
        sids = _write_multi_session_jsonl(jsonl, n_sessions=3, root_calls=5)
        events = read_events(jsonl)
        assert len(events) == 30  # 3 sessions × 5 calls × 2 events (model+tool)

    def test_filtered_returns_single_session(self, tmp_path):
        """With session_id, read_events returns only that session's events."""
        jsonl = tmp_path / "events.jsonl"
        sids = _write_multi_session_jsonl(jsonl, n_sessions=3, root_calls=5)
        events = read_events(jsonl, session_id=sids[1])
        assert len(events) == 10  # 1 session × 5 calls × 2 events
        assert all(e.session_id == sids[1] for e in events)


class TestBuildTreeSessionIsolation:
    """build_tree must produce correct step counts when given filtered events."""

    def test_unfiltered_tree_merges_sessions(self, tmp_path):
        """Without filtering, reasoning_agent steps == n_sessions × root_calls (the bug)."""
        jsonl = tmp_path / "events.jsonl"
        _write_multi_session_jsonl(jsonl, n_sessions=3, root_calls=5)
        all_events = read_events(jsonl)
        tree = build_tree(all_events)
        root_steps = tree.steps.get("reasoning_agent", [])
        # BUG: 3 sessions × 5 = 15 steps — this is the broken behavior
        assert len(root_steps) == 15

    def test_filtered_tree_has_correct_step_count(self, tmp_path):
        """With session filtering, reasoning_agent steps == root_calls for that session."""
        jsonl = tmp_path / "events.jsonl"
        sids = _write_multi_session_jsonl(jsonl, n_sessions=3, root_calls=5)
        filtered = read_events(jsonl, session_id=sids[0])
        tree = build_tree(filtered)
        root_steps = tree.steps.get("reasoning_agent", [])
        assert len(root_steps) == 5  # Only this session's 5 calls
