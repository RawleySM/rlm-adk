# Observability and Logging Reference

> Single source of truth for all RLM-ADK observability outputs, plugins, and configuration.
> Supersedes: `artifact_persistence.md`, `debug_yaml_and_traces_db.md`, `dashboard_overlap_and_session_db.md`, `e2e_session_runner_analysis.md`.

---

## 1. Overview

RLM-ADK produces six categories of observability output during an agent run:

```
Runner.run_async()
  └─ RLMOrchestratorAgent
       ├─ ObservabilityPlugin        ──► session state (always-on metrics)
       ├─ DebugLoggingPlugin         ──► rlm_adk_debug.yaml
       ├─ SqliteTracingPlugin        ──► .adk/traces.db
       ├─ ContextWindowSnapshotPlugin──► .adk/context_snapshots.jsonl
       │                                 .adk/model_outputs.jsonl
       ├─ LangfuseTracingPlugin      ──► external Langfuse instance (OTel)
       └─ FileArtifactService        ──► .adk/artifacts/...
```

The **dashboard** reads only the two JSONL files. The **debug YAML**, **traces.db**, and **artifacts** are independent outputs with no downstream consumers inside the project (they are for human inspection and external tooling). **Session.db** is created by the ADK session service for state persistence.

All `.adk/` paths are resolved to **absolute paths** under the project root via `_project_root()` in `rlm_adk/agent.py`. This ensures a single `.adk/` directory regardless of working directory.

---

## 2. Observability Outputs Inventory

| Output | Generator | Default Path | Toggle Env Var | Code Toggle | Default | Consumers |
|--------|-----------|-------------|----------------|-------------|---------|-----------|
| Session state metrics | `ObservabilityPlugin` | N/A (in-memory state) | N/A | N/A | Always ON | DebugLoggingPlugin, SqliteTracingPlugin |
| Debug YAML | `DebugLoggingPlugin` | `<project_root>/rlm_adk_debug.yaml` | `RLM_ADK_DEBUG=1` | `debug=True` | ON | Human inspection |
| Traces DB | `SqliteTracingPlugin` | `<project_root>/.adk/traces.db` | `RLM_ADK_SQLITE_TRACING=1` | `sqlite_tracing=True` | ON | Human inspection, SQL queries |
| Context snapshots | `ContextWindowSnapshotPlugin` | `<project_root>/.adk/context_snapshots.jsonl` | `RLM_CONTEXT_SNAPSHOTS=1` | N/A | OFF | Dashboard |
| Model outputs | `ContextWindowSnapshotPlugin` | `<project_root>/.adk/model_outputs.jsonl` | `RLM_CONTEXT_SNAPSHOTS=1` | N/A | OFF | Dashboard |
| Artifacts | `FileArtifactService` | `<project_root>/.adk/artifacts/` | N/A | `artifact_service=` param | ON | Human inspection |
| Session DB | `SqliteSessionService` | `<project_root>/.adk/session.db` | `RLM_SESSION_DB=<path>` | `db_path=` param | ON | ADK Runner |
| Langfuse traces | `LangfuseTracingPlugin` | External HTTP | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | `langfuse=True` | OFF | Langfuse UI |

---

## 3. Plugin Architecture

### Callback Lifecycle

All plugins implement `BasePlugin` and hook into ADK's callback chain. The orchestrator invokes callbacks in registration order:

```
before_run_callback          (once per run)
  before_agent_callback      (per agent invocation)
    before_model_callback    (per LLM call)
    after_model_callback
    on_model_error_callback  (on failure)
    before_tool_callback     (per tool call)
    after_tool_callback
    on_event_callback        (per yielded event)
  after_agent_callback
after_run_callback           (once per run)
```

Plugin registration happens in `rlm_adk/agent.py` `_default_plugins()` (lines 246-283). Plugins are appended to a list and passed to the agent factory.

### 3.1 ObservabilityPlugin (always-on)

| Aspect | Detail |
|--------|--------|
| File | `rlm_adk/plugins/observability.py` |
| Output | Session state keys only (no files) |
| Toggle | None -- always enabled (line 265 in `agent.py`) |

**State keys written by ObservabilityPlugin:**
- `INVOCATION_START_TIME`
- `OBS_TOTAL_CALLS` (line 120)
- `OBS_TOTAL_INPUT_TOKENS` (line 128)
- `OBS_TOTAL_OUTPUT_TOKENS` (line 131)
- `OBS_PER_ITERATION_TOKEN_BREAKDOWN`
- Dynamic `obs:model_usage:{model}` keys
- `OBS_TOOL_INVOCATION_SUMMARY`
- `OBS_ARTIFACT_SAVES` (but see [Section 9 Artifact Tracking Bug](#artifact-tracking-bug) -- never populated during normal runs)
- `OBS_TOTAL_EXECUTION_TIME` (line 265)
- `USER_LAST_SUCCESSFUL_CALL_ID` (line 271 -- cross-session write)

**State keys NOT written by ObservabilityPlugin** (contrary to prior documentation):
- `OBS_ITERATION_TIMES` -- dead key, never written (see [Section 9](#dead-state-keys))
- `OBS_WORKER_TOTAL_DISPATCHES` -- written by dispatch closure (`dispatch.py:280`), not ObservabilityPlugin
- `OBS_ARTIFACT_BYTES_SAVED` -- dead key, never written
- `REASONING_INPUT_TOKENS` -- written by `reasoning_after_model` (`callbacks/reasoning.py:173`)
- `WORKER_INPUT_TOKENS` -- written by dispatch closure (`dispatch.py`)

These state keys are consumed by both the DebugLoggingPlugin and SqliteTracingPlugin for their summary reports.

> **GAP: State mutation visibility.** ObservabilityPlugin writes state via direct `callback_context.state[key] = value` and `invocation_context.session.state[key] = value`. These writes do NOT appear in the event stream's `state_delta` dictionaries. They are only visible in the final session state after the run completes.

> **GAP: Stale CONTEXT_WINDOW_SNAPSHOT.** `CONTEXT_WINDOW_SNAPSHOT` read at line 154 is stale/misattributed for worker calls -- it always contains the last reasoning agent's snapshot, not worker data.

### 3.2 DebugLoggingPlugin --> `rlm_adk_debug.yaml`

| Aspect | Detail |
|--------|--------|
| File | `rlm_adk/plugins/debug_logging.py` (lines 1-530) |
| Class | `DebugLoggingPlugin(BasePlugin)` (line 52) |
| Output | Single YAML file written at end of run |
| Default path | `rlm_adk_debug.yaml` (line 64) |
| Toggle | `RLM_ADK_DEBUG=1` env var (line 266) or `debug=True` param |
| Default | ON |

**Constructor parameters:**
- `output_path: str = "rlm_adk_debug.yaml"` (line 64)
- `include_session_state: bool = True` (line 65)
- `include_system_instruction: bool = True` (line 66)

**Callback data capture:**

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

**File write** occurs in `after_run_callback` (lines 429-507). Output structure:

```python
# Lines 492-500
{
    "session_id": ...,
    "user_id": ...,
    "final_state": state_snapshot,
    "traces": [...]  # All accumulated trace entries
}
```

Run summary (lines 438-478) is printed to **stdout** via `print()` calls. This is separate from the YAML file write (lines 483-507). The summary includes token counts, timing, worker dispatch stats, and artifact stats.

**State keys read** (from `rlm_adk/state.py` lines 23-47): `ITERATION_COUNT`, `REQUEST_ID`, `FINAL_ANSWER`, `REASONING_PROMPT_CHARS`, `REASONING_SYSTEM_CHARS`, `REASONING_HISTORY_MSG_COUNT`, `REASONING_CONTENT_COUNT`, `CONTEXT_WINDOW_SNAPSHOT`, `REASONING_INPUT_TOKENS`, `WORKER_INPUT_TOKENS`, `WORKER_PROMPT_CHARS`, `WORKER_CONTENT_COUNT`, `WORKER_DISPATCH_COUNT`, `WORKER_RESULTS_COMMITTED`, `WORKER_EVENTS_DRAINED`, `OBS_WORKER_DISPATCH_LATENCY_MS`, `OBS_TOTAL_INPUT_TOKENS`, `OBS_TOTAL_OUTPUT_TOKENS`, `OBS_TOTAL_CALLS`, `OBS_TOTAL_EXECUTION_TIME`, `OBS_WORKER_TOTAL_DISPATCHES`, `OBS_ARTIFACT_SAVES`, `OBS_ARTIFACT_BYTES_SAVED`.

**State key provenance table** -- not all state keys come from ObservabilityPlugin:

| State Key | Written By | File |
|-----------|-----------|------|
| `REASONING_PROMPT_CHARS` | `reasoning_before_model` | `callbacks/reasoning.py:142` |
| `REASONING_SYSTEM_CHARS` | `reasoning_before_model` | `callbacks/reasoning.py:143` |
| `REASONING_CONTENT_COUNT` | `reasoning_before_model` | `callbacks/reasoning.py:144` |
| `REASONING_HISTORY_MSG_COUNT` | `reasoning_before_model` | `callbacks/reasoning.py:145` |
| `REASONING_INPUT_TOKENS` | `reasoning_after_model` | `callbacks/reasoning.py:173` |
| `REASONING_OUTPUT_TOKENS` | `reasoning_after_model` | `callbacks/reasoning.py:176` |
| `WORKER_PROMPT_CHARS` | dispatch closure | `dispatch.py` |
| `WORKER_CONTENT_COUNT` | dispatch closure | `dispatch.py` |
| `WORKER_INPUT_TOKENS` | dispatch closure | `dispatch.py` |
| `WORKER_DISPATCH_COUNT` | dispatch closure | `dispatch.py:279` |
| `WORKER_RESULTS_COMMITTED` | orchestrator | `orchestrator.py:226` |
| `WORKER_EVENTS_DRAINED` | orchestrator | `orchestrator.py:225,312` |
| `OBS_WORKER_TOTAL_DISPATCHES` | dispatch closure | `dispatch.py:280` |
| `OBS_WORKER_DISPATCH_LATENCY_MS` | dispatch closure | `dispatch.py:419` |
| `CONTEXT_WINDOW_SNAPSHOT` | `reasoning_before_model` | `callbacks/reasoning.py:146` |
| `OBS_TOTAL_INPUT_TOKENS` | ObservabilityPlugin | `plugins/observability.py:128` |
| `OBS_TOTAL_OUTPUT_TOKENS` | ObservabilityPlugin | `plugins/observability.py:131` |
| `OBS_TOTAL_CALLS` | ObservabilityPlugin | `plugins/observability.py:120` |
| `OBS_TOTAL_EXECUTION_TIME` | ObservabilityPlugin | `plugins/observability.py:265` |

### 3.3 SqliteTracingPlugin --> `.adk/traces.db`

| Aspect | Detail |
|--------|--------|
| File | `rlm_adk/plugins/sqlite_tracing.py` (lines 1-471) |
| Class | `SqliteTracingPlugin(BasePlugin)` (line 75) |
| Output | SQLite database with `traces` and `spans` tables |
| Default path | `.adk/traces.db` (line 94) |
| Toggle | `RLM_ADK_SQLITE_TRACING=1` env var (line 269) or `sqlite_tracing=True` param |
| Default | ON |

> **Note:** SqliteTracingPlugin reads only 5 state keys in `after_run_callback`: `FINAL_ANSWER`, `OBS_TOTAL_INPUT_TOKENS`, `OBS_TOTAL_OUTPUT_TOKENS`, `OBS_TOTAL_CALLS`, `ITERATION_COUNT`. It does NOT consume the full OBS key set.

**Schema** (lines 38-72):

`traces` table (lines 39-53):
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

`spans` table (lines 55-66):
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

Indexes (lines 68-71) on: `trace_id`, `operation`, `session_id`, `start_time`.

**DB initialization** (lines 109-121): parent directory creation, SQLite connection, schema execution, performance pragmas (`WAL`, `SYNCHRONOUS=NORMAL`, `busy_timeout=5000`).

**Callback data capture:**

| Callback | Lines | Action |
|----------|-------|--------|
| `before_run_callback` | 194-219 | INSERT root trace row, init `_trace_id` |
| `after_run_callback` | 221-251 | UPDATE trace with summary stats |
| `before_agent_callback` | 255-271 | Create agent span, push onto parent stack |
| `after_agent_callback` | 273-283 | Close agent span, set end_time |
| `before_model_callback` | 287-309 | Create model_call span, store in `_pending_model_spans` |
| `after_model_callback` | 311-359 | Close model_call span with token usage |
| `on_model_error_callback` | 361-386 | Mark pending model span as error |
| `before_tool_callback` | 390-412 | Create tool_call span, store in `_pending_tool_spans` |
| `after_tool_callback` | 414-434 | Close tool_call span with result preview |
| `on_event_callback` | 438-459 | Capture artifact_save spans for artifact deltas |

**Span parent-child tracking:**
- `_agent_span_stack` (line 102): stack of active agent span IDs
- `_pending_model_spans` (line 104): dict for before/after model pairing
- `_pending_tool_spans` (line 106): dict for before/after tool pairing
- `_current_parent_span_id()` (lines 127-129): top of agent stack

**Data write methods:**
- `_write_span()` (lines 131-165): INSERT OR REPLACE + commit
- `_update_span_end()` (lines 167-190): UPDATE + commit

### 3.4 ContextWindowSnapshotPlugin --> JSONL files

| Aspect | Detail |
|--------|--------|
| File | `rlm_adk/plugins/context_snapshot.py` |
| Output | `.adk/context_snapshots.jsonl` and `.adk/model_outputs.jsonl` |
| Toggle | `RLM_CONTEXT_SNAPSHOTS=1` env var (lines 279-282 in `agent.py`) |
| Default | OFF |

This plugin captures pre-model and post-model snapshots as line-delimited JSON. It is the sole data source for the dashboard (see [Section 5](#5-dashboard)).

> **Critical ordering constraint:** ContextWindowSnapshotPlugin MUST be last in the plugin list (currently appended last at `agent.py:279-282`). Its `after_model_callback` depends on agent callbacks (`reasoning_before_model` / `worker_before_model`) having already mutated the `LlmRequest` in-place. Plugins fire BEFORE agent callbacks, so the plugin stores a mutable reference in `before_model_callback` and decomposes it in `after_model_callback` after agent callbacks have run.

> **BUG risk:** Any new plugin that returns non-None from `before_model_callback` would short-circuit remaining plugins AND agent callbacks, breaking ContextWindowSnapshotPlugin's decomposition.

### 3.5 LangfuseTracingPlugin (external)

| Aspect | Detail |
|--------|--------|
| File | `rlm_adk/plugins/langfuse_tracing.py` |
| Output | Traces sent to external Langfuse instance via OTel |
| Toggle | `langfuse=True` param + env vars below |
| Default | OFF |

Uses `openinference-instrumentation-google-adk` for OTel auto-instrumentation. Requires: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`.

---

## 4. Artifact System

### Storage Layout

Default artifact root: `<project_root>/.adk/artifacts/` (defined in `rlm_adk/agent.py` via `_project_root()`).

```
.adk/artifacts/
└── users/
    └── {user_id}/
        ├── sessions/
        │   └── {session_id}/
        │       └── artifacts/
        │           └── {artifact_path}/
        │               └── versions/
        │                   └── {version}/
        │                       ├── {original_filename}
        │                       └── metadata.json
        └── artifacts/
            └── {artifact_path}/...
```

### Artifact Helper Functions (`rlm_adk/artifacts.py`)

| Function | Lines | Purpose |
|----------|-------|---------|
| `save_repl_output()` | 62-107 | Saves REPL stdout/stderr |
| `save_repl_code()` | 110-150 | Saves Python code blocks |
| `save_worker_result()` | 153-195 | Saves worker/sub-agent results |
| `save_final_answer()` | 198-236 | Saves final answer as markdown |
| `save_binary_artifact()` | 239-275 | Saves arbitrary binary data |
| `load_artifact()` | 278-313 | Loads artifacts by filename |
| `list_artifacts()` | 316-341 | Lists all artifact filenames |
| `delete_artifact()` | 344-373 | Deletes artifacts |
| `_update_save_tracking()` | 376-397 | Updates state metadata |

### Naming Conventions

| Type | Filename Pattern |
|------|-----------------|
| REPL code | `repl_code_iter_{iteration}_turn_{turn}.py` |
| REPL output | `repl_output_iter_{iteration}.txt` |
| Worker results | `worker_{name}_iter_{iteration}.txt` |
| Final answer | `final_answer.md` |

### Full Call Chain: Entrypoint to Disk Write

```
1. CLI: adk run rlm_adk
   └─> Discovers app symbol (rlm_adk/agent.py:459)

2. create_rlm_runner()  (rlm_adk/agent.py:419-446)
   └─> Resolves artifact_service (lines 439-440):
       default: FileArtifactService(root_dir=_DEFAULT_ARTIFACT_ROOT)  # absolute path via _project_root()
   └─> Creates Runner(artifact_service=artifact_service)

3. Runner.run_async(user_id, session_id, new_message)
   └─> Sets ctx.artifact_service before invocation

4. RLMOrchestratorAgent._run_async_impl()
   └─> Iteration loop (orchestrator.py:92+)
   └─> save_repl_code(ctx, ...)        → artifacts.py:110-150
   └─> save_repl_output(ctx, ...)      → artifacts.py:62-107
   └─> save_worker_result(ctx, ...)    → artifacts.py:153-195
   └─> save_binary_artifact(ctx, ...)  → artifacts.py:239-275
   └─> save_final_answer(ctx, ...)     → artifacts.py:198-236

5. Each save function calls:
   └─> inv_ctx.artifact_service.save_artifact(app_name, user_id, session_id, filename, artifact)

   **BUG: `artifacts.py` calls `inv_ctx.artifact_service.save_artifact()` directly, bypassing
   `CallbackContext.save_artifact()`.** This means artifact saves do NOT populate
   `event.actions.artifact_delta`, and ObservabilityPlugin's `on_event_callback` never sees them.
   See [Section 9 Artifact Tracking Bug](#artifact-tracking-bug) for full impact and fix options.

6. FileArtifactService.save_artifact() [async wrapper]
   └─> file_artifact_service.py:311-336
   └─> asyncio.to_thread(self._save_artifact_sync, ...)

7. FileArtifactService._save_artifact_sync() [disk write]
   └─> file_artifact_service.py:338-400
   └─> mkdir, version numbering, write_bytes/write_text, metadata.json

8. Event tracking:
   └─> artifact_delta[filename] = version (callback_context.py:118)
   └─> Yielded in Event.actions.artifact_delta
   NOTE: Step 8 is the intended flow, but it is currently unreachable because
   step 5 bypasses CallbackContext (see BUG note above).
```

### Toggle / Configuration

| Mechanism | How | Effect |
|-----------|-----|--------|
| Default | Pass nothing | Uses `FileArtifactService(root_dir=_DEFAULT_ARTIFACT_ROOT)` (absolute path) |
| In-memory | `artifact_service=InMemoryArtifactService()` | Volatile, no disk writes |
| Custom root | `FileArtifactService(root_dir="/custom/path")` | Changes storage location |
| Disable | Set `artifact_service` to `None` | All save ops gracefully skip with debug log |
| No env var toggle | N/A | No direct env var to toggle on/off |

### Artifact Lifecycle

1. **Creation**: Automatic during orchestrator execution
2. **Versioning**: Incremental integer (0, 1, 2, ...)
3. **Metadata**: JSON per version (filename, mime_type, canonical_uri, custom_metadata)
4. **Scoping**: Session-scoped (default) or user-scoped with `user:` prefix
5. **Operations**: Save, load, list, delete via artifact service API

### Key ADK Package Code

| Component | File | Lines |
|-----------|------|-------|
| `FileArtifactService.__init__` | `.venv/.../google/adk/artifacts/file_artifact_service.py` | 210-217 |
| Path building | same | 219-237 |
| `_save_artifact_sync` (disk write) | same | 338-400 |
| `_load_artifact_sync` | same | 420-471 |
| `_list_artifact_keys_sync` | same | 487-516 |
| `InvocationContext.artifact_service` | `.venv/.../google/adk/agents/invocation_context.py` | -- |
| `CallbackContext.save_artifact` | `.venv/.../google/adk/agents/callback_context.py` | 110-119 |
| `EventActions.artifact_delta` | `.venv/.../google/adk/events/event_actions.py` | 69 |
| Runner artifact delta tracking | `.venv/.../google/adk/runners.py` | 645-699 |

---

## 5. Dashboard

### Data Sources

The dashboard consumes **only** the two JSONL files. It does NOT read session.db, traces.db, debug YAML, or artifacts.

| Source | Path | Generator |
|--------|------|-----------|
| Context snapshots | `.adk/context_snapshots.jsonl` | `ContextWindowSnapshotPlugin` |
| Model outputs | `.adk/model_outputs.jsonl` | `ContextWindowSnapshotPlugin` |

Default paths from `data_loader.py` (resolved via `_project_root()` at construction time):
```python
jsonl_path = str(_project_root() / ".adk" / "context_snapshots.jsonl")
outputs_path = str(_project_root() / ".adk" / "model_outputs.jsonl")
```

### Architecture

```
ContextWindowSnapshotPlugin (generates JSONL)
  |
.adk/context_snapshots.jsonl + .adk/model_outputs.jsonl
  |
DashboardDataLoader (reads JSONL)
  |
data_models.py (ContextChunk, ContextWindow, ModelOutput, SessionSummary, IterationData)
  |
DashboardController (state management, navigation)
  |
app.py (NiceGUI UI components and layout)
```

### Overlap with Observability Stack

| Output | Used By Dashboard? |
|--------|--------------------|
| `rlm_adk_debug.yaml` | NO |
| `.adk/traces.db` | NO |
| `.adk/artifacts/` | NO |
| `.adk/context_snapshots.jsonl` | YES |
| `.adk/model_outputs.jsonl` | YES |
| Session state | NO |

### Data Loading Pipeline (`data_loader.py` lines 27-303)

| Method | Purpose | Source |
|--------|---------|--------|
| `list_sessions()` | Get distinct session_ids | `context_snapshots.jsonl` |
| `load_session(session_id)` | Load all entries for one session | Both JSONL files |
| `_read_entries(session_id)` | Filter JSONL by session_id | `context_snapshots.jsonl` |
| `_read_output_entries(session_id)` | Filter outputs by session_id | `model_outputs.jsonl` |
| `_build_summary()` | Aggregate tokens, counts | Computed from entries |
| `_build_iterations()` | Group by iteration | Computed from entries |
| `_build_context_window()` | Convert entry to ContextWindow | Single entry |
| `_build_model_output()` | Convert entry to ModelOutput | Single entry |

Graceful degradation: returns empty lists if files do not exist (lines 44-45, 102-103).

### Persistence

The dashboard has NO persistent data layer. All state lives in a volatile `DashboardState` dataclass (`controller.py` lines 23-56) and is lost on page refresh.

---

## 6. Session Storage

### What Creates session.db

**RLM ADK wrapper** (`rlm_adk/agent.py`):
```python
_DEFAULT_DB_PATH = str(_project_root() / ".adk" / "session.db")  # absolute path

def _default_session_service(db_path: str | None = None):
    resolved_path = db_path or os.getenv("RLM_SESSION_DB", _DEFAULT_DB_PATH)
    db_dir = Path(resolved_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved_path)
    return SqliteSessionService(db_path=resolved_path)
```

The ADK framework (`SqliteSessionService`) creates the database on first `create_session()` call and applies schema and pragmas.

### Path Resolution

All `.adk/` paths are resolved to absolute paths via `_project_root()` (uses `Path(__file__).resolve().parents[1]`). This ensures a single `.adk/` directory under the project root regardless of CWD. The `RLM_SESSION_DB` env var override continues to take precedence when set.

### ADK CLI vs RLM ADK Path Resolution

The ADK CLI uses `PerAgentDatabaseSessionService` with per-agent storage, creating `<agents_root>/<app_name>/.adk/session.db`. RLM ADK bypasses this via its own `_default_session_service()` in `agent.py`, using `_project_root()` for absolute path resolution.

---

## 7. E2E Test Observability

### Test Session Lifecycle

Tests use `InMemorySessionService` (no session.db created) with all file-writing plugins disabled:

```python
# tests_rlm_adk/test_provider_fake_e2e.py lines 41-57
app = create_rlm_app(
    model=os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
    thinking_budget=0,
    debug=False,
    langfuse=False,
    sqlite_tracing=False,
)
session_service = InMemorySessionService()
runner = Runner(app=app, session_service=session_service)
```

### Event Stream Structure

The orchestrator (`rlm_adk/orchestrator.py` lines 161-400) yields events at 7 generation points:

```
Runner.run_async()
  └─ Orchestrator._run_async_impl()
       for i in range(max_iterations):
         yield Event(state_delta={ITERATION_COUNT, ...})
         yield Event(state_delta={MESSAGE_HISTORY})
         await reasoning_agent.run_async(ctx)
           async for event: yield event         <-- reasoning events
         while not event_queue.empty():
           yield event_queue.get_nowait()        <-- worker events
         # Execute REPL code (may call llm_query_async)
         # Drain mid-iteration worker events
         ┌─ BRANCH A (non-final iteration):
         │  yield Event(state_delta={LAST_REPL_RESULT: {
         │    code_blocks, has_output, has_errors, total_llm_calls
         │  }})
         └─ BRANCH B (FINAL_ANSWER found, lines 336-374):
            yield Event(state_delta={FINAL_ANSWER, ...})
            yield Event(content=...)              <-- final response
            return  (LAST_REPL_RESULT NOT yielded)
```

> **GAP:** Points 6 (`LAST_REPL_RESULT`) and 7 (`FINAL_ANSWER`) are **mutually exclusive branches**, not sequential steps. When `FINAL_ANSWER` is found (orchestrator.py lines 336-374), the code returns without yielding `LAST_REPL_RESULT`. Final iteration REPL data is not captured in the event stream.

> **Note:** ObservabilityPlugin runs unconditionally in tests (added at `agent.py:265`), but its state writes are invisible to event stream scanners -- they are only available in the final session state.

### REPL Snapshot Extraction

Tests extract REPL data from the event stream (`test_provider_fake_e2e.py` lines 414-429):

```python
def _extract_repl_events(events):
    repl_snapshots = []
    worker_event_count = 0
    for event in events:
        sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
        if LAST_REPL_RESULT in sd:
            repl_snapshots.append(sd[LAST_REPL_RESULT])
        if getattr(event, "author", "").startswith("worker_"):
            worker_event_count += 1
    return repl_snapshots, worker_event_count
```

REPL snapshot structure (from `orchestrator.py` lines 391-398):
```python
{
    "code_blocks": int,
    "has_output": bool,
    "has_errors": bool,
    "total_llm_calls": int,
}
```

### Test Assertions (lines 511-564)

1. Model calls match fixture expectations
2. Worker-authored events present (author starts with `"worker_"`)
3. At least one iteration with code blocks
4. Total LLM calls > 0 (worker dispatch succeeded)
5. Either clean output OR worker calls succeeded
6. Final answer matches expected value

### Contract Runner Framework

**File**: `tests_rlm_adk/provider_fake/contract_runner.py` (lines 113-147)

```python
async def run_fixture_contract(fixture_path: Path):
    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, ...)
    try:
        base_url = await server.start()
        _set_env(base_url, router)
        runner, session = await _make_runner_and_session(router)
        final_state = await _run_to_completion(runner, session, "test prompt")
        return router.check_expectations(final_state, fixture_path, elapsed)
    finally:
        await server.stop()
        _restore_env(saved)
```

Contract validation (`fixtures.py` lines 203-260) checks `final_answer`, `total_iterations`, `total_model_calls` and returns `ContractResult(passed, checks, call_summary, total_elapsed_s)`.

Fixture JSON schema:
```json
{
  "scenario_id": "string",
  "description": "string",
  "config": { "model", "thinking_budget", "max_iterations", "retry_delay" },
  "responses": [
    { "call_index": 0, "caller": "reasoning|worker", "status": 200, "body": {} }
  ],
  "fault_injections": [
    { "call_index": 0, "fault_type": "malformed_json|http_error" }
  ],
  "expected": { "final_answer": "42", "total_iterations": 1, "total_model_calls": 1 }
}
```

### Proposed REPLTracingPlugin

**Status**: Not yet implemented.

Would persist REPL traces as ADK artifacts using the `FileArtifactService`.

**Filename pattern**: `repl_trace_iter_{iteration}.json`

**Proposed trace schema**:
```json
{
  "iteration": 0,
  "timestamp": 1708957234.123,
  "code_blocks": [
    {
      "index": 0,
      "code": "result = llm_query('...')",
      "execution_time_ms": 145.2,
      "stdout": "output text",
      "stderr": "",
      "has_errors": false,
      "llm_calls": [
        {
          "prompt": "...",
          "response": "...",
          "model": "gemini-fake",
          "input_tokens": 50,
          "output_tokens": 20,
          "execution_time_ms": 142.1
        }
      ]
    }
  ],
  "total_execution_time_ms": 145.2,
  "total_llm_calls": 1,
  "has_output": true,
  "has_errors": false,
  "final_answer": null
}
```

**Feasibility caveats:**

1. `LAST_REPL_RESULT` contains only summary integers (`code_blocks` count, `total_llm_calls` count), not per-block `RLMChatCompletion` objects. Achieving the proposed detailed schema (per-block `llm_calls` array with prompt/response/tokens) requires orchestrator changes, contradicting the "no core changes" benefit.
2. Plugin would miss the final iteration's data -- `LAST_REPL_RESULT` is not yielded when `FINAL_ANSWER` is found (see event stream diagram above).
3. `REPLResult.execution_time` already exists at `types.py:125` (in seconds, not milliseconds). Does not need to be added, just plumbed through to the event stream.
4. Test runners have no `artifact_service` (defaults to `None`). Plugin needs a `None`-guard, and the contract runner needs to supply a service.

**Implementation steps** (accounting for caveats above):
1. Create `rlm_adk/plugins/repl_tracing.py` -- listen to `LAST_REPL_RESULT` state deltas, save JSON artifacts per iteration
2. Extend `REPLResult` (`rlm_adk/types.py`) -- plumb existing `execution_time` field through to event stream
3. Instrument `LocalREPL` (`rlm_adk/repl/local_repl.py`) -- track code block execution time
4. Add query utilities (`rlm_adk/observability/repl_query.py`) -- `get_repl_traces()`, `compare_repl_snapshots()`
5. Extend `contract_runner.py` -- supply `artifact_service`, load REPL traces from artifacts post-run, expose in `ContractResult`

---

## 8. Configuration Reference

### Environment Variables

| Variable | Controls | Default | Section |
|----------|----------|---------|---------|
| `RLM_ADK_DEBUG` | DebugLoggingPlugin activation | `"1"` (ON via `debug=True` default) | [3.2](#32-debugloggingplugin----rlm_adk_debugyaml) |
| `RLM_ADK_SQLITE_TRACING` | SqliteTracingPlugin activation | `"1"` (ON via `sqlite_tracing=True` default) | [3.3](#33-sqlitetracingplugin----adktracesdb) |
| `RLM_CONTEXT_SNAPSHOTS` | ContextWindowSnapshotPlugin activation | OFF | [3.4](#34-contextwindowsnapshotplugin----jsonl-files) |
| `RLM_SESSION_DB` | Session database path override | `<project_root>/.adk/session.db` | [6](#6-session-storage) |
| `LANGFUSE_PUBLIC_KEY` | Langfuse project public key | N/A (required if langfuse=True) | [3.5](#35-langfusetracingplugin-external) |
| `LANGFUSE_SECRET_KEY` | Langfuse project secret key | N/A (required if langfuse=True) | [3.5](#35-langfusetracingplugin-external) |
| `LANGFUSE_BASE_URL` | Langfuse server URL | N/A (required if langfuse=True) | [3.5](#35-langfusetracingplugin-external) |

### Constructor Parameters (`create_rlm_runner()` / `create_rlm_app()`)

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `debug` | `bool` | `True` | Enable DebugLoggingPlugin |
| `sqlite_tracing` | `bool` | `True` | Enable SqliteTracingPlugin |
| `langfuse` | `bool` | `False` | Enable LangfuseTracingPlugin |
| `artifact_service` | `BaseArtifactService \| None` | `FileArtifactService(root_dir=_DEFAULT_ARTIFACT_ROOT)` (absolute) | Artifact storage backend |
| `db_path` | `str \| None` | `<project_root>/.adk/session.db` | Session database path |

### Plugin Constructor Parameters

| Plugin | Parameter | Default |
|--------|-----------|---------|
| `DebugLoggingPlugin` | `output_path` | `"rlm_adk_debug.yaml"` |
| `DebugLoggingPlugin` | `include_session_state` | `True` |
| `DebugLoggingPlugin` | `include_system_instruction` | `True` |
| `SqliteTracingPlugin` | `db_path` | `".adk/traces.db"` (overridden to absolute by `_default_plugins()`) |

---

## 9. Known Issues & Recommendations

### Dashboard Isolation

**Issue**: The dashboard reads only the two JSONL files and does not consume any other observability output. This is by design but means the dashboard cannot show trace/span data, artifacts, or debug YAML content.

**Implication**: To get dashboard data, `RLM_CONTEXT_SNAPSHOTS=1` must be set (it is OFF by default). Without it, the dashboard has no data to display.

### Artifact Tracking Bug

**BUG:** Split accounting between `artifacts.py` and `ObservabilityPlugin` results in permanently broken artifact metrics.

- `OBS_ARTIFACT_BYTES_SAVED` is a dead key -- defined in `state.py:105`, read in `observability.py:282` and `debug_logging.py:472`, but **never written by any code**. Always reports 0.
- `OBS_ARTIFACT_SAVES` is never populated during normal runs because `artifacts.py` bypasses `CallbackContext.save_artifact()`, calling `inv_ctx.artifact_service.save_artifact()` directly. This means `artifact_delta` is never set on events, so ObservabilityPlugin's `on_event_callback` never increments the counter. The counter that IS correct is `ARTIFACT_SAVE_COUNT` (maintained by `_update_save_tracking()` in `artifacts.py`), but ObservabilityPlugin never reads it.
- The `after_run_callback` artifact stats log branch (`observability.py:298-300`) is permanently unreachable.

**Fix options:**
- (a) ObservabilityPlugin reads `ARTIFACT_SAVE_COUNT` and `ARTIFACT_TOTAL_BYTES_SAVED` instead of `obs:` variants
- (b) `artifacts.py` uses `CallbackContext.save_artifact()` instead of direct service call

### Dead State Keys

| Dead Key | Defined | Status |
|----------|---------|--------|
| `OBS_ITERATION_TIMES` | `state.py:50` | Imported in `observability.py:27`, never written or read |
| `OBS_WORKER_TOTAL_DISPATCHES` | `state.py:85` | Not imported by `observability.py` despite synthesis claiming it's tracked |
| `OBS_ARTIFACT_LOADS` | `state.py:103` | Orphaned -- no writer, no reader |
| `OBS_ARTIFACT_DELETES` | `state.py:104` | Orphaned |
| `OBS_ARTIFACT_SAVE_LATENCY_MS` | `state.py:106` | Orphaned |
| `OBS_ARTIFACT_BYTES_SAVED` | `state.py:105` | Read but never written |

### Unused Imports in observability.py

The following imports in `observability.py` are unused:
- `REASONING_INPUT_TOKENS` (line 34)
- `REASONING_OUTPUT_TOKENS` (line 35)
- `WORKER_INPUT_TOKENS` (line 40)
- `WORKER_OUTPUT_TOKENS` (line 41)
- `OBS_ITERATION_TIMES` (line 27)

### Plugin Ordering Constraints

- ObservabilityPlugin is hardcoded first (`agent.py:265`) -- no documented reason, not technically required to be first.
- ContextWindowSnapshotPlugin **MUST** be last -- depends on agent callback mutations to `LlmRequest` having already occurred (see [Section 3.4](#34-contextwindowsnapshotplugin----jsonl-files)).
- `on_event_callback` in ObservabilityPlugin writes bypass event tracking (uses `invocation_context.session.state` directly, not `EventActions(state_delta={})`).

### Proposed Improvements

| Improvement | Status | Description |
|-------------|--------|-------------|
| REPLTracingPlugin | Proposed | Persist REPL traces as versioned JSON artifacts (see [Section 7](#proposed-repltracingplugin)) |
| ~~Absolute path resolution~~ | **RESOLVED** | All `.adk/` paths now resolve via `_project_root()` (`Path(__file__).resolve().parents[1]`). See `agent.py`, `migration.py`, `data_loader.py`. Tests: `test_adk_path_resolution.py` (12 tests). |
| Dashboard traces.db integration | Potential | Allow dashboard to optionally read from traces.db for span-level detail |
| Worker timeout | Open issue | No timeout on worker API calls; stalled Gemini call blocks forever |
| Rate-limit backoff | Open issue | No 429 backoff in worker pool; large batches hit rate limits immediately |

---

## Key Files Index

| Component | File | Lines |
|-----------|------|-------|
| Plugin registration | `rlm_adk/agent.py` | 246-283 |
| Default paths | `rlm_adk/agent.py` | 64-65 |
| Runner/app factory | `rlm_adk/agent.py` | 348-459 |
| Orchestrator event loop | `rlm_adk/orchestrator.py` | 92-400 |
| Artifact helpers | `rlm_adk/artifacts.py` | 62-397 |
| State key constants | `rlm_adk/state.py` | 1-135 |
| ObservabilityPlugin | `rlm_adk/plugins/observability.py` | -- |
| DebugLoggingPlugin | `rlm_adk/plugins/debug_logging.py` | 1-530 |
| SqliteTracingPlugin | `rlm_adk/plugins/sqlite_tracing.py` | 1-471 |
| ContextWindowSnapshotPlugin | `rlm_adk/plugins/context_snapshot.py` | -- |
| LangfuseTracingPlugin | `rlm_adk/plugins/langfuse_tracing.py` | -- |
| Dashboard data loader | `dashboard/data_loader.py` | 27-303 |
| Dashboard controller | `dashboard/controller.py` | 23-56 |
| Worker callbacks | `rlm_adk/callbacks/worker.py` | 20-142+ |
| Dispatch closures | `rlm_adk/dispatch.py` | 205-424 |
| E2E tests | `tests_rlm_adk/test_provider_fake_e2e.py` | 35-564 |
| Contract runner | `tests_rlm_adk/provider_fake/contract_runner.py` | 69-147 |
| Fixture router | `tests_rlm_adk/provider_fake/fixtures.py` | 79-268 |
| Fake server | `tests_rlm_adk/provider_fake/server.py` | 20-118 |
| ADK FileArtifactService | `.venv/.../google/adk/artifacts/file_artifact_service.py` | 210-516 |
| ADK CallbackContext | `.venv/.../google/adk/agents/callback_context.py` | 110-119 |
| ADK EventActions | `.venv/.../google/adk/events/event_actions.py` | 69 |
