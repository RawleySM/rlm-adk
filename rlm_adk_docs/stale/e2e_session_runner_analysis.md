# E2E Session & Runner Analysis

## 1. Session Lifecycle

**File**: `tests_rlm_adk/test_provider_fake_e2e.py` (lines 35-79)
**File**: `tests_rlm_adk/provider_fake/contract_runner.py` (lines 69-147)

### Session Creation
- `InMemorySessionService()` instantiated (line 50)
- `await session_service.create_session(app_name="rlm_adk", user_id="test-user")`
- Session has immutable `.id`, `.user_id`; mutable `session.state` dict

### Session Access During Run
- Runner accepts `user_id`, `session_id`, `new_message` (Content object)
- `runner.run_async()` is async generator yielding `Event` objects
- Final state refetch via `runner.session_service.get_session(app_name, user_id, session_id)`
- All state mutations propagate via `Event` objects with `state_delta`

### Key State Keys (from `rlm_adk/state.py`)
- `FINAL_ANSWER`: Terminal condition marker
- `LAST_REPL_RESULT`: Dict snapshot of REPL execution state
- `ITERATION_COUNT`: Counter for loop iterations
- `MESSAGE_HISTORY`: Accumulated conversation history
- `WORKER_EVENTS_DRAINED`: Count of worker event yields
- Worker accounting: `WORKER_DISPATCH_COUNT`, `WORKER_INPUT_TOKENS`, `WORKER_OUTPUT_TOKENS`, etc.

---

## 2. Runner Utilization

**File**: `tests_rlm_adk/test_provider_fake_e2e.py` (lines 41-57)

```python
app = create_rlm_app(
    model=os.environ.get("RLM_ADK_MODEL", "gemini-fake"),
    thinking_budget=0,       # determinism
    debug=False,             # no DebugLoggingPlugin
    langfuse=False,
    sqlite_tracing=False,
)
session_service = InMemorySessionService()
runner = Runner(app=app, session_service=session_service)
```

### Runner Lifecycle
1. **Setup**: App instantiated with plugins/callbacks
2. **Invocation**: `runner.run_async(user_id, session_id, new_message)`
3. **Event loop**: Yields events until FINAL_ANSWER or max_iterations
4. **Cleanup**: Session persists in service; state queryable post-run

### Critical Invariant (ADK Contract)
- All state mutations MUST be via `Event(actions=EventActions(state_delta={...}))`
- Direct writes to `ctx.session.state[key]` bypass event tracking

---

## 3. Event Stream Structure

**File**: `rlm_adk/orchestrator.py` (lines 161-400)

### Event Fields
- `invocation_id`: Unique run identifier
- `author`: Agent name (e.g., `"rlm_orchestrator"`, `"worker_1"`, `"dispatch"`)
- `actions.state_delta`: Dict of key-value mutations to commit
- `actions.artifact_delta`: Artifact version tracking
- `actions.end_of_agent`: Signals agent completion
- `content`: Optional `types.Content`
- `timestamp`: Float unix timestamp

### Event Generation Points (7 total)
1. **Initial state** (line 161-165): REQUEST_ID, MESSAGE_HISTORY
2. **Pre-reasoning** (line 180-186): Updates MESSAGE_HISTORY
3. **Post-reasoning** (yielded by reasoning_agent.run_async)
4. **Worker drain** (line 214-228): Drains event_queue, emits sync-point
5. **Mid-iteration drain** (line 301-318): Events from REPL code execution
6. **Iteration end** (line 386-400): LAST_REPL_RESULT snapshot
7. **Final answer** (line 351-368): FINAL_ANSWER + content event

### Data Flow Diagram
```
Runner.run_async()
  └─ Orchestrator._run_async_impl()
       for i in range(max_iterations):
         yield Event(state_delta={ITERATION_COUNT, ...})
         yield Event(state_delta={MESSAGE_HISTORY})
         await reasoning_agent.run_async(ctx)
           async for event: yield event    ◄── reasoning events
         while not event_queue.empty():
           yield event_queue.get_nowait()  ◄── worker events
         # Execute REPL code (may call llm_query_async)
         # Drain mid-iteration worker events
         yield Event(state_delta={LAST_REPL_RESULT: {
           code_blocks, has_output, has_errors, total_llm_calls
         }})
         if FINAL_ANSWER found:
           yield Event(state_delta={FINAL_ANSWER, ...})
           yield Event(content=...)        ◄── final response
           return
```

---

## 4. REPL Introspection & Snapshot Data

**File**: `tests_rlm_adk/test_provider_fake_e2e.py` (lines 414-429)

### `_extract_repl_events()` Function
```python
def _extract_repl_events(events):
    repl_snapshots = []
    worker_event_count = 0
    for event in events:
        sd = getattr(getattr(event, "actions", None), "state_delta", None) or {}
        if LAST_REPL_RESULT in sd:
            repl_snapshots.append(sd[LAST_REPL_RESULT])
        if getattr(event, "author", "").startswith("worker_"):
            worker_event_count += 1
    return repl_snapshots, worker_event_count
```

### REPL Snapshot Structure (from orchestrator.py lines 391-398)
```python
{
  "code_blocks": int,         # number of code blocks executed
  "has_output": bool,         # stdout present in any block
  "has_errors": bool,         # stderr present in any block
  "total_llm_calls": int,     # total worker dispatch calls in iteration
}
```

### Test Assertions (lines 511-564)
1. Model calls match fixture expectations
2. Worker-authored events present (author starts with `"worker_"`)
3. At least one iteration with code blocks
4. Total LLM calls > 0 (worker dispatch succeeded)
5. Either clean output OR worker calls succeeded
6. Final answer matches expected value

---

## 5. Contract Runner Framework

**File**: `tests_rlm_adk/provider_fake/contract_runner.py` (lines 113-147)

```python
async def run_fixture_contract(fixture_path: Path):
    router = ScenarioRouter.from_file(fixture_path)
    server = FakeGeminiServer(router=router, ...)
    try:
        base_url = await server.start()
        _set_env(base_url, router)
        runner, session = await _make_runner_and_session(router)
        final_state = await _run_to_completion(runner, session, "test prompt")
        return router.check_expectations(final_state, fixture_path, elapsed)
    finally:
        await server.stop()
        _restore_env(saved)
```

### Contract Validation (fixtures.py lines 203-260)
- Checks: `final_answer`, `total_iterations`, `total_model_calls`
- Returns `ContractResult(passed, checks, call_summary, total_elapsed_s)`
- `diagnostics()` method for human-readable report

---

## 6. Fixture Data Flow

### Fixture JSON Schema
```json
{
  "scenario_id": "string",
  "description": "string",
  "config": { "model", "thinking_budget", "max_iterations", "retry_delay" },
  "responses": [
    { "call_index": 0, "caller": "reasoning|worker", "status": 200, "body": {...} }
  ],
  "fault_injections": [
    { "call_index": 0, "fault_type": "malformed_json|http_error", ... }
  ],
  "expected": { "final_answer": "42", "total_iterations": 1, "total_model_calls": 1 }
}
```

### ScenarioRouter Behavior (fixtures.py lines 79-268)
- Thread-safe FIFO with `_call_index` counter
- Fault injection overlay: checks `_faults[call_index]` before normal response
- Request logging: `call_index`, `has_system_instruction`, `contents_count`, `model`, `first_content_preview`
- Exhaustion fallback: returns `FINAL(fixture-exhausted)` if responses run out

### FakeGeminiServer Handler (server.py lines 75-117)
- Validates `x-goog-api-key` header
- Parses request JSON, calls `router.next_response(body, request_meta)`
- Handles malformed JSON fault via `_raw` sentinel

---

## 7. Dispatch Architecture

**File**: `rlm_adk/dispatch.py` (lines 51-424)

### WorkerPool
- Pre-allocated per-model pools (asyncio.Queue)
- On-demand creation if pool exhausted (deadlock prevention)
- Pool size capped; excess workers discarded on release

### Dispatch Closures (lines 205-424)
- `llm_query_async(prompt, model)` → delegates to batched
- `llm_query_batched_async(prompts, model)`:
  1. Chunk prompts into batches of `RLM_MAX_CONCURRENT_WORKERS` (default 4)
  2. Acquire workers, set `_pending_prompt`, dispatch via `ParallelAgent`
  3. Read results from `worker._result` (object carrier, not dirty state)
  4. Accumulate call records to `call_log_sink` for REPL telemetry
  5. Reset `worker.parent_agent = None`, release to pool

---

## 8. Callback & Plugin Telemetry

### Worker Callbacks (`rlm_adk/callbacks/worker.py`)
| Callback | Lines | Action |
|----------|-------|--------|
| `worker_before_model` | 20-68 | Injects `_pending_prompt` into `llm_request.contents` |
| `worker_after_model` | 71-116 | Extracts response, writes `_result`, `_result_ready`, `_call_record` |
| `worker_on_model_error` | 119+ | Graceful error isolation, writes error result |

### ObservabilityPlugin (`rlm_adk/plugins/observability.py`)
- Tracks: `INVOCATION_START_TIME`, token counts, iteration times
- Always enabled, observe-only (never blocks)

### SqliteTracingPlugin (`rlm_adk/plugins/sqlite_tracing.py`)
- Writes `traces` + `spans` tables to `.adk/traces.db`
- Indexed on trace_id, operation, session_id, start_time

---

## 9. Proposed REPL Trace Persistence Solution

### Recommendation: ADK Artifact System + REPLTracingPlugin

**Format**: JSON (human-readable, embeddable in artifacts)
**Storage**: ADK `FileArtifactService` with versioning
**Filename pattern**: `repl_trace_iter_{iteration}.json`

### Trace Schema
```json
{
  "iteration": 0,
  "timestamp": 1708957234.123,
  "code_blocks": [
    {
      "index": 0,
      "code": "result = llm_query('...')",
      "execution_time_ms": 145.2,
      "stdout": "output text",
      "stderr": "",
      "has_errors": false,
      "llm_calls": [
        {
          "prompt": "...",
          "response": "...",
          "model": "gemini-fake",
          "input_tokens": 50,
          "output_tokens": 20,
          "execution_time_ms": 142.1
        }
      ]
    }
  ],
  "total_execution_time_ms": 145.2,
  "total_llm_calls": 1,
  "has_output": true,
  "has_errors": false,
  "final_answer": null
}
```

### Implementation Steps

1. **Create `rlm_adk/plugins/repl_tracing.py`**: Listen to `LAST_REPL_RESULT` state deltas, save JSON artifacts per iteration
2. **Extend `REPLResult`** (`rlm_adk/types.py`): Add `execution_time_ms`, ensure `llm_calls` field
3. **Instrument `LocalREPL`** (`rlm_adk/repl/local_repl.py`): Track code block execution time
4. **Add query utilities** (`rlm_adk/observability/repl_query.py`): `get_repl_traces()`, `compare_repl_snapshots()`
5. **Extend `contract_runner.py`**: Load REPL traces from artifacts post-run, expose in `ContractResult`

### Benefits
| Aspect | Solution |
|--------|----------|
| Persistence | ADK artifact system (auto-versioned, scoped) |
| Queryability | JSON + utility functions; integrates with test framework |
| Debugging | Full code + llm_calls + execution times in one place |
| Integration | Plugin-based, alongside Langfuse/SQLite |
| Non-invasive | No core orchestrator changes; optional via plugin registration |

---

## Key Files & Line Numbers

| Component | File | Lines |
|-----------|------|-------|
| Session lifecycle | test_provider_fake_e2e.py | 35-79 |
| Event stream | orchestrator.py | 161-400 |
| REPL introspection | test_provider_fake_e2e.py | 414-564 |
| Contract runner | contract_runner.py | 113-147 |
| Fixture router | fixtures.py | 79-268 |
| Fake server | server.py | 20-118 |
| Worker pool | dispatch.py | 51-203 |
| Dispatch closures | dispatch.py | 205-424 |
| Worker callbacks | callbacks/worker.py | 20-142+ |
| State keys | state.py | 1-135 |
| REPL types | types.py | 1-80+ |
| AST rewriter | repl/ast_rewriter.py | 1-200+ |
| Artifacts | artifacts.py | 1-120+ |
| Plugins | plugins/*.py | Various |
