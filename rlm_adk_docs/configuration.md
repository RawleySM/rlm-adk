<!-- validated: 2026-03-09 -->

# Configuration Reference

Complete reference for RLM-ADK environment variables, agent factory functions, plugin wiring, model configuration, and project settings.

Source files: `rlm_adk/agent.py`, `rlm_adk/dispatch.py`, `rlm_adk/state.py`, `pyproject.toml`.

---

## 1. Environment variables

All env vars are read at import time or factory call time. A `.env` file at the project root is loaded via `python-dotenv` with `override=False` (existing vars take precedence).

### Model and API

| Variable | Default | Description |
|----------|---------|-------------|
| `RLM_ADK_MODEL` | `gemini-3.1-pro-preview` | Model identifier for the root agent and ADK CLI entrypoint |
| `RLM_REASONING_HTTP_TIMEOUT` | `300000` | HTTP timeout in milliseconds for Gemini API calls (5 min) |

### Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `RLM_MAX_DEPTH` | `3` | Maximum recursion depth for child orchestrators |
| `RLM_MAX_ITERATIONS` | `30` | Maximum REPL tool calls per depth level |
| `RLM_MAX_CONCURRENT_CHILDREN` | `3` | Concurrency limit for batched dispatch (semaphore) |
| `RLM_LLM_MAX_RETRIES` | `3` | Transient error retry count for child dispatch |
| `RLM_LLM_RETRY_DELAY` | `5.0` | Base retry delay in seconds for transient errors |

### Plugins

| Variable | Default | Description |
|----------|---------|-------------|
| `RLM_ADK_DEBUG` | off | Enable verbose logging on ObservabilityPlugin (`1`/`true`/`yes`) |
| `RLM_ADK_SQLITE_TRACING` | off | Enable SqliteTracingPlugin via env var (`1`/`true`/`yes`). Also enabled by `sqlite_tracing=True` kwarg (default). |
| `RLM_ADK_LANGFUSE` | off | Enable LangfuseTracingPlugin (`1`/`true`/`yes`) |
| `RLM_REPL_TRACE` | `0` | REPL tracing level: `0`=off, `1`=timing+snapshots+dataflow, `2`=+tracemalloc memory |
| `RLM_ADK_CLOUD_OBS` | off | Enable Google Cloud tracing and analytics plugins (`1`/`true`/`yes`) |
| `RLM_CONTEXT_SNAPSHOTS` | off | Enable ContextWindowSnapshotPlugin (`1`/`true`/`yes`) |

### Tracing (Langfuse)

| Variable | Default | Description |
|----------|---------|-------------|
| `LANGFUSE_PUBLIC_KEY` | -- | Langfuse project public key (required for Langfuse plugin) |
| `LANGFUSE_SECRET_KEY` | -- | Langfuse project secret key (required for Langfuse plugin) |
| `LANGFUSE_BASE_URL` | -- | Langfuse server URL (e.g. `http://localhost:3100`) |

### Session and storage

| Variable | Default | Description |
|----------|---------|-------------|
| `RLM_SESSION_DB` | `.adk/session.db` | Path to SQLite session database |

---

## 2. Agent factory functions

All factories are in `rlm_adk/agent.py`. The call hierarchy is: `create_rlm_runner` > `create_rlm_app` > `create_rlm_orchestrator` > `create_reasoning_agent`.

| Function | Returns | Description |
|----------|---------|-------------|
| `create_rlm_runner(model, ...)` | `Runner` | Full entry point: App + plugins + session service + artifact service. Recommended for programmatic usage. |
| `create_rlm_app(model, ...)` | `App` | App with root orchestrator and plugins. Used by ADK CLI via module-level `app` symbol. |
| `create_rlm_orchestrator(model, ...)` | `RLMOrchestratorAgent` | Orchestrator wrapping a reasoning agent with WorkerPool and REPL. |
| `create_child_orchestrator(model, depth, prompt, ...)` | `RLMOrchestratorAgent` | Child orchestrator for recursive dispatch at depth > 0. Uses condensed static instruction, no repomix. |
| `create_reasoning_agent(model, ...)` | `LlmAgent` | Configures the core LLM agent with instructions, planner, callbacks, and retry config. |

### create_rlm_runner

```python
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
) -> Runner
```

Resolves services: `session_service` defaults to `_default_session_service()` (SqliteSessionService with WAL). `artifact_service` defaults to `FileArtifactService(root_dir=".adk/artifacts")`.

### create_child_orchestrator

```python
def create_child_orchestrator(
    model: str,
    depth: int,
    prompt: str,
    worker_pool: WorkerPool | None = None,
    max_iterations: int = 10,
    thinking_budget: int = 512,
    output_schema: type | None = None,
) -> RLMOrchestratorAgent
```

Called by dispatch closures. Uses `RLM_CHILD_STATIC_INSTRUCTION` (no repomix/repo docs). Depth-suffixed names: `child_orchestrator_d{depth}`, `reasoning_output@d{depth}`. Lower thinking budget (512 vs 1024) for cost control.

---

## 3. Plugin wiring

`_default_plugins()` in `rlm_adk/agent.py` builds the plugin list. Plugins are observe-only and non-blocking.

### Always-on

| Plugin | Condition | Notes |
|--------|-----------|-------|
| `ObservabilityPlugin` | Always included | `verbose=True` when `RLM_ADK_DEBUG=1` |

### On by default

| Plugin | Condition | Notes |
|--------|-----------|-------|
| `SqliteTracingPlugin` | `sqlite_tracing=True` (default) or `RLM_ADK_SQLITE_TRACING=1` | Writes to `.adk/traces.db` |

### Opt-in

| Plugin | Condition | Notes |
|--------|-----------|-------|
| `LangfuseTracingPlugin` | `langfuse=True` or `RLM_ADK_LANGFUSE=1` | Requires Langfuse env vars |
| `REPLTracingPlugin` | `RLM_REPL_TRACE >= 1` | Saves `repl_traces.json` artifact at run end |
| `GoogleCloudTracingPlugin` | `RLM_ADK_CLOUD_OBS=1` | Silently skipped if import fails |
| `GoogleCloudAnalyticsPlugin` | `RLM_ADK_CLOUD_OBS=1` | Silently skipped if import fails |
| `ContextWindowSnapshotPlugin` | `RLM_CONTEXT_SNAPSHOTS=1` | Writes `.adk/context_snapshots.jsonl` and `.adk/model_outputs.jsonl` |

When `plugins=` is passed explicitly to `create_rlm_app()` or `create_rlm_runner()`, it overrides the default list entirely.

---

## 4. Model configuration

### Root agent model

`_root_agent_model()` resolves the model for the module-level `app` and `root_agent` symbols:

```python
os.getenv("RLM_ADK_MODEL", "gemini-3.1-pro-preview")
```

### Per-agent override

Every factory function accepts a `model` parameter. Child orchestrators inherit the model from the dispatch closure (typically the same model as the parent).

### HTTP retry options

Default retry configuration (`_DEFAULT_RETRY_OPTIONS`):

| Parameter | Value |
|-----------|-------|
| `attempts` | 3 |
| `initial_delay` | 1.0 s |
| `max_delay` | 60.0 s |
| `exp_base` | 2.0 |

Applied via `_build_generate_content_config(retry_config)` which produces a `GenerateContentConfig` with `HttpOptions`. The HTTP timeout is controlled by `RLM_REASONING_HTTP_TIMEOUT` (default 300000 ms).

Pass `retry_config=None` (default) for the above defaults. Pass `retry_config={}` to use the SDK's built-in defaults only.

---

## 5. pyproject.toml settings

### Project metadata

| Field | Value |
|-------|-------|
| Name | `rlms` |
| Version | `0.1.0` |
| Python | `>=3.12` |
| License | MIT |

### Key dependencies

| Package | Minimum version | Role |
|---------|-----------------|------|
| `google-adk` | `>=1.2.0` | Agent Development Kit framework |
| `google-genai` | `>=1.56.0` | Gemini API client |
| `langfuse` | `>=3.14.0` | LLM tracing (opt-in) |
| `openinference-instrumentation-google-adk` | `>=0.1.9` | OTel auto-instrumentation for Langfuse |
| `python-dotenv` | `>=1.2.1` | `.env` file loading |
| `repomix` | `>=0.5.0` | Repository context skill |
| `rich` | `>=13.0.0` | Terminal formatting |

### Optional dependency groups

| Group | Packages | Purpose |
|-------|----------|---------|
| `dashboard` | nicegui | Streamlit-based observability dashboard |
| `modal` | modal, dill | Modal cloud sandbox |
| `e2b` | e2b-code-interpreter, dill | E2B sandbox |
| `daytona` | daytona, dill | Daytona sandbox |
| `prime` | prime-sandboxes, dill | Prime sandbox |

### Test configuration (`[tool.pytest.ini_options]`)

| Setting | Value | Effect |
|---------|-------|--------|
| `testpaths` | `["tests", "tests_rlm_adk"]` | Directories pytest scans |
| `asyncio_mode` | `auto` | Auto-detect async test functions and fixtures |
| `addopts` | `-m "provider_fake_contract and not agent_challenge"` | Default marker filter: runs ~28 provider-fake contract tests |

Override the default marker filter with `-m ""` to run the full ~970 test suite.

### Custom markers

| Marker | Description |
|--------|-------------|
| `provider_fake` | E2e tests against provider-fake replay fixtures (no network) |
| `provider_fake_contract` | Default provider-fake fixture-contract suite |
| `provider_fake_extended` | Non-default provider-fake coverage |
| `agent_challenge` | Tests depending on `agent_challenge/` fixtures |
| `unit_nondefault` | Non-default tests excluded from the provider-fake default run |

### Ruff configuration

| Setting | Value |
|---------|-------|
| `line-length` | 100 |
| `target-version` | `py312` |
| Lint rules | E, W, F, I, B, UP |
| Ignored | E501 (line length, handled by formatter) |
| Quote style | double |

### Default file paths

| Path | Purpose |
|------|---------|
| `.adk/session.db` | Session state persistence (SqliteSessionService) |
| `.adk/artifacts/` | Artifact storage root (FileArtifactService) |
| `.adk/traces.db` | Observability traces (SqliteTracingPlugin) |
| `.adk/context_snapshots.jsonl` | Context window snapshots (ContextWindowSnapshotPlugin) |
| `.adk/model_outputs.jsonl` | Model output captures (ContextWindowSnapshotPlugin) |

---

## ADK Gotchas

### include_contents='default' is required

The reasoning agent must be created with `include_contents="default"`. This tells ADK to manage tool call/response history automatically. Without it, the reasoning agent would not see previous `execute_code` calls and their results in its context window, breaking multi-turn REPL interaction. Omitting it or setting it to `None` silently drops tool history from the prompt.

### ADK coupling risk table

| Dependency | Location | Risk |
|-----------|----------|------|
| `model_post_init` setting `parent_agent` | `dispatch.py` worker reuse | Behavior change breaks worker pool |
| `include_contents="default"` semantics | `agent.py` | ADK could change how tool history is included |
| Plugin callback wiring in `base_llm_flow.py` | `observability.py` | Ephemeral state workaround depends on current wiring gaps |

### State mutation (AR-CRIT-001)

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. The write appears to succeed at runtime but the Runner never sees it, so it is never persisted and does not appear in the event stream. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

---

## Recent Changes

> Append entries here when modifying source files documented by this branch. A stop hook (`ai_docs/scripts/check_doc_staleness.py`) will remind you.

- **2026-03-09 13:00** — Initial branch doc created from codebase exploration.
- **2026-03-09 13:15** — `agent.py`: Added `fanout_idx: int = 0` parameter to `create_child_orchestrator()` for artifact filename disambiguation.

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
