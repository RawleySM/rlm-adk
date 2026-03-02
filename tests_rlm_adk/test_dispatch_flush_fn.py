"""Tests for dispatch.py flush_fn.

Verifies:
1. create_dispatch_closures returns a 3-tuple (llm_query_async, llm_query_batched_async, flush_fn)
2. flush_fn returns accumulated state (dispatch counts, latencies)
3. flush_fn resets accumulators after call
4. Dispatch works without event_queue (events consumed and discarded)
"""

from unittest.mock import MagicMock

import pytest

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures


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


# ── Tests ────────────────────────────────────────────────────────────────


class TestFlushFn:
    """Tests for the flush_fn closure returned by create_dispatch_closures."""

    def test_create_dispatch_closures_returns_3_tuple(self):
        """create_dispatch_closures must return a 3-tuple."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()
        ctx = _make_invocation_context()

        result = create_dispatch_closures(pool, ctx)
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) == 3, f"Expected 3-tuple, got {len(result)}-tuple"

    def test_flush_fn_is_callable(self):
        """The third element of the return tuple must be callable."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()
        ctx = _make_invocation_context()

        _, _, flush_fn = create_dispatch_closures(pool, ctx)
        assert callable(flush_fn), f"flush_fn is not callable: {type(flush_fn)}"

    @pytest.mark.asyncio
    async def test_flush_fn_returns_accumulated_state(self):
        """After a dispatch, flush_fn should return accumulated counts."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()

        worker = pool._pools["test-model"].get_nowait()

        async def mock_run(_ctx):
            worker._result = "done"  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            return
            yield  # make it an async generator

        _patch_worker_run(worker, mock_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        llm_query_async, _, flush_fn = create_dispatch_closures(pool, ctx)

        await llm_query_async("test prompt")

        delta = flush_fn()
        assert isinstance(delta, dict)
        assert "worker_dispatch_count" in delta
        assert delta["worker_dispatch_count"] >= 1
        assert "obs:worker_total_dispatches" in delta
        assert "obs:worker_dispatch_latency_ms" in delta

    @pytest.mark.asyncio
    async def test_flush_fn_resets_accumulators(self):
        """After flush_fn is called, accumulators should be reset to zero."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()

        worker = pool._pools["test-model"].get_nowait()

        async def mock_run(_ctx):
            worker._result = "done"  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            return
            yield

        _patch_worker_run(worker, mock_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        llm_query_async, _, flush_fn = create_dispatch_closures(pool, ctx)

        await llm_query_async("test prompt")

        # First flush: should have counts
        delta1 = flush_fn()
        assert delta1["worker_dispatch_count"] >= 1

        # Second flush: should be reset
        delta2 = flush_fn()
        assert delta2["worker_dispatch_count"] == 0
        assert delta2["obs:worker_total_dispatches"] == 0
        assert delta2["obs:worker_dispatch_latency_ms"] == []

    @pytest.mark.asyncio
    async def test_dispatch_without_event_queue_works(self):
        """Dispatch with event_queue=None should work (events consumed and discarded)."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        pool.ensure_initialized()

        worker = pool._pools["test-model"].get_nowait()

        async def mock_run(_ctx):
            worker._result = "result text"  # type: ignore[attr-defined]
            worker._result_ready = True  # type: ignore[attr-defined]
            return
            yield

        _patch_worker_run(worker, mock_run)
        pool._pools["test-model"].put_nowait(worker)

        ctx = _make_invocation_context()
        # No event_queue -- should default to None
        llm_query_async, _, flush_fn = create_dispatch_closures(pool, ctx)

        result = await llm_query_async("test prompt")
        assert str(result) == "result text"

