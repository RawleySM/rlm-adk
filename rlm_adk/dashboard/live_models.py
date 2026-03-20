"""Data models for the live recursive dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SourceKind = Literal[
    "dynamic_instruction_param",
    "state_key",
    "request_chunk",
    "tool_variable",
]


PaneStatus = Literal["running", "idle", "completed", "error", "cancelled"]


@dataclass(frozen=True)
class LiveWatermark:
    """Incremental read position across SQLite and JSONL sources."""

    trace_id: str | None = None
    latest_telemetry_time: float = 0.0
    latest_sse_seq: int = -1
    snapshot_offset: int = 0
    output_offset: int = 0


@dataclass(frozen=True)
class LiveRequestChunk:
    chunk_id: str
    category: str
    title: str
    text: str
    char_count: int
    token_count: int
    token_count_is_exact: bool = False
    iteration_origin: int = -1

    @property
    def preview(self) -> str:
        return self.text[:240]

    @property
    def label(self) -> str:
        return self.title or self.category


@dataclass(frozen=True)
class LiveStateItem:
    raw_key: str
    base_key: str
    depth: int
    fanout_idx: int | None
    value: Any
    value_type: str
    event_time: float
    seq: int

    @property
    def value_preview(self) -> str:
        text = self.value if isinstance(self.value, str) else repr(self.value)
        return text[:240]


@dataclass(frozen=True)
class LiveContextItem:
    label: str
    raw_key: str
    scope: str
    source_kind: SourceKind
    token_count: int
    token_count_is_exact: bool
    display_value_preview: str


@dataclass(frozen=True)
class LiveContextBannerItem:
    label: str
    raw_key: str
    scope: str
    present: bool
    token_count: int
    token_count_is_exact: bool
    source_kind: SourceKind
    display_value_preview: str


@dataclass(frozen=True)
class LiveContextSelection:
    label: str
    raw_key: str
    scope: str
    source_kind: SourceKind
    text: str


@dataclass(frozen=True)
class LiveSessionSummary:
    user_query: str
    registered_skills: list[tuple[str, str]] = field(default_factory=list)
    registered_plugins: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class LiveChildSummary:
    parent_depth: int
    depth: int
    fanout_idx: int
    model: str | None
    status: PaneStatus
    error: bool
    elapsed_ms: float | None
    prompt: str
    prompt_preview: str
    result_text: str
    final_answer: str
    visible_output_text: str
    visible_output_preview: str
    thought_text: str
    thought_preview: str
    raw_output: Any | None
    raw_output_preview: str
    input_tokens: int
    output_tokens: int
    thought_tokens: int
    finish_reason: str | None
    error_message: str | None
    structured_output: dict[str, Any] | None
    event_time: float
    seq: int


@dataclass(frozen=True)
class LiveToolEvent:
    telemetry_id: str
    agent_name: str
    depth: int
    fanout_idx: int | None
    tool_name: str
    start_time: float
    end_time: float | None
    duration_ms: float | None
    result_preview: str
    repl_has_errors: bool
    repl_has_output: bool
    repl_llm_calls: int
    repl_stdout_len: int
    repl_stderr_len: int
    repl_trace_summary: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class LiveModelEvent:
    telemetry_id: str
    agent_name: str
    depth: int
    fanout_idx: int | None
    iteration: int
    call_number: int | None
    start_time: float
    end_time: float | None
    duration_ms: float | None
    model: str
    model_version: str | None
    status: PaneStatus
    finish_reason: str | None
    input_tokens: int
    output_tokens: int
    thought_tokens: int
    prompt_chars: int
    system_chars: int
    num_contents: int
    skill_instruction: str | None


@dataclass(frozen=True)
class LiveInvocation:
    invocation_id: str
    pane_id: str
    depth: int
    fanout_idx: int | None
    agent_name: str
    model: str
    model_version: str | None
    status: PaneStatus
    iteration: int
    input_tokens: int
    output_tokens: int
    thought_tokens: int
    elapsed_ms: float
    request_chunks: list[LiveRequestChunk]
    state_items: list[LiveStateItem]
    child_summaries: list[LiveChildSummary]
    repl_submission: str
    repl_expanded_code: str
    repl_stdout: str
    repl_stderr: str
    reasoning_visible_text: str
    reasoning_thought_text: str
    structured_output: dict[str, Any] | None
    raw_payload: dict[str, Any]
    model_events: list[LiveModelEvent] = field(default_factory=list)
    tool_events: list[LiveToolEvent] = field(default_factory=list)


@dataclass(frozen=True)
class LivePane:
    pane_id: str
    invocation_id: str
    depth: int
    fanout_idx: int | None
    agent_name: str
    model: str
    model_version: str | None
    status: PaneStatus
    is_active: bool
    is_expanded: bool
    iteration: int
    latest_tool_call_number: int | None
    input_tokens: int
    output_tokens: int
    thought_tokens: int
    elapsed_ms: float
    latest_event_time: float
    parent_pane_id: str | None
    request_chunks: list[LiveRequestChunk]
    state_items: list[LiveStateItem]
    child_summaries: list[LiveChildSummary]
    repl_submission: str
    repl_expanded_code: str
    repl_stdout: str
    repl_stderr: str
    reasoning_visible_text: str
    reasoning_thought_text: str
    structured_output: dict[str, Any] | None
    raw_payload: dict[str, Any]
    model_events: list[LiveModelEvent] = field(default_factory=list)
    tool_events: list[LiveToolEvent] = field(default_factory=list)
    sibling_fanouts: list[LiveChildSummary] = field(default_factory=list)
    banner_items: list[LiveContextBannerItem] = field(default_factory=list)
    invocations: list[LiveInvocation] = field(default_factory=list)

    @property
    def breadcrumb_label(self) -> str:
        fanout = "root" if self.fanout_idx is None else str(self.fanout_idx)
        return f"Layer {self.depth} | Fan-out {fanout} | {self.agent_name}"

    @property
    def request_summary_items(self) -> list[tuple[str, str]]:
        chunk_count = len(self.request_chunks)
        elapsed = f"{self.elapsed_ms:.0f} ms" if self.elapsed_ms else "0 ms"
        return [
            ("prompt", str(self.input_tokens)),
            ("output", str(self.output_tokens)),
            ("thought", str(self.thought_tokens)),
            ("chunks", str(chunk_count)),
            ("model", self.model),
            ("elapsed", elapsed),
        ]


@dataclass(frozen=True)
class LiveRunStats:
    total_live_model_calls: int = 0
    active_depth: int = 0
    active_children: int = 0


@dataclass(frozen=True)
class LiveInvocationNode:
    pane_id: str
    invocation: LiveInvocation
    available_invocations: list[LiveInvocation] = field(default_factory=list)
    context_items: list[LiveContextBannerItem] = field(default_factory=list)
    child_nodes: list[LiveInvocationNode] = field(default_factory=list)
    lineage: list[LiveInvocation] = field(default_factory=list)
    parent_code_text: str = ""
    parent_stdout_text: str = ""
    parent_stderr_text: str = ""
    invocation_context_tokens: int = 0


@dataclass(frozen=True)
class LiveRunState:
    panes: list[LivePane]
    active_pane_id: str | None
    invocation_nodes: list[LiveInvocationNode]
    breadcrumb: str
    run_status: PaneStatus
    total_live_model_calls: int
    active_depth: int
    active_children: int


@dataclass(frozen=True)
class LiveRunSnapshot:
    session_id: str
    trace_id: str | None
    status: PaneStatus
    started_at: float = 0.0
    finished_at: float = 0.0
    panes: list[LivePane] = field(default_factory=list)
    pane_map: dict[str, LivePane] = field(default_factory=dict)
    pane_order: list[str] = field(default_factory=list)
    root_pane_id: str | None = None
    active_candidate_pane_id: str | None = None
    stats: LiveRunStats = field(default_factory=LiveRunStats)
    watermark: LiveWatermark = field(default_factory=LiveWatermark)

    @property
    def is_empty(self) -> bool:
        return not self.panes


@dataclass
class LiveDashboardState:
    available_sessions: list[str] = field(default_factory=list)
    available_session_labels: dict[str, str] = field(default_factory=dict)
    available_replay_fixtures: list[str] = field(default_factory=list)
    selected_session_id: str | None = None
    snapshot: LiveRunSnapshot | None = None
    run_state: LiveRunState | None = None
    replay_path: str = ""
    selected_skills: list[str] = field(default_factory=list)
    launch_in_progress: bool = False
    launch_cancelled: bool = False
    launch_error: str | None = None
    launched_session_id: str | None = None
    active_pane_id: str | None = None
    selected_fanouts_by_parent_depth: dict[int, int] = field(default_factory=dict)
    selected_invocation_id_by_pane: dict[str, str] = field(default_factory=dict)
    auto_follow: bool = True
    live_updates_paused: bool = False
    available_provider_fake_fixtures: list[str] = field(default_factory=list)
    selected_provider_fake_fixture: str = ""
    last_error: str | None = None
    context_selection: LiveContextSelection | None = None
    context_viewer_open: bool = False
    step_mode_enabled: bool = False
    step_mode_waiting: bool = False
    step_mode_paused_label: str = ""

    @property
    def panes(self) -> list[LivePane]:
        return self.snapshot.panes if self.snapshot else []

    @property
    def run_status(self) -> PaneStatus:
        return self.snapshot.status if self.snapshot else "idle"

    @property
    def stats(self) -> LiveRunStats:
        return self.snapshot.stats if self.snapshot else LiveRunStats()

    @property
    def active_pane(self) -> LivePane | None:
        if not self.snapshot or not self.active_pane_id:
            return None
        return self.snapshot.pane_map.get(self.active_pane_id)

    @property
    def pause_live_updates(self) -> bool:
        return self.live_updates_paused
