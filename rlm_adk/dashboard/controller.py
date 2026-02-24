"""Dashboard controller -- business logic with no UI dependencies.

Manages state transitions, data loading, and navigation.  Fully testable
without NiceGUI imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rlm_adk.dashboard.data_loader import DashboardDataLoader
from rlm_adk.dashboard.data_models import (
    APITokenUsage,
    ContextChunk,
    IterationData,
    ModelOutput,
    SessionSummary,
    TokenReconciliation,
)


@dataclass
class DashboardState:
    """Observable state for the dashboard UI."""

    available_sessions: list[str] = field(default_factory=list)
    selected_session_id: str | None = None
    session_summary: SessionSummary | None = None
    iterations: list[IterationData] = field(default_factory=list)
    current_iteration: int = 0
    selected_chunk: ContextChunk | None = None
    selected_worker_chunk: ContextChunk | None = None
    api_usage: APITokenUsage | None = None
    reconciliation: TokenReconciliation | None = None
    is_loading: bool = False

    @property
    def current_iteration_data(self) -> IterationData | None:
        """Return the IterationData for the current iteration index."""
        if 0 <= self.current_iteration < len(self.iterations):
            return self.iterations[self.current_iteration]
        return None

    @property
    def current_reasoning_output(self) -> ModelOutput | None:
        """Return the ModelOutput for the reasoning agent in the current iteration."""
        it_data = self.current_iteration_data
        if it_data is not None:
            return it_data.reasoning_output
        return None

    @property
    def total_iterations(self) -> int:
        return len(self.iterations)


class DashboardController:
    """Coordinates data loading and state transitions.

    Contains no UI logic -- all UI interaction goes through
    DashboardUI.refresh_all().
    """

    def __init__(self, loader: DashboardDataLoader):
        self.loader = loader
        self.state = DashboardState()

    async def select_session(self, session_id: str) -> None:
        """Load a session and populate state."""
        self.state.is_loading = True
        try:
            summary, iterations = self.loader.load_session(session_id)
            self.state.selected_session_id = session_id
            self.state.session_summary = summary
            self.state.iterations = iterations
            self.state.current_iteration = 0
            self.state.selected_chunk = None
            self.state.selected_worker_chunk = None
            self.state.reconciliation = None
            self.state.api_usage = None
        finally:
            self.state.is_loading = False

    def navigate(self, delta: int) -> None:
        """Move current_iteration by delta, clamped to valid range."""
        if not self.state.iterations:
            return
        new_idx = self.state.current_iteration + delta
        new_idx = max(0, min(new_idx, len(self.state.iterations) - 1))
        if new_idx != self.state.current_iteration:
            self.state.current_iteration = new_idx
            self.state.selected_chunk = None

    def navigate_to(self, index: int) -> None:
        """Jump to a specific iteration index."""
        if not self.state.iterations:
            return
        index = max(0, min(index, len(self.state.iterations) - 1))
        if index != self.state.current_iteration:
            self.state.current_iteration = index
            self.state.selected_chunk = None

    def select_chunk(self, chunk: ContextChunk) -> None:
        """Select a chunk for detail display."""
        self.state.selected_chunk = chunk

    def select_worker_chunk(self, chunk: ContextChunk) -> None:
        """Select a worker chunk for the worker detail panel."""
        self.state.selected_worker_chunk = chunk

    def find_chunk_by_id(self, chunk_id: str) -> ContextChunk | None:
        """Find a chunk by its chunk_id in the current iteration."""
        it_data = self.state.current_iteration_data
        if it_data is None:
            return None
        if it_data.reasoning_window:
            for chunk in it_data.reasoning_window.chunks:
                if chunk.chunk_id == chunk_id:
                    return chunk
        for ww in it_data.worker_windows:
            for chunk in ww.chunks:
                if chunk.chunk_id == chunk_id:
                    return chunk
        return None

    def get_chunks_for_category(
        self, category: Any, window_type: str = "reasoning"
    ) -> list[ContextChunk]:
        """Return all chunks matching a category in the current iteration."""
        it_data = self.state.current_iteration_data
        if it_data is None:
            return []
        result: list[ContextChunk] = []
        if window_type == "reasoning" and it_data.reasoning_window:
            result.extend(
                c
                for c in it_data.reasoning_window.chunks
                if c.category == category
            )
        return result

    def set_reconciliation(
        self, api_usage: APITokenUsage | None
    ) -> None:
        """Compute reconciliation from local summary and gcloud data."""
        self.state.api_usage = api_usage
        self.state.reconciliation = reconcile(
            self.state.session_summary, api_usage
        )


def reconcile(
    local: SessionSummary | None, gcloud: APITokenUsage | None
) -> TokenReconciliation:
    """Reconcile local token counts against GCloud monitoring data."""
    if local is None:
        return TokenReconciliation(
            local_input_tokens=0,
            local_output_tokens=0,
            api_input_tokens=0,
            api_output_tokens=0,
            input_delta=0,
            output_delta=0,
            input_match=True,
            output_match=True,
            error_message="No session data loaded",
        )

    if gcloud is None:
        return TokenReconciliation(
            local_input_tokens=local.total_input_tokens,
            local_output_tokens=local.total_output_tokens,
            api_input_tokens=0,
            api_output_tokens=0,
            input_delta=0,
            output_delta=0,
            input_match=True,
            output_match=True,
            error_message="Cloud usage data unavailable -- showing local metrics only",
        )

    input_delta = gcloud.total_input_tokens - local.total_input_tokens
    threshold = local.total_input_tokens * 0.05 if local.total_input_tokens > 0 else 0
    return TokenReconciliation(
        local_input_tokens=local.total_input_tokens,
        local_output_tokens=local.total_output_tokens,
        api_input_tokens=gcloud.total_input_tokens,
        api_output_tokens=0,  # Cloud Monitoring does not track output tokens
        input_delta=input_delta,
        output_delta=0,
        input_match=abs(input_delta) < threshold,
        output_match=True,  # Cannot verify output tokens
        error_message=None,
    )


class DashboardUI:
    """Coordinates UI refresh across multiple refreshable sections.

    NiceGUI review correction: provides a concrete refresh_all() method
    that the keyboard handler and navigation buttons can call.
    """

    def __init__(self, controller: DashboardController):
        self.controller = controller
        self._refreshables: list[Any] = []

    def register(self, refreshable_fn: Any) -> None:
        """Register a @ui.refreshable for coordinated refresh."""
        self._refreshables.append(refreshable_fn)

    def refresh_all(self) -> None:
        """Refresh all registered UI sections."""
        for r in self._refreshables:
            r.refresh()
