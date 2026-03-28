#!/usr/bin/env python
"""Run the understand_bench_v2 benchmark with the RLM agent.

Claude-code runs this via:
    .venv/bin/python scripts/run_understand_bench.py --skill understand_v1

All telemetry goes to stdout as [RLM:*] tagged lines.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Logging setup -- stderr only, keep stdout clean for [RLM:*] lines
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
for _noisy in ("LiteLLM", "litellm", "httpx", "httpcore", "opentelemetry"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# Bypass LiteLLM -- use Gemini directly
os.environ["RLM_ADK_LITELLM"] = ""

_DB_PATH = PROJECT_ROOT / "rlm_adk" / ".adk" / "traces.db"
_MANIFEST_PATH = PROJECT_ROOT / "rlm_adk" / ".adk" / "bench_manifest.json"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run understand_bench_v2 with RLM agent")
    p.add_argument("--skill", default="understand_v1", help="Skill directory name")
    p.add_argument(
        "--difficulty",
        default=None,
        choices=["easy", "medium", "hard"],
        help="Filter by difficulty",
    )
    p.add_argument("--case", default=None, help="Run single case by ID")
    p.add_argument("--model", default="gemini-3.1-pro-preview", help="Model override")
    p.add_argument("--max-iterations", type=int, default=30, help="REPL call cap")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Pre-flight readiness checks
# ---------------------------------------------------------------------------


async def preflight() -> bool:
    """Run pre-flight checks. Returns True if all pass."""
    all_ok = True

    # 1. Active benchmark sessions
    if not _DB_PATH.is_file():
        print(
            "[RLM:PREFLIGHT] active_bench_sessions=0 (db not found, first run)",
            flush=True,
        )
    else:
        try:
            conn = sqlite3.connect(str(_DB_PATH))
            cur = conn.execute(
                "SELECT COUNT(*) FROM traces "
                "WHERE status = 'running' "
                "  AND user_id = 'bench_user' "
                "  AND start_time > (strftime('%s', 'now') - 7200)"
            )
            active = cur.fetchone()[0]

            # Count stale rows (informational)
            cur2 = conn.execute(
                "SELECT COUNT(*) FROM traces "
                "WHERE status = 'running' "
                "  AND user_id = 'bench_user' "
                "  AND start_time <= (strftime('%s', 'now') - 7200)"
            )
            stale = cur2.fetchone()[0]
            conn.close()

            if stale > 0:
                print(
                    f"[RLM:PREFLIGHT] stale_bench_sessions={stale} (ignored, older than 2h)",
                    flush=True,
                )
            print(
                f"[RLM:PREFLIGHT] active_bench_sessions={active}",
                flush=True,
            )
            if active > 0:
                print(
                    "[RLM:ERROR] Active benchmark sessions found. "
                    "Wait for them to complete or investigate stale runs.",
                    flush=True,
                )
                all_ok = False
        except sqlite3.Error as e:
            print(f"[RLM:PREFLIGHT] active_bench_sessions=error:{e}", flush=True)
            all_ok = False

    # 2. Gemini API
    try:
        from google import genai

        client = genai.Client()
        # Lightweight check -- list models, no tokens consumed
        _models = list(client.models.list(config={"page_size": 1}))
        print("[RLM:PREFLIGHT] gemini=ok", flush=True)
    except Exception as e:
        print(f"[RLM:PREFLIGHT] gemini=error:{e}", flush=True)
        all_ok = False

    # 3. OpenRouter balance (optional)
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        try:
            import urllib.request

            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {openrouter_key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())["data"]
                limit = data.get("limit", 0) or 0
                usage = data.get("usage", 0) or 0
                balance = limit - usage
                print(
                    f"[RLM:PREFLIGHT] openrouter_balance=${balance:.2f}",
                    flush=True,
                )
        except Exception as e:
            print(f"[RLM:PREFLIGHT] openrouter=error:{e}", flush=True)
    else:
        print("[RLM:PREFLIGHT] openrouter=n/a", flush=True)

    # 4. Final summary
    gemini_status = "ok" if all_ok else "fail"
    print(
        f"[RLM:READY] gemini={gemini_status} active_bench_sessions={'0' if all_ok else 'blocked'}",
        flush=True,
    )
    return all_ok


# ---------------------------------------------------------------------------
# Instruction router for skill injection
# ---------------------------------------------------------------------------


def _make_bench_instruction_router(skill_name: str):
    """Build an instruction_router that injects the skill's SKILL.md body at ALL depths.

    The instruction_router is called by before_agent_callback in orchestrator.py:431-453
    for every agent invocation (root and children spawned via llm_query()). Returning the
    skill text at all depths ensures that child agents spawned during recursive execution
    also receive the understand skill instructions, so the benchmark consistently evaluates
    the skill across the entire recursive execution tree.
    """
    from rlm_adk.skills.loader import discover_skill_dirs

    skill_text = ""
    for skill_dir in discover_skill_dirs({skill_name}):
        md_path = Path(skill_dir) / "SKILL.md"
        if md_path.is_file():
            raw = md_path.read_text()
            # Strip YAML frontmatter, keep instruction body
            if raw.startswith("---"):
                _, _, body = raw.split("---", 2)
                skill_text = body.strip()
            else:
                skill_text = raw.strip()
            break

    if not skill_text:
        print(
            f"[RLM:ERROR] Skill '{skill_name}' not found or has no SKILL.md body",
            flush=True,
        )

    def router(depth: int, fanout_idx: int) -> str:
        # Inject at ALL depths so children from llm_query() also get the skill
        return skill_text

    return router


# ---------------------------------------------------------------------------
# Case ID extraction helper
# ---------------------------------------------------------------------------


def _extract_case_id(path: Path) -> str:
    """Extract case_id from a case JSON file path (filename without extension)."""
    return path.stem


# ---------------------------------------------------------------------------
# Telemetry emission
# ---------------------------------------------------------------------------


def emit_telemetry(line: str) -> None:
    """Print a telemetry line to stdout."""
    print(line, flush=True)


# ---------------------------------------------------------------------------
# Manifest writing
# ---------------------------------------------------------------------------


def _write_manifest(
    skill: str,
    status: str,
    difficulty_filter: str | None,
    case_filter: str | None,
    expected_cases: int,
    completed_cases: int,
    trace_ids: list[str],
    suite_result: dict,
    per_case: list[dict],
) -> None:
    """Write bench_manifest.json to the .adk/ runtime directory."""
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "skill": skill,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": status,
        "filter": {"difficulty": difficulty_filter, "case": case_filter},
        "expected_cases": expected_cases,
        "completed_cases": completed_cases,
        "trace_ids": trace_ids,
        "db_path": str(_DB_PATH),
        "suite_result": suite_result,
        "per_case": per_case,
    }
    _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


# ---------------------------------------------------------------------------
# Async main
# ---------------------------------------------------------------------------


async def main() -> None:
    args = _parse_args()

    # Pre-flight
    if not await preflight():
        print("[RLM:ERROR] Pre-flight checks failed. Aborting.", flush=True)
        sys.exit(1)

    # Imports (after sys.path setup)
    from rlm_adk.agent import create_rlm_runner
    from rlm_adk.eval.understand_bench_v2.agent_bridge import (
        run_case_async,
    )
    from rlm_adk.eval.understand_bench_v2.loader import (
        build_manifest,
        discover_cases,
        load_case_with_gold,
        resolve_file_path,
    )
    from rlm_adk.eval.understand_bench_v2.scoring import score_result

    # Runner construction
    # CRITICAL: Do NOT pass plugins=[]. Omitting plugins lets it default to None,
    # which triggers _default_plugins(sqlite_tracing=True) and correctly includes
    # SqliteTracingPlugin.
    runner = create_rlm_runner(
        model=args.model,
        enabled_skills=[args.skill],
        sqlite_tracing=True,
        instruction_router=_make_bench_instruction_router(args.skill),
    )

    # Set max iterations via env var (consumed by orchestrator)
    os.environ["RLM_MAX_ITERATIONS"] = str(args.max_iterations)

    # Discover cases
    paths = discover_cases(difficulty=args.difficulty)

    # --case filtering
    if args.case:
        paths = [p for p in paths if _extract_case_id(p) == args.case]
        if not paths:
            print(
                f"[RLM:ERROR] case '{args.case}' not found "
                f"in difficulty={args.difficulty or 'all'}",
                flush=True,
            )
            sys.exit(1)

    expected_cases = len(paths)

    # Write initial manifest with status=running
    _write_manifest(
        skill=args.skill,
        status="running",
        difficulty_filter=args.difficulty,
        case_filter=args.case,
        expected_cases=expected_cases,
        completed_cases=0,
        trace_ids=[],
        suite_result={},
        per_case=[],
    )

    results = []
    trace_ids = []
    per_case = []

    for i, path in enumerate(paths, 1):
        case, gold = load_case_with_gold(path)
        manifest = build_manifest(case)

        # Build file metadata matching runner.py:104-117
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

        print(
            f"[RLM:CASE] n={i}/{expected_cases} id={case.case_id} "
            f"difficulty={case.difficulty} status=running",
            flush=True,
        )

        agent_output, trace_id = await run_case_async(
            runner,
            case.broad_objective,
            manifest,
            file_metadata,
            case.provided_files,
            case.processing_challenges,
            skill_name=args.skill,
            telemetry_cb=emit_telemetry,
        )
        trace_ids.append(trace_id)

        result = score_result(case, agent_output)
        results.append(result)

        per_case.append(
            {
                "case_id": case.case_id,
                "difficulty": case.difficulty,
                "score": result.total_score,
                "recall": result.recall,
                "precision": result.precision,
                "order_score": result.order_score,
                "halt_score": result.halt_score,
                "skill_score": result.skill_score,
                "trace_id": trace_id,
            }
        )

        print(
            f"[RLM:SCORE] id={case.case_id} total={result.total_score:.1f} "
            f"R={result.recall:.2f} P={result.precision:.2f} "
            f"O={result.order_score:.2f} H={result.halt_score:.0f} "
            f"S={result.skill_score:.2f}",
            flush=True,
        )

    # Suite summary
    passed = sum(1 for r in results if r.total_score >= 60.0)
    failed = len(results) - passed
    avg = sum(r.total_score for r in results) / len(results) if results else 0.0

    suite_result = {
        "cases": len(results),
        "passed": passed,
        "failed": failed,
        "avg_score": round(avg, 1),
    }

    print(
        f"[RLM:SUITE] cases={len(results)} passed={passed} failed={failed} "
        f"avg={avg:.1f} skill={args.skill}",
        flush=True,
    )
    print(
        f"[RLM:ACTION] type=review_and_improve skill={args.skill} db={_DB_PATH}",
        flush=True,
    )

    # Write final manifest with status=complete
    _write_manifest(
        skill=args.skill,
        status="complete",
        difficulty_filter=args.difficulty,
        case_filter=args.case,
        expected_cases=expected_cases,
        completed_cases=len(results),
        trace_ids=trace_ids,
        suite_result=suite_result,
        per_case=per_case,
    )

    await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
