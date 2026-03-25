# Polya Understand Phase: GAP-OB-003

**Gap**: `execution_mode` not captured in SqliteTracingPlugin telemetry DB schema

**Date**: 2026-03-24

---

## 1. Problem Restatement

REPLTool determines whether each code execution used the `"sync"` or `"thread_bridge"` execution path and writes this into the `LAST_REPL_RESULT` session state dict. However, the SqliteTracingPlugin's `telemetry` table has no column to store this value, and neither of its two extraction paths (`after_tool_callback`, `make_telemetry_finalizer`) attempts to read or persist it. The result is that `execution_mode` is present in transient session state but permanently lost when telemetry is written to disk.

## 2. Exact Objective

Add a queryable `execution_mode TEXT` column to the `telemetry` table so that any row where `tool_name = 'execute_code'` records whether the REPL execution used the sync or thread_bridge path. After the fix, `SELECT execution_mode FROM telemetry WHERE tool_name = 'execute_code'` must return either `"sync"` or `"thread_bridge"` for every such row.

## 3. Knowns / Givens

### Data (what the code already produces)

| Source | Where | What |
|---|---|---|
| `REPLTrace.execution_mode` | `rlm_adk/repl/trace.py` line 32 | `Literal["sync", "thread_bridge"]`, default `"sync"` |
| `local_repl.py` line 452 | `rlm_adk/repl/local_repl.py` | Sets `trace.execution_mode = "thread_bridge"` when thread bridge is used |
| `repl_tool.py` line 215 | CancelledError path | Writes `"execution_mode": trace.execution_mode if trace else "thread_bridge"` into `LAST_REPL_RESULT` state dict |
| `repl_tool.py` line 246 | Exception path | Same pattern as above |
| `repl_tool.py` line 276 | Success path | Writes `"execution_mode": exec_mode` into `LAST_REPL_RESULT` state dict |
| `repl_tool.py` line 263 | Success path | `exec_mode = trace.execution_mode if trace else "thread_bridge"` |

### Rules (how the plugin stores data)

- `after_tool_callback` (sqlite_tracing.py lines 1248-1364): Fires after ADK tool execution. For `execute_code`, it reads `repl_state` via `_resolve_repl_state()` (which returns the `LAST_REPL_RESULT` dict from session state) and extracts fields like `has_errors`, `has_output`, `total_llm_calls`, `trace_summary`. It builds an `update_kwargs` dict and calls `_update_telemetry()`.
- `make_telemetry_finalizer` (sqlite_tracing.py lines 454-505): Creates a `_finalize` closure that REPLTool calls from its `finally` block. This closure receives the `_final_result` dict (NOT the `LAST_REPL_RESULT` state dict) and extracts fields like `stdout`, `stderr`, `has_errors`, `has_output`, `llm_calls_made`. Idempotent -- only fires if `after_tool_callback` did not already consume the pending entry.
- `_update_telemetry` (sqlite_tracing.py lines 575-588): Generic UPDATE by `telemetry_id`. Accepts arbitrary `**kwargs` as column=value pairs.
- `_insert_telemetry` (sqlite_tracing.py lines 549-573): Generic INSERT. Same kwargs pattern.
- `_migrate_schema` (sqlite_tracing.py lines 331-443): On init, compares `PRAGMA table_info` against `_EXPECTED_COLUMNS` and adds missing columns via `ALTER TABLE`.

### Constraints

- The plugin is observe-only: all callbacks return `None` and never block execution. DB write errors are caught and logged as warnings.
- Two independent extraction paths must both be updated because they race -- either `after_tool_callback` or `_finalize` may be the one that actually persists the data, depending on whether ADK fires the callback.
- The `_finalize` closure receives the `_final_result` dict, which is constructed separately from the `LAST_REPL_RESULT` state dict. Currently `_final_result` does NOT contain `execution_mode`.

### Context

- The thread bridge replaced the AST rewriter. Knowing which execution mode was active per REPL call is critical for debugging thread bridge issues.
- The `execution_mode` value domain is a strict two-element set: `"sync"` or `"thread_bridge"`.

## 4. Unknowns and Their Relationships to Givens

There is one primary unknown and two dependent implementation questions:

| Unknown | Relationship to givens |
|---|---|
| **U1**: How to get `execution_mode` into the `telemetry` table | Requires changes in 3 files across 4 locations (see Representation below) |
| **U2**: How `after_tool_callback` should extract it | It already calls `_resolve_repl_state()` which returns the `LAST_REPL_RESULT` dict. That dict already contains `execution_mode`. A single `.get("execution_mode")` suffices. |
| **U3**: How `_finalize` should extract it | The `_finalize` closure receives `_final_result`, which currently lacks `execution_mode`. Two sub-steps: (a) add `execution_mode` to `_final_result` in repl_tool.py at all 3 construction sites, (b) extract it in the closure. |

The chain is: `REPLTrace` -> `repl_tool.py` writes to `LAST_REPL_RESULT` AND `_final_result` -> `sqlite_tracing.py` reads from one of those -> writes to `telemetry` table.

## 5. Definitions / Clarified Terms

- **`execution_mode`**: A string, either `"sync"` (REPL code ran in the main async loop without thread bridge involvement) or `"thread_bridge"` (REPL code ran in a worker thread via `run_coroutine_threadsafe`, enabling sync `llm_query()` calls).
- **`LAST_REPL_RESULT`**: A session state key (`"last_repl_result"`) whose value is a dict written by REPLTool after each execution. Depth-scoped via `depth_key()`. Contains observability summary fields.
- **`_final_result`**: A local dict variable in `REPLTool.run_async()` constructed at each return path (lines 217-223, 248-254, 300-306). Passed to `_finalize_telemetry()`. Distinct from `LAST_REPL_RESULT` -- it is a subset of fields tailored for the tool return value.
- **`repl_state`**: The resolved `LAST_REPL_RESULT` dict as seen by `after_tool_callback` through `_resolve_repl_state()`.
- **`_finalize` closure**: The inner function returned by `make_telemetry_finalizer()`. Called by REPLTool in its `finally` block. Receives `(id(tool_context), _final_result)`.

## 6. Representation

```
Data flow diagram: execution_mode from source to telemetry DB

REPLTrace.execution_mode        (trace.py:32, set by local_repl.py:452)
         |
         v
repl_tool.py run_async()
    |                          |
    | writes to                | constructs
    | LAST_REPL_RESULT         | _final_result
    | (state dict, HAS         | (local dict, MISSING
    |  execution_mode)         |  execution_mode) <-- FIX NEEDED (U3a)
    v                          v
after_tool_callback            _finalize closure
    |                          |
    | reads repl_state         | reads result dict
    | via _resolve_repl_state  | (the _final_result)
    | (HAS execution_mode      | (MISSING execution_mode
    |  but never extracts it)  |  in source dict) <-- FIX NEEDED (U3b)
    | <-- FIX NEEDED (U2)      |
    v                          v
update_kwargs dict             update_kwargs dict
    |                          |
    v                          v
_update_telemetry(id, **update_kwargs)
    |
    v
telemetry table
    |
    MISSING execution_mode column <-- FIX NEEDED (schema)
```

**Modification sites (4 locations across 2 files):**

| # | File | Location | Change |
|---|---|---|---|
| S1 | `sqlite_tracing.py` | `_SCHEMA_SQL` (line 178-228) + `_EXPECTED_COLUMNS` (line 364-409) | Add `execution_mode TEXT` to `telemetry` table schema and migration list |
| S2 | `sqlite_tracing.py` | `after_tool_callback` REPL enrichment block (lines 1317-1357) | Extract `execution_mode` from `repl_state` (or fall through to `result` dict) and add to `update_kwargs` |
| S3 | `sqlite_tracing.py` | `_finalize` closure (lines 470-503) | Extract `execution_mode` from `result` dict and add to `update_kwargs` |
| S4 | `repl_tool.py` | `_final_result` construction at 3 return paths (lines 217-223, 248-254, 300-306) | Add `"execution_mode"` key to each `_final_result` dict |

## 7. Facts vs Assumptions

### Confirmed Facts

1. `execution_mode` is written into `LAST_REPL_RESULT` at all 3 return paths in repl_tool.py (lines 215, 246, 276). Verified by reading source.
2. `execution_mode` is NOT written into `_final_result` at any of the 3 return paths (lines 217-223, 248-254, 300-306). Verified by reading source.
3. `sqlite_tracing.py` has zero hits for the string `"execution_mode"`. Verified by grep.
4. The `telemetry` table schema (lines 178-228) has no `execution_mode` column. Verified by reading `_SCHEMA_SQL`.
5. `_EXPECTED_COLUMNS["telemetry"]` (lines 364-409) has no `execution_mode` entry. Verified by reading source.
6. `after_tool_callback` already resolves `repl_state` via `_resolve_repl_state()` for `execute_code` tools (line 1320-1323). That `repl_state` dict already contains `execution_mode`.
7. The `_finalize` closure receives `_final_result` as its `result` parameter, not `repl_state`.
8. `_update_telemetry` accepts arbitrary `**kwargs` -- no code change needed there to accept a new column, only the DB schema must have the column.

### Assumptions

1. **No existing mitigation**: There is no workaround that recovers `execution_mode` from any other telemetry column (e.g., it is not derivable from `repl_trace_summary`). While `trace_summary` does include `execution_mode` in its JSON, relying on JSON parsing inside a TEXT blob is not a substitute for a first-class column. Confirmed by code reviewer.
2. **Both extraction paths are needed**: We cannot assume `after_tool_callback` always fires. The `_finalize` closure exists specifically as a fallback for GAP-06 (ADK sometimes does not fire `after_tool_callback`). Both paths must extract `execution_mode`.

## 8. Problem Type

This is a **schema-and-extraction gap** -- a data pipeline problem where a value is produced upstream but the downstream persistence layer lacks both the storage column and the extraction logic to capture it. It is not a design problem or an ambiguity problem. The data exists, the destination exists, the wiring is missing.

Structurally analogous to previous lineage data-flow gaps (BUG-009 through BUG-013 in `issues/`) where specific fields were written to session state but not extracted into the telemetry table.

## 9. Edge Cases / Toy Examples

| Case | `execution_mode` value | Source |
|---|---|---|
| REPL execution with no `llm_query()` calls | `"sync"` | `REPLTrace` default (trace.py:32) |
| REPL execution with `llm_query()` calls via thread bridge | `"thread_bridge"` | `local_repl.py:452` sets it |
| REPL execution with no trace holder (trace is None) | `"thread_bridge"` | Hardcoded fallback in repl_tool.py:263 |
| CancelledError during execution | `trace.execution_mode if trace else "thread_bridge"` | repl_tool.py:215 |
| Exception during execution | `trace.execution_mode if trace else "thread_bridge"` | repl_tool.py:246 |
| Call-limit exceeded (call_count > max_calls) | Not set in `LAST_REPL_RESULT` | repl_tool.py:133-141 -- this is an edge case where `execution_mode` is absent from state; the telemetry column should be NULL for these rows |
| `after_tool_callback` fires AND `_finalize` fires | Only one persists (idempotent via `pending.pop`). The first one to consume the pending entry writes the data; the second is a no-op. |

## 10. Well-Posedness Judgment

**Well-posed.** The problem is fully specified:
- The data source is known and already produces the value.
- The destination schema is known and needs exactly one new column.
- The two extraction paths are known and need exactly one new line each.
- The `_final_result` gap (missing `execution_mode`) is known and needs exactly 3 additions (one per return path).
- There are no ambiguities in the value domain (`"sync"` | `"thread_bridge"` | NULL for call-limit rows).
- There are no dependencies on external systems or ADK internals -- this is entirely internal plugin infrastructure.

## 11. Constraints and Success Criteria

### Constraints

- The plugin remains observe-only: changes must not block execution or raise exceptions.
- Schema migration must be backward-compatible (new column added via `ALTER TABLE ADD COLUMN` for existing databases).
- Both extraction paths must be updated (idempotent pairing via `pending.pop`).

### Success Criteria

1. `SELECT execution_mode FROM telemetry WHERE tool_name = 'execute_code' AND execution_mode IS NOT NULL` returns rows for every REPL execution (except call-limit-exceeded rows where no execution occurs).
2. The value is `"sync"` when no thread bridge was used, `"thread_bridge"` when it was.
3. Existing `traces.db` files are migrated on next plugin init (new column appears via `_migrate_schema`).
4. No existing tests break.
5. New test(s) verify that `execution_mode` appears in telemetry rows after an `execute_code` tool call.

## 12. Scope Boundary

### In scope

- Add `execution_mode TEXT` to telemetry table schema (`_SCHEMA_SQL`) and migration list (`_EXPECTED_COLUMNS`).
- Extract `execution_mode` in `after_tool_callback` from `repl_state` dict.
- Extract `execution_mode` in `_finalize` closure from `result` dict.
- Add `"execution_mode"` key to `_final_result` dicts in `repl_tool.py` (3 locations).

### Out of scope

- Adding `execution_mode` to the `traces` (summary) table. Per-invocation aggregation of execution modes (e.g., "were all REPL calls sync or mixed?") is a separate concern.
- Changing the `execution_mode` value domain or the logic that determines sync vs thread_bridge.
- Dashboard or query-layer changes to surface the new column.
- The call-limit-exceeded path (line 133-141) which returns early before any execution occurs -- NULL is the correct value there.
