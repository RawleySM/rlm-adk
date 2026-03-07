"""Generic fixture-contract runner for provider-fake.

Executes any fixture JSON through the real production pipeline and asserts
against ``expected`` values in the fixture, producing structured
:class:`ContractResult` diagnostics on mismatch.

Usage::

    from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract

    result = await run_fixture_contract(Path("tests_rlm_adk/fixtures/provider_fake/full_pipeline.json"))
    assert result.passed, result.diagnostics()

    # Plugin-aware variant:
    from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract_with_plugins

    result = await run_fixture_contract_with_plugins(fixture_path, traces_db_path="/tmp/traces.db")
    assert result.contract.passed
    assert result.traces_db_path is not None
"""

from __future__ import annotations

import dataclasses
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from google.adk.artifacts import InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from rlm_adk.agent import create_rlm_app, create_rlm_runner
from rlm_adk.repl.local_repl import LocalREPL

from .fixtures import ContractResult, ScenarioRouter
from .server import FakeGeminiServer


def _wire_test_hooks(app: Any) -> None:
    """Chain test state hooks onto reasoning agent.

    When a fixture sets ``config.test_hooks = true``, this function:
    1. Chains ``reasoning_test_state_hook`` before ``reasoning_before_model``
       so the CB_REASONING_CONTEXT dict flows into state and (via the
       ``{cb_reasoning_context?}`` template placeholder) into systemInstruction.
    2. Wires ``orchestrator_test_state_hook`` as ``before_agent_callback``.
    3. Wires ``tool_test_state_hook`` as ``before_tool_callback``.

    Note: Worker/child hooks are no longer wired here.  Child orchestrators
    are spawned on-demand by dispatch.py and cannot be monkey-patched at
    app creation time.  The CB_WORKER_CONTEXT tests that depended on this
    have been removed.
    """
    from rlm_adk.callbacks.orchestrator import orchestrator_test_state_hook
    from rlm_adk.callbacks.reasoning import (
        reasoning_before_model,
        reasoning_test_state_hook,
        tool_test_state_hook,
    )

    orchestrator = app.root_agent

    # --- Wire orchestrator before_agent_callback ---
    # Fires before the reasoning agent's first LLM call, so the dict is
    # in state for ALL reasoning template resolutions (including call 0).
    object.__setattr__(orchestrator, "before_agent_callback", orchestrator_test_state_hook)

    # --- Chain reasoning hooks ---
    reasoning_agent = orchestrator.reasoning_agent
    original_reasoning_cb = reasoning_agent.before_model_callback

    def chained_reasoning_before_model(callback_context, llm_request):
        reasoning_test_state_hook(callback_context, llm_request)
        if original_reasoning_cb:
            return original_reasoning_cb(callback_context=callback_context, llm_request=llm_request)
        return reasoning_before_model(callback_context, llm_request)

    object.__setattr__(reasoning_agent, "before_model_callback", chained_reasoning_before_model)

    # --- Wire tool before_tool_callback on reasoning agent ---
    # Fires before each execute_code call, writes CB_TOOL_CONTEXT to state.
    # Available in reasoning template resolution from the NEXT LLM call onward.
    object.__setattr__(reasoning_agent, "before_tool_callback", tool_test_state_hook)


@dataclasses.dataclass
class PluginContractResult:
    """Enriched result from a plugin-aware fixture run."""

    contract: ContractResult
    events: list[Any]
    final_state: dict[str, Any]
    artifact_service: InMemoryArtifactService
    traces_db_path: str | None
    router: ScenarioRouter


# Env vars we override for the fake server; restored after each run.
_ENV_KEYS = (
    "GOOGLE_GEMINI_BASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "RLM_ADK_MODEL",
    "RLM_LLM_RETRY_DELAY",
    "RLM_LLM_MAX_RETRIES",
    "RLM_MAX_ITERATIONS",
    "RLM_REPL_TRACE",
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


def _make_repl(router: ScenarioRouter) -> LocalREPL | None:
    """Create a LocalREPL pre-loaded with initial_repl_globals from fixture config.

    Supports plain values (dicts, strings, lists) and mock functions via
    the ``$mock_return`` sentinel::

        "initial_repl_globals": {
            "pack_repo": {"$mock_return": "known XML string"},
            "_test_metadata": {"key": "value"}
        }

    Returns None if no initial_repl_globals are configured.
    """
    repl_globals_spec = router.config.get("initial_repl_globals")
    if not repl_globals_spec:
        return None

    repl = LocalREPL(depth=1)
    for key, value in repl_globals_spec.items():
        if isinstance(value, dict) and "$mock_return" in value:
            return_value = value["$mock_return"]
            repl.globals[key] = lambda *args, _rv=return_value, **kwargs: _rv
        else:
            repl.globals[key] = value
    return repl


async def _make_runner_and_session(
    router: ScenarioRouter,
) -> tuple[Runner, Any]:
    """Create a Runner + session using config from the fixture's router."""
    repl = _make_repl(router)

    # When test_hooks is enabled, append cb_reasoning_context placeholder
    # to the dynamic instruction so the state dict flows into systemInstruction.
    dynamic_instruction = None
    if router.config.get("test_hooks"):
        from rlm_adk.utils.prompts import RLM_DYNAMIC_INSTRUCTION
        dynamic_instruction = (
            RLM_DYNAMIC_INSTRUCTION
            + "Callback state: {cb_reasoning_context?}\n"
            + "Orchestrator state: {cb_orchestrator_context?}\n"
            + "Tool state: {cb_tool_context?}\n"
        )

    kwargs: dict[str, Any] = {
        "model": os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
        "thinking_budget": router.config.get("thinking_budget", 0),
        "repl": repl,
        "langfuse": False,
        "sqlite_tracing": False,
    }
    if dynamic_instruction is not None:
        kwargs["dynamic_instruction"] = dynamic_instruction

    app = create_rlm_app(**kwargs)

    # Wire test hooks onto reasoning agent and worker pool
    if router.config.get("test_hooks"):
        _wire_test_hooks(app)

    session_service = InMemorySessionService()
    runner = Runner(app=app, session_service=session_service)
    initial_state = router.config.get("initial_state") or None
    session = await session_service.create_session(
        app_name="rlm_adk",
        user_id="test-user",
        state=initial_state,
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
    """Execute a fixture through the plugin-enabled production pipeline.

    Default provider-fake contract runs should exercise the same observability
    stack as real runs, so this wrapper delegates to
    :func:`run_fixture_contract_with_plugins` with:

    - ``ObservabilityPlugin`` enabled
    - ``SqliteTracingPlugin`` writing to a temporary SQLite DB
    - ``REPLTracingPlugin`` enabled via ``repl_trace_level=2``

    Args:
        fixture_path: Path to the fixture JSON file.
        prompt: User prompt to send to the runner.

    Returns:
        A :class:`ContractResult` with pass/fail status and diagnostics.
    """
    with tempfile.TemporaryDirectory(prefix="provider-fake-obs-") as tmpdir:
        plugin_result = await run_fixture_contract_with_plugins(
            fixture_path,
            prompt=prompt,
            traces_db_path=str(Path(tmpdir) / "traces.db"),
            repl_trace_level=2,
        )
    return plugin_result.contract


async def run_fixture_contract_with_plugins(
    fixture_path: Path,
    prompt: str = "test prompt",
    traces_db_path: str | None = None,
    repl_trace_level: int = 2,
) -> PluginContractResult:
    """Execute a fixture through the full plugin-enabled pipeline.

    Uses ``create_rlm_runner()`` with:
    - ``InMemoryArtifactService`` for volatile artifact storage
    - ``InMemorySessionService`` for test isolation
    - ``ObservabilityPlugin`` (always on)
    - ``SqliteTracingPlugin`` pointing to *traces_db_path*
    - ``REPLTracingPlugin`` (when *repl_trace_level* > 0)
    - ``ObservabilityPlugin`` verbose mode disabled (noisy in CI)
    - ``LangfuseTracingPlugin`` disabled (requires external service)

    Args:
        fixture_path: Path to the fixture JSON file.
        prompt: User prompt to send to the runner.
        traces_db_path: Path for SqliteTracingPlugin DB.  ``None`` disables
            sqlite tracing.
        repl_trace_level: ``RLM_REPL_TRACE`` env var value (0 = off).

    Returns:
        A :class:`PluginContractResult` with contract result, events,
        final state, artifact service reference, and traces DB path.
    """
    from rlm_adk.plugins.observability import ObservabilityPlugin
    from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
    from rlm_adk.plugins.repl_tracing import REPLTracingPlugin

    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, host="127.0.0.1", port=0)

    saved = _save_env()
    try:
        base_url = await server.start()
        _set_env(base_url, router)
        os.environ["RLM_REPL_TRACE"] = str(repl_trace_level)

        # Build plugin list
        from google.adk.plugins.base_plugin import BasePlugin
        plugins: list[BasePlugin] = [ObservabilityPlugin()]
        if traces_db_path:
            plugins.append(SqliteTracingPlugin(db_path=traces_db_path))
        if repl_trace_level > 0:
            plugins.append(REPLTracingPlugin())

        artifact_service = InMemoryArtifactService()
        session_service = InMemorySessionService()

        repl = _make_repl(router)
        runner = create_rlm_runner(
            model=os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
            thinking_budget=router.config.get("thinking_budget", 0),
            repl=repl,
            plugins=plugins,
            artifact_service=artifact_service,
            session_service=session_service,
            langfuse=False,
            sqlite_tracing=False,
        )

        initial_state = router.config.get("initial_state") or None
        session = await session_service.create_session(
            app_name="rlm_adk",
            user_id="test-user",
            state=initial_state,
        )

        t0 = time.monotonic()
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

        elapsed = time.monotonic() - t0

        # Re-fetch session to get final state
        final_session = await runner.session_service.get_session(
            app_name="rlm_adk",
            user_id="test-user",
            session_id=session.id,
        )
        final_state = final_session.state if final_session else {}

        contract = router.check_expectations(
            final_state,
            fixture_path,
            elapsed,
            events=events,
        )

        return PluginContractResult(
            contract=contract,
            events=events,
            final_state=final_state,
            artifact_service=artifact_service,
            traces_db_path=traces_db_path,
            router=router,
        )
    finally:
        await server.stop()
        _restore_env(saved)
