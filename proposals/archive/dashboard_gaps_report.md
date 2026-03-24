# RLM Live Dashboard Gaps Report

**Date**: 2026-03-18
**Session**: `7136675d-3c3f-47ae-aa5a-f33a9dfa502d`
**Replay**: `tests_rlm_adk/replay/recursive_ping.json`
**Trace**: `5209b063e3e949eab6fb1d800e9784a9`

---

## Executive Summary

The live dashboard has **14 distinct gaps** across 5 categories: state capture, telemetry completeness, display correctness, REPL visibility, and trace lifecycle. The root causes trace to two systemic issues: (1) tool calls at depths 0-3 never finalize in telemetry, and (2) session state events are only captured at depth 0, leaving child agents invisible in the state viewer.

---

## GAP-01: REPL Submitted Code Not Visible in State Keys

**Severity**: Critical
**Category**: State Capture

The dashboard shows `repl_submitted_code (~0 tok)` for all agents. The model's submitted Python code is not viewable anywhere in the state context viewer.

**Root cause**: In the current session, `repl_submitted_code` is never written to `session_state_events`. The `REPLTool` writes via `tool_context.state[depth_key(REPL_SUBMITTED_CODE, depth)]`, but for depths 0-3 the tool call never completes (see GAP-06), so these state writes may not be flushed to the SQLite tracing plugin. Historical sessions that ran to full completion DO have these events (verified: 17 events across other sessions).

**Evidence**:
```
SELECT COUNT(*) FROM session_state_events
WHERE trace_id='5209b063...' AND state_key='repl_submitted_code'
→ 0 rows
```

**Expected**: Each agent's submitted code should appear as a state event with the full code text, viewable by clicking the `repl_submitted_code` chip.

---

## GAP-02: All State Keys Show ~0 tok for Child Agents (Depths 1-4)

**Severity**: Critical
**Category**: State Capture

Every state key chip for child agents (`final_answer@d1`, `last_repl_result@d1`, `reasoning_thought_text@d1`, etc.) shows `~0 tok`. The entire state panel for children is effectively empty.

**Root cause**: `session_state_events` contains **zero rows at depth > 0**. State writes via `callback_context.state` and `tool_context.state` in child agents (workers running inside `ParallelAgent`) are not being captured by the `SqliteTracingPlugin`.

**Evidence**:
```
Depth 0: 8 state keys (enabled_skills, iteration_count, obs:*, reasoning_*, request_id)
Depth 1: (none)
Depth 2: (none)
Depth 3: (none)
Depth 4: (none)
```

**Likely cause**: Workers run in isolated invocation contexts under `ParallelAgent`. The `SqliteTracingPlugin` may only subscribe to state changes on the root agent's session, or worker state mutations use a separate state scope that doesn't propagate to the plugin's event stream.

---

## GAP-03: Agent Display Names Don't Match Actual Agent Names

**Severity**: Medium
**Category**: Display Correctness

The dashboard renders names like `parent_reasoning_agent_0`, `child_reasoning_agent_1`, etc. The actual agent names in telemetry are `reasoning_agent`, `child_reasoning_d1`, `child_reasoning_d2`, etc.

**Root cause**: `_display_agent_name()` in `live_invocation_tree.py:26-28` constructs synthetic names:
```python
def _display_agent_name(invocation: LiveInvocation) -> str:
    prefix = "parent" if invocation.depth == 0 else "child"
    return f"{prefix}_reasoning_agent_{invocation.depth}"
```
This does not match the actual `agent_name` field from telemetry.

**Expected**: Display the actual `invocation.agent_name` or at minimum use the correct naming convention (`reasoning_agent` for depth 0, `child_reasoning_dN` for depth N).

---

## GAP-04: Step Mode Shows Wrong Depth for Paused Agent

**Severity**: High
**Category**: Display Correctness

When step mode pauses on `child_reasoning_d3` (actual depth 3), the dashboard shows `Paused: child_reasoning_d3 @ depth 0`.

**Root cause**: `StepModePlugin.before_model_callback()` reads depth from `callback_context.state.get("current_depth", 0)`. The orchestrator **does** yield `CURRENT_DEPTH: self.depth` in its initial state delta — but only for the **root** orchestrator (depth 0). Workers at depths 1-4 are `LlmAgent` instances under `ParallelAgent`, not orchestrator instances, so they never set `CURRENT_DEPTH`. Additionally, even the root's write to `CURRENT_DEPTH=0` doesn't appear in `session_state_events`:
```
SELECT COUNT(*) FROM session_state_events WHERE state_key='current_depth'
→ 0 events across ALL sessions
```

This means either (a) the initial state delta's `CURRENT_DEPTH` is not captured by `SqliteTracingPlugin`, or (b) the `on_event_callback` filters it out. Either way, the plugin always falls back to `0`.

**Fix**: Extract depth from the agent name via `_depth_from_agent()` pattern (which `live_loader.py` already uses) instead of relying on state. This is simpler and works for all agent types.

---

## GAP-05: REPL Panel Shows No Code/Stdout/Stderr for Depths 0-3

**Severity**: Critical
**Category**: REPL Visibility

The REPL panel (the amber-bordered box next to each child agent card) shows `stdout` and `stderr` action chips, but clicking them shows empty content for all agents except depth 4.

**Root cause**: REPL content is sourced from `tool_events[-1].payload` (which comes from `telemetry.result_payload`). Tool calls at depths 0-3 have `result_payload=NULL` because they never complete (see GAP-06).

**Evidence**:
```
reasoning_agent@d0:  end_time=None  result_payload=NULL  repl_stdout=NULL
child_reasoning_d1@d1: end_time=None  result_payload=NULL  repl_stdout=NULL
child_reasoning_d2@d2: end_time=None  result_payload=NULL  repl_stdout=NULL
child_reasoning_d3@d3: end_time=None  result_payload=NULL  repl_stdout=NULL
child_reasoning_d4@d4: end_time=1773859487.88  result_payload={"stdout":"[DEPTH_LIMIT]..."}  ✓
```

Only the leaf agent (depth 4, which hits `DEPTH_LIMIT` and returns immediately) has complete tool telemetry.

---

## GAP-06: Tool Calls at Depths 0-3 Never Finalize in Telemetry

**Severity**: Critical
**Category**: Telemetry Completeness

Tool call telemetry rows for depths 0-3 have `end_time=NULL`, `duration_ms=NULL`, `call_number=NULL`, `result_preview=NULL`. These rows are created when the tool starts but never updated when it finishes.

**Root cause**: The `execute_code` tool at each depth dispatches a child agent, which itself runs asynchronously. The telemetry instrumentation writes the start row but the completion update either (a) doesn't fire because the tool's async execution is interrupted by the child's parallel agent lifecycle, or (b) the `SqliteTracingPlugin`'s `after_tool_callback` is not invoked for tools that dispatch children.

**Impact**: This is the root cause of GAP-01, GAP-05, and partially GAP-02. Without tool completion, no REPL results, stdout, stderr, or tool state updates are captured in SQLite.

---

## GAP-07: Trace Never Finalizes (status=running, end_time=None, total_calls=0)

**Severity**: High
**Category**: Trace Lifecycle

The trace row shows `status=running`, `end_time=None`, `total_calls=0` even after the replay completes and all 5 agents have finished.

**Root cause**: The `SqliteTracingPlugin`'s trace finalization logic (which updates `end_time`, `status`, `total_calls`) is not triggered. This could be because:
1. The replay `handle.run()` completes but the plugin's shutdown hook isn't called
2. The trace is finalized in an `atexit` handler that hasn't fired
3. The dashboard process keeps running, so the plugin never gets a cleanup signal

**Impact**: Dashboard shows `idle` status badge (because `_normalize_status` treats running+total_calls=0 as idle). Metrics like total_calls=0 are wrong. The actual telemetry shows 5 model calls + 5 tool calls.

---

## GAP-08: Model Call Metrics Not Captured in Traces Summary

**Severity**: Medium
**Category**: Telemetry Completeness

`traces.total_calls=0`, `traces.total_input_tokens=0`, `traces.total_output_tokens=0` despite telemetry having 5 model calls with real token counts (7287 + 4*989 input tokens).

**Related to**: GAP-07. These summary fields are populated during trace finalization.

---

## GAP-09: No Reasoning State Events for Child Agents

**Severity**: High
**Category**: State Capture

`reasoning_visible_output_text` and `reasoning_thought_text` only appear at depth 0. Child agents (depths 1-4) have model outputs captured in `model_outputs.jsonl` but no corresponding state events.

**Evidence**:
```
model_outputs.jsonl:
  child_reasoning_d2: output_len=84 "I'll delegate to a child LLM via execute_code..."
  child_reasoning_d3: output_len=80 "I'll delegate to a child LLM via execute_code..."
  child_reasoning_d4: output_len=51 "I'll delegate to a child LLM and report..."

session_state_events:
  reasoning_visible_output_text@d0: (empty string)
  reasoning_thought_text@d0: "The user is instructing me to..." (285 chars)
  reasoning_*@d1 through d4: (not present)
```

**Root cause**: Worker reasoning callbacks fire within the `ParallelAgent`'s isolated invocation context. State writes via `callback_context.state` in these contexts don't propagate to the main session's state event stream.

---

## GAP-10: `reasoning_visible_output_text@d0` Is Empty Despite Model Output Existing

**Severity**: Medium
**Category**: State Capture

The root agent's `reasoning_visible_output_text` is stored as an empty string, yet `reasoning_thought_text` has 285 chars of content.

**Root cause**: The reasoning agent's response at depth 0 is a tool call (function call to `execute_code`), not a text response. The `after_model_callback` in `reasoning.py` extracts `visible_text` from text parts of the response — but when the model responds with only a function call, there are no text parts, so `visible_text=""`. The thought text comes from a separate extraction path.

**This is partially expected behavior** for tool-calling iterations, but the dashboard doesn't distinguish "empty because tool call" from "empty because no data captured."

---

## GAP-11: `code` Action Chip Missing from REPL Panel When No Code in State

**Severity**: Medium
**Category**: REPL Visibility

The REPL panel conditionally shows the `code` chip only when `node.parent_code_text.strip()` is truthy (`live_invocation_tree.py:185`). Since REPL code is sourced from `invocation.repl_expanded_code or invocation.repl_submission`, and both are empty due to GAP-01, the code chip is hidden — giving the false impression no code was submitted.

**Expected**: The REPL panel should always show the `code` chip (even if clicking reveals "no code captured yet"), or should source code from the model's function call arguments (available in the snapshot chunks or telemetry `tool_args`).

---

## GAP-12: Token Count Estimation Shows ~0 tok for All State Keys

**Severity**: Medium
**Category**: Display Correctness

All state key chips display `~0 tok` because `_estimate_token_count()` computes:
```python
round(total_tokens * len(text) / total_chars)
```
When `text=""` (because the state value is empty/missing), the result is 0. The `~` prefix indicates these are estimates, but showing `~0` for every key is misleading.

**Expected**: For keys with no value, show a distinct indicator (e.g., "n/a" or omit the token count) rather than `~0 tok` which implies the key exists but is empty.

---

## GAP-13: `present` Flag Logic for State Keys Uses Substring Match

**Severity**: Low
**Category**: Display Correctness

The `present` flag (which controls green vs gray chip styling) is computed via:
```python
present = preview[:80] in request_text if preview else False
```
This checks if the state value's first 80 chars appear as a substring in the request text. This produces false negatives when state values are reformatted/truncated in the prompt, and false positives for short common strings. For REPL-related keys, a special case exists but it too depends on `invocation.repl_submission` being non-empty.

---

## GAP-14: Dashboard Shows Stale `idle` Status During Active Replay

**Severity**: Medium
**Category**: Trace Lifecycle

Because `traces.total_calls=0` and `traces.status=running`, the `_normalize_status()` function returns `"idle"` (it checks `total_calls > 0` to distinguish running from idle). During the actual replay execution, the dashboard briefly shows `running` but reverts to `idle` once the trace metadata is read.

**Fix**: Use telemetry event count as a secondary signal, or update `total_calls` incrementally during the trace.

---

## Root Cause Dependency Graph

```
GAP-06: Tool calls depths 0-3 never finalize
  ├── GAP-01: repl_submitted_code not in state events
  ├── GAP-05: REPL stdout/stderr empty for depths 0-3
  └── GAP-11: code chip hidden

GAP-02: No state events at depth > 0  (ParallelAgent isolation)
  ├── GAP-09: No reasoning state for children
  ├── GAP-12: All state keys ~0 tok
  └── GAP-04: current_depth never written → wrong paused depth

GAP-07: Trace never finalizes
  ├── GAP-08: Summary metrics all zero
  └── GAP-14: Status shows idle instead of completed
```

---

## Priority Fix Order

| Priority | Gap | Fix Complexity | Impact |
|----------|-----|---------------|--------|
| P0 | GAP-06 | High | Root cause — tool telemetry finalization for recursive REPL dispatches |
| P0 | GAP-02 | High | Root cause — worker state event propagation through ParallelAgent |
| P1 | GAP-04 | Low | Write `current_depth` in dispatch or extract from agent name |
| P1 | GAP-03 | Low | Use `invocation.agent_name` instead of synthetic name |
| P1 | GAP-07 | Medium | Add explicit trace finalization in replay launcher or plugin cleanup |
| P2 | GAP-10 | Low | Distinguish "empty because tool call" from "no data" in UI |
| P2 | GAP-11 | Low | Always show code chip; fallback to function call args from snapshot |
| P2 | GAP-12 | Low | Show "n/a" instead of `~0 tok` for missing state values |
| P3 | GAP-13 | Low | Improve `present` detection or remove misleading green/gray styling |
| P3 | GAP-14 | Low | Use telemetry count as secondary status signal |

---

## Data Verification Commands

```bash
# Reproduce: run the replay and inspect the database
.venv/bin/python -c "
import sqlite3; db = sqlite3.connect('rlm_adk/.adk/traces.db')
trace_id = '5209b063e3e949eab6fb1d800e9784a9'

# GAP-06: tool calls without end_time
print(db.execute('SELECT agent_name, end_time FROM telemetry WHERE trace_id=? AND event_type=\"tool_call\"', (trace_id,)).fetchall())

# GAP-02: no state at depth > 0
print(db.execute('SELECT COUNT(*) FROM session_state_events WHERE trace_id=? AND key_depth > 0', (trace_id,)).fetchone())

# GAP-04: current_depth never written
print(db.execute('SELECT COUNT(*) FROM session_state_events WHERE state_key=\"current_depth\"').fetchone())
"
```
