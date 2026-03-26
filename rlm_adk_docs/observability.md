<!-- validated: 2026-03-26 -->

# Observability and Plugin Reference

This document covers the RLM-ADK observability stack: plugin architecture, callback
system, child dispatch observability path, REPL tracing, and dashboard. For the full list
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
agent. All counters are instance-local attributes on the plugin -- no
observability keys are written to session state. SQLite telemetry is the
authoritative lineage sink. The plugin does **not** fire for child
orchestrators (see section 8).

### Hook Points

1. **before_agent_callback** -- records `INVOCATION_START_TIME` if unset.
2. **after_model_callback** -- increments instance-local `_total_calls`;
   extracts `prompt_token_count` and `candidates_token_count` from
   `usage_metadata`; accumulates into `_total_input_tokens` /
   `_total_output_tokens`; tracks per-model usage in `_model_usage`;
   records non-STOP finish reasons in `_finish_reason_counts`. Consumes
   `_rlm_pending_request_meta` from the agent (set by
   `reasoning_before_model`) for prompt/system char counts.
3. **before_tool_callback** -- increments `_tool_invocation_summary[tool_name]`.
4. **on_event_callback** -- tracks artifact saves from `artifact_delta` into
   `_artifact_saves_acc`.
5. **after_agent_callback** -- logs agent exit.
6. **after_run_callback** -- logs final summary with call counts, token totals,
   execution time, and artifact saves.

### Known Limitation

**Does not fire for child orchestrators.** Each child orchestrator runs in a
branch-isolated invocation context, so ObservabilityPlugin callbacks never
trigger for child dispatch calls. Child telemetry flows through the
SqliteTracingPlugin telemetry table instead (see section 8).

---

## 3. SqliteTracingPlugin

**File:** `rlm_adk/plugins/sqlite_tracing.py`

Persists structured telemetry into `.adk/traces.db` (standard-library `sqlite3`,
no external dependencies). Uses a 3-table + 1 first-class table schema with
migration logic for evolving columns, plus 4 SQL views for query convenience.

> **Note on `spans` table:** The legacy `spans` table is no longer created on
> fresh databases. Pre-existing databases retain the table harmlessly (no
> `DROP TABLE` is issued), but no code writes to it. All span-like data now
> lives in the `telemetry` table rows and the SQL views derived from them.

### Schema

#### `traces` table -- one row per invocation

| Column(s) | Type | Description |
|-----------|------|-------------|
| trace_id | TEXT PK | Unique trace identifier |
| session_id, user_id, app_name | TEXT | Session metadata |
| start_time, end_time, status | REAL/TEXT | Lifecycle timestamps + `running`/`completed` |
| total_input_tokens, total_output_tokens, total_calls, iterations | INT | Aggregate accounting |
| request_id, repo_url, root_prompt_preview, prompt_hash | TEXT | Request context + SHA-256 |
| child_dispatch_count, child_total_batch_dispatches | INT | Dispatch totals (computed from telemetry rows at run end) |
| child_error_counts, tool_invocation_summary | TEXT (JSON) | `{category: count}`, `{tool: count}` |
| finish_safety/recitation/max_tokens_count | INT | Finish-reason tallies |
| model_usage_summary | TEXT (JSON) | Token breakdowns per model |
| artifact_saves | INT | Artifact save count |
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
| skill_instruction | TEXT | Active skill instruction text at time of model call |
| fanout_idx, parent_depth, parent_fanout_idx | INT | Lineage coordinates |
| branch, invocation_id, session_id | TEXT | Invocation context |
| output_schema_name | TEXT | Pydantic schema name (if structured output) |
| decision_mode, structured_outcome | TEXT | Structured output flow tracking |
| terminal_completion | INT | Whether this call produced a terminal completion |
| completion_display_text | TEXT | Human-readable completion text (from CompletionEnvelope) |
| completion_reasoning_summary | TEXT | Reasoning summary at completion time |
| completion_error_category | TEXT | Error category if completion was an error |
| completion_mode | TEXT | Completion mode (e.g. `set_model_response`) |
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
| key_category | TEXT | `obs_artifact`, `flow_control`, `repl`, `cache`, `request_meta`, `other` |
| key_depth | INT | 0 for base, N for `@dN` |
| key_fanout | INT | Fanout index (nullable) |
| value_type | TEXT | `int`, `float`, `text`, `json` |
| value_int, value_float | NUMERIC | Typed value columns |
| value_text | TEXT | String value (truncated to 2000 chars) |
| value_json | TEXT | JSON-serialized value |

#### `completion_records` table -- one row per completion event

A first-class table for completion data, written through three distinct write
paths (see "Completion Persistence" below). The `producer_type` discriminator
identifies which callback produced each row.

| Column | Type | Description |
|--------|------|-------------|
| completion_id | TEXT PK | Unique completion identifier |
| telemetry_id | TEXT | FK to the telemetry row that triggered this completion (nullable) |
| trace_id | TEXT FK | Parent trace |
| producer_type | TEXT NOT NULL | Discriminator: `model`, `orchestrator`, or `orchestrator_error` |
| terminal | INT | Whether this was a terminal (final) completion |
| mode | TEXT NOT NULL | Completion mode (e.g. `set_model_response`) |
| output_schema_name | TEXT | Pydantic schema name (if structured output) |
| validated_output | TEXT (JSON) | JSON-serialized validated output |
| raw_output | TEXT | Raw output string (truncated to 2000 chars) |
| display_text | TEXT | Human-readable display text (truncated to 2000 chars) |
| reasoning_summary | TEXT | Reasoning summary (truncated to 500 chars) |
| finish_reason | TEXT | LLM finish reason |
| error | INT | Whether this completion was an error (0/1) |
| error_category | TEXT | Error classification category |
| agent_name | TEXT | Agent that produced this completion |
| depth | INT | Recursion depth |
| fanout_idx | INT | Fanout index |
| created_at | REAL | Insertion timestamp |

#### SQL Views

Four SQL views are created for query convenience. These are defined in
`_SCHEMA_SQL` and created on fresh databases alongside the tables. On
migrated databases, views are created by the migration logic.

**`session_state_events_unified`** -- Flattens the typed value columns of
`session_state_events` into a single `value` column via `COALESCE` across
`value_text`, `value_int`, `value_float`, and `value_json`. Use this view
when you want a single human-readable value column without caring about the
underlying storage type.

**`execution_observations`** -- Projects timing, token counts, REPL outcomes,
and error information from all `telemetry` rows (no filter). Includes
`duration_ms`, `input_tokens`, `output_tokens`, `thought_tokens`,
`finish_reason`, `status`, `error_type`, `error_message`, `execution_mode`,
tool-call details, and REPL enrichment columns (`repl_has_errors`,
`repl_has_output`, `repl_llm_calls`, `repl_stdout_len`, `repl_stderr_len`,
`repl_trace_summary`). Use this view for performance analysis, error
investigation, and REPL execution monitoring.

**`telemetry_completions`** -- Filters `telemetry` to rows where
`decision_mode = 'set_model_response'` only. Projects completion-specific
columns: `structured_outcome`, `terminal_completion`, `output_schema_name`,
`validated_output_json`, `result_preview`, `result_payload`, and the four
inline completion columns (`completion_display_text`,
`completion_reasoning_summary`, `completion_error_category`,
`completion_mode`). `finish_reason` is deliberately excluded because it is
always NULL on tool-call rows. Use this view to inspect structured output
outcomes and completion decisions without scanning the full telemetry table.

**`lineage_records`** -- Projects tree-structure edge columns from all
`telemetry` rows: `agent_name`, `agent_type`, `iteration`, `depth`,
`fanout_idx`, `parent_depth`, `parent_fanout_idx`, `branch`,
`invocation_id`, `session_id`, `output_schema_name`, `decision_mode`,
`structured_outcome`, `terminal_completion`. Use this view for provenance
queries, depth analysis, and reconstructing the execution tree.

### Completion Persistence

Completion data is written through three distinct paths, each triggered by a
different callback. All three paths write to the `completion_records` table
via the `_insert_completion_record()` helper.

**Write path 1: `_flush_deferred_tool_lineage()`** -- Captures per-
`set_model_response` completions from the reasoning agent. Called at
`before_model_callback`, `after_agent_callback`, and `after_run_callback`
flush points. Reads the `CompletionEnvelope` from
`agent._rlm_terminal_completion` and writes with `producer_type='model'`.
The `telemetry_id` is set to the deferred tool entry's telemetry row.

**Write path 2: `after_run_callback`** -- Captures the root orchestrator's
final answer. Reads `_rlm_terminal_completion` from
`invocation_context.agent`. Writes with `producer_type='orchestrator'` (or
`'orchestrator_error'` if the completion has `error=True`). Anchors to the
most recent terminal `set_model_response` telemetry row at depth 0 via a
SQL lookup.

**Write path 3: `after_agent_callback`** -- Captures child orchestrator
completions at depth > 0. Gated by `isinstance(agent, RLMOrchestratorAgent)`
to prevent reasoning agent leakage (reasoning agent completions are already
captured by write path 1). Writes with `producer_type='orchestrator'` (or
`'orchestrator_error'`). `telemetry_id` is NULL because child orchestrator
agent callbacks do not have a direct telemetry row anchor.

### Capture Strategy

Only state keys matching curated sets are captured. The curated set is defined
in `rlm_adk/state.py` (`CURATED_STATE_KEYS` and `CURATED_STATE_PREFIXES`) and
shared with `dispatch.py` and `sqlite_tracing.py`. The plugin imports
`parse_depth_key` and `should_capture_state_key` from `state.py` (with thin
aliases `_parse_key` and `_should_capture` preserving internal call sites).

**Curated exact keys:** `current_depth`, `iteration_count`, `should_stop`,
`final_response_text`, `last_repl_result`, `skill_instruction`.

**Curated prefixes:** `obs:`, `artifact_`, `last_repl_result`,
`repl_skill_globals`, `repl_submitted_code`, `reasoning_`, `final_answer`.

Keys with `@d{N}` or `@d{N}f{M}` suffixes are parsed into `key_depth` and
`key_fanout` columns. Key categorization is handled by a plugin-local
`_categorize_key()` function that maps base keys to one of the categories
listed in the schema above.

### Child Event Re-Emission

Rows with `key_depth > 0` represent state changes from recursive child
orchestrators. These events are re-emitted from `dispatch.py` via an
`asyncio.Queue` bridge and drained in the parent orchestrator's yield loop.
The `event_author` column carries the child's agent name (e.g.
`child_reasoning_d1`), enabling provenance queries. See
`dispatch_and_state.md` "Child Event Re-Emission" for the full mechanism.

### Skill Instruction Capture

The `skill_instruction` telemetry column captures `callback_context.state[DYN_SKILL_INSTRUCTION]` at `before_model_callback` time, recording which skill instruction was active for each model call. This enables per-call attribution of instruction routing decisions.

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

## 5.1 Additional Plugins

Several other specialized plugins manage state, cost, and lifecycle migrations:

- **`MigrationPlugin`** (`rlm_adk/plugins/migration.py`): Handles schema migrations for state files or databases when moving between RLM-ADK versions.
- **`ContextSnapshotPlugin`** (`rlm_adk/plugins/context_snapshot.py`): Periodically saves copies of the current context window or state dictionary for debugging or UI replay.
- **`LiteLLMCostTrackingPlugin`** (`rlm_adk/plugins/litellm_cost_tracking.py`): Integrates with LiteLLM to provide precise API cost estimation based on the extracted token usage counts.

---

## 6. Callback System

### Worker Callbacks

The original `rlm_adk/callbacks/worker.py` has been removed. The leaf
LlmAgent worker pool was replaced by recursive child orchestrators
(`dispatch.py`). Worker-level callbacks (`worker_before_model`,
`worker_after_model`, `worker_on_model_error`) no longer exist. Error
classification (`_classify_error`) has moved to `rlm_adk/dispatch.py`
(see section 8).

### Reasoning Callbacks

**File:** `rlm_adk/callbacks/reasoning.py`

**`reasoning_before_model`** -- merges ADK's dynamic instruction into
`system_instruction`; records prompt/system char counts and content count
into `_rlm_pending_request_meta` on the agent (consumed by
ObservabilityPlugin's `after_model_callback`).

**`reasoning_after_model`** -- splits response parts into visible and thought
text; stores per-invocation response metadata (`input_tokens`,
`output_tokens`, `thought_tokens`, `finish_reason`, `reasoning_summary`) on
the agent as `_rlm_last_response_meta`; injects lineage into
`llm_response.custom_metadata`.

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

## 8. Child Dispatch Observability Path

Child sub-LM queries are dispatched via recursive child orchestrators (not
leaf LlmAgent workers). Each child orchestrator runs with its own REPL,
callbacks, and plugin stack in a branch-isolated invocation context.
ObservabilityPlugin does not fire for children, so child telemetry flows
through two paths: the telemetry table and the child event re-emission queue.

```
  parent REPL code calls llm_query_async() or llm_query_batched_async()
          |
          v
  dispatch.py spawns child RLMOrchestratorAgent at depth+1
    (semaphore-limited concurrency via _child_semaphore)
          |
          v
  child orchestrator runs (reasoning_agent + REPLTool + plugins)
    SqliteTracingPlugin on the child writes telemetry rows directly
          |
          v
  child yields events; dispatch.py iterates child.run_async():
    - accumulates state_delta into _child_state dict
    - curated state keys pushed onto child_event_queue (asyncio.Queue)
      for parent re-emission
          |
          v
  child completes; _read_child_completion() extracts result:
    priority: CompletionEnvelope > _structured_result > output_key > error
          |
          v
  dispatch closure returns LLMResult to REPL code
    _build_call_log() appends RLMChatCompletion to call_log_sink
          |
          v
  parent orchestrator drains child_event_queue in yield loop
    re-emits curated child state deltas with rlm_child_event metadata
          |
          v
  SqliteTracingPlugin.on_event_callback picks up re-emitted events
    -> inserts session_state_events rows with key_depth > 0
```

### Trace Summary Derivation

At `after_run_callback`, SqliteTracingPlugin builds the trace summary
entirely from the `telemetry` table (not from session state keys). It
queries aggregate token counts, finish-reason distributions, tool invocation
counts, max depth, and child dispatch counts (tool_call rows at depth > 0)
directly from SQLite.

### Error Classification

`_classify_error(exception)` in `rlm_adk/dispatch.py` maps exceptions to
categories:

| Category | Trigger |
|----------|---------|
| TIMEOUT | `asyncio.TimeoutError` or `litellm.Timeout` |
| RATE_LIMIT | HTTP 429 |
| AUTH | HTTP 401 / 403 |
| SERVER | HTTP 5xx |
| CLIENT | HTTP 4xx (other) |
| NETWORK | Connection / DNS errors |
| PARSE_ERROR | JSON decode / malformed response errors |
| UNKNOWN | Everything else |

The function checks both `.code` and `.status_code` attributes (the latter
for LiteLLM compatibility). In the fake provider test environment, errors
classify as UNKNOWN because fake server exceptions lack these attributes.

---

## 9. REPL Trace Infrastructure

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

## 10. Dashboard

**Directory:** `rlm_adk/dashboard/`

NiceGUI-based UI. Reads `.adk/context_snapshots.jsonl` and
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

**Current status:** ObservabilityPlugin no longer writes observability counters
to session state (all counters are instance-local), so this limitation no
longer requires a workaround. It remains documented because any future plugin
that needs state-delta visibility from `after_model_callback` will encounter
the same issue.

### ADK coupling risk table

| Dependency | Location | Risk |
|-----------|----------|------|
| `_output_schema_processor.get_structured_model_response` | `worker_retry.py` BUG-13 patch | Module restructure breaks patch (graceful fallback) |
| `CallbackContext._invocation_context.agent` | Multiple callbacks | Private API rename breaks agent access |
| `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel | `worker_retry.py` | Sentinel value change breaks retry detection |

### State mutation (AR-CRIT-001)

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. The write appears to succeed at runtime but the Runner never sees it, so it is never persisted and does not appear in the event stream. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

---

## Recent Changes

> Append entries here when modifying source files documented by this branch. A stop hook (`ai_docs/scripts/check_doc_staleness.py`) will remind you.

<!-- Entries incorporated into the main body on 2026-03-22:
- 2026-03-17 09:15: reasoning.py dead state writes removal
- 2026-03-18 00:00: section 8.1 cumulative dispatch keys (removed -- accumulators no longer exist)
- 2026-03-19 12:40: OBS_ARTIFACT_BYTES_SAVED removal, dead _categorize_key rules, three-plane cleanup
- 2026-03-21 16:30: sqlite_tracing.py imports from state.py, child event re-emission subsection
-->

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
- **2026-03-25 16:55** — `rlm_adk/plugins/sqlite_tracing.py`: Pre-existing uncommitted change: added `tool_args_json TEXT` column to telemetry table schema; serializes tool args for non-execute_code tools in `after_tool_callback` `[session: cd2d9e3f]`
- **2026-03-26 00:00** — `rlm_adk/plugins/sqlite_tracing.py`: Telemetry schema refactor: removed `spans` table from fresh DB creation; added 4 inline completion columns to `telemetry` (`completion_display_text`, `completion_reasoning_summary`, `completion_error_category`, `completion_mode`); added `completion_records` table with `producer_type` discriminator; added 4 SQL views (`session_state_events_unified`, `execution_observations`, `telemetry_completions`, `lineage_records`); added 3 completion write paths (`_flush_deferred_tool_lineage` / `after_run_callback` / `after_agent_callback`)
