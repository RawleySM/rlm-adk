<!-- validated: 2026-03-18 -->

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
    instruction_router: Any = None,
    fanout_idx: int = 0,
) -> tuple[llm_query_async, llm_query_batched_async, flush_fn]
```

The three closures share:

- A `_child_semaphore` (`asyncio.Semaphore`, sized by `RLM_MAX_CONCURRENT_CHILDREN`, default 3).
- Six local accumulators (see below).
- References to `dispatch_config`, `ctx`, `call_log_sink`, `trace_sink`, `depth`, `max_depth`, `instruction_router`, and `fanout_idx`.

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

When an `instruction_router` is provided, `create_dispatch_closures` pre-computes `_parent_skill_instruction = instruction_router(depth, fanout_idx)`. This cached value is used by `flush_fn` to restore the parent's skill instruction after child dispatch (preventing child state from clobbering the parent's `DYN_SKILL_INSTRUCTION`).

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
| `skill_instruction` (DYN_SKILL_INSTRUCTION) | `_parent_skill_instruction` | Only if instruction_router provided |

Because flush resets accumulators, each REPL turn's state reflects only that turn's dispatch
activity, not a running total.

---

## Per-Iteration vs Cumulative Keys

Dispatch observability keys come in two flavors: **per-iteration** (reset after each REPL turn)
and **cumulative** (monotonically non-decreasing across the entire session).

### Per-iteration keys

Written by `flush_fn()` and reset to zero after each snapshot. These reflect only the
dispatch activity of the most recent REPL turn. Useful for per-step analysis and debugging.

### Cumulative keys

Written by `flush_fn()` but **never reset**. Each flush adds the current turn's values to the
running total. These are monotonically non-decreasing across the session lifetime. Useful for
dashboards, `_rlm_state` REPL introspection, and end-of-session summaries.

### Mapping table

| Per-Iteration (resets each turn) | Cumulative (never resets) |
|---|---|
| `obs:child_dispatch_count` | `obs:child_dispatch_count_total` |
| `obs:child_total_batch_dispatches` | `obs:child_batch_dispatches_total` |
| `obs:child_error_counts` | `obs:child_error_counts_total` |
| `obs:structured_output_failures` | `obs:structured_output_failures_total` |

### Why cumulative keys exist

The `_rlm_state` read-only snapshot is built **before** code execution in REPLTool
(so that user code can inspect dispatch metrics from the previous turn). Because per-iteration
keys reset to zero after each flush, they oscillate across turns. For example, a session that
dispatches one child per turn sees `obs:child_dispatch_count` follow the pattern 1 -> 0 -> 1 -> 0.
This makes per-iteration keys unreliable for "how many total dispatches have occurred?" questions.

Cumulative keys solve this by providing a stable, monotonically increasing view:
`obs:child_dispatch_count_total` would show 0 -> 1 -> 1 -> 2 -> 2 for the same session.

### Initialization

Cumulative keys are seeded to zero in the orchestrator's `initial_state` on turn 1.
This guarantees they are **never absent** from session state -- consumers can always read
them without a `get(..., 0)` guard.

### Cumulative latency excluded

`obs:child_dispatch_latency_ms` has no cumulative counterpart. Latency lists grow
without bound and have no meaningful scalar sum, so accumulating them across the entire
session would produce unbounded memory growth with limited analytical value.

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

## Child Event Re-Emission

Child orchestrators run inside `_run_child()` which consumes their events into a local
`_child_state` dict. Without re-emission, these events never reach the ADK Runner's
plugin loop — meaning `SqliteTracingPlugin.on_event_callback` never fires for child
state changes, and `session_state_events` has zero rows with `key_depth > 0`.

### Queue mechanism

`create_dispatch_closures()` accepts an optional `child_event_queue: asyncio.Queue[Event]`.
When provided, `_run_child()` filters each child's `state_delta` through
`should_capture_state_key()` and pushes curated events onto the queue with
`put_nowait()`.

The orchestrator's `_run_async_impl()` drains the queue after each yielded event
from `reasoning_agent.run_async(ctx)`:

```
dispatch._run_child()                    orchestrator._run_async_impl()
  async for _event in child.run_async:     async for event in reasoning_agent.run_async:
    if curated state-delta:                    yield event
      queue.put_nowait(event)  ──────>         while not queue.empty():
                                                   yield queue.get_nowait()
```

A final drain runs after the reasoning loop completes to catch edge cases where
the last tool call produces child events but reasoning_agent terminates without
yielding another event.

### Curated filter

Only state keys matching `CURATED_STATE_KEYS` (exact) or `CURATED_STATE_PREFIXES`
(startswith) are re-emitted. Both sets are defined in `rlm_adk/state.py` and shared
with `sqlite_tracing.py`. Non-curated keys (obs counters, request metadata, cache
keys) are filtered out to keep the event stream focused on working state.

### Event metadata

Re-emitted events carry `custom_metadata`:

| Field | Type | Description |
|-------|------|-------------|
| `rlm_child_event` | `bool` | Always `True` — tag for filtering |
| `child_depth` | `int` | Depth of the child that produced the event |
| `child_fanout_idx` | `int` | Fanout index within a batch |

### Causal ordering

Child events accumulate during REPL tool execution (which triggers `_run_child`).
They drain after the tool-response event and appear before the next LLM call.
This is a natural consequence of the asyncio.Queue bridge.

---

## State Key Reference

All constants are defined in `rlm_adk/state.py`.

### Flow Control

| Constant | Key String | Scope | Depth-Scoped |
|----------|-----------|-------|:------------:|
| `APP_MAX_DEPTH` | `app:max_depth` | app | No |
| `APP_MAX_ITERATIONS` | `app:max_iterations` | app | No |
| `CURRENT_DEPTH` | `current_depth` | session | Yes |
| `ITERATION_COUNT` | `iteration_count` | session | Yes |
| `SHOULD_STOP` | `should_stop` | session | Yes |
| `POLICY_VIOLATION` | `policy_violation` | session | No |

### REPL Execution

| Constant | Key String | Depth-Scoped |
|----------|-----------|:------------:|
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

### Skill Expansion Observability Keys

| Constant | Key String | Depth-Scoped |
|----------|-----------|:------------:|
| `REPL_EXPANDED_CODE` | `repl_expanded_code` | Yes |
| `REPL_EXPANDED_CODE_HASH` | `repl_expanded_code_hash` | Yes |
| `REPL_SKILL_EXPANSION_META` | `repl_skill_expansion_meta` | Yes |
| `REPL_DID_EXPAND` | `repl_did_expand` | Yes |

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
| `obs_model_usage_key(model)` | `obs:model_usage:{model}` | ObservabilityPlugin |
| `obs:litellm_last_call_cost` | `obs:litellm_last_call_cost` | LiteLLMCostTrackingPlugin |
| `obs:litellm_total_cost` | `obs:litellm_total_cost` | LiteLLMCostTrackingPlugin |

### Observability -- Dispatch (Per-Iteration)

| Constant | Key String | Written By |
|----------|-----------|------------|
| `OBS_CHILD_DISPATCH_COUNT` | `obs:child_dispatch_count` | flush_fn |
| `OBS_CHILD_DISPATCH_LATENCY_MS` | `obs:child_dispatch_latency_ms` | flush_fn |
| `OBS_CHILD_TOTAL_BATCH_DISPATCHES` | `obs:child_total_batch_dispatches` | flush_fn |
| `OBS_CHILD_ERROR_COUNTS` | `obs:child_error_counts` | flush_fn |
| `OBS_STRUCTURED_OUTPUT_FAILURES` | `obs:structured_output_failures` | flush_fn |
| `OBS_BUG13_SUPPRESS_COUNT` | `obs:bug13_suppress_count` | flush_fn |

### Observability -- Dispatch (Cumulative)

| Constant | Key String | Written By |
|----------|-----------|------------|
| `OBS_CHILD_DISPATCH_COUNT_TOTAL` | `obs:child_dispatch_count_total` | flush_fn |
| `OBS_CHILD_BATCH_DISPATCHES_TOTAL` | `obs:child_batch_dispatches_total` | flush_fn |
| `OBS_CHILD_ERROR_COUNTS_TOTAL` | `obs:child_error_counts_total` | flush_fn |
| `OBS_STRUCTURED_OUTPUT_FAILURES_TOTAL` | `obs:structured_output_failures_total` | flush_fn |

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
| `DYN_SKILL_INSTRUCTION` | `skill_instruction` |

### Cache

| Constant | Key String |
|----------|-----------|
| `CACHE_STORE` | `cache:store` |
| `CACHE_HIT_COUNT` | `cache:hit_count` |
| `CACHE_MISS_COUNT` | `cache:miss_count` |
| `CACHE_LAST_HIT_KEY` | `cache:last_hit_key` |

### Migration Status

| Constant | Key String |
|----------|-----------|
| `MIGRATION_STATUS` | `migration:status` |
| `MIGRATION_TIMESTAMP` | `migration:timestamp` |
| `MIGRATION_ERROR` | `migration:error` |

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

## Callback Lifecycles and Error Isolation

Worker agents inside the `WorkerPool` rely on critical callback logic (`rlm_adk/callbacks/worker.py`) for robustness.

- **Error Isolation (FM-20):** `worker_on_model_error` is an essential safety net for recursive dispatch. It catches exceptions thrown by an underlying LLM (e.g., rate limits, timeouts) and translates them into an `LlmResponse` holding the error state. This prevents a single child failure from crashing its sibling workers within a `ParallelAgent` batch, ensuring graceful degradation.
- **Result Extraction:** `worker_after_model` executes when a child completes successfully, extracting the result and preparing it for the orchestrator, and populating `agent._call_record`.

**Testing Context Keys:** `CB_REASONING_CONTEXT` and `CB_TOOL_CONTEXT` (and related test hook keys) are heavily used within these callbacks. During automated testing, callbacks inject their execution context into these state keys, allowing test fixtures to verify exact state transitions, prompt generation, and error isolation behavior without modifying the main execution path.

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
keys, submitted code keys, skill expansion keys, `ITERATION_COUNT`, `SHOULD_STOP`, and per-invocation token keys
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
- **2026-03-12 11:18** — `dispatch.py`, `state.py`: Added `instruction_router` and `fanout_idx` params to `create_dispatch_closures()`. flush_fn restores parent's `DYN_SKILL_INSTRUCTION` after child dispatch. Added `DYN_SKILL_INSTRUCTION` state key.
- **2026-03-15 15:42** — `dispatch.py`: Added branch isolation for child orchestrators via `ctx.model_copy()` + unique `branch` string (same pattern as ADK's `ParallelAgent`). Children no longer share the parent's event history, preventing context leakage across recursive layers.
- **2026-03-17 10:05** — `dispatch.py`: Moved `_classify_error()` here from deleted `callbacks/worker.py` (sole live consumer). `state.py`: Removed dead constants `CB_WORKER_CONTEXT`, `REASONING_CALL_START`, `REASONING_CONTENT_COUNT`, `REASONING_HISTORY_MSG_COUNT`.
- **2026-03-17 13:49** — `state.py`: Added `REPL_STATE_SNAPSHOT`, `EXPOSED_STATE_KEYS` frozenset (17 allowlisted keys for read-only REPL introspection). Enables provider-fake fixture code to inspect session state via `_rlm_state` dict.
- **2026-03-18 00:00** — `dispatch_and_state.md`: Added "Per-Iteration vs Cumulative Keys" section documenting cumulative dispatch counters (`obs:*_total`), mapping table, initialization semantics, and rationale for `_rlm_state` introspection stability.
- **2026-03-19 12:40** — `state.py`: Removed 12 dead state key definitions (`OBS_CHILD_DISPATCH_COUNT`, `OBS_CHILD_ERROR_COUNTS`, `OBS_CHILD_DISPATCH_LATENCY_MS`, `OBS_CHILD_TOTAL_BATCH_DISPATCHES`, cumulative `_TOTAL` variants, `OBS_STRUCTURED_OUTPUT_FAILURES`, `OBS_BUG13_SUPPRESS_COUNT`, `OBS_PER_ITERATION_TOKEN_BREAKDOWN`, `OBS_ARTIFACT_BYTES_SAVED`). `dispatch.py`: Removed 5 dead local accumulators (`_acc_child_dispatches`, `_acc_child_batch_dispatches`, `_acc_child_latencies`, `_acc_child_error_counts`, `_acc_structured_output_failures`) — accumulated but never read. Sqlite tracer derives equivalent metrics from its telemetry table. Part of three-plane (state/lineage/completion) cleanup.
- **2026-03-19 13:01** — `state.py`: Added `OBS_LITELLM_TOTAL_COST` constant for `litellm_cost_tracking.py` (was bare string). `litellm_cost_tracking.py`: Per-call cost moved from state to plugin instance attr (lineage data, not state); total cost now uses constant.

- **2026-03-21 16:30** — `state.py`: Added `parse_depth_key()`, `should_capture_state_key()`, `CURATED_STATE_KEYS`, `CURATED_STATE_PREFIXES` — extracted from `sqlite_tracing.py` for sharing with `dispatch.py`. `dispatch.py`: Added `child_event_queue` parameter to `create_dispatch_closures()`; `_run_child` filters and pushes curated child state-delta events onto queue. Added "Child Event Re-Emission" doc section. `[session: 1cffccc7]`

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
