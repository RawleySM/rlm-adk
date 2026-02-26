"""CLI entry point for running fixture contracts.

Usage::

    python -m tests_rlm_adk.provider_fake                       # run all fixtures
    python -m tests_rlm_adk.provider_fake path/to/fix.json      # run specific fixture(s)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .conftest import FIXTURE_DIR
from .contract_runner import run_fixture_contract
from .fixtures import ContractResult


def _discover_fixtures(args: list[str]) -> list[Path]:
    """Resolve fixture paths from CLI args, or glob all from FIXTURE_DIR."""
    if args:
        return [Path(a) for a in args]
    return sorted(FIXTURE_DIR.glob("*.json"))


async def _run_all(fixtures: list[Path]) -> list[ContractResult]:
    results: list[ContractResult] = []
    for fixture_path in fixtures:
        print(f"\n--- {fixture_path.stem} ---")
        try:
            result = await run_fixture_contract(fixture_path)
            results.append(result)
            if result.passed:
                print(result.summary_line())
            else:
                print(result.diagnostics())
        except Exception as exc:
            print(f"[ERROR] {fixture_path.stem}: {exc}")
            results.append(ContractResult(
                fixture_path=str(fixture_path),
                scenario_id=fixture_path.stem,
                passed=False,
                checks=[{"field": "exception", "expected": "no error", "actual": str(exc), "ok": False}],
                call_summary=[],
                total_elapsed_s=0.0,
            ))
    return results


def main() -> None:
    fixtures = _discover_fixtures(sys.argv[1:])
    if not fixtures:
        print("No fixture files found.")
        sys.exit(1)

    print(f"Running {len(fixtures)} fixture contract(s)...")
    results = asyncio.run(_run_all(fixtures))

    # Summary table
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        print(f"  {r.summary_line()}")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    print(f"\n{passed} passed, {failed} failed out of {len(results)} fixture(s)")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
