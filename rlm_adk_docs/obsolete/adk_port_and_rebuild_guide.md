# Port & Rebuild Guide: `rlm` on Google Agent Development Kit (ADK)

> **Status**: Canonical rebuild specification
> **Source codebase**: [alexzhang13/rlm](https://github.com/alexzhang13/rlm)
> **Target framework**: Google ADK for Python (v1.7.0+)
> **Scope**: Local execution path only (isolated environments deferred to Phase 6)

---

## A. Executive Intent

### What behavior is preserved from `rlm`

1. **The `rlm.completion(prompt)` contract** — a drop-in replacement for `llm.completion(prompt)` that offloads context into a REPL environment and lets the LM recursively call itself through code execution.
2. **Iterative REPL loop** — up to `max_iterations` turns of: prompt the LM, extract ```` ```repl``` ```` code blocks, execute them in a persistent Python namespace, feed results back.
3. **Sub-LM calls from executed code** — `llm_query(prompt, model=None)` and `llm_query_batched(prompts, model=None)` available as namespace-injected closures inside `exec()`, returning string results consumed programmatically by the running code.
4. **Depth-based and model-name routing** — depth=0 uses the main backend; depth=1 uses `other_backend_client`; explicit `model=` overrides both.
5. **Context loading** — arbitrary payloads (string, dict, list) loaded as `context` / `context_N` variables in the execution namespace.
6. **Final answer extraction** — `FINAL(...)` and `FINAL_VAR(...)` patterns parsed from LM output.
7. **Usage tracking** — per-model token counts aggregated across all sub-calls.
8. **Persistence mode** — optional environment reuse across `completion()` calls for multi-turn conversations with versioned contexts and histories.

### What changes because ADK becomes the execution substrate

1. **The TCP socket `LMHandler` is replaced** by ADK's `Runner`/`App` orchestration and `LlmAgent` worker dispatch. No custom socket server for local execution.
2. **The imperative iteration loop in `RLM.completion()`** becomes a custom `BaseAgent._run_async_impl()` that yields `Event` objects, with flow control expressed through ADK callbacks, plugins, and state rather than ad-hoc Python branching.
3. **Cross-cutting concerns** (depth guards, caching, logging, usage tracking) move from scattered code into a structured plugin and callback hierarchy with explicit trigger points.
4. **State management** shifts from Python instance variables to ADK `session.state` with prefix-scoped keys, delta-tracked mutations, and `SessionService`-backed persistence.
5. **Sub-LM dispatch** uses `ParallelAgent` composition with pre-allocated `LlmAgent` worker pools, fully async via AST rewriting of LM-generated code.

### What "done" means (parity criteria)

| Criterion | Metric |
|-----------|--------|
| **Functional parity** | Given identical prompts, contexts, and model backends, the ADK build produces equivalent final answers (semantic, not byte-identical) |
| **Sub-call routing** | `llm_query(prompt, model="X")` reaches the correct backend; depth-based default routing preserved |
| **Iteration behavior** | Same iteration count, same code extraction, same REPL execution semantics |
| **Usage tracking** | Token counts match within rounding tolerance |
| **Persistence** | Multi-turn sessions with versioned contexts and histories work identically |
| **Error behavior** | Same failure modes: `ValueError` on missing API keys, execution errors surfaced in `stderr`, max-iteration fallback to `_default_answer` |

---

## B. Current System Map (from `rlm`)

### B.1 Lifecycle: prompt to final response

```
User
  │
  ▼
rlm.completion(prompt, root_prompt=None)
  │
  ├─ 1. _setup_prompt(prompt)
  │     Build message_history: system prompt + metadata + context info + user prompt
  │
  ├─ 2. _spawn_completion_context(prompt)
  │     ├─ Create BaseLM client via get_client(backend, kwargs)
  │     ├─ Optionally create other_backend_client for depth=1
  │     ├─ Wrap in LMHandler (ThreadingTCPServer on auto-assigned port)
  │     ├─ Register additional clients by model name
  │     ├─ Create/reuse environment (LocalREPL default)
  │     │    ├─ setup(): sandboxed globals, safe builtins, helper functions
  │     │    ├─ load_context(payload): inject context/context_0 into namespace
  │     │    └─ Inject llm_query(), llm_query_batched(), FINAL_VAR(), show_vars()
  │     └─ yield (lm_handler, environment)
  │
  ├─ 3. Iteration loop (up to max_iterations)
  │     ├─ a. lm_handler.completion(current_prompt) → response text
  │     ├─ b. find_code_blocks(response) → list of ```repl``` blocks
  │     ├─ c. For each code block:
  │     │      environment.execute_code(code) → REPLResult(stdout, stderr, locals, llm_calls)
  │     ├─ d. find_final_answer(response, environment) → check FINAL/FINAL_VAR
  │     │      If found → return final_answer
  │     ├─ e. format_iteration(iteration) → append to message_history
  │     └─ f. Build current_prompt = message_history + user prompt suffix
  │
  ├─ 4. If no final answer after max_iterations:
  │     _default_answer(message_history, lm_handler)
  │       → One final LM call with full history + "provide final answer" prompt
  │
  └─ 5. Return final_answer string + usage summary
```

### B.2 Environment types and comms models

| Type | Base Class | Comms Model | Current Implementations |
|------|-----------|-------------|------------------------|
| **Non-isolated** | `NonIsolatedEnv` | Direct TCP socket to `LMHandler` on localhost. Length-prefixed JSON protocol (4-byte big-endian + UTF-8 JSON). `llm_query()` opens a new TCP connection per call via `send_lm_request()`. | `LocalREPL` |
| **Isolated** | `IsolatedEnv` | HTTP broker pattern. Flask server inside cloud sandbox exposes `/enqueue`, `/pending`, `/respond`. Host-side poller thread forwards requests to `LMHandler` via socket, posts responses back via tunnel URL. 100ms polling interval. State persisted via `dill` serialization. | `ModalREPL`, `PrimeREPL`, `DockerREPL`, `DaytonaREPL`, `E2BREPL` (all deleted from working tree; deferred) |

**Key protocol details (non-isolated path)**:

- `socket_send(sock, data)`: `struct.pack(">I", len(payload)) + payload`
- `socket_recv(sock)`: read 4-byte length, then read exactly that many bytes
- `socket_request(address, data, timeout=300)`: open → send → recv → close
- `LMRequest` dataclass: `prompt`, `prompts` (batched), `model`, `depth`
- `LMResponse` dataclass: `error`, `chat_completion`, `chat_completions`
- Batched requests use `asyncio.run()` inside the synchronous handler thread

### B.3 Extensibility points

| Extension Point | Mechanism | Registry |
|----------------|-----------|----------|
| **LM Clients** | Inherit `BaseLM`, implement `completion()`, `acompletion()`, `get_usage_summary()`, `get_last_usage()` | `rlm/clients/__init__.py` → `get_client(backend, kwargs)` |
| **Environments** | Inherit `NonIsolatedEnv` or `IsolatedEnv`, implement `setup()`, `load_context()`, `execute_code()`, `cleanup()` | `rlm/environments/__init__.py` → `get_environment(env_type, kwargs)` |
| **Persistence** | Implement `SupportsPersistence` protocol: `update_handler_address()`, `add_context()`, `get_context_count()`, `add_history()`, `get_history_count()` | Runtime `isinstance()` check |
| **Logging** | `RLMLogger` writes JSON-lines; `VerbosePrinter` produces rich console output | Constructor injection on `RLM` |

### B.4 Key types

| Type | Location | Purpose |
|------|----------|---------|
| `RLM` | `core/rlm.py` | Top-level orchestrator. Owns config, spawns per-completion contexts, runs iteration loop |
| `LMHandler` | `core/lm_handler.py` | Multi-threaded TCP server wrapping `BaseLM` clients. Routes by depth and model name |
| `BaseLM` | `clients/base_lm.py` | Abstract LM client interface |
| `OpenAIClient` | `clients/openai.py` | OpenAI/OpenRouter/vLLM implementation |
| `BaseEnv` / `NonIsolatedEnv` / `IsolatedEnv` | `environments/base_env.py` | Environment hierarchy |
| `LocalREPL` | `environments/local_repl.py` | Default non-isolated environment with sandboxed `exec()` |
| `LMRequest` / `LMResponse` | `core/comms_utils.py` | Socket protocol message types |
| `REPLResult` | `core/types.py` | `stdout`, `stderr`, `locals`, `llm_calls` from code execution |
| `RLMIteration` | `core/types.py` | One iteration: response text + list of `CodeBlock`s |
| `CodeBlock` | `core/types.py` | One code block: source code + `REPLResult` |
| `UsageSummary` / `ModelUsageSummary` | `core/types.py` | Per-model token tracking |

---

## C. ADK Rebuild Architecture

### C.1 Component diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  App (google.adk.apps.App)                                              │
│  name="rlm_adk"                                                         │
│  plugins=[                                                               │
│    DebugLoggingPlugin,     # MED-1: development traces                  │
│    DepthGuardPlugin,       # enforce max recursion depth                │
│    CachePlugin,            # global LLM response cache                  │
│    ObservabilityPlugin,    # usage tracking, timings, audit trail       │
│    PolicyPlugin,           # auth/safety guardrails                     │
│  ]                                                                       │
│  events_compaction_config = EventsCompactionConfig(...)                  │
│  context_cache_config     = ContextCacheConfig(...)                      │
│  resumability_config      = ResumabilityConfig(persistent=True)          │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  RLMOrchestratorAgent (custom BaseAgent)                           │  │
│  │  _run_async_impl(ctx):                                             │  │
│  │    1. Build system prompt + metadata                               │  │
│  │    2. Load context into state                                      │  │
│  │    3. Loop up to max_iterations:                                   │  │
│  │       a. Dispatch to ReasoningAgent → get response                 │  │
│  │       b. Extract ```repl``` code blocks                            │  │
│  │       c. AST-rewrite code (llm_query → await llm_query_async)     │  │
│  │       d. Execute _repl_exec() in sandboxed namespace              │  │
│  │       e. Check FINAL/FINAL_VAR → yield final event if found       │  │
│  │       f. Yield state_delta events (iteration results, obs metrics)│  │
│  │    4. If exhausted → dispatch to DefaultAnswerAgent                │  │
│  │                                                                    │  │
│  │  ┌──────────────────────┐  ┌────────────────────────────────────┐ │  │
│  │  │  ReasoningAgent      │  │  DefaultAnswerAgent                │ │  │
│  │  │  (LlmAgent)          │  │  (LlmAgent)                       │ │  │
│  │  │  model=main_backend  │  │  model=main_backend               │ │  │
│  │  │  include_contents=   │  │  instruction="Given history,      │ │  │
│  │  │    'none'            │  │    provide final answer"           │ │  │
│  │  │  output_key=         │  │  output_key=                      │ │  │
│  │  │    "reasoning_output"│  │    "default_answer"               │ │  │
│  │  └──────────────────────┘  └────────────────────────────────────┘ │  │
│  │                                                                    │  │
│  │  ┌──────────────────────────────────────────────────────────────┐ │  │
│  │  │  Worker Pool (LlmAgent instances)                            │ │  │
│  │  │  Pre-allocated: N workers per registered model backend       │ │  │
│  │  │  Managed via asyncio.Queue                                   │ │  │
│  │  │                                                              │ │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │ │  │
│  │  │  │ Worker_0 │ │ Worker_1 │ │ Worker_2 │ │ Worker_N │       │ │  │
│  │  │  │ LlmAgent │ │ LlmAgent │ │ LlmAgent │ │ LlmAgent │       │ │  │
│  │  │  │ model=*  │ │ model=*  │ │ model=*  │ │ model=*  │       │ │  │
│  │  │  │ incl=none│ │ incl=none│ │ incl=none│ │ incl=none│       │ │  │
│  │  │  │ no_xfer  │ │ no_xfer  │ │ no_xfer  │ │ no_xfer  │       │ │  │
│  │  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │ │  │
│  │  │                                                              │ │  │
│  │  │  Dispatch: llm_query_async(prompt, model=None)               │ │  │
│  │  │    → acquire K workers from pool (K=1 single, K=N batched)   │ │  │
│  │  │    → ParallelAgent(sub_agents=acquired_workers)              │ │  │
│  │  │    → yield from ParallelAgent.run_async(ctx)                 │ │  │
│  │  │    → read output_key from each worker                        │ │  │
│  │  │    → return workers to pool                                  │ │  │
│  │  └──────────────────────────────────────────────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  Runner                                                                  │
│    app = App(...)                                                        │
│    session_service = InMemorySessionService | DatabaseSessionService     │
│    run_config = RunConfig(max_llm_calls=..., streaming_mode=NONE)       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### C.2 Runner + SessionService choices

| Choice | Option | Implication |
|--------|--------|-------------|
| **SessionService** | `InMemorySessionService` | Default for development. State lost on restart. Sufficient for single-process, non-persistent `rlm` usage. |
| | `DatabaseSessionService` | Required for `persistent=True` multi-turn conversations. Survives restarts. Maps to `rlm`'s persistent environment pattern. |
| **App-level configs** | `EventsCompactionConfig` | **Required.** 15 iterations x N sub-calls accumulate many events. Configure compaction to prevent unbounded session growth. |
| | `ContextCacheConfig` | **Recommended.** The RLM system prompt is largely static across iterations. Gemini context caching reduces repeated token cost. |
| | `ResumabilityConfig(persistent=True)` | **Recommended for persistent mode.** Long-running REPL sessions that may be interrupted benefit from resumable invocations. |

### C.3 How RLM recursion maps onto ADK agent composition

Current `rlm` has a single level of recursion: the orchestrator (depth=0) dispatches sub-LM calls at depth=1 via `llm_query()` / `llm_query_batched()`. `max_depth` is validated but only depth=1 is supported.

**ADK mapping:**

- The **orchestrator** is a custom `BaseAgent` (`RLMOrchestratorAgent`) whose `_run_async_impl` contains the iteration loop.
- **Sub-LM calls** are handled by pre-allocated `LlmAgent` worker instances, dispatched via `ParallelAgent` (see CRIT-3).
- **Depth** is set once when entering REPL execution context (HIGH-4) and stored in `temp:current_depth`. It does **not** increment per concurrent worker dispatch.
- The **`model=` parameter** (HIGH-5) routes to the correct worker pool: each registered model backend has its own `asyncio.Queue` of `LlmAgent` instances configured with that model. Default routing (no model specified) uses the depth-based backend.

**Invocation scoping for `temp:` keys:**

When the orchestrator dispatches workers via `ParallelAgent`, all agents in the chain share the same `InvocationContext` and therefore the same `temp:` state. This means:

- `temp:current_depth` is visible to all workers (correct — depth is uniform per invocation)
- `temp:iteration_count` is visible to all workers (correct — iteration is a property of the orchestrator)
- Worker-specific intermediate results must use unique keys (e.g., `temp:worker_{id}_result`) to avoid collisions during parallel dispatch

### C.4 RunConfig specification (HIGH-1)

`RunConfig` controls runtime behavior for `runner.run_async()`:

| Parameter | Recommended Value | Rationale |
|-----------|-------------------|-----------|
| `max_llm_calls` | `max_iterations * (1 + expected_sub_calls_per_iteration) * 1.5` | Default is 500. With 15 iterations and multiple sub-LM calls per iteration (potentially batched), the orchestrator can hit this cap. Formula: 15 iterations x (1 reasoning call + avg 3 sub-calls) x 1.5 safety margin = ~90. Adjust based on workload profiling. |
| `streaming_mode` | `StreamingMode.NONE` | RLM uses non-streaming completions. The REPL loop needs the complete response to extract code blocks. Streaming adds complexity with no benefit here. |

---

## D. Callback & Plugin Plan (the "Porting Contract")

### D.1 Plugin suite (global, App-registered)

Plugins apply to **every** agent, tool, and model call in the Runner. They execute **before** any local callbacks. Per CRIT-2, plugins are registered on `App`, not `Runner`.

#### D.1.1 `DepthGuardPlugin`

| Property | Value |
|----------|-------|
| **Name** | `DepthGuardPlugin` |
| **Trigger points** | `before_model_callback`, `on_model_error_callback` |
| **Reads from state** | `temp:current_depth`, `app:max_depth` |
| **Writes to state** | `temp:depth_guard_blocked` (bool, set to `True` when blocking) |
| **Logs/exports** | Warning when depth limit reached; error details from `on_model_error_callback` |
| **Failure behavior** | **Intervene (short-circuit)**: `before_model_callback` returns a synthetic `LlmResponse` with an error message when depth exceeds `app:max_depth`. Does NOT increment depth per concurrent dispatch (HIGH-4). `on_model_error_callback` (HIGH-2): catches rate limits, auth failures, transient HTTP errors. Logs the error, returns a fallback `LlmResponse` describing the failure for the orchestrator to handle. |

#### D.1.2 `CachePlugin`

| Property | Value |
|----------|-------|
| **Name** | `CachePlugin` |
| **Trigger points** | `before_model_callback` (cache check), `after_model_callback` (cache store) |
| **Reads from state** | `cache:store` (dict of fingerprint → response), `cache:hit_count`, `cache:miss_count` |
| **Writes to state** | `cache:store`, `cache:hit_count`, `cache:miss_count`, `cache:last_hit_key` |
| **Logs/exports** | Cache hit/miss events with fingerprint, model name, token savings estimate |
| **Failure behavior** | **Intervene (short-circuit)** on cache hit: returns cached `LlmResponse` from `before_model_callback`, skipping the model call entirely. On cache miss: **Observe** — allows the model call, then stores result in `after_model_callback`. Cache errors (serialization failures) are logged but never block the model call. |

#### D.1.3 `ObservabilityPlugin`

| Property | Value |
|----------|-------|
| **Name** | `ObservabilityPlugin` |
| **Trigger points** | `before_agent_callback`, `after_agent_callback`, `before_model_callback`, `after_model_callback`, `before_tool_callback`, `after_tool_callback`, `on_event_callback`, `after_run_callback` |
| **Reads from state** | `obs:*` keys, `temp:invocation_start_time`, `temp:iteration_count` |
| **Writes to state** | `obs:total_input_tokens`, `obs:total_output_tokens`, `obs:total_calls`, `obs:model_usage:{model_name}`, `obs:iteration_times`, `obs:tool_invocation_summary`, `obs:total_execution_time` |
| **Logs/exports** | Structured log entries at each trigger point: agent name, invocation ID, model name, token counts, timing. Final summary in `after_run_callback`. |
| **Failure behavior** | **Observe only** — never returns a value, never blocks execution. Logging errors are caught and suppressed. |

#### D.1.4 `PolicyPlugin`

| Property | Value |
|----------|-------|
| **Name** | `PolicyPlugin` |
| **Trigger points** | `before_model_callback`, `before_tool_callback`, `on_user_message_callback` |
| **Reads from state** | `app:blocked_patterns`, `user:auth_level`, `temp:current_depth` |
| **Writes to state** | `temp:policy_violation` (string description if blocked) |
| **Logs/exports** | Policy violation events with user ID, content hash, rule triggered |
| **Failure behavior** | **Intervene (short-circuit)**: returns blocking `LlmResponse` or tool result dict when policy violated. Auth failures raise immediately per `rlm`'s "fail fast, fail loud" philosophy. |

#### D.1.5 `DebugLoggingPlugin` (MED-1: development only)

| Property | Value |
|----------|-------|
| **Name** | `DebugLoggingPlugin` (ADK built-in) |
| **Configuration** | `output_path="rlm_adk_debug.yaml"`, `include_session_state=True`, `include_system_instruction=True` |
| **Trigger points** | All available hooks (built-in behavior) |
| **Reads from state** | All keys (for state snapshot recording) |
| **Writes to state** | None |
| **Logs/exports** | Full interaction traces to YAML: prompts, responses, tool calls, state snapshots. Used during parity testing (Phase 4 of migration). |
| **Failure behavior** | **Observe only**. Remove from production `App` configuration. |
| **Error handling** | Must implement `on_model_error_callback` for recording model failures during development. |

### D.2 Local callback suite (per-agent/tool specifics)

Local callbacks apply only to the specific agent or tool instance they are configured on. They execute **after** plugin callbacks.

Per HIGH-6, every `LlmAgent` variant requires a full callback specification.

#### D.2.1 `ReasoningAgent` callbacks

| Callback | Function | Behavior |
|----------|----------|----------|
| `before_model_callback` | `reasoning_before_model` | **Amend**: Injects the current `message_history` from `temp:message_history` into the `LlmRequest`. Sets `temp:reasoning_call_start` timestamp. The `include_contents='none'` setting (HIGH-3) means the agent receives prompts entirely via this callback. |
| `after_model_callback` | `reasoning_after_model` | **Observe**: Records response length, extracts token usage from `LlmResponse`, writes `temp:last_reasoning_response`. Computes call duration from `temp:reasoning_call_start`. |

#### D.2.2 Worker `LlmAgent` callbacks

Per HIGH-3, worker agents are configured with:
- `include_contents='none'`
- `disallow_transfer_to_parent=True`
- `disallow_transfer_to_peers=True`
- `generate_content_config` with appropriate `temperature` (e.g., `0.0` for deterministic)

| Callback | Function | Behavior |
|----------|----------|----------|
| `before_model_callback` | `worker_before_model` | **Amend**: Injects the single prompt from the dispatch closure into `LlmRequest`. Sets the model override if `model=` was specified in the `llm_query()` call (HIGH-5). |
| `after_model_callback` | `worker_after_model` | **Observe**: Extracts the text response, writes to worker's `output_key`. Records token usage for aggregation. |

#### D.2.3 `DefaultAnswerAgent` callbacks

| Callback | Function | Behavior |
|----------|----------|----------|
| `before_model_callback` | `default_before_model` | **Amend**: Injects the full accumulated `message_history` plus the "provide your best final answer" suffix into `LlmRequest`. |
| `after_model_callback` | `default_after_model` | **Observe**: Records the default answer, marks `temp:used_default_answer = True` for observability. |

---

## E. State Schema: Key Naming + Ownership + Lifecycle

### E.1 Prefix scoping rules

ADK recognizes exactly four prefix scopes:

| Prefix | Scope | Persistence | Behavior |
|--------|-------|-------------|----------|
| *(none)* | Session | Persists within session via `SessionService` | Default scope. Survives across invocations within same session. |
| `user:` | User | Persists across sessions for same `user_id` | User preferences, auth state. |
| `app:` | Application | Persists across all users and sessions | Global configuration. |
| `temp:` | Invocation | Discarded after invocation completes | Intermediate calculations, per-invocation flags. Shared across parent and sub-agents within same invocation. |

> **LOW-1 Warning**: `cache:`, `obs:`, and other custom prefixes used in this schema are **naming conventions only**, not ADK-recognized scopes. Keys like `cache:hit_count` are **session-scoped** (equivalent to unprefixed) and will persist across invocations within the same session. This is an intentional design choice for cache counters — they accumulate across invocations for observability. If per-invocation reset is needed, use `temp:` prefix instead.

### E.2 State key catalog

#### Flow Control Keys

| Key | Prefix | Scope | Owner | Valid When | Serialization | Example Value |
|-----|--------|-------|-------|-----------|---------------|---------------|
| `app:max_depth` | `app:` | App | App initialization | Always | `int` | `1` |
| `app:max_iterations` | `app:` | App | App initialization | Always | `int` | `15` |
| `temp:current_depth` | `temp:` | Invocation | `RLMOrchestratorAgent` | During REPL execution | `int` | `1` |
| `temp:iteration_count` | `temp:` | Invocation | `RLMOrchestratorAgent` | During iteration loop | `int` | `7` |
| `temp:should_stop` | `temp:` | Invocation | `RLMOrchestratorAgent` | After FINAL detected | `bool` | `True` |
| `temp:used_default_answer` | `temp:` | Invocation | `DefaultAnswerAgent` callback | After max iterations | `bool` | `True` |
| `temp:depth_guard_blocked` | `temp:` | Invocation | `DepthGuardPlugin` | When depth exceeded | `bool` | `True` |
| `temp:policy_violation` | `temp:` | Invocation | `PolicyPlugin` | When policy violated | `str` | `"blocked: forbidden pattern"` |

#### REPL Execution Keys

| Key | Prefix | Scope | Owner | Valid When | Serialization | Example Value |
|-----|--------|-------|-------|-----------|---------------|---------------|
| `temp:message_history` | `temp:` | Invocation | `RLMOrchestratorAgent` | During iteration loop | `list[dict]` (JSON-serializable) | `[{"role":"system","content":"..."},...]` |
| `temp:current_code_blocks` | `temp:` | Invocation | `RLMOrchestratorAgent` | During code extraction | `list[str]` | `["import json\n..."]` |
| `temp:last_repl_result` | `temp:` | Invocation | `RLMOrchestratorAgent` | After code execution | `dict` with `stdout`, `stderr`, `locals_summary` | `{"stdout":"42\n","stderr":"","locals_summary":{"x":"int"}}` |
| `temp:final_answer` | `temp:` | Invocation | `RLMOrchestratorAgent` | When FINAL detected | `str` | `"The answer is 42."` |
| `temp:last_reasoning_response` | `temp:` | Invocation | `ReasoningAgent` callback | After each reasoning call | `str` | Full LM response text |

#### Context and Persistence Keys

| Key | Prefix | Scope | Owner | Valid When | Serialization | Example Value |
|-----|--------|-------|-------|-----------|---------------|---------------|
| `context_count` | *(none)* | Session | `RLMOrchestratorAgent` | After context load | `int` | `3` |
| `history_count` | *(none)* | Session | `RLMOrchestratorAgent` | After history store | `int` | `2` |
| `context_payload_{N}` | *(none)* | Session | `RLMOrchestratorAgent` | After context load | `str` or `dict` or `list` | `"The quick brown fox..."` |
| `message_history_{N}` | *(none)* | Session | `RLMOrchestratorAgent` | After completion | `list[dict]` | `[{"role":"user","content":"..."}]` |

#### Caching Keys

| Key | Prefix | Scope | Owner | Valid When | Serialization | Example Value |
|-----|--------|-------|-------|-----------|---------------|---------------|
| `cache:store` | *(session)* | Session | `CachePlugin` | After first model call | `dict[str, str]` (fingerprint → serialized response) | `{"a1b2c3": "{\"text\":\"...\"}"}` |
| `cache:hit_count` | *(session)* | Session | `CachePlugin` | Accumulates across invocations | `int` | `12` |
| `cache:miss_count` | *(session)* | Session | `CachePlugin` | Accumulates across invocations | `int` | `45` |
| `cache:last_hit_key` | *(session)* | Session | `CachePlugin` | After cache hit | `str` | `"a1b2c3"` |

> **Note (LOW-1)**: `cache:*` keys are session-scoped despite the `:` separator. They are **not** `temp:` — they intentionally persist across invocations to provide cumulative cache statistics. To reset per invocation, use `temp:cache_hit_count` instead.

#### Observability Keys

| Key | Prefix | Scope | Owner | Valid When | Serialization | Example Value |
|-----|--------|-------|-------|-----------|---------------|---------------|
| `obs:total_input_tokens` | *(session)* | Session | `ObservabilityPlugin` | Accumulates | `int` | `15230` |
| `obs:total_output_tokens` | *(session)* | Session | `ObservabilityPlugin` | Accumulates | `int` | `4821` |
| `obs:total_calls` | *(session)* | Session | `ObservabilityPlugin` | Accumulates | `int` | `23` |
| `obs:model_usage:{model}` | *(session)* | Session | `ObservabilityPlugin` | Accumulates | `dict` with `calls`, `input_tokens`, `output_tokens` | `{"calls":5,"input_tokens":3000,"output_tokens":800}` |
| `obs:iteration_times` | *(session)* | Session | `ObservabilityPlugin` | After each iteration | `list[float]` (seconds) | `[2.3, 1.8, 3.1]` |
| `obs:tool_invocation_summary` | *(session)* | Session | `ObservabilityPlugin` | After tool calls | `dict[str, int]` (tool_name → call_count) | `{"llm_query":12,"llm_query_batched":3}` |
| `obs:total_execution_time` | *(session)* | Session | `ObservabilityPlugin` | After run completes | `float` (seconds) | `45.7` |
| `temp:invocation_start_time` | `temp:` | Invocation | `ObservabilityPlugin` | During invocation | `float` (epoch) | `1708000000.123` |
| `temp:reasoning_call_start` | `temp:` | Invocation | `ReasoningAgent` callback | During reasoning call | `float` (epoch) | `1708000001.456` |

#### Type Validation Keys

| Key | Prefix | Scope | Owner | Valid When | Serialization | Example Value |
|-----|--------|-------|-------|-----------|---------------|---------------|
| `temp:validation_pass` | `temp:` | Invocation | Validation callbacks | After validation | `bool` | `True` |
| `temp:validation_errors` | `temp:` | Invocation | Validation callbacks | After validation failure | `list[str]` | `["Missing 'prompt' field","Invalid model name"]` |
| `obs:validation_fail_count` | *(session)* | Session | `ObservabilityPlugin` | Accumulates | `int` | `2` |

#### API/Messaging Integration Keys

| Key | Prefix | Scope | Owner | Valid When | Serialization | Example Value |
|-----|--------|-------|-------|-----------|---------------|---------------|
| `temp:request_id` | `temp:` | Invocation | `PolicyPlugin` / `on_user_message_callback` | During invocation | `str` (UUID) | `"req-a1b2c3d4"` |
| `temp:idempotency_key` | `temp:` | Invocation | `PolicyPlugin` | During invocation | `str` | `"idem-x7y8z9"` |
| `user:last_successful_call_id` | `user:` | User | `ObservabilityPlugin` | After successful completion | `str` | `"req-a1b2c3d4"` |

---

## F. Porting the RLM "REPL + LMHandler" Concept into ADK

### F.1 `llm_query()` and `llm_query_batched()` as namespace-injected closures

These functions are **NOT** ADK `FunctionTool`s. They are closures injected into the `exec()` namespace that LM-generated code calls directly. Their string return values are consumed programmatically (JSON parsing, list indexing, conditional logic).

**Why not `FunctionTool`**: ADK tools are designed for LLM-invoked function calling, where the LLM decides to call the tool based on its description. In `rlm`, `llm_query()` is called by *code* that the LLM wrote, running inside `exec()`. The code expects a synchronous-looking function that returns a string. The call is deterministic (code execution), not LLM-decided.

**Implementation**: The closures are created inside `RLMOrchestratorAgent._run_async_impl()` and capture the orchestrator's context:

```
# Pseudocode — architecture spec, not implementation
async def llm_query_async(prompt: str, model: str | None = None) -> str:
    """Acquire 1 worker, dispatch via ParallelAgent, return string result."""
    worker = await worker_pool.get(model)       # route by model name (HIGH-5)
    # Inject prompt via before_model_callback
    worker._pending_prompt = prompt
    parallel = ParallelAgent(name="dispatch_1", sub_agents=[worker])
    async for event in parallel.run_async(ctx):
        event_queue.put_nowait(event)            # drain to orchestrator
    result = ctx.session.state.get(worker.output_key, "")
    worker_pool.put(worker)                      # return to pool
    return result

async def llm_query_batched_async(prompts: list[str], model: str | None = None) -> list[str]:
    """Acquire K workers, dispatch via single ParallelAgent, return K string results."""
    workers = [await worker_pool.get(model) for _ in prompts]
    for w, p in zip(workers, prompts):
        w._pending_prompt = p
    parallel = ParallelAgent(name=f"batch_{len(prompts)}", sub_agents=workers)
    async for event in parallel.run_async(ctx):
        event_queue.put_nowait(event)
    results = [ctx.session.state.get(w.output_key, "") for w in workers]
    for w in workers:
        worker_pool.put(w)
    return results
```

`llm_query_async` is the degenerate K=1 case of `llm_query_batched_async`. There is **one dispatch implementation**.

### F.2 AST rewriting for sync/async bridge (CRIT-3)

The REPL presents a sync/async boundary: `exec()` is synchronous, but ADK agents are async. The strategy is **AST rewriting**:

1. An `ast.NodeTransformer` transforms LM-generated code:
   - `llm_query(p)` → `await llm_query_async(p)`
   - `llm_query_batched(ps)` → `await llm_query_batched_async(ps)`
   - Wraps the entire code block in `async def _repl_exec(): ...`

2. The orchestrator's `_run_async_impl` then `await`s this function natively — **no thread pool, no `run_in_executor`, no `run_coroutine_threadsafe`**.

3. **Event yield during REPL execution**: The REPL coroutine runs as an `asyncio.Task`. `ParallelAgent` events from each dispatch are collected into an `asyncio.Queue` by the dispatch closure. A drain loop in `_run_async_impl` yields them to the Runner. A sentinel value signals task completion. The drain loop and the REPL task interleave cooperatively at `await` points within the same event loop.

4. **Timeout shape** (CRIT-3.3): Timeouts wrap a **consumption coroutine** — an `async def` that iterates the worker's async generator and collects events — not the async generator object itself:
   ```
   asyncio.wait_for(consume_coroutine(), timeout=N)
   ```
   An async generator is not an awaitable and cannot be passed to `asyncio.wait_for` directly.

5. **stdout/stderr capture** (CRIT-3.4): `sys.stdout` / `sys.stderr` redirect to `StringIO` covers the full `_repl_exec()` task lifetime. When `_repl_exec()` yields control during `await llm_query_async(...)`, the event loop may run other coroutines. The capture mechanism must be **task-local** (using `contextvars.ContextVar`) to avoid capturing output from other concurrent tasks. Synchronous segments between `await` points are captured normally.

### F.3 LMHandler depth-based and model-name routing → ADK `LlmAgent` configuration (HIGH-5)

Current `rlm` routing in `LMHandler.get_client(model, depth)`:
- `depth=0`: use `default_client` (main backend)
- `depth=1`: use `other_backend_client` if registered, else `default_client`
- If `model` is specified and registered: use that client (overrides depth)

**ADK mapping:**

| Scenario | ADK Mechanism |
|----------|---------------|
| Depth-based default routing | `RLMOrchestratorAgent` uses `ReasoningAgent` (main model) at depth=0. Worker pool defaults to `other_backend_client`'s model at depth=1. |
| Explicit `model=` override | Per-model worker pools: `worker_pools: dict[str, asyncio.Queue[LlmAgent]]`. When `model="gpt-4"` is specified, dispatch acquires from `worker_pools["gpt-4"]`. |
| Model registration | At `App` initialization, create a pool of `LlmAgent` workers for each registered model. Workers have `generate_content_config` matching the model's parameters. |

### F.4 TCP/broker patterns: what ADK replaces vs. what remains

| Component | ADK Replaces? | Rationale |
|-----------|--------------|-----------|
| `LMHandler` (TCP server) | **Yes, for local execution** | ADK `Runner` + `LlmAgent` workers handle all LM dispatch natively. No need for a separate TCP server. |
| `LMRequestHandler` | **Yes** | Request routing is handled by `before_model_callback` on workers and the worker pool dispatch mechanism. |
| `socket_send` / `socket_recv` / `socket_request` | **Yes, for local** | Direct async dispatch replaces socket IPC for local path. |
| `LMRequest` / `LMResponse` | **Partially** | These types can be retained as internal types for the dispatch closure's interface, or replaced by ADK's `LlmRequest` / `LlmResponse`. |
| HTTP broker pattern (isolated) | **Retained (deferred)** | Isolated environments still need the broker pattern. When Phase 6 begins, evaluate ADK's Daytona integration as a potential replacement. The broker's `/enqueue` → `/pending` → `/respond` flow is orthogonal to ADK's local agent dispatch. |

### F.5 State mutations inside `_run_async_impl` (CRIT-1)

Inside `RLMOrchestratorAgent._run_async_impl`, writing to `ctx.session.state` directly **bypasses delta tracking**. The only correct way to record a state change is to yield an `Event` with `EventActions(state_delta={...})`:

```
yield Event(
    invocation_id=ctx.invocation_id,
    author=self.name,
    actions=EventActions(state_delta={"temp:iteration_count": i + 1}),
)
```

**Every** state write inside `_run_async_impl` must use this pattern:
- Iteration counters (`temp:iteration_count`)
- Pending code blocks (`temp:current_code_blocks`)
- REPL results (`temp:last_repl_result`)
- Final answers (`temp:final_answer`)
- Message history updates (`temp:message_history`)
- All `obs:*` metrics written from the orchestrator loop

Direct `ctx.session.state[key] = value` mutations are an **anti-pattern** that will silently break persistence with any `SessionService` other than in-memory.

State writes inside **callbacks** (`before_agent_callback`, `after_model_callback`, etc.) correctly use `callback_context.state` and are unaffected by this constraint.

---

## G. Caching Strategy (Callback-First)

### G.1 Global cache plugin design

The `CachePlugin` uses the **intervene** pattern to short-circuit model calls:

**Cache check (`before_model_callback`)**:
1. Generate a cache key by fingerprinting the `LlmRequest`: hash of `(model_name, sorted_contents_text, system_instruction_hash)`
2. Look up `callback_context.state.get("cache:store", {})` for the fingerprint
3. If found: increment `cache:hit_count`, set `cache:last_hit_key`, return the cached `LlmResponse` — this **short-circuits** the model call and all downstream local callbacks
4. If not found: increment `cache:miss_count`, return `None` to proceed

**Cache store (`after_model_callback`)**:
1. Serialize the `LlmResponse` to a JSON-safe dict
2. Store under the fingerprint key in `cache:store`
3. Apply size limits (LRU eviction if store exceeds configured max entries)

### G.2 Local caches for tool outputs

Not applicable for the initial local execution path — `llm_query()` calls are dispatched through workers and covered by the global `CachePlugin`. If tool-specific caching is needed later (e.g., for isolated environments with expensive setup), implement via `before_tool_callback` / `after_tool_callback` on the specific tool instance.

### G.3 Cache key design

| Component | Source | Normalization |
|-----------|--------|---------------|
| Model name | `llm_request.model` or agent's configured model | Lowercase, strip whitespace |
| Prompt content | All `Content` parts concatenated | Strip trailing whitespace, normalize newlines |
| System instruction | `llm_request.config.system_instruction` | SHA-256 hash (long, mostly static) |
| Temperature | `generate_content_config.temperature` | Include as float — different temperatures should not share cache |

**Key format**: `SHA-256(model + "||" + prompt_normalized + "||" + system_instruction_hash + "||" + temperature)`

**Invalidation**: Time-based TTL per entry (configurable, default 300s). Entries evicted on next access after TTL expiry. No proactive expiration — amortized over cache checks.

**Storage backends**:
- **Default**: In-state dict (`cache:store`). Simple, persists with session. Limited by session size.
- **Scaled**: External Redis/Memcached with cache keys stored in state as references. Requires custom `CachePlugin` subclass.

### G.4 Telemetry keys for cache observability

| Key | Type | Updated By | Purpose |
|-----|------|-----------|---------|
| `cache:hit_count` | `int` | `CachePlugin.before_model_callback` | Total cache hits this session |
| `cache:miss_count` | `int` | `CachePlugin.before_model_callback` | Total cache misses this session |
| `cache:last_hit_key` | `str` | `CachePlugin.before_model_callback` | Fingerprint of last cache hit |
| `cache:store` | `dict` | `CachePlugin.after_model_callback` | The cache itself (fingerprint → response) |

---

## H. Observability & Audit Trail

### H.1 Event model: state changes → `state_delta` → persistence

ADK's state tracking follows this flow:

1. **In callbacks**: Modifications to `callback_context.state` or `tool_context.state` are automatically tracked. The `State.__setitem__` delta mechanism records changes into `Event.actions.state_delta`.

2. **In `_run_async_impl`** (CRIT-1): State changes must be explicitly yielded as `Event` objects with `EventActions(state_delta={...})`. Direct `ctx.session.state` mutation bypasses tracking.

3. **Persistence**: The `SessionService` processes each `Event` via `append_event()`. The `state_delta` from each event is applied to the session's state. Persistent services (`DatabaseSessionService`, `VertexAiSessionService`) durably store these deltas.

4. **Compaction**: With `EventsCompactionConfig` on the `App`, old events are compacted to prevent unbounded growth. This is critical for RLM sessions with 15+ iterations and multiple sub-calls each.

### H.2 Plugin-level vs. local-level logging

| Level | What gets logged | By whom | Format |
|-------|-----------------|---------|--------|
| **Plugin (global)** | Every model call (pre/post), every agent entry/exit, every tool invocation, errors, cache hits/misses, policy violations, request IDs | `ObservabilityPlugin`, `DebugLoggingPlugin`, `PolicyPlugin` | Structured JSON logs with: `{invocation_id, timestamp, agent_name, event_type, model_name, tokens, duration}` |
| **Local (per-agent)** | Agent-specific details: reasoning response characteristics, worker prompt injection, default answer usage | `ReasoningAgent` callbacks, Worker callbacks, `DefaultAnswerAgent` callbacks | State delta entries + callback-internal logging |

### H.3 End-to-end invocation tracing

To trace a single user invocation:

1. **Entry**: `PolicyPlugin.on_user_message_callback` generates `temp:request_id` (UUID) and stores it in state
2. **Propagation**: All subsequent log entries include `temp:request_id` from state. Because `temp:` keys are shared across the invocation (including sub-agents), the ID propagates automatically.
3. **Correlation**: `ObservabilityPlugin.on_event_callback` enriches each yielded event with the request ID as metadata
4. **Exit**: `ObservabilityPlugin.after_run_callback` writes the final summary keyed by `temp:request_id`, stores `user:last_successful_call_id` for cross-session reference
5. **External**: The `temp:request_id` can be returned to the caller for correlation with external systems

---

## I. Type Validation & Safety

### I.1 What must be validated at boundaries

| Boundary | What to validate | Mechanism |
|----------|-----------------|-----------|
| **Runner input** (user message) | Content is well-formed `types.Content`, text parts are non-empty strings | `PolicyPlugin.on_user_message_callback` |
| **Model I/O envelopes** | `LlmRequest` has valid `contents` and `config`; `LlmResponse` has non-null `content` with parseable `parts` | `before_model_callback` / `after_model_callback` in `ObservabilityPlugin` |
| **Worker prompt injection** | Prompt string is non-empty, model name (if specified) exists in registered pools | `worker_before_model` local callback |
| **REPL code extraction** | Code blocks matched by regex are syntactically valid Python (parse with `ast.parse` before execution) | `RLMOrchestratorAgent._run_async_impl` |
| **REPL execution results** | `stdout`/`stderr` are strings, `locals` dict contains only serializable values | `RLMOrchestratorAgent` post-execution |
| **State writes** | All values written to state are JSON-serializable (no functions, no connections, no custom class instances) | Each state-writing component validates before `state_delta` construction |

### I.2 How validation failures are recorded and escalated

1. **Record in state**: Set `temp:validation_errors` (list of error strings) and `temp:validation_pass = False`
2. **Increment counter**: `obs:validation_fail_count += 1`
3. **Log structured error**: Include validation context (boundary name, expected type, actual value summary)
4. **Escalation rules** (following `rlm`'s "fail fast, fail loud" philosophy):

| Failure | Escalation |
|---------|-----------|
| Missing API key | Immediate `ValueError` — no fallback |
| Invalid model name | Immediate `ValueError` — no silent default |
| Malformed user input | Return error `Content` via `on_user_message_callback` — no silent drop |
| Unparseable code block | Skip block, record error in `stderr` equivalent, continue iteration |
| Non-serializable state value | Coerce to string representation, log warning, continue |
| Model API error | `on_model_error_callback` logs and either retries or returns fallback `LlmResponse` |

### I.3 Fail fast, fail loud guidance

Per the `rlm` codebase culture:
- **No defensive programming or silent fallbacks** — if something is wrong, surface it immediately
- **Minimize branching** — prefer single code paths; every `if`/`try` needs justification
- **Configuration errors are fatal** — missing keys, invalid types, unregistered models all raise immediately at initialization, not at first use
- **Runtime errors are surfaced** — execution failures in REPL code appear in `stderr` and are fed back to the LM for self-correction, not swallowed

---

## J. API/Messaging Integration

### J.1 Where inbound/outbound messaging occurs

| Point | Direction | What happens |
|-------|-----------|-------------|
| `Runner.run_async(new_message=...)` | Inbound | User's prompt enters the system. `on_user_message_callback` fires first (plugin), then `before_run_callback`. |
| `ReasoningAgent` model call | Outbound | Prompt sent to main LM backend. `before_model_callback` fires (plugin then local). |
| Worker `LlmAgent` model calls | Outbound | Sub-LM prompts sent to worker backends. Same callback chain. |
| `DefaultAnswerAgent` model call | Outbound | Fallback prompt sent to main backend. Same callback chain. |
| `Event` yield from `_run_async_impl` | Outbound | Iteration results, state deltas, final answer yielded to Runner. `on_event_callback` fires. |
| `after_run_callback` | Teardown | Final cleanup, metric export, connection closing. |

### J.2 Idempotency keys and request IDs in state

| Key | Set by | When | Purpose |
|-----|--------|------|---------|
| `temp:request_id` | `PolicyPlugin.on_user_message_callback` | Invocation start | Unique identifier for this invocation. UUID v4. Used for tracing and deduplication. |
| `temp:idempotency_key` | `PolicyPlugin.on_user_message_callback` | Invocation start | Derived from `hash(user_id + session_id + message_content)`. Used to detect duplicate submissions. If a matching key exists in recent history, return cached result. |
| `user:last_successful_call_id` | `ObservabilityPlugin.after_run_callback` | After successful completion | Cross-session reference for the most recent successful invocation. |

### J.3 How plugins enforce auth/policy before tool execution

1. `PolicyPlugin.before_tool_callback` checks `user:auth_level` against tool requirements
2. If insufficient: returns `{"error": "Unauthorized", "required_level": "admin"}` — short-circuits tool execution
3. `PolicyPlugin.before_model_callback` checks `app:blocked_patterns` against prompt content
4. If pattern matched: returns synthetic `LlmResponse` with policy violation message — short-circuits model call
5. All enforcement is logged with `temp:request_id` for audit trail

---

## K. Migration Plan

### K.1 Incremental port strategy (6 phases)

**Phase 1: Foundation (Week 1-2)**
- Set up ADK project structure
- Implement `RLMOrchestratorAgent` as a custom `BaseAgent` with `_run_async_impl`
- Implement basic iteration loop without sub-LM calls
- State: `temp:iteration_count`, `temp:message_history`, `temp:final_answer`
- Wire up `ReasoningAgent` (`LlmAgent`) with `before_model_callback` for prompt injection
- Register `DebugLoggingPlugin` for development traces (MED-1)

**Phase 2: Worker dispatch (Week 2-3)**
- Implement worker pool (`asyncio.Queue` of `LlmAgent` instances)
- Implement AST rewriting transformer (CRIT-3)
- Implement `llm_query_async` / `llm_query_batched_async` closures
- Implement `ParallelAgent`-based dispatch
- Implement event drain loop with sentinel
- Implement stdout/stderr capture with `contextvars.ContextVar`
- Wire up `DefaultAnswerAgent` for max-iteration fallback

**Phase 3: Plugins & callbacks (Week 3-4)**
- Implement `DepthGuardPlugin` with `on_model_error_callback` (HIGH-2)
- Implement `CachePlugin` with fingerprinting
- Implement `ObservabilityPlugin` with all trigger points
- Implement `PolicyPlugin`
- Configure all local callbacks per HIGH-6
- Configure worker `LlmAgent` instances per HIGH-3

**Phase 4: Parity testing (Week 4-5)**
- Run identical prompts through both old `rlm` and new ADK build
- Compare: final answers, iteration counts, sub-call counts, token usage
- Use `DebugLoggingPlugin` output for detailed comparison
- Fix discrepancies
- Validate `model=` routing (HIGH-5)
- Validate depth behavior (HIGH-4)

**Phase 5: Persistence & production (Week 5-6)**
- Implement `DatabaseSessionService` integration
- Port `SupportsPersistence` protocol to session state operations
- Validate versioned contexts and histories via state keys
- Configure `EventsCompactionConfig`, `ContextCacheConfig`, `ResumabilityConfig` (CRIT-2)
- Configure `RunConfig.max_llm_calls` based on profiling (HIGH-1)
- Remove `DebugLoggingPlugin` from production configuration

**Phase 6: Isolated environments (deferred)**
- Evaluate ADK's Daytona integration for sandbox execution (MED-2)
- Port or adapt the HTTP broker pattern for Modal/Prime/Docker/E2B
- The broker's `/enqueue` → `/pending` → `/respond` flow is orthogonal to ADK's local dispatch and may be retained as-is with the `LMHandler` TCP server replaced by ADK worker dispatch on the host side

### K.2 Parity test plan

| Test Category | What to Compare | Pass Criteria |
|--------------|----------------|---------------|
| **Basic completion** | Same prompt → final answer | Semantically equivalent (LLM non-determinism expected) |
| **Code execution** | Same code blocks extracted and executed | Identical code extraction; equivalent execution results |
| **Sub-LM routing** | `llm_query(p, model="X")` reaches correct backend | Same model invoked, same response quality |
| **Depth routing** | Default depth=1 routing | Same backend selected |
| **Batched calls** | `llm_query_batched(prompts)` | Same number of results, same order |
| **Iteration count** | Number of loops before FINAL | Same count ±1 (LLM non-determinism) |
| **Usage tracking** | Token counts per model | Match within 5% tolerance |
| **Max iteration fallback** | Behavior when FINAL not found | Default answer produced |
| **Persistence** | Multi-turn with versioned contexts | Same context variables accessible |
| **Error handling** | Missing API key, bad model name | Same error types raised |

### K.3 Rollback strategy

1. The ADK build is a **parallel implementation**, not an in-place modification. The original `rlm` code remains functional.
2. The `RLM` class constructor gains an `engine` parameter: `engine="classic"` (default, original) or `engine="adk"`.
3. During migration, both engines are available. Integration tests run against both.
4. Rollback = set `engine="classic"`. No code changes required.
5. After Phase 5 parity is confirmed, `engine="adk"` becomes default. Classic engine deprecated.
6. After Phase 6, classic engine removed.

### K.4 Definition of done checklist

- [ ] `rlm.completion(prompt)` produces equivalent results via ADK engine
- [ ] `llm_query()` and `llm_query_batched()` work from within `exec()`'d code
- [ ] `model=` parameter routes to correct backend
- [ ] Depth-based routing preserved (depth=0 → main, depth=1 → other)
- [ ] `FINAL()` and `FINAL_VAR()` extraction works
- [ ] Max-iteration fallback to `_default_answer` works
- [ ] Token usage tracked and aggregated correctly
- [ ] All plugins registered and firing at correct trigger points
- [ ] State schema keys populated correctly (spot-check via `DebugLoggingPlugin`)
- [ ] Cache plugin achieves cache hits on repeated identical sub-calls
- [ ] Persistent mode works with `DatabaseSessionService`
- [ ] `RunConfig.max_llm_calls` configured and tested
- [ ] `EventsCompactionConfig` prevents unbounded event growth
- [ ] No `ctx.session.state[key] = value` mutations in `_run_async_impl` (CRIT-1)
- [ ] All workers configured with `include_contents='none'`, `disallow_transfer_to_parent=True`, `disallow_transfer_to_peers=True` (HIGH-3)
- [ ] `DebugLoggingPlugin` removed from production configuration
- [ ] All tests pass: unit, integration, parity

---

## Next Actions

1. **Scaffold the ADK project** — create `rlm_adk/` package with `__init__.py`, `agent.py`, `plugins/`, `callbacks/`, `tools/` directories following ADK project structure conventions.

2. **Implement `RLMOrchestratorAgent`** — custom `BaseAgent` with `_run_async_impl` containing the iteration loop skeleton. Start with hardcoded prompts, no sub-LM dispatch.

3. **Implement the AST rewriting transformer** — `ast.NodeTransformer` that converts `llm_query(p)` to `await llm_query_async(p)` and wraps code in `async def _repl_exec()`. Unit test with representative LM-generated code samples.

4. **Implement the worker pool** — `asyncio.Queue`-based pool of `LlmAgent` instances with `ParallelAgent` dispatch. Test with mock models first, then real backends.

5. **Port `LocalREPL` execution semantics** — sandboxed `exec()` with safe builtins, context injection, stdout/stderr capture using `contextvars.ContextVar`. Validate REPL parity.

6. **Implement `DepthGuardPlugin` and `ObservabilityPlugin`** — these are the highest-value plugins for correctness and debuggability. Wire up `on_model_error_callback` (HIGH-2).

7. **Implement `CachePlugin`** — fingerprinting + intervene pattern. Test cache hit/miss behavior with deterministic prompts.

8. **Write parity test suite** — side-by-side comparison framework that runs identical prompts through classic and ADK engines, comparing outputs, iteration counts, and token usage.

9. **Configure `App`-level settings** — `EventsCompactionConfig`, `ContextCacheConfig`, `ResumabilityConfig`, `RunConfig` with calculated `max_llm_calls`.

10. **Evaluate Daytona ADK integration** — once local execution parity is confirmed, assess whether the Daytona integration can replace the custom HTTP broker for isolated environments.
