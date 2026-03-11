<!-- validated: 2026-03-09 -->
<!-- sources: tests_rlm_adk/provider_fake/, tests_rlm_adk/test_fmea_e2e.py, tests_rlm_adk/test_provider_fake_e2e.py, rlm_adk_docs/testing.md -->

# Testing Patterns Analysis for LiteLLM Integration

## 1. Replay Fixture Format Specification

Replay fixtures live in `tests_rlm_adk/replay/*.json`. They feed `adk run --replay` — not pytest directly.

### Schema

```json
{
  "state": {
    "app:max_iterations": 10,
    "app:max_depth": 3
  },
  "queries": [
    "First user prompt string",
    "Second user prompt string"
  ]
}
```

Top-level keys: `state` (dict) and `queries` (non-empty list of strings). No other keys allowed. Schema validated by `tests_rlm_adk/test_e2e_replay.py::TestReplaySchema`.

### Running a Replay

```bash
.venv/bin/adk run --replay tests_rlm_adk/replay/recursive_ping.json rlm_adk
```

Replay does NOT make assertions — it drives the agent with pre-written prompts against a live LLM.

### Existing Replay Fixtures

| File | What It Tests |
|------|--------------|
| `recursive_ping.json` | 3-layer recursive dispatch, validates `pong` propagates up |
| `test_structured_pipeline.json` | `set_model_response` structured output via `llm_query` |
| `test_recursive_security_audit.json` | Multi-depth repo analysis |
| `test_repo_analysis.json` | `pack_repo` skill + multi-iteration analysis |
| `test_basic_context.json` | Minimal context sanity check |

---

## 2. Provider-Fake Architecture

All provider-fake tests are network-free and fully deterministic.

### Component Map

```
tests_rlm_adk/provider_fake/
  server.py          — FakeGeminiServer (aiohttp, POST /v1beta/models/{model}:generateContent)
  fixtures.py        — ScenarioRouter, ContractResult, matcher operators
  contract_runner.py — run_fixture_contract(), run_fixture_contract_with_plugins()
  conftest.py        — fake_gemini fixture, FIXTURE_DIR constant

tests_rlm_adk/fixtures/provider_fake/
  *.json             — 36+ fixture files
```

### FakeGeminiServer

aiohttp server on `127.0.0.1:0` (OS-assigned port). Single route: `POST /v1beta/models/{model}:generateContent`. Validates `x-goog-api-key` header presence (missing = 401).

### ScenarioRouter

Thread-safe FIFO sequential response dispatcher. Holds fixture's `responses` list and `fault_injections` dict. For each request:
1. Checks `fault_injections` keyed by `call_index` first
2. If no fault, consumes next entry from `responses` (incrementing `_response_pointer`)
3. If exhausted, returns empty-text fallback

### ContractResult / PluginContractResult

```python
@dataclasses.dataclass
class PluginContractResult:
    contract: ContractResult
    events: list[Any]
    final_state: dict[str, Any]
    artifact_service: InMemoryArtifactService
    traces_db_path: str | None
    router: ScenarioRouter
```

### Environment Variable Wiring

The contract runner overrides env vars to redirect `google-genai` SDK traffic to the fake server:

| Variable | Value During Test |
|----------|------------------|
| `GOOGLE_GEMINI_BASE_URL` | `http://127.0.0.1:<port>` |
| `GEMINI_API_KEY` | `"fake-key-for-testing"` |
| `GOOGLE_API_KEY` | Deleted |
| `RLM_ADK_MODEL` | `config.model` from fixture |

### Matcher Operators

Used in `expected_state` and `expected_contract`:

| Operator | Meaning |
|----------|---------|
| `{"$gt": N}` | Greater-than |
| `{"$gte": N}` | Greater-than-or-equal |
| `{"$lt": N}` | Less-than |
| `{"$lte": N}` | Less-than-or-equal |
| `{"$not_none": true}` | Not None |
| `{"$not_empty": true}` | Not empty |
| `{"$has_key": "k"}` | Dict contains key |
| `{"$type": "list"}` | Type check |
| `{"$contains": "needle"}` | Substring match |
| `{"$len_gte": N}` | Length >= N |
| `{"$len_eq": N}` | Length == N |
| `{"$absent": true}` | Key must NOT exist |

---

## 3. Fixture JSON Schema (Complete)

```json
{
  "scenario_id": "unique_snake_case_id",
  "description": "Human-readable description",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.01,
    "max_retries": 3,
    "initial_state": { "app:max_depth": 3 }
  },
  "responses": [
    {
      "call_index": 0,
      "caller": "reasoning",
      "status": 200,
      "body": { "candidates": [...], "usageMetadata": {...} }
    }
  ],
  "fault_injections": [
    {
      "call_index": 1,
      "fault_type": "http_error",
      "status": 429,
      "body": { "error": {"message": "rate limited", "code": 429} }
    }
  ],
  "expected": { "final_answer": "...", "total_iterations": 2 },
  "expected_state": { "obs:child_dispatch_count": 3 },
  "expected_contract": { "callers": { "sequence": [...], "count": 4 } }
}
```

### Key Design Rules

1. `responses` consumed FIFO — `call_index` is annotation only, not routing
2. `fault_injections` ARE keyed by `call_index`
3. `usageMetadata` is required in every response body
4. Final reasoning response uses `FINAL(answer text)` in a text part
5. Workers respond via `set_model_response` functionCall

---

## 4. Existing `llm_query_batched` Test Coverage

### Fixture Files

| Fixture | What It Tests |
|---------|--------------|
| `structured_output_batched_k3.json` | K=3 parallel workers, all succeed |
| `structured_output_batched_k3_with_retry.json` | K=3, Worker 2 empty field retry |
| `structured_output_batched_k3_multi_retry.json` | K=3, multiple retry cycles |
| `structured_output_batched_k3_mixed_exhaust.json` | K=3, mixed retry exhaustion |
| `fake_recursive_ping.json` | Recursive `llm_query` 3-layer depth |

### Batched Response Sequence (K=3, no retry, 5 calls)

```
call 0: reasoning  → execute_code with llm_query_batched code
call 1: worker     → Worker 1 set_model_response
call 2: worker     → Worker 2 set_model_response
call 3: worker     → Worker 3 set_model_response
call 4: reasoning  → FINAL(aggregated result)
```

---

## 5. pytest Marker System

```toml
addopts = '-m "provider_fake_contract and not agent_challenge"'
markers = [
    "provider_fake_contract: default provider-fake fixture-contract suite",
    "provider_fake_extended: non-default provider-fake coverage",
    "unit_nondefault: excluded from default pytest run",
]
```

For LiteLLM: add `"litellm_integration: tests requiring valid LiteLLM API key"` to markers. Already excluded from default `addopts` since it lacks `provider_fake_contract`.

---

## 6. Templates for LiteLLM Integration Tests

### 6a. Provider-Fake Fixture Template

Create `tests_rlm_adk/fixtures/provider_fake/litellm_basic_query.json`:

```json
{
  "scenario_id": "litellm_basic_query",
  "description": "LiteLLM smoke test: single llm_query child dispatch",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 3,
    "retry_delay": 0.0
  },
  "responses": [
    {
      "call_index": 0, "caller": "reasoning", "status": 200,
      "body": {
        "candidates": [{"content": {"role": "model", "parts": [
          {"functionCall": {"name": "execute_code", "args": {"code": "result = llm_query(\"say hello\")\nprint(result)"}}}
        ]}, "finishReason": "STOP", "index": 0}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50, "totalTokenCount": 150}
      }
    },
    {
      "call_index": 1, "caller": "worker", "status": 200,
      "body": {
        "candidates": [{"content": {"role": "model", "parts": [
          {"functionCall": {"name": "set_model_response", "args": {"final_answer": "hello from litellm", "reasoning_summary": "said hello"}}}
        ]}, "finishReason": "STOP", "index": 0}],
        "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 15, "totalTokenCount": 65}
      }
    },
    {
      "call_index": 2, "caller": "reasoning", "status": 200,
      "body": {
        "candidates": [{"content": {"role": "model", "parts": [
          {"text": "Child said hello.\n\nFINAL(hello from litellm)"}
        ]}, "finishReason": "STOP", "index": 0}],
        "usageMetadata": {"promptTokenCount": 200, "candidatesTokenCount": 20, "totalTokenCount": 220}
      }
    }
  ],
  "expected": {"final_answer": "hello from litellm", "total_iterations": 1, "total_model_calls": 3},
  "expected_state": {
    "obs:child_dispatch_count": 1,
    "obs:child_error_counts": {"$absent": true},
    "last_repl_result": {"$not_none": true}
  }
}
```

### 6b. FMEA Test Class Template

```python
class TestLiteLLMBasicQuery:
    FIXTURE = "litellm_basic_query"

    async def test_contract(self, fmea_result):
        assert fmea_result.contract.passed, fmea_result.contract.diagnostics()

    async def test_child_dispatched_once(self, fmea_result):
        assert fmea_result.final_state.get("obs:child_dispatch_count", 0) == 1

    async def test_no_child_errors(self, fmea_result):
        assert "obs:child_error_counts" not in fmea_result.final_state
```

### 6c. Live API Test Template

```python
pytestmark = [pytest.mark.asyncio, pytest.mark.unit_nondefault]

async def test_litellm_single_query_live():
    _skip_if_no_api_key()
    model = os.environ.get("RLM_TEST_LITELLM_MODEL", "litellm/openai/gpt-4o-mini")
    runner = create_rlm_runner(model=model, ...)
    # ... run and assert final_answer is non-empty
```

---

## 7. API Key Validation Script Patterns

### Pattern 1: Inline pytest skip

```python
def _require_env(var: str, description: str) -> str:
    value = os.environ.get(var)
    if not value:
        pytest.skip(f"{var} not set — {description}")
    return value
```

### Pattern 2: Standalone validation script

```python
#!/usr/bin/env python3
"""scripts/validate_litellm_keys.py — pre-flight API key check"""
import asyncio, os, sys, httpx

PROVIDERS = {
    "OPENAI_API_KEY": ("https://api.openai.com/v1/models", "Bearer"),
    "GEMINI_API_KEY": ("https://generativelanguage.googleapis.com/v1beta/models", "x-goog-api-key"),
    "GROQ_API_KEY": ("https://api.groq.com/openai/v1/models", "Bearer"),
    "DEEPSEEK_API_KEY": ("https://api.deepseek.com/v1/models", "Bearer"),
}

async def check_provider(name, url, auth_type, key):
    headers = {"Authorization": f"Bearer {key}"} if auth_type == "Bearer" else {"x-goog-api-key": key}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        return resp.status_code == 200
```

### Pattern 3: pytest session fixture

```python
@pytest.fixture(scope="session")
def litellm_env():
    base_url = os.environ.get("LITELLM_BASE_URL")
    api_key = os.environ.get("LITELLM_API_KEY")
    if not base_url or not api_key:
        pytest.skip("LITELLM_BASE_URL or LITELLM_API_KEY not set")
    return {"base_url": base_url, "api_key": api_key}
```

---

## 8. Provider-Fake Limitation for LiteLLM

The fake server only handles `POST /v1beta/models/{model}:generateContent` (Gemini format). LiteLLM uses `POST /v1/chat/completions` (OpenAI format). Options:

1. **Add `FakeLiteLLMServer`** with same `ScenarioRouter` but serving `/v1/chat/completions`
2. **Configure LiteLLM proxy** to internally redirect to the Gemini fake server
3. **Scope initial tests** to Gemini reasoning layer; test LiteLLM model-string routing in unit tests

---

## 9. Critical Gotchas for Test Authors

- **Class-scoped `fmea_result`** is mandatory — DO NOT make it `scope="function"`
- **Fixture response ordering is FIFO**, not by `call_index`
- **`usageMetadata` required** in every response body
- **AR-CRIT-001** applies in dispatch — state writes via `flush_fn` only
- **`asyncio_mode = "auto"`** — don't add `@pytest.mark.asyncio` individually
- **Pydantic agents** require `object.__setattr__` for dynamic attrs

---

## 10. Essential Files

| File | Role |
|------|------|
| `tests_rlm_adk/provider_fake/server.py` | FakeGeminiServer |
| `tests_rlm_adk/provider_fake/fixtures.py` | ScenarioRouter, ContractResult, matchers |
| `tests_rlm_adk/provider_fake/contract_runner.py` | run_fixture_contract_with_plugins |
| `tests_rlm_adk/provider_fake/conftest.py` | FIXTURE_DIR constant |
| `tests_rlm_adk/conftest.py` | Global conftest, auto-marker logic |
| `tests_rlm_adk/test_fmea_e2e.py` | FMEA class-scoped fixture pattern |
| `tests_rlm_adk/fixtures/provider_fake/structured_output_batched_k3.json` | Canonical batched fixture |
| `tests_rlm_adk/replay/recursive_ping.json` | Live replay recursive dispatch |
