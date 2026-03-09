# RLM-ADK Observability Stack & Plugin System

## RLM-ADK Observability Stack & Plugin System - Comprehensive Documentation

Based on my thorough exploration of the codebase, here is a complete analysis of the observability infrastructure:

---

## 1. PLUGIN ARCHITECTURE OVERVIEW

### Plugin Base Classes & Registration
- All plugins extend `google.adk.plugins.base_plugin.BasePlugin`
- Plugins wired during orchestrator creation in `rlm_adk/agent.py`
- Plugins in `rlm_adk/plugins/__init__.py`: ObservabilityPlugin, SqliteTracingPlugin, LangfuseTracingPlugin, REPLTracingPlugin, CachePlugin, PolicyPlugin, MigrationPlugin

### Callback Lifecycle
Each plugin implements zero or more of:
- `before_run_callback` / `after_run_callback` — session lifecycle
- `before_agent_callback` / `after_agent_callback` — agent entry/exit
- `before_model_callback` / `after_model_callback` — LLM calls
- `on_model_error_callback` — LLM failures
- `before_tool_callback` / `after_tool_callback` — tool execution
- `on_event_callback` — state delta events

---

## 2. OBSERVABILITY PLUGIN

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/observability.py`

### What It Observes
- Token usage (input/output) per model call
- Finish reasons (SAFETY, RECITATION, MAX_TOKENS, STOP)
- Invocation timing and execution duration
- Tool invocation counts
- Per-iteration token breakdown
- Artifact operations

### Hook Points & Flow
1. **before_agent_callback**: Records INVOCATION_START_TIME if not set
2. **after_model_callback**:
   - Increments OBS_TOTAL_CALLS
   - Extracts tokens from usage_metadata (prompt_token_count, candidates_token_count)
   - Accumulates into OBS_TOTAL_INPUT_TOKENS, OBS_TOTAL_OUTPUT_TOKENS
   - Tracks finish_reason as obs:finish_{reason}_count
   - Builds per-iteration token breakdown entry with iteration, input_tokens, output_tokens, finish_reason, agent_type, prompt_chars, system_chars
3. **before_tool_callback**: Increments OBS_TOOL_INVOCATION_SUMMARY by tool name
4. **on_event_callback**: Tracks artifact saves from artifact_delta
5. **after_agent_callback**: Re-persists ephemeral keys (reason: ADK's base_llm_flow.py doesn't wire event_actions for plugin after_model_callback)
6. **after_run_callback**: Final summary with reasoning/worker call counts, dispatch metrics, latencies

### Ephemeral Keys Workaround
- Writes to callback_context.state in after_model_callback don't land in state_delta Events
- after_agent_callback re-reads from session.state and re-writes via properly-wired CallbackContext
- Keys: OBS_TOTAL_CALLS, OBS_TOTAL_INPUT_TOKENS/OUTPUT_TOKENS, OBS_PER_ITERATION_TOKEN_BREAKDOWN, OBS_FINISH_* counters, CONTEXT_WINDOW_SNAPSHOT

### Known Limitation
- **Does NOT fire for workers** — ParallelAgent gives workers isolated invocation contexts
- Worker observability flows through: worker_after_model → dispatch closures → accumulators → flush_fn → tool_context.state

---

## 3. SQLITE TRACING PLUGIN

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py`

### Database Schema
```
traces       — One row per invocation (enriched at run end)
telemetry    — One row per model call or tool invocation
spans        — Legacy table (retained for backward compatibility, no new writes)
session_state_events — One row per curated state key change from events
```

### Data Persistence Strategy

#### traces table (key columns)
- trace_id, session_id, user_id, app_name
- start_time, end_time, status
- total_input_tokens, total_output_tokens, total_calls, iterations
- request_id, repo_url, root_prompt_preview
- child_dispatch_count, child_total_batch_dispatches, child_error_counts (JSON)
- finish_safety_count, finish_recitation_count, finish_max_tokens_count
- tool_invocation_summary (JSON), artifact_saves, artifact_bytes_saved
- per_iteration_breakdown (JSON), model_usage_summary (JSON)
- prompt_hash (SHA256), max_depth_reached

#### telemetry table (per-call instrumentation)
- telemetry_id, trace_id, event_type ("model_call" or "tool_call")
- agent_name, iteration, depth (0 for depth-0, @d1 for depth 1)
- call_number, start_time, end_time, duration_ms
- model, input_tokens, output_tokens, thought_tokens, finish_reason
- num_contents, agent_type, prompt_chars, system_chars
- tool_name, tool_args_keys (JSON), result_preview
- REPL enrichment: repl_has_errors, repl_has_output, repl_llm_calls, stdout/stderr_len, repl_trace_summary (JSON)
- status, error_type, error_message

#### session_state_events table (state tracking)
- event_id, trace_id, seq (monotonic), event_author, event_time
- state_key, key_category (obs_reasoning, obs_dispatch, obs_artifact, obs_finish, flow_control, repl, cache, request_meta)
- key_depth (0 for base, 1 for @d1), key_fanout (for fanout-scoped keys)
- value_type, value_int, value_float, value_text (0-2000 chars), value_json

### Capture Strategy (Curated)
Only captures state keys matching:
- Prefixes: obs:, artifact_, last_repl_result, repl_submitted_code
- Exact keys: iteration_count, should_stop, final_answer, policy_violation, request_id, idempotency_key, cache:hit_count/miss_count, worker_dispatch_count

### Hook Points
1. **before_run_callback**: Create traces row with config snapshot (app:max_depth, app:max_iterations, env vars)
2. **before_model_callback**: Insert telemetry row, store (telemetry_id, start_time) in _pending_model_telemetry
3. **after_model_callback**: Update telemetry with tokens, finish_reason, duration_ms
4. **on_model_error_callback**: Mark pending telemetry as error with error_type, error_message
5. **before_tool_callback**: Insert telemetry row for tool_call
6. **after_tool_callback**: Update with result_preview, duration_ms; REPL enrichment: resolve last_repl_result by depth, extract has_errors, has_output, llm_calls, stdout/stderr lengths
7. **on_event_callback**: For each curated key in state_delta, insert session_state_events row with typed value (int/float/text/json)
8. **after_run_callback**: Update traces with final stats (end_time, status=completed, token totals, iterations, final_answer_length, etc.)

---

## 4. REPL TRACING PLUGIN

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/repl_tracing.py`

### Purpose
Captures per-code-block trace summaries from LAST_REPL_RESULT events and saves accumulated traces as a JSON artifact (repl_traces.json) at run end.

### How It Works
1. Listens on on_event_callback for state_delta entries starting with LAST_REPL_RESULT
2. Extracts trace_summary from repl_result dict
3. Groups traces by iteration and depth: key = f"d{depth}:i{iteration}"
4. Accumulates in _traces_by_iteration dict
5. On after_run_callback, saves as artifact with structure:
   ```json
   {
     "d0:i0": {"depth": 0, "iteration": 0, "trace_summary": {...}},
     "d0:i1": {...},
     "d1:i0": {"depth": 1, "iteration": 0, "trace_summary": {...}},
     ...
   }
   ```

### Trace Levels (from repl/trace.py)
Controlled by RLM_REPL_TRACE environment variable:
- Level 0: Off (default) — no tracing overhead
- Level 1: LLM call timing + variable snapshots + data flow tracking
- Level 2: Level 1 + tracemalloc memory tracking via injected header/footer

---

## 5. LANGFUSE TRACING PLUGIN

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/langfuse_tracing.py`

### Architecture
- Thin wrapper around `openinference-instrumentation-google-adk`
- One-time initialization of Langfuse client + GoogleADKInstrumentor
- All span creation is automatic via OpenTelemetry instrumentation

### Activation
Requires environment variables:
- LANGFUSE_PUBLIC_KEY
- LANGFUSE_SECRET_KEY
- LANGFUSE_BASE_URL (e.g., http://localhost:3100 for self-hosted)

### Initialization Flow
1. _init_langfuse_instrumentation() called at plugin __init__
2. Checks env vars; if any missing, returns False with warning
3. Imports langfuse.get_client() and OpenInference GoogleADKInstrumentor
4. Authenticates client with auth_check()
5. Calls GoogleADKInstrumentor().instrument() (global, process-wide)
6. Sets _INSTRUMENTED = True (idempotent guard)

### What Gets Traced
- Every model call becomes an OTel span
- Every tool invocation becomes an OTel span
- Every agent transition becomes an OTel span
- Spans automatically forwarded to Langfuse UI

---

## 6. CALLBACK SYSTEM (Worker & Reasoning)

### Worker Callbacks
**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker.py`

#### worker_before_model
- Reads agent._pending_prompt (set by dispatch closure)
- Injects it as llm_request.contents (user role, text part)

#### worker_after_model
- Extracts response_text from llm_response.content.parts (skips thought parts)
- Detects safety filtering (finish_reason == SAFETY)
- Writes to agent._result, agent._result_ready = True
- If safety filtered: agent._result_error = True
- Builds call_record dict: prompt, response, input_tokens, output_tokens, model, finish_reason, error, error_category
- Writes to agent._call_record for dispatch closure to read
- Also writes to callback_context.state[output_key] for ADK persistence
- FM-20 error isolation: callback failure doesn't crash ParallelAgent siblings

#### worker_on_model_error
- Catches LLM errors gracefully (no crash of ParallelAgent)
- Classifies error: TIMEOUT, RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, PARSE_ERROR, UNKNOWN
- Writes error_msg to agent._result, agent._result_error = True
- Returns LlmResponse so agent completes normally

### Reasoning Callbacks
**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py`

#### reasoning_before_model
- Merges ADK's dynamic instruction (from instruction template) into system_instruction
- Records per-invocation accounting: REASONING_PROMPT_CHARS, REASONING_SYSTEM_CHARS, REASONING_CONTENT_COUNT, REASONING_HISTORY_MSG_COUNT
- Snapshots context_window: agent_type, depth, content_count, prompt_chars, system_chars, total_chars

#### reasoning_after_model
- Splits llm_response.content.parts into visible and thought text
- Records depth-scoped keys: REASONING_VISIBLE_OUTPUT_TEXT@d{depth}, REASONING_THOUGHT_TEXT@d{depth}
- Extracts tokens: REASONING_INPUT_TOKENS@d{depth}, REASONING_OUTPUT_TOKENS@d{depth}, REASONING_THOUGHT_TOKENS@d{depth}
- Parses JSON response for reasoning_summary if output starts with {

### Worker Retry Plugin
**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker_retry.py`

#### WorkerRetryPlugin
- Extends ReflectAndRetryToolPlugin
- Detects empty string values in set_model_response tool results
- Triggers retry via parent class reflection/retry mechanism

#### make_worker_tool_callbacks()
- Factory returning (after_tool_cb, on_tool_error_cb)
- Wired by dispatch.py when output_schema is provided
- Captures validated structured results on worker agent._structured_result

#### BUG-13 Monkey-Patch
- Patches `google.adk.flows.llm_flows._output_schema_processor.get_structured_model_response()`
- Detects REFLECT_AND_RETRY_RESPONSE_TYPE sentinel in response
- Returns None to suppress premature worker termination
- Allows agent loop to continue for retry
- Idempotent, applied at module import time
- Observability: _bug13_stats["suppress_count"] counter readable at runtime

---

## 7. WORKER OBSERVABILITY PATH

**Critical Architecture**: ObservabilityPlugin does NOT fire for workers (isolated invocation contexts). Worker observability flows through dispatch closures instead.

### Dispatch Flow (dispatch.py)

```
dispatch closure
  ↓
llm_query_batched_async spawns K workers via ParallelAgent
  ↓
worker_after_model callback (runs in worker's agent context)
  └→ writes agent._result, agent._result_error, agent._call_record
  ↓
ParallelAgent completes, returns agent objects
  ↓
dispatch closure reads agent._call_record
  ↓
Accumulates in local _acc_* dicts (AR-CRIT-001):
  - _acc_child_dispatches (count of workers)
  - _acc_child_batch_dispatches (count of batch calls)
  - _acc_child_latencies (list of elapsed_ms per batch)
  - _acc_child_error_counts (dict: error_category → count)
  - _acc_child_summaries (dict: per-child telemetry summary)
  - _acc_structured_output_failures (count of validation failures)
  ↓
REPLTool calls flush_fn() after each execution
  ↓
flush_fn snapshots into tool_context.state (no event, direct state write):
  - OBS_CHILD_DISPATCH_COUNT
  - OBS_CHILD_DISPATCH_LATENCY_MS
  - OBS_CHILD_TOTAL_BATCH_DISPATCHES
  - OBS_CHILD_ERROR_COUNTS
  - OBS_STRUCTURED_OUTPUT_FAILURES
  - obs:child_summary@d{depth}f{fanout_idx} (per-child dict)
  - OBS_BUG13_SUPPRESS_COUNT (if > 0)
  ↓
Accumulators reset for next iteration
```

### Error Classification (worker.py)
- `_classify_error(error)` categorizes: RATE_LIMIT (429), AUTH (401/403), SERVER (5xx), CLIENT (4xx), NETWORK, TIMEOUT, PARSE_ERROR, UNKNOWN
- Written to _acc_child_error_counts[category]

### Example Error Accumulation
```python
# Line 649 in dispatch.py
for r in all_results:
    if r.error:
        cat = r.error_category or "UNKNOWN"
        _acc_child_error_counts[cat] = _acc_child_error_counts.get(cat, 0) + 1
```

---

## 8. STATE KEYS ARCHITECTURE

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py`

### Key Categories

#### Observability Keys (obs: prefix, session-scoped)
- **Token Accounting**:
  - OBS_TOTAL_INPUT_TOKENS, OBS_TOTAL_OUTPUT_TOKENS
  - OBS_TOTAL_CALLS, OBS_TOTAL_EXECUTION_TIME
  - REASONING_INPUT_TOKENS@d{depth}, REASONING_OUTPUT_TOKENS@d{depth}, REASONING_THOUGHT_TOKENS@d{depth}

- **Finish Reasons**:
  - obs:finish_safety_count, obs:finish_recitation_count, obs:finish_max_tokens_count

- **Per-Iteration Breakdown**:
  - OBS_PER_ITERATION_TOKEN_BREAKDOWN (list of dicts: iteration, call_number, input_tokens, output_tokens, finish_reason, agent_type, prompt_chars, system_chars)

- **Tool Invocation**:
  - OBS_TOOL_INVOCATION_SUMMARY (dict: tool_name → count)

- **Child Dispatch**:
  - OBS_CHILD_DISPATCH_COUNT, OBS_CHILD_ERROR_COUNTS (dict), OBS_CHILD_DISPATCH_LATENCY_MS (list), OBS_CHILD_TOTAL_BATCH_DISPATCHES
  - obs:child_summary@d{depth}f{fanout_idx} (per-child detailed dict)

- **Structured Output**:
  - OBS_STRUCTURED_OUTPUT_FAILURES (count)

- **AST Rewriting**:
  - OBS_REWRITE_COUNT, OBS_REWRITE_TOTAL_MS, OBS_REWRITE_FAILURE_COUNT, OBS_REWRITE_FAILURE_CATEGORIES

- **Reasoning Retry**:
  - OBS_REASONING_RETRY_COUNT, OBS_REASONING_RETRY_DELAY_MS

- **BUG-13 Patch**:
  - OBS_BUG13_SUPPRESS_COUNT

#### Depth-Scoped Keys
Require @d{depth} suffix for recursive agents (set in DEPTH_SCOPED_KEYS):
- ITERATION_COUNT, FINAL_ANSWER, LAST_REPL_RESULT, SHOULD_STOP
- REASONING_INPUT_TOKENS, REASONING_OUTPUT_TOKENS, REASONING_THOUGHT_TOKENS
- REASONING_VISIBLE_OUTPUT_TEXT, REASONING_THOUGHT_TEXT, REASONING_FINISH_REASON
- REPL_SUBMITTED_CODE, REPL_SUBMITTED_CODE_PREVIEW, REPL_SUBMITTED_CODE_HASH

#### Artifact Tracking
- ARTIFACT_SAVE_COUNT, ARTIFACT_LOAD_COUNT, ARTIFACT_TOTAL_BYTES_SAVED
- ARTIFACT_LAST_SAVED_FILENAME, ARTIFACT_LAST_SAVED_VERSION
- OBS_ARTIFACT_SAVES, OBS_ARTIFACT_BYTES_SAVED

### Helper Functions
- `depth_key(key, depth)` → f"{key}@d{depth}"
- `child_obs_key(depth, fanout_idx)` → f"obs:child_summary@d{depth}f{fanout_idx}"

---

## 9. ARTIFACTS SYSTEM

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/artifacts.py`

### Unwired Helper Functions (Available but not auto-called)
- `save_repl_code(ctx, iteration, turn, code)` — saves as `repl_code_iter_{iteration}_turn_{turn}.py`
- `save_repl_output(ctx, iteration, stdout, stderr)` — saves as `repl_output_iter_{iteration}.txt`
- `save_repl_trace(ctx, iteration, turn, trace_dict)` — saves as `repl_trace_iter_{iteration}_turn_{turn}.json`
- `save_worker_result(ctx, worker_name, iteration, result_text)` — saves as `worker_{worker_name}_iter_{iteration}.txt`
- `save_final_answer(ctx, answer)` — saves as `final_answer.md`
- `save_binary_artifact(ctx, filename, data, mime_type)` — arbitrary binary
- `load_artifact(ctx, filename, version)` — load by name/version
- `list_artifacts(ctx)` — enumerate session artifacts
- `delete_artifact(ctx, filename)` — delete by name

### Tracking Metadata
- Updated by `_update_save_tracking()`: ARTIFACT_SAVE_COUNT, ARTIFACT_TOTAL_BYTES_SAVED, ARTIFACT_LAST_SAVED_FILENAME, ARTIFACT_LAST_SAVED_VERSION

---

## 10. DASHBOARD

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/`

### Data Flow
- **Source**: `.adk/context_snapshots.jsonl` and `.adk/model_outputs.jsonl`
- **Loader**: DashboardDataLoader reads JSONL, groups by session_id, builds SessionSummary + list[IterationData]
- **UI**: Streamlit-based components
  - api_usage.py — token charts, model usage tracking
  - token_charts.py — per-iteration breakdowns
  - worker_panel.py — child dispatch metrics
  - output_panel.py — final answer, reasoning summary
  - context_bar.py — depth/iteration navigation

### Observability Visualization
Renders ObservabilityPlugin + dispatch metrics via charts and tables

---

## 11. REPL TRACE INFRASTRUCTURE

**File**: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/repl/trace.py`

### REPLTrace Dataclass
Invisible per-code-block accumulator:
- start_time, end_time (wall_time_ms when serialized)
- llm_calls: list of {index, type, start_time, prompt_len, elapsed_ms, response_len, error, extra}
- var_snapshots: list of {label, time, vars (dict of variable summaries)}
- peak_memory_bytes (tracemalloc integration)
- exceptions: list of error events
- data_flow_edges: list of (source_index, target_index) tuples
- execution_mode: "sync" | "async"
- submitted_code_*: chars, hash, preview

### DataFlowTracker
Detects when llm_query() response feeds into subsequent prompt:
- Uses substring fingerprinting (default 40 chars)
- Maintains _responses dict (call_index → response_text)
- check_prompt() detects if prev response substring in current prompt
- Records edges as (source_index, target_index)

### Code Injection (Level 2)
- TRACE_HEADER / TRACE_HEADER_MEMORY: injected before user code
- TRACE_FOOTER / TRACE_FOOTER_MEMORY: injected after user code
- Captures _rlm_trace object that REPL execution shares

---

## 12. DATA FLOW SUMMARY

### Per-Iteration Flow
```
Orchestrator iteration
  ↓
REPLTool.execute_code("user code")
  ↓
Code executes with:
  - Available: llm_query, llm_query_batched (from dispatch closure)
  - Calls to llm_query trigger dispatch.llm_query_async
  ↓
llm_query_async spawns child orchestrator at depth+1
  ↓
Child runs independently (own REPL, reasoning agent, tools)
  ↓
ParallelAgent collects all worker results
  ↓
worker_after_model callbacks extract results into agent._result, agent._call_record
  ↓
dispatch closure reads agent._call_record, accumulates in _acc_* dicts
  ↓
REPL code continues with llm_query result
  ↓
REPLTool completes execution
  ↓
REPLTool calls flush_fn() → snapshots _acc_* into tool_context.state
  ↓
State mutations visible in next ObservabilityPlugin callback
  ↓
SqliteTracingPlugin.on_event_callback reads state_delta, writes session_state_events
```

### End-of-Run Flow
```
After all iterations
  ↓
ObservabilityPlugin.after_run_callback:
  - Reads final state
  - Computes reasoning_calls, worker_calls from breakdowns
  - Logs summary
  ↓
SqliteTracingPlugin.after_run_callback:
  - Updates traces row with final stats
  - Computes model_usage summary
  - Calculates max_depth_reached from telemetry agent_name patterns
  ↓
REPLTracingPlugin.after_run_callback:
  - Saves _traces_by_iteration as repl_traces.json artifact
  ↓
LangfuseTracingPlugin:
  - All spans already sent via OTel instrumentation
```

---

## 13. KEY ARCHITECTURAL PRINCIPLES

### AR-CRIT-001: State Mutation Rules
- **NEVER** write directly to `ctx.session.state[key] = value` in dispatch closures
- **Correct**: Use local accumulators + flush_fn() → tool_context.state
- **Correct**: Write in tool/callback contexts: tool_context.state, callback_context.state, EventActions
- **Why**: Maintains ADK event tracking; bypassing breaks observability

### AD-CRIT-002: Worker Observability Isolation
- Workers run in isolated invocation contexts (ParallelAgent behavior)
- ObservabilityPlugin callbacks don't fire for workers
- Worker observability must flow through dispatch closures
- Error classification happens in _classify_error(exception)

### BUG-13 Mitigation
- ADK's postprocessor prematurely terminates workers on set_model_response
- Patch detects ToolFailureResponse sentinel and returns None
- Allows retry loop to continue
- Idempotent, installed at import time
- Countered in _bug13_stats["suppress_count"]

### Depth Scoping
- Recursive agents need independent state per depth
- depth_key("key", 2) → "key@d2"
- SqliteTracingPlugin parses @d{depth} suffix, stores in key_depth column

---

## 14. KNOWN LIMITATIONS & CAVEATS

1. **ObservabilityPlugin doesn't fire for workers** — expected; use dispatch accumulators
2. **Ephemeral keys in after_model_callback** — workaround: after_agent_callback re-persists
3. **ADK private module restructure risk** — BUG-13 patch catches ImportError gracefully
4. **Langfuse optional dependency** — plugin skips with warning if env vars missing
5. **REPLTracingPlugin requires LAST_REPL_RESULT events** — no trace if tracing disabled
6. **SqliteTracingPlugin schema evolution** — migration logic handles adding columns to existing DBs
7. **Artifact service optional** — all save_*_artifact functions return None gracefully if no service

---

## 15. OBSERVABILITY CHECKLIST

To verify observability is working:

1. **Token Accounting**: Check OBS_TOTAL_INPUT_TOKENS, OBS_TOTAL_OUTPUT_TOKENS in traces.db
2. **Finish Reasons**: Verify obs:finish_safety_count, obs:finish_recitation_count in SQLite telemetry
3. **Child Dispatch**: OBS_CHILD_DISPATCH_COUNT > 0, OBS_CHILD_ERROR_COUNTS dict populated
4. **Worker Errors**: Look for OBS_CHILD_ERROR_COUNTS entries (keys: RATE_LIMIT, SERVER, TIMEOUT, etc.)
5. **REPL Traces**: repl_traces.json artifact created with per-iteration trace_summary
6. **SQLite**: traces.db populated with 3 tables (traces, telemetry, session_state_events)
7. **Langfuse**: Spans visible in Langfuse UI if credentials configured
8. **Dashboard**: `.adk/context_snapshots.jsonl` entries for dashboard rendering

---

## Summary

The RLM-ADK observability stack consists of:
- **ObservabilityPlugin**: Token accounting, finish reasons, timing
- **SqliteTracingPlugin**: 3-table schema (traces, telemetry, session_state_events)
- **REPLTracingPlugin**: Per-iteration code block traces as JSON artifact
- **LangfuseTracingPlugin**: OpenTelemetry integration for self-hosted Langfuse
- **Callback System**: worker_after_model, reasoning_before/after_model for per-call instrumentation
- **Dispatch Accumulators**: Local state → flush_fn → tool_context.state (AR-CRIT-001)
- **Artifact System**: Unwired helpers for saving REPL code, output, traces, final answer
- **Depth Scoping**: @d{depth} suffix for recursive agent state isolation
- **Dashboard**: Streamlit UI consuming .adk/context_snapshots.jsonl

All plugins are observe-only (non-blocking), with errors caught and logged at warning/debug levels.
