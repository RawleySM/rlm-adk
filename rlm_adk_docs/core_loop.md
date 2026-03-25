<!-- validated: 2026-03-24 -->

# RLM-ADK Core Loop Reference

The core loop: an LLM reasoning agent writes Python code, which executes in a sandboxed REPL. That code can call `llm_query()` to spawn child agents, which themselves get their own REPL -- recursion to arbitrary depth. ADK's native tool-calling loop drives everything; the orchestrator does not manually iterate.

---

## 1. RLMOrchestratorAgent

**File:** `rlm_adk/orchestrator.py` (class at line 209)

`RLMOrchestratorAgent(BaseAgent)` is a Pydantic model. All dynamic attribute writes use `object.__setattr__()`.

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `reasoning_agent` | `LlmAgent` | required | Sub-agent that does reasoning + tool calls |
| `root_prompt` | `str \| None` | `None` | User's query |
| `repo_url` | `str \| None` | `None` | Optional repository URL for context |
| `persistent` | `bool` | `False` | Keep REPL across invocations |
| `worker_pool` | `Any` | `None` | `DispatchConfig` for child dispatch |
| `repl` | `Any` | `None` | Pre-configured `LocalREPL` (optional) |
| `depth` | `int` | `0` | Nesting depth (0 = root) |
| `fanout_idx` | `int` | `0` | Index within a batched dispatch |
| `output_schema` | `Any` | `None` | Pydantic schema for structured output |
| `instruction_router` | `Any` | `None` | `Callable[[int, int], str]` for dynamic skill instructions |
| `enabled_skills` | `tuple[str, ...]` | `()` | Activated skill names for catalog-driven injection |
| `parent_depth` | `int \| None` | `None` | Parent orchestrator's depth (lineage tracking) |
| `parent_fanout_idx` | `int \| None` | `None` | Parent orchestrator's fanout index (lineage tracking) |

The single entry point is `_run_async_impl(ctx) -> AsyncGenerator[Event, None]`.

---

## 2. Collapsed Iteration Pattern (Phase 5)

The orchestrator does NOT manually iterate. It wires tools onto the reasoning agent at runtime, then delegates entirely to ADK's native tool-calling loop.

### What `_run_async_impl` does (orchestrator.py, lines 242-658)

```
1. Create LocalREPL (or reuse self.repl)
2. Create dispatch closures -> (llm_query_async, llm_query_batched_async, post_dispatch_state_patch_fn)
   (passes instruction_router + fanout_idx for skill instruction routing)
2b. If worker_pool present: create _child_event_queue (asyncio.Queue), pass to create_dispatch_closures
3. Inject async query fns + skill helpers into REPL globals
4. Build REPLTool(repl, max_calls, post_dispatch_state_patch_fn, telemetry_finalizer, depth, fanout_idx)
5. Build SetModelResponseTool(output_schema)
5b. Inject _rlm_state snapshot into REPL globals before each code execution
    (from EXPOSED_STATE_KEYS, depth-scoped where applicable, plus runtime lineage:
     _rlm_depth, _rlm_fanout_idx, _rlm_agent_name)
6. Wire both onto reasoning_agent.tools via object.__setattr__
6b. If instruction_router: compute skill_instruction, write DYN_SKILL_INSTRUCTION to initial state,
    wire before_agent_callback on reasoning_agent to seed callback_context.state
7. Yield initial state delta Event (CURRENT_DEPTH, ITERATION_COUNT, REQUEST_ID)
8. Yield user Content Event with root_prompt
9. Delegate: async for event in reasoning_agent.run_async(ctx): yield event
   After each yielded event: drain _child_event_queue (if present), yielding child events
10. Final drain of _child_event_queue before _collect_completion
11. Extract final answer via _collect_completion (CompletionEnvelope)
12. Yield final Content Event with answer (or error)
13. Cleanup: clear tools, callbacks; destroy REPL if not persistent
```

ADK's loop (step 9) handles: model invocation, tool call detection, tool execution, retry on schema validation failure, and loop termination when `set_model_response` succeeds.

Transient HTTP errors (408, 429, 500-504) are retried with exponential backoff: `RLM_LLM_MAX_RETRIES` (default 3), `RLM_LLM_RETRY_DELAY` (default 5.0s).

---

## 3. REPLTool

**File:** `rlm_adk/tools/repl_tool.py` (class at line 50)

ADK `BaseTool` with `name="execute_code"`. The model calls it via function calling.

### Constructor

```
REPLTool(
    repl: LocalREPL,
    max_calls: int = 60,
    trace_holder: list | None = None,
    post_dispatch_state_patch_fn: Callable[[], dict] | None = None,
    telemetry_finalizer: Callable[[int, dict], None] | None = None,
    depth: int = 0,
    fanout_idx: int = 0,
    summarization_threshold: int = 5000,
)
```

### run_async return value

```python
{
    "stdout": str,       # Captured stdout
    "stderr": str,       # Captured stderr (includes exceptions)
    "variables": dict,   # JSON-serializable REPL locals
    "llm_calls_made": bool,  # True if code contained llm_query calls
    "call_number": int,      # Invocation count (1-indexed)
}
```

### Execution flow inside run_async (lines 120-355)

```
1. Persist submitted code metadata to tool_context.state
2. Save code as versioned artifact
3. Increment call count; if > max_calls, return error immediately
4. Build _rlm_state snapshot from EXPOSED_STATE_KEYS (depth-scoped where applicable)
   -> Inject runtime lineage metadata: _rlm_depth, _rlm_fanout_idx, _rlm_agent_name
   -> Write into repl.globals["_rlm_state"] (read-only, AR-CRIT-001 compliant)
5. Execute code via repl.execute_code() (sync, with timeout)
   -> llm_query() calls inside REPL code use the thread bridge
      (run_coroutine_threadsafe) to dispatch child orchestrators without
      AST rewriting — the sync callable blocks the REPL thread until the
      async child completes on the event loop
6. Call post_dispatch_state_patch_fn() to apply working-state patches into tool_context.state
7. Write LAST_REPL_RESULT summary dict to tool_context.state
8. If output > summarization_threshold, set skip_summarization = True
9. Filter locals to JSON-serializable values and return
```

### Call limit enforcement

When `call_count > max_calls`, returns `stderr: "REPL call limit reached. Submit your final answer now."` Default is 60 for REPLTool constructor, but the orchestrator passes `max_iterations` (default 30 from `RLM_MAX_ITERATIONS` env var).

On `CancelledError` or `Exception`: applies working-state patches, writes partial `LAST_REPL_RESULT`, returns error in `stderr`. The tool never raises -- always returns a dict so ADK can continue.

---

## 4. LocalREPL & Execution Engine

**Files:** `rlm_adk/repl/local_repl.py` and `rlm_adk/repl/ipython_executor.py`

Persistent Python namespace with safe builtins and async LM dispatch hooks. While `LocalREPL` manages the namespace and safe builtins, the actual execution of code is delegated to the `IPythonDebugExecutor` engine.

### IPythonDebugExecutor (`ipython_executor.py`)

This backend engine handles the complex mechanics of execution:
- **IPython Integration:** Supports rich IPython display outputs and magic commands (if enabled).
- **Sync Execution:** Manages the threading context for running sync code with timeouts. The thread bridge handles async dispatch transparently within sync execution.
- **Debugpy Arming:** Configures `debugpy` attachments when triggered via `REPLDebugConfig` for step-through debugging.

### LocalREPL Constructor

```python
LocalREPL(depth: int = 1, sync_timeout: float | None = None)
```

`sync_timeout` defaults to `RLM_REPL_SYNC_TIMEOUT` env var (default 30s).

### Public methods

| Method | Signature | Purpose |
|--------|-----------|---------|
| `execute_code` | `(code, trace?) -> REPLResult` | Sync execution with timeout via ThreadPoolExecutor |
| `set_llm_query_fns` | `(llm_query_fn, llm_query_batched_fn)` | Set sync bridge closures from thread_bridge.py |
| `cleanup` | `()` | Remove temp dir, clear globals/locals |

### Persistent namespace

- `self.globals`: Safe builtins, `__import__`, helper functions, LM query functions
- `self.locals`: User-defined variables (persist across execute_code calls)
- `self.temp_dir`: Working directory for code execution

### Safe builtins (line 83-173)

Allowed: `print`, `len`, `str`, `int`, `float`, `list`, `dict`, `set`, `tuple`, `range`, `enumerate`, `zip`, `map`, `filter`, `sorted`, `open`, `__import__`, `exec`, and all standard exception types.

Blocked (set to `None`): `eval`, `compile`, `input`, `globals`.

### Helper functions injected into globals

| Function | Purpose |
|----------|---------|
| `FINAL_VAR(var_name)` | Return a variable's value as a string; errors helpfully if not found |
| `SHOW_VARS()` | List all non-underscore variables with their types |
| `llm_query(prompt, ...)` | Sync bridge closure — blocks REPL thread, dispatches child via run_coroutine_threadsafe |
| `llm_query_batched(prompts, ...)` | Sync batched bridge closure — same mechanism, returns list of LLMResult |
| `probe_repo(source)` | Quick repo stats (files, chars, tokens) |
| `pack_repo(source)` | Entire repo as XML string |
| `shard_repo(source, max_bytes)` | Directory-aware repo chunking |
| `LLMResult` | The LLMResult class itself, for isinstance checks in REPL code |

### I/O isolation

Context manager replaces `sys.stdout`/`sys.stderr` under `_EXEC_LOCK`. A custom `open()` resolves relative paths against `temp_dir` (no `os.chdir()`).

---

## 5. Thread Bridge

**File:** `rlm_adk/repl/thread_bridge.py`

Bridges sync REPL code to async child dispatch without AST rewriting. The REPL runs user code synchronously in a worker thread; when that code calls `llm_query()`, the thread bridge uses `asyncio.run_coroutine_threadsafe()` to schedule the async dispatch coroutine on the main event loop and blocks the worker thread until the result is ready.

### How it works

1. The orchestrator creates sync bridge closures via `create_bridge_closures()` in `thread_bridge.py`.
2. These closures (`llm_query_fn`, `llm_query_batched_fn`) are injected into `repl.globals` as `llm_query` and `llm_query_batched`.
3. When REPL code calls `llm_query("sub-question")`, the bridge closure:
   a. Gets the running event loop via the captured loop reference.
   b. Submits `llm_query_async("sub-question")` to the loop with `run_coroutine_threadsafe()`.
   c. Blocks the REPL thread on `future.result(timeout=...)` until the child completes.
   d. Returns the `LLMResult` directly to the calling code.
4. No AST transformation is needed -- `llm_query()` is a real sync callable.

### Depth limit and timeout

The bridge enforces depth limits and per-call timeouts. If `depth + 1 >= max_depth`, it returns an error `LLMResult` immediately without spawning a child. Timeouts are configurable via `RLM_THREAD_BRIDGE_TIMEOUT`.

### Replaces

The thread bridge replaces the deleted `ast_rewriter.py` module. The old approach detected `llm_query()` calls via AST analysis, rewrote them to `await llm_query_async()`, promoted containing functions to async, and wrapped everything in `async def _repl_exec()`. The thread bridge eliminates this complexity entirely.

---

## 6. Types

**File:** `rlm_adk/types.py`

### ReasoningOutput (Pydantic model, line 15)

| Field | Type | Description |
|-------|------|-------------|
| `final_answer` | `str` | Complete answer to the query |
| `reasoning_summary` | `str` | Brief reasoning summary (default `""`) |

Used as the default `output_schema` on the reasoning agent. ADK injects `SetModelResponseTool` so the model emits validated JSON matching this schema.

### LLMResult (str subclass, line 95)

Backward-compatible string that carries metadata. Works in f-strings, concatenation, `isinstance(x, str)`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `error` | `bool` | Whether this result represents an error |
| `error_category` | `str \| None` | TIMEOUT, RATE_LIMIT, AUTH, SERVER, SCHEMA_VALIDATION_EXHAUSTED, etc. |
| `http_status` | `int \| None` | HTTP status code if applicable |
| `finish_reason` | `str \| None` | STOP, SAFETY, RECITATION, MAX_TOKENS |
| `input_tokens` | `int` | Input token count |
| `output_tokens` | `int` | Output token count |
| `thoughts_tokens` | `int` | Extended thinking token count |
| `model` | `str \| None` | Model identifier used |
| `wall_time_ms` | `float` | End-to-end latency |
| `visible_text` | `str \| None` | Model's visible output text |
| `thought_text` | `str \| None` | Model's thinking text |
| `parsed` | `dict \| None` | Validated structured output (when output_schema used) |

### REPLResult (dataclass, line 237)

| Field | Type | Description |
|-------|------|-------------|
| `stdout` | `str` | Captured standard output |
| `stderr` | `str` | Captured standard error |
| `locals` | `dict` | Snapshot of REPL locals after execution |
| `execution_time` | `float \| None` | Wall-clock seconds |
| `llm_calls` | `list[RLMChatCompletion]` | Child LLM calls made during execution |
| `trace` | `dict \| None` | Serialized REPLTrace (when tracing enabled) |

### RLMChatCompletion (dataclass, line 189)

Record of a single child LLM call. Key fields: `root_model`, `prompt`, `response`, `usage_summary: UsageSummary`, `execution_time`, `finish_reason`, `parsed_response`.

---

## 7. Complete Execution Sequence

```
User prompt
  |
  v
Runner.run_async(user_id, session_id, new_message)
  |
  v
RLMOrchestratorAgent._run_async_impl(ctx)
  |
  +-- Create LocalREPL
  +-- Create dispatch closures (llm_query_async, post_dispatch_state_patch_fn)
  +-- Create _child_event_queue (asyncio.Queue) if worker_pool present
  +-- Inject query fns + skill helpers into REPL
  +-- Build REPLTool + SetModelResponseTool
  +-- Wire tools onto reasoning_agent
  +-- Yield state delta Event (depth, iteration, request_id)
  +-- Yield user Content Event (root_prompt)
  |
  v
reasoning_agent.run_async(ctx)  [ADK native loop]
  |
  +---> Model invocation (Gemini API)
  |       |
  |       v
  |     Model returns functionCall: execute_code OR set_model_response
  |       |
  |       +-- execute_code:
  |       |     REPLTool.run_async(code=...)
  |       |       +-- Build _rlm_state snapshot -> repl.globals
  |       |       +-- Sync execution (llm_query uses thread bridge for child dispatch)
  |       |       +-- post_dispatch_state_patch_fn() -> tool_context.state
  |       |       +-- Return {stdout, stderr, variables}
  |       |     Drain _child_event_queue (yield child events)
  |       |     Loop back to model invocation
  |       |
  |       +-- set_model_response:
  |             Validate against ReasoningOutput schema
  |             If valid: store in output_key, exit loop
  |             If invalid: retry (up to 2 retries)
  |
  v
Final drain of _child_event_queue
  |
  v
Orchestrator extracts final answer via _collect_completion()
  +-- CompletionEnvelope normalizes the payload
  +-- Save artifact
  +-- Yield final Content Event with answer
  |
  v
Runner commits state, forwards events upstream
```

---

## 8. Recursion and Depth Tracking

### How child orchestrators spawn

When REPL code calls `llm_query("sub-question")`:

```
1. llm_query() bridge closure (from thread_bridge.py) executes in the REPL thread:
   a. Calls run_coroutine_threadsafe(llm_query_async("sub-question"), loop)
   b. Blocks the REPL thread on future.result(timeout=...)
2. llm_query_async() closure (from dispatch.py) executes on the event loop:
   a. Delegates to llm_query_batched_async(["sub-question"])
   b. Depth limit check: if depth + 1 >= max_depth, return error LLMResult
   c. create_child_orchestrator(model, depth=depth+1, prompt="sub-question")
   d. child._run_async_impl(ctx) runs (same flow as root, but:
      - Uses RLM_CHILD_STATIC_INSTRUCTION (condensed, no repomix)
      - max_iterations=10 (vs 30 for root)
      - thinking_budget=512 (vs 1024 for root)
      - Depth-suffixed state keys: "iteration_count@d1", "final_answer@d1"
      - include_repomix=False)
   e. Extract LLMResult from child's completion
3. LLMResult returned to parent REPL code as the return value
4. Parent code continues with the child's answer as a string
```

### Depth scoping

**File:** `rlm_adk/state.py` -- `depth_key(key, depth) -> str`

- `depth == 0`: returns `key` unchanged
- `depth > 0`: returns `f"{key}@d{depth}"`

This prevents state collisions when child orchestrators run within the same session. The `DEPTH_SCOPED_KEYS` set defines which keys require depth suffixes (iteration counts, final answers, submitted code metadata).

### Depth limits

| Parameter | Default | Env var |
|-----------|---------|---------|
| Max depth | 3 | `RLM_MAX_DEPTH` |
| Max concurrent children | 3 | `RLM_MAX_CONCURRENT_CHILDREN` |
| Child max iterations | 10 | (hardcoded in `create_child_orchestrator`) |

When `depth + 1 >= max_depth`, dispatch returns an error `LLMResult` immediately without spawning a child.

### Batched dispatch

`llm_query_batched(["q1", "q2", "q3"])` spawns children concurrently, limited by an `asyncio.Semaphore` (default 3). All children run in parallel and results are returned in prompt order.

---

## 9. Extension Points

### Adding custom skills

1. Define a `Skill` with `Frontmatter` in a new file under `rlm_adk/skills/`.
2. Append instructions to `static_instruction` in `create_reasoning_agent()` (`rlm_adk/agent.py`, line 205-208).
3. Inject callable functions into `repl.globals` in `orchestrator._run_async_impl` (line 267-271).
4. The model discovers the skill via instruction text and calls the injected functions in REPL code.

### Adding custom plugins

Create a `BasePlugin` subclass and wire it in `_default_plugins()` (`rlm_adk/agent.py`). Plugins are passed to `App(plugins=[...])` or `create_rlm_runner(plugins=[...])`. The default plugin list is: `DashboardAutoLaunchPlugin`, `StepModePlugin`, `ObservabilityPlugin` (always), plus conditionally: `SqliteTracingPlugin`, `LangfuseTracingPlugin`, `REPLTracingPlugin`, `GoogleCloudTracingPlugin`, `GoogleCloudAnalyticsPlugin`, `ContextWindowSnapshotPlugin`, and `LiteLLMCostTrackingPlugin`.

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RLM_ADK_MODEL` | `gemini-3.1-pro-preview` | Root model |
| `RLM_MAX_ITERATIONS` | `30` | Max tool calls per orchestrator |
| `RLM_MAX_DEPTH` | `3` | Max recursion depth |
| `RLM_MAX_CONCURRENT_CHILDREN` | `3` | Semaphore limit for batched dispatch |
| `RLM_LLM_MAX_RETRIES` | `3` | Transient error retries |
| `RLM_LLM_RETRY_DELAY` | `5.0` | Initial retry delay (seconds) |
| `RLM_REPL_SYNC_TIMEOUT` | `30` | Sync execution timeout (seconds) |
| `RLM_REPL_TRACE` | `0` | Trace level (0=off, 1=timing, 2=+memory) |
---

## 10. Agent Factories

**File:** `rlm_adk/agent.py`

| Factory | Returns | Purpose |
|---------|---------|---------|
| `create_reasoning_agent(model, ...)` | `LlmAgent` | Main reasoning sub-agent with callbacks, planner, and config. `output_schema` is intentionally NOT accepted -- the orchestrator wires `SetModelResponseTool(schema)` at runtime. |
| `create_rlm_orchestrator(model, ...)` | `RLMOrchestratorAgent` | Root orchestrator with reasoning agent + worker pool. Accepts `instruction_router`. |
| `create_child_orchestrator(model, depth, prompt, ...)` | `RLMOrchestratorAgent` | Child orchestrator with condensed instructions. Accepts `fanout_idx`, `instruction_router`, `parent_fanout_idx`. |
| `create_rlm_app(model, ...)` | `App` | Full ADK App with plugins. The module-level `app` symbol is what `adk run` discovers. |
| `create_rlm_runner(model, ...)` | `Runner` | App + session service + artifact service. Accepts `instruction_router`. For programmatic/test use — the ADK CLI (`adk run rlm_adk`) is the primary entrypoint and wires services via `services.py` instead. |

### Root vs child differences

| Property | Root | Child |
|----------|------|-------|
| Static instruction | `RLM_STATIC_INSTRUCTION` + repomix skill | `RLM_CHILD_STATIC_INSTRUCTION` (condensed) |
| `include_repomix` | `True` | `False` |
| `max_iterations` | 30 | 10 |
| `thinking_budget` | 1024 | 512 |
| `output_key` | `"reasoning_output"` | `"reasoning_output@d{depth}"` |

The module-level `app` symbol in `rlm_adk/agent.py` (line 544) is discovered by the ADK CLI (`adk run rlm_adk` and `adk web`). The CLI is the primary entrypoint — `services.py` auto-registers custom service factories so all plugins, sessions, and artifacts are wired with zero flags.

---

## ADK Gotchas

### Pydantic model constraints

ADK agents (`LlmAgent`, `BaseAgent` subclasses) are Pydantic models. Dynamic attribute writes must use `object.__setattr__()`:

```python
# WRONG -- Pydantic rejects unknown fields
agent.my_attr = "value"

# CORRECT
object.__setattr__(agent, "my_attr", "value")
```

This applies throughout the core loop: `orchestrator.py` wires `reasoning_agent.tools` at runtime, dispatch closures set `worker._pending_prompt`, `worker._result`, `worker._call_record`.

### include_contents='default' is required

```python
LlmAgent(
    ...
    include_contents="default",
    ...
)
```

This tells ADK to manage tool call/response history automatically. Without it, the reasoning agent would not see previous `execute_code` calls and their results in its context window, breaking multi-turn REPL interaction. Always set on `reasoning_agent`. Omitting it or setting it to `None` silently drops tool history from the prompt.

### State mutation (AR-CRIT-001)

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. The write appears to succeed at runtime but the Runner never sees it, so it is never persisted and does not appear in the event stream. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

---

## Recent Changes

> Append entries here when modifying source files documented by this branch. A stop hook (`ai_docs/scripts/check_doc_staleness.py`) will remind you.

<!-- All entries through 2026-03-22 incorporated into main body. -->

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
- **2026-03-25 16:30** — `rlm_adk/orchestrator.py`: GAP-A: passes `enabled_skills=self.enabled_skills` to `create_dispatch_closures()` so children inherit SkillToolset `[session: cd2d9e3f]`
- **2026-03-25 16:30** — `rlm_adk/dispatch.py`: GAP-A: added `enabled_skills` param to `create_dispatch_closures()` and `_run_child()`, propagated to `create_child_orchestrator()` `[session: cd2d9e3f]`
- **2026-03-25 16:30** — `rlm_adk/agent.py`: GAP-A: added `enabled_skills: tuple[str, ...] = ()` param to `create_child_orchestrator()` `[session: cd2d9e3f]`
- **2026-03-25 16:45** — `rlm_adk/orchestrator.py`: GAP-D: passes `repo_url=self.repo_url` to `create_dispatch_closures()` so children get dynamic instruction resolution `[session: cd2d9e3f]`
- **2026-03-25 16:45** — `rlm_adk/dispatch.py`: GAP-D: added `repo_url` param to `create_dispatch_closures()` and `_run_child()` `[session: cd2d9e3f]`
- **2026-03-25 16:45** — `rlm_adk/agent.py`: GAP-D: added `repo_url: str | None = None` param to `create_child_orchestrator()` `[session: cd2d9e3f]`
- **2026-03-25 16:55** — `rlm_adk/orchestrator.py`: GAP-D reviewer fix: added comment documenting intentional non-propagation of user_ctx_manifest to children `[session: cd2d9e3f]`
