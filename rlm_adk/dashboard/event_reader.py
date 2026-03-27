"""Event reader and invocation tree builder for the dashboard.

Parses JSONL event files (written by DashboardEventPlugin) into StepEvent
dataclass instances and builds an InvocationTree using explicit lineage
edges (parent_tool_call_id, model_event_id, dispatch_call_index).

Agent C deliverable — independent of Agent B's plugin code.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# ── Dataclasses ──────────────────────────────────────────────────────


@dataclass
class StepEvent:
    """Single event from the JSONL event stream."""

    # ── Identity ──
    event_id: str = ""
    phase: str = ""  # "model" or "tool"

    # ── Lineage ──
    invocation_id: str = ""
    parent_invocation_id: str | None = None
    parent_tool_call_id: str | None = None
    dispatch_call_index: int = 0
    branch: str | None = None
    session_id: str | None = None

    # ── Step pairing ──
    model_event_id: str | None = None  # tool events: points to triggering model event

    # ── Scope ──
    agent_name: str = ""
    depth: int = 0
    fanout_idx: int | None = None
    ts: float = 0.0

    # ── Model phase fields ──
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    model: str = ""
    error: bool = False
    error_message: str | None = None

    # ── Tool phase fields ──
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result: dict | None = None
    code: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    duration_ms: float | None = None
    llm_query_detected: bool = False
    llm_query_count: int = 0


@dataclass
class InvocationTree:
    """Tree structure built from explicit lineage edges."""

    # inv_id -> list of events in that invocation
    by_inv: dict[str, list[StepEvent]] = field(default_factory=dict)
    # tool event_id -> sorted child invocation_ids
    children_of_tool: dict[str, list[str]] = field(default_factory=dict)
    # inv_id -> list of (model_event, tool_event | None) pairs
    steps: dict[str, list[tuple[StepEvent, StepEvent | None]]] = field(default_factory=dict)


# ── Public API ───────────────────────────────────────────────────────


def read_events(path: str | Path, *, session_id: str | None = None) -> list[StepEvent]:
    """Read JSONL file and return list of StepEvent instances.

    Args:
        path: Path to the JSONL event file.
        session_id: When provided, only events matching this session_id are
            returned.  Without this filter the file accumulates events across
            all sessions, causing ``build_tree`` to merge unrelated runs into
            one tree (e.g. 12 sessions × 5 root calls = 60 ``reasoning_agent``
            steps instead of 5).
    """
    events: list[StepEvent] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if session_id is not None and data.get("session_id") != session_id:
                continue
            events.append(
                StepEvent(**{k: v for k, v in data.items() if k in StepEvent.__dataclass_fields__})
            )
    return events


def build_tree(events: list[StepEvent]) -> InvocationTree:
    """Build invocation tree using explicit lineage edges.

    Groups events by agent_name (not invocation_id) because in this
    architecture all agents within one Runner invocation share the same
    invocation_id via ctx.model_copy().  Agent names are unique per depth
    and fanout: reasoning_agent, child_reasoning_d1f0, child_reasoning_d2f0.
    """
    # Group events by agent_name (unique per agent instance)
    by_inv: dict[str, list[StepEvent]] = defaultdict(list)
    for e in events:
        by_inv[e.agent_name].append(e)

    # Children grouped by parent_tool_call_id
    # Use agent_name as the child identifier (not invocation_id)
    # Deduplicate by (parent_tool_call_id, agent_name) pair so the same
    # agent can appear under multiple tool calls (e.g. llm_query_batched
    # reuses child_reasoning_d1f0 across different execute_code invocations).
    children_of_tool: dict[str, list[str]] = defaultdict(list)
    seen_pair: set[tuple[str, str]] = set()
    for e in events:
        if e.parent_tool_call_id:
            pair = (e.parent_tool_call_id, e.agent_name)
            if pair not in seen_pair:
                children_of_tool[e.parent_tool_call_id].append(e.agent_name)
                seen_pair.add(pair)

    # Sort children by dispatch_call_index (not completion order) — R5-1
    for _tool_id, child_names in children_of_tool.items():
        child_names.sort(
            key=lambda name: next(
                (
                    e.dispatch_call_index
                    for e in by_inv[name]
                    if e.dispatch_call_index is not None
                ),
                0,
            )
        )

    # Pair model+tool within each agent via model_event_id
    steps: dict[str, list[tuple[StepEvent, StepEvent | None]]] = {}
    for agent_name, agent_events in by_inv.items():
        paired: list[tuple[StepEvent, StepEvent | None]] = []
        for e in agent_events:
            if e.phase == "model":
                paired.append((e, None))
            elif e.phase == "tool" and e.model_event_id:
                for i, (m, _) in enumerate(paired):
                    if m.event_id == e.model_event_id:
                        paired[i] = (m, e)
                        break
        steps[agent_name] = paired

    return InvocationTree(
        by_inv=dict(by_inv),
        children_of_tool=dict(children_of_tool),
        steps=steps,
    )


def events_for_invocation(tree: InvocationTree, inv_id: str) -> list[StepEvent]:
    """Get all events for a given invocation."""
    return tree.by_inv.get(inv_id, [])


def children_of_tool_event(tree: InvocationTree, tool_event_id: str) -> list[str]:
    """Get sorted child invocation_ids spawned by a tool event."""
    return tree.children_of_tool.get(tool_event_id, [])
