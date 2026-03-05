"""Skill helper e2e tests: coverage checks + provider-fake pipeline.

Validates that the repomix REPL helpers (probe_repo, pack_repo, shard_repo)
work correctly inside the actual agent REPL runtime via per-iteration
LAST_REPL_RESULT snapshot introspection.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest
from google.adk.sessions import InMemorySessionService
from google.genai import types

from rlm_adk.agent import create_rlm_app
from rlm_adk.skills.repomix_skill import REPOMIX_SKILL
from rlm_adk.state import FINAL_ANSWER, LAST_REPL_RESULT

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.fixtures import ScenarioRouter
from tests_rlm_adk.provider_fake.server import FakeGeminiServer

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]

SKILL_FIXTURE = FIXTURE_DIR / "agent_challenge" / "skill_helper.json"
EXPECTED_FINAL = (
    "skill_helpers_validated: probe=4_files, pack=xml_ok, "
    "shard=chunks_ok, batched=2_analyses"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_repl_blocks(text: str) -> list[str]:
    """Extract ```repl code blocks from text."""
    return re.findall(r"```repl\n(.*?)```", text, re.DOTALL)


def _extract_function_calls(code: str) -> set[str]:
    """AST-based extraction of top-level function call names."""
    names: set[str] = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _load_fixture_repl_code(fixture_path: Path) -> list[str]:
    """Load fixture JSON and extract REPL code from reasoning responses.

    Supports both legacy ```repl text blocks and functionCall execute_code args.
    """
    import json

    with open(fixture_path) as f:
        fixture = json.load(f)
    blocks: list[str] = []
    for resp in fixture["responses"]:
        if resp.get("caller") != "reasoning":
            continue
        part = resp["body"]["candidates"][0]["content"]["parts"][0]
        # functionCall format (execute_code tool)
        if "functionCall" in part:
            fc = part["functionCall"]
            if fc.get("name") == "execute_code" and "code" in fc.get("args", {}):
                blocks.append(fc["args"]["code"])
        # Legacy text format with ```repl blocks
        elif "text" in part:
            blocks.extend(_extract_repl_blocks(part["text"]))
    return blocks


def _extract_repl_snapshots(events) -> list[dict]:
    """Extract LAST_REPL_RESULT dicts from event stream."""
    snapshots = []
    for event in events:
        sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
        if LAST_REPL_RESULT in sd:
            snapshots.append(sd[LAST_REPL_RESULT])
    return snapshots


# ---------------------------------------------------------------------------
# Runner helpers (duplicated from test_provider_fake_e2e.py to avoid
# fragile test-importing-test patterns)
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
    for key in ("GOOGLE_GEMINI_BASE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                "RLM_ADK_MODEL", "RLM_LLM_RETRY_DELAY", "RLM_LLM_MAX_RETRIES",
                "RLM_MAX_ITERATIONS"):
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
# TestSkillInstructionCoverage — sync, fast
# ===========================================================================

class TestSkillInstructionCoverage:
    """Validate skill instruction docs cover all helpers with valid examples."""

    def test_skill_instructions_have_repl_examples(self):
        blocks = _extract_repl_blocks(REPOMIX_SKILL.instructions)
        assert len(blocks) >= 3, (
            f"Expected >= 3 repl blocks in skill instructions, got {len(blocks)}"
        )

    def test_skill_instructions_cover_all_helpers(self):
        blocks = _extract_repl_blocks(REPOMIX_SKILL.instructions)
        all_code = "\n".join(blocks)
        calls = _extract_function_calls(all_code)
        for helper in ("probe_repo", "pack_repo", "shard_repo"):
            assert helper in calls, (
                f"{helper} not found in skill instruction examples. "
                f"Found calls: {calls}"
            )

    def test_fixture_covers_all_helpers(self):
        blocks = _load_fixture_repl_code(SKILL_FIXTURE)
        all_code = "\n".join(blocks)
        calls = _extract_function_calls(all_code)
        for helper in ("probe_repo", "pack_repo", "shard_repo"):
            assert helper in calls, (
                f"{helper} not found in fixture REPL code. Found calls: {calls}"
            )

    def test_fixture_repl_blocks_are_valid_python(self):
        blocks = _load_fixture_repl_code(SKILL_FIXTURE)
        assert len(blocks) >= 1, "No REPL blocks found in fixture"
        for i, block in enumerate(blocks):
            try:
                ast.parse(block)
            except SyntaxError as e:
                pytest.fail(
                    f"REPL block {i} failed to parse:\n{block}\nError: {e}"
                )


# ===========================================================================
# TestSkillHelperE2E — async, provider-fake pipeline
# ===========================================================================

class TestSkillHelperE2E:
    """E2E: skill helpers inside the real REPL runtime with per-iteration introspection."""

    @pytest.mark.parametrize("fake_server", [SKILL_FIXTURE], indirect=True)
    async def test_skill_helper_pipeline(self, fake_server: FakeGeminiServer):
        runner, session = await _make_runner_and_session()
        events, state = await _run_to_completion(runner, session)

        # Contract
        assert state.get(FINAL_ANSWER) == EXPECTED_FINAL, (
            f"final_answer mismatch: {state.get(FINAL_ANSWER)!r}"
        )
        assert fake_server.router.call_index == 5, (
            f"Expected 5 model calls, got {fake_server.router.call_index}"
        )

        # Per-iteration REPL introspection
        snapshots = _extract_repl_snapshots(events)
        iters_with_code = [s for s in snapshots if s["code_blocks"] > 0]
        assert len(iters_with_code) == 2, (
            f"Expected 2 iterations with code, got {len(iters_with_code)}. "
            f"All snapshots: {snapshots}"
        )

        # Iteration 1: probe_repo + pack_repo (no workers)
        assert iters_with_code[0]["has_errors"] is False, (
            f"Iteration 1 had errors: {iters_with_code[0]}"
        )
        assert iters_with_code[0]["has_output"] is True, (
            f"Iteration 1 had no output: {iters_with_code[0]}"
        )
        assert iters_with_code[0]["total_llm_calls"] == 0, (
            f"Iteration 1 should have 0 llm_calls: {iters_with_code[0]}"
        )

        # Iteration 2: shard_repo + llm_query_batched (2 workers)
        assert iters_with_code[1]["has_errors"] is False, (
            f"Iteration 2 had errors: {iters_with_code[1]}"
        )
        assert iters_with_code[1]["has_output"] is True, (
            f"Iteration 2 had no output: {iters_with_code[1]}"
        )
        assert iters_with_code[1]["total_llm_calls"] == 2, (
            f"Iteration 2 should have 2 llm_calls: {iters_with_code[1]}"
        )

        # Worker dispatches verified via total_llm_calls in REPL snapshots above.
        # In the collapsed orchestrator, worker events are consumed internally
        # by _consume_events and don't appear in the outer event stream.
