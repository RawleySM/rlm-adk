<!-- validated: 2026-03-17 -->

# ADK v1.27.0 A2A & Multi-Agent: Opportunity Assessment for RLM-ADK

## 1. What Changed in v1.27.0

ADK v1.27.0 introduces first-class (experimental) support for the Agent-to-Agent (A2A) protocol. The key additions:

### 1.1 RemoteA2aAgent (`google.adk.agents.remote_a2a_agent`)

A new `BaseAgent` subclass that acts as a **client** to a remote A2A service. It:

- Accepts an `AgentCard` (object, URL, or file path) describing the remote agent's capabilities and endpoint.
- Resolves the card lazily on first invocation, caches the result.
- Converts ADK session events into A2A `Message` objects (via `GenAIPartToA2APartConverter`), sends them to the remote agent over JSON-RPC, and converts the A2A response back into ADK `Event` objects.
- Supports streaming task updates (working/submitted/completed state transitions), artifact updates, and thought propagation.
- Manages session statefulness: tracks `context_id` and `task_id` across calls so stateful remote agents preserve context.
- Accepts an `a2a_request_meta_provider` callback for injecting auth tokens, request metadata, or custom headers into outgoing A2A requests. This is the **interceptor** pattern mentioned in the changelog.
- Manages its own `httpx.AsyncClient` lifecycle (or accepts a shared one via `A2AClientFactory`).
- Surfaces errors as ADK `Event` objects with `error_message` and `custom_metadata` containing A2A-specific diagnostics.

### 1.2 A2aAgentExecutor (`google.adk.a2a.executor.a2a_agent_executor`)

A new `AgentExecutor` implementation that acts as a **server**, exposing any ADK agent as an A2A-compatible service. It:

- Wraps an ADK `Runner` (or a callable that produces one).
- Converts incoming A2A `RequestContext` into ADK `Content` + `RunConfig` via pluggable `A2ARequestToAgentRunRequestConverter`.
- Runs the ADK agent via `runner.run_async()`, converting each yielded ADK `Event` into A2A `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent` via pluggable `AdkEventToA2AEventsConverter`.
- Publishes all updates to an A2A `EventQueue` for streaming back to the caller.
- Handles session creation/lookup automatically.
- Uses `TaskResultAggregator` to determine final task state (completed/failed/auth_required/input_required).

### 1.3 Conversion Layer (`google.adk.a2a.converters`)

Bidirectional converters between ADK and A2A types:

- **Part converters**: `convert_genai_part_to_a2a_part` / `convert_a2a_part_to_genai_part` -- handle text, files, inline data, function calls/responses, code execution results. Thought propagation is preserved via `TextPart.metadata["adk:thought"]`.
- **Event converters**: `convert_event_to_a2a_events` / `convert_a2a_message_to_event` -- map ADK Events to A2A TaskStatusUpdateEvents and back. Long-running tool metadata is preserved.
- **Request converter**: `convert_a2a_request_to_agent_run_request` -- maps A2A `RequestContext` into ADK runner arguments.
- All converters are pluggable (type-aliased callables), enabling custom serialization.

### 1.4 Utilities

- **`AgentCardBuilder`**: Builds an A2A `AgentCard` from any ADK `BaseAgent` by introspecting its tools, sub-agents, planner, code executor, and instruction text. Supports LlmAgent, SequentialAgent, ParallelAgent, LoopAgent, and custom agents.
- **`to_a2a()`**: One-liner to convert any ADK agent into a Starlette ASGI application with A2A routes, agent card at `/.well-known/agent.json`, and automatic session/artifact services.

### 1.5 Experimental Status

All A2A classes are decorated with `@a2a_experimental`, which emits a warning on first use. The A2A protocol itself is not experimental -- only ADK's implementation wrapper is. This means the API surface may change in future ADK releases.

---

## 2. Mapping Against Current RLM-ADK Architecture

### 2.1 Current Dispatch Architecture

```
RLMOrchestratorAgent._run_async_impl(ctx)
  |
  +-- creates REPLTool, wires reasoning_agent with tools
  +-- delegates to reasoning_agent.run_async(ctx)
       |
       +-- LLM generates code calling llm_query() / llm_query_batched()
       +-- AST rewriter converts to await llm_query_async()
       +-- dispatch.py: create_dispatch_closures() produces closures
            |
            +-- _run_child(prompt, model, output_schema, fanout_idx)
                 |
                 +-- create_child_orchestrator(model, depth+1, prompt, ...)
                 +-- child.run_async(child_ctx)  [in-process, shared session]
                 +-- _read_child_completion() extracts result
                 +-- Returns LLMResult to REPL code
```

Key characteristics of the current design:

- **In-process only**: Children are `RLMOrchestratorAgent` instances running in the same Python process, sharing the same `InvocationContext` (with branched event history).
- **Shared session state**: Children read/write depth-scoped keys in the shared session. `flush_fn()` atomically snapshots accumulators into `tool_context.state`.
- **Semaphore-limited concurrency**: `_child_semaphore` (default 3) limits parallel children.
- **Depth-limited recursion**: `max_depth` (default 3) prevents infinite recursion.
- **Rich observability**: Per-child summaries, error classification, token accounting, latency tracking, structured output outcome tracking -- all flow through local accumulators into session state via `flush_fn()`.
- **REPL integration**: Children are invisible to the REPL code -- `llm_query()` returns an `LLMResult(str)` that the code processes like any string.

### 2.2 A2A Alternative: Remote Dispatch

With `RemoteA2aAgent`, a child dispatch could instead send the prompt to a remote A2A service:

```
_run_child(prompt, model, output_schema, fanout_idx)
  |
  +-- Instead of create_child_orchestrator():
  |     remote_agent = RemoteA2aAgent(name=..., agent_card=card_url)
  |     async for event in remote_agent.run_async(child_ctx):
  |         ... collect events, extract result ...
  |
  +-- Convert A2A response to LLMResult
  +-- Return to REPL code (same interface)
```

### 2.3 A2A Server: Exposing RLM-ADK

With `A2aAgentExecutor` + `to_a2a()`, the RLM orchestrator itself can be exposed:

```
# rlm_adk/a2a_server.py (hypothetical)
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from rlm_adk.agent import create_rlm_app

app_adk = create_rlm_app(model="gemini-3.1-pro-preview")
a2a_app = to_a2a(
    app_adk.root_agent,
    host="0.0.0.0",
    port=8080,
    runner=create_rlm_runner(model="gemini-3.1-pro-preview"),
)
# uvicorn rlm_adk.a2a_server:a2a_app --host 0.0.0.0 --port 8080
```

This would make RLM-ADK callable by any A2A-compatible agent or orchestrator.

---

## 3. Proposed Integration Opportunities

### 3.1 Expose RLM-ADK as an A2A Service

**What**: Create `rlm_adk/a2a_server.py` that wraps the existing orchestrator as an A2A endpoint.

**Why**: Other agents (Claude Code, Gemini agents, third-party A2A clients) could invoke RLM-ADK as a specialized "recursive analysis" service. This aligns with the personal-agent evolution philosophy -- the agent becomes a reusable capability, not just an interactive CLI tool.

**Key design decisions**:

- Use `create_rlm_runner()` (not the default `to_a2a()` in-memory services) to get real SQLite sessions, file artifacts, and the full plugin stack. The `to_a2a()` convenience function defaults to `InMemorySessionService` which would break observability and persistence.
- Build a custom `AgentCard` rather than relying on `AgentCardBuilder` auto-generation, because RLM's capabilities (recursive REPL execution, structured output, depth-limited recursion) are not easily inferred from the agent tree.
- Wire the existing `ObservabilityPlugin` and `SqliteTracingPlugin` through the Runner so A2A-served requests get full tracing.

**Effort**: S (small) -- the plumbing exists; the work is a thin server script + agent card definition + deployment config.

### 3.2 Consume External A2A Agents as Specialized Workers

**What**: Allow `llm_query()` calls in REPL code to optionally route to remote A2A agents instead of in-process children.

**Why**: Some sub-tasks benefit from specialized agents that RLM-ADK does not need to host itself:

- A code-review agent running on a different model or framework.
- A search/retrieval agent with access to private data sources.
- A domain-specific agent (legal, medical, financial) running behind access controls.

**How**: Introduce an `A2ADispatchTarget` alongside the existing in-process `DispatchConfig`:

```python
# Conceptual -- not final API
class A2ADispatchTarget:
    """Route specific sub-queries to a remote A2A agent."""
    agent_card: str | AgentCard
    route_predicate: Callable[[str], bool]  # prompt -> should_route
    timeout: float = 300.0

class DispatchConfig:
    default_model: str | Any
    other_model: str | Any | None = None
    pool_size: int = 5
    a2a_targets: list[A2ADispatchTarget] = []  # NEW
```

In `_run_child()`, check if any `a2a_target.route_predicate(prompt)` matches. If so, use `RemoteA2aAgent` instead of `create_child_orchestrator()`. The LLMResult interface remains identical -- REPL code is unaware of the routing.

**Effort**: M (medium) -- requires dispatch routing logic, RemoteA2aAgent lifecycle management, error classification for A2A errors, and integration tests.

### 3.3 Hybrid Dispatch: Local + Remote

**What**: A dispatch strategy that uses in-process children by default but falls back to (or prefers) A2A agents for specific prompt patterns, models, or capability requirements.

**Why**: The instruction_router already selects skill instructions per depth/fanout_idx. Extending this to select dispatch targets (local vs. remote) is a natural generalization. The Polya topology engine (planned) could use this to route "Understanding" tasks to a search agent and "Implementation" tasks to a code agent.

**Design principle**: The REPL code's `llm_query()` interface must not change. Routing is infrastructure, not application logic.

### 3.4 Thought Propagation Through A2A Boundaries

**What**: Preserve RLM's recursive reasoning chain when crossing A2A boundaries.

**Current state in ADK v1.27.0**:

- `convert_genai_part_to_a2a_part()` preserves `part.thought` as `TextPart.metadata["adk:thought"]`.
- `convert_a2a_part_to_genai_part()` reads `TextPart.metadata` but does NOT currently restore `part.thought` on the receiving side.
- `RemoteA2aAgent._handle_a2a_response()` marks streaming "working" state parts as `part.thought = True`.

**Gap for RLM-ADK**: RLM's reasoning callbacks (`reasoning_before_model`, `reasoning_after_model`) track `REASONING_THOUGHT_TEXT` and `REASONING_THOUGHT_TOKENS` via the GenAI response's thinking parts. When a child dispatches over A2A, the remote agent's thinking would need to flow back through the A2A response as thought-tagged parts, then be captured by the parent's observability pipeline.

**Mitigation**: The custom `a2a_part_converter` parameter on `RemoteA2aAgent` enables injecting a converter that maps `adk:thought` metadata back to `genai_types.Part(thought=True)`. This would make A2A-routed children's thoughts visible in the parent's trace.

---

## 4. Architectural Fit Assessment

### 4.1 Does A2A's Request/Response Model Fit RLM's Recursive Dispatch?

**Mostly yes, with caveats.**

- A2A's `send_message` -> stream of `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent` maps well to RLM's `child.run_async(ctx)` -> stream of `Event` pattern. Both are async generators yielding incremental results.
- A2A tasks have a clear lifecycle (submitted -> working -> completed/failed) that maps to RLM's child dispatch lifecycle.
- **Caveat: state isolation.** In-process children share the parent's `InvocationContext` (with branched event history). A2A children have fully isolated sessions. This means:
  - Depth-scoped state keys (`"key@d2"`) do not cross A2A boundaries. The remote agent manages its own session state.
  - `user_ctx` (REPL globals) cannot be shared. The remote agent would need the context passed in the prompt or via A2A message metadata.
  - `flush_fn()` accumulators work differently -- instead of reading child state deltas from a shared dict, the parent would need to extract observability data from the A2A response metadata.
- **Caveat: structured output.** RLM's `output_schema` parameter causes `create_child_orchestrator()` to wire `SetModelResponseTool` + `WorkerRetryPlugin` on the child. A remote A2A agent would need to implement its own structured output validation. The parent cannot enforce schema validation across an A2A boundary.

### 4.2 How Do A2A Interceptors Help?

The `a2a_request_meta_provider` callback on `RemoteA2aAgent` receives `(InvocationContext, A2AMessage)` and returns metadata dict. This enables:

- **Auth**: Inject bearer tokens, API keys, or signed JWTs per-request. Critical for calling external agents behind auth gates.
- **Rate limiting**: Attach quota identifiers so the remote server can enforce per-caller limits. Alternatively, implement client-side rate limiting in the provider callback.
- **Error context**: Attach the parent's `REQUEST_ID`, depth, and fanout_idx as metadata so the remote agent can include them in error responses for cross-boundary debugging.
- **Observability correlation**: Inject trace IDs (e.g., Langfuse trace ID, OpenTelemetry span ID) so distributed traces can be stitched together.

### 4.3 Impact on Observability

**A2A calls do NOT flow through RLM-ADK's plugins automatically.**

- `ObservabilityPlugin`, `SqliteTracingPlugin`, and `REPLTracingPlugin` operate on ADK Events within the parent's Runner. A2A responses arrive as events authored by the `RemoteA2aAgent`, which the plugins will see -- but they will not see the remote agent's internal events (tool calls, REPL executions, sub-dispatches).
- The remote agent, if it is also an RLM-ADK instance, runs its own plugin stack independently.
- **Mitigation path**: The A2A response's `custom_metadata` includes `adk:` prefixed keys (app_name, session_id, invocation_id, etc.). A custom plugin could extract these and record them in the parent's trace DB for cross-boundary correlation.
- The existing `_acc_child_summaries` accumulator pattern in `dispatch.py` would need an A2A-specific branch that builds child summaries from A2A response metadata instead of reading `_child_state` dicts.

---

## 5. Risks

### 5.1 Latency Overhead

- In-process child dispatch: ~0ms network overhead. The child runs in the same event loop.
- A2A child dispatch: HTTP round-trip + remote agent execution + response serialization. For a remote Gemini call, this adds 50-200ms of network overhead on top of the LLM latency.
- **Impact on RLM**: A parent REPL code block that dispatches 5 parallel `llm_query()` calls would see 5 parallel HTTP requests instead of 5 in-process coroutines. The semaphore still limits concurrency, but the wall-clock overhead increases.
- **Mitigation**: A2A dispatch should be opt-in for specific use cases (external specialists, cross-framework agents), not the default path. In-process dispatch remains the fast path.

### 5.2 State Isolation

- In-process children share session state (depth-scoped). A2A children are fully isolated.
- `user_ctx` (repo contents loaded into REPL globals) cannot be transparently shared over A2A. The remote agent starts with empty REPL globals.
- **Impact on RLM**: Recursive dispatch that depends on shared context (e.g., a child that needs to read files loaded by the parent) would not work over A2A without explicit context passing.
- **Mitigation**: For A2A dispatch, the parent would need to serialize relevant context into the prompt or use A2A message parts (FilePart for file data). This changes the dispatch semantics and may require prompt engineering.

### 5.3 Debugging Complexity

- In-process: all events, state deltas, and errors are in one trace DB, one log stream.
- A2A: the remote agent has its own trace DB, its own logs, its own error classification. Correlating a parent error with a remote child failure requires distributed tracing.
- **Mitigation**: Use the interceptor to inject correlation IDs. Build a dashboard view that stitches parent + child traces via shared `REQUEST_ID`.

### 5.4 Experimental API Stability

- All A2A classes are `@a2a_experimental`. ADK may change the API in v1.28+.
- **Mitigation**: Wrap A2A usage behind an abstraction layer (`rlm_adk/dispatch_a2a.py`) so changes to ADK's A2A API only require updating one file.

### 5.5 Structured Output Across Boundaries

- RLM's `output_schema` + `WorkerRetryPlugin` + BUG-13 monkey-patch are tightly coupled to in-process `LlmAgent` internals.
- A remote A2A agent cannot be instrumented with these patches.
- **Mitigation**: The remote agent must implement its own structured output validation. The parent should treat A2A responses as unvalidated text and do client-side schema validation if needed.

---

## 6. Opportunity Rating

| Dimension | Rating | Rationale |
|-----------|--------|-----------|
| **Effort: Expose RLM-ADK as A2A service** | **S** (small) | `to_a2a()` exists. Need: custom AgentCard, server script, pass real Runner with plugins. ~1 day. |
| **Effort: Consume external A2A agents** | **M** (medium) | Requires dispatch routing, RemoteA2aAgent lifecycle, error mapping, observability bridge. ~3-5 days. |
| **Effort: Full hybrid dispatch** | **L** (large) | Requires dispatch strategy abstraction, context serialization for A2A, distributed tracing, structured output bridge. ~2 weeks. |
| **Impact** | **Medium** | Near-term: A2A exposure enables RLM-ADK to be called by other agents (useful for personal multi-agent workflows). A2A consumption enables specialist delegation. Long-term: enables the Polya topology engine to route phases to different agent types. |
| **Risk** | **Medium** | Experimental API may break. State isolation changes dispatch semantics. Latency overhead for chatty recursive patterns. But: all A2A features are additive -- nothing breaks the existing in-process dispatch path. |

---

## 7. Recommended Sequencing

### Phase 1: Expose (S effort, immediate value)

Create `rlm_adk/a2a_server.py` with a custom `AgentCard` and `A2aAgentExecutor` wrapping `create_rlm_runner()`. Deploy locally. Test with the ADK `RemoteA2aAgent` from a second agent.

**Acceptance criteria**: Another ADK agent can send a prompt to RLM-ADK over A2A and receive a structured response with the final answer.

### Phase 2: Consume (M effort, enables specialist delegation)

Add `A2ADispatchTarget` to `DispatchConfig`. Implement A2A-aware `_run_child()` branch in `dispatch.py`. Build observability bridge for A2A child summaries.

**Acceptance criteria**: REPL code calling `llm_query("review this code", model="a2a://code-review-agent")` routes to a remote A2A agent and returns an `LLMResult` indistinguishable from an in-process child.

### Phase 3: Hybrid + Polya Integration (L effort, strategic)

Integrate dispatch target selection into the instruction_router / Polya topology engine. Implement context serialization for A2A dispatch. Build distributed tracing dashboard.

**Acceptance criteria**: The Polya topology engine can route "Understanding" phase to a remote search agent and "Implementation" phase to the local REPL agent, with full end-to-end observability.

---

## 8. Key Source Files Referenced

| File | Role |
|------|------|
| `rlm_adk/orchestrator.py` | Current orchestrator -- delegates to reasoning_agent |
| `rlm_adk/dispatch.py` | Current dispatch -- in-process child orchestrators |
| `rlm_adk/agent.py` | Factory functions -- `create_child_orchestrator()`, `create_rlm_runner()` |
| `.venv/.../google/adk/agents/remote_a2a_agent.py` | ADK's RemoteA2aAgent (A2A client) |
| `.venv/.../google/adk/a2a/executor/a2a_agent_executor.py` | ADK's A2aAgentExecutor (A2A server) |
| `.venv/.../google/adk/a2a/utils/agent_to_a2a.py` | `to_a2a()` convenience function |
| `.venv/.../google/adk/a2a/utils/agent_card_builder.py` | AgentCardBuilder for auto-generating cards |
| `.venv/.../google/adk/a2a/converters/part_converter.py` | Bidirectional part conversion (GenAI <-> A2A) |
| `.venv/.../google/adk/a2a/converters/event_converter.py` | Bidirectional event conversion |
| `.venv/.../google/adk/a2a/converters/request_converter.py` | A2A request -> ADK RunRequest |
| `.venv/.../google/adk/a2a/experimental.py` | @a2a_experimental decorator |
