<!-- validated: 2026-03-09 -->

# Artifacts and Session Layer

Reference for RLM-ADK's session persistence, state access patterns, and artifact system.

Source files: `rlm_adk/agent.py`, `rlm_adk/artifacts.py`, `rlm_adk/state.py`, `rlm_adk/plugins/repl_tracing.py`, `rlm_adk/orchestrator.py`.

---

## 1. SqliteSessionService

The default session service is created by `_default_session_service()` in `rlm_adk/agent.py`. It backs all session state to a SQLite database on disk.

### Creation flow

1. Resolve path: explicit `db_path` arg > `RLM_SESSION_DB` env var > `.adk/session.db`
2. Create parent directory (`mkdir -p`)
3. Open a synchronous `sqlite3` connection and apply startup pragmas
4. Close the synchronous connection
5. Return `SqliteSessionService(db_path=resolved_path)`

### WAL mode pragmas (`_SQLITE_STARTUP_PRAGMAS`)

| Pragma | Value | Purpose |
|--------|-------|---------|
| `journal_mode` | WAL | Write-Ahead Logging for concurrent reads |
| `synchronous` | NORMAL | Balanced durability/performance |
| `cache_size` | -64000 | 64 MB page cache |
| `temp_store` | MEMORY | In-memory temporary tables |
| `mmap_size` | 268435456 | 256 MB memory-mapped I/O |
| `wal_autocheckpoint` | 1000 | Checkpoint every 1000 pages |

WAL mode persists on disk once set. Other pragmas are per-connection but are applied by the one-time synchronous connection before ADK opens its own.

### InvocationContext lifecycle

The ADK `Runner` creates an `InvocationContext` per `run_async()` call containing:

- `ctx.invocation_id` -- UUID for this invocation
- `ctx.session` -- Session instance with `state` dict
- `ctx.session.state` -- `Dict[str, Any]` for session-scoped key/value pairs
- `ctx._invocation_context.agent` -- current agent (private API, used by callbacks)

State survives process restarts (disk-backed). The session service supports rewind/replay via version tracking.

---

## 2. State access patterns

Full state key catalog and depth-scoping rules are documented in `rlm_adk_docs/dispatch_and_state.md`. This section covers the **correct mutation paths** enforced by AR-CRIT-001.

### Correct: in tools (REPLTool)

```python
async def run_async(self, *, args, tool_context: ToolContext):
    tool_context.state[key] = value  # event-tracked by ADK
```

### Correct: in orchestrator events

```python
yield Event(
    invocation_id=ctx.invocation_id,
    author=self.name,
    actions=EventActions(state_delta={key: value}),
)
```

### Correct: in callbacks (via callback_context)

```python
def after_model(callback_context: CallbackContext, llm_response):
    callback_context.state[key] = value
```

### NEVER: in dispatch closures

```python
# WRONG -- bypasses ADK event tracking (AR-CRIT-001)
ctx.session.state[key] = value
```

Dispatch closures use **local accumulators** that capture values in closure scope, then `flush_fn()` atomically snapshots them into `tool_context.state` after each REPL execution. This prevents dirty reads under concurrent execution and maintains ADK traceability.

---

## 3. FileArtifactService

ADK's built-in `FileArtifactService` persists versioned files to disk. Created by `create_rlm_runner()` when no explicit artifact service is provided:

```python
artifact_service = FileArtifactService(root_dir=".adk/artifacts")
```

### Disk layout

```
.adk/artifacts/users/{user_id}/sessions/{session_id}/artifacts/
  repl_code_d0_f0_iter_1_turn_0.py/
    versions/0/repl_code_d0_f0_iter_1_turn_0.py
  repl_code_d1_f0_iter_1_turn_0.py/
    versions/0/repl_code_d1_f0_iter_1_turn_0.py
  repl_traces.json/
    versions/0/repl_traces.json
  final_answer_d0_f0.md/
    versions/0/final_answer_d0_f0.md
```

Each artifact filename maps to a directory. Subsequent saves to the same filename create new version directories (0, 1, 2, ...). The service resolves the latest version by default when loading.

### Versioning

- `save_artifact()` returns the version number (int) of the saved artifact
- `load_artifact(filename, version=None)` loads the latest version; pass an explicit version number to load a specific one
- Versions are monotonically increasing integers starting at 0

---

## 4. Active artifact pipelines

Three artifact pipelines are currently wired in production code:

| Artifact | Naming convention | Written by | Trigger |
|----------|-------------------|------------|---------|
| Submitted REPL code | `repl_code_d{D}_f{F}_iter_{N}_turn_{M}.py` | `REPLTool.run_async()` via `save_repl_code()` | Every `execute_code` tool call |
| Aggregated REPL traces | `repl_traces.json` | `REPLTracingPlugin.after_run_callback()` | End of run (when `RLM_REPL_TRACE >= 1`) |
| Final answer | `final_answer_d{D}_f{F}.md` | Orchestrator via `save_final_answer()` | Final answer detected |

### repl_code pipeline

`REPLTool.run_async()` calls `await save_repl_code(tool_context, iteration, turn, code)` immediately after receiving the submitted code, **before execution begins**. The code is persisted even if execution fails, is cancelled, or hits the call limit.

The artifact path is independent of the state-based observability path. Both fire on every tool call:

- **State path**: `tool_context.state[REPL_SUBMITTED_CODE_*]` keys flow through `SqliteTracingPlugin` into `session_state_events`.
- **Artifact path**: `save_repl_code()` writes a `.py` file through `FileArtifactService` to disk.

### repl_traces.json pipeline

`REPLTracingPlugin` listens on `on_event_callback` for `LAST_REPL_RESULT` state deltas. It extracts `trace_summary` from each result dict, groups by `d{depth}:i{iteration}`, and saves the aggregate as a single JSON artifact at run end.

Requires `RLM_REPL_TRACE=1` or `RLM_REPL_TRACE=2` to activate.

### final_answer.md pipeline

The orchestrator calls `save_final_answer(ctx, answer)` when a final answer is detected. The artifact is saved as `final_answer.md` with MIME type `text/markdown`.

---

## 5. Available but unwired helpers

The following helpers in `rlm_adk/artifacts.py` are fully implemented but not called from production code paths. All accept `InvocationContext` or `CallbackContext` and return `None` gracefully when no artifact service is configured.

| Helper | Artifact name | Purpose |
|--------|---------------|---------|
| `save_repl_output(ctx, iteration, stdout, stderr, depth, fanout_idx)` | `repl_output_d{D}_f{F}_iter_{N}.txt` | Persist stdout/stderr from REPL execution |
| `save_repl_trace(ctx, iteration, turn, trace_dict, depth, fanout_idx)` | `repl_trace_d{D}_f{F}_iter_{N}_turn_{M}.json` | Persist per-block trace as JSON |
| `save_worker_result(ctx, worker_name, iteration, result_text)` | `worker_{name}_iter_{N}.txt` | Persist worker agent responses |
| `save_binary_artifact(ctx, filename, data, mime_type)` | caller-defined | Generic binary artifact persistence |
| `load_artifact(ctx, filename, version=None)` | -- | Load artifact by filename; latest version if unspecified |
| `list_artifacts(ctx)` | -- | List all artifact keys in current session scope |
| `delete_artifact(ctx, filename)` | -- | Delete artifact and all its versions |

`should_offload_to_artifact(data, threshold=10240)` is a synchronous utility that returns `True` when `len(data)` exceeds the threshold (default 10 KB), intended for deciding whether to store data inline in state or offload to an artifact.

---

## 6. Tracking metadata

Every `save_*` call updates session state via `_update_save_tracking()`:

| State key | Type | Description |
|-----------|------|-------------|
| `ARTIFACT_SAVE_COUNT` | int | Incremented per save operation |
| `ARTIFACT_TOTAL_BYTES_SAVED` | int | Cumulative byte count across all saves |
| `ARTIFACT_LAST_SAVED_FILENAME` | str | Most recent artifact filename |
| `ARTIFACT_LAST_SAVED_VERSION` | int | Most recent version number |
| `ARTIFACT_LOAD_COUNT` | int | Incremented per successful `load_artifact()` call |

These keys are session-scoped (not depth-scoped). The `ObservabilityPlugin` tracks artifact operations via `on_event_callback` watching `artifact_delta` in events, and the `SqliteTracingPlugin` captures these keys in `session_state_events` when they appear in state deltas.

Note: `_update_save_tracking()` writes directly to `ctx.session.state` (not through `tool_context.state`), because artifact helpers receive `InvocationContext` rather than `ToolContext`. This is an accepted deviation from AR-CRIT-001 since artifact tracking metadata is observability-only and does not drive control flow.

---

## ADK Gotchas

### Ephemeral state keys in plugin callbacks

Writes to `callback_context.state` in `after_model_callback` do NOT land in `state_delta` on yielded Events. ADK's `base_llm_flow.py` does not wire `event_actions` for plugin `after_model_callback`. This affects artifact tracking keys observed via `on_event_callback`. The workaround is in `ObservabilityPlugin.after_agent_callback`, which re-reads and re-writes affected keys through a properly-wired `CallbackContext`.

### Private API: CallbackContext._invocation_context

`CallbackContext` does not expose `.agent` publicly. Artifact helpers that need session access use `ctx._invocation_context` — a private API that could change in future ADK releases.

### State mutation (AR-CRIT-001)

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. The write appears to succeed at runtime but the Runner never sees it, so it is never persisted and does not appear in the event stream. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

The `_update_save_tracking()` deviation noted above is an accepted exception for observability-only metadata.

---

## Recent Changes

> Append entries here when modifying source files documented by this branch. A stop hook (`ai_docs/scripts/check_doc_staleness.py`) will remind you.

- **2026-03-09 13:00** — Initial branch doc created from codebase exploration.
- **2026-03-09 13:00** — `artifacts.py`: Wired `save_repl_code()` into `REPLTool.run_async()` for REPL code persistence. Fixed AR-CRIT-001 in `_update_save_tracking()` and `load_artifact()` — uses `ctx.state` (ADK State wrapper) instead of raw `ctx.session.state`.
- **2026-03-09 14:00** — `artifacts.py`, `repl_tool.py`, `orchestrator.py`, `agent.py`, `dispatch.py`: Added `depth` and `fanout_idx` parameters to `save_repl_code()`, `save_repl_output()`, `save_repl_trace()`, `save_final_answer()`. Artifact filenames now use `d{depth}_f{fanout_idx}` prefix (e.g. `repl_code_d1_f2_iter_3_turn_0.py`) to prevent collisions between parent/child orchestrators and between batched siblings. REPLTool accepts `fanout_idx` and threads it alongside `depth` to artifact helpers. Orchestrator threads `fanout_idx` through to REPLTool and `save_final_answer()`. `create_child_orchestrator()` accepts and passes `fanout_idx`. `_run_child()` in dispatch threads `fanout_idx` to child creation.

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
