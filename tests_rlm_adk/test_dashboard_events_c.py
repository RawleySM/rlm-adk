"""Agent C: Event reader + tree builder tests.

TDD test file for rlm_adk/dashboard/event_reader.py.
Uses hand-written JSONL fixtures — no dependency on Agent B's plugin.

NOTE: The tree builder groups by agent_name (not invocation_id) because
in this architecture all agents share one invocation_id via ctx.model_copy().
"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
BASIC = FIXTURES / "dashboard_events_basic.jsonl"
BATCH = FIXTURES / "dashboard_events_batch.jsonl"


# ── Cycle 1: read_events parses JSONL ────────────────────────────────


def test_read_events_parses_jsonl():
    """read_events returns list[StepEvent] from JSONL file."""
    from rlm_adk.dashboard.event_reader import StepEvent, read_events

    events = read_events(BASIC)

    # Basic fixture has 10 lines (5 model + 5 tool)
    assert len(events) == 10
    assert all(isinstance(e, StepEvent) for e in events)

    # Spot-check first model event
    m0 = events[0]
    assert m0.event_id == "m0"
    assert m0.phase == "model"
    assert m0.invocation_id == "inv0"
    assert m0.input_tokens == 100
    assert m0.output_tokens == 50
    assert m0.thought_tokens == 10
    assert m0.model == "gemini-2.5-flash"
    assert m0.depth == 0
    assert m0.agent_name == "reasoning_agent"

    # Spot-check first tool event
    t0 = events[1]
    assert t0.event_id == "t0"
    assert t0.phase == "tool"
    assert t0.tool_name == "list_skills"
    assert t0.model_event_id == "m0"
    assert t0.duration_ms == 100

    # Spot-check child event
    m2 = events[4]
    assert m2.event_id == "m2"
    assert m2.invocation_id == "inv1"
    assert m2.parent_invocation_id == "inv0"
    assert m2.parent_tool_call_id == "t1"
    assert m2.depth == 1


# ── Cycle 2: build_tree links parent_tool_call_id ────────────────────


def test_build_tree_links_parent_tool_call_id():
    """children_of_tool maps parent execute_code event_id -> child agent_names."""
    from rlm_adk.dashboard.event_reader import (
        build_tree,
        children_of_tool_event,
        events_for_invocation,
        read_events,
    )

    events = read_events(BASIC)
    tree = build_tree(events)

    # t1 is the execute_code call that spawned child_reasoning_d1f0
    # (tree now groups by agent_name, not invocation_id)
    assert children_of_tool_event(tree, "t1") == ["child_reasoning_d1f0"]

    # t0 (list_skills) spawned no children
    assert children_of_tool_event(tree, "t0") == []

    # non-existent tool event returns empty
    assert children_of_tool_event(tree, "nonexistent") == []

    # events_for_invocation (now keyed by agent_name)
    root_events = events_for_invocation(tree, "reasoning_agent")
    assert len(root_events) == 6  # m0,t0,m1,t1,m4,t4
    assert all(e.agent_name == "reasoning_agent" for e in root_events)

    child_events = events_for_invocation(tree, "child_reasoning_d1f0")
    assert len(child_events) == 4  # m2,t2,m3,t3
    assert all(e.agent_name == "child_reasoning_d1f0" for e in child_events)


# ── Cycle 3: batch children sorted by dispatch_call_index ────────────


def test_build_tree_sorts_children_by_dispatch_call_index():
    """Batch children appear in dispatch order, not completion order."""
    from rlm_adk.dashboard.event_reader import (
        build_tree,
        children_of_tool_event,
        read_events,
    )

    events = read_events(BATCH)
    tree = build_tree(events)

    # In the fixture, children complete out of order: c2 (ts=2.0), c0 (ts=2.5), c1 (ts=3.0)
    # But dispatch_call_index order is: c0=0, c1=1, c2=2
    # Tree now groups by agent_name: child_d1f0, child_d1f1, child_d1f2
    children = children_of_tool_event(tree, "t0")
    assert children == ["child_d1f0", "child_d1f1", "child_d1f2"]


# ── Cycle 4: model/tool pairing via model_event_id ──────────────────


def test_model_tool_pairing_via_model_event_id():
    """steps[agent_name] pairs each model event with its tool event."""
    from rlm_adk.dashboard.event_reader import build_tree, read_events

    events = read_events(BASIC)
    tree = build_tree(events)

    # reasoning_agent has 3 model-tool pairs: (m0,t0), (m1,t1), (m4,t4)
    root_steps = tree.steps["reasoning_agent"]
    assert len(root_steps) == 3

    m, t = root_steps[0]
    assert m.event_id == "m0"
    assert t is not None
    assert t.event_id == "t0"
    assert t.model_event_id == "m0"

    m, t = root_steps[1]
    assert m.event_id == "m1"
    assert t is not None
    assert t.event_id == "t1"

    m, t = root_steps[2]
    assert m.event_id == "m4"
    assert t is not None
    assert t.event_id == "t4"

    # child_reasoning_d1f0 has 2 model-tool pairs: (m2,t2), (m3,t3)
    child_steps = tree.steps["child_reasoning_d1f0"]
    assert len(child_steps) == 2

    m, t = child_steps[0]
    assert m.event_id == "m2"
    assert t is not None
    assert t.event_id == "t2"

    m, t = child_steps[1]
    assert m.event_id == "m3"
    assert t is not None
    assert t.event_id == "t3"
