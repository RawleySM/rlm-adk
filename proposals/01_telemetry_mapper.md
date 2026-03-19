# Telemetry Mapper: Signal Catalog for Polya Understand Skill Evaluation

**Date:** 2026-03-18
**Author:** Telemetry-Mapper teammate
**Status:** Proposal (research/design -- no code changes)

This document catalogs every telemetry signal available during a Polya understand
skill execution, maps each signal to what it reveals about the agent's
understanding process, identifies gaps in observability coverage, and notes
which signals are topology-specific vs universal.

---

## 1. Signal Catalog Table

Each row maps a concrete telemetry signal to the understanding-process aspect
it reveals. Signals are grouped by their capture mechanism.

### 1.1 Dispatch Accumulator Signals (flush_fn -> tool_context.state)

Written by `flush_fn()` in `rlm_adk/dispatch.py` (line 790), flushed into
`tool_context.state` by `REPLTool.run_async()` at line 296 of
`rlm_adk/tools/repl_tool.py`.

| Signal | State Key | Type | What It Reveals About Understanding |
|--------|-----------|------|-------------------------------------|
| Per-iteration child dispatch count | `obs:child_dispatch_count` | int | How many sub-queries the agent chose to spawn in this REPL turn. For Polya, this is the number of probe children (v1: 8 dimensions, T2: Q questions, T3: selected dimensions, T4: 2 advocates). A low count may indicate the agent is skipping probing phases. |
| Cumulative child dispatch count | `obs:child_dispatch_count_total` | int | Running total of all child dispatches across all REPL turns. Reveals the total investigative effort invested. Monotonically non-decreasing, seeded to 0 at `orchestrator.py` line 331. |
| Per-iteration batch dispatch count | `obs:child_total_batch_dispatches` | int | Number of `llm_query_batched()` calls this turn (each batched call counts as 1 regardless of batch size). Reveals whether the agent used parallel fan-out (expected for PROBE phases) vs sequential dispatch (REFRAME, SYNTHESIZE, VALIDATE, REFLECT). |
| Cumulative batch dispatch count | `obs:child_batch_dispatches_total` | int | Running total of batched dispatch calls. For v1 Polya with 2 cycles, expect at least 2 (one per PROBE phase). |
| Dispatch latency list | `obs:child_dispatch_latency_ms` | list[float] | Wall-clock latency per batch dispatch. Reveals how long each probe/synthesis/validation child took. High latency on PROBE batches may indicate context packet size issues. No cumulative counterpart (latency lists would grow unbounded). |
| Per-iteration error counts | `obs:child_error_counts` | dict[str, int] | Error category breakdown (`{RATE_LIMIT: N, SERVER: N, ...}`). Reveals whether probe children are failing and why -- RATE_LIMIT errors suggest throttling, UNKNOWN errors suggest probe prompt issues. |
| Cumulative error counts | `obs:child_error_counts_total` | dict[str, int] | Running total of errors across all turns. High cumulative errors across cycles indicate systemic reliability issues with the understanding topology. |
| Per-iteration structured output failures | `obs:structured_output_failures` | int | Number of children whose structured output validation was exhausted. Reveals whether probe children are unable to produce well-formed dimension responses. |
| Cumulative structured output failures | `obs:structured_output_failures_total` | int | Running total of structured output failures. |
| Per-child summary | `obs:child_summary@d{depth}f{fanout_idx}` | dict | Rich per-child telemetry including: `prompt`, `prompt_preview`, `result_text`, `result_preview`, `input_tokens`, `output_tokens`, `thought_tokens`, `finish_reason`, `error`, `error_category`, `error_message`, `elapsed_ms`, `model`, `depth`, `fanout_idx`, `structured_output` sub-dict, `nested_dispatch` sub-dict, `reasoning_summary`, `visible_output_text`, `thought_text`. **This is the single richest signal** -- it reveals exactly what each probe child was asked, what it returned, how many tokens it consumed, whether it errored, and what structured output it produced. |
| BUG-13 suppress count | `obs:bug13_suppress_count` | int | Number of times the BUG-13 monkey-patch suppressed premature worker termination during structured output retry. Non-zero values reveal that probe children hit the retry path. |

Source: `rlm_adk/dispatch.py` lines 790-829 (flush_fn), lines 564-655 (per-child summary construction), lines 727-756 (accumulator updates).

### 1.2 ObservabilityPlugin Signals (reasoning agent level)

Written by `ObservabilityPlugin` in `rlm_adk/plugins/observability.py` (line 50).
These fire for the **parent reasoning agent only** -- not for worker children
(section 8 of `observability.md`).

| Signal | State Key | Type | What It Reveals About Understanding |
|--------|-----------|------|-------------------------------------|
| Total reasoning LLM calls | `obs:total_calls` | int | Total model calls by the parent reasoning agent. For Polya understand, this is the number of REPL tool invocations (each triggers a model call to generate code). Multiple calls indicate the agent is iterating on its understanding strategy. |
| Total input tokens (reasoning) | `obs:total_input_tokens` | int | Cumulative input tokens consumed by the parent agent. Reveals context window pressure -- high values may indicate the agent is accumulating large probe response histories. |
| Total output tokens (reasoning) | `obs:total_output_tokens` | int | Cumulative output tokens from the parent agent. Reveals code generation effort -- longer code blocks suggest more complex orchestration logic. |
| Per-iteration token breakdown | `obs:per_iteration_token_breakdown` | list[dict] | List of `{iteration, call_number, input_tokens, output_tokens, finish_reason, agent_type, prompt_chars, system_chars, context_snapshot}` dicts. Reveals token consumption trajectory across REPL turns -- increasing `input_tokens` indicates context accumulation. |
| Finish reason counters | `obs:finish_{reason}_count` | int | Per-reason counters (SAFETY, RECITATION, MAX_TOKENS). Safety finishes reveal content filtering during understanding. MAX_TOKENS finishes reveal context window exhaustion. |
| Tool invocation summary | `obs:tool_invocation_summary` | dict[str, int] | `{execute_code: N, set_model_response: M}`. Reveals how many REPL turns the agent used for the understand skill vs how many times it attempted structured output. |
| Per-model usage | `obs:model_usage:{model_name}` | dict | `{calls, input_tokens, output_tokens}` per model version. Reveals which model handled reasoning vs which handled child probing. |
| Context window snapshot | `context_window_snapshot` | dict | Snapshot of prompt/system char counts at each model call. Reveals how the context window fills up as the understanding loop progresses. |
| Artifact saves | `obs:artifact_saves` | int | Number of artifact saves during the run. Reveals whether the agent is persisting intermediate understanding artifacts. |
| Invocation start time | `invocation_start_time` | float | Unix timestamp of invocation start. Combined with end time, reveals total wall-clock duration of the understanding process. |

Source: `rlm_adk/plugins/observability.py` lines 66-408.

### 1.3 REPL Trace Signals (REPLTrace dataclass)

Captured when `RLM_REPL_TRACE >= 1`. Dataclass defined at
`rlm_adk/repl/trace.py` line 22. Stored in `LAST_REPL_RESULT.trace_summary`.

| Signal | Field | Type | What It Reveals About Understanding |
|--------|-------|------|-------------------------------------|
| Wall time | `wall_time_ms` | float | Total execution time for the REPL code block. Reveals how long the expanded Polya skill code took to run (including all child dispatches). |
| LLM call list | `llm_calls` | list[dict] | Each entry: `{index, type, start_time, prompt_len, elapsed_ms, response_len, error, batch_size, input_tokens, output_tokens, thoughts_tokens, model, finish_reason, error_category}`. **Critical for understanding evaluation** -- reveals the exact sequence of `llm_query()` and `llm_query_batched()` calls the Polya skill made, their prompt sizes, response sizes, and timing. Maps directly to Polya phases (REFRAME, PROBE, SYNTHESIZE, VALIDATE, REFLECT). |
| Data flow edges | `data_flow_edges` | list[tuple[int, int]] | `(source_call_index, target_call_index)` tuples detecting when one `llm_query()` response was fed into a subsequent prompt. **Reveals iterative refinement** -- e.g., whether REFRAME output was incorporated into PROBE prompts, whether PROBE responses were fed into SYNTHESIZE. The presence and density of edges indicates how well the Polya loop chains information. |
| Variable snapshots | `var_snapshots` | list[dict] | `{label, time, vars}` snapshots of REPL namespace variables. Reveals intermediate state during skill execution -- e.g., what `packets`, `manifest`, `reframed_questions`, `probe_responses`, `understanding`, `validation`, `reflection` variables contained. |
| Peak memory bytes | `peak_memory_bytes` | int | Peak memory usage (trace level 2 only). Reveals whether large context packets cause memory pressure during understanding. |
| Exceptions | `exceptions` | list[dict] | Error events during execution. Reveals runtime failures in the Polya skill code itself (parsing errors, type errors in response handling). |
| Execution mode | `execution_mode` | str | `"sync"` or `"async"`. Always `"async"` for Polya skills (they call `llm_query` which is AST-rewritten). |
| Submitted code chars | `submitted_code_chars` | int | Size of the code block submitted. For Polya skill expansion, this is the size of the expanded skill source. Reveals code complexity. |
| Submitted code hash | `submitted_code_hash` | str | SHA-256 of submitted code. Enables deduplication and caching analysis. |
| LLM call count (summary) | `llm_call_count` | int | Total number of LLM calls in this code block. For a single-cycle v1 Polya: expect ~11 calls (1 reframe + 8 probes + 1 synthesize + 1 validate + 0-1 reflect). |
| Failed LLM calls (summary) | `failed_llm_calls` | int | Number of LLM calls that returned errors. Reveals probe failure rate. |
| Data flow edge count (summary) | `data_flow_edges` (in summary) | int | Count of detected edges. Reveals chaining density. |

Source: `rlm_adk/repl/trace.py` lines 22-117.

### 1.4 SQLite Tracing Tables

Persisted by `SqliteTracingPlugin` in `rlm_adk/plugins/sqlite_tracing.py` (line 325).

#### 1.4.1 `traces` table (one row per invocation)

| Column | Type | What It Reveals About Understanding |
|--------|------|-------------------------------------|
| `total_input_tokens` | INT | Total input tokens for the entire session. Reveals the cost of the understanding process. |
| `total_output_tokens` | INT | Total output tokens. Reveals generation volume. |
| `total_calls` | INT | Total LLM calls (reasoning agent). Reveals REPL turn count. |
| `iterations` | INT | Number of REPL iterations. Each Polya cycle typically uses 1 REPL turn. |
| `child_dispatch_count` | INT | Final per-iteration dispatch count (last turn only -- see oscillation caveat in `observability.md` section 8.1). |
| `child_total_batch_dispatches` | INT | Final per-iteration batch count. |
| `child_error_counts` | TEXT (JSON) | Final per-iteration error breakdown. |
| `finish_safety_count` | INT | Safety-filtered model calls. |
| `finish_recitation_count` | INT | Recitation-blocked calls. |
| `finish_max_tokens_count` | INT | Max-tokens exhaustion events. |
| `per_iteration_breakdown` | TEXT (JSON) | Full token trajectory across all turns. |
| `model_usage_summary` | TEXT (JSON) | Per-model token/call aggregates. |
| `tool_invocation_summary` | TEXT (JSON) | Tool usage histogram. |
| `artifact_saves` | INT | Number of persisted artifacts. |
| `max_depth_reached` | INT | Deepest recursion depth. For Polya, always depth 1 (parent dispatches to depth-1 children). |
| `prompt_hash` | TEXT | SHA-256 of the root prompt. Enables analysis of how different objectives affect understanding. |

Source: `rlm_adk/plugins/sqlite_tracing.py` lines 210-243.

#### 1.4.2 `telemetry` table (one row per model call or tool invocation)

| Column | Type | What It Reveals About Understanding |
|--------|------|-------------------------------------|
| `event_type` | TEXT | `model_call` or `tool_call`. Distinguishes reasoning calls from REPL executions. |
| `agent_name` | TEXT | Which agent made the call. |
| `iteration` | INT | REPL iteration number. Maps to Polya cycle for single-turn-per-cycle skills. |
| `depth` | INT | Recursion depth. Parent is 0, probes are 1. |
| `input_tokens` / `output_tokens` / `thought_tokens` | INT | Per-call token counts. Reveals per-phase token cost. |
| `finish_reason` | TEXT | LLM finish reason. STOP is normal; SAFETY/MAX_TOKENS indicate problems. |
| `tool_name` | TEXT | `execute_code` for REPL calls. |
| `repl_has_errors` | INT | Whether REPL execution had errors. Reveals skill code failures. |
| `repl_has_output` | INT | Whether REPL produced stdout output. Polya skills print debug logs, so this should always be 1. |
| `repl_llm_calls` | INT | Number of child LLM calls within the REPL execution. The key metric for understanding probe fan-out. |
| `repl_trace_summary` | TEXT (JSON) | Embedded REPLTrace summary (same as section 1.3 summary fields). **Highest-fidelity per-code-block signal in the database.** |
| `repl_stdout` / `repl_stderr` | TEXT | Full stdout/stderr from REPL. For Polya skills, stdout contains the `_log()` debug output showing phase progression, prompt lengths, response previews, and verdicts. |
| `skill_instruction` | TEXT | Active skill instruction at the time of the model call. Reveals which Polya topology was selected by the instruction router. |
| `prompt_chars` / `system_chars` | INT | Prompt and system instruction sizes for reasoning agent calls. |
| `result_payload` | TEXT | Serialized tool result. For `execute_code`, this is the full REPL response dict. |

Source: `rlm_adk/plugins/sqlite_tracing.py` lines 258-294.

#### 1.4.3 `session_state_events` table (one row per curated state key change)

| Column | Type | What It Reveals About Understanding |
|--------|------|-------------------------------------|
| `state_key` | TEXT | The base key that changed. Filtered by curated prefixes (`obs:`, `artifact_`, `last_repl_result`, `repl_submitted_code`, `repl_expanded_code`, `repl_skill_expansion_meta`, `repl_did_expand`) and exact keys (`iteration_count`, `should_stop`, `final_answer`, `request_id`, `skill_instruction`, etc.). |
| `key_category` | TEXT | One of: `obs_reasoning`, `obs_dispatch`, `obs_artifact`, `obs_finish`, `flow_control`, `repl`, `cache`, `request_meta`, `other`. Enables filtering for dispatch-specific events during understanding. |
| `key_depth` | INT | Depth parsed from `@dN` suffix. 0 for parent, N for children. |
| `key_fanout` | INT | Fanout index parsed from `@dNfM` suffix. Maps to specific probe children. |
| `seq` | INT | Monotonic sequence number within the trace. Enables exact ordering of state mutations -- reveals the temporal sequence of dispatch-count increments, error accumulations, and iteration transitions. |
| `value_int` / `value_float` / `value_text` / `value_json` | MIXED | Typed value columns. `value_json` carries the rich `obs:child_summary@d{depth}f{fanout}` dicts. |

Source: `rlm_adk/plugins/sqlite_tracing.py` lines 296-311, lines 586-628 (`_insert_sse`), lines 113-144 (curated capture set).

### 1.5 REPL State Snapshot (_rlm_state)

Built by `REPLTool.run_async()` at line 192 of `rlm_adk/tools/repl_tool.py`.
Injected into REPL globals as `_rlm_state` before each code block executes.
Read-only snapshot of `EXPOSED_STATE_KEYS` (defined at `rlm_adk/state.py` line 160).

| Key in _rlm_state | Source Key | What It Reveals About Understanding |
|--------------------|-----------|-------------------------------------|
| `iteration_count` | `iteration_count` (depth-scoped) | Current REPL turn number. Polya skill code can inspect this to adapt behavior across cycles. |
| `current_depth` | `current_depth` | Recursion depth. Always 0 for the parent reasoning agent executing the skill. |
| `app:max_iterations` | `app:max_iterations` | Configured iteration limit. Constrains how many Polya cycles can run. |
| `app:max_depth` | `app:max_depth` | Configured depth limit. Constrains whether probes can recurse further. |
| `obs:child_dispatch_count` | Per-iteration key | Dispatch count from the *previous* turn (taken before current execution). Oscillates 0/N between turns. |
| `obs:child_dispatch_count_total` | Cumulative key | Stable running total of all dispatches. The reliable metric for "how many probes so far." |
| `obs:child_error_counts` | Per-iteration key | Error breakdown from the previous turn. |
| `obs:child_dispatch_latency_ms` | Per-iteration key | Latency list from the previous turn. |
| `obs:child_total_batch_dispatches` | Per-iteration key | Batch count from the previous turn. |
| `obs:child_batch_dispatches_total` | Cumulative key | Stable running total of batch dispatches. |
| `obs:structured_output_failures` | Per-iteration key | Structured output failures from the previous turn. |
| `obs:structured_output_failures_total` | Cumulative key | Running total of structured output failures. |
| `obs:total_input_tokens` | Reasoning total | Total input tokens consumed by the parent so far. |
| `obs:total_output_tokens` | Reasoning total | Total output tokens generated by the parent so far. |
| `reasoning_input_tokens` | Depth-scoped | Input tokens for the most recent reasoning call. |
| `reasoning_output_tokens` | Depth-scoped | Output tokens for the most recent reasoning call. |
| `obs:rewrite_count` | Global | Number of AST rewrites performed (1 per REPL turn with `llm_query` calls). |
| `obs:rewrite_failure_count` | Global | Number of AST rewrite failures. |
| `last_repl_result` | Depth-scoped | The REPL result dict from the previous turn including `trace_summary`, `total_llm_calls`, `has_errors`, `stdout`, `stderr`. |
| `repl_submitted_code_chars` | Depth-scoped | Size of submitted code from the previous turn. |

Source: `rlm_adk/state.py` lines 160-183 (`EXPOSED_STATE_KEYS`), `rlm_adk/tools/repl_tool.py` lines 185-198.

### 1.6 Skill Expansion Signals

Written by `REPLTool.run_async()` when synthetic skill imports are expanded
(`rlm_adk/tools/repl_tool.py` lines 164-183).

| Signal | State Key | Type | What It Reveals About Understanding |
|--------|-----------|------|-------------------------------------|
| Expanded code | `repl_expanded_code` (depth-scoped) | str | Full source of the Polya skill after expansion. Reveals which topology variant was loaded. |
| Expanded code hash | `repl_expanded_code_hash` (depth-scoped) | str | SHA-256 of expanded code. Enables version tracking. |
| Expansion metadata | `repl_skill_expansion_meta` (depth-scoped) | dict | `{symbols: [...], modules: [...]}`. Lists which functions/classes from the Polya skill were inlined. Reveals the complete dependency tree of the topology. |
| Did expand flag | `repl_did_expand` (depth-scoped) | bool | Whether skill expansion occurred. Always `True` for Polya skills. |

Source: `rlm_adk/tools/repl_tool.py` lines 175-183, `rlm_adk/state.py` lines 116-119.

### 1.7 Reasoning Callback Signals

Written by `reasoning_before_model` and `reasoning_after_model` in
`rlm_adk/callbacks/reasoning.py`.

| Signal | State Key | Type | What It Reveals About Understanding |
|--------|-----------|------|-------------------------------------|
| Reasoning prompt chars | `reasoning_prompt_chars` | int | Character count of the prompt sent to the reasoning agent. Reveals context accumulation pressure. |
| Reasoning system chars | `reasoning_system_chars` | int | Character count of the system instruction. Includes the Polya skill instruction block. |
| Reasoning input tokens | `reasoning_input_tokens` (depth-scoped) | int | Input tokens for the latest reasoning call. |
| Reasoning output tokens | `reasoning_output_tokens` (depth-scoped) | int | Output tokens for the latest reasoning call. |
| Reasoning summary | `reasoning_summary` (depth-scoped) | str | JSON summary extracted from structured output. For understanding, this is the `ReasoningOutput` summary field. |
| Reasoning visible output text | `reasoning_visible_output_text` (depth-scoped) | str | The non-thought portion of the model's response. |
| Reasoning thought text | `reasoning_thought_text` (depth-scoped) | str | The thought/chain-of-thought portion. Reveals the agent's internal deliberation about which topology to invoke. |

### 1.8 REPLTracingPlugin Artifact

Written by `REPLTracingPlugin` at run end (`rlm_adk/plugins/repl_tracing.py` lines 71-98).

| Signal | Location | Type | What It Reveals About Understanding |
|--------|----------|------|-------------------------------------|
| `repl_traces.json` artifact | File artifact, keyed `d{depth}:i{iteration}` | dict | Aggregated trace summaries across all REPL turns and depths. For understanding evaluation, the `d0:i0` entry contains the trace for the Polya skill execution: `wall_time_ms`, `llm_call_count`, `failed_llm_calls`, `peak_memory_bytes`, `data_flow_edges`, `submitted_code_chars`, `submitted_code_hash`. |

Source: `rlm_adk/plugins/repl_tracing.py` lines 25-98.

### 1.9 Worker Callback Signals (per-child, non-plugin path)

Written by `worker_after_model` in `rlm_adk/callbacks/worker.py`, consumed by
dispatch closure via `agent._call_record`.

| Signal | Field | Type | What It Reveals About Understanding |
|--------|-------|------|-------------------------------------|
| `_call_record.prompt` | str | The exact prompt sent to the probe child. Reveals what question was asked and how much context was included. |
| `_call_record.response` | str | The probe child's raw response text. Reveals quality of dimensional analysis. |
| `_call_record.input_tokens` / `output_tokens` | int | Per-child token consumption. |
| `_call_record.model` | str | Model used for this child. |
| `_call_record.finish_reason` | str | LLM finish reason for this child. |
| `_call_record.error` / `error_category` | str | Error details if the probe failed. |

Source: `rlm_adk/callbacks/worker.py` (worker_after_model callback), consumed by `rlm_adk/dispatch.py` lines 440-655.

---

## 2. Signal Sources by Layer

### Layer 1: Plugin Callbacks (ObservabilityPlugin)

- **When:** `after_model_callback`, `before_tool_callback`, `on_event_callback`, `after_agent_callback`, `after_run_callback`
- **Scope:** Parent reasoning agent only (does NOT fire for worker children)
- **Keys written:** `obs:total_calls`, `obs:total_input_tokens`, `obs:total_output_tokens`, `obs:per_iteration_token_breakdown`, `obs:finish_*_count`, `obs:tool_invocation_summary`, `obs:model_usage:*`, `obs:artifact_saves`, `context_window_snapshot`
- **File:** `rlm_adk/plugins/observability.py` (line 50)
- **Understanding relevance:** Reveals the parent agent's token economics and call patterns, but NOT the probe children's behavior.

### Layer 2: Dispatch Accumulators (flush_fn -> tool_context.state)

- **When:** After each REPL execution, `REPLTool.run_async()` calls `flush_fn()` (line 296)
- **Scope:** Aggregates all child dispatches from the current REPL turn
- **Keys written:** `obs:child_dispatch_count`, `obs:child_dispatch_latency_ms`, `obs:child_total_batch_dispatches`, `obs:child_error_counts`, `obs:structured_output_failures`, `obs:child_summary@d{depth}f{fanout}`, `obs:bug13_suppress_count`, plus all cumulative `*_total` counterparts
- **File:** `rlm_adk/dispatch.py` (lines 790-829)
- **Understanding relevance:** The primary source for child probe telemetry. Each `obs:child_summary` contains the full prompt, response, tokens, errors, and structured output details for one probe child.

### Layer 3: REPL Traces (REPLTracingPlugin)

- **When:** `on_event_callback` captures `LAST_REPL_RESULT` state deltas; `after_run_callback` saves artifact
- **Scope:** Per-code-block trace data (timing, LLM calls, data flow, memory)
- **Keys written:** `LAST_REPL_RESULT.trace_summary` (embedded in result dict)
- **Artifact:** `repl_traces.json` (versioned file artifact)
- **Files:** `rlm_adk/repl/trace.py` (lines 22-155), `rlm_adk/plugins/repl_tracing.py` (lines 25-98)
- **Understanding relevance:** Reveals the exact sequence and timing of `llm_query()` / `llm_query_batched()` calls within the Polya skill, plus data flow edges showing iterative refinement.

### Layer 4: SQLite Tables (traces, telemetry, session_state_events)

- **When:** Various callbacks throughout execution
- **Scope:** Persistent structured telemetry in `.adk/traces.db`
- **Tables:** `traces` (1 row per invocation), `telemetry` (1 row per model/tool call), `session_state_events` (1 row per curated state key change)
- **File:** `rlm_adk/plugins/sqlite_tracing.py` (lines 258-321 schema, lines 586-628 SSE insert, lines 1096-1120 on_event)
- **Understanding relevance:** The durable queryable record. `telemetry.repl_trace_summary` embeds the REPLTrace summary; `telemetry.repl_stdout` contains Polya debug logs; `session_state_events` provides a time-ordered stream of all dispatch metric changes.

### Layer 5: State Snapshot (_rlm_state)

- **When:** Built by `REPLTool.run_async()` before each code block executes (line 192)
- **Scope:** Read-only snapshot of `EXPOSED_STATE_KEYS` injected into REPL globals
- **File:** `rlm_adk/tools/repl_tool.py` (lines 185-198), `rlm_adk/state.py` (lines 160-183)
- **Understanding relevance:** Enables the Polya skill code itself to introspect dispatch metrics from previous turns. The cumulative `*_total` keys provide stable running totals.

---

## 3. Telemetry Gaps

### Gap 1: No Topology Identification in Telemetry

**Missing aspect:** Which Polya topology variant (v1, T1, T2, T3, T4) was selected and executed.

**Current state:** The `skill_instruction` column in `telemetry` captures the full skill instruction text at `before_model_callback` time (sqlite_tracing.py line 287), and `repl_skill_expansion_meta` lists expanded symbols. However, there is no single, query-friendly field that says "this was a T3 run."

**Where to capture:** In `REPLTool.run_async()`, after `expand_skill_imports()` completes. Parse the `expansion.expanded_modules` list to extract the topology identifier (e.g., `rlm_repl_skills.polya_understand_t3_adaptive` -> `"t3_adaptive"`). Write to a new state key like `repl_skill_topology`.

**Estimated complexity:** Low. 5-10 lines in `repl_tool.py`, 1 new state key constant, add to curated capture set in sqlite_tracing.py.

### Gap 2: No Phase-Level Telemetry Within a Single REPL Turn

**Missing aspect:** The Polya skill executes multiple phases (REFRAME, PROBE, SYNTHESIZE, VALIDATE, REFLECT) within a single REPL `execute_code` call. There is no structured breakdown of which `llm_calls[]` entries correspond to which Polya phase.

**Current state:** The `llm_calls[]` list in REPLTrace records call index, timing, and prompt/response sizes. The `data_flow_edges` detect chaining. But there is no phase label on each call. The only way to reconstruct phases is by parsing the debug `_log()` output in `repl_stdout` or by analyzing prompt content in `obs:child_summary`.

**Where to capture:** In the dispatch closure's trace recording code (`rlm_adk/dispatch.py` lines 758-786). The Polya skill code could set a phase label on the trace object before each `llm_query()` call. Alternatively, add a `phase` parameter to `llm_query()` / `llm_query_batched()` that flows through to the trace.

**Estimated complexity:** Medium. Requires:
1. Adding an optional `phase: str` parameter to the `llm_query_async()` / `llm_query_batched_async()` closures in `dispatch.py`
2. Flowing it into the trace entry dict
3. Updating the REPLTrace `llm_calls` entry schema
4. Modifying Polya skill source to pass phase labels (all 5 topology files)

### Gap 3: No Probe Response Quality Scoring

**Missing aspect:** Whether each probe child's response actually answered the probing question with evidence, or returned a vague/hallucinated response.

**Current state:** The `obs:child_summary` contains `result_text` and `result_preview`, but no quality assessment. The Polya skill code parses responses internally (e.g., extracting STATUS/EVIDENCE/GAPS markers in T1, CONFIDENCE in T3), but these parsed fields are not surfaced to telemetry.

**Where to capture:** In the Polya skill code itself, after parsing each probe response. The skill could write structured quality metrics to a REPL variable that is then captured by `var_snapshots` or printed to stdout for `repl_stdout` capture.

**Estimated complexity:** Medium. Requires modifying all 5 topology skill source strings to emit structured quality data (e.g., `{dimension: "givens", status: "PARTIAL", confidence: "MEDIUM", evidence_len: 340, gaps_len: 120}`). This data would flow through `repl_stdout` and be captured in `telemetry.repl_stdout`.

### Gap 4: No Data Flow Edge Attribution to Polya Dimensions

**Missing aspect:** The `data_flow_edges` list in REPLTrace records `(source_call_index, target_call_index)` but does not say which Polya dimension the edge connects. For example, an edge from call 3 (probe for "unknowns") to call 9 (synthesize prompt) is recorded as `(3, 9)` but there is no way to determine which dimension's probe response was chained.

**Where to capture:** In the `DataFlowTracker` (`rlm_adk/repl/trace.py` line 120). Extend `register_response()` to accept an optional `label` parameter, and include it in the edge tuples: `(source_index, target_index, source_label, target_label)`.

**Estimated complexity:** Low-Medium. Requires:
1. Extending `DataFlowTracker` to store labels
2. Passing labels from dispatch closures
3. The dispatch closure would need the label from the Polya skill (via the phase/dimension parameter from Gap 2)

### Gap 5: No Cross-Cycle Comparison Metrics for Iterative Topologies

**Missing aspect:** For v1 (iterative) and T3 (round-trip) topologies, there is no comparison metric between cycle 1 and cycle 2 showing how the understanding improved. Did round 2 fill the gaps identified in round 1? Did confidence improve?

**Current state:** Each cycle's results are available in `repl_stdout` (debug log) and in the Polya result object's `phase_results` list, but no delta metric is computed or surfaced to telemetry.

**Where to capture:** In the Polya skill code, at the end of each cycle. Compute and print a delta summary: `{dimensions_improved: ["unknowns", "constraints"], confidence_delta: {unknowns: "LOW->MEDIUM"}, new_gaps: [], resolved_gaps: ["API schema"]}`.

**Estimated complexity:** Medium. Requires modifying v1 and T3 skill source strings to compute and emit delta metrics.

### Gap 6: No Retrieval Order Quality Signal

**Missing aspect:** Whether the retrieval order produced by the understand skill is actionable, specific, and correctly ordered by dependency.

**Current state:** The retrieval order is parsed and returned in the result object (`retrieval_order` field), and the count appears in debug logs. But there is no telemetry signal for retrieval quality (e.g., how many items are specific artifact names vs generic requests like "more documentation").

**Where to capture:** In the Polya skill code, after `extract_retrieval_order()`. Classify each item as SPECIFIC (named artifact), SEMI_SPECIFIC (category with source), or GENERIC (vague request). Emit to stdout.

**Estimated complexity:** Low. 10-15 lines of classification logic added to each topology's main function.

### Gap 7: No Timestamp for Individual Polya Phases

**Missing aspect:** Start/end timestamps for each Polya phase within a single REPL turn. The REPL trace captures `wall_time_ms` for the entire code block and `elapsed_ms` per LLM call, but there is no structured record of "REFRAME took 2.3s, PROBE batch took 5.1s, SYNTHESIZE took 1.8s."

**Where to capture:** In the Polya skill code. Wrap each phase in timing calls and emit a `phase_timings` dict to stdout or a REPL variable.

**Estimated complexity:** Low. Add `time.perf_counter()` calls around each phase in the skill source strings.

### Gap 8: No Probe-to-Dimension Mapping in Child Summaries

**Missing aspect:** The `obs:child_summary@d1f{N}` entries contain `prompt_preview` but no structured `dimension_id` field. To determine which Polya dimension a probe child investigated, one must parse the prompt text.

**Where to capture:** In the dispatch closure's child summary construction (`rlm_adk/dispatch.py` lines 564-655). Add an optional `metadata` dict parameter to `llm_query_async()` / `llm_query_batched_async()` that flows through to the child summary.

**Estimated complexity:** Medium. Requires adding a parameter to the dispatch closure signatures and modifying Polya skill code to pass metadata.

---

## 4. Per-Topology Signal Availability

### 4.1 Universal Signals (available for ALL topologies)

These signals are topology-agnostic -- they are captured by the infrastructure
regardless of which Polya variant runs.

| Signal Category | Example Keys | Source |
|----------------|-------------|--------|
| Dispatch counts | `obs:child_dispatch_count`, `obs:child_dispatch_count_total` | dispatch.py flush_fn |
| Batch dispatch counts | `obs:child_total_batch_dispatches`, `obs:child_batch_dispatches_total` | dispatch.py flush_fn |
| Error counts | `obs:child_error_counts`, `obs:child_error_counts_total` | dispatch.py flush_fn |
| Dispatch latency | `obs:child_dispatch_latency_ms` | dispatch.py flush_fn |
| Per-child summaries | `obs:child_summary@d{depth}f{fanout}` | dispatch.py _run_child |
| Structured output failures | `obs:structured_output_failures*` | dispatch.py flush_fn |
| REPL trace (llm_calls, data_flow_edges, wall_time) | `LAST_REPL_RESULT.trace_summary` | trace.py REPLTrace |
| Reasoning agent tokens | `obs:total_*_tokens`, `obs:per_iteration_token_breakdown` | observability.py |
| Skill expansion metadata | `repl_skill_expansion_meta`, `repl_did_expand` | repl_tool.py |
| Submitted/expanded code | `repl_submitted_code*`, `repl_expanded_code*` | repl_tool.py |
| SQLite telemetry rows | `telemetry.repl_*`, `telemetry.skill_instruction` | sqlite_tracing.py |
| Session state event stream | `session_state_events.*` | sqlite_tracing.py |
| _rlm_state snapshot | All `EXPOSED_STATE_KEYS` | repl_tool.py |
| REPL stdout/stderr (debug logs) | `telemetry.repl_stdout` / `repl_stderr` | sqlite_tracing.py |
| Artifact saves | `repl_traces.json`, REPL code artifacts | repl_tracing.py, repl_tool.py |

### 4.2 Topology-Specific Signal Patterns

The *values* of the universal signals differ by topology in predictable ways.
This table shows expected patterns.

| Signal | v1 (Iterative) | T1 (Workflow-First) | T2 (Flat) | T3 (Adaptive Round-Trip) | T4 (Debate) |
|--------|----------------|---------------------|-----------|--------------------------|-------------|
| **`obs:child_dispatch_count` per cycle** | 8 probes + 1 reframe + 1 synth + 1 validate + 1 reflect = ~12 | 1 workflow + N assessors + (optional) M chunk assessors + 1 synth = varies | Q investigators + 1 synth = Q+1 | 1 select + D probes + (optional) G re-probes + 1 synth = varies | 2 advocates + 1 judge = 3 |
| **`obs:child_total_batch_dispatches`** | 1 per cycle (PROBE batch) | 1-2 (step assess + optional chunk assess) | 1 (investigation batch) | 1-2 (probe R1 + optional probe R2) | 1 (advocate batch) |
| **`llm_calls[]` count** | ~12 per cycle x max_cycles | 3-4 + (N_steps x optional L2 chunks) | Q+1 (Q=5 default) | 3-5 (SELECT + R1 + optional R2 + SYNTH) | 3 (optimist + critic + judge) |
| **`data_flow_edges` density** | High: REFRAME->PROBE, PROBE->SYNTH, SYNTH->VALIDATE, VALIDATE->REFLECT, REFLECT->next REFRAME | Medium: WORKFLOW->ASSESS, ASSESS->SYNTH | Low: questions are generated locally (no LLM), only INVESTIGATE->SYNTH edge | Medium: SELECT->PROBE, PROBE->GAP_ANALYSIS (local), PROBE->REPROBE, all->SYNTH | Low: only ADVOCATE->JUDGE edges (judge never sees raw context) |
| **Multi-cycle support** | Yes (max_cycles parameter, REFLECT VERDICT: CONTINUE triggers next cycle) | No (single pass) | No (single pass) | Conditional (round 2 re-probe is a second "cycle" within single REPL turn) | No (single pass) |
| **Phase count in debug log** | 5 per cycle: REFRAME, PROBE, SYNTHESIZE, VALIDATE, REFLECT | 4: PREPARE, L1_ASSESS, L2_CHUNK (optional), SYNTHESIS | 4: BUILD_CONTEXT, GENERATE_QUESTIONS, INVESTIGATE, SYNTHESIZE | 5: SELECT, PROBE_R1, GAP_ANALYSIS, REPROBE_R2 (optional), SYNTHESIZE | 2: ADVOCATE, JUDGE |
| **Structured output usage** | Optional (output_schema parameter on llm_query) | No (text parsing) | No (text parsing) | No (text parsing) | No (text parsing) |
| **Manifest-only parent** | Yes (REFRAME sees manifest only) | Yes (L0 sees manifest only) | No (L0 sees full context) | Yes (SELECT sees manifest only) | No (advocates see full context) |
| **Debug log prefix** | `[polya_understand]` | `[t1_workflow]` | `[t2_flat]` | `[t3_adaptive]` | `[t4_debate]` |

### 4.3 Topology-Specific Result Object Fields

These are available in the Polya skill's return value (accessible in REPL
variables after skill execution) but are NOT directly surfaced to telemetry
state keys. They would appear in `var_snapshots` if trace level >= 1, and
in `repl_stdout` via the skill's `_log()` calls.

| Topology | Result Class | Unique Fields (not in other topologies) |
|----------|-------------|----------------------------------------|
| v1 | `PolyaUnderstandResult` | `halted`, `well_posedness`, `can_continue`, `phase_results[]`, `final_reflection`, `validation` |
| T1 | `T1WorkflowResult` | `workflow_steps[]`, `step_assessments[]`, `chunk_assessments{}`, `gap_assessment`, `used_l2` |
| T2 | `T2FlatResult` | `verdict` (SUFFICIENT/PARTIAL/INSUFFICIENT), `coverage_assessment`, `gaps[]`, `questions_asked[]`, `investigation_responses[]` |
| T3 | `T3AdaptiveResult` | `selected_dimensions[]`, `round1_results[]`, `round2_results[]`, `gaps_detected[]`, `cycles_completed` (1 or 2) |
| T4 | `T4DebateResult` | `verdict` (T4Verdict: PROCEED/HALT/CONDITIONAL), `confidence_map{}`, `adjudication`, `optimist_case` (T4OptimistCase), `critic_case` (T4CriticCase) |

---

## Source File Reference

| File | Lines Referenced | Role in Telemetry |
|------|----------------|-------------------|
| `rlm_adk/dispatch.py` | 440-655 (child summary), 699-789 (accumulators), 790-829 (flush_fn) | Dispatch accumulator + flush path |
| `rlm_adk/tools/repl_tool.py` | 110-341 (run_async) | State snapshot, skill expansion, flush invocation, LAST_REPL_RESULT |
| `rlm_adk/plugins/observability.py` | 50-408 | Reasoning agent token accounting |
| `rlm_adk/plugins/sqlite_tracing.py` | 50-144 (key filtering), 258-321 (schema), 586-628 (_insert_sse), 1096-1120 (on_event) | Persistent SQLite storage |
| `rlm_adk/plugins/repl_tracing.py` | 25-98 | REPL trace artifact persistence |
| `rlm_adk/repl/trace.py` | 22-155 | REPLTrace dataclass + DataFlowTracker |
| `rlm_adk/state.py` | 58-183 (keys), 186-209 (depth-scoped), 214-228 (depth_key, obs_model_usage_key) | State key constants + snapshot definition |
| `rlm_adk/orchestrator.py` | 325-334 | Cumulative counter seeding |
| `rlm_adk/callbacks/reasoning.py` | - | Reasoning prompt/token accounting |
| `rlm_adk/callbacks/worker.py` | - | Worker _call_record construction |
| `rlm_adk/skills/polya_understand.py` | 1-1329 | v1 iterative topology |
| `rlm_adk/skills/polya_understand_t1_workflow.py` | 1-1043 | T1 workflow-first topology |
| `rlm_adk/skills/polya_understand_t2_flat.py` | 1-601 | T2 flat open-ended topology |
| `rlm_adk/skills/polya_understand_t3_adaptive.py` | 1-1163 | T3 dimension-adaptive topology |
| `rlm_adk/skills/polya_understand_t4_debate.py` | 1-907 | T4 adversarial debate topology |
