# Dashboard Detail: Surfacing Stuck-Loop Diagnostics from child_reasoning_d4

## 1. Investigation Summary

**Session**: `cb5f9db2-52ed-4572-b2c9-f5268fcc38f4` | **Run**: 2026-03-20 12:03:58 | **Status**: cancelled after 143.6s

`child_reasoning_d4` (depth 4) entered a stuck loop: it made **14 model calls** and **13 tool calls** without ever calling `set_model_response`. The session was externally cancelled at 12:06:21. Agents d0-d3 each completed in a single model+tool cycle; d4 consumed **76% of the entire session's wall time** and **78% of total tokens**.

---

## 2. Telemetry Detail Captured for child_reasoning_d4

All data comes from the `telemetry` table in `rlm_adk/.adk/traces.db`, keyed by `agent_name = 'child_reasoning_d4'`.

### 2.1 Two-Phase Stuck Pattern

| Phase | Tool Calls | Duration | Behavior |
|-------|-----------|----------|----------|
| **1: Depth-limit bounce** | #1-#5 (12:04:28 - 12:05:05) | ~37s | REPL returns `[DEPTH_LIMIT] Cannot dispatch at depth 5 (max_depth=5)`. Model ignores the error and retries identically each time. |
| **2: REPL call-limit wall** | #6-#13 (12:05:05 - 12:06:17) | ~72s | `_call_count > _max_calls`. REPL returns `stderr: REPL call limit reached. Submit your final answer now.` Model ignores and retries 8 more times. |

### 2.2 Per-Call Telemetry (model_call rows)

| # | start_time | duration_ms | input_tokens | output_tokens | finish_reason | num_contents | iteration |
|---|-----------|-------------|-------------|--------------|--------------|-------------|-----------|
| 1 | 12:04:28 | 6185 | 1031 | 178 | STOP | 2 | 1 |
| 2 | 12:04:34 | 8175 | 1031 | 145 | STOP | 2 | 1 |
| 3 | 12:04:42 | 6166 | 1031 | 204 | STOP | 2 | 1 |
| 4 | 12:04:48 | 8549 | 1031 | 169 | STOP | 2 | 1 |
| 5 | 12:04:57 | 7397 | 1031 | 142 | STOP | 2 | 1 |
| 6 | 12:05:05 | 8767 | 1031 | 147 | STOP | 2 | 1 |
| 7 | 12:05:13 | 9560 | 1031 | 201 | STOP | 2 | 1 |
| 8 | 12:05:23 | 8107 | 1031 | 143 | STOP | 2 | 1 |
| 9 | 12:05:31 | 7746 | 1031 | 179 | STOP | 2 | 1 |
| 10 | 12:05:39 | 7736 | 1031 | 114 | STOP | 2 | 1 |
| 11 | 12:05:46 | 7505 | 1031 | 94 | STOP | 2 | 1 |
| 12 | 12:05:54 | 8189 | 1031 | 127 | STOP | 2 | 1 |
| 13 | 12:06:02 | 7424 | 1031 | 190 | STOP | 2 | 1 |
| 14 | 12:06:09 | 7864 | 1031 | 189 | STOP | 2 | 1 |

**Key observations captured in telemetry**:
- `input_tokens` is **constant at 1031** across all 14 calls (prompt never grows)
- `num_contents` is **constant at 2** (tool results are not appended to conversation)
- `finish_reason` is always **STOP** (never MAX_TOKENS, SAFETY, etc.)
- `iteration` stays at **1** in model rows (REPLTool increments in tool_context.state, not in telemetry model rows)
- **No cancelled model call** except the final #15 which has `end_time=None, tokens=None`

### 2.3 Per-Call Telemetry (tool_call rows)

| # | duration_ms | tool_name | repl_has_errors | repl_has_output | repl_stdout_len | repl_stderr_len | result_preview |
|---|-------------|-----------|----------------|----------------|----------------|----------------|----------------|
| 1-5 | 5-99ms | execute_code | 0 | 1 | varies | 0 | `[DEPTH_LIMIT] Cannot dispatch at depth 5...` |
| 6-13 | 5-7ms | execute_code | 1 | 0 | 0 | ~47 | `REPL call limit reached. Submit your final answer now.` |

**Key observations**:
- Phase 1 tools report `repl_has_errors=0, repl_has_output=1` (depth-limit is returned as stdout, not stderr)
- Phase 2 tools report `repl_has_errors=1, repl_has_output=0` (call-limit is returned as stderr)
- Tool durations are negligible (5-99ms) vs model durations (6-9.5s each)
- `repl_llm_calls` increments monotonically (1 through 13)

### 2.4 Aggregate Cost Impact

| Metric | d4 | Session Total | d4 % |
|--------|-----|--------------|------|
| Model calls | 14 | 18 | 78% |
| Tool calls | 13 | 17 | 76% |
| Input tokens | 13,403 | 23,783 | 56% |
| Output tokens | 2,222 | 2,832 | 78% |
| Wall time | 108.8s | 143.6s | 76% |

### 2.5 Root Cause Evidence

The stuck loop was caused by `include_contents="none"` on child reasoning agents (set at `agent.py:379`). This setting prevents ADK from appending tool-call/response pairs to conversation history. Each model call sees the **exact same 2-content, 1031-token prompt** — it cannot learn from its own REPL errors. The model instruction says "call execute_code with llm_query()" so it does, endlessly.

There is no ADK-level `max_llm_calls` guard on child reasoning agents. The REPL's `max_calls=5` correctly refuses execution, but returns the refusal as a tool response rather than terminating the agent loop.

### 2.6 Data NOT Captured

- **No session_state_events for d4**: Only 2 SSE rows exist (root-level `current_depth=0` and `iteration_count=0`). d4's depth-scoped keys are mutated inside REPL execution context and don't emit separate SSE rows.
- **No structured_outcome**: d4 never reached `set_model_response`, so `structured_outcome` and `terminal_completion` are NULL.
- **No cost tracking**: LiteLLM cost tracking was not active; `custom_metadata_json` is NULL.
- **No spans data**: Spans table is empty (legacy, no longer written to).

---

## 3. Dashboard Surfacing Proposal

### 3.1 Stuck-Loop Detection Badge

**What**: A prominent warning badge on panes where the agent appears stuck.

**Detection heuristic** (computable from existing telemetry):
```
stuck = (
    model_call_count >= 3
    AND all model calls have identical input_tokens
    AND all model calls have identical num_contents
    AND no set_model_response was issued
)
```

**Where**: In the `_header()` function of `live_invocation_tree.py`, next to the agent name and token badge. Show an amber/red pill: `STUCK: 14 model calls, same prompt`.

**Data source**: `LiveModelEvent` list on `LiveInvocationNode`. The loader already materializes these from the `telemetry` table.

### 3.2 Model Call Timeline (per-pane)

**What**: A compact horizontal timeline showing each model call and tool call as colored segments, with duration proportional to wall time.

**Mockup**:
```
child_reasoning_d4  [1035 tok]  STUCK: 14 calls, same prompt
|===M1===|t|===M2====|t|===M3===|t|...                    |===M14====|t|X
 6.2s     6ms 8.2s    6ms                                   7.9s      7ms cancelled
```

Where:
- `M` = model call (blue segments, width proportional to `duration_ms`)
- `t` = tool call (amber segments, very thin because 5-99ms)
- `X` = cancelled (red marker)

**Implementation**:
- New component `live_model_timeline.py` in `rlm_adk/dashboard/components/`
- Renders from `LivePane.model_events` and `LivePane.tool_events` (both already populated)
- Uses NiceGUI `ui.element("div")` with flexbox, each segment as a child div with proportional `flex-grow` or fixed pixel widths

### 3.3 Tool Result Stream (per-pane expandable)

**What**: An expandable section below the model timeline showing the sequence of tool invocations and their results. This is the key missing detail — the dashboard currently shows only the *latest* REPL code/stdout/stderr, but doesn't show the **history** of all tool calls.

**Mockup**:
```
TOOL CALLS (13)                                          [expand]
 #1  execute_code  6ms   stdout: [DEPTH_LIMIT] Cannot dispatch at depth 5 (max_depth=5)
 #2  execute_code  17ms  stdout: [DEPTH_LIMIT] Cannot dispatch at depth 5 (max_depth=5)
 ...
 #5  execute_code  9ms   stdout: [DEPTH_LIMIT] Cannot dispatch at depth 5 (max_depth=5)
 ── REPL CALL LIMIT HIT ──
 #6  execute_code  5ms   stderr: REPL call limit reached. Submit your final answer now.
 ...
 #13 execute_code  7ms   stderr: REPL call limit reached. Submit your final answer now.
```

**Data source**: `telemetry` table rows where `event_type = 'tool_call'` and `agent_name = 'child_reasoning_d4'`. The fields `result_preview`, `repl_stdout`, `repl_stderr`, `repl_has_errors`, `duration_ms`, and `call_number` are all already captured.

**Implementation**:
- The `LiveToolEvent` model (`live_models.py:136`) already has `result_preview`, `repl_has_errors`, `repl_has_output`, `repl_stdout_len`, `repl_stderr_len`
- `LivePane.tool_events` is already populated by the loader
- Add a new collapsible section in `_render_node()` that iterates `node.invocation.tool_events` and renders each as a compact row
- Color-code: green for successful output, amber for depth-limit, red for call-limit/error

### 3.4 Prompt Stagnation Indicator

**What**: A small indicator on each model call showing whether the prompt changed from the previous call. When `input_tokens` and `num_contents` are identical across consecutive calls, flag it as "stagnant".

**Where**: In the model call timeline (3.2) or as a column in the tool result stream (3.3).

**Detection**: Compare `input_tokens` and `num_contents` of consecutive `LiveModelEvent` entries. If both are equal for N consecutive calls, show: `prompt unchanged x N`.

### 3.5 Phase Annotation

**What**: Automatic grouping of tool calls into phases based on result pattern changes.

**Detection**:
- Group consecutive tool calls by `result_preview` prefix match (first 40 chars)
- Label transitions: e.g., "Depth-limit (5 calls)" -> "Call-limit (8 calls)"

**Where**: Rendered as horizontal divider labels in the tool result stream (3.3).

### 3.6 Aggregate Cost Breakdown (per-pane)

**What**: Show the pane's share of session-wide resources.

**Mockup** (in header area):
```
child_reasoning_d4  [1035 tok]  14 model calls | 108.8s (76% of session) | 13,403 in / 2,222 out tokens
```

**Data source**: Already available:
- `LivePane.model_events` count and sum of `duration_ms`, `input_tokens`, `output_tokens`
- Session total from `LiveRunSnapshot.stats` (needs a `total_input_tokens` / `total_output_tokens` addition)

### 3.7 Cancellation / Terminal State Marker

**What**: When the last model call has `end_time=None` (cancelled mid-request), show a distinct "cancelled mid-call" indicator rather than just "cancelled".

**Where**: In the model timeline (3.2) and in the pane status badge.

**Data source**: `LiveModelEvent` where `end_time is None` and `status = 'cancelled'`.

---

## 4. Implementation Priority

| Priority | Feature | Effort | Value |
|----------|---------|--------|-------|
| **P0** | 3.3 Tool Result Stream | Medium | Core missing data — shows WHY the agent is stuck |
| **P0** | 3.1 Stuck-Loop Badge | Small | Instant visual alert on stuck agents |
| **P1** | 3.2 Model Call Timeline | Medium | Visual timeline makes cost waste obvious |
| **P1** | 3.5 Phase Annotation | Small | Groups repetitive calls into readable phases |
| **P2** | 3.4 Prompt Stagnation Indicator | Small | Explains root cause (stateless prompt) |
| **P2** | 3.6 Cost Breakdown | Small | Helps user understand token waste |
| **P3** | 3.7 Cancellation Marker | Trivial | Polish |

## 5. Files to Modify

| File | Change |
|------|--------|
| `rlm_adk/dashboard/components/live_invocation_tree.py` | Add stuck badge in `_header()`, add tool result stream section in `_render_node()`, add phase annotations |
| `rlm_adk/dashboard/components/live_model_timeline.py` | **New file** — model/tool timeline bar component |
| `rlm_adk/dashboard/live_models.py` | Add `is_stuck` property to `LivePane`, add `total_input_tokens`/`total_output_tokens` to `LiveRunStats` |
| `rlm_adk/dashboard/live_loader.py` | Compute stuck detection from model events, populate cost breakdown |
| `rlm_adk/dashboard/live_app.py` | Wire new `on_open_tool_stream` callback for expandable tool history |

## 6. Data Already Available vs Needed

| Data Point | Available? | Source |
|-----------|-----------|--------|
| Per-call model tokens, duration, finish_reason | Yes | `LiveModelEvent` from `telemetry` |
| Per-call tool results (preview) | Yes | `LiveToolEvent.result_preview` from `telemetry` |
| Per-call tool stdout/stderr full text | Yes | `telemetry.repl_stdout` / `telemetry.repl_stderr` |
| Per-call tool error flags | Yes | `LiveToolEvent.repl_has_errors` |
| REPL call count | Yes | `LiveToolEvent.repl_llm_calls` |
| num_contents per model call | Yes | `LiveModelEvent.num_contents` |
| input_tokens per model call | Yes | `LiveModelEvent.input_tokens` |
| Session total tokens | Partial | Need to aggregate from all `LiveModelEvent` across panes |
| Cancelled mid-call detection | Yes | `LiveModelEvent.end_time is None` |

**No new telemetry columns needed.** All proposed features can be built from data already captured in the `telemetry` table and already materialized into `LiveModelEvent` / `LiveToolEvent` models.

---

## 7. Data Source Analysis: Session Events vs SQLite Telemetry

### 7.1 Can We Read from ADK Session Events Instead of SQLite?

**No — child agent events are invisible in `session.db`.**

Investigation of the ADK session database for this run found:
- `session.db` contains **only 5 events** for this session (user message, 3 orchestrator setup events, 1 reasoning_agent model call)
- **Zero events from d1, d2, d3, or d4** appear in session.db
- All 5 events share a single `invocation_id` (`e-a3b22c4f-58ff-43f0-ba0a-925885eec0b3`)
- The session `state` dict has only 7 root-level keys — no depth-scoped keys

This happens because of how `dispatch.py` runs children (line 324-336):

```python
child_ctx = ctx.model_copy()  # shallow copy of InvocationContext
branch_suffix = f"{ctx.agent.name}.{child.name}"
child_ctx.branch = f"{ctx.branch}.{branch_suffix}" if ctx.branch else branch_suffix
async for _event in child.run_async(child_ctx):
    actions = getattr(_event, "actions", None)
    state_delta = getattr(actions, "state_delta", None)
    if isinstance(state_delta, dict):
        _child_state.update(state_delta)
```

Key observations:
1. Children run via `child.run_async(child_ctx)` — this calls `BaseAgent.run_async` directly, **not** `Runner.run_async`. The Runner is what persists events to `session_service`. Without the Runner, events are yielded in-memory only.
2. The dispatch loop iterates `_event` objects but only extracts `state_delta` — it discards the full `Event` object (content, usage_metadata, finish_reason, etc.).
3. The branch path grows with nesting: d4's branch is `rlm_orchestrator.child_orchestrator_d1.child_orchestrator_d1.child_orchestrator_d2.child_orchestrator_d2.child_orchestrator_d3.child_orchestrator_d3.child_orchestrator_d4`.

### 7.2 What Data IS on the Event Objects (That We Currently Discard)

Each `_event` yielded by `child.run_async(child_ctx)` is a full ADK `Event` (Pydantic model extending `LlmResponse`) with these fields:

**Already used by dispatch:**
- `event.actions.state_delta` — merged into `_child_state`

**Available but discarded:**

| Event Field | Type | Dashboard Value |
|-------------|------|----------------|
| `event.content` | `types.Content` | Raw model output: text parts, `FunctionCall` parts (tool name + args), `FunctionResponse` parts (tool results). **This is the full conversation turn.** |
| `event.usage_metadata` | `GenerateContentResponseUsageMetadata` | `prompt_token_count`, `candidates_token_count`, `thoughts_token_count` — per-event token counts |
| `event.finish_reason` | `types.FinishReason` | STOP, SAFETY, MAX_TOKENS, RECITATION — per model call |
| `event.model_version` | `str` | Exact model version (e.g., `z-ai/glm-5-20260211`) |
| `event.author` | `str` | Agent name that produced the event |
| `event.branch` | `str` | Full branch path |
| `event.timestamp` | `float` | Event creation time |
| `event.invocation_id` | `str` | Invocation ID |
| `event.id` | `str` | Unique event ID |
| `event.get_function_calls()` | `list[FunctionCall]` | Tool calls requested by model (name, args, id) |
| `event.get_function_responses()` | `list[FunctionResponse]` | Tool results returned to model (name, response, id) |
| `event.is_final_response()` | `bool` | Whether this is the terminal text event (i.e., `set_model_response`) |
| `event.error_code` | `str` | Error code if model returned an error |
| `event.error_message` | `str` | Error message |
| `event.custom_metadata` | `dict` | Arbitrary key-value metadata (LiteLLM cost, etc.) |
| `event.actions.artifact_delta` | `dict[str, int]` | Artifact saves in this event |
| `event.actions.escalate` | `bool` | Whether agent is escalating to parent |

### 7.3 What the SQLite Plugin Captures That Events Don't

The `SqliteTracingPlugin` fires its callbacks at the plugin level (before/after model, before/after tool) and records data **not available on Event objects**:

| SQLite-Only Data | Source |
|-----------------|--------|
| `duration_ms` per model call | Plugin measures `start_time` → `end_time` around model callback |
| `prompt_chars`, `system_chars` | Read from `agent._rlm_pending_request_meta` (set by before_model) |
| `num_contents` | Count of `llm_request.contents` in before_model |
| `skill_instruction` | Read from `llm_request` config in before_model |
| `repl_stdout`, `repl_stderr` | Extracted from tool result dict in after_tool |
| `repl_has_errors`, `repl_has_output` | Extracted from tool result dict in after_tool |
| `repl_llm_calls` | Extracted from tool result dict in after_tool |
| `result_payload` (full JSON) | Full tool result dict serialized in after_tool |
| `call_number` (monotonic) | Plugin's own model_call_count per trace |
| `tool_args_keys` | Keys from tool_args dict in before_tool |
| `output_schema_name` | From llm_request in before_model |

### 7.4 What Events Have That SQLite Doesn't

| Event-Only Data | Why It Matters |
|----------------|---------------|
| `event.content.parts` — full `FunctionCall` objects | Contains the **exact code** the model submitted (currently only captured by REPL tool writing to state, which doesn't survive for d4) |
| `event.content.parts` — full `FunctionResponse` objects | Contains the **exact tool response** returned to the model (SQLite has `result_preview` truncated + `repl_stdout`/`repl_stderr` separately) |
| `event.content.parts` — text parts (model visible output + thought) | The model's reasoning text for each turn (currently captured in `model_outputs.jsonl` by `ContextWindowSnapshotPlugin`, not SQLite) |
| `event.actions.state_delta` — full delta dict per event | Currently only `_child_state.update()` is called — the per-event granularity is lost (we can't tell which state keys changed on which turn) |
| `event.is_final_response()` | Direct check for `set_model_response` — currently inferred from `terminal_completion` column being NULL |
| `event.actions.escalate` | Whether agent tried to escalate (currently not tracked) |

### 7.5 Recommendation: Capture Child Events in Dispatch

**The highest-value change is to capture child events in `dispatch.py` instead of discarding them.** The dispatch loop already iterates every event — it just throws away everything except `state_delta`.

**Proposed approach**: Accumulate child events into a list that the `SqliteTracingPlugin` (or a new lightweight plugin) can read:

```python
# In dispatch.py, line 332:
_child_events: list[Event] = []
async for _event in child.run_async(child_ctx):
    _child_events.append(_event)  # NEW: capture full event
    actions = getattr(_event, "actions", None)
    state_delta = getattr(actions, "state_delta", None)
    if isinstance(state_delta, dict):
        _child_state.update(state_delta)
```

Then the list can be:
1. **Attached to the child orchestrator** as `child._rlm_child_events = _child_events`
2. **Read by the parent's after_tool callback** which already has access to the child agent
3. **Forwarded to the dashboard** via an existing plugin callback or new state key

**However**, this would mean holding all child events in memory for the duration of the parent's REPL execution. For a stuck d4 with 14 model calls, that's ~27 Event objects (14 model response events + 13 tool response events) — negligible memory.

### 7.6 Pragmatic Path Forward

Given the data source analysis, the **pragmatic recommendation** is:

1. **For the immediate dashboard features (P0/P1)**: Use SQLite telemetry + JSONL. All required data is already there. No code changes needed outside the dashboard.

2. **For richer future features**: Wire child event capture in dispatch.py. This would unlock:
   - Per-turn `FunctionCall` args (the exact code submitted each time)
   - Per-turn `FunctionResponse` content (the exact REPL result returned)
   - Per-turn state_delta granularity (which keys changed on which turn)
   - Direct `is_final_response()` detection (stuck-loop detection without heuristics)

3. **Do NOT try to read from `session.db`**: Child events are structurally invisible there. This is an ADK architectural constraint (children run via `BaseAgent.run_async`, not `Runner.run_async`), not a bug.
