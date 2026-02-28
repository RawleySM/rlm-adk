# REPL & Worker Flow: Post-Migration Architecture

This document covers the REPLTool architecture after the REPL-to-REPLTool
migration. The reasoning agent now uses ADK's native tool-calling protocol
instead of regex-parsed code blocks and sentinel functions.

---

## 1. Architecture Overview

### Before (Legacy)

The reasoning agent operated with `include_contents='none'`. The orchestrator
manually assembled `message_history` in state each iteration, and the
`before_model` callback injected it into `llm_request.contents`. The model
produced markdown fenced code blocks (`` ```repl ```) that the orchestrator
extracted via regex, executed in the REPL, and appended results back into the
history. Final answers were signaled by `FINAL()` / `FINAL_VAR()` sentinel
calls embedded in code blocks.

### After (Tool-Calling)

The reasoning agent operates with `include_contents='default'` and two ADK
tools:

1. **`execute_code`** -- an ADK `BaseTool` subclass (`REPLTool`) that wraps
   `LocalREPL` for Python execution.
2. **`set_model_response`** -- ADK's built-in structured output tool, injected
   automatically when `output_schema` is set on the agent.

ADK manages the full conversation history (user messages, model responses,
tool calls, tool results) natively. The orchestrator no longer builds or
injects `message_history` -- ADK's `include_contents='default'` handles it.

**`ReasoningOutput`** is the structured output schema:

```python
# rlm_adk/types.py
class ReasoningOutput(BaseModel):
    final_answer: str = Field(description="Complete final answer to the query.")
    reasoning_summary: str = Field(default="", description="Brief reasoning summary.")
```

When the model is ready to submit its answer, it calls `set_model_response`
with JSON matching this schema. ADK validates the response against the Pydantic
model before accepting it.

---

## 2. REPLTool

**File:** `rlm_adk/tools/repl_tool.py`

`REPLTool` is an ADK `BaseTool` subclass that wraps a `LocalREPL` instance.
The model invokes it via function calling as `execute_code(code="...")`.

### Construction

```python
REPLTool(
    repl=local_repl,          # LocalREPL instance (persistent environment)
    max_calls=60,             # Hard limit on tool invocations per session
    trace_holder=trace_list,  # Optional list to accumulate trace dicts
    flush_fn=flush_callable,  # Optional callable returning dispatch accumulator dict
)
```

### Function Declaration

The tool declares a single `code` parameter:

```python
def _get_declaration(self) -> FunctionDeclaration:
    return FunctionDeclaration(
        name="execute_code",
        description="Execute Python code in a persistent REPL environment. ...",
        parameters=Schema(
            type=Type.OBJECT,
            properties={
                "code": Schema(
                    type=Type.STRING,
                    description="Python code to execute in the REPL.",
                ),
            },
            required=["code"],
        ),
    )
```

### Execution Flow (`run_async`)

1. **Call counting**: Increments `_call_count`. If it exceeds `_max_calls`,
   returns an error message directing the model to submit its final answer.

2. **LLM-call detection**: Uses `has_llm_calls(code)` (AST analysis) to check
   whether the code contains `llm_query` or `llm_query_batched` calls.

3. **Sync path** (no LLM calls): Calls `self.repl.execute_code(code)` directly.
   This runs synchronously under `_EXEC_LOCK`.

4. **Async path** (has LLM calls): Rewrites the code AST via
   `rewrite_for_async(code)` to transform `llm_query(...)` into
   `await llm_query_async(...)`, compiles the rewritten tree, and executes it
   via `self.repl.execute_code_async(code, repl_exec_fn)`.

5. **Exception safety**: The entire execution is wrapped in
   `except (Exception, asyncio.CancelledError)` so that REPL errors never
   crash the agent loop. Errors are returned as `stderr` in the tool result.

6. **Trace recording**: If `trace_holder` is set, appends the trace dict
   (or the full `REPLResult` dict if no trace was produced).

7. **Accumulator flush**: If `flush_fn` is set, calls it and writes the
   returned key/value pairs into `tool_context.state`. This is how dispatch
   accounting (worker token counts, latencies) propagates from the closure's
   local accumulators into ADK state.

8. **Return value**: A dict with `stdout`, `stderr`, `variables` (simple-type
   locals), `llm_calls_made` (bool), and `call_number`.

---

## 3. Depth-Scoped State Keys

**File:** `rlm_adk/state.py`

### Problem

When the orchestrator spawns nested reasoning agents (depth > 0), each agent
reads and writes the same state keys (`message_history`, `iteration_count`,
etc.). Without scoping, a depth-1 agent clobbers the depth-0 agent's state.

### Solution

The `depth_key()` function appends a `@dN` suffix to keys when depth > 0:

```python
def depth_key(key: str, depth: int = 0) -> str:
    if depth == 0:
        return key          # "iteration_count"
    return f"{key}@d{depth}"  # "iteration_count@d1"
```

### Scoped Keys

The `DEPTH_SCOPED_KEYS` set defines which keys get depth-scoping:

```python
DEPTH_SCOPED_KEYS: set[str] = {
    MESSAGE_HISTORY,    # "message_history"
    ITERATION_COUNT,    # "iteration_count"
    FINAL_ANSWER,       # "final_answer"
    LAST_REPL_RESULT,   # "last_repl_result"
    SHOULD_STOP,        # "should_stop"
}
```

### Unscoped Keys

The following key families are intentionally NOT scoped because they are
global aggregates:

- **`obs:*`** -- Observability counters (total tokens, latencies, error counts)
- **`worker_*`** -- Worker dispatch lifecycle counters
- **`cache:*`** -- Cache store and hit/miss counters
- **`app:*`** -- Application-scoped configuration

`LAST_REASONING_RESPONSE` and `CURRENT_CODE_BLOCKS` are also excluded from
scoping because the tool-calling migration removes them from the write path
entirely.

---

## 4. Reasoning Agent Factory

**File:** `rlm_adk/agent.py`

### Signature

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
) -> LlmAgent:
```

### Dual Mode

The factory produces different agent configurations depending on whether
`tools` is provided:

| Parameter | Legacy Mode | Tool-Calling Mode |
|---|---|---|
| `tools` | `None` / `[]` | `[REPLTool(...)]` |
| `output_schema` | `None` | `ReasoningOutput` |
| `include_contents` | `'none'` | `'default'` |
| History management | Callback injects `message_history` | ADK manages natively |
| Final answer | `FINAL()` sentinel in code block | `set_model_response` tool call |

The mode is determined by a single line:

```python
content_mode = "default" if tools else "none"
```

### Other Notable Settings

- `disallow_transfer_to_parent=True` and `disallow_transfer_to_peers=True`
  prevent the reasoning agent from transferring control.
- `output_key="reasoning_output"` stores the final response in state.
- `before_model_callback=reasoning_before_model` and
  `after_model_callback=reasoning_after_model` are always attached.

---

## 5. Callback Simplification

**File:** `rlm_adk/callbacks/reasoning.py`

### `reasoning_before_model`

This callback has dual-mode behavior, detected via `_is_tool_calling_mode()`:

```python
def _is_tool_calling_mode(callback_context: CallbackContext) -> bool:
    agent = callback_context._invocation_context.agent
    tools = getattr(agent, "tools", None)
    return isinstance(tools, list) and len(tools) > 0
```

**In both modes**, the callback:
- Extracts `static_instruction` text from `llm_request.config.system_instruction`
- Extracts the resolved `dynamic_instruction` from `llm_request.contents`
- Merges them into a single `system_instruction`
- Records per-invocation token accounting (`REASONING_PROMPT_CHARS`,
  `REASONING_SYSTEM_CHARS`, `REASONING_CONTENT_COUNT`, etc.)

**Legacy mode only** (`not tool_calling`):
- Reads `MESSAGE_HISTORY` from state
- Builds `llm_request.contents` from the message history
- Overwrites `llm_request.contents` with the constructed list

**Tool-calling mode** (`tool_calling`):
- Leaves `llm_request.contents` untouched -- ADK manages the full
  conversation history including tool call/response pairs

### `reasoning_after_model`

Now accounting-only. It:
- Extracts the text response into `LAST_REASONING_RESPONSE` (for backward
  compatibility with the legacy orchestrator loop; will be removed in a
  future phase)
- Records `REASONING_INPUT_TOKENS` and `REASONING_OUTPUT_TOKENS` from
  `llm_response.usage_metadata`
- Returns `None` (observe-only, does not alter the response)

### What Was Removed

The legacy callback used to overwrite `llm_request.contents` unconditionally
and write `LAST_REASONING_RESPONSE` for the orchestrator to parse code blocks
from. In tool-calling mode, both of these are unnecessary -- ADK handles
contents, and the orchestrator reads the `output_key` or processes tool
call events directly.

---

## 6. Worker Dispatch Flow

**File:** `rlm_adk/dispatch.py`

### `create_dispatch_closures`

Creates the `llm_query_async` and `llm_query_batched_async` closures that are
injected into the REPL namespace. These closures capture the `WorkerPool`,
`InvocationContext`, and `event_queue`.

```python
def create_dispatch_closures(
    worker_pool: WorkerPool,
    ctx: InvocationContext,
    event_queue: asyncio.Queue[Event],
    call_log_sink: list | None = None,
    trace_sink: list | None = None,
    worker_repl: LocalREPL | None = None,   # Controls bifurcated wiring
) -> tuple[Any, Any]:
```

### Bifurcated Worker Wiring

When a dispatch call includes `output_schema`, the worker needs tools for
structured output validation. The wiring depends on whether `worker_repl`
was provided to `create_dispatch_closures`:

```python
if output_schema is not None:
    worker.output_schema = output_schema
    if worker_repl is not None:
        # Worker gets REPLTool; ADK's processor injects
        # SetModelResponseTool at runtime alongside it
        worker.tools = [REPLTool(worker_repl)]
    else:
        # Worker gets explicit SetModelResponseTool only
        worker.tools = [SetModelResponseTool(output_schema)]
    after_cb, error_cb = make_worker_tool_callbacks(max_retries=2)
    worker.after_tool_callback = after_cb
    worker.on_tool_error_callback = error_cb
    worker._structured_result = None
```

**Path A** (`worker_repl` absent): The worker gets a `SetModelResponseTool`
that validates structured output against the schema. This is the standard
path for plain text workers that need structured output.

**Path B** (`worker_repl` present): The worker gets a `REPLTool` for code
execution. ADK's output schema processor automatically injects
`SetModelResponseTool` at runtime when `output_schema` is set, so the worker
ends up with both tools.

### Cleanup in `finally`

After each batch, the `finally` block resets all per-dispatch wiring on every
worker:

```python
finally:
    for worker in workers:
        worker._pending_prompt = None
        worker._result = None
        worker._result_error = False
        worker._call_record = None
        if output_schema is not None:
            worker.output_schema = None
            worker.tools = []
            worker.after_tool_callback = None
            worker.on_tool_error_callback = None
            if hasattr(worker, "_structured_result"):
                worker._structured_result = None
        worker.parent_agent = None      # Allow reuse after ParallelAgent
        await worker_pool.release(worker, model)
```

This ensures workers return to the pool in a clean state, with no leftover
tool callbacks or schema references.

---

## 7. Worker Retry and Tool-Name Guards

**File:** `rlm_adk/callbacks/worker_retry.py`

### `WorkerRetryPlugin`

Extends ADK's `ReflectAndRetryToolPlugin` to detect empty values in
`set_model_response` results and trigger retries:

```python
class WorkerRetryPlugin(ReflectAndRetryToolPlugin):
    async def extract_error_from_result(self, *, tool, tool_args, tool_context, result):
        if tool.name != "set_model_response":
            return None    # Only inspect set_model_response
        for key, value in tool_args.items():
            if isinstance(value, str) and not value.strip():
                return {"error": "Empty value", "details": f"Empty string for field '{key}'..."}
        return None
```

### Tool-Name Guards

The `_SET_MODEL_RESPONSE_TOOL_NAME` constant guards all retry/reflection logic:

```python
_SET_MODEL_RESPONSE_TOOL_NAME = "set_model_response"
```

The `on_tool_error_cb` wrapper only intercepts errors from
`set_model_response`. Errors from other tools (e.g., `execute_code` /
REPLTool) return `None` so they propagate through ADK's normal error handling:

```python
async def on_tool_error_cb(tool, args, tool_context, error):
    if tool.name != _SET_MODEL_RESPONSE_TOOL_NAME:
        return None   # Don't intercept REPLTool errors
    return await plugin.on_tool_error_callback(...)
```

The `after_tool_cb` wrapper captures validated structured results when
`set_model_response` succeeds, storing them on `worker._structured_result`
for the dispatch closure to read:

```python
async def after_tool_cb(tool, args, tool_context, tool_response):
    if tool.name == "set_model_response" and isinstance(tool_response, dict):
        agent = tool_context._invocation_context.agent
        agent._structured_result = tool_response
    return await plugin.after_tool_callback(...)
```

---

## 8. Parallel REPL Safety

**File:** `rlm_adk/repl/local_repl.py`

### The Problem

`LocalREPL.execute_code()` mutates process-global state: `os.chdir()` to the
temp directory and `sys.stdout`/`sys.stderr` for output capture. When multiple
workers run REPL code concurrently, these globals race.

### Threading Lock

A module-level `threading.Lock` serializes synchronous execution:

```python
_EXEC_LOCK = threading.Lock()
```

The lock is acquired in `execute_code()`:

```python
def execute_code(self, code: str, trace: REPLTrace | None = None) -> REPLResult:
    with _EXEC_LOCK, self._capture_output() as (stdout_buf, stderr_buf), self._temp_cwd():
        # ... exec(code) ...
```

### Async Path

The async execution path (`execute_code_async`) uses `contextvars.ContextVar`
for stdout/stderr capture instead of replacing `sys.stdout`/`sys.stderr`
globally. A `_TaskLocalStream` proxy class routes writes to the task-local
buffer when set:

```python
_capture_stdout: contextvars.ContextVar[io.StringIO | None] = ...
_capture_stderr: contextvars.ContextVar[io.StringIO | None] = ...

class _TaskLocalStream:
    def write(self, s):
        buf = self._ctx_var.get(None)
        if buf is not None:
            return buf.write(s)
        return self._original.write(s)
```

This allows concurrent async REPL executions (from different workers) to
capture output independently without a global lock, since each asyncio task
has its own `ContextVar` scope.

---

## 9. Prompt Changes

**File:** `rlm_adk/utils/prompts.py`

### Tool-Calling Instructions

`RLM_STATIC_INSTRUCTION` now references the two tools explicitly:

```
You are tasked with answering a query. You have access to two tools:

1. execute_code(code="..."): Execute Python in a persistent REPL environment.
   Variables persist between calls. Returns stdout, stderr, and variables.
2. set_model_response(final_answer="...", reasoning_summary="..."):
   Provide your final answer. Call ONLY when analysis is complete.
```

Code examples use `execute_code(code='...')` function call syntax:

```
execute_code(code='data = open("/path/to/data.txt").read()\nchunk = data[:10000]\n...')
```

Final answer submission uses `set_model_response`:

```
set_model_response(
    final_answer="The synthesized answer...",
    reasoning_summary="Loaded data, chunked by headers, queried sub-LLMs..."
)
```

### What Replaced What

| Legacy | Tool-Calling |
|---|---|
| `` ```repl\ncode\n``` `` | `execute_code(code="...")` |
| `FINAL("answer")` | `set_model_response(final_answer="...")` |
| `FINAL_VAR("var_name")` | `set_model_response(final_answer="...")` |
| Regex extraction in orchestrator | ADK tool call/response protocol |
| Manual `message_history` assembly | `include_contents='default'` |

---

## 10. End-to-End Flow Summary

1. **Orchestrator** creates a `LocalREPL` and a `REPLTool` wrapping it.

2. **`create_reasoning_agent()`** is called with `tools=[repl_tool]` and
   `output_schema=ReasoningOutput`, producing an `LlmAgent` with
   `include_contents='default'`.

3. **`create_dispatch_closures()`** creates `llm_query_async` and
   `llm_query_batched_async` closures, which are injected into the REPL's
   global namespace via `repl.set_async_llm_query_fns(...)`.

4. The **reasoning agent** runs in ADK's standard tool-calling loop:
   - Model generates a `execute_code` function call
   - ADK invokes `REPLTool.run_async()` with the code
   - REPLTool detects whether the code has LLM calls (AST analysis)
   - Sync code runs under `_EXEC_LOCK`; async code runs via the rewritten
     `_repl_exec` coroutine
   - Tool result (stdout, stderr, variables) is returned to the model
   - Model sees the result and decides next action

5. When the model is ready, it calls **`set_model_response`** with
   `final_answer` and optional `reasoning_summary`. ADK validates against
   `ReasoningOutput` and terminates the agent loop.

6. **Worker sub-LM calls** from within REPL code (`llm_query(...)`) go
   through the dispatch closures, which acquire workers from the pool,
   dispatch via `ParallelAgent`, and return `LLMResult` objects. Workers
   with `output_schema` get bifurcated wiring (REPLTool or
   SetModelResponseTool) with retry callbacks guarded by tool name.
