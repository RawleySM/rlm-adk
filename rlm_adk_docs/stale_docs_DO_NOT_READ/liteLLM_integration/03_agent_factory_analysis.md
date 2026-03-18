<!-- validated: 2026-03-09 -->

# Agent Factory Analysis for LiteLLM Integration

Deep analysis of the agent factory chain, orchestrator setup, and model configuration
flow in RLM-ADK. Written to inform LiteLLM provider integration work.

Source files: `rlm_adk/agent.py`, `rlm_adk/orchestrator.py`, `rlm_adk/dispatch.py`,
`rlm_adk/state.py`, `rlm_adk_docs/configuration.md`, `pyproject.toml`.

---

## 1. Factory Chain Diagram

```
CLI entry: `adk run rlm_adk`
    |
    v
rlm_adk/agent.py  (module level, evaluated at import)
    app = create_rlm_app(model=_root_agent_model())
    root_agent = app.root_agent

_root_agent_model()
    └── os.getenv("RLM_ADK_MODEL", "gemini-3.1-pro-preview")

create_rlm_runner(model, ...)               [programmatic callers]
    └── create_rlm_app(model, ...)
            └── create_rlm_orchestrator(model, ...)
                    ├── create_reasoning_agent(model, ...)
                    │       └── LlmAgent(name="reasoning_agent", model=model, ...)
                    └── WorkerPool(default_model=model)   [alias for DispatchConfig]

create_child_orchestrator(model, depth, prompt, ...)   [called by dispatch closures]
    ├── create_reasoning_agent(model, ..., name=f"child_reasoning_d{depth}", ...)
    │       └── LlmAgent(name=..., model=model, ...)
    └── WorkerPool(default_model=model)
```

The model string travels as a plain Python `str` parameter through every layer.
No coercion, wrapping, or validation occurs before it reaches `LlmAgent(model=...)`.

---

## 2. Model Configuration Flow

### 2.1 Root agent (CLI / module-level `app`)

`agent.py:544`
```python
def _root_agent_model() -> str:
    return os.getenv("RLM_ADK_MODEL", "gemini-3.1-pro-preview")

app = create_rlm_app(model=_root_agent_model())   # line 551
```

This runs once at import time when `adk run rlm_adk` imports the module.
The model string is frozen at that point.

### 2.2 `create_reasoning_agent` — the only place `LlmAgent` is instantiated

`agent.py:212-230`

```python
return LlmAgent(
    name=name,
    model=model,            # <-- plain str or LiteLlm() object
    description="...",
    instruction=dynamic_instruction,
    static_instruction=static_instruction,
    include_contents="default",
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    output_key=output_key,
    planner=planner,
    generate_content_config=gcc,   # <-- HttpRetryOptions lives here
    before_model_callback=reasoning_before_model,
    after_model_callback=reasoning_after_model,
    tools=tools or [],
    output_schema=output_schema,
)
```

`LlmAgent.model` accepts either a `str` (native Gemini model ID) or a `LiteLlm`
object. ADK resolves the model type at request time. This is the primary
integration point for LiteLLM.

### 2.3 `generate_content_config` and its scope

`agent.py:123-148`

```python
def _build_generate_content_config(retry_config) -> GenerateContentConfig | None:
    return GenerateContentConfig(
        http_options=HttpOptions(
            timeout=int(os.getenv("RLM_REASONING_HTTP_TIMEOUT", "300000")),
            retry_options=retry_opts,   # HttpRetryOptions
        ),
    )
```

`GenerateContentConfig` is a `google-genai` type. It is **Gemini-specific**.
When a `LiteLlm` model is used, ADK routes the request through the LiteLLM
layer instead of `google.genai`, and `GenerateContentConfig` is silently
ignored (LiteLLM does not consume it). Timeout and retry must be configured
via LiteLLM-native mechanisms (e.g., `timeout=`, `num_retries=` on the
`LiteLlm()` constructor, or provider-level env vars).

This is a **gap** that must be addressed in the integration plan.

### 2.4 WorkerPool / DispatchConfig — the child model path

`dispatch.py:83-103`

```python
class DispatchConfig:
    def __init__(self, default_model: str, other_model: str | None = None, pool_size: int = 5):
        self.default_model = default_model
        self.other_model = other_model or default_model

WorkerPool = DispatchConfig   # backward-compatible alias
```

`create_dispatch_closures` reads `dispatch_config.other_model` (line 321) as
`target_model` for each child:

```python
target_model = model or dispatch_config.other_model
```

`create_child_orchestrator` is then called with `model=target_model`
(`dispatch.py:344`), which flows through `create_reasoning_agent` and into
`LlmAgent(model=target_model)`.

**Implication**: The `WorkerPool(default_model=...)` constructor call at
`agent.py:256` is where the child model is set. For LiteLLM, this would
be the `LiteLlm` object (or its string representation).

### 2.5 Tools wired at runtime, not at factory time

`orchestrator.py:294`

```python
object.__setattr__(self.reasoning_agent, 'tools', [repl_tool, set_model_response_tool])
```

Tools are injected via `object.__setattr__` at the start of each
`_run_async_impl` call, and cleared in the `finally` block (line 481).
The model parameter is not touched here — it is stable from factory time.

---

## 3. Environment Variable Catalog

### Model and API

| Variable | Default | Set In | Description |
|----------|---------|--------|-------------|
| `RLM_ADK_MODEL` | `gemini-3.1-pro-preview` | `agent.py:544` | Root agent model; read once at import time |
| `RLM_REASONING_HTTP_TIMEOUT` | `300000` (ms) | `agent.py:145` | HTTP timeout for `HttpOptions` (Gemini only) |

### Retry and Limits

| Variable | Default | Set In | Description |
|----------|---------|--------|-------------|
| `RLM_MAX_ITERATIONS` | `30` | `orchestrator.py:224` | Max REPL tool calls per depth level |
| `RLM_MAX_DEPTH` | `3` | `dispatch.py:131` | Max recursion depth for child orchestrators |
| `RLM_MAX_CONCURRENT_CHILDREN` | `3` | `dispatch.py:132` | Semaphore limit for parallel child dispatch |
| `RLM_LLM_MAX_RETRIES` | `3` | `orchestrator.py:339` | Retry count for transient orchestrator errors |
| `RLM_LLM_RETRY_DELAY` | `5.0` | `orchestrator.py:340` | Base retry delay in seconds |

### Plugins

| Variable | Default | Set In | Description |
|----------|---------|--------|-------------|
| `RLM_ADK_DEBUG` | off | `agent.py:344` | Enable verbose mode on ObservabilityPlugin |
| `RLM_ADK_SQLITE_TRACING` | off | `agent.py:346` | Enable SqliteTracingPlugin |
| `RLM_ADK_LANGFUSE` | off | `agent.py:355` | Enable LangfuseTracingPlugin |
| `RLM_REPL_TRACE` | `0` | `agent.py:358` | REPL tracing level (0/1/2) |
| `RLM_ADK_CLOUD_OBS` | off | `agent.py:366` | Enable Google Cloud plugins |
| `RLM_CONTEXT_SNAPSHOTS` | off | `agent.py:376` | Enable ContextWindowSnapshotPlugin |

### LiteLLM-relevant (currently absent, would need to be added)

| Variable | Suggested Default | Description |
|----------|------------------|-------------|
| `RLM_LITELLM_TIMEOUT` | `300` (s) | Timeout for LiteLLM requests |
| `RLM_LITELLM_NUM_RETRIES` | `3` | LiteLLM-native retry count |
| `RLM_LITELLM_FALLBACKS` | -- | Comma-separated fallback model list |
| `RLM_WORKER_MODEL` | (same as root) | Model string for child/worker orchestrators |

---

## 4. Dependency Versions (from `pyproject.toml`)

| Package | Minimum Version | Role |
|---------|----------------|------|
| `google-adk` | `>=1.2.0` | Agent Development Kit |
| `google-genai` | `>=1.56.0` | Gemini API client |
| `anthropic` | `>=0.75.0` | Anthropic SDK (present but not yet wired) |
| `openai` | `>=2.14.0` | OpenAI SDK (present but not yet wired) |
| `portkey-ai` | `>=2.1.0` | Portkey gateway SDK (present but not yet wired) |
| `langfuse` | `>=3.14.0` | Tracing (opt-in) |
| `python-dotenv` | `>=1.2.1` | `.env` loading |

Note: `litellm` package itself is **not** listed in `pyproject.toml` yet.

---

## 5. Plugin Wiring Architecture

`_default_plugins()` in `agent.py:326-384` builds the plugin list:
1. Check an env var or boolean parameter
2. Attempt import (with `ImportError` guard)
3. Instantiate and append to `plugins` list
4. Return list; passed to `App(plugins=resolved_plugins)`

A LiteLLM plugin would follow the same pattern: new file in `rlm_adk/plugins/`,
implement `BasePlugin`, add instantiation block in `_default_plugins()`.

---

## 6. Critical Integration Points

### 6.1 Primary: `LlmAgent(model=...)` at `agent.py:212`
ADK already accepts `LiteLlm` objects natively — zero-friction entry point.

### 6.2 `generate_content_config` must be conditionally suppressed
`_build_generate_content_config` at `agent.py:123` — Gemini-specific; silently ignored by LiteLLM but retry/timeout must be configured via LiteLLM-native mechanisms.

### 6.3 `BuiltInPlanner` / `ThinkingConfig` must be gated
`agent.py:196-202` — Gemini-only feature, must skip for non-Gemini models.

### 6.4 Error classification needs LiteLLM branches
- `is_transient_error` at `orchestrator.py:69-85` — checks `google.genai` errors
- `_classify_error` at `callbacks/worker.py:32-58` — checks `.code` attribute
- LiteLLM uses `litellm.exceptions.*` with `.status_code` not `.code`

### 6.5 Worker model routing
`WorkerPool(default_model=...)` at `agent.py:256` should accept separate `worker_model` for multi-provider scenarios.

### 6.6 `RLM_ADK_MODEL` env var format
No code change needed — LiteLLM format is `provider/model-name` (e.g., `openai/gpt-4o`). String passes through unchanged; only `LlmAgent` construction needs to wrap in `LiteLlm()`.

---

## 7. Full Factory Call Chain

```
$ adk run rlm_adk
  → import rlm_adk.agent
    → load_dotenv(".env")
    → _root_agent_model() → os.getenv("RLM_ADK_MODEL", "gemini-3.1-pro-preview")
    → create_rlm_app(model=...)
      → create_rlm_orchestrator(model=...)
        → create_reasoning_agent(model=...)
          → _build_generate_content_config(...)
          → BuiltInPlanner(ThinkingConfig(...))
          → LlmAgent(model=model, planner=..., generate_content_config=..., ...)
        → WorkerPool(default_model=model)
        → RLMOrchestratorAgent(reasoning_agent=..., worker_pool=..., ...)
      → _default_plugins()
      → App(root_agent=orchestrator, plugins=[...])
  → ADK CLI creates Runner → Runner.run_async()
    → RLMOrchestratorAgent._run_async_impl(ctx)
      → create_dispatch_closures(worker_pool, ctx, ...)
      → REPLTool(repl, ...)
      → reasoning_agent.run_async(ctx)
        → LLM call → tool calls → REPLTool → llm_query_async() → child orchestrator
```
