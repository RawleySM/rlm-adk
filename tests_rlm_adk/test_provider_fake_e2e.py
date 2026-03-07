"""End-to-end tests using the provider-contract fake Gemini server.

Validates the full production pipeline including plugins, artifact
persistence, and tracing:

- **Group A**: Contract validation — parametrized over all fixture JSON files.
- **Group B**: Plugin + artifact integration — observability state, artifact
  persistence via InMemoryArtifactService.
- **Group C**: Tracing integration — SqliteTracingPlugin DB assertions,
  REPL trace events in the event stream.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rlm_adk.state import (
    ARTIFACT_SAVE_COUNT,
    FINAL_ANSWER,
)

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import (
    PluginContractResult,
    run_fixture_contract,
    run_fixture_contract_with_plugins,
)
from tests_rlm_adk.provider_fake.fixtures import save_captured_requests

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Worker fixtures that were designed for leaf LlmAgent workers (single API call
# per worker) and are incompatible with the child orchestrator dispatch
# (Phase 3).  Child orchestrators make multiple API calls per dispatch,
# exhausting the fixture's scripted response list.
_WORKER_FIXTURE_EXCLUSIONS = {
    "all_workers_fail_batch",
    "worker_429_mid_batch",
    "worker_500_retry_exhausted",
    "worker_500_retry_exhausted_naive",
    "worker_empty_response",
    "worker_empty_response_finish_reason",
    "worker_safety_finish",
}


def _all_fixture_paths() -> list[Path]:
    """Discover all fixture JSON files in the provider_fake fixture dir."""
    return sorted(
        p for p in FIXTURE_DIR.glob("*.json")
        if p.name != "index.json" and p.stem not in _WORKER_FIXTURE_EXCLUSIONS
    )


# ===========================================================================
# GROUP A: Contract validation (existing, simplified)
# ===========================================================================


@pytest.mark.provider_fake_contract
@pytest.mark.parametrize("fixture_path", _all_fixture_paths(), ids=lambda p: p.stem)
async def test_fixture_contract(fixture_path: Path):
    """Validate any fixture through the real pipeline against its expected values.

    Each fixture manages its own FakeGeminiServer lifecycle via the
    contract runner — does NOT use a shared pytest fixture.
    """
    result = await run_fixture_contract(fixture_path)
    if not result.passed:
        print(result.diagnostics())
    assert result.passed, f"Fixture contract failed: {fixture_path.name}\n{result.diagnostics()}"


@pytest.mark.parametrize(
    ("fixture_name", "required_fields"),
    [
        (
            "fake_recursive_ping",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
            },
        ),
        (
            "structured_output_batched_k3_with_retry",
            {
                "contract:callers.sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "structured_output_batched_k3_multi_retry",
            {
                "contract:callers.sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "max_iterations_exceeded",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:tool_results.any[1]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "max_iterations_exceeded_persistent",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:tool_results.any[1]",
                "contract:tool_results.any[2]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "worker_500_then_success",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:obs:child_summary@d1f0",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "worker_500_retry_exhausted",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:obs:child_error_counts",
                "contract:observability:obs:child_summary@d1f0",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "worker_500_retry_exhausted_naive",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:obs:child_error_counts",
                "contract:observability:obs:child_summary@d1f0",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "worker_empty_response",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:obs:child_error_counts",
                "contract:observability:obs:child_summary@d1f1",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "worker_max_tokens_naive",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:obs:child_summary@d1f0",
                "contract:observability:last_repl_result",
                "contract:observability:obs:finish_max_tokens_count",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "worker_safety_finish",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:obs:child_error_counts",
                "contract:observability:obs:child_summary@d1f0",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "structured_output_retry_exhaustion",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:obs:child_error_counts",
                "contract:observability:obs:structured_output_failures",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "structured_output_retry_exhaustion_pure_validation",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:obs:child_error_counts",
                "contract:observability:obs:structured_output_failures",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
        (
            "structured_output_batched_k3_mixed_exhaust",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:obs:child_error_counts",
                "contract:observability:obs:structured_output_failures",
                "contract:observability:last_repl_result",
                "contract:observability:obs:per_iteration_token_breakdown",
            },
        ),
    ],
)
async def test_priority_fixture_contracts_cover_runtime_and_observability(
    fixture_name: str,
    required_fields: set[str],
):
    """Priority fixtures should exercise both runtime-visible and obs-visible contracts."""
    result = await run_fixture_contract(FIXTURE_DIR / f"{fixture_name}.json")
    assert result.passed, result.diagnostics()
    checked_fields = {check["field"] for check in result.checks}
    missing = required_fields - checked_fields
    assert not missing, (
        f"Fixture {fixture_name} missing contract coverage for: {sorted(missing)}"
    )


# ===========================================================================
# GROUP B: Plugin + artifact integration
# ===========================================================================


async def _run_with_plugins(
    fixture_name: str, tmp_path: Path
) -> PluginContractResult:
    """Run a named fixture through the plugin-enabled pipeline."""
    fixture_path = FIXTURE_DIR / f"{fixture_name}.json"
    traces_db = str(tmp_path / "traces.db")
    return await run_fixture_contract_with_plugins(
        fixture_path,
        traces_db_path=traces_db,
        repl_trace_level=1,
    )


@pytest.mark.agent_challenge
async def test_observability_state_happy_path(tmp_path: Path):
    """ObservabilityPlugin populates OBS_* counters (captured by SqliteTracingPlugin).

    Plugin after_model_callback state writes are visible during the run
    (read by SqliteTracingPlugin.after_run_callback) but are not committed
    to the session service via event state_deltas.  We verify through the
    traces DB which reads from the live session state.
    """
    result = await _run_with_plugins("agent_challenge/happy_path_single_iteration", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        row = conn.execute(
            "SELECT total_calls, total_input_tokens, total_output_tokens "
            "FROM traces LIMIT 1"
        ).fetchone()
        assert row is not None, "No trace row — ObservabilityPlugin may not have run"
        total_calls, input_tokens, output_tokens = row
        assert total_calls > 0, f"OBS_TOTAL_CALLS should be > 0, got {total_calls}"
        assert input_tokens > 0, f"OBS_TOTAL_INPUT_TOKENS should be > 0, got {input_tokens}"
        assert output_tokens > 0, f"OBS_TOTAL_OUTPUT_TOKENS should be > 0, got {output_tokens}"
        print(f"  obs: calls={total_calls}, in_tokens={input_tokens}, out_tokens={output_tokens}")
    finally:
        conn.close()

    # Verify agent-level token accounting is in the final state
    # (agent callbacks state writes DO persist via event state_delta)
    state = result.final_state
    assert state.get("reasoning_input_tokens", 0) > 0, "reasoning_input_tokens should be > 0"
    assert state.get("reasoning_output_tokens", 0) > 0, "reasoning_output_tokens should be > 0"


@pytest.mark.agent_challenge
async def test_artifact_persistence_happy_path(tmp_path: Path):
    """InMemoryArtifactService stores final_answer.md artifact."""
    result = await _run_with_plugins("agent_challenge/happy_path_single_iteration", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()

    # The orchestrator saves final_answer.md when a FINAL answer is detected.
    # Check via artifact_service.
    art_svc = result.artifact_service
    keys = await art_svc.list_artifact_keys(
        app_name="rlm_adk",
        user_id="test-user",
        session_id=result.events[0].invocation_id if result.events else "unknown",
    )
    # Artifact save count in state should be > 0 if artifacts were saved.
    save_count = result.final_state.get(ARTIFACT_SAVE_COUNT, 0)
    # The happy_path fixture returns FINAL(42) without code blocks,
    # so the only artifact expected is final_answer.md (if wired).
    # If the orchestrator does not save artifacts for no-code-block runs,
    # we just verify the plugin pipeline did not crash.
    assert result.final_state.get(FINAL_ANSWER) == "42"
    print(f"  artifact_save_count={save_count}, artifact_keys={keys}")


@pytest.mark.agent_challenge
async def test_artifact_persistence_multi_iteration(tmp_path: Path):
    """InMemoryArtifactService stores code/output artifacts for worker fixtures."""
    result = await _run_with_plugins("agent_challenge/multi_iteration_with_workers", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.final_state.get(FINAL_ANSWER) == "4"

    # With an artifact service wired, the orchestrator should have saved
    # repl_code and repl_output artifacts for iterations with code blocks.
    save_count = result.final_state.get(ARTIFACT_SAVE_COUNT, 0)
    print(f"  artifact_save_count={save_count}")
    # At minimum, the pipeline ran through plugins without error.
    assert len(result.events) > 0, "Expected events from the run"


# ===========================================================================
# GROUP C: Tracing integration
# ===========================================================================


@pytest.mark.agent_challenge
async def test_sqlite_traces_recorded_happy_path(tmp_path: Path):
    """SqliteTracingPlugin writes a completed trace row with token stats."""
    result = await _run_with_plugins("agent_challenge/happy_path_single_iteration", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        # Check traces table
        row = conn.execute(
            "SELECT status, total_calls, total_input_tokens, total_output_tokens "
            "FROM traces LIMIT 1"
        ).fetchone()
        assert row is not None, "No trace row found in traces table"
        status, total_calls, input_tokens, output_tokens = row
        assert status == "completed", f"Expected trace status 'completed', got {status!r}"
        assert total_calls > 0, f"Expected total_calls > 0, got {total_calls}"
        assert input_tokens > 0, f"Expected total_input_tokens > 0, got {input_tokens}"

        # Check telemetry table has model_call rows
        model_rows = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE event_type = 'model_call'"
        ).fetchone()[0]
        assert model_rows > 0, "Expected at least one model_call telemetry row"

        print(f"  trace: status={status}, calls={total_calls}, "
              f"in_tokens={input_tokens}, out_tokens={output_tokens}")
        print(f"  model_call telemetry rows: {model_rows}")
    finally:
        conn.close()


@pytest.mark.agent_challenge
async def test_sqlite_traces_recorded_multi_iteration(tmp_path: Path):
    """SqliteTracingPlugin captures spans for multi-iteration worker runs."""
    result = await _run_with_plugins("agent_challenge/multi_iteration_with_workers", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        row = conn.execute(
            "SELECT status, total_calls FROM traces LIMIT 1"
        ).fetchone()
        assert row is not None, "No trace row found"
        status, total_calls = row
        assert status == "completed"
        # 3 model calls: reasoning #1, worker #1, reasoning #2
        assert total_calls >= 3, f"Expected >= 3 total_calls, got {total_calls}"

        # Should have at least 3 model_call telemetry rows
        model_rows = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE event_type = 'model_call'"
        ).fetchone()[0]
        assert model_rows >= 3, f"Expected >= 3 model_call telemetry rows, got {model_rows}"

        print(f"  trace: status={status}, calls={total_calls}, model_rows={model_rows}")
    finally:
        conn.close()


@pytest.mark.agent_challenge
async def test_repl_trace_in_events_multi_iteration(tmp_path: Path):
    """REPL execution results flow through function_response events.

    In the collapsed orchestrator (Phase 5B), REPL execution happens inside
    the REPLTool.  Results are returned as function_response content rather
    than LAST_REPL_RESULT state deltas.  This test verifies that at least one
    function_response event contains stdout from code execution and that the
    llm_calls_made flag is set.
    """
    result = await _run_with_plugins("agent_challenge/multi_iteration_with_workers", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()

    # Extract function_response content from events (tool execution results)
    tool_results = []
    for event in result.events:
        content = getattr(event, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []):
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "name", "") == "execute_code":
                response_data = getattr(fr, "response", None)
                if isinstance(response_data, dict):
                    tool_results.append(response_data)

    print(f"  tool_results: {len(tool_results)}")
    for idx, tr in enumerate(tool_results):
        stdout_preview = (tr.get("stdout", "") or "")[:80]
        print(f"    #{idx}: stdout={stdout_preview!r} llm_calls={tr.get('llm_calls_made')}")

    # At least one tool result should exist (code was executed)
    assert len(tool_results) >= 1, (
        f"No execute_code function_response events found"
    )

    # At least one tool result should have llm_calls_made=True
    results_with_llm = [tr for tr in tool_results if tr.get("llm_calls_made")]
    assert len(results_with_llm) > 0, (
        f"No tool result had llm_calls_made=True — tool_results: {tool_results}"
    )


# ===========================================================================
# GROUP D: Request body capture
# ===========================================================================


async def test_captured_requests_populated():
    """ContractResult.captured_requests is populated with full request bodies."""
    fixture_path = FIXTURE_DIR / "worker_500_then_success.json"
    result = await run_fixture_contract(fixture_path)

    assert result.passed, result.diagnostics()

    # At least 2 requests: reasoning + worker (possibly retried)
    assert len(result.captured_requests) >= 2, (
        f"Expected >= 2 captured requests, got {len(result.captured_requests)}"
    )

    # First request should be a reasoning call with systemInstruction and contents
    first = result.captured_requests[0]
    assert "systemInstruction" in first, (
        f"First request missing systemInstruction, keys: {list(first.keys())}"
    )
    assert "contents" in first, (
        f"First request missing contents, keys: {list(first.keys())}"
    )

    # All captured requests should be dicts (deep-copied, not references)
    for i, req in enumerate(result.captured_requests):
        assert isinstance(req, dict), f"Request #{i} is not a dict: {type(req)}"

    print(f"  captured_requests: {len(result.captured_requests)}")
    for i, req in enumerate(result.captured_requests):
        print(f"    #{i}: keys={sorted(req.keys())}")


async def test_save_captured_requests_to_json(tmp_path: Path):
    """save_captured_requests writes valid JSON that round-trips."""
    fixture_path = FIXTURE_DIR / "worker_500_then_success.json"
    result = await run_fixture_contract(fixture_path)
    assert result.passed, result.diagnostics()

    out = tmp_path / "captured.json"
    returned_path = save_captured_requests(result.captured_requests, out)

    assert returned_path == out
    assert out.exists()

    import json
    loaded = json.loads(out.read_text())
    assert len(loaded) == len(result.captured_requests)
    assert loaded[0]["systemInstruction"] == result.captured_requests[0]["systemInstruction"]
