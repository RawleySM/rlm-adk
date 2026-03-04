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
# G5: REPL globals injection (mock pack_repo + _test_metadata)
# ---------------------------------------------------------------------------


async def test_g5_repo_xml_in_worker1_prompt(contract_result):
    """Call 1 (worker 1) contains REPO_XML_START/END markers from mock pack_repo."""
    req_str = _serialize(contract_result.captured_requests[1])
    assert "REPO_XML_START" in req_str, "REPO_XML_START not in worker 1 request"
    assert "REPO_XML_END" in req_str, "REPO_XML_END not in worker 1 request"


async def test_g5_repo_xml_content_not_truncated(contract_result):
    """Call 1 (worker 1) contains full repo XML including file contents."""
    req_str = _serialize(contract_result.captured_requests[1])
    content = _find_marker_content(req_str, "«REPO_XML_START»", "«REPO_XML_END»")
    assert content is not None, "Could not extract REPO_XML content"
    assert "test-repo" in content, "repo name not in REPO_XML"
    assert "main.py" in content, "main.py not in REPO_XML"
    assert "utils.py" in content, "utils.py not in REPO_XML"


async def test_g5_metadata_dict_in_worker1_prompt(contract_result):
    """Call 1 (worker 1) contains METADATA_START/END markers from _test_metadata global."""
    req_str = _serialize(contract_result.captured_requests[1])
    assert "METADATA_START" in req_str, "METADATA_START not in worker 1 request"
    assert "METADATA_END" in req_str, "METADATA_END not in worker 1 request"


# ---------------------------------------------------------------------------
# G4: Combined data sources in single worker prompt
# ---------------------------------------------------------------------------


async def test_g4_combined_prompt_markers(contract_result):
    """Call 1 (worker 1) contains COMBINED_PROMPT_START/END wrapping both sources."""
    req_str = _serialize(contract_result.captured_requests[1])
    assert "COMBINED_PROMPT_START" in req_str, "COMBINED_PROMPT_START not in worker 1"
    assert "COMBINED_PROMPT_END" in req_str, "COMBINED_PROMPT_END not in worker 1"


async def test_g4_both_sources_in_combined_prompt(contract_result):
    """Call 1 combined prompt contains BOTH repo XML markers AND metadata markers."""
    req_str = _serialize(contract_result.captured_requests[1])
    content = _find_marker_content(req_str, "«COMBINED_PROMPT_START»", "«COMBINED_PROMPT_END»")
    assert content is not None, "Could not extract COMBINED_PROMPT content"
    assert "REPO_XML_START" in content, "REPO_XML not inside COMBINED_PROMPT"
    assert "METADATA_START" in content, "METADATA not inside COMBINED_PROMPT"


# ---------------------------------------------------------------------------
# G2: Variable persistence across REPL iterations
# ---------------------------------------------------------------------------


async def test_g2_persisted_repo_xml_in_worker2(contract_result):
    """Call 3 (worker 2) contains repo_xml persisted from iter 1."""
    req_str = _serialize(contract_result.captured_requests[3])
    assert "REPO_XML_START" in req_str, "Persisted repo_xml not in worker 2 request"
    assert "REPO_XML_END" in req_str, "Persisted repo_xml END not in worker 2 request"


async def test_g2_persisted_metadata_in_worker2(contract_result):
    """Call 3 (worker 2) contains metadata dict persisted from iter 1."""
    req_str = _serialize(contract_result.captured_requests[3])
    assert "METADATA_START" in req_str, "Persisted metadata not in worker 2 request"


# ---------------------------------------------------------------------------
# G3: Prior worker result chaining
# ---------------------------------------------------------------------------


async def test_g3_chained_prompt_markers(contract_result):
    """Call 3 (worker 2) contains CHAINED_PROMPT_START/END markers."""
    req_str = _serialize(contract_result.captured_requests[3])
    assert "CHAINED_PROMPT_START" in req_str, "CHAINED_PROMPT_START not in worker 2"
    assert "CHAINED_PROMPT_END" in req_str, "CHAINED_PROMPT_END not in worker 2"


async def test_g3_prior_worker_result_in_chained_prompt(contract_result):
    """Call 3 (worker 2) contains worker 1's response text in the chained prompt."""
    req_str = _serialize(contract_result.captured_requests[3])
    content = _find_marker_content(req_str, "«CHAINED_PROMPT_START»", "«CHAINED_PROMPT_END»")
    assert content is not None, "Could not extract CHAINED_PROMPT content"
    assert "WORKER_RESPONSE_1_START" in content, "Worker 1 response not in chained prompt"
    assert "arithmetic operations" in content, "Worker 1 content not in chained prompt"


async def test_g3_chained_prompt_has_both_old_and_new_data(contract_result):
    """Call 3 chained prompt has BOTH prior worker result AND original repo XML."""
    req_str = _serialize(contract_result.captured_requests[3])
    content = _find_marker_content(req_str, "«CHAINED_PROMPT_START»", "«CHAINED_PROMPT_END»")
    assert content is not None, "Could not extract CHAINED_PROMPT content"
    assert "WORKER_RESPONSE_1_START" in content, "Prior worker result missing"
    assert "REPO_XML_START" in content, "Original repo XML missing from chained prompt"


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
# G7: Worker systemInstruction content
# ---------------------------------------------------------------------------


async def test_g7_worker_has_system_instruction(contract_result):
    """Call 1 (worker) has systemInstruction with 'Answer the user' instruction."""
    req = contract_result.captured_requests[1]
    assert "systemInstruction" in req, "Worker request missing systemInstruction"
    sys_text = json.dumps(req["systemInstruction"], ensure_ascii=False)
    assert "Answer" in sys_text, (
        f"Worker systemInstruction missing expected instruction: {sys_text[:200]}"
    )


# ---------------------------------------------------------------------------
# G8: Worker generationConfig
# ---------------------------------------------------------------------------


async def test_g8_worker_generation_config(contract_result):
    """Call 1 (worker) has generationConfig with temperature=0.0."""
    req = contract_result.captured_requests[1]
    assert "generationConfig" in req, "Worker request missing generationConfig"
    gen_config = req["generationConfig"]
    # temperature may be 0 or 0.0
    assert gen_config.get("temperature") == 0 or gen_config.get("temperature") == 0.0, (
        f"Worker temperature not 0.0: {gen_config}"
    )


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


async def test_worker_calls_lack_execute_code(contract_result):
    """Worker calls (1, 3) should NOT have execute_code in tools."""
    for idx in (1, 3):
        req = contract_result.captured_requests[idx]
        if "tools" in req:
            tools_str = json.dumps(req["tools"])
            assert "execute_code" not in tools_str, (
                f"Worker call {idx} should not have execute_code tool"
            )


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
# CB_WORKER_CONTEXT: callback state dict in worker request contents
# ---------------------------------------------------------------------------


async def test_cb_worker_context_in_worker1(contract_result):
    """Call 1 (worker 1) contents contain CB_WORKER_STATE_START/END from test hook."""
    req_str = _serialize(contract_result.captured_requests[1])
    assert "CB_WORKER_STATE_START" in req_str, (
        f"CB_WORKER_STATE_START not in worker 1 request: {req_str[:300]}"
    )
    assert "CB_WORKER_STATE_END" in req_str, (
        f"CB_WORKER_STATE_END not in worker 1 request: {req_str[:300]}"
    )


async def test_cb_worker_context_in_worker2(contract_result):
    """Call 3 (worker 2) contents contain CB_WORKER_STATE markers."""
    req_str = _serialize(contract_result.captured_requests[3])
    assert "CB_WORKER_STATE_START" in req_str, (
        "CB_WORKER_STATE_START not in worker 2 request"
    )


async def test_cb_worker_context_has_hook_name(contract_result):
    """Worker request contains the hook function name in the context dict."""
    req_str = _serialize(contract_result.captured_requests[1])
    assert "worker_test_state_hook" in req_str, (
        "Hook name not in worker request — dict may not be fully serialized"
    )


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
    """Save captured requests to JSON, reload, verify all markers survive."""
    out_path = tmp_path / "captured_comprehensive.json"
    save_captured_requests(contract_result.captured_requests, out_path)

    with open(out_path) as f:
        reloaded = json.load(f)

    assert len(reloaded) == 5

    # Spot-check key markers in reloaded data
    markers_by_call = {
        1: ["REPO_XML_START", "METADATA_START", "COMBINED_PROMPT_START"],
        3: ["CHAINED_PROMPT_START", "WORKER_RESPONSE_1_START", "REPO_XML_START"],
    }
    for call_idx, markers in markers_by_call.items():
        req_str = json.dumps(reloaded[call_idx], ensure_ascii=False)
        for marker in markers:
            assert marker in req_str, (
                f"{marker} not found after roundtrip in call {call_idx}"
            )
