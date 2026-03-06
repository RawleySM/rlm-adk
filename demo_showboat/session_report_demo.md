# Session Assessment Report CLI

Consolidates session telemetry from the 4-table SQLite schema (traces, telemetry, session_state_events, spans) into a structured 6-section JSON report. Designed for debugging, performance analysis, and code review.

**File**: `rlm_adk/eval/session_report.py`

---

## 1. CLI --help

```bash
.venv/bin/python -m rlm_adk.eval.session_report --help
```

Expected output:

```
usage: session_report.py [-h] --trace-id TRACE_ID [--db DB]

Generate a session assessment report from SQLite telemetry.

options:
  -h, --help           show this help message and exit
  --trace-id TRACE_ID  The trace_id to generate a report for.
  --db DB              Path to the SQLite traces database (default: .adk/traces.db)
```

---

## 2. Report Structure (6 Sections)

```bash
.venv/bin/python -m rlm_adk.eval.session_report \
  --trace-id bffab79f7daa41a4b2b01f68df8b1d3f \
  --db .adk/traces.db 2>/dev/null \
  | .venv/bin/python -c "
import json, sys
data = json.load(sys.stdin)
for section in data:
    if isinstance(data[section], dict):
        print(f'{section}: {list(data[section].keys())}')
    else:
        print(f'{section}: {type(data[section]).__name__}')
"
```

Expected output:

```
overview: ['trace_id', 'session_id', 'status', 'app_name', 'start_time', 'end_time', 'wall_clock_s', 'total_input_tokens', 'total_output_tokens', 'total_model_calls', 'total_tool_calls', 'iterations', 'final_answer_length']
layer_tree: ['depth_-1', 'depth_0', 'depth_1', 'depth_2']
performance: ['model_call_latency_by_layer', 'rate_limit_errors', 'repl_execution']
errors: ['telemetry_errors', 'repl_errors', 'error_propagation_by_depth', 'total_error_count']
repl_outcomes: ['total_executions', 'successful', 'with_errors', 'error_pattern_counts', 'by_depth', 'reasoning_agent_calls']
state_timeline: ['total_events', 'categories', 'events']
```

---

## 3. Layer Tree -- Depth Hierarchy

The `layer_tree` section groups telemetry by agent depth, showing model calls, tool calls, token usage, and errors at each level of the recursive dispatch tree.

```bash
.venv/bin/python -m rlm_adk.eval.session_report \
  --trace-id bffab79f7daa41a4b2b01f68df8b1d3f \
  --db .adk/traces.db 2>/dev/null \
  | .venv/bin/python -c "
import json, sys
data = json.load(sys.stdin)
tree = data['layer_tree']
for key in sorted(tree.keys()):
    layer = tree[key]
    print(f\"{key}: agents={layer['agents']}, model_calls={layer['model_calls']}, \"
          f\"tool_calls={layer['tool_calls']}, in_tok={layer['input_tokens']}, \"
          f\"out_tok={layer['output_tokens']}, errors={layer['error_count']}\")
"
```

Expected output (trace bffab79f):

```
depth_-1: agents=[], model_calls=22, tool_calls=0, in_tok=72886, out_tok=9909, errors=0
depth_0: agents=['reasoning_agent'], model_calls=3, tool_calls=3, in_tok=12434, out_tok=457, errors=0
depth_1: agents=['child_reasoning_d1'], model_calls=67, tool_calls=58, in_tok=182215, out_tok=19682, errors=5
depth_2: agents=['child_reasoning_d2'], model_calls=374, tool_calls=191, in_tok=569836, out_tok=61922, errors=83
```

Note: `depth_-1` captures telemetry rows with no parseable `_dN` suffix in the agent name (e.g. workers, parallel agents).

---

## 4. Performance Metrics

The `performance` section includes per-layer model call latency (min/max/avg/p95), rate-limit error counts, and REPL execution timing.

```bash
.venv/bin/python -m rlm_adk.eval.session_report \
  --trace-id bffab79f7daa41a4b2b01f68df8b1d3f \
  --db .adk/traces.db 2>/dev/null \
  | .venv/bin/python -c "
import json, sys
data = json.load(sys.stdin)
perf = data['performance']
print('--- Model call latency by layer ---')
for key in sorted(perf['model_call_latency_by_layer'].keys()):
    stats = perf['model_call_latency_by_layer'][key]
    print(f\"  {key}: count={stats['count']}, avg={stats['avg_ms']}ms, p95={stats['p95_ms']}ms\")
print(f\"Rate limit errors: {perf['rate_limit_errors']}\")
print(f\"REPL executions: {perf['repl_execution']}\")

# Token amplification (derived from overview + layer_tree)
ov = data['overview']
if ov['total_input_tokens'] and ov['total_output_tokens']:
    amp = ov['total_input_tokens'] / max(ov['total_output_tokens'], 1)
    print(f'Token amplification (input/output): {amp:.2f}x')
"
```

Expected output (trace bffab79f):

```
--- Model call latency by layer ---
  depth_-1: count=22, avg=0.0ms, p95=0.0ms
  depth_0: count=3, avg=6768.1ms, p95=10188.9ms
  depth_1: count=60, avg=2145.2ms, p95=6224.1ms
  depth_2: count=255, avg=1164.0ms, p95=3655.2ms
Rate limit errors: 88
REPL executions: {'count': 247, 'min_ms': 0.7, 'max_ms': 9830.9, 'avg_ms': 67.3, 'p95_ms': 18.9}
Token amplification (input/output): 9.10x
```

Note: Token amplification is not a built-in field -- it is derived from overview totals. See "Improvements" below.

---

## 5. Error Aggregation

The `errors` section groups telemetry errors by agent + error type, extracts REPL stderr errors, and builds a depth-keyed error propagation map.

```bash
.venv/bin/python -m rlm_adk.eval.session_report \
  --trace-id bffab79f7daa41a4b2b01f68df8b1d3f \
  --db .adk/traces.db 2>/dev/null \
  | .venv/bin/python -c "
import json, sys
data = json.load(sys.stdin)
errs = data['errors']
print(f\"Total error count: {errs['total_error_count']}\")
print('Telemetry errors:')
for e in errs['telemetry_errors']:
    print(f\"  depth={e['depth']} agent={e['agent_name']} type={e['error_type']} count={e['count']}\")
print(f\"Error propagation by depth: {errs['error_propagation_by_depth']}\")
print(f\"REPL errors: {len(errs['repl_errors'])}\")
"
```

Expected output (trace bffab79f):

```
Total error count: 88
Telemetry errors:
  depth=2 agent=child_reasoning_d2 type=_ResourceExhaustedError count=83
  depth=1 agent=child_reasoning_d1 type=_ResourceExhaustedError count=5
Error propagation by depth: {'2': ['_ResourceExhaustedError'], '1': ['_ResourceExhaustedError']}
REPL errors: 0
```

---

## 6. Nonexistent Trace Handling

```bash
.venv/bin/python -m rlm_adk.eval.session_report \
  --trace-id does_not_exist \
  --db .adk/traces.db 2>/dev/null \
  | .venv/bin/python -c "
import json, sys
data = json.load(sys.stdin)
print(json.dumps(data, indent=2))
"
```

Expected output:

```json
{
  "overview": {
    "error": "trace_id does_not_exist not found"
  }
}
```

---

## Code Quality Findings

### BUG: Line 142 -- `_query_one(...)["cnt"]` subscripts potentially-None result

**Location**: `session_report.py` line 142-146

```python
"total_tool_calls": _query_one(
    conn,
    "SELECT COUNT(*) AS cnt FROM telemetry WHERE trace_id = ? AND event_type = 'tool_call'",
    (trace_id,),
)["cnt"],
```

**Type-checker diagnosis**: `_query_one` returns `Optional[dict[str, Any]]`. A type checker (Pyright, mypy) flags `["cnt"]` as "Object of type None is not subscriptable."

**Runtime risk**: In practice, `COUNT(*)` always returns exactly one row, so `_query_one` will never return `None` for this query. **However**, if the `telemetry` table does not exist (e.g. the DB only has the `traces` table), `conn.execute()` raises `sqlite3.OperationalError: no such table: telemetry` which propagates as an unhandled crash.

**Fix**: Guard with `_has_table(conn, "telemetry")` before querying, or wrap in a try/except, or use the same pattern as `_build_layer_tree` which tolerates empty results. Apply the same fix to lines 114-121 (token totals) and lines 124-129 (iteration count from SSE).

### Missing: `_has_table` guards in `_build_overview`

Lines 114-146 query `telemetry` and `session_state_events` without checking table existence. Other `_build_*` functions (`_build_layer_tree`, `_build_performance`, `_build_errors`, `_build_repl_outcomes`) also query `telemetry` directly. Only `_build_state_timeline` checks `_has_table` first.

### Missing: Token amplification metric

The performance section does not compute token amplification (input_tokens / output_tokens ratio), which is a key cost diagnostic. This can be added as a derived field in `_build_performance` or left to the consumer.

### Minor: `depth_-1` naming

Agents with unparseable names (workers, parallel agents) fall into `depth_-1`. Consider renaming to `depth_unknown` for clarity in the layer_tree output.

### Minor: REPL p95 > avg anomaly

In the sample trace, REPL p95 (18.9ms) < avg (67.3ms), which indicates a right-skewed distribution with a few very slow outliers. The p95 is computed correctly (from sorted values), but the avg is pulled up by the outliers. This is correct behavior but worth noting for interpretation.
