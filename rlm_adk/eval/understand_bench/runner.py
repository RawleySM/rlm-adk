"""Runner for the Understand-phase benchmark suite.

Discovers and executes benchmark cases, scores agent outputs via
:func:`scoring.score_result`, and produces aggregate reports.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from rlm_adk.eval.understand_bench.loader import (
    discover_cases,
    load_case_with_gold,
)
from rlm_adk.eval.understand_bench.scoring import (
    AgentRetrievalOutput,
    BenchmarkResult,
    score_result,
)

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent

# Passing threshold: cases with total_score >= this value count as "passed".
_PASS_THRESHOLD = 60.0


# ---------------------------------------------------------------------------
# Aggregate result model
# ---------------------------------------------------------------------------


class BenchmarkSuiteResult(BaseModel):
    """Aggregate results from running the full benchmark suite."""

    results: list[BenchmarkResult]
    summary: dict[str, Any]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class BenchmarkRunner:
    """Runs understand-phase benchmark cases and collects scored results.

    Usage::

        runner = BenchmarkRunner(difficulty_filter="easy")
        cases = runner.list_cases()
        result = runner.run_case("case_efile_auth", my_agent_fn)
        suite = runner.run_all(my_agent_fn)
        print(suite.summary)
    """

    def __init__(
        self,
        base_dir: str | Path | None = None,
        difficulty_filter: str | None = None,
    ) -> None:
        """Initialize the runner.

        Args:
            base_dir: Base directory for benchmark files.  Defaults to
                the ``understand_bench`` package directory.
            difficulty_filter: Optional filter for ``"easy"``,
                ``"medium"``, or ``"hard"``.
        """
        self._base_dir = Path(base_dir) if base_dir is not None else _PACKAGE_DIR
        self._difficulty_filter = difficulty_filter

        # Eagerly discover paths so callers get fast feedback on bad dirs.
        self._case_paths = discover_cases(
            base_dir=self._base_dir,
            difficulty=self._difficulty_filter,
        )

        # Build an index: case_id -> path.
        self._case_index: dict[str, Path] = {}
        for path in self._case_paths:
            # Parse just enough to extract case_id without full validation.
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                case_id = raw.get("case_id", path.stem)
            except (json.JSONDecodeError, OSError):
                case_id = path.stem
            self._case_index[case_id] = path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_cases(self) -> list[dict[str, str]]:
        """List available cases with ``case_id``, ``difficulty``, and ``path``.

        Returns:
            A list of dicts, each with keys ``"case_id"``,
            ``"difficulty"``, and ``"path"``.
        """
        result: list[dict[str, str]] = []
        for path in self._case_paths:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                case_id = raw.get("case_id", path.stem)
                difficulty = raw.get("difficulty", "unknown")
            except (json.JSONDecodeError, OSError):
                case_id = path.stem
                difficulty = "unknown"
            result.append(
                {
                    "case_id": case_id,
                    "difficulty": difficulty,
                    "path": str(path),
                }
            )
        return result

    async def run_case(
        self,
        case_id: str,
        agent_fn: Callable[[str, dict[str, Any]], Awaitable[AgentRetrievalOutput]],
    ) -> BenchmarkResult:
        """Run a single benchmark case.

        Args:
            case_id: The identifier of the case to run (must match a
                discovered case).
            agent_fn: An async callable that takes
                ``(broad_objective, provided_context_dict)`` and returns
                an :class:`AgentRetrievalOutput`.

        Returns:
            A scored :class:`BenchmarkResult`.

        Raises:
            KeyError: If *case_id* is not among the discovered cases.
        """
        if case_id not in self._case_index:
            available = sorted(self._case_index.keys())
            raise KeyError(f"Case {case_id!r} not found. Available: {available}")

        case_path = self._case_index[case_id]
        case, _gold = load_case_with_gold(case_path)

        logger.info("Running case %s (%s)", case.case_id, case.difficulty)
        t0 = time.monotonic()

        agent_output = await agent_fn(case.broad_objective, case.provided_context_dict)

        elapsed = time.monotonic() - t0
        logger.info("Case %s completed in %.2fs", case.case_id, elapsed)

        result = score_result(case, agent_output)
        return result

    async def run_all(
        self,
        agent_fn: Callable[[str, dict[str, Any]], Awaitable[AgentRetrievalOutput]],
    ) -> BenchmarkSuiteResult:
        """Run all discovered cases and return aggregate results.

        Args:
            agent_fn: An async callable that takes
                ``(broad_objective, provided_context_dict)`` and returns
                an :class:`AgentRetrievalOutput`.

        Returns:
            A :class:`BenchmarkSuiteResult` with per-case results and
            a summary report.
        """
        results: list[BenchmarkResult] = []
        for case_id in sorted(self._case_index.keys()):
            try:
                result = await self.run_case(case_id, agent_fn)
                results.append(result)
            except Exception:
                logger.exception("Error running case %s", case_id)

        summary = self.run_suite_report(results)
        return BenchmarkSuiteResult(results=results, summary=summary)

    def run_suite_report(
        self,
        results: list[BenchmarkResult],
    ) -> dict[str, Any]:
        """Generate a summary report from benchmark results.

        Args:
            results: List of scored :class:`BenchmarkResult` instances.

        Returns:
            A dict with:

            * ``total_cases`` -- number of cases run.
            * ``passed`` -- cases with ``total_score >= 60``.
            * ``failed`` -- cases with ``total_score < 60``.
            * ``avg_score``, ``min_score``, ``max_score`` -- score
              statistics.
            * ``by_difficulty`` -- breakdown by difficulty level, each
              with ``avg``, ``count``, ``passed``, ``failed``.
            * ``per_case`` -- list of per-case summaries with
              ``case_id``, ``score``, ``recall``, ``precision``,
              ``order_score``, ``halt_score``, ``penalties``.
        """
        if not results:
            return {
                "total_cases": 0,
                "passed": 0,
                "failed": 0,
                "avg_score": 0.0,
                "min_score": 0.0,
                "max_score": 0.0,
                "by_difficulty": {},
                "per_case": [],
            }

        scores = [r.total_score for r in results]
        passed = sum(1 for s in scores if s >= _PASS_THRESHOLD)
        failed = len(scores) - passed

        # Per-case summaries.
        per_case: list[dict[str, Any]] = []
        for r in results:
            per_case.append(
                {
                    "case_id": r.case_id,
                    "score": r.total_score,
                    "recall": r.recall,
                    "precision": r.precision,
                    "order_score": r.order_score,
                    "halt_score": r.halt_score,
                    "penalties": dict(r.penalties),
                }
            )

        # Group by difficulty.
        by_difficulty: dict[str, dict[str, Any]] = {}
        # We need to look up difficulty per case_id.  Use the index.
        difficulty_map: dict[str, str] = {}
        for path in self._case_paths:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                difficulty_map[raw.get("case_id", path.stem)] = raw.get("difficulty", "unknown")
            except (json.JSONDecodeError, OSError):
                difficulty_map[path.stem] = "unknown"

        # Build per-difficulty buckets.
        difficulty_buckets: dict[str, list[float]] = {}
        for r in results:
            diff = difficulty_map.get(r.case_id, "unknown")
            difficulty_buckets.setdefault(diff, []).append(r.total_score)

        for diff, bucket in sorted(difficulty_buckets.items()):
            by_difficulty[diff] = {
                "avg": sum(bucket) / len(bucket),
                "count": len(bucket),
                "passed": sum(1 for s in bucket if s >= _PASS_THRESHOLD),
                "failed": sum(1 for s in bucket if s < _PASS_THRESHOLD),
            }

        return {
            "total_cases": len(results),
            "passed": passed,
            "failed": failed,
            "avg_score": sum(scores) / len(scores),
            "min_score": min(scores),
            "max_score": max(scores),
            "by_difficulty": by_difficulty,
            "per_case": per_case,
        }


# ---------------------------------------------------------------------------
# Bridge agent_fn: runs the real RLM agent via create_rlm_runner
# ---------------------------------------------------------------------------


async def _run_rlm_agent_async(
    broad_objective: str,
    provided_context_dict: dict[str, Any],
    *,
    model: str | None = None,
    max_iterations: int = 20,
    max_depth: int = 2,
) -> AgentRetrievalOutput:
    """Run the RLM agent against a benchmark case and extract retrieval output.

    Builds the pre-seeded session state with ``user_provided_ctx``, creates
    a Runner via :func:`rlm_adk.agent.create_rlm_runner`, executes the
    agent, and extracts ``retrieval_order`` and ``halted`` from the final
    REPL output or session state.

    Args:
        broad_objective: The case's broad objective string.
        provided_context_dict: The case's provided context dict (filename->content).
        model: LLM model identifier.  Defaults to ``RLM_ADK_MODEL`` env var
            or ``gemini-2.5-flash``.
        max_iterations: Maximum tool calls for the agent.
        max_depth: Maximum recursion depth for child dispatches.

    Returns:
        An :class:`AgentRetrievalOutput` extracted from the agent run.
    """
    import os
    import re

    from google.genai import types

    from rlm_adk.agent import create_rlm_runner
    from rlm_adk.state import (
        DYN_USER_CTX_MANIFEST,
        LAST_REPL_RESULT,
        USER_PROVIDED_CTX,
        USER_PROVIDED_CTX_EXCEEDED,
        USR_PROVIDED_FILES_SERIALIZED,
        USR_PROVIDED_FILES_UNSERIALIZED,
    )

    resolved_model = model or os.getenv("RLM_ADK_MODEL", "gemini-2.5-flash")

    # Build manifest from provided_context_dict
    filenames = sorted(k for k in provided_context_dict if not k.startswith("_"))
    manifest_lines = [
        "Pre-loaded context variable: user_ctx (dict)",
        'Pre-loaded files (access via user_ctx["<filename>"]):',
    ]
    for fn in filenames:
        content = provided_context_dict[fn]
        if isinstance(content, str):
            chars = len(content)
        else:
            chars = len(json.dumps(content, default=str))
        manifest_lines.append(f"  - {fn} ({chars:,} chars)")
    manifest_lines.append(f"Total: {len(filenames)} files, {len(filenames)} pre-loaded")
    manifest_str = "\n".join(manifest_lines)

    # Build query that steers the agent to use polya-understand skill
    query = (
        "You have pre-loaded context files available as user_ctx in the REPL. "
        "Use the polya-understand skill to analyze this context. "
        "Run: from rlm_repl_skills.polya_understand import run_polya_understand; "
        f'result = run_polya_understand(objective="{broad_objective}", '
        'project_context=user_ctx, project_name="benchmark-case"); '
        "print(result.retrieval_order); print(result.halted)"
    )

    runner = create_rlm_runner(
        model=resolved_model,
        root_prompt=query,
        thinking_budget=0,
    )

    # Create session with pre-seeded state
    session = await runner.session_service.create_session(
        app_name="rlm_adk",
        user_id="benchmark",
        state={
            "app:max_iterations": max_iterations,
            "app:max_depth": max_depth,
            USER_PROVIDED_CTX: provided_context_dict,
            USER_PROVIDED_CTX_EXCEEDED: False,
            USR_PROVIDED_FILES_SERIALIZED: filenames,
            USR_PROVIDED_FILES_UNSERIALIZED: [],
            DYN_USER_CTX_MANIFEST: manifest_str,
        },
    )

    # Run the agent
    raw_output_parts: list[str] = []
    content_msg = types.Content(
        role="user",
        parts=[types.Part.from_text(text=query)],
    )

    async for event in runner.run_async(
        user_id="benchmark",
        session_id=session.id,
        new_message=content_msg,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    raw_output_parts.append(part.text)

    raw_output = "\n".join(raw_output_parts)

    # Extract retrieval_order and halted from output
    # Look for patterns like: ['artifact1', 'artifact2']
    # and: True / False for halted
    retrieval_order: list[str] = []
    halted = False

    # Try to extract from LAST_REPL_RESULT in session state
    updated_session = await runner.session_service.get_session(
        app_name="rlm_adk",
        user_id="benchmark",
        session_id=session.id,
    )
    last_repl = ""
    if updated_session:
        last_repl = updated_session.state.get(LAST_REPL_RESULT, "")

    # Parse from LAST_REPL_RESULT first (contains only REPL stdout),
    # fall back to raw_output tail.
    parse_text = last_repl if last_repl else raw_output

    # Extract retrieval order: find last Python list pattern in text
    list_matches = list(re.finditer(r"\[([^\]]*)\]", parse_text))
    if list_matches:
        # Use the LAST match — retrieval_order is printed after other output
        list_content = list_matches[-1].group(1)
        items = re.findall(r"['\"]([^'\"]+)['\"]", list_content)
        retrieval_order = items

    # Extract halted: look for standalone True/False AFTER retrieval output
    # Split on the last list match to avoid matching booleans in JSON data
    halted_text = parse_text
    if list_matches:
        halted_text = parse_text[list_matches[-1].end():]
    halted_match = re.search(r"\b(True|False)\b", halted_text)
    if halted_match:
        halted = halted_match.group(1) == "True"

    return AgentRetrievalOutput(
        retrieved_artifacts=retrieval_order,
        halted=halted,
        raw_output=raw_output,
    )


def make_rlm_agent_fn(
    *,
    model: str | None = None,
    max_iterations: int = 20,
    max_depth: int = 2,
):
    """Create an async agent_fn for :meth:`BenchmarkRunner.run_case`.

    Returns an async callable with signature
    ``(broad_objective, provided_context_dict) -> AgentRetrievalOutput``.

    Args:
        model: LLM model identifier (default: env var or gemini-2.5-flash).
        max_iterations: Maximum tool calls.
        max_depth: Maximum recursion depth.

    Returns:
        An async callable for use as ``agent_fn``.
    """

    async def agent_fn(
        broad_objective: str,
        provided_context_dict: dict[str, Any],
    ) -> AgentRetrievalOutput:
        return await _run_rlm_agent_async(
            broad_objective,
            provided_context_dict,
            model=model,
            max_iterations=max_iterations,
            max_depth=max_depth,
        )

    return agent_fn


# ---------------------------------------------------------------------------
# CLI entry point — dry-run with a dummy agent
# ---------------------------------------------------------------------------


async def _dummy_agent(
    broad_objective: str,
    provided_context_dict: dict[str, Any],
) -> AgentRetrievalOutput:
    """A dummy agent that always halts with no retrievals.

    Useful for dry-run testing of the benchmark harness itself.
    """
    return AgentRetrievalOutput(
        retrieved_artifacts=[],
        halted=True,
        raw_output="[dry-run] No retrievals — always halt.",
    )


async def _main_async() -> None:
    """Async CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the Understand-phase benchmark suite (dry-run).",
    )
    parser.add_argument(
        "--base-dir",
        type=str,
        default=None,
        help="Base directory for benchmark files (default: package dir).",
    )
    parser.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "medium", "hard"],
        default=None,
        help="Filter cases by difficulty level.",
    )
    parser.add_argument(
        "--case",
        type=str,
        default=None,
        help="Run a single case by case_id instead of the full suite.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    runner = BenchmarkRunner(
        base_dir=args.base_dir,
        difficulty_filter=args.difficulty,
    )

    print(f"Discovered {len(runner._case_paths)} case(s):")
    for info in runner.list_cases():
        print(f"  [{info['difficulty']}] {info['case_id']}")
    print()

    if args.case:
        result = await runner.run_case(args.case, _dummy_agent)
        print(f"Case: {result.case_id}")
        print(f"  Score: {result.total_score:.1f} / {result.max_possible_score:.1f}")
        print(f"  Recall: {result.recall:.2f}")
        print(f"  Precision: {result.precision:.2f}")
        print(f"  Order: {result.order_score:.2f}")
        print(f"  Halt: {result.halt_score:.2f}")
        if result.penalties:
            print(f"  Penalties: {result.penalties}")
    else:
        suite = await runner.run_all(_dummy_agent)
        print("--- Suite Results ---")
        print(json.dumps(suite.summary, indent=2))


def main() -> None:
    """CLI entry point."""
    import asyncio

    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
