"""FR-011 + AR-HIGH-003/005: Worker pool dispatch and isolation.

FR-011: Sub-LM query support (single, batched, model override).
AR-HIGH-003: Worker agent isolation (include_contents, disallow_transfer).
AR-HIGH-005: Routing semantics (depth-based default, model= override).
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures

# ── AR-HIGH-003 Worker Agent Isolation ───────────────────────────────────


class TestWorkerIsolation:
    """AR-HIGH-003: Workers must enforce isolation constraints."""

    def test_workers_include_contents_none(self):
        pool = WorkerPool(default_model="model-a", pool_size=1)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        assert worker.include_contents == "none"

    def test_workers_disallow_transfer_to_parent(self):
        pool = WorkerPool(default_model="model-a", pool_size=1)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        assert worker.disallow_transfer_to_parent is True

    def test_workers_disallow_transfer_to_peers(self):
        pool = WorkerPool(default_model="model-a", pool_size=1)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        assert worker.disallow_transfer_to_peers is True

    def test_workers_have_callbacks(self):
        pool = WorkerPool(default_model="model-a", pool_size=1)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        assert worker.before_model_callback is not None
        assert worker.after_model_callback is not None

    def test_workers_have_pending_prompt_slot(self):
        pool = WorkerPool(default_model="model-a", pool_size=1)
        pool.register_model("model-a")
        worker = pool._pools["model-a"].get_nowait()
        assert hasattr(worker, "_pending_prompt")
        assert worker._pending_prompt is None


# ── AR-HIGH-005 Routing Semantics ────────────────────────────────────────


class TestWorkerPoolRouting:
    """AR-HIGH-005: Depth-based default and model= override routing."""

    def test_default_model_and_other_model(self):
        pool = WorkerPool(default_model="main-model", other_model="sub-model")
        assert pool.default_model == "main-model"
        assert pool.other_model == "sub-model"

    def test_other_model_defaults_to_default(self):
        pool = WorkerPool(default_model="model-x")
        assert pool.other_model == "model-x"

    def test_ensure_initialized_creates_pools(self):
        pool = WorkerPool(default_model="main", other_model="sub", pool_size=3)
        pool.ensure_initialized()
        assert "main" in pool._pools
        assert "sub" in pool._pools
        assert pool._pools["main"].qsize() == 3
        assert pool._pools["sub"].qsize() == 3

    @pytest.mark.asyncio
    async def test_acquire_default_uses_other_model(self):
        pool = WorkerPool(default_model="main", other_model="sub", pool_size=1)
        pool.ensure_initialized()
        worker = await pool.acquire(model=None)
        assert worker.model == "sub"
        await pool.release(worker)

    @pytest.mark.asyncio
    async def test_acquire_explicit_model(self):
        pool = WorkerPool(default_model="main", other_model="sub", pool_size=1)
        pool.ensure_initialized()
        # Explicit model auto-registers
        worker = await pool.acquire(model="custom-model")
        assert worker.model == "custom-model"
        await pool.release(worker, model="custom-model")

    @pytest.mark.asyncio
    async def test_release_returns_to_pool(self):
        pool = WorkerPool(default_model="main", other_model="sub", pool_size=2)
        pool.ensure_initialized()
        w1 = await pool.acquire()
        assert pool._pools["sub"].qsize() == 1
        await pool.release(w1)
        assert pool._pools["sub"].qsize() == 2


class TestWorkerPoolRegistration:
    """Pool registration and auto-registration."""

    def test_register_model_creates_correct_size(self):
        pool = WorkerPool(default_model="m", pool_size=5)
        pool.register_model("m")
        assert pool._pools["m"].qsize() == 5

    def test_register_model_custom_size(self):
        pool = WorkerPool(default_model="m", pool_size=5)
        pool.register_model("m", pool_size=3)
        assert pool._pools["m"].qsize() == 3

    @pytest.mark.asyncio
    async def test_auto_register_on_acquire(self):
        pool = WorkerPool(default_model="main", pool_size=2)
        pool.ensure_initialized()
        worker = await pool.acquire(model="new-model")
        assert "new-model" in pool._pools
        await pool.release(worker, model="new-model")

    def test_worker_names_unique(self):
        pool = WorkerPool(default_model="m", pool_size=3)
        pool.register_model("m")
        names = set()
        for _ in range(3):
            w = pool._pools["m"].get_nowait()
            names.add(w.name)
        assert len(names) == 3


class TestDispatchClosures:
    """FR-011: Dispatch closure creation and empty-prompts edge case."""

    @pytest.mark.asyncio
    async def test_empty_prompts_returns_empty(self):
        pool = WorkerPool(default_model="m", pool_size=1)
        pool.ensure_initialized()
        ctx = MagicMock()
        ctx.session.state = {}
        event_queue = asyncio.Queue()

        _, batched_fn, _ = create_dispatch_closures(pool, ctx, event_queue)
        results = await batched_fn([])
        assert results == []
