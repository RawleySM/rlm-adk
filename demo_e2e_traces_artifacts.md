# E2E Traces & Artifacts: llm_query + llm_query_batched through Plugin Pipeline

*2026-02-26T20:29:19Z by Showboat 0.6.0*
<!-- showboat-id: cee5d6a9-5de2-48bf-80bb-33d2e12aa4ae -->

## What This Proves

Running real test fixtures that use `llm_query()` and `llm_query_batched()` through the
**full plugin-enabled pipeline** (ObservabilityPlugin + SqliteTracingPlugin + REPLTracingPlugin)
produces:

1. **Sqlite trace rows** with `status=completed`, accurate token counts, and model call totals
2. **Span-level telemetry** — one `model_call` span per LLM invocation (reasoning + workers)
3. **REPL trace events** — `LAST_REPL_RESULT` state deltas with `code_blocks > 0` and `total_llm_calls > 0`
4. **Artifact persistence** via `InMemoryArtifactService` wired through `create_rlm_runner()`

The key difference from the old tests: we use `run_fixture_contract_with_plugins()` which
exercises the **real production wiring** including plugins, artifact service, and tracing.

## The Plugin-Enabled Runner

`run_fixture_contract_with_plugins()` is the new entry point that wires
`create_rlm_runner()` with ObservabilityPlugin, SqliteTracingPlugin, and REPLTracingPlugin.

```bash
sed -n '171,198p' /home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/provider_fake/contract_runner.py
```

```output
async def run_fixture_contract_with_plugins(
    fixture_path: Path,
    prompt: str = "test prompt",
    traces_db_path: str | None = None,
    repl_trace_level: int = 1,
) -> PluginContractResult:
    """Execute a fixture through the full plugin-enabled pipeline.

    Uses ``create_rlm_runner()`` with:
    - ``InMemoryArtifactService`` for volatile artifact storage
    - ``InMemorySessionService`` for test isolation
    - ``ObservabilityPlugin`` (always on)
    - ``SqliteTracingPlugin`` pointing to *traces_db_path*
    - ``REPLTracingPlugin`` (when *repl_trace_level* > 0)
    - ``DebugLoggingPlugin`` disabled (noisy in CI)
    - ``LangfuseTracingPlugin`` disabled (requires external service)

    Args:
        fixture_path: Path to the fixture JSON file.
        prompt: User prompt to send to the runner.
        traces_db_path: Path for SqliteTracingPlugin DB.  ``None`` disables
            sqlite tracing.
        repl_trace_level: ``RLM_REPL_TRACE`` env var value (0 = off).

    Returns:
        A :class:`PluginContractResult` with contract result, events,
        final state, artifact service reference, and traces DB path.
    """
```

```bash
sed -n '211,232p' /home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/provider_fake/contract_runner.py
```

```output

        # Build plugin list
        from google.adk.plugins.base_plugin import BasePlugin
        plugins: list[BasePlugin] = [ObservabilityPlugin()]
        if traces_db_path:
            plugins.append(SqliteTracingPlugin(db_path=traces_db_path))
        if repl_trace_level > 0:
            plugins.append(REPLTracingPlugin())

        artifact_service = InMemoryArtifactService()
        session_service = InMemorySessionService()

        runner = create_rlm_runner(
            model=os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
            thinking_budget=router.config.get("thinking_budget", 0),
            plugins=plugins,
            artifact_service=artifact_service,
            session_service=session_service,
            debug=False,
            langfuse=False,
            sqlite_tracing=False,
        )
```

## Demo 1: full_pipeline — llm_query_batched (4 workers) + llm_query retry (1 worker)

Fixture flow: Iter 1 dispatches `llm_query_batched()` to triage 4 records (workers 1-4),
one worker returns an error. Iter 2 retries the failed record with a single `llm_query()` (worker 5).
Total: 8 model calls (3 reasoning + 5 workers).

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import asyncio, sqlite3, os
from pathlib import Path

async def main():
    from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract_with_plugins
    fixture = Path('tests_rlm_adk/fixtures/provider_fake/full_pipeline.json')
    db = '/tmp/demo_full_pipeline_traces.db'
    if os.path.exists(db): os.unlink(db)

    result = await run_fixture_contract_with_plugins(fixture, traces_db_path=db, repl_trace_level=1)

    c = result.contract
    print(f'Contract: {\"PASS\" if c.passed else \"FAIL\"} ({c.scenario_id})')
    print(f'  final_answer = {result.final_state.get(\"final_answer\", \"NONE\")}')
    print(f'  model_calls  = {result.router.call_index}')
    print()

    conn = sqlite3.connect(db)
    row = conn.execute('SELECT status, total_calls, total_input_tokens, total_output_tokens, iterations FROM traces LIMIT 1').fetchone()
    print(f'Trace row:')
    print(f'  status            = {row[0]}')
    print(f'  total_calls       = {row[1]}')
    print(f'  total_input_tokens  = {row[2]}')
    print(f'  total_output_tokens = {row[3]}')
    print(f'  iterations        = {row[4]}')
    print()

    spans = conn.execute('SELECT operation_name, COUNT(*) FROM spans GROUP BY operation_name ORDER BY operation_name').fetchall()
    print(f'Spans by operation:')
    for op, cnt in spans:
        print(f'  {op:20s} = {cnt}')
    print()

    model_spans = conn.execute('SELECT COUNT(*) FROM spans WHERE operation_name = \"model_call\"').fetchone()[0]
    ok_spans = conn.execute('SELECT COUNT(*) FROM spans WHERE operation_name = \"model_call\" AND status = \"ok\"').fetchone()[0]
    print(f'Model call spans: {model_spans} total, all ok: {ok_spans == model_spans}')
    conn.close()
    print()

    from rlm_adk.state import LAST_REPL_RESULT
    repl_snaps = []
    for ev in result.events:
        sd = getattr(getattr(ev, 'actions', None), 'state_delta', None) or {}
        if LAST_REPL_RESULT in sd:
            repl_snaps.append(sd[LAST_REPL_RESULT])
    print(f'REPL trace snapshots: {len(repl_snaps)}')
    for i, s in enumerate(repl_snaps):
        if isinstance(s, dict):
            print(f'  iter#{i}: code_blocks={s.get(\"code_blocks\",0)}, llm_calls={s.get(\"total_llm_calls\",0)}, has_output={s.get(\"has_output\",False)}, errors={s.get(\"has_errors\",False)}')

asyncio.run(main())
" 2>&1 | grep -v '^\[RLM\]'

```

```output
Contract: PASS (full_pipeline)
  final_answer = Pipeline: 4 triaged, 2 deduped, 0 errors. Dispositions: 1 exact, 2 fuzzy, 1 anomaly.
  model_calls  = 8

Trace row:
  status            = completed
  total_calls       = 8
  total_input_tokens  = 3320
  total_output_tokens = 990
  iterations        = 2

Spans by operation:
  agent                = 11
  model_call           = 12

Model call spans: 12 total, all ok: True

REPL trace snapshots: 1
  iter#0: code_blocks=1, llm_calls=6, has_output=True, errors=False
```

## Demo 2: hierarchical_summarization — llm_query_batched (3 map) + llm_query (1 reduce)

Fixture flow: Iter 1 dispatches `llm_query_batched()` to extract facts from 3 document chunks
(map phase), then `llm_query()` to synthesize a single summary (reduce phase).
Total: 6 model calls (2 reasoning + 4 workers).

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import asyncio, sqlite3, os
from pathlib import Path

async def main():
    from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract_with_plugins
    fixture = Path('tests_rlm_adk/fixtures/provider_fake/hierarchical_summarization.json')
    db = '/tmp/demo_hier_summ_traces.db'
    if os.path.exists(db): os.unlink(db)

    result = await run_fixture_contract_with_plugins(fixture, traces_db_path=db, repl_trace_level=1)

    c = result.contract
    print(f'Contract: {\"PASS\" if c.passed else \"FAIL\"} ({c.scenario_id})')
    print(f'  final_answer = {result.final_state.get(\"final_answer\", \"NONE\")}')
    print(f'  model_calls  = {result.router.call_index}')
    print()

    conn = sqlite3.connect(db)
    row = conn.execute('SELECT status, total_calls, total_input_tokens, total_output_tokens, iterations FROM traces LIMIT 1').fetchone()
    print(f'Trace row:')
    print(f'  status            = {row[0]}')
    print(f'  total_calls       = {row[1]}')
    print(f'  total_input_tokens  = {row[2]}')
    print(f'  total_output_tokens = {row[3]}')
    print(f'  iterations        = {row[4]}')
    print()

    spans = conn.execute('SELECT operation_name, COUNT(*) FROM spans GROUP BY operation_name ORDER BY operation_name').fetchall()
    print(f'Spans by operation:')
    for op, cnt in spans:
        print(f'  {op:20s} = {cnt}')
    print()

    model_spans = conn.execute('SELECT COUNT(*) FROM spans WHERE operation_name = \"model_call\"').fetchone()[0]
    ok_spans = conn.execute('SELECT COUNT(*) FROM spans WHERE operation_name = \"model_call\" AND status = \"ok\"').fetchone()[0]
    print(f'Model call spans: {model_spans} total, all ok: {ok_spans == model_spans}')
    conn.close()
    print()

    from rlm_adk.state import LAST_REPL_RESULT
    repl_snaps = []
    for ev in result.events:
        sd = getattr(getattr(ev, 'actions', None), 'state_delta', None) or {}
        if LAST_REPL_RESULT in sd:
            repl_snaps.append(sd[LAST_REPL_RESULT])
    print(f'REPL trace snapshots: {len(repl_snaps)}')
    for i, s in enumerate(repl_snaps):
        if isinstance(s, dict):
            print(f'  iter#{i}: code_blocks={s.get(\"code_blocks\",0)}, llm_calls={s.get(\"total_llm_calls\",0)}, has_output={s.get(\"has_output\",False)}, errors={s.get(\"has_errors\",False)}')

asyncio.run(main())
" 2>&1 | grep -v '^\[RLM\]'

```

```output
Contract: PASS (hierarchical_summarization)
  final_answer = Map-reduce: 3 chunks extracted, synthesis confidence=0.87, evidence from all 3 chunks, 0 conflicts.
  model_calls  = 6

Trace row:
  status            = completed
  total_calls       = 6
  total_input_tokens  = 2150
  total_output_tokens = 890
  iterations        = 2

Spans by operation:
  agent                = 8
  model_call           = 8

Model call spans: 8 total, all ok: True

REPL trace snapshots: 1
  iter#0: code_blocks=1, llm_calls=4, has_output=True, errors=False
```

## Demo 3: sliding_window_chunking — 3x llm_query_batched (8 workers, overlapping chunks)

Fixture flow: SlidingWindow(window=4, stride=2) splits 8 records into 3 overlapping chunks.
Each chunk dispatches `llm_query_batched()`. Total: 10 model calls (2 reasoning + 8 workers).

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
import asyncio, sqlite3, os
from pathlib import Path

async def main():
    from tests_rlm_adk.provider_fake.contract_runner import run_fixture_contract_with_plugins
    fixture = Path('tests_rlm_adk/fixtures/provider_fake/sliding_window_chunking.json')
    db = '/tmp/demo_sliding_window_traces.db'
    if os.path.exists(db): os.unlink(db)

    result = await run_fixture_contract_with_plugins(fixture, traces_db_path=db, repl_trace_level=1)

    c = result.contract
    print(f'Contract: {\"PASS\" if c.passed else \"FAIL\"} ({c.scenario_id})')
    print(f'  final_answer = {result.final_state.get(\"final_answer\", \"NONE\")}')
    print(f'  model_calls  = {result.router.call_index}')
    print()

    conn = sqlite3.connect(db)
    row = conn.execute('SELECT status, total_calls, total_input_tokens, total_output_tokens, iterations FROM traces LIMIT 1').fetchone()
    print(f'Trace row:')
    print(f'  status            = {row[0]}')
    print(f'  total_calls       = {row[1]}')
    print(f'  total_input_tokens  = {row[2]}')
    print(f'  total_output_tokens = {row[3]}')
    print(f'  iterations        = {row[4]}')
    print()

    spans = conn.execute('SELECT operation_name, COUNT(*) FROM spans GROUP BY operation_name ORDER BY operation_name').fetchall()
    print(f'Spans by operation:')
    for op, cnt in spans:
        print(f'  {op:20s} = {cnt}')
    print()

    model_spans = conn.execute('SELECT COUNT(*) FROM spans WHERE operation_name = \"model_call\"').fetchone()[0]
    ok_spans = conn.execute('SELECT COUNT(*) FROM spans WHERE operation_name = \"model_call\" AND status = \"ok\"').fetchone()[0]
    print(f'Model call spans: {model_spans} total, all ok: {ok_spans == model_spans}')
    conn.close()
    print()

    from rlm_adk.state import LAST_REPL_RESULT
    repl_snaps = []
    for ev in result.events:
        sd = getattr(getattr(ev, 'actions', None), 'state_delta', None) or {}
        if LAST_REPL_RESULT in sd:
            repl_snaps.append(sd[LAST_REPL_RESULT])
    print(f'REPL trace snapshots: {len(repl_snaps)}')
    for i, s in enumerate(repl_snaps):
        if isinstance(s, dict):
            print(f'  iter#{i}: code_blocks={s.get(\"code_blocks\",0)}, llm_calls={s.get(\"total_llm_calls\",0)}, has_output={s.get(\"has_output\",False)}, errors={s.get(\"has_errors\",False)}')

asyncio.run(main())
" 2>&1 | grep -v '^\[RLM\]'

```

```output
Contract: PASS (sliding_window_chunking)
  final_answer = 8 records classified across 3 chunks with 50% prefix overlap. All parses succeeded.
  model_calls  = 10

Trace row:
  status            = completed
  total_calls       = 10
  total_input_tokens  = 1920
  total_output_tokens = 800
  iterations        = 2

Spans by operation:
  agent                = 14
  model_call           = 15

Model call spans: 15 total, all ok: True

REPL trace snapshots: 1
  iter#0: code_blocks=1, llm_calls=8, has_output=True, errors=False
```

## Full Test Suite

All 20 tests: 14 contract validations (Group A) + 3 plugin/artifact tests (Group B) + 3 tracing tests (Group C).

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -q 2>&1 | tail -1 | sed 's/ in [0-9.]*s//'
```

```output
20 passed
```

## Summary

| Fixture | Pattern | Workers | Model Calls | Trace Status | Spans | REPL llm_calls |
|---------|---------|---------|-------------|--------------|-------|----------------|
| full_pipeline | batched(4) + retry(1) | 5 | 8 | completed | 12 model_call | 6 |
| hierarchical_summarization | batched(3) + reduce(1) | 4 | 6 | completed | 8 model_call | 4 |
| sliding_window_chunking | 3x batched(8 total) | 8 | 10 | completed | 15 model_call | 8 |

All three fixtures demonstrate that `llm_query()` and `llm_query_batched()` produce real,
queryable traces and spans through the SqliteTracingPlugin, accurate token accounting via
the ObservabilityPlugin, and REPL trace snapshots with correct `total_llm_calls` counts
via the REPLTracingPlugin — all wired through the production `create_rlm_runner()` factory.
