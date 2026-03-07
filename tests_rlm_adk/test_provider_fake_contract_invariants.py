from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]


def _write_fixture(tmp_path: Path, fixture_name: str, updates: dict) -> Path:
    fixture = json.loads((FIXTURE_DIR / fixture_name).read_text())
    fixture.update(updates)
    path = tmp_path / fixture_name.replace("/", "_")
    path.write_text(json.dumps(fixture, indent=2))
    return path


async def test_contract_invariants_cover_callers_events_tool_results_and_obs(tmp_path: Path):
    fixture_path = _write_fixture(
        tmp_path,
        "repl_runtime_error.json",
        {
            "expected_contract": {
                "callers": {
                    "sequence": ["reasoning", "reasoning", "reasoning"],
                    "counts": {"reasoning": 3},
                    "count": 3,
                },
                "captured_requests": {"count": 3},
                "events": {
                    "part_counts": {
                        "function_call:execute_code": 2,
                        "function_response:execute_code": 2,
                        "text": {"$gte": 2},
                    },
                    "part_sequence": [
                        {"kind": "function_call", "name": "execute_code", "role": "model"},
                        {"kind": "function_response", "name": "execute_code", "role": "user"},
                        {"kind": "function_call", "name": "execute_code", "role": "model"},
                        {"kind": "function_response", "name": "execute_code", "role": "user"},
                    ],
                },
                "tool_results": {
                    "count": 2,
                    "stdout_contains": "Runtime fixed: hello world",
                    "stderr_contains": "NameError",
                    "any": [
                        {
                            "function_name": "execute_code",
                            "llm_calls_made": False,
                            "stderr": {"$contains": "NameError"},
                        },
                        {
                            "function_name": "execute_code",
                            "stdout": {"$contains": "Runtime fixed: hello world"},
                            "stderr": "",
                        },
                    ],
                },
                "observability": {
                    "counters": {
                        "obs:total_calls": {"$gte": 3},
                        "obs:tool_invocation_summary": {
                            "execute_code": 2,
                        },
                    },
                },
            },
        },
    )

    result = await run_fixture_contract(fixture_path)

    assert result.passed, result.diagnostics()
    checked_fields = {check["field"] for check in result.checks}
    assert "contract:callers.sequence" in checked_fields
    assert "contract:events.part_sequence" in checked_fields
    assert "contract:tool_results.any[0]" in checked_fields
    assert "contract:observability:obs:tool_invocation_summary" in checked_fields


@pytest.mark.agent_challenge
async def test_contract_invariants_fail_when_fixture_falls_back_to_exhausted_response(tmp_path: Path):
    fixture_path = _write_fixture(
        tmp_path,
        "agent_challenge/happy_path_single_iteration.json",
        {
            "responses": [],
            "expected": {
                "final_answer": "fixture-exhausted",
                "total_iterations": 0,
                "total_model_calls": 1,
            },
        },
    )

    result = await run_fixture_contract(fixture_path)

    assert not result.passed
    failed_checks = {check["field"]: check for check in result.checks if not check["ok"]}
    assert "fixture_exhausted_fallback" in failed_checks
    assert failed_checks["fixture_exhausted_fallback"]["actual"] is True
    assert "call indices" in failed_checks["fixture_exhausted_fallback"]["detail"]
