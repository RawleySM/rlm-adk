# RLM-ADK Testing Infrastructure

## RLM-ADK Testing Infrastructure Documentation

### 1. Provider-Fake System Overview

The provider-fake system provides deterministic, network-free end-to-end testing using canned Gemini API responses.

#### **FakeGeminiServer** (`tests_rlm_adk/provider_fake/server.py`)

The `FakeGeminiServer` class is a lightweight aiohttp-based HTTP server that emulates the Gemini `POST /v1beta/models/{model}:generateContent` endpoint.

**Key responsibilities:**
- Starts an aiohttp server on localhost with an OS-assigned port (port=0)
- Handles POST requests at `/v1beta/models/{model}:generateContent`
- Validates API key headers (accepts any value, rejects missing)
- Parses JSON request bodies
- Routes responses via a `ScenarioRouter` instance
- Returns malformed JSON when fault injection specifies `malformed_json`

**Lifecycle methods:**
- `async start() -> str`: Starts the server, returns base URL (e.g., `http://127.0.0.1:54321`)
- `async stop() -> None`: Gracefully shuts down the server
- `base_url` property: Returns the server's base URL

**Request handling:**
- `_handle_generate_content(request)`: Delegates to `router.next_response(body)` and returns `(status_code, response_body)` as JSON

---

#### **ScenarioRouter** (`tests_rlm_adk/provider_fake/fixtures.py`)

The `ScenarioRouter` is a **thread-safe** sequential response router with fault injection overlay. It consumes fixture responses in FIFO order and supports fault injection at specific call indices.

**Constructor:**
```python
ScenarioRouter(fixture: dict[str, Any])
```

Loads from a fixture dict containing:
- `scenario_id`: Unique identifier (used in diagnostics)
- `description`: Human-readable description
- `config`: Configuration dict (model, max_iterations, thinking_budget, retry_delay, test_hooks, initial_repl_globals, initial_state)
- `expected`: Simple expectations (final_answer, total_iterations, total_model_calls)
- `expected_state`: Declarative state assertions using operators like `$gt`, `$gte`, `$lt`, `$lte`, `$not_none`, `$not_empty`, `$has_key`, `$type`, `$contains`, `$len_gte`, `$len_eq`, `$absent`
- `expected_contract`: Rich contract invariants (callers, captured_requests, events, tool_results, observability)
- `responses`: List of scripted response dicts with `call_index`, `caller`, `status`, `body`
- `fault_injections`: List of fault dicts with `call_index`, `fault_type`, `status`, `body`

**Key methods:**

1. **`from_file(path: str | Path) -> ScenarioRouter`**: Class method to load a fixture JSON file

2. **`next_response(request_body, request_meta) -> tuple[int, dict]`**: Thread-safe method returning `(status_code, response_body)` for the next API call. Logs request metadata and checks for:
   - Fault injections (checked first by call_index)
   - Normal sequential responses (FIFO)
   - Fixture exhaustion fallback (returns empty-text response when out of scripted responses)

3. **`check_expectations(final_state, fixture_path, elapsed_s, events=None) -> ContractResult`**: Validates final run state against fixture expectations. Checks:
   - `final_answer`, `total_iterations`, `total_model_calls` (simple expectations)
   - Declarative state assertions with structural matchers
   - Fixture exhaustion fallback usage
   - Contract invariants (via `_check_contract_invariants`)

4. **`reset() -> None`**: Resets state for fixture reuse between tests (thread-safe)

**State tracking:**
- `_call_index`: Counter incremented on each `next_response()` call
- `_response_pointer`: Index into the `responses` list
- `_request_log`: List of sanitized request metadata
- `_captured_requests`: Full request bodies (for later inspection)
- `_captured_metadata`: Caller information per request
- `_fixture_exhausted_calls`: Call indices that hit the fallback

**Thread safety:**
Uses `threading.Lock()` to protect all stateful operations. Multiple concurrent worker calls are safely serialized.

---

#### **ContractResult** (`tests_rlm_adk/provider_fake/fixtures.py`)

A dataclass containing the outcome of a fixture contract run:

```python
@dataclasses.dataclass
class ContractResult:
    fixture_path: str
    scenario_id: str
    passed: bool
    checks: list[dict]           # [{field, expected, actual, ok, detail?}, ...]
    call_summary: list[dict]      # Request metadata from request_log
    total_elapsed_s: float
    captured_requests: list[dict] = ...
    captured_metadata: list[dict] = ...
```

**Key methods:**
- `diagnostics() -> str`: Multi-line human-readable report with all checks and call log
- `summary_line() -> str`: One-liner for batch output (PASS/FAIL + mismatches)

---

#### **Contract Runners** (`tests_rlm_adk/provider_fake/contract_runner.py`)

Two main entry points for executing fixtures:

1. **`run_fixture_contract(fixture_path, prompt="test prompt") -> ContractResult`**
   - Simplest entry point
   - Runs fixture through the full plugin-enabled pipeline
   - Enables: `ObservabilityPlugin`, `SqliteTracingPlugin`, `REPLTracingPlugin` (level 1)
   - Uses temporary directory for traces.db
   - Returns just the `ContractResult`

2. **`run_fixture_contract_with_plugins(fixture_path, prompt, traces_db_path, repl_trace_level) -> PluginContractResult`**
   - Full-featured entry point
   - Creates `FakeGeminiServer`, starts it, sets environment variables
   - Creates `LocalREPL` if `initial_repl_globals` in config
   - Wires test hooks if `config.test_hooks = true`
   - Runs the agent to completion via `runner.run_async()`
   - Captures all events, final state, and contract result
   - Returns a `PluginContractResult` containing:
     - `contract: ContractResult`
     - `events: list[Any]` (ADK event stream)
     - `final_state: dict[str, Any]`
     - `artifact_service: InMemoryArtifactService`
     - `traces_db_path: str | None`
     - `router: ScenarioRouter`

**Test hooks** (when `config.test_hooks = true`):
- Chains callbacks on reasoning agent to flow state dict into `systemInstruction`
- Wires orchestrator + tool callbacks to capture context
- Enables `CB_REASONING_CONTEXT`, `CB_ORCHESTRATOR_CONTEXT`, `CB_TOOL_CONTEXT` state keys

**Environment override:**
```
GOOGLE_GEMINI_BASE_URL = server.base_url
GEMINI_API_KEY = "fake-key-for-testing"
RLM_ADK_MODEL = config.get("model", "gemini-fake")
RLM_LLM_RETRY_DELAY = config.get("retry_delay", 0.01)
RLM_LLM_MAX_RETRIES = config.get("max_retries", 3)
RLM_MAX_ITERATIONS = config.get("max_iterations", 5)
RLM_REPL_TRACE = str(repl_trace_level)
```

---

### 2. Fixture File Structure

Fixtures are JSON files in `tests_rlm_adk/fixtures/provider_fake/` with the following schema:

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
    "initial_repl_globals": { "var": "value" or "$mock_return": "value" },
    "initial_state": { "key": "value" }
  },
  "responses": [
    {
      "call_index": 0,
      "caller": "reasoning" | "worker",
      "status": 200,
      "body": { "candidates": [...] }
    }
  ],
  "fault_injections": [
    {
      "call_index": N,
      "fault_type": "http_error" | "malformed_json",
      "status": 429 | 500 | ...,
      "body": { "error": {...} }
    }
  ],
  "expected": {
    "final_answer": "expected string",
    "total_iterations": 2,
    "total_model_calls": 5
  },
  "expected_state": {
    "key": value or { "$operator": operand },
    "nested": { "key": { "$type": "dict" } }
  },
  "expected_contract": {
    "callers": [ "reasoning", "worker", "reasoning" ] or { "sequence": [...], "counts": {...}, "count": N },
    "captured_requests": N,
    "events": {
      "part_counts": { "text": N, "function_call:execute_code": M },
      "part_sequence": [...]
    },
    "tool_results": {
      "count": N,
      "any": [ { "field": { "$operator": value } } ],
      "stdout_contains": [ "needle1", "needle2" ],
      "stderr_contains": [ "error text" ]
    },
    "observability": {
      "counters": {
        "obs:total_calls": { "$gt": 0 },
        "obs:total_input_tokens": { "$gt": 0 }
      }
    }
  }
}
```

**Matcher operators** (in `expected_state` and `expected_contract`):
- `$gt`, `$gte`, `$lt`, `$lte`: Numeric comparisons
- `$not_none`: Value is not None
- `$not_empty`: Value is not empty (dict/list/string)
- `$has_key`: Dict has key
- `$type`: Type check (list, dict, str, int, float, bool)
- `$contains`: String substring check
- `$len_gte`, `$len_eq`: Length checks
- `$absent`: Key should not exist in state

**Response body schema** (Gemini API format):
```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          { "text": "..." } or 
          { "functionCall": { "name": "execute_code", "args": { "code": "..." } } }
        ]
      },
      "finishReason": "STOP" | "MAX_TOKENS" | "SAFETY",
      "index": 0
    }
  ],
  "usageMetadata": {
    "promptTokenCount": N,
    "candidatesTokenCount": M,
    "totalTokenCount": K
  },
  "modelVersion": "gemini-fake"
}
```

**Current fixtures** (51 total): See `/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/fixtures/provider_fake/index.json` for complete FMEA mapping.

Key fixture categories:
1. **Baseline** (no workers): `happy_path_single_iteration`, `fault_429_then_success`, `empty_reasoning_output`
2. **Single worker** (`llm_query`): `repl_error_then_retry`, `deterministic_guardrails`, `exec_sandbox_codegen`
3. **Parallel workers** (`llm_query_batched`): `structured_output_batched_k3*`, `sliding_window_chunking`
4. **Error/retry**: `fault_429_then_success`, `structured_output_retry_*`, `worker_500_retry_exhausted`
5. **Observability/hooks**: `request_body_comprehensive`, `fake_recursive_ping`
6. **Structured output**: `structured_output_batched_k3*`, `structured_output_retry_*`

---

### 3. Pytest Fixtures and Conftest

#### **Root conftest** (`tests_rlm_adk/conftest.py`)

```python
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-tags tests into suites based on markers."""
    # If no 'provider_fake' marker → add 'unit_nondefault'
    # If 'provider_fake' but no 'provider_fake_contract' → add 'provider_fake_extended'

@pytest.fixture
def repl():
    """Provide a fresh LocalREPL, clean up after test."""
    r = LocalREPL()
    yield r
    r.cleanup()
```

#### **Provider-fake conftest** (`tests_rlm_adk/provider_fake/conftest.py`)

```python
@pytest.fixture
async def fake_gemini(request) -> AsyncIterator[FakeGeminiServer]:
    """Parametrized fixture that starts a fake server from a fixture JSON.
    
    Usage:
        @pytest.mark.parametrize("fake_gemini", [
            FIXTURE_DIR / "fixture.json",
        ], indirect=True)
        async def test_foo(fake_gemini):
            ...
    """
    # Loads fixture, creates FakeGeminiServer, starts it
    # Saves/overrides GOOGLE_GEMINI_BASE_URL, GEMINI_API_KEY
    # Yields server
    # Stops server and restores env vars
```

---

### 4. Test Files and Patterns

#### **test_provider_fake_e2e.py** (Contract validation)

```python
@pytest.mark.provider_fake_contract
@pytest.mark.parametrize("fixture_path", _all_fixture_paths(), ids=lambda p: p.stem)
async def test_fixture_contract(fixture_path: Path):
    """Validate each fixture through the real pipeline."""
    result = await run_fixture_contract(fixture_path)
    assert result.passed, result.diagnostics()
```

- **Group A**: Contract validation (parametrized over all fixtures)
- **Group B**: Plugin + artifact integration (observability state, artifact persistence)
- **Group C**: Tracing integration (SqliteTracingPlugin DB assertions, REPL trace events)

**Worker fixture exclusions** (incompatible with child orchestrator dispatch):
- `all_workers_fail_batch`, `worker_429_mid_batch`, `worker_500_retry_exhausted`, `worker_500_retry_exhausted_naive`, `worker_empty_response`, `worker_empty_response_finish_reason`, `worker_safety_finish`

---

#### **test_fmea_e2e.py** (Failure mode testing)

Uses a **class-scoped fixture pattern**:

```python
@pytest_asyncio.fixture(scope="class")
async def fmea_result(request, tmp_path_factory):
    """Run the fixture once per test class, share result across all methods."""
    fixture_name = request.cls.FIXTURE
    tmp_path = tmp_path_factory.mktemp(fixture_name)
    return await run_fixture_contract_with_plugins(
        FIXTURE_DIR / f"{fixture_name}.json",
        traces_db_path=str(tmp_path / "traces.db"),
        repl_trace_level=1,
    )
```

**Pattern:**
- Each test class has a `FIXTURE = "fixture_name"` class variable
- The `fmea_result` fixture runs the fixture once per class
- All test methods in the class receive the same `PluginContractResult` instance
- Eliminates redundant runs of expensive fixtures

**Example test class structure:**
```python
class TestReplErrorThenRetry:
    FIXTURE = "repl_error_then_retry"
    
    async def test_contract(self, fmea_result: PluginContractResult):
        assert fmea_result.contract.passed, fmea_result.contract.diagnostics()
    
    async def test_iteration_count(self, fmea_result: PluginContractResult):
        iter_count = fmea_result.final_state.get(ITERATION_COUNT)
        assert iter_count == 2
    
    async def test_tool_results(self, fmea_result: PluginContractResult):
        tool_results = _extract_tool_results(fmea_result.events)
        assert len(tool_results) >= 2
```

**Helper functions:**
- `_extract_tool_results(events: list) -> list[dict]`: Extract execute_code function_response dicts
- `_request_function_responses(request: dict) -> list[dict]`: Extract functionResponse from request
- `_request_function_calls(request: dict) -> list[dict]`: Extract functionCall from request

**Covered failure modes** (~20 test classes):
- FM-05/14/23: REPL Error Then Retry
- Recursive dispatch (child orchestrators)
- Structured output with retries
- Worker API errors (429, 500)
- REPL syntax/runtime errors
- Max iterations exceeded
- Empty reasoning output
- Malformed JSON
- Token truncation

---

#### **test_request_body_comprehensive.py** (Request body fidelity)

```python
async def test_captured_metadata_preserves_reasoning_worker_call_sequence(contract_result):
    assert contract_result.captured_metadata == [
        {"call_index": 0, "caller": "reasoning"},
        {"call_index": 1, "caller": "worker"},
        ...
    ]

async def test_dynamic_context_reinjected_in_reasoning_request_contents(contract_result):
    for idx in (0, 2, 4):
        contents_text = _request_contents_text(contract_result.captured_requests[idx])
        assert "exp-42" in contents_text  # Test hook context
```

Tests that:
- Captured requests preserve metadata (call_index, caller)
- Test hooks correctly inject state into request body
- Function response payloads survive round-trip through network simulation

---

### 5. Test Configuration (pyproject.toml)

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "tests_rlm_adk"]
asyncio_mode = "auto"
addopts = '-m "provider_fake_contract and not agent_challenge"'
markers = [
    "provider_fake: e2e tests against provider-fake (no network)",
    "provider_fake_contract: default fixture-contract suite (~28 tests, ~22s)",
    "provider_fake_extended: non-default coverage beyond default suite",
    "agent_challenge: fixtures under tests_rlm_adk/fixtures/provider_fake/agent_challenge/",
    "unit_nondefault: non-default tests excluded from default pytest run",
]
```

**Default behavior** (`pytest` with no args):
- Runs only `provider_fake_contract` tests (28 fixtures, ~22 seconds)
- Excludes `agent_challenge` tests
- Does NOT run full 970+ test suite

**Alternative runs:**
```bash
# Full suite (970+ tests, ~3 minutes)
pytest tests_rlm_adk/ -m "" -q

# One test
pytest tests_rlm_adk/test_fmea_e2e.py::TestReplErrorThenRetry::test_contract -m "" -v

# All tests in a file
pytest tests_rlm_adk/test_fmea_e2e.py -m "" -v

# Provider-fake extended (non-default)
pytest -m "provider_fake and not provider_fake_contract" -v
```

---

### 6. Replay System

Replay fixtures enable deterministic agent testing with pre-recorded LLM responses.

**Files:** `tests_rlm_adk/replay/*.json`

**Structure:**
```json
{
  "state": {
    "app:max_iterations": 10,
    "app:max_depth": 3
  },
  "queries": [
    "First LLM query prompt",
    "Second LLM query prompt",
    ...
  ]
}
```

**Usage:**
```bash
adk run --replay tests_rlm_adk/replay/recursive_ping.json rlm_adk
```

**Key fixtures:**
- `recursive_ping.json`: 3-layer recursive orchestrator dispatch (layer 0 → layer 1 → layer 2)
- `test_structured_pipeline.json`: Structured output with `set_model_response()`
- `test_recursive_security_audit.json`: Security-focused recursion test

The replay mechanism captures the exact LLM conversation flow and allows reproducible testing without external API calls.

---

### 7. Adding New Test Fixtures

**Steps:**

1. **Create fixture JSON** in `tests_rlm_adk/fixtures/provider_fake/my_scenario.json`

2. **Define responses array** with canned Gemini API responses:
   ```json
   {
     "scenario_id": "my_scenario",
     "description": "What this tests",
     "config": {
       "model": "gemini-fake",
       "max_iterations": 5,
       "test_hooks": false
     },
     "responses": [
       {
         "call_index": 0,
         "caller": "reasoning",
         "status": 200,
         "body": { "candidates": [...] }
       },
       { "call_index": 1, "caller": "worker", "status": 200, "body": {...} },
       { "call_index": 2, "caller": "reasoning", "status": 200, "body": {...} }
     ],
     "fault_injections": [],
     "expected": {
       "final_answer": "expected result",
       "total_iterations": 1,
       "total_model_calls": 3
     },
     "expected_state": {
       "obs:total_calls": { "$gt": 0 }
     },
     "expected_contract": {}
   }
   ```

3. **Add test class** (if FMEA coverage required):
   ```python
   class TestMyScenario:
       FIXTURE = "my_scenario"
       
       async def test_contract(self, fmea_result: PluginContractResult):
           assert fmea_result.contract.passed
   ```

4. **Run to validate:**
   ```bash
   pytest tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[my_scenario] -v
   ```

---

### 8. FMEA Mapping and Coverage

The `index.json` file maps failure modes to fixtures and tests. Structure:

```json
{
  "$schema": "Failure Mode → Fixture → Test mapping",
  "$generated": "2026-03-03",
  "$source": "rlm_adk_docs/FMEA/...",
  "failure_modes": {
    "FM-01": {
      "id": "FM-01",
      "name": "Orchestrator Transient Error Retry Exhaustion",
      "pathway": "P2",
      "rpn": 84,
      "coverage": "partial",
      "fixtures": [ { "fixture": "fault_429_then_success.json", "coverage_level": "partial" } ],
      "tests": [ { "file": "tests_rlm_adk/test_provider_fake_e2e.py", "test": "test_fixture_contract[...]", "type": "contract" } ]
    },
    ...
  }
}
```

**Coverage levels:**
- `full`: Comprehensive fixture + dedicated test class assertions
- `partial`: Fixture present but limited test coverage
- `gap`: No fixture or test

**Current coverage:** ~80 tests across 51 fixtures, 25+ failure modes addressed.

---

### 9. Key Design Patterns

#### **Thread-Safe Fixture Routing**
- `ScenarioRouter._lock` (threading.Lock) protects all state mutations
- Safe for concurrent worker dispatches in the same test

#### **Class-Scoped Fixture Efficiency**
- `@pytest_asyncio.fixture(scope="class")` runs expensive fixture once per test class
- All test methods share the same `PluginContractResult`
- Reduces total test runtime from ~4min (per-method) to ~22s (provider_fake_contract)

#### **Declarative Matchers**
- `_match_value()` and `_match_structure()` support nested operator dicts
- Enable flexible assertions without custom assert code
- Support list/dict recursion for deep state validation

#### **Fault Injection Overlay**
- Fault injections checked BEFORE normal response sequence
- Allow precise error injection at specific call indices
- Support HTTP errors (429, 500, 401) and malformed JSON

#### **Caller Tracking**
- `captured_metadata` preserves reasoning vs. worker distinction
- Enables `expected_contract.callers.sequence` assertions
- Used to verify correct dispatch patterns

#### **Observability Assertions**
- `expected_contract.observability.counters` for token/call counts
- Fixture validation includes plugin state (ObservabilityPlugin output)
- Tests verify correct token accounting across iterations

---

### 10. Summary

The RLM-ADK testing infrastructure provides:

1. **Deterministic e2e testing** via FakeGeminiServer + ScenarioRouter
2. **Comprehensive fixture coverage** (51 fixtures, 25+ failure modes, FMEA-mapped)
3. **Efficient test execution** (provider_fake_contract: ~28 tests, ~22s; full suite: ~970 tests, ~3min)
4. **Declarative contract assertions** (matchers, operators, nested structures)
5. **Plugin-aware testing** (observability, tracing, artifacts all exercised)
6. **Class-scoped fixtures** for optimal performance
7. **Thread-safe router** for parallel worker simulation
8. **Request body capture** for runtime + observability verification
9. **Replay system** for offline agent testing
10. **FMEA integration** for coverage tracking and gap identification