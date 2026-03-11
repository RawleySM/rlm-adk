# LiteLLM + Google ADK Integration Research

> Research document for planning LiteLLM integration into the RLM-ADK project.
> Produced: 2026-03-09

---

## 1. LiteLLM Overview

LiteLLM is a Python SDK and optional proxy server (AI Gateway) that provides a **unified OpenAI-compatible interface** to 100+ LLM providers. It translates between provider-specific APIs so callers use a single calling convention regardless of backend.

### Key Features Relevant to RLM-ADK

| Feature | Why It Matters |
|---------|---------------|
| **Unified API** | Single `completion()` / `acompletion()` call for all providers |
| **Router + Load Balancing** | Distribute requests across deployments; per-deployment TPM/RPM limits |
| **Fallbacks & Retries** | Automatic cross-model fallback on 429/500; per-exception retry policies |
| **Cooldown Management** | Auto-cooldown deployments that hit rate limits; auto-recovery |
| **Async-native** | `acompletion()`, `aembedding()`, async streaming -- first-class asyncio support |
| **Cost Tracking** | Built-in token counting and cost calculation per model |
| **Tool/Function Calling** | Translates OpenAI-format tool calls to provider-native formats |
| **Caching** | In-memory, Redis, and semantic caching options |
| **Observability** | Callback system with Langfuse integration (we already use Langfuse) |

### Two Usage Modes

1. **Python SDK (in-process)**: Import `litellm` and use `Router` / `acompletion()` directly. No separate server.
2. **Proxy Server (AI Gateway)**: Standalone HTTP server that acts as an OpenAI-compatible endpoint. Useful for multi-service deployments but adds a network hop.

**For RLM-ADK, the Python SDK (in-process Router) is the right fit** -- it avoids the network hop and integrates directly into our asyncio event loop.

---

## 2. LiteLLM Router (Load Balancing, Fallbacks, Retry Logic, Rate Limit Handling)

### 2.1 Router Initialization

The `Router` manages a `model_list` of deployments. Each deployment maps a logical `model_name` (alias) to actual `litellm_params`:

```python
from litellm import Router
from litellm.router import RetryPolicy, AllowedFailsPolicy

model_list = [
    {
        "model_name": "reasoning",            # logical name used in code
        "litellm_params": {
            "model": "gemini/gemini-2.5-pro",
            "api_key": os.getenv("GEMINI_API_KEY"),
            "rpm": 10,
            "tpm": 4_000_000,
            "max_parallel_requests": 5,
        },
    },
    {
        "model_name": "reasoning",            # same logical name = load-balanced
        "litellm_params": {
            "model": "openai/o3",
            "api_key": os.getenv("OPENAI_API_KEY"),
            "rpm": 30,
            "tpm": 1_000_000,
            "max_parallel_requests": 10,
        },
    },
    {
        "model_name": "worker",
        "litellm_params": {
            "model": "gemini/gemini-2.5-flash",
            "api_key": os.getenv("GEMINI_API_KEY"),
            "rpm": 100,
            "tpm": 4_000_000,
        },
    },
    {
        "model_name": "worker",
        "litellm_params": {
            "model": "deepseek/deepseek-chat",
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "rpm": 60,
        },
    },
]

router = Router(
    model_list=model_list,
    routing_strategy="simple-shuffle",    # recommended for production
    num_retries=2,                        # retries per deployment before failover
    allowed_fails=1,                      # failures before cooldown
    cooldown_time=60,                     # seconds in cooldown
    fallbacks=[{"reasoning": ["worker"]}],  # cross-model-group fallback
    retry_policy=RetryPolicy(
        RateLimitErrorRetries=3,
        TimeoutErrorRetries=2,
        InternalServerErrorRetries=2,
        AuthenticationErrorRetries=0,     # don't retry auth errors
        BadRequestErrorRetries=0,
    ),
    allowed_fails_policy=AllowedFailsPolicy(
        RateLimitErrorAllowedFails=1,     # cool down fast on 429
        InternalServerErrorAllowedFails=3,
    ),
    # max_fallbacks=5,                    # max cross-model fallback depth (default=5)
)
```

### 2.2 Routing Strategies

| Strategy | Behavior |
|----------|----------|
| `simple-shuffle` | Weighted random based on RPM/TPM ratios. **Recommended for production.** |
| `least-busy` | Route to deployment with fewest in-flight requests |
| `usage-based-routing` | Route to deployment with lowest TPM usage this minute (requires Redis for multi-instance) |
| `latency-based-routing` | Route to deployment with lowest historical latency |
| `cost-based-routing` | Route to cheapest available deployment |

### 2.3 Fallback Chain (Order of Operations)

When a request fails, the Router follows this sequence:

1. **Per-deployment retries**: Retry on the *same* deployment up to `num_retries` times (with exponential backoff for 429s).
2. **Model-group failover**: Try other healthy deployments in the *same* model group (e.g., other "reasoning" deployments).
3. **Cross-model fallbacks**: If all deployments in the primary group fail, try the `fallbacks` chain (e.g., "reasoning" -> "worker").
4. **Specialized fallbacks**: `context_window_fallbacks` (for context-length errors) and `content_policy_fallbacks` (for safety filters) trigger model-specific fallbacks.
5. **Give up**: After `max_fallbacks` (default=5) cross-model attempts, raise the exception.

### 2.4 Cooldown Management

- When a deployment returns 429 or exceeds `allowed_fails` failures in a minute, it enters **cooldown**.
- Cooldown duration = `cooldown_time` seconds (or `Retry-After` header value if present).
- During cooldown, the deployment is **excluded from routing** -- requests go to other deployments.
- After cooldown expires, the deployment is **automatically re-added** to the rotation.
- `AllowedFailsPolicy` lets you set different thresholds per error type (e.g., cool down after 1 rate-limit error but tolerate 3 server errors).

### 2.5 Rate Limit Enforcement

- **TPM/RPM per deployment**: Set `rpm` and `tpm` in `litellm_params` for each deployment.
- **max_parallel_requests**: Caps concurrent in-flight requests per deployment. If not set, derived from RPM (or TPM / 1000 * 6).
- **Pre-call checks**: With `enforce_model_rate_limits` enabled, requests are blocked *before* hitting the provider if the deployment would exceed its limit (returns 429 with `Retry-After: 60`).
- **Usage tracking**: The Router tracks TPM/RPM usage per deployment per minute. For multi-instance deployments, Redis is used for shared counters.

### 2.6 RetryPolicy Fields

| Field | Controls |
|-------|----------|
| `BadRequestErrorRetries` | 400 errors |
| `AuthenticationErrorRetries` | 401/403 errors |
| `TimeoutErrorRetries` | Timeout errors |
| `RateLimitErrorRetries` | 429 errors |
| `ContentPolicyViolationErrorRetries` | Safety filter rejections |
| `InternalServerErrorRetries` | 500+ errors |

### 2.7 AllowedFailsPolicy Fields

Same pattern: `BadRequestErrorAllowedFails`, `AuthenticationErrorAllowedFails`, `TimeoutErrorAllowedFails`, `RateLimitErrorAllowedFails`, `ContentPolicyViolationErrorAllowedFails`, `InternalServerErrorAllowedFails`.

---

## 3. LiteLLM Async Support

### 3.1 Core Async Functions

```python
from litellm import acompletion

# Direct async call (no router)
response = await acompletion(
    model="gemini/gemini-2.5-flash",
    messages=[{"role": "user", "content": "Hello"}],
)
```

### 3.2 Router Async Methods

```python
# All Router methods have async counterparts:
response = await router.acompletion(model="reasoning", messages=[...])
response = await router.aembedding(model="embed", input=[...])

# Async streaming
response = await router.acompletion(
    model="reasoning",
    messages=[...],
    stream=True,
)
async for chunk in response:
    print(chunk.choices[0].delta.content)

# Batch async (concurrent calls)
responses = await router.abatch_completion(
    models=["reasoning", "worker"],
    messages=[[...], [...]],
)
```

### 3.3 Async Architecture

- `acompletion()` is a true async function -- it uses `httpx` / `aiohttp` under the hood for providers that support async.
- For providers without native async, `acompletion` uses `asyncio.run_in_executor()` to run the sync call in a thread pool (non-blocking).
- The Router's `acompletion()` handles routing, retries, fallbacks, and cooldown checks all within the async context.
- **Compatible with our asyncio event loop**: The Router can be used directly inside our existing `async def` dispatch closures and tool functions.

---

## 4. Google ADK Model Configuration

### 4.1 How Models Are Wired in ADK

ADK agents configure their LLM via the `model` parameter on `LlmAgent`:

```python
from google.adk.agents import LlmAgent

# Option 1: Model name string (resolved by LLMRegistry)
agent = LlmAgent(model="gemini-2.5-flash", name="my_agent", ...)

# Option 2: BaseLlm instance (direct)
from google.adk.models.lite_llm import LiteLlm
agent = LlmAgent(model=LiteLlm(model="openai/gpt-4o"), name="my_agent", ...)
```

### 4.2 Model Provider Resolution Chain

1. **Direct BaseLlm instance**: If `model` is already a `BaseLlm` subclass, use it directly.
2. **LLMRegistry lookup**: If `model` is a string, `LLMRegistry.new_llm(model_string)` matches against registered `BaseLlm` classes via their `supported_models()` regex patterns.
3. **Ancestor inheritance**: If not set, inherit from parent agent.
4. **Default model**: Falls back to `gemini-2.5-flash` (or override with `LlmAgent.set_default_model()`).

### 4.3 Registered BaseLlm Implementations

The `models/__init__.py` conditionally registers:

| Class | Supports | Condition |
|-------|----------|-----------|
| `Gemini` | `gemini-*` models (native Google genai SDK) | Always |
| `Claude` | `claude-*` models (native Anthropic SDK) | `anthropic` installed |
| `LiteLlm` | `openai/*`, `anthropic/*`, `groq/*`, `vertex_ai/*`, etc. | `litellm` installed |
| `Gemma` | `gemma-*` (local) | Always |

### 4.4 The LiteLlm Wrapper Class

`google.adk.models.lite_llm.LiteLlm` is a `BaseLlm` subclass that wraps the `litellm` library:

- **`__init__(self, model: str, **kwargs)`**: Stores `model` name and additional args (`api_key`, `api_base`, `api_version`, `headers`, etc.) in `self._additional_args`.
- **`self.llm_client`**: An internal `LiteLLMClient` instance that wraps `litellm.acompletion` and `litellm.completion`. This is **not** a `litellm.Router` -- it calls the global `litellm.acompletion()` function directly.
- **`generate_content_async(llm_request, stream)`**: Converts ADK's `LlmRequest` to litellm's message/tool format, calls `self.llm_client.acompletion(...)`, converts the response back to ADK's `LlmResponse`.
- **Tool calling**: Converts ADK `function_declarations` to litellm tool format; extracts `tool_calls` from responses back to ADK `FunctionCall` objects.
- **Response schema**: Converts `response_schema` to litellm-compatible format (Gemini-style or OpenAI-style depending on provider).

### 4.5 Extension Points

1. **Pass `BaseLlm` instance directly**: `LlmAgent(model=LiteLlm(model="openai/gpt-4o"))`.
2. **Register custom `BaseLlm`**: Subclass `BaseLlm`, implement `generate_content_async` and `supported_models`, register with `LLMRegistry.register(MyLlm)`.
3. **`model_code` with `CodeConfig`**: For YAML/JSON agent configs, use `model_code` to specify a class and kwargs.
4. **LiteLlm kwargs pass-through**: Any extra kwargs to `LiteLlm(...)` are forwarded to `litellm.acompletion()`.

### 4.6 Critical Limitation: No Native Router Support

ADK's `LiteLlm` wrapper uses `LiteLLMClient` (a thin wrapper around `litellm.acompletion`) -- it does **not** accept a `litellm.Router` instance. There is an [open feature request (google/adk-python#110)](https://github.com/google/adk-python/issues/110) for this.

This means: **to use Router-level load balancing/fallbacks, we need a custom `BaseLlm` implementation** that delegates to a `litellm.Router` instead of calling `litellm.acompletion` directly.

---

## 5. Integration Patterns

### Pattern A: Custom BaseLlm Wrapping litellm.Router (Recommended)

Create a custom `BaseLlm` subclass that holds a `litellm.Router` and delegates `generate_content_async` through it. This gives us full Router capabilities (load balancing, fallbacks, cooldowns) while staying within ADK's model system.

```python
# Conceptual sketch -- not production code
from google.adk.models.lite_llm import LiteLlm

class RouterLiteLlm(LiteLlm):
    """LiteLlm subclass that routes through a litellm.Router."""

    def __init__(self, model: str, router: "litellm.Router", **kwargs):
        super().__init__(model=model, **kwargs)
        self._router = router

    async def generate_content_async(self, llm_request, stream=False):
        # Convert LlmRequest -> litellm messages/tools (reuse parent's conversion)
        messages, tools, response_format = self._get_completion_inputs(llm_request)

        # Route through the Router instead of direct acompletion
        response = await self._router.acompletion(
            model=self.model,   # logical model name in Router's model_list
            messages=messages,
            tools=tools,
            response_format=response_format,
            stream=stream,
            **self._additional_args,
        )

        # Convert response back to ADK LlmResponse (reuse parent's conversion)
        yield self._to_llm_response(response)
```

**Advantages**:
- Full Router features: load balancing, fallbacks, retries, cooldowns
- Stays within ADK's `BaseLlm` contract
- Single Router instance shared across all agents
- No proxy server overhead

**Considerations**:
- Must carefully reuse LiteLlm's request/response conversion logic
- The Router's `model` parameter uses logical names, not provider-prefixed names
- Need to handle streaming response conversion

### Pattern B: LiteLLM Proxy Server (Alternative)

Run LiteLLM as a local proxy, point all agents at `http://localhost:4000` with `openai/` prefix:

```python
agent = LlmAgent(
    model=LiteLlm(
        model="openai/reasoning",  # proxy model alias
        api_base="http://localhost:4000",
    ),
    ...
)
```

**Advantages**: No custom code, all config in YAML.
**Disadvantages**: Extra process, network hop, harder to debug, latency overhead.

### Pattern C: Monkey-Patch LiteLLMClient (Escape Hatch)

Replace the `LiteLLMClient` that `LiteLlm` uses internally:

```python
from google.adk.models.lite_llm import LiteLlm, LiteLLMClient

# Create a shim that delegates to Router
class RouterClient:
    def __init__(self, router):
        self._router = router
    async def acompletion(self, **kwargs):
        return await self._router.acompletion(**kwargs)

router = Router(model_list=[...])
llm = LiteLlm(model="reasoning", llm_client=RouterClient(router))
```

**Note**: ADK's LiteLlm constructor accepts `llm_client` as a kwarg (it pops it from kwargs). However, it is typed as `LiteLLMClient`, so this is fragile.

### Recommended Approach

**Pattern A** (custom BaseLlm subclass) is the most robust:
- Type-safe, no monkey-patching
- Full control over request/response pipeline
- Can be registered with LLMRegistry for string-based model resolution
- Can reuse most of LiteLlm's conversion logic by subclassing

---

## 6. Available API Keys & Models

Based on the `.env` file, the following provider keys are **active** (uncommented):

| Provider | Env Var | LiteLLM Model Prefix | Example Models |
|----------|---------|----------------------|----------------|
| **Google Gemini** | `GEMINI_API_KEY` | `gemini/` | `gemini/gemini-2.5-pro`, `gemini/gemini-2.5-flash`, `gemini/gemini-2.0-flash` |
| **OpenAI** | `OPENAI_API_KEY` | `openai/` | `openai/gpt-4o`, `openai/gpt-4o-mini`, `openai/o3`, `openai/o4-mini` |
| **DeepSeek** | `DEEPSEEK_API_KEY` | `deepseek/` | `deepseek/deepseek-chat`, `deepseek/deepseek-reasoner` |
| **Groq** | `GROQ_API_KEY` | `groq/` | `groq/llama-3.3-70b-versatile`, `groq/llama3-70b-8192`, `groq/mixtral-8x7b-32768` |
| **Perplexity** | `PERPLEXITY_API_KEY` | `perplexity/` | `perplexity/sonar-pro`, `perplexity/sonar` |
| **DashScope** | `DASHSCOPE_API_KEY` | `dashscope/` | `dashscope/qwen-turbo`, `dashscope/qwen-plus`, `dashscope/qwen-max` |
| **MiniMax** | `MINIMAX_API_KEY` | `minimax/` | `minimax/MiniMax-M2.5`, `minimax/MiniMax-Text-01` |
| **ElevenLabs** | `ELEVENLABS_API_KEY` | N/A | Audio/TTS only, not applicable for LLM completion |

**Commented out (inactive)**:
- `OPENROUTER_API_KEY` -- would enable `openrouter/` prefix for all OpenRouter models
- `ANTHROPIC_API_KEY` -- would enable `anthropic/` prefix for Claude models directly

### Recommended Model Groupings for Router

```python
# Reasoning tier (high capability, lower RPM)
reasoning_deployments = [
    {"model_name": "reasoning", "litellm_params": {"model": "gemini/gemini-2.5-pro", ...}},
    {"model_name": "reasoning", "litellm_params": {"model": "openai/o3", ...}},
    {"model_name": "reasoning", "litellm_params": {"model": "deepseek/deepseek-reasoner", ...}},
]

# Worker tier (fast, high RPM)
worker_deployments = [
    {"model_name": "worker", "litellm_params": {"model": "gemini/gemini-2.5-flash", ...}},
    {"model_name": "worker", "litellm_params": {"model": "openai/gpt-4o-mini", ...}},
    {"model_name": "worker", "litellm_params": {"model": "deepseek/deepseek-chat", ...}},
    {"model_name": "worker", "litellm_params": {"model": "groq/llama-3.3-70b-versatile", ...}},
    {"model_name": "worker", "litellm_params": {"model": "dashscope/qwen-plus", ...}},
    {"model_name": "worker", "litellm_params": {"model": "minimax/MiniMax-M2.5", ...}},
]

# Search/grounded tier (optional)
search_deployments = [
    {"model_name": "search", "litellm_params": {"model": "perplexity/sonar-pro", ...}},
]
```

---

## 7. Rate Limit Mitigation Strategy

### The 429 Problem in RLM-ADK

Currently, RLM-ADK uses a single Gemini API key with `gemini-2.5-pro` for reasoning and `gemini-2.5-flash` for workers. The `WorkerPool` dispatches multiple parallel `llm_query()` calls, and under load these hit Gemini's RPM/TPM limits, producing 429 errors. Our current mitigation is retry with backoff in `HttpRetryOptions`, but this:

- Blocks the entire worker while waiting
- Does not redirect to alternative providers
- Wastes time retrying a provider that is already rate-limited

### How LiteLLM Solves This

LiteLLM's Router addresses 429s at multiple levels:

#### Level 1: Per-Deployment Rate Awareness
- Set `rpm` and `tpm` per deployment in the `model_list`
- Router tracks usage per deployment per minute
- With `usage-based-routing`, requests are routed to the deployment with the lowest current utilization
- With `simple-shuffle`, requests are distributed proportionally to each deployment's capacity

#### Level 2: Automatic Cooldown on 429
- When a deployment returns 429, it immediately enters cooldown (configurable duration)
- During cooldown, all requests are routed to other deployments in the same model group
- `AllowedFailsPolicy(RateLimitErrorAllowedFails=1)` means a single 429 triggers cooldown
- If the 429 response includes a `Retry-After` header, the cooldown duration matches it

#### Level 3: Cross-Model Fallback
- If all deployments in a model group are in cooldown (e.g., all "reasoning" deployments), the Router falls back to alternate model groups
- Example: `fallbacks=[{"reasoning": ["worker"]}]` -- if Gemini Pro and OpenAI o3 are both rate-limited, use a worker-tier model instead
- `max_fallbacks=5` prevents infinite fallback loops

#### Level 4: Pre-Call Rate Limit Enforcement
- With `enforce_model_rate_limits` enabled, the Router checks TPM/RPM usage *before* sending the request
- If the deployment would exceed its limit, the request is immediately routed elsewhere (no wasted API call)
- This prevents "retry storms" where multiple requests hit a rate-limited provider simultaneously

#### Level 5: Parallel Request Limiting
- `max_parallel_requests` per deployment caps concurrent in-flight calls
- Prevents overwhelming a single deployment even if RPM hasn't been exhausted
- If not set explicitly, derived from RPM setting

### Concrete Mitigation Plan

```
Current state:
  reasoning_agent -> gemini-2.5-pro (single key, 10 RPM)
  worker_pool     -> gemini-2.5-flash (single key, ~100 RPM)
  Result: 429s under load, entire pipeline stalls

With LiteLLM Router:
  reasoning_agent -> Router("reasoning")
    -> gemini/gemini-2.5-pro (10 RPM, cooldown=60s)
    -> openai/o3 (30 RPM, cooldown=30s)
    -> deepseek/deepseek-reasoner (20 RPM)
    Fallback: "worker" group

  worker_pool -> Router("worker")
    -> gemini/gemini-2.5-flash (100 RPM, cooldown=30s)
    -> openai/gpt-4o-mini (100 RPM)
    -> deepseek/deepseek-chat (60 RPM)
    -> groq/llama-3.3-70b-versatile (30 RPM)
    -> dashscope/qwen-plus (60 RPM)
    -> minimax/MiniMax-M2.5 (unknown RPM, conservative limit)

  Result:
    - 429 on Gemini? Automatically routes to OpenAI/DeepSeek
    - All Gemini deploys cooled down? Falls back across providers
    - No wasted API calls (pre-call enforcement)
    - Aggregate RPM across all providers >> single provider RPM
    - Workers spread across 6 providers instead of 1
```

### Key Configuration Recommendations

1. **Set conservative RPM/TPM limits** per deployment (80% of actual limits) to avoid hitting provider limits at all.
2. **Use `simple-shuffle` routing** for production (lowest overhead, no Redis needed).
3. **Set `RateLimitErrorRetries=1`** -- don't waste time retrying a rate-limited provider; fail over fast.
4. **Set `RateLimitErrorAllowedFails=1`** -- cool down immediately on first 429.
5. **Set `cooldown_time`** based on provider reset windows (typically 60s for per-minute limits).
6. **Keep `num_retries=2`** for non-rate-limit errors (server errors, timeouts).
7. **Set `max_parallel_requests`** per deployment to prevent bursts (especially for Gemini with low RPM).
8. **Monitor with callbacks** -- LiteLLM supports custom callbacks for logging routing decisions, which can feed into our existing observability pipeline.

### Integration with Existing Error Handling

Our existing error classification in `callbacks/worker.py` (RATE_LIMIT, SERVER, SAFETY, etc.) should still work:
- LiteLLM handles retries/fallbacks *before* errors reach our code
- Only errors that exhaust all retries + fallbacks will surface to our `on_model_error_callback`
- We should update `_classify_error` to recognize LiteLLM's wrapped exceptions (`litellm.RateLimitError`, etc.)
- The `OBS_WORKER_ERROR_COUNTS` will reflect only *terminal* failures (all retries exhausted)

---

## Appendix: Source Links

- [LiteLLM Router - Load Balancing](https://docs.litellm.ai/docs/routing)
- [LiteLLM Fallbacks & Retries](https://docs.litellm.ai/docs/proxy/reliability)
- [LiteLLM Streaming + Async](https://docs.litellm.ai/docs/completion/stream)
- [LiteLLM Providers List](https://docs.litellm.ai/docs/providers)
- [LiteLLM Google ADK Tutorial](https://docs.litellm.ai/docs/tutorials/google_adk)
- [ADK LiteLLM Docs](https://google.github.io/adk-docs/agents/models/litellm/)
- [ADK Model Providers](https://google.github.io/adk-docs/agents/models/)
- [ADK LiteLlm Source (lite_llm.py)](https://github.com/google/adk-python/blob/main/src/google/adk/models/lite_llm.py)
- [Feature Request: Router Support in ADK (#110)](https://github.com/google/adk-python/issues/110)
- [LiteLLM DeepSeek Provider](https://docs.litellm.ai/docs/providers/deepseek)
- [LiteLLM Groq Provider](https://docs.litellm.ai/docs/providers/groq)
- [LiteLLM DashScope Provider](https://docs.litellm.ai/docs/providers/dashscope)
- [LiteLLM Perplexity Provider](https://docs.litellm.ai/docs/providers/perplexity)
- [LiteLLM MiniMax Provider](https://docs.litellm.ai/docs/providers/minimax)
- [LiteLLM Proxy Load Balancing](https://docs.litellm.ai/docs/proxy/load_balancing)
- [LiteLLM Dynamic TPM/RPM Allocation](https://docs.litellm.ai/docs/proxy/dynamic_rate_limit)
