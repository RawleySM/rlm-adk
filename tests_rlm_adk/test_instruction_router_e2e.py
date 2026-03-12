"""E2E tests for instruction_router depth/fanout isolation.

RED phase: these tests define the contract for the instruction_router feature.
The feature does not exist yet -- all tests are expected to fail.

The instruction_router is a callable ``(depth, fanout_idx) -> str`` that returns
a unique marker string to be injected into the systemInstruction for each
(depth, fanout_idx) pair.  Tests verify:

1. Markers appear in the correct API calls (isolation).
2. Markers are absent from API calls at other depths/fanout indices (no leakage).
3. Backward compatibility: no router means no marker injection.
4. SQLite telemetry captures the skill_instruction column.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from rlm_adk.agent import create_rlm_app
from rlm_adk.state import FINAL_ANSWER
from tests_rlm_adk.provider_fake.fixtures import ScenarioRouter
from tests_rlm_adk.provider_fake.server import FakeGeminiServer

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

# ---------------------------------------------------------------------------
# Fixture path and marker constants
# ---------------------------------------------------------------------------

_FIXTURE = Path(__file__).parent / "fixtures" / "provider_fake" / "instruction_router_fanout.json"

# Unique marker strings per (depth, fanout_idx)
_MARKER_D0 = "IROUTER_DEPTH0_F0_a1b2c3"
_MARKER_D1F0 = "IROUTER_DEPTH1_F0_d4e5f6"
_MARKER_D1F1 = "IROUTER_DEPTH1_F1_g7h8i9"

_MARKERS = {
    (0, 0): _MARKER_D0,
    (1, 0): _MARKER_D1F0,
    (1, 1): _MARKER_D1F1,
}


def _test_router(depth: int, fanout_idx: int) -> str:
    """Return a unique marker string for each (depth, fanout_idx) pair."""
    return _MARKERS.get((depth, fanout_idx), f"IROUTER_DEPTH{depth}_F{fanout_idx}_unknown")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _system_instruction_text(request_body: dict) -> str:
    """Extract full system instruction text from a captured Gemini request body."""
    si = request_body.get("systemInstruction", {})
    parts = si.get("parts", [])
    return " ".join(p.get("text", "") for p in parts if isinstance(p, dict))


# Env vars we override for the fake server; restored after each run.
_ENV_KEYS = (
    "GOOGLE_GEMINI_BASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "RLM_ADK_MODEL",
    "RLM_LLM_RETRY_DELAY",
    "RLM_LLM_MAX_RETRIES",
    "RLM_MAX_ITERATIONS",
    "RLM_MAX_CONCURRENT_CHILDREN",
    "RLM_ADK_RETRY_DELAY",
    "RLM_ADK_MAX_RETRIES",
    "GOOGLE_GENAI_USE_VERTEXAI",
)


def _save_env() -> dict[str, str | None]:
    """Snapshot current values of overridden env vars."""
    return {k: os.environ.get(k) for k in _ENV_KEYS}


def _restore_env(saved: dict[str, str | None]) -> None:
    """Restore env vars to their pre-run values."""
    for key, val in saved.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


async def _run_with_router(
    fixture_path: Path,
    router_fn: Callable[[int, int], str] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], ScenarioRouter]:
    """Run a fixture through the real pipeline with an optional instruction_router.

    Returns:
        (final_state, captured_requests, scenario_router)
    """
    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)

    saved = _save_env()
    try:
        base_url = await server.start()

        # Set env vars to redirect SDK traffic to the fake server
        os.environ["GOOGLE_GEMINI_BASE_URL"] = base_url
        os.environ["GEMINI_API_KEY"] = "fake-key-for-testing"
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ["RLM_ADK_MODEL"] = "gemini-fake"
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
        os.environ["RLM_MAX_CONCURRENT_CHILDREN"] = "1"
        os.environ["RLM_LLM_RETRY_DELAY"] = "0"
        os.environ["RLM_LLM_MAX_RETRIES"] = "0"
        os.environ["RLM_MAX_ITERATIONS"] = str(router.config.get("max_iterations", 5))

        # Build app with or without instruction_router
        app_kwargs: dict[str, Any] = {
            "model": "gemini-fake",
            "thinking_budget": 0,
            "langfuse": False,
            "sqlite_tracing": False,
        }
        if router_fn is not None:
            app_kwargs["instruction_router"] = router_fn

        app = create_rlm_app(**app_kwargs)

        session_service = InMemorySessionService()
        runner = Runner(app=app, session_service=session_service)

        initial_state = router.config.get("initial_state") or None
        session = await session_service.create_session(
            app_name="rlm_adk",
            user_id="test-user",
            state=initial_state,
        )

        # Run to completion
        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text="test prompt")],
        )
        async for _event in runner.run_async(
            user_id="test-user",
            session_id=session.id,
            new_message=content,
        ):
            pass

        # Re-fetch session for final state
        final_session = await runner.session_service.get_session(
            app_name="rlm_adk",
            user_id="test-user",
            session_id=session.id,
        )
        final_state = final_session.state if final_session else {}

        return final_state, router.captured_requests, router

    finally:
        await server.stop()
        _restore_env(saved)


async def _run_with_router_and_sqlite(
    fixture_path: Path,
    router_fn: Callable[[int, int], str] | None,
    db_path: str,
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Run a fixture with SqliteTracingPlugin enabled.

    Returns:
        (final_state, db_path, captured_requests)
    """
    from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)

    saved = _save_env()
    try:
        base_url = await server.start()

        os.environ["GOOGLE_GEMINI_BASE_URL"] = base_url
        os.environ["GEMINI_API_KEY"] = "fake-key-for-testing"
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ["RLM_ADK_MODEL"] = "gemini-fake"
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
        os.environ["RLM_MAX_CONCURRENT_CHILDREN"] = "1"
        os.environ["RLM_LLM_RETRY_DELAY"] = "0"
        os.environ["RLM_LLM_MAX_RETRIES"] = "0"
        os.environ["RLM_MAX_ITERATIONS"] = str(router.config.get("max_iterations", 5))

        sqlite_plugin = SqliteTracingPlugin(db_path=db_path)

        app_kwargs: dict[str, Any] = {
            "model": "gemini-fake",
            "thinking_budget": 0,
            "langfuse": False,
            "sqlite_tracing": False,
            "plugins": [sqlite_plugin],
        }
        if router_fn is not None:
            app_kwargs["instruction_router"] = router_fn

        app = create_rlm_app(**app_kwargs)

        session_service = InMemorySessionService()
        runner = Runner(app=app, session_service=session_service)

        initial_state = router.config.get("initial_state") or None
        session = await session_service.create_session(
            app_name="rlm_adk",
            user_id="test-user",
            state=initial_state,
        )

        content = types.Content(
            role="user",
            parts=[types.Part.from_text(text="test prompt")],
        )
        async for _event in runner.run_async(
            user_id="test-user",
            session_id=session.id,
            new_message=content,
        ):
            pass

        final_session = await runner.session_service.get_session(
            app_name="rlm_adk",
            user_id="test-user",
            session_id=session.id,
        )
        final_state = final_session.state if final_session else {}

        return final_state, db_path, router.captured_requests

    finally:
        await server.stop()
        _restore_env(saved)


# ===========================================================================
# TestInstructionRouterIsolation
# ===========================================================================


class TestInstructionRouterIsolation:
    """Verify instruction_router injects markers at the correct depth/fanout."""

    @pytest.fixture(scope="class")
    async def router_result(self):
        """Run the fixture once with _test_router and share across all tests."""
        final_state, captured_requests, router = await _run_with_router(_FIXTURE, _test_router)
        return final_state, captured_requests, router

    async def test_contract_passes(self, router_result):
        """The router ran to completion and produced a final_answer."""
        final_state, _captured, _router = router_result
        assert final_state.get(FINAL_ANSWER) is not None, (
            f"Expected final_answer in state, got keys: {list(final_state.keys())}"
        )

    async def test_d0_marker_in_reasoning_calls(self, router_result):
        """Calls 0 and 5 (reasoning, d=0) systemInstruction contains _MARKER_D0."""
        _state, captured, _router = router_result
        assert len(captured) >= 6, f"Expected >= 6 captured requests, got {len(captured)}"

        for idx in (0, 5):
            si_text = _system_instruction_text(captured[idx])
            assert _MARKER_D0 in si_text, (
                f"Call {idx}: expected {_MARKER_D0!r} in systemInstruction, got: {si_text[:200]!r}"
            )

    async def test_d1f0_marker_in_first_worker(self, router_result):
        """Calls 1 and 2 (worker d=1 f=0) systemInstruction contains _MARKER_D1F0."""
        _state, captured, _router = router_result
        assert len(captured) >= 6

        for idx in (1, 2):
            si_text = _system_instruction_text(captured[idx])
            assert _MARKER_D1F0 in si_text, (
                f"Call {idx}: expected {_MARKER_D1F0!r} in systemInstruction, "
                f"got: {si_text[:200]!r}"
            )

    async def test_d1f1_marker_in_second_worker(self, router_result):
        """Calls 3 and 4 (worker d=1 f=1) systemInstruction contains _MARKER_D1F1."""
        _state, captured, _router = router_result
        assert len(captured) >= 6

        for idx in (3, 4):
            si_text = _system_instruction_text(captured[idx])
            assert _MARKER_D1F1 in si_text, (
                f"Call {idx}: expected {_MARKER_D1F1!r} in systemInstruction, "
                f"got: {si_text[:200]!r}"
            )

    async def test_d0_marker_absent_from_workers(self, router_result):
        """Calls 1-4 (workers) must NOT contain the d=0 marker."""
        _state, captured, _router = router_result
        assert len(captured) >= 6

        for idx in (1, 2, 3, 4):
            si_text = _system_instruction_text(captured[idx])
            assert _MARKER_D0 not in si_text, (
                f"Call {idx}: d=0 marker {_MARKER_D0!r} leaked into worker call. "
                f"systemInstruction: {si_text[:200]!r}"
            )

    async def test_d1f0_marker_absent_from_d0_and_f1(self, router_result):
        """Calls 0, 3, 4, 5 must NOT contain the d=1 f=0 marker."""
        _state, captured, _router = router_result
        assert len(captured) >= 6

        for idx in (0, 3, 4, 5):
            si_text = _system_instruction_text(captured[idx])
            assert _MARKER_D1F0 not in si_text, (
                f"Call {idx}: d=1 f=0 marker {_MARKER_D1F0!r} leaked. "
                f"systemInstruction: {si_text[:200]!r}"
            )

    async def test_d1f1_marker_absent_from_d0_and_f0(self, router_result):
        """Calls 0, 1, 2, 5 must NOT contain the d=1 f=1 marker."""
        _state, captured, _router = router_result
        assert len(captured) >= 6

        for idx in (0, 1, 2, 5):
            si_text = _system_instruction_text(captured[idx])
            assert _MARKER_D1F1 not in si_text, (
                f"Call {idx}: d=1 f=1 marker {_MARKER_D1F1!r} leaked. "
                f"systemInstruction: {si_text[:200]!r}"
            )


# ===========================================================================
# TestInstructionRouterBackwardCompat
# ===========================================================================


class TestInstructionRouterBackwardCompat:
    """Verify backward compatibility: no router means no marker injection."""

    @pytest.fixture(scope="class")
    async def compat_result(self):
        """Run the fixture once without a router."""
        final_state, captured_requests, router = await _run_with_router(_FIXTURE, None)
        return final_state, captured_requests, router

    async def test_no_router_no_skill_instruction(self, compat_result):
        """Without a router, no marker text should appear in any systemInstruction."""
        _state, captured, _router = compat_result

        all_markers = [_MARKER_D0, _MARKER_D1F0, _MARKER_D1F1]
        for idx, req in enumerate(captured):
            si_text = _system_instruction_text(req)
            for marker in all_markers:
                assert marker not in si_text, (
                    f"Call {idx}: marker {marker!r} found in systemInstruction "
                    f"without a router. text: {si_text[:200]!r}"
                )

    async def test_contract_passes_without_router(self, compat_result):
        """The pipeline completes and produces a final_answer even without a router."""
        final_state, _captured, _router = compat_result
        assert final_state.get(FINAL_ANSWER) is not None, (
            f"Expected final_answer in state, got keys: {list(final_state.keys())}"
        )


# ===========================================================================
# TestInstructionRouterSqliteTelemetry
# ===========================================================================


class TestInstructionRouterSqliteTelemetry:
    """Verify instruction_router markers are captured in SQLite telemetry."""

    @pytest.fixture(scope="class")
    async def sqlite_result_with_router(self, tmp_path_factory):
        """Run with router and SQLite tracing enabled."""
        tmp_dir = tmp_path_factory.mktemp("irouter_sqlite")
        db_path = str(tmp_dir / "traces.db")
        final_state, db_path_out, captured = await _run_with_router_and_sqlite(
            _FIXTURE, _test_router, db_path
        )
        return final_state, db_path_out, captured

    @pytest.fixture(scope="class")
    async def sqlite_result_without_router(self, tmp_path_factory):
        """Run without router and SQLite tracing enabled."""
        tmp_dir = tmp_path_factory.mktemp("irouter_sqlite_no_router")
        db_path = str(tmp_dir / "traces.db")
        final_state, db_path_out, captured = await _run_with_router_and_sqlite(
            _FIXTURE, None, db_path
        )
        return final_state, db_path_out, captured

    async def test_skill_instruction_in_telemetry_rows(self, sqlite_result_with_router):
        """Telemetry model_call rows contain skill_instruction matching markers."""
        _state, db_path, _captured = sqlite_result_with_router

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT skill_instruction FROM telemetry WHERE event_type = 'model_call'"
            ).fetchall()
        finally:
            conn.close()

        assert len(rows) > 0, "Expected telemetry rows for model_call events"

        # Collect all non-null skill_instruction values
        skill_instructions = [row[0] for row in rows if row[0] is not None]
        assert len(skill_instructions) > 0, (
            "Expected at least one telemetry row with skill_instruction set"
        )

        # At least one row should contain each marker
        all_text = " ".join(skill_instructions)
        for marker in [_MARKER_D0, _MARKER_D1F0, _MARKER_D1F1]:
            assert marker in all_text, (
                f"Expected marker {marker!r} in telemetry skill_instruction values, "
                f"got: {skill_instructions!r}"
            )

    async def test_skill_instruction_null_without_router(self, sqlite_result_without_router):
        """Without a router, all telemetry rows have skill_instruction IS NULL."""
        _state, db_path, _captured = sqlite_result_without_router

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT skill_instruction FROM telemetry WHERE event_type = 'model_call'"
            ).fetchall()
        finally:
            conn.close()

        assert len(rows) > 0, "Expected telemetry rows for model_call events"

        non_null = [row[0] for row in rows if row[0] is not None]
        assert len(non_null) == 0, (
            f"Expected all skill_instruction values to be NULL without router, "
            f"got {len(non_null)} non-null values: {non_null!r}"
        )
