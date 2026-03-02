# RLM-ADK Architecture

**Date:** 2026-02-28
**Codebase:** `/home/rawley-stanhope/dev/rlm-adk`

---

## 1. System Overview

RLM-ADK (Recursive Language Models on Google Agent Development Kit) is a reasoning agent system built on top of Google's ADK (`google.adk`) framework. Its core purpose is to let a primary LLM reason and act by executing Python code in a persistent REPL environment, and to dispatch sub-LM queries to a pool of isolated worker LLMs running in parallel.

The system has three distinguishing capabilities:

1. **REPL-driven reasoning.** The primary reasoning agent (`LlmAgent`) calls a custom tool named `execute_code` (the `REPLTool`). Each call executes Python code in a sandboxed `LocalREPL` environment whose namespace is persistent across calls within a single invocation. The model can iterate: write code, observe output, write more code.

2. **Sub-LM dispatch.** REPL code can call `llm_query(prompt)` or `llm_query_batched(prompts)`. These are synchronous-looking APIs that the AST rewriter automatically transforms to `await llm_query_async(prompt)` / `await llm_query_batched_async(prompts)`. The async implementations acquire pre-allocated `LlmAgent` workers from a `WorkerPool` and dispatch them via ADK's `ParallelAgent`, enabling concurrent sub-LM calls without blocking the event loop.

3. **Collapsed orchestration.** The `RLMOrchestratorAgent` (a `BaseAgent`) does not manually iterate or parse code blocks. It wires up the `REPLTool`, yields an initial user `Content` event, then delegates entirely to `reasoning_agent.run_async(ctx)`. ADK's native tool-calling loop handles all iteration — each model turn that calls `execute_code` runs the REPL and feeds results back into the model's conversation history automatically.

---

## 2. Architecture Diagram

```
User / Caller
    |
    | runner.run_async(user_id=..., session_id=..., new_message=...)
    v
+----------------------------------------------------------+
|  Runner (google.adk.runners.Runner)                      |
|  - Drives the ADK event loop                             |
|  - Commits state_delta via SqliteSessionService          |
|  - Commits artifact_delta via FileArtifactService        |
|  - Forwards processed Events upstream to caller          |
|                                                          |
|  +----------------------------------------------------+  |
|  |  App (google.adk.apps.App, name="rlm_adk")        |  |
|  |  Plugins (applied globally to all agents):         |  |
|  |    - ObservabilityPlugin (always on)               |  |
|  |    - DebugLoggingPlugin  (default on)              |  |
|  |    - SqliteTracingPlugin (default on)              |  |
|  |    - LangfuseTracingPlugin (opt-in)                |  |
|  |    - REPLTracingPlugin (opt-in, RLM_REPL_TRACE>0)  |  |
|  |    - ContextWindowSnapshotPlugin (opt-in)          |  |
|  |    - CachePlugin (manual wiring only)              |  |
|  |                                                    |  |
|  |  +----------------------------------------------+  |  |
|  |  | RLMOrchestratorAgent (BaseAgent)             |  |  |
|  |  | _run_async_impl():                           |  |  |
|  |  |   1. Create LocalREPL                        |  |  |
|  |  |   2. create_dispatch_closures() -> WorkerPool|  |  |
|  |  |   3. Create REPLTool(repl, flush_fn)         |  |  |
|  |  |   4. Wire reasoning_agent.tools=[repl_tool]  |  |  |
|  |  |   5. Yield initial state Event               |  |  |
|  |  |   6. Yield initial user Content Event        |  |  |
|  |  |   7. reasoning_agent.run_async(ctx)  <loop>  |  |  |
|  |  |   8. Extract final_answer from output_key    |  |  |
|  |  |   9. Yield FINAL_ANSWER state Event          |  |  |
|  |  |                                              |  |  |
|  |  |  +----------------------------------------+  |  |  |
|  |  |  | reasoning_agent (LlmAgent)             |  |  |  |
|  |  |  | model: gemini-3.1-pro-preview          |  |  |  |
|  |  |  | include_contents: "default"            |  |  |  |
|  |  |  | output_key: "reasoning_output"         |  |  |  |
|  |  |  | planner: BuiltInPlanner (ThinkingConfig)|  |  |  |
|  |  |  | tools: [REPLTool(name="execute_code")] |  |  |  |
|  |  |  | before_model: reasoning_before_model   |  |  |  |
|  |  |  | after_model:  reasoning_after_model    |  |  |  |
|  |  |  |                                        |  |  |  |
|  |  |  | ADK tool-calling loop:                 |  |  |  |
|  |  |  |  [call LLM] -> execute_code({code}) -> |  |  |  |
|  |  |  |  [REPLTool.run_async()] ->             |  |  |  |
|  |  |  |  [LocalREPL.execute_code()] ->         |  |  |  |
|  |  |  |  return {stdout, stderr, variables}    |  |  |  |
|  |  |  |  -> [call LLM again with result] ...   |  |  |  |
|  |  |  +------+--+------------------------------+  |  |  |
|  |  |         |  | llm_query_async / llm_query_batched_async
|  |  |         |  | (injected into REPL namespace)
|  |  |         v  v                                |  |  |
|  |  |  +----------------------------------------+  |  |  |
|  |  |  | WorkerPool                             |  |  |  |
|  |  |  | dict[model_name -> asyncio.Queue]      |  |  |  |
|  |  |  | pool_size=5 workers per model          |  |  |  |
|  |  |  |                                        |  |  |  |
|  |  |  |  Single dispatch (K=1):                |  |  |  |
|  |  |  |    worker.run_async(ctx)               |  |  |  |
|  |  |  |                                        |  |  |  |
|  |  |  |  Batch dispatch (K>1):                 |  |  |  |
|  |  |  |    ParallelAgent([w1, w2, ...]).        |  |  |  |
|  |  |  |      run_async(ctx)                    |  |  |  |
|  |  |  |                                        |  |  |  |
|  |  |  |  +-----------+  +-----------+          |  |  |  |
|  |  |  |  | worker_1  |  | worker_2  |  ...     |  |  |  |
|  |  |  |  | LlmAgent  |  | LlmAgent  |          |  |  |  |
|  |  |  |  | include_  |  | include_  |          |  |  |  |
|  |  |  |  | contents: |  | contents: |          |  |  |  |
|  |  |  |  | "none"    |  | "none"    |          |  |  |  |
|  |  |  |  +-----------+  +-----------+          |  |  |  |
|  |  |  +----------------------------------------+  |  |  |
|  |  +----------------------------------------------+  |  |
|  +----------------------------------------------------+  |
+----------------------------------------------------------+
         |                        |
         v                        v
  SqliteSessionService      FileArtifactService
  (.adk/session.db, WAL)    (.adk/artifacts/)
```

---

## 3. Core Components

### 3.1 `rlm_adk/__init__.py` — Public API

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/__init__.py`

Exports the four factory functions as the public API:
- `create_rlm_runner(model, ...)` — full Runner with services and plugins
- `create_rlm_app(model, ...)` — App with plugins, no services
- `create_rlm_orchestrator(model, ...)` — RLMOrchestratorAgent
- `create_reasoning_agent(model, ...)` — LlmAgent for depth=0 reasoning
- `app` — module-level App symbol for ADK CLI discovery (`adk run rlm_adk`, `adk web`)

### 3.2 `rlm_adk/agent.py` — Agent and Runner Factory

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py`

Contains all factory functions. Key behaviors:

**`create_reasoning_agent()`** (lines 151-226): Builds the LlmAgent for the main reasoning loop.
- `instruction=RLM_DYNAMIC_INSTRUCTION` — template string with `{var?}` placeholders resolved from session state at each turn (repo_url, root_prompt, etc.). ADK places the resolved result into `contents` as user content.
- `static_instruction=RLM_STATIC_INSTRUCTION` — stable system prompt (code examples, REPL guidance, repomix docs). ADK places this into `system_instruction` without template processing. Repomix skill instructions are appended here at factory time.
- `include_contents="default"` — ADK manages the full tool call/response history.
- `output_key="reasoning_output"` — ADK writes the final text response to `session.state["reasoning_output"]`.
- `before_model_callback=reasoning_before_model`, `after_model_callback=reasoning_after_model`.
- `planner=BuiltInPlanner(thinking_config=ThinkingConfig(include_thoughts=True, thinking_budget=1024))` — enables Gemini's built-in thinking.
- HTTP retry: 3 attempts, exponential backoff, 300s timeout.

**`create_rlm_orchestrator()`** (lines 229-267): Wraps the reasoning agent in `RLMOrchestratorAgent`. Creates a default `WorkerPool` if none is provided.

**`create_rlm_app()`** (lines 326-386): Wraps orchestrator in `App` with plugins. Default plugin set: `ObservabilityPlugin`, `DebugLoggingPlugin`, `SqliteTracingPlugin`. Langfuse, REPL tracing, and `ContextWindowSnapshotPlugin` are opt-in (via `RLM_ADK_LANGFUSE`, `RLM_REPL_TRACE`, and `RLM_CONTEXT_SNAPSHOTS` env vars respectively).

**`create_rlm_runner()`** (lines 389-487): Wraps `App` in `Runner` with `SqliteSessionService` (WAL mode, `.adk/session.db`) and `FileArtifactService` (`.adk/artifacts/`).

**`_default_session_service()`** (lines 85-120): Creates a `SqliteSessionService` with performance pragmas applied via a one-time synchronous `sqlite3` connection: `journal_mode=WAL`, `synchronous=NORMAL`, `cache_size=-64000`, `temp_store=MEMORY`, `mmap_size=268435456`, `wal_autocheckpoint=1000`.

### 3.3 `rlm_adk/orchestrator.py` — RLMOrchestratorAgent

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py`

`RLMOrchestratorAgent` extends `BaseAgent`. It is a Pydantic model (`model_config = {"arbitrary_types_allowed": True}`).

**Fields:**
- `reasoning_agent: LlmAgent` — declared as a Pydantic field so ADK recognizes it as a sub-agent.
- `root_prompt: str | None`, `repo_url: str | None`, `persistent: bool`, `worker_pool: Any`, `repl: Any`.

**`_run_async_impl(ctx)` execution sequence** (lines 99-311):

1. Read `max_iterations` from `ctx.session.state.get(APP_MAX_ITERATIONS, 30)`.
2. Create or reuse `LocalREPL(depth=1)`. Inject `LLMResult` into REPL globals.
3. Create `trace_holder: list[REPLTrace | None] = [None]` for REPL tracing.
4. Call `create_dispatch_closures(worker_pool, ctx, ...)` to get `(llm_query_async, llm_query_batched_async, flush_fn)`. Inject the async functions into the REPL via `repl.set_async_llm_query_fns(...)`. Register a sync stub that raises `RuntimeError` for direct `llm_query()` calls.
5. Inject repomix skill helpers (`probe_repo`, `pack_repo`, `shard_repo`) into REPL globals.
6. Create `REPLTool(repl, max_calls=max_iterations, flush_fn=flush_fn, trace_holder=trace_holder)`.
7. Wire tools onto `reasoning_agent` at runtime using `object.__setattr__` (required because `LlmAgent` is a Pydantic model). Also ensure `include_contents="default"`.
8. Yield initial state `Event` with `EventActions(state_delta={CURRENT_DEPTH: 1, ITERATION_COUNT: 0, REQUEST_ID: uuid4(), ...})`.
9. Yield initial user `Content` event carrying `root_prompt`.
10. Delegate to `reasoning_agent.run_async(ctx)` with exponential-backoff retry for transient errors (408, 429, 500, 502, 503, 504; `asyncio.TimeoutError`; `ConnectionError`; `OSError`; `httpx` errors). Default: 3 retries, 5s base delay.
11. Read `ctx.session.state["reasoning_output"]`. Parse as JSON (dict → `ReasoningOutput` format) or plain text with `FINAL()` pattern extraction.
12. Call `save_final_answer(ctx, answer=final_answer)` to save the answer as an artifact.
13. Yield `Event(state_delta={FINAL_ANSWER: ..., SHOULD_STOP: True})` and a final model `Content` event.
14. In `finally`: reset `reasoning_agent.tools = []`, call `repl.cleanup()` (unless `persistent=True`).

**Transient error classification** (`is_transient_error`, lines 54-70): Type-based check against `google.genai` `ServerError`/`ClientError` status codes, `asyncio.TimeoutError`, `ConnectionError`, `OSError`, and optionally `httpx` exceptions.

### 3.4 `rlm_adk/dispatch.py` — WorkerPool and Dispatch Closures

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py`

#### WorkerPool (lines 50-202)

Manages a `dict[str, asyncio.Queue[LlmAgent]]` — one unbounded queue per registered model name.

**Worker configuration** (`_create_worker`, lines 97-144): Each worker is an `LlmAgent` with:
- `include_contents="none"` — worker receives prompt only via `before_model_callback`. No history.
- `disallow_transfer_to_parent=True`, `disallow_transfer_to_peers=True`.
- `output_key=f"{worker_name}_output"`.
- `before_model_callback=worker_before_model`, `after_model_callback=worker_after_model`, `on_model_error_callback=worker_on_model_error`.
- `generate_content_config`: `temperature=0.0`, 120s HTTP timeout, 2-attempt retry.
- Dynamic attributes set via `worker._pending_prompt = None`, `worker._result = None`, `worker._result_ready = False`, `worker._result_error = False`, `worker._call_record = None`.

**`acquire(model)`** (lines 146-171): `get_nowait()` from the pool queue. If `QueueEmpty`, creates a new on-demand worker to prevent deadlock when batch size exceeds pool capacity.

**`release(worker, model)`** (lines 173-192): Returns worker to queue only if `queue.qsize() < pool_size`. On-demand workers are discarded when the pool is at capacity.

**`ensure_initialized()`** (lines 194-202): Pre-allocates pools for `default_model` and `other_model`. Called by orchestrator at startup.

#### create_dispatch_closures (lines 214-559)

Returns a 3-tuple: `(llm_query_async, llm_query_batched_async, flush_fn)`.

**Local accumulators** (lines 243-245): `_acc_dispatch_count`, `_acc_batch_dispatches`, `_acc_latencies` are `nonlocal` variables in the closure. These accumulate state without writing to `ctx.session.state` directly (AR-CRIT-001).

**`llm_query_async(prompt, model, output_schema)`** (lines 247-288): The K=1 case. Delegates to `llm_query_batched_async([prompt])`. Records timing in `REPLTrace` if trace_sink is provided.

**`llm_query_batched_async(prompts, model, output_schema)`** (lines 290-536): The K>N case. Execution:
1. Reads `RLM_MAX_CONCURRENT_WORKERS` (default 4) to determine chunk size.
2. Splits prompts into sequential chunks of at most `max_concurrent`.
3. For each chunk: acquires workers, injects prompts via `worker._pending_prompt`, resets result carrier attributes.
4. If `output_schema` is provided: sets `worker.output_schema`, `worker.tools=[SetModelResponseTool(schema)]`, and wires `after_tool_callback`/`on_tool_error_callback` from `make_worker_tool_callbacks()`.
5. Single-worker chunk: `asyncio.wait_for(worker.run_async(ctx), timeout=180s)`.
6. Multi-worker chunk: creates a transient `ParallelAgent(sub_agents=workers)` and `asyncio.wait_for(parallel.run_async(ctx), timeout=180s)`.
7. Reads results from `worker._result`, `worker._result_ready`, `worker._result_error`, `worker._call_record`.
8. Constructs `LLMResult` objects (str subclass with metadata fields).
9. In `finally`: clears all worker dynamic attributes, resets structured output wiring, sets `worker.parent_agent = None` (critical — ADK sets this in `model_post_init` and raises if already set on reuse), calls `worker_pool.release(worker, model)`.

**`flush_fn()`** (lines 538-557): Snapshots accumulated state (`_acc_dispatch_count`, `_acc_batch_dispatches`, `_acc_latencies`) into a dict and resets all accumulators to zero. Returns the dict for writing to `tool_context.state` by the caller (REPLTool).

**`_consume_events(run_iter)`** (lines 208-211): Async function that iterates and discards all events from a `run_async()` iterator. Used for both single-worker and `ParallelAgent` dispatch — results are read from agent objects, not from events.

### 3.5 `rlm_adk/tools/repl_tool.py` — REPLTool

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py`

`REPLTool` extends `BaseTool` with `name="execute_code"`. It exposes a single parameter: `code: str`.

**`run_async(args, tool_context)`** (lines 75-161):

1. Increments `_call_count`. Writes `tool_context.state[ITERATION_COUNT] = _call_count`.
2. If `_call_count > max_calls`: returns early with a call-limit error message.
3. Calls `has_llm_calls(code)` (AST parse). If true:
   - Calls `rewrite_for_async(code)` to get a transformed AST module.
   - `compile(tree, "<repl>", "exec")` and `exec(compiled, ns)` where `ns` merges `repl.globals` and `repl.locals`.
   - Calls `await repl.execute_code_async(code, repl_exec_fn)`.
4. If false: calls `repl.execute_code(code)` (synchronous).
5. Appends trace data to `trace_holder` if provided.
6. Calls `self._flush_fn()` and writes the returned dict keys into `tool_context.state` one by one.
7. Writes `tool_context.state[LAST_REPL_RESULT]` summary dict.
8. Filters `result.locals` to JSON-serializable primitives for the return value.
9. Returns `{stdout, stderr, variables, llm_calls_made, call_number}`.

Writing to `tool_context.state` is the correct ADK pattern — it goes through `EventActions` tracking.

### 3.6 `rlm_adk/repl/local_repl.py` — LocalREPL

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/local_repl.py`

Provides a sandboxed Python execution environment.

**Sandboxing** (lines 82-172): `_SAFE_BUILTINS` allows standard builtins including `exec`, `open`, `__import__`, `__build_class__`, and `locals`, but blocks `input=None`, `eval=None`, `compile=None`, `globals=None`. The namespace merges `globals` and `locals` dicts.

**Output capture** (lines 33-74): A module-level `_TaskLocalStream` proxy is installed over `sys.stdout` and `sys.stderr` at import time. The proxy checks a `contextvars.ContextVar` buffer: if set, writes go to the buffer; otherwise they pass through to the original stream. This provides task-local capture in async execution.

**`execute_code(code, trace)`** (lines 267-313): Synchronous path. Acquires `_EXEC_LOCK` (a module-level `threading.Lock`) to serialize access to process-global state (`os.chdir`, `sys.stdout/stderr`) from concurrent REPLs. Changes CWD to `self.temp_dir` via `_temp_cwd()` context manager. Executes in a merged `{**self.globals, **self.locals}` namespace. Post-execution: updates `self.locals` with new non-private variables.

**`execute_code_async(code, repl_exec_fn, trace)`** (lines 315-382): Async path for AST-rewritten code. Sets `ContextVar` buffers for stdout/stderr, replaces `sys.stdout/sys.stderr` directly (for reliability across pytest capture environments), changes CWD, then `await repl_exec_fn()`. The function returns `locals()` from inside `_repl_exec()`. Updates `self.locals` with the returned dict.

**Injected globals** available to all REPL code at runtime. `LocalREPL.__init__` injects `FINAL_VAR` and `SHOW_VARS`. `set_llm_query_fns()` / `set_async_llm_query_fns()` inject the four LLM query functions (`llm_query`, `llm_query_batched`, `llm_query_async`, `llm_query_batched_async`). The orchestrator (`_run_async_impl`) additionally injects `LLMResult`, `probe_repo`, `pack_repo`, and `shard_repo` into `repl.globals`.

**`cleanup()`** (line 384): Removes `self.temp_dir` and clears `globals` and `locals`.

### 3.7 `rlm_adk/repl/ast_rewriter.py` — AST Rewriter

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/ast_rewriter.py`

Transforms LM-generated Python code from synchronous `llm_query()` calls to async/await form so it can run inside an `async def _repl_exec()` function.

**`has_llm_calls(code)`** (lines 15-36): Parses the code into an AST and walks nodes looking for `ast.Call` where `func` is an `ast.Name` with `id in ("llm_query", "llm_query_batched")`. Returns `False` on `SyntaxError` (execution will catch it later). This is the fast path: if no LM calls are detected, `rewrite_for_async` is never called.

**`rewrite_for_async(code)`** (lines 161-228):
1. Parse code into `ast.Module`.
2. Apply `LlmCallRewriter` (an `ast.NodeTransformer`) which visits every `ast.Call` and rewrites `llm_query(args)` to `ast.Await(llm_query_async(args))` and `llm_query_batched(args)` to `ast.Await(llm_query_batched_async(args))`. Handles nested calls via `self.generic_visit(node)` first.
3. Apply `_promote_functions_to_async(tree)` — iterates to a fixed point: any `FunctionDef` that contains an `ast.Await` node (detected by `_contains_await`) is promoted to `AsyncFunctionDef` via `_FuncDefPromoter`, and then its call sites are wrapped with `await` via `_PromotedCallAwaiter`. This handles helper functions that call `llm_query`.
4. Append `return locals()` to the statement list.
5. Wrap all statements in `async def _repl_exec(): <body>`.
6. Return the new `ast.Module` (single `AsyncFunctionDef`).

The caller (`REPLTool`) then `compile()`s and `exec()`s this module, extracts `_repl_exec` from the namespace, and `await`s it.

### 3.8 `rlm_adk/repl/trace.py` — REPL Tracing Infrastructure

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py`

Provides optional per-code-block trace accumulation controlled by the `RLM_REPL_TRACE` environment variable (0=off, 1=timing+vars+data-flow, 2=+memory via `tracemalloc`).

**`REPLTrace`** (lines 22-109): Dataclass accumulating `start_time`, `end_time`, `llm_calls` list, `var_snapshots` list, `peak_memory_bytes`, `exceptions`, `data_flow_edges`, and `execution_mode`. Methods: `record_llm_start()`, `record_llm_end()` (matched by `call_index`), `snapshot_vars()`, `to_dict()`, `summary()`.

**`DataFlowTracker`** (lines 112-146): Detects when one `llm_query` response feeds into a subsequent prompt. Uses substring fingerprinting: the first 40 characters of a completed response are checked against later prompt text. Records edges as `(source_call_index, target_call_index)` tuples.

**Trace header/footer strings** (lines 149-193): Four module-level string constants are exported. At `trace_level == 1`, `TRACE_HEADER` / `TRACE_FOOTER` are prepended/appended to REPL code -- these set `_rlm_trace.start_time` and `_rlm_trace.end_time` via `time.perf_counter()`. At `trace_level >= 2`, `TRACE_HEADER_MEMORY` / `TRACE_FOOTER_MEMORY` are used instead -- these additionally start `tracemalloc`, capture peak memory, and write to `_rlm_trace.peak_memory_bytes`. The `_rlm_trace` object is injected into the execution namespace by `execute_code()` / `execute_code_async()`.

### 3.9 `rlm_adk/state.py` — State Key Constants

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py`

Defines all string constants used as ADK session state keys. Key groupings:

| Group | Examples | Notes |
|---|---|---|
| Flow control | `APP_MAX_DEPTH`, `APP_MAX_ITERATIONS`, `CURRENT_DEPTH`, `ITERATION_COUNT`, `SHOULD_STOP`, `POLICY_VIOLATION` | Set at invocation start |
| REPL execution | `LAST_REPL_RESULT`, `FINAL_ANSWER`, `MESSAGE_HISTORY` | Written by REPLTool, orchestrator |
| Dynamic instruction | `DYN_REPO_URL = "repo_url"`, `DYN_ROOT_PROMPT = "root_prompt"` | Match `{var?}` placeholders in `RLM_DYNAMIC_INSTRUCTION` |
| Per-invocation accounting | `REASONING_PROMPT_CHARS`, `REASONING_INPUT_TOKENS`, `WORKER_DISPATCH_COUNT` | Written by callbacks |
| Observability | `OBS_TOTAL_INPUT_TOKENS`, `OBS_WORKER_DISPATCH_LATENCY_MS`, etc. | Written by plugins/dispatch |
| Caching | `CACHE_STORE`, `CACHE_HIT_COUNT`, `CACHE_MISS_COUNT` | Written by CachePlugin |
| Artifacts | `ARTIFACT_SAVE_COUNT`, `OBS_ARTIFACT_SAVES` | Written by artifact helpers |
| Request | `REQUEST_ID`, `IDEMPOTENCY_KEY` | Set at invocation start |

**ADK state key prefix scoping:**
- No prefix: session scope (persists within a session).
- `user:` prefix: user scope (persists across sessions for the same user).
- `app:` prefix: application scope (persists across all users/sessions).
- `cache:`, `obs:`, `migration:` are naming conventions only — they are session-scoped despite the colon separator.

**Depth-scoped keys** (lines 111-128): `DEPTH_SCOPED_KEYS` is the set of keys that need independent state per recursion depth (`MESSAGE_HISTORY`, `ITERATION_COUNT`, `FINAL_ANSWER`, `LAST_REPL_RESULT`, `SHOULD_STOP`). `depth_key(key, depth)` appends `@dN` for `N > 0`, returning the original key unchanged at depth 0.

**`obs_model_usage_key(model_name)`** (lines 131-133): Helper function returning `f"obs:model_usage:{model_name}"` for per-model usage tracking keys.

### 3.10 `rlm_adk/types.py` — Data Types

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py`

**`LLMResult(str)`** (lines 50-80): A `str` subclass that carries worker call metadata as instance attributes: `error: bool`, `error_category: str | None`, `http_status: int | None`, `finish_reason: str | None`, `input_tokens: int`, `output_tokens: int`, `model: str | None`, `wall_time_ms: float`, `parsed: dict | None`. Created via `__new__` which calls `super().__new__(cls, text)` and sets kwargs as attributes. Backward-compatible with all `str` operations. REPL code can inspect `result.error`, `result.error_category`, `result.parsed`.

**`ReasoningOutput(BaseModel)`** (lines 12-22): Pydantic model for structured reasoning output. Fields: `final_answer: str`, `reasoning_summary: str`. Intended for use as `output_schema` on the reasoning agent, though the current orchestrator does not set it there (to avoid ADK's postprocessor mis-handling plain text responses).

**`REPLResult`** (lines 164-202): Dataclass holding `stdout`, `stderr`, `locals`, `execution_time`, `llm_calls: list[RLMChatCompletion]`, `trace: dict | None`. Returned by both `execute_code()` and `execute_code_async()`.

**`RLMChatCompletion`** (lines 134-162): Dataclass recording a single LLM call: `root_model`, `prompt`, `response`, `usage_summary`, `execution_time`. Accumulated in `repl._pending_llm_calls` for call log sinks.

**`ModelUsageSummary`** / **`UsageSummary`** (lines 87-128): Dataclasses for token cost tracking, serializable to/from dict.

**`_serialize_value(value)`** (lines 26-42): Module-level helper used by `REPLResult.to_dict()` to convert REPL namespace values to JSON-serializable representations. Handles primitives, modules, lists, dicts, callables, and falls back to `repr()`.

---

## 4. State Management

### AR-CRIT-001: No Direct ctx.session.state Writes in Dispatch Closures

The ADK `Runner` tracks state changes by inspecting `EventActions.state_delta` on yielded `Event` objects. Writing directly to `ctx.session.state[key] = value` inside dispatch closures bypasses this event tracking and can cause state to be lost, overwritten, or observed inconsistently across concurrent operations.

**Correct state write patterns:**

| Context | Correct Method |
|---|---|
| Orchestrator `_run_async_impl` | `yield Event(actions=EventActions(state_delta={key: val}))` |
| Reasoning callbacks | `callback_context.state[key] = val` |
| Worker callbacks | `callback_context.state[key] = val` |
| REPLTool `run_async` | `tool_context.state[key] = val` |
| Plugin callbacks | `callback_context.state[key] = val` or `invocation_context.session.state[key] = val` |

**The flush_fn pattern** solves the problem for dispatch closures:

1. `create_dispatch_closures()` returns local accumulators `_acc_dispatch_count`, `_acc_batch_dispatches`, `_acc_latencies` as closure-captured `nonlocal` variables.
2. Each `llm_query_batched_async()` call increments these accumulators.
3. `flush_fn()` reads the accumulators into a dict and resets them.
4. `REPLTool.run_async()` calls `self._flush_fn()` after each code execution and writes the returned dict into `tool_context.state` — which is the correct write path.
5. The orchestrator passes `flush_fn` to `REPLTool` at construction time.

**Worker result carrier pattern**: Worker results are read from agent object attributes (`worker._result`, `worker._result_ready`, `worker._result_error`, `worker._call_record`) set by callbacks, not from session state. This eliminates the "dirty state read" problem where one worker's state write could be overwritten by another.

### Depth-Scoped Keys

`depth_key(key, depth)` from `state.py` namespaces certain keys per recursion depth. At `depth=0` the key is unchanged; at `depth=N` it becomes `key@dN`. This prevents nested reasoning agents from trampling each other's `ITERATION_COUNT`, `FINAL_ANSWER`, etc. The current collapsed orchestrator runs at `depth=1`.

---

## 5. Dispatch Mechanism

### Worker Lifecycle per Dispatch Call

```
llm_query_async(prompt) called from REPL code
    |
    | (AST rewriter transformed this to: await llm_query_async(prompt))
    v
llm_query_batched_async([prompt])
    |
    v
worker = await worker_pool.acquire(model)   # get_nowait() or create on demand
worker._pending_prompt = prompt
worker._result = None
worker._result_ready = False
worker._result_error = False
    |
    v
if K == 1:
    asyncio.wait_for(_consume_events(worker.run_async(ctx)), timeout=180s)
else:
    parallel = ParallelAgent(sub_agents=[w1, w2, ...])
    asyncio.wait_for(_consume_events(parallel.run_async(ctx)), timeout=180s)
    |                       |
    |   (inside run_async)  v
[ADK calls worker_before_model callback]
    -> reads worker._pending_prompt
    -> sets llm_request.contents = [Content(role="user", parts=[Part(text=prompt)])]
    |
    v
[ADK calls Gemini API]
    |
    v
[ADK calls worker_after_model callback]
    -> extracts response text from llm_response.content.parts
    -> sets worker._result = response_text
    -> sets worker._result_ready = True
    -> sets worker._call_record = {prompt, response, tokens, model, ...}
    -> writes callback_context.state[output_key] = response_text
    |
    v
[_consume_events finishes draining the run_async iterator]
    |
    v
[dispatch closure reads worker._result, builds LLMResult]
    |
    v
finally block:
    worker._pending_prompt = None
    worker._result = None
    worker._result_error = False
    worker._call_record = None
    (if output_schema: reset output_schema, tools, callbacks, _structured_result)
    worker.parent_agent = None      # CRITICAL: allows worker reuse
    await worker_pool.release(worker, model)
    |
    v
return LLMResult(response_text, error=False, input_tokens=N, ...)
```

### Structured Output Dispatch (output_schema provided)

When `llm_query_async(prompt, output_schema=MySchema)` is called:

1. `worker.output_schema = MySchema` and `worker.tools = [SetModelResponseTool(MySchema)]`.
2. `after_tool_callback` and `on_tool_error_callback` are set from `make_worker_tool_callbacks()`.
3. After dispatch, `worker._structured_result` holds the validated dict (set by `after_tool_cb` when `set_model_response` succeeds).
4. The dispatch closure serializes `_structured_result` to JSON as `result_text` and sets `LLMResult.parsed = structured`.
5. A BUG-13 monkey-patch in `worker_retry.py` prevents ADK's `_output_schema_processor.get_structured_model_response()` from prematurely terminating the worker loop when `ReflectAndRetryToolPlugin` emits a `ToolFailureResponse` (retry guidance dict containing `"response_type": REFLECT_AND_RETRY_RESPONSE_TYPE`).
6. Wiring is cleaned up in the `finally` block: `worker.output_schema = None`, `worker.tools = []`, callbacks reset.

### Timeout and Error Handling

- Per-dispatch timeout: `RLM_WORKER_TIMEOUT` env var (default 180s) via `asyncio.wait_for`.
- On `asyncio.TimeoutError`: sets `worker._result = f"[Worker {name} timed out ...]"`, `_result_ready = True`, `_result_error = True`.
- On LLM error during dispatch: `worker_on_model_error` sets `_result_error = True`, `_call_record["error_category"]`, and returns a synthetic `LlmResponse` to prevent `ParallelAgent` from crashing.
- Dispatch closure catches any remaining exceptions and appends error `LLMResult` objects for the affected batch slice.

---

## 6. Callback Architecture

ADK's callback execution order: Plugin callbacks run first (in registration order), then agent-level callbacks. If any callback returns a non-None value, the chain is short-circuited.

### 6.1 Reasoning Agent Callbacks

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py`

**`reasoning_before_model(callback_context, llm_request)`** (lines 65-125):

Purpose: Merge dynamic instruction into `system_instruction`.

When both `static_instruction` and `instruction` are set on an `LlmAgent`, ADK:
- Places `static_instruction` content into `system_instruction` on the `LlmRequest`.
- Resolves the `instruction` template (substituting `{var?}` placeholders from session state) and appends the result to `contents` as user content.

This callback:
1. Extracts the current `system_instruction` text from `llm_request.config.system_instruction`.
2. Extracts the resolved dynamic instruction from `llm_request.contents`.
3. Appends dynamic instruction to `system_instruction` text.
4. Writes the merged text back to `llm_request.config.system_instruction`.
5. Records timing: `callback_context.state[REASONING_CALL_START] = time.perf_counter()`.
6. Records token accounting: `REASONING_PROMPT_CHARS`, `REASONING_SYSTEM_CHARS`, `REASONING_CONTENT_COUNT`, `REASONING_HISTORY_MSG_COUNT`, `CONTEXT_WINDOW_SNAPSHOT`.
7. Returns `None` (does not short-circuit).

**`reasoning_after_model(callback_context, llm_response)`** (lines 128-147):

Purpose: Record token usage from response metadata.

Reads `llm_response.usage_metadata.prompt_token_count` and `candidates_token_count`. Writes to `REASONING_INPUT_TOKENS` and `REASONING_OUTPUT_TOKENS`. Returns `None` — observe only.

### 6.2 Worker Callbacks

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker.py`

**`worker_before_model(callback_context, llm_request)`** (lines 40-60):

Reads `callback_context._invocation_context.agent._pending_prompt` (the prompt injected by the dispatch closure). Constructs `llm_request.contents = [Content(role="user", parts=[Part.from_text(pending_prompt)])]`. Returns `None`.

Note: Several callback and plugin functions access ADK's private `_invocation_context` attribute (including `worker_after_model`, `worker_on_model_error`, and `ContextWindowSnapshotPlugin`). This is required because callbacks receive `CallbackContext`, not the agent directly.

**`worker_after_model(callback_context, llm_response)`** (lines 63-108):

Extracts response text from `llm_response.content.parts` (skipping parts with `part.thought=True`). Reads the agent via `callback_context._invocation_context.agent`. Sets:
- `agent._result = response_text`
- `agent._result_ready = True`
- `agent._call_record = {prompt, response, input_tokens, output_tokens, model, finish_reason, error}`
- `callback_context.state[output_key] = response_text` (for ADK persistence)

Returns `None`.

**`worker_on_model_error(callback_context, llm_request, error)`** (lines 111-147):

Error isolation for `ParallelAgent`. Sets `agent._result`, `agent._result_ready = True`, `agent._result_error = True`, and `agent._call_record` with error metadata. Returns a synthetic `LlmResponse` with the error message as content text. This allows the agent to complete normally within `ParallelAgent` without crashing the entire batch.

**`_classify_error(error)`** (lines 22-37): Type-based classification into: `TIMEOUT`, `RATE_LIMIT` (429), `AUTH` (401/403), `SERVER` (5xx), `CLIENT` (4xx), `NETWORK` (`ConnectionError`/`OSError`), `UNKNOWN`.

### 6.3 Structured Output Callbacks

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker_retry.py`

**`WorkerRetryPlugin(ReflectAndRetryToolPlugin)`** (lines 36-66): Extends ADK's `ReflectAndRetryToolPlugin`. Overrides `extract_error_from_result()` to detect empty string values in `set_model_response` tool args. Returns an error dict `{"error": "Empty value", "details": ...}` when a field is empty; returns `None` otherwise (indicating success).

**`make_worker_tool_callbacks(max_retries=2)`** (lines 69-142): Factory returning `(after_tool_cb, on_tool_error_cb)`.

`after_tool_cb(tool, args, tool_context, tool_response)`:
- If `tool.name == "set_model_response"` and `tool_response` is a dict: stores on `agent._structured_result`.
- Delegates to `plugin.after_tool_callback(tool=tool, tool_args=args, tool_context=tool_context, result=tool_response)` for validation and retry signaling.

`on_tool_error_cb(tool, args, tool_context, error)`:
- Only intercepts `set_model_response` errors; returns `None` for other tools.
- Delegates to `plugin.on_tool_error_callback(...)`.

Note: ADK calls these with `args=` keyword but the plugin expects `tool_args=`; the wrapper translates between the two conventions.

**BUG-13 patch** (`_patch_output_schema_postprocessor`, lines 162-200): Installed at module import time. Wraps `google.adk.flows.llm_flows._output_schema_processor.get_structured_model_response` to return `None` when the parsed result dict contains `"response_type": REFLECT_AND_RETRY_RESPONSE_TYPE`. This prevents ADK from treating retry guidance as a valid structured output response and terminating the worker loop prematurely.

---

## 7. Plugin System

All plugins extend `google.adk.plugins.base_plugin.BasePlugin`. Plugins are registered on the `App` and apply globally to all agents. They run before agent-level callbacks. A plugin returning a non-None value from a callback short-circuits all remaining plugins and agent callbacks for that hook.

### 7.1 ObservabilityPlugin

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py`

**Always included.** Observe-only — never returns a non-None value. Catches and suppresses all errors internally.

| Callback | Action |
|---|---|
| `before_agent_callback` | Sets `INVOCATION_START_TIME` if not set. Logs agent entry. |
| `after_agent_callback` | Logs agent exit. |
| `before_model_callback` | Logs model call start. |
| `after_model_callback` | Increments `OBS_TOTAL_CALLS`, accumulates `OBS_TOTAL_INPUT_TOKENS`, `OBS_TOTAL_OUTPUT_TOKENS`, per-model usage (`obs:model_usage:{model}`), finish_reason counters, per-iteration token breakdown list (`OBS_PER_ITERATION_TOKEN_BREAKDOWN`). |
| `before_tool_callback` | Increments `OBS_TOOL_INVOCATION_SUMMARY[tool_name]`. |
| `on_event_callback` | Logs state delta events. Tracks `OBS_ARTIFACT_SAVES` from `event.actions.artifact_delta`. |
| `after_run_callback` | Computes `OBS_TOTAL_EXECUTION_TIME`. Sets `USER_LAST_SUCCESSFUL_CALL_ID`. Logs completion summary. |

### 7.2 DebugLoggingPlugin

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/debug_logging.py`

**Enabled by default** (can be disabled by `debug=False` and no `RLM_ADK_DEBUG` env var). Observe-only. Accumulates trace entries in `self._traces: list[dict]` and writes to YAML at `after_run_callback`.

| Callback | Action |
|---|---|
| `before_agent_callback` | Prints `[RLM] agent=... iter=... event=before_agent`. Appends trace entry with state snapshot. |
| `after_agent_callback` | Prints `[RLM] ... event=after_agent`. |
| `before_model_callback` | Prints one-line summary with `iter`, `model`, `prompt_chars`, `system_chars`, `history_msgs`. Appends trace with prompt preview and token accounting. |
| `after_model_callback` | Prints `[RLM] iter=... response agent=... tokens_in=... tokens_out=...`. Appends trace with response preview. |
| `on_model_error_callback` | Prints `[RLM_ERR] ...`. Appends error trace entry. |
| `before_tool_callback` | Appends tool invocation trace. |
| `after_tool_callback` | Appends tool result trace (truncated to 500 chars). |
| `on_event_callback` | Prints state delta keys; prints artifact delta filenames. Appends event trace. |
| `after_run_callback` | Prints run summary line. Dumps all traces to YAML at `output_path` (default `rlm_adk_debug.yaml`). Clears `self._traces`. |

### 7.3 SqliteTracingPlugin

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py`

**Enabled by default.** Writes span-like telemetry to `.adk/traces.db`.

Schema: two tables — `traces` (one row per invocation) and `spans` (one row per callback event). Agent spans form a stack (`_agent_span_stack`) for parent-child tracking. Model spans are paired by model name key (`_pending_model_spans`). Tool spans are paired by tool name (`_pending_tool_spans`).

| Callback | SQLite operation |
|---|---|
| `before_run_callback` | INSERT into `traces` (status='running'). |
| `after_run_callback` | UPDATE `traces` with final stats from session state. |
| `before_agent_callback` | INSERT span (operation='agent'). Push span_id to stack. |
| `after_agent_callback` | UPDATE span end_time. Pop from stack. |
| `before_model_callback` | INSERT span (operation='model_call') with model name and num_contents. |
| `after_model_callback` | UPDATE span end_time with token counts. |
| `on_model_error_callback` | UPDATE span status='error' with error details. |
| `before_tool_callback` | INSERT span (operation='tool_call'). |
| `after_tool_callback` | UPDATE span end_time with result preview. |
| `on_event_callback` | INSERT span for artifact saves (operation='artifact_save'). |

### 7.4 LangfuseTracingPlugin

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/langfuse_tracing.py`

**Opt-in** via `langfuse=True` or `RLM_ADK_LANGFUSE=1`. A thin wrapper — all actual span creation is handled by `openinference-instrumentation-google-adk` (Google ADK OpenInference instrumentor). The plugin's sole role is to call `GoogleADKInstrumentor().instrument()` once at construction time after verifying Langfuse credentials via `client.auth_check()`. Implements no callback methods itself — the instrumentor hooks into ADK's event system directly at the OTel level. Safe to include with missing env vars — initialization is skipped with a warning.

Required env vars: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`.

### 7.5 REPLTracingPlugin

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py`

**Opt-in** when `RLM_REPL_TRACE > 0`. Accumulates per-iteration REPL trace data in `self._traces_by_iteration: dict[int, Any]`.

| Callback | Action |
|---|---|
| `on_event_callback` | Reads `LAST_REPL_RESULT` from `event.actions.state_delta`. If it contains a `trace_summary` key, stores it under the iteration number. |
| `after_run_callback` | Saves accumulated traces as `repl_traces.json` artifact via `artifact_service.save_artifact()`. |

### 7.6 CachePlugin

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/cache.py`

**Opt-in** — not included in the default plugin list. LLM response cache using the before_model/after_model intervene pattern.

**`before_model_callback`**: Computes a SHA-256 fingerprint of the `LlmRequest` (model name + normalized content text + system instruction hash + temperature). Stores fingerprint in `state["cache_pending_fingerprint"]`. Checks `state[CACHE_STORE]` for a matching entry within `ttl_seconds` (default 300s). On hit: returns the cached `LlmResponse` (short-circuits the actual model call). On miss: returns `None`.

**`after_model_callback`**: Reads the pending fingerprint. Stores the response in `CACHE_STORE[fingerprint]` with a timestamp. If `len(cache_store) > max_entries` (default 1000): evicts the oldest entries by timestamp (LRU-by-age).

Cache state is stored in session state (`CACHE_STORE`), so it persists within a session but not across sessions (unless session state is persisted to SQLite, in which case it does persist across invocations within the same session).

### 7.7 PolicyPlugin

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/policy.py`

**Always included.** Auth/safety guardrails using the intervene pattern — can short-circuit model calls and tool invocations when policy is violated.

| Callback | Action |
|---|---|
| `on_user_message_callback` | Generates `REQUEST_ID` (uuid) and `IDEMPOTENCY_KEY` (SHA-256 of user_id + session_id + message text). |
| `before_model_callback` | Checks prompt text against `blocked_patterns` regex list. On match: sets `POLICY_VIOLATION` in state, returns an `LlmResponse` with violation message (short-circuits the model call). |
| `before_tool_callback` | Checks `tool.required_auth_level` against `state["user:auth_level"]`. Level hierarchy: admin > user > guest. Returns error dict if the user's level is insufficient. |

Constructor arg: `blocked_patterns: list[str] | None` — compiled to `re.compile()` patterns at init time.

### 7.8 ContextWindowSnapshotPlugin

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py`

**Opt-in** via `RLM_CONTEXT_SNAPSHOTS=1`. Captures full context window decomposition to JSONL files at each LLM call.

| Callback | Action |
|---|---|
| `before_model_callback` | Stashes a mutable reference to the `LlmRequest` keyed by agent name (concurrent worker safety via `asyncio.Lock`). |
| `after_model_callback` | Decomposes the (now-mutated) `LlmRequest` into typed chunks (`static_instruction`, `dynamic_instruction`, `user_prompt`, `repl_code`, `repl_output`, `context_var`, `llm_response`, `worker_prompt`). Pairs with `usage_metadata` token counts. Writes context decomposition to `.adk/context_snapshots.jsonl` and model outputs to `.adk/model_outputs.jsonl`. |
| `on_model_error_callback` | Flushes the pending entry with an error flag set. |
| `after_run_callback` | Closes JSONL file handles. |

Architecture note: Plugins fire BEFORE agent callbacks. The plugin stores a reference in `before_model_callback`, then reads the mutated request in `after_model_callback` (after agent callbacks have run and populated the request).

### 7.9 MigrationPlugin

**File:** `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/migration.py`

**Opt-in** via `RLM_MIGRATION_ENABLED=1` + `RLM_POSTGRES_URL`. End-of-session batch migration from SQLite to PostgreSQL. Safe to include when PostgreSQL is not configured — all callbacks become no-ops.

| Callback | Action |
|---|---|
| `after_run_callback` | Reads session + events from local SQLite (synchronous `sqlite3`, separate from ADK's `aiosqlite` connections). Upserts session to Postgres. Batch-inserts events with `ON CONFLICT DO NOTHING`. Sets `MIGRATION_STATUS` / `MIGRATION_TIMESTAMP` in state. Optionally prunes old local sessions (FIFO, configurable retention count). On failure: sets `MIGRATION_STATUS=failed` and `MIGRATION_ERROR`. |

Constructor args: `postgres_url: str | None` (falls back to `RLM_POSTGRES_URL`), `sqlite_db_path: str | None` (falls back to `RLM_SESSION_DB`, then `.adk/session.db`), `retention_count: int | None` (falls back to `RLM_MIGRATION_RETENTION`, then `50`; set to `0` to disable pruning).

Env vars: `RLM_MIGRATION_ENABLED`, `RLM_POSTGRES_URL`, `RLM_SESSION_DB`, `RLM_MIGRATION_RETENTION`.

---

## 8. Key Invariants

### 8.1 State Write Discipline (AR-CRIT-001)

Direct writes to `ctx.session.state[key] = value` inside dispatch closures in `dispatch.py` are forbidden. The closure-captured local accumulators (`_acc_dispatch_count`, `_acc_batch_dispatches`, `_acc_latencies`) are the only state tracked during dispatch. They are flushed into session state via `flush_fn()` called from `REPLTool.run_async()`, which writes through `tool_context.state` — the correct event-tracked path.

### 8.2 Worker parent_agent Clearing

ADK's `ParallelAgent` sets `parent_agent` on each sub-agent in `model_post_init`. If a worker already has `parent_agent` set when it is placed into a new `ParallelAgent`, ADK raises a `ValueError`. The dispatch closure's `finally` block always executes `worker.parent_agent = None` before `worker_pool.release()`. This is critical for worker reuse across invocations and across batch calls.

### 8.3 Pydantic Model Constraints

`LlmAgent` and `RLMOrchestratorAgent` are Pydantic models. Two consequences:

1. Dynamic attributes cannot be set via normal assignment on Pydantic model instances. The dispatch closure uses `worker._pending_prompt = value` (which works because Pydantic allows extra dynamic attributes for Python instances, just not field validation). For Pydantic-declared fields, `object.__setattr__(agent, field_name, value)` is required — used in the orchestrator to wire `tools` and `include_contents` at runtime.

2. The orchestrator itself cannot use `MagicMock` as field values in tests. Tests must create real `LlmAgent` instances and patch methods directly.

### 8.4 include_contents = "default" Always

The reasoning agent always uses `include_contents="default"`. ADK manages the full tool call/response history (the sequence of `[call LLM → function call event → tool execution → function response event → call LLM again]`). If `include_contents="none"` were used, the model would have no history and could not continue reasoning across tool calls.

Workers use `include_contents="none"` because they are stateless: each worker receives exactly one prompt via `worker_before_model` and produces one response. No history is needed or desired.

### 8.5 No temp: Prefix on State Keys

ADK's `Runner` strips keys with the `temp:` prefix from the yielded event stream. All worker state keys (dispatch counts, latencies, etc.) must not use the `temp:` prefix, or they will be silently dropped and never committed to session state.

### 8.6 Tool Wiring at Runtime

The orchestrator wires `tools=[repl_tool]` onto `reasoning_agent` in `_run_async_impl()` before delegation, and removes them in the `finally` block. This is necessary because:
1. The `REPLTool` instance must be created fresh per invocation (it holds per-invocation state: `_call_count`, `trace_holder`, `flush_fn`).
2. The `flush_fn` closure captures the current invocation's `WorkerPool` and `InvocationContext`.
3. `object.__setattr__` is required for this runtime mutation because `LlmAgent` is a Pydantic model.

---

## 9. Data Flow: End-to-End Execution

```
1. Caller invokes runner.run_async(user_id, session_id, new_message)
   |
2. ADK Runner starts invocation: creates InvocationContext, calls app plugins'
   before_run_callback (e.g., SqliteTracingPlugin creates trace row)
   |
3. Runner calls RLMOrchestratorAgent._run_async_impl(ctx)
   |
4. Orchestrator yields:
   Event(state_delta={CURRENT_DEPTH:1, ITERATION_COUNT:0, REQUEST_ID:uuid})
   Event(content=Content(role="user", parts=[Part(text=root_prompt)]))
   |
5. Orchestrator calls reasoning_agent.run_async(ctx) inside a retry loop
   (up to RLM_LLM_MAX_RETRIES attempts with exponential backoff for
   transient errors: ServerError, ClientError with retryable status codes,
   TimeoutError, ConnectionError, OSError, httpx errors)
   |
6. ADK LlmAgent loop begins:
   a. Plugin before_model_callbacks fire (Observability, Debug, SqliteTracing, ...)
   b. reasoning_before_model fires: merges dynamic→system_instruction, records metrics
   c. ADK sends LlmRequest to Gemini API (gemini-3.1-pro-preview)
   d. Gemini returns: either a text response OR a function_call for execute_code
   e. Plugin after_model_callbacks fire
   f. reasoning_after_model fires: records token usage
   |
7. If Gemini returns function_call(execute_code, {code: "..."}):
   a. ADK calls REPLTool.run_async(args={code:...}, tool_context)
   b. REPLTool checks has_llm_calls(code):
      - If True: rewrite_for_async(code) -> compile -> exec -> await _repl_exec()
        [REPL code calls await llm_query_async("sub-prompt")]
          -> llm_query_batched_async(["sub-prompt"])
             -> worker_pool.acquire() -> inject prompt -> worker.run_async(ctx)
                -> worker_before_model: sets llm_request.contents from _pending_prompt
                -> Gemini API called for worker
                -> worker_after_model: stores result on worker._result
             -> read worker._result -> LLMResult(text)
      - If False: repl.execute_code(code) [synchronous]
   c. REPLTool calls flush_fn() -> writes dispatch accumulators to tool_context.state
   d. REPLTool writes LAST_REPL_RESULT to tool_context.state
   e. Returns {stdout, stderr, variables, llm_calls_made, call_number}
   f. ADK appends function_response event to conversation history
   g. Loop returns to step 6a (model is called again with the tool result)
   |
8. When Gemini returns a final text response (no function call):
   ADK's LlmAgent loop exits; reasoning_agent.run_async(ctx) completes
   ADK writes final text to session.state["reasoning_output"] via output_key
   |
9. Orchestrator reads ctx.session.state["reasoning_output"]
   Parses as JSON (ReasoningOutput) or plain text
   Calls save_final_answer(ctx, answer)
   Yields Event(state_delta={FINAL_ANSWER: answer, SHOULD_STOP: True})
   Yields Event(content=Content(role="model", parts=[Part(text=answer)]))
   |
10. ADK Runner processes all events, commits state via SqliteSessionService,
    saves artifacts via FileArtifactService
    Calls after_run_callback on plugins (Observability logs summary, Debug writes YAML,
    SqliteTracing finalizes trace row, REPLTracing saves artifact)
    |
11. Events propagate to caller via async iteration of runner.run_async()
```

---

## 10. Environment Variables

| Variable | Default | Description |
|---|---|---|
| `RLM_ADK_MODEL` | `gemini-3.1-pro-preview` | Model for ADK CLI-discovered `app` symbol |
| `RLM_MAX_ITERATIONS` | `30` | Max `execute_code` calls per invocation |
| `RLM_LLM_MAX_RETRIES` | `3` | Transient error retries in orchestrator |
| `RLM_LLM_RETRY_DELAY` | `5.0` | Base delay (seconds) for exponential backoff |
| `RLM_MAX_CONCURRENT_WORKERS` | `4` | Max parallel workers per batch |
| `RLM_WORKER_TIMEOUT` | `180` | Per-dispatch timeout in seconds |
| `RLM_WORKER_HTTP_TIMEOUT` | `120000` | Worker HTTP timeout in milliseconds |
| `RLM_REASONING_HTTP_TIMEOUT` | `300000` | Reasoning agent HTTP timeout in milliseconds |
| `RLM_REPL_TRACE` | `0` | REPL trace level (0=off, 1=timing, 2=+memory) |
| `RLM_SESSION_DB` | `.adk/session.db` | SQLite session database path |
| `RLM_ADK_DEBUG` | on by default | Plugin on by default (`debug=True`); env var is redundant force-enable. Pass `debug=False` and leave unset to disable |
| `RLM_ADK_SQLITE_TRACING` | on by default | Plugin on by default (`sqlite_tracing=True`); env var is redundant force-enable |
| `RLM_ADK_LANGFUSE` | unset | Set to `1`/`true` to enable LangfuseTracingPlugin |
| `RLM_CONTEXT_SNAPSHOTS` | unset | Set to `1`/`true` to enable ContextWindowSnapshotPlugin |
| `RLM_MIGRATION_ENABLED` | unset | Set to `1`/`true` to enable MigrationPlugin |
| `RLM_POSTGRES_URL` | unset | SQLAlchemy async PostgreSQL URL (e.g., `postgresql+asyncpg://user:pass@host/db`) |
| `RLM_MIGRATION_RETENTION` | `50` | Number of sessions to retain locally after migration (0 disables pruning) |
| `LANGFUSE_PUBLIC_KEY` | required | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | required | Langfuse project secret key |
| `LANGFUSE_BASE_URL` | required | Langfuse instance URL |

---

## 11. Essential Files Reference

| File | Role |
|---|---|
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/__init__.py` | Public API exports |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py` | Factory functions: Runner, App, orchestrator, reasoning agent |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py` | `RLMOrchestratorAgent`: collapsed orchestrator, invocation lifecycle |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py` | `WorkerPool`, `create_dispatch_closures`, `llm_query_async`, `flush_fn` |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py` | `REPLTool`: ADK `BaseTool` wrapping `LocalREPL` |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/local_repl.py` | `LocalREPL`: sandboxed Python execution, output capture, async path |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/ast_rewriter.py` | Sync-to-async bridge: `has_llm_calls`, `rewrite_for_async` |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py` | `REPLTrace`, `DataFlowTracker`, trace headers |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py` | All state key constants, `depth_key()`, `DEPTH_SCOPED_KEYS` |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/types.py` | `LLMResult`, `ReasoningOutput`, `REPLResult`, `RLMChatCompletion` |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py` | `reasoning_before_model`: instruction merge, token accounting |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker.py` | `worker_before_model`: prompt injection; `worker_after_model`: result carrier; `worker_on_model_error`: isolation |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker_retry.py` | `WorkerRetryPlugin`, `make_worker_tool_callbacks`, BUG-13 patch |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py` | Token/call/artifact metrics (always on) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/debug_logging.py` | Full interaction trace to YAML (default on) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py` | Span telemetry to `.adk/traces.db` (default on) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/langfuse_tracing.py` | OTel tracing to Langfuse via `GoogleADKInstrumentor` (opt-in) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py` | REPL traces saved as JSON artifact (opt-in) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/cache.py` | LLM response cache with TTL and LRU eviction (opt-in) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py` | `ContextWindowSnapshotPlugin`: full context window decomposition to JSONL (opt-in) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/policy.py` | `PolicyPlugin`: auth/safety guardrails (before_model, before_tool, on_user_message) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/migration.py` | `MigrationPlugin`: end-of-session SQLite-to-PostgreSQL batch migration (opt-in) |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/artifacts.py` | Artifact helper functions: `save_final_answer`, convenience wrappers |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/utils/prompts.py` | `RLM_STATIC_INSTRUCTION`, `RLM_DYNAMIC_INSTRUCTION` prompt templates |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/utils/parsing.py` | `find_final_answer`: FINAL()/FINAL_VAR() pattern extraction |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/repomix_helpers.py` | `probe_repo`, `pack_repo`, `shard_repo` injected into REPL namespace |
| `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/repomix_skill.py` | `build_skill_instruction_block`: appended to static instruction |

---

*Document generated from source code at commit `c809837` (branch `main`).*
