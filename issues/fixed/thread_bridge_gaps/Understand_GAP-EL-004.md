# Polya Understand Phase: GAP-EL-004

**Executor shutdown ordering allows resource leak on timeout with in-flight child dispatches**

**Date**: 2026-03-25

---

## A. Restate

When a REPL code block that contains `llm_query()` calls times out at the `execute_code_threaded` layer (default 30s), the worker thread is not cancelled. It continues running -- potentially for up to 300 more seconds -- because the thread bridge's `future.result(timeout=300)` has not yet expired. The `executor.shutdown(wait=False)` call returns immediately without terminating the thread, and the child orchestrator coroutine scheduled via `run_coroutine_threadsafe` continues consuming API quota and event loop resources on the main loop. No mechanism exists to cancel the orphaned coroutine, collect its result, or account for its resource usage.

---

## B. Target

Ensure that when `execute_code_threaded` times out, all in-flight child dispatch coroutines (spawned via `run_coroutine_threadsafe` from the worker thread) are cancelled or prevented from executing further work, and the orphaned worker thread is signalled to stop rather than continuing to run additional `llm_query()` calls from the remaining REPL code.

The deliverable is a specification for the minimum changes needed to close the gap: a cancellation signalling mechanism, cancellation of in-flight async futures, and timeout alignment or coordination.

---

## C. Givens

### C.1 The timeout mismatch (two independent timeout surfaces)

**Surface 1: `execute_code_threaded` timeout** (`local_repl.py` lines 500-507)

```python
loop = asyncio.get_running_loop()                          # line 499
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)  # line 500
try:
    stdout, stderr, _success = await asyncio.wait_for(      # line 502
        loop.run_in_executor(                                # line 503
            executor, self._execute_code_threadsafe, code, trace,  # line 504
        ),
        timeout=self.sync_timeout,                           # line 506
    )
```

`self.sync_timeout` defaults to `float(os.environ.get("RLM_REPL_SYNC_TIMEOUT", "30"))` (line 201-203). This is the outer timeout: if the entire code block (including any `llm_query()` calls within it) does not complete within 30 seconds, `asyncio.wait_for` raises `TimeoutError`.

**Surface 2: thread bridge `future.result()` timeout** (`thread_bridge.py` lines 77-80)

```python
future = asyncio.run_coroutine_threadsafe(                  # line 77
    llm_query_async(prompt, **kwargs), loop                  # line 78
)
return future.result(timeout=_timeout)                       # line 80
```

`_timeout` defaults to `300.0` (line 37, parameter default `timeout: float = 300.0`). This is the per-call timeout: each individual `llm_query()` call blocks the worker thread for up to 300 seconds waiting for the child orchestrator to complete.

**The mismatch**: The outer timeout (30s) fires long before the inner timeout (300s) expires. When the outer timeout fires, the worker thread is still blocked at `future.result(timeout=300)` -- it has 270 seconds of waiting left.

### C.2 What `executor.shutdown(wait=False)` does and does not do (`local_repl.py` line 518)

```python
finally:
    executor.shutdown(wait=False)                            # line 518
```

`concurrent.futures.ThreadPoolExecutor.shutdown(wait=False)` signals the executor to not accept new tasks and returns immediately. It does NOT:
- Interrupt or cancel the running thread
- Cancel `concurrent.futures.Future` objects that are already running
- Cancel `asyncio.Future` objects submitted via `run_coroutine_threadsafe`

The worker thread continues running `_execute_code_threadsafe` until it completes naturally. If that code is blocked at `future.result(timeout=300)` inside `llm_query()`, the thread will remain alive for up to 300 seconds.

Note: The sync `execute_code` method (line 466) uses `pool.shutdown(wait=not timed_out, cancel_futures=True)`, but `cancel_futures=True` only cancels _pending_ futures in the executor queue, not the one that is already running.

### C.3 What happens after timeout -- the orphaned cascade

After `execute_code_threaded` times out (line 508):

1. `asyncio.wait_for` raises `TimeoutError` (line 508)
2. `executor.shutdown(wait=False)` returns immediately (line 518)
3. `execute_code_threaded` returns a `REPLResult` with timeout error (lines 520-527)
4. `REPLTool.run_async()` returns this result to the reasoning agent (line 311 of `repl_tool.py`)
5. The reasoning agent may call `set_model_response` or submit another `execute_code`

Meanwhile, in the orphaned worker thread:
6. `future.result(timeout=300)` is still blocking at `thread_bridge.py` line 80
7. The child orchestrator coroutine is still running on the event loop (`dispatch.py` line 318: `async for _event in child.run_async(child_ctx)`)
8. The child orchestrator may create its own `execute_code_threaded` with its own executor and its own worker thread
9. The child orchestrator makes API calls, consuming quota
10. When the child finishes, `future.result()` returns to the orphaned worker thread
11. The worker thread continues executing the remaining REPL code after the `llm_query()` call site
12. If there are more `llm_query()` calls in the remaining code, the cycle repeats

### C.4 The `loop.is_closed()` guard (GAP-EL-007 fix, `thread_bridge.py` lines 70-74)

```python
if loop.is_closed():                                        # line 70
    raise RuntimeError(
        "Event loop is closed. The parent orchestrator has already finished. "
        "This typically happens when REPL code continues executing after a timeout."
    )
```

This guard catches one specific case: if `asyncio.run()` has completed and closed the event loop entirely (e.g., the entire ADK Runner has shut down), then the orphaned thread's next `llm_query()` call will raise `RuntimeError` instead of the confusing `RuntimeError: Event loop is closed` from `run_coroutine_threadsafe`.

**What it catches**: Loop closure after full process shutdown.

**What it misses**: The common case where `execute_code_threaded` timed out but the event loop is still running (because the reasoning agent is still active and may be processing the timeout error or a new `execute_code` call). In this case, `loop.is_closed()` returns `False`, the orphaned thread successfully submits a new child orchestrator coroutine, and the leak continues.

### C.5 The child semaphore (`dispatch.py` line 142)

```python
_child_semaphore = asyncio.Semaphore(max_concurrent)        # line 142
```

The semaphore is scoped to a single `create_dispatch_closures` call -- it is a local variable captured in the closures. Each parent orchestrator gets its own semaphore. Orphaned children from a timed-out code block hold semaphore slots belonging to the now-irrelevant closure instance. A new `execute_code` call creates new dispatch closures with a fresh semaphore, so orphaned children do not count against the new dispatch's concurrency limit.

### C.6 No cancellation mechanism exists

- `thread_bridge.py` does not expose the `asyncio.Future` created by `run_coroutine_threadsafe` (lines 77-78). It is a local variable inside the `llm_query()` closure.
- `local_repl.py` does not store a reference to the future returned by `run_in_executor` (line 503). `asyncio.wait_for` wraps it in an internal task.
- No `threading.Event` or cancellation token is shared between `execute_code_threaded` and the `llm_query` closure.
- The `CancelledError` handler in `thread_bridge.py` (line 81-84) handles `concurrent.futures.CancelledError`, but nothing currently triggers cancellation on the future.

### C.7 Thread bridge wiring in orchestrator (`orchestrator.py` lines 303-309)

```python
_loop = asyncio.get_running_loop()                          # line 305
repl.set_llm_query_fns(
    make_sync_llm_query(llm_query_async, _loop),            # line 307
    make_sync_llm_query_batched(llm_query_batched_async, _loop),  # line 308
)
```

The sync closures are created once per orchestrator `_run_async_impl` invocation. They capture `_loop` and the async dispatch closures. There is no mechanism to invalidate or disable these closures after a timeout.

---

## D. Conditions / Constraints

1. **Python threads cannot be forcibly killed.** CPython has no safe mechanism to terminate a running thread from outside. The only option is cooperative cancellation: set a flag that the thread checks and voluntarily exits.

2. **`concurrent.futures.Future.cancel()` only prevents execution of not-yet-started tasks.** Once `ThreadPoolExecutor` has started running a callable, `cancel()` returns `False` and has no effect.

3. **`asyncio.Future` from `run_coroutine_threadsafe` CAN be cancelled.** Calling `.cancel()` on the `concurrent.futures.Future` returned by `run_coroutine_threadsafe` will cancel the underlying `asyncio.Task` on the event loop. This raises `CancelledError` in the coroutine and `concurrent.futures.CancelledError` in the blocking `future.result()` call.

4. **The fix must not introduce deadlocks.** The thread bridge exists specifically to avoid the deadlock that the `_EXEC_LOCK` + `os.chdir` pattern caused. Any cancellation mechanism must not re-introduce blocking.

5. **The fix must be cooperative, not intrusive.** It should not require changes to user-submitted REPL code. The cancellation check should happen at the `llm_query()` call boundary.

6. **Backward compatibility.** The `make_sync_llm_query` API signature should remain compatible, or changes should be additive (new optional parameters).

7. **The event loop is NOT closed during the leak window.** The event loop is still running (the reasoning agent is still active). This means `loop.is_closed()` returns `False` and does not help.

---

## E. Unknowns

| # | Unknown | Relationship to givens |
|---|---------|----------------------|
| U1 | What is the right cancellation signalling mechanism? | A `threading.Event` shared between `execute_code_threaded` and `llm_query` closures is the natural Python primitive. But the closures are created in `orchestrator.py` (line 307-308) before any `execute_code_threaded` call, and a new `threading.Event` per code block would require either re-creating the closures or passing the event as a mutable reference. |
| U2 | Should the `asyncio.Future` from `run_coroutine_threadsafe` be cancelled on timeout? | Cancelling it would raise `CancelledError` in the child orchestrator coroutine and `concurrent.futures.CancelledError` in the blocked worker thread. The worker thread already handles `CancelledError` (thread_bridge.py line 81-84). But the `asyncio.Future` is a local variable inside the `llm_query` closure -- it must be exposed for external cancellation. |
| U3 | Should the thread bridge timeout be aligned to `sync_timeout`? | Aligning them (e.g., `thread_bridge timeout <= sync_timeout`) would prevent the mismatch, but would mean individual `llm_query()` calls cannot take longer than 30s, which is too short for many child orchestrator runs. The timeout should probably be dynamic per-call based on remaining budget, not a flat alignment. |
| U4 | Can a single `threading.Event` be reused across multiple `execute_code_threaded` calls? | If the closures are created once per orchestrator lifetime, a single event that is `set()` on timeout and `clear()`ed on the next `execute_code` call would work. But race conditions must be considered: what if the orphaned thread checks the event between `clear()` and the new code block's first `llm_query()`? |
| U5 | What happens to the orphaned child orchestrator's REPL cleanup? | `dispatch.py` line 414-418 cleans up the child's REPL in the `finally` block of `_run_child`. If the child orchestrator's `asyncio.Task` is cancelled, the `finally` block should still execute (Python guarantees `finally` on `CancelledError`). But if the task is cancelled during a nested `run_in_executor`, the executor's thread may continue running. |

---

## F. Definitions

- **Orphaned worker thread**: A thread started by `execute_code_threaded`'s `ThreadPoolExecutor` that continues running after `execute_code_threaded` has returned due to timeout. The thread is still executing `_execute_code_threadsafe` (and potentially blocked inside `llm_query()`).

- **Orphaned child orchestrator**: An `asyncio.Task` (coroutine) scheduled on the event loop via `run_coroutine_threadsafe` by an orphaned worker thread. The task runs `_run_child` in `dispatch.py`, which spawns a child `RLMOrchestratorAgent` and iterates its events. No parent is listening for the result.

- **Sync timeout / outer timeout**: `self.sync_timeout` (default 30s from `RLM_REPL_SYNC_TIMEOUT`). Controls how long `execute_code_threaded` waits for the entire code block to finish. Set at `local_repl.py` line 506.

- **Thread bridge timeout / inner timeout**: `_timeout` (default 300s). Controls how long each individual `llm_query()` call blocks the worker thread waiting for the child orchestrator. Set at `thread_bridge.py` line 80.

- **Cancellation token**: A `threading.Event` (or similar primitive) that can be checked cooperatively by the worker thread at each `llm_query()` call site. When set, the worker thread should abort instead of submitting new work.

- **`run_coroutine_threadsafe` future**: The `concurrent.futures.Future` returned by `asyncio.run_coroutine_threadsafe()`. Calling `.cancel()` on this future cancels the underlying `asyncio.Task` on the event loop, which raises `CancelledError` in the coroutine.

---

## G. Representation

### Data flow and timeout interaction diagram

```
                               EVENT LOOP (main thread)
                               ========================

  execute_code_threaded()
  |
  |  asyncio.wait_for(
  |      loop.run_in_executor(executor, _execute_code_threadsafe, code),
  |      timeout=30s                    <--- OUTER TIMEOUT (line 506)
  |  )
  |
  |                                WORKER THREAD (executor)
  |                                ========================
  |
  |                                _execute_code_threadsafe(code)
  |                                  |
  |                                  |  ... execute user code ...
  |                                  |
  |                                  |  llm_query("prompt")     [thread_bridge.py]
  |                                  |    |
  |                                  |    |  loop.is_closed()?  NO  (line 70)
  |                                  |    |
  |                                  |    |  future = run_coroutine_threadsafe(
  |                                  |    |      llm_query_async("prompt"), loop
  |                                  |    |  )                   (line 77-78)
  |                                  |    |
  |  <~~~ coroutine scheduled ~~~>   |    |
  |  _run_child() starts             |    |  future.result(timeout=300s)
  |  child.run_async(child_ctx)      |    |    <--- INNER TIMEOUT (line 80)
  |    |                             |    |    BLOCKED for up to 300s
  |    |                             |    |
  +----+-----------------------------+----+--------------------------------+
  |    |                             |    |                                |
  |    |        t=30s: OUTER TIMEOUT FIRES                                |
  |    |                             |    |                                |
  |  TimeoutError raised (line 508)  |    |  (thread keeps blocking)      |
  |  executor.shutdown(wait=False)   |    |                                |
  |    (line 518)                    |    |                                |
  |  Returns REPLResult (timeout)    |    |                                |
  |    (lines 520-527)               |    |                                |
  |                                  |    |                                |
  |  REPLTool returns to agent       |    |  (still blocked at            |
  |  Agent may call execute_code     |    |   future.result(300s))        |
  |    again or set_model_response   |    |                                |
  |                                  |    |                                |
  |    |  child still running...     |    |                                |
  |    |  making API calls...        |    |                                |
  |    |  consuming quota...         |    |                                |
  |    |                             |    |                                |
  |    |  child finishes             |    |                                |
  |    |  future.result() returns    |    |                                |
  |    |                             |    |  result = future.result()      |
  |                                  |    |  return result                 |
  |                                  |  (worker thread continues          |
  |                                  |   executing remaining code         |
  |                                  |   after the llm_query() line)      |
  |                                  |                                    |
  |                                  |  llm_query("next prompt")          |
  |                                  |    |  ANOTHER child dispatched...  |
  |                                  |    |  ANOTHER 300s of leakage...   |
  |                                  |                                    |
  +----------------------------------+------------------------------------+
       ORPHANED RESOURCES                 ORPHANED WORKER THREAD
       (child orchestrators,              (continues running code,
        API quota, event loop             making more llm_query calls)
        tasks, semaphore slots)
```

### Cancellation token flow (proposed fix)

```
  execute_code_threaded()
  |
  |  cancel_event = threading.Event()       <--- NEW: per-code-block token
  |
  |  asyncio.wait_for(..., timeout=30s)
  |
  |  except TimeoutError:
  |      cancel_event.set()                 <--- Signal cancellation
  |      cancel outstanding futures         <--- Cancel run_coroutine_threadsafe futures
  |
  |                                WORKER THREAD
  |
  |                                llm_query("prompt")
  |                                  |
  |                                  |  cancel_event.is_set()?  YES --> RuntimeError
  |                                  |                          NO  --> proceed
  |                                  |
  |                                  |  future = run_coroutine_threadsafe(...)
  |                                  |  _outstanding_futures.append(future)
  |                                  |  future.result(timeout=...)
  |                                  |
  |                                  |  If cancelled externally:
  |                                  |    CancelledError raised
  |                                  |    Converted to RuntimeError (line 81-84)
```

---

## H. Assumptions

| # | Item | Type | Risk | Notes |
|---|------|------|------|-------|
| 1 | `executor.shutdown(wait=False)` does not cancel in-flight threads | Fact | -- | Python documentation: "If wait is False, this method will return immediately." Running threads continue. |
| 2 | `asyncio.wait_for` timeout does not cancel the `run_in_executor` task's underlying thread | Fact | -- | `asyncio.wait_for` cancels the wrapping `asyncio.Task`, but the underlying OS thread continues running. `run_in_executor` wraps a `concurrent.futures.Future` which cannot be cancelled once started. |
| 3 | `concurrent.futures.Future.cancel()` from `run_coroutine_threadsafe` cancels the `asyncio.Task` | Fact | -- | Python documentation: the returned future represents the result of the coroutine; cancelling it cancels the asyncio task. |
| 4 | The event loop is still running when the leak occurs | Fact | -- | The leak happens during normal operation (the reasoning agent continues after timeout). The loop only closes when `asyncio.run()` completes. |
| 5 | A `threading.Event` can be safely checked from the worker thread without synchronization issues | Fact | -- | `threading.Event` is thread-safe by design. `is_set()` is non-blocking. |
| 6 | Orphaned children are rare in practice (require slow child orchestrator + short sync_timeout) | Assumption | MEDIUM | With default 30s sync_timeout and real LLM calls that take 5-30s, any code block with even one `llm_query()` call that takes >30s will trigger this. Not rare. |
| 7 | The `_pending_llm_calls` list on the orphaned thread does not cause data corruption | Assumption | LOW | The orphaned thread may append to `repl._pending_llm_calls` after `execute_code_threaded` has already copied it into the `REPLResult`. The appended entries are lost but do not corrupt the returned result because `REPLResult` stores a `.copy()` (line 525). However, the next `execute_code_threaded` call clears the list (line 494), which could race with the orphaned thread's append. |
| 8 | Orphaned threads eventually exit | Assumption | LOW | The thread will exit after: (a) all `llm_query()` calls' 300s timeouts expire, or (b) all child orchestrators complete, or (c) the loop is closed (GAP-EL-007 guard). But this could take up to `N * 300s` where N is the number of remaining `llm_query()` calls in the code. |

---

## I. Well-Posedness

**Well-posed, with one design choice to resolve.**

The problem is fully specified:
- The timeout mismatch is a concrete numerical fact (30s vs 300s)
- The orphan mechanism is deterministic and reproducible
- The Python threading constraints are well-documented

The one design choice is: **what cancellation mechanism to use?**

Four options exist (from the gap description):

1. **Cancel `run_coroutine_threadsafe` futures on timeout** -- requires exposing futures from the thread bridge closure. Cancels child orchestrators but does not stop the worker thread from executing remaining non-`llm_query` code.

2. **Propagate a `threading.Event` cancellation token** -- requires plumbing the event through `make_sync_llm_query` into the closure. Checks the event at each `llm_query()` call boundary. Does not cancel already-in-flight child orchestrators.

3. **Combine 1 and 2** -- the most complete solution. The `threading.Event` prevents new `llm_query()` calls, and cancelling outstanding futures stops already-in-flight children.

4. **Align timeouts** -- set thread bridge timeout to `<= sync_timeout`. This eliminates the mismatch but makes `llm_query()` calls too short for practical use.

Option 3 is the minimum complete fix. Option 4 is too restrictive for production use.

The problem is solvable without ambiguity.

---

## J. Success Criteria

1. **No orphaned child orchestrators after timeout.** When `execute_code_threaded` times out, all `run_coroutine_threadsafe` futures created during that code block's execution are cancelled. The child orchestrator coroutines receive `CancelledError`.

2. **No new `llm_query()` calls from orphaned threads.** After timeout, any subsequent `llm_query()` call from the orphaned worker thread raises `RuntimeError` (or similar) immediately instead of submitting new work to the event loop.

3. **No API quota leak.** Orphaned children do not continue making LLM API calls after the parent code block has timed out.

4. **`CancelledError` handled cleanly.** The orphaned worker thread's `CancelledError` from `future.result()` is caught by the existing handler at `thread_bridge.py` lines 81-84 and converted to a `RuntimeError`. This exception propagates through the remaining REPL code and terminates the thread.

5. **No deadlocks introduced.** The cancellation mechanism must not re-introduce the `_EXEC_LOCK` deadlock that the thread bridge was designed to avoid.

6. **Existing tests pass.** No regression in the existing test suite.

7. **New test(s) verify the fix.** A test that submits code with a slow `llm_query()` call, triggers the outer timeout, and verifies that (a) the child orchestrator is cancelled and (b) no subsequent `llm_query()` calls succeed from the orphaned thread.

---

## Problem Type

**Concurrent resource lifecycle management.** The problem is a classic producer-consumer lifecycle mismatch: the consumer (`execute_code_threaded`) has stopped consuming, but the producer (worker thread + child orchestrators) continues producing. The fix is a cooperative shutdown signal that propagates across the thread boundary and into the async event loop.

Structurally analogous to "graceful shutdown" patterns in server architectures, where a parent process signals child workers to stop via a shared cancellation token, and cancels outstanding async operations.

---

## Edge Cases / Toy Examples

| # | Scenario | Expected behavior (after fix) |
|---|----------|-------------------------------|
| 1 | Code block with no `llm_query()` calls times out | No change from current behavior. No child orchestrators to cancel. Worker thread finishes naturally (running pure Python that took >30s). |
| 2 | Code block with one `llm_query()` call that is in-flight at timeout | The `run_coroutine_threadsafe` future is cancelled. Worker thread receives `CancelledError` from `future.result()`, which is caught and converted to `RuntimeError`. Thread terminates. Child orchestrator receives `CancelledError`. |
| 3 | Code block with one completed `llm_query()` and one pending `llm_query()` at timeout | First call completed normally (result already returned). Second call checks the cancellation token, finds it set, raises `RuntimeError` immediately without submitting work. |
| 4 | Code block with `llm_query_batched([p1, p2, p3])` in-flight at timeout | The single `run_coroutine_threadsafe` future wrapping all 3 children is cancelled. All 3 child orchestrators receive `CancelledError`. Worker thread terminates. |
| 5 | Two consecutive `execute_code_threaded` calls: first times out, second is normal | The cancellation token from the first call must not affect the second call. Either: (a) each call creates a new cancellation token, or (b) the token is `clear()`ed at the start of each call. |
| 6 | Nested depth: child orchestrator's own `execute_code_threaded` times out | Same mechanism applies recursively. Each depth level's `execute_code_threaded` has its own cancellation token. Timeout at depth N cancels depth N+1 children. |
| 7 | Worker thread calls `llm_query()` exactly at the moment timeout fires | Race condition. The cancellation check and `run_coroutine_threadsafe` are not atomic. The submitted future should be tracked and cancelled after the timeout fires. Both the check-before-submit guard and the cancel-after-timeout sweep are needed. |
| 8 | Orphaned thread completes before cancellation signal propagates | Harmless. The thread has already exited. The cancellation signal is a no-op. The `run_coroutine_threadsafe` future has already resolved. |

---

## Files to Modify

| # | File | Location | Change |
|---|------|----------|--------|
| F1 | `rlm_adk/repl/thread_bridge.py` | `make_sync_llm_query()` (lines 33-88) | Add optional `cancel_event: threading.Event` parameter. Inside `llm_query()` closure, check `cancel_event.is_set()` before submitting work (after line 74). Track outstanding `run_coroutine_threadsafe` futures in a thread-safe list so they can be cancelled externally. |
| F2 | `rlm_adk/repl/thread_bridge.py` | `make_sync_llm_query_batched()` (lines 91-146) | Same changes as F1, for the batched variant. |
| F3 | `rlm_adk/repl/local_repl.py` | `execute_code_threaded()` (lines 480-527) | Create a `threading.Event` per code block (before line 500). On `TimeoutError` (line 508), call `cancel_event.set()` and cancel all outstanding `run_coroutine_threadsafe` futures tracked by the thread bridge closures. |
| F4 | `rlm_adk/repl/local_repl.py` | `set_llm_query_fns()` (lines 224-227) | Extend to also store references to cancel-event-aware metadata from the closures (e.g., the outstanding-futures list and the cancel event), so `execute_code_threaded` can access them at timeout. |
| F5 | `rlm_adk/orchestrator.py` | Thread bridge wiring (lines 303-309) | Pass any new parameters (cancel event, outstanding futures list) through `make_sync_llm_query` and `make_sync_llm_query_batched`. |
| F6 | `tests_rlm_adk/test_thread_bridge.py` | New test(s) | Test that cancellation token prevents new `llm_query()` calls. Test that outstanding futures are cancelled on timeout. Test that consecutive `execute_code_threaded` calls work correctly (no stale cancellation state). |

---

## Summary

GAP-EL-004 is a concurrent resource lifecycle problem caused by a 30s/300s timeout mismatch between two independent timeout surfaces. When the outer timeout fires, `executor.shutdown(wait=False)` does not stop the worker thread, and the inner 300s timeout keeps the orphaned thread alive. The `loop.is_closed()` guard (GAP-EL-007) only catches the edge case where the entire event loop has shut down -- it does not help when the loop is still running (which is the common case). The fix requires two cooperating mechanisms: (1) a `threading.Event` cancellation token checked at each `llm_query()` call boundary to prevent new work submission, and (2) cancellation of outstanding `run_coroutine_threadsafe` futures to stop already-in-flight child orchestrators. Both mechanisms must be wired through the thread bridge closures and activated by `execute_code_threaded` on timeout.
