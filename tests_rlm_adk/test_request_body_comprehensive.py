"""Request-body fidelity checks for the comprehensive provider-fake fixture.

This suite mirrors the runtime/observability hardening pattern:
- runtime: parent-visible execute_code functionResponse payloads prove chained child use
- observability: captured worker requests + metadata retain hidden child context that
  parent stdout does not expose
"""

import json

import pytest

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract
from tests_rlm_adk.provider_fake.fixtures import save_captured_requests

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

FIXTURE_PATH = FIXTURE_DIR / "request_body_comprehensive.json"

_result_cache: dict[str, object] = {}


@pytest.fixture
async def contract_result():
    if "result" not in _result_cache:
        _result_cache["result"] = await run_fixture_contract(FIXTURE_PATH)
    return _result_cache["result"]


def _serialize(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _request_contents_text(request: dict) -> str:
    return _serialize(request.get("contents", []))


def _request_system_text(request: dict) -> str:
    return _serialize(request.get("systemInstruction", {}))


def _execute_code_responses(request: dict) -> list[dict]:
    responses = []
    for content in request.get("contents", []):
        for part in content.get("parts", []):
            function_response = part.get("functionResponse")
            if function_response and function_response.get("name") == "execute_code":
                response = function_response.get("response")
                if isinstance(response, dict):
                    responses.append(response)
    return responses


async def test_fixture_passes(contract_result):
    assert contract_result.passed, contract_result.diagnostics()


async def test_expected_contract_checks_cover_runtime_and_observability(contract_result):
    checked_fields = {check["field"] for check in contract_result.checks}
    assert "contract:callers.sequence" in checked_fields
    assert "contract:captured_requests.count" in checked_fields
    assert "contract:events.part_sequence" in checked_fields
    assert "contract:tool_results.any[0]" in checked_fields
    assert "contract:tool_results.any[1]" in checked_fields
    assert "contract:observability:obs:tool_invocation_summary" in checked_fields
    assert "contract:observability:obs:total_calls" in checked_fields


async def test_captured_metadata_preserves_reasoning_worker_call_sequence(contract_result):
    assert contract_result.captured_metadata == [
        {"call_index": 0, "caller": "reasoning"},
        {"call_index": 1, "caller": "worker"},
        {"call_index": 2, "caller": "reasoning"},
        {"call_index": 3, "caller": "worker"},
        {"call_index": 4, "caller": "reasoning"},
    ]


async def test_dynamic_context_reinjected_in_reasoning_request_contents(contract_result):
    for idx in (0, 2, 4):
        contents_text = _request_contents_text(contract_result.captured_requests[idx])
        assert "DICT_STATE_START" in contents_text, f"call {idx} missing dict marker"
        assert "exp-42" in contents_text, f"call {idx} missing experiment_id"
        assert "learning_rate" in contents_text, f"call {idx} missing nested parameters"
        assert "comprehensive" in contents_text, f"call {idx} missing tag list item"


async def test_parent_function_response_variables_preserve_repo_and_metadata(contract_result):
    response = _execute_code_responses(contract_result.captured_requests[2])[0]

    assert response["llm_calls_made"] is True
    assert response["call_number"] == 1
    assert "WORKER_RESPONSE_1_START" in response["stdout"]
    assert "STDOUT_SENTINEL_START" in response["stdout"]

    variables = response["variables"]
    assert "REPO_XML_START" in variables["repo_xml"]
    assert variables["metadata"]["source"] == "unit_test"
    assert variables["metadata"]["version"] == "1.0.0"
    assert "COMBINED_PROMPT_START" in variables["combined_prompt"]
    assert "WORKER_RESPONSE_1_START" in variables["result"]


async def test_parent_function_response_chain_proves_chained_child_use(contract_result):
    first_response, second_response = _execute_code_responses(contract_result.captured_requests[4])

    assert first_response["llm_calls_made"] is True
    assert second_response["llm_calls_made"] is True
    assert first_response["call_number"] == 1
    assert second_response["call_number"] == 2

    first_result = first_response["variables"]["result"]
    second_variables = second_response["variables"]
    assert second_variables["prior_analysis"] == first_result
    assert "CHAINED_PROMPT_START" in second_variables["synthesis_prompt"]
    assert "WORKER_RESPONSE_1_START" in second_variables["synthesis_prompt"]
    assert "REPO_XML_START" in second_variables["synthesis_prompt"]
    assert "METADATA_START" in second_variables["synthesis_prompt"]
    assert "WORKER_RESPONSE_2_START" in second_variables["final_result"]

    # Parent stdout proves the child ran, but omits the full hidden prompt context.
    assert "WORKER_RESPONSE_2_START" in second_response["stdout"]
    assert "CHAINED_PROMPT_START" not in second_response["stdout"]
    assert "REPO_XML_START" not in second_response["stdout"]


async def test_worker_requests_preserve_hidden_child_context_not_visible_in_stdout(contract_result):
    first_worker = contract_result.captured_requests[1]
    second_worker = contract_result.captured_requests[3]
    first_worker_text = _serialize(first_worker)
    second_worker_text = _serialize(second_worker)
    parent_stdout = _execute_code_responses(contract_result.captured_requests[4])[1]["stdout"]

    assert "child_reasoning_d1" in _request_system_text(first_worker)
    assert "DICT_STATE_START" in first_worker_text
    assert "called tool `execute_code`" in first_worker_text
    assert "COMBINED_PROMPT_START" in first_worker_text
    assert "WORKER_RESPONSE_1_START" not in first_worker_text

    assert "child_reasoning_d1" in _request_system_text(second_worker)
    assert "DICT_STATE_START" in second_worker_text
    assert "execute_code` tool returned result" in second_worker_text
    assert "WORKER_RESPONSE_1_START" in second_worker_text
    assert "CHAINED_PROMPT_START" in second_worker_text
    assert "REPO_XML_START" in second_worker_text

    assert "CHAINED_PROMPT_START" not in parent_stdout
    assert "REPO_XML_START" not in parent_stdout


async def test_reasoning_and_child_requests_keep_execute_code_tool_surface(contract_result):
    for idx in range(len(contract_result.captured_requests)):
        request = contract_result.captured_requests[idx]
        assert "tools" in request, f"call {idx} missing tools"
        assert "execute_code" in _serialize(request["tools"]), f"call {idx} missing execute_code"


async def test_save_captured_requests_with_metadata_roundtrip(contract_result, tmp_path):
    output_path = tmp_path / "captured_comprehensive.json"
    save_captured_requests(
        contract_result.captured_requests,
        output_path,
        contract_result.captured_metadata,
    )

    reloaded = json.loads(output_path.read_text())
    assert sorted(reloaded) == [
        "request_to_reasoning_agent_iter_1",
        "request_to_reasoning_agent_iter_2",
        "request_to_reasoning_agent_iter_3",
        "request_to_worker_iter_1",
        "request_to_worker_iter_2",
    ]
    assert reloaded["request_to_worker_iter_2"]["_meta"] == {
        "call_index": 3,
        "caller": "worker",
        "model": "worker",
        "iteration": 2,
    }
    assert "CHAINED_PROMPT_START" in _serialize(reloaded["request_to_worker_iter_2"]["body"])
