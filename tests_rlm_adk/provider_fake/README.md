# Provider Fake

Deterministic Gemini API fake for testing the full RLM-ADK pipeline without an API key.

A lightweight `aiohttp` server (`FakeGeminiServer`) serves canned responses from
JSON fixture files through the real production code path: HTTP transport, SDK
deserialization, ADK plugin chain, orchestrator loop, REPL execution, and worker
dispatch.

## Quick Start

```bash
# List available fixtures
python -m tests_rlm_adk.provider_fake --list

# Run a single fixture by name
python -m tests_rlm_adk.provider_fake polymorphic_dag_routing

# Run with dashboard snapshot generation
python -m tests_rlm_adk.provider_fake --snapshot polymorphic_dag_routing

# Run multiple via glob
python -m tests_rlm_adk.provider_fake "multi*"

# Run all fixtures
python -m tests_rlm_adk.provider_fake

# Run all with snapshots
python -m tests_rlm_adk.provider_fake --snapshot
```

| Flag              | Short | Effect                                                        |
|-------------------|-------|---------------------------------------------------------------|
| `--list`          | `-l`  | Print available fixture names and exit                        |
| `--snapshot`      | `-s`  | Enable `ContextWindowSnapshotPlugin` (writes `.adk/` JSONL)  |

Positional arguments accept fixture **stems** (`polymorphic_dag_routing`),
**globs** (`poly*`, `*worker*`), or **full paths**.

### Dashboard Workflow

Generate snapshot data from a deterministic fixture, then visualize it:

```bash
python -m tests_rlm_adk.provider_fake --snapshot polymorphic_dag_routing
python -m rlm_adk.dashboard
# Open http://localhost:8080/dashboard
```

## Architecture

```
                  ┌──────────────────┐
                  │  Fixture JSON    │
                  │  (responses +    │
                  │   expectations)  │
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │  ScenarioRouter  │  Sequential FIFO dispatch
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │ FakeGeminiServer  │  aiohttp on 127.0.0.1:0
                  │ POST /v1beta/     │
                  │ models/{m}:       │
                  │ generateContent   │
                  └────────┬─────────┘
                           │  GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:{port}
                           │
               ┌───────────▼──────────────┐
               │  google-genai SDK Client  │  Real HTTP transport
               └───────────┬──────────────┘
                           │
               ┌───────────▼──────────────┐
               │  ADK Runner + Plugins     │  Real plugin chain
               │  (Observability, Tracing, │
               │   Snapshots, REPL Trace)  │
               └───────────┬──────────────┘
                           │
               ┌───────────▼──────────────┐
               │  RLMOrchestratorAgent     │  Real orchestrator loop
               │  + WorkerPool + REPL      │
               └───────────┬──────────────┘
                           │
               ┌───────────▼──────────────┐
               │  ContractResult           │  Pass/fail + diagnostics
               └──────────────────────────┘
```

### Key Design Decisions

- **HTTP-level fake** (not mock): Validates the full transport path — URL
  construction, header plumbing, request serialization, response deserialization,
  SDK retry behavior.
- **Sequential matching**: Responses are consumed in FIFO order by call index.
  No prompt hashing or content matching. Deterministic and trivially debuggable.
- **Zero production code changes**: Integration is entirely through env vars
  (`GOOGLE_GEMINI_BASE_URL`, `GEMINI_API_KEY`, `RLM_ADK_MODEL`).
- **Fault injection overlay**: Fixture `fault_injections` array can inject 429s,
  500s, malformed JSON, or delays at any call index.

## Module Layout

```
tests_rlm_adk/
  provider_fake/
    __init__.py           Package marker
    __main__.py           CLI entry point (argparse)
    server.py             FakeGeminiServer (aiohttp)
    fixtures.py           ScenarioRouter, ContractResult
    contract_runner.py    run_fixture_contract(), run_fixture_contract_with_plugins()
    conftest.py           pytest fixtures (fake_gemini)
  fixtures/
    provider_fake/
      *.json              Fixture files (14 scenarios)
```

## Fixture Schema

```json
{
  "scenario_id": "happy_path_single_iteration",
  "description": "Reasoning agent returns FINAL(42) on first iteration",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 5,
    "retry_delay": 0.0
  },
  "responses": [
    {
      "call_index": 0,
      "caller": "reasoning",
      "status": 200,
      "body": { "candidates": [...], "usageMetadata": {...} }
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

| Field              | Required | Description                                              |
|--------------------|----------|----------------------------------------------------------|
| `scenario_id`      | Yes      | Unique identifier (matches filename stem)                |
| `description`      | No       | Human-readable scenario description                      |
| `config.model`     | No       | Model name (default: `gemini-fake`)                      |
| `config.thinking_budget` | No | Thinking token budget (default: `0` for determinism)     |
| `config.max_iterations`  | No | Orchestrator iteration cap (default: `5`)                |
| `config.retry_delay`     | No | LLM retry delay in seconds (default: `0.0`)             |
| `responses[]`      | Yes      | Ordered list of canned API responses                     |
| `responses[].caller` | No    | `reasoning` or `worker` (documentation only, not matched)|
| `fault_injections[]` | No    | Fault overlay keyed by `call_index`                      |
| `expected`         | No       | Assertions: `final_answer`, `total_iterations`, `total_model_calls` |

### Fault Injection

```json
"fault_injections": [
  {"call_index": 0, "fault_type": "http_error", "status": 429,
   "body": {"error": {"code": 429, "message": "Rate limited", "status": "RESOURCE_EXHAUSTED"}}},
  {"call_index": 2, "fault_type": "malformed_json", "body_raw": "{bad json"},
  {"call_index": 4, "fault_type": "delay", "delay_seconds": 5.0}
]
```

| `fault_type`     | Effect                                    |
|------------------|-------------------------------------------|
| `http_error`     | Return specified `status` + error body    |
| `malformed_json` | Return 200 with raw invalid JSON string   |
| `delay`          | Delay response by `delay_seconds`         |
| `empty_candidates` | Return 200 with empty candidates array  |

## Available Fixtures

| Fixture                        | Iterations | Workers | Tests                                     |
|--------------------------------|------------|---------|-------------------------------------------|
| `happy_path_single_iteration`  | 1          | 0       | Basic FINAL detection                     |
| `multi_iteration_with_workers` | 2          | 1       | Worker dispatch + REPL execution          |
| `fault_429_then_success`       | 1          | 0       | SDK retry on 429                          |
| `full_pipeline`                | 2+         | 1+      | End-to-end with code + workers            |
| `polymorphic_dag_routing`      | 2          | 5       | Batched triage + routed comparison agents |
| `hierarchical_summarization`   | 2          | 3+      | Multi-level worker fan-out                |
| `adaptive_confidence_gating`   | 2          | 4       | Confidence-based routing logic            |
| `sliding_window_chunking`      | 2          | 3       | Chunked processing with workers           |
| `structured_control_plane`     | 2          | 2       | Structured output validation              |
| `deterministic_guardrails`     | 2          | 2       | Guardrail enforcement                     |
| `battlefield_report_telemetry` | 2          | 3       | Telemetry/metrics collection              |
| `multi_turn_repl_session`      | 3+         | 0       | Multi-turn REPL without workers           |
| `exec_sandbox_codegen`         | 2          | 0       | REPL code generation + execution          |
| `skill_helper`                 | 2          | 1       | Skill helper dispatch                     |
| `request_body_comprehensive`   | 3          | 2       | Request body data-flow gaps (G1-G9), callback state hooks, skill frontmatter |

## Contract Runner API

### CLI

```bash
python -m tests_rlm_adk.provider_fake [--list] [--snapshot] [fixtures...]
```

### Programmatic

```python
from pathlib import Path
from tests_rlm_adk.provider_fake.contract_runner import (
    run_fixture_contract,
    run_fixture_contract_with_plugins,
)

# Minimal run (no plugins)
result = await run_fixture_contract(Path("tests_rlm_adk/fixtures/provider_fake/full_pipeline.json"))
assert result.passed, result.diagnostics()

# Plugin-aware run (observability, tracing, snapshots)
plugin_result = await run_fixture_contract_with_plugins(
    Path("tests_rlm_adk/fixtures/provider_fake/full_pipeline.json"),
    traces_db_path="/tmp/traces.db",
    repl_trace_level=1,
)
assert plugin_result.contract.passed
```

| Function                             | Plugins              | Use Case                        |
|--------------------------------------|----------------------|---------------------------------|
| `run_fixture_contract()`             | None (fast)          | Contract validation, CI         |
| `run_fixture_contract_with_plugins()`| Obs + Tracing + REPL | Dashboard data, debugging       |

### pytest

```bash
# Run all fixture contracts as parametrized tests
.venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -v
```

The e2e test suite has three groups:
- **Group A**: Contract validation — parametrized over all fixture JSON files
- **Group B**: Plugin + artifact integration — observability state, artifact persistence
- **Group C**: Tracing integration — SqliteTracingPlugin DB assertions, REPL trace events

## Env Vars Set During Fixture Runs

The contract runner saves, overrides, and restores these env vars per run:

| Env Var                    | Value During Run                  |
|----------------------------|-----------------------------------|
| `GOOGLE_GEMINI_BASE_URL`   | `http://127.0.0.1:{port}`        |
| `GEMINI_API_KEY`           | `fake-key-for-testing`            |
| `GOOGLE_API_KEY`           | *(removed)*                       |
| `RLM_ADK_MODEL`            | From fixture `config.model`       |
| `RLM_LLM_RETRY_DELAY`     | From fixture `config.retry_delay` |
| `RLM_LLM_MAX_RETRIES`     | From fixture `config.max_retries` |
| `RLM_MAX_ITERATIONS`       | From fixture `config.max_iterations` |
| `RLM_REPL_TRACE`           | `0` (or `1` with plugins)        |
| `RLM_CONTEXT_SNAPSHOTS`    | `1` (when `--snapshot` flag used) |

## Writing New Fixtures

1. Copy an existing fixture as a template
2. Set `scenario_id` to match the filename stem
3. Add responses in the exact call order the orchestrator will make:
   - First response is always the reasoning agent (iteration 0)
   - Worker responses follow in dispatch order
   - Next reasoning response continues the loop
   - Final reasoning response must contain `FINAL(...)` to terminate
4. Set `expected` values for contract assertions
5. Verify: `python -m tests_rlm_adk.provider_fake your_new_fixture`

### Naming Convention

`{scenario_type}_{key_detail}.json` — use snake_case. Group related fixtures
by prefix (e.g., `fault_*`).

### Response Format

Responses use the Gemini API wire format (camelCase). Minimum viable response:

```json
{
  "candidates": [{
    "content": {"role": "model", "parts": [{"text": "response text"}]},
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
```

Code blocks in reasoning responses must use the exact `` ```repl `` fence format.
`FINAL(...)` must appear at the start of a line.

### `request_body_comprehensive` Details

Dedicated test file: `test_request_body_comprehensive.py`. Verifies 9 data-flow gaps
that prior fixtures did not cover:

| Gap | Description                                          |
|-----|------------------------------------------------------|
| G1  | Dict-typed state key in dynamic instruction          |
| G2  | Variable persistence across REPL iterations          |
| G3  | Prior worker result chaining                         |
| G4  | Multiple data sources combined in single worker prompt |
| G5  | Data loaded from REPL globals                        |
| G6  | `functionResponse` variables dict fidelity           |
| G7  | Worker `systemInstruction` content                   |
| G8  | Worker `generationConfig`                            |
| G9  | Dynamic instruction re-injection across iterations   |

Also tests callback state hooks (orchestrator `before_agent`/`after_agent`,
reasoning `after_model`, tool `before_tool`/`after_tool`) and skill frontmatter
injection into the system prompt.

## Related Docs

- [Design Spec](design-spec.md) — architectural decisions, dual-layer approach
- [Fixture Strategy](fixture-strategy.md) — matching strategy, schema details
- [Gemini Contract Summary](gemini-contract-summary.md) — wire format reference
- [Dashboard README](../../rlm_adk/dashboard/README.md) — dashboard data sources and launch
- [Fixture Index](../../tests_rlm_adk/fixtures/provider_fake/index.json) — comprehensive fixture-to-test mapping index with FMEA failure mode coverage tracking, fixture-test cross-references, and coverage statistics
