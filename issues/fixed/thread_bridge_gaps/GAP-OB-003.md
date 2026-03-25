# GAP-OB-003: execution_mode not captured in SqliteTracingPlugin telemetry
**Severity**: HIGH
**Category**: observability
**Files**: `rlm_adk/plugins/sqlite_tracing.py`, `rlm_adk/tools/repl_tool.py`

## Problem

REPLTool writes `execution_mode` (value `"sync"` or `"thread_bridge"`) into the `LAST_REPL_RESULT` state key dict (repl_tool.py lines 216, 247, 263, 276). The `repl_trace_summary` JSON blob may also contain it. However, SqliteTracingPlugin's `telemetry` table has no `execution_mode` column, and neither `after_tool_callback` nor `make_telemetry_finalizer` extracts or persists this field.

This means there is no way to query traces.db to determine whether a given REPL execution used the sync path or the thread bridge path. For debugging thread bridge issues, this is a significant gap -- you cannot filter telemetry rows by execution mode.

## Evidence

1. `repl_tool.py` line 276: `"execution_mode": exec_mode` written into `last_repl` dict
2. `repl_tool.py` line 263: `exec_mode = trace.execution_mode if trace else "thread_bridge"`
3. Grep for `execution_mode` in `sqlite_tracing.py` returns zero hits
4. The `telemetry` table schema (lines 178-228) has no `execution_mode` column
5. `after_tool_callback` (line 1317-1357) does not extract `execution_mode` from REPL state
6. `make_telemetry_finalizer` (lines 486-499) does not extract `execution_mode`

## Suggested Fix

1. Add `execution_mode TEXT` to the `telemetry` table schema and `_EXPECTED_COLUMNS` migration list.
2. In `after_tool_callback`, when `tool_name == "execute_code"`, extract `execution_mode` from `repl_state` or from the result dict and include it in `update_kwargs`.
3. Do the same in `make_telemetry_finalizer`'s `_finalize` closure.
