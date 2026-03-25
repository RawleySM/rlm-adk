"""Data models for the recursive notebook flow view."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FlowBlockKind = Literal[
    "agent_card",
    "code_cell",
    "arrow",
    "child_card",
    "output_cell",
]

ArrowDirection = Literal["down", "right", "left"]

ArrowKind = Literal["execute_code", "llm_query", "set_model_response", "return_value"]


@dataclass(frozen=True)
class FlowAgentCard:
    """Reasoning agent header card in the flow transcript."""

    kind: FlowBlockKind = "agent_card"
    pane_id: str = ""
    invocation_id: str = ""
    agent_name: str = ""
    depth: int = 0
    fanout_idx: int | None = None
    status: str = "idle"
    iteration: int = 0
    available_iteration_ids: list[tuple[int, str]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    total_context_tokens: int = 0
    model: str = ""
    context_items: list[Any] = field(default_factory=list)
    state_items: list[Any] = field(default_factory=list)
    request_chunks: list[Any] = field(default_factory=list)
    model_events: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class LlmQueryLineInfo:
    """Metadata for a single llm_query call site in a code cell."""

    line_number: int
    function_name: str = "llm_query"
    schema_name: str | None = None
    child_depth: int | None = None
    child_fanout_idx: int | None = None
    child_status: str | None = None
    child_prompt_preview: str = ""
    child_result_preview: str = ""
    child_pane_id: str | None = None


@dataclass(frozen=True)
class FlowCodeCell:
    """Code pane block in the flow transcript."""

    kind: FlowBlockKind = "code_cell"
    code: str = ""
    llm_query_lines: list[LlmQueryLineInfo] = field(default_factory=list)
    pane_id: str = ""
    invocation_id: str = ""


@dataclass(frozen=True)
class FlowArrow:
    """Directional connector between flow blocks."""

    kind: FlowBlockKind = "arrow"
    direction: ArrowDirection = "down"
    arrow_kind: ArrowKind = "execute_code"
    label: str = ""


@dataclass(frozen=True)
class FlowChildCard:
    """Compact inline child agent card."""

    kind: FlowBlockKind = "child_card"
    depth: int = 0
    fanout_idx: int = 0
    status: str = "idle"
    error: bool = False
    error_message: str | None = None
    prompt_preview: str = ""
    result_preview: str = ""
    visible_output_preview: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    elapsed_ms: float | None = None
    finish_reason: str | None = None
    model: str | None = None
    pane_id: str | None = None
    structured_output: dict[str, Any] | None = None


@dataclass(frozen=True)
class FlowOutputCell:
    """Output cell below the code cell."""

    kind: FlowBlockKind = "output_cell"
    stdout: str = ""
    stderr: str = ""
    child_returns: list[FlowChildCard] = field(default_factory=list)
    has_errors: bool = False
    pane_id: str = ""
    invocation_id: str = ""


@dataclass(frozen=True)
class FlowInspectorData:
    """Data for the right sidebar context inspector."""

    state_items: list[Any] = field(default_factory=list)
    skills: list[tuple[str, str]] = field(default_factory=list)
    return_value_json: str | None = None
    selected_pane_id: str = ""
    context_items: list[Any] = field(default_factory=list)


FlowBlock = FlowAgentCard | FlowCodeCell | FlowArrow | FlowChildCard | FlowOutputCell


@dataclass(frozen=True)
class FlowTranscript:
    """Complete linearized flow transcript."""

    blocks: list[FlowBlock] = field(default_factory=list)
    inspector: FlowInspectorData | None = None
