# CURRENT_DEPTH Fix and Depth-Scoping Cleanup

> Generated 2026-03-20 from three-agent analysis (2 explorers + 1 planner).
> Driven by reward-hacking review of `lineage_completion_planes` fixture that
> surfaced `current_depth=0` for depth-1 children in `_rlm_state` snapshot.

---

## Bug Summary

`CURRENT_DEPTH` is written to session state with `depth_key(CURRENT_DEPTH, self.depth)` at `orchestrator.py:372`, producing scoped keys like `current_depth@d1`. But `CURRENT_DEPTH` is **not** in `DEPTH_SCOPED_KEYS` (`state.py:143-157`), so `REPLTool`'s snapshot builder (`repl_tool.py:203-204`) always reads the **unscoped** `"current_depth"` key — which is the parent's value (0). At depth 0 this happens to be correct (`depth_key` returns the bare key when depth=0). At depth > 0, REPL code sees the parent's stale value instead of the child's actual depth.

Evidence: `repl_capture_lineage.json` shows `_rlm_state.current_depth=0` for both depth-1 children, while `_rlm_state._rlm_depth=1` (the lineage injection we added) is correct.

---

## Part A: The CURRENT_DEPTH Fix (Critical)

### Root Cause

- **Write path (correct)**: `orchestrator.py:372` writes `depth_key(CURRENT_DEPTH, self.depth): self.depth`. At depth 1 this produces `"current_depth@d1": 1`.
- **Read path (buggy)**: `repl_tool.py:203-204` iterates `EXPOSED_STATE_KEYS` and checks `if key in DEPTH_SCOPED_KEYS` to decide whether to apply `depth_key()`. Since `CURRENT_DEPTH` is not in `DEPTH_SCOPED_KEYS`, it reads the bare `"current_depth"` key — the parent's value (0).

### Fix

#### `rlm_adk/state.py` (lines 143-159)

Add `CURRENT_DEPTH` to `DEPTH_SCOPED_KEYS`. Remove `MESSAGE_HISTORY` (dead key, see Part B). Update comment.

```python
DEPTH_SCOPED_KEYS: set[str] = {
    CURRENT_DEPTH,          # <-- ADD (was missing, causing depth>0 to read parent's value)
    # MESSAGE_HISTORY,      # <-- REMOVE (dead key, never used with depth_key())
    ITERATION_COUNT,
    FINAL_RESPONSE_TEXT,
    LAST_REPL_RESULT,
    SHOULD_STOP,
    REPL_SUBMITTED_CODE,
    REPL_SUBMITTED_CODE_PREVIEW,
    REPL_SUBMITTED_CODE_HASH,
    REPL_SUBMITTED_CODE_CHARS,
    REPL_EXPANDED_CODE,
    REPL_EXPANDED_CODE_HASH,
    REPL_SKILL_EXPANSION_META,
    REPL_DID_EXPAND,
}
# NOTE: Only iteration-local keys that need independent state per depth
# level are included. CURRENT_DEPTH is included because child
# orchestrators write depth_key(CURRENT_DEPTH, depth) and REPLTool
# must read the depth-scoped value. Global observability keys are excluded.
```

#### `tests_rlm_adk/test_repl_state_snapshot.py`

**Line ~164-186** (`test_snapshot_depth_scoping`): The test seeds `CURRENT_DEPTH: depth` at the unscoped key. After the fix, REPLTool reads `depth_key(CURRENT_DEPTH, 2)` = `"current_depth@d2"`. Change seeding:

```python
# Before (buggy):
tc = _make_tool_context({
    scoped_key: fake_repl_result,
    CURRENT_DEPTH: depth,           # unscoped
    APP_MAX_ITERATIONS: 30,
})

# After (correct):
tc = _make_tool_context({
    scoped_key: fake_repl_result,
    depth_key(CURRENT_DEPTH, depth): depth,   # depth-scoped
    APP_MAX_ITERATIONS: 30,
})
```

The assertion `snapshot.get(CURRENT_DEPTH) == depth` remains correct — the snapshot builder uses the unscoped key name for the clean API (`repl_tool.py:207`).

**Line ~185**: Update comment from `"CURRENT_DEPTH is not depth-scoped"` to `"CURRENT_DEPTH IS depth-scoped (in DEPTH_SCOPED_KEYS)"`.

#### No fixture changes needed

- Depth-0 assertions remain correct (`depth_key("current_depth", 0) == "current_depth"`)
- Child fixture code that prints `current_depth` will now print the correct value, but existing assertions only check depth-0 values
- `expected_state.current_depth: 0` reads the unscoped key (root's value), still correct

### Impacted Locations (read-only verification, no changes needed)

| File | Lines | Notes |
|------|-------|-------|
| `orchestrator.py` | 372 | Write path — already correct (uses `depth_key()`) |
| `repl_tool.py` | 203-207 | Read path — automatically fixed by adding to `DEPTH_SCOPED_KEYS` |
| `sqlite_tracing.py` | 73, 114 | `_CURATED_EXACT` captures unscoped key for session_state_events. `_parse_key()` at line 47 already handles `@dN` suffixes correctly. No change needed. |
| `plugins/step_mode.py` | ~36-37 | Reads depth from agent name regex, NOT from state. Unaffected. |
| `lineage_completion_planes.json` | 26, 59, 160 | Child REPL code prints `current_depth`; will now show correct values. No assertion changes needed. |
| `fake_recursive_ping.json` | 18, 50, 83, 196 | Same — layers 1-2 will now show correct depth values. |

---

## Part B: Dead Key Cleanup — Remove MESSAGE_HISTORY

`MESSAGE_HISTORY = "message_history"` is in `DEPTH_SCOPED_KEYS` but **never used** with `depth_key()` anywhere in production code. Legacy from pre-collapsed orchestrator (ADK's `include_contents='default'` replaced it entirely).

### Fix

#### `rlm_adk/state.py`

- **Line 144**: Remove `MESSAGE_HISTORY` from `DEPTH_SCOPED_KEYS`
- **Line 20**: Keep the constant definition for now (separate cleanup if desired)

---

## Part C: Legacy Key Audit Against the Refactor Vision

The refactor plan (`lineage_control_plane_REFACTOR.md`) says session state should ONLY contain:

1. **Control plane**: `CURRENT_DEPTH`, `ITERATION_COUNT`, `SHOULD_STOP`, request IDs, app limits
2. **Prompt-template inputs**: `ROOT_PROMPT`, `REPO_URL`, `DYN_SKILL_INSTRUCTION`, user context keys, enabled skills
3. **REPL continuity**: `LAST_REPL_RESULT`
4. **Final root completion text**: `FINAL_RESPONSE_TEXT`
5. **Step-mode state**

### Keys that violate this boundary

| Key | Category | Current Usage | Recommendation |
|-----|----------|---------------|----------------|
| `OBS_TOTAL_INPUT_TOKENS` | Lineage | ObservabilityPlugin writes via callback_context.state | **Keep for now** — run-summary counter. Already captured authoritatively in telemetry table. Long-term: remove from state. |
| `OBS_TOTAL_OUTPUT_TOKENS` | Lineage | Same | Same |
| `OBS_TOTAL_CALLS` | Lineage | Same | Same |
| `OBS_FINISH_*_COUNT` | Lineage | Per non-STOP finish reason | **Keep for now** — lightweight. Already in telemetry. |
| `OBS_REWRITE_*` | Per-tool lineage | REPLTool writes to unscoped keys | **Remove state writes** (see Part D) |
| `OBS_TOOL_INVOCATION_SUMMARY` | Lineage | ObservabilityPlugin before_tool_callback | **Keep for now** |
| `OBS_REASONING_RETRY_*` | Lineage | Orchestrator writes once per invocation | **Keep for now** |
| `CACHE_*` keys | Dead | No writers in production code | **Document as unimplemented** |
| `MIGRATION_*` keys | Dead | Never used | **Document as dead** |
| `ARTIFACT_*` tracking | Borderline | Written by artifact save utilities | **Keep** — small working state |

### Action for this PR

No obs:* key removals for correctness. Add a block comment in `state.py` above the observability section (~line 51):

```python
# Observability Keys (session-scoped)
# NOTE: These global accumulator keys are candidates for migration to the
# lineage plane (SQLite telemetry / agent-local attrs) per the three-plane
# refactor vision (prompts/lineage_control_plane_REFACTOR.md). They remain
# in state for now as lightweight run-summary counters. sqlite_tracing
# already captures authoritative values directly, so these state keys are
# redundant for telemetry but still used by ObservabilityPlugin's
# after_agent_callback re-persistence workaround.
```

---

## Part D: OBS_REWRITE_* State Write Collision

### Problem

`OBS_REWRITE_COUNT`, `OBS_REWRITE_TOTAL_MS`, `OBS_REWRITE_FAILURE_COUNT`, `OBS_REWRITE_FAILURE_CATEGORIES` are written by each `REPLTool` instance to **unscoped** state keys (`repl_tool.py:234-244`). Each REPLTool maintains instance-local counters (`self._rewrite_count` etc.) and writes cumulative values to `tool_context.state`. When children have their own REPLTool at depth > 0, child writes land in shared session state and overwrite the parent's values. Last writer wins.

### Assessment

- At depth 0, coincidentally correct (parent writes last after all child dispatches)
- No production consumers read these from state
- Telemetry table captures rewrite timing per tool_call row authoritatively
- Tests only print them diagnostically (no hard assertions)

### Fix

#### `rlm_adk/tools/repl_tool.py` (lines ~234-244)

**Remove** the state writes entirely (Option A — preferred):

```python
# Before:
tool_context.state[OBS_REWRITE_COUNT] = self._rewrite_count
tool_context.state[OBS_REWRITE_TOTAL_MS] = round(self._rewrite_total_ms, 3)
# ... failure counters ...

# After: Remove these lines entirely.
# Rewrite count is tracked on self._rewrite_count (instance-local).
# The telemetry table captures rewrite timing per tool_call row.
```

Same treatment for failure counter writes at lines ~240-244.

Remove the now-unused imports: `OBS_REWRITE_COUNT`, `OBS_REWRITE_TOTAL_MS`, `OBS_REWRITE_FAILURE_COUNT`, `OBS_REWRITE_FAILURE_CATEGORIES` from the `from rlm_adk.state import (...)` block.

---

## Part E: Fanout Collision Risk — Document Design Decision

### Current State

`depth_key()` only uses depth, not fanout_idx. The regex at `sqlite_tracing.py:47` (`@d(\d+)(?:f(\d+))?`) supports parsing `@d1f2` patterns, but `depth_key()` only produces `@dN` suffixes.

### Risk

With `RLM_MAX_CONCURRENT_CHILDREN > 1`, sibling children at the same depth write to the same `@dN` scoped keys. Two children at depth 1 with fanout_idx 0 and 1 both write to `"iteration_count@d1"`.

### Assessment: NOT a correctness problem

1. Children run in branch-isolated event streams (`dispatch.py:329-331`)
2. Completion is read from in-memory `_rlm_terminal_completion` attrs, not state keys
3. `session_state_events` rows capture writes as they happen (both writes recorded with timestamps)
4. Parent reads its own `@d0` keys, not children's `@dN` keys

### Action

Add design invariant comment to `state.py` `depth_key()` docstring:

```python
def depth_key(key: str, depth: int = 0) -> str:
    """Return a depth-scoped state key.

    At depth 0 the original key is returned unchanged.
    At depth N > 0 the key is suffixed with ``@dN`` so nested
    reasoning agents operate on independent state.

    Design note: Fanout scoping (``@dNfM``) is NOT implemented.
    Sibling children at the same depth share the ``@dN`` namespace.
    This is acceptable because:
    - Children run in branch-isolated event streams (dispatch.py)
    - Completion is read from in-memory agent attrs, not state keys
    - sqlite_tracing._parse_key() supports @dNfM parsing for future
      expansion if needed
    """
```

---

## Part F: Keep `_rlm_depth` Lineage Injection

After the CURRENT_DEPTH fix, `_rlm_state["current_depth"]` and `_rlm_state["_rlm_depth"]` will show the **same value** at all depths. They have different provenance paths:

- `current_depth`: Flows through session state event pipeline (`EventActions(state_delta=...)` → Runner → `tool_context.state`)
- `_rlm_depth`: Set from `self._depth` on the REPLTool instance (constructor argument from orchestrator)

**Recommendation: KEEP `_rlm_depth`**

1. **Different failure modes**: If the state event pipeline breaks, `current_depth` could be stale while `_rlm_depth` remains correct
2. **Non-state provenance**: Proves the REPLTool was constructed at the claimed depth, independent of what any state key says
3. **Zero overhead**: Single dict assignment per tool call

### Action

Update comment at `repl_tool.py:209-213`:

```python
# Inject runtime lineage metadata from the tool/agent for
# non-circular test verification. After the CURRENT_DEPTH fix,
# _rlm_depth and current_depth show the same value, but they
# have independent provenance paths: _rlm_depth comes from the
# REPLTool constructor (set by orchestrator), while current_depth
# flows through the session state event pipeline. Keeping both
# enables cross-check diagnostics when one path fails.
```

---

## Part G: Documentation Updates

### `rlm_adk_docs/dispatch_and_state.md`

- Update `CURRENT_DEPTH` row to mark as depth-scoped
- Remove `MESSAGE_HISTORY` row (dead key)

### `tests_rlm_adk/test_step_mode_plugin.py`

- Change `"current_depth": 0` at lines 57, 79 to `"current_depth": 999` with comment `# decoy — step_mode reads depth from agent name, not state`
- Documentation-quality improvement, not correctness fix

---

## Implementation Sequence

1. **`rlm_adk/state.py`** — Add `CURRENT_DEPTH` to `DEPTH_SCOPED_KEYS`, remove `MESSAGE_HISTORY`, add design comments to `depth_key()` and obs keys section
2. **`rlm_adk/tools/repl_tool.py`** — Remove `OBS_REWRITE_*` state writes, update lineage injection comment
3. **`tests_rlm_adk/test_repl_state_snapshot.py`** — Fix `test_snapshot_depth_scoping` to seed depth-scoped CURRENT_DEPTH key, update line 185 comment
4. **`tests_rlm_adk/test_step_mode_plugin.py`** — Change depth state values to decoy 999
5. **`rlm_adk_docs/dispatch_and_state.md`** — Table updates
6. **Run tests**: `.venv/bin/python -m pytest tests_rlm_adk/` — verify no regressions

### Why existing tests pass without fixture changes

- Depth-0 behavior is unchanged (`depth_key("current_depth", 0) == "current_depth"`)
- Child fixture code that prints `current_depth` will now print the correct value, but existing assertions only check depth-0 values
- `expected_state.current_depth: 0` reads the unscoped key (root's value), still correct
- The `lineage_completion_planes.json` `obs:total_calls: 9` and `obs:total_input_tokens >= 2000` thresholds (tightened in the reward-hacking fix) are unaffected

### Potential Challenges

1. **`test_repl_state_snapshot.py`** is the only test that seeds `CURRENT_DEPTH` at depth > 0 — needs the scoped seeding fix
2. **`OBS_REWRITE_*` removal** — `test_rlm_state_snapshot_audit.py` and `test_state_accuracy_diagnostic.py` reference `obs:rewrite_count` but only for diagnostic printing (no hard assertions). Safe to remove.
3. **Session state persistence** — No migration concern. New `"current_depth@dN"` keys don't collide with existing `"current_depth"`.

---

## Critical Files

| File | Changes |
|------|---------|
| `rlm_adk/state.py` | Add CURRENT_DEPTH to DEPTH_SCOPED_KEYS, remove MESSAGE_HISTORY, add comments |
| `rlm_adk/tools/repl_tool.py` | Remove OBS_REWRITE_* state writes, update lineage comment |
| `tests_rlm_adk/test_repl_state_snapshot.py` | Fix depth-scoped seeding + comment |
| `tests_rlm_adk/test_step_mode_plugin.py` | Decoy depth values |
| `rlm_adk_docs/dispatch_and_state.md` | Table updates |
| `rlm_adk/plugins/sqlite_tracing.py` | Verification only — `_parse_key` handles @dN correctly, no change needed |
