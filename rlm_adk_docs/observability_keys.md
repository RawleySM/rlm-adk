# Observability Keys Reference

All session-scoped state keys used for observability across the RLM ADK runtime.
Keys use the `obs:` naming convention prefix (session-scoped, not a true ADK scope).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  Root Orchestrator (depth=0)                                        │
│                                                                     │
│  reasoning_agent ──► REPLTool.run_async()                          │
│       │                    │                                        │
│       │              calls flush_fn()                               │
│       │                    │                                        │
│       │              ┌─────▼──────┐                                │
│       │              │ Dispatch   │  _acc_child_dispatches          │
│       │              │ Closures   │  _acc_child_latencies           │
│       │              │            │  _acc_child_error_counts        │
│       │              │            │  _acc_child_batch_dispatches    │
│       │              │            │  _acc_structured_output_failures│
│       │              └─────┬──────┘                                │
│       │                    │ spawns                                  │
│       │              ┌─────▼──────────────────┐                    │
│       │              │ Child Orchestrator(d=1) │                    │
│       │              │  reasoning + REPLTool   │                    │
│       │              │  + own dispatch closures│                    │
│       │              └────────────────────────┘                    │
│       │                                                             │
│  ObservabilityPlugin ◄── after_model (reasoning-level tokens)      │
│  DebugLoggingPlugin  ◄── reads all keys for stdout/YAML trace      │
│  SqliteTracingPlugin ◄── reads summary keys for traces.db          │
│  REPLTracingPlugin   ◄── reads LAST_REPL_RESULT + ITERATION_COUNT │
└─────────────────────────────────────────────────────────────────────┘
```

**Key insight:** ObservabilityPlugin does NOT fire for child orchestrators — each child
gets an isolated `InvocationContext`.  Child obs data flows through:

```
child orchestrator → _classify_error → LLMResult.error* fields
  → parent dispatch accumulator vars → flush_fn() → tool_context.state
    → ObservabilityPlugin reads at run end
```

---

## Key Reference

### Reasoning-Level Keys (ObservabilityPlugin)

Written by `ObservabilityPlugin.after_model_callback` and persisted via `after_agent_callback`.

| Constant | State Key | Type | Writer | Reader(s) | Description |
|---|---|---|---|---|---|
| `OBS_TOTAL_CALLS` | `obs:total_calls` | `int` | ObservabilityPlugin | DebugLogging, SqliteTracing | Cumulative LLM call count (reasoning-level only) |
| `OBS_TOTAL_INPUT_TOKENS` | `obs:total_input_tokens` | `int` | ObservabilityPlugin | DebugLogging, SqliteTracing | Cumulative input tokens (reasoning) |
| `OBS_TOTAL_OUTPUT_TOKENS` | `obs:total_output_tokens` | `int` | ObservabilityPlugin | DebugLogging, SqliteTracing | Cumulative output tokens (reasoning) |
| `OBS_TOTAL_EXECUTION_TIME` | `obs:total_execution_time` | `float` | ObservabilityPlugin (after_run) | DebugLogging | Wall-clock run time in seconds |
| `OBS_PER_ITERATION_TOKEN_BREAKDOWN` | `obs:per_iteration_token_breakdown` | `list[dict]` | ObservabilityPlugin | — | Per-call breakdown with iteration, tokens, finish_reason, agent_type |
| `OBS_TOOL_INVOCATION_SUMMARY` | `obs:tool_invocation_summary` | `dict[str,int]` | ObservabilityPlugin (before_tool) | — | Tool name → invocation count map |
| `obs_model_usage_key(model)` | `obs:model_usage:{model}` | `dict` | ObservabilityPlugin | — | Per-model `{calls, input_tokens, output_tokens}` |

### Finish Reason Tracking (ObservabilityPlugin)

Written by `ObservabilityPlugin.after_model_callback` when `finish_reason != "STOP"`.

| Constant | State Key | Type | Description |
|---|---|---|---|
| `OBS_FINISH_SAFETY_COUNT` | `obs:finish_safety_count` | `int` | Count of SAFETY finish reasons |
| `OBS_FINISH_RECITATION_COUNT` | `obs:finish_recitation_count` | `int` | Count of RECITATION finish reasons |
| `OBS_FINISH_MAX_TOKENS_COUNT` | `obs:finish_max_tokens_count` | `int` | Count of MAX_TOKENS finish reasons |
| *(dynamic)* | `obs:finish_{reason}_count` | `int` | Any other finish reason, lowercased |

### Worker/Child Dispatch Keys (flush_fn)

Written by `dispatch.create_dispatch_closures` → `flush_fn()` → consumed by `REPLTool.run_async()` into `tool_context.state`.

| Constant | State Key | Type | Accumulator | Description |
|---|---|---|---|---|
| `WORKER_DISPATCH_COUNT` | `worker_dispatch_count` | `int` | `_acc_child_dispatches` | Total child dispatches (backward compat, used by REPLTool for `LAST_REPL_RESULT.total_llm_calls`) |
| `OBS_WORKER_TOTAL_DISPATCHES` | `obs:worker_total_dispatches` | `int` | `_acc_child_dispatches` | Same value as above, obs-prefixed alias |
| `OBS_CHILD_DISPATCH_COUNT` | `obs:child_dispatch_count` | `int` | `_acc_child_dispatches` | Same value, child-specific key read by ObservabilityPlugin.after_run |
| `OBS_WORKER_DISPATCH_LATENCY_MS` | `obs:worker_dispatch_latency_ms` | `list[float]` | `_acc_child_latencies` | Per-dispatch latency in ms (backward compat key) |
| `OBS_CHILD_DISPATCH_LATENCY_MS` | `obs:child_dispatch_latency_ms` | `list[float]` | `_acc_child_latencies` | Same value, child-specific alias |
| `OBS_WORKER_TOTAL_BATCH_DISPATCHES` | `obs:worker_total_batch_dispatches` | `int` | `_acc_child_batch_dispatches` | Count of batch dispatches (k>1) — backward compat |
| `OBS_CHILD_TOTAL_BATCH_DISPATCHES` | `obs:child_total_batch_dispatches` | `int` | `_acc_child_batch_dispatches` | Same value, child-specific alias |
| `OBS_WORKER_ERROR_COUNTS` | `obs:worker_error_counts` | `dict[str,int]` | `_acc_child_error_counts` | Error category → count (backward compat) |
| `OBS_CHILD_ERROR_COUNTS` | `obs:child_error_counts` | `dict[str,int]` | `_acc_child_error_counts` | Same value, child-specific alias |
| `OBS_STRUCTURED_OUTPUT_FAILURES` | `obs:structured_output_failures` | `int` | `_acc_structured_output_failures` | Count of structured output validation exhaustions |

**Dual-key pattern:** Each accumulator writes both an `OBS_WORKER_*` key (backward compat with
pre-recursive-agent code) and an `OBS_CHILD_*` key (semantically accurate for the new architecture).

### Child Summary Keys (Fanout Tracking)

| Constant | State Key | Type | Writer | Description |
|---|---|---|---|---|
| `OBS_CHILD_SUMMARY_PREFIX` | `obs:child_summary@` | *(prefix)* | — | Prefix for fanout-indexed summaries |
| `child_obs_key(depth, idx)` | `obs:child_summary@d{depth}f{idx}` | `dict` | dispatch closures | Per-child summary keyed by depth and fanout index |

### Worker Pool Keys (Legacy)

| Constant | State Key | Type | Writer | Description |
|---|---|---|---|---|
| `OBS_WORKER_POOL_EXHAUSTION_COUNT` | `obs:worker_pool_exhaustion_count` | `int` | WorkerPool.acquire | Count of pool exhaustion events (legacy WorkerPool path) |
| `OBS_WORKER_TIMEOUT_COUNT` | `obs:worker_timeout_count` | `int` | dispatch closures | Timeout-specific error count (legacy) |
| `OBS_WORKER_RATE_LIMIT_COUNT` | `obs:worker_rate_limit_count` | `int` | dispatch closures | Rate-limit-specific error count (legacy) |

### Artifact Observability Keys

| Constant | State Key | Type | Writer | Reader(s) | Description |
|---|---|---|---|---|---|
| `OBS_ARTIFACT_SAVES` | `obs:artifact_saves` | `int` | ObservabilityPlugin (on_event) | DebugLogging | Artifact save count from event.actions.artifact_delta |
| `OBS_ARTIFACT_LOADS` | `obs:artifact_loads` | `int` | ArtifactService wrappers | — | Artifact load count |
| `OBS_ARTIFACT_DELETES` | `obs:artifact_deletes` | `int` | ArtifactService wrappers | — | Artifact delete count |
| `OBS_ARTIFACT_BYTES_SAVED` | `obs:artifact_bytes_saved` | `int` | ArtifactService wrappers | DebugLogging, ObservabilityPlugin | Total bytes saved |
| `OBS_ARTIFACT_SAVE_LATENCY_MS` | `obs:artifact_save_latency_ms` | `list[float]` | ArtifactService wrappers | — | Per-save latency |

### Supporting Non-OBS Keys Used by Observability

These keys lack the `obs:` prefix but are read by observability plugins.

| Constant | State Key | Type | Writer | Reader(s) | Description |
|---|---|---|---|---|---|
| `INVOCATION_START_TIME` | `invocation_start_time` | `float` | ObservabilityPlugin (before_agent) | ObservabilityPlugin (after_run) | Unix timestamp of run start |
| `REASONING_CALL_START` | `reasoning_call_start` | `float` | reasoning callbacks | — | Timestamp of current reasoning call start |
| `REASONING_PROMPT_CHARS` | `reasoning_prompt_chars` | `int` | reasoning_before_model | ObservabilityPlugin, DebugLogging | Character count of reasoning prompt |
| `REASONING_SYSTEM_CHARS` | `reasoning_system_chars` | `int` | reasoning_before_model | ObservabilityPlugin, DebugLogging | Character count of system instruction |
| `REASONING_CONTENT_COUNT` | `reasoning_content_count` | `int` | reasoning_before_model | DebugLogging | Number of content parts |
| `REASONING_HISTORY_MSG_COUNT` | `reasoning_history_msg_count` | `int` | reasoning_before_model | DebugLogging | History message count |
| `REASONING_INPUT_TOKENS` | `reasoning_input_tokens` | `int` | reasoning_after_model | DebugLogging | Input tokens for current reasoning call |
| `REASONING_OUTPUT_TOKENS` | `reasoning_output_tokens` | `int` | reasoning_after_model | DebugLogging | Output tokens for current reasoning call |
| `WORKER_PROMPT_CHARS` | `worker_prompt_chars` | `int` | worker_before_model | ObservabilityPlugin, DebugLogging | Character count of worker prompt |
| `WORKER_CONTENT_COUNT` | `worker_content_count` | `int` | worker_before_model | DebugLogging | Worker content part count |
| `WORKER_INPUT_TOKENS` | `worker_input_tokens` | `int` | worker_after_model | DebugLogging | Worker input tokens |
| `WORKER_OUTPUT_TOKENS` | `worker_output_tokens` | `int` | worker_after_model | DebugLogging | Worker output tokens |
| `CONTEXT_WINDOW_SNAPSHOT` | `context_window_snapshot` | `dict` | context_snapshot plugin | ObservabilityPlugin, DebugLogging | Context window state at call time |
| `ITERATION_COUNT` | `iteration_count` | `int` | orchestrator | All plugins | Current iteration number |
| `LAST_REPL_RESULT` | `last_repl_result` | `dict` | REPLTool | DebugLogging, REPLTracing | Last REPL execution summary |
| `REQUEST_ID` | `request_id` | `str` | orchestrator | ObservabilityPlugin, DebugLogging | UUID for request correlation |
| `FINAL_ANSWER` | `final_answer` | `str` | orchestrator | DebugLogging, SqliteTracing | Final answer text |

---

## Plugin Key Usage Matrix

| Key | ObservabilityPlugin | DebugLoggingPlugin | SqliteTracingPlugin | REPLTracingPlugin |
|---|---|---|---|---|
| `obs:total_calls` | **W/R** | R | R | — |
| `obs:total_input_tokens` | **W/R** | R | R | — |
| `obs:total_output_tokens` | **W/R** | R | R | — |
| `obs:total_execution_time` | **W** | R | — | — |
| `obs:per_iteration_token_breakdown` | **W** | — | — | — |
| `obs:tool_invocation_summary` | **W** | — | — | — |
| `obs:model_usage:{model}` | **W** | — | — | — |
| `obs:finish_{reason}_count` | **W** | — | — | — |
| `obs:worker_total_dispatches` | — | R | — | — |
| `obs:worker_dispatch_latency_ms` | — | R | — | — |
| `obs:child_dispatch_count` | R (after_run) | — | — | — |
| `obs:child_error_counts` | R (after_run) | — | — | — |
| `obs:artifact_saves` | **W** (on_event) | R | — | — |
| `obs:artifact_bytes_saved` | R (after_run) | R | — | — |
| `last_repl_result` | — | R | — | R |
| `iteration_count` | R | R | R | R |
| `request_id` | R | R | — | — |

**W** = writes, **R** = reads, **W/R** = writes and reads back

---

## Data Flow: Dispatch Accumulator → Session State

```
1. Child orchestrator completes (or errors)
   └─► LLMResult(text, error=True/False, error_category="RATE_LIMIT")

2. llm_query_batched_async processes results
   └─► _acc_child_dispatches += k
   └─► _acc_child_latencies.append(elapsed_ms)
   └─► _acc_child_error_counts[category] += 1  (if error)

3. REPLTool.run_async() calls flush_fn()
   └─► flush_fn() snapshots accumulators → returns dict
   └─► flush_fn() resets accumulators to zero

4. REPLTool writes flush_fn() output to tool_context.state
   └─► Keys appear in EventActions.state_delta
   └─► ADK Runner merges state_delta into session.state

5. ObservabilityPlugin.after_run_callback reads final session.state
   └─► Logs child_dispatches, child_errors in summary
```

---

## Test Fixture Validation

### FMEA Observability Tests (`tests_rlm_adk/test_fmea_e2e.py`)

| Test Name | Keys Validated | Fixture |
|---|---|---|
| `test_obs_worker_dispatches` | `OBS_WORKER_TOTAL_DISPATCHES` | `multi_iteration_with_workers` |
| `test_obs_batch_dispatches` | `OBS_WORKER_TOTAL_BATCH_DISPATCHES` | `structured_output_batched_k3` |
| `test_obs_dispatch_latency` | `OBS_WORKER_DISPATCH_LATENCY_MS` | `multi_iteration_with_workers` |
| `test_obs_worker_error_counts_429` | `OBS_WORKER_ERROR_COUNTS["RATE_LIMIT"]` | `worker_429_mid_batch` |
| `test_obs_worker_error_counts_500` | `OBS_WORKER_ERROR_COUNTS["SERVER"]` | `worker_500_then_success` |
| `test_obs_worker_error_counts_safety` | `OBS_WORKER_ERROR_COUNTS` + safety | `worker_safety_finish` |
| `test_obs_worker_error_counts_malformed` | `OBS_WORKER_ERROR_COUNTS` | `worker_malformed_json` |
| `test_obs_structured_output_failures` | `OBS_STRUCTURED_OUTPUT_FAILURES` | `structured_output_retry_exhaustion` |
| `test_obs_finish_reason_safety` | `OBS_FINISH_SAFETY_COUNT` | `reasoning_safety_finish` |
| `test_obs_finish_reason_max_tokens` | `OBS_FINISH_MAX_TOKENS_COUNT` | `worker_max_tokens_truncated` |
| `test_obs_reasoning_tokens` | `OBS_TOTAL_INPUT_TOKENS`, `OBS_TOTAL_OUTPUT_TOKENS` | `happy_path_single_iteration` |

### Provider-Fake E2E Tests (`tests_rlm_adk/test_provider_fake_e2e.py`)

These validate the full pipeline (fake Gemini server → orchestrator → session state)
for each fixture scenario, confirming obs keys land in final session state.

### Dispatch flush_fn Tests (`tests_rlm_adk/test_dispatch_flush_fn.py`)

Validates that `flush_fn()` returns correct accumulator snapshots and resets state.

---

## Source Files

| File | Role |
|---|---|
| `rlm_adk/state.py` | All key constant definitions |
| `rlm_adk/dispatch.py` | Accumulator closures, flush_fn, child orchestrator spawning |
| `rlm_adk/tools/repl_tool.py` | Calls flush_fn(), writes results to tool_context.state |
| `rlm_adk/plugins/observability.py` | Reasoning-level token/call/finish tracking |
| `rlm_adk/plugins/debug_logging.py` | Reads most keys for stdout + YAML trace output |
| `rlm_adk/plugins/sqlite_tracing.py` | Reads summary keys for traces.db persistence |
| `rlm_adk/plugins/repl_tracing.py` | Reads LAST_REPL_RESULT for REPL trace artifacts |
| `rlm_adk/callbacks/reasoning.py` | Writes REASONING_* prompt/token accounting keys |
| `rlm_adk/callbacks/worker.py` | Writes WORKER_* accounting keys, _classify_error |
| `rlm_adk/callbacks/worker_retry.py` | Structured output retry + BUG-13 patch |
