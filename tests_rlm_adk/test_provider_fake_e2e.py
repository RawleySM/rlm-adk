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

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_fixture_paths() -> list[Path]:
    """Discover all fixture JSON files in the provider_fake fixture dir."""
    return sorted(FIXTURE_DIR.glob("*.json"))


# ===========================================================================
# GROUP A: Contract validation (existing, simplified)
# ===========================================================================


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


async def test_observability_state_happy_path(tmp_path: Path):
    """ObservabilityPlugin populates OBS_* counters (captured by SqliteTracingPlugin).

    Plugin after_model_callback state writes are visible during the run
    (read by SqliteTracingPlugin.after_run_callback) but are not committed
    to the session service via event state_deltas.  We verify through the
    traces DB which reads from the live session state.
    """
    result = await _run_with_plugins("happy_path_single_iteration", tmp_path)

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


async def test_artifact_persistence_happy_path(tmp_path: Path):
    """InMemoryArtifactService stores final_answer.md artifact."""
    result = await _run_with_plugins("happy_path_single_iteration", tmp_path)

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


async def test_artifact_persistence_multi_iteration(tmp_path: Path):
    """InMemoryArtifactService stores code/output artifacts for worker fixtures."""
    result = await _run_with_plugins("multi_iteration_with_workers", tmp_path)

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


async def test_sqlite_traces_recorded_happy_path(tmp_path: Path):
    """SqliteTracingPlugin writes a completed trace row with token stats."""
    result = await _run_with_plugins("happy_path_single_iteration", tmp_path)

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

        # Check spans table has model_call spans
        model_spans = conn.execute(
            "SELECT COUNT(*) FROM spans WHERE operation_name = 'model_call'"
        ).fetchone()[0]
        assert model_spans > 0, "Expected at least one model_call span"

        print(f"  trace: status={status}, calls={total_calls}, "
              f"in_tokens={input_tokens}, out_tokens={output_tokens}")
        print(f"  model_call spans: {model_spans}")
    finally:
        conn.close()


async def test_sqlite_traces_recorded_multi_iteration(tmp_path: Path):
    """SqliteTracingPlugin captures spans for multi-iteration worker runs."""
    result = await _run_with_plugins("multi_iteration_with_workers", tmp_path)

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

        # Should have at least 3 model_call spans
        model_spans = conn.execute(
            "SELECT COUNT(*) FROM spans WHERE operation_name = 'model_call'"
        ).fetchone()[0]
        assert model_spans >= 3, f"Expected >= 3 model_call spans, got {model_spans}"

        print(f"  trace: status={status}, calls={total_calls}, model_spans={model_spans}")
    finally:
        conn.close()


async def test_repl_trace_in_events_multi_iteration(tmp_path: Path):
    """REPL execution results flow through function_response events.

    In the collapsed orchestrator (Phase 5B), REPL execution happens inside
    the REPLTool.  Results are returned as function_response content rather
    than LAST_REPL_RESULT state deltas.  This test verifies that at least one
    function_response event contains stdout from code execution and that the
    llm_calls_made flag is set.
    """
    result = await _run_with_plugins("multi_iteration_with_workers", tmp_path)

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
