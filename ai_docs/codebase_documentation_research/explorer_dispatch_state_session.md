# RLM-ADK Dispatch, State Management & Session Layer

## RLM-ADK Dispatch System, State Management, and Session/Service Layer - Complete Exploration

Based on my thorough analysis of the codebase, here are the comprehensive findings:

### 1. DISPATCH SYSTEM (rlm_adk/dispatch.py)

**Core Architecture:**
- **DispatchConfig Class** (formerly WorkerPool): Holds model configuration (default_model, other_model, pool_size)
  - `ensure_initialized()`: No-op for backward compatibility
  - Backward-compatible alias: `WorkerPool = DispatchConfig`

**create_dispatch_closures() Function - 3-Tuple Return Pattern:**
```
Returns: (llm_query_async, llm_query_batched_async, flush_fn)
```

- **llm_query_async(prompt, model=None, output_schema=None)**: Single query dispatch
  - Delegates to `llm_query_batched_async([prompt], ...)`
  - Records trace entries when trace_sink provided
  - Returns LLMResult with wall_time_ms, input/output tokens, finish_reason

- **llm_query_batched_async(prompts, model=None, output_schema=None, _record_trace_entries=True)**: Batch dispatch
  - Spawns K children concurrently via `asyncio.gather(*tasks)`
  - Limited by `_child_semaphore` (max_concurrent from RLM_MAX_CONCURRENT_CHILDREN env var, default 3)
  - Accumulates latencies, error counts, structured output failures
  - Returns list[LLMResult]

- **flush_fn()**: Snapshot & Reset Pattern (AR-CRIT-001)
  - Returns dict with accumulated state keys
  - Resets all local accumulators to initial state
  - Called by REPLTool after each code execution

**Local Accumulators (AR-CRIT-001 Pattern):**
- `_acc_child_dispatches`: Count of total child invocations
- `_acc_child_batch_dispatches`: Count of batch operations (k > 1)
- `_acc_child_latencies`: list[float] of dispatch elapsed_ms
- `_acc_child_error_counts`: dict[error_category] → count
- `_acc_child_summaries`: dict[obs_key] → full summary dict
- `_acc_structured_output_failures`: Count of schema validation failures

**Why Local Accumulators?**
- `ctx.session.state` mutations in dispatch closures bypass ADK event tracking
- Local accumulators capture in-closure scope, then `flush_fn()` atomically snapshots to `tool_context.state`
- Prevents dirty reads in concurrent REPL execution
- Each iteration resets accumulators; REPLTool calls flush_fn after execution

**Child Orchestrator Lifecycle (_run_child):**
1. Depth check: if depth+1 >= max_depth, return DEPTH_LIMIT error
2. Create child via `create_child_orchestrator(model, depth+1, prompt, worker_pool, output_schema)`
3. Run async: `async for event in child.run_async(ctx)` → collect state_deltas into `_child_state`
4. Call `_read_child_completion(child, child_depth, _child_state, shared_state)` to normalize completion
5. Build `LLMResult` with completion data (text, error_category, tokens, finish_reason, parsed output)
6. Record `_build_call_log()` for REPL observability (RLMChatCompletion record)
7. Write per-child summary: `obs:child_summary@d{depth}f{fanout_idx}`
8. Clean up child REPL if not persistent

**Per-Child Observability Summary Structure:**
- model, depth, fanout_idx, elapsed_ms
- error, error_category, error_message
- input_tokens, output_tokens, thought_tokens, finish_reason
- prompt_preview, result_preview (500 char truncation)
- visible_output_preview, thought_preview, raw_output_preview
- parsed_output (only if success and is dict)
- reasoning_retry (count, delay_ms, used)
- nested_dispatch (count, batch_dispatches, error_counts, structured_output_failures)
- structured_output (expected, schema_name, attempts, retry_count, outcome, validated_result, events)

**Observability Keys Written to State by flush_fn():**
- `OBS_CHILD_DISPATCH_COUNT`: Total children spawned
- `OBS_CHILD_DISPATCH_LATENCY_MS`: list[float] of per-batch latencies
- `OBS_CHILD_TOTAL_BATCH_DISPATCHES`: Count of multi-child batches
- `OBS_CHILD_ERROR_COUNTS`: dict of error categories
- `OBS_STRUCTURED_OUTPUT_FAILURES`: Count of schema validation exhaustion
- `OBS_BUG13_SUPPRESS_COUNT`: BUG-13 monkey-patch invocations
- Per-child summaries: `obs:child_summary@d{depth}f{fanout_idx}` (full dict)

**Depth & Max Depth:**
- Default max_depth=3; overridden by RLM_MAX_DEPTH env var
- Checked at start of `_run_child()`: if depth+1 >= max_depth, returns error

---

### 2. STATE MANAGEMENT (rlm_adk/state.py)

**State Key Categories:**

**Flow Control Keys (session-scoped, depth-scoped variants exist):**
- `CURRENT_DEPTH`: Current nesting level (0 = root)
- `ITERATION_COUNT`: Number of REPL tool calls per depth
- `SHOULD_STOP`: Boolean flag to halt reasoning loop
- `POLICY_VIOLATION`: Security/policy event (from plugins)
- `APP_MAX_ITERATIONS`: Maximum tool calls (app-scoped default)
- `APP_MAX_DEPTH`: Maximum depth (app-scoped default)

**REPL Execution Keys (depth-scoped):**
- `MESSAGE_HISTORY`: Conversation history per depth
- `LAST_REPL_RESULT`: Result of last code execution
- `FINAL_ANSWER`: Final answer text for the depth
- `REASONING_SUMMARY`: Brief summary from LLM
- `REASONING_FINISH_REASON`: "STOP", "MAX_TOKENS", "SAFETY", "RECITATION", "UNKNOWN"
- `REASONING_VISIBLE_OUTPUT_TEXT`: Non-thinking model output
- `REASONING_THOUGHT_TEXT`: Hidden thinking/reasoning text
- `REASONING_THOUGHT_TOKENS`: Token count for thinking
- `REASONING_RAW_OUTPUT`: Raw model response (dict or string)
- `REASONING_PARSED_OUTPUT`: Structured output when schema provided (dict)

**Token Accounting Keys (depth-scoped):**
- `REASONING_INPUT_TOKENS`: Input tokens to model
- `REASONING_OUTPUT_TOKENS`: Output tokens from model
- `REASONING_PROMPT_CHARS`: Total prompt text characters
- `REASONING_SYSTEM_CHARS`: System instruction characters
- `REASONING_HISTORY_MSG_COUNT`: Message history length
- `REASONING_CONTENT_COUNT`: Content blocks in request
- `CONTEXT_WINDOW_SNAPSHOT`: Context usage state

**Observability Keys (session-scoped, NOT depth-scoped):**
- `OBS_TOTAL_INPUT_TOKENS`: Cumulative across all depths
- `OBS_TOTAL_OUTPUT_TOKENS`: Cumulative across all depths
- `OBS_TOTAL_CALLS`: Total model invocations
- `OBS_TOOL_INVOCATION_SUMMARY`: dict of tool → count
- `OBS_TOTAL_EXECUTION_TIME`: Wall time ms
- `OBS_PER_ITERATION_TOKEN_BREAKDOWN`: Per-iteration accounting
- `OBS_FINISH_SAFETY_COUNT`, `OBS_FINISH_RECITATION_COUNT`, `OBS_FINISH_MAX_TOKENS_COUNT`: Finish reason counts
- `OBS_STRUCTURED_OUTPUT_FAILURES`: Schema validation exhaustion count
- `OBS_REWRITE_COUNT`: AST rewrites for llm_query detection
- `OBS_REWRITE_FAILURE_COUNT`: Failed rewrites
- `OBS_REASONING_RETRY_COUNT`: LLM transient retry count
- `OBS_REASONING_RETRY_DELAY_MS`: Total retry backoff delay
- `OBS_BUG13_SUPPRESS_COUNT`: BUG-13 monkey-patch invocations
- `OBS_CHILD_DISPATCH_COUNT`: Total child orchestrators spawned
- `OBS_CHILD_ERROR_COUNTS`: dict[category] of child errors
- `OBS_CHILD_DISPATCH_LATENCY_MS`: list of per-batch latencies
- `OBS_CHILD_TOTAL_BATCH_DISPATCHES`: Count of batch operations

**API/Request Keys:**
- `REQUEST_ID`: UUID assigned at invocation start (root orchestrator)
- `IDEMPOTENCY_KEY`: Optional user-provided idempotency token
- `USER_LAST_SUCCESSFUL_CALL_ID`: Tracking for user sessions

**Context Keys:**
- `ROOT_PROMPT`: Initial user query
- `REPO_URL`: Repository URL for context
- `DYN_ROOT_PROMPT`: Dynamic instruction state var (ADK resolves)
- `DYN_REPO_URL`: Dynamic instruction state var (ADK resolves)

**REPL Submitted Code Keys (depth-scoped):**
- `REPL_SUBMITTED_CODE`: Full code text
- `REPL_SUBMITTED_CODE_CHARS`: Character count
- `REPL_SUBMITTED_CODE_HASH`: SHA256 hash
- `REPL_SUBMITTED_CODE_PREVIEW`: First 500 chars

**Caching Keys:**
- `CACHE_STORE`: Persistent cache dict
- `CACHE_HIT_COUNT`, `CACHE_MISS_COUNT`, `CACHE_LAST_HIT_KEY`: Cache metrics

**Test Hook Keys (cb_ prefix, session-scoped):**
- `CB_REASONING_CONTEXT`: Reasoning callback context (test-only)
- `CB_WORKER_CONTEXT`: Worker callback context (test-only)
- `CB_ORCHESTRATOR_CONTEXT`: Orchestrator callback context (test-only)
- `CB_TOOL_CONTEXT`: Tool execution context (test-only)

**Artifact Tracking Keys:**
- `ARTIFACT_SAVE_COUNT`, `ARTIFACT_LOAD_COUNT`: Operation counts
- `ARTIFACT_TOTAL_BYTES_SAVED`: Size tracking
- `ARTIFACT_LAST_SAVED_FILENAME`, `ARTIFACT_LAST_SAVED_VERSION`: Last operation metadata

**Depth Scoping:**

```python
DEPTH_SCOPED_KEYS = {
    MESSAGE_HISTORY, ITERATION_COUNT,
    FINAL_ANSWER, LAST_REPL_RESULT, SHOULD_STOP,
    REASONING_INPUT_TOKENS, REASONING_OUTPUT_TOKENS,
    REASONING_SUMMARY, REASONING_FINISH_REASON,
    REASONING_VISIBLE_OUTPUT_TEXT, REASONING_THOUGHT_TEXT,
    REASONING_THOUGHT_TOKENS, REASONING_RAW_OUTPUT,
    REASONING_PARSED_OUTPUT,
    REPL_SUBMITTED_CODE, REPL_SUBMITTED_CODE_PREVIEW,
    REPL_SUBMITTED_CODE_HASH, REPL_SUBMITTED_CODE_CHARS,
}
```

- `depth_key(key, depth)`: Returns key unchanged at depth=0, or `{key}@d{depth}` at depth > 0
- Ensures independent state per recursive agent level
- Global observability keys are NOT depth-scoped (cumulative)

---

### 3. SESSION SERVICE (rlm_adk/agent.py)

**Session Service Hierarchy:**
- `BaseSessionService`: ADK base class (abstract)
- `SqliteSessionService`: Concrete implementation backed by SQLite
  - Persists state across invocations in `.adk/session.db`
  - Supports rewind/replay via version tracking

**Default Session Service Creation (_default_session_service):**
```python
def _default_session_service(db_path: str | None = None) -> BaseSessionService:
    resolved_path = db_path or os.getenv("RLM_SESSION_DB", _DEFAULT_DB_PATH)
    # _DEFAULT_DB_PATH = str(_project_root() / ".adk" / "session.db")
    
    db_dir = Path(resolved_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    
    # Apply WAL mode pragmas for concurrent reads
    conn = sqlite3.connect(resolved_path)
    conn.executescript(_SQLITE_STARTUP_PRAGMAS)  # WAL, NORMAL sync, mmap, etc.
    conn.close()
    
    return SqliteSessionService(db_path=resolved_path)
```

**SQLite Configuration (_SQLITE_STARTUP_PRAGMAS):**
- `PRAGMA journal_mode = WAL`: Write-Ahead Logging for concurrent reads
- `PRAGMA synchronous = NORMAL`: Balanced durability/performance
- `PRAGMA cache_size = -64000`: 64MB cache
- `PRAGMA temp_store = MEMORY`: In-memory temp tables
- `PRAGMA mmap_size = 268435456`: Memory-mapped I/O (256MB)
- `PRAGMA wal_autocheckpoint = 1000`: Checkpoint frequency

**InvocationContext (ADK):**
- Provided by ADK at runtime via `agent.run_async(ctx)`
- Contains:
  - `ctx.invocation_id`: UUID for this invocation
  - `ctx.session`: Session instance with `state` dict
  - `ctx.session.state`: Dict[str, Any] for session-scoped state
  - `ctx._invocation_context.agent`: Current agent (private API, used by callbacks)

**State Access Patterns:**

Within tools (REPLTool):
```python
async def run_async(self, *, args, tool_context: ToolContext):
    tool_context.state[key] = value  # Correct - event tracked
```

Within callbacks (reasoning_before_model, etc.):
```python
def reasoning_before_model(callback_context: CallbackContext, ...):
    agent = callback_context._invocation_context.agent  # Get agent from private API
    # No direct state write; use EventActions in events
```

Within events (orchestrator):
```python
yield Event(
    invocation_id=ctx.invocation_id,
    author=self.name,
    actions=EventActions(state_delta={key: value}),  # Correct - event driven
)
```

**NEVER in dispatch closures:**
```python
# WRONG - bypasses event tracking (AR-CRIT-001)
ctx.session.state[key] = value
```

---

### 4. AGENT FACTORY (rlm_adk/agent.py)

**create_reasoning_agent():**
```python
def create_reasoning_agent(
    model: str,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    thinking_budget: int = 1024,
    retry_config: dict[str, Any] | None = None,
    *,
    tools: list | None = None,
    output_schema: type | None = None,
    include_repomix: bool = True,
    name: str = "reasoning_agent",
    output_key: str = "reasoning_output",
) -> LlmAgent:
```
- Returns configured `LlmAgent` (Google ADK LlmAgent, not RLMOrchestratorAgent)
- Static instruction: Placed in `system_instruction` (no template processing, safe for code)
- Dynamic instruction: Template with `{var?}` placeholders, resolved by ADK
- Thinking budget: Passed to BuiltInPlanner → ThinkingConfig
- Repomix: Appends skill instruction block to static_instruction (parent only, not children)
- `include_contents='default'`: ADK manages tool call/response history
- `output_schema`: Optional Pydantic BaseModel for structured output validation

**create_rlm_orchestrator():**
```python
def create_rlm_orchestrator(
    model: str,
    root_prompt: str | None = None,
    persistent: bool = False,
    worker_pool: Any = None,
    repl: Any = None,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    repo_url: str | None = None,
    thinking_budget: int = 1024,
    retry_config: dict[str, Any] | None = None,
) -> RLMOrchestratorAgent:
```
- Creates reasoning_agent via `create_reasoning_agent()`
- Default WorkerPool if not provided
- Returns RLMOrchestratorAgent (custom BaseAgent that delegates to reasoning_agent)
- Root prompt stored in orchestrator, yielded as initial user Content event

**create_child_orchestrator():**
```python
def create_child_orchestrator(
    model: str,
    depth: int,
    prompt: str,
    worker_pool: WorkerPool | None = None,
    max_iterations: int = 10,
    thinking_budget: int = 512,
    output_schema: type | None = None,
) -> RLMOrchestratorAgent:
```
- Used by dispatch closures to spawn recursive agents
- Uses `RLM_CHILD_STATIC_INSTRUCTION` (no repomix, no repo docs)
- Depth-suffixed output_key: `reasoning_output@d{depth}`
- Depth-suffixed agent name: `child_orchestrator_d{depth}`
- Lower thinking budget (512 vs 1024) for cost control
- Sets `depth` and `output_schema` on orchestrator instance

**create_rlm_app():**
```python
def create_rlm_app(
    model: str,
    root_prompt: str | None = None,
    persistent: bool = False,
    worker_pool: Any = None,
    repl: Any = None,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    repo_url: str | None = None,
    plugins: list[BasePlugin] | None = None,
    thinking_budget: int = 1024,
    langfuse: bool = False,
    sqlite_tracing: bool = True,
) -> App:
```
- Creates orchestrator via `create_rlm_orchestrator()`
- Wires plugins via `_default_plugins()` if not provided
- Returns ADK App with root_agent=orchestrator

**create_rlm_runner():**
```python
def create_rlm_runner(
    model: str,
    root_prompt: str | None = None,
    persistent: bool = False,
    worker_pool: Any = None,
    repl: Any = None,
    static_instruction: str = RLM_STATIC_INSTRUCTION,
    dynamic_instruction: str = RLM_DYNAMIC_INSTRUCTION,
    repo_url: str | None = None,
    plugins: list[BasePlugin] | None = None,
    thinking_budget: int = 1024,
    artifact_service: BaseArtifactService | None = None,
    session_service: BaseSessionService | None = None,
    langfuse: bool = False,
    sqlite_tracing: bool = True,
) -> Runner:
```
- Full entry point: App + plugins + services
- Creates app via `create_rlm_app()`
- Resolves session service: explicit > `_default_session_service()`
- Resolves artifact service: explicit > `FileArtifactService(.adk/artifacts)`
- Returns ADK Runner (drives event loop, manages state persistence)

**Model Configuration:**
- `_root_agent_model()`: Returns `os.getenv("RLM_ADK_MODEL", "gemini-3.1-pro-preview")`
- Applied to module-level `app` and `root_agent` symbols
- Per-agent: `create_reasoning_agent(model=...)`
- Per-child: `create_child_orchestrator(model=...)`

**HTTP Retry Configuration:**
- `_DEFAULT_RETRY_OPTIONS`: `HttpRetryOptions(attempts=3, initial_delay=1.0, max_delay=60.0, exp_base=2.0)`
- `_build_generate_content_config(retry_config)`: Builds GenerateContentConfig with HTTP options
- Per-agent: `create_reasoning_agent(retry_config=...)`
- Timeout: `RLM_REASONING_HTTP_TIMEOUT` env var (default 300000ms = 5min)

**Default Plugins (_default_plugins):**
- Always included: `ObservabilityPlugin` (verbose if RLM_ADK_DEBUG=1)
- Optional:
  - SqliteTracingPlugin (enabled by default, disable via `sqlite_tracing=False`)
  - LangfuseTracingPlugin (opt-in via `RLM_ADK_LANGFUSE=1` or `langfuse=True`)
  - REPLTracingPlugin (opt-in via `RLM_REPL_TRACE=1|2`)
  - GoogleCloudTracingPlugin, GoogleCloudAnalyticsPlugin (opt-in via `RLM_ADK_CLOUD_OBS=1`)
  - ContextWindowSnapshotPlugin (opt-in via `RLM_CONTEXT_SNAPSHOTS=1`)

---

### 5. CONFIGURATION (pyproject.toml & Environment)

**Project Metadata:**
- Name: `rlms`
- Version: `0.1.0`
- Python: >=3.12
- Dependencies: google-adk>=1.2.0, google-genai>=1.56.0, langfuse>=3.14.0, etc.

**Key Environment Variables:**
- `RLM_ADK_MODEL`: Model to use (default `gemini-3.1-pro-preview`)
- `RLM_SESSION_DB`: SQLite database path (default `.adk/session.db`)
- `RLM_MAX_DEPTH`: Max recursion depth (default 3)
- `RLM_MAX_ITERATIONS`: Max REPL tool calls per depth (default 30)
- `RLM_MAX_CONCURRENT_CHILDREN`: Concurrency limit for batched dispatch (default 3)
- `RLM_MAX_DEPTH`: Maximum nesting depth for child orchestrators
- `RLM_LLM_MAX_RETRIES`: Transient error retry count (default 3)
- `RLM_LLM_RETRY_DELAY`: Base retry delay in seconds (default 5.0)
- `RLM_REASONING_HTTP_TIMEOUT`: HTTP timeout ms (default 300000)
- `RLM_ADK_DEBUG`: Enable verbose logging on ObservabilityPlugin (1/true/yes)
- `RLM_ADK_SQLITE_TRACING`: Enable SqliteTracingPlugin (1/true/yes)
- `RLM_ADK_LANGFUSE`: Enable LangfuseTracingPlugin (1/true/yes)
- `RLM_REPL_TRACE`: Enable REPLTracingPlugin level (0=off, 1=timing+snapshots, 2=+memory)
- `RLM_ADK_CLOUD_OBS`: Enable Google Cloud observability plugins (1/true/yes)
- `RLM_CONTEXT_SNAPSHOTS`: Enable context window snapshot plugin (1/true/yes)
- `.env` file loading: Loaded from project root, no override of existing vars

**Test Configuration (pytest):**
- `asyncio_mode = "auto"`: Auto-detect async fixtures
- Default marker: `-m "provider_fake_contract and not agent_challenge"`
- Default marker filters out ~942 non-default tests, running only ~28 provider-fake contract tests
- Override with `-m ""` to run all tests

**Default Paths:**
- Session DB: `.adk/session.db`
- Artifacts: `.adk/artifacts/`
- Traces: `.adk/traces.db`

---

### 6. CRITICAL INVARIANTS (AR-CRIT-001)

**State Mutation Rules:**
1. **Never** in dispatch closures: `ctx.session.state[key] = value`
   - Bypasses ADK event tracking
   - Solution: Use local accumulators + `flush_fn()`

2. **Always** in tools: `tool_context.state[key] = value`
   - Tracked by ADK, committed by Runner

3. **Always** in orchestrator: `yield Event(actions=EventActions(state_delta={...}))`
   - Event-driven, idempotent, trackable

4. **Always in callbacks**: Avoid direct state writes; use events

**Depth Scoping:**
- Keys in `DEPTH_SCOPED_KEYS` must use `depth_key(key, depth)` when accessed
- Global observability keys are cumulative, NOT depth-scoped
- Prevents state collision in recursive agents

**Local Accumulator Pattern:**
```python
_acc_counter = 0  # Closure-local
def handler():
    nonlocal _acc_counter
    _acc_counter += 1

def flush_fn():
    nonlocal _acc_counter
    result = {"count": _acc_counter}
    _acc_counter = 0
    return result
```

**Session Persistence:**
- SqliteSessionService persists state between invocations
- State survives process restarts (disk-backed)
- Supports rewind/replay via session version tracking

---

### 7. DATA FLOW BETWEEN COMPONENTS

```
User Request → Runner.run_async()
  → creates InvocationContext(session, invocation_id)
  → calls orchestrator.run_async(ctx)
    → yields initial state event + prompt event
    → wires REPLTool, SetModelResponseTool onto reasoning_agent
    → wires reasoning callbacks (before_model, after_model)
    → delegates reasoning_agent.run_async(ctx)
      → ADK loop: LlmRequest → Gemini API → LlmResponse
      → before_model callback: extracts tokens, state, instruction
      → after_model callback: records token accounting
      → tool calling: REPLTool.run_async() OR SetModelResponseTool
        → REPLTool:
          - Executes code in LocalREPL
          - Detects llm_query via AST (has_llm_calls)
          - Rewrites to async (rewrite_for_async)
          - Calls dispatch closures (llm_query_async/batched_async)
            → spawn child orchestrator at depth+1
            → each child runs full orchestrator loop
            → collect state_deltas, completion data
            → build LLMResult with metadata
            → accumulate in local closure state
          - Calls flush_fn() to snapshot accumulators → tool_context.state
          - Returns result dict to ADK loop
      → yields events from reasoning_agent
    → extracts final_answer from output_key
    → yields final state event + content event
  → Runner commits state_delta to SqliteSessionService
  → Runner forwards events upstream
```

---

### 8. TESTING & PROVIDER-FAKE

**Default Test Run:**
- 28 provider-fake contract tests (~22s)
- Marker filter: `provider_fake_contract and not agent_challenge`

**Full Suite:**
- 970+ tests (~3min)
- Run with: `-m ""`

**Replay Fixture:**
- `.venv/bin/adk run --replay tests_rlm_adk/replay/recursive_ping.json rlm_adk`
- Fixtures: `tests_rlm_adk/fixtures/provider_fake/*.json`
- Server: `tests_rlm_adk/provider_fake/server.py` (FakeGeminiServer, aiohttp)
- Structural matcher: `tests_rlm_adk/provider_fake/fixtures.py`

---

This completes the comprehensive exploration of RLM-ADK's dispatch system, state management, and session/service layer. The architecture emphasizes:

1. **Event-driven state mutation** to maintain ADK traceability
2. **Local accumulators with flush_fn** for dispatch closure isolation
3. **Depth-scoped keys** for recursive agent independence
4. **SqliteSessionService** for persistent, resumable sessions
5. **Closed-loop factory pattern** for agent creation and configuration
