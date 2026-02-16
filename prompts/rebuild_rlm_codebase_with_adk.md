## PROMPT: “Rebuild `rlm` on Google-ADK”

You are a **software documentation agent**. Your job is to draft **rebuild-grade software documentation** for porting an existing GitHub codebase to a new core dependency.

### 0) Inputs (read these first)

* Codebase: `alexzhang13/rlm` (Recursive Language Models inference library) ([GitHub][1])
* **CRITICAL: Start your overview of the `rlm` codebase by reading `@rlm_packed.xml` first. DO NOT attempt to read every file in the codebase individually unless you need deep detail on a specific implementation after reviewing the repomix file.**
* New core dependency: Google **Agent Development Kit (ADK) for Python** docs:

  * Callbacks design patterns & best practices ([Google GitHub][2])
  * Plugins + plugin callback hooks ([Google GitHub][3])
  * Sessions / State (`session.state`) ([Google GitHub][4])
  * Types of callbacks (before/after agent/model/tool) ([Google GitHub][5])

### 1) Your deliverable

Produce a **single, cohesive “Port & Rebuild Guide”** that would allow an engineering team to:

1. Understand the current `rlm` architecture and its execution lifecycle
2. Design an ADK-native architecture that preserves core behavior
3. Implement the rebuild with **ADK callbacks + plugin callbacks + state key-value pairs** as the primary control/observability surface
4. Validate parity (functional + behavioral + performance) and provide migration steps

Write as if this is the canonical doc in the repo: **clear, prescriptive, and complete**.

---

## 2) Ground-truth summary of the current `rlm` system (you must base on repo facts)

Explain the existing architecture at a level sufficient to port it:

### 2.1 Core concepts to capture

* RLM replaces `llm.completion(...)` with `rlm.completion(...)` and offloads context into a REPL environment; the LM can recursively call itself via the environment. ([GitHub][1])
* Default environment is a **local REPL** (same process, `exec`, shares host venv) and there are **isolated environments** (e.g., cloud sandboxes) with different comms patterns. ([GitHub][1])
* The repo’s “environment ↔ LM handler communication” includes a host `LMHandler` TCP server, length-prefixed JSON requests, and an HTTP broker pattern for isolated sandboxes. ([GitHub][6])
* Clients and environments are extensible via base classes (`BaseLM`, `NonIsolatedEnv`, `IsolatedEnv`) and registry patterns. ([GitHub][6])
* Dependencies indicate multi-provider LLM backends (OpenAI, Anthropic, Google GenAI, etc.). ([GitHub][7])

### 2.2 What NOT to do

Do not invent modules/classes that are not in the repo. If you’re unsure, say “unspecified in source” and proceed with an assumption clearly labeled.

---

## 3) Target architecture: ADK-first rebuild (this is the heart of the doc)

Your documentation must propose an ADK-native design that emphasizes:

### 3.1 A callback-driven control plane

Use ADK callback patterns explicitly:

* Guardrails & policy enforcement via `before_model_callback` / `before_tool_callback` that can block or short-circuit. ([Google GitHub][2])
* Dynamic state management via `callback_context.state` / `tool_context.state` with changes tracked into `Event.actions.state_delta` and persisted by `SessionService`. ([Google GitHub][2])
* Logging/monitoring and caching patterns as first-class callback responsibilities. ([Google GitHub][2])
* Conditional skipping of steps (show how this replaces ad-hoc branching). ([Google GitHub][2])

### 3.2 Plugins vs local callbacks (you must delineate crisply)

Explain and enforce the hierarchy:

**Plugins (global, Runner-registered):**

* Apply globally to every agent/tool/model in a Runner. ([Google GitHub][3])
* Execute **before** object-level callbacks; plugin return values can short-circuit and skip downstream callbacks. ([Google GitHub][3])
* Support modes: observe (no return), intervene (return value short-circuits), amend (mutate context). ([Google GitHub][3])

**Agent/Model/Tool callbacks (local, instance-configured):**

* Apply only to that specific instance. ([Google GitHub][3])

### 3.3 State as the backbone (`session.state`)

Your guide must include a **state taxonomy** and rules:

* State is a key-value scratchpad per session; keys are strings; values must be serializable; persistence depends on the SessionService. ([Google GitHub][4])
* Use prefix scoping conventions and explain why:

  * no prefix -> session
  * `user:` cross-session per user
  * `app:` global per app
  * `temp:` invocation-scoped (discarded after invocation) ([Google GitHub][4])
* Explicitly warn against modifying `session.state` outside callback/tool contexts; prefer context-based state updates or `EventActions.state_delta`. ([Google GitHub][4])

---

## 4) Required documentation sections (write them all)

Your output MUST contain these sections, in this order:

### A. Executive intent

* What behavior is preserved from `rlm`
* What changes because ADK becomes the execution substrate
* What “done” means (parity criteria)

### B. Current system map (from `rlm`)

* Lifecycle: prompt → REPL load → code exec → subcalls → final response
* Environment types (non-isolated vs isolated) and comms models (TCP vs broker) ([GitHub][6])
* Extensibility points: LM clients, environments, registries ([GitHub][6])

### C. ADK rebuild architecture

* Component diagram in text (no images required)
* Runner + SessionService choices and what they imply for persistence ([Google GitHub][4])
* How RLM recursion maps onto ADK agent composition (e.g., parent agent orchestrating sub-agent calls); explain invocation scoping for `temp:` keys when sub-agents are used. ([Google GitHub][4])

### D. Callback & Plugin plan (the “porting contract”)

Provide:

1. A **Plugin suite** (global cross-cutting concerns)
2. A **Local callback suite** (per-agent/tool specifics)

For each item include:

* Name
* Trigger points (before/after agent/model/tool; plugin hooks)
* What it reads/writes in `state`
* What it logs/exports (observability)
* Failure behavior (short-circuit vs escalate)

Use ADK’s callback timing definitions (before/after agent and what they’re “for”). ([Google GitHub][5])

### E. State schema: key naming + ownership + lifecycle

Produce a table-like spec (markdown is fine) that includes:

* Key prefix and why
* Which module “owns” writing it (plugin vs local callback vs tool)
* When it is valid (invocation/session/user/app)
* Serialization constraints
* Example values

You MUST include keys for:

* Flow control (e.g., skip flags, recursion depth, stopping conditions)
* Caching (request fingerprints, hit/miss counters)
* Observability (timings, token usage, tool invocation summaries)
* Type validation outcomes (schema pass/fail, error summaries)
* API/messaging integration (request IDs, idempotency keys, last successful call IDs)

### F. Porting the RLM “REPL + LMHandler” concept into ADK

Explain how to express these in ADK terms:

* `llm_query()` and `llm_query_batched()` are **namespace-injected closures** that LM-generated code calls inside `exec()` — they are NOT ADK `FunctionTool`s. Their string return values are consumed programmatically by the executing code (JSON parsing, list indexing, conditional logic). See CRIT-3 for the async dispatch architecture.
* The LM handler's depth-based and model-name routing mapped onto ADK `LlmAgent` configuration — preserving the `model=` parameter that lets REPL code address specific backends (see HIGH-5)
* Where the old TCP/broker patterns fit (if they remain for isolated environments) vs what ADK replaces for local execution
  Tie each decision to **plugins/callbacks/state** rather than “just code”.

### G. Caching strategy (must be callback-first)

Describe:

* Global cache plugin design that can short-circuit model calls (plugin “intervene” pattern). ([Google GitHub][3])
* Local caches for tool outputs where appropriate
* Cache key design, invalidation, storage backend options
* Telemetry keys in `state` for cache observability

### H. Observability & audit trail

Define:

* Event model: how state changes become `state_delta` and persist via SessionService ([Google GitHub][2])
* What gets logged at plugin level vs local level
* How to trace a single user invocation end-to-end via IDs stored in state

### I. Type validation & safety

Document:

* What must be validated at boundaries (tool args, tool outputs, model I/O envelopes)
* How validation failures are recorded in state and escalated
* “Fail fast, fail loud” guidance compatible with the repo’s culture ([GitHub][6])

### J. API/messaging integration

Specify:

* Where inbound/outbound messaging occurs (Runner input, tool calls, event hooks)
* How to store idempotency keys and request IDs in state
* How plugins enforce auth/policy before tool execution ([Google GitHub][2])

### K. Migration plan

Include:

* Incremental port strategy (thin slice first)
* Parity test plan
* Rollback strategy
* “Definition of done” checklist

---

## 5) Hard constraints (follow these)

* Keep the doc rebuild-grade: someone should be able to implement from it.
* Prefer ADK mechanisms (plugins/callbacks/state) over ad-hoc control flow.
* Do not recommend direct `session.state` mutation outside context-managed lifecycles; explicitly call out the ADK warning. ([Google GitHub][4])
* Every cross-cutting concern must be assigned to **a plugin** unless there’s a strong reason it must be local. ([Google GitHub][3])
* Make a clear distinction between:

  * **Global plugin callback hooks** (Runner registered, precedence) ([Google GitHub][3])
  * **Local callbacks** (agent/model/tool instance) ([Google GitHub][5])
* Do not include implementation code unless explicitly requested; this deliverable is documentation, architecture, and specs.

---

## 5b) ADK pattern clarifications (apply these throughout)

The following clarifications address specific ADK library patterns and component
associations that the output document MUST reflect accurately. Each is tied to
one or more sections from §4.

### CRIT-1: State mutation inside custom `BaseAgent._run_async_impl`

**Affects: §C, §E, §F, §H**

Inside `_run_async_impl`, writing to `ctx.session.state` directly **bypasses
delta tracking**. The `State.__setitem__` delta mechanism only fires through
`CallbackContext.state` or `ToolContext.state`. In a custom `BaseAgent`, the
only correct way to record a state change is to **yield an `Event` with
`EventActions(state_delta={...})`**:

```
yield Event(
    invocation_id=ctx.invocation_id,
    author=self.name,
    actions=EventActions(state_delta={"temp:iteration_count": i + 1}),
)
```

Every inline state write inside `_run_async_impl` (iteration counters,
pending code blocks, REPL results, final answers, message history, all `obs:`
metrics written from the orchestrator loop) MUST use this pattern. Direct
`ctx.session.state[key] = value` mutations are an **anti-pattern** that will
silently break persistence with any `SessionService` other than in-memory.

State writes inside **callbacks** (`before_agent_callback`,
`after_model_callback`, etc.) correctly use `callback_context.state` and are
unaffected by this constraint.

### CRIT-2: Use the `App` class — plugins on `Runner` are deprecated

**Affects: §C, §D**

As of ADK v1.7.0+, the `plugins` parameter on `Runner` is **deprecated**.
The correct top-level container is `google.adk.apps.App`:

```
App(
    name="rlm_adk",
    root_agent=orchestrator_agent,
    plugins=[...],
    events_compaction_config=...,   # manage event growth in long sessions
    context_cache_config=...,       # Gemini context caching for static prompts
    resumability_config=...,        # for interrupted long-running sessions
)
```

The component diagram (§C.1) must show `App` as the outermost container. The
`Runner` receives the `App` via `Runner(app=app, session_service=...)`. Three
`App`-level configuration objects must be evaluated:

| Config                      | ADK Class                  | RLM relevance |
|-----------------------------|----------------------------|---------------|
| `events_compaction_config`  | `EventsCompactionConfig`   | 15 iterations × N sub-calls accumulate many events; compaction prevents unbounded growth |
| `context_cache_config`      | `ContextCacheConfig`       | The RLM system prompt is largely static across iterations; Gemini context caching reduces repeated token cost |
| `resumability_config`       | `ResumabilityConfig`       | Long-running REPL sessions that may be interrupted map to `persistent=True` |

### HIGH-1: `RunConfig` must be specified

**Affects: §C, §F, §K**

`RunConfig` controls runtime behavior passed to `runner.run_async()`. The
output must address `RunConfig.max_llm_calls` (default: **500**). With 15
iterations and multiple sub-LM calls per iteration, the orchestrator can hit
this safety cap. The doc must specify how to calculate and configure this
limit (e.g., `max_iterations * expected_sub_calls_per_iteration * safety_margin`).

Additionally evaluate `StreamingMode` for the REPL use case and document the
choice (likely `StreamingMode.NONE` for non-streaming completion parity).

### HIGH-2: Leverage `on_model_error_callback` and `on_tool_error_callback`

**Affects: §D, §F**

ADK v1.7.0 introduced error-specific plugin callbacks:

- `on_model_error_callback`: fires when a model API call throws an exception.
  Can return a fallback `LlmResponse` to suppress the error and resume flow.
- `on_tool_error_callback`: fires when a tool raises an exception.
  Can return a fallback `dict` to suppress the error.

The `DebugLoggingPlugin` must implement `on_model_error_callback` at minimum
for recording model failures. If a `DepthGuardPlugin` or similar uses
`before_model_callback` to intervene, model *errors* (rate limits, auth
failures, transient HTTP errors) should be caught by `on_model_error_callback`
as the ADK-native first line of defense. The `asyncio.wait_for` timeout in
the dispatch function is a complementary cooperative-cancellation layer, not
a replacement for the error callback.

### HIGH-3: Worker `LlmAgent` instances need additional configuration fields

**Affects: §C, §F**

Worker `LlmAgent` declarations must include:

| Field                          | Value    | Reason |
|--------------------------------|----------|--------|
| `include_contents`             | `'none'` | Workers receive prompts entirely via `before_model_callback`; without this, workers receive the full growing conversation history, wasting tokens on every sub-LM call |
| `disallow_transfer_to_parent`  | `True`   | Prevents the LLM from deciding to transfer control away from the worker, which would break the dispatch/return contract |
| `disallow_transfer_to_peers`   | `True`   | Same — workers must complete and return, never transfer |
| `generate_content_config`      | Set `temperature` appropriate to task (e.g., `0.0` for deterministic classification) | Current `BaseLM` config params must be mapped to `GenerateContentConfig` |

### MED-1: Use the native `DebugLoggingPlugin` for development

**Affects: §D, §H**

ADK ships `DebugLoggingPlugin` which records detailed interaction data to a
YAML file (`adk_debug.yaml` by default). During development and parity testing
(§K), register `DebugLoggingPlugin` alongside any custom observability plugin:

```
DebugLoggingPlugin(
    output_path="rlm_adk_debug.yaml",
    include_session_state=True,
    include_system_instruction=True,
)
```

This provides full interaction traces for debugging the REPL loop, AST
transformer behavior, and worker dispatch without building custom logging
infrastructure. The output must mention this as a development-phase tool
in the plugin suite (§D.1) and migration plan (§K).

### MED-2: Scope the environment rebuild to local execution only

**Affects: §B, §C, §F, §K**

The ADK integrations catalog includes a first-party **Daytona integration**
for sandbox code execution. However, for the initial rebuild phases, the
output document must scope the environment story to **local code execution
only** (`LocalREPL` equivalent). Isolated environments (Modal, Prime, Docker,
E2B, Daytona) are deferred to Phase 6 of the migration plan.

The document should note the Daytona ADK integration exists and should be
evaluated when the isolated environment phase begins, but must not design
around it prematurely. All architecture and state schema decisions in §C–§F
must work end-to-end with the local REPL path before isolated environments
are considered.

### LOW-1: `cache:` is a naming convention, not a special ADK prefix

**Affects: §E, §G**

ADK recognizes exactly four prefix scopes: unprefixed (session-scoped),
`app:`, `user:`, and `temp:`. The `cache:` prefix used in the caching state
keys (e.g., `cache:hit_count`, `cache:miss_count`) is **not** an ADK-recognized
prefix — it is a naming convention and these keys are **session-scoped**
(persisted within the session by `SessionService`, not discarded like `temp:`).

The state schema (§E) must explicitly note this: `cache:*` keys behave as
unprefixed session state and will persist across invocations within the same
session. If cache counters should reset per invocation, they must use `temp:`
prefix instead (e.g., `temp:cache_hit_count`). If they should accumulate
across invocations for observability, session-scoped is correct but the doc
must state this is an intentional choice.

### CRIT-3: REPL async dispatch architecture

**Affects: §C, §F, §K**

The REPL presents a sync/async boundary: `exec()` is synchronous, but ADK
agents are async. The correct strategy is **AST rewriting** — an
`ast.NodeTransformer` transforms LM-generated code so that `llm_query(p)`
becomes `await llm_query_async(p)` (and the batched variant), wrapping the
entire code block in `async def _repl_exec()`. The orchestrator's
`_run_async_impl` then `await`s this function natively — no thread pool,
no `run_in_executor`, no `run_coroutine_threadsafe`.

The document must specify these mechanics precisely:

1. **All worker dispatch goes through `ParallelAgent`**: Pre-allocated
   `LlmAgent` instances managed via `asyncio.Queue`. Both
   `llm_query_async(prompt)` and `llm_query_batched_async(prompts)` use
   the same code path: acquire K workers from the pool (K=1 for single,
   K=N for batched), compose them into a
   `ParallelAgent(name="batch_dispatch", sub_agents=acquired_workers)`,
   yield from `ParallelAgent.run_async(ctx)`, read results from each
   worker's `output_key`, and return workers to the pool. There is **no
   separate single-dispatch path** — `llm_query_async` is the degenerate
   K=1 case. This unified path means: event propagation from workers is
   always handled by `ParallelAgent` natively, plugin callbacks always
   fire on the parallel dispatch as a unit, and there is one dispatch
   implementation to test and maintain. `ParallelAgent` is lightweight
   (no fields beyond `BaseAgent`) so per-call construction is cheap.

2. **Event yield**: Because all worker dispatch goes through
   `ParallelAgent`, the orchestrator yields events from
   `ParallelAgent.run_async(ctx)` and events from all workers flow
   through to the Runner without a manual drain loop per dispatch. For
   the **overall REPL task** (`_repl_exec()`), a concurrent event queue
   is still needed: the REPL coroutine runs as an `asyncio.Task`,
   `ParallelAgent` events from each dispatch are collected into an
   `asyncio.Queue` by the dispatch closure, and a drain loop in
   `_run_async_impl` yields them to the Runner. Use a sentinel value to
   signal task completion. The drain loop and the REPL task interleave
   cooperatively at `await` points within the same event loop.

3. **Timeout shape**: Timeouts wrap a **consumption coroutine** — an
   `async def` that iterates the worker's async generator and collects
   events — not the async generator object itself. The correct form is
   `asyncio.wait_for(consume_coroutine(), timeout=N)`. An async generator
   is not an awaitable and cannot be passed to `asyncio.wait_for` directly.

4. **stdout/stderr capture**: The capture mechanism (e.g., `sys.stdout` /
   `sys.stderr` redirect to `StringIO`) must define its boundary relative
   to async `await` points. When `_repl_exec()` yields control during
   `await llm_query_async(...)`, the event loop may run other coroutines.
   Specify whether capture covers the full task lifetime or only
   synchronous segments.

### HIGH-4: Recursion depth is a nesting level, not a dispatch counter

**Affects: §C, §D, §E, §F**

In current `rlm`, `depth` is a property of the `LMRequest`: 0 for the
orchestrator, 1 for sub-LM calls from REPL code. It does **not** increment
per concurrent worker dispatch. In the ADK rebuild, the depth value must be
set **once** when entering REPL execution context and remain constant
regardless of how many workers are dispatched concurrently. If a
`DepthGuardPlugin` checks depth and it were incremented per dispatch,
batched calls would be incorrectly blocked.

### HIGH-5: `model=` parameter routing must be preserved

**Affects: §C, §F**

`llm_query(prompt, model="X")` accepts an optional `model` parameter. In
current `rlm`, `LMHandler.get_client(model, depth)` routes by explicit model
name (overriding depth-based routing) when a model is specified and
registered. The ADK rebuild must preserve this: when REPL code passes a
`model` argument, the dispatch function must route to the correct backend.
Specify the routing mechanism (e.g., per-model worker pools, dynamic model
override via `before_model_callback`, or `generate_content_config` override).

### HIGH-6: Every `LlmAgent` variant requires a full callback specification

**Affects: §D**

The callback plan (§D.2) must define `before_model_callback` and
`after_model_callback` for **every** `LlmAgent` type — reasoning agent,
workers, and the default-answer agent (invoked when max iterations are
exhausted). An agent without callback specifications is an agent without
prompt injection and observability.

---

## 6) Output format requirements

* Use Markdown headings and tight, readable structure.
* Include at least:

  * 1 architecture “map” section (text diagram)
  * 1 state schema section (table-like)
  * 1 callback/plugin catalog section (bullet spec or table-like)
  * 1 migration checklist section

End with a short “Next actions” list (max 10 bullets) describing the immediate engineering steps.

---

[1]: https://github.com/alexzhang13/rlm "GitHub - alexzhang13/rlm: General plug-and-play inference library for Recursive Language Models (RLMs), supporting various sandboxes."
[2]: https://google.github.io/adk-docs/callbacks/design-patterns-and-best-practices/ "Callback patterns - Agent Development Kit"
[3]: https://google.github.io/adk-docs/plugins/ "Plugins - Agent Development Kit"
[4]: https://google.github.io/adk-docs/sessions/state/ "State - Agent Development Kit"
[5]: https://google.github.io/adk-docs/callbacks/types-of-callbacks/ "Types of callbacks - Agent Development Kit"
[6]: https://raw.githubusercontent.com/alexzhang13/rlm/main/AGENTS.md "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/alexzhang13/rlm/main/pyproject.toml "raw.githubusercontent.com"
