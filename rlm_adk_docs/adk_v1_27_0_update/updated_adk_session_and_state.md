<!-- validated: 2026-03-17 -->
# ADK v1.27.0 Opportunity Assessment: Session, State, and Artifact Changes

**Date:** 2026-03-17
**ADK Version:** v1.27.0 (commit 501c827, released 2026-03-12)
**Scope:** Session management, state mutation, artifact services, event compaction, durable runtime

---

## 1. Change-by-Change Analysis

### 1.1 Row-Level Locking Optimization in `append_event` (closes #4655)

**What changed:** The `SqliteSessionService.append_event` previously used table-level locking semantics. v1.27.0 introduces row-level locking optimization so concurrent appends to *different* sessions no longer block each other.

**Current installed code** (`sqlite_session_service.py` lines 360-453): The installed v1.27.0 `append_event` uses a per-connection transaction with `SELECT ... WHERE app_name=? AND user_id=? AND id=?` for staleness checks, followed by targeted `UPDATE` / `INSERT` statements within a single `async with self._get_db_connection()` block. The optimization narrows the locking scope to the specific session row being updated rather than locking the entire table.

**Impact on RLM-ADK:**

Our WAL pragma strategy in `rlm_adk/agent.py` (lines 119-126, `_SQLITE_STARTUP_PRAGMAS`) applies six pragmas via a one-time synchronous `sqlite3` connection before constructing the `SqliteSessionService`:

```python
_SQLITE_STARTUP_PRAGMAS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;
PRAGMA wal_autocheckpoint = 1000;
"""
```

These pragmas remain **fully complementary** to the row-level locking fix:

- **WAL mode** (`journal_mode = WAL`): Still critical. The ADK `SqliteSessionService` still does NOT set WAL mode (confirmed: `_get_db_connection()` at line 456-464 only sets `PRAGMA foreign_keys = ON`). WAL enables concurrent readers during writes -- the row-level locking fix reduces writer-to-writer contention but WAL is orthogonal (it enables reader concurrency).
- **`synchronous = NORMAL`**: Still needed. ADK does not set this.
- **`cache_size`, `temp_store`, `mmap_size`, `wal_autocheckpoint`**: Performance tuning unrelated to locking.

**Conclusion:** No simplification possible. Our WAL pragma strategy fills a gap that v1.27.0 does NOT address. The row-level locking fix improves multi-session concurrency, but RLM-ADK typically operates on a single session per invocation, so the direct benefit is modest. Keep `_SQLITE_STARTUP_PRAGMAS` as-is.

**One concern:** The `_get_db_connection()` still opens a new `aiosqlite.connect()` per operation (no connection pooling). Our pragmas are applied once via a synchronous connection, but `journal_mode = WAL` is *persistent on disk*, so it survives reconnection. Per-connection pragmas (`synchronous`, `cache_size`, etc.) are NOT applied to the aiosqlite connections ADK opens internally. This was a pre-existing gap, not introduced by v1.27.0.

---

### 1.2 Temp-Scoped State Visibility Fix

**What changed:** Previously, `temp:`-prefixed state keys were invisible to subsequent agents *within the same invocation*. v1.27.0 fixes this so temp state written by one agent (e.g., reasoning_agent) is visible to subsequent agents in the same invocation, but still stripped before persistence.

**How temp state works (confirmed in source):**

1. `_trim_temp_delta_state` (`base_session_service.py` lines 114-124) strips `temp:` keys from `event.actions.state_delta` before persisting.
2. `_session_util.extract_state_delta` (`_session_util.py` line 48) skips `temp:` keys when routing state to storage tiers.
3. The `State.__setitem__` (`state.py` lines 42-47) writes to BOTH `_value` (live session dict) AND `_delta` (pending commit). The fix ensures that temp keys written to `_value` remain accessible to subsequent agents during the same invocation, even though they're removed from `_delta` before persistence.

**Impact on AR-CRIT-001:**

This is the most important change for RLM-ADK. Our dispatch accumulator pattern in `rlm_adk/dispatch.py` (lines 199-812) was specifically designed to work around the fact that `temp:` state was unreliable. The `flush_fn()` pattern uses local closure accumulators that are snapshotted into `tool_context.state` after each REPL execution, avoiding any reliance on temp state.

Key question: **Could we simplify the accumulator pattern by using `temp:` keys?**

**Answer: No. The accumulator pattern should NOT be simplified.** Here is why:

1. **AR-CRIT-001 is about delta-tracked writes, not temp visibility.** The core rule is "never write `ctx.session.state[key] = value` in dispatch closures." Dispatch closures run inside the REPL execution context, where there is no `CallbackContext` or `ToolContext` available -- only the raw `InvocationContext`. Even with temp state now visible, writing to `ctx.session.state` still bypasses delta tracking.

2. **The accumulator pattern serves a different purpose.** The accumulators (`_acc_child_dispatches`, `_acc_child_error_counts`, etc. at lines 200-206) exist because dispatch closures cannot write to `tool_context.state` -- they don't have a `tool_context`. The `flush_fn()` bridges this gap by returning the accumulated state as a dict, which `REPLTool.run_async()` then writes to `tool_context.state` (lines 277-281).

3. **Temp state is stripped before persistence.** Even if we used `temp:` keys, the observability data written by dispatch closures (e.g., `OBS_CHILD_DISPATCH_COUNT`, `OBS_CHILD_ERROR_COUNTS`) are session-scoped keys that MUST persist across the invocation for `ObservabilityPlugin.after_run_callback` to read them. Making them `temp:` would break observability.

**However, one narrow opportunity exists:** The `_parent_skill_instruction` restoration logic in `flush_fn()` (line 801-802) restores `DYN_SKILL_INSTRUCTION` after child dispatch overwrites it. If temp state now flows correctly between agents, we *might* be able to use `temp:skill_instruction_backup` in `_seed_skill_instruction` callback (`orchestrator.py` line 350-356) to avoid the overwrite problem entirely. But this is fragile and the current approach works reliably.

**Conclusion:** The temp-state visibility fix does NOT enable simplification of the AR-CRIT-001 accumulator pattern. The dispatch closure architecture is fundamentally about bridging the gap between "code running in REPL" and "delta-tracked state writes," which temp visibility does not solve.

---

### 1.3 Session Validation Before Streaming

**What changed:** The Runner now validates the session exists *before* starting to stream events, rather than eagerly advancing the runner. This prevents scenarios where a caller starts consuming events from a non-existent session and gets a mid-stream error.

**Impact on `create_rlm_runner()`:**

Confirmed in `runners.py` (lines 452-562): `run_async()` calls `_get_or_create_session()` at the top of `_run_with_trace()` (line 496), which either retrieves or creates the session (if `auto_create_session=True`). Our `create_rlm_runner()` (`agent.py` lines 531-630) does NOT set `auto_create_session` -- it relies on callers creating sessions explicitly:

```python
runner = Runner(
    app=rlm_app,
    session_service=resolved_session_service,
    artifact_service=artifact_service,
)
```

This means `auto_create_session` defaults to `False`, and invalid session IDs will raise `ValueError` at the start of streaming rather than mid-stream. This is strictly better behavior for us -- no code changes needed.

**Potential enhancement:** Consider setting `auto_create_session=True` in `create_rlm_runner()` for convenience, since callers currently must explicitly create a session before calling `runner.run_async()`. This would simplify the programmatic API. However, it would be a behavioral change -- assess whether any callers rely on the explicit session creation flow.

---

### 1.4 EventCompaction via `events_compaction_config`

**What changed:** ADK now supports automatic event compaction through `App.events_compaction_config`. After each invocation completes, the Runner checks if compaction should be triggered (based on invocation count threshold or token threshold) and generates a `CompactedEvent` that summarizes older events using an LLM summarizer.

**Two compaction strategies (confirmed in `compaction.py`):**

1. **Sliding window compaction** (`compaction_interval` + `overlap_size`): Triggers after N new invocations. Summarizes the oldest events while keeping an overlap window for context continuity.
2. **Token threshold compaction** (`token_threshold` + `event_retention_size`): Triggers when prompt token count exceeds a threshold. Keeps the last N raw events and summarizes everything older.

**Impact on RLM-ADK:**

This is a **high-value opportunity** for managing context window growth in long RLM sessions. Currently, RLM sessions can generate many events per invocation (initial state, user prompt, multiple tool calls, tool responses, state deltas, final answer). A single RLM invocation with 10 REPL calls generates ~25+ events. Multi-turn sessions compound this rapidly.

**Concrete proposal:**

Wire `EventsCompactionConfig` into `create_rlm_app()` (`agent.py` line 524):

```python
# In create_rlm_app():
from google.adk.apps.app import EventsCompactionConfig

compaction_config = None
_compaction_threshold = int(os.getenv("RLM_COMPACTION_TOKEN_THRESHOLD", "0"))
if _compaction_threshold > 0:
    _retention = int(os.getenv("RLM_COMPACTION_RETENTION", "20"))
    _interval = int(os.getenv("RLM_COMPACTION_INTERVAL", "3"))
    compaction_config = EventsCompactionConfig(
        compaction_interval=_interval,
        overlap_size=1,
        token_threshold=_compaction_threshold,
        event_retention_size=_retention,
    )

return App(
    name="rlm_adk",
    root_agent=orchestrator,
    plugins=resolved_plugins,
    events_compaction_config=compaction_config,
)
```

**Considerations:**
- The compaction summarizer uses the root agent's `canonical_model`, which means it makes an additional LLM call. For Gemini models this is cheap but adds latency at the end of each invocation.
- Compaction runs *after* all agent events are yielded (confirmed at `runners.py` line 554-558), so it does not affect the in-flight reasoning loop.
- The `CompactedEvent` is appended to the session via `session_service.append_event`, which means our WAL-pragma'd SQLite handles it correctly.
- RLM-ADK's depth-scoped state keys (e.g., `iteration_count@d1`) are stored in `state_delta`, not in event content. Compaction summarizes event *content*, not state deltas, so depth-scoped state is unaffected.
- However, REPL code/output stored as event content (tool call args and tool responses) IS subject to compaction. This is desirable for multi-turn sessions but could lose detail if a user wants to inspect earlier iterations.

**Risk:** Compaction could summarize away REPL code blocks that the model later needs to reference. Mitigation: set `event_retention_size` high enough to keep the current invocation's events intact (20+ events). The token threshold approach is safer than the invocation-count approach for RLM because a single invocation can generate many events.

---

### 1.5 Artifact Services Accept Dict Representations of `types.Part` (closes #2886)

**What changed:** Artifact services now accept dictionary representations of `types.Part` in addition to actual `types.Part` objects. This means callers can pass `{"text": "hello"}` instead of `types.Part(text="hello")`.

**Impact on `rlm_adk/artifacts.py`:**

Our artifact helpers (`save_repl_output`, `save_repl_code`, `save_final_answer`, etc.) all construct proper `types.Part` objects before calling `artifact_service.save_artifact()`:

- `save_repl_output` (line 99): `types.Part.from_bytes(data=..., mime_type=...)`
- `save_repl_code` (line 222): `types.Part(text=content)`
- `save_final_answer` (line 362): `types.Part.from_bytes(data=..., mime_type=...)`
- `save_binary_artifact` (line 401): `types.Part.from_bytes(data=data, mime_type=mime_type)`

**Conclusion:** No changes needed. Our code already uses proper `types.Part` construction. The dict support is a convenience for external callers and does not affect our usage pattern. However, if we ever add a REPL skill that lets user code save artifacts, the dict acceptance provides a more ergonomic API:

```python
# In REPL code, a user could do:
await artifact_service.save_artifact(
    ..., artifact={"text": "my result"}  # Now works in v1.27.0
)
```

This is a minor quality-of-life improvement, not actionable now.

---

### 1.6 GetSessionConfig Passthrough from Runner to Session Service

**What changed:** The Runner now passes `GetSessionConfig` through to the session service when retrieving sessions, allowing callers to control event filtering (e.g., `num_recent_events`, `after_timestamp`) at the Runner level.

**Impact on `create_rlm_runner()`:**

Currently, `Runner.run_async()` calls `_get_or_create_session()` which calls `session_service.get_session()` without any `config` parameter (confirmed at `runners.py` line 374-376). The passthrough likely applies to callers who interact with `runner.session_service.get_session()` directly.

**Potential enhancement for session resumption:**

RLM-ADK sessions can accumulate thousands of events. When resuming a session (e.g., `adk run --resume`), loading ALL events is wasteful if the user only needs recent context. With `GetSessionConfig` passthrough:

```python
# When resuming, only load recent events:
session = await runner.session_service.get_session(
    app_name="rlm_adk",
    user_id="user",
    session_id="...",
    config=GetSessionConfig(num_recent_events=100),
)
```

This is a moderate improvement for long-running sessions. Currently not wired through our API surface.

---

### 1.7 Durable Runtime Support (`ResumabilityConfig`)

**What changed:** ADK now supports durable/resumable invocations through `ResumabilityConfig` on `App`. When enabled:
- The Runner can accept an `invocation_id` to resume a previous invocation.
- Long-running tool calls can pause execution and resume later.
- The Runner validates resumability config before allowing resume attempts.

**Confirmed in source** (`app.py` lines 41-59, `runners.py` lines 506-521):

```python
class ResumabilityConfig(BaseModel):
    is_resumable: bool = False

# In run_async():
if invocation_id:
    if not self.resumability_config or not self.resumability_config.is_resumable:
        raise ValueError("invocation_id provided but app is not resumable.")
    invocation_context = await self._setup_context_for_resumed_invocation(...)
```

**Impact on RLM-ADK:**

Currently, `create_rlm_app()` does NOT pass `resumability_config` to `App()`. This means resumability is disabled.

**Potential value for RLM:**
- RLM invocations can be long (10+ minutes with recursive dispatch). If the process crashes mid-invocation, all state accumulated by the orchestrator's `EventActions(state_delta=...)` yields is already persisted in SQLite. But the REPL state (variables, imports) is lost.
- Resumability could help if a transient Gemini API outage crashes the invocation after 8 minutes of work. The Runner could resume from the last event.

**Caveats:**
1. "Any temporary / in-memory state will be lost upon resumption" (from `ResumabilityConfig` docstring). For RLM-ADK, this means the `LocalREPL` environment, dispatch closures, and all REPL globals (including `user_ctx`) would be lost. Resumption would restart from the last persisted event but with an empty REPL.
2. Tool calls must be idempotent. Our `REPLTool` is NOT idempotent -- re-executing the same code block could have side effects (network calls, file writes).
3. The `persistent` flag on `RLMOrchestratorAgent` already provides session-to-session REPL persistence, but that's for multi-turn sessions, not mid-invocation crash recovery.

**Conclusion:** Durable runtime is not immediately useful for RLM-ADK due to REPL state loss and non-idempotent tool calls. File as a future investigation when ADK adds richer state serialization or when RLM-ADK implements REPL state checkpointing.

---

## 2. Proposed Enhancements (Priority Order)

### Enhancement A: Wire EventCompaction into `create_rlm_app()`

**Files:** `rlm_adk/agent.py` (line 524)
**Effort:** S (Small) -- ~15 lines of code, env-var gated
**Impact:** High -- prevents context window overflow in multi-turn sessions
**Risk:** Low -- opt-in via env var, compaction runs post-invocation

Add `RLM_COMPACTION_TOKEN_THRESHOLD` and `RLM_COMPACTION_RETENTION` env vars. When the threshold is set, create an `EventsCompactionConfig` and pass it to `App()`. Default off (threshold=0).

### Enhancement B: Expose `GetSessionConfig` in Session Resume Flow

**Files:** `rlm_adk/agent.py`, potentially `rlm_adk/services.py`
**Effort:** S (Small) -- add optional `GetSessionConfig` parameter to `create_rlm_runner()`
**Impact:** Medium -- improves session load time for long-running sessions
**Risk:** Low -- additive parameter, backward compatible

### Enhancement C: Add `auto_create_session=True` to `create_rlm_runner()`

**Files:** `rlm_adk/agent.py` (line 625)
**Effort:** S (Small) -- one parameter change
**Impact:** Low -- convenience improvement for programmatic callers
**Risk:** Low -- behavioral change but callers already create sessions explicitly

---

## 3. Risk Assessment

### AR-CRIT-001 Impact Summary

| Change | Affects AR-CRIT-001? | Risk Level | Detail |
|--------|---------------------|------------|--------|
| Row-level locking | No | None | Storage-layer optimization only |
| Temp-state visibility | **Audit required** | Low | Does NOT enable simplification; could introduce subtle bugs if someone adds `temp:` keys in dispatch closures thinking they'll persist |
| Session validation | No | None | Runner-level change, transparent to agents |
| EventCompaction | **Audit required** | Low | Compaction appends events via `session_service.append_event()` which goes through delta tracking correctly |
| Artifact dict support | No | None | Our code uses proper `types.Part` objects |
| GetSessionConfig | No | None | Read-path change only |
| Durable runtime | Not applicable | None | Not enabled |

### Key Risk: Temp-State Misuse

The temp-state visibility fix could tempt future developers to use `temp:` keys in dispatch closures as a "safe" state channel. This would be WRONG because:

1. `temp:` keys are stripped from `event.actions.state_delta` before persistence (`base_session_service.py` line 119-123).
2. Dispatch closures don't have access to delta-tracked state (`CallbackContext` / `ToolContext`).
3. Any `temp:` write via `ctx.session.state["temp:key"] = value` bypasses delta tracking entirely.

**Mitigation:** Add a comment in `dispatch.py` at line 199:

```python
# Local accumulators -- replaces ctx.session.state reads (AR-CRIT-001)
# NOTE: Do NOT use temp: prefix keys as an alternative. Even with ADK v1.27.0
# temp-state visibility fix, dispatch closures lack delta-tracked state access.
# The accumulator + flush_fn pattern is the ONLY correct approach here.
```

---

## 4. Opportunity Ratings

| Change | Effort | Impact | Risk | Recommendation |
|--------|--------|--------|------|----------------|
| Row-level locking | N/A (automatic) | Low (single-session usage) | None | No action needed |
| Temp-state visibility | N/A | None (no simplification) | Low | Add warning comment in dispatch.py |
| Session validation | N/A (automatic) | Low (better error messages) | None | No action needed |
| **EventCompaction** | **S** | **High** | **Low** | **Implement (Enhancement A)** |
| Artifact dict support | N/A | None (already using Part objects) | None | No action needed |
| GetSessionConfig | S | Medium | Low | Implement when session resume is prioritized |
| Durable runtime | M | Low (REPL state loss) | Medium | Defer until REPL checkpointing |

---

## 5. Files Referenced

| File | Lines | Relevance |
|------|-------|-----------|
| `rlm_adk/agent.py` | 119-126, 524, 600-630 | WAL pragmas, App creation, Runner creation |
| `rlm_adk/dispatch.py` | 199-206, 783-812 | AR-CRIT-001 accumulators, flush_fn |
| `rlm_adk/orchestrator.py` | 324-432 | State delta yields, initial state setup |
| `rlm_adk/artifacts.py` | 99, 222, 362, 401 | Part construction in save helpers |
| `rlm_adk/tools/repl_tool.py` | 277-281 | flush_fn integration |
| `rlm_adk/plugins/observability.py` | 60-64, 272-306 | Accumulator pattern in on_event_callback |
| `rlm_adk/state.py` | 1-194 | All state key constants |
| `rlm_adk/services.py` | 22-38 | CLI service registry |
| `.venv/.../sqlite_session_service.py` | 360-453, 455-464 | append_event, _get_db_connection |
| `.venv/.../base_session_service.py` | 105-134 | _trim_temp_delta_state, append_event base |
| `.venv/.../state.py` | 20-81 | State class, delta tracking |
| `.venv/.../runners.py` | 452-562 | run_async, compaction integration |
| `.venv/.../apps/app.py` | 63-152 | EventsCompactionConfig, App, ResumabilityConfig |
| `.venv/.../apps/compaction.py` | 170-435 | Sliding window + token threshold compaction |
