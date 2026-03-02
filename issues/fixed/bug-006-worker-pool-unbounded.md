# Bug 006: Worker Pool Grows Unboundedly on Exhaustion

## Summary

The `WorkerPool` in `dispatch.py` grows permanently whenever a batch dispatch
exceeds the configured `pool_size`. On-demand workers created to prevent
deadlocks are returned to the pool alongside original workers, inflating the
pool beyond its intended capacity. The pool never shrinks, constituting a
memory leak under sustained burst load.

## Affected Code

**File:** `rlm_adk/dispatch.py`

### 1. Pool initialization (`register_model`, lines 66-82)

The pool is created as an **unbounded** `asyncio.Queue` and populated with
exactly `pool_size` workers:

```python
queue: asyncio.Queue[LlmAgent] = asyncio.Queue()   # no maxsize
for _ in range(size):
    worker = self._create_worker(model_name)
    queue.put_nowait(worker)
```

With default `pool_size=5`, the queue starts with 5 workers.

### 2. On-demand creation (`acquire`, lines 114-139)

When the pool is exhausted (batch size > pool size), new workers are created
on-demand to avoid deadlocks:

```python
try:
    return self._pools[target_model].get_nowait()
except asyncio.QueueEmpty:
    logger.info("Pool '%s' exhausted, creating worker on demand", target_model)
    return self._create_worker(target_model)
```

For a batch of 22 prompts with `pool_size=5`, this creates 17 on-demand workers.

### 3. Unconditional release (`release`, lines 141-150)

All workers -- both original and on-demand -- are returned to the pool without
any capacity check:

```python
async def release(self, worker: LlmAgent, model: str | None = None):
    target_model = model or self.other_model
    if target_model in self._pools:
        await self._pools[target_model].put(worker)
```

### 4. Finally block (`llm_query_batched_async`, lines 297-301)

Every acquired worker is released back, including on-demand ones:

```python
finally:
    for worker in workers:
        worker._pending_prompt = None
        await worker_pool.release(worker, model)
```

## Reproduction Scenario

1. Initialize `WorkerPool` with `pool_size=5`.
2. Dispatch a batch of 22 prompts via `llm_query_batched_async`.
3. `acquire()` is called 22 times:
   - First 5 calls return pre-allocated workers from the queue.
   - Next 17 calls hit `QueueEmpty`, creating 17 on-demand workers.
4. After the batch completes, the `finally` block releases all 22 workers
   back into the queue.
5. The pool now contains **22 workers** instead of the configured **5**.
6. Subsequent batches of size K <= 22 reuse these 22 workers, but the pool
   never shrinks back to 5.
7. Each burst that exceeds the current pool size ratchets the pool higher.
   Under sustained burst load, the pool grows indefinitely.

## Impact

- **Memory leak**: Each `LlmAgent` instance holds model configuration,
  callback references, and internal state. Hundreds or thousands of orphaned
  workers accumulate under sustained burst traffic.
- **Misleading pool_size**: The configured `pool_size` parameter has no
  effect as an upper bound; it only controls the initial allocation.
- **No steady-state recovery**: Even after load subsides, the oversized pool
  persists for the lifetime of the process.

## Root Cause

The `release()` method performs an unconditional `put()` on an unbounded
queue. There is no check to enforce that the pool does not exceed its
configured `pool_size`. On-demand workers are indistinguishable from original
pool workers at release time.

## Resolution

**Fixed in:** `rlm_adk/dispatch.py`, method `WorkerPool.release()`

**Approach:** Added a capacity check in `release()` that compares the current
queue size against `self.pool_size` before returning a worker. If the pool is
already at capacity, the worker is silently discarded with a debug log message
instead of being put back into the queue. This ensures on-demand workers
created during pool exhaustion are garbage-collected after use, while original
pool workers are always returned (since they are released while the pool is
below capacity).

**Code change:**

```python
async def release(self, worker: LlmAgent, model: str | None = None):
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

**Tests added:** `tests_rlm_adk/test_bug006_pool_growth.py` (3 tests)

- `test_pool_does_not_grow_beyond_pool_size` -- Acquires 6 workers from a
  pool_size=3 pool, releases all 6, verifies pool remains at 3.
- `test_on_demand_workers_are_discarded` -- Drains the pool, creates on-demand
  workers, releases on-demand first, verifies pool never exceeds pool_size.
- `test_repeated_bursts_do_not_accumulate` -- Runs 5 burst cycles of 7
  workers each against a pool_size=3 pool, verifies no ratcheting growth.

**Test results:** All 3 new tests pass. All 234 previously passing tests
remain green. The 27 pre-existing failures (bug001, bug002, bug004, bug005)
are unrelated.
