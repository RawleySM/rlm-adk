# GAP-EL-005: ADK Runner completion while child orchestrators are in-flight leaves orphaned coroutines

**Severity**: MEDIUM
**Category**: event-loop
**Files**: `rlm_adk/orchestrator.py`, `rlm_adk/dispatch.py`, `rlm_adk/repl/thread_bridge.py`

## Problem

The ADK Runner's `run_async` is an async generator (line 503-633 of `runners.py`). It iterates events from the root agent's `run_async(ctx)` until the generator is exhausted. The generator finishes when:

1. The reasoning agent calls `set_model_response` (normal completion)
2. An unrecoverable exception is raised
3. The caller stops iterating the generator (e.g., web server closes connection)

When `run_async` finishes, the orchestrator's `_run_async_impl` returns. But consider this timing:

```
T=0: Reasoning agent calls execute_code with code that calls llm_query()
T=1: Worker thread submits llm_query -> run_coroutine_threadsafe -> child orchestrator starts
T=2: asyncio.wait_for times out on execute_code_threaded
T=3: REPLTool returns timeout error to reasoning agent
T=4: Reasoning agent calls set_model_response (gives up)
T=5: Orchestrator finishes, events drain, _run_async_impl returns
T=6: Runner's run_async generator finishes
T=7: Event loop continues running (for the current asyncio.run())
T=8: Child orchestrator coroutine (from T=1) is STILL running on the loop
T=9: Child orchestrator eventually finishes, but nobody consumes its result
```

The child orchestrator coroutine is an orphaned `asyncio.Task` on the event loop. It runs to completion unsupervised. In the sync `Runner.run()` path (lines 438-501), the event loop is spun up in a separate thread via `asyncio.run()`. When `asyncio.run()` returns, the loop closes and cancels all pending tasks -- but this is uncontrolled cleanup, not graceful shutdown.

In the async `Runner.run_async()` path (where the caller already has a running loop), the orphaned tasks persist until the caller's loop ends.

## Evidence

`dispatch.py` line 318 -- child orchestrator runs as a coroutine on the event loop:
```python
async for _event in child.run_async(child_ctx):
```

This is wrapped in `_run_child` which is an async function, scheduled via `asyncio.gather` (line 500). When scheduled via `run_coroutine_threadsafe`, it becomes an `asyncio.Task` on the loop.

`orchestrator.py` lines 574-579 -- final drain only empties the queue, does not cancel in-flight tasks:
```python
if _child_event_queue is not None:
    while not _child_event_queue.empty():
        try:
            yield _child_event_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
```

There is no mechanism to track or cancel coroutines that were scheduled via `run_coroutine_threadsafe` from dangling worker threads.

## Suggested Fix

1. **Track in-flight futures**: In the thread bridge or dispatch layer, maintain a `set` of `concurrent.futures.Future` objects returned by `run_coroutine_threadsafe`. In the orchestrator's `finally` block (line 652-667), cancel all pending futures.

2. **Use `asyncio.TaskGroup` (Python 3.11+)**: Instead of `run_coroutine_threadsafe`, wrap child dispatches in a task group whose lifetime is tied to the orchestrator. When the orchestrator exits, the task group cancels all children.

3. **Graceful shutdown in `repl.cleanup()`**: The orchestrator calls `repl.cleanup()` at line 667. This could be extended to cancel any pending thread-bridge futures that reference this REPL instance.
