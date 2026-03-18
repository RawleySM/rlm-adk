<!-- validated: 2026-03-12 -->

# RLM-ADK Core Loop Reference

The core loop: an LLM reasoning agent writes Python code, which executes in a sandboxed REPL. That code can call `llm_query()` to spawn child agents, which themselves get their own REPL -- recursion to arbitrary depth. ADK's native tool-calling loop drives everything; the orchestrator does not manually iterate.

---

## 1. RLMOrchestratorAgent

**File:** `rlm_adk/orchestrator.py` (class at line 188)

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
| `output_schema` | `Any` | `None` | Pydantic schema for structured output |
| `instruction_router` | `Any` | `None` | `Callable[[int, int], str]` for dynamic skill instructions |

The single entry point is `_run_async_impl(ctx) -> AsyncGenerator[Event, None]`.

---

## 2. Collapsed Iteration Pattern (Phase 5)

The orchestrator does NOT manually iterate. It wires tools onto the reasoning agent at runtime, then delegates entirely to ADK's native tool-calling loop.

### What `_run_async_impl` does (orchestrator.py, lines 216-481)

```
1. Create LocalREPL (or reuse self.repl)
2. Create dispatch closures -> (llm_query_async, llm_query_batched_async, flush_fn)
   (passes instruction_router + fanout_idx for skill instruction routing)
3. Inject async query fns + skill helpers into REPL globals
4. Build REPLTool(repl, max_calls, flush_fn)
5. Build SetModelResponseTool(output_schema)
6. Wire both onto reasoning_agent.tools via object.__setattr__
6b. If instruction_router: compute skill_instruction, write DYN_SKILL_INSTRUCTION to initial state,
    wire before_agent_callback on reasoning_agent to seed callback_context.state
7. Yield initial state delta Event (CURRENT_DEPTH, ITERATION_COUNT, REQUEST_ID)
8. Yield user Content Event with root_prompt
9. Delegate: async for event in reasoning_agent.run_async(ctx): yield event
10. Extract final answer from output_key in session state
11. Yield final Content Event with answer (or error)
12. Cleanup: clear tools, callbacks; destroy REPL if not persistent
```

ADK's loop (step 9) handles: model invocation, tool call detection, tool execution, retry on schema validation failure, and loop termination when `set_model_response` succeeds.

Transient HTTP errors (408, 429, 500-504) are retried with exponential backoff: `RLM_LLM_MAX_RETRIES` (default 3), `RLM_LLM_RETRY_DELAY` (default 5.0s).

---

## 3. REPLTool

**File:** `rlm_adk/tools/repl_tool.py` (class at line 40)

ADK `BaseTool` with `name="execute_code"`. The model calls it via function calling.

### Constructor

```
REPLTool(
    repl: LocalREPL,
    max_calls: int = 60,
    trace_holder: list | None = None,
    flush_fn: Callable[[], dict] | None = None,
    depth: int = 0,
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

### Execution flow inside run_async (lines 93-277)

```
1. Persist submitted code metadata to tool_context.state
2. Save code as versioned artifact
3. Increment call count; if > max_calls, return error immediately
4. Expand synthetic skill imports (expand_skill_imports())
   -> If expansion occurred, write REPL_EXPANDED_CODE, REPL_EXPANDED_CODE_HASH,
      REPL_SKILL_EXPANSION_META, REPL_DID_EXPAND to tool_context.state
5. AST detection: has_llm_calls(expanded_code)?
   YES -> rewrite_for_async(expanded_code) -> compile -> exec -> await _repl_exec()
          Uses repl.execute_code_async()
   NO  -> repl.execute_code() (sync, with timeout)
6. Call flush_fn() to snapshot dispatch accumulators into tool_context.state
7. Write LAST_REPL_RESULT summary dict to tool_context.state
8. If output > summarization_threshold, set skip_summarization = True
9. Filter locals to JSON-serializable values and return
```

### Skill Import Expansion Pass (Step 4)

**File:** `rlm_adk/repl/skill_registry.py`

Before AST analysis, REPLTool calls `expand_skill_imports(code)` from the `SkillRegistry` singleton. This expansion pass detects synthetic `from rlm_repl_skills.<module> import <symbol>` statements in the submitted code and replaces them with inline source blocks.

The expansion pipeline:

1. Parse submitted code to AST.
2. Detect `ImportFrom` nodes targeting the `rlm_repl_skills.*` namespace.
3. If none found, return the original code unchanged (`did_expand=False`).
4. Resolve requested symbols and their transitive dependencies via the registry.
5. Topologically sort all required exports by their `requires` dependency graph.
6. Check for name conflicts between expanded symbols and user-defined names in the submitted code (hard error on conflict).
7. Reassemble: normal imports first, then skill source blocks (with `# --- skill: module.name ---` markers), then remaining user code.

The expanded code is what flows into `has_llm_calls()` and `rewrite_for_async()`. This makes `llm_query()` calls inside skill source visible to the AST rewriter, which would otherwise miss them if they were hidden behind a runtime import. The original submitted code is preserved separately for observability (see `REPL_SUBMITTED_CODE` vs `REPL_EXPANDED_CODE` in state).

### Call limit enforcement

When `call_count > max_calls`, returns `stderr: "REPL call limit reached. Submit your final answer now."` Default is 60 for REPLTool constructor, but the orchestrator passes `max_iterations` (default 30 from `RLM_MAX_ITERATIONS` env var).

On `CancelledError` or `Exception`: flushes accumulators, writes partial `LAST_REPL_RESULT`, returns error in `stderr`. The tool never raises -- always returns a dict so ADK can continue.

---

## 4. LocalREPL & Execution Engine

**Files:** `rlm_adk/repl/local_repl.py` and `rlm_adk/repl/ipython_executor.py`

Persistent Python namespace with safe builtins and async LM dispatch hooks. While `LocalREPL` manages the namespace and safe builtins, the actual execution of code is delegated to the `IPythonDebugExecutor` engine.

### IPythonDebugExecutor (`ipython_executor.py`)

This backend engine handles the complex mechanics of execution:
- **IPython Integration:** Supports rich IPython display outputs and magic commands (if enabled).
- **Sync/Async Execution:** Manages the threading/event loop contexts for running sync code with timeouts vs. awaiting AST-rewritten async code.
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
| `execute_code_async` | `(code, repl_exec_fn, trace?) -> REPLResult` | Async execution for AST-rewritten code |
| `set_llm_query_fns` | `(llm_query_fn, llm_query_batched_fn)` | Set sync query fns (always raises in ADK mode) |
| `set_async_llm_query_fns` | `(llm_query_async_fn, llm_query_batched_async_fn)` | Set async query fns used by rewritten code |
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
| `llm_query(prompt, ...)` | Sync stub that raises RuntimeError (AST rewriter converts to async) |
| `llm_query_async(prompt, ...)` | Async dispatch to child orchestrator (injected by orchestrator) |
| `llm_query_batched(prompts, ...)` | Sync stub (same as llm_query) |
| `llm_query_batched_async(prompts, ...)` | Async batched dispatch (injected by orchestrator) |
| `probe_repo(source)` | Quick repo stats (files, chars, tokens) |
| `pack_repo(source)` | Entire repo as XML string |
| `shard_repo(source, max_bytes)` | Directory-aware repo chunking |
| `LLMResult` | The LLMResult class itself, for isinstance checks in REPL code |

### I/O isolation

Sync: context manager replaces `sys.stdout`/`sys.stderr` under `_EXEC_LOCK`. Async: task-local `ContextVar` buffers prevent cross-contamination. A custom `open()` resolves relative paths against `temp_dir` (no `os.chdir()`).

---

## 5. AST Rewriter

**File:** `rlm_adk/repl/ast_rewriter.py`

Transforms synchronous REPL code to async when it contains LM calls.

### Detection: `has_llm_calls(code) -> bool` (line 15)

Parses code to AST and walks for `ast.Call` nodes where `func.id` is `llm_query` or `llm_query_batched`. Returns `False` on `SyntaxError` (caught later during execution).

### Transformation: `rewrite_for_async(code) -> ast.Module` (line 161)

```
Step 1: Parse code to AST
Step 2: LlmCallRewriter transforms calls:
        llm_query(p)         -> await llm_query_async(p)
        llm_query_batched(ps) -> await llm_query_batched_async(ps)
Step 3: _promote_functions_to_async (transitive closure):
        If a FunctionDef contains await, convert to AsyncFunctionDef
        Wrap call sites of promoted functions with await
        Repeat until no new promotions needed
Step 4: Wrap entire body in: async def _repl_exec(): <body>; return locals()
Step 5: fix_missing_locations and return ast.Module
```

The caller (REPLTool) then: `compile(tree)` -> `exec(compiled, ns)` -> `ns["_repl_exec"]` -> `await repl.execute_code_async(code, repl_exec_fn)`.

### Example

`result = llm_query("Summarize")` becomes `result = await llm_query_async("Summarize")` inside `async def _repl_exec(): ... return locals()`.

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
  +-- Create dispatch closures (llm_query_async, flush_fn)
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
  |       |       +-- AST check -> sync or async execution
  |       |       +-- flush_fn() -> tool_context.state
  |       |       +-- Return {stdout, stderr, variables}
  |       |     Loop back to model invocation
  |       |
  |       +-- set_model_response:
  |             Validate against ReasoningOutput schema
  |             If valid: store in output_key, exit loop
  |             If invalid: retry (up to 2 retries)
  |
  v
Orchestrator extracts final answer from session state
  +-- _collect_reasoning_completion() normalizes the payload
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
1. REPLTool detects llm_query via has_llm_calls() -> True
2. AST rewriter: llm_query("sub-question") -> await llm_query_async("sub-question")
3. llm_query_async() closure (from dispatch.py) executes:
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
4. LLMResult returned to parent REPL as the await value
5. Parent code continues with the child's answer as a string
```

### Depth scoping

**File:** `rlm_adk/state.py` -- `depth_key(key, depth) -> str`

- `depth == 0`: returns `key` unchanged
- `depth > 0`: returns `f"{key}@d{depth}"`

This prevents state collisions when child orchestrators run within the same session. The `DEPTH_SCOPED_KEYS` set defines which keys require depth suffixes (iteration counts, final answers, token counts, submitted code metadata).

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

Create a `BasePlugin` subclass and wire it in `_default_plugins()` (`rlm_adk/agent.py`). Plugins are passed to `App(plugins=[...])` or `create_rlm_runner(plugins=[...])`.

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
| `create_reasoning_agent(model, ...)` | `LlmAgent` | Main reasoning sub-agent with callbacks, planner, and config |
| `create_rlm_orchestrator(model, ...)` | `RLMOrchestratorAgent` | Root orchestrator with reasoning agent + worker pool |
| `create_child_orchestrator(model, depth, prompt, ...)` | `RLMOrchestratorAgent` | Child orchestrator with condensed instructions |
| `create_rlm_app(model, ...)` | `App` | Full ADK App with plugins. The module-level `app` symbol is what `adk run` discovers. |
| `create_rlm_runner(model, ...)` | `Runner` | App + session service + artifact service. For programmatic/test use — the ADK CLI (`adk run rlm_adk`) is the primary entrypoint and wires services via `services.py` instead. |

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

- **2026-03-09 13:00** — Initial branch doc created from codebase exploration.
- **2026-03-09 13:15** — `orchestrator.py`: Added `fanout_idx` Pydantic field to `RLMOrchestratorAgent`, threaded to REPLTool and `save_final_answer()`.
- **2026-03-09 13:15** — `repl_tool.py`: Added `fanout_idx` to `REPLTool.__init__()`, threaded to `save_repl_code()` with depth and fanout_idx.
- **2026-03-09 13:15** — `agent.py`: Added `fanout_idx` to `create_child_orchestrator()`, passed to `RLMOrchestratorAgent`.
- **2026-03-10 10:22** — `repl_tool.py`: Documented skill import expansion pass (step 4) in REPL execution pipeline.
- **2026-03-12 14:37** — `orchestrator.py`: Added `instruction_router` field to `RLMOrchestratorAgent`. `_run_async_impl` now seeds `DYN_SKILL_INSTRUCTION` into initial state and wires `before_agent_callback` for skill instruction propagation.
- **2026-03-13 09:45** — `agent.py`: Added `instruction_router` parameter to `create_rlm_runner()` (pass-through to `create_rlm_app()`). New `services.py` registers CLI service factories; does not affect the core loop or factory chain.
- **2026-03-13 16:10** — `orchestrator.py`: Side-effect import of polya_narrative skill moved from `skills.repl_skills.polya_narrative` to `skills.polya_narrative_skill`. `agent.py`: `create_reasoning_agent()` now appends polya-narrative skill instructions to `static_instruction` alongside repomix (under `include_repomix` guard).
- **2026-03-17 13:49** — `repl_tool.py`: Added `_rlm_state` snapshot injection before code execution. Builds a fresh dict from `EXPOSED_STATE_KEYS` (depth-scoped where applicable) and injects into `repl.globals` each `run_async()` call. Read-only — AR-CRIT-001 compliant.

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
