# Reasoning Agent REPL Dispatch Internals

This document traces how a reasoning-model `execute_code` submission is parsed and how `llm_query()` / `llm_query_batched()` calls dispatch worker agents under the hood.

## 1. Where REPL code submission enters the system

The reasoning agent submits REPL work as an ADK function call:

- Tool name: `execute_code`
- Payload: `args.code` (a Python source string)

Concrete fixture example:

- `tests_rlm_adk/fixtures/provider_fake/multi_iteration_with_workers.json` shows reasoning returning:
  - `functionCall.name = "execute_code"`
  - `functionCall.args.code = "result = llm_query('what is 2+2?')\nprint(result)"`

Runtime wiring path:

1. `RLMOrchestratorAgent` creates a `REPLTool` and attaches it to `reasoning_agent.tools` at runtime.
2. ADK parses the function call into `run_async(args=...)` using `REPLTool._get_declaration()`.
3. `REPLTool.run_async()` receives `args["code"]` and executes it.

Relevant code:

- `rlm_adk/orchestrator.py:153-170`
- `rlm_adk/tools/repl_tool.py:60-79`

## 2. How `llm_query*` calls are parsed from submitted code

`REPLTool.run_async()` performs AST-based detection:

- `has_llm_calls(code)` parses the code via `ast.parse(code)`.
- It detects only `ast.Call` where `node.func` is `ast.Name("llm_query")` or `ast.Name("llm_query_batched")`.

If detected:

1. `rewrite_for_async(code)` rewrites:
   - `llm_query(...)` -> `await llm_query_async(...)`
   - `llm_query_batched(...)` -> `await llm_query_batched_async(...)`
2. Rewriter promotes sync functions containing new `await` expressions to `async def`, then awaits promoted callsites transitively.
3. Entire block is wrapped into:
   - `async def _repl_exec(): ... return locals()`
4. Compiled module is `exec`-ed, and `_repl_exec` is awaited by `LocalREPL.execute_code_async(...)`.

If not detected:

- Code runs in the sync REPL path (`LocalREPL.execute_code(...)`).

Relevant code:

- `rlm_adk/tools/repl_tool.py:107-119`
- `rlm_adk/repl/ast_rewriter.py:15-36`
- `rlm_adk/repl/ast_rewriter.py:39-67`
- `rlm_adk/repl/ast_rewriter.py:82-120`
- `rlm_adk/repl/ast_rewriter.py:161-228`
- `rlm_adk/repl/local_repl.py:368-445`

Known parsing limits (documented by tests):

- Aliases are not detected (`q = llm_query; q("...")`).
- Attribute style is not detected (`module.llm_query("...")`).

References:

- `tests_rlm_adk/test_adk_ast_rewriter.py:55-77`

## 3. Orchestrator wiring that makes rewritten calls resolvable

Before reasoning starts, orchestrator wires closures into the REPL globals:

1. `create_dispatch_closures(worker_pool, ctx, ...)` returns:
   - `llm_query_async`
   - `llm_query_batched_async`
   - `flush_fn`
2. `repl.set_async_llm_query_fns(...)` injects async handlers.
3. Sync names `llm_query` / `llm_query_batched` are intentionally set to a stub that raises, so sync fallback cannot silently run in ADK mode.

Relevant code:

- `rlm_adk/orchestrator.py:127-143`
- `rlm_adk/repl/local_repl.py:210-217`
- `rlm_adk/repl/local_repl.py:205-208`

## 4. Worker dispatch path: `llm_query_async`

`llm_query_async` is a thin K=1 wrapper:

1. Optional trace begin.
2. Delegates to `llm_query_batched_async([prompt], ...)`.
3. Optional trace end.
4. Returns first `LLMResult`.

Relevant code:

- `rlm_adk/dispatch.py:257-299`

## 5. Worker dispatch path: `llm_query_batched_async`

### 5.1 Batch planning

1. Read `RLM_MAX_CONCURRENT_WORKERS` (default `4`).
2. Split prompts into chunks of size `max_concurrent`.
3. Increment local accumulators for observability (`dispatch_count`, batch count, latency, errors).

Code:

- `rlm_adk/dispatch.py:324-353`
- `rlm_adk/dispatch.py:341-346`

### 5.2 Worker acquisition and prompt injection

For each prompt in a chunk:

1. `worker_pool.acquire(model)` gets a worker (or creates on demand if pool exhausted).
2. Dispatch closure sets per-worker carriers:
   - `_pending_prompt`
   - `_result`, `_result_ready`, `_result_error` reset
3. If `output_schema` is set:
   - install `SetModelResponseTool(output_schema)`
   - install retry callbacks from `make_worker_tool_callbacks(...)`
   - clear `_structured_result`

Code:

- `rlm_adk/dispatch.py:365-382`
- `rlm_adk/dispatch.py:373-381`
- `rlm_adk/dispatch.py:152-179` (pool exhaustion behavior)

### 5.3 Execution model

- If chunk size is 1: run that worker directly (`worker.run_async(ctx)`) under timeout.
- If chunk size > 1: run a `ParallelAgent(sub_agents=workers)` under timeout.

Timeout marks unfinished workers as error results with `error_category="TIMEOUT"`.

Code:

- `rlm_adk/dispatch.py:384-415`
- `rlm_adk/dispatch.py:390-405`
- `rlm_adk/dispatch.py:416-431`

### 5.4 How worker callbacks bridge data back to dispatch

Dispatch does not read worker output from session-state dirty reads; it reads worker object carriers populated by callbacks:

- `worker_before_model`: copies `worker._pending_prompt` into outbound `LlmRequest.contents`.
- `worker_after_model`: extracts text/usage, writes:
  - `worker._result`
  - `worker._result_ready`
  - `worker._call_record`
- `worker_on_model_error`: writes error carrier fields and returns a synthetic `LlmResponse` so batch continues.

Code:

- `rlm_adk/callbacks/worker.py:55-75`
- `rlm_adk/callbacks/worker.py:78-157`
- `rlm_adk/callbacks/worker.py:160-196`

### 5.5 Result assembly and ordering guarantees

After batch completion, dispatch iterates workers in acquisition order and builds `LLMResult` objects in that same order, preserving prompt-response positional mapping.

Branches:

- `_result_ready` false -> `NO_RESULT` error
- `_result_error` true -> error `LLMResult` with category from `_call_record`
- success -> plain or structured output into `LLMResult(parsed=...)`

Code:

- `rlm_adk/dispatch.py:433-498`
- `rlm_adk/types.py:50-79` (`LLMResult` carrier fields)

### 5.6 Structured output branch (`output_schema`)

When `output_schema` is passed:

1. Worker toolchain uses `set_model_response`.
2. `after_tool_cb` captures validated dict into `worker._structured_result`.
3. Dispatch emits `LLMResult(parsed=structured_dict)` on success.
4. If retries exhaust and worker falls back to text, dispatch marks:
   - `error=True`
   - `error_category="SCHEMA_VALIDATION_EXHAUSTED"`

Code:

- `rlm_adk/dispatch.py:373-381`
- `rlm_adk/callbacks/worker_retry.py:74-147`
- `rlm_adk/dispatch.py:460-488`

### 5.7 Cleanup and reuse

Finally, dispatch:

1. Clears prompt/result carriers.
2. Clears structured-output wiring when used.
3. Sets `worker.parent_agent = None` (required for safe reuse after `ParallelAgent`).
4. Releases worker back to pool (or discards on-demand worker when pool full).

Code:

- `rlm_adk/dispatch.py:592-612`
- `rlm_adk/dispatch.py:181-201`

## 6. REPL result + observability handoff

Dispatch accumulates observability in closure-local counters and exposes a `flush_fn()` delta.

- `REPLTool.run_async()` calls `flush_fn()` after code execution (also in cancellation/exception paths) and merges metrics into `tool_context.state`.
- It writes `last_repl_result` summary and returns tool response payload with:
  - `stdout`, `stderr`, `variables`
  - `llm_calls_made`
  - `call_number`

Code:

- `rlm_adk/dispatch.py:625-660`
- `rlm_adk/tools/repl_tool.py:168-206`
- `rlm_adk/tools/repl_tool.py:120-166`

## 7. End-to-end mental model

1. Reasoning LLM emits ADK function call `execute_code(code="...llm_query(...)...")`.
2. ADK parses args -> `REPLTool.run_async(args)`.
3. `REPLTool` AST-detects `llm_query*` calls.
4. Rewriter converts sync-looking calls to awaited async closures.
5. `LocalREPL.execute_code_async()` runs rewritten `_repl_exec`.
6. `llm_query_async` / `llm_query_batched_async` dispatch through `WorkerPool` + (`ParallelAgent` when K>1).
7. Worker callbacks fill agent carriers; dispatch converts carriers to ordered `LLMResult`s.
8. REPL code receives `LLMResult` values as if local variables, continues execution, prints/outputs, and returns.
