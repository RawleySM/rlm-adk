"""REPL execution tracing infrastructure.

Provides invisible instrumentation for REPL code block execution:
- REPLTrace: Per-code-block trace accumulator (timing, LLM calls, vars, memory)
- DataFlowTracker: Detects when one llm_query response feeds into a subsequent prompt
- Trace header/footer strings for optional code injection (trace_level >= 2)

Trace levels (RLM_REPL_TRACE env var):
- 0: Off (default) - no tracing overhead
- 1: LLM call timing + variable snapshots + data flow tracking
- 2: + tracemalloc memory tracking via injected header/footer
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class REPLTrace:
    """Invisible trace accumulator for a single REPL code block execution."""

    start_time: float = 0.0
    end_time: float = 0.0
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    var_snapshots: list[dict[str, Any]] = field(default_factory=list)
    peak_memory_bytes: int = 0
    exceptions: list[dict[str, Any]] = field(default_factory=list)
    data_flow_edges: list[tuple[int, int]] = field(default_factory=list)
    execution_mode: str = "sync"  # "sync" | "async"
    submitted_code_chars: int = 0
    submitted_code_hash: str | None = None
    submitted_code_preview: str = ""
    _call_counter: int = field(default=0, repr=False)

    def record_llm_start(self, call_index: int, prompt: str, call_type: str = "single") -> None:
        """Record the start of an LLM call."""
        self.llm_calls.append({
            "index": call_index,
            "type": call_type,
            "start_time": time.perf_counter(),
            "prompt_len": len(prompt),
        })

    def record_llm_end(
        self,
        call_index: int,
        response: str,
        elapsed_ms: float,
        error: bool = False,
        **extra: Any,
    ) -> None:
        """Record the end of an LLM call, updating the existing entry."""
        for entry in self.llm_calls:
            if entry.get("index") == call_index:
                entry["elapsed_ms"] = round(elapsed_ms, 2)
                entry["response_len"] = len(response)
                entry["error"] = error
                entry.update(extra)
                return
        # If no matching start entry, create a new one
        self.llm_calls.append({
            "index": call_index,
            "elapsed_ms": round(elapsed_ms, 2),
            "response_len": len(response),
            "error": error,
            **extra,
        })

    def snapshot_vars(self, namespace: dict[str, Any], label: str = "") -> None:
        """Capture a snapshot of user-visible variables."""
        snapshot: dict[str, Any] = {"label": label, "time": time.perf_counter()}
        var_summary: dict[str, str] = {}
        for k, v in namespace.items():
            if k.startswith("_"):
                continue
            try:
                type_name = type(v).__name__
                if isinstance(v, (str, int, float, bool)):
                    var_summary[k] = f"{type_name}({repr(v)[:80]})"
                elif isinstance(v, (list, dict, tuple, set)):
                    var_summary[k] = f"{type_name}(len={len(v)})"
                else:
                    var_summary[k] = type_name
            except Exception:
                var_summary[k] = "?"
        snapshot["vars"] = var_summary
        self.var_snapshots.append(snapshot)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "wall_time_ms": round(max(0, self.end_time - self.start_time) * 1000, 2) if self.start_time and self.end_time else 0,
            "execution_mode": self.execution_mode,
            "submitted_code_chars": self.submitted_code_chars,
            "submitted_code_hash": self.submitted_code_hash,
            "submitted_code_preview": self.submitted_code_preview,
            "llm_calls": self.llm_calls,
            "var_snapshots": self.var_snapshots,
            "peak_memory_bytes": self.peak_memory_bytes,
            "exceptions": self.exceptions,
            "data_flow_edges": self.data_flow_edges,
        }

    def summary(self) -> dict[str, Any]:
        """Compact summary for LAST_REPL_RESULT enrichment."""
        return {
            "wall_time_ms": round(max(0, self.end_time - self.start_time) * 1000, 2) if self.start_time and self.end_time else 0,
            "llm_call_count": len(self.llm_calls),
            "failed_llm_calls": sum(1 for c in self.llm_calls if c.get("error")),
            "peak_memory_bytes": self.peak_memory_bytes,
            "data_flow_edges": len(self.data_flow_edges),
            "submitted_code_chars": self.submitted_code_chars,
            "submitted_code_hash": self.submitted_code_hash,
        }


class DataFlowTracker:
    """Detects when one llm_query() response feeds into a subsequent prompt.

    Uses substring fingerprinting: if a significant substring of a previous
    response appears in a later prompt, we record a data flow edge.
    """

    def __init__(self, min_fingerprint_len: int = 40):
        self._responses: dict[int, str] = {}  # call_index -> response text
        self._edges: list[tuple[int, int]] = []
        self._min_len = min_fingerprint_len

    def register_response(self, call_index: int, response: str) -> None:
        """Register a completed LLM response for future fingerprint matching."""
        self._responses[call_index] = response

    def check_prompt(self, call_index: int, prompt: str) -> None:
        """Check if this prompt contains substrings from previous responses."""
        if len(prompt) < self._min_len:
            return
        for prev_index, prev_response in self._responses.items():
            if prev_index >= call_index:
                continue
            if len(prev_response) < self._min_len:
                continue
            # Check if a significant substring of the response appears in the prompt
            fingerprint = prev_response[:self._min_len]
            if fingerprint in prompt:
                edge = (prev_index, call_index)
                if edge not in self._edges:
                    self._edges.append(edge)

    def get_edges(self) -> list[tuple[int, int]]:
        """Return detected data flow edges as (source_index, target_index) tuples."""
        return list(self._edges)


# ---------------------------------------------------------------------------
# Trace header/footer strings for code injection (trace_level >= 2)
# ---------------------------------------------------------------------------

TRACE_HEADER = '''\
# --- RLM Trace Header ---
try:
    import time as _rlm_time
    _rlm_trace.start_time = _rlm_time.perf_counter()
except Exception:
    pass
'''

TRACE_HEADER_MEMORY = '''\
# --- RLM Trace Header (with memory) ---
try:
    import time as _rlm_time
    import tracemalloc as _rlm_tracemalloc
    _rlm_trace.start_time = _rlm_time.perf_counter()
    _rlm_mem_was_tracing = _rlm_tracemalloc.is_tracing()
    if not _rlm_mem_was_tracing:
        _rlm_tracemalloc.start()
except Exception:
    pass
'''

TRACE_FOOTER = '''\
# --- RLM Trace Footer ---
try:
    _rlm_trace.end_time = _rlm_time.perf_counter()
except Exception:
    pass
'''

TRACE_FOOTER_MEMORY = '''\
# --- RLM Trace Footer (with memory) ---
try:
    if not _rlm_mem_was_tracing:
        _current, _peak = _rlm_tracemalloc.get_traced_memory()
        _rlm_trace.peak_memory_bytes = _peak
        _rlm_tracemalloc.stop()
    _rlm_trace.end_time = _rlm_time.perf_counter()
except Exception:
    pass
'''
