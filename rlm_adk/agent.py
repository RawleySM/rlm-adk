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
should use ``create_rlm_runner()`` which returns a ``Runner``
with plugins, session service, and artifact service already wired.
"""

import logging
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.apps.app import App
from google.adk.artifacts import BaseArtifactService, FileArtifactService
from google.adk.planners import BuiltInPlanner
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import Runner
from google.adk.sessions.base_session_service import BaseSessionService
from google.genai import types
from google.genai.types import GenerateContentConfig, HttpOptions, HttpRetryOptions

from rlm_adk.callbacks.reasoning import reasoning_after_model, reasoning_before_model
from rlm_adk.dispatch import WorkerPool
from rlm_adk.orchestrator import RLMOrchestratorAgent
from rlm_adk.plugins.dashboard_auto_launch import DashboardAutoLaunchPlugin
from rlm_adk.plugins.dashboard_events import DashboardEventPlugin
from rlm_adk.plugins.langfuse_tracing import LangfuseTracingPlugin
from rlm_adk.plugins.observability import ObservabilityPlugin
from rlm_adk.plugins.step_mode import StepModePlugin
from rlm_adk.utils.prompts import (
    RLM_CHILD_STATIC_INSTRUCTION,
    RLM_DYNAMIC_INSTRUCTION,
    RLM_STATIC_INSTRUCTION,
)

logger = logging.getLogger(__name__)


def _is_litellm_active() -> bool:
    """Check if LiteLLM Router mode is enabled via RLM_ADK_LITELLM env var."""
    return os.getenv("RLM_ADK_LITELLM", "").lower() in ("1", "true", "yes")


def _resolve_model(model_str, tier=None):
    """Resolve model string to either plain str (Gemini) or LiteLlm (Router).

    When ``RLM_ADK_LITELLM`` is not active, returns *model_str* unchanged.
    When active, creates a ``LiteLlm`` object backed by the singleton Router.

    CRIT-1: If *model_str* is already a non-string (e.g. a ``LiteLlm`` object),
    it is returned as-is to prevent double-wrapping on recursive dispatch.
    """
    if not _is_litellm_active():
        return model_str
    if not isinstance(model_str, str):
        return model_str  # Already a LiteLlm object (CRIT-1)
    from rlm_adk.models.litellm_router import create_litellm_model

    logical_name = tier or os.getenv("RLM_LITELLM_TIER", "reasoning")
    return create_litellm_model(logical_name)


# Load project-root .env so model and API key env vars are available.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env", override=False)


def _project_root() -> Path:
    """Resolve the project root directory (contains pyproject.toml).

    Uses __file__ to anchor resolution, matching the .env pattern at line 54.
    Used only for repo-level paths (e.g. .env loading).
    """
    return Path(__file__).resolve().parents[1]


def _package_dir() -> Path:
    """Resolve the rlm_adk package directory (contains agent.py).

    This is the directory where ``adk run`` roots its ``.adk`` storage.
    Use this (not ``_project_root()``) as the anchor for all plugin and
    service file paths so that custom plugins write to the same ``.adk/``
    directory as ADK's built-in session and artifact services.
    """
    return Path(__file__).resolve().parent


_DEFAULT_RETRY_OPTIONS = HttpRetryOptions(
    attempts=3,
    initial_delay=1.0,
    max_delay=60.0,
    exp_base=2.0,
)

_DEFAULT_DB_PATH = str(_package_dir() / ".adk" / "session.db")
_DEFAULT_ARTIFACT_ROOT = str(_package_dir() / ".adk" / "artifacts")

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
    name: str = "reasoning_agent",
    output_key: str = "reasoning_output",
    include_contents: str = "default",
) -> LlmAgent:
    """Create the ReasoningAgent (main LLM for depth=0 reasoning).

    Args:
        model: The LLM model identifier.
        static_instruction: Stable system prompt content (code examples, REPL
            guidance).  Passed as LlmAgent ``static_instruction=``
            which ADK places into ``system_instruction`` *without* template
            processing, so raw curly braces in code examples are safe.
        dynamic_instruction: Template string with ``{var?}`` state-variable
            placeholders (repo_url, root_prompt, etc.).
            Passed as LlmAgent ``instruction=``; when ``static_instruction``
            is also set, ADK resolves the template and appends the result to
            ``contents`` as user content.  ADK 1.27 handles positioning
            natively via its request processors.
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

    Note:
        ``output_schema`` is intentionally NOT accepted here.  The orchestrator
        wires ``SetModelResponseTool(schema)`` at runtime alongside ``REPLTool``
        so the model chooses between ``execute_code`` and ``set_model_response``.
        Passing ``output_schema`` to ``LlmAgent`` would cause ADK to inject a
        duplicate ``set_model_response`` tool.
    """
    litellm_active = _is_litellm_active()

    planner = None
    if thinking_budget > 0 and not litellm_active:
        planner = BuiltInPlanner(
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=thinking_budget,
            )
        )

    gcc = _build_generate_content_config(retry_config) if not litellm_active else None

    resolved_model = _resolve_model(model) if litellm_active else model

    return LlmAgent(
        name=name,
        model=resolved_model,
        description="Main reasoning agent for RLM iteration loop",
        instruction=dynamic_instruction,
        static_instruction=static_instruction,
        # ADK manages tool call/response history. Tools are wired at
        # runtime by the orchestrator.
        include_contents=include_contents,
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        output_key=output_key,
        planner=planner,
        generate_content_config=gcc,
        before_model_callback=reasoning_before_model,
        after_model_callback=reasoning_after_model,
        tools=tools or [],
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
    instruction_router: Any = None,
    enabled_skills: Iterable[str] | None = None,
) -> RLMOrchestratorAgent:
    """Create the RLMOrchestratorAgent with the reasoning sub-agent."""
    resolved_enabled_skills = tuple(enabled_skills) if enabled_skills else ()
    reasoning = create_reasoning_agent(
        model,
        static_instruction=static_instruction,
        dynamic_instruction=dynamic_instruction,
        thinking_budget=thinking_budget,
        retry_config=retry_config,
    )

    # Default WorkerPool if none provided
    if worker_pool is None:
        if _is_litellm_active():
            from rlm_adk.models.litellm_router import create_litellm_model

            worker_tier = os.getenv("RLM_LITELLM_WORKER_TIER", "worker")
            worker_pool = WorkerPool(
                default_model=model,
                other_model=create_litellm_model(worker_tier),
            )
        else:
            worker_pool = WorkerPool(default_model=model)

    kwargs: dict[str, Any] = {
        "name": "rlm_orchestrator",
        "description": "RLM recursive iteration loop orchestrator",
        "reasoning_agent": reasoning,
        "root_prompt": root_prompt,
        "persistent": persistent,
        "worker_pool": worker_pool,
        "repl": repl,
        "enabled_skills": resolved_enabled_skills,
        "sub_agents": [reasoning],
    }
    if repo_url:
        kwargs["repo_url"] = repo_url
    if instruction_router is not None:
        kwargs["instruction_router"] = instruction_router

    return RLMOrchestratorAgent(**kwargs)


def create_child_orchestrator(
    model: "str | Any",
    depth: int,
    prompt: str,
    worker_pool: WorkerPool | None = None,
    thinking_budget: int = 512,
    output_schema: type | None = None,
    fanout_idx: int = 0,
    parent_fanout_idx: int | None = None,
    instruction_router: Any = None,
    enabled_skills: tuple[str, ...] = (),
    repo_url: str | None = None,
    parent_invocation_id: str | None = None,
    parent_tool_call_id: str | None = None,
    dispatch_call_index: int = 0,
) -> RLMOrchestratorAgent:
    """Create a child orchestrator for recursive dispatch at *depth* > 0.

    The child uses a condensed static instruction (no repomix/repo docs)
    and depth-suffixed output keys to prevent state collisions.

    Args:
        model: The LLM model identifier.
        depth: Nesting depth (must be > 0).
        prompt: The sub-query for this child to solve.
        worker_pool: Optional shared WorkerPool (created if None).
        thinking_budget: Token budget for built-in planner.
        output_schema: Optional Pydantic schema for structured output.
        fanout_idx: Fanout index within a batched dispatch (0 = single/first).
        enabled_skills: Skill names to propagate to child (default empty).
        repo_url: Optional repository URL for dynamic instruction template resolution.
    """
    reasoning = create_reasoning_agent(
        model,
        static_instruction=RLM_CHILD_STATIC_INSTRUCTION,
        thinking_budget=thinking_budget,
        name=f"child_reasoning_d{depth}f{fanout_idx}",
        output_key=f"reasoning_output@d{depth}f{fanout_idx}",
        # output_schema intentionally NOT set on LlmAgent — the orchestrator
        # injects SetModelResponseTool manually at runtime (orchestrator.py:303-305).
        # Setting it here too causes ADK's _OutputSchemaRequestProcessor to inject
        # a duplicate SetModelResponseTool on every LLM step (same root-agent
        # reasoning documented at orchestrator.py:297-302).
        include_contents="none",
    )

    if worker_pool is None:
        worker_pool = WorkerPool(default_model=model)

    return RLMOrchestratorAgent(
        name=f"child_orchestrator_d{depth}f{fanout_idx}",
        description=f"Child orchestrator at depth {depth} fanout {fanout_idx}",
        reasoning_agent=reasoning,
        root_prompt=prompt,
        persistent=False,
        worker_pool=worker_pool,
        depth=depth,
        fanout_idx=fanout_idx,
        output_schema=output_schema,
        instruction_router=instruction_router,
        enabled_skills=enabled_skills,
        repo_url=repo_url,
        parent_depth=depth - 1 if depth > 0 else None,
        parent_fanout_idx=parent_fanout_idx,
        parent_invocation_id=parent_invocation_id,
        parent_tool_call_id=parent_tool_call_id,
        dispatch_call_index=dispatch_call_index,
        sub_agents=[reasoning],
    )


def _default_plugins(
    *,
    langfuse: bool = False,
    sqlite_tracing: bool = True,
) -> list[BasePlugin]:
    """Build the default plugin list.

    ObservabilityPlugin is always included (observe-only, zero overhead on the
    happy path).  When ``RLM_ADK_DEBUG=1`` is set, verbose mode is enabled
    on ObservabilityPlugin (prints summary to stdout).

    LangfuseTracingPlugin is opt-in (default ``False``).  Enable via
    ``langfuse=True`` or ``RLM_ADK_LANGFUSE=1`` env var.

    SqliteTracingPlugin is opt-in by default (``sqlite_tracing=True``).
    Disable via ``sqlite_tracing=False``.  If the plugin module is not yet
    available (Track B), it is silently skipped.
    """
    _debug_env = os.getenv("RLM_ADK_DEBUG", "").lower() in ("1", "true", "yes")
    plugins: list[BasePlugin] = [
        DashboardAutoLaunchPlugin(),
        StepModePlugin(),
        ObservabilityPlugin(verbose=_debug_env),
    ]
    _sqlite_env = os.getenv("RLM_ADK_SQLITE_TRACING", "").lower() in ("1", "true", "yes")
    if sqlite_tracing or _sqlite_env:
        try:
            from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

            plugins.append(
                SqliteTracingPlugin(
                    db_path=str(_package_dir() / ".adk" / "traces.db"),
                )
            )
        except ImportError:
            logger.debug("SqliteTracingPlugin not available, skipping")
    # DashboardEventPlugin is always included (not env-gated) — it replaces
    # ContextWindowSnapshotPlugin as the primary event capture surface for
    # the interactive dashboard.
    _adk_dir = str(_package_dir() / ".adk")
    plugins.append(
        DashboardEventPlugin(
            output_path=f"{_adk_dir}/dashboard_events.jsonl",
        )
    )
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

    _cloud_env = os.getenv("RLM_ADK_CLOUD_OBS", "").lower() in ("1", "true", "yes")
    if _cloud_env:
        try:
            from rlm_adk.plugins.google_cloud_analytics import GoogleCloudAnalyticsPlugin
            from rlm_adk.plugins.google_cloud_tracing import GoogleCloudTracingPlugin

            plugins.append(GoogleCloudTracingPlugin())
            plugins.append(GoogleCloudAnalyticsPlugin())
        except ImportError:
            logger.debug("Google Cloud plugins not available, skipping")

    _snapshot_env = os.getenv("RLM_CONTEXT_SNAPSHOTS", "").lower() in ("1", "true", "yes")
    if _snapshot_env:
        from rlm_adk.plugins.context_snapshot import ContextWindowSnapshotPlugin

        _adk_dir = str(_package_dir() / ".adk")
        plugins.append(
            ContextWindowSnapshotPlugin(
                output_path=f"{_adk_dir}/context_snapshots.jsonl",
                output_capture_path=f"{_adk_dir}/model_outputs.jsonl",
            )
        )

    if _is_litellm_active():
        try:
            from rlm_adk.plugins.litellm_cost_tracking import LiteLLMCostTrackingPlugin

            plugins.append(LiteLLMCostTrackingPlugin())
        except ImportError:
            logger.debug("LiteLLMCostTrackingPlugin not available, skipping")

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
    thinking_budget: int = 1024,
    langfuse: bool = False,
    sqlite_tracing: bool = True,
    instruction_router: Any = None,
    enabled_skills: Iterable[str] | None = None,
    retry_config: dict[str, Any] | None = None,
) -> App:
    """Create the full RLM ADK App with plugins wired in.

    This is the recommended entry point for programmatic usage.  The returned
    ``App`` carries the ``ObservabilityPlugin`` (always).  Pass *plugins* to
    override the default plugin list entirely.

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
        instruction_router=instruction_router,
        enabled_skills=enabled_skills,
        retry_config=retry_config,
    )
    resolved_plugins = (
        plugins
        if plugins is not None
        else _default_plugins(
            langfuse=langfuse,
            sqlite_tracing=sqlite_tracing,
        )
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
    thinking_budget: int = 1024,
    artifact_service: BaseArtifactService | None = None,
    session_service: BaseSessionService | None = None,
    langfuse: bool = False,
    sqlite_tracing: bool = True,
    instruction_router: Any = None,
    enabled_skills: Iterable[str] | None = None,
    retry_config: dict[str, Any] | None = None,
) -> Runner:
    """Create the full RLM ADK Runner: App + plugins + services.

    This is the recommended entry point for programmatic usage.  The returned
    ``Runner`` has:

    - The ``App`` with ``ObservabilityPlugin`` (always).
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
        thinking_budget=thinking_budget,
        langfuse=langfuse,
        sqlite_tracing=sqlite_tracing,
        instruction_router=instruction_router,
        enabled_skills=enabled_skills,
        retry_config=retry_config,
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
    return os.getenv(
        "RLM_ADK_MODEL", "gemini-3.1-pro-preview"
    )  # AGENT: DO NOT CHANGE WITHOUT ASKING USER


# ADK CLI entrypoint (`adk run rlm_adk`, `adk web`) discovers the ``app``
# symbol first (preferred) with plugins wired in.  The CLI creates its own
# ``Runner`` wrapping the ``App``.  ``root_agent`` is kept for backward
# compatibility with callers that import it directly.
app = create_rlm_app(model=_root_agent_model())
root_agent = app.root_agent
