<!-- validated: 2026-03-22 -->

# Dispatch System and State Management

Reference for `rlm_adk/dispatch.py` and `rlm_adk/state.py`. Covers the closure-based dispatch
pattern, working-state patch discipline, depth scoping, and the AR-CRIT-001 invariant.

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
    max_depth: int = 5,        # overridden by RLM_MAX_DEPTH env var
    instruction_router: Any = None,
    fanout_idx: int = 0,
    child_event_queue: asyncio.Queue[Event] | None = None,
) -> tuple[llm_query_async, llm_query_batched_async, post_dispatch_state_patch_fn]
```

The three closures share:

- A `_child_semaphore` (`asyncio.Semaphore`, sized by `RLM_MAX_CONCURRENT_CHILDREN`, default 3).
- A pre-computed `_parent_skill_instruction` (when `instruction_router` is provided).
- References to `dispatch_config`, `ctx`, `call_log_sink`, `trace_sink`, `depth`, `max_depth`, `instruction_router`, `fanout_idx`, and `child_event_queue`.

REPLTool injects `llm_query_async` and `llm_query_batched_async` into the REPL namespace. User
code calls `llm_query(prompt)`, the AST rewriter transforms it to `await llm_query_async(prompt)`,
and dispatch happens transparently.

---

## Working-State Patch and AR-CRIT-001

### Why the patch function exists

Writing `ctx.session.state[key] = value` inside a dispatch closure **bypasses ADK event tracking**.
The ADK Runner only commits state changes that arrive via tracked channels (tool context, event
actions, output keys). Direct session writes produce silent data loss -- state appears to update
locally but is never persisted or surfaced in the event stream.

This is codified as **AR-CRIT-001**: the critical invariant that all state mutations must flow
through ADK-tracked channels.

### How post_dispatch_state_patch_fn works

When an `instruction_router` is provided, `create_dispatch_closures` pre-computes
`_parent_skill_instruction = instruction_router(depth, fanout_idx)`. This cached value is used
by `post_dispatch_state_patch_fn` to restore the parent's skill instruction after child dispatch
(preventing child state from clobbering the parent's `DYN_SKILL_INSTRUCTION`).

`post_dispatch_state_patch_fn()` is called by REPLTool after each code execution (and on
cancellation/exception paths). It returns a minimal `dict[str, Any]` containing only
working-state keys that need restoration:

| State Key | Source | Present |
|-----------|--------|---------|
| `skill_instruction` (DYN_SKILL_INSTRUCTION) | `_parent_skill_instruction` | Only if instruction_router was provided |

REPLTool writes each returned key/value pair into `tool_context.state`, which is an ADK-tracked
channel.

> **Historical note:** This function was previously named `flush_fn` and flushed six local
> accumulators (`_acc_child_dispatches`, `_acc_child_batch_dispatches`, `_acc_child_latencies`,
> `_acc_child_error_counts`, `_acc_child_summaries`, `_acc_structured_output_failures`) plus
> per-iteration and cumulative obs dispatch keys. Those accumulators were removed in the
> three-plane cleanup (2026-03-19) because the SQLite tracer derives equivalent metrics from
> its telemetry table. The function was renamed to `post_dispatch_state_patch_fn` to reflect
> its reduced scope.

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

1. Create K tasks, each calling `_run_child(prompt, model, output_schema, fanout_idx)`.
2. `await asyncio.gather(*tasks)` -- semaphore gates actual concurrency inside `_run_child`.
3. Optionally record trace entries for REPL tracing (per-call timing, data flow edges).

---

## Child Lifecycle (_run_child)

Each child follows this sequence:

1. **Depth check** -- if `depth + 1 >= max_depth`, return an `LLMResult` with `error_category="DEPTH_LIMIT"` immediately.
2. **Create child orchestrator** -- `create_child_orchestrator(model, depth+1, prompt, worker_pool, output_schema)`.
3. **Run under semaphore** -- `async with _child_semaphore: async for event in child.run_async(child_ctx)`. State deltas from each event are collected into `_child_state`. When `child_event_queue` is provided, curated state-delta events are filtered through `should_capture_state_key(parse_depth_key(k)[0])` and pushed onto the queue via `put_nowait()` for parent re-emission.
4. **Read completion** -- `_read_child_completion(child, child_depth, _child_state)` normalizes the child's result by checking: `_rlm_terminal_completion` attribute (on orchestrator or reasoning_agent), `_structured_result`, `output_key` in child state, or error fallback.
5. **Build LLMResult** -- populated with text, parsed output, error info, wall time, finish reason.
6. **Record call log** -- appends an `RLMChatCompletion` to `call_log_sink` for REPL observability.
7. **Cleanup** -- if the child has a non-persistent REPL, call `child.repl.cleanup()`.

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
| `FINAL_RESPONSE_TEXT` | `final_response_text` | Yes |

### REPL State Introspection

| Constant | Key String | Description |
|----------|-----------|-------------|
| `REPL_STATE_SNAPSHOT` | `_rlm_state` | Read-only state dict injected into REPL globals |
| `EXPOSED_STATE_KEYS` | *(frozenset)* | 8 allowlisted keys for `_rlm_state` introspection |

`EXPOSED_STATE_KEYS` contains: `ITERATION_COUNT`, `CURRENT_DEPTH`, `APP_MAX_ITERATIONS`,
`APP_MAX_DEPTH`, `LAST_REPL_RESULT`, `STEP_MODE_ENABLED`, `SHOULD_STOP`, `FINAL_RESPONSE_TEXT`.

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

### Observability -- REPL / AST

| Constant | Key String | Written By |
|----------|-----------|------------|
| `OBS_REWRITE_COUNT` | `obs:rewrite_count` | REPLTool |
| `OBS_REWRITE_TOTAL_MS` | `obs:rewrite_total_ms` | REPLTool |
| `OBS_REWRITE_FAILURE_COUNT` | `obs:rewrite_failure_count` | REPLTool |
| `OBS_REWRITE_FAILURE_CATEGORIES` | `obs:rewrite_failure_categories` | REPLTool |
| `OBS_REASONING_RETRY_COUNT` | `obs:reasoning_retry_count` | orchestrator |
| `OBS_REASONING_RETRY_DELAY_MS` | `obs:reasoning_retry_delay_ms` | orchestrator |

### Observability -- Cost Tracking

| Constant | Key String | Written By |
|----------|-----------|------------|
| `OBS_LITELLM_TOTAL_COST` | `obs:litellm_total_cost` | LiteLLMCostTrackingPlugin |

> **Note:** `ObservabilityPlugin` no longer writes any state keys. All its counters
> (`_total_calls`, `_total_input_tokens`, `_total_output_tokens`, `_model_usage`,
> `_finish_reason_counts`, `_tool_invocation_summary`, etc.) live on plugin instance
> attributes. SQLite telemetry is the authoritative lineage sink. The 12 `OBS_*`
> constants that previously tracked global/dispatch counters in session state were
> removed in the three-plane cleanup.

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
| `APP_ARTIFACT_OFFLOAD_THRESHOLD` | `app:artifact_offload_threshold` |

### Test Hooks

| Constant | Key String |
|----------|-----------|
| `CB_REASONING_CONTEXT` | `cb_reasoning_context` |
| `CB_ORCHESTRATOR_CONTEXT` | `cb_orchestrator_context` |
| `CB_TOOL_CONTEXT` | `cb_tool_context` |

---

## state.py Function and Set Reference

| Name | Type | Description |
|------|------|-------------|
| `depth_key(key, depth)` | function | Returns depth-scoped key (`key@dN` for N > 0, `key` for N == 0) |
| `parse_depth_key(raw_key)` | function | Inverse of `depth_key()` -- returns `(base_key, depth, fanout_or_None)` |
| `should_capture_state_key(base_key)` | function | Returns `True` if key matches `CURATED_STATE_KEYS` or `CURATED_STATE_PREFIXES` |
| `DEPTH_SCOPED_KEYS` | `set[str]` | Keys requiring `@dN` scoping at depth > 0 |
| `EXPOSED_STATE_KEYS` | `frozenset[str]` | 8 keys allowlisted for `_rlm_state` REPL introspection |
| `CURATED_STATE_KEYS` | `frozenset[str]` | Exact keys captured for child event re-emission and SQLite tracing |
| `CURATED_STATE_PREFIXES` | `tuple[str, ...]` | Prefix patterns for curated state capture |

---

## Callback Lifecycles and Error Classification

Error classification for child dispatch failures is handled by `_classify_error()` in
`rlm_adk/dispatch.py`. This function was moved from the deleted `callbacks/worker.py`
(its sole live consumer). It classifies exceptions into categories:

| Category | Condition |
|----------|-----------|
| `TIMEOUT` | `asyncio.TimeoutError` or `litellm.Timeout` |
| `RATE_LIMIT` | HTTP 429 |
| `AUTH` | HTTP 401 / 403 |
| `SERVER` | HTTP 5xx |
| `CLIENT` | HTTP 4xx (other) |
| `NETWORK` | `ConnectionError` / `OSError` |
| `PARSE_ERROR` | `JSONDecodeError`, `ValueError` with JSON indicators |
| `UNKNOWN` | Default fallback |

**Testing Context Keys:** `CB_REASONING_CONTEXT` and `CB_TOOL_CONTEXT` (and related test hook
keys) are used within callbacks. During automated testing, callbacks inject their execution
context into these state keys, allowing test fixtures to verify exact state transitions, prompt
generation, and error isolation behavior without modifying the main execution path.

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

The `DEPTH_SCOPED_KEYS` set defines which keys require scoping. It includes `CURRENT_DEPTH`,
`ITERATION_COUNT`, `FINAL_RESPONSE_TEXT`, `LAST_REPL_RESULT`, `SHOULD_STOP`, all submitted code
keys, and all skill expansion keys. Global observability keys (`obs:*`) are intentionally
excluded -- they accumulate across all depths.

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

**In dispatch closures (via patch function):**

```python
# REPLTool calls post_dispatch_state_patch_fn() after execution:
delta = post_dispatch_state_patch_fn()
for key, value in delta.items():
    tool_context.state[key] = value  # Tracked channel
```

### Incorrect pattern

```python
# WRONG -- bypasses ADK event tracking entirely
async def llm_query_async(prompt, ...):
    ctx.session.state["skill_instruction"] = "..."  # SILENT DATA LOSS
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

### State mutation (AR-CRIT-001) -- repeated for emphasis

**NEVER** write `ctx.session.state[key] = value` in dispatch closures -- this bypasses ADK event tracking. The write appears to succeed at runtime but the Runner never sees it, so it is never persisted and does not appear in the event stream. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

---

## Recent Changes

> Append entries here when modifying source files documented by this branch. A stop hook (`ai_docs/scripts/check_doc_staleness.py`) will remind you.

<!-- Entries through 2026-03-21 have been incorporated into the main body. -->

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
