# SQLite 3-Table Schema Restructuring (Phase 4)

*2026-03-05T18:28:22Z by Showboat 0.6.0*
<!-- showboat-id: 35a8ea2c-c146-4912-b77a-c8a5c7aec296 -->

Restructured SqliteTracingPlugin from a 2-table schema (traces, spans) to a 3-table schema (traces enriched, telemetry, session_state_events). The spans table is retained for backward compatibility but no longer receives writes. All callback write paths now target the new structured tables.

## 1. Three tables created

```bash
.venv/bin/python -c "
from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
import sqlite3, tempfile, os
p = SqliteTracingPlugin(db_path=os.path.join(tempfile.mkdtemp(), 'demo.db'))
conn = sqlite3.connect(str(p._db_path))
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall()]
print('Tables:', tables)
for t in tables:
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info({t})').fetchall()]
    print(f'  {t}: {len(cols)} columns -> {cols}')
conn.close()
"
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
Tables: ['session_state_events', 'spans', 'telemetry', 'traces']
  session_state_events: 14 columns -> ['event_id', 'trace_id', 'seq', 'event_author', 'event_time', 'state_key', 'key_category', 'key_depth', 'key_fanout', 'value_type', 'value_int', 'value_float', 'value_text', 'value_json']
  spans: 10 columns -> ['span_id', 'trace_id', 'parent_span_id', 'operation_name', 'agent_name', 'start_time', 'end_time', 'status', 'attributes', 'events']
  telemetry: 27 columns -> ['telemetry_id', 'trace_id', 'event_type', 'agent_name', 'iteration', 'depth', 'call_number', 'start_time', 'end_time', 'duration_ms', 'model', 'input_tokens', 'output_tokens', 'finish_reason', 'num_contents', 'agent_type', 'prompt_chars', 'system_chars', 'tool_name', 'tool_args_keys', 'result_preview', 'repl_has_errors', 'repl_has_output', 'repl_llm_calls', 'status', 'error_type', 'error_message']
  traces: 28 columns -> ['trace_id', 'session_id', 'user_id', 'app_name', 'start_time', 'end_time', 'status', 'total_input_tokens', 'total_output_tokens', 'total_calls', 'iterations', 'final_answer_length', 'metadata', 'request_id', 'repo_url', 'root_prompt_preview', 'total_execution_time_s', 'child_dispatch_count', 'child_error_counts', 'structured_output_failures', 'finish_safety_count', 'finish_recitation_count', 'finish_max_tokens_count', 'tool_invocation_summary', 'artifact_saves', 'artifact_bytes_saved', 'per_iteration_breakdown', 'model_usage_summary']
```

## 2. Callback write paths updated - telemetry table receives model_call and tool_call rows

```bash
.venv/bin/python -c "
import asyncio, sqlite3, tempfile, os, json
from unittest.mock import MagicMock
from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

db = os.path.join(tempfile.mkdtemp(), 'demo.db')
p = SqliteTracingPlugin(db_path=db)

async def demo():
    ctx = MagicMock()
    ctx.session.id = 'sess_1'
    ctx.session.user_id = 'user_1'
    ctx.app_name = 'demo_app'
    ctx.session.state = {}
    await p.before_run_callback(invocation_context=ctx)

    # Model call
    cb = MagicMock(); cb.state = {'iteration_count': 1}
    req = MagicMock(); req.model = 'gemini-2.5-flash'; req.contents = [1,2,3]
    await p.before_model_callback(callback_context=cb, llm_request=req)

    resp = MagicMock()
    resp.model_version = 'gemini-2.5-flash'
    resp.usage_metadata = MagicMock()
    resp.usage_metadata.prompt_token_count = 200
    resp.usage_metadata.candidates_token_count = 80
    resp.error_code = None
    resp.finish_reason = MagicMock(); resp.finish_reason.name = 'STOP'
    await p.after_model_callback(callback_context=cb, llm_response=resp)

    # Tool call
    tool = MagicMock(); tool.name = 'execute_code'
    tc = MagicMock()
    await p.before_tool_callback(tool=tool, tool_args={'code': 'x=1+1'}, tool_context=tc)
    await p.after_tool_callback(tool=tool, tool_args={'code': 'x=1+1'}, tool_context=tc, result={'output': '2', 'has_errors': False, 'total_llm_calls': 1})

asyncio.run(demo())

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
print('=== telemetry rows ===')
for row in conn.execute('SELECT event_type, model, input_tokens, output_tokens, finish_reason, tool_name, duration_ms, result_preview, repl_llm_calls FROM telemetry'):
    print(dict(row))
print()
print('=== spans rows (should be empty - no writes) ===')
print('count:', conn.execute('SELECT COUNT(*) FROM spans').fetchone()[0])
conn.close()
"
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
=== telemetry rows ===
{'event_type': 'model_call', 'model': 'gemini-2.5-flash', 'input_tokens': 200, 'output_tokens': 80, 'finish_reason': 'STOP', 'tool_name': None, 'duration_ms': 0.9307861328125, 'result_preview': None, 'repl_llm_calls': None}
{'event_type': 'tool_call', 'model': None, 'input_tokens': None, 'output_tokens': None, 'finish_reason': None, 'tool_name': 'execute_code', 'duration_ms': 0.1575946807861328, 'result_preview': "{'output': '2', 'has_errors': False, 'total_llm_calls': 1}", 'repl_llm_calls': 1}

=== spans rows (should be empty - no writes) ===
count: 0
```

## 3. Depth/fanout parsing and session_state_events

```bash
.venv/bin/python -c "
from rlm_adk.plugins.sqlite_tracing import _parse_key, _categorize_key

# Depth/fanout parsing
tests = ['obs:total_calls', 'iteration_count@d2', 'obs:child_summary@d1f0', 'last_repl_result@d3']
for k in tests:
    base, depth, fanout = _parse_key(k)
    cat = _categorize_key(base)
    print(f'{k:40s} -> base={base}, depth={depth}, fanout={fanout}, category={cat}')
"
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
obs:total_calls                          -> base=obs:total_calls, depth=0, fanout=None, category=obs_reasoning
iteration_count@d2                       -> base=iteration_count, depth=2, fanout=None, category=flow_control
obs:child_summary@d1f0                   -> base=obs:child_summary, depth=1, fanout=0, category=obs_dispatch
last_repl_result@d3                      -> base=last_repl_result, depth=3, fanout=None, category=repl
```

## 4. Enriched traces columns populated at run end

```bash
.venv/bin/python -c "
import asyncio, sqlite3, tempfile, os, json
from unittest.mock import MagicMock
from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin

db = os.path.join(tempfile.mkdtemp(), 'demo.db')
p = SqliteTracingPlugin(db_path=db)

async def demo():
    ctx = MagicMock()
    ctx.session.id = 'sess_1'; ctx.session.user_id = 'u1'; ctx.app_name = 'demo'
    ctx.session.state = {}
    await p.before_run_callback(invocation_context=ctx)
    ctx.session.state = {
        'obs:total_input_tokens': 5000, 'obs:total_output_tokens': 2500,
        'obs:total_calls': 10, 'iteration_count': 4,
        'final_answer': 'Done.', 'request_id': 'req-demo-1',
        'repo_url': 'https://github.com/example/repo',
        'root_prompt': 'Analyze this repo',
        'obs:total_execution_time': 25.3,
        'obs:child_dispatch_count': 3,
        'obs:child_error_counts': {'RATE_LIMIT': 1, 'SERVER': 2},
        'obs:structured_output_failures': 1,
        'obs:finish_safety_count': 0, 'obs:finish_recitation_count': 0, 'obs:finish_max_tokens_count': 1,
        'obs:tool_invocation_summary': {'execute_code': 6, 'web_search': 2},
        'obs:artifact_saves': 3, 'obs:artifact_bytes_saved': 4096,
        'obs:per_iteration_token_breakdown': [{'iter': 0, 'in': 1000, 'out': 500}],
        'obs:model_usage:gemini-2.5-flash': {'calls': 8, 'input_tokens': 4000, 'output_tokens': 2000},
        'obs:model_usage:gemini-2.5-pro': {'calls': 2, 'input_tokens': 1000, 'output_tokens': 500},
    }
    await p.after_run_callback(invocation_context=ctx)

asyncio.run(demo())

conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
row = conn.execute('SELECT request_id, repo_url, total_execution_time_s, child_dispatch_count, child_error_counts, tool_invocation_summary, model_usage_summary FROM traces').fetchone()
for k in row.keys():
    v = row[k]
    if isinstance(v, str) and v.startswith('{'):
        v = json.loads(v)
    print(f'  {k}: {v}')
conn.close()
"
```

```output
/home/rawley-stanhope/dev/rlm-adk/.venv/lib/python3.12/site-packages/requests/__init__.py:113: RequestsDependencyWarning: urllib3 (2.6.2) or chardet (6.0.0.post1)/charset_normalizer (3.4.4) doesn't match a supported version!
  warnings.warn(
  request_id: req-demo-1
  repo_url: https://github.com/example/repo
  total_execution_time_s: 25.3
  child_dispatch_count: 3
  child_error_counts: {'RATE_LIMIT': 1, 'SERVER': 2}
  tool_invocation_summary: {'execute_code': 6, 'web_search': 2}
  model_usage_summary: {'gemini-2.5-flash': {'calls': 8, 'input_tokens': 4000, 'output_tokens': 2000}, 'gemini-2.5-pro': {'calls': 2, 'input_tokens': 1000, 'output_tokens': 500}}
```

## 5. All tests pass (36 tests: 13 new 3-table + 23 updated existing)

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_sqlite_3table.py tests_rlm_adk/test_adk_plugins_sqlite_tracing.py --noconftest -v 2>&1 | grep -E '(PASSED|FAILED|passed|failed)'
```

```output
tests_rlm_adk/test_sqlite_3table.py::TestTelemetryTableExists::test_telemetry_table_exists PASSED [  2%]
tests_rlm_adk/test_sqlite_3table.py::TestSessionStateEventsTableExists::test_session_state_events_table_exists PASSED [  5%]
tests_rlm_adk/test_sqlite_3table.py::TestTelemetryColumns::test_telemetry_columns PASSED [  8%]
tests_rlm_adk/test_sqlite_3table.py::TestSessionStateEventsColumns::test_session_state_events_columns PASSED [ 11%]
tests_rlm_adk/test_sqlite_3table.py::TestTracesEnrichedColumns::test_traces_enriched_columns PASSED [ 13%]
tests_rlm_adk/test_sqlite_3table.py::TestBeforeModelWritesTelemetry::test_before_model_writes_telemetry PASSED [ 16%]
tests_rlm_adk/test_sqlite_3table.py::TestAfterModelUpdatesTelemetry::test_after_model_updates_telemetry PASSED [ 19%]
tests_rlm_adk/test_sqlite_3table.py::TestBeforeToolWritesTelemetry::test_before_tool_writes_telemetry PASSED [ 22%]
tests_rlm_adk/test_sqlite_3table.py::TestAfterToolUpdatesTelemetry::test_after_tool_updates_telemetry PASSED [ 25%]
tests_rlm_adk/test_sqlite_3table.py::TestOnEventWritesSessionStateEvents::test_on_event_writes_session_state_events PASSED [ 27%]
tests_rlm_adk/test_sqlite_3table.py::TestDepthKeyParsing::test_depth_key_parsing PASSED [ 30%]
tests_rlm_adk/test_sqlite_3table.py::TestFanoutKeyParsing::test_fanout_key_parsing PASSED [ 33%]
tests_rlm_adk/test_sqlite_3table.py::TestAfterRunEnrichedTraces::test_after_run_enriched_traces PASSED [ 36%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestSchemaCreation::test_schema_creation PASSED [ 38%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestSchemaCreation::test_wal_mode_enabled PASSED [ 41%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestSchemaCreation::test_traces_table_has_enriched_columns PASSED [ 44%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestSchemaCreation::test_spans_table_columns PASSED [ 47%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestTraceLifecycle::test_before_run_creates_trace PASSED [ 50%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestTraceLifecycle::test_after_run_updates_trace PASSED [ 52%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestAgentCallbacks::test_before_agent_pushes_name PASSED [ 55%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestAgentCallbacks::test_after_agent_pops_name PASSED [ 58%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestModelTelemetry::test_before_model_creates_telemetry PASSED [ 61%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestModelTelemetry::test_after_model_updates_telemetry PASSED [ 63%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestModelTelemetry::test_model_error_marks_telemetry_error PASSED [ 66%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestToolTelemetry::test_before_tool_creates_telemetry PASSED [ 69%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestToolTelemetry::test_after_tool_updates_telemetry PASSED [ 72%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestEventCallback::test_on_event_artifact_delta PASSED [ 75%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestEventCallback::test_on_event_without_artifact_delta_no_sse PASSED [ 77%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestAgentNameInTelemetry::test_model_telemetry_captures_agent_name PASSED [ 80%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestAgentNameInTelemetry::test_nested_agent_captures_innermost_name PASSED [ 83%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestDirectoryCreation::test_db_path_directory_creation PASSED [ 86%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestCallbackReturnValues::test_all_callbacks_return_none PASSED [ 88%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestErrorResilience::test_db_error_does_not_crash PASSED [ 91%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestErrorResilience::test_close_closes_connection PASSED [ 94%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestErrorResilience::test_close_idempotent PASSED [ 97%]
tests_rlm_adk/test_adk_plugins_sqlite_tracing.py::TestErrorResilience::test_callbacks_after_close_do_not_crash PASSED [100%]
======================== 36 passed, 1 warning in 10.56s ========================
```
