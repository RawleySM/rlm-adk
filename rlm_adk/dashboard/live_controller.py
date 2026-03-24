"""Controller for the live recursive dashboard."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from rlm_adk.dashboard.flow_builder import build_flow_transcript
from rlm_adk.dashboard.flow_models import FlowTranscript
from rlm_adk.dashboard.live_loader import LiveDashboardLoader
from rlm_adk.dashboard.live_models import (
    LiveContextBannerItem,
    LiveContextSelection,
    LiveDashboardState,
    LiveInvocation,
    LiveInvocationNode,
    LivePane,
    LiveRunState,
    LiveSessionSummary,
)
from rlm_adk.dashboard.run_service import (
    list_provider_fake_fixtures,
    list_replay_fixtures,
    prepare_provider_fake_launch,
    prepare_replay_launch,
    resolve_fixture_file_path,
)
from rlm_adk.step_gate import step_gate


@dataclass(frozen=True)
class LiveBreadcrumb:
    depth: int
    fanout_idx: int | None
    agent_name: str
    status: str

    @property
    def label(self) -> str:
        fanout = "root" if self.fanout_idx is None else str(self.fanout_idx)
        return f"d{self.depth}/f{fanout} {self.agent_name}"


class LiveDashboardController:
    """Owns live dashboard state transitions and polling decisions."""

    def __init__(self, loader: LiveDashboardLoader):
        self.loader = loader
        self.state = LiveDashboardState()
        self.state.selected_skills = []
        self._launch_task: asyncio.Task | None = None

    def _refresh_available_sessions(self) -> None:
        session_labels = self.loader.list_session_labels()
        self.state.available_sessions = [session_id for session_id, _label in session_labels]
        self.state.available_session_labels = {
            session_id: label for session_id, label in session_labels
        }

    async def initialize(self) -> None:
        self.state.available_replay_fixtures = list_replay_fixtures()
        self.state.available_provider_fake_fixtures = list_provider_fake_fixtures()
        # No default pre-selection — dropdowns start empty, user picks on-deck fixture.
        self._refresh_available_sessions()
        if self.state.available_sessions and not self.state.selected_session_id:
            await self.select_session(self.state.available_sessions[0])

    async def refresh_sessions(self) -> None:
        self._refresh_available_sessions()
        sessions = self.state.available_sessions
        if not self.state.selected_session_id and sessions:
            await self.select_session(sessions[0])

    def set_replay_path(self, replay_path: str) -> None:
        self.state.replay_path = replay_path
        if replay_path:
            self.state.selected_provider_fake_fixture = ""  # mutual exclusion
        self.state.launch_error = None

    def set_provider_fake_fixture(self, fixture_stem: str) -> None:
        self.state.selected_provider_fake_fixture = fixture_stem
        if fixture_stem:
            self.state.replay_path = ""  # mutual exclusion
        self.state.launch_error = None

    def set_selected_skills(self, selected_skills: list[str]) -> None:
        self.state.selected_skills = list(selected_skills) if selected_skills else []
        self.state.launch_error = None

    async def launch_replay(self) -> str | None:
        if self.state.launch_in_progress:
            return None

        try:
            if self.state.selected_provider_fake_fixture:
                handle = await prepare_provider_fake_launch(
                    self.state.selected_provider_fake_fixture,
                    enabled_skills=self.state.selected_skills,
                )
            elif self.state.replay_path:
                handle = await prepare_replay_launch(
                    self.state.replay_path,
                    enabled_skills=self.state.selected_skills,
                )
            else:
                self.state.launch_error = "No fixture selected"
                return None
        except Exception as exc:
            self.state.launch_error = str(exc)
            self.state.last_error = str(exc)
            return None
        self.state.launch_in_progress = True
        self.state.launch_cancelled = False
        self.state.launch_error = None
        self.state.launched_session_id = handle.session_id
        if handle.session_id not in self.state.available_sessions:
            self.state.available_sessions = [handle.session_id, *self.state.available_sessions]
        self.state.available_session_labels.setdefault(handle.session_id, handle.session_id)
        await self.select_session(handle.session_id)
        self._launch_task = asyncio.create_task(self._run_launch(handle))
        return handle.session_id

    async def _run_launch(self, handle) -> None:
        try:
            await handle.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.launch_error = str(exc)
            self.state.last_error = str(exc)
        finally:
            self.state.launch_in_progress = False

    async def cancel_launch(self) -> None:
        """Cancel the running launch task and stamp the trace as cancelled."""
        if self._launch_task is None or self._launch_task.done():
            return
        self._launch_task.cancel()
        # Don't await the task — ADK runner cleanup can block the event loop.
        # Set state immediately; _run_launch's finally block is idempotent.
        self.state.launch_in_progress = False
        self.state.launch_cancelled = True
        if self.state.launched_session_id:
            try:
                self.loader.mark_trace_cancelled(self.state.launched_session_id)
            except Exception:
                pass

    async def select_session(self, session_id: str) -> None:
        self.state.selected_session_id = session_id
        self.state.selected_fanouts_by_parent_depth.clear()
        self.state.selected_invocation_id_by_pane.clear()
        self.state.last_error = None
        self.close_context_viewer()
        snapshot = self.loader.load_session(session_id)
        self.state.snapshot = snapshot
        self.state.active_pane_id = self._resolve_active_pane_id(snapshot)
        self._sync_selected_invocations(snapshot.pane_map.values())
        self._sync_selected_fanouts_from_active()
        self._refresh_run_state()

    async def poll(self) -> bool:
        if self.state.live_updates_paused or not self.state.selected_session_id:
            return False
        previous = self.state.snapshot.watermark if self.state.snapshot else None
        snapshot = self.loader.load_session(
            self.state.selected_session_id,
            previous=previous,
        )
        changed = (
            self.state.snapshot is None
            or snapshot.watermark != self.state.snapshot.watermark
            or len(snapshot.panes) != len(self.state.snapshot.panes)
            or snapshot.active_candidate_pane_id != self.state.snapshot.active_candidate_pane_id
        )
        self.state.snapshot = snapshot
        self._sync_selected_invocations(snapshot.pane_map.values())
        if self.state.auto_follow:
            self.state.active_pane_id = self._resolve_active_pane_id(snapshot)
            self._sync_selected_fanouts_from_active()
        else:
            self.state.active_pane_id = self._clamp_active_pane(self.state.active_pane_id)
        self._refresh_run_state()

        # Sync step-gate state
        self.state.step_mode_enabled = step_gate.step_mode_enabled
        self.state.step_mode_waiting = step_gate.waiting
        if step_gate.waiting and step_gate.paused_agent_name is not None:
            self.state.step_mode_paused_label = (
                f"Paused: {step_gate.paused_agent_name} @ depth {step_gate.paused_depth}"
            )
        else:
            self.state.step_mode_paused_label = ""

        return changed

    def set_auto_follow(self, enabled: bool) -> None:
        self.state.auto_follow = enabled
        if enabled and self.state.snapshot is not None:
            self.state.active_pane_id = self._resolve_active_pane_id(self.state.snapshot)
            self._sync_selected_fanouts_from_active()
            self._refresh_run_state()

    def set_live_updates_paused(self, paused: bool) -> None:
        self.state.live_updates_paused = paused
        self._refresh_run_state()

    def set_pause_live_updates(self, paused: bool) -> None:
        self.set_live_updates_paused(paused)

    def toggle_auto_follow(self) -> None:
        self.set_auto_follow(not self.state.auto_follow)

    def toggle_live_updates_paused(self) -> None:
        self.set_live_updates_paused(not self.state.live_updates_paused)

    def set_step_mode(self, enabled: bool) -> None:
        step_gate.set_step_mode(enabled)
        self.state.step_mode_enabled = enabled
        if not enabled:
            self.state.step_mode_waiting = False
            self.state.step_mode_paused_label = ""

    def advance_step(self) -> None:
        step_gate.advance()

    def activate_pane(self, pane_id: str, *, manual: bool = True) -> None:
        pane = self._pane_by_id(pane_id)
        if pane is None:
            return
        self.state.active_pane_id = pane_id
        if manual:
            self.state.auto_follow = False
        self._sync_selected_fanouts_from_pane(pane)
        self._refresh_run_state()

    def set_active_pane(self, pane_id: str, *, manual: bool = True) -> None:
        self.activate_pane(pane_id, manual=manual)

    def select_sibling(self, parent_depth: int, fanout_idx: int) -> None:
        self.state.selected_fanouts_by_parent_depth[parent_depth] = fanout_idx
        child_depth = parent_depth + 1
        pane = self._find_pane(child_depth, fanout_idx)
        if pane is None:
            return
        self.activate_pane(pane.pane_id, manual=True)

    def focus_child_fanout(self, parent_pane_id: str, fanout_idx: int) -> None:
        parent = self._pane_by_id(parent_pane_id)
        if parent is None:
            return
        self.select_sibling(parent.depth, fanout_idx)

    def open_context_viewer(self, item: LiveContextBannerItem) -> None:
        text = self.loader.resolve_banner_item_text(
            self.selected_invocation(self.state.active_pane),
            item,
            lineage=self.selected_invocation_lineage(),
        )
        self.state.context_selection = LiveContextSelection(
            label=item.label,
            raw_key=item.raw_key,
            scope=item.scope,
            source_kind=item.source_kind,
            text=text,
        )
        self.state.context_viewer_open = True

    def open_invocation_context_viewer(
        self,
        invocation: LiveInvocation,
        item: LiveContextBannerItem,
        lineage: list[LiveInvocation],
    ) -> None:
        text = self.loader.resolve_banner_item_text(
            invocation,
            item,
            lineage=lineage,
        )
        self.state.context_selection = LiveContextSelection(
            label=item.label,
            raw_key=item.raw_key,
            scope=item.scope,
            source_kind=item.source_kind,
            text=text,
        )
        self.state.context_viewer_open = True

    def open_repl_output_viewer(
        self,
        *,
        invocation_id: str,
        text: str,
        label: str,
    ) -> None:
        normalized = text.strip()
        self.state.context_selection = LiveContextSelection(
            label=label,
            raw_key=invocation_id,
            scope="tool_variable",
            source_kind="tool_variable",
            text=normalized or f"No {label} captured.",
        )
        self.state.context_viewer_open = True

    def open_text_viewer(self, *, label: str, text: str, raw_key: str = "session") -> None:
        normalized = text.strip()
        self.state.context_selection = LiveContextSelection(
            label=label,
            raw_key=raw_key,
            scope="tool_variable",
            source_kind="tool_variable",
            text=normalized or f"No {label} captured.",
        )
        self.state.context_viewer_open = True

    def open_on_deck_fixture_viewer(self) -> None:
        """Load the on-deck fixture JSON and display it in the context viewer."""
        import json as _json

        if self.state.replay_path:
            kind, value = "replay", self.state.replay_path
        elif self.state.selected_provider_fake_fixture:
            kind, value = "provider_fake", self.state.selected_provider_fake_fixture
        else:
            return

        path = resolve_fixture_file_path(kind, value)
        if path is None or not path.exists():
            text = f"Fixture file not found: {value}"
        else:
            with path.open() as fh:
                text = _json.dumps(_json.load(fh), indent=2)

        display_label = value if kind == "replay" else f"provider_fake/{value}"
        self.state.context_selection = LiveContextSelection(
            label=f"Fixture: {display_label}",
            raw_key=str(path or value),
            scope="tool_variable",
            source_kind="tool_variable",
            text=text,
        )
        self.state.context_viewer_open = True

    def close_context_viewer(self) -> None:
        self.state.context_selection = None
        self.state.context_viewer_open = False

    def select_iteration(self, pane_id: str, invocation_id: str) -> None:
        pane = self._pane_by_id(pane_id)
        if pane is None:
            return
        if invocation_id not in {inv.invocation_id for inv in pane.invocations}:
            return
        self.state.auto_follow = False
        self.state.selected_invocation_id_by_pane[pane_id] = invocation_id
        for descendant_id in self._descendant_pane_ids(pane_id):
            self.state.selected_invocation_id_by_pane.pop(descendant_id, None)
        self._refresh_run_state()

    def active_lineage(self) -> list[LivePane]:
        if self.state.snapshot is None:
            return []
        panes_by_depth = {pane.depth: pane for pane in self.state.snapshot.panes}
        lineage: list[LivePane] = []
        root = panes_by_depth.get(0)
        if root is not None:
            lineage.append(root)
        target_depth = (
            self.state.active_pane.depth
            if self.state.active_pane is not None
            else (max(panes_by_depth) if panes_by_depth else 0)
        )
        for parent_depth in range(0, target_depth):
            child_depth = parent_depth + 1
            selected = self.state.selected_fanouts_by_parent_depth.get(parent_depth)
            pane = self._find_pane(child_depth, selected)
            if pane is None and selected is None:
                pane = self._first_pane_for_depth(child_depth)
            if pane is None:
                break
            lineage.append(pane)
        return lineage

    def breadcrumbs(self) -> list[LiveBreadcrumb]:
        return [
            LiveBreadcrumb(
                depth=pane.depth,
                fanout_idx=pane.fanout_idx,
                agent_name=pane.agent_name,
                status=pane.status,
            )
            for pane in self.active_lineage()
        ]

    def banner_items(self) -> list[LiveContextBannerItem]:
        return self.loader.build_banner_items(
            self.selected_invocation(self.state.active_pane),
            lineage=self.selected_invocation_lineage(),
        )

    def invocation_tree(self) -> list[LiveInvocationNode]:
        if self.state.snapshot is None:
            return []
        roots = [pane for pane in self.state.snapshot.panes if pane.parent_pane_id is None]
        nodes: list[LiveInvocationNode] = []
        for root in sorted(roots, key=lambda item: (item.depth, item.fanout_idx or -1)):
            node = self._build_invocation_node(root, lineages=[])
            if node is not None:
                nodes.append(node)
        return nodes

    def flow_transcript(self) -> FlowTranscript:
        """Build a linearized flow transcript from the invocation tree."""
        return build_flow_transcript(self.invocation_tree())

    def session_summary(self) -> LiveSessionSummary:
        return self.loader.session_summary(self.state.selected_session_id)

    def selected_invocation(self, pane: LivePane | None) -> LiveInvocation | None:
        if pane is None or not pane.invocations:
            return None
        selected_id = self.state.selected_invocation_id_by_pane.get(pane.pane_id)
        for invocation in pane.invocations:
            if invocation.invocation_id == selected_id:
                return invocation
        return pane.invocations[-1]

    def selected_invocation_lineage(self) -> list[LiveInvocation]:
        return [
            invocation
            for invocation in (self.selected_invocation(pane) for pane in self.active_lineage())
            if invocation is not None
        ]

    def active_sibling_fanouts(self) -> list:
        pane = self.state.active_pane
        if pane is None:
            return []
        if pane.depth == 0:
            return pane.sibling_fanouts
        parent = self._find_pane(pane.depth - 1, self._selected_fanout_for_depth(pane.depth - 1))
        if parent is None:
            parent = self._first_pane_for_depth(pane.depth - 1)
        return parent.sibling_fanouts if parent is not None else []

    def _resolve_active_pane_id(self, snapshot) -> str | None:
        if snapshot.active_candidate_pane_id is None:
            return snapshot.root_pane_id
        candidate = snapshot.pane_map.get(snapshot.active_candidate_pane_id)
        if candidate is None:
            return snapshot.root_pane_id
        lineage = [pane for pane in snapshot.panes if pane.depth <= candidate.depth]
        lineage.sort(key=lambda pane: pane.depth)
        for pane in lineage:
            if pane.fanout_idx is not None and pane.depth > 0:
                self.state.selected_fanouts_by_parent_depth[pane.depth - 1] = pane.fanout_idx
        return candidate.pane_id

    def _sync_selected_fanouts_from_active(self) -> None:
        pane = self.state.active_pane
        if pane is None:
            return
        self._sync_selected_fanouts_from_pane(pane)

    def _sync_selected_fanouts_from_pane(self, pane: LivePane) -> None:
        if pane.fanout_idx is None or pane.depth == 0:
            return
        self.state.selected_fanouts_by_parent_depth[pane.depth - 1] = pane.fanout_idx

    def _clamp_active_pane(self, pane_id: str | None) -> str | None:
        if self.state.snapshot is None:
            return None
        if pane_id and pane_id in self.state.snapshot.pane_map:
            return pane_id
        return self.state.snapshot.root_pane_id

    def _pane_by_id(self, pane_id: str | None) -> LivePane | None:
        if self.state.snapshot is None or pane_id is None:
            return None
        return self.state.snapshot.pane_map.get(pane_id)

    def _find_pane(self, depth: int, fanout_idx: int | None) -> LivePane | None:
        if self.state.snapshot is None:
            return None
        for pane in self.state.snapshot.panes:
            if pane.depth != depth:
                continue
            if pane.depth == 0:
                return pane
            if fanout_idx is None or pane.fanout_idx == fanout_idx:
                return pane
        return None

    def _first_pane_for_depth(self, depth: int) -> LivePane | None:
        if self.state.snapshot is None:
            return None
        for pane in self.state.snapshot.panes:
            if pane.depth == depth:
                return pane
        return None

    def _selected_fanout_for_depth(self, parent_depth: int) -> int | None:
        return self.state.selected_fanouts_by_parent_depth.get(parent_depth)

    def _sync_selected_invocations(self, panes) -> None:
        for pane in panes:
            if pane.invocations and pane.pane_id not in self.state.selected_invocation_id_by_pane:
                self.state.selected_invocation_id_by_pane[pane.pane_id] = pane.invocations[
                    -1
                ].invocation_id

    def _descendant_pane_ids(self, pane_id: str) -> set[str]:
        if self.state.snapshot is None:
            return set()
        descendants: set[str] = set()
        frontier = [pane_id]
        while frontier:
            current = frontier.pop()
            children = [
                pane.pane_id for pane in self.state.snapshot.panes if pane.parent_pane_id == current
            ]
            for child in children:
                if child not in descendants:
                    descendants.add(child)
                    frontier.append(child)
        descendants.discard(pane_id)
        return descendants

    def _build_invocation_node(
        self,
        pane: LivePane,
        *,
        lineages: list[LiveInvocation],
        lower_bound: float = float("-inf"),
        upper_bound: float = float("inf"),
        parent_code_text: str = "",
        parent_stdout_text: str = "",
        parent_stderr_text: str = "",
    ) -> LiveInvocationNode | None:
        visible_invocations = [
            invocation
            for invocation in pane.invocations
            if lower_bound <= self._invocation_timestamp(invocation) < upper_bound
        ]
        visible_invocations = self._dedupe_invocations_by_iteration(visible_invocations)
        if not visible_invocations:
            return None
        selected = self._selected_invocation_in_window(pane, visible_invocations)
        next_upper_bound = self._next_invocation_timestamp(
            visible_invocations,
            selected,
            upper_bound,
        )
        lineage = [*lineages, selected]
        context_items = self.loader.build_banner_items(selected, lineage=lineage)
        child_nodes: list[LiveInvocationNode] = []
        if self.state.snapshot is not None:
            child_panes = [
                child for child in self.state.snapshot.panes if child.parent_pane_id == pane.pane_id
            ]
            # Children are spawned during the selected iteration's REPL execution.
            # Their timestamps fall AFTER the parent snapshot but BEFORE the next
            # iteration snapshot.  When the latest iteration is selected, use the
            # previous iteration's timestamp as lower_bound so children remain
            # visible even when auto-following to the final iteration.
            selected_ts = self._invocation_timestamp(selected)
            prev_ts = self._previous_invocation_timestamp(visible_invocations, selected)
            child_lower = prev_ts if prev_ts is not None else selected_ts
            # parent_code_text: prefer the invocation that actually dispatched
            # children (the one with REPL code), falling back to the selected.
            code_source = selected
            if not (selected.repl_expanded_code or selected.repl_submission):
                for inv in reversed(visible_invocations):
                    if inv.repl_expanded_code or inv.repl_submission:
                        code_source = inv
                        break
            for child in sorted(child_panes, key=lambda item: (item.depth, item.fanout_idx or -1)):
                child_node = self._build_invocation_node(
                    child,
                    lineages=lineage,
                    lower_bound=child_lower,
                    upper_bound=next_upper_bound,
                    parent_code_text=code_source.repl_expanded_code or code_source.repl_submission,
                    parent_stdout_text=code_source.repl_stdout,
                    parent_stderr_text=code_source.repl_stderr,
                )
                if child_node is not None:
                    child_nodes.append(child_node)
        return LiveInvocationNode(
            pane_id=pane.pane_id,
            invocation=selected,
            available_invocations=visible_invocations,
            context_items=context_items,
            child_nodes=child_nodes,
            lineage=lineage,
            parent_code_text=parent_code_text,
            parent_stdout_text=parent_stdout_text,
            parent_stderr_text=parent_stderr_text,
            invocation_context_tokens=int(selected.raw_payload.get("total_request_tokens") or 0),
        )

    @staticmethod
    def _invocation_timestamp(invocation: LiveInvocation) -> float:
        return float(invocation.raw_payload.get("timestamp") or 0.0)

    @staticmethod
    def _previous_invocation_timestamp(
        visible_invocations: list[LiveInvocation],
        selected: LiveInvocation,
    ) -> float | None:
        """Return the timestamp of the iteration before *selected*, or None."""
        selected_ts = float(selected.raw_payload.get("timestamp") or 0.0)
        prev_ts: float | None = None
        for invocation in visible_invocations:
            ts = float(invocation.raw_payload.get("timestamp") or 0.0)
            if ts < selected_ts:
                if prev_ts is None or ts > prev_ts:
                    prev_ts = ts
        return prev_ts

    def _selected_invocation_in_window(
        self,
        pane: LivePane,
        visible_invocations: list[LiveInvocation],
    ) -> LiveInvocation:
        selected_id = self.state.selected_invocation_id_by_pane.get(pane.pane_id)
        for invocation in visible_invocations:
            if invocation.invocation_id == selected_id:
                return invocation
        chosen = visible_invocations[-1]
        self.state.selected_invocation_id_by_pane[pane.pane_id] = chosen.invocation_id
        return chosen

    @staticmethod
    def _next_invocation_timestamp(
        visible_invocations: list[LiveInvocation],
        selected: LiveInvocation,
        default_upper_bound: float,
    ) -> float:
        selected_ts = float(selected.raw_payload.get("timestamp") or 0.0)
        for invocation in visible_invocations:
            ts = float(invocation.raw_payload.get("timestamp") or 0.0)
            if ts > selected_ts:
                return min(ts, default_upper_bound)
        return default_upper_bound

    @staticmethod
    def _dedupe_invocations_by_iteration(
        invocations: list[LiveInvocation],
    ) -> list[LiveInvocation]:
        by_iteration: dict[int, LiveInvocation] = {}
        for invocation in invocations:
            current = by_iteration.get(invocation.iteration)
            if current is None or (
                float(invocation.raw_payload.get("timestamp") or 0.0),
                invocation.invocation_id,
            ) > (
                float(current.raw_payload.get("timestamp") or 0.0),
                current.invocation_id,
            ):
                by_iteration[invocation.iteration] = invocation
        return [by_iteration[key] for key in sorted(by_iteration)]

    def _refresh_run_state(self) -> None:
        snapshot = self.state.snapshot
        if snapshot is None:
            self.state.run_state = None
            return
        active_pane_id = self.state.active_pane_id
        panes = [
            LivePane(
                **{
                    **pane.__dict__,
                    "is_active": pane.pane_id == active_pane_id,
                    "is_expanded": pane.pane_id == active_pane_id,
                }
            )
            for pane in snapshot.panes
        ]
        breadcrumbs = self.breadcrumbs()
        self.state.run_state = LiveRunState(
            panes=panes,
            active_pane_id=active_pane_id,
            invocation_nodes=self.invocation_tree(),
            breadcrumb=" > ".join(item.label for item in breadcrumbs),
            run_status=self.state.run_status,
            total_live_model_calls=self.state.stats.total_live_model_calls,
            active_depth=self.state.stats.active_depth,
            active_children=self.state.stats.active_children,
        )


class LiveDashboardUI:
    """Coordinate refreshable sections for the live dashboard page."""

    def __init__(self, controller: LiveDashboardController):
        self.controller = controller
        self._refreshables: list = []

    def register(self, refreshable_fn) -> None:
        self._refreshables.append(refreshable_fn)

    def refresh_all(self) -> None:
        for refreshable in self._refreshables:
            refreshable.refresh()
