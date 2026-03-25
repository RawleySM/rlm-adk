"""Architecture introspection skill: exercises full rlm_adk pipeline.

Module-import delivery: discovered by loader.py, exports injected into REPL
globals. llm_query_fn is auto-injected by the loader wrapper.

Key difference from source-expansion: this function cannot access REPL globals
via globals(). The rlm_state parameter must be passed explicitly from REPL code.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class TestSkillResult:
    """Typed result from run_test_skill(). All fields are JSON-serializable."""

    state_snapshot: dict[str, Any]
    execution_mode: str
    thread_bridge_latency_ms: float
    child_result: str
    timestamps: dict[str, float]
    batched_probe_results: list[str] | None = None


def run_test_skill(
    child_prompt: str = "Reply with exactly: arch_test_ok",
    *,
    emit_debug: bool = True,
    rlm_state: dict[str, Any] | None = None,
    llm_query_fn=None,
    llm_query_batched_fn=None,
) -> TestSkillResult:
    """Exercise the full rlm_adk architecture pipeline and return diagnostic data.

    Args:
        child_prompt: Prompt to send to the child orchestrator.
        emit_debug: Whether to print [TEST_SKILL:...] tagged lines.
        rlm_state: The _rlm_state dict from REPL globals (pass explicitly).
        llm_query_fn: Auto-injected by loader wrapper. The sync llm_query callable.
        llm_query_batched_fn: Auto-injected by loader wrapper. The sync
            llm_query_batched callable for parallel child dispatch.

    Returns:
        TestSkillResult with all captured diagnostic data.
    """
    if llm_query_fn is None:
        raise RuntimeError(
            "llm_query_fn not available. "
            "Call run_test_skill from REPL with llm_query wired, "
            "or pass llm_query_fn explicitly."
        )

    def _tag(key: str, value: Any) -> None:
        if emit_debug:
            print(f"[TEST_SKILL:{key}={value}]")

    timestamps: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Step 1: Capture _rlm_state (passed explicitly, not from globals())
    # ------------------------------------------------------------------
    timestamps["t0_start"] = time.perf_counter()

    state_snapshot: dict[str, Any] = {}
    _state = rlm_state or {}
    for k, v in _state.items():
        try:
            json.dumps(v)
            state_snapshot[k] = v
        except (TypeError, ValueError):
            state_snapshot[k] = repr(v)

    _tag("depth", state_snapshot.get("_rlm_depth", "?"))
    _tag("rlm_agent_name", state_snapshot.get("_rlm_agent_name", "?"))
    _tag("iteration_count", state_snapshot.get("iteration_count", "?"))
    _tag("current_depth", state_snapshot.get("current_depth", "?"))
    _tag("should_stop", state_snapshot.get("should_stop", "?"))
    _tag("state_keys_count", len(state_snapshot))
    _tag("state_keys", sorted(state_snapshot.keys()))

    # ------------------------------------------------------------------
    # Step 2: Detect execution mode at runtime
    # Thread bridge runs REPL code in a worker thread (not MainThread).
    # Detecting the thread name proves the bridge is actually in use.
    # ------------------------------------------------------------------
    import threading
    _thread_name = threading.current_thread().name
    execution_mode = "thread_bridge" if _thread_name != "MainThread" else "direct"
    _tag("execution_mode", execution_mode)
    _tag("worker_thread_name", _thread_name)
    _tag("llm_query_fn_type", type(llm_query_fn).__name__)

    # ------------------------------------------------------------------
    # Step 3: Exercise child dispatch via llm_query_fn()
    # ------------------------------------------------------------------
    timestamps["t1_before_llm_query"] = time.perf_counter()
    _tag("calling_llm_query", True)

    child_result = llm_query_fn(child_prompt)

    timestamps["t2_after_llm_query"] = time.perf_counter()

    latency_ms = (timestamps["t2_after_llm_query"] - timestamps["t1_before_llm_query"]) * 1000.0

    _tag("child_result_preview", str(child_result)[:120])
    _tag("thread_bridge_latency_ms", round(latency_ms, 2))

    # ------------------------------------------------------------------
    # Step 3b: Exercise batched child dispatch via llm_query_batched_fn()
    # Only runs if llm_query_batched_fn is provided (not None).
    # ------------------------------------------------------------------
    batched_probe_results: list[str] | None = None
    if llm_query_batched_fn is not None:
        timestamps["t2b_before_batched"] = time.perf_counter()
        _tag("calling_llm_query_batched", True)

        raw_batched = llm_query_batched_fn(["batch_probe_1", "batch_probe_2"])
        batched_probe_results = [str(r) for r in raw_batched]

        timestamps["t2b_after_batched"] = time.perf_counter()
        batched_latency_ms = (
            timestamps["t2b_after_batched"] - timestamps["t2b_before_batched"]
        ) * 1000.0
        _tag("batched_results", batched_probe_results)
        _tag("batched_latency_ms", round(batched_latency_ms, 2))

    # ------------------------------------------------------------------
    # Step 4: Final summary
    # ------------------------------------------------------------------
    timestamps["t3_end"] = time.perf_counter()

    _tag("COMPLETE", True)
    _tag(
        "summary",
        (
            f"depth={state_snapshot.get('_rlm_depth', '?')} "
            f"mode={execution_mode} "
            f"latency_ms={latency_ms:.1f} "
            f"child_ok={bool(child_result)}"
        ),
    )

    return TestSkillResult(
        state_snapshot=state_snapshot,
        execution_mode=execution_mode,
        thread_bridge_latency_ms=latency_ms,
        child_result=str(child_result),
        timestamps={k: round(v, 6) for k, v in timestamps.items()},
        batched_probe_results=batched_probe_results,
    )
