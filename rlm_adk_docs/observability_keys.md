# Observability Keys Reference

All session-scoped state keys used for observability across the RLM ADK runtime.
Keys use the `obs:` naming convention prefix (session-scoped, not a true ADK scope).

## Architecture Overview

```
+-----------------------------------------------------------------+
|  Root Orchestrator (depth=0)                                     |
|                                                                  |
|  reasoning_agent --> REPLTool.run_async()                        |
|       |                    |                                     |
|       |              writes OBS_REWRITE_COUNT,                   |
|       |              OBS_REWRITE_TOTAL_MS (before exec)          |
|       |                    |                                     |
|       |              calls flush_fn()                            |
|       |                    |                                     |
|       |              +-----v------+                              |
|       |              | Dispatch   |  _acc_child_dispatches        |
|       |              | Closures   |  _acc_child_latencies         |
|       |              |            |  _acc_child_error_counts      |
|       |              |            |  _acc_child_batch_dispatches  |
|       |              |            |  _acc_structured_output_fail  |
|       |              |            |  _acc_child_summaries         |
|       |              |            |    .prompt_preview (500ch)    |
|       |              |            |    .result_preview (500ch)    |
|       |              |            |    .error_message             |
|       |              |            |  _bug13_stats (process-global)|
|       |              +-----+------+                              |
|       |                    | spawns                               |
|       |              +-----v----------------------+              |
|       |              | Child Orchestrator(d=1)    |              |
|       |              |  reasoning + REPLTool      |              |
|       |              |  + own dispatch closures   |              |
|       |              +----------------------------+              |
|       |                                                          |
|  Orchestrator retry loop --> OBS_REASONING_RETRY_COUNT (Event)   |
|  ObservabilityPlugin <-- after_model (reasoning-level tokens)    |
|  SqliteTracingPlugin <-- 4-table schema (traces/telemetry/SSE/spans)|
|  REPLTracingPlugin   <-- reads LAST_REPL_RESULT + ITERATION_COUNT|
+-----------------------------------------------------------------+
```

**Key insight:** ObservabilityPlugin does NOT fire for child orchestrators -- each child
gets an isolated `InvocationContext`.  Child obs data flows through:

```
child orchestrator -> _classify_error -> LLMResult.error* fields
  -> parent dispatch accumulator vars -> flush_fn() -> tool_context.state
    -> ObservabilityPlugin reads at run end
```

---

## Key Reference

### Reasoning-Level Keys (ObservabilityPlugin)

Written by `ObservabilityPlugin.after_model_callback` and persisted via `after_agent_callback`.

| Constant | State Key | Type | Writer | Description |
|---|---|---|---|---|
| `OBS_TOTAL_CALLS` | `obs:total_calls` | `int` | ObservabilityPlugin | Cumulative LLM call count (reasoning-level only) |
| `OBS_TOTAL_INPUT_TOKENS` | `obs:total_input_tokens` | `int` | ObservabilityPlugin | Cumulative input tokens (reasoning) |
| `OBS_TOTAL_OUTPUT_TOKENS` | `obs:total_output_tokens` | `int` | ObservabilityPlugin | Cumulative output tokens (reasoning) |
| `OBS_TOTAL_EXECUTION_TIME` | `obs:total_execution_time` | `float` | ObservabilityPlugin (after_run) | Wall-clock run time in seconds |
| `OBS_PER_ITERATION_TOKEN_BREAKDOWN` | `obs:per_iteration_token_breakdown` | `list[dict]` | ObservabilityPlugin | Per-call breakdown with iteration, tokens, finish_reason, agent_type |
| `OBS_TOOL_INVOCATION_SUMMARY` | `obs:tool_invocation_summary` | `dict[str,int]` | ObservabilityPlugin (before_tool) | Tool name -> invocation count map |
| `obs_model_usage_key(model)` | `obs:model_usage:{model}` | `dict` | ObservabilityPlugin | Per-model `{calls, input_tokens, output_tokens}` |

**ADK limitation:** `OBS_TOTAL_EXECUTION_TIME` is written by `after_run_callback` to
`invocation_context.session.state`, but does NOT appear in `get_session` final_state.
It IS available to other plugins sharing the same `after_run_callback` invocation
(e.g., SqliteTracingPlugin reads it in its own `after_run_callback`).

### Finish Reason Tracking (ObservabilityPlugin)

Written by `ObservabilityPlugin.after_model_callback` when `finish_reason != "STOP"`.

| Constant | State Key | Type | Description |
|---|---|---|---|
| `OBS_FINISH_SAFETY_COUNT` | `obs:finish_safety_count` | `int` | Count of SAFETY finish reasons |
| `OBS_FINISH_RECITATION_COUNT` | `obs:finish_recitation_count` | `int` | Count of RECITATION finish reasons |
| `OBS_FINISH_MAX_TOKENS_COUNT` | `obs:finish_max_tokens_count` | `int` | Count of MAX_TOKENS finish reasons |
| *(dynamic)* | `obs:finish_{reason}_count` | `int` | Any other finish reason, lowercased |

### Child Dispatch Keys (flush_fn)

Written by `dispatch.create_dispatch_closures` -> `flush_fn()` -> consumed by `REPLTool.run_async()` into `tool_context.state`.

| Constant | State Key | Type | Accumulator | Description |
|---|---|---|---|---|
| `OBS_CHILD_DISPATCH_COUNT` | `obs:child_dispatch_count` | `int` | `_acc_child_dispatches` | Total child dispatches per flush |
| `OBS_CHILD_DISPATCH_LATENCY_MS` | `obs:child_dispatch_latency_ms` | `list[float]` | `_acc_child_latencies` | Per-dispatch latency in ms |
| `OBS_CHILD_TOTAL_BATCH_DISPATCHES` | `obs:child_total_batch_dispatches` | `int` | `_acc_child_batch_dispatches` | Count of batch dispatches (k>1) |
| `OBS_CHILD_ERROR_COUNTS` | `obs:child_error_counts` | `dict[str,int]` | `_acc_child_error_counts` | Error category -> count |
| `OBS_STRUCTURED_OUTPUT_FAILURES` | `obs:structured_output_failures` | `int` | `_acc_structured_output_failures` | Count of schema validation exhaustions |
| `OBS_BUG13_SUPPRESS_COUNT` | `obs:bug13_suppress_count` | `int` | `_bug13_stats["suppress_count"]` | BUG-13 monkey-patch invocations (process-global counter, included when > 0) |

### Child Summary Keys (Fanout Tracking)

| Function | State Key | Type | Writer | Description |
|---|---|---|---|---|
| `child_obs_key(depth, idx)` | `obs:child_summary@d{depth}f{idx}` | `dict` | dispatch closures | Per-child summary keyed by depth and fanout index |

Each child summary dict contains:

| Field | Type | Description |
|---|---|---|
| `model` | `str` | Target model used for the child dispatch |
| `elapsed_ms` | `float` | Wall-clock time for child orchestrator execution |
| `error` | `bool` | Whether the child produced an error |
| `error_category` | `str \| None` | Error category from `_classify_error` (e.g., `RATE_LIMIT`, `UNKNOWN`) |
| `prompt_preview` | `str` | First 500 characters of the dispatch prompt |
| `result_preview` | `str \| None` | First 500 characters of the child result (None if no result) |
| `error_message` | `str \| None` | Exception message string (only set on exception path) |

### AST Rewrite Instrumentation Keys (REPLTool)

Written by `REPLTool.run_async()` to `tool_context.state` **before** code execution begins,
so values survive execution errors (CancelledError, Exception).

| Constant | State Key | Type | Writer | Description |
|---|---|---|---|---|
| `OBS_REWRITE_COUNT` | `obs:rewrite_count` | `int` | REPLTool | Cumulative count of AST rewrites (`llm_query()` -> `await llm_query_async()`) |
| `OBS_REWRITE_TOTAL_MS` | `obs:rewrite_total_ms` | `float` | REPLTool | Cumulative wall-clock time spent in AST rewriting (ms, rounded to 3 decimals) |

### Reasoning Retry Observability Keys (Orchestrator)

Written by `RLMOrchestratorAgent.run_async_impl()` as an `Event(state_delta=...)` after
the reasoning retry loop fires (transient LLM errors).

| Constant | State Key | Type | Writer | Description |
|---|---|---|---|---|
| `OBS_REASONING_RETRY_COUNT` | `obs:reasoning_retry_count` | `int` | orchestrator (Event state_delta) | Current retry attempt number (0 = first try, 1+ = retries) |

### Artifact Observability Keys

| Constant | State Key | Type | Writer | Description |
|---|---|---|---|---|
| `OBS_ARTIFACT_SAVES` | `obs:artifact_saves` | `int` | ObservabilityPlugin (on_event) | Artifact save count from event.actions.artifact_delta |
| `OBS_ARTIFACT_BYTES_SAVED` | `obs:artifact_bytes_saved` | `int` | ArtifactService wrappers | Total bytes saved |

### Supporting Non-OBS Keys Used by Observability

| Constant | State Key | Type | Writer | Reader(s) | Description |
|---|---|---|---|---|---|
| `INVOCATION_START_TIME` | `invocation_start_time` | `float` | ObservabilityPlugin (before_agent) | ObservabilityPlugin (after_run) | Unix timestamp of run start |
| `REASONING_CALL_START` | `reasoning_call_start` | `float` | reasoning callbacks | -- | Timestamp of current reasoning call start |
| `REASONING_PROMPT_CHARS` | `reasoning_prompt_chars` | `int` | reasoning_before_model | ObservabilityPlugin | Character count of reasoning prompt |
| `REASONING_SYSTEM_CHARS` | `reasoning_system_chars` | `int` | reasoning_before_model | ObservabilityPlugin | Character count of system instruction |
| `REASONING_CONTENT_COUNT` | `reasoning_content_count` | `int` | reasoning_before_model | -- | Number of content parts |
| `REASONING_HISTORY_MSG_COUNT` | `reasoning_history_msg_count` | `int` | reasoning_before_model | -- | History message count |
| `REASONING_INPUT_TOKENS` | `reasoning_input_tokens` | `int` | reasoning_after_model | -- | Input tokens for current reasoning call |
| `REASONING_OUTPUT_TOKENS` | `reasoning_output_tokens` | `int` | reasoning_after_model | -- | Output tokens for current reasoning call |
| `CONTEXT_WINDOW_SNAPSHOT` | `context_window_snapshot` | `dict` | context_snapshot plugin | ObservabilityPlugin | Context window state at call time |
| `ITERATION_COUNT` | `iteration_count` | `int` | orchestrator | All plugins | Current iteration number |
| `LAST_REPL_RESULT` | `last_repl_result` | `dict` | REPLTool | REPLTracing | Last REPL execution summary |
| `REQUEST_ID` | `request_id` | `str` | orchestrator | ObservabilityPlugin | UUID for request correlation |
| `FINAL_ANSWER` | `final_answer` | `str` | orchestrator | SqliteTracing | Final answer text |

---

## Removed Keys (Phases 1-3)

The following constants were removed from `state.py` during the observability hardening:

### Dead Keys (never written by production code)

| Former Constant | Former State Key | Reason |
|---|---|---|
| `OBS_WORKER_TIMEOUT_COUNT` | `obs:worker_timeout_count` | Never written; `_classify_error` -> `_acc_child_error_counts` dict handles this |
| `OBS_WORKER_RATE_LIMIT_COUNT` | `obs:worker_rate_limit_count` | Never written; same as above |
| `OBS_WORKER_POOL_EXHAUSTION_COUNT` | `obs:worker_pool_exhaustion_count` | WorkerPool deleted; semaphore replaced it |
| `OBS_CHILD_SUMMARY_PREFIX` | `obs:child_summary@` | Never imported; `child_obs_key()` function used directly |
| `OBS_ARTIFACT_LOADS` | `obs:artifact_loads` | Forward-declared, never written |
| `OBS_ARTIFACT_DELETES` | `obs:artifact_deletes` | Forward-declared, never written |
| `OBS_ARTIFACT_SAVE_LATENCY_MS` | `obs:artifact_save_latency_ms` | Forward-declared, never written |

### Legacy Worker Token Accounting Keys (removed with leaf workers)

| Former Constant | Former State Key | Reason |
|---|---|---|
| `WORKER_PROMPT_CHARS` | `worker_prompt_chars` | Never written in child-orchestrator architecture |
| `WORKER_CONTENT_COUNT` | `worker_content_count` | Never written in child-orchestrator architecture |
| `WORKER_INPUT_TOKENS` | `worker_input_tokens` | Never written in child-orchestrator architecture |
| `WORKER_OUTPUT_TOKENS` | `worker_output_tokens` | Never written in child-orchestrator architecture |

### Duplicate Dispatch Keys (replaced by canonical OBS_CHILD_* keys)

| Former Constant | Former State Key | Canonical Replacement |
|---|---|---|
| `WORKER_DISPATCH_COUNT` | `worker_dispatch_count` | `OBS_CHILD_DISPATCH_COUNT` |
| `OBS_WORKER_TOTAL_DISPATCHES` | `obs:worker_total_dispatches` | `OBS_CHILD_DISPATCH_COUNT` |
| `OBS_WORKER_DISPATCH_LATENCY_MS` | `obs:worker_dispatch_latency_ms` | `OBS_CHILD_DISPATCH_LATENCY_MS` |
| `OBS_WORKER_TOTAL_BATCH_DISPATCHES` | `obs:worker_total_batch_dispatches` | `OBS_CHILD_TOTAL_BATCH_DISPATCHES` |
| `OBS_WORKER_ERROR_COUNTS` | `obs:worker_error_counts` | `OBS_CHILD_ERROR_COUNTS` |

### Removed Plugin

| Plugin | Lines | Reason |
|---|---|---|
| `DebugLoggingPlugin` | 522 | Redundant with ObservabilityPlugin; verbose mode absorbed its summary output |

---

## Plugin Matrix

| Key | ObservabilityPlugin | SqliteTracingPlugin | REPLTracingPlugin |
|---|---|---|---|
| `obs:total_calls` | **W/R** | R (after_run) | -- |
| `obs:total_input_tokens` | **W/R** | R (after_run) | -- |
| `obs:total_output_tokens` | **W/R** | R (after_run) | -- |
| `obs:total_execution_time` | **W** (after_run) | R (after_run) | -- |
| `obs:per_iteration_token_breakdown` | **W** | R (after_run, JSON) | -- |
| `obs:tool_invocation_summary` | **W** (before_tool) | R (after_run, JSON) | -- |
| `obs:model_usage:{model}` | **W** | R (after_run, JSON) | -- |
| `obs:finish_{reason}_count` | **W** | R (after_run) | -- |
| `obs:child_dispatch_count` | R (after_run) | R (after_run) | -- |
| `obs:child_error_counts` | R (after_run) | R (after_run, JSON) | -- |
| `obs:child_dispatch_latency_ms` | R (after_run) | -- | -- |
| `obs:child_total_batch_dispatches` | R (after_run) | -- | -- |
| `obs:structured_output_failures` | -- | R (after_run) | -- |
| `obs:artifact_saves` | **W** (on_event) | -- | -- |
| `obs:artifact_bytes_saved` | R (after_run) | -- | -- |
| `obs:rewrite_count` | -- | -- | -- |
| `obs:rewrite_total_ms` | -- | -- | -- |
| `obs:reasoning_retry_count` | -- | -- | -- |
| `obs:bug13_suppress_count` | -- | -- | -- |
| `last_repl_result` | R (after_run) | -- | R |
| `iteration_count` | R | R (before_model) | R |
| `request_id` | R | R (after_run) | -- |
| `final_answer` | R (after_run) | R (after_run) | -- |

**W** = writes, **R** = reads, **W/R** = writes and reads back

**Non-plugin writers:** `obs:rewrite_count` and `obs:rewrite_total_ms` are written by `REPLTool.run_async()` to `tool_context.state` (not by any plugin). `obs:reasoning_retry_count` is written by the orchestrator via `EventActions(state_delta=...)`. `obs:bug13_suppress_count` is written by `flush_fn()` in dispatch closures (reads `_bug13_stats["suppress_count"]`).

### Plugin Status

| Plugin | Status | Role |
|---|---|---|
| `ObservabilityPlugin` | **Active** (default-on) | Token/call/finish tracking, ephemeral re-persist, verbose mode summary |
| `SqliteTracingPlugin` | **Active** (opt-in) | 4-table SQLite persistence (traces, telemetry, session_state_events, spans [legacy]). Companion CLI: `python -m rlm_adk.eval.session_report` |
| `REPLTracingPlugin` | **Active** (opt-in, `RLM_REPL_TRACE` env) | REPL execution profiling, trace artifacts |
| `LangfuseTracingPlugin` | **Active** (opt-in) | OTel auto-instrumentation via `openinference-instrumentation-google-adk` |
| `DebugLoggingPlugin` | **REMOVED** (Phase 3) | Absorbed by ObservabilityPlugin verbose mode |

---

## Ephemeral Key Re-Persist Mechanism

ADK's `base_llm_flow.py` creates `CallbackContext` *without* `event_actions` for plugin
`after_model_callback`, so state writes there hit the live session dict but never land
in a `state_delta` Event.  ObservabilityPlugin's `after_agent_callback` re-writes these
values through the properly-wired `CallbackContext` so they appear in `final_state`.

**Fixed keys re-persisted:**
- `OBS_TOTAL_CALLS`, `OBS_TOTAL_INPUT_TOKENS`, `OBS_TOTAL_OUTPUT_TOKENS`
- `OBS_PER_ITERATION_TOKEN_BREAKDOWN`
- `OBS_FINISH_SAFETY_COUNT`, `OBS_FINISH_RECITATION_COUNT`, `OBS_FINISH_MAX_TOKENS_COUNT`
- `CONTEXT_WINDOW_SNAPSHOT`

**Dynamic prefixes re-persisted:**
- `obs:finish_*` (any finish reason counter)
- `obs:model_usage:*` (per-model usage dicts)
- `obs:child_summary@*` (fanout summaries)

---

## Data Flow: Dispatch Accumulator -> Session State

```
1. Child orchestrator completes (or errors)
   +-- LLMResult(text, error=True/False, error_category="RATE_LIMIT")

2. llm_query_batched_async processes results
   +-- _acc_child_dispatches += k
   +-- _acc_child_latencies.append(elapsed_ms)
   +-- _acc_child_error_counts[category] += 1  (if error)

3. REPLTool.run_async() calls flush_fn()
   +-- flush_fn() snapshots accumulators -> returns dict
   +-- flush_fn() resets accumulators to zero

4. REPLTool writes flush_fn() output to tool_context.state
   +-- Keys appear in EventActions.state_delta
   +-- ADK Runner merges state_delta into session.state

5. ObservabilityPlugin.after_run_callback reads final session.state
   +-- Logs child_dispatches, child_errors, latencies in summary
```

---

## SQLite 4-Table Schema

### `traces` table (one row per invocation)

| Column | Type | Source |
|---|---|---|
| `trace_id` | TEXT PK | UUID generated at run start |
| `session_id` | TEXT | invocation_context.session.id |
| `user_id` | TEXT | invocation_context.session.user_id |
| `app_name` | TEXT | invocation_context.app_name |
| `start_time` | REAL | time.time() at before_run |
| `end_time` | REAL | time.time() at after_run |
| `status` | TEXT | 'running' -> 'completed' |
| `total_input_tokens` | INTEGER | `OBS_TOTAL_INPUT_TOKENS` |
| `total_output_tokens` | INTEGER | `OBS_TOTAL_OUTPUT_TOKENS` |
| `total_calls` | INTEGER | `OBS_TOTAL_CALLS` |
| `iterations` | INTEGER | `ITERATION_COUNT` |
| `final_answer_length` | INTEGER | `len(FINAL_ANSWER)` |
| `request_id` | TEXT | `REQUEST_ID` |
| `repo_url` | TEXT | `REPO_URL` |
| `root_prompt_preview` | TEXT | `ROOT_PROMPT[:500]` |
| `total_execution_time_s` | REAL | `OBS_TOTAL_EXECUTION_TIME` |
| `child_dispatch_count` | INTEGER | `OBS_CHILD_DISPATCH_COUNT` |
| `child_error_counts` | TEXT (JSON) | `OBS_CHILD_ERROR_COUNTS` |
| `structured_output_failures` | INTEGER | `OBS_STRUCTURED_OUTPUT_FAILURES` |
| `finish_safety_count` | INTEGER | `OBS_FINISH_SAFETY_COUNT` |
| `finish_recitation_count` | INTEGER | `OBS_FINISH_RECITATION_COUNT` |
| `finish_max_tokens_count` | INTEGER | `OBS_FINISH_MAX_TOKENS_COUNT` |
| `tool_invocation_summary` | TEXT (JSON) | `OBS_TOOL_INVOCATION_SUMMARY` |
| `artifact_saves` | INTEGER | `OBS_ARTIFACT_SAVES` |
| `artifact_bytes_saved` | INTEGER | `OBS_ARTIFACT_BYTES_SAVED` |
| `per_iteration_breakdown` | TEXT (JSON) | `OBS_PER_ITERATION_TOKEN_BREAKDOWN` |
| `model_usage_summary` | TEXT (JSON) | Aggregated `obs:model_usage:*` keys |
| `config_json` | TEXT (JSON) | Run config snapshot (max_depth, max_iterations, env vars) captured at `before_run` |
| `prompt_hash` | TEXT | SHA-256 hex digest of `root_prompt`, computed at `after_run` |
| `max_depth_reached` | INTEGER | Deepest orchestrator depth observed in telemetry agent names (parsed from `_dN` suffix) |

### `telemetry` table (one row per model call or tool invocation)

| Column | Type | Description |
|---|---|---|
| `telemetry_id` | TEXT PK | UUID |
| `trace_id` | TEXT | FK to traces |
| `event_type` | TEXT | 'model_call' or 'tool_call' |
| `agent_name` | TEXT | Name of the active agent |
| `iteration` | INTEGER | Current iteration number |
| `depth` | INTEGER | Orchestrator depth (default 0) |
| `call_number` | INTEGER | Monotonic call counter (sourced from `OBS_TOTAL_CALLS` at `before_model`) |
| `start_time` / `end_time` | REAL | Unix timestamps |
| `duration_ms` | REAL | Wall-clock duration |
| `model` | TEXT | Model name (model_call only) |
| `input_tokens` / `output_tokens` | INTEGER | Token counts |
| `finish_reason` | TEXT | LLM finish reason |
| `num_contents` | INTEGER | Number of content parts in request |
| `agent_type` | TEXT | 'reasoning' or NULL (sourced from `CONTEXT_WINDOW_SNAPSHOT`) |
| `prompt_chars` / `system_chars` | INTEGER | Prompt/system instruction character counts (sourced from `CONTEXT_WINDOW_SNAPSHOT`) |
| `tool_name` | TEXT | Tool name (tool_call only) |
| `tool_args_keys` | TEXT (JSON) | List of argument keys |
| `result_preview` | TEXT | str(result)[:500] |
| `repl_has_errors` | INTEGER | REPL enrichment (execute_code only) |
| `repl_has_output` | INTEGER | REPL enrichment |
| `repl_llm_calls` | INTEGER | REPL enrichment |
| `status` | TEXT | 'ok' or 'error' |
| `error_type` / `error_message` | TEXT | Error details |

### `session_state_events` table (one row per curated state key change)

| Column | Type | Description |
|---|---|---|
| `event_id` | TEXT PK | UUID |
| `trace_id` | TEXT | FK to traces |
| `seq` | INTEGER | Monotonic counter per trace |
| `event_author` | TEXT | Event author (agent name) |
| `event_time` | REAL | Unix timestamp |
| `state_key` | TEXT | Base key (depth suffix parsed out) |
| `key_category` | TEXT | obs_reasoning, obs_dispatch, obs_artifact, obs_finish, flow_control, repl, cache, request_meta, other |
| `key_depth` | INTEGER | Parsed @dN suffix (default 0) |
| `key_fanout` | INTEGER | Parsed @dNfM suffix |
| `value_type` | TEXT | int, float, str, list, dict, bool, null |
| `value_int` | INTEGER | For int/bool values |
| `value_float` | REAL | For float values |
| `value_text` | TEXT | For string values (truncated to 2000 chars) |
| `value_json` | TEXT | For list/dict values (JSON) |

### `spans` table (legacy -- retained, no new writes)

The `spans` table is retained for backward compatibility but no longer receives writes.
New telemetry data flows exclusively through the `telemetry` and `session_state_events` tables.

### Schema Migration (`_migrate_schema()`)

`SqliteTracingPlugin._migrate_schema()` runs at init after `CREATE TABLE IF NOT EXISTS`.
It inspects each table via `PRAGMA table_info` and issues `ALTER TABLE ADD COLUMN` for any
columns missing from existing databases. This provides forward-compatible schema evolution
without requiring users to delete their `traces.db` file when new columns are added.

---

## Test Coverage

### FMEA Observability Tests (`tests_rlm_adk/test_fmea_e2e.py`)

| Test Name | Keys Validated | Fixture |
|---|---|---|
| `test_obs_total_calls_persisted` | `OBS_TOTAL_CALLS`, `OBS_CHILD_DISPATCH_COUNT` | `worker_500_then_success` |
| `test_obs_error_counts_absent` | `OBS_CHILD_ERROR_COUNTS` | `structured_output_batched_k3_with_retry` |
| `test_obs_finish_max_tokens_tracked` | `OBS_CHILD_DISPATCH_LATENCY_MS`, `OBS_CHILD_ERROR_COUNTS` | `worker_max_tokens_truncated` |
| `test_obs_error_counts` | `OBS_CHILD_ERROR_COUNTS` | `structured_output_retry_exhaustion` |
| `test_obs_error_counts_exhaustion` | `OBS_CHILD_ERROR_COUNTS` | `structured_output_batched_k3_mixed_exhaust` |
| `test_obs_structured_output_failures` | `OBS_STRUCTURED_OUTPUT_FAILURES` | `structured_output_batched_k3_mixed_exhaust` |

### Obs E2E Hardening Tests (`tests_rlm_adk/test_obs_e2e_hardening.py`)

| Test Class | Keys Validated | Fixture |
|---|---|---|
| `TestObsPerIterationTokenBreakdown` | `OBS_PER_ITERATION_TOKEN_BREAKDOWN` (list, fields, agent_type) | `worker_500_then_success` |
| `TestObsFinishSafetyCount` | `OBS_FINISH_SAFETY_COUNT >= 1` | `reasoning_safety_finish` |
| `TestObsFinishMaxTokensCount` | `OBS_FINISH_MAX_TOKENS_COUNT` (type) | `worker_max_tokens_truncated` |
| `TestObsModelUsage` | `obs:model_usage:*` (existence, fields) | `worker_500_then_success` |
| `TestObsTotalExecutionTime` | `OBS_TOTAL_EXECUTION_TIME` (ADK limitation documented, SQLite verified) | `repl_error_then_retry` |
| `TestObsChildDispatchCount` | `OBS_CHILD_DISPATCH_COUNT`, legacy key absence, latency, batch dispatches | `structured_output_batched_k3` |
| `TestObsToolInvocationSummary` | `OBS_TOOL_INVOCATION_SUMMARY` (dict, execute_code entry) | `repl_error_then_retry` |
| `TestObsTokenAggregates` | `OBS_TOTAL_CALLS`, `OBS_TOTAL_INPUT_TOKENS`, `OBS_TOTAL_OUTPUT_TOKENS` | `repl_error_then_retry` |

### Provider-Fake E2E Tests (`tests_rlm_adk/test_provider_fake_e2e.py`)

Validates the full pipeline (fake Gemini server -> orchestrator -> session state)
for each fixture scenario, confirming obs keys land in final session state.

### Dispatch flush_fn Tests (`tests_rlm_adk/test_dispatch_flush_fn.py`)

Validates that `flush_fn()` returns correct accumulator snapshots and resets state.

### Rewrite Instrumentation Tests (`tests_rlm_adk/test_rewrite_instrumentation.py`)

8 tests validating `OBS_REWRITE_COUNT`, `OBS_REWRITE_TOTAL_MS`, `OBS_REASONING_RETRY_COUNT`,
and `OBS_BUG13_SUPPRESS_COUNT` state key definitions, REPLTool write behavior, and
flush_fn inclusion of bug13 stats.

### Session Report Tests (`tests_rlm_adk/test_session_report.py`)

11 tests validating `session_report.build_session_report()` output sections (overview,
layer_tree, performance, errors, repl_outcomes, state_timeline) against synthetic
SQLite databases with known telemetry data.

### Child Obs Summary Tests (`tests_rlm_adk/test_child_obs_summary.py`)

13 tests validating `obs:child_summary@d{depth}f{idx}` key generation, dict field contents
(model, elapsed_ms, error, error_category, prompt_preview, result_preview, error_message),
and ObservabilityPlugin re-persist of `obs:child_summary@*` keys.

---

## Source Files

| File | Role |
|---|---|
| `rlm_adk/state.py` | All key constant definitions |
| `rlm_adk/dispatch.py` | Accumulator closures, flush_fn, child orchestrator spawning |
| `rlm_adk/tools/repl_tool.py` | Calls flush_fn(), writes results to tool_context.state |
| `rlm_adk/plugins/observability.py` | Reasoning-level token/call/finish tracking, ephemeral re-persist, verbose summary |
| `rlm_adk/plugins/sqlite_tracing.py` | 4-table schema: traces, telemetry, session_state_events, spans (legacy) |
| `rlm_adk/plugins/repl_tracing.py` | Reads LAST_REPL_RESULT for REPL trace artifacts |
| `rlm_adk/plugins/langfuse_tracing.py` | OTel auto-instrumentation (no callback overlap) |
| `rlm_adk/callbacks/reasoning.py` | Writes REASONING_* prompt/token accounting keys |
| `rlm_adk/callbacks/worker.py` | _classify_error for child orchestrator error categories |
| `rlm_adk/callbacks/worker_retry.py` | Structured output retry + BUG-13 patch |
| `rlm_adk/eval/session_report.py` | CLI tool: 6-section JSON report from trace_id (overview, layer_tree, performance, errors, repl_outcomes, state_timeline). Uses raw sqlite3, no duckdb dependency |
