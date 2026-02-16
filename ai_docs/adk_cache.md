# ADK Context Caching -- Deep Dive

## Table of Contents

1. [Gemini Context Caching at the API Level](#1-gemini-context-caching-at-the-api-level)
2. [How ADK Integrates with Gemini Caching](#2-how-adk-integrates-with-gemini-caching)
3. [static_instruction vs context_cache_config](#3-static_instruction-vs-context_cache_config)
4. [Why Current Logs Show cached_content_token_count: 0](#4-why-current-logs-show-cached_content_token_count-0)
5. [How to Enable Caching in This Project](#5-how-to-enable-caching-in-this-project)
6. [Cost/Benefit Analysis](#6-costbenefit-analysis)
7. [Limitations and Caveats](#7-limitations-and-caveats)

---

## 1. Gemini Context Caching at the API Level

Gemini offers two distinct caching mechanisms:

### Implicit Caching (automatic, no config needed)

- Enabled by default on most Gemini models since May 2025.
- If a request shares a **common prefix** with a recent request, Gemini automatically serves the overlapping portion from cache.
- No developer configuration required -- cost savings are passed through transparently.
- Opportunistic: no guarantee of a cache hit, but likely when you send structurally similar requests within a short timeframe.
- Best practice: place large, static content at the **beginning** of the prompt; put variable content (user query, dynamic instructions) at the **end**.

### Explicit Caching (manual, guaranteed savings)

- Developer creates a named cache object via `caches.create()` containing system instructions, tools, and/or conversation contents.
- Subsequent requests reference the cache by name instead of re-sending the cached content.
- Guaranteed savings: every request that references the cache pays the cached token rate.
- Requires management: caches have a TTL, must be refreshed when content changes, and incur hourly storage costs.

### Minimum Token Thresholds

The Gemini API enforces minimum input token counts for caching eligibility:

| Model                  | Min Tokens (explicit cache) |
|------------------------|-----------------------------|
| Gemini 3 Flash Preview | 1,024                       |
| Gemini 3 Pro Preview   | 4,096                       |
| Gemini 2.5 Flash       | 1,024                       |
| Gemini 2.5 Pro         | 4,096                       |

If the total cacheable content (system instruction + tools + conversation history) is below this threshold, explicit caching is not created.

### Pricing (as of Feb 2026)

All current Gemini models offer a **90% discount** on cached input tokens:

| Model                  | Regular Input (per 1M tokens) | Cached Input (per 1M tokens) | Storage (per 1M tokens/hour) |
|------------------------|-------------------------------|------------------------------|------------------------------|
| Gemini 3 Pro Preview   | $2.00                         | $0.20                        | $4.50                        |
| Gemini 3 Flash Preview | $0.50                         | $0.05                        | $1.00                        |
| Gemini 2.5 Pro         | $1.25                         | $0.125                       | $4.50                        |
| Gemini 2.5 Flash       | $0.30                         | $0.03                        | $1.00                        |

Note: prices double for prompts exceeding 200K tokens on Pro models.

---

## 2. How ADK Integrates with Gemini Caching

ADK's explicit caching support is built from four components that form a pipeline:

### 2a. ContextCacheConfig (configuration)

**Source**: `src/google/adk/agents/context_cache_config.py`

Decorated with `@experimental`. Configured at the `App` level. When present, caching is enabled for ALL LlmAgents in the app. When absent (`None`), caching is disabled entirely.

```python
class ContextCacheConfig(BaseModel):
    cache_intervals: int = 10      # max invocations before cache refresh (1-100)
    ttl_seconds: int = 1800        # cache TTL, default 30 minutes
    min_tokens: int = 0            # skip caching if request < N tokens
```

Key semantics:
- `cache_intervals`: After this many invocations reusing the same cache, ADK forces a refresh (creates a new cache). This prevents stale caches from persisting indefinitely even if the TTL has not elapsed.
- `ttl_seconds`: Passed to the Gemini API as the cache TTL. The cache is stored server-side for this duration. Storage is billed per hour.
- `min_tokens`: ADK checks the **previous** request's prompt token count (from `usage_metadata`) against this threshold. If below, caching is skipped. This prevents caching overhead on small requests.

### 2b. ContextCacheRequestProcessor (request pipeline)

**Source**: `src/google/adk/flows/llm_flows/context_cache_processor.py`

Runs as part of `SingleFlow`'s request processor chain (after instructions, identity, and contents processors). It:

1. Checks `invocation_context.context_cache_config` -- returns early if `None`.
2. Sets `llm_request.cache_config` from the invocation context.
3. Searches session events (newest to oldest) for the most recent `CacheMetadata` and `prompt_token_count` from prior LLM responses for the same agent.
4. If found, attaches them to the `LlmRequest` so the cache manager can validate or recreate the cache.

This processor yields no events -- it only mutates the `LlmRequest`.

### 2c. GeminiContextCacheManager (cache lifecycle)

**Source**: `src/google/adk/models/gemini_context_cache_manager.py`

Invoked from `Gemini.generate_content_async()` when `llm_request.cache_config` is set. Manages the full cache lifecycle:

**First invocation (no prior metadata)**:
- Generates a fingerprint (SHA-256 of system_instruction + tools + tool_config + first N contents).
- Returns fingerprint-only `CacheMetadata` (no active cache yet).
- Does NOT create a cache on the first call because there is no prior token count to validate against `min_tokens`.

**Second invocation (fingerprint-only metadata from first call)**:
- Compares current fingerprint with stored fingerprint.
- If they match AND `cacheable_contents_token_count >= min_tokens`, creates a cache via `caches.create()`.
- The cache includes: system_instruction, tools, tool_config, and the first N contents (everything except the most recent user message batch).
- Applies the cache: sets `cached_content = cache_name` on the request, removes system_instruction/tools from config, strips cached contents from the contents list.

**Subsequent invocations (active cache)**:
- Validates: cache not expired, invocations_used <= cache_intervals, fingerprint still matches.
- If valid: reuses the cache (same apply logic).
- If invalid: cleans up old cache, potentially creates new one.

The fingerprint includes the first N contents (conversation history up to the last user message batch), so the cache is invalidated when the conversation history diverges.

### 2d. CacheMetadata (state tracking)

**Source**: `src/google/adk/models/cache_metadata.py`

Immutable Pydantic model stored on LLM response events. Two states:

1. **Fingerprint-only**: `cache_name=None`, only `fingerprint` and `contents_count` populated. Used for prefix matching between invocations.
2. **Active cache**: All fields populated -- `cache_name` (Gemini resource name), `expire_time`, `invocations_used`, `created_at`.

### 2e. Integration in google_llm.py

**Source**: `src/google/adk/models/google_llm.py`

In `Gemini.generate_content_async()`:
1. If `llm_request.cache_config` is set, instantiates `GeminiContextCacheManager`.
2. Calls `handle_context_caching(llm_request)` which may modify the request in-place (remove system_instruction, remove cached contents, set `cached_content` reference).
3. After receiving the model response, calls `populate_cache_metadata_in_response()` to attach cache metadata to the `LlmResponse`.
4. The metadata flows through to the session event, making it available for the next invocation's `ContextCacheRequestProcessor`.

### Data Flow Summary

```
App(context_cache_config=...)
  |
  v
InvocationContext.context_cache_config
  |
  v
ContextCacheRequestProcessor.run_async()
  - Sets llm_request.cache_config
  - Finds prior CacheMetadata from session events
  - Sets llm_request.cache_metadata
  - Sets llm_request.cacheable_contents_token_count
  |
  v
Gemini.generate_content_async()
  - Instantiates GeminiContextCacheManager
  - handle_context_caching() -> validates/creates/reuses cache
  - Modifies llm_request in-place if active cache
  - Calls Gemini API (generate_content)
  - Attaches CacheMetadata to LlmResponse
  |
  v
Session event stores CacheMetadata
  (available for next invocation's ContextCacheRequestProcessor)
```

---

## 3. static_instruction vs context_cache_config

These are **complementary but independent** features. Neither implies the other.

### static_instruction (LlmAgent field)

**What it does**: Separates static prompt content from dynamic, template-resolved content.

- `static_instruction` goes to `system_instruction` in the LLM request (position 0, before everything else).
- `instruction` (the dynamic field) goes to **user content** appended after the static system instruction.
- Without `static_instruction`, `instruction` goes directly to `system_instruction`.

**Source**: `src/google/adk/flows/llm_flows/instructions.py`, lines 97-117:
```python
# Handle static_instruction - add via append_instructions
if agent.static_instruction:
    static_content = _transformers.t_content(agent.static_instruction)
    llm_request.append_instructions(static_content)

# If static_instruction exists, dynamic instruction goes to user content
if agent.instruction and agent.static_instruction:
    si = await _process_agent_instruction(agent, invocation_context)
    dynamic_content = types.Content(role='user', parts=[types.Part(text=si)])
    llm_request.contents.append(dynamic_content)
```

**What it does NOT do**: It does NOT enable caching by itself. The `static_instruction` docstring explicitly states:

> Setting static_instruction alone does NOT enable caching automatically. For explicit caching control, configure context_cache_config at App level.

**Why it helps caching**: By placing static content first in system_instruction and dynamic content later in user content, the request has a stable prefix that:
1. Maximizes **implicit cache** hits (Gemini sees the same prefix across requests).
2. Provides a clean boundary for **explicit caching** (the cache manager can cache the stable prefix and leave dynamic content uncached).

### context_cache_config (App-level config)

**What it does**: Enables ADK's explicit caching pipeline (the full machinery described in Section 2).

- Creates server-side cache objects via the Gemini API.
- Manages cache lifecycle (creation, validation, refresh, cleanup).
- Removes cached content from subsequent requests (reducing request size and cost).

**What it does NOT do**: It does NOT change how instructions are structured. That is `static_instruction`'s job.

### The Relationship

| Feature               | static_instruction               | context_cache_config             |
|-----------------------|----------------------------------|----------------------------------|
| Scope                 | Per-agent (LlmAgent field)       | Per-app (App-level config)       |
| Purpose               | Instruction structure/ordering   | Cache lifecycle management       |
| Caching effect        | Helps implicit cache (stable prefix) | Enables explicit cache           |
| Requires the other?   | No                               | No (but benefits from it)        |

For maximum cost savings, use **both**: `static_instruction` to structure the prompt with a stable prefix, and `context_cache_config` to explicitly cache that prefix server-side.

---

## 4. Why Current Logs Show cached_content_token_count: 0

The observability logs for this project show `cached_content_token_count: 0` for all 12 LLM calls. This is because:

1. **No `context_cache_config` is set on the App**:
   ```python
   # rlm_agent/agent.py, line 104
   app = App(
       name="rlm_agent",
       root_agent=root_agent,
       plugins=[ObservabilityPlugin()],
       # NO context_cache_config parameter!
   )
   ```

2. **Without `context_cache_config`**, the `ContextCacheRequestProcessor` returns early (line 59 of `context_cache_processor.py`):
   ```python
   if not invocation_context.context_cache_config:
       return
   ```

3. **No `cache_config` is set on `LlmRequest`**, so `Gemini.generate_content_async()` skips cache handling entirely (line 168 of `google_llm.py`):
   ```python
   if llm_request.cache_config:
       # ... cache handling -- never entered
   ```

4. **Implicit caching may still be happening** at the Gemini API level, but ADK does not track it. The `cached_content_token_count` field in the Gemini API response only reflects **explicit** cache usage. Implicit cache savings appear only in billing, not in the API response metadata.

5. **The `static_instruction` on the thinker agent** (`EXPLORER_INSTRUCTION`, ~4K chars) structures the prompt correctly for caching, but without `context_cache_config`, no explicit cache is created.

---

## 5. How to Enable Caching in This Project

### Step 1: Add ContextCacheConfig to the App

Modify `/home/rawleysm/dev/sandbox/rlm_parallel/rlm_agent/agent.py`:

```python
"""RLM agent -- minimal proof of concept."""

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App
from .prompts_explorer import EXPLORER_INSTRUCTION
from .observability_plugin import ObservabilityPlugin
from .repl_orchestrator import REPLOrchestratorAgent
from .fetcher_agent import FetcherAgent

MODEL = "gemini-3-pro-preview"

# ... (agents defined as before) ...

# -- App wrapper --
app = App(
    name="rlm_agent",
    root_agent=root_agent,
    plugins=[ObservabilityPlugin()],
    context_cache_config=ContextCacheConfig(
        min_tokens=4096,       # Gemini 3 Pro minimum is 4,096
        ttl_seconds=600,       # 10 minutes -- enough for one RLM run
        cache_intervals=10,    # up to 10 loop iterations before refresh
    ),
)
```

### Step 2: Verify static_instruction is already set

The thinker agent already uses `static_instruction=EXPLORER_INSTRUCTION`, which places the ~4K-char explorer prompt as system instruction. This is the correct pattern -- the stable prompt is first, and the dynamic per-iteration instruction is in user content.

### Step 3: Understand the warm-up behavior

Explicit caching in ADK has a **two-invocation warm-up**:

1. **First LLM call**: No cache exists. ADK generates a fingerprint and returns fingerprint-only metadata. The full prompt is sent uncached.
2. **Second LLM call**: ADK finds the fingerprint from the first call, checks that `prompt_token_count >= min_tokens`, and creates the cache. This call also sends the full prompt (the cache is created from this request's content).
3. **Third+ LLM calls**: Cache is active. System instruction, tools, and cached contents are removed from the request. Only new user content is sent.

In the LoopAgent with `max_iterations=5`, the thinker runs up to 5 times. The first two calls pay full price; calls 3-5 benefit from caching. For a single-iteration run, caching provides no benefit.

### Step 4: Monitor cache hits

After enabling caching, the observability logs should show:
- `cached_content_token_count: 0` for the first two calls (warm-up)
- `cached_content_token_count: N` (where N > 0) for subsequent calls

ADK also emits OpenTelemetry spans (`handle_context_caching`, `create_cache`) that can be inspected for cache lifecycle events.

---

## 6. Cost/Benefit Analysis

### For This Project (gemini-3-pro-preview)

The thinker's `static_instruction` (EXPLORER_INSTRUCTION) is approximately 4,000 characters, which translates to roughly 1,000 tokens. Combined with tools and any accumulated conversation contents, the total cacheable prefix grows with each iteration.

**Scenario: 5-iteration LoopAgent run**

Assuming the cacheable prefix stabilizes at ~10K tokens after iteration 2:

| Invocation | Cached Tokens | Regular Cost    | Cached Cost     | Savings |
|------------|---------------|-----------------|-----------------|---------|
| 1 (warm-up) | 0            | 10K * $2/1M = $0.020 | $0.020     | $0.000  |
| 2 (warm-up) | 0            | 10K * $2/1M = $0.020 | $0.020     | $0.000  |
| 3           | 10K          | 10K * $2/1M = $0.020 | 10K * $0.2/1M = $0.002 | $0.018  |
| 4           | 10K          | $0.020          | $0.002          | $0.018  |
| 5           | 10K          | $0.020          | $0.002          | $0.018  |
| **Total**   |              | **$0.100**      | **$0.046**      | **$0.054 (54%)** |

Plus storage cost: 10K tokens * $4.50/1M/hour * (10 min / 60) = $0.0075 (negligible).

**Break-even**: Caching pays for itself by the 3rd iteration. For single-iteration runs, it adds overhead (fingerprint computation, metadata storage) with no benefit.

### Considerations

- **More iterations = more savings**: The 2-call warm-up cost is amortized over more cached calls.
- **Larger static content = larger savings**: If `static_instruction` were 50K tokens (e.g., a full codebase dump), savings would be dramatically higher.
- **The sub-LM calls in REPL (`sublm_dispatcher`)** are separate Gemini API calls that do NOT benefit from this cache -- they are independent requests with their own prompts.
- **Storage costs are negligible** for TTLs under 1 hour at these token counts.

---

## 7. Limitations and Caveats

### Experimental Status

`ContextCacheConfig` and `GeminiContextCacheManager` are both decorated with `@experimental`. The API may change in future ADK releases. Monitor the ADK changelog when upgrading.

### Gemini Models Only

The caching pipeline is implemented only in `Gemini.generate_content_async()` (in `google_llm.py`). Non-Gemini LLM backends (e.g., LiteLLM, custom models) do not support ADK's explicit caching.

### Two-Invocation Warm-Up

The cache is NEVER created on the first invocation. ADK needs:
1. A fingerprint from the first call.
2. A `prompt_token_count` from the first call's response to check against `min_tokens`.

This means single-shot agents (no looping, no multi-turn) get zero benefit from explicit caching.

### Minimum Token Threshold

The Gemini API enforces model-specific minimums (see Section 1). ADK's `min_tokens` config is checked **in addition to** the API's minimum. If the cacheable content is below either threshold, no cache is created.

For `gemini-3-pro-preview`, the API minimum is 4,096 tokens. Setting `min_tokens=4096` in `ContextCacheConfig` matches this.

### Cache Invalidation

The cache fingerprint includes system_instruction + tools + tool_config + first N contents. If ANY of these change between invocations, the cache is invalidated and must be recreated. In the LoopAgent, the thinker's `include_contents='none'` means conversation contents do not grow, so the fingerprint should be stable across iterations (only system_instruction and tools matter).

### No Caching for Interactions API

If `Gemini(use_interactions_api=True)` is used, context caching is bypassed entirely. The Interactions API maintains its own stateful conversation mechanism via `previous_interaction_id`.

### Live API Not Supported

`static_instruction` does not work with the Live API (streaming bidirectional). The Live API has its own session-based caching mechanism.

### App-Wide Scope

`context_cache_config` applies to ALL LlmAgents in the app. There is no per-agent cache configuration. In this project, this means the thinker, fetcher (if it were an LlmAgent), and any sub-agents all share the same cache config. Non-LLM agents (SequentialAgent, LoopAgent, REPLOrchestratorAgent) are unaffected since they never make LLM calls.

### Implicit Caching Is Free and Always On

Even without `context_cache_config`, Gemini's implicit caching may already be providing some cost savings. These savings are reflected in billing but NOT in the API response's `cached_content_token_count` field. The field only reports explicit cache usage.

---

## Source Files Referenced

| File | Description |
|------|-------------|
| `src/google/adk/agents/context_cache_config.py` | `ContextCacheConfig` Pydantic model |
| `src/google/adk/models/gemini_context_cache_manager.py` | Cache lifecycle manager |
| `src/google/adk/flows/llm_flows/context_cache_processor.py` | Request processor that wires cache config into LLM requests |
| `src/google/adk/models/cache_metadata.py` | Immutable cache state tracking |
| `src/google/adk/models/google_llm.py` | Gemini integration, `generate_content_async()` |
| `src/google/adk/flows/llm_flows/instructions.py` | How `static_instruction` and `instruction` are handled |
| `src/google/adk/flows/llm_flows/single_flow.py` | Request processor chain ordering |
| `src/google/adk/models/llm_request.py` | `LlmRequest` with cache fields |
| `src/google/adk/agents/llm_agent.py` | `LlmAgent.static_instruction` field definition |

## External References

- Gemini API caching docs: https://ai.google.dev/gemini-api/docs/caching
- Vertex AI caching overview: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview
- ADK caching docs: https://google.github.io/adk-docs/context/caching/
- Gemini API pricing: https://ai.google.dev/pricing
- Implicit caching announcement: https://developers.googleblog.com/en/gemini-2-5-models-now-support-implicit-caching/
