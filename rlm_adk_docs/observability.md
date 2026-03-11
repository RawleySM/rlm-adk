<!-- validated: 2026-03-10 -->

# Observability and Plugin Reference

This document covers the RLM-ADK observability stack: plugin architecture, callback
system, worker observability path, REPL tracing, and dashboard. For the full list
of state keys, see `dispatch_and_state.md`.

---

## 1. Plugin Architecture

All plugins extend `google.adk.plugins.base_plugin.BasePlugin` and are wired
during orchestrator creation in `rlm_adk/agent.py`. Plugins are observe-only:
they never return values and never block execution. Errors are caught and logged.

### Lifecycle Hooks

A plugin can implement any combination of:

| Hook | When it fires |
|------|---------------|
| `before_run_callback` / `after_run_callback` | Session start / end |
| `before_agent_callback` / `after_agent_callback` | Agent entry / exit |
| `before_model_callback` / `after_model_callback` | Before / after each LLM call |
| `on_model_error_callback` | LLM call failure |
| `before_tool_callback` / `after_tool_callback` | Before / after tool execution |
| `on_event_callback` | State-delta events |

### Registered Plugins

ObservabilityPlugin, SqliteTracingPlugin, REPLTracingPlugin, LangfuseTracingPlugin,
CachePlugin, PolicyPlugin, MigrationPlugin.

---

## 2. ObservabilityPlugin

**File:** `rlm_adk/plugins/observability.py`

Tracks token usage, finish reasons, tool counts, and timing for the reasoning
agent. It does **not** fire for workers (see section 8).

### Hook Points

1. **before_agent_callback** -- records `INVOCATION_START_TIME` if unset.
2. **after_model_callback** -- increments `OBS_TOTAL_CALLS`; extracts
   `prompt_token_count` and `candidates_token_count` from `usage_metadata`;
   accumulates into total-token counters; tracks finish reason as
   `obs:finish_{reason}_count`; appends per-iteration breakdown entry
   (iteration, input/output tokens, finish reason, agent type, prompt/system chars).
3. **before_tool_callback** -- increments `OBS_TOOL_INVOCATION_SUMMARY[tool_name]`.
4. **on_event_callback** -- tracks artifact saves from `artifact_delta`.
5. **after_agent_callback** -- re-persists ephemeral keys (see below).
6. **after_run_callback** -- logs final summary with reasoning/worker call counts,
   dispatch metrics, and latencies.

### Ephemeral Keys Workaround

Writes to `callback_context.state` inside `after_model_callback` do not land in
ADK `state_delta` events because `base_llm_flow.py` does not wire `event_actions`
for plugin callbacks. The workaround: `after_agent_callback` re-reads affected
keys from `session.state` and re-writes them through a properly-wired
`CallbackContext`, ensuring they appear in the event stream. Affected keys
include all `OBS_TOTAL_*` counters, `OBS_PER_ITERATION_TOKEN_BREAKDOWN`,
finish-reason counters, and `CONTEXT_WINDOW_SNAPSHOT`.

### Known Limitation

**Does not fire for workers.** ParallelAgent gives each worker an isolated
invocation context, so ObservabilityPlugin callbacks never trigger. Worker
metrics flow through the dispatch accumulator path instead (section 8).

---

## 3. SqliteTracingPlugin

**File:** `rlm_adk/plugins/sqlite_tracing.py`

Persists structured telemetry into `.adk/traces.db` (standard-library `sqlite3`,
no external dependencies). Uses a 3-table schema with migration logic for
evolving columns.

### Schema

#### `traces` table -- one row per invocation

| Column(s) | Type | Description |
|-----------|------|-------------|
| trace_id | TEXT PK | Unique trace identifier |
| session_id, user_id, app_name | TEXT | Session metadata |
| start_time, end_time, status | REAL/TEXT | Lifecycle timestamps + `running`/`completed` |
| total_input_tokens, total_output_tokens, total_calls, iterations | INT | Aggregate accounting |
| request_id, repo_url, root_prompt_preview, prompt_hash | TEXT | Request context + SHA-256 |
| child_dispatch_count, child_total_batch_dispatches | INT | Dispatch totals |
| child_error_counts, tool_invocation_summary | TEXT (JSON) | `{category: count}`, `{tool: count}` |
| finish_safety/recitation/max_tokens_count | INT | Finish-reason tallies |
| per_iteration_breakdown, model_usage_summary | TEXT (JSON) | Token breakdowns |
| artifact_saves, artifact_bytes_saved | INT | Artifact totals |
| max_depth_reached | INT | Deepest recursion depth observed |

#### `telemetry` table -- one row per model call or tool invocation

| Column(s) | Type | Description |
|-----------|------|-------------|
| telemetry_id | TEXT PK | Unique ID |
| trace_id | TEXT FK | Parent trace |
| event_type | TEXT | `model_call` or `tool_call` |
| agent_name, model | TEXT | Agent and model identifiers |
| iteration, depth, call_number | INT | Position in execution |
| start_time, end_time, duration_ms | REAL | Timing |
| input_tokens, output_tokens, thought_tokens | INT | Per-call token counts |
| finish_reason | TEXT | LLM finish reason |
| tool_name, tool_args_keys, result_preview | TEXT | Tool call details |
| repl_has_errors, repl_has_output | INT (bool) | REPL enrichment flags |
| repl_llm_calls, stdout_len, stderr_len | INT | REPL metrics |
| repl_trace_summary | TEXT (JSON) | Embedded trace summary |
| status, error_type, error_message | TEXT | Error tracking |

#### `session_state_events` table -- one row per curated state key change

| Column | Type | Description |
|--------|------|-------------|
| event_id | TEXT PK | Unique ID |
| trace_id | TEXT FK | Parent trace |
| seq | INT | Monotonic sequence |
| event_author | TEXT | Event source agent |
| event_time | REAL | Timestamp |
| state_key | TEXT | Raw key name |
| key_category | TEXT | `obs_reasoning`, `obs_dispatch`, `obs_artifact`, `obs_finish`, `flow_control`, `repl`, `cache`, `request_meta` |
| key_depth | INT | 0 for base, N for `@dN` |
| key_fanout | INT | Fanout index (nullable) |
| value_type | TEXT | `int`, `float`, `text`, `json` |
| value_int, value_float | NUMERIC | Typed value columns |
| value_text | TEXT | String value (truncated to 2000 chars) |
| value_json | TEXT | JSON-serialized value |

### Capture Strategy

Only state keys matching curated prefixes are captured: `obs:`, `artifact_`,
`last_repl_result`, `repl_submitted_code`, plus exact keys like
`iteration_count`, `should_stop`, `final_answer`, `request_id`, and cache
counters. Keys with `@d{N}` or `@d{N}f{M}` suffixes are parsed into
`key_depth` and `key_fanout` columns.

### REPL Enrichment

In `after_tool_callback`, when the tool is `execute_code`, the plugin resolves
`LAST_REPL_RESULT` by depth, then extracts `has_errors`, `has_output`,
`llm_calls`, `stdout_len`, `stderr_len`, and `trace_summary` into the
telemetry row for that tool call.

---

## 4. REPLTracingPlugin

**File:** `rlm_adk/plugins/repl_tracing.py`

Listens for `LAST_REPL_RESULT` state-delta events via `on_event_callback`.
Extracts the `trace_summary` field from each result dict and groups entries by
iteration and depth under a key of the form `d{depth}:i{iteration}`.

On `after_run_callback`, saves the accumulated dict as a `repl_traces.json`
artifact:

```json
{
  "d0:i0": {"depth": 0, "iteration": 0, "trace_summary": {...}},
  "d0:i1": {"depth": 0, "iteration": 1, "trace_summary": {...}},
  "d1:i0": {"depth": 1, "iteration": 0, "trace_summary": {...}}
}
```

Traces are only generated when `RLM_REPL_TRACE` >= 1 (see section 9).

---

## 5. LangfuseTracingPlugin

**File:** `rlm_adk/plugins/langfuse_tracing.py`

A thin wrapper around `openinference-instrumentation-google-adk` that
auto-instruments all ADK spans via OpenTelemetry.

### Required Environment Variables

| Variable | Example |
|----------|---------|
| `LANGFUSE_PUBLIC_KEY` | `pk-lf-rlm-local` |
| `LANGFUSE_SECRET_KEY` | `sk-lf-rlm-local` |
| `LANGFUSE_BASE_URL` | `http://localhost:3100` |

### Initialization

1. `__init__` calls `_init_langfuse_instrumentation()`.
2. Checks env vars; skips with warning if any are missing.
3. Imports `langfuse.get_client()` and `GoogleADKInstrumentor`.
4. Runs `auth_check()` against the Langfuse server.
5. Calls `GoogleADKInstrumentor().instrument()` (process-global, idempotent).

### What Gets Auto-Traced

Every model call, tool invocation, and agent transition becomes an OTel span
forwarded to the Langfuse UI. No manual span creation is needed.

---

## 6. Callback System

### Worker Callbacks

**File:** `rlm_adk/callbacks/worker.py`

**`worker_before_model`** -- reads `agent._pending_prompt` (set by the dispatch
closure) and injects it as `llm_request.contents` (user role, text part).

**`worker_after_model`** -- extracts response text from `llm_response.content.parts`
(skipping thought parts); detects safety filtering; writes to `agent._result` and
sets `agent._result_ready = True`; builds a `_call_record` dict containing
`prompt`, `response`, `input_tokens`, `output_tokens`, `model`, `finish_reason`,
`error`, and `error_category`; writes to `agent._call_record` for the dispatch
closure to consume.

**`worker_on_model_error`** -- catches LLM errors without crashing ParallelAgent
siblings. Classifies the error (TIMEOUT, RATE_LIMIT, AUTH, SERVER, CLIENT,
NETWORK, PARSE_ERROR, UNKNOWN) and writes error info to `agent._result` /
`agent._result_error`. Returns an `LlmResponse` so the agent completes normally.

### Reasoning Callbacks

**File:** `rlm_adk/callbacks/reasoning.py`

**`reasoning_before_model`** -- merges ADK's dynamic instruction into
`system_instruction`; records prompt/system char counts, content count, and
history message count; snapshots `CONTEXT_WINDOW_SNAPSHOT`.

**`reasoning_after_model`** -- splits response parts into visible and thought text;
records depth-scoped token keys (`REASONING_INPUT_TOKENS@d{depth}`, etc.);
extracts `reasoning_summary` from JSON responses.

---

## 7. WorkerRetryPlugin and BUG-13

**File:** `rlm_adk/callbacks/worker_retry.py`

### WorkerRetryPlugin

Extends ADK's `ReflectAndRetryToolPlugin`. Detects empty string values in
`set_model_response` tool results and triggers a retry via the parent class
reflection/retry mechanism. The `make_worker_tool_callbacks()` factory returns
`(after_tool_cb, on_tool_error_cb)` with positional-arg signatures wired by
`dispatch.py` when `output_schema` is provided.

### BUG-13 Monkey-Patch

ADK's `_output_schema_processor.get_structured_model_response()` prematurely
terminates workers whenever `set_model_response` is called -- even when the
response is a retry sentinel. The patch:

1. Installed at module import time via `_patch_output_schema_postprocessor()`.
2. Wraps the original function.
3. Detects the `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel in the response.
4. Returns `None` to suppress termination, allowing the retry loop to continue.
5. Idempotent and process-global (safe under asyncio).

**Observability:** `_bug13_stats["suppress_count"]` is a process-global counter
incremented on each suppression. Tests read this to verify the patch fires at
runtime, not just that it was installed.

---

## 8. Worker Observability Path

Because ObservabilityPlugin does not fire for workers, all worker metrics flow
through dispatch closures and local accumulators (AR-CRIT-001).

```
  worker LLM call completes
          |
          v
  worker_after_model callback
    writes agent._call_record = {prompt, response, tokens, error...}
    writes agent._result, agent._result_ready
          |
          v
  ParallelAgent completes batch, returns agent objects
          |
          v
  dispatch closure reads each agent._call_record
          |
          v
  local accumulators (never session.state -- AR-CRIT-001):
    _acc_child_dispatches        count of workers
    _acc_child_batch_dispatches  count of batch calls
    _acc_child_latencies         list of elapsed_ms per batch
    _acc_child_error_counts      {error_category: count}
    _acc_child_summaries         {per-child telemetry dict}
    _acc_structured_output_failures  validation failure count
          |
          v
  REPLTool calls flush_fn() after each REPL execution
          |
          v
  flush_fn snapshots accumulators into tool_context.state:
    OBS_CHILD_DISPATCH_COUNT
    OBS_CHILD_DISPATCH_LATENCY_MS
    OBS_CHILD_TOTAL_BATCH_DISPATCHES
    OBS_CHILD_ERROR_COUNTS
    OBS_STRUCTURED_OUTPUT_FAILURES
    obs:child_summary@d{depth}f{fanout_idx}
    OBS_BUG13_SUPPRESS_COUNT (if > 0)
          |
          v
  accumulators reset for next iteration
          |
          v
  SqliteTracingPlugin.on_event_callback picks up state_delta
    -> inserts session_state_events rows
```

### Error Classification

`_classify_error(exception)` in `worker.py` maps exceptions to categories:

| Category | Trigger |
|----------|---------|
| RATE_LIMIT | HTTP 429 |
| AUTH | HTTP 401 / 403 |
| SERVER | HTTP 5xx |
| CLIENT | HTTP 4xx (other) |
| NETWORK | Connection / DNS errors |
| TIMEOUT | Timeout errors |
| PARSE_ERROR | Response parsing failures |
| UNKNOWN | Everything else |

In the fake provider test environment, errors classify as UNKNOWN because fake
server exceptions lack the `.code` attribute.

---

## 9. Skill Expansion Observability Keys

**Written by:** `REPLTool.run_async()` in `rlm_adk/tools/repl_tool.py`

When REPLTool expands synthetic skill imports (see `skills_and_prompts.md` section 8), it writes four depth-scoped state keys to `tool_context.state`. These are **additive** -- they do not replace the existing submitted code keys (`REPL_SUBMITTED_CODE`, `REPL_SUBMITTED_CODE_HASH`, etc.), which continue to capture the original code as written by the model.

| Key | Constant | Type | Description |
|-----|----------|------|-------------|
| `repl_expanded_code` | `REPL_EXPANDED_CODE` | `str` | Full expanded source text (with skill source inlined) |
| `repl_expanded_code_hash` | `REPL_EXPANDED_CODE_HASH` | `str` | SHA-256 hex digest of the expanded source |
| `repl_skill_expansion_meta` | `REPL_SKILL_EXPANSION_META` | `dict` | `{"symbols": [...], "modules": [...]}` -- lists of expanded symbol names and synthetic module paths |
| `repl_did_expand` | `REPL_DID_EXPAND` | `bool` | `True` when expansion occurred; key is absent when no synthetic imports were detected |

All four keys are **depth-scoped** (listed in `DEPTH_SCOPED_KEYS` in `state.py`). At depth 0 the keys are bare; at depth N they are suffixed `@dN` (e.g. `repl_expanded_code@d1`).

These keys are only written when `expand_skill_imports()` returns `did_expand=True`. If the submitted code contains no `from rlm_repl_skills.*` imports, none of these keys are set.

**Relationship to existing keys:**

| What | Key | Content |
|------|-----|---------|
| Original submitted code | `REPL_SUBMITTED_CODE` | Code as the model wrote it (with synthetic imports) |
| Expanded executed code | `REPL_EXPANDED_CODE` | Code actually executed (synthetic imports replaced with inline source) |

This split enables debugging expansion issues: compare the submitted code hash to the expanded code hash to determine whether expansion changed the code, and inspect `REPL_SKILL_EXPANSION_META` to see exactly which symbols were inlined.

---

## 10. REPL Trace Infrastructure

**File:** `rlm_adk/repl/trace.py`

### Trace Levels

Controlled by the `RLM_REPL_TRACE` environment variable:

| Level | What it captures |
|-------|-----------------|
| 0 (default) | Off -- no tracing overhead |
| 1 | LLM call timing, variable snapshots, data flow tracking |
| 2 | Level 1 + `tracemalloc` memory tracking via injected code header/footer |

### REPLTrace Dataclass

Per-code-block accumulator with fields:

- `start_time`, `end_time` (serialized as `wall_time_ms`)
- `llm_calls` -- list of `{index, type, start_time, prompt_len, elapsed_ms, response_len, error}`
- `var_snapshots` -- list of `{label, time, vars}`
- `peak_memory_bytes` -- from tracemalloc (level 2 only)
- `exceptions` -- list of error events
- `data_flow_edges` -- list of `(source_index, target_index)` tuples
- `execution_mode` -- `"sync"` or `"async"`
- `submitted_code_chars`, `submitted_code_hash`, `submitted_code_preview`

### DataFlowTracker

Detects when one `llm_query()` response feeds into a subsequent prompt:

1. Maintains `_responses` dict mapping `call_index` to response text.
2. On each new prompt, `check_prompt()` tests whether a substring fingerprint
   (default 40 chars) of any prior response appears in the current prompt.
3. Records detected edges as `(source_index, target_index)`.

### Code Injection (Level 2)

At trace level 2, `TRACE_HEADER_MEMORY` and `TRACE_FOOTER_MEMORY` strings are
injected before/after user code. These start/stop `tracemalloc` and capture
peak memory into the shared `_rlm_trace` object.

---

## 11. Dashboard

**Directory:** `rlm_adk/dashboard/`

Streamlit-based UI. Reads `.adk/context_snapshots.jsonl` and
`.adk/model_outputs.jsonl`. `data_loader.py` groups by session into
`SessionSummary` + `IterationData`. Components: `api_usage.py` (token charts),
`token_charts.py` (per-iteration breakdowns), `worker_panel.py` (dispatch
metrics), `output_panel.py` (final answer), `context_bar.py` (depth/iteration
navigation).

---

## ADK Gotchas

### Private API: CallbackContext._invocation_context.agent

ADK's `CallbackContext` does not expose `.agent` as a public property. To access the agent from inside a callback:

```python
# WRONG
agent = callback_context.agent

# CORRECT
agent = callback_context._invocation_context.agent
```

Used in:
- `callbacks/worker_retry.py` — `after_tool_cb` reads the agent to set `_structured_result`
- `callbacks/reasoning.py` — accesses agent name and depth for observability
- `plugins/observability.py` — reads agent type for per-iteration breakdown

**Risk:** This is a private API. An ADK update could rename or restructure `_invocation_context`. If it breaks, callbacks lose agent access.

### Ephemeral state keys in plugin callbacks

Writes to `callback_context.state` in `after_model_callback` do NOT land in `state_delta` on yielded Events. ADK's `base_llm_flow.py` does not wire `event_actions` for plugin `after_model_callback`.

**Workaround:** `ObservabilityPlugin.after_agent_callback` re-reads affected keys from `session.state` and re-writes them via a properly-wired `CallbackContext`. Without this, keys like `OBS_TOTAL_CALLS`, `OBS_TOTAL_INPUT_TOKENS`, `OBS_TOTAL_OUTPUT_TOKENS`, `OBS_PER_ITERATION_TOKEN_BREAKDOWN`, finish-reason counters, and `CONTEXT_WINDOW_SNAPSHOT` appear in `session.state` (in-memory) but are invisible to `SqliteTracingPlugin.on_event_callback` and any other event-driven consumer.

### ADK coupling risk table

| Dependency | Location | Risk |
|-----------|----------|------|
| `_output_schema_processor.get_structured_model_response` | `worker_retry.py` BUG-13 patch | Module restructure breaks patch (graceful fallback) |
| `CallbackContext._invocation_context.agent` | Multiple callbacks | Private API rename breaks agent access |
| `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel | `worker_retry.py` | Sentinel value change breaks retry detection |
| Plugin callback wiring in `base_llm_flow.py` | `observability.py` | Ephemeral state workaround depends on current wiring gaps |

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
- **2026-03-10** — Added section 9 (Skill Expansion Observability Keys) documenting REPL_EXPANDED_CODE, REPL_EXPANDED_CODE_HASH, REPL_SKILL_EXPANSION_META, REPL_DID_EXPAND.

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
