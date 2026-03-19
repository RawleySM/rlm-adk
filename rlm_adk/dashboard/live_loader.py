"""Composite loader for the live recursive dashboard."""

from __future__ import annotations

import ast
import json
import logging
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rlm_adk.agent import _default_plugins, _package_dir
from rlm_adk.dashboard.live_models import (
    LiveChildSummary,
    LiveContextBannerItem,
    LiveInvocation,
    LiveModelEvent,
    LivePane,
    LiveRequestChunk,
    LiveRunSnapshot,
    LiveRunState,
    LiveRunStats,
    LiveSessionSummary,
    LiveStateItem,
    LiveToolEvent,
    LiveWatermark,
)
from rlm_adk.skills import selected_skill_summaries
from rlm_adk.state import (
    DEPTH_SCOPED_KEYS,
    DYN_REPO_URL,
    DYN_ROOT_PROMPT,
    DYN_SKILL_INSTRUCTION,
    ENABLED_SKILLS,
    REPL_EXPANDED_CODE,
    REPL_SUBMITTED_CODE,
)
from rlm_adk.utils.prompts import RLM_DYNAMIC_INSTRUCTION

logger = logging.getLogger(__name__)

_DEPTH_RE = re.compile(r"_d(\d+)")
_PROMPT_VAR_RE = re.compile(r"{([^}?]+)\??}")

_BANNER_DYNAMIC_KEYS = [DYN_REPO_URL, DYN_ROOT_PROMPT, DYN_SKILL_INSTRUCTION]
_KNOWN_DYNAMIC_KEYS = list(
    dict.fromkeys(_BANNER_DYNAMIC_KEYS + _PROMPT_VAR_RE.findall(RLM_DYNAMIC_INSTRUCTION))
)
_KNOWN_STATE_KEYS = sorted(DEPTH_SCOPED_KEYS)


def _pane_id(depth: int, fanout_idx: int | None) -> str:
    if fanout_idx is None:
        return f"d{depth}:root"
    return f"d{depth}:f{fanout_idx}"


def _depth_from_agent(agent_name: str) -> int:
    if agent_name == "reasoning_agent":
        return 0
    match = _DEPTH_RE.search(agent_name or "")
    return int(match.group(1)) if match else 0


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_jsonish(
    value_type: str,
    value_text: str | None,
    value_json: str | None,
    value_int: int | None = None,
    value_float: float | None = None,
) -> Any:
    if value_type in {"dict", "list"} and value_json:
        try:
            return json.loads(value_json)
        except json.JSONDecodeError:
            return value_json
    if value_type == "bool":
        return bool(_safe_int(value_int if value_int is not None else value_text))
    if value_type == "int":
        return _safe_int(value_int if value_int is not None else value_text)
    if value_type == "float":
        try:
            raw = value_float if value_float is not None else value_text
            return float(raw) if raw is not None else 0.0
        except (TypeError, ValueError):
            return value_text
    return value_text


def _estimate_token_count(text: str, total_chars: int, total_tokens: int) -> int:
    if not text or total_chars <= 0 or total_tokens <= 0:
        return 0
    return round(total_tokens * len(text) / total_chars)


def _display_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, indent=2, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return repr(value)
    return repr(value)


def _chunk_text(chunks: list[dict[str, Any]]) -> str:
    return "\n".join(chunk.get("text", "") for chunk in chunks if chunk.get("text"))


def _parse_tool_preview(result_preview: str | None) -> dict[str, Any]:
    if not result_preview or not result_preview.startswith("{"):
        return {}
    try:
        value = ast.literal_eval(result_preview)
    except (SyntaxError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


@dataclass
class _SessionCache:
    trace_row: dict[str, Any] | None = None
    telemetry_rows: list[dict[str, Any]] = field(default_factory=list)
    sse_rows: list[dict[str, Any]] = field(default_factory=list)
    snapshot_rows: list[dict[str, Any]] = field(default_factory=list)
    output_rows: list[dict[str, Any]] = field(default_factory=list)
    watermark: LiveWatermark = field(default_factory=LiveWatermark)


class LiveDashboardLoader:
    """Incremental loader over SQLite telemetry and JSONL snapshot streams."""

    def __init__(
        self,
        *,
        db_path: str | None = None,
        traces_db_path: str | None = None,
        snapshots_path: str | None = None,
        outputs_path: str | None = None,
    ) -> None:
        package_dir = _package_dir()
        resolved_db_path = traces_db_path or db_path
        self._db_path = Path(resolved_db_path or package_dir / ".adk" / "traces.db")
        self._snapshots_path = Path(
            snapshots_path or package_dir / ".adk" / "context_snapshots.jsonl"
        )
        self._outputs_path = Path(outputs_path or package_dir / ".adk" / "model_outputs.jsonl")
        self._cache_by_session: dict[str, _SessionCache] = {}
        self._table_columns_cache: dict[str, set[str]] = {}

    def load_run(self, session_id: str):
        """Compatibility wrapper returning a UI-ready run state."""
        snapshot = self.load_session(session_id)
        active_pane_id = snapshot.active_candidate_pane_id or snapshot.root_pane_id
        panes = list(snapshot.panes)
        pane_map = {pane.pane_id: pane for pane in panes}
        active_pane = pane_map.get(active_pane_id) if active_pane_id else None
        breadcrumb = active_pane.breadcrumb_label if active_pane is not None else ""
        return LiveRunState(
            panes=panes,
            active_pane_id=active_pane_id,
            invocation_nodes=[],
            breadcrumb=breadcrumb,
            run_status=snapshot.status,
            total_live_model_calls=snapshot.stats.total_live_model_calls,
            active_depth=snapshot.stats.active_depth,
            active_children=snapshot.stats.active_children,
        )

    def list_sessions(self) -> list[str]:
        return [session_id for session_id, _label in self.list_session_labels()]

    def list_session_labels(self) -> list[tuple[str, str]]:
        if not self._db_path.exists():
            return []
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT session_id,
                       MIN(start_time) AS created_at,
                       MAX(start_time) AS last_started_at
                FROM traces
                WHERE session_id IS NOT NULL AND session_id != ''
                GROUP BY session_id
                ORDER BY last_started_at DESC
                """
            ).fetchall()
        return [
            (session_id, self._format_session_label(session_id, created_at))
            for session_id, created_at, _last_started_at in rows
            if session_id
        ]

    def session_summary(self, session_id: str | None) -> LiveSessionSummary:
        if not session_id:
            return LiveSessionSummary(user_query="")
        cache = self._cache_by_session.get(session_id)
        trace_row = cache.trace_row if cache and cache.trace_row else {}
        sse_rows = cache.sse_rows if cache else []
        user_query = self._latest_session_text(sse_rows, "root_prompt") or str(
            trace_row.get("root_prompt_preview") or ""
        )
        enabled_skills = self._latest_session_value(sse_rows, ENABLED_SKILLS)
        if isinstance(enabled_skills, str):
            enabled_skills = [enabled_skills]
        return LiveSessionSummary(
            user_query=user_query,
            registered_skills=self._registered_skills(enabled_skills),
            registered_plugins=self._registered_plugins(
                has_context_snapshots=bool(cache and cache.snapshot_rows),
            ),
        )

    def load_session(
        self,
        session_id: str,
        *,
        previous: LiveWatermark | None = None,
    ) -> LiveRunSnapshot:
        cache = self._cache_by_session.setdefault(session_id, _SessionCache())
        self._refresh_trace_row(cache, session_id)
        if cache.trace_row is None:
            return LiveRunSnapshot(session_id=session_id, trace_id=None, status="idle")
        self._refresh_telemetry(cache)
        self._refresh_sse(cache)
        self._refresh_jsonl(
            cache,
            session_id=session_id,
            path=self._snapshots_path,
            kind="snapshot",
            previous_offset=previous.snapshot_offset if previous else None,
        )
        self._refresh_jsonl(
            cache,
            session_id=session_id,
            path=self._outputs_path,
            kind="output",
            previous_offset=previous.output_offset if previous else None,
        )
        return self._build_snapshot(session_id, cache)

    def build_banner_items(
        self,
        invocation: LiveInvocation | None,
        *,
        lineage: list[LiveInvocation] | None = None,
    ) -> list[LiveContextBannerItem]:
        if invocation is None:
            return []

        context_chunks = self._context_request_chunks(invocation, lineage=lineage)
        total_request_chars = sum(chunk.char_count for chunk in context_chunks)
        total_request_tokens = sum(chunk.token_count for chunk in context_chunks)

        request_items: dict[str, LiveContextBannerItem] = {}
        for chunk in invocation.request_chunks:
            label = chunk.title or chunk.category
            request_items[f"chunk:{chunk.chunk_id}"] = LiveContextBannerItem(
                label=label,
                raw_key=chunk.chunk_id,
                scope="request_chunk",
                present=True,
                token_count=chunk.token_count,
                token_count_is_exact=chunk.token_count_is_exact,
                source_kind="request_chunk",
                display_value_preview=chunk.preview,
            )

        state_lookup = {
            item.base_key: item for item in invocation.state_items if item.depth == invocation.depth
        }
        banner_items: list[LiveContextBannerItem] = []

        for key in _KNOWN_DYNAMIC_KEYS:
            value = self._extract_dynamic_value(key, context_chunks)
            present = bool(value.strip())
            token_count = _estimate_token_count(
                value,
                total_request_chars,
                total_request_tokens,
            )
            banner_items.append(
                LiveContextBannerItem(
                    label=key,
                    raw_key=key,
                    scope="dynamic_instruction_param",
                    present=present,
                    token_count=token_count,
                    token_count_is_exact=False,
                    source_kind="dynamic_instruction_param",
                    display_value_preview=value[:240],
                )
            )

        for key in _KNOWN_STATE_KEYS:
            item = state_lookup.get(key)
            present = False
            preview = ""
            display_text = ""
            token_count = 0
            if item is not None:
                display_text = _display_text(item.value)
                preview = display_text[:240]
                present = bool(display_text)
                token_count = _estimate_token_count(
                    display_text,
                    total_request_chars,
                    total_request_tokens,
                )
            banner_items.append(
                LiveContextBannerItem(
                    label=self._depth_scoped_label(key, invocation.depth),
                    raw_key=key,
                    scope="state_key",
                    present=present,
                    token_count=token_count,
                    token_count_is_exact=False,
                    source_kind="state_key",
                    display_value_preview=preview,
                )
            )

        banner_items.extend(request_items.values())
        return banner_items

    def resolve_banner_item_text(
        self,
        invocation: LiveInvocation | None,
        item: LiveContextBannerItem,
        *,
        lineage: list[LiveInvocation] | None = None,
    ) -> str:
        if invocation is None:
            return "No active pane context available."

        if item.source_kind == "request_chunk":
            for chunk in invocation.request_chunks:
                if chunk.chunk_id == item.raw_key:
                    return chunk.text or f"No text captured for {item.label}."
            return f"No request chunk captured for {item.label}."

        if item.source_kind == "dynamic_instruction_param":
            value = self._extract_dynamic_value(
                item.raw_key,
                self._context_request_chunks(invocation, lineage=lineage),
            )
            return value or f"No dynamic instruction text captured for {item.label}."

        if item.source_kind == "state_key":
            for state_item in invocation.state_items:
                if state_item.depth == invocation.depth and state_item.base_key == item.raw_key:
                    text = _display_text(state_item.value)
                    return text or f"No state text captured for {item.label}."
            return f"No state value captured for {item.label}."

        return item.display_value_preview or item.raw_key

    @staticmethod
    def _latest_session_text(sse_rows: list[dict[str, Any]], key: str) -> str:
        value = LiveDashboardLoader._latest_session_value(sse_rows, key)
        text = _display_text(value).strip()
        return text

    @staticmethod
    def _latest_session_value(sse_rows: list[dict[str, Any]], key: str) -> Any:
        for row in reversed(sse_rows):
            if row.get("state_key") != key:
                continue
            value = _parse_jsonish(
                row.get("value_type", "str"),
                row.get("value_text"),
                row.get("value_json"),
                row.get("value_int"),
                row.get("value_float"),
            )
            if value not in (None, "", [], {}):
                return value
        return None

    @staticmethod
    def _registered_skills(enabled_skills: Any = None) -> list[tuple[str, str]]:
        try:
            return selected_skill_summaries(enabled_skills)
        except ValueError:
            return selected_skill_summaries(None)

    @staticmethod
    def _registered_plugins(
        *,
        has_context_snapshots: bool,
    ) -> list[tuple[str, str]]:
        plugins = {
            type(plugin).__name__: type(plugin).__doc__ or "" for plugin in _default_plugins()
        }
        if has_context_snapshots:
            plugins.setdefault(
                "ContextWindowSnapshotPlugin",
                "Captures the exact model-facing request chunks and outputs.",
            )
        return sorted(
            (
                name,
                " ".join(description.strip().split()),
            )
            for name, description in plugins.items()
        )

    def _refresh_trace_row(self, cache: _SessionCache, session_id: str) -> None:
        if not self._db_path.exists():
            return
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT trace_id, session_id, app_name, status, start_time, end_time,
                       total_calls, config_json, root_prompt_preview
                FROM traces
                WHERE session_id = ?
                ORDER BY start_time DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        cache.trace_row = dict(row) if row is not None else None
        if cache.trace_row and cache.watermark.trace_id != cache.trace_row["trace_id"]:
            cache.telemetry_rows.clear()
            cache.sse_rows.clear()
            cache.snapshot_rows.clear()
            cache.output_rows.clear()
            cache.watermark = LiveWatermark(trace_id=cache.trace_row["trace_id"])

    @staticmethod
    def _format_session_label(session_id: str, created_at: float | None) -> str:
        if created_at is None:
            return session_id
        created_text = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
        return f"{created_text} | {session_id}"

    def _refresh_telemetry(self, cache: _SessionCache) -> None:
        if not self._db_path.exists() or not cache.trace_row:
            return
        preferred_columns = [
            "telemetry_id",
            "trace_id",
            "event_type",
            "agent_name",
            "iteration",
            "depth",
            "call_number",
            "start_time",
            "end_time",
            "duration_ms",
            "model",
            "input_tokens",
            "output_tokens",
            "thought_tokens",
            "finish_reason",
            "num_contents",
            "agent_type",
            "prompt_chars",
            "system_chars",
            "tool_name",
            "tool_args_keys",
            "result_preview",
            "repl_has_errors",
            "repl_has_output",
            "repl_llm_calls",
            "repl_stdout_len",
            "repl_stderr_len",
            "repl_trace_summary",
            "skill_instruction",
            "result_payload",
            "repl_stdout",
            "repl_stderr",
            "status",
            "error_type",
            "error_message",
        ]
        available_columns = self._table_columns("telemetry")
        selected_columns = [column for column in preferred_columns if column in available_columns]
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT {", ".join(selected_columns)}
                FROM telemetry
                WHERE trace_id = ? AND start_time > ?
                ORDER BY start_time
                """,
                (cache.trace_row["trace_id"], cache.watermark.latest_telemetry_time),
            ).fetchall()
        if rows:
            cache.telemetry_rows.extend(dict(row) for row in rows)
            cache.watermark = LiveWatermark(
                trace_id=cache.watermark.trace_id,
                latest_telemetry_time=max(row["start_time"] for row in rows),
                latest_sse_seq=cache.watermark.latest_sse_seq,
                snapshot_offset=cache.watermark.snapshot_offset,
                output_offset=cache.watermark.output_offset,
            )

    def _refresh_sse(self, cache: _SessionCache) -> None:
        if not self._db_path.exists() or not cache.trace_row:
            return
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT seq, event_time, state_key, key_depth, key_fanout,
                       value_type, value_int, value_float, value_text, value_json
                FROM session_state_events
                WHERE trace_id = ? AND seq > ?
                ORDER BY seq
                """,
                (cache.trace_row["trace_id"], cache.watermark.latest_sse_seq),
            ).fetchall()
        if rows:
            cache.sse_rows.extend(dict(row) for row in rows)
            cache.watermark = LiveWatermark(
                trace_id=cache.watermark.trace_id,
                latest_telemetry_time=cache.watermark.latest_telemetry_time,
                latest_sse_seq=max(row["seq"] for row in rows),
                snapshot_offset=cache.watermark.snapshot_offset,
                output_offset=cache.watermark.output_offset,
            )

    def _refresh_jsonl(
        self,
        cache: _SessionCache,
        *,
        session_id: str,
        path: Path,
        kind: str,
        previous_offset: int | None,
    ) -> None:
        if not path.exists():
            return
        offset = (
            cache.watermark.snapshot_offset if kind == "snapshot" else cache.watermark.output_offset
        )
        if previous_offset is not None and previous_offset < offset:
            offset = previous_offset
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(offset)
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("session_id") != session_id:
                    continue
                target = cache.snapshot_rows if kind == "snapshot" else cache.output_rows
                target.append(payload)
            end_offset = handle.tell()
        cache.watermark = LiveWatermark(
            trace_id=cache.watermark.trace_id,
            latest_telemetry_time=cache.watermark.latest_telemetry_time,
            latest_sse_seq=cache.watermark.latest_sse_seq,
            snapshot_offset=end_offset if kind == "snapshot" else cache.watermark.snapshot_offset,
            output_offset=end_offset if kind == "output" else cache.watermark.output_offset,
        )

    def _build_snapshot(self, session_id: str, cache: _SessionCache) -> LiveRunSnapshot:
        trace_row = cache.trace_row or {}
        snapshots = sorted(cache.snapshot_rows, key=lambda row: row.get("timestamp", 0.0))
        outputs = sorted(cache.output_rows, key=lambda row: row.get("timestamp", 0.0))
        telemetry = sorted(cache.telemetry_rows, key=lambda row: row.get("start_time", 0.0))
        sse_rows = sorted(cache.sse_rows, key=lambda row: row.get("seq", -1))

        child_summaries = self._build_child_summaries(sse_rows)
        fanout_by_snapshot = self._match_child_summaries(snapshots, child_summaries)
        state_by_depth = self._latest_state_by_depth(sse_rows)
        outputs_by_key = {self._event_key(row): row for row in outputs}
        tool_events_by_depth = self._tool_events_by_depth(telemetry)
        model_events_by_depth = defaultdict(list)
        for row in telemetry:
            if row.get("event_type") != "model_call":
                continue
            depth = _depth_from_agent(row.get("agent_name") or "")
            model_events_by_depth[depth].append(row)

        pane_invocations: dict[tuple[int, int | None], list[LiveInvocation]] = defaultdict(list)
        pane_last_activity: dict[tuple[int, int | None], float] = defaultdict(float)

        for snapshot in snapshots:
            depth = _depth_from_agent(snapshot.get("agent_name", ""))
            fanout_idx = fanout_by_snapshot.get(id(snapshot))
            if depth > 0 and fanout_idx is None:
                fanout_idx = 0
            pane_key = (depth, fanout_idx)
            live_invocation = self._build_invocation(
                snapshot=snapshot,
                output_row=outputs_by_key.get(self._event_key(snapshot)),
                state_items=state_by_depth.get(depth, []),
                own_summaries=child_summaries.get(depth, []),
                child_summaries=child_summaries.get(depth + 1, []),
                tool_rows=tool_events_by_depth.get(depth, []),
                model_rows=model_events_by_depth.get(depth, []),
                fanout_idx=fanout_idx,
            )
            pane_invocations[pane_key].append(live_invocation)
            pane_last_activity[pane_key] = max(
                pane_last_activity[pane_key],
                live_invocation.raw_payload.get("timestamp", 0.0),
            )

        if not pane_invocations and trace_row:
            telemetry_model_count = sum(
                1 for r in cache.telemetry_rows if r.get("event_type") == "model_call"
            )
            status = self._normalize_status(
                trace_row.get("status"),
                total_calls=trace_row.get("total_calls", 0),
                telemetry_model_count=telemetry_model_count,
            )
            return LiveRunSnapshot(
                session_id=session_id,
                trace_id=trace_row.get("trace_id"),
                status=status,
                started_at=trace_row.get("start_time", 0.0),
                finished_at=trace_row.get("end_time", 0.0) or 0.0,
                watermark=cache.watermark,
            )

        panes: list[LivePane] = []
        pane_map: dict[str, LivePane] = {}
        active_candidate: str | None = None
        ordered_keys = sorted(
            pane_invocations.keys(), key=lambda item: (item[0], item[1] is None, item[1] or -1)
        )

        for depth, fanout_idx in ordered_keys:
            invocations = pane_invocations[(depth, fanout_idx)]
            latest = invocations[-1]
            child_options = child_summaries.get(depth + 1, [])
            sibling_fanouts = [child for child in child_options if child.parent_depth == depth]
            status = latest.status
            if status == "completed" and trace_row.get("status") == "running":
                status = "idle"
            pane = LivePane(
                pane_id=_pane_id(depth, fanout_idx),
                invocation_id=latest.invocation_id,
                depth=depth,
                fanout_idx=fanout_idx,
                agent_name=latest.agent_name,
                model=latest.model,
                model_version=latest.model_version,
                status=status,
                is_active=False,
                is_expanded=False,
                iteration=max(inv.iteration for inv in invocations),
                latest_tool_call_number=len(latest.tool_events) or None,
                input_tokens=sum(inv.input_tokens for inv in invocations),
                output_tokens=sum(inv.output_tokens for inv in invocations),
                thought_tokens=sum(inv.thought_tokens for inv in invocations),
                elapsed_ms=sum(inv.elapsed_ms for inv in invocations),
                latest_event_time=max(inv.raw_payload.get("timestamp", 0.0) for inv in invocations),
                parent_pane_id=_pane_id(depth - 1, fanout_idx if depth > 1 else None)
                if depth > 0
                else None,
                request_chunks=latest.request_chunks,
                state_items=latest.state_items,
                child_summaries=latest.child_summaries,
                repl_submission=latest.repl_submission,
                repl_expanded_code=latest.repl_expanded_code,
                repl_stdout=latest.repl_stdout,
                repl_stderr=latest.repl_stderr,
                reasoning_visible_text=latest.reasoning_visible_text,
                reasoning_thought_text=latest.reasoning_thought_text,
                structured_output=latest.structured_output,
                raw_payload=latest.raw_payload,
                model_events=latest.model_events,
                tool_events=latest.tool_events,
                sibling_fanouts=sibling_fanouts,
                invocations=invocations,
            )
            pane_map[pane.pane_id] = pane
            panes.append(pane)
            if active_candidate is None or (
                pane.latest_event_time,
                pane.depth,
            ) > (
                pane_map[active_candidate].latest_event_time if active_candidate else 0.0,
                pane_map[active_candidate].depth if active_candidate else -1,
            ):
                active_candidate = pane.pane_id

        stats = LiveRunStats(
            total_live_model_calls=sum(
                1 for row in telemetry if row.get("event_type") == "model_call"
            ),
            active_depth=pane_map[active_candidate].depth if active_candidate else 0,
            active_children=len(
                [
                    child
                    for child in child_summaries.get(
                        (pane_map[active_candidate].depth if active_candidate else 0) + 1, []
                    )
                    if child.status == "running"
                ]
            ),
        )
        telemetry_model_count = sum(
            1 for r in cache.telemetry_rows if r.get("event_type") == "model_call"
        )
        status = self._normalize_status(
            trace_row.get("status"),
            total_calls=trace_row.get("total_calls", 0),
            telemetry_model_count=telemetry_model_count,
        )
        return LiveRunSnapshot(
            session_id=session_id,
            trace_id=trace_row.get("trace_id"),
            status=status,
            started_at=trace_row.get("start_time", 0.0),
            finished_at=trace_row.get("end_time", 0.0) or 0.0,
            panes=panes,
            pane_map=pane_map,
            pane_order=[pane.pane_id for pane in panes],
            root_pane_id=_pane_id(0, None) if _pane_id(0, None) in pane_map else None,
            active_candidate_pane_id=active_candidate,
            stats=stats,
            watermark=cache.watermark,
        )

    def _build_child_summaries(
        self, sse_rows: list[dict[str, Any]]
    ) -> dict[int, list[LiveChildSummary]]:
        grouped: dict[int, list[LiveChildSummary]] = defaultdict(list)
        for row in sse_rows:
            if row.get("state_key") != "obs:child_summary":
                continue
            payload = _parse_jsonish(
                row.get("value_type", "str"),
                row.get("value_text"),
                row.get("value_json"),
                row.get("value_int"),
                row.get("value_float"),
            )
            if not isinstance(payload, dict):
                continue
            depth = _safe_int(payload.get("depth"), row.get("key_depth", 0))
            fanout_idx = _safe_int(payload.get("fanout_idx"), row.get("key_fanout", 0))
            status = "error" if payload.get("error") else "completed"
            grouped[depth].append(
                LiveChildSummary(
                    parent_depth=max(depth - 1, 0),
                    depth=depth,
                    fanout_idx=fanout_idx,
                    model=payload.get("model"),
                    status=status,
                    error=bool(payload.get("error")),
                    elapsed_ms=float(payload.get("elapsed_ms") or 0.0),
                    prompt=str(payload.get("prompt") or payload.get("prompt_preview") or ""),
                    prompt_preview=str(payload.get("prompt_preview") or ""),
                    result_text=str(
                        payload.get("result_text") or payload.get("result_preview") or ""
                    ),
                    final_answer=str(payload.get("final_answer") or ""),
                    visible_output_text=str(
                        payload.get("visible_output_text")
                        or payload.get("visible_output_preview")
                        or ""
                    ),
                    visible_output_preview=str(payload.get("visible_output_preview") or ""),
                    thought_text=str(
                        payload.get("thought_text") or payload.get("thought_preview") or ""
                    ),
                    thought_preview=str(payload.get("thought_preview") or ""),
                    raw_output=payload.get("raw_output"),
                    raw_output_preview=str(payload.get("raw_output_preview") or ""),
                    input_tokens=_safe_int(payload.get("input_tokens")),
                    output_tokens=_safe_int(payload.get("output_tokens")),
                    thought_tokens=_safe_int(payload.get("thought_tokens")),
                    finish_reason=payload.get("finish_reason"),
                    error_message=payload.get("error_message"),
                    structured_output=payload.get("structured_output")
                    if isinstance(payload.get("structured_output"), dict)
                    else None,
                    event_time=float(row.get("event_time") or 0.0),
                    seq=_safe_int(row.get("seq")),
                )
            )
        for summaries in grouped.values():
            summaries.sort(key=lambda item: (item.event_time, item.seq))
        return grouped

    def _match_child_summaries(
        self,
        snapshots: list[dict[str, Any]],
        child_summaries: dict[int, list[LiveChildSummary]],
    ) -> dict[int, int]:
        mapping: dict[int, int] = {}
        unmatched: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for snapshot in snapshots:
            depth = _depth_from_agent(snapshot.get("agent_name", ""))
            unmatched[depth].append(snapshot)
        for depth, summaries in child_summaries.items():
            candidates = unmatched.get(depth, [])
            used: set[int] = set()
            for summary in summaries:
                matched_idx: int | None = None
                for idx, snapshot in enumerate(candidates):
                    if idx in used:
                        continue
                    prompt_text = _chunk_text(snapshot.get("chunks", []))
                    prompt_preview = summary.prompt_preview.strip()
                    if prompt_preview and (
                        prompt_preview[:120] in prompt_text or prompt_text[:120] in prompt_preview
                    ):
                        matched_idx = idx
                        break
                if matched_idx is None and candidates:
                    eligible = [
                        (idx, snapshot)
                        for idx, snapshot in enumerate(candidates)
                        if idx not in used
                        and snapshot.get("timestamp", 0.0) <= summary.event_time + 0.001
                    ]
                    if eligible:
                        matched_idx = max(
                            eligible,
                            key=lambda pair: pair[1].get("timestamp", 0.0),
                        )[0]
                if matched_idx is not None:
                    used.add(matched_idx)
                    mapping[id(candidates[matched_idx])] = summary.fanout_idx
        return mapping

    def _latest_state_by_depth(
        self, sse_rows: list[dict[str, Any]]
    ) -> dict[int, list[LiveStateItem]]:
        latest: dict[tuple[int, str], LiveStateItem] = {}
        for row in sse_rows:
            base_key = row.get("state_key", "")
            depth = _safe_int(row.get("key_depth"))
            value = _parse_jsonish(
                row.get("value_type", "str"),
                row.get("value_text"),
                row.get("value_json"),
                row.get("value_int"),
                row.get("value_float"),
            )
            item = LiveStateItem(
                raw_key=self._depth_scoped_label(base_key, depth),
                base_key=base_key,
                depth=depth,
                fanout_idx=row.get("key_fanout"),
                value=value,
                value_type=row.get("value_type", "str"),
                event_time=float(row.get("event_time") or 0.0),
                seq=_safe_int(row.get("seq")),
            )
            latest[(depth, base_key)] = item
        grouped: dict[int, list[LiveStateItem]] = defaultdict(list)
        for item in latest.values():
            grouped[item.depth].append(item)
        for items in grouped.values():
            items.sort(key=lambda item: item.seq)
        return grouped

    def _tool_events_by_depth(
        self, telemetry_rows: list[dict[str, Any]]
    ) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in telemetry_rows:
            if row.get("event_type") != "tool_call":
                continue
            depth = _safe_int(
                row.get("depth"),
                _depth_from_agent(row.get("agent_name") or ""),
            )
            grouped[depth].append(row)
        for rows in grouped.values():
            rows.sort(key=lambda row: row.get("start_time", 0.0))
        return grouped

    def _build_invocation(
        self,
        *,
        snapshot: dict[str, Any],
        output_row: dict[str, Any] | None,
        state_items: list[LiveStateItem],
        own_summaries: list[LiveChildSummary],
        child_summaries: list[LiveChildSummary],
        tool_rows: list[dict[str, Any]],
        model_rows: list[dict[str, Any]],
        fanout_idx: int | None,
    ) -> LiveInvocation:
        depth = _depth_from_agent(snapshot.get("agent_name", ""))
        chunks = self._build_request_chunks(snapshot)
        timestamp = float(snapshot.get("timestamp") or 0.0)
        request_total_tokens = _safe_int(snapshot.get("input_tokens"))
        request_total_chars = sum(chunk.char_count for chunk in chunks)

        relevant_models = [
            self._build_model_event(row, output_row, fanout_idx)
            for row in model_rows
            if row.get("agent_name") == snapshot.get("agent_name")
            and abs((row.get("start_time") or 0.0) - timestamp) < 0.01
        ]
        relevant_tools = [
            self._build_tool_event(row, depth, fanout_idx)
            for row in tool_rows
            if row.get("agent_name") == snapshot.get("agent_name")
            and row.get("start_time", 0.0) >= timestamp
        ]

        latest_repl = {
            item.base_key: item
            for item in state_items
            if item.base_key in {REPL_SUBMITTED_CODE, REPL_EXPANDED_CODE}
        }
        matching_children = [child for child in child_summaries if child.parent_depth == depth]
        tool_payload = (relevant_tools[-1].payload or {}) if relevant_tools else {}
        repl_stdout = str(tool_payload.get("stdout") or "")
        repl_stderr = str(tool_payload.get("stderr") or "")
        if not repl_stdout and relevant_tools and relevant_tools[-1].result_preview:
            repl_stdout = relevant_tools[-1].result_preview

        structured_output = None
        pane_summary: LiveChildSummary | None = None
        for child in own_summaries:
            if child.depth == depth and child.fanout_idx == (fanout_idx or 0):
                pane_summary = child
                structured_output = child.structured_output
                break

        status: str = "completed"
        if any(model.status == "error" for model in relevant_models):
            status = "error"
        elif any(tool.repl_has_errors for tool in relevant_tools):
            status = "error"

        return LiveInvocation(
            invocation_id=f"{snapshot.get('agent_name')}:{timestamp}",
            pane_id=_pane_id(depth, fanout_idx),
            depth=depth,
            fanout_idx=fanout_idx,
            agent_name=str(snapshot.get("agent_name") or "unknown"),
            model=str(snapshot.get("model_version") or snapshot.get("model") or "unknown"),
            model_version=snapshot.get("model_version"),
            status=status,  # type: ignore[arg-type]
            iteration=_safe_int(snapshot.get("iteration")),
            input_tokens=request_total_tokens,
            output_tokens=_safe_int(snapshot.get("output_tokens")),
            thought_tokens=_safe_int(snapshot.get("thoughts_tokens")),
            elapsed_ms=sum(event.duration_ms or 0.0 for event in relevant_models),
            request_chunks=chunks,
            state_items=state_items,
            child_summaries=matching_children,
            repl_submission=str(
                latest_repl.get(REPL_SUBMITTED_CODE).value
                if latest_repl.get(REPL_SUBMITTED_CODE)
                else ""
            ),
            repl_expanded_code=str(
                latest_repl.get(REPL_EXPANDED_CODE).value
                if latest_repl.get(REPL_EXPANDED_CODE)
                else ""
            ),
            repl_stdout=repl_stdout,
            repl_stderr=repl_stderr,
            reasoning_visible_text=str(
                (output_row or {}).get("output_text")
                or (pane_summary.visible_output_text if pane_summary is not None else "")
            ),
            reasoning_thought_text=str(
                pane_summary.thought_text if pane_summary is not None else ""
            ),
            structured_output=structured_output,
            raw_payload={
                "timestamp": timestamp,
                "total_request_chars": request_total_chars,
                "total_request_tokens": request_total_tokens,
                "snapshot": snapshot,
                "output": output_row or {},
                "summary": pane_summary.raw_output if pane_summary is not None else None,
            },
            model_events=relevant_models,
            tool_events=relevant_tools,
        )

    def _build_request_chunks(self, snapshot: dict[str, Any]) -> list[LiveRequestChunk]:
        chunks: list[LiveRequestChunk] = []
        total_tokens = _safe_int(snapshot.get("input_tokens"))
        total_chars = sum(
            _safe_int(chunk.get("char_count"), len(chunk.get("text", "")))
            for chunk in snapshot.get("chunks", [])
        )
        for chunk in snapshot.get("chunks", []):
            text = chunk.get("text", "")
            char_count = _safe_int(chunk.get("char_count"), len(text))
            token_count = _estimate_token_count(text, total_chars, total_tokens)
            chunks.append(
                LiveRequestChunk(
                    chunk_id=str(chunk.get("chunk_id") or ""),
                    category=str(chunk.get("category") or "unknown"),
                    title=str(chunk.get("title") or ""),
                    text=text,
                    char_count=char_count,
                    token_count=token_count,
                    token_count_is_exact=False,
                    iteration_origin=_safe_int(chunk.get("iteration_origin"), -1),
                )
            )
        return chunks

    def _build_model_event(
        self,
        row: dict[str, Any],
        output_row: dict[str, Any] | None,
        fanout_idx: int | None,
    ) -> LiveModelEvent:
        status = "error" if row.get("status") == "error" else "completed"
        model_version = (output_row or {}).get("model_version")
        return LiveModelEvent(
            telemetry_id=str(row.get("telemetry_id") or ""),
            agent_name=str(row.get("agent_name") or "unknown"),
            depth=_depth_from_agent(row.get("agent_name") or ""),
            fanout_idx=fanout_idx,
            iteration=_safe_int(row.get("iteration")),
            call_number=row.get("call_number"),
            start_time=float(row.get("start_time") or 0.0),
            end_time=float(row.get("end_time") or 0.0) or None,
            duration_ms=float(row.get("duration_ms") or 0.0) or None,
            model=str(row.get("model") or "unknown"),
            model_version=model_version,
            status=status,  # type: ignore[arg-type]
            finish_reason=row.get("finish_reason"),
            input_tokens=_safe_int(row.get("input_tokens")),
            output_tokens=_safe_int(row.get("output_tokens")),
            thought_tokens=_safe_int(row.get("thought_tokens")),
            prompt_chars=_safe_int(row.get("prompt_chars")),
            system_chars=_safe_int(row.get("system_chars")),
            num_contents=_safe_int(row.get("num_contents")),
            skill_instruction=row.get("skill_instruction"),
        )

    def _build_tool_event(
        self,
        row: dict[str, Any],
        depth: int,
        fanout_idx: int | None,
    ) -> LiveToolEvent:
        payload = _parse_tool_preview(row.get("result_preview"))
        result_payload = row.get("result_payload")
        if result_payload:
            try:
                payload = json.loads(result_payload)
            except json.JSONDecodeError:
                payload = {"raw": result_payload}
        if row.get("repl_stdout") is not None:
            payload["stdout"] = row.get("repl_stdout") or ""
        if row.get("repl_stderr") is not None:
            payload["stderr"] = row.get("repl_stderr") or ""
        return LiveToolEvent(
            telemetry_id=str(row.get("telemetry_id") or ""),
            agent_name=str(row.get("agent_name") or "unknown"),
            depth=depth,
            fanout_idx=fanout_idx,
            tool_name=str(row.get("tool_name") or "unknown"),
            start_time=float(row.get("start_time") or 0.0),
            end_time=float(row.get("end_time") or 0.0) or None,
            duration_ms=float(row.get("duration_ms") or 0.0) or None,
            result_preview=str(row.get("result_preview") or ""),
            repl_has_errors=bool(row.get("repl_has_errors")),
            repl_has_output=bool(row.get("repl_has_output")),
            repl_llm_calls=_safe_int(row.get("repl_llm_calls")),
            repl_stdout_len=_safe_int(row.get("repl_stdout_len")),
            repl_stderr_len=_safe_int(row.get("repl_stderr_len")),
            repl_trace_summary=(
                json.loads(row["repl_trace_summary"]) if row.get("repl_trace_summary") else None
            ),
            payload=payload if payload else None,
        )

    @staticmethod
    def _event_key(row: dict[str, Any]) -> tuple[str, int, int]:
        return (
            str(row.get("agent_name") or ""),
            _safe_int(row.get("iteration")),
            round(float(row.get("timestamp") or row.get("start_time") or 0.0), 3),
        )

    @staticmethod
    def _normalize_status(
        status: str | None, *, total_calls: Any, telemetry_model_count: int = 0
    ) -> str:
        if status == "completed":
            return "completed"
        if status == "error":
            return "error"
        effective_calls = _safe_int(total_calls) or telemetry_model_count
        return "running" if effective_calls > 0 else "idle"

    @staticmethod
    def _format_token_suffix(token_count: int, exact: bool) -> str:
        prefix = "" if exact else "~"
        return f"{prefix}{token_count} tok"

    @staticmethod
    def _context_request_chunks(
        invocation: LiveInvocation,
        *,
        lineage: list[LiveInvocation] | None = None,
    ) -> list[LiveRequestChunk]:
        if not lineage:
            return invocation.request_chunks
        chunks: list[LiveRequestChunk] = []
        seen_ids: set[str] = set()
        for lineage_invocation in lineage:
            for chunk in lineage_invocation.request_chunks:
                if chunk.chunk_id in seen_ids:
                    continue
                chunks.append(chunk)
                seen_ids.add(chunk.chunk_id)
        return chunks or invocation.request_chunks

    @staticmethod
    def _depth_scoped_label(base_key: str, depth: int) -> str:
        return base_key if depth == 0 else f"{base_key}@d{depth}"

    @staticmethod
    def _extract_dynamic_value(key: str, chunks: list[LiveRequestChunk]) -> str:
        labels = {
            DYN_REPO_URL: "Repository URL:",
            DYN_ROOT_PROMPT: "Original query:",
            "test_context": "Additional context:",
            DYN_SKILL_INSTRUCTION: "Skill instruction:",
        }
        for chunk in chunks:
            text = chunk.text
            label = labels.get(key)
            if label and label in text:
                for line in text.splitlines():
                    if line.startswith(label):
                        return line[len(label) :].strip()
        return ""

    def _table_columns(self, table_name: str) -> set[str]:
        cached = self._table_columns_cache.get(table_name)
        if cached is not None:
            return cached
        if not self._db_path.exists():
            return set()
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = {row[1] for row in rows}
        self._table_columns_cache[table_name] = columns
        return columns
