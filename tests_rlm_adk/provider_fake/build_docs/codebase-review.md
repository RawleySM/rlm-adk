# RLM-ADK Provider Fake: Codebase Review

## 1. Executive Summary

The `rlm-adk` system is a Google ADK (Agent Development Kit) application that makes all model calls through the `google.genai` client library, specifically via the `Gemini` backend class inside ADK's `google.adk.models.google_llm` module. Every model call — for both the reasoning agent and the worker pool — ultimately reaches `client.aio.models.generate_content()` on a `google.genai.Client` instance.

**Key findings for building a local fake Gemini API:**

- There are exactly **two call sites** that touch real model APIs: (1) `reasoning_agent` (one `LlmAgent` that drives the main RLM loop) and (2) `WorkerPool` workers (a pool of `LlmAgent` instances for sub-LM calls dispatched via `ParallelAgent`). Both use the same ADK `LlmAgent` -> `Gemini` -> `google.genai.Client` pathway.
- The **API endpoint** defaults to `https://generativelanguage.googleapis.com/` (Gemini Developer API, not Vertex AI). It is controlled by `HttpOptions.base_url`, which can be set via the `GOOGLE_GEMINI_BASE_URL` environment variable or `google.genai._base_url.set_default_base_urls()`. This is the cleanest injection point.
- The **API key** is read from `GOOGLE_API_KEY` (preferred) or `GEMINI_API_KEY` env var. The fake server must accept any value for this header (`x-goog-api-key`).
- The **model name** for the CLI-discoverable `app` object is controlled by `RLM_ADK_MODEL` env var (default `gemini-3.1-pro-preview`). Workers inherit the same model string. Both can be overridden freely.
- **No streaming** is used in the normal path. The ADK `LlmAgent` flow calls `generate_content` (non-streaming) via `await self.api_client.aio.models.generate_content(...)`. Streaming is only used if `RunConfig(streaming_mode=StreamingMode.SSE)` is explicitly set, which this application does not do.
- **No tool/function calls** are used. The reasoning agent and workers use plain text responses only. The `before_model_callback` for the reasoning agent (`reasoning_before_model`) and workers (`worker_before_model`) reconstruct `llm_request.contents` entirely from scratch, making it straightforward to predict exactly what the fake must receive.
- The existing `before_model_callback` is **the ideal hook** for returning a pre-canned `LlmResponse` before the real API is called, making callback-level interception viable as an alternative to running a fake HTTP server.

---

## 2. File Map

### Core Application Files

| File | Class / Function | Role |
|---|---|---|
| `rlm_adk/agent.py` | `create_reasoning_agent()` line 140, `create_rlm_orchestrator()` line 200, `create_rlm_app()` line 281, `create_rlm_runner()` line 344, `_root_agent_model()` line 445 | Factory functions; wires model string, retry config, callbacks, plugins, services |
| `rlm_adk/orchestrator.py` | `RLMOrchestratorAgent` line 66, `_run_async_impl()` line 92 | Main iteration loop; dispatches to `reasoning_agent.run_async(ctx)` |
| `rlm_adk/dispatch.py` | `WorkerPool` line 50, `create_dispatch_closures()` line 201, `llm_query_async()` line 227, `llm_query_batched_async()` line 242 | Worker pool management; dispatches sub-LM queries via `worker.run_async(ctx)` and `ParallelAgent.run_async(ctx)` |
| `rlm_adk/state.py` | All constants | State key definitions used across all modules |
| `rlm_adk/types.py` | `REPLResult`, `CodeBlock`, `RLMIteration`, `RLMChatCompletion` | Data structures for REPL execution results |

### Callback Files

| File | Function | Hook Point | What It Does |
|---|---|---|---|
| `rlm_adk/callbacks/reasoning.py` | `reasoning_before_model()` line 69 | `before_model_callback` on `reasoning_agent` | Rebuilds `llm_request.contents` from `message_history` state; sets `system_instruction`; records `REASONING_CALL_START` |
| `rlm_adk/callbacks/reasoning.py` | `reasoning_after_model()` line 158 | `after_model_callback` on `reasoning_agent` | Extracts text from `llm_response.content.parts` (skipping `part.thought`); writes to `LAST_REASONING_RESPONSE` state; reads `usage_metadata.prompt_token_count` / `candidates_token_count` |
| `rlm_adk/callbacks/worker.py` | `worker_before_model()` line 20 | `before_model_callback` on each worker `LlmAgent` | Reads `agent._pending_prompt`; sets `llm_request.contents` to a single `Content(role="user", parts=[Part.from_text(text=prompt)])` |
| `rlm_adk/callbacks/worker.py` | `worker_after_model()` line 71 | `after_model_callback` on each worker `LlmAgent` | Extracts text from `llm_response.content.parts`; writes to `agent._result` and `agent._result_ready`; reads `usage_metadata` |
| `rlm_adk/callbacks/worker.py` | `worker_on_model_error()` line 109 | `on_model_error_callback` on each worker `LlmAgent` | Catches LLM errors; writes error string to `agent._result`; returns synthetic `LlmResponse` to prevent `ParallelAgent` crash |

### Plugin Files

| File | Class | Callbacks Implemented | Impact on Model Calls |
|---|---|---|---|
| `rlm_adk/plugins/observability.py` | `ObservabilityPlugin` | all (observe-only) | None — returns `None` from all model callbacks |
| `rlm_adk/plugins/debug_logging.py` | `DebugLoggingPlugin` | all (observe-only) | None — logs but always returns `None` |
| `rlm_adk/plugins/sqlite_tracing.py` | `SqliteTracingPlugin` | all (observe-only) | None — writes spans to SQLite but returns `None` |
| `rlm_adk/plugins/langfuse_tracing.py` | `LangfuseTracingPlugin` | none (OTel auto-instrumentation) | None — initialization-only plugin |
| `rlm_adk/plugins/cache.py` | `CachePlugin` (not in default stack) | `before_model`, `after_model` | Could short-circuit model calls by returning cached `LlmResponse` |
| `rlm_adk/plugins/context_snapshot.py` | `ContextWindowSnapshotPlugin` | `before_model`, `after_model` | Observe-only |

### ADK Internal Files (installed package, read-only)

| File | Class | Role |
|---|---|---|
| `.venv/.../google/adk/models/google_llm.py` | `Gemini` line 83 | ADK's Gemini backend; builds `google.genai.Client`; calls `client.aio.models.generate_content()` |
| `.venv/.../google/adk/models/registry.py` | `LLMRegistry` line 38 | Maps model name string (regex `gemini-.*`) to `Gemini` class |
| `.venv/.../google/genai/_base_url.py` | `get_base_url()` line 34, `set_default_base_urls()` line 25 | Resolves base URL: `HttpOptions.base_url` > `set_default_base_urls()` > `GOOGLE_GEMINI_BASE_URL` env var |
| `.venv/.../google/genai/_api_client.py` | `BaseApiClient.__init__()` line 544 | Reads `GOOGLE_API_KEY` / `GEMINI_API_KEY`; sets `base_url` to `https://generativelanguage.googleapis.com/`; sets `api_version` to `v1beta`; attaches `x-goog-api-key` header |

### Test Files

| File | What It Tests | Mock Strategy |
|---|---|---|
| `tests_rlm_adk/conftest.py` | Shared fixtures | Provides real `LocalREPL` instances only |
| `tests_rlm_adk/test_adk_orchestrator_loop.py` | Parsing, iteration format, AST structure | No model calls |
| `tests_rlm_adk/test_adk_dispatch_worker_pool.py` | `WorkerPool` routing, pool sizing | `MagicMock()` for `InvocationContext`; empty-prompts path only |
| `tests_rlm_adk/test_adk_persistence.py` | `LocalREPL` persistence | No model calls |
| `tests_rlm_adk/test_adk_ast_rewriter.py` | AST transformation logic | No model calls |
| `tests_rlm_adk/test_adk_types.py` | Data structures | No model calls |

### Replay Files

| File | Purpose |
|---|---|
| `tests_rlm_adk/replay/test_repo_analysis.json` | `adk run --replay` fixture: initial state + user query |
| `tests_rlm_adk/replay/test_basic_context.json` | Simple context test replay |
| `tests_rlm_adk/replay/test_structured_pipeline.json` | Structured pipeline replay |

---

## 3. Model Call Flow Diagram

```
User / adk CLI
      |
      v
Runner.run_async(user_id, session_id, new_message)
      |
      v
App (plugins=[ObservabilityPlugin, DebugLoggingPlugin, SqliteTracingPlugin])
      |
      v
RLMOrchestratorAgent._run_async_impl(ctx)   [orchestrator.py:92]
      |
      |-- yield Event(state_delta={initial_state})
      |
      |-- for i in range(max_iterations):
      |       |
      |       |-- [1] REASONING AGENT CALL
      |       |       |
      |       |       +-- plugin.before_agent_callback() x3 (observe only)
      |       |       +-- plugin.before_model_callback() x3 (observe only, return None)
      |       |       +-- reasoning_before_model(ctx, llm_request)    [callbacks/reasoning.py:69]
      |       |       |       reads state[MESSAGE_HISTORY] -> builds llm_request.contents
      |       |       |       builds system_instruction from static_instruction + dynamic_instruction
      |       |       |       returns None (proceeds to model call)
      |       |       |
      |       |       +-- Gemini.generate_content_async(llm_request)  [google_llm.py:153]
      |       |       |       |
      |       |       |       +-- google.genai.Client.aio.models.generate_content(
      |       |       |               model=llm_request.model,
      |       |       |               contents=llm_request.contents,
      |       |       |               config=llm_request.config
      |       |       |           )
      |       |       |       HTTP POST .../v1beta/models/{model}:generateContent
      |       |       |       Header: x-goog-api-key: <GEMINI_API_KEY>
      |       |       |
      |       |       +-- reasoning_after_model(ctx, llm_response)    [callbacks/reasoning.py:158]
      |       |       |       extracts llm_response.content.parts[*].text (skipping .thought)
      |       |       |       writes state[LAST_REASONING_RESPONSE] = response_text
      |       |       |       reads llm_response.usage_metadata
      |       |       |       returns None
      |       |       |
      |       |       +-- plugin.after_model_callback() x3 (observe only)
      |       |       +-- plugin.after_agent_callback() x3 (observe only)
      |       |       +-- yield Event(content=response_content)
      |       |
      |       |-- drain event_queue
      |       |-- response = ctx.session.state[LAST_REASONING_RESPONSE]
      |       |-- code_blocks = find_code_blocks(response)
      |       |
      |       |-- for code in code_blocks:
      |       |       if has_llm_calls(code):
      |       |           rewrite_for_async(code) -> wraps in async def _repl_exec()
      |       |           repl.execute_code_async(code, repl_exec_fn)
      |       |       else:
      |       |           repl.execute_code(code)
      |       |
      |       |-- [2] WORKER DISPATCH (when llm_query called from REPL code)
      |       |       |
      |       |       +-- llm_query_batched_async(prompts)            [dispatch.py:242]
      |       |       |       per worker LlmAgent:
      |       |       |           worker_before_model -> sets llm_request.contents
      |       |       |           Gemini.generate_content_async -> HTTP POST
      |       |       |           worker_after_model -> extracts agent._result
      |       |       |
      |       |-- drain event_queue (mid-iteration)
      |       |-- final_answer = find_final_answer(response)
      |       |-- if final_answer: yield terminating events, return
      |       |-- else: message_history.extend(format_iteration(...))
```

---

## 4. Current Test Architecture

### What Is Tested Today

The existing test suite contains **zero end-to-end tests that invoke model APIs**. All tests are pure-Python unit tests that test parsing, state, dispatch routing, etc. No ADK runner is used, no model calls are made.

### How Mock `InvocationContext` Is Constructed

```python
ctx = MagicMock()
ctx.session.state = {}
```

For any test that dispatches real workers, `ctx._invocation_context.agent` must also be satisfied.

### Replay Mechanism

The `adk run --replay` mechanism reads a JSON file that provides initial state and user queries. It makes real model calls through the real ADK runner.

---

## 5. Injection Point Recommendations

### Option A: Environment Variable — Preferred for HTTP Fake Server

The `google-genai` client reads `GOOGLE_GEMINI_BASE_URL`:

```bash
GOOGLE_GEMINI_BASE_URL=http://localhost:9999   # points all requests to local fake
GEMINI_API_KEY=fake-key-any-value              # accepted by fake without validation
RLM_ADK_MODEL=gemini-fake                     # model name passed through as-is
```

**URL pattern the fake must serve:**

```
POST http://localhost:9999/v1beta/models/{model_name}:generateContent
Header: x-goog-api-key: fake-key-any-value
Header: Content-Type: application/json
```

### Option B: `Gemini.base_url` Field on the ADK Model Object

Pass `Gemini(model="gemini-fake", base_url="http://localhost:9999")` instead of a string to `LlmAgent`. Requires modifying factory functions.

### Option C: `before_model_callback` Short-Circuit — Preferred for Pure-Python Tests

A `FakeModelPlugin` can return a pre-canned `LlmResponse` from `before_model_callback`, skipping the API call entirely. No HTTP server needed.

### Option D: `google.genai._base_url.set_default_base_urls()` — Programmatic Global Override

```python
from google.genai._base_url import set_default_base_urls
set_default_base_urls(gemini_url="http://localhost:9999", vertex_url=None)
```

Must be called before any `LlmAgent` makes its first call.

---

## 6. Request / Response Schema Details

### What the Fake Must Accept (Request)

```
POST /v1beta/models/{model_name}:generateContent
```

Request body (`GenerateContentRequest`):
```json
{
  "contents": [
    {"role": "user", "parts": [{"text": "...prompt text..."}]},
    {"role": "model", "parts": [{"text": "...assistant response..."}]}
  ],
  "systemInstruction": {
    "parts": [{"text": "...system prompt..."}]
  },
  "generationConfig": {
    "temperature": 0.0,
    "thinkingConfig": {
      "includeThoughts": true,
      "thinkingBudget": 1024
    }
  }
}
```

### What the Fake Must Return (Response)

```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [{"text": "...response text here..."}]
      },
      "finishReason": "STOP"
    }
  ],
  "usageMetadata": {
    "promptTokenCount": 100,
    "candidatesTokenCount": 50,
    "totalTokenCount": 150
  },
  "modelVersion": "gemini-fake"
}
```

### Critical Fields Accessed by Project Code

| Field | Where Accessed | Notes |
|---|---|---|
| `candidates[0].content.parts[*].text` | `reasoning_after_model`, `worker_after_model` | Must be non-empty |
| `candidates[0].content.parts[*].thought` | Both after_model callbacks | Parts with `thought=True` are excluded. Not needed in fake responses. |
| `usageMetadata.promptTokenCount` | After-model callbacks, observability, debug | Accessed via snake_case alias |
| `usageMetadata.candidatesTokenCount` | Same locations | Accessed via snake_case alias |
| `modelVersion` | `observability.py` | Falls back to "unknown" if absent |

---

## 7. Configuration Reference

### Environment Variables

| Variable | Default | Effect |
|---|---|---|
| `RLM_ADK_MODEL` | `gemini-3.1-pro-preview` | Model name for root agent |
| `GEMINI_API_KEY` | (none) | API key for Gemini |
| `GOOGLE_API_KEY` | (none) | API key, takes precedence |
| `GOOGLE_GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com/` | **Primary injection point** |
| `RLM_MAX_ITERATIONS` | `30` | Max orchestrator iterations |
| `RLM_LLM_MAX_RETRIES` | `3` | Retry count on transient errors |
| `RLM_LLM_RETRY_DELAY` | `5.0` | Base delay for retry backoff |
| `RLM_MAX_CONCURRENT_WORKERS` | `4` | Max parallel workers per batch |

### Retry Logic

- Application-level (`orchestrator.py` lines 181-201): Retries `ServerError` and `ClientError` with status `{408, 429, 500, 502, 503, 504}`. Exponential backoff: `delay = base_delay * (2 ** attempt)`.
- SDK-level (`HttpRetryOptions(attempts=3, initial_delay=1.0, max_delay=60.0)`): Configured in `_build_generate_content_config()`.

---

## 8. Risks and Open Questions

### Risk 1: `@cached_property` on `Gemini.api_client`
Once the `Client` is constructed, `base_url` is frozen. `GOOGLE_GEMINI_BASE_URL` must be set before the first model call.

### Risk 2: Worker Pool Workers Are Pre-Allocated
`api_client` is `@cached_property` so workers pick up env var overrides on first use.

### Risk 3: `thinking_budget` Field in Request
Set `thinking_budget=0` to skip `BuiltInPlanner` for simpler fake responses.

### Risk 4: No Existing E2E Test Infrastructure
No existing tests go through `runner.run_async()`. Full scaffolding required.

### Risk 5: `include_contents='none'` on Workers
Workers always get a single-turn request.

### Risk 6: ParallelAgent Adds Workers as Sub-Agents
`worker.parent_agent = None` must be cleared after each batch (already handled in production code).

### Risk 7: `on_model_error_callback` Returns Synthetic `LlmResponse`
The fake must return error HTTP status codes (429, 500) to test this path.

---

## 9. Minimal Config Change to Route All Traffic Through Fake

```python
import os
import pytest

@pytest.fixture(autouse=True, scope="session")
def fake_gemini_endpoint():
    os.environ["GOOGLE_GEMINI_BASE_URL"] = "http://localhost:9999"
    os.environ["GEMINI_API_KEY"] = "fake-key-for-testing"
    yield
    del os.environ["GOOGLE_GEMINI_BASE_URL"]
    del os.environ["GEMINI_API_KEY"]
```

The fake must serve:
```
POST /v1beta/models/{any-model-name}:generateContent
-> 200 OK, Content-Type: application/json

{
  "candidates": [{
    "content": {"role": "model", "parts": [{"text": "FINAL(test answer)"}]},
    "finishReason": "STOP"
  }],
  "usageMetadata": {
    "promptTokenCount": 10,
    "candidatesTokenCount": 5,
    "totalTokenCount": 15
  }
}
```
