# BUG-015: Child state events have NULL value_text for numeric/boolean keys

**Status**: Not a serialization bug -- query-layer issue
**Severity**: Low (observability convenience, not data loss)
**Discovered By**: skill_arch_test e2e (8-call depth=2 fixture)
**Date**: 2026-03-25

---

## Evidence

From the `session_state_events` dump of the passing `skill_arch_test` fixture, querying `value_text`:

```
  d=1 current_depth                  = None                                     author=child_orchestrator_d1
  d=1 iteration_count                = None                                     author=child_orchestrator_d1
  d=1 should_stop                    = None                                     author=child_orchestrator_d1
  d=1 final_response_text            = child_confirmed_depth2: depth2_leaf_ok   author=child_orchestrator_d1
  d=1 reasoning_output               = {"final_answer": "child_confirmed_depth2... author=child_reasoning_d1
  d=2 current_depth                  = None                                     author=child_orchestrator_d2
  d=2 iteration_count                = None                                     author=child_orchestrator_d2
  d=2 final_response_text            = depth2_leaf_ok                           author=child_orchestrator_d2
  d=2 reasoning_output               = {"final_answer": "depth2_leaf_ok"...     author=child_reasoning_d2
```

String-typed keys (`final_response_text`, `reasoning_output`) have correct `value_text` values. Numeric/boolean keys (`current_depth`, `iteration_count`, `should_stop`) show `value_text = NULL`.

Yet `final_state` correctly shows the values exist in session state:

```
  current_depth@d1 = 1
  current_depth@d2 = 2
  should_stop@d1 = True
  should_stop@d2 = True
```

---

## Root Cause Analysis

**This is NOT a serialization bug. The values are correctly stored -- they are in `value_int`, not `value_text`.**

### The type-dispatch in `_typed_value()` works correctly

The `_typed_value()` function at `sqlite_tracing.py:88-104` implements a type-discriminated column layout:

```python
def _typed_value(value: Any) -> tuple[str, int | None, float | None, str | None, str | None]:
    """Return (value_type, value_int, value_float, value_text, value_json)."""
    if value is None:
        return "null", None, None, None, None
    if isinstance(value, bool):
        return "bool", int(value), None, None, None
    if isinstance(value, int):
        return "int", value, None, None, None
    if isinstance(value, float):
        return "float", None, value, None, None
    if isinstance(value, str):
        return "str", None, None, value, None
    if isinstance(value, list):
        return "list", None, None, None, json.dumps(value, default=str)
    if isinstance(value, dict):
        return "dict", None, None, None, json.dumps(value, default=str)
    return "other", None, None, str(value), None
```

For each Python type, the value is placed into exactly one typed column:

| Python Type | `value_type` | `value_int` | `value_float` | `value_text` | `value_json` |
|---|---|---|---|---|---|
| `None` | `"null"` | NULL | NULL | NULL | NULL |
| `bool` (True) | `"bool"` | 1 | NULL | NULL | NULL |
| `bool` (False) | `"bool"` | 0 | NULL | NULL | NULL |
| `int` (e.g. 1) | `"int"` | 1 | NULL | NULL | NULL |
| `float` | `"float"` | NULL | 3.14 | NULL | NULL |
| `str` | `"str"` | NULL | NULL | `"hello"` | NULL |
| `list` | `"list"` | NULL | NULL | NULL | `[...]` |
| `dict` | `"dict"` | NULL | NULL | NULL | `{...}` |

### What the evidence actually shows

The keys that appear as `value_text = NULL` are all int/bool types:

- `current_depth` = `int` (0, 1, 2) --> stored in `value_int`, `value_text` is correctly NULL
- `iteration_count` = `int` (0, 1, ...) --> stored in `value_int`, `value_text` is correctly NULL
- `should_stop` = `bool` (True/False) --> stored in `value_int` as 0/1, `value_text` is correctly NULL

The keys that show correct values are all string types:

- `final_response_text` = `str` --> stored in `value_text`
- `reasoning_output` = `str` (JSON string from output_key) --> stored in `value_text`

### The data pipeline is intact

The full pipeline from child orchestrator through re-emission to SQLite insertion is correct:

1. **Child orchestrator** (`orchestrator.py:391-394`) yields `EventActions(state_delta={depth_key(CURRENT_DEPTH, self.depth): self.depth})` -- value is `int`.
2. **Dispatch curated filter** (`dispatch.py:325-328`) passes the value through unchanged: `curated = {k: v for k, v in state_delta.items() if should_capture_state_key(parse_depth_key(k)[0])}`.
3. **Re-emission** (`dispatch.py:331-343`) wraps curated dict into a new `Event(actions=EventActions(state_delta=curated))` -- value still `int`.
4. **Parent drain** (`orchestrator.py:523-528`) yields the re-emitted event unchanged.
5. **Plugin on_event_callback** (`sqlite_tracing.py:1381-1383`) iterates `state_delta.items()` and calls `_insert_sse(raw_key, value, ...)`.
6. **`_insert_sse`** (`sqlite_tracing.py:609`) calls `_typed_value_for_key()` which delegates to `_typed_value()`, correctly placing `int` into `value_int`.

No values are lost or stripped at any stage.

### The actual issue: query-layer reads only `value_text`

The evidence was produced by a query that only selected `value_text`:

```sql
SELECT state_key, value_text, event_author
FROM session_state_events
WHERE key_depth > 0
```

This naturally returns NULL for any row where the value lives in `value_int`, `value_float`, or `value_json`. A correct unified-value query would use `COALESCE`:

```sql
SELECT
    state_key,
    key_depth,
    COALESCE(value_text, CAST(value_int AS TEXT), CAST(value_float AS TEXT), value_json) AS value,
    value_type,
    event_author
FROM session_state_events
WHERE key_depth > 0
ORDER BY seq;
```

---

## Pertinent Code Objects

| Object/Function | File | Line | Role | Callsite |
|---|---|---|---|---|
| `_typed_value()` | `rlm_adk/plugins/sqlite_tracing.py` | 88 | Type-dispatch: routes values to correct column by Python type | Called by `_typed_value_for_key()` |
| `_typed_value_for_key()` | `rlm_adk/plugins/sqlite_tracing.py` | 107 | Thin wrapper, delegates to `_typed_value()` | Called by `_insert_sse()` |
| `_insert_sse()` | `rlm_adk/plugins/sqlite_tracing.py` | 595 | Inserts one `session_state_events` row with all 5 value columns | Called by `on_event_callback()` |
| `on_event_callback()` | `rlm_adk/plugins/sqlite_tracing.py` | 1372 | Iterates `event.actions.state_delta` and calls `_insert_sse()` per key | ADK plugin lifecycle |
| `_run_child()` curated filter | `rlm_adk/dispatch.py` | 324-343 | Filters child state_delta to curated keys, enqueues re-emission Event | Called during `child.run_async()` iteration |
| `_run_async_impl()` drain loop | `rlm_adk/orchestrator.py` | 523-528 | Yields re-emitted child events from `_child_event_queue` | Called during `reasoning_agent.run_async()` iteration |
| `_run_async_impl()` initial state | `rlm_adk/orchestrator.py` | 391-394 | Yields `current_depth` (int) and `iteration_count` (int) in state_delta | First event from child orchestrator |
| `session_state_events` schema | `rlm_adk/plugins/sqlite_tracing.py` | 231-246 | Table with `value_int`, `value_float`, `value_text`, `value_json` columns | DDL in `_SCHEMA_SQL` |
| `test_depth2_final_response_text` | `tests_rlm_adk/test_skill_arch_e2e.py` | 212-226 | Queries `value_text` for `final_response_text` (correctly, since it is a `str`) | e2e test assertion |

---

## Verdict: Not a Bug in Serialization

The `_typed_value()` type-dispatch is working exactly as designed. Integer values go to `value_int`, boolean values go to `value_int` (as 0/1), and string values go to `value_text`. The five-column layout (`value_type`, `value_int`, `value_float`, `value_text`, `value_json`) is a standard type-discriminated union pattern for SQLite.

**The apparent "NULL values" are a query-layer issue**, not a data-layer issue. Any query or diagnostic script that reads only `value_text` will miss int/bool/float/list/dict values.

---

## Proposed Fix: Convenience View + Query Guidance

### Option A: Create a SQL view for unified value access

Add a `CREATE VIEW` to `_SCHEMA_SQL` that exposes a unified `value` column:

```sql
CREATE VIEW IF NOT EXISTS session_state_events_unified AS
SELECT
    event_id, trace_id, seq, event_author, event_time,
    state_key, key_category, key_depth, key_fanout,
    value_type,
    COALESCE(value_text, CAST(value_int AS TEXT), CAST(value_float AS TEXT), value_json) AS value,
    value_int, value_float, value_text, value_json
FROM session_state_events;
```

Diagnostic queries then use `SELECT value FROM session_state_events_unified WHERE ...` without needing to know the type.

### Option B: Add a `value_display` column

Compute a display-friendly text representation at insert time and store it in an additional `value_display TEXT` column, so every row always has a human-readable value regardless of type. This adds a column migration but simplifies all downstream queries.

### Option C: Document the query pattern (minimal fix)

Add a comment to `_typed_value()` and/or the schema DDL explaining the type-discriminated layout, and provide a canonical COALESCE query snippet in the docstring. Update any test or diagnostic code that queries only `value_text` to use the COALESCE pattern.

**Recommended**: Option A (view) -- zero migration cost, backward compatible, and immediately useful for all ad-hoc diagnostic queries.

---

## Impact

### Affected queries/tests

1. **`test_depth2_final_response_text`** (`tests_rlm_adk/test_skill_arch_e2e.py:217-226`) -- queries `value_text` for `final_response_text`. This test is CORRECT because `final_response_text` is always a `str`, so `value_text` is the right column. No fix needed.

2. **Ad-hoc diagnostic queries** -- any manual `SELECT value_text FROM session_state_events` will miss int/bool values at child depths. This is what produced the original evidence.

3. **`session_report.py:144`** -- correctly queries `value_int` for `iteration_count`. No fix needed.

4. **Future dashboard/observability consumers** -- any new code that reads `session_state_events` must use either the COALESCE pattern or the proposed view to get a unified value. Without guidance, developers will naturally reach for `value_text` and hit the same confusion.

### Not affected

- Data integrity: all values are correctly stored and retrievable.
- Child event re-emission: pipeline is working correctly.
- `final_state` dict: values are present and correct (uses session state, not SQLite).
- Existing passing tests: no test relies on `value_text` for int/bool keys.

---

## Note

**This is a query-layer convenience issue, not a data loss bug.** The `value_int` column correctly contains the expected values for `current_depth`, `iteration_count`, and `should_stop` at all depths. The original observation of "NULL values" was caused by querying only the `value_text` column, which is NULL by design for non-string types in the type-discriminated column layout.

The fix is to either (a) provide a unified SQL view, (b) add a computed `value_display` column, or (c) document the COALESCE query pattern. No changes to the serialization or re-emission pipeline are needed.

---

## Fix Applied: Option A — `session_state_events_unified` SQL View

**Status**: RESOLVED (2026-03-25)
**Fix**: Option A (CREATE VIEW) added to `_SCHEMA_SQL` in `sqlite_tracing.py`
**Tests**: 21 new tests in `tests_rlm_adk/test_unified_view.py`
**Demo**: `tests_rlm_adk/SHOWBOAT_bug015_unified_view.md` (showboat-verified)

### Changes

**`rlm_adk/plugins/sqlite_tracing.py`** — Added `CREATE VIEW IF NOT EXISTS session_state_events_unified` to `_SCHEMA_SQL` (line 258). The view exposes a unified `value` column via `COALESCE(value_text, CAST(value_int AS TEXT), CAST(value_float AS TEXT), value_json)`. Zero migration cost — views are created alongside tables on every DB init.

**`tests_rlm_adk/test_unified_view.py`** — 21 tests across 5 classes:

| Class | Tests | What it validates |
|---|---|---|
| `TestUnifiedViewExists` | 1 | View appears in `sqlite_master` after plugin init |
| `TestUnifiedValueResolution` | 8 | Each Python type (int, bool True/False, float, str, dict, list, null) resolves correctly |
| `TestUnifiedViewColumns` | 1 | View schema includes all expected columns |
| `TestTypedValueRoundTrip` | 10 | `_typed_value()` output → INSERT → unified view SELECT round-trip for all types |
| `TestCoalescePriority` | 1 | `value_text` wins over `value_int` when both are set |

### TDD Cycle

1. **RED**: Wrote 21 tests querying `session_state_events_unified` — all failed with `OperationalError: no such table: session_state_events_unified`.
2. **GREEN**: Added `CREATE VIEW` to `_SCHEMA_SQL` — all 21 tests pass.
3. **Regression**: Verified 52 existing related tests (child_event_reemission, execution_mode_telemetry, skill_arch_e2e) still pass.

### Showboat Demo (verified reproducible)

```
# BUG-015 Fix: session_state_events_unified SQL View

*2026-03-25T13:15:54Z by Showboat 0.6.1*

BUG-015: Child state events (current_depth, iteration_count, should_stop)
showed NULL value_text in diagnostic queries. Root cause: these are int/bool
values stored in value_int by the type-discriminated column layout. Queries
selecting only value_text naturally miss them. Fix: add a CREATE VIEW
session_state_events_unified that COALESCEs across all typed columns into a
single unified "value" column.

The CREATE VIEW DDL added to _SCHEMA_SQL:

  CREATE VIEW IF NOT EXISTS session_state_events_unified AS
  SELECT
      event_id, trace_id, seq, event_author, event_time,
      state_key, key_category, key_depth, key_fanout,
      value_type,
      COALESCE(value_text, CAST(value_int AS TEXT),
               CAST(value_float AS TEXT), value_json) AS value,
      value_int, value_float, value_text, value_json
  FROM session_state_events;

Test results: 21 passed

End-to-end round-trip demo (old query vs unified view):

  === value_text only (old query - shows NULLs) ===
    current_depth                  = None
    should_stop                    = None
    iteration_count                = None
    confidence                     = None
    final_response_text            = hello world
    reasoning_output               = None
    batch_results                  = None
    empty_key                      = None

  === unified view (new query - no NULLs except None) ===
    current_depth                  = 2                (type=int)
    should_stop                    = 1                (type=bool)
    iteration_count                = 0                (type=int)
    confidence                     = 3.14             (type=float)
    final_response_text            = hello world      (type=str)
    reasoning_output               = {"answer": "yes"} (type=dict)
    batch_results                  = [1, 2, 3]        (type=list)
    empty_key                      = None             (type=null)

The old query (SELECT value_text) shows NULL for int/bool/float/json values.
The unified view resolves all types through COALESCE. Zero migration cost,
backward compatible, zero data changes required.
```
