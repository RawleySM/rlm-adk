# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run

```bash
# Install dependencies
uv sync

# Run the agent (ADK CLI)
.venv/bin/adk run rlm_adk

# Run with replay fixture
.venv/bin/adk run --replay tests_rlm_adk/replay/recursive_ping.json rlm_adk

# Lint
ruff check rlm_adk/ tests_rlm_adk/
ruff format --check rlm_adk/ tests_rlm_adk/
```

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

## Architecture

RLM-ADK is a recursive language model agent built on Google ADK (`google.adk`). The core loop: an LLM reasoning agent writes Python code, which executes in a sandboxed REPL. That code can call `llm_query()` to spawn child agents, which themselves get their own REPL — recursion to arbitrary depth.

### Core Flow

```
RLMOrchestratorAgent (BaseAgent)
  └─ delegates to reasoning_agent.run_async(ctx)
       └─ LlmAgent calls REPLTool ("execute_code") via ADK function-calling
            └─ REPLTool wraps LocalREPL
                 └─ User code calls llm_query() → AST-rewritten to async
                      └─ Dispatched via WorkerPool → child LlmAgent/ParallelAgent
                           └─ Child can itself be a full RLMOrchestratorAgent (recursion)
```

### Key Modules

| Module | Role |
|--------|------|
| `orchestrator.py` | `RLMOrchestratorAgent(BaseAgent)` — collapsed orchestrator, delegates to reasoning_agent |
| `agent.py` | Factory functions: `create_rlm_runner()`, `create_rlm_app()`, `create_rlm_orchestrator()`, `create_child_orchestrator()` |
| `dispatch.py` | `WorkerPool`, `create_dispatch_closures()` → returns `(llm_query_async, llm_query_batched_async, flush_fn)` |
| `tools/repl_tool.py` | `REPLTool(BaseTool)` — executes code, detects llm_query via AST, enforces call limits |
| `repl/local_repl.py` | Sandboxed Python env with persistent globals, safe builtins |
| `repl/ast_rewriter.py` | Transforms sync `llm_query()` to `await llm_query_async()` |
| `state.py` | All state key constants + `depth_key(key, depth)` for depth-scoped keys |
| `callbacks/worker_retry.py` | Structured output self-healing + BUG-13 monkey-patch |

### State Mutation Rules (AR-CRIT-001)

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

Dispatch closures use **local accumulators** + `flush_fn()` to snapshot into `tool_context.state` after each REPL execution.

### Depth Scoping

Recursive agents need independent state per depth level. `depth_key("iteration_count", 2)` → `"iteration_count@d2"`. The `DEPTH_SCOPED_KEYS` set in `state.py` defines which keys require this.

### Observability Stack

- `ObservabilityPlugin` — token accounting, finish reason tracking (does NOT fire for workers due to ParallelAgent isolation)
- `SqliteTracingPlugin` — persists traces/telemetry/state events to `.adk/traces.db`
- `REPLTracingPlugin` — aggregated REPL traces as `repl_traces.json` artifact
- `LangfuseTracingPlugin` — LLM tracing via OpenTelemetry

Worker observability flows through: `worker_after_model` → `_call_record` → `dispatch.py accumulators` → `flush_fn` → `tool_context.state`.

## Provider-Fake Test Infrastructure

The e2e test suite uses `FakeGeminiServer` (aiohttp) with canned JSON fixture responses — no network calls, fully deterministic.

| Component | File |
|-----------|------|
| Server | `tests_rlm_adk/provider_fake/server.py` |
| Contract runner | `tests_rlm_adk/provider_fake/contract_runner.py` |
| Fixture loader + structural matcher | `tests_rlm_adk/provider_fake/fixtures.py` |
| Fixture JSON files | `tests_rlm_adk/fixtures/provider_fake/*.json` |

Each fixture JSON defines `responses` (canned model replies), `config` (iterations, depth), and `expected_contract` (assertions on final state, caller sequence, tool results, observability keys).

`test_fmea_e2e.py` uses a **class-scoped `fmea_result` fixture** that runs each fixture once per test class and shares the `PluginContractResult` across all test methods — do not regress to per-method execution.

## ADK Pydantic Gotchas

- ADK agents are Pydantic models — use `object.__setattr__(agent, 'attr', value)` for dynamic attributes
- Can't use `MagicMock` as Pydantic field values in tests — create real agent instances and patch methods
- Mock `CallbackContext` must set `ctx._invocation_context.agent` (not `ctx.agent`)
- Must clear `worker.parent_agent = None` after each `ParallelAgent` batch (ADK sets parent in `model_post_init`, raises if already set)
