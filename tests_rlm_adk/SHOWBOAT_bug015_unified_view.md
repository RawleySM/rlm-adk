# BUG-015 Fix: session_state_events_unified SQL View

*2026-03-25T13:15:54Z by Showboat 0.6.1*
<!-- showboat-id: be6c936e-f953-4083-a67b-1b63a17cdfdd -->

BUG-015: Child state events (current_depth, iteration_count, should_stop) showed NULL value_text in diagnostic queries. Root cause: these are int/bool values stored in value_int by the type-discriminated column layout. Queries selecting only value_text naturally miss them. Fix: add a CREATE VIEW session_state_events_unified that COALESCEs across all typed columns into a single unified "value" column.

```bash
sed -n "258,265p" rlm_adk/plugins/sqlite_tracing.py
```

```output
CREATE VIEW IF NOT EXISTS session_state_events_unified AS
SELECT
    event_id, trace_id, seq, event_author, event_time,
    state_key, key_category, key_depth, key_fanout,
    value_type,
    COALESCE(value_text, CAST(value_int AS TEXT), CAST(value_float AS TEXT), value_json) AS value,
    value_int, value_float, value_text, value_json
FROM session_state_events;
```

```bash
sed -n "88,104p" rlm_adk/plugins/sqlite_tracing.py
```

```output
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

The _typed_value() function correctly routes each Python type to exactly one typed column (value_int, value_float, value_text, value_json). The unified view uses COALESCE to merge all four back into a single "value" column, with value_text taking priority. 21 TDD tests verify the view exists, resolves all types, preserves original columns, round-trips through _typed_value, and respects COALESCE priority.

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_unified_view.py -q -o "addopts=" 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
21 passed
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import sqlite3, tempfile, os
from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin, _typed_value

db_path = os.path.join(tempfile.mkdtemp(), \"demo.db\")
plugin = SqliteTracingPlugin(db_path=db_path)
conn = plugin._conn

test_values = [
    (\"current_depth\", 2),
    (\"should_stop\", True),
    (\"iteration_count\", 0),
    (\"confidence\", 3.14),
    (\"final_response_text\", \"hello world\"),
    (\"reasoning_output\", {\"answer\": \"yes\"}),
    (\"batch_results\", [1, 2, 3]),
    (\"empty_key\", None),
]

for i, (key, val) in enumerate(test_values):
    vtype, vint, vfloat, vtext, vjson = _typed_value(val)
    conn.execute(
        \"INSERT INTO session_state_events \"
        \"(event_id, trace_id, seq, event_author, event_time, \"
        \"state_key, key_category, key_depth, key_fanout, \"
        \"value_type, value_int, value_float, value_text, value_json) \"
        \"VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)\",
        (f\"e{i}\", \"tr1\", i, \"demo\", 1000.0+i, key, \"test\", 1, None,
         vtype, vint, vfloat, vtext, vjson),
    )
conn.commit()

print(\"=== value_text only (old query - shows NULLs) ===\")
for row in conn.execute(\"SELECT state_key, value_text FROM session_state_events ORDER BY seq\"):
    print(f\"  {row[0]:30s} = {row[1]}\")

print()
print(\"=== unified view (new query - no NULLs except None) ===\")
for row in conn.execute(\"SELECT state_key, value, value_type FROM session_state_events_unified ORDER BY seq\"):
    print(f\"  {row[0]:30s} = {str(row[1]):30s}  (type={row[2]})\")
" 2>&1
```

```output
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
  current_depth                  = 2                               (type=int)
  should_stop                    = 1                               (type=bool)
  iteration_count                = 0                               (type=int)
  confidence                     = 3.14                            (type=float)
  final_response_text            = hello world                     (type=str)
  reasoning_output               = {"answer": "yes"}               (type=dict)
  batch_results                  = [1, 2, 3]                       (type=list)
  empty_key                      = None                            (type=null)
```

The old query (SELECT value_text) shows NULL for int/bool/float/json values. The unified view resolves all types through COALESCE. Zero migration cost, backward compatible, zero data changes required.
