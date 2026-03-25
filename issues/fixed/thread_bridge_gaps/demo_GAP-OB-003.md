# Demo: GAP-OB-003 -- execution_mode not persisted to sqlite telemetry

## What was fixed

`REPLTool` wrote `execution_mode` (value `"sync"` or `"thread_bridge"`) into `LAST_REPL_RESULT` session state, but `SqliteTracingPlugin` had no `execution_mode` column in the `telemetry` table and never extracted the value. There was no way to query which execution path a REPL invocation used after the fact.

## Before (the problem)

### No column in telemetry schema

The `telemetry` CREATE TABLE in `sqlite_tracing.py` had no `execution_mode` column. The value was silently dropped.

### No extraction in after_tool_callback

`after_tool_callback` read `repl_has_errors`, `repl_has_output`, and `repl_llm_calls` from `repl_state` but never read `execution_mode`.

### No extraction in _finalize closure

`make_telemetry_finalizer` built `update_kwargs` from the result dict but never pulled `execution_mode` from it.

### Result: impossible query

```sql
-- This would fail: no such column
SELECT execution_mode FROM telemetry WHERE tool_name = 'execute_code';
```

## After (the fix)

### 1. REPLTool: execution_mode in _final_result at all 3 return paths (repl_tool.py)

All three return paths (normal, exception, cancelled) now include `execution_mode` in both the `LAST_REPL_RESULT` state dict and the `_final_result` dict passed to the telemetry finalizer:

```python
# Normal path (line 278)
"execution_mode": exec_mode,

# Exception path (line 247, 255)
"execution_mode": trace.execution_mode if trace else "thread_bridge",

# CancelledError path (line 215, 223)
"execution_mode": trace.execution_mode if trace else "thread_bridge",
```

### 2. Schema + migration in sqlite_tracing.py

Column added to the CREATE TABLE (line 225):

```sql
execution_mode  TEXT,
```

Column added to the migration list (line 408) so existing DBs get it via `ALTER TABLE ADD COLUMN`:

```python
("execution_mode", "TEXT"),
```

### 3. Extraction in after_tool_callback (line 1340)

```python
update_kwargs["execution_mode"] = repl_state.get("execution_mode", "")
```

### 4. Extraction in _finalize closure (line 502)

```python
update_kwargs["execution_mode"] = result.get("execution_mode", "")
```

### Result: queryable execution path

```sql
SELECT execution_mode, COUNT(*) FROM telemetry
WHERE tool_name = 'execute_code'
GROUP BY execution_mode;
-- Returns: sync | N, thread_bridge | M
```

## Verification commands

### 1. Run the 7 new tests

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_execution_mode_telemetry.py -x -q -o "addopts="
```

Expected: 7 passed. Tests cover:
- `TestREPLToolFinalResultExecutionMode` (3 tests): normal, exception, and cancelled return paths all include `execution_mode`
- `TestTelemetrySchemaHasExecutionMode` (2 tests): fresh DB has column; migration adds column to existing DB
- `TestAfterToolCallbackExecutionMode` (1 test): `after_tool_callback` extracts `execution_mode` from `repl_state` and writes to DB
- `TestFinalizerExecutionMode` (1 test): `_finalize` closure extracts `execution_mode` from result dict and writes to DB

### 2. Grep for execution_mode in sqlite_tracing.py

```bash
grep -n "execution_mode" rlm_adk/plugins/sqlite_tracing.py
```

Expected: 4 hits -- schema definition (line 225), migration tuple (line 408), _finalize extraction (line 502), after_tool_callback extraction (line 1340).

### 3. Grep for execution_mode in repl_tool.py

```bash
grep -n "execution_mode" rlm_adk/tools/repl_tool.py
```

Expected: 6 hits across the 3 return paths (each path writes it to both `LAST_REPL_RESULT` and `_final_result`).

## Files changed

| File | Change |
|------|--------|
| `rlm_adk/tools/repl_tool.py` | Added `execution_mode` to `_final_result` dicts at all 3 return paths |
| `rlm_adk/plugins/sqlite_tracing.py` | Added column to schema + migration list; extraction in `_finalize` and `after_tool_callback` |
| `tests_rlm_adk/test_execution_mode_telemetry.py` | 7 new tests covering all 4 fix parts |

## Verification Checklist

- [ ] `test_execution_mode_telemetry.py`: all 7 tests pass
- [ ] `repl_tool.py`: normal return path includes `"execution_mode": exec_mode` in both `last_repl` and `_final_result`
- [ ] `repl_tool.py`: exception return path includes `"execution_mode"` in both state dict and `_final_result`
- [ ] `repl_tool.py`: cancelled return path includes `"execution_mode"` in both state dict and `_final_result`
- [ ] `sqlite_tracing.py`: `execution_mode TEXT` in CREATE TABLE statement
- [ ] `sqlite_tracing.py`: `("execution_mode", "TEXT")` in migration list
- [ ] `sqlite_tracing.py`: `after_tool_callback` reads `repl_state.get("execution_mode", "")`
- [ ] `sqlite_tracing.py`: `_finalize` closure reads `result.get("execution_mode", "")`
- [ ] `SELECT execution_mode FROM telemetry` no longer errors on fresh or migrated DBs
