# GAP-TH-005: Unbounded thread creation under recursive dispatch -- `max_depth` limits depth but not concurrent thread count

**Severity**: MEDIUM
**Category**: threading
**Files**: `rlm_adk/repl/local_repl.py`, `rlm_adk/dispatch.py`, `rlm_adk/repl/thread_bridge.py`

## Problem

Each `execute_code_threaded` call creates a new `ThreadPoolExecutor(max_workers=1)` (line 453). Each `llm_query()` call in REPL code dispatches to the event loop, which may spawn a child orchestrator, which calls `execute_code_threaded` again with ANOTHER `ThreadPoolExecutor`. Additionally, `llm_query_batched()` can spawn up to `max_concurrent` (default 3) children simultaneously via `asyncio.gather` (dispatch.py line 500).

The maximum concurrent thread count is:

```
threads = product of fanout at each depth level

Example with max_depth=5, max_concurrent=3:
- Depth 0: 1 thread (root REPL)
- Depth 1: 3 threads (batched llm_query with 3 prompts)
- Depth 2: 9 threads (each child batches 3 more)
- Depth 3: 27 threads
- Depth 4: 81 threads
Total: 121 threads
```

With `max_concurrent=3` and `max_depth=5`, worst case is 3^4 = 81 concurrent threads (depth 0 through depth 4, each fanning out by 3). With higher concurrency or depth settings, this grows exponentially.

The `_THREAD_DEPTH` ContextVar was intended to limit this, but as documented in GAP-TH-002, it doesn't propagate across thread boundaries. The `max_depth` check in `dispatch.py` (line 281) limits depth but not fanout. The `_child_semaphore` limits concurrency at each level (default 3 via `RLM_MAX_CONCURRENT_CHILDREN`), but doesn't account for the multiplicative effect across levels.

While 81-121 threads is manageable on modern systems, the bound is not explicitly documented or enforced. If someone sets `RLM_MAX_DEPTH=10` and `RLM_MAX_CONCURRENT_CHILDREN=10`, worst case is 10^9 = 1 billion threads (in theory -- in practice the system would run out of memory first).

## Evidence

```python
# local_repl.py line 453
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

# dispatch.py lines 141-142
max_depth = int(os.getenv("RLM_MAX_DEPTH", str(max_depth)))
max_concurrent = int(os.getenv("RLM_MAX_CONCURRENT_CHILDREN", "3"))

# dispatch.py line 500
results = await asyncio.gather(*tasks)  # All children run concurrently
```

The thread count formula is: `sum(max_concurrent^d for d in range(max_depth))`.

## Suggested Fix

Add a process-wide thread counter (not a ContextVar -- use `threading.Semaphore` or an `AtomicInteger` equivalent):

```python
# In thread_bridge.py or local_repl.py
import threading

_GLOBAL_THREAD_COUNT = threading.Semaphore(
    int(os.environ.get("RLM_MAX_TOTAL_THREADS", "50"))
)

async def execute_code_threaded(self, code, trace=None):
    acquired = _GLOBAL_THREAD_COUNT.acquire(blocking=False)
    if not acquired:
        return REPLResult(
            stdout="", stderr="Thread pool exhausted", ...
        )
    try:
        # ... existing logic ...
    finally:
        _GLOBAL_THREAD_COUNT.release()
```

This caps the total number of concurrent REPL worker threads across all depth levels.

Alternatively, document the expected bounds and add a warning log when thread count exceeds a threshold.
