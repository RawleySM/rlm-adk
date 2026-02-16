"""RLM ADK Application - Wires all components into a runnable ADK App.

This module provides:
- create_rlm_runner(): Factory to create the configured Runner (App + plugins + services)
- create_rlm_app(): Factory to create the configured App with plugins
- create_rlm_orchestrator(): Factory to create the configured orchestrator
- create_reasoning_agent(): Factory to create the reasoning LlmAgent

Architecture (per ADK runtime event-loop):

    Agent -> App (plugins) -> Runner (services + event loop)

The ``Runner`` is the central orchestrator.  It drives the event loop,
receives Events yielded by agent logic, commits state/artifact changes
via Services, and forwards processed events upstream.

The ADK CLI (``adk run``, ``adk web``) discovers the module-level ``app``
symbol and creates its own ``Runner`` internally.  Programmatic callers
should use ``create_rlm_runner()`` which returns an ``InMemoryRunner``
with plugins, session service, and artifact service already wired.
"""

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.apps.app import App
from google.adk.planners import BuiltInPlanner
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import InMemoryRunner
from google.genai import types

from rlm_adk.callbacks.reasoning import reasoning_after_model, reasoning_before_model
from rlm_adk.dispatch import WorkerPool
from rlm_adk.orchestrator import RLMOrchestratorAgent
from rlm_adk.plugins.debug_logging import DebugLoggingPlugin
from rlm_adk.plugins.observability import ObservabilityPlugin
from rlm_adk.utils.prompts import (
    RLM_DYNAMIC_INSTRUCTION,
    RLM_STATIC_INSTRUCTION,
)

logger = logging.getLogger(__name__)

# Load repo-root .env so model and API key env vars are available.
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)


def create_reasoning_agent(
    model: str,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    thinking_budget: int = 1024,
) -> LlmAgent:
    """Create the ReasoningAgent (main LLM for depth=0 reasoning).

    Args:
        model: The LLM model identifier.
        static_instruction: Stable system prompt content (code examples, REPL
            guidance, repomix docs).  Passed as LlmAgent ``static_instruction=``
            which ADK places into ``system_instruction`` *without* template
            processing, so raw curly braces in code examples are safe.
        dynamic_instruction: Template string with ``{var?}`` state-variable
            placeholders (repo_url, root_prompt, etc.).
            Passed as LlmAgent ``instruction=``; when ``static_instruction``
            is also set, ADK resolves the template and appends the result to
            ``contents`` as user content.  The before_model callback then
            relocates it into ``system_instruction`` to maintain proper Gemini
            role alternation in contents.
        thinking_budget: Token budget for the model's built-in thinking/planning.
            Passed to ``BuiltInPlanner`` via ``ThinkingConfig``.  Set to ``0``
            to disable the planner.
    """
    planner = None
    if thinking_budget > 0:
        planner = BuiltInPlanner(
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=thinking_budget,
            )
        )

    return LlmAgent(
        name="reasoning_agent",
        model=model,
        description="Main reasoning agent for RLM iteration loop",
        instruction=dynamic_instruction,
        static_instruction=static_instruction,
        include_contents="none",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        output_key="reasoning_output",
        planner=planner,
        before_model_callback=reasoning_before_model,
        after_model_callback=reasoning_after_model,
    )


def create_rlm_orchestrator(
    model: str,
    root_prompt: str | None = None,
    persistent: bool = False,
    worker_pool: Any = None,
    repl: Any = None,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    repo_url: str | None = None,
    thinking_budget: int = 1024,
) -> RLMOrchestratorAgent:
    """Create the RLMOrchestratorAgent with the reasoning sub-agent."""
    reasoning = create_reasoning_agent(
        model,
        static_instruction=static_instruction,
        dynamic_instruction=dynamic_instruction,
        thinking_budget=thinking_budget,
    )

    # Default WorkerPool if none provided
    if worker_pool is None:
        worker_pool = WorkerPool(default_model=model)

    kwargs: dict[str, Any] = {
        "name": "rlm_orchestrator",
        "description": "RLM recursive iteration loop orchestrator",
        "reasoning_agent": reasoning,
        "root_prompt": root_prompt,
        "persistent": persistent,
        "worker_pool": worker_pool,
        "repl": repl,
        "sub_agents": [reasoning],
    }
    if repo_url:
        kwargs["repo_url"] = repo_url

    return RLMOrchestratorAgent(**kwargs)


def _default_plugins(*, debug: bool = True) -> list[BasePlugin]:
    """Build the default plugin list.

    ObservabilityPlugin is always included (observe-only, zero overhead on the
    happy path).  DebugLoggingPlugin is included by default.  Set *debug* to
    ``False`` **and** leave ``RLM_ADK_DEBUG`` unset to disable it.
    """
    plugins: list[BasePlugin] = [ObservabilityPlugin()]
    _debug_env = os.getenv("RLM_ADK_DEBUG", "").lower() in ("1", "true", "yes")
    if debug or _debug_env:
        plugins.append(DebugLoggingPlugin())
    return plugins


def create_rlm_app(
    model: str,
    root_prompt: str | None = None,
    persistent: bool = False,
    worker_pool: Any = None,
    repl: Any = None,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    repo_url: str | None = None,
    plugins: list[BasePlugin] | None = None,
    debug: bool = True,
    thinking_budget: int = 1024,
) -> App:
    """Create the full RLM ADK App with plugins wired in.

    This is the recommended entry point for programmatic usage.  The returned
    ``App`` carries the ``ObservabilityPlugin`` (always) and the
    ``DebugLoggingPlugin`` (enabled by default).  Pass *plugins* to override
    the default plugin list entirely.

    Args:
        model: The LLM model identifier.
        root_prompt: Initial user prompt for the RLM loop.
        persistent: Whether to persist REPL state across invocations.
        worker_pool: Optional WorkerPool for sub-agent dispatch.
        repl: Optional pre-configured REPL environment.
        static_instruction: Stable system prompt content.
        dynamic_instruction: Template string with state-variable placeholders.
        repo_url: Optional repository URL for context.
        plugins: Explicit plugin list.  When ``None`` (default), uses
            :func:`_default_plugins`.
        debug: Enable DebugLoggingPlugin (default ``True``; also forced on
            via ``RLM_ADK_DEBUG`` env-var).
        thinking_budget: Token budget for the reasoning agent's built-in
            planner.  Set to ``0`` to disable.
    """
    orchestrator = create_rlm_orchestrator(
        model=model,
        root_prompt=root_prompt,
        persistent=persistent,
        worker_pool=worker_pool,
        repl=repl,
        static_instruction=static_instruction,
        dynamic_instruction=dynamic_instruction,
        repo_url=repo_url,
        thinking_budget=thinking_budget,
    )
    resolved_plugins = plugins if plugins is not None else _default_plugins(debug=debug)
    return App(
        name="rlm_adk",
        root_agent=orchestrator,
        plugins=resolved_plugins,
    )


def create_rlm_runner(
    model: str,
    root_prompt: str | None = None,
    persistent: bool = False,
    worker_pool: Any = None,
    repl: Any = None,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    repo_url: str | None = None,
    plugins: list[BasePlugin] | None = None,
    debug: bool = True,
    thinking_budget: int = 1024,
) -> InMemoryRunner:
    """Create the full RLM ADK Runner: App + plugins + in-memory services.

    This is the recommended entry point for programmatic usage.  The returned
    ``InMemoryRunner`` has:

    - The ``App`` with ``ObservabilityPlugin`` (always) and
      ``DebugLoggingPlugin`` (enabled by default).
    - An in-memory ``SessionService`` for state persistence across the
      event loop.
    - An in-memory ``ArtifactService`` for binary artifact storage.

    The ``Runner`` drives the ADK event loop: it calls
    ``agent.run_async(ctx)``, receives yielded ``Event`` objects, commits
    ``state_delta`` / ``artifact_delta`` via services, and forwards
    processed events upstream.

    Usage::

        runner = create_rlm_runner(model="gemini-2.5-flash")
        session = await runner.session_service.create_session(
            app_name="rlm_adk", user_id="user",
        )
        async for event in runner.run_async(
            user_id="user", session_id=session.id, new_message=content,
        ):
            print(event)

    Args:
        model: The LLM model identifier.
        root_prompt: Initial user prompt for the RLM loop.
        persistent: Whether to persist REPL state across invocations.
        worker_pool: Optional WorkerPool for sub-agent dispatch.
        repl: Optional pre-configured REPL environment.
        static_instruction: Stable system prompt content.
        dynamic_instruction: Template string with state-variable placeholders.
        repo_url: Optional repository URL for context.
        plugins: Explicit plugin list.  When ``None`` (default), uses
            :func:`_default_plugins`.
        debug: Enable DebugLoggingPlugin (default ``True``; also forced on
            via ``RLM_ADK_DEBUG`` env-var).
        thinking_budget: Token budget for the reasoning agent's built-in
            planner.  Set to ``0`` to disable.
    """
    rlm_app = create_rlm_app(
        model=model,
        root_prompt=root_prompt,
        persistent=persistent,
        worker_pool=worker_pool,
        repl=repl,
        static_instruction=static_instruction,
        dynamic_instruction=dynamic_instruction,
        repo_url=repo_url,
        plugins=plugins,
        debug=debug,
        thinking_budget=thinking_budget,
    )
    return InMemoryRunner(app=rlm_app)


def _root_agent_model() -> str:
    """Resolve model used by ADK CLI-discoverable root_agent."""
    return os.getenv("RLM_ADK_MODEL", "gemini-3-pro-preview") #AGENT: DO NOT CHANGE WITHOUT ASKING USER


# ADK CLI entrypoint (`adk run rlm_adk`, `adk web`) discovers the ``app``
# symbol first (preferred) with plugins wired in.  The CLI creates its own
# ``Runner`` wrapping the ``App``.  ``root_agent`` is kept for backward
# compatibility with callers that import it directly.
app = create_rlm_app(model=_root_agent_model())
root_agent = app.root_agent
