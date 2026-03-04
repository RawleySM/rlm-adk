"""Request body verification — asserts captured request bodies contain
complete marker-delimited content from reasoning agent and worker calls."""

import json
from pathlib import Path

import pytest

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract
from tests_rlm_adk.provider_fake.fixtures import save_captured_requests

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

FIXTURE_PATH = FIXTURE_DIR / "request_body_roundtrip.json"

# Marker pairs: (start, end, description, expected_call_indices)
MARKERS = [
    ("«ARTIFACT_START»", "«ARTIFACT_END»", "artifact dict in worker request", [1]),
    ("«WORKER_INSTRUCTION_START»", "«WORKER_INSTRUCTION_END»", "instruction string in worker request", [1]),
    ("«WORKER_RESPONSE_START»", "«WORKER_RESPONSE_END»", "worker response in reasoning iter 2", [2]),
    ("«STDOUT_SENTINEL_START»", "«STDOUT_SENTINEL_END»", "stdout sentinel in reasoning iter 2", [2]),
    ("«FINAL_ANSWER_START»", "«FINAL_ANSWER_END»", "final answer in session state", None),
]


def _serialize_request(req: dict) -> str:
    """Serialize a request body to string, preserving Unicode markers."""
    return json.dumps(req, ensure_ascii=False)


def _find_marker_content(text: str, start: str, end: str) -> str | None:
    """Extract content between start and end markers, or None if not found."""
    s = text.find(start)
    e = text.find(end)
    if s == -1 or e == -1 or e <= s:
        return None
    return text[s + len(start):e]


# ---------------------------------------------------------------------------
# Module-level fixture: run once, share across all tests
# ---------------------------------------------------------------------------

_result_cache: dict[str, object] = {}


@pytest.fixture
async def contract_result():
    """Run the fixture once per module and cache the result."""
    if "result" not in _result_cache:
        _result_cache["result"] = await run_fixture_contract(FIXTURE_PATH)
    return _result_cache["result"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_fixture_passes(contract_result):
    """Basic contract assertion — the fixture should pass."""
    assert contract_result.passed, contract_result.diagnostics()


async def test_captured_request_count(contract_result):
    """Exactly 3 captured requests: reasoning iter1 + worker + reasoning iter2."""
    assert len(contract_result.captured_requests) == 3, (
        f"Expected 3 captured requests, got {len(contract_result.captured_requests)}"
    )


async def test_reasoning_request_has_system_instruction(contract_result):
    """Call 0 (reasoning) has systemInstruction containing 'execute_code'."""
    req = contract_result.captured_requests[0]
    assert "systemInstruction" in req, "Call 0 missing systemInstruction"
    sys_text = json.dumps(req["systemInstruction"], ensure_ascii=False)
    assert "execute_code" in sys_text, (
        f"systemInstruction does not mention 'execute_code': {sys_text[:200]}"
    )


async def test_reasoning_request_has_tools(contract_result):
    """Call 0 (reasoning) has tools with an execute_code function declaration."""
    req = contract_result.captured_requests[0]
    assert "tools" in req, "Call 0 missing tools"
    tools_str = json.dumps(req["tools"])
    assert "execute_code" in tools_str, (
        f"tools does not contain 'execute_code' declaration: {tools_str[:200]}"
    )


async def test_worker_request_contains_artifact_markers(contract_result):
    """Call 1 (worker) contains ARTIFACT_START and ARTIFACT_END."""
    req_str = _serialize_request(contract_result.captured_requests[1])
    assert "«ARTIFACT_START»" in req_str, "ARTIFACT_START not found in worker request"
    assert "«ARTIFACT_END»" in req_str, "ARTIFACT_END not found in worker request"


async def test_worker_request_contains_instruction_markers(contract_result):
    """Call 1 (worker) contains WORKER_INSTRUCTION_START and WORKER_INSTRUCTION_END."""
    req_str = _serialize_request(contract_result.captured_requests[1])
    assert "«WORKER_INSTRUCTION_START»" in req_str, "WORKER_INSTRUCTION_START not found in worker request"
    assert "«WORKER_INSTRUCTION_END»" in req_str, "WORKER_INSTRUCTION_END not found in worker request"


async def test_reasoning_iter2_contains_worker_response_markers(contract_result):
    """Call 2 (reasoning iter2) contains WORKER_RESPONSE_START and WORKER_RESPONSE_END."""
    req_str = _serialize_request(contract_result.captured_requests[2])
    assert "«WORKER_RESPONSE_START»" in req_str, "WORKER_RESPONSE_START not found in reasoning iter2 request"
    assert "«WORKER_RESPONSE_END»" in req_str, "WORKER_RESPONSE_END not found in reasoning iter2 request"


async def test_reasoning_iter2_contains_stdout_sentinel(contract_result):
    """Call 2 (reasoning iter2) contains STDOUT_SENTINEL_START and STDOUT_SENTINEL_END."""
    req_str = _serialize_request(contract_result.captured_requests[2])
    assert "«STDOUT_SENTINEL_START»" in req_str, "STDOUT_SENTINEL_START not found in reasoning iter2 request"
    assert "«STDOUT_SENTINEL_END»" in req_str, "STDOUT_SENTINEL_END not found in reasoning iter2 request"


async def test_reasoning_request_has_skill_frontmatter(contract_result):
    """Reasoning calls (0 and 2) systemInstruction contains skill frontmatter XML."""
    for idx in (0, 2):
        req = contract_result.captured_requests[idx]
        assert "systemInstruction" in req, f"Call {idx} missing systemInstruction"
        sys_text = json.dumps(req["systemInstruction"], ensure_ascii=False)
        assert "<available_skills>" in sys_text, (
            f"Call {idx} systemInstruction missing <available_skills> XML tag"
        )
        assert "repomix-repl-helpers" in sys_text, (
            f"Call {idx} systemInstruction missing 'repomix-repl-helpers' skill name"
        )


async def test_marker_content_not_truncated(contract_result):
    """For each marker pair with call indices, extract content and verify non-empty with expected substrings."""
    expected_substrings = {
        "«ARTIFACT_START»": ["repo_name", "files"],
        "«WORKER_INSTRUCTION_START»": ["Analyze", "artifact"],
        "«WORKER_RESPONSE_START»": ["simple Python project"],
        "«STDOUT_SENTINEL_START»": ["known stdout string"],
    }

    for start_marker, end_marker, desc, call_indices in MARKERS:
        if call_indices is None:
            continue  # FINAL_ANSWER checked via ContractResult
        for idx in call_indices:
            req_str = _serialize_request(contract_result.captured_requests[idx])
            content = _find_marker_content(req_str, start_marker, end_marker)
            assert content is not None, (
                f"Could not extract content between {start_marker} and {end_marker} "
                f"in call {idx} ({desc})"
            )
            assert len(content.strip()) > 0, (
                f"Empty content between {start_marker} and {end_marker} in call {idx}"
            )
            # Check expected substrings
            for substr in expected_substrings.get(start_marker, []):
                assert substr in content, (
                    f"Expected '{substr}' in content between {start_marker}..{end_marker} "
                    f"(call {idx}), got: {content[:200]}"
                )


# ---------------------------------------------------------------------------
# Structural verification tests — request body composition types
# ---------------------------------------------------------------------------


async def test_reasoning_request_has_generation_config(contract_result):
    """Call 0 (reasoning) has generationConfig key in the request body."""
    req = contract_result.captured_requests[0]
    assert "generationConfig" in req, "Call 0 missing generationConfig"


async def test_reasoning_iter2_has_generation_config(contract_result):
    """Call 2 (reasoning iter2) has generationConfig (same agent, same config)."""
    req = contract_result.captured_requests[2]
    assert "generationConfig" in req, "Call 2 missing generationConfig"


async def test_reasoning_call0_contents_structure(contract_result):
    """Call 0 (reasoning) has contents with at least one user-role part."""
    req = contract_result.captured_requests[0]
    assert "contents" in req, "Call 0 missing contents"
    contents = req["contents"]
    assert isinstance(contents, list), "contents is not a list"
    assert len(contents) >= 1, "contents is empty"
    # First content should be user role (the prompt)
    user_parts = [c for c in contents if c.get("role") == "user"]
    assert len(user_parts) >= 1, (
        f"No user-role content in call 0; roles: {[c.get('role') for c in contents]}"
    )


async def test_worker_request_has_contents_with_prompt(contract_result):
    """Call 1 (worker) has contents with the worker prompt text."""
    req = contract_result.captured_requests[1]
    assert "contents" in req, "Call 1 missing contents"
    contents = req["contents"]
    assert isinstance(contents, list), "worker contents is not a list"
    assert len(contents) >= 1, "worker contents is empty"
    # Worker contents should contain the dispatched prompt text
    req_str = _serialize_request(req["contents"])
    assert "WORKER_INSTRUCTION" in req_str or "Analyze" in req_str, (
        f"Worker contents does not contain expected prompt text: {req_str[:300]}"
    )


async def test_reasoning_iter2_has_function_response_parts(contract_result):
    """Call 2 (reasoning iter2) has functionResponse parts in contents (tool result from REPL)."""
    req = contract_result.captured_requests[2]
    assert "contents" in req, "Call 2 missing contents"
    contents = req["contents"]
    # Look for functionResponse parts anywhere in the contents history
    has_func_response = False
    for content in contents:
        for part in content.get("parts", []):
            if "functionResponse" in part:
                has_func_response = True
                break
        if has_func_response:
            break
    assert has_func_response, (
        "Call 2 contents missing functionResponse parts — "
        "REPL tool result should appear in conversation history"
    )


async def test_reasoning_iter2_has_function_call_parts(contract_result):
    """Call 2 (reasoning iter2) has functionCall parts in contents (model's prior tool call)."""
    req = contract_result.captured_requests[2]
    contents = req["contents"]
    has_func_call = False
    for content in contents:
        for part in content.get("parts", []):
            if "functionCall" in part:
                has_func_call = True
                break
        if has_func_call:
            break
    assert has_func_call, (
        "Call 2 contents missing functionCall parts — "
        "model's prior execute_code call should appear in conversation history"
    )


async def test_reasoning_iter2_contents_has_both_roles(contract_result):
    """Call 2 (reasoning iter2) has both user and model roles in contents history."""
    req = contract_result.captured_requests[2]
    contents = req["contents"]
    roles = {c.get("role") for c in contents}
    assert "user" in roles, f"No user-role content in call 2; roles: {roles}"
    assert "model" in roles, f"No model-role content in call 2; roles: {roles}"


async def test_worker_request_lacks_tools(contract_result):
    """Call 1 (worker) should NOT have tools — workers are text-only LLM calls."""
    req = contract_result.captured_requests[1]
    # Workers don't get tool declarations; if tools leak into worker requests
    # it wastes tokens and could cause unexpected function calls
    if "tools" in req:
        tools_str = json.dumps(req["tools"])
        assert "execute_code" not in tools_str, (
            "Worker request should not contain execute_code tool declaration"
        )


async def test_reasoning_requests_have_tools_consistently(contract_result):
    """Both reasoning calls (0 and 2) should have tools with execute_code."""
    for idx in (0, 2):
        req = contract_result.captured_requests[idx]
        assert "tools" in req, f"Call {idx} missing tools"
        tools_str = json.dumps(req["tools"])
        assert "execute_code" in tools_str, (
            f"Call {idx} tools missing execute_code: {tools_str[:200]}"
        )


async def test_reasoning_requests_have_system_instruction_consistently(contract_result):
    """Both reasoning calls (0 and 2) should have systemInstruction."""
    for idx in (0, 2):
        req = contract_result.captured_requests[idx]
        assert "systemInstruction" in req, f"Call {idx} missing systemInstruction"


# ---------------------------------------------------------------------------
# Dynamic instruction / initial_state tests
# ---------------------------------------------------------------------------


async def test_reasoning_request_contains_dynamic_context_markers(contract_result):
    """Call 0 systemInstruction contains dynamic context markers from initial_state."""
    req = contract_result.captured_requests[0]
    assert "systemInstruction" in req, "Call 0 missing systemInstruction"
    sys_text = json.dumps(req["systemInstruction"], ensure_ascii=False)
    assert "\u00abDYNAMIC_CONTEXT_START\u00bb" in sys_text, (
        f"DYNAMIC_CONTEXT_START not found in call 0 systemInstruction: {sys_text[:300]}"
    )
    assert "\u00abDYNAMIC_CONTEXT_END\u00bb" in sys_text, (
        f"DYNAMIC_CONTEXT_END not found in call 0 systemInstruction: {sys_text[:300]}"
    )


async def test_reasoning_iter2_contains_dynamic_context(contract_result):
    """Call 2 systemInstruction also has the dynamic context markers (persists across iterations)."""
    req = contract_result.captured_requests[2]
    assert "systemInstruction" in req, "Call 2 missing systemInstruction"
    sys_text = json.dumps(req["systemInstruction"], ensure_ascii=False)
    assert "\u00abDYNAMIC_CONTEXT_START\u00bb" in sys_text, (
        f"DYNAMIC_CONTEXT_START not found in call 2 systemInstruction: {sys_text[:300]}"
    )
    assert "\u00abDYNAMIC_CONTEXT_END\u00bb" in sys_text, (
        f"DYNAMIC_CONTEXT_END not found in call 2 systemInstruction: {sys_text[:300]}"
    )


# ---------------------------------------------------------------------------
# JSON roundtrip test
# ---------------------------------------------------------------------------


async def test_save_captured_requests_roundtrip(contract_result, tmp_path):
    """Save captured requests to JSON, reload, verify markers still present."""
    out_path = tmp_path / "captured_requests.json"
    save_captured_requests(contract_result.captured_requests, out_path)

    with open(out_path) as f:
        reloaded = json.load(f)

    assert len(reloaded) == 3

    # Verify markers survive the JSON roundtrip
    for start_marker, end_marker, desc, call_indices in MARKERS:
        if call_indices is None:
            continue
        for idx in call_indices:
            req_str = json.dumps(reloaded[idx], ensure_ascii=False)
            assert start_marker in req_str, (
                f"{start_marker} not found after roundtrip in call {idx} ({desc})"
            )
            assert end_marker in req_str, (
                f"{end_marker} not found after roundtrip in call {idx} ({desc})"
            )
