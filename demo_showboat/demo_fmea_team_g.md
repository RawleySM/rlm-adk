# FMEA Team G: Worker Dispatch Edge Cases

*2026-03-01 by Showboat 0.6.0*

## FM-13: CancelledError Swallowed by REPLTool (RPN=56, Pathway: P2d)

**Failure Mode:** During REPL code execution (either sync or async path), an
external task cancellation (e.g., an outer `asyncio.wait_for` timeout or a
manual `task.cancel()`) raises `asyncio.CancelledError` inside the
`REPLTool.run_async` method. Instead of propagating the cancellation signal
upward so the caller knows the task was cancelled, the error is caught and
converted to a stderr string. The ADK tool-calling loop continues as if the
code merely failed, and the model sees a `CancelledError` error message
rather than the task being stopped.

**Risk:** RPN=56 (Severity=4, Occurrence=2, Detection=7). The high detection
score (7) reflects that cancellation is silently consumed -- the orchestrator
has no way to distinguish "code failed" from "task was cancelled." The
cancellation signal is lost, which violates Python's asyncio cancellation
contract. The model may retry the same code or attempt to "fix" a
CancelledError, wasting tokens and time on a fundamentally unrecoverable
situation.

**Source Code Inspection:**

The exception handler at `rlm_adk/tools/repl_tool.py` lines 120-127:

```python
# repl_tool.py lines 107-127
        try:
            if has_llm_calls(code):
                llm_calls_made = True
                tree = rewrite_for_async(code)
                compiled = compile(tree, "<repl>", "exec")
                # Merge globals and locals so _repl_exec sees variables from
                # previous executions (imports, user-defined vars, etc.)
                ns = {**self.repl.globals, **self.repl.locals}
                exec(compiled, ns)
                repl_exec_fn = ns["_repl_exec"]
                result = await self.repl.execute_code_async(code, repl_exec_fn, trace=trace)
            else:
                result = self.repl.execute_code(code, trace=trace)
        except (Exception, asyncio.CancelledError) as exc:
            return {
                "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}",
                "variables": {},
                "llm_calls_made": llm_calls_made,
                "call_number": self._call_count,
            }
```

Note: In Python 3.9+, `asyncio.CancelledError` is a subclass of
`BaseException`, not `Exception`. The handler explicitly lists both
`(Exception, asyncio.CancelledError)` to ensure CancelledError is caught
even though it would NOT be caught by a bare `except Exception`.

**How the code handles FM-13:**

1. The `try` block at line 107 wraps both the sync (`execute_code`) and async
   (`execute_code_async`) execution paths. Any exception raised during code
   execution, AST compilation, or async dispatch enters the `except` handler.

2. The `except (Exception, asyncio.CancelledError)` at line 120 catches
   `CancelledError` alongside all regular exceptions. Since `CancelledError`
   inherits from `BaseException` (not `Exception`) in Python 3.9+, this
   explicit listing is intentional -- the author wanted to catch cancellation.

3. The handler at lines 121-127 formats the cancellation as a dict with the
   error in `stderr` (e.g., `"CancelledError: "`) and returns it to ADK as a
   normal tool result. ADK's tool-calling loop interprets this as a successful
   tool invocation that produced an error message, not as a cancellation.

4. Because the `CancelledError` is not re-raised, the asyncio task remains
   alive. The ADK tool-calling loop feeds the error string back to the model
   as the tool response. The model sees `"CancelledError: "` in stderr and
   may attempt to retry or "fix" the code, unaware that the system intended
   to abort the task.

5. The `flush_fn` call at lines 130-135 and the `LAST_REPL_RESULT` write at
   lines 138-146 are skipped (they are after the `except` return), meaning
   dispatch accumulators are not flushed for this iteration. This is also
   FM-14's failure mode, which compounds with FM-13.

**Testability Assessment:** Unit-testable. The existing test at
`tests_rlm_adk/test_repl_tool.py` lines 142-154 (class
`TestREPLToolExceptionSafety`, method `test_cancelled_error_returns_stderr`)
already exercises this exact path by patching `repl.execute_code` to raise
`CancelledError` and asserting that "CancelledError" appears in `stderr`.
However, this test only verifies the *current* behavior (swallowing), not the
*correct* behavior (re-raising). No e2e fixture exists because the
provider-fake framework cannot inject task cancellation.

**Recommended Test Scenario:** A unit test that verifies the CancelledError
propagates rather than being swallowed:

1. Create a `REPLTool` with a patched `repl.execute_code_async` that raises
   `asyncio.CancelledError`.
2. Call `tool.run_async(...)` and assert that `CancelledError` propagates
   (i.e., the call raises, it does not return a dict).
3. Alternatively, if the design decision is to swallow intentionally, add a
   test that verifies the model receives a specific "task cancelled" message
   that is distinct from a code error, and that `SHOULD_STOP` is set.

**Gaps:**
- The existing unit test validates the swallowing behavior but does not test
  whether this is *correct* -- no assertion that the cancellation should
  propagate.
- No e2e fixture coverage (provider-fake cannot inject cancellation).
- No integration test verifying behavior when an outer `asyncio.wait_for`
  cancels the REPL tool mid-execution.
- The `flush_fn` is skipped on CancelledError (compounds with FM-14).

---

## FM-11: Worker Pool Exhaustion with On-Demand Creation (RPN=54, Pathway: P6a)

**Failure Mode:** When all `pool_size` workers are in-flight (acquired and
not yet released), a new `acquire()` call finds the pool queue empty.
Instead of blocking or raising, it creates a new `LlmAgent` worker
synchronously via `_create_worker()`. This on-demand creation blocks the
asyncio event loop during Pydantic model construction (LlmAgent is a
Pydantic model). After use, the on-demand worker is discarded during
`release()` if the pool is already at capacity.

**Risk:** RPN=54 (Severity=3, Occurrence=3, Detection=6). The severity is
moderate (brief event loop stall, no data loss). Occurrence is moderate
because batch sizes exceeding `pool_size` (default 5) are plausible with
`llm_query_batched` of 6+ prompts. Detection is poor (6) because the stall
is transient and only visible via event loop monitoring or timing analysis.

**Source Code Inspection:**

The `WorkerPool.acquire()` method at `rlm_adk/dispatch.py` lines 146-171:

```python
# dispatch.py lines 146-171
    async def acquire(self, model: str | None = None) -> LlmAgent:
        """Acquire a worker from the appropriate pool.

        If the pool is empty, creates a new worker on demand to prevent
        deadlocks when batch size exceeds pool capacity.

        Args:
            model: Model name. None uses the depth=1 default (other_model).

        Returns:
            An LlmAgent worker ready for prompt injection and dispatch.
        """
        target_model = model or self.other_model

        if target_model not in self._pools:
            # Auto-register on first use for dynamically-specified models
            self.register_model(target_model)

        try:
            return self._pools[target_model].get_nowait()
        except asyncio.QueueEmpty:
            # Pool exhausted — create a worker on demand to avoid deadlock
            logger.info(
                "Pool '%s' exhausted, creating worker on demand", target_model
            )
            return self._create_worker(target_model)
```

The `_create_worker()` method at `rlm_adk/dispatch.py` lines 97-144:

```python
# dispatch.py lines 97-144
    def _create_worker(self, model_name: str) -> LlmAgent:
        """Create a single LlmAgent worker configured per HIGH-3.
        ...
        """
        self._worker_counter += 1
        worker_name = f"worker_{self._worker_counter}"

        worker = LlmAgent(
            name=worker_name,
            model=model_name,
            description=f"Sub-LM worker for {model_name}",
            instruction="Answer the user's query directly and concisely.",
            include_contents="none",
            disallow_transfer_to_parent=True,
            disallow_transfer_to_peers=True,
            output_key=f"{worker_name}_output",
            before_model_callback=worker_before_model,
            after_model_callback=worker_after_model,
            on_model_error_callback=worker_on_model_error,
            generate_content_config=types.GenerateContentConfig(
                temperature=0.0,
                http_options=HttpOptions(
                    timeout=int(os.getenv("RLM_WORKER_HTTP_TIMEOUT", "120000")),
                    retry_options=HttpRetryOptions(
                        attempts=2, initial_delay=1.0, max_delay=30.0,
                    ),
                ),
            ),
        )
        # Slot for the dispatch closure to inject the prompt before dispatch.
        worker._pending_prompt = None
        # Result carrier attributes
        worker._result = None
        worker._result_ready = False
        worker._result_error = False
        worker._call_record = None

        return worker
```

The `release()` method at `rlm_adk/dispatch.py` lines 173-192:

```python
# dispatch.py lines 173-192
    async def release(self, worker: LlmAgent, model: str | None = None):
        """Return a worker to its pool after dispatch completes.

        Only returns the worker if the pool has not yet reached its
        configured pool_size. On-demand workers created during pool
        exhaustion are discarded to prevent unbounded pool growth.

        Args:
            worker: The LlmAgent to return.
            model: The model pool to return it to. None uses the depth=1 default.
        """
        target_model = model or self.other_model
        if target_model in self._pools:
            if self._pools[target_model].qsize() < self.pool_size:
                await self._pools[target_model].put(worker)
            else:
                logger.debug(
                    "Pool '%s' at capacity (%d), discarding on-demand worker %s",
                    target_model, self.pool_size, worker.name,
                )
```

**How the code handles FM-11:**

1. `acquire()` at line 164 first attempts a non-blocking `get_nowait()` from
   the asyncio queue for the target model's pool.

2. If the queue is empty (all `pool_size` workers are in-flight), the
   `QueueEmpty` exception is caught at line 166, and `_create_worker()` is
   called synchronously at line 171.

3. `_create_worker()` constructs a new `LlmAgent` (a Pydantic model) with
   full configuration including `GenerateContentConfig`, `HttpOptions`, and
   `HttpRetryOptions`. This is a synchronous Pydantic `__init__` call that
   blocks the event loop. The construction also sets dynamic attributes
   (`_pending_prompt`, `_result`, etc.) via direct assignment.

4. After dispatch completes, the `finally` block at lines 512-530 calls
   `worker_pool.release(worker, model)` for each worker in the batch.

5. `release()` at line 186 checks `qsize() < self.pool_size`. If the pool
   is already at capacity (original workers were released first), the
   on-demand worker is discarded with a debug log at lines 189-192. This
   prevents unbounded pool growth (Bug-6 fix).

6. The design deliberately chooses on-demand creation over blocking (`await
   queue.get()`) to prevent deadlocks: if a batch dispatch needs K workers
   but the pool only has N < K, blocking would deadlock because no worker
   would complete until all K are acquired and dispatched.

**Testability Assessment:** Unit-testable. The pool exhaustion and cap
behavior are exercised by `tests_rlm_adk/test_bug006_pool_growth.py` (3
tests) and `tests_rlm_adk/test_adk_dispatch_worker_pool.py` (12 tests).
These tests verify that on-demand workers are created, that pool size does
not grow beyond the configured limit, and that repeated bursts do not cause
accumulation. However, no test measures the event loop stall duration, and
no e2e fixture exercises a batch size > pool_size through the full dispatch
pipeline.

**Recommended Test Scenario:**

1. Create a `WorkerPool` with `pool_size=2`.
2. Dispatch a batch of 4 prompts via `llm_query_batched_async`.
3. Verify that 2 on-demand workers are created (check `_worker_counter`).
4. Verify that after dispatch completes, pool size is still 2 (on-demand
   workers discarded).
5. Optionally: measure `asyncio.get_event_loop().time()` before and after
   the `acquire()` call to assert the stall is below a threshold (e.g.,
   50ms).

**Gaps:**
- No e2e fixture exercises batch size > pool_size through the full
  dispatch/REPL pipeline.
- No test measures the event loop stall duration during on-demand
  `_create_worker()`.
- The `max_concurrent` chunking at line 314 (`RLM_MAX_CONCURRENT_WORKERS`,
  default 4) limits individual batch sizes, so pool exhaustion requires
  concurrent batches or `max_concurrent > pool_size`. This interaction is
  not tested.
- The `logger.info` at line 168 is the only observable signal of pool
  exhaustion. No metric is written to session state for observability.

---

## FM-10: Worker Dispatch Timeout (RPN=50, Pathway: P6b)

**Failure Mode:** One or more workers exceed the `RLM_WORKER_TIMEOUT`
(default 180 seconds, read from environment at module load). The
`asyncio.wait_for` wrapper raises `asyncio.TimeoutError`. The timeout
handler sets error results on any workers that have not yet completed,
but the cancelled coroutine may leave ADK internal state inconsistent for
the timed-out worker's context.

**Risk:** RPN=50 (Severity=5, Occurrence=2, Detection=5). The severity
is moderate-to-high because a timeout during a multi-worker batch means
some workers completed successfully and others did not, producing mixed
results. The cancellation of the inner coroutine (worker's `run_async`)
may leave ADK's session event stream in an inconsistent state. Detection
is moderate (5) because the timeout is logged and the error result contains
a timeout message, but there is no dedicated metric counter for timeouts
in the current implementation.

**Source Code Inspection:**

The timeout constant at `rlm_adk/dispatch.py` line 205:

```python
# dispatch.py line 205
_WORKER_DISPATCH_TIMEOUT = float(os.getenv("RLM_WORKER_TIMEOUT", "180"))
```

The single-worker timeout path at `rlm_adk/dispatch.py` lines 374-383:

```python
# dispatch.py lines 374-383
                if len(workers) == 1:
                    try:
                        await asyncio.wait_for(
                            _consume_events(workers[0].run_async(ctx)),
                            timeout=_WORKER_DISPATCH_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        workers[0]._result = f"[Worker {workers[0].name} timed out after {_WORKER_DISPATCH_TIMEOUT}s]"
                        workers[0]._result_ready = True
                        workers[0]._result_error = True
```

The multi-worker (ParallelAgent) timeout path at `rlm_adk/dispatch.py` lines 384-399:

```python
# dispatch.py lines 384-399
                else:
                    parallel = ParallelAgent(
                        name=f"batch_{batch_num}_{len(workers)}",
                        sub_agents=list(workers),
                    )
                    try:
                        await asyncio.wait_for(
                            _consume_events(parallel.run_async(ctx)),
                            timeout=_WORKER_DISPATCH_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        for w in workers:
                            if not getattr(w, '_result_ready', False):
                                w._result = f"[Worker {w.name} timed out after {_WORKER_DISPATCH_TIMEOUT}s]"
                                w._result_ready = True
                                w._result_error = True
```

The result reading at `rlm_adk/dispatch.py` lines 401-439 (already shown in FM-08 demo_fmea_team_a.md) reads `_result_error` and produces `LLMResult(error=True, error_category="UNKNOWN")` for timed-out workers.

The `finally` cleanup at `rlm_adk/dispatch.py` lines 512-530:

```python
# dispatch.py lines 512-530
            finally:
                for worker in workers:
                    worker._pending_prompt = None
                    worker._result = None
                    worker._result_error = False
                    worker._call_record = None
                    # Reset structured output wiring
                    if output_schema is not None:
                        worker.output_schema = None
                        worker.tools = []
                        worker.after_tool_callback = None
                        worker.on_tool_error_callback = None
                        if hasattr(worker, "_structured_result"):
                            worker._structured_result = None
                    # Detach from ParallelAgent parent so the worker can be
                    # re-used in a future batch (ADK sets parent_agent in
                    # model_post_init and raises if already set).
                    worker.parent_agent = None
                    await worker_pool.release(worker, model)
```

**How the code handles FM-10:**

1. Both the single-worker path (line 376) and the multi-worker
   ParallelAgent path (line 390) wrap the dispatch in
   `asyncio.wait_for(..., timeout=_WORKER_DISPATCH_TIMEOUT)`.

2. When the timeout fires, `asyncio.wait_for` cancels the inner coroutine
   (`_consume_events(worker.run_async(ctx))` or
   `_consume_events(parallel.run_async(ctx))`) and raises
   `asyncio.TimeoutError`.

3. For the **single-worker** case (lines 380-383), the handler sets the
   error result directly on the one worker:
   `_result` = timeout message, `_result_ready = True`,
   `_result_error = True`.

4. For the **multi-worker** case (lines 394-399), the handler iterates over
   all workers and checks `_result_ready`. Workers that completed before the
   timeout have `_result_ready=True` (set by `worker_after_model` or
   `worker_on_model_error`), so they are skipped. Only incomplete workers
   get the timeout error result.

5. The result reading loop at lines 401-439 then processes all workers.
   Timed-out workers appear as `LLMResult(error=True,
   error_category="UNKNOWN")` because the `_call_record` was never written
   by the callback (the worker did not complete), and the default fallback
   in `record.get("error_category", "UNKNOWN")` at line 419 produces
   `"UNKNOWN"` rather than the more informative `"TIMEOUT"`.

6. The `finally` block at lines 512-530 always executes, cleaning up
   carrier attributes and releasing workers back to the pool. This ensures
   timed-out workers are properly cleaned up and re-pooled.

7. Note that `_WORKER_DISPATCH_TIMEOUT` at line 205 is read from the
   environment variable `RLM_WORKER_TIMEOUT` at **module load time** using
   `os.getenv`. This means the timeout cannot be changed at runtime without
   reloading the module.

**Testability Assessment:** Difficult to test via e2e fixture. The
provider-fake server does not support delay injection (it responds
immediately to all requests). A unit test could mock `asyncio.wait_for`
or use a very short timeout, but testing the interaction between timeout
cancellation and ADK's internal state requires an integration test with
actual coroutine scheduling.

**Recommended Test Scenario:**

1. Set `RLM_WORKER_TIMEOUT` to a very small value (e.g., 0.001 seconds).
2. Patch `_consume_events` or the worker's `run_async` to `await
   asyncio.sleep(10)` (guaranteed to exceed timeout).
3. For K=1: verify the single worker gets `_result_error=True` and
   `_result` contains "timed out".
4. For K=3: set up 3 workers where one sleeps forever. Verify the two fast
   workers have successful results and the slow one has the timeout error.
5. Verify the `finally` block executes and all workers are released to the
   pool.

**Gaps:**
- No e2e fixture coverage (provider-fake cannot inject delays).
- No unit test for the timeout path in either single-worker or
  multi-worker dispatch.
- Timed-out workers get `error_category="UNKNOWN"` instead of `"TIMEOUT"`
  because the `_call_record` is never written. The `_classify_error`
  function in `worker.py` does handle `asyncio.TimeoutError` with a
  `"TIMEOUT"` category, but it is never invoked for dispatch-level timeouts
  (only for `on_model_error_callback`-level errors).
- No `OBS_WORKER_TIMEOUT_COUNT` state key is incremented on dispatch
  timeout (the key exists in `state.py` line 79 but is never written to).
- The interaction between `asyncio.wait_for` cancelling the inner coroutine
  and ADK's event stream consistency is unverified.

---

## FM-12: Worker parent_agent Not Cleared (RPN=16, Pathway: P6h)

**Failure Mode:** After a `ParallelAgent` batch dispatch, if the
`worker.parent_agent = None` cleanup is not executed, the next batch that
reuses the same worker will fail. ADK's `BaseAgent.model_post_init` sets
`parent_agent` when a sub-agent is added to a `ParallelAgent`. If
`parent_agent` is already set (non-None), ADK raises `ValueError`. This
would crash the entire dispatch for the next batch, not just one worker.

**Risk:** RPN=16 (Severity=8, Occurrence=1, Detection=2). The severity is
high (8) because the failure is a hard `ValueError` crash that kills the
entire batch dispatch and potentially the orchestrator run. However,
occurrence is very low (1) because the `finally` block reliably executes
in Python. Detection is excellent (2) because the `ValueError` is
immediately visible as a stack trace.

**Source Code Inspection:**

The `finally` block that clears `parent_agent` at `rlm_adk/dispatch.py`
lines 512-530:

```python
# dispatch.py lines 512-530
            finally:
                for worker in workers:
                    worker._pending_prompt = None
                    worker._result = None
                    worker._result_error = False
                    worker._call_record = None
                    # Reset structured output wiring
                    if output_schema is not None:
                        worker.output_schema = None
                        worker.tools = []
                        worker.after_tool_callback = None
                        worker.on_tool_error_callback = None
                        if hasattr(worker, "_structured_result"):
                            worker._structured_result = None
                    # Detach from ParallelAgent parent so the worker can be
                    # re-used in a future batch (ADK sets parent_agent in
                    # model_post_init and raises if already set).
                    worker.parent_agent = None
                    await worker_pool.release(worker, model)
```

The comment at lines 526-528 documents the Bug-7 fix: ADK sets
`parent_agent` in `model_post_init` and raises `ValueError` if the agent
already has a parent.

The `ParallelAgent` construction at `rlm_adk/dispatch.py` lines 385-388:

```python
# dispatch.py lines 385-388
                    parallel = ParallelAgent(
                        name=f"batch_{batch_num}_{len(workers)}",
                        sub_agents=list(workers),
                    )
```

When `ParallelAgent.__init__` receives `sub_agents`, ADK's
`model_post_init` iterates over them and sets `agent.parent_agent = self`
for each sub-agent. If any agent already has `parent_agent != None`, ADK
raises `ValueError`.

**How the code handles FM-12:**

1. During batch dispatch, workers are acquired from the pool and added to
   the `workers` list at lines 352-372. The `ParallelAgent` is constructed
   at lines 385-388 with these workers as `sub_agents`.

2. ADK's `ParallelAgent.model_post_init` sets `worker.parent_agent` to the
   `ParallelAgent` instance for each worker. This is the ADK-internal
   mechanism for establishing the agent hierarchy.

3. After the batch completes (success, error, or timeout), the `finally`
   block at lines 512-530 always executes. For each worker, it:
   - Resets carrier attributes (`_pending_prompt`, `_result`, etc.)
   - Resets structured output wiring if applicable
   - Sets `worker.parent_agent = None` at line 529
   - Releases the worker back to the pool at line 530

4. The `parent_agent = None` assignment at line 529 is the critical Bug-7
   fix. Without it, the next `ParallelAgent` construction that includes
   this worker would raise `ValueError` because `parent_agent` is already
   set.

5. The `finally` block iterates over ALL workers in the batch, not just
   successful ones. Even if a worker timed out or raised an error, its
   `parent_agent` is cleared. This is important because a `TimeoutError`
   at the dispatch level (FM-10) does not prevent the `finally` block from
   running.

6. Residual risk: If the `finally` block itself raises an exception BEFORE
   reaching line 529 for a given worker (e.g., `worker._pending_prompt =
   None` raises because the worker object is corrupted), that worker's
   `parent_agent` would not be cleared, and subsequent workers in the loop
   would also be skipped. This is unlikely because the cleanup operations
   are simple attribute assignments.

**Testability Assessment:** Partially tested. Multi-worker e2e fixtures
(e.g., `structured_output_batched_k3.json`, `worker_429_mid_batch.json`)
exercise the full dispatch path including the `finally` block, which means
`parent_agent = None` is executed. However, no test explicitly asserts:
(a) that `parent_agent` is None after dispatch, or (b) that a worker can
be successfully reused in a second batch after being released. The existing
unit tests in `test_bug006_pool_growth.py` test pool size capping but do
not touch `parent_agent`.

**Recommended Test Scenario:**

1. Create a `WorkerPool` with `pool_size=2`.
2. Dispatch a batch of 2 prompts (using ParallelAgent).
3. After dispatch completes, verify `worker.parent_agent is None` for both
   workers.
4. Dispatch a second batch of 2 prompts using the same pool.
5. Verify the second dispatch succeeds without `ValueError` (proving
   workers were properly cleaned up and reusable).
6. Edge case: inject an exception in the `finally` cleanup before the
   `parent_agent = None` line, verify the next dispatch raises `ValueError`.

**Gaps:**
- No test asserts `worker.parent_agent is None` after dispatch.
- No test verifies multi-batch worker reuse through the pool (acquire,
  dispatch, release, acquire again, dispatch again).
- The `finally` block's robustness against mid-cleanup exceptions is
  untested. If line 514 (`worker._pending_prompt = None`) raised, lines
  515-530 would be skipped for that worker.
- No e2e fixture specifically targets the re-pooling path (most fixtures
  are single-batch).

---

## Summary

| FM | Name | RPN | Testability | Current Coverage | Key Finding |
|----|------|-----|-------------|------------------|-------------|
| FM-13 | CancelledError Swallowed by REPLTool | 56 | Unit-testable | Unit test validates swallowing (not correctness) | `except (Exception, asyncio.CancelledError)` catches cancellation and converts to stderr; cancellation signal lost; flush_fn skipped |
| FM-11 | Worker Pool Exhaustion with On-Demand Creation | 54 | Unit-testable | 3 pool-cap unit tests (no e2e) | `get_nowait()` + synchronous `_create_worker()` blocks event loop; on-demand workers properly discarded at release |
| FM-10 | Worker Dispatch Timeout | 50 | Integration test needed | No coverage | `asyncio.wait_for` cancels inner coroutine; timed-out workers get `error_category="UNKNOWN"` instead of `"TIMEOUT"`; `OBS_WORKER_TIMEOUT_COUNT` never written |
| FM-12 | Worker parent_agent Not Cleared | 16 | Unit + e2e testable | Partial (exercised, not asserted) | `finally` block at line 529 clears `parent_agent`; Bug-7 fix is reliable but no test asserts on re-pooling correctness |

**Key architectural insight:** These four failure modes span the lifecycle of
a worker dispatch: pool acquisition (FM-11), execution timeout (FM-10), REPL
error handling (FM-13), and post-dispatch cleanup (FM-12). The current
implementation handles all four defensively, but the defenses have gaps:

1. **FM-13** is a semantic bug -- `CancelledError` should propagate, not be
   swallowed. The current behavior violates asyncio's cancellation contract.
2. **FM-11** is a design tradeoff -- on-demand creation prevents deadlock
   but stalls the event loop. The tradeoff is reasonable given the
   alternative (deadlock).
3. **FM-10** has an observability gap -- timeouts produce `"UNKNOWN"` error
   category instead of `"TIMEOUT"`, and the `OBS_WORKER_TIMEOUT_COUNT`
   state key is defined but never written.
4. **FM-12** is well-mitigated by the Bug-7 fix, but the mitigation is
   exercised indirectly (never explicitly asserted in tests).
