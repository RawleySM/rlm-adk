# Child Event Re-Emission via Queue

*2026-03-21T18:10:55Z by Showboat 0.6.1*
<!-- showboat-id: 0aca5969-2d63-4520-8ff0-fdeb4f3f9c41 -->

## Problem

The RLM architecture dispatches recursive child `RLMOrchestratorAgent`s via `llm_query()` calls in REPL code. These children yield ADK events internally, but the call stack from child to Runner is non-generator -- events cannot yield through it. Result: **child state events were silenced**. The `session_state_events` table in `traces.db` had zero rows with `key_depth > 0`, making recursive cognitive work invisible to observability.

## Solution: asyncio.Queue Bridge

An `asyncio.Queue` bridges the gap between dispatch (where child events are produced) and the orchestrator's yield loop (where events reach the Runner).

    dispatch._run_child()                    orchestrator._run_async_impl()
      async for _event in child.run_async:     async for event in reasoning_agent.run_async:
        if curated state-delta:                    yield event
          queue.put_nowait(event)  ------>         while not queue.empty():
                                                       yield queue.get_nowait()

Causal ordering is natural: child events accumulate during tool execution, drain after the tool-response event, and appear before the next LLM call.

## Files Modified

| File | Change |
|---|---|
| `rlm_adk/state.py` | `parse_depth_key`, `should_capture_state_key`, `CURATED_STATE_KEYS`, `CURATED_STATE_PREFIXES` |
| `rlm_adk/dispatch.py` | Accept `child_event_queue`, push curated events in `_run_child` loop |
| `rlm_adk/orchestrator.py` | Create `asyncio.Queue`, pass to dispatch, drain after each yield |
| `rlm_adk/plugins/sqlite_tracing.py` | Import from `state.py`, remove duplicated definitions |
| `tests_rlm_adk/test_child_event_reemission.py` | 6 tests (25 unit + 4 e2e) |
| `rlm_adk_docs/dispatch_and_state.md` | Document child event re-emission |
| `rlm_adk_docs/observability.md` | Document `key_depth > 0` in `session_state_events` |

## Key Design Decisions

- **`put_nowait` not `await put`**: Queue is unbounded, never blocks. Child events are finite per run, so no backpressure concern. Avoids introducing an `await` point inside the synchronous-looking dispatch path.
- **Curated filter**: Only observability-relevant keys pass through (iteration counts, REPL results, stop decisions). Prevents noise from internal bookkeeping keys flooding the parent event stream.
- **`custom_metadata` tagging**: Each re-emitted event carries `rlm_child_event: True`, `child_depth`, and `child_fanout_idx` for downstream consumers (SqliteTracingPlugin, dashboards) to distinguish child events from parent events.
- **Final drain**: A second drain loop after the retry loop covers the edge case where the last tool call produces child events but `reasoning_agent` terminates without yielding another event.

## Verification: Unit Tests (parse_depth_key, should_capture_state_key, queue filter)

25 unit tests covering key parsing round-trips, curated key acceptance/rejection, and queue population logic.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_child_event_reemission.py -v -m "unit_nondefault" 2>&1 | grep -E "(PASSED|FAILED|ERROR)" | head -30
```

```output
tests_rlm_adk/test_child_event_reemission.py::TestParseDepthKey::test_depth_zero_roundtrip PASSED [  4%]
tests_rlm_adk/test_child_event_reemission.py::TestParseDepthKey::test_depth_nonzero_roundtrip PASSED [  8%]
tests_rlm_adk/test_child_event_reemission.py::TestParseDepthKey::test_fanout_parsing PASSED [ 12%]
tests_rlm_adk/test_child_event_reemission.py::TestParseDepthKey::test_plain_key_no_suffix PASSED [ 16%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_exact_curated_keys_accepted[current_depth] PASSED [ 20%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_exact_curated_keys_accepted[iteration_count] PASSED [ 24%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_exact_curated_keys_accepted[should_stop] PASSED [ 28%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_exact_curated_keys_accepted[final_response_text] PASSED [ 32%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_exact_curated_keys_accepted[last_repl_result] PASSED [ 36%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_exact_curated_keys_accepted[skill_instruction] PASSED [ 40%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_prefix_curated_keys_accepted[obs:artifact_save_count] PASSED [ 44%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_prefix_curated_keys_accepted[artifact_final_answer] PASSED [ 48%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_prefix_curated_keys_accepted[last_repl_result] PASSED [ 52%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_prefix_curated_keys_accepted[repl_submitted_code] PASSED [ 56%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_prefix_curated_keys_accepted[repl_expanded_code] PASSED [ 60%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_prefix_curated_keys_accepted[repl_skill_expansion_meta] PASSED [ 64%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_prefix_curated_keys_accepted[repl_did_expand] PASSED [ 68%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_non_curated_keys_rejected[request_id] PASSED [ 72%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_non_curated_keys_rejected[obs:total_calls] PASSED [ 76%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_non_curated_keys_rejected[obs:rewrite_count] PASSED [ 80%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_non_curated_keys_rejected[cache:store] PASSED [ 84%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_non_curated_keys_rejected[user:last_successful_call_id] PASSED [ 88%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_non_curated_keys_rejected[app:max_depth] PASSED [ 92%]
tests_rlm_adk/test_child_event_reemission.py::TestShouldCaptureStateKey::test_non_curated_keys_rejected[some_random_key] PASSED [ 96%]
tests_rlm_adk/test_child_event_reemission.py::test_queue_receives_curated_child_events PASSED [100%]
```

## Verification: E2E Tests (recursive_ping, sqlite depth rows, backward compat, batched fanout)

4 provider-fake contract tests exercising the full pipeline: child events in the event stream, depth>0 rows in traces.db, zero child events for flat fixtures, and multiple fanout indices for batched dispatch.

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_child_event_reemission.py -v -m "provider_fake_contract" 2>&1 | grep -E "(PASSED|FAILED|ERROR)" | head -10
```

```output
tests_rlm_adk/test_child_event_reemission.py::test_recursive_ping_emits_child_events PASSED [ 25%]
tests_rlm_adk/test_child_event_reemission.py::test_recursive_ping_sqlite_depth_rows PASSED [ 50%]
tests_rlm_adk/test_child_event_reemission.py::test_flat_fixture_no_child_events PASSED [ 75%]
tests_rlm_adk/test_child_event_reemission.py::test_batched_dispatch_multiple_fanout_indices PASSED [100%]
```

## Verification: Lint (ruff check)

All changed production and test files pass ruff lint with zero violations.

```bash
.venv/bin/ruff check rlm_adk/state.py rlm_adk/dispatch.py rlm_adk/orchestrator.py rlm_adk/plugins/sqlite_tracing.py tests_rlm_adk/test_child_event_reemission.py 2>&1
```

```output
All checks passed!
```

## Verification: Format (ruff format --check)

All changed files are correctly formatted.

```bash
.venv/bin/ruff format --check rlm_adk/state.py rlm_adk/dispatch.py rlm_adk/orchestrator.py rlm_adk/plugins/sqlite_tracing.py tests_rlm_adk/test_child_event_reemission.py 2>&1
```

```output
5 files already formatted
```

## Verification: Diff Stats

Summary of all changes across the feature.

```bash
git diff --stat HEAD -- rlm_adk/state.py rlm_adk/dispatch.py rlm_adk/orchestrator.py rlm_adk/plugins/sqlite_tracing.py tests_rlm_adk/test_child_event_reemission.py rlm_adk_docs/dispatch_and_state.md rlm_adk_docs/observability.md 2>&1
```

```output
 rlm_adk/dispatch.py                | 109 +++++-----
 rlm_adk/orchestrator.py            |  18 ++
 rlm_adk/plugins/sqlite_tracing.py  | 396 +++++++++----------------------------
 rlm_adk/state.py                   |  56 +++++-
 rlm_adk_docs/dispatch_and_state.md |  56 ++++++
 rlm_adk_docs/observability.md      |  21 +-
 6 files changed, 281 insertions(+), 375 deletions(-)
```
