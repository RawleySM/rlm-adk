# RLM ADK Module Reference

Generated from source code reading. All signatures and behaviours are based
directly on the implementation files listed under each section.

---

## Table of Contents

1. [Core](#1-core)
   - [rlm_adk (package root)](#rlm_adk-package-root)
   - [rlm_adk/agent.py](#rlm_adkagentpy)
   - [rlm_adk/orchestrator.py](#rlm_adkorchestratpy)
   - [rlm_adk/dispatch.py](#rlm_adkdispatchpy)
2. [REPL](#2-repl)
   - [rlm_adk/repl/local_repl.py](#rlm_adkrepllocal_replpy)
   - [rlm_adk/repl/ast_rewriter.py](#rlm_adkreplast_rewriterpy)
   - [rlm_adk/tools/repl_tool.py](#rlm_adktoolsrepl_toolpy)
   - [rlm_adk/repl/trace.py](#rlm_adkrepltracepy)
3. [Callbacks](#3-callbacks)
   - [rlm_adk/callbacks/__init__.py](#rlm_adkcallbacksinitpy)
   - [rlm_adk/callbacks/reasoning.py](#rlm_adkcallbacksreasoningpy)
   - [rlm_adk/callbacks/worker.py](#rlm_adkcallbacksworkerpy)
   - [rlm_adk/callbacks/worker_retry.py](#rlm_adkcallbacksworker_retrypy)
4. [Plugins](#4-plugins)
   - [rlm_adk/plugins/__init__.py](#rlm_adkpluginsinitpy)
   - [rlm_adk/plugins/observability.py](#rlm_adkpluginsobservabilitypy)
   - [rlm_adk/plugins/repl_tracing.py](#rlm_adkpluginsrepl_tracingpy)
   - [rlm_adk/plugins/langfuse_tracing.py](#rlm_adkpluginslangfuse_tracingpy)
   - [rlm_adk/plugins/cache.py](#rlm_adkpluginscachepy)
   - [rlm_adk/plugins/debug_logging.py](#rlm_adkpluginsdebug_loggingpy)
   - [rlm_adk/plugins/sqlite_tracing.py](#rlm_adkpluginssqlite_tracingpy)
5. [Types and State](#5-types-and-state)
   - [rlm_adk/types.py](#rlm_adktypespy)
   - [rlm_adk/state.py](#rlm_adkstatepy)
6. [Utilities](#6-utilities)
   - [rlm_adk/utils/parsing.py](#rlm_adkutilsparsingpy)
   - [rlm_adk/utils/prompts.py](#rlm_adkutilspromptspy)

---

## 1. Core

### `rlm_adk` (package root)

**File:** `rlm_adk/__init__.py`

Package entry point. Re-exports the five public symbols from `rlm_adk.agent`
so that callers can import directly from the top-level package.

**Public exports:**

```python
from rlm_adk import (
    app,                    # ADK App instance (CLI entry point)
    create_rlm_runner,      # -> Runner
    create_rlm_app,         # -> App
    create_rlm_orchestrator, # -> RLMOrchestratorAgent
    create_reasoning_agent, # -> LlmAgent
)
```

`app` is the module-level `App` instance that the ADK CLI (`adk run rlm_adk`,
`adk web`) discovers automatically. It is created at import time using
`_root_agent_model()` which reads the `RLM_ADK_MODEL` environment variable
(default: `"gemini-3.1-pro-preview"`).

---

### `rlm_adk/agent.py`

**Purpose:** Factory module that wires all components into runnable ADK
objects. The recommended programmatic entry point is `create_rlm_runner()`.

---

#### `create_reasoning_agent`

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
) -> LlmAgent
```

Creates the `reasoning_agent` (`LlmAgent`, name `"reasoning_agent"`). This is
the primary LLM that executes the RLM iteration loop at depth=0.

Key configuration choices made inside this factory:

- `include_contents="default"` — ADK manages the full tool call/response
  history in `contents`.
- `disallow_transfer_to_parent=True`, `disallow_transfer_to_peers=True` — the
  agent cannot hand off execution.
- `output_key="reasoning_output"` — ADK writes the final model text response
  to this session state key.
- `planner=BuiltInPlanner(ThinkingConfig(...))` when `thinking_budget > 0`;
  set `thinking_budget=0` to disable built-in thinking.
- `before_model_callback=reasoning_before_model`,
  `after_model_callback=reasoning_after_model` — token accounting callbacks
  wired unconditionally.
- `static_instruction` is passed as `LlmAgent.static_instruction` (no
  template processing; raw curly braces in code examples are safe).
- `dynamic_instruction` is passed as `LlmAgent.instruction` (ADK resolves
  `{var?}` placeholders from session state at runtime).
- The repomix skill instruction block is appended to `static_instruction`
  via `rlm_adk.skills.repomix_skill.build_skill_instruction_block()`.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `str` | required | Gemini model identifier |
| `static_instruction` | `str` | `RLM_STATIC_INSTRUCTION` | Stable system prompt, no template processing |
| `dynamic_instruction` | `str` | `RLM_DYNAMIC_INSTRUCTION` | Template string; `{repo_url?}`, `{root_prompt?}` placeholders |
| `thinking_budget` | `int` | `1024` | Token budget for built-in planner; `0` disables it |
| `retry_config` | `dict \| None` | `None` | Keys map to `HttpRetryOptions` fields; `None` uses 3-attempt exponential backoff default; `{}` uses SDK built-ins only |
| `tools` | `list \| None` | `None` | Tools to attach; orchestrator overwrites at runtime |
| `output_schema` | `type \| None` | `None` | Pydantic `BaseModel` subclass for structured output |

**Returns:** `google.adk.agents.LlmAgent`

---

#### `create_rlm_orchestrator`

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
) -> RLMOrchestratorAgent
```

Creates the `RLMOrchestratorAgent` (name `"rlm_orchestrator"`). Internally
calls `create_reasoning_agent` and creates a default `WorkerPool` if none is
provided.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `str` | required | Model for both orchestrator and default worker pool |
| `root_prompt` | `str \| None` | `None` | Initial user prompt; stored to session state as `ROOT_PROMPT` |
| `persistent` | `bool` | `False` | If `True`, REPL is not cleaned up between invocations |
| `worker_pool` | `Any` | `None` | Pre-built `WorkerPool`; creates default if `None` |
| `repl` | `Any` | `None` | Pre-built `LocalREPL`; creates fresh `LocalREPL(depth=1)` if `None` |
| `repo_url` | `str \| None` | `None` | Stored to `REPO_URL` / `DYN_REPO_URL` state at run start |
| `thinking_budget` | `int` | `1024` | Forwarded to `create_reasoning_agent` |
| `retry_config` | `dict \| None` | `None` | Forwarded to `create_reasoning_agent` |

**Returns:** `RLMOrchestratorAgent`

---

#### `create_rlm_app`

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
    debug: bool = True,
    thinking_budget: int = 1024,
    langfuse: bool = False,
    sqlite_tracing: bool = True,
) -> App
```

Creates the full ADK `App` (name `"rlm_adk"`) with plugins wired in.
When `plugins` is `None`, calls the internal `_default_plugins()` which
assembles: `ObservabilityPlugin` (always), `DebugLoggingPlugin` (when
`debug=True` or `RLM_ADK_DEBUG=1`), `SqliteTracingPlugin` (when
`sqlite_tracing=True` or `RLM_ADK_SQLITE_TRACING=1`),
`LangfuseTracingPlugin` (when `langfuse=True` or `RLM_ADK_LANGFUSE=1`),
`REPLTracingPlugin` (when `RLM_REPL_TRACE > 0`),
`ContextWindowSnapshotPlugin` (when `RLM_CONTEXT_SNAPSHOTS=1`).

**Returns:** `google.adk.apps.app.App`

---

#### `create_rlm_runner`

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
    debug: bool = True,
    thinking_budget: int = 1024,
    artifact_service: BaseArtifactService | None = None,
    session_service: BaseSessionService | None = None,
    langfuse: bool = False,
    sqlite_tracing: bool = True,
) -> Runner
```

The recommended programmatic entry point. Returns a fully configured ADK
`Runner` with:

- The `App` from `create_rlm_app` (orchestrator + plugins).
- `SqliteSessionService` backed by `.adk/session.db` with WAL mode enabled
  (default), or caller-provided `session_service`.
- `FileArtifactService` rooted at `.adk/artifacts/` (default), or
  caller-provided `artifact_service`.

**Usage pattern:**

```python
runner = create_rlm_runner(model="gemini-2.5-flash")
session = await runner.session_service.create_session(
    app_name="rlm_adk", user_id="user",
)
async for event in runner.run_async(
    user_id="user", session_id=session.id, new_message=content,
):
    print(event)
```

**Returns:** `google.adk.runners.Runner`

**Environment variables read by `agent.py`:**

| Variable | Default | Effect |
|----------|---------|--------|
| `RLM_ADK_MODEL` | `"gemini-3.1-pro-preview"` | Model used by the CLI-discoverable `app` |
| `RLM_REASONING_HTTP_TIMEOUT` | `"300000"` | HTTP timeout (ms) for the reasoning agent |
| `RLM_SESSION_DB` | `.adk/session.db` | Path to SQLite session database |
| `RLM_ADK_DEBUG` | `""` | Set to `1`/`true`/`yes` to enable `DebugLoggingPlugin` |
| `RLM_ADK_SQLITE_TRACING` | `""` | Set to `1` to enable `SqliteTracingPlugin` |
| `RLM_ADK_LANGFUSE` | `""` | Set to `1` to enable `LangfuseTracingPlugin` |
| `RLM_REPL_TRACE` | `"0"` | Set > 0 to enable `REPLTracingPlugin` |
| `RLM_CONTEXT_SNAPSHOTS` | `""` | Set to `1` to enable `ContextWindowSnapshotPlugin` |

---

### `rlm_adk/orchestrator.py`

**Purpose:** `RLMOrchestratorAgent` is the custom `BaseAgent` that drives the
entire RLM execution. It is a thin coordinator: it creates a `REPLTool`,
wires it onto the `reasoning_agent` at runtime, emits an initial user message,
then delegates to `reasoning_agent.run_async(ctx)`. ADK's native tool-calling
loop handles all iteration.

---

#### `is_transient_error`

```python
def is_transient_error(exc: Exception) -> bool
```

Classifies an exception as transient (retryable). Checks for:

- `google.genai.errors.ServerError` / `ClientError` with status codes in
  `{408, 429, 500, 502, 503, 504}`.
- `asyncio.TimeoutError`, `ConnectionError`, `OSError`.
- `httpx.ConnectError`, `httpx.TimeoutException` (if httpx is installed).

Returns `False` for all other exceptions.

---

#### `RLMOrchestratorAgent`

```python
class RLMOrchestratorAgent(BaseAgent):
    reasoning_agent: LlmAgent
    root_prompt: str | None = None
    repo_url: str | None = None
    persistent: bool = False
    worker_pool: Any = None
    repl: Any = None
```

Pydantic model (inherits `BaseAgent`). Fields must be set at construction;
runtime attribute mutations require `object.__setattr__`.

**`_run_async_impl(ctx: InvocationContext) -> AsyncGenerator[Event, None]`**

The sole implementation method. Execution sequence:

1. Reads `app:max_iterations` from session state (env var
   `RLM_MAX_ITERATIONS`, default `30`).
2. Creates or reuses `LocalREPL(depth=1)`.
3. Calls `create_dispatch_closures(worker_pool, ctx, ...)` if a worker pool
   is present; injects `llm_query_async` and `llm_query_batched_async` into
   the REPL namespace.
4. Injects repomix helpers (`probe_repo`, `pack_repo`, `shard_repo`) into
   REPL globals.
5. Creates `REPLTool(repl, max_calls=max_iterations, flush_fn=flush_fn, ...)`.
6. Wires `reasoning_agent.tools = [repl_tool]` via `object.__setattr__`.
7. Yields an `Event` with `state_delta` containing initial state
   (`CURRENT_DEPTH`, `ITERATION_COUNT`, `REQUEST_ID`, `ROOT_PROMPT`,
   `REPO_URL`).
8. Yields a user `Content` event with the initial prompt.
9. Delegates to `reasoning_agent.run_async(ctx)` with up to
   `RLM_LLM_MAX_RETRIES` (default `3`) retries on transient errors
   (exponential backoff starting at `RLM_LLM_RETRY_DELAY` seconds, default
   `5.0`).
10. Extracts `final_answer` from `ctx.session.state["reasoning_output"]`:
    tries JSON parse → `ReasoningOutput.final_answer`, then `FINAL()` pattern,
    then raw text.
11. Saves the final answer as an artifact via `save_final_answer`.
12. Yields a `state_delta` event setting `FINAL_ANSWER` and `SHOULD_STOP`.
13. In the `finally` block: resets `reasoning_agent.tools = []`; calls
    `repl.cleanup()` unless `persistent=True`.

**State written by this agent (via `EventActions.state_delta`):**

| Key | Value |
|-----|-------|
| `current_depth` | `1` |
| `iteration_count` | `0` |
| `request_id` | `uuid.uuid4()` string |
| `root_prompt` | value of `self.root_prompt` |
| `repo_url` | value of `self.repo_url` |
| `final_answer` | extracted final answer text |
| `should_stop` | `True` |

**Environment variables:**

| Variable | Default | Effect |
|----------|---------|--------|
| `RLM_MAX_ITERATIONS` | `"30"` | Max `execute_code` tool calls |
| `RLM_LLM_MAX_RETRIES` | `"3"` | Retry count for transient LLM errors |
| `RLM_LLM_RETRY_DELAY` | `"5.0"` | Base delay (seconds) for exponential backoff |
| `RLM_REPL_TRACE` | `"0"` | Trace level (0=off, 1=timing, 2=+memory) |

---

### `rlm_adk/dispatch.py`

**Purpose:** Worker pool management and dispatch closure factory for sub-LM
calls. Replaces the former TCP socket-based LMHandler with ADK `LlmAgent`
workers dispatched via `ParallelAgent`.

---

#### `WorkerPool`

```python
class WorkerPool:
    def __init__(
        self,
        default_model: str,
        other_model: str | None = None,
        pool_size: int = 5,
    )
```

Manages per-model `asyncio.Queue` pools of `LlmAgent` workers. Workers are
configured with `include_contents="none"` so they receive prompts only via
`before_model_callback`. They cannot transfer to parent or peers.

Each worker has dynamic attributes set on it:

- `_pending_prompt: str | None` — prompt injected by the dispatch closure.
- `_result: str | None` — response text written by `worker_after_model`.
- `_result_ready: bool` — flag set when `_result` is populated.
- `_result_error: bool` — flag set when the result represents an error.
- `_call_record: dict | None` — metadata dict written by callbacks.

**Methods:**

```python
def register_model(self, model_name: str, pool_size: int | None = None) -> None
```
Creates a new pool for `model_name` with `pool_size` workers (defaults to
`self.pool_size`). Called automatically by `acquire()` on first use.

```python
async def acquire(self, model: str | None = None) -> LlmAgent
```
Gets a worker from the pool for `model` (uses `other_model` if `None`).
Creates a new worker on demand if the pool is empty, to prevent deadlocks
when batch size exceeds pool capacity.

```python
async def release(self, worker: LlmAgent, model: str | None = None) -> None
```
Returns a worker to its pool. Discards on-demand workers when the pool has
already reached `pool_size`, preventing unbounded growth.

```python
def ensure_initialized(self) -> None
```
Pre-allocates pools for `default_model` and `other_model`. Called by the
orchestrator before creating dispatch closures.

---

#### `create_dispatch_closures`

```python
def create_dispatch_closures(
    worker_pool: WorkerPool,
    ctx: InvocationContext,
    call_log_sink: list | None = None,
    trace_sink: list | None = None,
) -> tuple[Any, Any, Any]
```

Returns a 3-tuple: `(llm_query_async, llm_query_batched_async, flush_fn)`.

These closures are injected into the REPL namespace by the orchestrator.
LM-generated code calls the sync names (`llm_query`, `llm_query_batched`)
which the AST rewriter transforms to their async equivalents.

**`llm_query_async(prompt, model=None, output_schema=None) -> LLMResult`**

Dispatches a single sub-LM query. Delegates to `llm_query_batched_async`
with a one-element list. When `output_schema` is a Pydantic `BaseModel`
subclass, the worker is wired with `SetModelResponseTool` and
`WorkerRetryPlugin` for self-healing structured output. Returns an `LLMResult`
(str subclass); `result.parsed` contains the validated dict when
`output_schema` was used.

**`llm_query_batched_async(prompts, model=None, output_schema=None) -> list[LLMResult]`**

Dispatches `K` prompts concurrently via `ParallelAgent`, chunked into batches
of at most `RLM_MAX_CONCURRENT_WORKERS` (default `4`). Batches beyond the
first are dispatched sequentially. Each dispatch has a timeout of
`RLM_WORKER_TIMEOUT` seconds (default `180`). Results are returned in prompt
order. Error results have `LLMResult.error=True`.

**`flush_fn() -> dict`**

Snapshots local dispatch accumulators (dispatch count, batch count, latency
list) and returns them as a dict suitable for merging into session state.
Resets all accumulators to zero after the call. Called by `REPLTool` after
each code execution to flush metrics into `tool_context.state` (AR-CRIT-001
compliance).

**State written via `flush_fn` return value:**

| Key constant | Description |
|---|---|
| `WORKER_DISPATCH_COUNT` | Total individual prompts dispatched |
| `OBS_WORKER_TOTAL_DISPATCHES` | Same as above (observability alias) |
| `OBS_WORKER_DISPATCH_LATENCY_MS` | List of per-batch elapsed times |
| `OBS_WORKER_TOTAL_BATCH_DISPATCHES` | Count of batch dispatches (K > 1) |

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `worker_pool` | `WorkerPool` | Pre-initialized pool |
| `ctx` | `InvocationContext` | Current ADK invocation context |
| `call_log_sink` | `list \| None` | Accumulates `RLMChatCompletion` records |
| `trace_sink` | `list[REPLTrace \| None] \| None` | Mutable single-element list; `trace_sink[0]` is the current `REPLTrace` |

**Environment variables:**

| Variable | Default | Effect |
|----------|---------|--------|
| `RLM_MAX_CONCURRENT_WORKERS` | `"4"` | Max workers per batch |
| `RLM_WORKER_TIMEOUT` | `"180"` | Per-dispatch timeout (seconds) |
| `RLM_WORKER_HTTP_TIMEOUT` | `"120000"` | HTTP timeout (ms) per worker call |

---

## 2. REPL

### `rlm_adk/repl/local_repl.py`

**Purpose:** Sandboxed Python execution environment. Provides persistent
variable state across calls, safe builtins, and slots for injected LM-query
closures. Captures stdout/stderr via task-local `ContextVar` buffers so that
concurrent async REPL executions do not interfere.

---

#### `LocalREPL`

```python
class LocalREPL:
    def __init__(self, depth: int = 1)
```

**Attributes:**

- `depth: int` — nesting depth, used in temp directory naming.
- `temp_dir: str` — unique temporary directory (`repl_adk_{uuid}_`); code
  executes with CWD set to this directory.
- `globals: dict` — execution namespace with safe builtins, `FINAL_VAR`,
  `SHOW_VARS`.
- `locals: dict` — user-defined variables accumulated across calls.
- `_pending_llm_calls: list[RLMChatCompletion]` — cleared at the start of
  each `execute_code` call.

**Safe builtins** include standard types, iteration functions, file I/O
(`open`, `__import__`), and common exception types. `eval`, `input`, `compile`,
and `globals` are blocked (`None`). `exec` is allowed.

**Methods:**

```python
def set_llm_query_fns(
    self,
    llm_query_fn: Callable,
    llm_query_batched_fn: Callable,
) -> None
```
Injects sync LM-query stubs into `globals["llm_query"]` and
`globals["llm_query_batched"]`. In ADK mode these are replaced with a
`RuntimeError`-raising stub because the AST rewriter must convert sync calls
to async.

```python
def set_async_llm_query_fns(
    self,
    llm_query_async_fn: Callable,
    llm_query_batched_async_fn: Callable,
) -> None
```
Injects async LM-query closures from `create_dispatch_closures` into
`globals["llm_query_async"]` and `globals["llm_query_batched_async"]`.

```python
def execute_code(self, code: str, trace: REPLTrace | None = None) -> REPLResult
```
Executes `code` synchronously under `_EXEC_LOCK` (serializes access to
`os.chdir` and `sys.stdout/stderr`). Optionally injects a `REPLTrace`
accumulator as `_rlm_trace` in the namespace and wraps code with
`TRACE_HEADER`/`TRACE_FOOTER`. Captures stdout/stderr; updates `self.locals`
with new non-underscore variables. Returns `REPLResult`.

```python
async def execute_code_async(
    self,
    code: str,
    repl_exec_fn: Any,
    trace: REPLTrace | None = None,
) -> REPLResult
```
Executes the AST-rewritten async function `repl_exec_fn` (produced by
`rewrite_for_async`). Uses `ContextVar` tokens for task-local stdout/stderr
capture. Updates `self.locals` from the `dict` returned by `repl_exec_fn()`.
Returns `REPLResult`.

```python
def cleanup(self) -> None
```
Removes `temp_dir` and clears `globals` / `locals`. Called automatically in
`__exit__` and `__del__`. The orchestrator calls this unless `persistent=True`.

**Context manager:** `LocalREPL` supports `with` — `__exit__` calls
`cleanup()`.

---

### `rlm_adk/repl/ast_rewriter.py`

**Purpose:** AST transformation pipeline that bridges sync user code and
async dispatch. Only activates when `llm_query` or `llm_query_batched` calls
are detected.

---

#### `has_llm_calls`

```python
def has_llm_calls(code: str) -> bool
```

Returns `True` if `code` contains a call to `llm_query` or
`llm_query_batched` as detected by AST walking (not string matching). Returns
`False` on `SyntaxError`.

---

#### `LlmCallRewriter`

```python
class LlmCallRewriter(ast.NodeTransformer)
```

`ast.NodeTransformer` subclass. Rewrites call nodes:

- `llm_query(args)` → `await llm_query_async(args)`
- `llm_query_batched(args)` → `await llm_query_batched_async(args)`

All positional and keyword arguments are preserved. Handles nested calls via
bottom-up traversal (`generic_visit` before transformation).

---

#### `rewrite_for_async`

```python
def rewrite_for_async(code: str) -> ast.Module
```

Full transformation pipeline:

1. Parse `code` to AST.
2. Apply `LlmCallRewriter` to transform sync LM calls to async awaits.
3. Apply `_promote_functions_to_async` to transitively promote any
   `def` bodies that now contain `await` to `async def`, and wrap their call
   sites with `await`.
4. Wrap all statements in `async def _repl_exec(): ... return locals()`.
5. Return the compiled-ready `ast.Module`.

The caller compiles the module, execs it to get `_repl_exec`, then calls
`await repl.execute_code_async(code, repl_exec_fn)`.

**Raises:** `SyntaxError` if `code` cannot be parsed.

---

### `rlm_adk/tools/repl_tool.py`

**Purpose:** ADK `BaseTool` that wraps `LocalREPL`. This is the tool the
reasoning agent calls via function calling (name: `"execute_code"`). It
enforces a call limit, manages trace recording, and flushes dispatch
accumulators.

---

#### `REPLTool`

```python
class REPLTool(BaseTool):
    def __init__(
        self,
        repl: LocalREPL,
        *,
        max_calls: int = 60,
        trace_holder: list | None = None,
        flush_fn: Callable[[], dict] | None = None,
    )
```

Tool name: `"execute_code"`. Single parameter: `code: str` (required).

**`run_async(*, args: dict[str, Any], tool_context: ToolContext) -> dict`**

Execution flow:

1. Increments `_call_count`; writes `ITERATION_COUNT` to
   `tool_context.state`.
2. Returns an error sentinel dict if `_call_count > _max_calls`.
3. Calls `has_llm_calls(code)` to detect async path.
   - Async path: `rewrite_for_async` → compile → exec → get `_repl_exec`
     → `await repl.execute_code_async(code, repl_exec_fn)`.
   - Sync path: `repl.execute_code(code)`.
4. Appends trace to `trace_holder` if provided (either `result.trace` dict or
   `result.to_dict()`).
5. Calls `flush_fn()` and merges returned dict into `tool_context.state`
   (flushes dispatch accumulators).
6. Writes `LAST_REPL_RESULT` summary dict to `tool_context.state`.
7. Filters `result.locals` to JSON-serializable primitives for the returned
   `variables` dict.

**Return value shape:**

```python
{
    "stdout": str,
    "stderr": str,
    "variables": dict,           # JSON-serializable locals only
    "llm_calls_made": bool,
    "call_number": int,
}
```

**State written to `tool_context.state`:**

| Key | Value |
|-----|-------|
| `iteration_count` | Current `_call_count` |
| `worker_dispatch_count` | From `flush_fn()` accumulator |
| `obs:worker_dispatch_latency_ms` | From `flush_fn()` accumulator |
| `last_repl_result` | `{"code_blocks": 1, "has_errors": bool, "has_output": bool, "total_llm_calls": int}` |

---

### `rlm_adk/repl/trace.py`

**Purpose:** Optional per-code-block execution tracing. Activated by
`RLM_REPL_TRACE > 0`. Provides `REPLTrace` (accumulator) and
`DataFlowTracker` (dependency detection). Also exports string constants for
code injection (trace level 2).

---

#### `REPLTrace`

```python
@dataclass
class REPLTrace:
    start_time: float = 0.0
    end_time: float = 0.0
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    var_snapshots: list[dict[str, Any]] = field(default_factory=list)
    peak_memory_bytes: int = 0
    exceptions: list[dict[str, Any]] = field(default_factory=list)
    data_flow_edges: list[tuple[int, int]] = field(default_factory=list)
    execution_mode: str = "sync"   # "sync" | "async"
    _call_counter: int = field(default=0, repr=False)
```

**Methods:**

```python
def record_llm_start(self, call_index: int, prompt: str, call_type: str = "single") -> None
```
Appends a new LLM call entry. Called by `llm_query_async` before dispatch.

```python
def record_llm_end(
    self, call_index: int, response: str, elapsed_ms: float,
    error: bool = False, **extra: Any,
) -> None
```
Updates the existing entry for `call_index` with timing and response length.
Creates a new entry if no matching start was recorded.

```python
def snapshot_vars(self, namespace: dict[str, Any], label: str = "") -> None
```
Captures a type-summary of all non-underscore variables in `namespace`.

```python
def to_dict(self) -> dict[str, Any]
```
Returns a JSON-compatible dict with keys: `wall_time_ms`, `execution_mode`,
`llm_calls`, `var_snapshots`, `peak_memory_bytes`, `exceptions`,
`data_flow_edges`.

```python
def summary(self) -> dict[str, Any]
```
Compact version: `wall_time_ms`, `llm_call_count`, `failed_llm_calls`,
`peak_memory_bytes`, `data_flow_edges`.

---

#### `DataFlowTracker`

```python
class DataFlowTracker:
    def __init__(self, min_fingerprint_len: int = 40)
```

Detects when one `llm_query` response text feeds into a subsequent prompt via
substring fingerprinting. Maintains a `(call_index -> response)` registry.

**Methods:**

```python
def register_response(self, call_index: int, response: str) -> None
```
Registers a completed response for future matching.

```python
def check_prompt(self, call_index: int, prompt: str) -> None
```
Checks if `prompt` contains the first `min_fingerprint_len` characters of any
registered response with a lower index. If so, records an edge
`(prev_index, call_index)`.

```python
def get_edges(self) -> list[tuple[int, int]]
```
Returns the accumulated data flow edges.

**Exported string constants** (for code injection at trace level >= 2):

| Name | Purpose |
|------|---------|
| `TRACE_HEADER` | Injected before sync code: sets `_rlm_trace.start_time` |
| `TRACE_FOOTER` | Injected after sync code: sets `_rlm_trace.end_time` |
| `TRACE_HEADER_MEMORY` | Like `TRACE_HEADER` but also starts `tracemalloc` |
| `TRACE_FOOTER_MEMORY` | Like `TRACE_FOOTER` but records peak memory and stops `tracemalloc` |

---

## 3. Callbacks

### `rlm_adk/callbacks/__init__.py`

Re-exports all public callbacks for convenient import:

```python
from rlm_adk.callbacks import (
    reasoning_after_model,
    reasoning_before_model,
    worker_after_model,
    worker_before_model,
    worker_on_model_error,
)
```

---

### `rlm_adk/callbacks/reasoning.py`

**Purpose:** Before/after model callbacks for the `reasoning_agent`. The
before callback merges the ADK-resolved dynamic instruction into
`system_instruction` and records token accounting. The after callback reads
token usage from `usage_metadata`.

---

#### `reasoning_before_model`

```python
def reasoning_before_model(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None
```

Called before each `reasoning_agent` model call. Actions:

1. Records `REASONING_CALL_START = time.perf_counter()` in
   `callback_context.state`.
2. Extracts static system instruction text from `llm_request.config.system_instruction`.
3. Extracts the ADK-resolved dynamic instruction from `llm_request.contents`.
4. Concatenates static + dynamic into the final `system_instruction` string
   and writes it back to `llm_request.config.system_instruction`.
5. Writes per-invocation accounting to state: `REASONING_PROMPT_CHARS`,
   `REASONING_SYSTEM_CHARS`, `REASONING_CONTENT_COUNT`,
   `REASONING_HISTORY_MSG_COUNT`, `CONTEXT_WINDOW_SNAPSHOT`.

Returns `None` (does not intercept the model call).

---

#### `reasoning_after_model`

```python
def reasoning_after_model(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> LlmResponse | None
```

Records `REASONING_INPUT_TOKENS` and `REASONING_OUTPUT_TOKENS` from
`llm_response.usage_metadata`. Returns `None` (observe-only).

---

### `rlm_adk/callbacks/worker.py`

**Purpose:** Before/after/error callbacks for `LlmAgent` worker instances.
Workers receive their prompt exclusively via `worker_before_model` (since
`include_contents="none"`), and results are written onto the worker object
for the dispatch closure to read.

---

#### `worker_before_model`

```python
def worker_before_model(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None
```

Reads `agent._pending_prompt` (set by the dispatch closure) via
`callback_context._invocation_context.agent` and sets it as
`llm_request.contents` as a single user `Content`. Returns `None`.

---

#### `worker_after_model`

```python
def worker_after_model(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> LlmResponse | None
```

Extracts text response from `llm_response.content.parts` (skipping `thought`
parts). Writes to the worker object:

- `agent._result = response_text`
- `agent._result_ready = True`
- `agent._call_record = {prompt, response, input_tokens, output_tokens, model, finish_reason, error: False}`

Also writes `response_text` to `callback_context.state[output_key]` for ADK
persistence. Returns `None`.

---

#### `worker_on_model_error`

```python
def worker_on_model_error(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
    error: Exception,
) -> LlmResponse | None
```

Handles LLM errors without crashing the enclosing `ParallelAgent`. Writes
error state onto the agent object:

- `agent._result = "[Worker {name} error: ...]"`
- `agent._result_ready = True`
- `agent._result_error = True`
- `agent._call_record = {..., "error": True, "error_category": str, "http_status": int|None}`

Returns a synthetic `LlmResponse` with the error message so ADK treats the
worker as having completed normally.

**Error categories** (from internal `_classify_error`):
`TIMEOUT`, `RATE_LIMIT`, `AUTH`, `SERVER`, `CLIENT`, `NETWORK`, `UNKNOWN`.

---

### `rlm_adk/callbacks/worker_retry.py`

**Purpose:** Structured output self-healing for workers. Extends ADK's
`ReflectAndRetryToolPlugin` to detect empty field values in
`set_model_response` tool results, and provides a monkey-patch for BUG-13.

---

#### `WorkerRetryPlugin`

```python
class WorkerRetryPlugin(ReflectAndRetryToolPlugin):
    def __init__(self, max_retries: int = 2)
```

Overrides `extract_error_from_result` to detect empty string values in
`set_model_response` tool arguments. Returns an error dict `{"error":
"Empty value", "details": ...}` to trigger retry, or `None` if validation
passes.

---

#### `make_worker_tool_callbacks`

```python
def make_worker_tool_callbacks(
    max_retries: int = 2,
) -> tuple[Any, Any]
```

Returns `(after_tool_cb, on_tool_error_cb)` — async callables compatible with
`LlmAgent.after_tool_callback` and `LlmAgent.on_tool_error_callback`.

- `after_tool_cb(tool, args, tool_context, tool_response)`: On
  `set_model_response` success, captures `tool_response` dict onto
  `agent._structured_result`. Delegates to `WorkerRetryPlugin.after_tool_callback`
  for empty-value detection.
- `on_tool_error_cb(tool, args, tool_context, error)`: Only intercepts
  `set_model_response` errors; all others return `None`. Delegates to
  `WorkerRetryPlugin.on_tool_error_callback` for retry guidance generation.

**Note:** Both callbacks use positional signatures to match ADK's internal
call conventions (`args=` not `tool_args=`).

---

#### `_patch_output_schema_postprocessor`

```python
def _patch_output_schema_postprocessor() -> None
```

Module-level BUG-13 workaround. Monkey-patches
`google.adk.flows.llm_flows._output_schema_processor.get_structured_model_response`
to return `None` (instead of extracted text) when the `set_model_response`
function response contains a `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel. This
prevents ADK from prematurely terminating the worker loop when retry guidance
is present.

Idempotent — guarded by `_rlm_patched` attribute. Applied at module import
time.

---

## 4. Plugins

### `rlm_adk/plugins/__init__.py`

Re-exports all plugin classes:

```python
from rlm_adk.plugins import (
    CachePlugin,
    DebugLoggingPlugin,
    LangfuseTracingPlugin,
    ObservabilityPlugin,
    PolicyPlugin,
    SqliteTracingPlugin,   # None if not importable
    MigrationPlugin,       # None if not importable
)
```

`SqliteTracingPlugin` and `MigrationPlugin` are conditionally imported;
the names are set to `None` if their modules are unavailable.

---

### `rlm_adk/plugins/observability.py`

**Purpose:** Observe-only plugin that tracks usage metrics, timings, and
provides a structured audit trail. Never returns a non-`None` value from any
callback. All errors inside callbacks are caught and suppressed.

---

#### `ObservabilityPlugin`

```python
class ObservabilityPlugin(BasePlugin):
    def __init__(self, *, name: str = "observability")
```

**Callbacks implemented:**

| Callback | Action |
|----------|--------|
| `before_agent_callback` | Sets `INVOCATION_START_TIME` on first call; logs agent entry |
| `after_agent_callback` | Logs agent exit |
| `before_model_callback` | Logs model name and request ID |
| `after_model_callback` | Increments `OBS_TOTAL_CALLS`, accumulates `OBS_TOTAL_INPUT_TOKENS`, `OBS_TOTAL_OUTPUT_TOKENS`, per-model usage dict (`obs:model_usage:{model}`), per-iteration token breakdown list (`OBS_PER_ITERATION_TOKEN_BREAKDOWN`), finish-reason counters |
| `before_tool_callback` | Increments per-tool invocation count in `OBS_TOOL_INVOCATION_SUMMARY` |
| `on_event_callback` | Logs state delta counts; increments `OBS_ARTIFACT_SAVES` on artifact deltas |
| `after_run_callback` | Sets `OBS_TOTAL_EXECUTION_TIME`; stores `USER_LAST_SUCCESSFUL_CALL_ID`; logs run summary |

---

### `rlm_adk/plugins/repl_tracing.py`

**Purpose:** Persists per-iteration REPL trace summaries as a JSON artifact
(`repl_traces.json`) at run end. Enabled when `RLM_REPL_TRACE > 0`.

---

#### `REPLTracingPlugin`

```python
class REPLTracingPlugin(BasePlugin):
    def __init__(self, name: str = "repl_tracing")
```

**Callbacks:**

| Callback | Action |
|----------|--------|
| `on_event_callback` | Watches for `LAST_REPL_RESULT` in `state_delta`; extracts `trace_summary` field; indexes by `ITERATION_COUNT` |
| `after_run_callback` | Saves `_traces_by_iteration` dict as `repl_traces.json` artifact via `invocation_context.artifact_service` |

---

### `rlm_adk/plugins/langfuse_tracing.py`

**Purpose:** Thin wrapper that initializes Langfuse + Google ADK OpenInference
instrumentation once. All actual span creation is handled automatically by
`GoogleADKInstrumentor`. The plugin itself implements no callbacks beyond
`__init__`.

---

#### `LangfuseTracingPlugin`

```python
class LangfuseTracingPlugin(BasePlugin):
    def __init__(self, *, name: str = "langfuse_tracing")
```

On `__init__`, calls `_init_langfuse_instrumentation()` which:

1. Checks for required env vars: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
   `LANGFUSE_BASE_URL`. Logs a warning and skips if any are missing.
2. Calls `langfuse.get_client().auth_check()`.
3. Calls `GoogleADKInstrumentor().instrument()`.
4. Sets module-level `_INSTRUMENTED = True` (idempotent across multiple
   instances).

**Property:**

```python
@property
def enabled(self) -> bool
```
Returns `True` if instrumentation was successfully initialized.

**Required packages:** `langfuse`, `openinference-instrumentation-google-adk`.

---

### `rlm_adk/plugins/cache.py`

**Purpose:** Request-fingerprint-based LLM response cache. Uses an
intervene-pattern: `before_model_callback` returns a cached `LlmResponse`
on hit, short-circuiting the model call.

---

#### `CachePlugin`

```python
class CachePlugin(BasePlugin):
    def __init__(
        self,
        *,
        name: str = "cache",
        max_entries: int = 1000,
        ttl_seconds: float = 300.0,
    )
```

Cache stored as a dict in `callback_context.state[CACHE_STORE]` (session
state, so it persists within the session but not across sessions).

**Callbacks:**

| Callback | Action |
|----------|--------|
| `before_model_callback` | Computes fingerprint; checks `CACHE_STORE`; returns cached `LlmResponse` on hit (increments `CACHE_HIT_COUNT`); stores fingerprint in state for `after_model`; increments `CACHE_MISS_COUNT` on miss |
| `after_model_callback` | Stores response in `CACHE_STORE` under the pending fingerprint; applies LRU eviction when `len > max_entries` |

**Fingerprint** (`_fingerprint`): SHA-256 of `model || prompt_text ||
SHA-256(system_instruction) || temperature`.

**TTL eviction:** Stale entries (older than `ttl_seconds`) are deleted on
cache hit.

**LRU eviction:** When `len(cache_store) > max_entries`, oldest entries by
timestamp are removed.

**State keys used:**

| Key | Description |
|-----|-------------|
| `cache:store` | Dict mapping fingerprint to `{response, timestamp}` |
| `cache:hit_count` | Cumulative cache hits |
| `cache:miss_count` | Cumulative cache misses |
| `cache:last_hit_key` | Fingerprint of the most recent hit |

---

### `rlm_adk/plugins/debug_logging.py`

**Purpose:** Development-only full interaction trace logger. Records prompts,
responses, tool calls, state snapshots, and artifact deltas. Writes all traces
to a YAML file on `after_run_callback`. Not intended for production use.

---

#### `DebugLoggingPlugin`

```python
class DebugLoggingPlugin(BasePlugin):
    def __init__(
        self,
        *,
        name: str = "debug_logging",
        output_path: str = "rlm_adk_debug.yaml",
        include_session_state: bool = True,
        include_system_instruction: bool = True,
    )
```

**Callbacks implemented:** `before_agent_callback`, `after_agent_callback`,
`before_model_callback`, `after_model_callback`, `on_model_error_callback`,
`before_tool_callback`, `after_tool_callback`, `on_event_callback`,
`after_run_callback`.

All callbacks print a one-line summary to stdout (prefixed `[RLM]`) and
append a structured entry to `self._traces`. The after-model callback
additionally reads per-agent-type token accounting from state to annotate
entries.

`after_run_callback` prints a `[RLM] RUN_COMPLETE ...` summary line and
writes a YAML file to `output_path` containing session metadata, final state
snapshot, and the full trace list. Clears `_traces` after writing.

State snapshots use `_safe_state_snapshot` which only includes serializable
values (`str`, `int`, `float`, `bool`, `None`, `list`, `dict` truncated to
500 chars).

---

### `rlm_adk/plugins/sqlite_tracing.py`

**Purpose:** Lightweight local telemetry via SQLite. No external dependencies.
Each invocation creates one `traces` row; each callback event creates one
`spans` row. Observe-only.

---

#### `SqliteTracingPlugin`

```python
class SqliteTracingPlugin(BasePlugin):
    def __init__(
        self,
        *,
        name: str = "sqlite_tracing",
        db_path: str = ".adk/traces.db",
    )
```

On `__init__`, creates the DB file (parent dirs included), runs the schema SQL
(two tables: `traces`, `spans`; three indices), and sets WAL mode.

**Schema:**

- `traces`: `trace_id`, `session_id`, `user_id`, `app_name`, `start_time`,
  `end_time`, `status`, `total_input_tokens`, `total_output_tokens`,
  `total_calls`, `iterations`, `final_answer_length`, `metadata`.
- `spans`: `span_id`, `trace_id`, `parent_span_id`, `operation_name`,
  `agent_name`, `start_time`, `end_time`, `status`, `attributes`, `events`.

**Callbacks and operations:**

| Callback | Operation |
|----------|-----------|
| `before_run_callback` | INSERT trace row; clear span stacks |
| `after_run_callback` | UPDATE trace row with end_time, token totals, iteration count, final_answer_length |
| `before_agent_callback` | INSERT agent span; push span_id onto `_agent_span_stack` |
| `after_agent_callback` | UPDATE agent span end_time; pop from stack |
| `before_model_callback` | INSERT model_call span; store in `_pending_model_spans[model]` |
| `after_model_callback` | UPDATE model_call span with token counts; pop from pending map |
| `on_model_error_callback` | UPDATE pending model_call span as error |
| `before_tool_callback` | INSERT tool_call span; store in `_pending_tool_spans[tool_name]` |
| `after_tool_callback` | UPDATE tool_call span with result preview |
| `on_event_callback` | INSERT artifact_save span for events with `artifact_delta` |

**`close() -> None`:** Closes the SQLite connection. Should be called when the
plugin is no longer needed.

---

## 5. Types and State

### `rlm_adk/types.py`

**Purpose:** Data types shared across modules. Covers structured output
schemas, LM call metadata, cost tracking, and REPL execution results.

---

#### `ReasoningOutput`

```python
class ReasoningOutput(BaseModel):
    final_answer: str = Field(description="Complete final answer to the query.")
    reasoning_summary: str = Field(default="", description="Brief reasoning summary.")
```

Pydantic model intended for use as `output_schema` on the reasoning agent.
Not currently wired as `output_schema` in the orchestrator (see note in
`orchestrator.py` lines 163–167); the orchestrator reads the raw text from
`output_key` instead.

---

#### `LLMResult`

```python
class LLMResult(str):
    error: bool = False
    error_category: str | None = None
    http_status: int | None = None
    finish_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str | None = None
    wall_time_ms: float = 0.0
    parsed: dict | None = None
```

`str` subclass returned by `llm_query_async` and `llm_query_batched_async`.
Backward-compatible with all `str` operations. REPL code can inspect metadata:

```python
result = llm_query("prompt")
if result.error and result.error_category == "TIMEOUT":
    raise RuntimeError(f"Timed out: {result}")
```

`parsed` is populated with the validated dict when `output_schema` was
provided to the dispatch function.

**Error categories:** `TIMEOUT`, `RATE_LIMIT`, `AUTH`, `SERVER`, `CLIENT`,
`NETWORK`, `FORMAT`, `UNKNOWN`.

---

#### `ModelUsageSummary`

```python
@dataclass
class ModelUsageSummary:
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
```

Token accounting for a single model backend. Provides `to_dict()` and
`from_dict(data: dict)`.

---

#### `UsageSummary`

```python
@dataclass
class UsageSummary:
    model_usage_summaries: dict[str, ModelUsageSummary]
```

Aggregated cost tracking across all model backends in a single RLM call.
Provides `to_dict()` and `from_dict(data: dict)`.

---

#### `RLMChatCompletion`

```python
@dataclass
class RLMChatCompletion:
    root_model: str
    prompt: str | dict[str, Any]
    response: str
    usage_summary: UsageSummary
    execution_time: float
```

Record of a single sub-LM call made from within the REPL environment.
Accumulated in `LocalREPL._pending_llm_calls` and exposed via `REPLResult.llm_calls`.
Provides `to_dict()` and `from_dict(data: dict)`.

---

#### `REPLResult`

```python
@dataclass
class REPLResult:
    stdout: str
    stderr: str
    locals: dict
    execution_time: float | None
    llm_calls: list[RLMChatCompletion]
    trace: dict[str, Any] | None
```

Returned by `LocalREPL.execute_code` and `LocalREPL.execute_code_async`.
`trace` is `REPLTrace.to_dict()` if a `REPLTrace` was provided, else `None`.

`to_dict()` serializes `locals` via `_serialize_value` (handles modules,
callables, non-serializable objects gracefully).

---

### `rlm_adk/state.py`

**Purpose:** Central registry of session state key constants. All modules
import from here rather than using raw strings, ensuring consistency.

---

#### Key groups

**ADK scope prefixes** (standard ADK behavior):

| Prefix | Scope |
|--------|-------|
| (none) | Session — persists within one session |
| `user:` | User — persists across sessions for the same user |
| `app:` | Application — persists across all users/sessions |

Note: `cache:` and `obs:` prefixes are naming conventions within session scope
only.

**Flow control:**

| Constant | Key String | Description |
|----------|-----------|-------------|
| `APP_MAX_DEPTH` | `"app:max_depth"` | Maximum recursion depth |
| `APP_MAX_ITERATIONS` | `"app:max_iterations"` | Max tool calls per run |
| `CURRENT_DEPTH` | `"current_depth"` | Current recursion depth |
| `ITERATION_COUNT` | `"iteration_count"` | Current REPL tool call number |
| `SHOULD_STOP` | `"should_stop"` | Signal to terminate the loop |

**REPL execution:**

| Constant | Key String | Description |
|----------|-----------|-------------|
| `LAST_REPL_RESULT` | `"last_repl_result"` | Summary dict from last REPLTool call |
| `FINAL_ANSWER` | `"final_answer"` | Final answer text |

**Context metadata:**

| Constant | Key String |
|----------|-----------|
| `REPO_URL` | `"repo_url"` |
| `ROOT_PROMPT` | `"root_prompt"` |
| `REQUEST_ID` | `"request_id"` |

**Dynamic instruction state** (for ADK `{var?}` template resolution):

| Constant | Key String |
|----------|-----------|
| `DYN_REPO_URL` | `"repo_url"` (same as `REPO_URL`) |
| `DYN_ROOT_PROMPT` | `"root_prompt"` (same as `ROOT_PROMPT`) |

**Per-invocation token accounting:**

| Constant | Description |
|----------|-------------|
| `REASONING_PROMPT_CHARS` | Total prompt character count |
| `REASONING_SYSTEM_CHARS` | System instruction character count |
| `REASONING_HISTORY_MSG_COUNT` | Number of content entries |
| `REASONING_CONTENT_COUNT` | Same as above |
| `REASONING_INPUT_TOKENS` | From `usage_metadata.prompt_token_count` |
| `REASONING_OUTPUT_TOKENS` | From `usage_metadata.candidates_token_count` |
| `WORKER_PROMPT_CHARS` | Worker prompt character count |
| `WORKER_CONTENT_COUNT` | Worker content entry count |
| `WORKER_INPUT_TOKENS` | Worker input tokens |
| `WORKER_OUTPUT_TOKENS` | Worker output tokens |
| `CONTEXT_WINDOW_SNAPSHOT` | Dict snapshot from `reasoning_before_model` |

**Worker dispatch:**

| Constant | Description |
|----------|-------------|
| `WORKER_DISPATCH_COUNT` | Total individual queries dispatched in last flush |
| `OBS_WORKER_DISPATCH_LATENCY_MS` | List of per-batch elapsed times |
| `OBS_WORKER_TOTAL_DISPATCHES` | Cumulative dispatch count |
| `OBS_WORKER_TOTAL_BATCH_DISPATCHES` | Cumulative batch dispatch count |

**Observability:**

| Constant | Description |
|----------|-------------|
| `OBS_TOTAL_INPUT_TOKENS` | Cumulative input tokens across all calls |
| `OBS_TOTAL_OUTPUT_TOKENS` | Cumulative output tokens |
| `OBS_TOTAL_CALLS` | Total LLM model calls |
| `OBS_TOOL_INVOCATION_SUMMARY` | Dict of tool_name -> call count |
| `OBS_TOTAL_EXECUTION_TIME` | Wall time from `INVOCATION_START_TIME` to run end |
| `OBS_PER_ITERATION_TOKEN_BREAKDOWN` | List of per-call token breakdown dicts |
| `OBS_ARTIFACT_SAVES` | Count of artifact saves |
| `OBS_ARTIFACT_BYTES_SAVED` | Bytes saved to artifacts |

**Caching:**

| Constant | Key |
|----------|-----|
| `CACHE_STORE` | `"cache:store"` |
| `CACHE_HIT_COUNT` | `"cache:hit_count"` |
| `CACHE_MISS_COUNT` | `"cache:miss_count"` |
| `CACHE_LAST_HIT_KEY` | `"cache:last_hit_key"` |

**Depth-scoped keys:**

```python
DEPTH_SCOPED_KEYS: set[str] = {
    MESSAGE_HISTORY, ITERATION_COUNT, FINAL_ANSWER, LAST_REPL_RESULT, SHOULD_STOP,
}
```

These keys need independent state per nesting depth.

---

#### Utility functions

```python
def depth_key(key: str, depth: int = 0) -> str
```
Returns `key` unchanged at depth 0; returns `"{key}@d{depth}"` at depth > 0.

```python
def obs_model_usage_key(model_name: str) -> str
```
Returns `"obs:model_usage:{model_name}"` — the state key for per-model usage
tracking written by `ObservabilityPlugin`.

---

## 6. Utilities

### `rlm_adk/utils/parsing.py`

**Purpose:** Text parsing utilities for extracting final answers from LLM
response text using pattern matching.

---

#### `find_final_answer`

```python
def find_final_answer(text: str, environment: Any = None) -> str | None
```

Searches `text` for two patterns (checked in order):

1. `FINAL_VAR(variable_name)` at the start of a line: If `environment` is
   provided, executes `print(FINAL_VAR(variable_name))` in it and returns
   stdout. If no environment, returns `None`.
2. `FINAL(content)` at the start of a line (multiline match): Returns
   `content` stripped.

Returns `None` if neither pattern is found.

Used by `RLMOrchestratorAgent` as a fallback when the `reasoning_output`
state value is plain text (no JSON and no structured output schema).

---

### `rlm_adk/utils/prompts.py`

**Purpose:** System prompt string constants for the reasoning agent.

---

#### `RLM_STATIC_INSTRUCTION`

```python
RLM_STATIC_INSTRUCTION: str
```

Multi-paragraph static system prompt. Passed as `LlmAgent.static_instruction`
(no ADK template processing). Covers:

- Description of available tools: `execute_code` and `set_model_response`.
- REPL environment capabilities: `open()`, `llm_query`, `llm_query_batched`,
  `SHOW_VARS`, `print`.
- Strategy guidance: chunking, batching, progressive analysis.
- Code examples for data loading, chunking, batched LLM queries, and final
  answer submission via `set_model_response`.
- Repository processing overview (references `probe_repo`, `pack_repo`,
  `shard_repo` — documented in the repomix skill).

The repomix skill instruction block is appended at runtime in
`create_reasoning_agent` via `build_skill_instruction_block()`.

---

#### `RLM_DYNAMIC_INSTRUCTION`

```python
RLM_DYNAMIC_INSTRUCTION: str
```

Short template string passed as `LlmAgent.instruction`. ADK resolves
`{var?}` placeholders from session state at runtime:

```
Repository URL: {repo_url?}
Original query: {root_prompt?}
```

The `?` suffix makes the substitutions optional — no error if the state key
is absent. ADK appends the resolved result to `contents` as user-role text,
which `reasoning_before_model` then relocates into `system_instruction`.
