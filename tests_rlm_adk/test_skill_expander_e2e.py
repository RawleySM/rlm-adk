"""Skill expansion e2e tests: provider-fake pipeline with FakeGeminiServer.

GAP-1 / TEST-1: Validates that skill imports (from rlm_repl_skills.ping)
are expanded inline, detected by has_llm_calls, rewritten to async, and
executed with worker dispatch through the full orchestrator pipeline.

Also covers GAP-2 / TEST-2: asserts expansion observability state keys
(REPL_EXPANDED_CODE, REPL_EXPANDED_CODE_HASH, REPL_SKILL_EXPANSION_META,
REPL_DID_EXPAND) are persisted in final session state.
"""

from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path

import pytest
from google.adk.sessions import InMemorySessionService
from google.genai import types

from rlm_adk.agent import create_rlm_app
from rlm_adk.repl.skill_registry import _registry
from rlm_adk.state import (
    FINAL_ANSWER,
    LAST_REPL_RESULT,
    REPL_DID_EXPAND,
    REPL_EXPANDED_CODE,
    REPL_EXPANDED_CODE_HASH,
    REPL_SKILL_EXPANSION_META,
)
from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.fixtures import ScenarioRouter
from tests_rlm_adk.provider_fake.server import FakeGeminiServer

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake, pytest.mark.agent_challenge]

EXPANSION_FIXTURE = FIXTURE_DIR / "agent_challenge" / "skill_expansion.json"
EXPECTED_FINAL = "skill_expansion_ok: layer=0, payload=pong"


@pytest.fixture(autouse=True)
def _ensure_ping_registered():
    """Ensure ping skill exports are registered (may be cleared by other tests)."""
    import rlm_adk.skills.repl_skills.ping as ping_mod

    _registry.clear()
    importlib.reload(ping_mod)
    yield


# ---------------------------------------------------------------------------
# Runner helpers (same pattern as test_skill_helper_e2e.py)
# ---------------------------------------------------------------------------


async def _make_runner_and_session():
    from google.adk.runners import Runner

    app = create_rlm_app(
        model=os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
        thinking_budget=0,
        langfuse=False,
        sqlite_tracing=False,
    )
    session_service = InMemorySessionService()
    runner = Runner(app=app, session_service=session_service)
    session = await session_service.create_session(
        app_name="rlm_adk",
        user_id="test-user",
    )
    return runner, session


async def _run_to_completion(runner, session, prompt: str = "test prompt"):
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)],
    )
    events = []
    async for event in runner.run_async(
        user_id="test-user",
        session_id=session.id,
        new_message=content,
    ):
        events.append(event)
    final_session = await runner.session_service.get_session(
        app_name="rlm_adk",
        user_id="test-user",
        session_id=session.id,
    )
    return events, final_session.state if final_session else {}


def _extract_repl_snapshots(events) -> list[dict]:
    snapshots = []
    for event in events:
        sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
        if LAST_REPL_RESULT in sd:
            snapshots.append(sd[LAST_REPL_RESULT])
    return snapshots


# ---------------------------------------------------------------------------
# Fake server fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def fake_server(request):
    fixture_path: Path = request.param
    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)
    url = await server.start()

    saved = {}
    for key in (
        "GOOGLE_GEMINI_BASE_URL",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "RLM_ADK_MODEL",
        "RLM_LLM_RETRY_DELAY",
        "RLM_LLM_MAX_RETRIES",
        "RLM_MAX_ITERATIONS",
    ):
        saved[key] = os.environ.get(key)

    os.environ["GOOGLE_GEMINI_BASE_URL"] = url
    os.environ["GEMINI_API_KEY"] = "fake-key-for-testing"
    os.environ.pop("GOOGLE_API_KEY", None)
    os.environ["RLM_ADK_MODEL"] = "gemini-fake"
    os.environ["RLM_LLM_RETRY_DELAY"] = "0.01"
    os.environ["RLM_LLM_MAX_RETRIES"] = "3"
    os.environ["RLM_MAX_ITERATIONS"] = str(router.config.get("max_iterations", 5))

    yield server

    await server.stop()
    for key, val in saved.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


# ===========================================================================
# TestSkillExpansionE2E — async, provider-fake pipeline
# ===========================================================================


class TestSkillExpansionE2E:
    """E2E: skill import expansion through the full orchestrator pipeline."""

    @pytest.mark.parametrize("fake_server", [EXPANSION_FIXTURE], indirect=True)
    async def test_skill_expansion_pipeline(self, fake_server: FakeGeminiServer):
        runner, session = await _make_runner_and_session()
        events, state = await _run_to_completion(runner, session)

        # --- Contract: final answer ---
        assert state.get(FINAL_ANSWER) == EXPECTED_FINAL, (
            f"final_answer mismatch: {state.get(FINAL_ANSWER)!r}"
        )
        assert fake_server.router.call_index == 3, (
            f"Expected 3 model calls (1 reasoning + 1 worker + 1 final), "
            f"got {fake_server.router.call_index}"
        )

        # --- Per-iteration REPL introspection ---
        snapshots = _extract_repl_snapshots(events)
        iters_with_code = [s for s in snapshots if s["code_blocks"] > 0]
        assert len(iters_with_code) == 1, (
            f"Expected 1 iteration with code, got {len(iters_with_code)}"
        )

        # Iteration 1: skill expansion + llm_query (1 worker)
        assert iters_with_code[0]["has_errors"] is False, (
            f"Iteration 1 had errors: {iters_with_code[0]}"
        )
        assert iters_with_code[0]["total_llm_calls"] == 1, (
            f"Expected 1 llm_call (worker dispatch), got: {iters_with_code[0]}"
        )

    @pytest.mark.parametrize("fake_server", [EXPANSION_FIXTURE], indirect=True)
    async def test_expansion_state_keys_in_final_state(
        self,
        fake_server: FakeGeminiServer,
    ):
        """GAP-2: Verify expansion observability keys in session state."""
        runner, session = await _make_runner_and_session()
        _events, state = await _run_to_completion(runner, session)

        # REPL_DID_EXPAND
        assert state.get(REPL_DID_EXPAND) is True, (
            f"REPL_DID_EXPAND not True in final state: {state.get(REPL_DID_EXPAND)}"
        )

        # REPL_EXPANDED_CODE — should contain inlined skill source, not the import
        expanded_code = state.get(REPL_EXPANDED_CODE)
        assert expanded_code is not None, "REPL_EXPANDED_CODE missing from state"
        assert "from rlm_repl_skills" not in expanded_code, (
            "Expanded code should not contain the synthetic import"
        )
        assert "run_recursive_ping" in expanded_code, (
            "Expanded code should contain the inlined function"
        )

        # REPL_EXPANDED_CODE_HASH — must match actual hash
        code_hash = state.get(REPL_EXPANDED_CODE_HASH)
        expected_hash = hashlib.sha256(expanded_code.encode()).hexdigest()
        assert code_hash == expected_hash, f"Hash mismatch: {code_hash} != {expected_hash}"

        # REPL_SKILL_EXPANSION_META — symbols and modules
        meta = state.get(REPL_SKILL_EXPANSION_META)
        assert isinstance(meta, dict), f"Expected dict, got {type(meta)}"
        assert "run_recursive_ping" in meta["symbols"], (
            f"Expected run_recursive_ping in symbols: {meta['symbols']}"
        )
        assert "rlm_repl_skills.ping" in meta["modules"], (
            f"Expected rlm_repl_skills.ping in modules: {meta['modules']}"
        )
