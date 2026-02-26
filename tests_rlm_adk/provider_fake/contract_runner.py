"""Generic fixture-contract runner for provider-fake.

Executes any fixture JSON through the real production pipeline and asserts
against ``expected`` values in the fixture, producing structured
:class:`ContractResult` diagnostics on mismatch.

Usage::

    from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract

    result = await run_fixture_contract(Path("tests_rlm_adk/fixtures/provider_fake/full_pipeline.json"))
    assert result.passed, result.diagnostics()
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from rlm_adk.agent import create_rlm_app

from .fixtures import ContractResult, ScenarioRouter
from .server import FakeGeminiServer


# Env vars we override for the fake server; restored after each run.
_ENV_KEYS = (
    "GOOGLE_GEMINI_BASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "RLM_ADK_MODEL",
    "RLM_LLM_RETRY_DELAY",
    "RLM_LLM_MAX_RETRIES",
    "RLM_MAX_ITERATIONS",
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


def _set_env(base_url: str, router: ScenarioRouter) -> None:
    """Set env vars to redirect SDK traffic to the fake server."""
    os.environ["GOOGLE_GEMINI_BASE_URL"] = base_url
    os.environ["GEMINI_API_KEY"] = "fake-key-for-testing"
    os.environ.pop("GOOGLE_API_KEY", None)
    os.environ["RLM_ADK_MODEL"] = router.config.get("model", "gemini-fake")
    os.environ["RLM_LLM_RETRY_DELAY"] = str(router.config.get("retry_delay", 0.01))
    os.environ["RLM_LLM_MAX_RETRIES"] = str(router.config.get("max_retries", 3))
    os.environ["RLM_MAX_ITERATIONS"] = str(router.config.get("max_iterations", 5))


async def _make_runner_and_session(
    router: ScenarioRouter,
) -> tuple[Runner, Any]:
    """Create a Runner + session using config from the fixture's router."""
    app = create_rlm_app(
        model=os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
        thinking_budget=router.config.get("thinking_budget", 0),
        debug=False,
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


async def _run_to_completion(
    runner: Runner, session: Any, prompt: str = "test prompt",
) -> dict[str, Any]:
    """Drive the runner to completion and return final session state."""
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)],
    )
    async for _event in runner.run_async(
        user_id="test-user",
        session_id=session.id,
        new_message=content,
    ):
        pass  # consume all events

    # Re-fetch session to get final state
    final_session = await runner.session_service.get_session(
        app_name="rlm_adk",
        user_id="test-user",
        session_id=session.id,
    )
    return final_session.state if final_session else {}


async def run_fixture_contract(
    fixture_path: Path,
    prompt: str = "test prompt",
) -> ContractResult:
    """Execute a fixture through the real pipeline and check expectations.

    Lifecycle: load fixture -> start FakeGeminiServer -> set env vars ->
    create app + Runner -> run_async to completion -> check_expectations ->
    teardown server + restore env vars.

    Args:
        fixture_path: Path to the fixture JSON file.
        prompt: User prompt to send to the runner.

    Returns:
        A :class:`ContractResult` with pass/fail status and diagnostics.
    """
    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)

    saved = _save_env()
    try:
        base_url = await server.start()
        _set_env(base_url, router)

        t0 = time.monotonic()
        runner, session = await _make_runner_and_session(router)
        final_state = await _run_to_completion(runner, session, prompt)
        elapsed = time.monotonic() - t0

        return router.check_expectations(final_state, fixture_path, elapsed)
    finally:
        await server.stop()
        _restore_env(saved)
