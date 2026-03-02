# Debug YAML and Traces.db Observability Outputs

## 1. `rlm_adk_debug.yaml` - YAML Debug Log

### Primary Generator: DebugLoggingPlugin
- **File**: `rlm_adk/plugins/debug_logging.py` (lines 1-530)
- **Class**: `DebugLoggingPlugin(BasePlugin)` (line 52)

### Output File Configuration
- **Default path**: `rlm_adk_debug.yaml` (line 64, constructor parameter)
- **Constructor args**:
  - `output_path: str = "rlm_adk_debug.yaml"` (line 64)
  - `include_session_state: bool = True` (line 65)
  - `include_system_instruction: bool = True` (line 66)

### Data Generation Path (ADK Callback Methods)

| Callback | Lines | Records |
|----------|-------|---------|
| `before_agent_callback` | 74-101 | `event="before_agent"`, agent_name, state snapshot, request_id |
| `after_agent_callback` | 103-126 | `event="after_agent"`, timestamp |
| `before_model_callback` | 128-215 | `event="before_model"`, model, prompt_preview, system_instruction, token accounting |
| `after_model_callback` | 217-316 | `event="after_model"`, response_preview, token usage from `usage_metadata` (bug-005 fix) |
| `on_model_error_callback` | 318-345 | `event="model_error"`, error_type, error_message |
| `before_tool_callback` | 347-365 | `event="before_tool"`, tool_name, args preview |
| `after_tool_callback` | 367-386 | `event="after_tool"`, tool_name, result_preview |
| `on_event_callback` | 388-427 | `event="on_event"`, author, state_delta_keys, artifact_delta |

### File Write: `after_run_callback` (lines 429-507)

```python
# Lines 492-500
output = {
    "session_id": invocation_context.session.id,
    "user_id": invocation_context.session.user_id,
    "final_state": state_snapshot,
    "traces": self._traces,  # All accumulated trace entries
}
with open(self._output_path, "w") as f:
    yaml.dump(output, f, default_flow_style=False, sort_keys=False)
```

Run summary logged at lines 438-478: token counts, timing, worker dispatch stats, artifact stats.

### Activation / Toggle

**In `rlm_adk/agent.py` `_default_plugins()` (line 246-283):**
- Appended if `debug=True` (line 268)
- **Env var override** (line 266): `RLM_ADK_DEBUG` in `("1", "true", "yes")`
- Factory functions `create_rlm_app()` / `create_rlm_runner()`: `debug` parameter (default `True`)

### State Keys Read
From `rlm_adk/state.py` (lines 23-47 imports):
- `ITERATION_COUNT`, `REQUEST_ID`, `FINAL_ANSWER`
- `REASONING_PROMPT_CHARS`, `REASONING_SYSTEM_CHARS`, `REASONING_HISTORY_MSG_COUNT`, `REASONING_CONTENT_COUNT`
- `WORKER_PROMPT_CHARS`, `WORKER_CONTENT_COUNT`
- `OBS_TOTAL_INPUT_TOKENS`, `OBS_TOTAL_OUTPUT_TOKENS`, `OBS_TOTAL_CALLS`
- `OBS_TOTAL_EXECUTION_TIME`, `OBS_WORKER_TOTAL_DISPATCHES`, `OBS_ARTIFACT_SAVES`, `OBS_ARTIFACT_BYTES_SAVED`

---

## 2. `.adk/traces.db` - SQLite Telemetry Database

### Primary Generator: SqliteTracingPlugin
- **File**: `rlm_adk/plugins/sqlite_tracing.py` (lines 1-471)
- **Class**: `SqliteTracingPlugin(BasePlugin)` (line 75)

### Database File Configuration
- **Default path**: `.adk/traces.db` (line 94, constructor parameter)

### Database Schema (lines 38-72)

**`traces` table** (lines 39-53):
```sql
CREATE TABLE IF NOT EXISTS traces (
    trace_id            TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    user_id             TEXT,
    app_name            TEXT,
    start_time          REAL NOT NULL,
    end_time            REAL,
    status              TEXT DEFAULT 'running',
    total_input_tokens  INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_calls         INTEGER DEFAULT 0,
    iterations          INTEGER DEFAULT 0,
    final_answer_length INTEGER,
    metadata            TEXT
);
```

**`spans` table** (lines 55-66):
```sql
CREATE TABLE IF NOT EXISTS spans (
    span_id         TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    parent_span_id  TEXT,
    operation_name  TEXT NOT NULL,
    agent_name      TEXT,
    start_time      REAL NOT NULL,
    end_time        REAL,
    status          TEXT DEFAULT 'ok',
    attributes      TEXT,
    events          TEXT
);
```

**Indexes** (lines 68-71): on trace_id, operation, session_id, start_time

### Database Initialization (lines 109-121)
- Parent directory creation (line 112)
- SQLite connection (line 113)
- Schema execution (line 114)
- Performance pragmas (lines 115-117): `WAL`, `SYNCHRONOUS=NORMAL`, `busy_timeout=5000`

### Data Generation Path

| Callback | Lines | Action |
|----------|-------|--------|
| `before_run_callback` | 194-219 | INSERT root trace row, init `_trace_id` |
| `after_run_callback` | 221-251 | UPDATE trace with summary stats (tokens, calls, iterations, final_answer) |
| `before_agent_callback` | 255-271 | Create agent span, push onto parent stack |
| `after_agent_callback` | 273-283 | Close agent span, set end_time |
| `before_model_callback` | 287-309 | Create model_call span, store in `_pending_model_spans` |
| `after_model_callback` | 311-359 | Close model_call span with token usage; fallback standalone span |
| `on_model_error_callback` | 361-386 | Mark pending model span as error |
| `before_tool_callback` | 390-412 | Create tool_call span, store in `_pending_tool_spans` |
| `after_tool_callback` | 414-434 | Close tool_call span with result preview |
| `on_event_callback` | 438-459 | Capture artifact_save spans for artifact deltas |

### Data Write Methods
- `_write_span()` (lines 131-165): INSERT OR REPLACE + commit
- `_update_span_end()` (lines 167-190): UPDATE + commit

### Span Parent-Child Tracking
- `_agent_span_stack` (line 102): Stack of active agent span IDs
- `_pending_model_spans` (line 104): Dict for before/after model pairing
- `_pending_tool_spans` (line 106): Dict for before/after tool pairing
- `_current_parent_span_id()` (lines 127-129): Top of agent stack

### Activation / Toggle

**In `rlm_adk/agent.py` `_default_plugins()` (line 246-283):**
- Appended if `sqlite_tracing=True` (line 270)
- **Env var override** (line 269): `RLM_ADK_SQLITE_TRACING` in `("1", "true", "yes")`
- Factory functions: `sqlite_tracing` parameter (default `True`)

---

## 3. Related Plugins

### ObservabilityPlugin
- **File**: `rlm_adk/plugins/observability.py`
- **Purpose**: Tracks metrics and usage, writes to session state (not files)
- **Always enabled** in `_default_plugins()` (line 265)
- **Populates state keys** consumed by both Debug and SQLite plugins

### ContextWindowSnapshotPlugin (Optional)
- **File**: `rlm_adk/plugins/context_snapshot.py`
- **Output files**: `.adk/context_snapshots.jsonl`, `.adk/model_outputs.jsonl`
- **Activation**: Only if `RLM_CONTEXT_SNAPSHOTS=1` env var (lines 279-282 in agent.py)

---

## 4. Summary Table

| Output | Plugin | Default Path | Toggle Env Var | Code Toggle | Default |
|--------|--------|--------------|----------------|-------------|---------|
| Debug YAML | `DebugLoggingPlugin` | `rlm_adk_debug.yaml` | `RLM_ADK_DEBUG=1` | `debug=True` | ON |
| Traces DB | `SqliteTracingPlugin` | `.adk/traces.db` | `RLM_ADK_SQLITE_TRACING=1` | `sqlite_tracing=True` | ON |
| Context Snapshots | `ContextWindowSnapshotPlugin` | `.adk/context_snapshots.jsonl` | `RLM_CONTEXT_SNAPSHOTS=1` | N/A | OFF |
| Metrics (state only) | `ObservabilityPlugin` | N/A (session state) | N/A | N/A | Always ON |
