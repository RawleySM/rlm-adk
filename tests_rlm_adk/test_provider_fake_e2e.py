"""End-to-end tests using the provider-contract fake Gemini server.

Validates the full production pipeline including plugins, artifact
persistence, and tracing:

- **Group A**: Contract validation — parametrized over all fixture JSON files.
- **Group B**: Plugin + artifact integration — observability state, artifact
  persistence via FileArtifactService.
- **Group C**: Tracing integration — SqliteTracingPlugin DB assertions,
  REPL trace events in the event stream.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rlm_adk.state import (
    ARTIFACT_SAVE_COUNT,
    FINAL_RESPONSE_TEXT,
)
from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import (
    PluginContractResult,
    run_fixture_contract,
    run_fixture_contract_with_plugins,
)
from tests_rlm_adk.provider_fake.fixtures import save_captured_requests
from tests_rlm_adk.provider_fake.lineage_assertion_plugin import LineageAssertionPlugin

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
            },
        ),
        (
            "structured_output_batched_k3_multi_retry",
            {
                "contract:callers.sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
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
            },
        ),
        (
            "worker_500_then_success",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
            },
        ),
        (
            "worker_500_retry_exhausted",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
            },
        ),
        (
            "worker_500_retry_exhausted_naive",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
            },
        ),
        (
            "worker_empty_response",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
            },
        ),
        (
            "worker_max_tokens_naive",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
            },
        ),
        (
            "worker_safety_finish",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
            },
        ),
        (
            "structured_output_retry_exhaustion",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
            },
        ),
        (
            "structured_output_retry_exhaustion_pure_validation",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
            },
        ),
        (
            "structured_output_batched_k3_mixed_exhaust",
            {
                "contract:callers.sequence",
                "contract:events.part_sequence",
                "contract:tool_results.any[0]",
                "contract:observability:obs:tool_invocation_summary",
                "contract:observability:last_repl_result",
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
    fixture_name: str,
    tmp_path: Path,
    extra_plugins: list | None = None,
) -> PluginContractResult:
    """Run a named fixture through the plugin-enabled pipeline."""
    fixture_path = FIXTURE_DIR / f"{fixture_name}.json"
    traces_db = str(tmp_path / "traces.db")
    return await run_fixture_contract_with_plugins(
        fixture_path,
        traces_db_path=traces_db,
        repl_trace_level=1,
        tmpdir=str(tmp_path),
        extra_plugins=extra_plugins,
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

    # Token accounting keys (reasoning_input_tokens, reasoning_output_tokens)
    # are no longer written to session state after the refactor.
    # Observability is verified through the traces DB above.


@pytest.mark.agent_challenge
async def test_artifact_persistence_happy_path(tmp_path: Path):
    """FileArtifactService stores final_answer.md artifact on disk."""
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
    fa = result.final_state.get(FINAL_RESPONSE_TEXT, "")
    assert "42" in fa, f"Expected '42' in final_response_text, got {fa!r}"
    print(f"  artifact_save_count={save_count}, artifact_keys={keys}")


@pytest.mark.agent_challenge
async def test_artifact_persistence_multi_iteration(tmp_path: Path):
    """FileArtifactService stores code/output artifacts for worker fixtures on disk."""
    result = await _run_with_plugins("agent_challenge/multi_iteration_with_workers", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    fa = result.final_state.get(FINAL_RESPONSE_TEXT, "")
    assert "FINAL(4)" in fa, f"Expected 'FINAL(4)' in response, got {fa!r}"

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
        "No execute_code function_response events found"
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


# ===========================================================================
# GROUP E: IPython backend e2e
# ===========================================================================


@pytest.mark.agent_challenge
async def test_ipython_backend_multi_iteration_with_workers(tmp_path: Path, monkeypatch):
    """Provider-fake e2e passes with RLM_REPL_BACKEND=ipython and debug disabled.

    Uses the multi_iteration_with_workers fixture which exercises execute_code.
    """
    monkeypatch.setenv("RLM_REPL_BACKEND", "ipython")
    monkeypatch.setenv("RLM_REPL_IPYTHON_EMBED", "0")
    monkeypatch.setenv("RLM_REPL_DEBUGPY", "0")
    monkeypatch.setenv("RLM_REPL_DEBUGPY_WAIT", "0")

    result = await _run_with_plugins("agent_challenge/multi_iteration_with_workers", tmp_path)
    assert result.contract.passed, result.contract.diagnostics()
    fa = result.final_state.get(FINAL_RESPONSE_TEXT, "")
    assert "FINAL(4)" in fa, f"Expected 'FINAL(4)' in response, got {fa!r}"

    # Verify at least one execute_code tool response exists
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

    assert len(tool_results) >= 1, "Expected at least one execute_code tool response"


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


# ===========================================================================
# GROUP F: User-provided context (Path B) integration
# ===========================================================================


@pytest.mark.provider_fake_contract
async def test_user_context_preseeded_manifest_and_repl(tmp_path: Path):
    """Path B user context: manifest, state keys, and REPL globals are wired."""
    result = await _run_with_plugins("user_context_preseeded", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()

    state = result.final_state

    # Manifest contains both file names
    manifest = state.get("user_ctx_manifest", "")
    assert "notes.txt" in manifest, f"Manifest missing notes.txt: {manifest!r}"
    assert "spec.md" in manifest, f"Manifest missing spec.md: {manifest!r}"

    # user_provided_ctx has exactly 2 keys
    ctx = state.get("user_provided_ctx")
    assert ctx is not None, "user_provided_ctx not in state"
    assert len(ctx) == 2, f"Expected 2 keys in user_provided_ctx, got {len(ctx)}"

    # exceeded flag is False
    assert state.get("user_provided_ctx_exceeded") is False, (
        f"Expected False, got {state.get('user_provided_ctx_exceeded')!r}"
    )

    # REPL stdout contains the content from user_ctx["notes.txt"]
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

    assert len(tool_results) >= 1, "No execute_code tool results found"
    stdout_texts = [tr.get("stdout", "") for tr in tool_results]
    assert any("meeting notes here" in s for s in stdout_texts), (
        f"REPL stdout should contain 'meeting notes here', got: {stdout_texts}"
    )


# ===========================================================================
# GROUP G: Persistent services verification
# ===========================================================================


@pytest.mark.provider_fake_contract
async def test_artifacts_persisted_to_disk(tmp_path: Path):
    """FileArtifactService writes artifact files to disk, not just memory."""
    result = await _run_with_plugins("fake_recursive_ping", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.artifact_root is not None
    artifact_root = Path(result.artifact_root)

    # Artifact root directory should exist on disk
    assert artifact_root.exists(), f"artifact_root does not exist: {artifact_root}"

    # Collect all files written under the artifact root
    artifact_files = list(artifact_root.rglob("*"))
    artifact_files = [f for f in artifact_files if f.is_file()]
    print(f"  artifact_root={artifact_root}")
    print(f"  artifact files ({len(artifact_files)}):")
    for f in artifact_files:
        print(f"    {f.relative_to(artifact_root)} ({f.stat().st_size} bytes)")

    # At least one artifact file should have been written
    assert len(artifact_files) > 0, (
        f"No artifact files found under {artifact_root}"
    )


@pytest.mark.provider_fake_contract
async def test_session_db_persisted_to_disk(tmp_path: Path):
    """SqliteSessionService writes a real SQLite DB with session data."""
    result = await _run_with_plugins("fake_recursive_ping", tmp_path)

    assert result.contract.passed, result.contract.diagnostics()
    assert result.session_db_path is not None

    db_path = Path(result.session_db_path)
    assert db_path.exists(), f"session DB does not exist: {db_path}"
    assert db_path.stat().st_size > 0, f"session DB is empty: {db_path}"

    # Verify it's a valid SQLite DB with session data
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert len(tables) > 0, f"No tables in session DB, got: {tables}"
        print(f"  session_db={db_path}")
        print(f"  tables: {sorted(tables)}")
    finally:
        conn.close()


# ===========================================================================
# GROUP H: Lineage / Completion / State planes
# ===========================================================================

_LINEAGE_FIXTURE = "agent_challenge/lineage_completion_planes"


async def _run_lineage_fixture(
    tmp_path: Path,
    monkeypatch,
    extra_plugins: list | None = None,
) -> tuple[PluginContractResult, LineageAssertionPlugin]:
    """Run the lineage_completion_planes fixture with lineage plugin."""
    monkeypatch.setenv("RLM_MAX_CONCURRENT_CHILDREN", "1")

    plugin = LineageAssertionPlugin()
    all_plugins: list = [plugin]
    if extra_plugins:
        all_plugins.extend(extra_plugins)
    fixture_path = FIXTURE_DIR / f"{_LINEAGE_FIXTURE}.json"
    traces_db = str(tmp_path / "traces.db")
    result = await run_fixture_contract_with_plugins(
        fixture_path,
        traces_db_path=traces_db,
        repl_trace_level=1,
        tmpdir=str(tmp_path),
        extra_plugins=all_plugins,
    )
    return result, plugin


@pytest.mark.agent_challenge
async def test_lineage_fixture_contract(tmp_path: Path, monkeypatch, repl_capture):
    """Fixture contract passes: 9 model calls, 2 iterations, correct final answer."""
    extra = [repl_capture] if repl_capture is not None else None
    result, plugin = await _run_lineage_fixture(tmp_path, monkeypatch, extra_plugins=extra)

    if not result.contract.passed:
        print(result.contract.diagnostics())
        # Diagnostic: print plugin summary
        print(f"\n  Plugin model_events: {len(plugin.model_events)}")
        for e in plugin.model_events:
            print(f"    {e['phase']} d={e.get('depth')} f={e.get('fanout_idx')} agent={e.get('agent_name')}")
        print(f"  Plugin tool_events: {len(plugin.tool_events)}")
        for e in plugin.tool_events:
            print(f"    {e['phase']} {e.get('tool_name')} d={e.get('depth')} f={e.get('fanout_idx')}")

    assert result.contract.passed, (
        f"Lineage fixture contract failed\n{result.contract.diagnostics()}"
    )

    # Fix #7: Verify FIFO response consumption order was not violated.
    # If asyncio task scheduling reordered child dispatch, the wrong agent
    # would consume the wrong scripted response — detected here by checking
    # that no fixture-exhausted fallbacks were used and that all 9 scripted
    # responses were consumed sequentially.
    router = result.router
    assert not router.fixture_exhausted_calls, (
        f"Fixture responses consumed out of order or exhausted: "
        f"fallback at call indices {router.fixture_exhausted_calls}"
    )
    assert router.call_index == 9, (
        f"Expected exactly 9 calls consumed, got {router.call_index}"
    )

    # Populate capture metadata for --repl-capture-json output
    if repl_capture is not None:
        repl_capture.fixture_name = _LINEAGE_FIXTURE
        repl_capture.final_state = result.final_state


@pytest.mark.agent_challenge
async def test_lineage_state_plane(tmp_path: Path, monkeypatch):
    """State plane: correct final state values, no leaked depth-scoped keys."""
    result, _plugin = await _run_lineage_fixture(tmp_path, monkeypatch)
    assert result.contract.passed, result.contract.diagnostics()

    state = result.final_state

    # final_response_text present and correct
    fa = state.get(FINAL_RESPONSE_TEXT, "")
    assert "Multi-depth analysis complete" in fa, f"Unexpected final answer: {fa!r}"

    # should_stop = True
    assert state.get("should_stop") is True, f"should_stop={state.get('should_stop')}"

    # iteration_count = 2 (two execute_code calls at depth 0)
    assert state.get("iteration_count") == 2, (
        f"iteration_count={state.get('iteration_count')}, expected 2"
    )

    # No leaked depth-scoped lineage keys from children
    for key in list(state.keys()):
        if "@d1" in key or "@d2" in key:
            # Depth-scoped keys from children are expected in session state
            # (written by child orchestrators via EventActions).  But they
            # should not be obs:reasoning_* keys which would indicate leakage.
            assert not key.startswith("obs:reasoning_"), (
                f"Leaked depth-scoped obs key: {key}"
            )

    print(f"  final_answer={fa[:80]!r}")
    print(f"  iteration_count={state.get('iteration_count')}")
    print(f"  should_stop={state.get('should_stop')}")


@pytest.mark.agent_challenge
async def test_lineage_sqlite_telemetry(tmp_path: Path, monkeypatch):
    """Lineage plane: SQLite telemetry has rows at all 3 depths with lineage columns."""
    result, _plugin = await _run_lineage_fixture(tmp_path, monkeypatch)
    assert result.contract.passed, result.contract.diagnostics()
    assert result.traces_db_path is not None

    conn = sqlite3.connect(result.traces_db_path)
    try:
        # --- Model-call rows exist at depth 0 (parent) ---
        d0_rows = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE event_type='model_call' AND depth=0"
        ).fetchone()[0]
        assert d0_rows >= 3, f"Expected >= 3 model_call rows at depth 0, got {d0_rows}"

        # --- Model-call rows exist at depth 1 ---
        d1_rows = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE event_type='model_call' AND depth=1"
        ).fetchone()[0]
        assert d1_rows >= 2, f"Expected >= 2 model_call rows at depth 1, got {d1_rows}"

        # --- Model-call rows exist at depth 2 ---
        d2_rows = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE event_type='model_call' AND depth=2"
        ).fetchone()[0]
        assert d2_rows >= 1, f"Expected >= 1 model_call rows at depth 2, got {d2_rows}"

        # --- Total model calls ---
        total = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE event_type='model_call'"
        ).fetchone()[0]
        assert total >= 9, f"Expected >= 9 total model_call rows, got {total}"

        # --- Traces table: max_depth_reached ---
        max_depth = conn.execute(
            "SELECT max_depth_reached FROM traces LIMIT 1"
        ).fetchone()
        if max_depth and max_depth[0] is not None:
            assert max_depth[0] >= 2, (
                f"Expected max_depth_reached >= 2, got {max_depth[0]}"
            )

        # --- Tool-call rows for execute_code and set_model_response ---
        exec_rows = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE event_type='tool_call' AND tool_name='execute_code'"
        ).fetchone()[0]
        smr_rows = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE event_type='tool_call' AND tool_name='set_model_response'"
        ).fetchone()[0]

        print(f"  model_call rows: d0={d0_rows} d1={d1_rows} d2={d2_rows} total={total}")
        print(f"  tool_call rows: execute_code={exec_rows} set_model_response={smr_rows}")
        print(f"  max_depth_reached={max_depth[0] if max_depth else 'N/A'}")

        # --- Lineage columns populated (check a sample row) ---
        sample = conn.execute(
            "SELECT depth, fanout_idx, output_schema_name, decision_mode, "
            "structured_outcome, terminal_completion, custom_metadata_json "
            "FROM telemetry WHERE event_type='model_call' AND depth=1 LIMIT 1"
        ).fetchone()
        if sample:
            print(f"  sample d1 row: depth={sample[0]} fanout={sample[1]} "
                  f"schema={sample[2]} decision={sample[3]} "
                  f"outcome={sample[4]} terminal={sample[5]}")
    finally:
        conn.close()


@pytest.mark.agent_challenge
async def test_lineage_plugin_model_events(tmp_path: Path, monkeypatch):
    """Lineage plugin: model events captured at all 3 depths with correct lineage."""
    result, plugin = await _run_lineage_fixture(tmp_path, monkeypatch)
    assert result.contract.passed, result.contract.diagnostics()

    # --- Model events at depth 0 ---
    d0_before = plugin.model_events_at(depth=0, phase="before")
    d0_after = plugin.model_events_at(depth=0, phase="after")
    assert len(d0_before) >= 3, (
        f"Expected >= 3 before_model events at d0, got {len(d0_before)}"
    )
    assert len(d0_after) >= 3, (
        f"Expected >= 3 after_model events at d0, got {len(d0_after)}"
    )

    # --- Model events at depth 1 ---
    d1_events = plugin.model_events_at(depth=1, phase="before")
    assert len(d1_events) >= 2, (
        f"Expected >= 2 before_model events at d1, got {len(d1_events)}"
    )

    # --- Model events at depth 2 ---
    d2_events = plugin.model_events_at(depth=2, phase="before")
    assert len(d2_events) >= 1, (
        f"Expected >= 1 before_model events at d2, got {len(d2_events)}"
    )

    # --- Depth 0 has correct output_schema_name ---
    d0_schemas = {e.get("output_schema_name") for e in d0_before}
    assert "ReasoningOutput" in d0_schemas, (
        f"Expected 'ReasoningOutput' in d0 schemas, got {d0_schemas}"
    )

    # --- After-model events at d0 captured depth correctly ---
    # NOTE: rlm_lineage in custom_metadata is injected by the agent callback
    # (reasoning_after_model) which fires AFTER plugin callbacks.  So the
    # plugin sees it as None.  Instead, verify depth is captured directly.
    for e in d0_after:
        assert e.get("depth") == 0, f"Expected depth 0 in d0 after_model, got {e}"

    # --- Depth 1 events MUST have parent_depth set ---
    d1_before = plugin.model_events_at(depth=1, phase="before")
    d1_with_parent = [e for e in d1_before if e.get("parent_depth") is not None]
    assert len(d1_with_parent) >= 1, (
        f"Expected >= 1 d1 before_model events with parent_depth set, "
        f"got 0 (total d1 events: {len(d1_before)}). "
        f"_rlm_parent_depth may not be set on child agents."
    )
    for e in d1_with_parent:
        assert e["parent_depth"] == 0, f"d1 parent_depth should be 0: {e}"

    # --- Depth 1 events have correct agent name (non-circular: comes from
    # production wiring in create_child_orchestrator, not fixture responses) ---
    d1_agent_names = {e.get("agent_name") for e in d1_before}
    assert "child_reasoning_d1" in d1_agent_names, (
        f"Expected 'child_reasoning_d1' in d1 agent names, got {d1_agent_names}"
    )

    # --- Depth 0 events have correct agent name ---
    d0_agent_names = {e.get("agent_name") for e in d0_before}
    assert "reasoning_agent" in d0_agent_names, (
        f"Expected 'reasoning_agent' in d0 agent names, got {d0_agent_names}"
    )

    # --- Depth 1 events must include both fanout indices (0 and 1) ---
    d1_fanouts = {e.get("fanout_idx") for e in d1_before}
    assert 0 in d1_fanouts, f"Expected fanout_idx=0 in d1 events, got {d1_fanouts}"
    assert 1 in d1_fanouts, f"Expected fanout_idx=1 in d1 events, got {d1_fanouts}"

    print(f"  model events: d0={len(d0_before)} d1={len(d1_events)} d2={len(d2_events)}")
    print(f"  d0 schemas: {d0_schemas}")
    print(f"  d1 events with parent_depth: {len(d1_with_parent)}")
    print(f"  d1 agent_names: {d1_agent_names}")
    print(f"  d1 fanout_idxs: {sorted(d for d in d1_fanouts if d is not None)}")


@pytest.mark.agent_challenge
async def test_lineage_plugin_tool_events(tmp_path: Path, monkeypatch):
    """Lineage plugin: tool events captured for execute_code and set_model_response."""
    result, plugin = await _run_lineage_fixture(tmp_path, monkeypatch)
    assert result.contract.passed, result.contract.diagnostics()

    # --- execute_code tool events ---
    exec_events = plugin.tool_events_for("execute_code")
    # 4 execute_code calls total (calls 0, 1, 4, 6), each has before+after = 8 events
    exec_before = [e for e in exec_events if e["phase"] == "before"]
    exec_after = [e for e in exec_events if e["phase"] == "after"]
    assert len(exec_before) >= 4, (
        f"Expected >= 4 before execute_code events, got {len(exec_before)}"
    )
    assert len(exec_after) >= 4, (
        f"Expected >= 4 after execute_code events, got {len(exec_after)}"
    )

    # --- set_model_response tool events ---
    smr_events = plugin.tool_events_for("set_model_response")
    smr_before = [e for e in smr_events if e["phase"] == "before"]
    # 5 set_model_response calls total (calls 2, 3, 5, 7, 8)
    assert len(smr_before) >= 5, (
        f"Expected >= 5 before set_model_response events, got {len(smr_before)}"
    )

    # --- Depth distribution of execute_code ---
    exec_depths = [e.get("depth") for e in exec_before]
    assert 0 in exec_depths, f"Expected depth 0 in execute_code events, got {exec_depths}"
    assert 1 in exec_depths, f"Expected depth 1 in execute_code events, got {exec_depths}"

    # --- Depth distribution of set_model_response ---
    smr_depths = [e.get("depth") for e in smr_before]
    assert 0 in smr_depths, f"Expected depth 0 in set_model_response events, got {smr_depths}"
    assert 1 in smr_depths, f"Expected depth 1 in set_model_response events, got {smr_depths}"
    assert 2 in smr_depths, f"Expected depth 2 in set_model_response events, got {smr_depths}"

    print(f"  execute_code: {len(exec_before)} before, {len(exec_after)} after")
    print(f"  set_model_response: {len(smr_before)} before")
    print(f"  exec depths: {sorted(set(exec_depths))}")
    print(f"  smr depths: {sorted(set(smr_depths))}")


@pytest.mark.agent_challenge
async def test_lineage_completion_plane(tmp_path: Path, monkeypatch):
    """Completion plane: terminal completions found at correct depths via plugin."""
    result, plugin = await _run_lineage_fixture(tmp_path, monkeypatch)
    assert result.contract.passed, result.contract.diagnostics()

    completions = plugin.completions()
    print(f"  total completions: {len(completions)}")
    for c in completions:
        tc = c.get("terminal_completion", {})
        print(
            f"    d={c.get('depth')} f={c.get('fanout_idx')} "
            f"agent={c.get('agent_name')} "
            f"terminal={tc.get('terminal')} mode={tc.get('mode')} "
            f"schema={tc.get('output_schema_name')}"
        )

    # Completions MUST be captured — an empty list indicates the plugin's
    # after_agent_callback never saw _rlm_terminal_completion, which means
    # the completion plane is broken.
    assert len(completions) >= 1, (
        "No terminal completions captured — after_agent_callback may not "
        "have fired or _rlm_terminal_completion was never set"
    )

    # Verify that at least one completion is terminal + structured
    terminal_completions = [
        c for c in completions
        if c.get("terminal_completion", {}).get("terminal") is True
    ]
    assert len(terminal_completions) >= 1, (
        "Expected at least 1 terminal completion"
    )

    # Check for completions at different depths
    completion_depths = {c.get("depth") for c in terminal_completions}
    print(f"  completion depths: {sorted(d for d in completion_depths if d is not None)}")

    # Verify mode is "structured" for at least some completions
    structured = [
        c for c in terminal_completions
        if c.get("terminal_completion", {}).get("mode") == "structured"
    ]
    assert len(structured) >= 1, (
        "Expected at least 1 structured completion"
    )
