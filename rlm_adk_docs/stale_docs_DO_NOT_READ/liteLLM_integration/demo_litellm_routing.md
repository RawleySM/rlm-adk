<!-- validated: 2026-03-09 -->

# Demo: LiteLLM Multi-Provider Routing

## 1. Overview

The LiteLLM integration adds multi-provider model routing to RLM-ADK. When
enabled via `RLM_ADK_LITELLM=1`, all LLM calls (reasoning agent, worker
dispatch, batched queries) are routed through a `litellm.Router` instead of
the default Gemini-only path.

**Why**: The primary motivation is 429 (rate-limit) mitigation for the async
worker dispatch path. When `llm_query_batched` fires N concurrent queries,
a single provider's RPM/TPM limits are quickly exhausted. The Router
distributes load across Gemini, OpenAI, DeepSeek, Groq, DashScope, and
MiniMax, with automatic fallback and cooldown when any deployment returns
429 or 5xx.

**What was built** (Phases 1-5, 66 tests):
- `RouterLiteLlmClient` -- drop-in `LiteLLMClient` subclass backed by `litellm.Router`
- Feature-gated factory integration (`_is_litellm_active`, `_resolve_model`)
- Error handling for LiteLLM exception types in both orchestrator and worker paths
- Dispatch integration with worker-tier model resolution
- Cost tracking plugin (`obs:litellm_total_cost`)

---

## 2. Architecture

```
RLM_ADK_LITELLM=1
  |
  v
agent.py: _is_litellm_active() == True
  |
  v
agent.py: _resolve_model("gemini-2.5-pro", tier="reasoning")
  |
  v
litellm_router.py: create_litellm_model("reasoning")
  |
  v
LiteLlm(model="reasoning", llm_client=RouterLiteLlmClient)
  |
  v
ADK LlmAgent uses LiteLlm.generate_content_async()
  |  (ADK handles all request/response conversion, tool calls, streaming)
  v
RouterLiteLlmClient.acompletion(model="reasoning", messages=..., tools=...)
  |
  v
litellm.Router.acompletion()
  |
  +---> gemini/gemini-2.5-pro    (RPM: 10, TPM: 4M)
  +---> openai/o3                (RPM: 30, TPM: 1M)
  +---> deepseek/deepseek-reasoner (RPM: 20)
  |
  v
Automatic: fallback on 429/5xx, cooldown, retry, shuffle across deployments
```

Worker dispatch follows the same path but resolves to the `"worker"` tier:

```
dispatch.py: WorkerPool(other_model=create_litellm_model("worker"))
  |
  v
litellm.Router selects from worker-tier deployments:
  +---> gemini/gemini-2.5-flash  (RPM: 100, TPM: 4M)
  +---> openai/gpt-4o-mini       (RPM: 100, TPM: 1M)
  +---> deepseek/deepseek-chat   (RPM: 60)
  +---> groq/llama-3.3-70b-versatile (RPM: 30)
  +---> dashscope/qwen-plus      (RPM: 60)
  +---> minimax/MiniMax-M2.5     (RPM: 30)
```

Key design choice: `RouterLiteLlmClient` inherits from ADK's `LiteLLMClient`
and overrides only `acompletion()` / `completion()`. All request/response
conversion, tool handling, and streaming are handled by ADK's existing
`LiteLlm.generate_content_async()` -- zero custom conversion code.

---

## 3. Setup Instructions

### Install Dependencies

```bash
uv sync --extra litellm
```

This installs `litellm>=1.50.0` as an optional dependency. When the extra
is not installed, the feature flag is a no-op and all code paths fall back
to the default Gemini client.

### Configure Environment

Add `RLM_ADK_LITELLM=1` and provider API keys to `rlm_adk/.env`:

```bash
# Master feature flag
RLM_ADK_LITELLM=1

# Provider API keys (set at least one)
GEMINI_API_KEY=...
OPENAI_API_KEY=...
DEEPSEEK_API_KEY=...
GROQ_API_KEY=...
DASHSCOPE_API_KEY=...
MINIMAX_API_KEY=...
PERPLEXITY_API_KEY=...
```

Only providers with a valid API key in the environment are included in the
Router's model list. Missing keys are silently skipped. If **no** keys are
set, `_get_or_create_client()` raises `RuntimeError` with a clear message
listing all supported key names.

### Validate Keys (Phase 6 -- Not Yet Implemented)

```bash
# Planned: .venv/bin/python scripts/validate_litellm_keys.py
# This script is part of Phase 6 (Testing) and has not been created yet.
```

---

## 4. Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RLM_ADK_LITELLM` | unset (off) | Master feature flag. Set to `1`, `true`, or `yes` to enable. |
| `RLM_LITELLM_TIER` | `"reasoning"` | Default logical tier for the root reasoning agent. |
| `RLM_LITELLM_WORKER_TIER` | `"worker"` | Logical tier for child/worker dispatch models. |
| `RLM_LITELLM_ROUTING_STRATEGY` | `"simple-shuffle"` | Router strategy (`simple-shuffle`, `least-busy`, `latency-based-routing`, `usage-based-routing`). |
| `RLM_LITELLM_NUM_RETRIES` | `2` | Per-deployment retry count before fallback. |
| `RLM_LITELLM_COOLDOWN_TIME` | `60` | Seconds a deployment is cooled down after failure. |
| `RLM_LITELLM_TIMEOUT` | unset (no timeout) | Request timeout in seconds. When unset, no explicit timeout is passed to the Router. |

All Router configuration env vars are read once at singleton creation time
(`_get_or_create_client` in `litellm_router.py:200-205`).

---

## 5. Provider Configuration

The Router model list is built by `build_model_list()` in
`rlm_adk/models/litellm_router.py:140-164`. Each provider is gated by
its API key env var:

### Reasoning Tier (`model_name: "reasoning"`)

| Provider | Model | API Key Env Var | Rate Limits |
|----------|-------|-----------------|-------------|
| Gemini | `gemini/gemini-2.5-pro` | `GEMINI_API_KEY` | RPM: 10, TPM: 4M |
| OpenAI | `openai/o3` | `OPENAI_API_KEY` | RPM: 30, TPM: 1M |
| DeepSeek | `deepseek/deepseek-reasoner` | `DEEPSEEK_API_KEY` | RPM: 20 |

### Worker Tier (`model_name: "worker"`)

| Provider | Model | API Key Env Var | Rate Limits |
|----------|-------|-----------------|-------------|
| Gemini | `gemini/gemini-2.5-flash` | `GEMINI_API_KEY` | RPM: 100, TPM: 4M |
| OpenAI | `openai/gpt-4o-mini` | `OPENAI_API_KEY` | RPM: 100, TPM: 1M |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` | RPM: 60 |
| Groq | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` | RPM: 30 |
| DashScope | `dashscope/qwen-plus` | `DASHSCOPE_API_KEY` | RPM: 60 |
| MiniMax | `minimax/MiniMax-M2.5` | `MINIMAX_API_KEY` | RPM: 30 |

### Search Tier (`model_name: "search"`)

| Provider | Model | API Key Env Var | Rate Limits |
|----------|-------|-----------------|-------------|
| Perplexity | `perplexity/sonar-pro` | `PERPLEXITY_API_KEY` | RPM: 30 |

The Router uses `simple-shuffle` (default) to distribute requests across all
deployments within a tier. When a deployment fails or hits a rate limit, it
enters a 60-second cooldown and the Router automatically selects the next
available deployment.

---

## 6. Running the Agent

### Basic Run

```bash
RLM_ADK_LITELLM=1 .venv/bin/adk run rlm_adk
```

When the Router is created, it logs the number of deployments and the
routing strategy:

```
INFO:rlm_adk.models.litellm_router:LiteLLM Router created: 12 deployments, strategy=simple-shuffle
```

### With Specific Provider Keys Only

To test with a single provider (e.g., OpenAI only):

```bash
RLM_ADK_LITELLM=1 OPENAI_API_KEY=sk-... .venv/bin/adk run rlm_adk
```

### Gemini-Only Fallback (Feature Flag Off)

```bash
# Omit RLM_ADK_LITELLM or set to 0 -- completely unchanged behavior
.venv/bin/adk run rlm_adk
```

---

## 7. How 429 Recovery Works

The `litellm.Router` provides three layers of resilience:

### Layer 1: Per-Deployment Retry

Each deployment gets `num_retries` attempts (default: 2) before being marked
as failed. This handles transient network blips.

### Layer 2: Cooldown + Fallback

After `allowed_fails` failures (default: 1), a deployment enters cooldown
for `cooldown_time` seconds (default: 60). The Router immediately selects
another deployment within the same tier.

Example scenario with `llm_query_batched` firing 8 concurrent worker queries:
```
Worker 1-3 -> gemini/gemini-2.5-flash (succeeds)
Worker 4   -> gemini/gemini-2.5-flash (429) -> retry -> (429) -> cooldown
Worker 5-6 -> openai/gpt-4o-mini (succeeds, gemini now in cooldown)
Worker 7   -> deepseek/deepseek-chat (succeeds)
Worker 8   -> groq/llama-3.3-70b-versatile (succeeds)
```

### Layer 3: Orchestrator-Level Retry

If the Router itself raises an exception (all deployments exhausted),
`RLMOrchestratorAgent._run_async_impl` catches it via `is_transient_error()`
(lines 86-98 of `orchestrator.py`) and retries with exponential backoff
(default: 3 retries, 5s base delay).

LiteLLM exception handling (`orchestrator.py:86-98`, `callbacks/worker.py:32-71`):

| Exception | `is_transient_error` | `_classify_error` |
|-----------|---------------------|-------------------|
| `litellm.RateLimitError` | `True` | `"RATE_LIMIT"` |
| `litellm.InternalServerError` | `True` | `"SERVER"` |
| `litellm.Timeout` | `True` | `"TIMEOUT"` |
| `litellm.ServiceUnavailableError` | `True` | `"SERVER"` |
| `litellm.AuthenticationError` | `False` | `"AUTH"` |
| `litellm.BadRequestError` | `False` | `"CLIENT"` |

The `_classify_error` function uses `status_code` (int) as the canonical
HTTP status attribute for LiteLLM exceptions, since LiteLLM's `.code`
attribute is either a string or `None` depending on the exception type.

---

## 8. Cost Tracking

The `LiteLLMCostTrackingPlugin` (`rlm_adk/plugins/litellm_cost_tracking.py`)
tracks per-call and cumulative costs using `litellm.completion_cost()`.

**State keys written:**
- `obs:litellm_last_call_cost` -- cost of the most recent model call (USD, 6 decimal places)
- `obs:litellm_total_cost` -- running cumulative total (USD, 6 decimal places)

**Automatic registration:** The plugin is added to `_default_plugins()` in
`agent.py:423-428` when `_is_litellm_active()` returns `True`. No manual
configuration needed.

### MED-2 Limitation: Partial Cost Coverage

The plugin only tracks costs for the **root reasoning agent's** model calls.
Child orchestrator costs (from `llm_query` / `llm_query_batched`) are NOT
tracked because ADK gives child agents isolated invocation contexts that do
not fire plugin callbacks.

**Workaround for complete cost tracking:** Configure `litellm.success_callback`
at the Router level. This hooks into every LiteLLM completion call regardless
of which ADK agent initiated it, providing global cost visibility.

---

## 9. Test Suite

All tests use the `unit_nondefault` marker and are excluded from the default
`pytest` run. Run with `-m ""` to include them.

### Unit Tests (No API Keys Required)

| File | Tests | Coverage |
|------|-------|----------|
| `tests_rlm_adk/test_litellm_foundation.py` | 16 | RouterLiteLlmClient, build_model_list, singleton, env var config |
| `tests_rlm_adk/test_litellm_errors.py` | 19 | _classify_error, is_transient_error for LiteLLM + Gemini exceptions |
| `tests_rlm_adk/test_litellm_factory.py` | 22 | _is_litellm_active, _resolve_model, planner/gcc gating, dispatch config, worker tier |
| `tests_rlm_adk/test_litellm_cost_tracking.py` | 9 | Cost accumulation, graceful failure, plugin registration |
| **Total** | **66** | |

```bash
# Run all LiteLLM unit tests
.venv/bin/python -m pytest \
  tests_rlm_adk/test_litellm_foundation.py \
  tests_rlm_adk/test_litellm_errors.py \
  tests_rlm_adk/test_litellm_factory.py \
  tests_rlm_adk/test_litellm_cost_tracking.py \
  -m "" -v
```

### Live Integration Tests (Phase 6 -- Not Yet Implemented)

```bash
# Planned: requires valid API keys + RLM_ADK_LITELLM=1
# RLM_ADK_LITELLM=1 .venv/bin/python -m pytest tests_rlm_adk/test_litellm_live.py -m "" -v
```

Phase 6 (Testing) will add:
- `scripts/validate_litellm_keys.py` -- pre-flight API key validation
- `tests_rlm_adk/test_litellm_live.py` -- live single-query and batched multi-provider tests

### Default Suite Impact

None. The default `pytest` run (`addopts = -m "provider_fake_contract and not agent_challenge"`)
completely excludes `unit_nondefault`-marked tests. Zero regressions across all phases.

---

## 10. Files Created/Modified

### Files Created

| File | Lines | Phase | Purpose |
|------|-------|-------|---------|
| `rlm_adk/models/__init__.py` | 0 | 1 | Package marker |
| `rlm_adk/models/litellm_router.py` | 242 | 1 | `RouterLiteLlmClient`, `build_model_list`, `_get_or_create_client`, `create_litellm_model` |
| `rlm_adk/plugins/litellm_cost_tracking.py` | 72 | 5 | `LiteLLMCostTrackingPlugin(BasePlugin)` |
| `tests_rlm_adk/test_litellm_foundation.py` | 257 | 1 | 16 foundation tests |
| `tests_rlm_adk/test_litellm_errors.py` | 179 | 3 | 19 error handling tests |
| `tests_rlm_adk/test_litellm_factory.py` | 295 | 2+4 | 22 factory + dispatch tests |
| `tests_rlm_adk/test_litellm_cost_tracking.py` | 204 | 5 | 9 cost tracking tests |

### Files Modified

| File | Lines | Phase | Change |
|------|-------|-------|--------|
| `rlm_adk/agent.py` | 598 | 2,4,5 | `_is_litellm_active()`, `_resolve_model()`, planner/gcc gating, worker tier in `create_rlm_orchestrator`, cost plugin in `_default_plugins` |
| `rlm_adk/orchestrator.py` | 499 | 3 | LiteLLM exception branches in `is_transient_error()` (lines 86-98) |
| `rlm_adk/callbacks/worker.py` | 266 | 3 | `status_code` fallback + `litellm.Timeout` detection in `_classify_error()` (lines 37-51) |
| `rlm_adk/dispatch.py` | 717 | 3,4 | `hasattr(e, "status_code")` guard; `DispatchConfig` type annotations relaxed to `str | Any` |
| `pyproject.toml` | -- | 1 | Added `litellm = ["litellm>=1.50.0"]` to `[project.optional-dependencies]` |

---

## 11. Known Limitations

1. **Cost tracking gap (MED-2)**: `LiteLLMCostTrackingPlugin` only captures
   root reasoning agent costs. Worker and child orchestrator costs are invisible
   to the plugin due to ADK's isolated invocation contexts. Use
   `litellm.success_callback` for complete coverage.

2. **Gemini-specific features disabled**: When `RLM_ADK_LITELLM=1`:
   - `BuiltInPlanner` (ThinkingConfig) is set to `None` -- the Router does not
     support Gemini's native thinking/planning protocol.
   - `GenerateContentConfig` with `HttpOptions`/`HttpRetryOptions` is not applied --
     retries are handled by the Router instead.

3. **No live integration tests yet**: Phase 6 (Testing) has not been implemented.
   The `scripts/validate_litellm_keys.py` script and `test_litellm_live.py` live
   tests are planned but not yet created.

4. **No replay fixtures**: Provider-fake replay fixtures (`FakeGeminiServer`)
   serve Gemini-only endpoints. LiteLLM testing relies on unit tests (mock Router)
   and planned live API tests (Phase 6).

5. **Singleton Router**: A single `RouterLiteLlmClient` instance is shared
   process-wide via `_cached_client`. This is thread-safe (double-checked
   locking with `threading.Lock`) but means Router configuration is immutable
   after first initialization. Changing env vars mid-process has no effect.

6. **Search tier unused**: The `"search"` tier (Perplexity `sonar-pro`) is
   configured in the Router's model list but no code path currently resolves
   to `create_litellm_model("search")`. It is available for future use.
