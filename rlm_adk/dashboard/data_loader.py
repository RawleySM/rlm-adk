"""Dashboard data loader -- reads JSONL context snapshots.

Single source of truth: reads ``.adk/context_snapshots.jsonl`` and groups
entries into ``SessionSummary`` + ``list[IterationData]``.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from rlm_adk.dashboard.data_models import (
    ChunkCategory,
    ContextChunk,
    ContextWindow,
    IterationData,
    SessionSummary,
    estimate_tokens_for_chunks,
)

logger = logging.getLogger(__name__)


class DashboardDataLoader:
    """Loads and structures context snapshot data from JSONL.

    Single source of truth: reads .adk/context_snapshots.jsonl
    and groups entries into SessionSummary + list[IterationData].
    """

    def __init__(self, jsonl_path: str = ".adk/context_snapshots.jsonl"):
        self._path = Path(jsonl_path)

    def list_sessions(self) -> list[str]:
        """Return distinct session_ids found in the JSONL file."""
        if not self._path.exists():
            return []
        session_ids: list[str] = []
        seen: set[str] = set()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        sid = entry.get("session_id", "")
                        if sid and sid not in seen:
                            seen.add(sid)
                            session_ids.append(sid)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning("Failed to read JSONL for session listing: %s", e)
        return session_ids

    def load_session(
        self, session_id: str
    ) -> tuple[SessionSummary, list[IterationData]]:
        """Load all entries for a session, build structured data."""
        entries = self._read_entries(session_id)
        summary = self._build_summary(entries, session_id)
        iterations = self._build_iterations(entries)
        return summary, iterations

    def _read_entries(self, session_id: str) -> list[dict]:
        """Read and filter JSONL lines by session_id."""
        if not self._path.exists():
            return []
        entries: list[dict] = []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("session_id") == session_id:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning("Failed to read JSONL entries: %s", e)
        return entries

    def _build_summary(
        self, entries: list[dict], session_id: str
    ) -> SessionSummary:
        """Compute session-level aggregates from entries."""
        if not entries:
            return SessionSummary(
                session_id=session_id,
                app_name="rlm_adk",
                model="unknown",
                total_iterations=0,
                total_input_tokens=0,
                total_output_tokens=0,
                total_calls=0,
                reasoning_calls=0,
                worker_calls=0,
                start_time=0.0,
                end_time=0.0,
            )

        total_input = sum(e.get("input_tokens", 0) or 0 for e in entries)
        total_output = sum(e.get("output_tokens", 0) or 0 for e in entries)
        reasoning_entries = [e for e in entries if e.get("agent_type") == "reasoning"]
        worker_entries = [e for e in entries if e.get("agent_type") == "worker"]
        timestamps = [e.get("timestamp", 0) for e in entries]
        iterations = [e.get("iteration", 0) for e in entries if e.get("agent_type") == "reasoning"]
        max_iteration = max(iterations) if iterations else 0

        # Get model from first reasoning entry
        model = "unknown"
        for e in entries:
            m = e.get("model", "") or e.get("model_version", "")
            if m and m != "unknown":
                model = m
                break

        return SessionSummary(
            session_id=session_id,
            app_name="rlm_adk",
            model=model,
            total_iterations=max_iteration + 1,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_calls=len(entries),
            reasoning_calls=len(reasoning_entries),
            worker_calls=len(worker_entries),
            start_time=min(timestamps) if timestamps else 0.0,
            end_time=max(timestamps) if timestamps else 0.0,
        )

    def _build_iterations(self, entries: list[dict]) -> list[IterationData]:
        """Group entries by iteration, build ContextWindow objects."""
        # Group entries by iteration
        by_iteration: dict[int, list[dict]] = defaultdict(list)
        for entry in entries:
            it_idx = entry.get("iteration", 0)
            by_iteration[it_idx].append(entry)

        if not by_iteration:
            return []

        max_iter = max(by_iteration.keys())
        iterations: list[IterationData] = []

        for idx in range(max_iter + 1):
            iter_entries = by_iteration.get(idx, [])
            reasoning_window = None
            worker_windows: list[ContextWindow] = []
            reasoning_in = 0
            reasoning_out = 0
            worker_in = 0
            worker_out = 0
            timestamps: list[float] = []

            for entry in iter_entries:
                timestamps.append(entry.get("timestamp", 0))
                window = self._build_context_window(entry)
                if entry.get("agent_type") == "reasoning":
                    reasoning_window = window
                    reasoning_in += entry.get("input_tokens", 0) or 0
                    reasoning_out += entry.get("output_tokens", 0) or 0
                else:
                    worker_windows.append(window)
                    worker_in += entry.get("input_tokens", 0) or 0
                    worker_out += entry.get("output_tokens", 0) or 0

            iterations.append(
                IterationData(
                    iteration_index=idx,
                    reasoning_window=reasoning_window,
                    worker_windows=worker_windows,
                    reasoning_input_tokens=reasoning_in,
                    reasoning_output_tokens=reasoning_out,
                    worker_input_tokens=worker_in,
                    worker_output_tokens=worker_out,
                    has_workers=len(worker_windows) > 0,
                    timestamp_start=min(timestamps) if timestamps else 0.0,
                    timestamp_end=max(timestamps) if timestamps else 0.0,
                )
            )

        return iterations

    def _build_context_window(self, entry: dict) -> ContextWindow:
        """Convert a single JSONL entry to a ContextWindow."""
        chunks: list[ContextChunk] = []
        for chunk_data in entry.get("chunks", []):
            text = chunk_data.get("text", "")
            lines = text.split("\n")
            head = "\n".join(lines[:5])
            tail = "\n".join(lines[-5:]) if len(lines) > 5 else head

            try:
                category = ChunkCategory(chunk_data.get("category", "user_prompt"))
            except ValueError:
                category = ChunkCategory.USER_PROMPT

            chunk = ContextChunk(
                chunk_id=chunk_data.get("chunk_id", ""),
                category=category,
                title=chunk_data.get("title", ""),
                char_count=chunk_data.get("char_count", len(text)),
                estimated_tokens=0,  # computed below
                iteration_origin=chunk_data.get("iteration_origin", -1),
                text_preview_head=head,
                text_preview_tail=tail,
                full_text=text,
            )
            chunks.append(chunk)

        total_tokens = entry.get("input_tokens", 0) or 0
        estimate_tokens_for_chunks(chunks, total_tokens)

        return ContextWindow(
            agent_type=entry.get("agent_type", "unknown"),
            agent_name=entry.get("agent_name", "unknown"),
            iteration=entry.get("iteration", 0),
            chunks=chunks,
            total_chars=entry.get("total_chars", 0),
            total_tokens=total_tokens,
            output_tokens=entry.get("output_tokens", 0) or 0,
            model=entry.get("model", "unknown"),
        )
