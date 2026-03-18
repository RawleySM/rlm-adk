<!-- validated: 2026-03-17 -->

# Testing Infrastructure Reference

This document covers the provider-fake e2e test system, fixture authoring, contract runners, pytest marker conventions, and the replay system.

---

## Provider-Fake Overview

The provider-fake system enables deterministic, network-free end-to-end testing by emulating the Gemini API at the HTTP level.

**FakeGeminiServer** (`tests_rlm_adk/provider_fake/server.py`) is a lightweight aiohttp server that:

- Binds to localhost on an OS-assigned port (`port=0`)
- Handles `POST /v1beta/models/{model}:generateContent`
- Validates API key headers (accepts any value, rejects missing)
- Delegates response selection to a `ScenarioRouter`
- Returns malformed JSON when fault injection requires it

Lifecycle: `await server.start()` returns the base URL; `await server.stop()` tears down gracefully. The `base_url` property is available between those calls.

---

## ScenarioRouter

`ScenarioRouter` (`tests_rlm_adk/provider_fake/fixtures.py`) is a thread-safe, FIFO sequential response dispatcher with a fault-injection overlay.

**Construction:** `ScenarioRouter(fixture: dict)` or `ScenarioRouter.from_file(path)`.

**Core method -- `next_response(request_body, request_meta) -> (status_code, response_body)`:**

1. Check fault injections first (matched by `call_index`).
2. If no fault, consume the next entry from the `responses` list (FIFO).
3. If responses are exhausted, return an empty-text fallback and log the call index.

All state (`_call_index`, `_response_pointer`, `_request_log`, `_captured_requests`, `_captured_metadata`, `_fixture_exhausted_calls`) is guarded by `threading.Lock`, so concurrent worker calls within a single test are safely serialized.

**`check_expectations(final_state, fixture_path, elapsed_s, events=None) -> ContractResult`** validates the run output against fixture expectations: simple value checks, declarative state matchers, fixture-exhaustion detection, and contract invariants.

**`reset()`** clears all state for fixture reuse.

---

## ContractResult

```python
@dataclasses.dataclass
class ContractResult:
    fixture_path: str
    scenario_id: str
    passed: bool
    checks: list[dict]           # [{field, expected, actual, ok, detail?}]
    call_summary: list[dict]      # Request metadata from request_log
    total_elapsed_s: float
    captured_requests: list[dict]
    captured_metadata: list[dict]
```

- **`diagnostics()`** -- multi-line human-readable report with every check and the full call log.
- **`summary_line()`** -- one-liner for batch output (`PASS`/`FAIL` plus mismatch count).

---

## Contract Runners

Located in `tests_rlm_adk/provider_fake/contract_runner.py`.

### run_fixture_contract(fixture_path, prompt="test prompt") -> ContractResult

Simplest entry point. Internally calls the plugin-enabled pipeline with `ObservabilityPlugin`, `SqliteTracingPlugin`, and `REPLTracingPlugin` (level 1). Uses a temp directory for `traces.db`. Returns `ContractResult` only.

### run_fixture_contract_with_plugins(...) -> PluginContractResult

Full-featured entry point. Creates and starts a `FakeGeminiServer`, sets environment overrides, optionally pre-seeds REPL globals and wires test hooks, runs the agent via `runner.run_async()`, then collects everything into:

```python
PluginContractResult:
    contract: ContractResult
    events: list[Any]                   # full ADK event stream
    final_state: dict[str, Any]
    artifact_service: InMemoryArtifactService
    traces_db_path: str | None
    router: ScenarioRouter
```

**Test hooks** (when `config.test_hooks = true`): chains callbacks on the reasoning agent to inject state into `systemInstruction`, wires orchestrator and tool callbacks, and populates `CB_REASONING_CONTEXT`, `CB_ORCHESTRATOR_CONTEXT`, `CB_TOOL_CONTEXT` state keys.

---

## Fixture JSON Schema

Fixtures live in `tests_rlm_adk/fixtures/provider_fake/*.json`.

```json
{
  "scenario_id": "unique_identifier",
  "description": "Human-readable test description",

  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.01,
    "max_retries": 3,
    "test_hooks": false,
    "initial_repl_globals": { "var": "value" },
    "initial_state": { "key": "value" }
  },

  "responses": [
    {
      "call_index": 0,
      "caller": "reasoning",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [
              { "text": "plain text response" },
              { "functionCall": { "name": "execute_code", "args": { "code": "print(1)" } } }
            ]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {
          "promptTokenCount": 100,
          "candidatesTokenCount": 50,
          "totalTokenCount": 150
        },
        "modelVersion": "gemini-fake"
      }
    }
  ],

  "fault_injections": [
    {
      "call_index": 1,
      "fault_type": "http_error | malformed_json",
      "status": 429,
      "body": { "error": { "message": "rate limited", "code": 429 } }
    }
  ],

  "expected": {
    "final_answer": "expected string",
    "total_iterations": 2,
    "total_model_calls": 5
  },

  "expected_state": {
    "plain_key": "literal value",
    "numeric_key": { "$gt": 0 },
    "absent_key": { "$absent": true }
  },

  "litellm_overrides": {
    "config": {
      "model": "openai/gpt-4o"
    }
  },

  "expected_contract": {
    "callers": ["reasoning", "worker", "reasoning"],
    "captured_requests": 3,
    "events": {
      "part_counts": { "text": 2, "function_call:execute_code": 1 },
      "part_sequence": ["text", "function_call:execute_code", "text"]
    },
    "tool_results": {
      "count": 2,
      "any": [{ "field": { "$contains": "needle" } }],
      "stdout_contains": ["hello"],
      "stderr_contains": ["error text"]
    },
    "observability": {
      "counters": {
        "obs:total_calls": { "$gt": 0 },
        "obs:total_input_tokens": { "$gte": 100 }
      }
    }
  }
}
```

`callers` also accepts an object form: `{ "sequence": [...], "counts": {...}, "count": N }`.

### Matcher Operators

Used in `expected_state` and `expected_contract` values:

| Operator | Meaning |
|----------|---------|
| `$gt`, `$gte`, `$lt`, `$lte` | Numeric comparisons |
| `$not_none` | Value is not `None` |
| `$not_empty` | Value is not empty (works on dict, list, string) |
| `$has_key` | Dict contains a specific key |
| `$type` | Type check (`list`, `dict`, `str`, `int`, `float`, `bool`) |
| `$contains` | Substring match on strings |
| `$len_gte`, `$len_eq` | Length comparisons |
| `$oneof` | Value matches at least one element in the provided list |
| `$absent` | Key must not exist in state |

Matchers compose: `_match_value()` and `_match_structure()` recurse into nested dicts and lists.

---

## How to Add a Fixture

1. **Copy a template.** Start from an existing fixture close to your scenario (e.g., `happy_path_single_iteration.json` for baseline, `repl_error_then_retry.json` for error paths). Save as `tests_rlm_adk/fixtures/provider_fake/my_scenario.json`.

2. **Set `scenario_id`** to a unique snake_case identifier matching the filename (without `.json`).

3. **Write `config`.** Set `max_iterations` to the minimum needed. Use `"test_hooks": true` only if you need request-body inspection. Set `"retry_delay": 0.01` to keep tests fast.

4. **Define `responses` in call order.** Each entry needs `call_index` (0-based), `caller` (`"reasoning"` or `"worker"`), `status` (usually 200), and `body` in Gemini API format. Reasoning responses use `functionCall` parts to trigger REPL execution; the final reasoning response uses a `text` part for the answer.

5. **Add `fault_injections`** (optional). Specify `call_index`, `fault_type` (`"http_error"` or `"malformed_json"`), `status`, and `body`. Faults are checked before normal responses at a given index.

6. **Set `expected`.** At minimum: `final_answer`, `total_iterations`, `total_model_calls`.

7. **Add `expected_state`** assertions (optional). Use matcher operators for numeric or structural checks against final agent state.

8. **Add `expected_contract`** invariants (optional). Specify `callers` sequence, `captured_requests` count, `events` part counts, `tool_results` checks, and `observability` counters.

9. **Validate the fixture** against the contract runner:
   ```bash
   .venv/bin/python -m pytest \
     tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[my_scenario] -v
   ```

10. **Add an FMEA test class** (if the fixture covers a failure mode):
    ```python
    # In tests_rlm_adk/test_fmea_e2e.py
    class TestMyScenario:
        FIXTURE = "my_scenario"

        async def test_contract(self, fmea_result: PluginContractResult):
            assert fmea_result.contract.passed, fmea_result.contract.diagnostics()

        async def test_specific_state(self, fmea_result: PluginContractResult):
            assert fmea_result.final_state.get("key") == "expected"
    ```

11. **Run the new class:**
    ```bash
    .venv/bin/python -m pytest \
      tests_rlm_adk/test_fmea_e2e.py::TestMyScenario -m "" -v
    ```

---

## test_fmea_e2e.py Patterns

This file uses a **class-scoped fixture** to run each fixture exactly once per test class:

```python
@pytest_asyncio.fixture(scope="class")
async def fmea_result(request, tmp_path_factory):
    fixture_name = request.cls.FIXTURE
    tmp_path = tmp_path_factory.mktemp(fixture_name)
    return await run_fixture_contract_with_plugins(
        FIXTURE_DIR / f"{fixture_name}.json",
        traces_db_path=str(tmp_path / "traces.db"),
        repl_trace_level=1,
    )
```

Each test class declares `FIXTURE = "fixture_name"` and receives the shared `PluginContractResult` through `fmea_result`. All methods in the class -- `test_contract`, `test_iteration_count`, `test_tool_results`, `test_obs_counters`, etc. -- read from the same result without re-running the agent.

Helper functions: `_extract_tool_results(events)`, `_request_function_responses(request)`, `_request_function_calls(request)`.

Approximately 20 test classes cover failure modes including REPL errors, structured output retries, worker API errors (429, 500), safety finishes, malformed JSON, token truncation, max-iterations exhaustion, and recursive dispatch.

---

## test_provider_fake_e2e.py

Organized into three groups:

- **Group A -- Contract validation.** Parametrized over all fixture paths via `_all_fixture_paths()`. Each fixture is run through `run_fixture_contract()` and asserted with `result.passed`. Some worker-error fixtures are excluded (they require child orchestrator dispatch that the simple runner does not support).

- **Group B -- Plugin and artifact integration.** Tests that observability state keys are populated, artifacts are persisted to `InMemoryArtifactService`, and plugin lifecycle methods fire correctly.

- **Group C -- Tracing integration.** Asserts on `SqliteTracingPlugin` database contents and REPL trace event structure.

All tests in this file carry the `@pytest.mark.provider_fake_contract` marker.

---

## Instruction Router E2E Tests

**File:** `tests_rlm_adk/test_instruction_router_e2e.py`

Tests the `instruction_router` feature end-to-end using the provider-fake infrastructure. Uses the `instruction_router_fanout.json` fixture to verify:

- Instruction router is called with correct `(depth, fanout_idx)` arguments
- `DYN_SKILL_INSTRUCTION` state key is populated in session state
- Skill instruction propagates through to the `{skill_instruction?}` template placeholder
- Parent skill instruction is restored by `flush_fn` after child dispatch
- `SqliteTracingPlugin` captures `skill_instruction` in telemetry rows

The fixture simulates a fanout dispatch scenario where the instruction router produces different instructions for different `(depth, fanout_idx)` combinations.

---

## Marker System

Defined in `pyproject.toml`:

| Marker | Purpose |
|--------|---------|
| `provider_fake` | Any e2e test using the fake server (no network) |
| `provider_fake_contract` | Default fixture-contract suite (~28 tests, ~22s) |
| `provider_fake_extended` | Coverage beyond the default suite |
| `agent_challenge` | Fixtures under `fixtures/provider_fake/agent_challenge/` |
| `unit_nondefault` | Unit tests excluded from the default run |

**Default filter** (configured in `pyproject.toml` `addopts`):

```
-m "provider_fake_contract and not agent_challenge"
```

**Override the filter** with `-m ""`:

```bash
# Full suite (~970 tests, ~3min)
.venv/bin/python -m pytest tests_rlm_adk/ -m "" -q

# Single test (must override marker filter)
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestMyClass::test_contract -m "" -v

# All tests in one file
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py -m "" -v

# Extended provider-fake only
.venv/bin/python -m pytest -m "provider_fake and not provider_fake_contract" -v
```

Auto-tagging in `conftest.py`: tests without `provider_fake` get `unit_nondefault`; tests with `provider_fake` but not `provider_fake_contract` get `provider_fake_extended`.

---

## ADK Gotchas

### MagicMock cannot be used as Pydantic field values

ADK agents are Pydantic models. Pydantic validation rejects `MagicMock`:

```python
# WRONG -- Pydantic validation rejects MagicMock
agent = LlmAgent(model=MagicMock(), ...)

# CORRECT -- create real instances, then patch methods
agent = LlmAgent(model="gemini-2.5-flash", name="test", ...)
agent.generate_content = AsyncMock(return_value=...)
```

### Dynamic attributes on test agents

```python
agent = LlmAgent(name="test_worker", model="gemini-2.5-flash")
object.__setattr__(agent, "_pending_prompt", "test prompt")
object.__setattr__(agent, "_result", None)
object.__setattr__(agent, "_result_ready", False)
```

### Mock CallbackContext must use private API path

```python
# WRONG
mock_ctx = MagicMock()
mock_ctx.agent = real_agent

# CORRECT -- must set the private _invocation_context path
mock_ctx = MagicMock()
mock_ctx._invocation_context.agent = real_agent
```

### ParallelAgent cleanup in tests

After any test that uses `ParallelAgent`, clear `parent_agent`:

```python
for worker in workers:
    worker.parent_agent = None
```

Failing to do this causes subsequent tests to raise on worker reuse.

### Class-scoped fixture pattern (FMEA tests)

Each FMEA test class uses a **class-scoped `fmea_result` fixture** that runs the provider-fake fixture ONCE per class and shares the `PluginContractResult` across all test methods. Do NOT regress to per-method execution — it multiplies runtime by the number of test methods per class.

### State mutation (AR-CRIT-001)

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. The write appears to succeed at runtime but the Runner never sees it, so it is never persisted and does not appear in the event stream. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

---

## Replay System

Replay fixtures (`tests_rlm_adk/replay/*.json`) provide pre-recorded LLM conversation flows for offline agent testing.

```json
{
  "state": {
    "app:max_iterations": 10,
    "app:max_depth": 3
  },
  "queries": [
    "First LLM query prompt",
    "Second LLM query prompt"
  ]
}
```

Run with:

```bash
.venv/bin/adk run --replay tests_rlm_adk/replay/recursive_ping.json rlm_adk
```

Key replay fixtures: `recursive_ping.json` (3-layer recursive dispatch), `test_structured_pipeline.json` (structured output with `set_model_response()`), `test_recursive_security_audit.json`.

Provider-fake fixtures include `instruction_router_fanout.json` for instruction router e2e coverage.

---

## Environment Overrides

During fixture runs, the contract runner sets these environment variables:

| Variable | Value |
|----------|-------|
| `GOOGLE_GEMINI_BASE_URL` | `server.base_url` (localhost) |
| `GEMINI_API_KEY` | `"fake-key-for-testing"` |
| `RLM_ADK_MODEL` | `config.model` (default `"gemini-fake"`) |
| `RLM_LLM_RETRY_DELAY` | `config.retry_delay` (default `0.01`) |
| `RLM_LLM_MAX_RETRIES` | `config.max_retries` (default `3`) |
| `RLM_MAX_ITERATIONS` | `config.max_iterations` (default `5`) |
| `RLM_REPL_TRACE` | `str(repl_trace_level)` |
| `RLM_ADK_LITELLM` | `config.litellm_mode` (default `False`) |
| `OPENAI_API_KEY` | (set if litellm is used) |
| `OPENAI_API_BASE` | `server.base_url + "/v1"` (if litellm is used) |

All overrides are restored to their original values after the run completes. If LiteLLM mode is active, the `contract_runner.py` directs traffic to the `/v1/chat/completions` endpoint.

## Testing

**IMPORTANT: Do NOT run the full 970+ test suite by default.** The default pytest invocation runs only the provider-fake e2e contract set (~28 tests, ~22s):

```bash
# DEFAULT — provider-fake contract tests only
.venv/bin/python -m pytest tests_rlm_adk/

# Run a single test
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py::TestReplErrorThenRetry::test_contract -m "" -v

# Run all tests in a file (override default marker filter)
.venv/bin/python -m pytest tests_rlm_adk/test_fmea_e2e.py -m "" -v

# Full suite (~970 tests, ~3min) — only when explicitly requested
.venv/bin/python -m pytest tests_rlm_adk/ -m "" -q
```

The default marker filter is `-m "provider_fake_contract and not agent_challenge"` (configured in pyproject.toml). Use `-m ""` to override and run all tests. `asyncio_mode = "auto"` is set globally.

---

## Recent Changes

> Append entries here when modifying source files documented by this branch. A stop hook (`ai_docs/scripts/check_doc_staleness.py`) will remind you.

- **2026-03-09 13:00** — Initial branch doc created from codebase exploration.
- **2026-03-10 14:52** — `fixtures.py`: Added `$oneof` matcher operator, `litellm_overrides` fixture section support with `_deep_merge`, and upgraded top-level checks (`final_answer`, `total_iterations`, `total_model_calls`) to use `_match_value()` for operator support. `contract_runner.py`: passes `litellm_mode` through to `check_expectations()`.
- **2026-03-12 17:30** — Added `test_instruction_router_e2e.py` and `instruction_router_fanout.json` fixture for instruction router e2e coverage.
- **2026-03-17 11:20** — `contract_runner.py`: Minor provider-fake improvements. Consolidated test suite from ~970 tests to 29 provider-fake contract tests in `test_provider_fake_e2e.py`. Removed 92 unit/FMEA/obs test files — coverage via e2e logging.

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
