<!-- validated: 2026-03-09 -->

# Dispatch System and State Management

Reference for `rlm_adk/dispatch.py` and `rlm_adk/state.py`. Covers the closure-based dispatch
pattern, local accumulator discipline, depth scoping, and the AR-CRIT-001 invariant.

---

## DispatchConfig

`DispatchConfig` holds model configuration for child dispatch. It replaced the earlier
`WorkerPool` class (a backward-compatible alias `WorkerPool = DispatchConfig` is retained).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_model` | `str` | required | Model for the root reasoning agent |
| `other_model` | `str \| None` | same as `default_model` | Model used for child orchestrators |
| `pool_size` | `int` | `5` | Legacy field (previously sized the worker pool) |

`ensure_initialized()` is a no-op kept for backward compatibility.

---

## create_dispatch_closures()

Factory that returns three closures sharing captured state. Signature:

```python
def create_dispatch_closures(
    dispatch_config: DispatchConfig,
    ctx: InvocationContext,
    call_log_sink: list | None = None,
    trace_sink: list | None = None,
    depth: int = 0,
    max_depth: int = 3,        # overridden by RLM_MAX_DEPTH env var
) -> tuple[llm_query_async, llm_query_batched_async, flush_fn]
```

The three closures share:

- A `_child_semaphore` (`asyncio.Semaphore`, sized by `RLM_MAX_CONCURRENT_CHILDREN`, default 3).
- Six local accumulators (see below).
- References to `dispatch_config`, `ctx`, `call_log_sink`, `trace_sink`, `depth`, and `max_depth`.

REPLTool injects `llm_query_async` and `llm_query_batched_async` into the REPL namespace. User
code calls `llm_query(prompt)`, the AST rewriter transforms it to `await llm_query_async(prompt)`,
and dispatch happens transparently.

---

## Local Accumulators and AR-CRIT-001

### Why accumulators exist

Writing `ctx.session.state[key] = value` inside a dispatch closure **bypasses ADK event tracking**.
The ADK Runner only commits state changes that arrive via tracked channels (tool context, event
actions, output keys). Direct session writes produce silent data loss -- state appears to update
locally but is never persisted or surfaced in the event stream.

This is codified as **AR-CRIT-001**: the critical invariant that all state mutations must flow
through ADK-tracked channels.

### What the accumulators track

| Accumulator | Type | Tracks |
|-------------|------|--------|
| `_acc_child_dispatches` | `int` | Total child orchestrators spawned |
| `_acc_child_batch_dispatches` | `int` | Number of multi-prompt batch operations |
| `_acc_child_latencies` | `list[float]` | Per-batch wall-clock elapsed (ms) |
| `_acc_child_error_counts` | `dict[str, int]` | Error category tallies |
| `_acc_child_summaries` | `dict[str, dict]` | Per-child observability summary dicts |
| `_acc_structured_output_failures` | `int` | Schema validation exhaustion count |

### How flush_fn works

`flush_fn()` is called by REPLTool after each code execution. It:

1. Snapshots all accumulators into a `dict[str, Any]`.
2. Resets every accumulator to its zero value (`0`, `[]`, `{}`, etc.).
3. Returns the snapshot dict.

REPLTool then writes each key/value pair into `tool_context.state`, which is an ADK-tracked
channel. This means accumulated dispatch telemetry enters the event stream correctly.

**Keys written by flush_fn:**

| State Key | Source Accumulator | Always present |
|-----------|--------------------|----------------|
| `obs:child_dispatch_count` | `_acc_child_dispatches` | Yes |
| `obs:child_dispatch_latency_ms` | `_acc_child_latencies` | Yes |
| `obs:child_total_batch_dispatches` | `_acc_child_batch_dispatches` | Only if > 0 |
| `obs:child_error_counts` | `_acc_child_error_counts` | Only if non-empty |
| `obs:structured_output_failures` | `_acc_structured_output_failures` | Only if > 0 |
| `obs:bug13_suppress_count` | `_bug13_stats["suppress_count"]` | Only if > 0 |
| `obs:child_summary@d{D}f{F}` | `_acc_child_summaries` | One per child |

Because flush resets accumulators, each REPL turn's state reflects only that turn's dispatch
activity, not a running total.

---

## llm_query_async

```python
async def llm_query_async(
    prompt: str,
    model: str | None = None,
    output_schema: type[BaseModel] | None = None,
) -> LLMResult
```

Dispatches a single sub-LM query. Delegates to `llm_query_batched_async([prompt], ...)` and
returns `results[0]`. Records trace start/end entries when a `trace_sink` is active.

## llm_query_batched_async

```python
async def llm_query_batched_async(
    prompts: list[str],
    model: str | None = None,
    output_schema: type[BaseModel] | None = None,
    _record_trace_entries: bool = True,
) -> list[LLMResult]
```

Spawns K child orchestrators concurrently via `asyncio.gather()`. Actual concurrency is bounded
by `_child_semaphore` (default 3, controlled by `RLM_MAX_CONCURRENT_CHILDREN`).

Flow per call:

1. Increment `_acc_child_dispatches` by K; increment `_acc_child_batch_dispatches` if K > 1.
2. Create K tasks, each calling `_run_child(prompt, model, output_schema, fanout_idx)`.
3. `await asyncio.gather(*tasks)` -- semaphore gates actual concurrency inside `_run_child`.
4. Record batch elapsed time in `_acc_child_latencies`.
5. Tally per-result errors into `_acc_child_error_counts`.
6. Optionally record trace entries for REPL tracing.

---

## Child Lifecycle (_run_child)

Each child follows this sequence:

1. **Depth check** -- if `depth + 1 >= max_depth`, return an `LLMResult` with `error_category="DEPTH_LIMIT"` immediately.
2. **Create child orchestrator** -- `create_child_orchestrator(model, depth+1, prompt, worker_pool, output_schema)`.
3. **Run under semaphore** -- `async with _child_semaphore: async for event in child.run_async(ctx)`. State deltas from each event are collected into `_child_state`.
4. **Read completion** -- `_read_child_completion(child, child_depth, _child_state, shared_state)` normalizes the child's result by checking: `_rlm_completion` attribute, depth-scoped state keys, `output_key` in session state, and `_structured_result`.
5. **Build LLMResult** -- populated with text, tokens, finish reason, parsed output, error info, wall time.
6. **Record call log** -- appends an `RLMChatCompletion` to `call_log_sink` for REPL observability.
7. **Write per-child summary** -- stored in `_acc_child_summaries` keyed by `obs:child_summary@d{depth}f{fanout_idx}`.
8. **Cleanup** -- if the child has a non-persistent REPL, call `child.repl.cleanup()`.

---

## Per-Child Observability Summary

Each child produces a summary dict stored at key `obs:child_summary@d{depth}f{fanout_idx}`:

| Field | Type | Description |
|-------|------|-------------|
| `model` | `str` | Model used for this child |
| `depth` | `int` | Child's depth level |
| `fanout_idx` | `int` | Index within the batch (0-based) |
| `elapsed_ms` | `float` | Wall-clock time for the child |
| `error` | `bool` | Whether the child errored |
| `error_category` | `str \| None` | Classification (e.g. `UNKNOWN`, `DEPTH_LIMIT`, `SCHEMA_VALIDATION_EXHAUSTED`) |
| `error_message` | `str \| None` | Error text if applicable |
| `input_tokens` | `int` | Input tokens consumed |
| `output_tokens` | `int` | Output tokens produced |
| `thought_tokens` | `int` | Thinking/reasoning tokens |
| `finish_reason` | `str \| None` | Model finish reason |
| `prompt_preview` | `str` | First 500 chars of prompt |
| `result_preview` | `str \| None` | First 500 chars of result |
| `visible_output_preview` | `str \| None` | Non-thinking output preview |
| `thought_preview` | `str \| None` | Thinking text preview |
| `raw_output_preview` | `str \| None` | Raw output preview |
| `parsed_output` | `dict \| None` | Validated structured output (only on success) |
| `reasoning_summary` | `str \| None` | Child's reasoning summary |
| `reasoning_retry` | `dict` | `{count, delay_ms, used}` |
| `nested_dispatch` | `dict` | `{count, batch_dispatches, error_counts, structured_output_failures}` |
| `structured_output` | `dict` | `{expected, schema_name, attempts, retry_count, outcome, validated_result, events}` |

The `structured_output.outcome` field takes one of: `not_applicable`, `validated`, `retry_recovered`,
`retry_exhausted`, `incomplete`, or `missing`.

---

## State Key Reference

All constants are defined in `rlm_adk/state.py`.

### Flow Control

| Constant | Key String | Scope | Depth-Scoped |
|----------|-----------|-------|:------------:|
| `APP_MAX_DEPTH` | `app:max_depth` | app | No |
| `APP_MAX_ITERATIONS` | `app:max_iterations` | app | No |
| `CURRENT_DEPTH` | `current_depth` | session | No |
| `ITERATION_COUNT` | `iteration_count` | session | Yes |
| `SHOULD_STOP` | `should_stop` | session | Yes |
| `POLICY_VIOLATION` | `policy_violation` | session | No |

### REPL Execution

| Constant | Key String | Depth-Scoped |
|----------|-----------|:------------:|
| `MESSAGE_HISTORY` | `message_history` | Yes |
| `LAST_REPL_RESULT` | `last_repl_result` | Yes |
| `FINAL_ANSWER` | `final_answer` | Yes |
| `REASONING_SUMMARY` | `reasoning_summary` | Yes |
| `REASONING_FINISH_REASON` | `reasoning_finish_reason` | Yes |
| `REASONING_VISIBLE_OUTPUT_TEXT` | `reasoning_visible_output_text` | Yes |
| `REASONING_THOUGHT_TEXT` | `reasoning_thought_text` | Yes |
| `REASONING_THOUGHT_TOKENS` | `reasoning_thought_tokens` | Yes |
| `REASONING_RAW_OUTPUT` | `reasoning_raw_output` | Yes |
| `REASONING_PARSED_OUTPUT` | `reasoning_parsed_output` | Yes |

### REPL Submitted Code

| Constant | Key String | Depth-Scoped |
|----------|-----------|:------------:|
| `REPL_SUBMITTED_CODE` | `repl_submitted_code` | Yes |
| `REPL_SUBMITTED_CODE_PREVIEW` | `repl_submitted_code_preview` | Yes |
| `REPL_SUBMITTED_CODE_HASH` | `repl_submitted_code_hash` | Yes |
| `REPL_SUBMITTED_CODE_CHARS` | `repl_submitted_code_chars` | Yes |

### Token Accounting

| Constant | Key String | Depth-Scoped |
|----------|-----------|:------------:|
| `REASONING_INPUT_TOKENS` | `reasoning_input_tokens` | Yes |
| `REASONING_OUTPUT_TOKENS` | `reasoning_output_tokens` | Yes |
| `REASONING_PROMPT_CHARS` | `reasoning_prompt_chars` | No |
| `REASONING_SYSTEM_CHARS` | `reasoning_system_chars` | No |
| `REASONING_HISTORY_MSG_COUNT` | `reasoning_history_msg_count` | No |
| `REASONING_CONTENT_COUNT` | `reasoning_content_count` | No |
| `CONTEXT_WINDOW_SNAPSHOT` | `context_window_snapshot` | No |

### Observability -- Global

| Constant | Key String | Written By |
|----------|-----------|------------|
| `OBS_TOTAL_INPUT_TOKENS` | `obs:total_input_tokens` | ObservabilityPlugin |
| `OBS_TOTAL_OUTPUT_TOKENS` | `obs:total_output_tokens` | ObservabilityPlugin |
| `OBS_TOTAL_CALLS` | `obs:total_calls` | ObservabilityPlugin |
| `OBS_TOOL_INVOCATION_SUMMARY` | `obs:tool_invocation_summary` | ObservabilityPlugin |
| `OBS_TOTAL_EXECUTION_TIME` | `obs:total_execution_time` | ObservabilityPlugin |
| `OBS_PER_ITERATION_TOKEN_BREAKDOWN` | `obs:per_iteration_token_breakdown` | ObservabilityPlugin |
| `OBS_FINISH_SAFETY_COUNT` | `obs:finish_safety_count` | ObservabilityPlugin |
| `OBS_FINISH_RECITATION_COUNT` | `obs:finish_recitation_count` | ObservabilityPlugin |
| `OBS_FINISH_MAX_TOKENS_COUNT` | `obs:finish_max_tokens_count` | ObservabilityPlugin |

### Observability -- Dispatch

| Constant | Key String | Written By |
|----------|-----------|------------|
| `OBS_CHILD_DISPATCH_COUNT` | `obs:child_dispatch_count` | flush_fn |
| `OBS_CHILD_DISPATCH_LATENCY_MS` | `obs:child_dispatch_latency_ms` | flush_fn |
| `OBS_CHILD_TOTAL_BATCH_DISPATCHES` | `obs:child_total_batch_dispatches` | flush_fn |
| `OBS_CHILD_ERROR_COUNTS` | `obs:child_error_counts` | flush_fn |
| `OBS_STRUCTURED_OUTPUT_FAILURES` | `obs:structured_output_failures` | flush_fn |
| `OBS_BUG13_SUPPRESS_COUNT` | `obs:bug13_suppress_count` | flush_fn |

### Observability -- REPL / AST

| Constant | Key String | Written By |
|----------|-----------|------------|
| `OBS_REWRITE_COUNT` | `obs:rewrite_count` | REPLTool |
| `OBS_REWRITE_TOTAL_MS` | `obs:rewrite_total_ms` | REPLTool |
| `OBS_REWRITE_FAILURE_COUNT` | `obs:rewrite_failure_count` | REPLTool |
| `OBS_REWRITE_FAILURE_CATEGORIES` | `obs:rewrite_failure_categories` | REPLTool |
| `OBS_REASONING_RETRY_COUNT` | `obs:reasoning_retry_count` | orchestrator |
| `OBS_REASONING_RETRY_DELAY_MS` | `obs:reasoning_retry_delay_ms` | orchestrator |

### API / Request

| Constant | Key String | Scope |
|----------|-----------|-------|
| `REQUEST_ID` | `request_id` | session |
| `IDEMPOTENCY_KEY` | `idempotency_key` | session |
| `USER_LAST_SUCCESSFUL_CALL_ID` | `user:last_successful_call_id` | user |

### Context

| Constant | Key String |
|----------|-----------|
| `ROOT_PROMPT` | `root_prompt` |
| `REPO_URL` | `repo_url` |
| `DYN_ROOT_PROMPT` | `root_prompt` |
| `DYN_REPO_URL` | `repo_url` |

### Cache

| Constant | Key String |
|----------|-----------|
| `CACHE_STORE` | `cache:store` |
| `CACHE_HIT_COUNT` | `cache:hit_count` |
| `CACHE_MISS_COUNT` | `cache:miss_count` |
| `CACHE_LAST_HIT_KEY` | `cache:last_hit_key` |

### Artifacts

| Constant | Key String |
|----------|-----------|
| `ARTIFACT_SAVE_COUNT` | `artifact_save_count` |
| `ARTIFACT_LOAD_COUNT` | `artifact_load_count` |
| `ARTIFACT_TOTAL_BYTES_SAVED` | `artifact_total_bytes_saved` |
| `ARTIFACT_LAST_SAVED_FILENAME` | `artifact_last_saved_filename` |
| `ARTIFACT_LAST_SAVED_VERSION` | `artifact_last_saved_version` |
| `OBS_ARTIFACT_SAVES` | `obs:artifact_saves` |
| `OBS_ARTIFACT_BYTES_SAVED` | `obs:artifact_bytes_saved` |
| `APP_ARTIFACT_OFFLOAD_THRESHOLD` | `app:artifact_offload_threshold` |

### Test Hooks

| Constant | Key String |
|----------|-----------|
| `CB_REASONING_CONTEXT` | `cb_reasoning_context` |
| `CB_WORKER_CONTEXT` | `cb_worker_context` |
| `CB_ORCHESTRATOR_CONTEXT` | `cb_orchestrator_context` |
| `CB_TOOL_CONTEXT` | `cb_tool_context` |

---

## depth_key() and DEPTH_SCOPED_KEYS

```python
def depth_key(key: str, depth: int = 0) -> str:
    if depth == 0:
        return key           # "iteration_count"
    return f"{key}@d{depth}" # "iteration_count@d2"
```

At depth 0 (root orchestrator), keys are used as-is. At depth N > 0, the `@dN` suffix gives each
recursive child its own independent state namespace. This prevents a child at depth 2 from
clobbering the root's `iteration_count`, for example.

The `DEPTH_SCOPED_KEYS` set defines which keys require scoping. It includes all REPL execution
keys, submitted code keys, `ITERATION_COUNT`, `SHOULD_STOP`, and per-invocation token keys
(`REASONING_INPUT_TOKENS`, `REASONING_OUTPUT_TOKENS`). Global observability keys (`obs:*`) are
intentionally excluded -- they accumulate across all depths.

Helper for per-child fan-out keys:

```python
def child_obs_key(depth: int, fanout_idx: int) -> str:
    return f"obs:child_summary@d{depth}f{fanout_idx}"
```

---

## AR-CRIT-001: State Mutation Invariant

All state mutations must flow through ADK-tracked channels. Direct writes to `ctx.session.state`
from dispatch closures are invisible to the ADK event stream and will be silently lost on
persistence.

### Correct patterns

**In tools (REPLTool):**

```python
async def run_async(self, *, args, tool_context: ToolContext):
    # Tracked -- ADK records this in the event stream
    tool_context.state["last_repl_result"] = result
```

**In orchestrator events:**

```python
yield Event(
    invocation_id=ctx.invocation_id,
    author=self.name,
    actions=EventActions(state_delta={"current_depth": depth}),
)
```

**In dispatch closures (via accumulator + flush):**

```python
# Inside closure: accumulate locally
_acc_child_dispatches += k

# REPLTool calls flush_fn() after execution:
delta = flush_fn()
for key, value in delta.items():
    tool_context.state[key] = value  # Tracked channel
```

### Incorrect pattern

```python
# WRONG -- bypasses ADK event tracking entirely
async def llm_query_async(prompt, ...):
    ctx.session.state["obs:child_dispatch_count"] += 1  # SILENT DATA LOSS
```

This write appears to succeed at runtime but the Runner never sees it, so it is never persisted
and does not appear in the event stream.

---

## ADK Gotchas

### Pydantic model constraints

ADK agents are Pydantic models. All dynamic attribute writes in dispatch closures must use `object.__setattr__()`:

```python
# WRONG -- Pydantic rejects unknown fields
worker.my_attr = "value"

# CORRECT
object.__setattr__(worker, "my_attr", "value")
```

Used in dispatch: `worker._pending_prompt`, `worker._result`, `worker._result_ready`, `worker._call_record`.

### ParallelAgent worker reuse

ADK's `ParallelAgent` sets `worker.parent_agent` in `model_post_init`. If you reuse a worker across batches without clearing it, ADK raises an error because `parent_agent` is already set.

```python
# After each ParallelAgent batch completes:
for worker in workers:
    worker.parent_agent = None  # MUST clear for reuse
```

This pattern is enforced in `dispatch.py` after each `llm_query_batched_async` call.

### State mutation (AR-CRIT-001) — repeated for emphasis

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. The write appears to succeed at runtime but the Runner never sees it, so it is never persisted and does not appear in the event stream. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

---

## Recent Changes

> Append entries here when modifying source files documented by this branch. A stop hook (`ai_docs/scripts/check_doc_staleness.py`) will remind you.

- **2026-03-09 11:05** — Initial branch doc created from codebase exploration.
- **2026-03-09 12:55** — `dispatch.py`: Documented child context propagation — all children share parent's `InvocationContext` (same session_id, artifact_service). Artifact filename collisions identified for batched dispatch (`fanout_idx` not yet threaded to child REPLTool).
- **2026-03-09 13:00** — `dispatch.py`: Added Args docstring to `_read_child_completion` function (child, child_depth, child_state, shared_state parameters).
- **2026-03-09 14:00** — `dispatch.py`, `agent.py`: `_run_child()` now passes `fanout_idx` to `create_child_orchestrator()`, which threads it to `RLMOrchestratorAgent(fanout_idx=...)`. This enables depth+fanout artifact filename disambiguation (`d{depth}_f{fanout_idx}` prefix on all artifact filenames).

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
