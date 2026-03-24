"""Benchmark runner for Understand-phase v2.

Discovers cases, runs an agent function against each, scores results,
and produces a suite summary. Includes a built-in dummy agent for
dry-run validation.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from rlm_adk.eval.understand_bench_v2.loader import (
    build_manifest,
    discover_cases,
    load_case_with_gold,
    resolve_file_path,
)
from rlm_adk.eval.understand_bench_v2.scoring import (
    AgentOutputV2,
    BenchmarkResultV2,
    score_result,
)

logger = logging.getLogger(__name__)

# Type alias for agent functions
AgentFn = Callable[
    [str, list[dict[str, Any]], list[dict[str, Any]]],
    AgentOutputV2,
]
# AgentFn signature: (broad_objective, manifest, file_metadata_list) -> AgentOutputV2


class SuiteResult(BaseModel):
    """Aggregate result for a full benchmark suite run."""

    results: list[BenchmarkResultV2]
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    avg_score: float = 0.0
    summary: str = ""


class BenchmarkRunnerV2:
    """Orchestrates benchmark case discovery, execution, and scoring."""

    def __init__(
        self,
        base_dir: str | Path | None = None,
        difficulty_filter: str | None = None,
        pass_threshold: float = 60.0,
    ) -> None:
        self._base_dir = base_dir
        self._difficulty_filter = difficulty_filter
        self._pass_threshold = pass_threshold

    def list_cases(self) -> list[dict[str, str]]:
        """Return a list of available case summaries."""
        paths = discover_cases(self._base_dir, self._difficulty_filter)
        summaries = []
        for p in paths:
            raw = json.loads(p.read_text(encoding="utf-8"))
            summaries.append(
                {
                    "case_id": raw.get("case_id", p.stem),
                    "difficulty": raw.get("difficulty", "unknown"),
                    "task_name": raw.get("task_name", ""),
                    "num_files": str(len(raw.get("provided_files", []))),
                    "path": str(p),
                }
            )
        return summaries

    def run_case(
        self,
        case_id: str,
        agent_fn: AgentFn,
    ) -> BenchmarkResultV2:
        """Run a single case and return the scored result."""
        paths = discover_cases(self._base_dir)
        case_path = None
        for p in paths:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if raw.get("case_id") == case_id:
                case_path = p
                break

        if case_path is None:
            raise ValueError(f"Case not found: {case_id}")

        case, gold = load_case_with_gold(case_path)
        manifest = build_manifest(case)

        # Build file metadata for the agent
        file_metadata = []
        for fref in case.provided_files:
            fpath = resolve_file_path(fref)
            file_metadata.append(
                {
                    "ref_id": fref.ref_id,
                    "display_name": fref.display_name,
                    "format": fref.format,
                    "doc_type": fref.doc_type,
                    "file_path": str(fpath),
                    "exists": fpath.is_file(),
                    "size_bytes": fref.size_bytes,
                    "description": fref.description,
                }
            )

        agent_output = agent_fn(case.broad_objective, manifest, file_metadata)
        return score_result(case, agent_output)

    def run_all(self, agent_fn: AgentFn) -> SuiteResult:
        """Run all discovered cases and return aggregate results."""
        paths = discover_cases(self._base_dir, self._difficulty_filter)
        results: list[BenchmarkResultV2] = []

        for path in paths:
            case, gold = load_case_with_gold(path)
            manifest = build_manifest(case)

            file_metadata = []
            for fref in case.provided_files:
                fpath = resolve_file_path(fref)
                file_metadata.append(
                    {
                        "ref_id": fref.ref_id,
                        "display_name": fref.display_name,
                        "format": fref.format,
                        "doc_type": fref.doc_type,
                        "file_path": str(fpath),
                        "exists": fpath.is_file(),
                        "size_bytes": fref.size_bytes,
                        "description": fref.description,
                    }
                )

            try:
                agent_output = agent_fn(case.broad_objective, manifest, file_metadata)
                result = score_result(case, agent_output)
            except Exception as e:
                logger.error("Case %s failed: %s", case.case_id, e)
                result = BenchmarkResultV2(
                    case_id=case.case_id,
                    recall=0.0,
                    precision=0.0,
                    order_score=0.0,
                    halt_score=0.0,
                    skill_score=0.0,
                    total_score=0.0,
                    details={"error": str(e)},
                )
            results.append(result)

        # Aggregate
        total = len(results)
        passed = sum(1 for r in results if r.total_score >= self._pass_threshold)
        failed = total - passed
        avg = sum(r.total_score for r in results) / total if total > 0 else 0.0

        lines = [
            f"Understand Bench v2 — {total} cases, {passed} passed, {failed} failed",
            f"Average score: {avg:.1f} / 100.0",
            f"Pass threshold: {self._pass_threshold}",
            "",
        ]
        for r in results:
            status = "PASS" if r.total_score >= self._pass_threshold else "FAIL"
            lines.append(
                f"  [{status}] {r.case_id}: {r.total_score:.1f} "
                f"(R={r.recall:.2f} P={r.precision:.2f} O={r.order_score:.2f} "
                f"H={r.halt_score:.0f} S={r.skill_score:.2f})"
            )

        return SuiteResult(
            results=results,
            total_cases=total,
            passed=passed,
            failed=failed,
            avg_score=avg,
            summary="\n".join(lines),
        )


# ---------------------------------------------------------------------------
# Built-in dummy agent (always halts, no retrievals, no skills)
# ---------------------------------------------------------------------------


def _dummy_agent(
    broad_objective: str,
    manifest: list[dict[str, Any]],
    file_metadata: list[dict[str, Any]],
) -> AgentOutputV2:
    """Dummy agent that halts immediately with no output."""
    return AgentOutputV2(
        retrieved_artifacts=[],
        halted=True,
        identified_skills=[],
        processing_plan=[],
        raw_output="[dummy] Halted — no analysis performed.",
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Understand Bench v2 Runner")
    parser.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    parser.add_argument("--case", help="Run a single case by ID")
    parser.add_argument("--list", action="store_true", help="List available cases")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    runner = BenchmarkRunnerV2(difficulty_filter=args.difficulty)

    if args.list:
        for case_info in runner.list_cases():
            print(
                f"  [{case_info['difficulty']}] {case_info['case_id']} "
                f"({case_info['num_files']} files) — {case_info['task_name']}"
            )
        return

    if args.case:
        result = runner.run_case(args.case, _dummy_agent)
        print(f"Score: {result.total_score:.1f} / {result.max_possible_score:.1f}")
        print(f"Recall: {result.recall:.2f}, Precision: {result.precision:.2f}")
        print(f"Order: {result.order_score:.2f}, Halt: {result.halt_score:.0f}")
        print(f"Skill: {result.skill_score:.2f}")
        if result.penalties:
            print(f"Penalties: {result.penalties}")
        return

    suite = runner.run_all(_dummy_agent)
    print(suite.summary)


if __name__ == "__main__":
    main()
