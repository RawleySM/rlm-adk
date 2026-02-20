"""Tests for Bug 006: Worker pool grows unboundedly on exhaustion.

The WorkerPool must NOT grow beyond pool_size when on-demand workers
are released back. On-demand workers created during pool exhaustion
should be discarded on release rather than returned to the pool.
"""

import asyncio
import pytest


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_pool_does_not_grow_beyond_pool_size():
    """After acquiring more workers than pool_size and releasing all,
    the pool should remain at pool_size, not grow."""
    from rlm_adk.dispatch import WorkerPool

    pool_size = 3
    pool = WorkerPool(
        default_model="test-model",
        other_model="test-model",
        pool_size=pool_size,
    )
    pool.register_model("test-model", pool_size=pool_size)

    # Acquire 6 workers: 3 from pool + 3 on-demand
    workers = []
    for _ in range(6):
        w = await pool.acquire("test-model")
        workers.append(w)

    # Pool should be empty now (3 taken from queue, 3 created on-demand)
    assert pool._pools["test-model"].qsize() == 0

    # Release all 6 workers back
    for w in workers:
        await pool.release(w, "test-model")

    # The pool must NOT have grown beyond pool_size
    assert pool._pools["test-model"].qsize() == pool_size, (
        f"Pool grew to {pool._pools['test-model'].qsize()} workers, "
        f"expected at most {pool_size}"
    )


@pytest.mark.asyncio
async def test_on_demand_workers_are_discarded():
    """On-demand workers should be discarded, not returned to the pool."""
    from rlm_adk.dispatch import WorkerPool

    pool_size = 2
    pool = WorkerPool(
        default_model="test-model",
        other_model="test-model",
        pool_size=pool_size,
    )
    pool.register_model("test-model", pool_size=pool_size)

    # Drain the pool
    original_workers = []
    for _ in range(pool_size):
        w = await pool.acquire("test-model")
        original_workers.append(w)

    # Create on-demand workers
    on_demand_workers = []
    for _ in range(3):
        w = await pool.acquire("test-model")
        on_demand_workers.append(w)

    # Release on-demand workers first
    for w in on_demand_workers:
        await pool.release(w, "test-model")

    # Pool should have at most pool_size workers
    assert pool._pools["test-model"].qsize() <= pool_size

    # Release original workers
    for w in original_workers:
        await pool.release(w, "test-model")

    # Pool should still be exactly pool_size
    assert pool._pools["test-model"].qsize() == pool_size, (
        f"Pool grew to {pool._pools['test-model'].qsize()} workers, "
        f"expected exactly {pool_size}"
    )


@pytest.mark.asyncio
async def test_repeated_bursts_do_not_accumulate():
    """Multiple burst cycles should not cause the pool to ratchet upward."""
    from rlm_adk.dispatch import WorkerPool

    pool_size = 3
    pool = WorkerPool(
        default_model="test-model",
        other_model="test-model",
        pool_size=pool_size,
    )
    pool.register_model("test-model", pool_size=pool_size)

    for _ in range(5):  # 5 burst cycles
        workers = []
        for _ in range(7):  # each burst acquires 7 (4 on-demand)
            w = await pool.acquire("test-model")
            workers.append(w)

        for w in workers:
            await pool.release(w, "test-model")

    # After 5 burst cycles, pool must still be at pool_size
    assert pool._pools["test-model"].qsize() == pool_size, (
        f"After 5 bursts, pool grew to {pool._pools['test-model'].qsize()} "
        f"workers, expected {pool_size}"
    )
