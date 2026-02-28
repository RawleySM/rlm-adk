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
import sqlite3
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.apps.app import App
from google.adk.planners import BuiltInPlanner
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.artifacts import BaseArtifactService, FileArtifactService
from google.adk.runners import InMemoryRunner, Runner
from google.adk.sessions.base_session_service import BaseSessionService
from google.genai import types
from google.genai.types import GenerateContentConfig, HttpOptions, HttpRetryOptions

from rlm_adk.callbacks.reasoning import reasoning_after_model, reasoning_before_model
from rlm_adk.dispatch import WorkerPool
from rlm_adk.orchestrator import RLMOrchestratorAgent
from rlm_adk.plugins.debug_logging import DebugLoggingPlugin
from rlm_adk.plugins.langfuse_tracing import LangfuseTracingPlugin
from rlm_adk.plugins.observability import ObservabilityPlugin
from rlm_adk.utils.prompts import (
    RLM_DYNAMIC_INSTRUCTION,
    RLM_STATIC_INSTRUCTION,
)

logger = logging.getLogger(__name__)

# Load repo-root .env so model and API key env vars are available.
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env", override=False)


def _project_root() -> Path:
    """Resolve the project root directory (contains pyproject.toml).

    Uses __file__ to anchor resolution, matching the .env pattern at line 54.
    """
    return Path(__file__).resolve().parents[1]


_DEFAULT_RETRY_OPTIONS = HttpRetryOptions(
    attempts=3,
    initial_delay=1.0,
    max_delay=60.0,
    exp_base=2.0,
)

_DEFAULT_DB_PATH = str(_project_root() / ".adk" / "session.db")
_DEFAULT_ARTIFACT_ROOT = str(_project_root() / ".adk" / "artifacts")

_SQLITE_STARTUP_PRAGMAS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;
PRAGMA wal_autocheckpoint = 1000;
"""


def _default_session_service(
    db_path: str | None = None,
) -> "BaseSessionService":
    """Create the default SqliteSessionService with performance pragmas.

    Ensures the parent directory exists, applies WAL mode and performance
    pragmas via a one-time synchronous connection, then returns the ADK
    SqliteSessionService instance.

    Args:
        db_path: Path to the SQLite database file.  Defaults to
            ``RLM_SESSION_DB`` env var, falling back to ``.adk/session.db``.

    Returns:
        A configured SqliteSessionService instance.
    """
    from google.adk.sessions.sqlite_session_service import SqliteSessionService

    resolved_path = db_path or os.getenv("RLM_SESSION_DB", _DEFAULT_DB_PATH)

    # Ensure parent directory exists
    db_dir = Path(resolved_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)

    # Apply persistent pragmas via synchronous sqlite3 connection.
    # WAL mode persists on disk once set; other pragmas are per-connection
    # but WAL is the critical one for concurrent reads.
    conn = sqlite3.connect(resolved_path)
    try:
        conn.executescript(_SQLITE_STARTUP_PRAGMAS)
    finally:
        conn.close()

    logger.info("Session DB: %s (WAL mode enabled)", resolved_path)

    return SqliteSessionService(db_path=resolved_path)


def _build_generate_content_config(
    retry_config: dict[str, Any] | None,
) -> GenerateContentConfig | None:
    """Build a GenerateContentConfig with HTTP retry options.

    Args:
        retry_config: Optional dict with keys matching ``HttpRetryOptions``
            fields (``attempts``, ``initial_delay``, ``max_delay``,
            ``exp_base``, ``jitter``, ``http_status_codes``).  When ``None``,
            sensible defaults (3 attempts, exponential backoff) are used.
            Pass an empty dict ``{}`` to use the SDK's built-in defaults.
    """
    if retry_config is not None:
        retry_opts = HttpRetryOptions(**retry_config) if retry_config else None
    else:
        retry_opts = _DEFAULT_RETRY_OPTIONS

    if retry_opts is None:
        return None

    return GenerateContentConfig(
        http_options=HttpOptions(
            timeout=int(os.getenv("RLM_REASONING_HTTP_TIMEOUT", "300000")),
            retry_options=retry_opts,
        ),
    )


def create_reasoning_agent(
    model: str,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    thinking_budget: int = 1024,
    retry_config: dict[str, Any] | None = None,
    *,
    tools: list | None = None,
    output_schema: type | None = None,
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
        retry_config: Optional dict of retry options passed to the Gemini model's
            ``HttpRetryOptions``.  Keys: ``attempts``, ``initial_delay``,
            ``max_delay``, ``exp_base``, ``jitter``, ``http_status_codes``.
            When ``None`` (default), uses sensible defaults (3 attempts,
            exponential backoff).  Pass an empty dict ``{}`` to use the SDK's
            built-in defaults only.
        tools: Optional list of tools (BaseTool, callables, or BaseToolset)
            to attach to the agent.  When provided, the agent operates in
            tool-calling mode (ADK manages tool call/response history).
        output_schema: Optional Pydantic BaseModel subclass for structured
            output.  When set, ADK injects a ``set_model_response`` tool
            and validates the model's response against this schema.
    """
    planner = None
    if thinking_budget > 0:
        planner = BuiltInPlanner(
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=thinking_budget,
            )
        )

    # Append repomix skill instructions to static instruction
    from rlm_adk.skills.repomix_skill import build_skill_instruction_block

    static_instruction = static_instruction + "\n" + build_skill_instruction_block()

    gcc = _build_generate_content_config(retry_config)

    # When tools are provided, ADK manages tool call/response history
    # via include_contents='default'.  Without tools, the orchestrator's
    # before_model callback injects message_history manually (legacy mode).
    content_mode = "default" if tools else "none"

    return LlmAgent(
        name="reasoning_agent",
        model=model,
        description="Main reasoning agent for RLM iteration loop",
        instruction=dynamic_instruction,
        static_instruction=static_instruction,
        include_contents=content_mode,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        output_key="reasoning_output",
        planner=planner,
        generate_content_config=gcc,
        before_model_callback=reasoning_before_model,
        after_model_callback=reasoning_after_model,
        tools=tools or [],
        output_schema=output_schema,
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
    retry_config: dict[str, Any] | None = None,
) -> RLMOrchestratorAgent:
    """Create the RLMOrchestratorAgent with the reasoning sub-agent."""
    reasoning = create_reasoning_agent(
        model,
        static_instruction=static_instruction,
        dynamic_instruction=dynamic_instruction,
        thinking_budget=thinking_budget,
        retry_config=retry_config,
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


def _default_plugins(
    *,
    debug: bool = True,
    langfuse: bool = False,
    sqlite_tracing: bool = True,
) -> list[BasePlugin]:
    """Build the default plugin list.

    ObservabilityPlugin is always included (observe-only, zero overhead on the
    happy path).  DebugLoggingPlugin is included by default.  Set *debug* to
    ``False`` **and** leave ``RLM_ADK_DEBUG`` unset to disable it.

    LangfuseTracingPlugin is opt-in (default ``False``).  Enable via
    ``langfuse=True`` or ``RLM_ADK_LANGFUSE=1`` env var.

    SqliteTracingPlugin is opt-in by default (``sqlite_tracing=True``).
    Disable via ``sqlite_tracing=False``.  If the plugin module is not yet
    available (Track B), it is silently skipped.
    """
    plugins: list[BasePlugin] = [ObservabilityPlugin()]
    _debug_env = os.getenv("RLM_ADK_DEBUG", "").lower() in ("1", "true", "yes")
    if debug or _debug_env:
        plugins.append(DebugLoggingPlugin(
            output_path=str(_project_root() / "rlm_adk_debug.yaml"),
        ))
    _sqlite_env = os.getenv("RLM_ADK_SQLITE_TRACING", "").lower() in ("1", "true", "yes")
    if sqlite_tracing or _sqlite_env:
        try:
            from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
            plugins.append(SqliteTracingPlugin(
                db_path=str(_project_root() / ".adk" / "traces.db"),
            ))
        except ImportError:
            logger.debug("SqliteTracingPlugin not available, skipping")
    _langfuse_env = os.getenv("RLM_ADK_LANGFUSE", "").lower() in ("1", "true", "yes")
    if langfuse or _langfuse_env:
        plugins.append(LangfuseTracingPlugin())
    _repl_trace_env = int(os.getenv("RLM_REPL_TRACE", "0"))
    if _repl_trace_env > 0:
        try:
            from rlm_adk.plugins.repl_tracing import REPLTracingPlugin
            plugins.append(REPLTracingPlugin())
        except ImportError:
            logger.debug("REPLTracingPlugin not available, skipping")

    _snapshot_env = os.getenv("RLM_CONTEXT_SNAPSHOTS", "").lower() in ("1", "true", "yes")
    if _snapshot_env:
        from rlm_adk.plugins.context_snapshot import ContextWindowSnapshotPlugin
        _adk_dir = str(_project_root() / ".adk")
        plugins.append(ContextWindowSnapshotPlugin(
            output_path=f"{_adk_dir}/context_snapshots.jsonl",
            output_capture_path=f"{_adk_dir}/model_outputs.jsonl",
        ))
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
    langfuse: bool = False,
    sqlite_tracing: bool = True,
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
        langfuse: Enable LangfuseTracingPlugin (default ``False``; also
            enabled via ``RLM_ADK_LANGFUSE=1`` env-var).
        sqlite_tracing: Enable SqliteTracingPlugin (default ``True``; also
            enabled via ``RLM_ADK_SQLITE_TRACING=1`` env-var).
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
    resolved_plugins = plugins if plugins is not None else _default_plugins(
        debug=debug, langfuse=langfuse, sqlite_tracing=sqlite_tracing,
    )
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
    artifact_service: BaseArtifactService | None = None,
    session_service: BaseSessionService | None = None,
    langfuse: bool = False,
    sqlite_tracing: bool = True,
) -> Runner:
    """Create the full RLM ADK Runner: App + plugins + services.

    This is the recommended entry point for programmatic usage.  The returned
    ``Runner`` has:

    - The ``App`` with ``ObservabilityPlugin`` (always) and
      ``DebugLoggingPlugin`` (enabled by default).
    - A ``SqliteSessionService`` for persistent state (default), or the
      caller-provided session service.
    - A ``FileArtifactService`` for persistent artifact storage (default),
      or the caller-provided artifact service.

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
        artifact_service: Optional artifact service to use.  When ``None``
            (default), creates a ``FileArtifactService`` rooted at
            ``.adk/artifacts/`` for persistent storage with rewind support.
            Pass ``InMemoryArtifactService()`` for volatile in-memory storage,
            or any other ``BaseArtifactService`` implementation.
        session_service: Optional session service to use.  When ``None``
            (default), creates a ``SqliteSessionService`` backed by
            ``.adk/session.db`` with WAL mode enabled.  Pass any
            ``BaseSessionService`` implementation to override.
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
        langfuse=langfuse,
        sqlite_tracing=sqlite_tracing,
    )

    # Resolve session service: explicit > default factory
    resolved_session_service = session_service or _default_session_service()

    # Resolve artifact service: explicit > default FileArtifactService
    if artifact_service is None:
        artifact_service = FileArtifactService(root_dir=_DEFAULT_ARTIFACT_ROOT)

    runner = Runner(
        app=rlm_app,
        session_service=resolved_session_service,
        artifact_service=artifact_service,
    )
    return runner


def _root_agent_model() -> str:
    """Resolve model used by ADK CLI-discoverable root_agent."""
    return os.getenv("RLM_ADK_MODEL", "gemini-3.1-pro-preview") #AGENT: DO NOT CHANGE WITHOUT ASKING USER


# ADK CLI entrypoint (`adk run rlm_adk`, `adk web`) discovers the ``app``
# symbol first (preferred) with plugins wired in.  The CLI creates its own
# ``Runner`` wrapping the ``App``.  ``root_agent`` is kept for backward
# compatibility with callers that import it directly.
app = create_rlm_app(model=_root_agent_model())
root_agent = app.root_agent
