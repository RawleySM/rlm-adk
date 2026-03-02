"""FR-011 + AR-HIGH-003/005: Worker pool dispatch and isolation.

FR-011: Sub-LM query support (single, batched, model override).
AR-HIGH-003: Worker agent isolation (include_contents, disallow_transfer).
AR-HIGH-005: Routing semantics (depth-based default, model= override).

Also covers FMEA items:
- FM-11 (item 14): _worker_counter increases when pool exhausted (on-demand creation)
- FM-11 (item 15): K > pool_size dispatch batch returns all results
- FM-10 (item 16): Timeout cleanup - workers released and parent_agent cleared
- FM-12 (item 17): worker.parent_agent is None after dispatch
- FM-20 (item 21): worker_after_model raising AttributeError does not crash batch
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.types import LLMResult

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


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_invocation_context(invocation_id: str = "test") -> MagicMock:
    """Build a mock InvocationContext for dispatch closure tests."""
    ctx = MagicMock()
    ctx.invocation_id = invocation_id
    ctx.session.state = {}
    return ctx


def _patch_worker_run(worker, run_fn):
    """Patch run_async on a Pydantic LlmAgent using object.__setattr__."""
    object.__setattr__(worker, "run_async", run_fn)


def _setup_pool_workers_mock(pool, model, result_text="done"):
    """Patch all workers in a pool with a mock run_async that sets result."""
    q = pool._pools[model]
    workers = []
    while not q.empty():
        w = q.get_nowait()
        workers.append(w)
    for w in workers:
        _make_worker_auto_complete(w, result_text)
        q.put_nowait(w)
    return workers


def _make_worker_auto_complete(worker, result_text="done"):
    """Patch a worker so run_async auto-sets result carrier attributes."""
    async def mock_run(_ctx):
        worker._result = result_text
        worker._result_ready = True
        worker._result_error = False
        worker._call_record = {
            "prompt": getattr(worker, "_pending_prompt", None),
            "response": result_text,
            "input_tokens": 10,
            "output_tokens": 5,
            "model": "test-model",
            "finish_reason": "STOP",
            "error": False,
        }
        return
        yield  # make it an async generator
    _patch_worker_run(worker, mock_run)


# ── FM-11 (Item 14): _worker_counter increases on pool exhaustion ──────


class TestWorkerPoolExhaustion:
    """FM-11: Pool exhaustion creates on-demand workers and tracks counter."""

    @pytest.mark.asyncio
    async def test_worker_counter_increases_on_exhaustion(self):
        """After acquiring pool_size + N workers, _worker_counter == pool_size + N."""
        pool_size = 3
        pool = WorkerPool(default_model="test-model", pool_size=pool_size)
        pool.ensure_initialized()

        initial_counter = pool._worker_counter
        assert initial_counter == pool_size  # 3 workers created at init

        # Acquire all pool workers + 2 on-demand
        acquired = []
        for _ in range(pool_size + 2):
            w = await pool.acquire()
            acquired.append(w)

        # Counter should reflect pool_size (initial) + 2 (on-demand)
        assert pool._worker_counter == pool_size + 2
        assert pool._pool_exhaustion_count == 2

        # Release all workers
        for w in acquired:
            await pool.release(w)

    @pytest.mark.asyncio
    async def test_on_demand_workers_are_discarded_on_release(self):
        """Workers beyond pool_size should be discarded, not returned to pool."""
        pool_size = 2
        pool = WorkerPool(default_model="test-model", pool_size=pool_size)
        pool.ensure_initialized()

        # Acquire 4 workers (2 from pool + 2 on-demand)
        acquired = []
        for _ in range(4):
            w = await pool.acquire()
            acquired.append(w)

        assert pool._pools["test-model"].qsize() == 0

        # Release all 4
        for w in acquired:
            await pool.release(w)

        # Pool should only hold pool_size workers (on-demand discarded)
        assert pool._pools["test-model"].qsize() == pool_size


# ── FM-11 (Item 15): K > pool_size dispatch ────────────────────────────


class TestDispatchKExceedsPoolSize:
    """FM-11: Dispatch batch with K > pool_size returns all K results."""

    @pytest.mark.asyncio
    async def test_batch_k_greater_than_pool_size(self):
        """Dispatch K=6 prompts with pool_size=3 returns all 6 results.

        Uses RLM_MAX_CONCURRENT_WORKERS=1 so each prompt is dispatched as a
        single-worker call (bypassing ParallelAgent which cannot be easily mocked).
        """
        pool_size = 3
        k = 6
        pool = WorkerPool(default_model="test-model", pool_size=pool_size)
        pool.ensure_initialized()

        # Patch all initial workers with auto-complete mock
        _setup_pool_workers_mock(pool, "test-model", result_text="result")

        # Also need to patch on-demand workers. We monkeypatch _create_worker
        # to return workers with auto-complete.
        original_create = pool._create_worker

        def patched_create(model_name):
            w = original_create(model_name)
            _make_worker_auto_complete(w, result_text="result")
            return w

        pool._create_worker = patched_create

        ctx = _make_invocation_context()
        _, batched_fn, flush_fn = create_dispatch_closures(pool, ctx)

        # Set max_concurrent=1 so each prompt is dispatched individually
        # (avoids needing to mock ParallelAgent internals)
        with patch.dict("os.environ", {"RLM_MAX_CONCURRENT_WORKERS": "1"}):
            results = await batched_fn([f"prompt_{i}" for i in range(k)])

        assert len(results) == k
        for r in results:
            assert str(r) == "result"
            assert not r.error

        # Pool should still be at pool_size after all releases
        assert pool._pools["test-model"].qsize() == pool_size

        # flush_fn should report all dispatches
        delta = flush_fn()
        assert delta["worker_dispatch_count"] == k
        assert delta["obs:worker_total_dispatches"] == k


# ── FM-10 (Item 16): Timeout cleanup verification ──────────────────────


class TestTimeoutCleanup:
    """FM-10: After timeout, workers are released and parent_agent cleared."""

    @pytest.mark.asyncio
    async def test_timeout_releases_single_worker_and_clears_parent(self):
        """On timeout (K=1), finally block must release worker and clear parent_agent."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()

        q = pool._pools["test-model"]
        w = q.get_nowait()

        async def hanging_run(_ctx):
            await asyncio.sleep(999)
            return
            yield
        _patch_worker_run(w, hanging_run)
        q.put_nowait(w)

        ctx = _make_invocation_context()
        query_fn, _, _ = create_dispatch_closures(pool, ctx)

        with patch("rlm_adk.dispatch._WORKER_DISPATCH_TIMEOUT", 0.01):
            result = await query_fn("prompt_1")

        assert result.error
        assert "timed out" in str(result)

        # Worker should be released back to pool
        assert pool._pools["test-model"].qsize() == 1

        # Worker should have parent_agent cleared
        released = pool._pools["test-model"].get_nowait()
        assert released.parent_agent is None

    @pytest.mark.asyncio
    async def test_timeout_releases_workers_in_batch(self):
        """On timeout (batch via max_concurrent=1), all workers released."""
        pool = WorkerPool(default_model="test-model", pool_size=2)
        pool.ensure_initialized()

        q = pool._pools["test-model"]
        workers_list = []
        while not q.empty():
            w = q.get_nowait()
            workers_list.append(w)

        for w in workers_list:
            async def hanging_run(_ctx, _w=w):
                await asyncio.sleep(999)
                return
                yield
            _patch_worker_run(w, hanging_run)
            q.put_nowait(w)

        ctx = _make_invocation_context()
        _, batched_fn, _ = create_dispatch_closures(pool, ctx)

        with patch("rlm_adk.dispatch._WORKER_DISPATCH_TIMEOUT", 0.01), \
             patch.dict("os.environ", {"RLM_MAX_CONCURRENT_WORKERS": "1"}):
            results = await batched_fn(["prompt_1", "prompt_2"])

        assert len(results) == 2
        for r in results:
            assert r.error

        # Workers should be released back to pool
        assert pool._pools["test-model"].qsize() == 2

        # Workers should have parent_agent cleared
        while not pool._pools["test-model"].empty():
            w = pool._pools["test-model"].get_nowait()
            assert w.parent_agent is None


# ── FM-12 (Item 17): parent_agent cleared after dispatch ───────────────


class TestParentAgentCleared:
    """FM-12: worker.parent_agent must be None after dispatch completes."""

    @pytest.mark.asyncio
    async def test_parent_agent_none_after_single_dispatch(self):
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()
        _setup_pool_workers_mock(pool, "test-model")

        ctx = _make_invocation_context()
        query_fn, _, _ = create_dispatch_closures(pool, ctx)

        await query_fn("test prompt")

        # Get the worker back from the pool and verify parent_agent
        worker = pool._pools["test-model"].get_nowait()
        assert worker.parent_agent is None
        pool._pools["test-model"].put_nowait(worker)

    @pytest.mark.asyncio
    async def test_parent_agent_none_after_batch_dispatch(self):
        """Batch of 3 dispatched individually (max_concurrent=1) clears parent_agent."""
        pool = WorkerPool(default_model="test-model", pool_size=3)
        pool.ensure_initialized()
        _setup_pool_workers_mock(pool, "test-model")

        ctx = _make_invocation_context()
        _, batched_fn, _ = create_dispatch_closures(pool, ctx)

        with patch.dict("os.environ", {"RLM_MAX_CONCURRENT_WORKERS": "1"}):
            await batched_fn(["p1", "p2", "p3"])

        # Drain all workers from pool and verify parent_agent is None
        q = pool._pools["test-model"]
        workers_checked = []
        while not q.empty():
            w = q.get_nowait()
            workers_checked.append(w)

        for w in workers_checked:
            assert w.parent_agent is None, f"{w.name} still has parent_agent set"
        assert len(workers_checked) == 3

        # Put workers back for cleanup
        for w in workers_checked:
            q.put_nowait(w)


# ── FM-20 (Item 21): worker_after_model crash isolation ────────────────


class TestWorkerCallbackCrashIsolation:
    """FM-20: If worker_after_model raises, batch does not crash."""

    @pytest.mark.asyncio
    async def test_attribute_error_in_callback_does_not_crash_batch(self):
        """Monkeypatch worker run to simulate callback AttributeError.
        Dispatch K=2 batch (max_concurrent=1) should complete with error results."""
        pool = WorkerPool(default_model="test-model", pool_size=2)
        pool.ensure_initialized()

        q = pool._pools["test-model"]
        workers = []
        while not q.empty():
            w = q.get_nowait()
            workers.append(w)

        for w in workers:
            async def mock_run_with_callback_error(_ctx, _w=w):
                # Simulate what the after_model callback does on error:
                # The try/except in worker_after_model catches and sets error result
                error_msg = f"[Worker {_w.name} callback error: AttributeError: test attr error]"
                _w._result = error_msg
                _w._result_ready = True
                _w._result_error = True
                _w._call_record = {
                    "prompt": getattr(_w, "_pending_prompt", None),
                    "response": error_msg,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "model": None,
                    "finish_reason": None,
                    "error": True,
                    "error_category": "CALLBACK_ERROR",
                }
                return
                yield
            _patch_worker_run(w, mock_run_with_callback_error)
            q.put_nowait(w)

        ctx = _make_invocation_context()
        _, batched_fn, _ = create_dispatch_closures(pool, ctx)

        with patch.dict("os.environ", {"RLM_MAX_CONCURRENT_WORKERS": "1"}):
            results = await batched_fn(["prompt_1", "prompt_2"])

        # Should not crash, both results should be error LLMResults
        assert len(results) == 2
        for r in results:
            assert isinstance(r, LLMResult)
            assert r.error is True
            assert "AttributeError" in str(r)

    @pytest.mark.asyncio
    async def test_mixed_success_and_callback_error(self):
        """One worker succeeds, another has callback error: both results returned."""
        pool = WorkerPool(default_model="test-model", pool_size=2)
        pool.ensure_initialized()

        q = pool._pools["test-model"]
        w1 = q.get_nowait()
        w2 = q.get_nowait()

        # w1 succeeds
        _make_worker_auto_complete(w1, result_text="success")

        # w2 has callback error
        async def mock_run_error(_ctx):
            error_msg = f"[Worker {w2.name} callback error: AttributeError: no attr]"
            w2._result = error_msg
            w2._result_ready = True
            w2._result_error = True
            w2._call_record = {
                "prompt": getattr(w2, "_pending_prompt", None),
                "response": error_msg,
                "input_tokens": 0,
                "output_tokens": 0,
                "model": None,
                "finish_reason": None,
                "error": True,
                "error_category": "CALLBACK_ERROR",
            }
            return
            yield
        _patch_worker_run(w2, mock_run_error)

        q.put_nowait(w1)
        q.put_nowait(w2)

        ctx = _make_invocation_context()
        _, batched_fn, _ = create_dispatch_closures(pool, ctx)

        with patch.dict("os.environ", {"RLM_MAX_CONCURRENT_WORKERS": "1"}):
            results = await batched_fn(["prompt_ok", "prompt_err"])

        assert len(results) == 2
        assert not results[0].error
        assert str(results[0]) == "success"
        assert results[1].error
        assert "AttributeError" in str(results[1])
