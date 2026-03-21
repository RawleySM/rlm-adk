"""Tests for child event re-emission via asyncio.Queue bridge.

Validates that curated state-delta events from recursive child
RLMOrchestratorAgents are re-emitted through the parent's yield loop
and reach the ADK Runner's event stream (and thus SqliteTracingPlugin).

Test 1: parse_depth_key / should_capture_state_key unit tests
Test 2: Queue population in dispatch (mock child)
Test 3: E2E with recursive_ping fixture — child events in event stream
Test 4: session_state_events rows with key_depth > 0
Test 5: Backward compat — depth-0-only fixture produces zero child events
Test 6: Concurrent children — multiple fanout indices in event stream
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path

import pytest

from rlm_adk.state import (
    CURRENT_DEPTH,
    DYN_SKILL_INSTRUCTION,
    FINAL_RESPONSE_TEXT,
    ITERATION_COUNT,
    LAST_REPL_RESULT,
    SHOULD_STOP,
    depth_key,
    parse_depth_key,
    should_capture_state_key,
)

FIXTURE_DIR = Path("tests_rlm_adk/fixtures/provider_fake")

# ---------------------------------------------------------------------------
# Test 1: Unit tests for parse_depth_key and should_capture_state_key
# ---------------------------------------------------------------------------


class TestParseDepthKey:
    """Verify parse_depth_key round-trips with depth_key."""

    def test_depth_zero_roundtrip(self):
        raw = depth_key("iteration_count", 0)
        base, d, f = parse_depth_key(raw)
        assert base == "iteration_count"
        assert d == 0
        assert f is None

    def test_depth_nonzero_roundtrip(self):
        raw = depth_key("iteration_count", 2)
        assert raw == "iteration_count@d2"
        base, d, f = parse_depth_key(raw)
        assert base == "iteration_count"
        assert d == 2
        assert f is None

    def test_fanout_parsing(self):
        base, d, f = parse_depth_key("should_stop@d1f3")
        assert base == "should_stop"
        assert d == 1
        assert f == 3

    def test_plain_key_no_suffix(self):
        base, d, f = parse_depth_key("request_id")
        assert base == "request_id"
        assert d == 0
        assert f is None


class TestShouldCaptureStateKey:
    """Verify curated key filter accepts/rejects correctly."""

    @pytest.mark.parametrize(
        "key",
        [
            CURRENT_DEPTH,
            ITERATION_COUNT,
            SHOULD_STOP,
            FINAL_RESPONSE_TEXT,
            LAST_REPL_RESULT,
            DYN_SKILL_INSTRUCTION,
        ],
    )
    def test_exact_curated_keys_accepted(self, key):
        assert should_capture_state_key(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "obs:artifact_save_count",
            "artifact_final_answer",
            "last_repl_result",
            "repl_submitted_code",
            "repl_expanded_code",
            "repl_skill_expansion_meta",
            "repl_did_expand",
        ],
    )
    def test_prefix_curated_keys_accepted(self, key):
        assert should_capture_state_key(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "request_id",
            "obs:total_calls",
            "obs:rewrite_count",
            "cache:store",
            "user:last_successful_call_id",
            "app:max_depth",
            "some_random_key",
        ],
    )
    def test_non_curated_keys_rejected(self, key):
        assert should_capture_state_key(key) is False


# ---------------------------------------------------------------------------
# Test 2: Queue population in dispatch (exercises real create_dispatch_closures)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_receives_curated_child_events():
    """Verify dispatch._run_child pushes curated state-delta events onto the queue.

    This test exercises the REAL create_dispatch_closures code path by:
    1. Constructing a minimal InvocationContext
    2. Mocking create_child_orchestrator to return a fake child that yields
       known events (mix of curated and non-curated state_delta keys)
    3. Calling llm_query_async (the closure returned by create_dispatch_closures)
    4. Asserting the child_event_queue received only curated events
    """
    from unittest.mock import MagicMock, patch

    from google.adk.agents import BaseAgent
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.events import Event, EventActions
    from google.adk.plugins.plugin_manager import PluginManager
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.sessions.session import Session

    from rlm_adk.dispatch import DispatchConfig, create_dispatch_closures
    from rlm_adk.types import CompletionEnvelope

    # --- Build minimal InvocationContext ---
    # Pydantic requires real BaseAgent / BaseSessionService instances.
    class _StubAgent(BaseAgent):
        async def _run_async_impl(self, ctx):
            yield

    parent_agent = _StubAgent(name="rlm_orchestrator")

    session = Session(
        id="test-session",
        app_name="rlm_adk",
        user_id="test-user",
        state={},
        events=[],
    )
    session_service = InMemorySessionService()
    ctx = InvocationContext(
        invocation_id="parent-inv",
        agent=parent_agent,
        session=session,
        session_service=session_service,
        plugin_manager=PluginManager(),
    )

    # --- Build fake child orchestrator ---
    # The fake child's run_async yields known events with a mix of curated
    # and non-curated state_delta keys, then sets _rlm_terminal_completion
    # so _read_child_completion returns a valid result.
    fake_child_events = [
        # Curated: iteration_count + current_depth at depth 1
        Event(
            invocation_id="parent-inv",
            author="child_orchestrator_d1",
            actions=EventActions(state_delta={"iteration_count@d1": 0, "current_depth@d1": 1}),
        ),
        # Non-curated: obs key + request_id (should be filtered out)
        Event(
            invocation_id="parent-inv",
            author="child_orchestrator_d1",
            actions=EventActions(state_delta={"obs:total_calls": 5, "request_id": "abc"}),
        ),
        # Curated: should_stop + final_response_text
        Event(
            invocation_id="parent-inv",
            author="child_orchestrator_d1",
            actions=EventActions(
                state_delta={
                    "should_stop@d1": True,
                    "final_response_text@d1": "done",
                }
            ),
        ),
        # Content event (no state_delta) — should not produce queue entry
        Event(
            invocation_id="parent-inv",
            author="child_orchestrator_d1",
        ),
    ]

    fake_child = MagicMock()
    fake_child.name = "child_orchestrator_d1"
    fake_child.persistent = False
    fake_child.repl = None

    # Set up the completion envelope so _read_child_completion finds a result
    fake_child._rlm_terminal_completion = CompletionEnvelope(
        terminal=True,
        mode="text",
        display_text="done",
        error=False,
    )
    fake_reasoning = MagicMock()
    fake_reasoning._rlm_terminal_completion = None
    fake_child.reasoning_agent = fake_reasoning

    async def _fake_run_async(child_ctx):
        for ev in fake_child_events:
            yield ev

    fake_child.run_async = _fake_run_async

    # --- Create dispatch closures with a real queue ---
    child_event_queue: asyncio.Queue[Event] = asyncio.Queue()
    dispatch_config = DispatchConfig(default_model="gemini-fake")

    with patch(
        "rlm_adk.agent.create_child_orchestrator",
        return_value=fake_child,
    ):
        llm_query_async, _batched, _patch_fn = create_dispatch_closures(
            dispatch_config,
            ctx,
            depth=0,
            max_depth=5,
            child_event_queue=child_event_queue,
        )

        # Call the closure — this runs _run_child which filters events
        result = await llm_query_async("test prompt")

    # --- Assert the queue received exactly the curated events ---
    assert not child_event_queue.empty(), (
        "child_event_queue is empty — dispatch._run_child did not push curated events"
    )
    assert child_event_queue.qsize() == 2, (
        f"Expected 2 curated events on queue, got {child_event_queue.qsize()}"
    )

    e1 = child_event_queue.get_nowait()
    assert e1.custom_metadata["rlm_child_event"] is True
    assert e1.custom_metadata["child_depth"] == 1
    assert "iteration_count@d1" in e1.actions.state_delta
    assert "current_depth@d1" in e1.actions.state_delta

    e2 = child_event_queue.get_nowait()
    assert "should_stop@d1" in e2.actions.state_delta
    assert "final_response_text@d1" in e2.actions.state_delta

    assert child_event_queue.empty()

    # Verify the dispatch result itself is valid
    assert not result.error
    assert "done" in str(result)


# ---------------------------------------------------------------------------
# Test 3: E2E with recursive_ping fixture — child events in event stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.provider_fake
@pytest.mark.provider_fake_contract
async def test_recursive_ping_emits_child_events():
    """Run recursive_ping fixture and assert child events appear in the stream."""
    from tests_rlm_adk.provider_fake.contract_runner import (
        run_fixture_contract_with_plugins,
    )

    fixture_path = FIXTURE_DIR / "fake_recursive_ping.json"
    if not fixture_path.exists():
        pytest.skip("recursive_ping fixture not found")

    with tempfile.TemporaryDirectory(prefix="child-reemit-") as tmpdir:
        result = await run_fixture_contract_with_plugins(
            fixture_path,
            traces_db_path=str(Path(tmpdir) / "traces.db"),
            tmpdir=tmpdir,
        )

    # Contract should pass
    assert result.contract.passed, result.contract.diagnostics()

    # Find child events in the event stream
    child_events = [
        e
        for e in result.events
        if getattr(e, "custom_metadata", None) and e.custom_metadata.get("rlm_child_event") is True
    ]

    assert len(child_events) > 0, "No child events found in event stream — re-emission not working"

    # Verify metadata structure
    for ce in child_events:
        assert "child_depth" in ce.custom_metadata
        assert ce.custom_metadata["child_depth"] >= 1
        assert "child_fanout_idx" in ce.custom_metadata

    # Verify at least some have curated state_delta keys
    all_child_keys = set()
    for ce in child_events:
        if ce.actions and ce.actions.state_delta:
            for k in ce.actions.state_delta:
                base, depth, _ = parse_depth_key(k)
                all_child_keys.add(base)

    curated_hits = {k for k in all_child_keys if should_capture_state_key(k)}
    assert len(curated_hits) > 0, f"Child events have keys {all_child_keys} but none are curated"

    # Verify causal ordering: child events should appear after an execute_code
    # tool-response event (the REPL execution that triggered the dispatch) and
    # before the next model event in the stream.
    child_event_ids = {id(ce) for ce in child_events}
    saw_execute_code_response = False
    child_after_tool_response = False
    for e in result.events:
        # Detect function_response for execute_code (tool response)
        if e.content and e.content.parts:
            for part in e.content.parts:
                fr = getattr(part, "function_response", None)
                if fr and getattr(fr, "name", None) == "execute_code":
                    saw_execute_code_response = True
        # Check if any child event appears after the first execute_code response
        if id(e) in child_event_ids and saw_execute_code_response:
            child_after_tool_response = True
            break
    assert child_after_tool_response, (
        "Child events should appear after execute_code tool-response events "
        "in the event stream (causal ordering violated)"
    )


# ---------------------------------------------------------------------------
# Test 4: session_state_events rows with key_depth > 0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.provider_fake
@pytest.mark.provider_fake_contract
async def test_recursive_ping_sqlite_depth_rows():
    """Run recursive_ping and verify session_state_events has key_depth > 0 rows."""
    from tests_rlm_adk.provider_fake.contract_runner import (
        run_fixture_contract_with_plugins,
    )

    fixture_path = FIXTURE_DIR / "fake_recursive_ping.json"
    if not fixture_path.exists():
        pytest.skip("recursive_ping fixture not found")

    with tempfile.TemporaryDirectory(prefix="child-sqlite-") as tmpdir:
        traces_db = str(Path(tmpdir) / "traces.db")
        result = await run_fixture_contract_with_plugins(
            fixture_path,
            traces_db_path=traces_db,
            tmpdir=tmpdir,
        )

        assert result.contract.passed, result.contract.diagnostics()

        # Query traces.db for depth > 0 rows
        conn = sqlite3.connect(traces_db)
        try:
            rows = conn.execute(
                "SELECT state_key, key_depth, event_author "
                "FROM session_state_events WHERE key_depth > 0"
            ).fetchall()
        finally:
            conn.close()

    assert len(rows) > 0, (
        "No session_state_events rows with key_depth > 0 — "
        "child events not reaching SqliteTracingPlugin"
    )

    # Verify the keys are sensible — child orchestrators always emit both
    # iteration_count and current_depth in their initial state event.
    depth_keys_found = {row[0] for row in rows}
    assert "iteration_count" in depth_keys_found, (
        f"Expected 'iteration_count' at depth>0, got: {depth_keys_found}"
    )
    assert "current_depth" in depth_keys_found, (
        f"Expected 'current_depth' at depth>0, got: {depth_keys_found}"
    )


# ---------------------------------------------------------------------------
# Test 5: Backward compatibility — depth-0-only fixture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.provider_fake
@pytest.mark.provider_fake_contract
async def test_flat_fixture_no_child_events():
    """A depth-0-only fixture should produce zero child events."""
    from tests_rlm_adk.provider_fake.contract_runner import (
        run_fixture_contract_with_plugins,
    )

    # repl_runtime_error is a depth-0-only fixture (no llm_query dispatch)
    fixture_path = FIXTURE_DIR / "repl_runtime_error.json"
    if not fixture_path.exists():
        pytest.skip("repl_runtime_error fixture not found")

    with tempfile.TemporaryDirectory(prefix="child-flat-") as tmpdir:
        traces_db = str(Path(tmpdir) / "traces.db")
        result = await run_fixture_contract_with_plugins(
            fixture_path,
            traces_db_path=traces_db,
            tmpdir=tmpdir,
        )

    assert result.contract.passed, result.contract.diagnostics()

    # No child events expected
    child_events = [
        e
        for e in result.events
        if getattr(e, "custom_metadata", None) and e.custom_metadata.get("rlm_child_event") is True
    ]
    assert len(child_events) == 0, (
        f"Flat fixture should not produce child events, got {len(child_events)}"
    )

    # Also verify no key_depth > 0 rows in traces.db
    with tempfile.TemporaryDirectory(prefix="child-flat2-") as tmpdir2:
        traces_db2 = str(Path(tmpdir2) / "traces.db")
        await run_fixture_contract_with_plugins(
            fixture_path,
            traces_db_path=traces_db2,
            tmpdir=tmpdir2,
        )
        conn = sqlite3.connect(traces_db2)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM session_state_events WHERE key_depth > 0"
            ).fetchone()
        finally:
            conn.close()
        assert rows[0] == 0, f"Expected 0 depth>0 rows for flat fixture, got {rows[0]}"


# ---------------------------------------------------------------------------
# Test 6: Concurrent children — multiple fanout indices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.provider_fake
@pytest.mark.provider_fake_contract
async def test_batched_dispatch_multiple_fanout_indices():
    """Batched dispatch (K>1) should produce child events with distinct fanout indices."""
    from tests_rlm_adk.provider_fake.contract_runner import (
        run_fixture_contract_with_plugins,
    )

    # structured_output_batched_k3 dispatches 3 children concurrently
    fixture_path = FIXTURE_DIR / "structured_output_batched_k3.json"
    if not fixture_path.exists():
        pytest.skip("structured_output_batched_k3 fixture not found")

    with tempfile.TemporaryDirectory(prefix="child-fanout-") as tmpdir:
        result = await run_fixture_contract_with_plugins(
            fixture_path,
            traces_db_path=str(Path(tmpdir) / "traces.db"),
            tmpdir=tmpdir,
        )

    assert result.contract.passed, result.contract.diagnostics()

    # Collect child events and their fanout indices.
    # Each child orchestrator (K=3) emits at least current_depth@d1 and
    # iteration_count@d1 in its initial state event, plus should_stop@d1
    # and final_response_text@d1 at completion. These are all curated keys,
    # so child events MUST appear.
    child_events = [
        e
        for e in result.events
        if getattr(e, "custom_metadata", None) and e.custom_metadata.get("rlm_child_event") is True
    ]

    assert len(child_events) > 0, (
        "No child events found for K=3 batched dispatch. "
        "Child orchestrators always emit curated state keys "
        "(current_depth, iteration_count) in their initial event."
    )

    fanout_indices = {
        e.custom_metadata["child_fanout_idx"]
        for e in child_events
        if "child_fanout_idx" in e.custom_metadata
    }

    # K=3 children should produce 3 distinct fanout indices (0, 1, 2)
    assert len(fanout_indices) >= 3, (
        f"Expected 3 distinct fanout indices for K=3 batch, got {len(fanout_indices)}: {fanout_indices}"
    )
