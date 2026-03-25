# BUG-014: Child set_model_response telemetry reports depth=0

**Status**: Open
**Severity**: Medium (telemetry correctness; cascading impact on trace summary queries)
**Discovered By**: `skill_arch_test` e2e fixture (8-call depth=2 fixture)
**Date**: 2026-03-25

---

## Evidence

From the telemetry dump of the passing `skill_arch_test` fixture, `tool_call` rows for child agents at depth=1 and depth=2 incorrectly report `depth=0`:

```
  tool_call    tool=set_model_response     agent=child_reasoning_d2             d=0 llm_calls=None
  tool_call    tool=set_model_response     agent=child_reasoning_d1             d=0 llm_calls=None
  tool_call    tool=set_model_response     agent=child_orchestrator_d1          d=0 llm_calls=None
```

Meanwhile, `model_call` rows for the **same agents** correctly show their depth:

```
  model_call   tool=None                   agent=child_reasoning_d1             d=1 llm_calls=None
  model_call   tool=None                   agent=child_reasoning_d2             d=2 llm_calls=None
```

The `agent_name` column correctly identifies these as child agents (`child_reasoning_d1`, `child_reasoning_d2`), proving the plugin fires for child agents. The depth is correct for `model_call` but wrong for `tool_call`.

This bug was previously cataloged as **Gap E2** in `tests_rlm_adk/REVIEW_skill_arch_e2e_gaps.md`:

> **Gap E2**: The `telemetry` row for `tool_call:set_model_response` at child depth shows `depth=0` instead of expected `depth=1`. The showboat demo shows: `tool_call | set_model_response | child_reasoning_d1 | 0`. This is likely because the child's `set_model_response` does not read the depth-scoped `current_depth` key. No assertion catches this incorrect depth value.

---

## Root Cause Analysis

### How `model_call` gets depth correctly (line 938)

In `SqliteTracingPlugin.before_model_callback` (sqlite_tracing.py, line 938), depth is resolved from the **agent object** attached to the invocation context:

```python
# sqlite_tracing.py:930-938
inv_ctx = getattr(callback_context, "_invocation_context", None)
agent = getattr(inv_ctx, "agent", None)

# Compute depth/fanout/parent from agent attrs
depth = self._coerce_int(getattr(agent, "_rlm_depth", 0))
```

The `_rlm_depth` attribute is set on the reasoning agent by the orchestrator at construction time (orchestrator.py, line 358):

```python
object.__setattr__(_ra, "_rlm_depth", self.depth)
```

This works correctly because every child reasoning agent has `_rlm_depth` stamped by its parent orchestrator. The model callback reads it directly from the agent object, bypassing session state entirely.

### How `tool_call` gets depth incorrectly (line 1204)

In `SqliteTracingPlugin.before_tool_callback` (sqlite_tracing.py, line 1204), depth is resolved from the **tool object's** `_depth` attribute:

```python
# sqlite_tracing.py:1204
tool_depth = self._coerce_int(getattr(tool, "_depth", 0))
```

This attribute (`_depth`) is only set on `REPLTool` instances (repl_tool.py, line 82). It is **not** set on ADK's internal `set_model_response` tool (which is `SetModelResponseTool`, an ADK framework class that RLM-ADK does not control).

When `getattr(tool, "_depth", 0)` is called on a `SetModelResponseTool` instance, it falls through to the default value of `0`. This is why every `set_model_response` tool_call row gets `depth=0` regardless of which agent called it.

### The asymmetry

| Callback | How depth is resolved | Works for children? |
|---|---|---|
| `before_model_callback` | `agent._rlm_depth` via `callback_context._invocation_context.agent` | Yes -- agent always has `_rlm_depth` |
| `before_tool_callback` | `tool._depth` via `getattr(tool, "_depth", 0)` | Only for `REPLTool` (which sets `_depth`). Fails for `set_model_response` and all other ADK-internal tools |

The tool callback **does** resolve the agent (lines 1214-1215) but only uses it for `fanout_idx`, `parent_depth`, etc. -- it never reads `_rlm_depth` from the agent for the `depth` column.

### The same bug exists in InstrumentationPlugin

The `InstrumentationPlugin` in `instrumented_runner.py` (line 287) has the same bug pattern -- it reads depth from `tool_context.state.get("current_depth", 0)` which reads the **unscoped** `current_depth` key (always the root's value of 0) instead of the depth-scoped `current_depth@d1` or `current_depth@d2` key:

```python
# instrumented_runner.py:287
depth = tool_context.state.get("current_depth", 0)
```

This is the same root cause expressed differently: at child depths, `current_depth` (unscoped) holds the root's value (0), while the child's actual depth is stored in `current_depth@d1` (value=1) or `current_depth@d2` (value=2).

---

## Pertinent Code Objects

| Object/Function | File | Line | Role | Callsite |
|---|---|---|---|---|
| `SqliteTracingPlugin.before_tool_callback` | `rlm_adk/plugins/sqlite_tracing.py` | 1191 | Inserts `tool_call` telemetry row with depth | **BUG SITE**: reads `tool._depth` (line 1204) |
| `SqliteTracingPlugin.before_model_callback` | `rlm_adk/plugins/sqlite_tracing.py` | 915 | Inserts `model_call` telemetry row with depth | **CORRECT**: reads `agent._rlm_depth` (line 938) |
| `REPLTool.__init__` | `rlm_adk/tools/repl_tool.py` | 82 | Sets `self._depth = depth` on REPLTool instances | Only tool that has `_depth` |
| `RLMOrchestratorAgent._run_async_impl` | `rlm_adk/orchestrator.py` | 358 | Sets `_rlm_depth` on reasoning agent | `object.__setattr__(_ra, "_rlm_depth", self.depth)` |
| `InstrumentationPlugin.before_tool_callback` | `tests_rlm_adk/provider_fake/instrumented_runner.py` | 287 | Emits `[PLUGIN:before_tool:...]` tags with depth | **SAME BUG**: reads `tool_context.state.get("current_depth", 0)` |
| `depth_key()` | `rlm_adk/state.py` | 146 | Returns depth-scoped key (`key@dN` for N>0) | Not called by tool callbacks |
| `CURRENT_DEPTH` | `rlm_adk/state.py` | 14 | State key constant `"current_depth"` | In `DEPTH_SCOPED_KEYS` -- requires `depth_key()` for children |
| `test_skill_arch_e2e` | `tests_rlm_adk/test_provider_fake_e2e.py` | 952 | Asserts depth distribution of `set_model_response` | Lines 953-955: asserts depths 0, 1, 2 are present |

---

## Proposed Fix

### Primary fix: `SqliteTracingPlugin.before_tool_callback` (sqlite_tracing.py)

Change the depth resolution in `before_tool_callback` to use the same pattern as `before_model_callback` -- read `_rlm_depth` from the agent on the invocation context, falling back to `tool._depth` for backward compatibility with REPLTool:

```python
# BEFORE (line 1204):
tool_depth = self._coerce_int(getattr(tool, "_depth", 0))

# AFTER:
inv_ctx = getattr(tool_context, "_invocation_context", None)
agent = getattr(inv_ctx, "agent", None)
tool_depth = self._coerce_int(
    getattr(agent, "_rlm_depth", None)
    or getattr(tool, "_depth", 0)
)
```

Note: the `inv_ctx` and `agent` variables are already resolved later in the same method (lines 1214-1215). The fix should either move that resolution earlier or duplicate the two `getattr` calls. Moving the existing block (lines 1214-1223) above line 1204 is the cleaner approach, then reusing the `agent` variable for depth.

### Secondary fix: `InstrumentationPlugin.before_tool_callback` (instrumented_runner.py)

Apply the same pattern:

```python
# BEFORE (line 287):
depth = tool_context.state.get("current_depth", 0)

# AFTER:
inv_ctx = getattr(tool_context, "_invocation_context", None)
agent = getattr(inv_ctx, "agent", None) if inv_ctx else None
depth = getattr(agent, "_rlm_depth", None)
if depth is None:
    depth = tool_context.state.get("current_depth", 0)
```

### Verification

The test at `tests_rlm_adk/test_provider_fake_e2e.py:952-955` already asserts that depths 0, 1, and 2 are all present in `set_model_response` telemetry events. This test currently **should fail** but may pass due to reading from a different source (the `InstrumentationPlugin` tags rather than the SQLite telemetry table). After the fix, the SQLite telemetry table itself will have correct depth values, making the `_build_trace_summary_from_telemetry` aggregation queries correct.

---

## Impact

### Direct impact

1. **`max_depth_reached` in traces table**: The `_build_trace_summary_from_telemetry()` method (line 772-779) computes `MAX(depth) FROM telemetry`. Since `set_model_response` tool_call rows all have `depth=0`, the max depth is computed only from `model_call` rows. This happens to still be correct because model_call rows have the right depth -- but if a leaf agent only calls `set_model_response` (no model_call row), its depth would be invisible.

2. **`child_dispatch_count` in traces table**: The query at line 782-790 counts `tool_call` rows with `depth > 0`. Since child `set_model_response` rows have `depth=0`, they are excluded from this count. This undercounts child dispatches.

3. **Dashboard and telemetry queries**: Any downstream query filtering `telemetry WHERE event_type = 'tool_call' AND depth > 0` will miss child `set_model_response` events entirely, giving an incomplete picture of child agent activity.

4. **Existing test assertions**: The assertions at `test_provider_fake_e2e.py:953-955` that check `1 in smr_depths` and `2 in smr_depths` read from `InstrumentationPlugin` emit tags, not the SQLite table. If these assertions are later changed to read from SQLite (which is the authoritative telemetry store), they will fail.

### No impact on functional correctness

This bug is telemetry-only. It does not affect agent execution, `set_model_response` behavior, child dispatch, or result propagation. The system runs correctly; only the observability layer reports wrong depth values for tool_call events.

---

## Fix Applied (2026-03-25)

**Status**: Closed

### Changes

#### 1. `SqliteTracingPlugin.before_tool_callback` (sqlite_tracing.py, lines 1214-1222)

Moved agent resolution (`inv_ctx`/`agent` getattr chain) above depth computation. Depth now reads `agent._rlm_depth` first (set by orchestrator at construction time), falling back to `tool._depth` for REPLTool backward compatibility:

```python
# Resolve agent first (moved above depth resolution for BUG-014)
inv_ctx = getattr(tool_context, "_invocation_context", None)
agent = getattr(inv_ctx, "agent", None)

# BUG-014 fix: resolve depth from agent._rlm_depth (set by
# orchestrator at construction), falling back to tool._depth
# for REPLTool backward compat.  Matches before_model_callback.
tool_depth = self._coerce_int(
    getattr(agent, "_rlm_depth", None)
    or getattr(tool, "_depth", 0)
)
```

#### 2. `InstrumentationPlugin.before_tool_callback` (instrumented_runner.py, lines 287-292)

Same pattern — resolve depth from `agent._rlm_depth` via invocation context, falling back to `tool_context.state.get("current_depth", 0)`:

```python
# BUG-014 fix: resolve depth from agent._rlm_depth (matches
# SqliteTracingPlugin.before_model_callback pattern), falling
# back to state for backward compat.
inv_ctx = getattr(tool_context, "_invocation_context", None)
_agent = getattr(inv_ctx, "agent", None) if inv_ctx else None
depth = getattr(_agent, "_rlm_depth", None)
if depth is None:
    depth = tool_context.state.get("current_depth", 0)
```

### Tests Added

3 new tests in `TestSetModelResponseDepth` class (`test_skill_arch_e2e.py`):

| Test | Assertion |
|---|---|
| `test_smr_depth_nonzero_exists` | At least one `set_model_response` tool_call row has `depth > 0` |
| `test_smr_depth2_exists` | A `set_model_response` row exists with `depth=2` (grandchild) |
| `test_smr_depth_distribution` | Depths `{0, 1, 2}` are all present in `set_model_response` rows |

### RED/GREEN Evidence

**RED (before fix):**
```
FAILED test_smr_depth_nonzero_exists
AssertionError: BUG-014: All set_model_response tool_call depths are 0.
Depths: [0, 0, 0, 0, 0]. Child/grandchild SMR calls should have depth > 0.
```

**GREEN (after fix):**
```
3 passed  (TestSetModelResponseDepth)
21 passed (full test_skill_arch_e2e.py suite, no regressions)
```

### Showboat Demo

```markdown
# BUG-014: Fix child set_model_response depth=0 telemetry

*2026-03-25T13:18:47Z by Showboat 0.6.1*
<!-- showboat-id: bfdb625b-e07e-4d9a-ab9a-daa5d9cd1934 -->

BUG-014: SqliteTracingPlugin.before_tool_callback resolved depth from tool._depth, which is only set on REPLTool instances. For ADK-internal tools like set_model_response (SetModelResponseTool), getattr(tool, "_depth", 0) always returns 0. Fix: resolve depth from agent._rlm_depth via invocation context (same pattern as before_model_callback), falling back to tool._depth for REPLTool backward compat. Same fix applied to InstrumentationPlugin.

\```bash
grep -n "BUG-014" rlm_adk/plugins/sqlite_tracing.py
\```

\```output
1214:            # Resolve agent first (moved above depth resolution for BUG-014)
1218:            # BUG-014 fix: resolve depth from agent._rlm_depth (set by
\```

\```bash
grep -n "BUG-014" tests_rlm_adk/provider_fake/instrumented_runner.py
\```

\```output
287:            # BUG-014 fix: resolve depth from agent._rlm_depth (matches
\```

The fix moves agent resolution (inv_ctx/agent getattr chain) above the depth computation, then reads agent._rlm_depth first. The _rlm_depth attribute is stamped on every child reasoning agent by its parent orchestrator at construction time, so it is always accurate. Falls back to tool._depth (set only on REPLTool) for backward compat.

\```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py::TestSetModelResponseDepth -q -m provider_fake 2>/dev/null | tail -1 | sed "s/ in [0-9.]*s//"
\```

\```output
3 passed
\```

\```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py -q -m provider_fake 2>/dev/null | tail -1 | sed "s/ in [0-9.]*s//"
\```

\```output
21 passed
\```
```
