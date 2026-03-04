# Provider-Contract Fake: Design Specification

## Architecture Decision

### Approach: Dual-Layer Fake (HTTP Server + Plugin Short-Circuit)

We implement **two complementary interception layers** rather than choosing one:

| Layer | What It Tests | Implementation |
|---|---|---|
| **Layer 1: HTTP Fake Server** | Transport wiring, request serialization, response deserialization, header/auth plumbing, retry at SDK transport boundary, error parsing | `aiohttp` server matching Gemini API wire contract |
| **Layer 2: FakeModelPlugin** | ADK plugin chain, callback ordering, `LlmResponse` construction, fast in-process deterministic tests | ADK `BasePlugin` subclass returning canned `LlmResponse` |

**Rationale**: The HTTP fake validates the real production wiring (network -> SDK -> ADK pipeline). The plugin fake provides fast, no-server tests for logic-level validation. Both share the same fixture format.

### Why Not Just One Layer?

- HTTP-only: Slow for CI, complex server lifecycle management
- Plugin-only: Skips the entire transport/serialization path — misses the most dangerous bugs (URL construction, header loss, response parsing, retry behavior)

The HTTP fake is the primary deliverable. The plugin fake is a bonus that reuses the fixture format.

---

## Endpoint Compatibility Scope

### Required (MVP)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1beta/models/{model}:generateContent` | Non-streaming text generation |

### Accepted but Ignored

| Field | Treatment |
|---|---|
| `systemInstruction` | Accepted, not validated |
| `generationConfig.thinkingConfig` | Accepted, not used for response selection |
| `safetySettings` | Accepted, ignored |
| `tools` / `toolConfig` | Accepted, ignored |
| Any unknown top-level fields | Accepted, ignored (forward-compatible) |

### Not Implemented

| Feature | Why |
|---|---|
| `streamGenerateContent` | Codebase does not use streaming |
| Function calling responses | Codebase does not use tool/function calls |
| `countTokens` | Not on critical path |
| Model listing | Not on critical path |

---

## Module Layout

```
tests_rlm_adk/
  provider_fake/
    __init__.py
    server.py              # aiohttp fake Gemini server
    plugin.py              # FakeModelPlugin (before_model_callback short-circuit)
    fixtures.py            # Fixture loader, ScenarioRouter
    conftest.py            # pytest fixtures: server lifecycle, env var injection
  fixtures/
    provider_fake/
      happy_path_single_iteration.json
      multi_iteration_with_workers.json
      fault_429_then_success.json
      malformed_response.json
      worker_batch_dispatch.json
```

---

## Fake Server Architecture

### Server: `server.py`

```
FakeGeminiServer
  ├── __init__(host, port, scenario_router)
  ├── start() -> URL
  ├── stop()
  ├── handle_generate_content(request) -> Response
  ├── request_log: list[dict]      # sanitized request/response trace
  └── reset()                      # clear state between tests
```

**Request handling flow**:
1. Parse JSON body (accept any valid JSON, ignore unknown fields)
2. Extract model name from URL path
3. Validate `x-goog-api-key` header is present (any value accepted)
4. Consult `ScenarioRouter` for the response to return
5. Return JSON response with correct status code
6. Log sanitized request/response pair

### ScenarioRouter: `fixtures.py`

```
ScenarioRouter
  ├── __init__(fixture_path_or_dict)
  ├── next_response(request_body) -> (status_code, response_body)
  ├── call_index: int              # monotonic call counter
  ├── remaining_responses: int
  └── reset()
```

**Matching strategy**: **Sequential with fault injection overlay**

- Responses are consumed in order from the fixture's `responses` array
- If `call_index` appears in `fault_injections`, return the specified error instead of the normal response
- This is deterministic, simple, and sufficient for scripted multi-turn scenarios

### Why Sequential (not prompt-hash or content-matching)?

1. **Determinism**: Exact same order every run — no hash collisions or regex fragility
2. **Simplicity**: Fixtures are human-readable ordered lists
3. **Debuggability**: "Call #3 returned fixture response #3" is trivially traceable
4. **Multi-turn support**: The orchestrator's iteration loop naturally produces a predictable call sequence

Content-matching could be added later as an optional overlay but is not needed for MVP.

---

## Fixture Schema

See `docs/provider_fake/fixture-strategy.md` for full details. Summary:

```json
{
  "scenario_id": "happy_path_single_iteration",
  "description": "Reasoning agent returns FINAL(42) on first iteration",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5
  },
  "responses": [
    {
      "call_index": 0,
      "caller": "reasoning",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {"role": "model", "parts": [{"text": "FINAL(42)"}]},
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {
          "promptTokenCount": 100,
          "candidatesTokenCount": 10,
          "totalTokenCount": 110
        },
        "modelVersion": "gemini-fake"
      }
    }
  ],
  "fault_injections": [],
  "expected": {
    "final_answer": "42",
    "total_iterations": 1,
    "total_model_calls": 1
  }
}
```

---

## Determinism Strategy

### What makes tests deterministic?

1. **Fixed fixture responses**: Every model call returns a pre-defined response in order
2. **Env-controlled model name**: `RLM_ADK_MODEL=gemini-fake` (matches `gemini-.*` regex)
3. **Thinking disabled**: `thinking_budget=0` avoids thought-part variability
4. **No network dependencies**: All traffic stays on localhost
5. **Fresh state per test**: Each test creates a new `InMemorySessionService` session
6. **Fixed random seeds**: `REQUEST_ID` is set deterministically in fixtures

### What is NOT deterministic?

1. Exact wall-clock timings (observability metrics will vary)
2. asyncio task scheduling order (but results are deterministic by fixture ordering)

---

## Fault Injection Strategy

### Supported Fault Types

| Fault | Status | Body | Tests |
|---|---|---|---|
| Rate limit | 429 | `{"error":{"code":429,"message":"...","status":"RESOURCE_EXHAUSTED"}}` | SDK + app-level retry |
| Server error | 500 | `{"error":{"code":500,"message":"...","status":"INTERNAL"}}` | SDK + app-level retry |
| Timeout | 408 | `{"error":{"code":408,"message":"...","status":"DEADLINE_EXCEEDED"}}` | Retry behavior |
| Bad request | 400 | `{"error":{"code":400,"message":"...","status":"INVALID_ARGUMENT"}}` | Non-retryable error path |
| Malformed JSON | 200 | `{broken json` | Parser robustness |
| Empty candidates | 200 | `{"candidates":[],"usageMetadata":{...}}` | Edge case handling |
| Missing parts | 200 | `{"candidates":[{"content":{"role":"model","parts":[]},...}]}` | Edge case handling |
| Connection refused | N/A | Server not started | Transport error handling |

### Fault Injection in Fixtures

```json
"fault_injections": [
  {
    "call_index": 0,
    "fault_type": "http_error",
    "status": 429,
    "body": {"error": {"code": 429, "message": "Rate limited", "status": "RESOURCE_EXHAUSTED"}}
  },
  {
    "call_index": 2,
    "fault_type": "malformed_json",
    "body_raw": "{this is not json"
  },
  {
    "call_index": 4,
    "fault_type": "delay",
    "delay_seconds": 5.0
  }
]
```

---

## Integration with ADK Config

### Zero Production Code Changes

The fake integrates entirely through environment variables and test-time configuration:

```python
# In test conftest.py
@pytest.fixture
async def fake_gemini(request):
    """Start fake Gemini server and configure env vars."""
    fixture_path = request.param  # parametrized with fixture file path
    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(host="127.0.0.1", port=0, router=router)  # port=0 = random
    url = await server.start()

    old_env = {k: os.environ.get(k) for k in ["GOOGLE_GEMINI_BASE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY"]}
    os.environ["GOOGLE_GEMINI_BASE_URL"] = url
    os.environ["GEMINI_API_KEY"] = "fake-key-for-testing"
    os.environ.pop("GOOGLE_API_KEY", None)  # avoid precedence issues

    yield server

    await server.stop()
    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
```

### ADK Runner Creation in Tests

```python
async def test_happy_path(fake_gemini):
    runner = create_rlm_runner(
        model="gemini-fake",
        thinking_budget=0,
        plugins=[],       # no debug/observability noise
        debug=False,
    )
    session = await runner.session_service.create_session(
        app_name="rlm_adk", user_id="test",
    )
    events = []
    content = types.Content(role="user", parts=[types.Part.from_text(text="test prompt")])
    async for event in runner.run_async(
        user_id="test", session_id=session.id, new_message=content,
    ):
        events.append(event)

    assert fake_gemini.router.call_index == 1  # exactly one model call
    # Assert on final state, events, etc.
```

---

## CI Integration

### How CI Runs It

```yaml
# In .github/workflows/test.yml or similar
- name: Run provider fake tests
  run: |
    .venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -v
  env:
    GEMINI_API_KEY: fake-key-for-testing
    # GOOGLE_GEMINI_BASE_URL is set dynamically by the test fixture
```

No external services needed. The fake server starts in-process on a random port and shuts down after each test.

### Test Isolation

- Each test gets its own `FakeGeminiServer` instance (random port)
- Each test gets its own `ScenarioRouter` (fresh call counter)
- Each test creates its own `Runner` with `InMemorySessionService`
- No shared state between tests
- Tests can run in parallel via `pytest-xdist` if needed

---

## Test Matrix

| # | Test | Layer Validated | Fixture | Assertions |
|---|---|---|---|---|
| 1 | Happy path deterministic response | Transport + ADK e2e | `happy_path_single_iteration` | Final answer = "42", 1 model call, correct state |
| 2 | Multi-iteration with workers | Transport + dispatch + REPL | `multi_iteration_with_workers` | Worker dispatched, REPL executed, final answer correct |
| 3 | Structured JSON response parsing | Response deserialization | `happy_path_single_iteration` | `usageMetadata` fields parsed correctly |
| 4 | Retryable error (429) then success | Retry at SDK transport boundary | `fault_429_then_success` | First call returns 429, retry succeeds, final answer correct |
| 5 | Malformed response handling | Parser robustness | `malformed_response` | Graceful error, no crash |
| 6 | Worker batch dispatch | Transport + ParallelAgent | `worker_batch_dispatch` | Multiple workers dispatched and results collected |

---

## Rollback / Fallback

If exact Gemini wire parity proves too complex:

1. **Fallback to plugin-only**: Use `FakeModelPlugin` for all deterministic tests. Loses transport validation but keeps logic validation.
2. **Fallback to partial wire**: Implement only the response body parsing, skip header/auth validation. Still better than mocks.
3. **Record/replay mode**: Record a real Gemini API session, store as fixtures, replay from the fake server. Gives exact wire parity for recorded scenarios.

---

## Record/Replay Option

Future enhancement (not MVP):

```python
class RecordingProxy:
    """Transparent proxy that records real Gemini API traffic as fixtures."""
    async def handle(self, request):
        # Forward to real Gemini API
        response = await forward_to_real_api(request)
        # Record request/response pair
        self.recordings.append({
            "request": sanitize(request),
            "response": response.json(),
            "status": response.status
        })
        return response

    def save_fixture(self, path):
        """Save recorded session as a fixture file."""
```

This would let us capture real API behavior once and replay it indefinitely.
