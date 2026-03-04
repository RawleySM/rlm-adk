"""Comprehensive request body verification — closes all 9 gaps (G1–G9) identified
in the data flow audit.

Gap coverage:
  G1: Dict-typed state key in dynamic instruction (test_context as nested dict)
  G2: Variable persistence across REPL iterations (repo_xml, metadata in iter 2)
  G3: Prior worker result chaining into next worker prompt
  G4: Multiple data sources combined in single worker prompt
  G5: Data loaded from REPL globals (mock pack_repo + _test_metadata)
  G6: functionResponse variables dict fidelity (nested dict, list values)
  G7: Worker systemInstruction content
  G8: Worker generationConfig (temperature=0.0)
  G9: Dynamic instruction re-injection across all reasoning iterations

Fixture: request_body_comprehensive.json (5 calls, 2 workers, 2 REPL iterations)
"""

import json

import pytest

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract
from tests_rlm_adk.provider_fake.fixtures import save_captured_requests

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

FIXTURE_PATH = FIXTURE_DIR / "request_body_comprehensive.json"


def _serialize(req: dict) -> str:
    """Serialize a request body preserving Unicode markers."""
    return json.dumps(req, ensure_ascii=False)


def _find_marker_content(text: str, start: str, end: str) -> str | None:
    """Extract content between start and end markers."""
    s = text.find(start)
    e = text.find(end)
    if s == -1 or e == -1 or e <= s:
        return None
    return text[s + len(start):e]


# ---------------------------------------------------------------------------
# Module-level cache: run fixture once, share across all tests
# ---------------------------------------------------------------------------

_result_cache: dict[str, object] = {}


@pytest.fixture
async def contract_result():
    """Run the comprehensive fixture once and cache the result."""
    if "result" not in _result_cache:
        _result_cache["result"] = await run_fixture_contract(FIXTURE_PATH)
    return _result_cache["result"]


# ---------------------------------------------------------------------------
# Baseline contract tests
# ---------------------------------------------------------------------------


async def test_fixture_passes(contract_result):
    """The comprehensive fixture should pass all contract assertions."""
    assert contract_result.passed, contract_result.diagnostics()


async def test_captured_request_count(contract_result):
    """Exactly 5 captured requests: reasoning1 + worker1 + reasoning2 + worker2 + reasoning3."""
    assert len(contract_result.captured_requests) == 5, (
        f"Expected 5 captured requests, got {len(contract_result.captured_requests)}"
    )


# ---------------------------------------------------------------------------
# G1: Dict-typed state key in dynamic instruction
# ---------------------------------------------------------------------------


async def test_g1_dict_state_in_system_instruction(contract_result):
    """Call 0 systemInstruction contains the dict-typed test_context with nested structure."""
    req = contract_result.captured_requests[0]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "DICT_STATE_START" in sys_text, (
        f"DICT_STATE_START not in call 0 systemInstruction: {sys_text[:300]}"
    )
    assert "DICT_STATE_END" in sys_text, (
        f"DICT_STATE_END not in call 0 systemInstruction: {sys_text[:300]}"
    )


async def test_g1_dict_state_nested_structure_preserved(contract_result):
    """Call 0 systemInstruction preserves nested dict fields (experiment_id, parameters, tags)."""
    req = contract_result.captured_requests[0]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "exp-42" in sys_text, "experiment_id 'exp-42' not in systemInstruction"
    assert "learning_rate" in sys_text, "nested parameters.learning_rate not in systemInstruction"
    assert "comprehensive" in sys_text, "tags list item 'comprehensive' not in systemInstruction"


# ---------------------------------------------------------------------------
# G5, G4, G2, G3: Worker prompt injection tests — REMOVED (Phase 3 migration)
# These tests verified data flow into leaf LlmAgent worker prompts.
# With child orchestrators, the prompt is passed to a child reasoning agent
# that has its own systemInstruction, tools, and call structure.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# G6: functionResponse variables dict fidelity
# ---------------------------------------------------------------------------


async def test_g6_function_response_has_variables(contract_result):
    """Call 2 (reasoning iter 2) has functionResponse with variables dict."""
    req = contract_result.captured_requests[2]
    contents = req.get("contents", [])
    func_resp_found = False
    for content in contents:
        for part in content.get("parts", []):
            if "functionResponse" in part:
                resp = part["functionResponse"].get("response", {})
                if "variables" in resp:
                    func_resp_found = True
                    break
        if func_resp_found:
            break
    assert func_resp_found, "Call 2 missing functionResponse with variables dict"


async def test_g6_variables_contain_repo_xml(contract_result):
    """Call 2 functionResponse variables include repo_xml string with full markers."""
    req = contract_result.captured_requests[2]
    req_str = _serialize(req)
    # The variables dict should have repo_xml as a key with the full mock value
    assert "repo_xml" in req_str, "repo_xml not in call 2 functionResponse variables"
    assert "REPO_XML_START" in req_str, "REPO_XML content truncated in functionResponse"


async def test_g6_variables_contain_metadata_dict(contract_result):
    """Call 2 functionResponse variables include _test_metadata as a nested dict."""
    req = contract_result.captured_requests[2]
    req_str = _serialize(req)
    # metadata is a dict with METADATA_START/END keys
    assert "METADATA_START" in req_str, "metadata dict not in call 2 functionResponse"
    assert "unit_test" in req_str, "metadata.source value not in functionResponse"
    assert "1.0.0" in req_str, "metadata.version value not in functionResponse"


# ---------------------------------------------------------------------------
# G7, G8: Worker systemInstruction + generationConfig — REMOVED (Phase 3)
# Child orchestrators have their own systemInstruction and generationConfig.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# G9: Dynamic instruction re-injection across iterations
# ---------------------------------------------------------------------------


async def test_g9_dynamic_instruction_in_reasoning_iter1(contract_result):
    """Call 0 systemInstruction contains dict-state markers from dynamic instruction."""
    req = contract_result.captured_requests[0]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "DICT_STATE_START" in sys_text, "Dynamic instruction missing in iter 1"


async def test_g9_dynamic_instruction_in_reasoning_iter2(contract_result):
    """Call 2 systemInstruction re-injects dict-state markers (persistence across iterations)."""
    req = contract_result.captured_requests[2]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "DICT_STATE_START" in sys_text, "Dynamic instruction missing in iter 2"
    assert "exp-42" in sys_text, "Nested experiment_id missing in iter 2 systemInstruction"


async def test_g9_dynamic_instruction_in_reasoning_iter3(contract_result):
    """Call 4 systemInstruction re-injects dict-state markers (final iteration)."""
    req = contract_result.captured_requests[4]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "DICT_STATE_START" in sys_text, "Dynamic instruction missing in iter 3"
    assert "exp-42" in sys_text, "Nested experiment_id missing in iter 3 systemInstruction"


# ---------------------------------------------------------------------------
# Structural verification (reasoning calls have tools, workers don't)
# ---------------------------------------------------------------------------


async def test_reasoning_calls_have_tools(contract_result):
    """All reasoning calls (0, 2, 4) have tools with execute_code."""
    for idx in (0, 2, 4):
        req = contract_result.captured_requests[idx]
        assert "tools" in req, f"Call {idx} missing tools"
        tools_str = json.dumps(req["tools"])
        assert "execute_code" in tools_str, f"Call {idx} missing execute_code tool"


    # test_worker_calls_lack_execute_code — REMOVED (Phase 3 migration)
    # Child orchestrators DO have execute_code as they are full reasoning agents.


# ---------------------------------------------------------------------------
# Stdout sentinels in reasoning iterations
# ---------------------------------------------------------------------------


async def test_stdout_sentinel_in_reasoning_iter2(contract_result):
    """Call 2 (reasoning iter 2) contains STDOUT_SENTINEL from iter 1 in functionResponse."""
    req_str = _serialize(contract_result.captured_requests[2])
    assert "STDOUT_SENTINEL_START" in req_str, "STDOUT_SENTINEL_START not in iter 2"
    assert "STDOUT_SENTINEL_END" in req_str, "STDOUT_SENTINEL_END not in iter 2"


async def test_stdout_sentinel_2_in_reasoning_iter3(contract_result):
    """Call 4 (reasoning iter 3) contains STDOUT_SENTINEL_2 from iter 2 in functionResponse."""
    req_str = _serialize(contract_result.captured_requests[4])
    assert "STDOUT_SENTINEL_2_START" in req_str, "STDOUT_SENTINEL_2_START not in iter 3"
    assert "STDOUT_SENTINEL_2_END" in req_str, "STDOUT_SENTINEL_2_END not in iter 3"


# ---------------------------------------------------------------------------
# CB_REASONING_CONTEXT: callback state dict in reasoning systemInstruction
# ---------------------------------------------------------------------------


async def test_cb_reasoning_context_in_reasoning_iter1(contract_result):
    """Call 0 systemInstruction contains CB_REASONING_STATE_START/END from test hook.

    The hook patches the already-resolved template text in llm_request.contents
    so the dict appears even on the first iteration (before ADK state-template
    resolution could pick it up).
    """
    req = contract_result.captured_requests[0]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "CB_REASONING_STATE_START" in sys_text, (
        f"CB_REASONING_STATE_START not in call 0 systemInstruction: {sys_text[:300]}"
    )
    assert "CB_REASONING_STATE_END" in sys_text, (
        f"CB_REASONING_STATE_END not in call 0 systemInstruction: {sys_text[:300]}"
    )


async def test_cb_reasoning_context_in_reasoning_iter2(contract_result):
    """Call 2 systemInstruction contains CB_REASONING_STATE markers (re-injected)."""
    req = contract_result.captured_requests[2]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "CB_REASONING_STATE_START" in sys_text, (
        "CB_REASONING_STATE_START not in call 2 systemInstruction"
    )


async def test_cb_reasoning_context_in_reasoning_iter3(contract_result):
    """Call 4 systemInstruction contains CB_REASONING_STATE markers (final iteration)."""
    req = contract_result.captured_requests[4]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "CB_REASONING_STATE_START" in sys_text, (
        "CB_REASONING_STATE_START not in call 4 systemInstruction"
    )


async def test_cb_reasoning_context_has_hook_name(contract_result):
    """Reasoning iter 2+ systemInstruction contains the hook function name.

    The hook dict flows into systemInstruction starting from the second
    reasoning call (call 2) because ADK resolves {cb_reasoning_context?}
    from state written by the prior iteration's before_model_callback.
    """
    req = contract_result.captured_requests[2]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "reasoning_test_state_hook" in sys_text, (
        "Hook name not in call 2 systemInstruction — dict may not be fully serialized"
    )


# ---------------------------------------------------------------------------
# CB_WORKER_CONTEXT — REMOVED (Phase 3 migration)
# Worker hooks are no longer wired via _create_worker monkey-patching.
# Child orchestrators are spawned on-demand and cannot be pre-hooked.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CB_ORCHESTRATOR_CONTEXT: before_agent_callback dict in systemInstruction
# ---------------------------------------------------------------------------


async def test_cb_orchestrator_context_in_reasoning_iter1(contract_result):
    """Call 0 systemInstruction contains CB_ORCHESTRATOR_STATE_START/END.

    before_agent_callback fires before the first LLM call, so the dict is
    in state for the very first template resolution (call 0).
    """
    req = contract_result.captured_requests[0]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "CB_ORCHESTRATOR_STATE_START" in sys_text, (
        f"CB_ORCHESTRATOR_STATE_START not in call 0 systemInstruction: {sys_text[:300]}"
    )
    assert "CB_ORCHESTRATOR_STATE_END" in sys_text, (
        f"CB_ORCHESTRATOR_STATE_END not in call 0 systemInstruction: {sys_text[:300]}"
    )


async def test_cb_orchestrator_context_in_reasoning_iter2(contract_result):
    """Call 2 systemInstruction contains orchestrator markers (persists across iterations)."""
    req = contract_result.captured_requests[2]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "CB_ORCHESTRATOR_STATE_START" in sys_text, (
        "CB_ORCHESTRATOR_STATE_START not in call 2 systemInstruction"
    )


async def test_cb_orchestrator_context_in_reasoning_iter3(contract_result):
    """Call 4 systemInstruction contains orchestrator markers (final iteration)."""
    req = contract_result.captured_requests[4]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "CB_ORCHESTRATOR_STATE_START" in sys_text, (
        "CB_ORCHESTRATOR_STATE_START not in call 4 systemInstruction"
    )


async def test_cb_orchestrator_context_has_hook_name(contract_result):
    """Call 0 systemInstruction contains orchestrator hook function name."""
    req = contract_result.captured_requests[0]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "orchestrator_test_state_hook" in sys_text, (
        "Orchestrator hook name not in call 0 systemInstruction"
    )


# ---------------------------------------------------------------------------
# CB_TOOL_CONTEXT: before_tool_callback dict in systemInstruction
# ---------------------------------------------------------------------------


async def test_cb_tool_context_in_reasoning_iter2(contract_result):
    """Call 2 systemInstruction contains CB_TOOL_STATE_START/END.

    before_tool_callback fires before each execute_code call. After the first
    tool execution (between call 0 and call 2), the dict is in state for
    call 2's template resolution.
    """
    req = contract_result.captured_requests[2]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "CB_TOOL_STATE_START" in sys_text, (
        f"CB_TOOL_STATE_START not in call 2 systemInstruction: {sys_text[:300]}"
    )
    assert "CB_TOOL_STATE_END" in sys_text, (
        f"CB_TOOL_STATE_END not in call 2 systemInstruction: {sys_text[:300]}"
    )


async def test_cb_tool_context_in_reasoning_iter3(contract_result):
    """Call 4 systemInstruction contains tool state markers (final iteration)."""
    req = contract_result.captured_requests[4]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "CB_TOOL_STATE_START" in sys_text, (
        "CB_TOOL_STATE_START not in call 4 systemInstruction"
    )


async def test_cb_tool_context_has_hook_name(contract_result):
    """Tool state dict contains the hook function name."""
    req = contract_result.captured_requests[2]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "tool_test_state_hook" in sys_text, (
        "Tool hook name not in call 2 systemInstruction"
    )


async def test_cb_tool_context_has_tool_name(contract_result):
    """Tool state dict contains the tool name 'execute_code'."""
    req = contract_result.captured_requests[2]
    sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
    assert "execute_code" in sys_text, (
        "Tool name 'execute_code' not in call 2 tool state dict"
    )


# ---------------------------------------------------------------------------
# Skill frontmatter in all reasoning calls
# ---------------------------------------------------------------------------


async def test_skill_frontmatter_in_all_reasoning_calls(contract_result):
    """All reasoning calls (0, 2, 4) systemInstruction has available_skills XML."""
    for idx in (0, 2, 4):
        req = contract_result.captured_requests[idx]
        sys_text = json.dumps(req.get("systemInstruction", {}), ensure_ascii=False)
        assert "<available_skills>" in sys_text, (
            f"Call {idx} systemInstruction missing <available_skills> XML"
        )


# ---------------------------------------------------------------------------
# JSON roundtrip test
# ---------------------------------------------------------------------------


async def test_save_captured_requests_roundtrip(contract_result, tmp_path):
    """Save captured requests to JSON, reload, verify basic structure survives."""
    out_path = tmp_path / "captured_comprehensive.json"
    save_captured_requests(contract_result.captured_requests, out_path)

    with open(out_path) as f:
        reloaded = json.load(f)

    assert len(reloaded) == len(contract_result.captured_requests)

    # Spot-check key markers in reasoning calls (indices 0, 2, 4)
    for idx in (0, 2, 4):
        if idx < len(reloaded):
            req_str = json.dumps(reloaded[idx], ensure_ascii=False)
            assert "DICT_STATE_START" in req_str, (
                f"DICT_STATE_START not found after roundtrip in call {idx}"
            )
