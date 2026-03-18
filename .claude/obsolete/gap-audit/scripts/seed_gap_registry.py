#!/usr/bin/env python3
"""Bootstrap gap_registry.json from observability_gaps_deferred.md + issues/.

Creates 3 OG-NN entries (pending, from issues/) and 28 OD-NN entries (deferred).
Runs gap_guard.py --check-only to validate output.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
REGISTRY_PATH = REPO_ROOT / "rlm_adk_docs" / "gap_registry.json"
GUARD_SCRIPT = Path(__file__).resolve().parent / "gap_guard.py"

TODAY = date.today().isoformat()

# ── Active gaps (OG-01 through OG-03) from issues/ ──

ACTIVE_GAPS = [
    {"id": "OG-01", "cluster": "A", "title": "REPL stdout not persisted under any state key",
     "severity": "HIGH", "source_ids": ["REPL-STDOUT"],
     "source_doc": "issues/bug-stdout-not-persisted-under-repl-state-key.md"},
    {"id": "OG-02", "cluster": "A", "title": "repl_trace_summary not landing in tool telemetry rows",
     "severity": "MEDIUM", "source_ids": ["REPL-TRACE-TEL"],
     "source_doc": "issues/bug-repl-trace-summary-missing-from-tool-telemetry.md"},
    {"id": "OG-03", "cluster": "A", "title": "repl_submitted_code* keys not persisted to session_state_events",
     "severity": "HIGH", "source_ids": ["REPL-CODE-SSE"],
     "source_doc": "issues/bug-repl-submitted-code-missing-from-session-state-events.md"},
]

# ── Deferred gaps (OD-01 through OD-28) from observability_gaps_deferred.md ──
# Each has a disposition_category and reason extracted from the deferred doc.

DEFERRED_GAPS = [
    # OD-01..04 removed — implemented (child prompt/response persistence, llm_calls, submitted code)

    # Low-value implementation detail
    {"id": "OD-05", "cluster": "A", "title": "Post-rewrite AST source persistence",
     "severity": "LOW", "source_ids": ["DEBUG-8.2"],
     "source_doc": "observability_gaps_deferred.md:30",
     "category": "low_value_detail",
     "reason": "Pre-rewrite code is the actual LLM output. Post-rewrite code is framework-generated and not necessary for core output observability."},
    {"id": "OD-06", "cluster": "C", "title": "Per-child error detail map",
     "severity": "HIGH", "source_ids": ["DEBUG-3.2"],
     "source_doc": "observability_gaps_deferred.md:36",
     "category": "low_value_detail",
     "reason": "Existing per-child summaries already include error, error_category, and error_message. Additional maps would be denormalized duplication."},
    {"id": "OD-07", "cluster": "B", "title": "Parent-child parent_trace_id / dispatch_tree",
     "severity": "HIGH", "source_ids": ["DEBUG-1.2", "DOC-4.1"],
     "source_doc": "observability_gaps_deferred.md:43",
     "category": "low_value_detail",
     "reason": "Current architecture already shares the invocation trace. Depth/fanout tagging is sufficient for current output-capture needs."},
    {"id": "OD-08", "cluster": "I", "title": "Policy violation on top-level trace row",
     "severity": "LOW", "source_ids": ["DOC-1.3d"],
     "source_doc": "observability_gaps_deferred.md:49",
     "category": "low_value_detail",
     "reason": "Already captured in session_state_events. Missing summary-row denormalization does not block LLM output observability."},

    # Performance / capacity telemetry outside current goal
    {"id": "OD-09", "cluster": "D", "title": "SDK-internal retry timing details",
     "severity": "MEDIUM", "source_ids": ["DEBUG-5.1"],
     "source_doc": "observability_gaps_deferred.md:58",
     "category": "perf_outside_scope",
     "reason": "Useful for reliability/performance analysis, but not required to persist model outputs, thoughts, or REPL code."},
    {"id": "OD-10", "cluster": "E", "title": "Semaphore wait time and effective parallelism",
     "severity": "MEDIUM", "source_ids": ["PERF-2e", "PERF-3a"],
     "source_doc": "observability_gaps_deferred.md:63",
     "category": "perf_outside_scope",
     "reason": "Performance telemetry for concurrency instrumentation, not output-content persistence. Deferred until performance analysis phase."},
    {"id": "OD-11", "cluster": "F", "title": "Child orchestrator creation and cleanup overhead",
     "severity": "MEDIUM", "source_ids": ["PERF-8a", "PERF-8c"],
     "source_doc": "observability_gaps_deferred.md:68",
     "category": "perf_outside_scope",
     "reason": "Useful for latency decomposition, not for capturing LLM outputs. Deferred until performance instrumentation phase."},
    {"id": "OD-12", "cluster": "J", "title": "Critical path and wall-clock decomposition",
     "severity": "LOW", "source_ids": ["PERF-10b/c/d"],
     "source_doc": "observability_gaps_deferred.md:73",
     "category": "perf_outside_scope",
     "reason": "Performance analysis work, not output observability closure. Requires wall-clock decomposition infrastructure not yet built."},
    {"id": "OD-13", "cluster": "I", "title": "child_total_batch_dispatches as dispatch-volume telemetry",
     "severity": "MEDIUM", "source_ids": ["DOC-1.2i"],
     "source_doc": "observability_gaps_deferred.md:78",
     "category": "perf_outside_scope",
     "reason": "Only the trace-row persistence part is being pulled into active scope. Broader dispatch-volume analytics remain non-blocking."},

    # REPL quality analytics deferred until after capture exists
    {"id": "OD-14", "cluster": "G", "title": "Variable state evolution / namespace diffs",
     "severity": "MEDIUM", "source_ids": ["CODE-3"],
     "source_doc": "observability_gaps_deferred.md:86",
     "category": "low_value_detail",
     "reason": "Secondary diagnostic layer; not required to capture outputs or submitted code. Depends on code capture existing first."},
    {"id": "OD-15", "cluster": "G", "title": "Code retry patterns",
     "severity": "MEDIUM", "source_ids": ["CODE-7"],
     "source_doc": "observability_gaps_deferred.md:91",
     "category": "low_value_detail",
     "reason": "Useful after capture exists, but not a prerequisite. Requires consecutive execute_code call tracking infrastructure."},
    {"id": "OD-16", "cluster": "G", "title": "REPL error classification by exception type",
     "severity": "MEDIUM", "source_ids": ["CODE-8"],
     "source_doc": "observability_gaps_deferred.md:96",
     "category": "low_value_detail",
     "reason": "Helpful for diagnosis, not for persistence of outputs/code. Only worker-level _classify_error() exists currently."},
    {"id": "OD-17", "cluster": "G", "title": "Error-recovery turns",
     "severity": "MEDIUM", "source_ids": ["PERF-9c"],
     "source_doc": "observability_gaps_deferred.md:101",
     "category": "low_value_detail",
     "reason": "Behavioral analytics, not output capture. Counting reasoning turns spent on REPL error recovery is a secondary metric."},
    {"id": "OD-18", "cluster": "G", "title": "format_execution_result() variable values",
     "severity": "MEDIUM", "source_ids": ["REPL-5"],
     "source_doc": "observability_gaps_deferred.md:106",
     "category": "low_value_detail",
     "reason": "Presentation/runtime formatting issue, not core observability persistence. Variable names are listed but values are dropped."},
    {"id": "OD-19", "cluster": "G", "title": "REPLResult.execution_time consumption",
     "severity": "MEDIUM", "source_ids": ["REPL-6"],
     "source_doc": "observability_gaps_deferred.md:111",
     "category": "low_value_detail",
     "reason": "Perf/UI-level concern, not LLM output capture. The field is populated but the orchestrator and formatting functions ignore it."},

    # Platform / analytics maturity work
    {"id": "OD-20", "cluster": "I", "title": "Run ordinal within session",
     "severity": "LOW", "source_ids": ["DOC-1.1d"],
     "source_doc": "observability_gaps_deferred.md:119",
     "category": "platform_maturity",
     "reason": "Multi-session analytics feature, not current gap closure. Requires monotonic counter distinguishing retry vs fresh run."},
    {"id": "OD-21", "cluster": "I", "title": "No normalized iteration table",
     "severity": "LOW", "source_ids": ["DOC-2.3"],
     "source_doc": "observability_gaps_deferred.md:124",
     "category": "platform_maturity",
     "reason": "Warehouse/queryability improvement, not required to store outputs. The per_iteration_breakdown JSON blob would need normalization."},
    {"id": "OD-22", "cluster": "I", "title": "No cost estimation metadata",
     "severity": "LOW", "source_ids": ["DOC-5.2"],
     "source_doc": "observability_gaps_deferred.md:129",
     "category": "platform_maturity",
     "reason": "Cost analytics, not output persistence. Requires model_pricing reference table for dollar cost which does not exist yet."},
    {"id": "OD-23", "cluster": "I", "title": "System instruction not stored",
     "severity": "LOW", "source_ids": ["DOC-6.1b"],
     "source_doc": "observability_gaps_deferred.md:134",
     "category": "out_of_scope",
     "reason": "Input provenance issue; useful, but outside the narrower capture outputs and REPL code target for this observability phase."},
    {"id": "OD-24", "cluster": "I", "title": "No artifact content hashing",
     "severity": "LOW", "source_ids": ["DOC-7.1"],
     "source_doc": "observability_gaps_deferred.md:139",
     "category": "platform_maturity",
     "reason": "Artifact integrity feature, not output observability. Requires artifact_versions table with content_hash which is new infrastructure."},
    {"id": "OD-25", "cluster": "I", "title": "No baseline/regression infrastructure",
     "severity": "LOW", "source_ids": ["DOC-3.2"],
     "source_doc": "observability_gaps_deferred.md:144",
     "category": "platform_maturity",
     "reason": "Monitoring platform work, not instrumentation gap closure. Requires baseline run sets, regression comparison, and alert infrastructure."},

    # Miscellaneous telemetry consistency issues
    {"id": "OD-26", "cluster": "J", "title": "Parallel dispatch race condition visibility",
     "severity": "LOW", "source_ids": ["DEBUG-4.3"],
     "source_doc": "observability_gaps_deferred.md:151",
     "category": "low_value_detail",
     "reason": "Consistency concern, but not a primary blocker for output capture. Object-carrier fields are transient by design."},
    {"id": "OD-27", "cluster": "J", "title": "Exception-vs-error-value distinction",
     "severity": "LOW", "source_ids": ["DEBUG-7.3"],
     "source_doc": "observability_gaps_deferred.md:156",
     "category": "low_value_detail",
     "reason": "Semantic telemetry cleanup, not raw output persistence. Dispatch raises exceptions for depth-limit but returns LLMResult for API errors."},
    {"id": "OD-28", "cluster": "C", "title": "Stale worker token-key concern",
     "severity": "LOW", "source_ids": ["REPL-4"],
     "source_doc": "observability_gaps_deferred.md:161",
     "category": "low_value_detail",
     "reason": "Appears tied to older worker-key assumptions and not the current child-orchestrator path. May be already resolved by migration."},
]


def make_pending_entry(gap: dict) -> dict:
    return {
        "id": gap["id"],
        "cluster": gap["cluster"],
        "title": gap["title"],
        "severity": gap["severity"],
        "source_ids": gap["source_ids"],
        "source_doc": gap["source_doc"],
        "disposition": "pending",
        "disposition_category": None,
        "disposition_reason": None,
        "disposition_date": None,
        "evidence": {
            "test_paths": [],
            "demo_path": None,
            "code_paths": [],
            "evidence_tier": None,
        },
    }


def make_deferred_entry(gap: dict) -> dict:
    return {
        "id": gap["id"],
        "cluster": gap["cluster"],
        "title": gap["title"],
        "severity": gap["severity"],
        "source_ids": gap["source_ids"],
        "source_doc": gap["source_doc"],
        "disposition": "deferred",
        "disposition_category": gap["category"],
        "disposition_reason": gap["reason"],
        "disposition_date": TODAY,
        "evidence": {
            "test_paths": [],
            "demo_path": None,
            "code_paths": [],
            "evidence_tier": None,
        },
    }


def main() -> int:
    gaps = {}

    for g in ACTIVE_GAPS:
        gaps[g["id"]] = make_pending_entry(g)

    for g in DEFERRED_GAPS:
        gaps[g["id"]] = make_deferred_entry(g)

    registry = {
        "$schema": "./gap_registry.schema.json",
        "meta": {
            "mode": "report",
            "total_gaps": len(gaps),
            "generated_from": "observability_gaps_deferred.md + issues/",
            "version": 2,
        },
        "gaps": gaps,
    }

    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)
        f.write("\n")

    print(f"Wrote {len(gaps)} gaps to {REGISTRY_PATH}")
    og_count = sum(1 for k in gaps if k.startswith("OG-"))
    od_count = sum(1 for k in gaps if k.startswith("OD-"))
    print(f"  {og_count} active (OG-) pending, {od_count} deferred (OD-)")

    # Validate with guard
    result = subprocess.run(
        [sys.executable, str(GUARD_SCRIPT), "--check-only"],
        capture_output=True, text=True,
    )
    print(f"\nGuard validation (exit {result.returncode}):")
    if result.stderr:
        print(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
