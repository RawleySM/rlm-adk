<!-- validated: 2026-03-09 -->

# LiteLLM Integration Implementation Plan

## Architecture Decision

**Strategy: Custom `RouterLiteLlmClient` injected into ADK's `LiteLlm` via the `llm_client` parameter**

After reading the ADK `LiteLlm` source at `.venv/lib/python3.12/site-packages/google/adk/models/lite_llm.py`:

1. `LiteLlm.__init__` accepts `llm_client` as a kwarg (line 1829 pops it from `kwargs` into Pydantic field at line 1816)
2. `LiteLLMClient` has exactly two methods: `acompletion(model, messages, tools, **kwargs)` and `completion(model, messages, tools, stream, **kwargs)`
3. `generate_content_async` (line 1843) handles ALL request/response conversion — we do NOT want to reimplement this
4. By replacing only the `llm_client` with one that delegates to `litellm.Router.acompletion()`, we get full Router capabilities with zero request/response conversion code

This is superior to a full `BaseLlm` subclass because:
- Zero risk of breaking ADK's complex message/tool conversion pipeline
- The `llm_client` field is a proper Pydantic field
- We reuse 100% of `LiteLlm.generate_content_async()` including streaming, tool calls, usage metadata
- Single Router instance shared via singleton client

**Feature flag**: `RLM_ADK_LITELLM=1` env var gates all LiteLLM behavior. When unset, the existing Gemini path is completely untouched.

---

## Phase 1: Foundation

**Goal**: `RouterLiteLlmClient` class, `litellm` dependency, env var config, model resolution helper. All additive, no existing code touched.

### Red Test

Create `tests_rlm_adk/test_litellm_foundation.py`:

```python
pytestmark = [pytest.mark.asyncio, pytest.mark.unit_nondefault]

class TestRouterLiteLlmClient:
    def test_import(self):
        from rlm_adk.models.litellm_router import RouterLiteLlmClient
        assert RouterLiteLlmClient is not None

    def test_init_with_model_list(self):
        from rlm_adk.models.litellm_router import RouterLiteLlmClient
        client = RouterLiteLlmClient(model_list=[
            {"model_name": "test", "litellm_params": {"model": "openai/gpt-4o-mini"}},
        ])
        assert client._router is not None

    async def test_acompletion_delegates_to_router(self, mocker):
        from rlm_adk.models.litellm_router import RouterLiteLlmClient
        client = RouterLiteLlmClient(model_list=[
            {"model_name": "test", "litellm_params": {"model": "openai/gpt-4o-mini"}},
        ])
        mock_response = mocker.MagicMock()
        mocker.patch.object(client._router, "acompletion", return_value=mock_response)
        result = await client.acompletion(model="test", messages=[], tools=None)
        client._router.acompletion.assert_called_once()
        assert result is mock_response

class TestModelListBuilder:
    def test_returns_list(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        from rlm_adk.models.litellm_router import build_model_list
        result = build_model_list()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_skips_missing_keys(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from rlm_adk.models.litellm_router import build_model_list
        result = build_model_list()
        assert isinstance(result, list)

class TestCreateLiteLlmModel:
    def test_returns_litellm_instance(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        from rlm_adk.models.litellm_router import create_litellm_model
        model = create_litellm_model("reasoning")
        from google.adk.models.lite_llm import LiteLlm
        assert isinstance(model, LiteLlm)

    def test_model_name_is_logical(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        from rlm_adk.models.litellm_router import create_litellm_model
        model = create_litellm_model("worker")
        assert model.model == "worker"
```

### Green Implementation

**CREATE** `rlm_adk/models/__init__.py` (empty)

**CREATE** `rlm_adk/models/litellm_router.py` (~150 lines):

```python
"""LiteLLM Router integration for RLM-ADK.

Provides RouterLiteLlmClient (drop-in LiteLLMClient replacement that delegates
to litellm.Router) and helper functions to build model lists from env vars.

Gated by RLM_ADK_LITELLM=1 env var at the call site (agent.py).
"""
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_litellm = None
_Router = None

def _ensure_litellm():
    global _litellm, _Router
    if _litellm is None:
        import litellm as _lit
        from litellm import Router as _R
        _litellm = _lit
        _Router = _R


class RouterLiteLlmClient:
    """LiteLLMClient-compatible class that routes through litellm.Router."""

    def __init__(self, model_list, routing_strategy="simple-shuffle",
                 num_retries=2, allowed_fails=1, cooldown_time=60,
                 fallbacks=None, timeout=None, **kwargs):
        _ensure_litellm()
        router_kwargs = {
            "model_list": model_list,
            "routing_strategy": routing_strategy,
            "num_retries": num_retries,
            "allowed_fails": allowed_fails,
            "cooldown_time": cooldown_time,
        }
        if fallbacks: router_kwargs["fallbacks"] = fallbacks
        if timeout is not None: router_kwargs["timeout"] = timeout
        self._router = _Router(**router_kwargs)

    async def acompletion(self, model, messages, tools, **kwargs):
        return await self._router.acompletion(
            model=model, messages=messages, tools=tools, **kwargs)

    def completion(self, model, messages, tools, stream=False, **kwargs):
        return self._router.completion(
            model=model, messages=messages, tools=tools, stream=stream, **kwargs)


_PROVIDER_CONFIGS = [
    ("GEMINI_API_KEY", "gemini/", [
        ("gemini-2.5-pro", "reasoning", {"rpm": 10, "tpm": 4_000_000}),
        ("gemini-2.5-flash", "worker", {"rpm": 100, "tpm": 4_000_000}),
    ]),
    ("OPENAI_API_KEY", "openai/", [
        ("o3", "reasoning", {"rpm": 30, "tpm": 1_000_000}),
        ("gpt-4o-mini", "worker", {"rpm": 100, "tpm": 1_000_000}),
    ]),
    ("DEEPSEEK_API_KEY", "deepseek/", [
        ("deepseek-reasoner", "reasoning", {"rpm": 20}),
        ("deepseek-chat", "worker", {"rpm": 60}),
    ]),
    ("GROQ_API_KEY", "groq/", [
        ("llama-3.3-70b-versatile", "worker", {"rpm": 30}),
    ]),
    ("DASHSCOPE_API_KEY", "dashscope/", [
        ("qwen-plus", "worker", {"rpm": 60}),
    ]),
    ("MINIMAX_API_KEY", "minimax/", [
        ("MiniMax-M2.5", "worker", {"rpm": 30}),
    ]),
    ("PERPLEXITY_API_KEY", "perplexity/", [
        ("sonar-pro", "search", {"rpm": 30}),
    ]),
]


def build_model_list(provider_configs=None):
    configs = provider_configs or _PROVIDER_CONFIGS
    model_list = []
    for env_var, prefix, models in configs:
        api_key = os.environ.get(env_var)
        if not api_key:
            continue
        for model_name, tier, limits in models:
            model_list.append({
                "model_name": tier,
                "litellm_params": {
                    "model": f"{prefix}{model_name}",
                    "api_key": api_key,
                    **limits,
                },
            })
    return model_list


_cached_client = None

def _get_or_create_client(model_list=None, **kwargs):
    global _cached_client
    if _cached_client is None:
        if model_list is None:
            model_list = build_model_list()
        _cached_client = RouterLiteLlmClient(model_list=model_list, **kwargs)
    return _cached_client


def create_litellm_model(logical_name="reasoning", model_list=None, **router_kwargs):
    from google.adk.models.lite_llm import LiteLlm
    client = _get_or_create_client(model_list=model_list, **router_kwargs)
    return LiteLlm(model=logical_name, llm_client=client)
```

**MODIFY** `pyproject.toml` — add `"litellm>=1.50.0"` to dependencies

### Files
- **CREATE** `rlm_adk/models/__init__.py`
- **CREATE** `rlm_adk/models/litellm_router.py`
- **CREATE** `tests_rlm_adk/test_litellm_foundation.py`
- **MODIFY** `pyproject.toml` dependencies

### Acceptance Criteria
- All `TestRouterLiteLlmClient`, `TestModelListBuilder`, `TestCreateLiteLlmModel` tests pass
- `create_litellm_model("reasoning")` returns `LiteLlm` with `RouterLiteLlmClient`

### Risk Notes
- `LiteLlm.__init__` pops `llm_client` from kwargs into Pydantic field. Verify duck-typed client is not rejected. If so, subclass `LiteLLMClient` instead.
- `litellm.Router` constructor may make network calls for some features. Use `simple-shuffle` to avoid this.

---

## Phase 2: Factory Integration

**Goal**: Wire `RouterLiteLlmClient` into `create_reasoning_agent`, gate Gemini-specific constructs.

### Red Test

Create `tests_rlm_adk/test_litellm_factory.py`:

```python
pytestmark = [pytest.mark.asyncio, pytest.mark.unit_nondefault]

class TestFactoryLiteLLMGating:
    def test_litellm_flag_off_uses_gemini(self, monkeypatch):
        monkeypatch.delenv("RLM_ADK_LITELLM", raising=False)
        from rlm_adk.agent import create_reasoning_agent
        agent = create_reasoning_agent("gemini-2.5-pro", thinking_budget=0)
        assert isinstance(agent.model, str)

    def test_litellm_flag_on_returns_litellm_model(self, monkeypatch):
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        from rlm_adk.agent import _resolve_model
        model = _resolve_model("gemini-2.5-pro")
        from google.adk.models.lite_llm import LiteLlm
        assert isinstance(model, LiteLlm)

    def test_planner_skipped_for_litellm(self, monkeypatch):
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        from rlm_adk.agent import create_reasoning_agent
        agent = create_reasoning_agent("reasoning", thinking_budget=1024)
        assert agent.planner is None

    def test_generate_content_config_none_for_litellm(self, monkeypatch):
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        from rlm_adk.agent import create_reasoning_agent
        agent = create_reasoning_agent("reasoning", thinking_budget=0)
        assert agent.generate_content_config is None
```

### Green Implementation

**MODIFY** `rlm_adk/agent.py` — add near line 55:

```python
def _is_litellm_active() -> bool:
    return os.getenv("RLM_ADK_LITELLM", "").lower() in ("1", "true", "yes")

def _resolve_model(model_str: str, tier: str | None = None) -> "str | LiteLlm":
    if not _is_litellm_active():
        return model_str
    from rlm_adk.models.litellm_router import create_litellm_model
    logical_name = tier or os.getenv("RLM_LITELLM_TIER", "reasoning")
    return create_litellm_model(logical_name)
```

**MODIFY** `create_reasoning_agent` at `agent.py:~195`:
```python
planner = None
if thinking_budget > 0 and not _is_litellm_active():
    planner = BuiltInPlanner(...)

gcc = _build_generate_content_config(retry_config) if not _is_litellm_active() else None

resolved_model = _resolve_model(model) if _is_litellm_active() else model
return LlmAgent(model=resolved_model, generate_content_config=gcc, planner=planner, ...)
```

### Files
- **MODIFY** `rlm_adk/agent.py` — `_is_litellm_active()`, `_resolve_model()`, gate planner/gcc
- **CREATE** `tests_rlm_adk/test_litellm_factory.py`

### Acceptance Criteria
- `RLM_ADK_LITELLM=0`: no behavior change
- `RLM_ADK_LITELLM=1`: `LlmAgent(model=LiteLlm("reasoning"))` with `planner=None`, `gcc=None`

### Risk Notes
- `_resolve_model` creates Router via singleton. First call initializes.
- Worker children need `"worker"` tier — handled in Phase 4.

---

## Phase 3: Error Handling

**Goal**: Extend `is_transient_error` and `_classify_error` for LiteLLM exceptions.

### Red Test

Create `tests_rlm_adk/test_litellm_errors.py`:

```python
pytestmark = [pytest.mark.unit_nondefault]

class TestClassifyLiteLLMErrors:
    def test_rate_limit_error(self):
        from rlm_adk.callbacks.worker import _classify_error
        import litellm
        exc = litellm.RateLimitError("rate limited", "openai", model="gpt-4o", llm_provider="openai")
        assert _classify_error(exc) == "RATE_LIMIT"

    def test_auth_error(self):
        from rlm_adk.callbacks.worker import _classify_error
        import litellm
        exc = litellm.AuthenticationError("bad key", "openai", model="gpt-4o", llm_provider="openai")
        assert _classify_error(exc) == "AUTH"

class TestIsTransientLiteLLM:
    def test_rate_limit_is_transient(self):
        from rlm_adk.orchestrator import is_transient_error
        import litellm
        exc = litellm.RateLimitError("rate limited", "openai", model="gpt-4o", llm_provider="openai")
        assert is_transient_error(exc) is True

    def test_auth_is_not_transient(self):
        from rlm_adk.orchestrator import is_transient_error
        import litellm
        exc = litellm.AuthenticationError("bad key", "openai", model="gpt-4o", llm_provider="openai")
        assert is_transient_error(exc) is False
```

### Green Implementation

**MODIFY** `rlm_adk/orchestrator.py` `is_transient_error` at line ~76:
```python
try:
    import litellm as _litellm_mod
    if isinstance(exc, _litellm_mod.RateLimitError): return True
    if isinstance(exc, _litellm_mod.InternalServerError): return True
    if isinstance(exc, _litellm_mod.Timeout): return True
    if isinstance(exc, _litellm_mod.ServiceUnavailableError): return True
    if isinstance(exc, (_litellm_mod.AuthenticationError, _litellm_mod.BadRequestError)):
        return False
except ImportError:
    pass
```

**MODIFY** `rlm_adk/callbacks/worker.py` `_classify_error` at line ~36:
```python
status_code = getattr(error, "status_code", None)
if status_code is not None and code is None:
    code = status_code
```

### Files
- **MODIFY** `rlm_adk/orchestrator.py` line ~76
- **MODIFY** `rlm_adk/callbacks/worker.py` line ~36
- **CREATE** `tests_rlm_adk/test_litellm_errors.py`

### Acceptance Criteria
- `_classify_error(litellm.RateLimitError(...))` returns `"RATE_LIMIT"`
- `is_transient_error(litellm.RateLimitError(...))` returns `True`
- Existing Gemini error paths unchanged

---

## Phase 4: Dispatch Integration

**Goal**: Wire through `DispatchConfig`, `create_child_orchestrator`, multi-model support.

### Red Test

Add to `tests_rlm_adk/test_litellm_factory.py`:

```python
class TestDispatchConfigLiteLLM:
    def test_dispatch_config_accepts_litellm(self, monkeypatch):
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        from rlm_adk.dispatch import DispatchConfig
        from rlm_adk.agent import _resolve_model
        dc = DispatchConfig(default_model=_resolve_model("reasoning"),
                           other_model=_resolve_model("worker"))
        from google.adk.models.lite_llm import LiteLlm
        assert isinstance(dc.other_model, LiteLlm)
```

### Green Implementation

**MODIFY** `rlm_adk/dispatch.py` line 83 — relax type annotations to `str | Any`

**MODIFY** `rlm_adk/agent.py` `create_rlm_orchestrator` — when LiteLLM active, create WorkerPool with worker tier:
```python
if _is_litellm_active():
    from rlm_adk.models.litellm_router import create_litellm_model
    worker_pool = WorkerPool(default_model=model, other_model=create_litellm_model("worker"))
```

**MODIFY** `rlm_adk/dispatch.py` line ~420 — fix `hasattr(e, "code")` guard:
```python
if hasattr(e, "code") or hasattr(e, "status_code"):
```

### Files
- **MODIFY** `rlm_adk/dispatch.py` lines 83, 420
- **MODIFY** `rlm_adk/agent.py` `create_rlm_orchestrator`
- **MODIFY** `rlm_adk/models/litellm_router.py` — singleton caching already done

### Acceptance Criteria
- `DispatchConfig(default_model=LiteLlm(...), other_model=LiteLlm(...))` works
- Same Router instance across all calls (singleton)
- `_run_child` passes `LiteLlm` objects through without error

### Risk Notes
- `dispatch.py:321` `target_model = model or dispatch_config.other_model` — `or` works correctly with `LiteLlm` objects (truthy)

---

## Phase 5: Observability

**Goal**: Token accounting for LiteLLM responses, cost tracking plugin.

### Green Implementation

**Token accounting already works**: ADK's `LiteLlm.generate_content_async` converts `response.usage` to `GenerateContentResponseUsageMetadata`. Existing `reasoning_after_model` reads this correctly. No changes needed.

**CREATE** `rlm_adk/plugins/litellm_cost_tracking.py` (~60 lines):

```python
class LiteLLMCostTrackingPlugin(BasePlugin):
    def __init__(self):
        self._total_cost = 0.0

    def after_model_callback(self, callback_context, llm_response):
        try:
            import litellm
            usage = llm_response.usage_metadata
            if usage:
                cost = litellm.completion_cost(
                    model=getattr(llm_response, "model_version", "unknown"),
                    prompt_tokens=usage.prompt_token_count or 0,
                    completion_tokens=usage.candidates_token_count or 0,
                )
                self._total_cost += cost
                callback_context.state["obs:litellm_last_call_cost"] = round(cost, 6)
                callback_context.state["obs:litellm_total_cost"] = round(self._total_cost, 6)
        except Exception as e:
            logger.debug("LiteLLM cost tracking error: %s", e)
        return None
```

**MODIFY** `rlm_adk/agent.py` `_default_plugins` — add cost tracking when LiteLLM active.

### Files
- **CREATE** `rlm_adk/plugins/litellm_cost_tracking.py`
- **MODIFY** `rlm_adk/agent.py` `_default_plugins`

---

## Phase 6: Testing

**Goal**: API key validation script, live e2e tests including `llm_query_batched` across providers.

### Strategy
Provider-fake tests stay Gemini-only (FakeGeminiServer serves Gemini endpoints only). LiteLLM testing via:
1. Unit tests (mock Router, verify wiring) — Phases 1-4
2. Live API tests (skip if no keys) — this phase

### Files to Create

**CREATE** `scripts/validate_litellm_keys.py` — pre-flight API key check using `litellm.acompletion` with `max_tokens=5`

**CREATE** `tests_rlm_adk/test_litellm_live.py`:
- `test_litellm_single_query_live` — single `llm_query` through Router
- `test_litellm_batched_query_live` — `llm_query_batched` across multiple providers, verify `obs:child_dispatch_count >= 3`

**MODIFY** `pyproject.toml` markers — add `"litellm_live: live LiteLLM integration tests"`

### Acceptance Criteria
- `pytest tests_rlm_adk/test_litellm_foundation.py -v` passes (no API keys needed)
- `pytest tests_rlm_adk/test_litellm_live.py -v` skips cleanly when no keys set
- `RLM_ADK_LITELLM=1 pytest tests_rlm_adk/test_litellm_live.py -m "" -v` passes with valid keys
- Default `pytest` run completely unaffected

---

## Phase 7: Demo

**Goal**: Showboat demo proving multi-provider routing works end-to-end.

**CREATE** `rlm_adk_docs/liteLLM_integration/demo_litellm_routing.md`:
1. Setup instructions
2. Key validation (`python scripts/validate_litellm_keys.py`)
3. Single-provider run transcript
4. Router selecting different providers
5. Cost tracking output
6. 429 recovery / fallback
7. Batched dispatch across providers

---

## Dependency Graph

```
Phase 1 (Foundation)
  |
  v
Phase 2 (Factory) -----> Phase 3 (Error Handling)
  |                            |
  v                            v
Phase 4 (Dispatch) <-----------+
  |
  v
Phase 5 (Observability)
  |
  v
Phase 6 (Testing)
  |
  v
Phase 7 (Demo)
```

Phases 2 and 3 can be developed in parallel. Each phase is independently shippable.

---

## New Environment Variables

| Variable | Default | Phase | Description |
|----------|---------|-------|-------------|
| `RLM_ADK_LITELLM` | unset (off) | 2 | Master feature flag |
| `RLM_LITELLM_TIER` | `"reasoning"` | 2 | Default logical tier for root agent |
| `RLM_LITELLM_WORKER_TIER` | `"worker"` | 4 | Logical tier for child dispatch |
| `RLM_LITELLM_ROUTING_STRATEGY` | `"simple-shuffle"` | 1 | Router strategy |
| `RLM_LITELLM_COOLDOWN_TIME` | `60` | 1 | Cooldown duration (seconds) |
| `RLM_LITELLM_NUM_RETRIES` | `2` | 1 | Per-deployment retry count |
| `RLM_LITELLM_TIMEOUT` | `300` | 1 | Request timeout (seconds) |
