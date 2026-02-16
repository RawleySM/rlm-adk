# Port & Rebuild Guide: `rlm` on Google Agent Development Kit (ADK)

> **Version**: 2.0 — Updated 2026-02-15
> **Source codebase**: [`alexzhang13/rlm`](https://github.com/alexzhang13/rlm) (Recursive Language Models inference library)
> **Target framework**: [Google Agent Development Kit (ADK) for Python](https://google.github.io/adk-docs/) v1.7.0+

---

## Table of Contents

- [A. Executive Intent](#a-executive-intent)
- [B. Current System Map](#b-current-system-map)
- [C. ADK Rebuild Architecture](#c-adk-rebuild-architecture)
- [D. Callback & Plugin Plan](#d-callback--plugin-plan)
- [E. State Schema](#e-state-schema)
- [F. Porting the REPL + LMHandler Concept into ADK](#f-porting-the-repl--lmhandler-concept-into-adk)
- [G. Caching Strategy](#g-caching-strategy)
- [H. Observability & Audit Trail](#h-observability--audit-trail)
- [I. Type Validation & Safety](#i-type-validation--safety)
- [J. API/Messaging Integration](#j-apimessaging-integration)
- [K. Migration Plan](#k-migration-plan)
- [Next Actions](#next-actions)

---

## A. Executive Intent

### What behavior is preserved from `rlm`

1. **Recursive completion semantics.** A caller replaces `llm.completion(prompt)` with `rlm.completion(prompt)`. The system loads context into an execution environment, lets the LM write and execute code iteratively, supports sub-LM calls from within executed code, and terminates when a `FINAL(...)` or `FINAL_VAR(...)` pattern is found or max iterations are exhausted.
2. **Environment-based code execution.** Arbitrary Python code emitted by the LM executes in a sandboxed namespace (`LocalREPL`) or an isolated cloud sandbox (Modal, Prime, Docker, E2B, Daytona). The environment exposes `context`, `llm_query()`, `llm_query_batched()`, `FINAL_VAR()`, and `SHOW_VARS()` as globals.
3. **Multi-provider LM routing.** A default backend (depth 0) and an optional secondary backend (depth 1) are registered; code executing inside the environment can invoke either via `llm_query(prompt, model=...)`.
4. **Iteration-scoped prompt assembly.** Each iteration appends the LM response and code execution results to the message history, providing the LM with a growing chain-of-thought trajectory.
5. **Persistent (multi-turn) sessions.** When `persistent=True`, the `LocalREPL` environment survives across `completion()` calls, preserving the execution namespace, versioned contexts (`context_0`, `context_1`, ...), and versioned histories (`history_0`, `history_1`, ...).
6. **Usage tracking and observability.** Per-model token counts (input/output), per-iteration timing, and structured JSON-lines logging (`RLMLogger`) are available. A rich console verbose printer (`VerbosePrinter`) displays execution details.
7. **Sub-LM dispatch as in-REPL function calls.** `llm_query()` and `llm_query_batched()` are Python functions injected into the REPL execution namespace. Code written by the orchestrating LM calls them as regular functions; their return values (strings) flow back into the executing Python code for programmatic use — parsing, assignment, computation, structured output handling — not merely for printing.

### What changes because ADK becomes the execution substrate

| Concern | Current `rlm` | ADK rebuild |
|---------|---------------|-------------|
| Agent loop | Hand-rolled `for i in range(max_iterations)` in `RLM.completion()` | Custom `BaseAgent._run_async_impl` with iteration-state-driven termination |
| LM calls | `LMHandler` TCP socket server dispatching to `BaseLM.completion()` | ADK `LlmAgent` model calls; sub-calls via pre-allocated worker pool of `LlmAgent` instances dispatched from async REPL code |
| REPL execution | Synchronous `exec()` calling synchronous `llm_query()` over TCP sockets | AST-rewritten async REPL: code is transformed so `llm_query()` becomes `await llm_query_async()`, executed as `async def _repl_exec()` within `_run_async_impl` — no thread pool, no sync bridge |
| Sub-LM dispatch | `send_lm_request()` / `send_lm_request_batched()` over TCP | `llm_query_async()` dispatches to pre-allocated worker `LlmAgent` from `asyncio.Queue` pool; `llm_query_batched_async()` dispatches N workers via `asyncio.gather()` |
| Deterministic stages | Inline code in `RLM._completion_turn()` (code parsing, final answer extraction, iteration formatting) | Inline functions within `_run_async_impl` with explicit state writes; observability via `ObservabilityPlugin` callbacks on the orchestrator agent + manual state logging |
| Timeout/cancellation | TCP socket timeout; thread blocks indefinitely on hung API calls | Native `asyncio.wait_for(llm_query_async(...), timeout=N)` — cooperative cancellation propagates through sub-agent to HTTP client |
| State management | Ad-hoc instance variables (`self.locals`, `self._context_count`, `self._history_count`) | `session.state` with prefix-scoped keys; changes tracked via `Event.actions.state_delta` and persisted by `SessionService` |
| Observability | `RLMLogger` (JSON-lines) + `VerbosePrinter` (rich) | ADK `ObservabilityPlugin` at Runner level; `after_model_callback` / `after_agent_callback` for per-instance telemetry; structured state keys for metrics |
| Cross-cutting policy | Scattered `if` checks (depth validation, iteration limits) | ADK `BasePlugin` subclasses registered on Runner; `before_model_callback` / `before_agent_callback` for guardrails |
| Event yield | N/A (no event model) | Sub-agent events yield from `_run_async_impl` in real time; Runner sees state deltas as they occur; `SessionService` persists incrementally |

### Definition of "done" (parity criteria)

1. **Functional parity**: Given the same prompt, context, model, and environment type, the ADK rebuild produces equivalent final answers to the current `rlm` system across a reference evaluation suite.
2. **Behavioral parity**: Iteration count, sub-call routing (depth 0 vs depth 1), code execution side effects, and persistent-session state accumulation match current behavior.
3. **Performance parity**: Wall-clock time per completion is within 10% of the current system (excluding network variance from LM provider calls).
4. **Observability parity**: All metrics currently captured by `RLMLogger` and `VerbosePrinter` are available via ADK state keys and plugin exports.
5. **Extensibility parity**: New environments and LM clients can be added by implementing the corresponding ADK agent / model adapter without modifying core orchestration.
6. **Resilience improvement**: Hung LLM API calls are handled via `asyncio.wait_for()` timeouts, with clean cancellation propagation — an improvement over current blocking TCP behavior.

---

## B. Current System Map

### B.1 Lifecycle: prompt → REPL → code execution → subcalls → final response

```
User
 │
 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  RLM.completion(prompt, root_prompt=None)                               │
│                                                                         │
│  1. _spawn_completion_context(prompt)                                   │
│     ├── Create BaseLM client via get_client(backend, kwargs)            │
│     ├── Create LMHandler(client, other_backend_client=...)              │
│     │   └── Start ThreadingTCPServer on auto-assigned port              │
│     ├── Create Environment via get_environment(type, kwargs)            │
│     │   └── LocalREPL: setup() → sandboxed globals, load_context()     │
│     └── Yield (lm_handler, environment)                                 │
│                                                                         │
│  2. _setup_prompt(prompt)                                               │
│     ├── QueryMetadata(prompt) → context_lengths, context_type           │
│     └── build_rlm_system_prompt(metadata, ...) → message_history        │
│                                                                         │
│  3. Iteration loop (max_iterations):                                    │
│     ├── _completion_turn(current_prompt, lm_handler, environment)       │
│     │   ├── lm_handler.completion(prompt) → LM response text            │
│     │   ├── find_code_blocks(response) → list[str] of ```repl``` blocks │
│     │   ├── For each code block:                                        │
│     │   │   └── environment.execute_code(code) → REPLResult             │
│     │   │       ├── stdout, stderr, locals                              │
│     │   │       └── llm_calls (sub-calls made via llm_query)            │
│     │   └── Return RLMIteration(response, code_blocks, time)            │
│     ├── find_final_answer(response, environment)                        │
│     │   ├── FINAL_VAR(var) → execute FINAL_VAR in env → answer          │
│     │   └── FINAL(text) → extract text → answer                         │
│     ├── If final_answer: return it                                      │
│     ├── format_iteration(iteration) → new messages                      │
│     └── Append to message_history, continue                             │
│                                                                         │
│  4. If max_iterations exhausted:                                        │
│     └── _default_answer(message_history, lm_handler)                    │
│         └── Ask LM to provide final answer from full history            │
│                                                                         │
│  5. Cleanup: environment.cleanup(), lm_handler.stop()                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### B.2 Environment types and communication models

**Non-Isolated Environments (`NonIsolatedEnv`)**

- **`LocalREPL`**: Runs on the same machine. Uses `exec()` in a sandboxed namespace with safe builtins. `llm_query()` communicates with `LMHandler` via the TCP socket protocol (4-byte big-endian length prefix + UTF-8 JSON payload). The namespace provides `context`, `llm_query`, `llm_query_batched`, `FINAL_VAR`, and `SHOW_VARS`.
- Communication: Direct TCP socket connection to `LMHandler` at `(host, port)` using `send_lm_request()` / `send_lm_request_batched()` from `comms_utils.py`.

**How `llm_query` and `llm_query_batched` work in `LocalREPL`** (critical for the ADK mapping):

- `_llm_query(prompt, model=None)` is a method on `LocalREPL` injected into the REPL's execution namespace as `globals["llm_query"]`. When the LM-generated code calls `response = llm_query("some prompt")`, it synchronously opens a TCP socket to `LMHandler`, sends an `LMRequest`, waits for the `LMResponse`, tracks the call in `_pending_llm_calls`, and **returns the response string** to the calling code.
- `_llm_query_batched(prompts, model=None)` operates identically but sends multiple prompts via `send_lm_request_batched()`, collects responses in order, and **returns a `list[str]`** to the calling code.
- **Critical**: These return values are used programmatically by the executing code — not just printed. The RLMOrchestratorAgent writes code that may `json.loads(response)`, split strings, index into the result list, or feed responses into further computation. The return path must be a real Python string (or list of strings) flowing back into the execution namespace.

**Isolated Environments (`IsolatedEnv`)**

- **`ModalREPL`**, **`PrimeREPL`**, **`DockerREPL`**, **`DaytonaREPL`**, **`E2BREPL`**: Run in cloud sandboxes or containers. Cannot directly reach the host's TCP socket server.
- Communication: HTTP broker pattern.
  1. A Flask server runs inside the sandbox with endpoints: `/enqueue` (submit LLM request, blocks until response), `/pending` (poll pending requests), `/respond` (deliver response), `/health`.
  2. The host-side environment class runs a poller thread that polls `{tunnel_url}/pending` every ~100ms.
  3. When `llm_query()` is called inside the sandbox, it POSTs to `http://localhost:8080/enqueue`; the poller picks it up, forwards to `LMHandler` via TCP socket, and POSTs the response back to `{tunnel_url}/respond`.
  4. State is serialized via `dill` to `/tmp/rlm_state.dill` between code blocks.

### B.3 Extensibility points

| Extension | Base class | Registry | Location |
|-----------|-----------|----------|----------|
| LM clients | `BaseLM` (abstract: `completion`, `acompletion`, `get_usage_summary`, `get_last_usage`) | `get_client()` in `clients/__init__.py` | `rlm/clients/` |
| Environments | `NonIsolatedEnv` or `IsolatedEnv` (both extend `BaseEnv`; abstract: `setup`, `load_context`, `execute_code`) | `get_environment()` in `environments/__init__.py` | `rlm/environments/` |
| Persistence protocol | `SupportsPersistence` (`runtime_checkable Protocol`; methods: `update_handler_address`, `add_context`, `get_context_count`, `add_history`, `get_history_count`) | `isinstance()` check | `rlm/environments/base_env.py` |

### B.4 Key data types

| Type | Module | Purpose |
|------|--------|---------|
| `LMRequest` | `core/comms_utils.py` | Socket request: `prompt` or `prompts`, `model`, `depth` |
| `LMResponse` | `core/comms_utils.py` | Socket response: `chat_completion` or `chat_completions`, `error` |
| `REPLResult` | `core/types.py` | Execution result: `stdout`, `stderr`, `locals`, `llm_calls` |
| `CodeBlock` | `core/types.py` | Pairs code string with its `REPLResult` |
| `RLMIteration` | `core/types.py` | One iteration: `response`, `code_blocks`, `final_answer`, `iteration_time` |
| `RLMChatCompletion` | `core/types.py` | Record of one LLM call: `root_model`, `prompt`, `response`, `usage_summary`, `execution_time` |
| `ModelUsageSummary` | `core/types.py` | Per-model: `total_calls`, `total_input_tokens`, `total_output_tokens` |
| `UsageSummary` | `core/types.py` | Map of model name → `ModelUsageSummary` |
| `RLMMetadata` | `core/types.py` | Configuration snapshot: `max_depth`, `max_iterations`, `backend`, `environment_type`, etc. |
| `QueryMetadata` | `core/types.py` | Context metadata: `context_lengths`, `context_total_length`, `context_type` |

---

## C. ADK Rebuild Architecture

### C.1 Component diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              ADK Runner                                      │
│  plugins: [ObservabilityPlugin, CachePlugin, DepthGuardPlugin,               │
│            AuthPolicyPlugin, TypeValidationPlugin]                            │
│                                                                              │
│  SessionService: InMemorySessionService (dev) │                              │
│                  DatabaseSessionService (prod)                               │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │            RLMPooledOrchestratorAgent (custom BaseAgent)                │  │
│  │                                                                        │  │
│  │  sub_agents: [RLMReasoningAgent, Worker_0, Worker_1, ..., Worker_N,    │  │
│  │               DefaultAnswerAgent]                                      │  │
│  │  worker_pool: asyncio.Queue[LlmAgent]  (pre-allocated, size N)         │  │
│  │  ast_transformer: ReplAstTransformer                                   │  │
│  │  repl: LocalREPL (persistent namespace)                                │  │
│  │                                                                        │  │
│  │  before_agent_callback:                                                │  │
│  │    - Load prompt/context into state                                    │  │
│  │    - Initialize temp:iteration_count = 0, temp:recursion_depth = 0     │  │
│  │    - Initialize temp:max_iterations from config                        │  │
│  │                                                                        │  │
│  │  _run_async_impl(ctx):                                                 │  │
│  │    for iteration in range(max_iterations):                             │  │
│  │      ┌──────────────────────────────────────────────────────────────┐  │  │
│  │      │ 1. REASONING: yield from RLMReasoningAgent.run_async(ctx)    │  │  │
│  │      │    → Events flow to Runner in real time                      │  │  │
│  │      │    → temp:last_response written via after_model_callback     │  │  │
│  │      └──────────────────────────────────────────────────────────────┘  │  │
│  │      ┌──────────────────────────────────────────────────────────────┐  │  │
│  │      │ 2. CODE PARSING (inline, deterministic):                     │  │  │
│  │      │    code_blocks = find_code_blocks(temp:last_response)        │  │  │
│  │      │    → Write temp:pending_code_blocks to state                 │  │  │
│  │      │    → Log block count via state write                         │  │  │
│  │      └──────────────────────────────────────────────────────────────┘  │  │
│  │      ┌──────────────────────────────────────────────────────────────┐  │  │
│  │      │ 3. ASYNC REPL EXECUTION:                                     │  │  │
│  │      │    For each code block:                                      │  │  │
│  │      │    a. AST-transform code → async def _repl_exec()            │  │  │
│  │      │       llm_query(p) → await llm_query_async(p)               │  │  │
│  │      │       llm_query_batched(ps) → await llm_query_batched_async │  │  │
│  │      │    b. exec(transformed, namespace)                           │  │  │
│  │      │    c. await namespace['_repl_exec']()                        │  │  │
│  │      │       ├── When code awaits llm_query_async(prompt):          │  │  │
│  │      │       │   worker = await worker_pool.get()                   │  │  │
│  │      │       │   async for event in worker.run_async(ctx):          │  │  │
│  │      │       │       yield event  ← real-time to Runner             │  │  │
│  │      │       │   result = ctx.session.state[worker.output_key]      │  │  │
│  │      │       │   worker_pool.put_nowait(worker)                     │  │  │
│  │      │       │   return result (str) to REPL code                   │  │  │
│  │      │       │                                                      │  │  │
│  │      │       ├── When code awaits llm_query_batched_async(prompts): │  │  │
│  │      │       │   workers = [await pool.get() for _ in prompts]      │  │  │
│  │      │       │   results = await asyncio.gather(                    │  │  │
│  │      │       │     *[dispatch(w, p, ctx) for w, p in zip(...)]      │  │  │
│  │      │       │   )  ← parallel dispatch, events yielded             │  │  │
│  │      │       │   [pool.put_nowait(w) for w in workers]              │  │  │
│  │      │       │   return results (list[str]) to REPL code            │  │  │
│  │      │       │                                                      │  │  │
│  │      │       └── Timeout: asyncio.wait_for(..., timeout=N)          │  │  │
│  │      │           → CancelledError propagates to HTTP client          │  │  │
│  │      │    d. Capture stdout/stderr/locals → temp:repl_results       │  │  │
│  │      └──────────────────────────────────────────────────────────────┘  │  │
│  │      ┌──────────────────────────────────────────────────────────────┐  │  │
│  │      │ 4. FINAL ANSWER EXTRACTION (inline, deterministic):          │  │  │
│  │      │    final = find_final_answer(temp:last_response, env)        │  │  │
│  │      │    → If found: set temp:final_answer, break                  │  │  │
│  │      └──────────────────────────────────────────────────────────────┘  │  │
│  │      ┌──────────────────────────────────────────────────────────────┐  │  │
│  │      │ 5. ITERATION FORMATTING (inline):                            │  │  │
│  │      │    Append response + REPL results to temp:message_history    │  │  │
│  │      └──────────────────────────────────────────────────────────────┘  │  │
│  │                                                                        │  │
│  │    If max_iterations exhausted:                                        │  │
│  │      yield from DefaultAnswerAgent.run_async(ctx)                      │  │
│  │                                                                        │  │
│  │  after_agent_callback:                                                 │  │
│  │    - Record obs:total_wall_time, obs:total_iterations                  │  │
│  │    - Log final answer or exhaustion                                    │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │  RLMReasoningAgent (LlmAgent)                                    │  │  │
│  │  │    model: primary model (depth 0)                                │  │  │
│  │  │    before_model_callback: assemble prompt from state             │  │  │
│  │  │    after_model_callback: write temp:last_response                │  │  │
│  │  └──────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │  Worker_0 ... Worker_N (pre-allocated LlmAgents)                 │  │  │
│  │  │    model: secondary model (depth 1) or primary fallback          │  │  │
│  │  │    output_key: f"temp:worker_{i}_result"                         │  │  │
│  │  │    before_model_callback: inject prompt from state, validate     │  │  │
│  │  │    after_model_callback: track tokens, log response              │  │  │
│  │  │    Managed via asyncio.Queue (worker_pool)                       │  │  │
│  │  └──────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                        │  │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │  │
│  │  │  DefaultAnswerAgent (LlmAgent)                                   │  │  │
│  │  │    Invoked only when max_iterations exhausted                    │  │  │
│  │  │    Receives full message history from state                      │  │  │
│  │  │    Generates forced final answer                                 │  │  │
│  │  └──────────────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                         SessionService                                 │  │
│  │  Persists: session.state, session.events, state_delta                  │  │
│  │  Prefix routing: (none)→session, user:→user, app:→app, temp:→discard  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

### C.2 Runner + SessionService choices

| SessionService | When to use | Implications |
|----------------|-------------|--------------|
| `InMemorySessionService` | Development, testing, single-process deployments | State lost on restart; no cross-process sharing; fastest for iteration |
| `DatabaseSessionService` | Production, multi-process, persistent sessions | Full persistence of session/user/app state; supports `persistent=True` multi-turn |
| `VertexAiSessionService` | GCP-native deployments | Managed persistence on Vertex AI; integrated with GCP observability |

**Persistence mapping**: The current `rlm` `persistent=True` mode maps to an ADK session that persists across `runner.run_async()` invocations. Versioned contexts (`context_0`, `context_1`, ...) become session-scoped state keys. Versioned histories (`history_0`, `history_1`, ...) become session-scoped state keys holding serialized message lists. The `LocalREPL` instance is stored on the orchestrator agent and persists across invocations for the same session.

### C.3 Why a flat orchestrator with inline deterministic stages

Previous iterations of this design wrapped each deterministic stage (code parsing, REPL execution, final answer extraction) in a separate `BaseAgent` subclass. This is replaced with **inline functions within `_run_async_impl`** for three reasons:

1. **Event yield contract**: The orchestrator's `_run_async_impl` must `yield` sub-agent events as they occur. With separate `BaseAgent` wrappers, events from worker `LlmAgent`s dispatched by `llm_query_async()` inside the REPL cannot be yielded by the orchestrator — the intermediate agent's `_run_async_impl` would need to somehow forward events from code running inside `exec()`. By keeping REPL execution inline in the orchestrator, `yield event` can be called directly when workers produce events.
2. **Async REPL integration**: The AST-transformed REPL code runs as `await namespace['_repl_exec']()` within `_run_async_impl`. This must happen in the orchestrator's async context to enable native `await` of `llm_query_async()` calls and native `yield` of worker events. Wrapping this in a sub-agent adds a layer of indirection that breaks the event yield chain.
3. **Simplicity**: Deterministic stages (parsing, extraction) are 1-5 line function calls. Wrapping each in a `BaseAgent` with `before_agent_callback` / `after_agent_callback` adds boilerplate without benefit. Observability for these stages is achieved via explicit state writes (logged by `ObservabilityPlugin.on_event_callback`) and inline logging within `_run_async_impl`.

**What is preserved**: Global plugins (`ObservabilityPlugin`, `TypeValidationPlugin`, etc.) still fire their `before_agent_callback` / `after_agent_callback` on the `RLMPooledOrchestratorAgent` and on each worker `LlmAgent`. Validation and observability for the orchestrator as a whole is not lost — it is simply concentrated at the orchestrator boundary rather than distributed across sub-agents.

### C.4 RLM recursion mapped onto worker pool dispatch

The current `rlm` supports `max_depth` (currently only depth 0 and 1):

- **Depth 0**: The main RLM agent uses the `default_client`. This maps to `RLMReasoningAgent` (LlmAgent).
- **Depth 1**: Code executing in the environment calls `llm_query()`, which routes to `other_backend_client`. This maps to a pre-allocated worker `LlmAgent` from the pool, configured with the secondary model.
- **`llm_query` as a degenerate batched call**: `llm_query(prompt)` dispatches one worker. `llm_query_batched(prompts)` dispatches N workers via `asyncio.gather()`. Both paths use the same `llm_query_async` / `llm_query_batched_async` functions, which acquire workers from the `asyncio.Queue` pool.
- **Depth guard**: `DepthGuardPlugin.before_model_callback` fires on worker agents and checks `temp:recursion_depth < app:max_depth`. If exceeded, returns a synthetic `LlmResponse` with an error message. The async REPL code receives this as the return value of `llm_query_async()`.

### C.5 `temp:` key scoping

Per ADK documentation, sub-agents share the same `InvocationContext` and `temp:` namespace. This means:

- `temp:recursion_depth` is visible to workers and checked by `DepthGuardPlugin`.
- `temp:last_response` set by `RLMReasoningAgent` is readable by the orchestrator.
- `temp:worker_{i}_result` set by workers via `output_key` is readable by `llm_query_async`.
- **Namespace discipline for workers**: Each worker writes to `temp:worker_{i}_result` where `i` is the worker's index. The orchestrator's dispatch function reads this key immediately after the worker completes, before the key could be overwritten by a subsequent dispatch.

---

## D. Callback & Plugin Plan

### D.1 Plugin suite (global, Runner-registered)

All plugins extend `BasePlugin` and are registered in the `Runner`'s `plugins` parameter. Plugins execute **before** any agent/model-level callbacks. A plugin returning a value **short-circuits** downstream callbacks and the original operation.

#### D.1.1 `ObservabilityPlugin`

| Attribute | Detail |
|-----------|--------|
| **Name** | `observability` |
| **Trigger points** | `before_run_callback`, `after_run_callback`, `before_agent_callback`, `after_agent_callback`, `before_model_callback`, `after_model_callback`, `on_event_callback` |
| **State reads** | `temp:request_id`, `temp:invocation_start_time`, `temp:iteration_count` |
| **State writes** | `temp:invocation_start_time` (before_run), `obs:total_wall_time` (after_run), `obs:iteration_timings` (after_agent on orchestrator), `obs:model_call_count` (after_model), `obs:total_input_tokens` / `obs:total_output_tokens` (after_model), `obs:worker_dispatch_count` (after_model on workers), `obs:worker_dispatch_summaries` (after_model on workers) |
| **Exports** | Structured log records at each callback point including agent name, invocation ID, timing, and token counts. Emits to Python logging and optionally to external systems. |
| **Failure behavior** | Observe-only (returns `None`). Logs errors internally but never short-circuits the agent workflow. |

#### D.1.2 `CachePlugin`

| Attribute | Detail |
|-----------|--------|
| **Name** | `cache` |
| **Trigger points** | `before_model_callback`, `after_model_callback` |
| **State reads** | `app:cache_enabled`, `temp:cache_key` |
| **State writes** | `temp:cache_key`, `cache:hit_count` / `cache:miss_count`, `cache:last_hit_key` |
| **Behavior** | **Intervene pattern**: Fires on both `RLMReasoningAgent` and worker `LlmAgent` model calls. Computes fingerprint, checks cache. Cache hit returns `LlmResponse` directly, short-circuiting the API call. Particularly valuable for repeated sub-LM prompts across iterations. |
| **Failure behavior** | On cache backend failure, falls through (returns `None`). |

#### D.1.3 `DepthGuardPlugin`

| Attribute | Detail |
|-----------|--------|
| **Name** | `depth_guard` |
| **Trigger points** | `before_model_callback` |
| **State reads** | `temp:recursion_depth`, `app:max_depth` |
| **State writes** | — |
| **Behavior** | **Intervene pattern**: Fires on worker `LlmAgent` model calls. If `temp:recursion_depth >= app:max_depth`, returns a synthetic `LlmResponse` with an error message. The async REPL code receives this as the return value of `llm_query_async()`, matching current behavior where `_llm_query` returns `f"Error: {response.error}"`. Does **not** fire on `RLMReasoningAgent` (depth 0 is always allowed). |
| **Failure behavior** | Short-circuits with a clear error string. |

#### D.1.4 `AuthPolicyPlugin`

| Attribute | Detail |
|-----------|--------|
| **Name** | `auth_policy` |
| **Trigger points** | `before_agent_callback`, `before_model_callback`, `on_user_message_callback` |
| **State reads** | `user:api_key_hash`, `app:allowed_models`, `app:agent_permissions` |
| **State writes** | `temp:auth_validated`, `temp:auth_violation_reason` |
| **Behavior** | **Intervene pattern**: Validates API key, model allowlist, agent permissions. |
| **Failure behavior** | Short-circuits with policy violation message. |

#### D.1.5 `TypeValidationPlugin`

| Attribute | Detail |
|-----------|--------|
| **Name** | `type_validation` |
| **Trigger points** | `before_agent_callback`, `after_agent_callback`, `after_model_callback` |
| **State reads** | `app:agent_schemas` |
| **State writes** | `temp:validation_pass`, `temp:validation_errors` |
| **Behavior** | **Amend + observe pattern**: Validates state keys on orchestrator agent entry/exit. Validates model response structure on all `LlmAgent`s (reasoning + workers). |
| **Failure behavior** | Short-circuits in `before_agent_callback` on critical schema violations; observe-only in `after_*` callbacks. |

### D.2 Local callback suite (per-agent instance)

#### D.2.1 `RLMPooledOrchestratorAgent` callbacks

| Callback | Trigger | State reads | State writes | Observability | Failure |
|----------|---------|-------------|--------------|---------------|---------|
| `before_agent_callback` | Before orchestrator starts | `app:max_iterations`, `app:max_depth`, `app:system_prompt`, `app:worker_timeout_seconds` | `temp:iteration_count = 0`, `temp:max_iterations`, `temp:recursion_depth = 0`, `temp:invocation_start_time`, `temp:message_history = []`, `temp:worker_dispatch_count = 0` | Logs orchestrator entry with config, worker pool size | Returns error `Content` if critical config missing |
| `after_agent_callback` | After orchestrator completes | `temp:final_answer`, `temp:iteration_count`, `temp:invocation_start_time` | `obs:total_wall_time`, `obs:total_iterations`, `obs:total_worker_dispatches` | Logs orchestrator exit with total time, iterations, worker dispatch count | Returns `None` (observe-only) |

#### D.2.2 `RLMReasoningAgent` callbacks

| Callback | Trigger | State reads | State writes | Observability | Failure |
|----------|---------|-------------|--------------|---------------|---------|
| `before_model_callback` | Before each LM call | `temp:message_history`, `temp:iteration_count`, `context_metadata`, `app:system_prompt` | Modifies `llm_request.contents` to include assembled prompt | Logs prompt assembly details | Returns `None` (amend pattern) |
| `after_model_callback` | After each LM call | `temp:iteration_count` | `temp:last_response`, `temp:iteration_count` (increment) | Logs response length | Returns `None` (observe + amend) |

#### D.2.3 Worker `LlmAgent` callbacks

Each pre-allocated worker has these callbacks configured at construction time:

| Callback | Trigger | State reads | State writes | Observability | Failure |
|----------|---------|-------------|--------------|---------------|---------|
| `before_model_callback` | Before worker model call | `temp:worker_{i}_prompt` (injected by dispatch function) | Modifies `llm_request.contents` to use the injected prompt | Logs prompt (truncated), model, worker index | Returns `None` (amend) |
| `after_model_callback` | After worker model call | — | `obs:worker_token_usage` (appended: `{worker, model, in_tokens, out_tokens}`) | Logs response length, tokens | Returns `None` (observe) |

**Prompt injection via `before_model_callback`**: The dispatch function writes the prompt to `temp:worker_{i}_prompt` before calling `worker.run_async(ctx)`. The worker's `before_model_callback` reads this key and sets `llm_request.contents` accordingly. This allows prompt injection without modifying the `LlmAgent.instruction` at runtime, using the standard ADK callback amend pattern.

---

## E. State Schema

### E.1 State key taxonomy

#### Flow Control Keys

| Key | Prefix | Scope | Owner (writes) | Valid during | Serialization | Example value |
|-----|--------|-------|-----------------|--------------|---------------|---------------|
| `temp:iteration_count` | `temp:` | Invocation | Orchestrator `before_agent_callback` (init), `_run_async_impl` (increment) | Current invocation only | `int` | `3` |
| `temp:max_iterations` | `temp:` | Invocation | Orchestrator `before_agent_callback` | Current invocation only | `int` | `15` |
| `temp:recursion_depth` | `temp:` | Invocation | Orchestrator `before_agent_callback` (init=0), dispatch function (increment/decrement) | Current invocation only | `int` | `0` |
| `app:max_depth` | `app:` | App-global | App initialization | Always | `int` | `1` |
| `app:worker_timeout_seconds` | `app:` | App-global | App initialization | Always | `float` | `60.0` |
| `temp:final_answer` | `temp:` | Invocation | Orchestrator `_run_async_impl` (after extraction) | Current invocation only | `str` or `None` | `"The answer is 42."` |
| `temp:stop_reason` | `temp:` | Invocation | Orchestrator `_run_async_impl` | Current invocation only | `str` | `"final_answer_found"` / `"max_iterations"` |
| `temp:pending_code_blocks` | `temp:` | Invocation | Orchestrator `_run_async_impl` (after parsing) | Current invocation only | `list[str]` | `["x = sum(context)\nprint(x)"]` |
| `temp:last_response` | `temp:` | Invocation | `RLMReasoningAgent.after_model_callback` | Current invocation only | `str` | `"Let me calculate..."` |
| `temp:message_history` | `temp:` | Invocation | Orchestrator `_run_async_impl` | Current invocation only | `list[dict]` | `[{"role": "system", "content": "..."}]` |

#### Worker Dispatch Keys

| Key | Prefix | Scope | Owner (writes) | Valid during | Serialization | Example value |
|-----|--------|-------|-----------------|--------------|---------------|---------------|
| `temp:worker_{i}_prompt` | `temp:` | Invocation | Dispatch function (before `worker.run_async`) | During single worker dispatch; overwritten per dispatch | `str` | `"Classify sentiment: ..."` |
| `temp:worker_{i}_result` | `temp:` | Invocation | Worker `LlmAgent` via `output_key` | After worker completes; read immediately by dispatch function | `str` | `"positive"` |
| `temp:worker_dispatch_count` | `temp:` | Invocation | Dispatch function (increment per dispatch) | Current invocation only | `int` | `5` |
| `temp:pending_llm_calls` | `temp:` | Invocation | Dispatch function (appended per dispatch) | Current invocation only | `list[dict]` | `[{"model": "gpt-4", "prompt": "...", "response": "...", "tokens": {...}}]` |

#### Caching Keys

| Key | Prefix | Scope | Owner (writes) | Valid during | Serialization | Example value |
|-----|--------|-------|-----------------|--------------|---------------|---------------|
| `app:cache_enabled` | `app:` | App-global | App initialization | Always | `bool` | `True` |
| `cache:hit_count` | (none) | Session | `CachePlugin` | Session lifetime | `int` | `7` |
| `cache:miss_count` | (none) | Session | `CachePlugin` | Session lifetime | `int` | `12` |
| `cache:last_hit_key` | (none) | Session | `CachePlugin` | Session lifetime | `str` | `"model:gpt-4:hash:abc123"` |
| `temp:cache_key` | `temp:` | Invocation | `CachePlugin.before_model_callback` | Current invocation only | `str` | `"model:gpt-4:hash:abc123"` |

#### Observability Keys

| Key | Prefix | Scope | Owner (writes) | Valid during | Serialization | Example value |
|-----|--------|-------|-----------------|--------------|---------------|---------------|
| `temp:request_id` | `temp:` | Invocation | `ObservabilityPlugin.before_run_callback` | Current invocation only | `str` (UUID) | `"inv-a1b2c3d4"` |
| `temp:invocation_start_time` | `temp:` | Invocation | `ObservabilityPlugin.before_run_callback` | Current invocation only | `float` (epoch) | `1739644800.123` |
| `obs:total_wall_time` | (none) | Session | `ObservabilityPlugin.after_run_callback` | Session lifetime | `float` (seconds) | `12.45` |
| `obs:total_iterations` | (none) | Session | Orchestrator `after_agent_callback` | Session lifetime | `int` | `5` |
| `obs:model_call_count` | (none) | Session | `ObservabilityPlugin.after_model_callback` | Session lifetime | `int` | `8` |
| `obs:total_input_tokens` | (none) | Session | `ObservabilityPlugin.after_model_callback` | Session lifetime | `int` | `15420` |
| `obs:total_output_tokens` | (none) | Session | `ObservabilityPlugin.after_model_callback` | Session lifetime | `int` | `3210` |
| `obs:worker_dispatch_count` | (none) | Session | Orchestrator `after_agent_callback` | Session lifetime | `int` | `10` |
| `obs:worker_dispatch_summaries` | (none) | Session | `ObservabilityPlugin.after_model_callback` (on workers) | Session lifetime | `list[dict]` | `[{"worker": "Worker_0", "time": 0.5}]` |
| `obs:iteration_timings` | (none) | Session | `ObservabilityPlugin.after_agent_callback` | Session lifetime | `list[float]` | `[1.2, 0.8, 2.1]` |
| `obs:code_execution_timings` | (none) | Session | Orchestrator `_run_async_impl` (state write) | Session lifetime | `list[float]` | `[0.3, 0.1, 0.5]` |
| `obs:worker_token_usage` | (none) | Session | Worker `after_model_callback` | Session lifetime | `list[dict]` | `[{"model": "gpt-4", "in": 500, "out": 120}]` |

#### Type Validation Keys

| Key | Prefix | Scope | Owner (writes) | Valid during | Serialization | Example value |
|-----|--------|-------|-----------------|--------------|---------------|---------------|
| `app:agent_schemas` | `app:` | App-global | App initialization | Always | `dict[str, dict]` | `{"RLMPooledOrchestratorAgent": {"input": {...}, "output": {...}}}` |
| `temp:validation_pass` | `temp:` | Invocation | `TypeValidationPlugin` | Current invocation only | `bool` | `True` |
| `temp:validation_errors` | `temp:` | Invocation | `TypeValidationPlugin` | Current invocation only | `list[str]` | `["Missing temp:last_response"]` |
| `validation:total_failures` | (none) | Session | `TypeValidationPlugin` | Session lifetime | `int` | `2` |
| `validation:failure_log` | (none) | Session | `TypeValidationPlugin` | Session lifetime | `list[dict]` | `[{"agent": "Worker_0", "error": "...", "time": ...}]` |

#### API/Messaging Integration Keys

| Key | Prefix | Scope | Owner (writes) | Valid during | Serialization | Example value |
|-----|--------|-------|-----------------|--------------|---------------|---------------|
| `temp:request_id` | `temp:` | Invocation | `ObservabilityPlugin.before_run_callback` | Current invocation only | `str` (UUID) | `"req-e5f6g7h8"` |
| `temp:idempotency_key` | `temp:` | Invocation | `AuthPolicyPlugin.on_user_message_callback` | Current invocation only | `str` | `"idem-x9y0z1"` |
| `user:api_key_hash` | `user:` | User | External auth system | Cross-session | `str` (SHA-256) | `"a1b2c3..."` |
| `app:allowed_models` | `app:` | App-global | App initialization | Always | `list[str]` | `["gpt-4", "gemini-2.0-flash"]` |
| `temp:auth_validated` | `temp:` | Invocation | `AuthPolicyPlugin` | Current invocation only | `bool` | `True` |

#### Context & Persistence Keys (multi-turn sessions)

| Key | Prefix | Scope | Owner (writes) | Valid during | Serialization | Example value |
|-----|--------|-------|-----------------|--------------|---------------|---------------|
| `context_count` | (none) | Session | Orchestrator `before_agent_callback` | Session lifetime | `int` | `3` |
| `context_0` | (none) | Session | Orchestrator `before_agent_callback` | Session lifetime | `str` or `dict` or `list` | `"The quick brown fox..."` |
| `history_count` | (none) | Session | Orchestrator `after_agent_callback` | Session lifetime | `int` | `2` |
| `history_0` | (none) | Session | Orchestrator `after_agent_callback` | Session lifetime | `list[dict]` | `[{"role": "user", "content": "..."}]` |

### E.2 State update rules

1. **Always use context-managed state updates.** Modify `ctx.session.state` within `_run_async_impl` or `callback_context.state` within callbacks. Changes are automatically tracked in `Event.actions.state_delta`. **Never** modify `session.state` directly outside of these contexts.
2. **Prefix discipline.** `temp:` for invocation-scoped, no prefix for session-scoped, `user:` for cross-session per user, `app:` for app-global.
3. **Serialization constraint.** All values must be JSON-serializable primitives.
4. **`temp:` keys are discarded after invocation.** Workers and orchestrator share `temp:` keys within the same invocation.

---

## F. Porting the REPL + LMHandler Concept into ADK

### F.1 Core design principle: `llm_query` as a REPL-namespace-injected function, not a Tool

This principle is unchanged from the original analysis. `llm_query()` and `llm_query_batched()` are Python functions injected into the REPL namespace. They are called by code written by the LLM executing in `exec()`, not by the LLM via function-calling. Return values are used programmatically (JSON parsing, string splitting, aggregation, conditional logic). See Section B.2 for the full analysis.

### F.2 The AST transformer: converting sync REPL code to async

**Problem**: ADK agents are async. The REPL uses `exec()`, which is synchronous. `llm_query()` inside `exec()` must dispatch to ADK worker agents (async) and return a string to the executing code.

**Solution**: Instead of a sync-to-async bridge with thread pools, **AST-transform** the LM-generated code so that `llm_query()` calls become `await llm_query_async()` calls, and the entire code block is wrapped in an `async def` that can be `await`-ed from `_run_async_impl`.

**Transformation steps** (implemented as `ReplAstTransformer`, an `ast.NodeTransformer` subclass):

1. **Parse** the code string into an AST via `ast.parse(code)`.
2. **Pass 1 — Identify async-needing functions**: Walk the AST to find all function definitions (`FunctionDef`) that transitively call `llm_query` or `llm_query_batched`. Mark these for conversion to `AsyncFunctionDef`.
3. **Pass 2 — Transform**:
   - Every `Call` node where `func` is `Name('llm_query')` → rename to `Name('llm_query_async')` and wrap in `Await`.
   - Every `Call` node where `func` is `Name('llm_query_batched')` → rename to `Name('llm_query_batched_async')` and wrap in `Await`.
   - Every marked `FunctionDef` → convert to `AsyncFunctionDef`.
   - Every `Call` to a marked function → wrap in `Await`.
4. **Wrap** the entire transformed body in `async def _repl_exec(): ...`.
5. **Compile** and return the transformed module.

**What the transform produces** — given this LM-generated code:

```python
response = llm_query("Classify: " + text)
data = json.loads(response)
if data["sentiment"] == "positive":
    details = llm_query("Elaborate: " + text)
```

The transformer produces:

```python
async def _repl_exec():
    response = await llm_query_async("Classify: " + text)
    data = json.loads(response)
    if data["sentiment"] == "positive":
        details = await llm_query_async("Elaborate: " + text)
```

**Edge case handling**:

| Edge case | Detection | Handling |
|-----------|-----------|---------|
| `llm_query()` at top level / in `for`/`if`/`while` | Direct AST match | Standard `Await` wrap — works in Python 3.12+ |
| `llm_query()` in list comprehension | AST match inside `ListComp` | `Await` inside comprehension — valid in `async def` since Python 3.6+ |
| `llm_query()` in nested `def` | Pass 1 marks the function | Convert to `async def`, convert call sites to `await` |
| `llm_query()` in lambda | AST match inside `Lambda` | **Reject**: raise `ValueError("llm_query() cannot be used inside lambda; restructure code")` — REPL returns error to LM for retry |
| `llm_query()` in class body | AST match inside `ClassDef` | **Reject**: raise `ValueError` with guidance |
| No `llm_query()` calls | Pass 1 finds nothing | Skip wrapping; run code synchronously via normal `exec()` |

### F.3 Async REPL execution within `_run_async_impl`

The orchestrator's `_run_async_impl` executes each code block as follows:

```
For each code_block in temp:pending_code_blocks:
  1. transformed = ast_transformer.transform(code_block)
  2. If no llm_query calls found (pure deterministic code):
       exec(code_block, combined_namespace)
       → Synchronous, no async wrapper needed
  3. If llm_query calls found:
       exec(compile(transformed, ...), combined_namespace)
       → This defines _repl_exec() in the namespace
       async for event in _repl_exec_with_events(namespace['_repl_exec'], ctx):
           yield event
  4. Capture stdout/stderr/locals → write temp:repl_results to state
```

**`_repl_exec_with_events`**: A helper async generator that runs the async REPL function while collecting and yielding events from worker dispatches. The `llm_query_async` closure (injected into the namespace) collects events from `worker.run_async(ctx)` into a shared queue, and `_repl_exec_with_events` drains this queue while the REPL code executes.

**Why this aligns with ADK**: The `_run_async_impl` async generator `yield`s events from workers in real time. The Runner sees `state_delta` entries as they occur. `SessionService` can persist incrementally. No events are lost or delayed.

### F.4 Worker pool design and dispatch

**Initialization**: The orchestrator pre-allocates N worker `LlmAgent` instances at construction time (default N=4, configurable via `app:worker_pool_size`):

```
worker_pool = asyncio.Queue()
for i in range(N):
    worker = LlmAgent(
        name=f"Worker_{i}",
        model=secondary_model,
        instruction="",  # Injected dynamically via before_model_callback
        output_key=f"temp:worker_{i}_result",
        before_model_callback=worker_before_model,
        after_model_callback=worker_after_model,
    )
    worker_pool.put_nowait(worker)
```

Workers are registered in `sub_agents` so the ADK framework manages their lifecycle and plugins fire on their callbacks.

**Dispatch function** (injected into REPL namespace as `llm_query_async`):

```
async def llm_query_async(prompt, model=None):
    worker = await asyncio.wait_for(
        worker_pool.get(), timeout=5.0
    )  # Wait for available worker, timeout if pool exhausted
    try:
        ctx.session.state[f"temp:worker_{worker_idx}_prompt"] = prompt
        ctx.session.state["temp:recursion_depth"] += 1
        async for event in asyncio.wait_for(
            worker.run_async(ctx), timeout=worker_timeout
        ):
            event_queue.put_nowait(event)  # Collected by _repl_exec_with_events
        result = ctx.session.state.get(worker.output_key, "Error: no response")
        # Track the call
        ctx.session.state["temp:worker_dispatch_count"] += 1
        return result
    except asyncio.TimeoutError:
        return "Error: LM query timed out"
    except asyncio.CancelledError:
        return "Error: LM query cancelled"
    finally:
        ctx.session.state["temp:recursion_depth"] -= 1
        await worker_pool.put(worker)
```

**Batched dispatch** (injected as `llm_query_batched_async`):

```
async def llm_query_batched_async(prompts, model=None):
    workers = []
    for _ in prompts:
        w = await asyncio.wait_for(worker_pool.get(), timeout=5.0)
        workers.append(w)
    try:
        tasks = [
            _dispatch_single(worker, prompt, ctx)
            for worker, prompt in zip(workers, prompts)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            r if isinstance(r, str) else f"Error: {r}"
            for r in results
        ]
    finally:
        for w in workers:
            await worker_pool.put(w)
```

`asyncio.gather()` dispatches all workers concurrently, matching the parallelism of the current `send_lm_request_batched()`.

### F.5 Timeout and cancellation

**Per-call timeout**: Every `llm_query_async()` call wraps the worker dispatch in `asyncio.wait_for(..., timeout=worker_timeout)`. The timeout is configurable via `app:worker_timeout_seconds` (default: 60s).

**What happens on timeout**:
1. `asyncio.wait_for` raises `asyncio.TimeoutError`.
2. The underlying task (worker's model call) is cancelled via `task.cancel()`.
3. `CancelledError` propagates through the worker agent's `run_async`, through ADK's model call infrastructure, to the underlying HTTP client (which should support cancellation via `aiohttp` or similar).
4. The `finally` block in the dispatch function returns the worker to the pool and decrements `temp:recursion_depth`.
5. `llm_query_async` returns `"Error: LM query timed out"` to the REPL code, matching current error-return behavior.
6. The REPL code continues executing with the error string — the LM can handle this in subsequent iterations.

**Pool exhaustion timeout**: If all N workers are busy and a new `llm_query_async()` call arrives, `asyncio.wait_for(worker_pool.get(), timeout=5.0)` waits up to 5 seconds for a worker to become available. If none does, it raises `TimeoutError` and returns an error string.

**Contrast with sync bridge**: In the previous sync bridge design, a hung API call would block a thread pool thread indefinitely (or until the `.result(timeout)` expired), consuming OS thread resources. The event loop couldn't yield events from the stuck sub-agent. Cancellation was advisory, not enforced. In the AST async approach, a hung API call consumes only an asyncio task — the event loop remains responsive, events from other operations continue flowing, and cancellation is cooperative through the async chain.

### F.6 Event yield contract: why this matters for ADK

ADK's `BaseAgent._run_async_impl` is an async generator. The Runner consumes events from it via `async for event in agent.run_async(ctx)`. Sub-agent events must be `yield`-ed by the parent:

```python
async for event in self.some_sub_agent.run_async(ctx):
    yield event
```

If the parent doesn't yield sub-agent events, the Runner never sees them. `state_delta` entries from sub-agent events are not persisted. Observability plugins don't fire on them.

In the AST async approach, the orchestrator's `_run_async_impl` directly yields events from worker dispatches via the event queue mechanism in `_repl_exec_with_events`. This means:
- Worker model call events (tokens, latency, response) are visible to the Runner in real time.
- `CachePlugin` hit/miss events are recorded as they happen.
- `DepthGuardPlugin` interventions produce events immediately.
- `SessionService` can persist state incrementally during long code executions.

### F.7 Structured output and programmatic return values

Unchanged from previous analysis. The response string from each worker `LlmAgent` flows through `output_key` → `session.state` → dispatch function → `llm_query_async()` return value → REPL code **unmodified**. All programmatic use patterns (JSON parsing, batched classification, multi-step extraction, conditional sub-queries) are supported.

### F.8 LM handler replacement

**Eliminated for non-isolated environments**: `LMHandler` TCP server, `LMRequest`/`LMResponse` protocol, `send_lm_request()`/`send_lm_request_batched()`.

| Current rlm | ADK equivalent |
|-------------|----------------|
| `LMHandler.get_client(depth=0)` | `RLMReasoningAgent` (LlmAgent) |
| `LMHandler.get_client(depth=1)` | Pre-allocated worker `LlmAgent` from pool |
| `send_lm_request(address, req)` | `await worker.run_async(ctx)` |
| `send_lm_request_batched(addr, prompts)` | `await asyncio.gather(*[dispatch(w, p, ctx) ...])` |
| `_llm_query(prompt)` in REPL | `await llm_query_async(prompt)` (AST-transformed) |
| `_llm_query_batched(prompts)` in REPL | `await llm_query_batched_async(prompts)` (AST-transformed) |

**What remains**: TCP socket / HTTP broker pattern retained **only** for isolated environments.

### F.9 Decision-to-mechanism mapping

| Decision | Mechanism | Why |
|----------|-----------|-----|
| Should we iterate again? | `temp:iteration_count < temp:max_iterations` in `_run_async_impl` | State-driven; observable via `obs:iteration_timings` |
| Is recursion depth exceeded? | `DepthGuardPlugin.before_model_callback` on workers | Plugin enforces globally |
| Should this model call be cached? | `CachePlugin.before_model_callback` on all LlmAgents | Plugin intervenes globally |
| Is this call authorized? | `AuthPolicyPlugin.before_model_callback` | Plugin enforces globally |
| Is there a final answer? | Inline `find_final_answer()` + state write in `_run_async_impl` | Deterministic; state write triggers `on_event_callback` for observability |
| How to handle a hung API call? | `asyncio.wait_for()` wrapping worker dispatch | Native async timeout; cancellation propagates to HTTP client |
| How to dispatch N sub-LM calls? | `asyncio.gather()` over N worker dispatches | Concurrent execution; pool manages resource limits |

---

## G. Caching Strategy

### G.1 Global cache plugin design

The `CachePlugin` implements the **intervene** pattern on `before_model_callback`, short-circuiting model API calls when a cached response exists. Fires on both `RLMReasoningAgent` and worker `LlmAgent` model calls. Sub-LM caching is automatic — repeated sub-LM prompts across iterations or within batched dispatches hit the cache.

### G.2 Cache key design

```
Format: "{scope}:{model}:{content_hash}"
Examples:
  "model:gemini-2.0-flash:sha256:a1b2c3d4..."
  "model:gpt-4:sha256:e5f6g7h8..."
```

Canonicalization: Strip whitespace artifacts, sort keys, exclude non-semantic fields.

### G.3 Invalidation

| Strategy | When | How |
|----------|------|-----|
| TTL-based | Always | Default 5 min for model responses |
| Context-change | New context loaded | Bump `cache:context_version` |
| Manual | User-triggered | Set `app:cache_enabled = False` |

### G.4 Storage backend options

| Backend | When | Tradeoffs |
|---------|------|-----------|
| `session.state` | Small caches, dev | Limited by state size |
| External Redis | Production | TTL support, survives restarts |
| ADK Artifacts | Large responses | `save_artifact` / `load_artifact` |

### G.5 Telemetry keys

| Key | Type | Description |
|-----|------|-------------|
| `cache:hit_count` | `int` | Total cache hits in session |
| `cache:miss_count` | `int` | Total cache misses in session |
| `cache:last_hit_key` | `str` | Most recent cache hit key |
| `cache:hit_rate` | `float` | `hit_count / (hit_count + miss_count)` |

---

## H. Observability & Audit Trail

### H.1 Event model: state changes as `state_delta`

Every state modification through `ctx.session.state` within `_run_async_impl` is captured in `Event.actions.state_delta` and persisted by `SessionService`. In the AST async architecture, worker events are yielded in real time, so state deltas from sub-LM dispatches appear in the event stream as they occur — not batched after code execution completes.

### H.2 Plugin-level vs inline-level observability

| Level | What gets logged | By whom | How |
|-------|-----------------|---------|-----|
| **Plugin (global)** | Every model call (tokens, latency), cache hits/misses, policy checks, agent entry/exit | `ObservabilityPlugin` | Callbacks on orchestrator + workers; state deltas tracked automatically |
| **Inline (orchestrator)** | Code parsing results (block count), REPL execution results (stdout/stderr), final answer detection, worker dispatch counts | `_run_async_impl` | Explicit `ctx.session.state` writes; `on_event_callback` fires on each state change |

### H.3 End-to-end invocation tracing

Traceable via `temp:request_id` (invocation-scoped UUID) + `session.id` + `user_id`. Worker events include `event.author = "Worker_0"` etc. Full trace reconstruction via session event history query.

### H.4 Migration from current logging

| Current `rlm` | ADK equivalent |
|----------------|----------------|
| `RLMLogger.log(iteration)` | `ObservabilityPlugin.on_event_callback` → structured log export |
| `VerbosePrinter.print_iteration(...)` | Orchestrator `after_agent_callback` with optional rich output |
| `VerbosePrinter.print_code_execution(...)` | Inline state write after REPL exec; plugin observes |
| `UsageSummary` / `ModelUsageSummary` | `obs:total_input_tokens`, `obs:total_output_tokens`, `obs:model_call_count`, `obs:worker_token_usage` |
| `_pending_llm_calls` | `temp:pending_llm_calls` populated by dispatch function |

---

## I. Type Validation & Safety

### I.1 What must be validated at boundaries

| Boundary | What to validate | Schema source |
|----------|-----------------|---------------|
| **Orchestrator entry** | Required `app:` config keys exist; context loaded | `app:agent_schemas` |
| **Worker model I/O** | `temp:worker_{i}_prompt` is non-empty string; output is non-empty string | `TypeValidationPlugin.before_model_callback` / `after_model_callback` |
| **Reasoning model I/O** | `llm_request.contents` non-empty; `LlmResponse` has valid parts | `TypeValidationPlugin.after_model_callback` |
| **AST transformation** | Code parses without syntax errors; unsupported patterns (lambda, class body) detected | `ReplAstTransformer` raises `ValueError` |

### I.2 Failure handling

- Worker `before_model_callback` failure: `DepthGuardPlugin` or `TypeValidationPlugin` returns synthetic `LlmResponse` with error string. `llm_query_async()` returns this to REPL code.
- AST transform failure: `ValueError` caught in orchestrator; error appended to REPL stderr; LM sees error and can retry.
- Worker timeout: `asyncio.TimeoutError` caught; error string returned to REPL code.

### I.3 "Fail fast, fail loud" alignment

1. **Missing API key** → `AuthPolicyPlugin` returns error `Content` immediately.
2. **Depth exceeded** → `DepthGuardPlugin` returns error `LlmResponse`; REPL code receives error string.
3. **AST unsupported pattern** → `ValueError` with specific guidance ("llm_query cannot be used inside lambda").
4. **Worker timeout** → Error string returned; LM can adjust strategy.
5. **Serialization failure** → ADK raises immediately; not caught.

---

## J. API/Messaging Integration

### J.1 Where inbound/outbound messaging occurs

| Point | Direction | ADK location | Current `rlm` equivalent |
|-------|-----------|-------------|--------------------------|
| User prompt | Inbound | `Runner.run_async(new_message=...)` | `RLM.completion(prompt)` |
| LM request (depth 0) | Outbound | `RLMReasoningAgent` model call | `LMHandler.completion(prompt)` |
| Sub-LM request from REPL | Outbound | `await llm_query_async(prompt)` → worker `LlmAgent` model call | `llm_query(prompt)` → `send_lm_request()` → `LMHandler` |
| REPL code execution | Internal | `await _repl_exec()` within `_run_async_impl` | `exec()` in namespace |
| Final response | Outbound | `Event` with `is_final_response() == True` | Return value of `RLM.completion()` |

### J.2 Auth/policy enforcement

Via `AuthPolicyPlugin` — validates API keys, model allowlists, agent permissions at `before_model_callback` / `before_agent_callback`. Rate limiting via session-scoped counters.

---

## K. Migration Plan

### K.1 Incremental port strategy

**Phase 1: Core orchestrator + reasoning agent (2 weeks)**
1. Implement `RLMPooledOrchestratorAgent` as custom `BaseAgent` with `_run_async_impl` iteration loop.
2. Implement `RLMReasoningAgent` as `LlmAgent` with prompt assembly and response capture callbacks.
3. Inline deterministic stages (code parsing, final answer extraction) in `_run_async_impl`.
4. Register with `InMemoryRunner`.
5. **Milestone**: Single-turn completion works with one model, no sub-LM calls.

**Phase 2: AST transformer + worker pool (2 weeks)**
1. Implement `ReplAstTransformer` (`ast.NodeTransformer`) with two-pass transform.
2. Build comprehensive test suite for AST transformation: top-level calls, control flow, comprehensions, nested functions, lambda rejection.
3. Pre-allocate worker `LlmAgent` pool with `asyncio.Queue`.
4. Implement `llm_query_async()` / `llm_query_batched_async()` dispatch functions with `asyncio.wait_for()` timeouts.
5. Implement `_repl_exec_with_events` event yield mechanism.
6. Implement `DepthGuardPlugin`.
7. Validate: JSON structured output round-trip, batched classification, multi-step extraction, conditional sub-queries, timeout handling.
8. **Milestone**: REPL code can call sub-LMs via AST-transformed `await llm_query_async()`; responses flow back as Python strings; events yield in real time; timeouts work; depth enforced.

**Phase 3: Observability (1 week)**
1. Implement `ObservabilityPlugin` with all callback hooks.
2. Verify real-time event yield from worker dispatches.
3. Migrate `RLMLogger` / `VerbosePrinter`.
4. **Milestone**: Full telemetry parity.

**Phase 4: Caching and policy (1 week)**
1. Implement `CachePlugin`, `AuthPolicyPlugin`, `TypeValidationPlugin`.
2. **Milestone**: Cross-cutting concerns are plugin-driven.

**Phase 5: Persistence and multi-turn (1 week)**
1. Session-state-backed versioned contexts and histories.
2. `DatabaseSessionService` for production.
3. **Milestone**: Multi-turn sessions match `persistent=True` behavior.

**Phase 6: Isolated environments (2 weeks)**
1. Port `ModalREPL` and others, retaining HTTP broker pattern.
2. Host-side delegates to worker pool instead of `LMHandler`.
3. **Milestone**: All environment types supported.

### K.2 Parity test plan

| Test category | What to compare | How |
|--------------|----------------|-----|
| **Functional** | Final answers | 50+ prompts; semantic equivalence |
| **Behavioral** | Iteration counts, sub-call counts | Iteration-level trace comparison |
| **AST fidelity** | Transformed code semantic equivalence | 100+ code patterns; verify AST output matches expected async form |
| **Sub-LM returns** | Structured output handling | 20+ prompts with programmatic `llm_query` return handling |
| **Timeout resilience** | Hung API recovery | Inject artificial delays; verify timeout returns error string; verify event loop stays responsive |
| **State** | Multi-turn session state | 5-turn conversations compared |
| **Performance** | Wall-clock time, tokens | Within 10% tolerance |
| **Event yield** | Real-time event delivery | Verify worker events appear in Runner stream during (not after) code execution |

### K.3 Rollback strategy

1. **Feature flag**: `app:use_adk_rebuild` state key.
2. **Parallel running**: Both systems side-by-side during phases 1-4.
3. **Incremental promotion**: Local first, then isolated.
4. **Rollback trigger**: >5% functional parity failure.

### K.4 Definition of done checklist

- [ ] `RLMPooledOrchestratorAgent` handles iteration loop with state-driven termination
- [ ] `RLMReasoningAgent` produces equivalent responses to current `LMHandler.completion()`
- [ ] `ReplAstTransformer` correctly transforms all supported code patterns
- [ ] `ReplAstTransformer` rejects unsupported patterns (lambda, class body) with clear errors
- [ ] Pre-allocated worker pool dispatches sub-LM calls via `asyncio.Queue`
- [ ] `llm_query_async()` returns strings for programmatic use in REPL code
- [ ] `llm_query_batched_async()` parallelizes via `asyncio.gather()` and returns ordered `list[str]`
- [ ] `asyncio.wait_for()` timeouts handle hung API calls gracefully
- [ ] Worker events yield to Runner in real time via event queue mechanism
- [ ] No thread pool, no `run_in_executor`, no `run_coroutine_threadsafe` in the critical path
- [ ] `DepthGuardPlugin` enforces `max_depth` on worker model calls
- [ ] `ObservabilityPlugin` captures all metrics from current `RLMLogger` + `VerbosePrinter`
- [ ] `CachePlugin` short-circuits redundant model calls (reasoning + workers)
- [ ] `AuthPolicyPlugin` validates API keys and model permissions
- [ ] `TypeValidationPlugin` validates model I/O at boundaries
- [ ] Multi-turn sessions persist context and history across invocations
- [ ] All 6 environment types supported
- [ ] Functional parity tests pass on 95%+ of evaluation prompts
- [ ] AST fidelity tests pass on 100% of code patterns
- [ ] Sub-LM structured output parity tests pass on 100% of test cases
- [ ] Timeout resilience tests pass — event loop responsive during hung calls
- [ ] Performance within 10% of baseline
- [ ] No `session.state` mutations outside `_run_async_impl` / callback contexts
- [ ] All cross-cutting concerns implemented as plugins
- [ ] Dead code from old `LMHandler` TCP server removed (non-isolated envs)
- [ ] Documentation updated (README, AGENTS.md)

---

## Next Actions

1. **Scaffold the ADK project**: Initialize `rlm_adk/` package; add `google-adk>=1.7.0` to optional dependencies; set up `InMemoryRunner` with a minimal `BaseAgent`.
2. **Implement `ReplAstTransformer`**: Build the `ast.NodeTransformer` with two-pass analysis (identify async-needing functions → transform calls + definitions); write exhaustive unit tests covering all edge cases from Section F.2.
3. **Implement `RLMPooledOrchestratorAgent`**: Custom `BaseAgent` with `_run_async_impl` iteration loop, inline deterministic stages, pre-allocated worker `LlmAgent` pool via `asyncio.Queue`.
4. **Implement async REPL execution**: Build `_repl_exec_with_events` that runs the AST-transformed code and yields worker events in real time; inject `llm_query_async` / `llm_query_batched_async` closures into REPL namespace.
5. **Implement timeout and cancellation**: Wrap all worker dispatches in `asyncio.wait_for()`; verify cancellation propagates to HTTP client; verify error strings return to REPL code.
6. **Validate structured output round-trip**: Integration tests with JSON parsing, batched classification, multi-step extraction, conditional sub-queries.
7. **Implement plugins**: `DepthGuardPlugin`, `ObservabilityPlugin`, `CachePlugin`, `AuthPolicyPlugin`, `TypeValidationPlugin`.
8. **Build parity evaluation suite**: 50+ reference prompts; 100+ AST transformation patterns; 20+ structured output patterns; timeout resilience tests.
9. **Port multi-turn persistence**: Session-state-backed versioned contexts/histories; validate with `DatabaseSessionService`.
10. **Port isolated environments**: Adapt broker pattern to dispatch to worker pool on host side.
