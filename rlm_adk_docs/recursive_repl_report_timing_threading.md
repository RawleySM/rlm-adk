# Recursive Worker REPL Timing/Threading Report

## Current Concurrency Model

- The runtime path is orchestrator -> REPL tool -> dispatch closures -> worker pool -> final answer (`rlm_adk_docs/architecture_summary.md:11-29`, `repomix-architecture-flow-compressed.xml:5-11`, `repomix-architecture-flow-compressed.xml:537-718`).
- `RLMOrchestratorAgent` builds one `LocalREPL` per run (unless a persistent REPL is injected), wires `llm_query_async` / `llm_query_batched_async`, and passes `flush_fn` into `REPLTool` (`rlm_adk/orchestrator.py:110-158`).
- `REPLTool.run_async` uses two execution modes:
  - async path with AST rewrite when `llm_query*` calls are detected (`rlm_adk/tools/repl_tool.py:108-117`)
  - sync path via `LocalREPL.execute_code` otherwise (`rlm_adk/tools/repl_tool.py:118-119`)
- Sync execution uses a per-call single-thread `ThreadPoolExecutor` and a module-global `_EXEC_LOCK` around `exec`, `os.chdir`, and stdout/stderr capture (`rlm_adk/repl/local_repl.py:77-81`, `rlm_adk/repl/local_repl.py:271-339`).
- Async execution does not use `_EXEC_LOCK`; it mutates `self.globals` and process `sys.stdout/stderr` around `await repl_exec_fn()` (`rlm_adk/repl/local_repl.py:385-437`).
- Dispatch concurrency is chunked by `RLM_MAX_CONCURRENT_WORKERS`, but pool exhaustion immediately creates on-demand workers instead of waiting (`rlm_adk/dispatch.py:324-353`, `rlm_adk/dispatch.py:152-179`).
- Worker dispatch timeouts are wrapped with `asyncio.wait_for` for both single and parallel paths (`rlm_adk/dispatch.py:386-414`).

## Recursive Execution Hazards

- Nested dispatch can exceed intended concurrency limits. `llm_query_async` delegates into `llm_query_batched_async`, and `acquire()` creates workers on demand when queue-empty, so recursive or `asyncio.gather`-style nested calls can expand worker cardinality without backpressure (`rlm_adk/dispatch.py:287-289`, `rlm_adk/dispatch.py:152-179`, `rlm_adk/dispatch.py:324-353`).
- Dispatch accumulators are closure-shared (`_acc_dispatch_count`, `_acc_latencies`, etc.) across all nested calls in one REPL invocation; nested paths interleave into one metric bucket and obscure per-branch timing attribution (`rlm_adk/dispatch.py:250-255`, `rlm_adk/dispatch.py:625-659`).
- Worker objects are reused and temporarily mutated (`_pending_prompt`, `_result*`, schema callbacks). If a timed-out run keeps executing after timeout, late writes can race with a reused worker instance (`rlm_adk/dispatch.py:368-380`, `rlm_adk/dispatch.py:592-612`).

## Locking/Timeout Implications

- `_EXEC_LOCK` is global across process, not per REPL. All sync REPL executions serialize, which protects global state but introduces head-of-line blocking under load (`rlm_adk/repl/local_repl.py:77-81`, `rlm_adk/repl/local_repl.py:281-339`).
- Sync timeout does not stop running code. `future.result(timeout=...)` times out, then `shutdown(wait=False)` returns, but running thread cannot be force-killed and may continue holding `_EXEC_LOCK`/CWD window (`rlm_adk/repl/local_repl.py:324-339`).
- Existing tests explicitly wait for timed-out threads before cleanup, indicating known trailing-thread behavior (`tests_rlm_adk/test_source_fixes_fmea.py:271-294`).
- `asyncio.wait_for` timeout handling sets synthetic timeout results and proceeds to release workers; no explicit post-cancel join/verification of worker task termination exists (`rlm_adk/dispatch.py:386-430`, `rlm_adk/dispatch.py:592-612`).
- Pool exhaustion is observable (`_pool_exhaustion_count`) but flush reports pool-level cumulative count, not closure-local delta; semantics can drift over long-lived pools (`rlm_adk/dispatch.py:174`, `rlm_adk/dispatch.py:648-650`).

## Event Loop and Cancellation Risks

- `REPLTool.run_async` directly calls blocking sync execution (`execute_code`) on the event loop thread in the non-LLM path (`rlm_adk/tools/repl_tool.py:118-119`), which can stall unrelated async tasks.
- Cancellation is converted into tool return payloads (`CancelledError: ...`) rather than re-raised, so caller-level cancellation semantics become “error result” semantics (`rlm_adk/tools/repl_tool.py:120-143`).
- Generic exceptions are similarly caught and returned, preventing fail-fast bubbling to orchestrator retry logic for tool-level infrastructure faults (`rlm_adk/tools/repl_tool.py:144-166`).
- For timed worker dispatch, cancellation/timeout path may release workers before underlying coroutine stack is fully quiesced; this is the main reuse race window in nested/high-load cases (`rlm_adk/dispatch.py:386-430`, `rlm_adk/dispatch.py:592-612`).

## Resource Lifecycle Risks

- `orchestrator` only calls `repl.cleanup()` when `persistent=False`; persistent mode intentionally retains temp dirs/state and requires external lifecycle control (`rlm_adk/orchestrator.py:330-334`).
- `LocalREPL.cleanup()` clears globals/locals and deletes temp dir (`rlm_adk/repl/local_repl.py:447-455`); if background sync thread still runs after timeout, lifecycle races are possible (again reflected by test-side sleep) (`tests_rlm_adk/test_source_fixes_fmea.py:271-294`).
- Worker cleanup exceptions are swallowed and processing continues; this avoids cascade failures but can silently leak worker state or skip release (`rlm_adk/dispatch.py:592-617`).
- Worker naming counter is monotonic and grows with each on-demand creation (`rlm_adk/dispatch.py:113-115`, `rlm_adk/dispatch.py:173-179`), which is fine functionally but indicates sustained exhaustion pressure over time.

## Recommended Mitigations

1. Add a per-`LocalREPL` `asyncio.Lock` around `execute_code_async` critical sections that mutate `self.globals`, `self.locals`, and `sys.stdout/stderr` (`rlm_adk/repl/local_repl.py:385-437`).
2. Replace per-call sync `ThreadPoolExecutor` with either a managed long-lived executor + watchdog, or subprocess isolation for hard-kill timeouts; current threads are not preemptible (`rlm_adk/repl/local_repl.py:324-339`).
3. Add a global dispatch semaphore (per orchestrator/session) so nested dispatch cannot bypass concurrency limits via on-demand worker creation (`rlm_adk/dispatch.py:152-179`, `rlm_adk/dispatch.py:324-353`).
4. On `wait_for` timeout, create explicit tasks, cancel, then `await` bounded drain before release; quarantine workers if cancellation confirmation fails (`rlm_adk/dispatch.py:386-430`, `rlm_adk/dispatch.py:592-612`).
5. Separate reusable worker instances from transient result carriers (e.g., external result map keyed by dispatch id) to avoid late-write contamination of recycled workers (`rlm_adk/dispatch.py:368-380`, `rlm_adk/dispatch.py:592-612`).
6. Clarify metric semantics for `OBS_WORKER_POOL_EXHAUSTION_COUNT` as cumulative vs per-iteration delta and align flush behavior accordingly (`rlm_adk/dispatch.py:648-650`).
7. Decide policy for cancellation propagation: keep conversion-to-result behavior, or re-raise cancellations so orchestrator/runtime can enforce cooperative shutdown (`rlm_adk/tools/repl_tool.py:120-166`).

## TDD Checks

- Existing coverage already validates:
  - Worker pool exhaustion creation/discard behavior (`tests_rlm_adk/test_adk_dispatch_worker_pool.py:215-259`, `tests_rlm_adk/test_bug006_pool_growth.py:20-122`)
  - Timeout cleanup + `parent_agent` reset (`tests_rlm_adk/test_adk_dispatch_worker_pool.py:322-390`)
  - Cleanup failure isolation in dispatch finally (`tests_rlm_adk/test_source_fixes_fmea.py:132-240`)
  - `flush_fn` returns and resets dispatch accumulators (`tests_rlm_adk/test_dispatch_flush_fn.py:59-117`)
  - Cancelled/error flush behavior in REPL tool end-to-end (`tests_rlm_adk/test_fmea_e2e.py:807-886`, `tests_rlm_adk/test_fmea_e2e.py:1173-1241`)
  - Async no-`chdir` safety across separate REPL instances (`tests_rlm_adk/test_source_fixes_fmea.py:302-363`)

- High-value missing tests:
  1. Same-REPL concurrent `execute_code_async` race test (globals/open/sys.stdout mutation contention).
  2. Timeout-reuse safety test proving timed-out worker task is fully cancelled before pool release/reacquire.
  3. Nested recursive dispatch stress test (`llm_query_batched_async` inside `asyncio.gather`) with cap assertions on in-flight workers.
  4. Pool exhaustion metric semantics test (cumulative vs delta across multiple `flush_fn` calls).
  5. Event-loop responsiveness test showing non-LLM sync path blocks loop, then validating mitigation once changed.
