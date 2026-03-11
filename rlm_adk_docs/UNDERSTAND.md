<!-- last-audit: 2026-03-10 -->
<!-- source: ai_docs/codebase_documentation_research/PLAN.md -->
# RLM-ADK: Agent Orientation Guide

**Codebase Summary** RLM-ADK is a **recursive language model agentic system** built on Google ADK (`google.adk`). A single Gemini model acts as both parent and child. The parent writes Python code in a sandboxed REPL; that code can call `llm_query()` to spawn child agents with their own REPLs — recursion to arbitrary depth. 

## How to Use This Document

**You are a coding agent.** This is the single entrypoint for understanding the RLM-ADK codebase. Follow these rules:

1. **Read this file first.** It gives you the full picture in ~170 lines.
2. **Identify which branch(es) your task touches** from the index below.
3. **Read only the linked doc(s) for those branches.** Do not read docs unrelated to your task.

### Branch Index

| Branch | Doc | Read When Your Task Involves... |
|--------|-----|--------------------------------|
| Core Loop | [core_loop.md](core_loop.md) | Orchestrator, REPL, AST rewriting, recursion, types, execution flow |
| Dispatch & State | [dispatch_and_state.md](dispatch_and_state.md) | WorkerPool, dispatch closures, state keys, AR-CRIT-001, depth scoping |
| Observability | [observability.md](observability.md) | Plugins, callbacks, tracing, worker obs path, dashboard |
| Testing | [testing.md](testing.md) | Provider-fake, fixtures, FMEA, contract runners, markers, replay |
| Artifacts & Session | [artifacts_and_session.md](artifacts_and_session.md) | Session service, artifact persistence, save helpers |
| Skills & Prompts | [skills_and_prompts.md](skills_and_prompts.md) | Skill system, static/dynamic instructions, adding skills |
| Configuration | [configuration.md](configuration.md) | Env vars, factory functions, plugin wiring, pyproject.toml |
| Vision: Dynamic Skill Loading | [vision/dynamic_skill_loading.md](vision/dynamic_skill_loading.md) | REPL embeddings, vector store, skill retrieval, feedback loop |
| Vision: Polya Topology Engine | [vision/polya_topology_engine.md](vision/polya_topology_engine.md) | Understand→Plan→Implement→Reflect, horizontal/vertical/hybrid workflows |
| Vision: Autonomous Self-Improvement | [vision/autonomous_self_improvement.md](vision/autonomous_self_improvement.md) | Cron-triggered agents, gap audits, doc staleness, test expansion |
| Vision: Evolution Principles | [vision/evolution_principles.md](vision/evolution_principles.md) | Design philosophy, self-improvement feedback loops |

> **ADK Gotchas** are distributed as a final section in each branch doc above. Every doc includes the AR-CRIT-001 state mutation warning, plus gotchas specific to that branch (Pydantic constraints, private API, BUG-13, testing patterns, etc.).

---

## Core Loop

| Command | Entry | What It Does |
|---------|-------|-------------|
| `adk run rlm_adk` | CLI | Interactive agent session |
| `adk web rlm_adk` | Web UI | Browser-based session |
| `create_rlm_runner(model)` | `rlm_adk/agent.py` | Programmatic Runner with services + plugins |
| `create_rlm_app(model)` | `rlm_adk/agent.py` | App wrapper (no session/artifact service) |

```
RLMOrchestratorAgent (BaseAgent)
  └─ delegates to reasoning_agent.run_async(ctx)      ← ADK native tool loop
       └─ LlmAgent calls REPLTool ("execute_code")
            └─ REPLTool wraps LocalREPL
                 └─ Code calls llm_query() → AST-rewritten to async
                      └─ Dispatched via create_dispatch_closures()
                           └─ Child RLMOrchestratorAgent at depth+1 (recursion)
```

The orchestrator is **collapsed** — no manual iteration loop. ADK's native tool-calling loop handles all iteration, retry, and structured output validation.

**Deep dive:** [core_loop.md](core_loop.md) — factory functions, runner lifecycle, orchestrator internals, REPL mechanics, AST rewriting, recursion depth tracking

---

## Dispatch & State

**Critical rule (AR-CRIT-001):** Never write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. Use `tool_context.state`, `callback_context.state`, or `EventActions(state_delta={})`.

Dispatch closures use **local accumulators** + `flush_fn()` to atomically snapshot state after each REPL execution.

Recursive agents use **depth-scoped keys**: `depth_key("iteration_count", 2)` → `"iteration_count@d2"`.

**Deep dive:** [dispatch_and_state.md](dispatch_and_state.md) — all state keys, depth scoping rules, WorkerPool, accumulator pattern, flush_fn mechanics

---

## Observability

Plugins provide token accounting, tracing, and telemetry:

| Plugin | Role |
|--------|------|
| `ObservabilityPlugin` | Token accounting, finish reason tracking |
| `SqliteTracingPlugin` | Traces/telemetry/state events to `.adk/traces.db` |
| `REPLTracingPlugin` | Per-code-block REPL traces to `repl_traces.json` |
| `LangfuseTracingPlugin` | OTel auto-instrumentation to Langfuse UI |

Worker observability flows through a separate path: `worker_after_model` -> `_call_record` -> dispatch accumulators -> `flush_fn` -> `tool_context.state`.

**Deep dive:** [observability.md](observability.md) — plugin architecture, worker obs path, callback wiring, dashboard, trace levels

---

## Testing

Two e2e test systems, both fully deterministic (no network calls):

- **Provider-Fake**: `FakeGeminiServer` (aiohttp) serves canned JSON responses through the real production pipeline. 51 fixture files, ~28 default contract tests (~22s). FMEA failure mode coverage.
- **Live API Replay**: `adk run --replay` with pre-recorded conversation fixtures.

Default `pytest` runs only provider-fake contracts. Full suite (970+ tests) requires `-m ""`.

**Deep dive:** [testing.md](testing.md) — fixture schema, contract runner API, FMEA patterns, how to add fixtures, marker system

---

## Artifacts & Session

| Service | Role |
|---------|------|
| `SqliteSessionService` | Persistent state across invocations (`.adk/session.db`) |
| `FileArtifactService` | Versioned file persistence (`.adk/artifacts/`) |

Both are wired by `create_rlm_runner()` and passed to the ADK Runner.

**Deep dive:** [artifacts_and_session.md](artifacts_and_session.md) — session lifecycle, artifact versioning, save helpers

---

## Skills & Prompts

Skills use YAML frontmatter for discovery. Code-based skills are auto-imported into REPL globals. The `instructions` parameter (dynamic instruction slot) is currently a template with `{repo_url?}` and `{root_prompt?}` — this is the primary extension point for Polya topology and task-specific priming.

**Deep dive:** [skills_and_prompts.md](skills_and_prompts.md) — skill system, static vs dynamic instructions, child instruction condensation, repomix skill

---

## Configuration

Key env vars: `RLM_ADK_MODEL` (model), `RLM_MAX_ITERATIONS` (REPL call cap), `RLM_MAX_DEPTH` (recursion limit), `RLM_REPL_TRACE` (trace level 0/1/2). All plugin activation is env-var controlled.

**Deep dive:** [configuration.md](configuration.md) — all env vars, factory function signatures, plugin wiring, pyproject.toml settings

---

## Vision & Roadmap

RLM-ADK is Rawley Stanhope's personal agent — designed for a single power user, not multi-tenant deployment. It evolves through three planned capabilities:

| Feature | Status | Doc |
|---------|--------|-----|
| Dynamic skill loading from REPL execution history embeddings | Planned (research complete) | [vision/dynamic_skill_loading.md](vision/dynamic_skill_loading.md) |
| Polya topology engine — horizontal/vertical/hybrid workflows via dynamic instructions | Planned (research complete) | [vision/polya_topology_engine.md](vision/polya_topology_engine.md) |
| Autonomous self-improvement via cron-triggered agents | Conceptual | [vision/autonomous_self_improvement.md](vision/autonomous_self_improvement.md) |

Design philosophy: [vision/evolution_principles.md](vision/evolution_principles.md)

---

## Key Source Files

| File | Role |
|------|------|
| `rlm_adk/orchestrator.py` | RLMOrchestratorAgent — collapsed orchestrator |
| `rlm_adk/agent.py` | Factory functions (runner, app, orchestrator, child) |
| `rlm_adk/dispatch.py` | WorkerPool, dispatch closures, flush_fn |
| `rlm_adk/tools/repl_tool.py` | REPLTool (execute_code) |
| `rlm_adk/repl/local_repl.py` | Sandboxed Python REPL |
| `rlm_adk/repl/ast_rewriter.py` | Sync-to-async llm_query transform |
| `rlm_adk/state.py` | State key constants, depth_key() |
| `rlm_adk/callbacks/worker_retry.py` | Structured output self-healing, BUG-13 |
| `rlm_adk/plugins/observability.py` | Token accounting plugin |
| `rlm_adk/plugins/sqlite_tracing.py` | SQLite tracing plugin |
| `rlm_adk/repl/skill_registry.py` | Synthetic REPL skill import expansion |
| `rlm_adk/skills/repl_skills/ping.py` | First expandable skill module (recursive ping) |
| `tests_rlm_adk/provider_fake/` | FakeGeminiServer, contract runner |

---

## Document Freshness

Each linked doc has a `<!-- validated: YYYY-MM-DD -->` header. If the validated date is older than recent changes to the source files it documents, treat the doc as potentially stale and verify against source code before relying on it.

Source material and research: `ai_docs/codebase_documentation_research/`
