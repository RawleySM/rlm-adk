"""Focused request-body fidelity checks for the roundtrip provider-fake fixture."""

import json

import pytest

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

FIXTURE_PATH = FIXTURE_DIR / "request_body_roundtrip.json"

_result_cache: dict[str, object] = {}


@pytest.fixture
async def contract_result():
    if "result" not in _result_cache:
        _result_cache["result"] = await run_fixture_contract(FIXTURE_PATH)
    return _result_cache["result"]


def _serialize(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _execute_code_response(request: dict) -> dict:
    for content in request.get("contents", []):
        for part in content.get("parts", []):
            function_response = part.get("functionResponse")
            if function_response and function_response.get("name") == "execute_code":
                response = function_response.get("response")
                if isinstance(response, dict):
                    return response
    raise AssertionError("missing execute_code functionResponse")


async def test_fixture_passes(contract_result):
    assert contract_result.passed, contract_result.diagnostics()


async def test_captured_metadata_matches_single_child_dispatch(contract_result):
    assert contract_result.captured_metadata == [
        {"call_index": 0, "caller": "reasoning"},
        {"call_index": 1, "caller": "worker"},
        {"call_index": 2, "caller": "reasoning"},
    ]


async def test_parent_function_response_proves_child_dispatch(contract_result):
    response = _execute_code_response(contract_result.captured_requests[2])

    assert response["llm_calls_made"] is True
    assert response["call_number"] == 1
    assert "WORKER_RESPONSE_START" in response["stdout"]
    assert "STDOUT_SENTINEL_START" in response["stdout"]
    assert "ARTIFACT_START" in _serialize(response["variables"]["artifact"])
    assert "WORKER_RESPONSE_START" in response["variables"]["result"]


async def test_worker_request_preserves_hidden_child_context(contract_result):
    worker_request = contract_result.captured_requests[1]
    worker_text = _serialize(worker_request)
    parent_stdout = _execute_code_response(contract_result.captured_requests[2])["stdout"]

    assert "child_reasoning_d1" in worker_text
    assert "DYNAMIC_CONTEXT_START" in worker_text
    assert "WORKER_INSTRUCTION_START" in worker_text
    assert "ARTIFACT_START" in worker_text
    assert "called tool `execute_code`" in worker_text

    assert "WORKER_INSTRUCTION_START" not in parent_stdout
    assert "ARTIFACT_START" not in parent_stdout


async def test_expected_contract_checks_are_exercised(contract_result):
    checked_fields = {check["field"] for check in contract_result.checks}
    assert "contract:callers.sequence" in checked_fields
    assert "contract:captured_requests.count" in checked_fields
    assert "contract:events.part_sequence" in checked_fields
    assert "contract:tool_results.any[0]" in checked_fields
    assert "contract:observability:obs:child_dispatch_count" in checked_fields
