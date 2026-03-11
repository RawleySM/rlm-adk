<!-- validated: 2026-03-09 -->
<!-- sources: rlm_adk/dispatch.py, rlm_adk/callbacks/worker.py, rlm_adk/callbacks/worker_retry.py, rlm_adk/callbacks/reasoning.py, rlm_adk/agent.py, rlm_adk/orchestrator.py -->

# Dispatch & Worker Analysis: LiteLLM Integration Mapping

## 1. Executive Summary

RLM-ADK no longer uses a flat `WorkerPool` of `LlmAgent` workers. Since the REPL-to-REPLTool migration (Phases 1-5), every `llm_query()` call from REPL code spawns a **child `RLMOrchestratorAgent`** at `depth+1`. The "WorkerPool" concept survives only as `DispatchConfig` (aliased as `WorkerPool` for backward compatibility), which is now just a model-name holder.

The key consequence for LiteLLM integration: the **model string flows into `LlmAgent(model=...)` at agent-creation time** in `agent.py:create_reasoning_agent()` and `agent.py:create_child_orchestrator()`.

---

## 2. Class and Function Signatures with Line Numbers

### 2.1 `rlm_adk/dispatch.py`

**`DispatchConfig` (line 83)**
```python
class DispatchConfig:
    def __init__(
        self,
        default_model: str,
        other_model: str | None = None,
        pool_size: int = 5,
    ): ...
    def ensure_initialized(self): ...  # No-op for backward compat
```
`WorkerPool = DispatchConfig` at line 102 — backward-compatible alias.

**`create_dispatch_closures` (line 105)**
```python
def create_dispatch_closures(
    dispatch_config: DispatchConfig,
    ctx: InvocationContext,
    call_log_sink: list | None = None,
    trace_sink: list | None = None,
    depth: int = 0,
    max_depth: int = 3,
) -> tuple[Any, Any, Any]:
    # Returns: (llm_query_async, llm_query_batched_async, flush_fn)
```

**`llm_query_async` (line 561)** — inner closure
```python
async def llm_query_async(
    prompt: str,
    model: str | None = None,
    output_schema: type[BaseModel] | None = None,
) -> LLMResult:
```
Delegates to `llm_query_batched_async([prompt], ...)` and unwraps `results[0]`.

**`llm_query_batched_async` (line 601)** — inner closure
```python
async def llm_query_batched_async(
    prompts: list[str],
    model: str | None = None,
    output_schema: type[BaseModel] | None = None,
    _record_trace_entries: bool = True,
) -> list[LLMResult]:
```
Fires `asyncio.gather(*[_run_child(p, model, output_schema, idx) for ...])`.

**`_run_child` (line 313)** — inner async
```python
async def _run_child(
    prompt: str,
    model: str | None,
    output_schema: type[BaseModel] | None,
    fanout_idx: int,
) -> LLMResult:
```
Resolves `target_model = model or dispatch_config.other_model`, calls `create_child_orchestrator(model=target_model, ...)`, then runs `async for _event in child.run_async(ctx)`.

**`flush_fn` (line 689)** — inner closure
```python
def flush_fn() -> dict:
    # Returns accumulated state delta dict, resets local accumulators
```

### 2.2 `rlm_adk/callbacks/worker.py`

**`_classify_error` (line 32)**
```python
def _classify_error(error: Exception) -> str:
    # Returns: "TIMEOUT" | "RATE_LIMIT" | "AUTH" | "SERVER" | "CLIENT" | "NETWORK" | "PARSE_ERROR" | "UNKNOWN"
    # Keyed on error.code: 429 -> RATE_LIMIT, 401/403 -> AUTH, >=500 -> SERVER, >=400 -> CLIENT
```

**`worker_before_model` (line 61)** — injects `agent._pending_prompt` into `llm_request.contents`

**`worker_after_model` (line 84)** — extracts response text, writes to `agent._result`, `agent._call_record`

**`worker_on_model_error` (line 166)** — sets `agent._result_error=True`, returns synthetic `LlmResponse`

### 2.3 `rlm_adk/callbacks/worker_retry.py`

**`WorkerRetryPlugin` (line 79)** — extends `ReflectAndRetryToolPlugin`, detects empty values in `set_model_response`

**`make_worker_tool_callbacks` (line 112)** — returns `(after_tool_cb, on_tool_error_cb)`

**`_patch_output_schema_postprocessor` (line 238)** — BUG-13 monkey-patch, applied at import time

### 2.4 `rlm_adk/callbacks/reasoning.py`

**`reasoning_before_model` (line 109)** — merges instructions, records token accounting. Returns None (proceed).

**`reasoning_after_model` (line 176)** — reads `usage_metadata`, writes depth-scoped token keys.

---

## 3. Data Flow Diagrams

### 3.1 Full Call Chain: User Prompt to LLM API

```
User prompt
    |
    v
RLMOrchestratorAgent._run_async_impl()          [orchestrator.py:217]
    |-- creates LocalREPL
    |-- calls create_dispatch_closures()          [dispatch.py:105]
    |   `-- returns: (llm_query_async, llm_query_batched_async, flush_fn)
    |-- creates REPLTool(repl, flush_fn=flush_fn)
    |-- wires reasoning_agent.tools = [repl_tool, set_model_response_tool]
    |
    v
reasoning_agent.run_async(ctx)                   [ADK LlmAgent loop]
    |-- reasoning_before_model callback           [callbacks/reasoning.py:109]
    |
    v
LlmAgent calls google.genai -> Gemini API        [THE API CALL]
    |-- HttpRetryOptions(attempts=3, ...)
    |
    v
reasoning_after_model callback                   [callbacks/reasoning.py:176]
    |
    v
Model returns execute_code function call -> REPLTool.run_async()
    |-- AST rewriter rewrites llm_query() -> await llm_query_async()
    |-- executes Python code in LocalREPL
    |
    v (if code contains llm_query())
llm_query_async -> llm_query_batched_async -> asyncio.gather(_run_child(...))
    |
    v
_run_child(prompt, target_model, schema, idx)    [dispatch.py:313]
    |-- target_model = model or dispatch_config.other_model
    |-- create_child_orchestrator(model=target_model, depth=depth+1, ...)
    |-- async for event in child.run_async(ctx)   [recurses]
    |-- returns LLMResult(answer)
```

### 3.2 Model String Flow

```
RLM_ADK_MODEL env var -> _root_agent_model()
    -> create_rlm_app(model=...)
    -> create_rlm_orchestrator(model=...)
    -> create_reasoning_agent(model=...)
    -> LlmAgent(model=model_str)
    -> ADK -> google.genai -> Gemini API

For children:
    DispatchConfig.other_model
    -> _run_child: target_model = model or dispatch_config.other_model
    -> create_child_orchestrator(model=target_model)
    -> create_reasoning_agent(model=target_model)
    -> LlmAgent(model=target_model)
```

### 3.3 Error Handling Flow for 429s

```
LLM API call raises ClientError(code=429)
    |
    +-- Path A: REASONING AGENT
    |   orchestrator.py:is_transient_error(exc) -> True
    |   Retry loop: max_retries=3, exponential backoff (5s * 2^attempt)
    |   On exhaustion: yields error Event, raises
    |
    +-- Path B: CHILD AGENT (during _run_child)
        Exception propagates out of child.run_async(ctx)
        _run_child except block: _classify_error(e)
        NO RETRY — converts to LLMResult(error=True, error_category="RATE_LIMIT")
```

---

## 4. WorkerPool Architecture (Current State)

`WorkerPool` / `DispatchConfig` is now a thin data holder:
```
DispatchConfig
    fields:
        default_model: str      -- model for reasoning agent
        other_model: str        -- model for child dispatches (defaults to default_model)
        pool_size: int = 5      -- retained for backward compat, not used
```

**Concurrency control** via semaphore in `create_dispatch_closures`:
- `_child_semaphore = asyncio.Semaphore(max_concurrent)` where `max_concurrent = RLM_MAX_CONCURRENT_CHILDREN` (default 3)

---

## 5. Existing Retry and Backoff Logic

| Layer | Mechanism | Scope | Gap |
|-------|-----------|-------|-----|
| `google.genai` SDK | `HttpRetryOptions(attempts=3)` | All LlmAgent calls | Retries before raising |
| `orchestrator.py` retry loop | `is_transient_error()` + backoff | Reasoning agent at any depth | Only for agent's own `run_async()` |
| `_run_child` except block | `_classify_error(e)` | Child-level errors | **NO RETRY** — converts to error LLMResult |
| REPL code | Manual check `result.error_category` | User code | Requires explicit retry logic |

**Critical gap**: Child dispatches via `_run_child` have NO retry for 429s. LiteLLM addresses this by routing to fallback models/deployments before the exception surfaces.

---

## 6. LiteLLM Integration Strategies

### Strategy A: ADK Native `LiteLlm()` Model Object (Recommended)

ADK's `LlmAgent.model` already accepts `LiteLlm()` objects natively (see `google.adk.models.lite_llm`).

```python
from google.adk.models.lite_llm import LiteLlm
LlmAgent(model=LiteLlm(model="openai/gpt-4o"), ...)
```

**Integration point**: `create_reasoning_agent()` at `agent.py:212` — wrap model string in `LiteLlm()`.

### Strategy B: `before_model_callback` Intercept

`reasoning_before_model` (`callbacks/reasoning.py:109`) fires before every model call. Returning non-None `LlmResponse` short-circuits `google.genai`. This is the hook for custom routing via `litellm.Router.acompletion()`.

### Strategy C: LiteLLM Proxy Server (External)

Deploy LiteLLM proxy as OpenAI-compatible endpoint. Lowest code change but adds operational complexity.

---

## 7. Key Code Locations to Modify

| File | Line | What to Change | Why |
|------|------|----------------|-----|
| `rlm_adk/agent.py` | 151 | `create_reasoning_agent` signature | Accept model as `str | LiteLlm` |
| `rlm_adk/agent.py` | 212 | `LlmAgent(model=...)` | Pass `LiteLlm()` object |
| `rlm_adk/agent.py` | 123 | `_build_generate_content_config` | Gate for non-Gemini models |
| `rlm_adk/agent.py` | 196 | `BuiltInPlanner` | Gate for Gemini-only |
| `rlm_adk/agent.py` | 274 | `create_child_orchestrator` | Propagate LiteLlm model |
| `rlm_adk/dispatch.py` | 83 | `DispatchConfig` | Accept `str | LiteLlm` for model fields |
| `rlm_adk/orchestrator.py` | 69 | `is_transient_error` | Add LiteLLM exception types |
| `rlm_adk/callbacks/worker.py` | 32 | `_classify_error` | Handle `.status_code` not `.code` |
| `rlm_adk/callbacks/reasoning.py` | 176 | `reasoning_after_model` | Handle OpenAI-format usage metadata |

---

## 8. Essential Files

| File | Role |
|------|------|
| `rlm_adk/dispatch.py` | `DispatchConfig`, dispatch closures, `_run_child`, `flush_fn` |
| `rlm_adk/agent.py` | `create_reasoning_agent`, `create_child_orchestrator`, `_build_generate_content_config` |
| `rlm_adk/orchestrator.py` | Retry loop, `is_transient_error()`, tool wiring |
| `rlm_adk/callbacks/reasoning.py` | `reasoning_before_model` — primary LiteLLM intercept point |
| `rlm_adk/callbacks/worker.py` | `_classify_error` — error categorization |
| `rlm_adk/callbacks/worker_retry.py` | `WorkerRetryPlugin`, BUG-13 patch |
| `rlm_adk/tools/repl_tool.py` | `REPLTool.run_async()` — calls `flush_fn()` |
| `rlm_adk/state.py` | State key constants, `depth_key()` |
