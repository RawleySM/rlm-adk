"""Tests for dispatch.py flush_fn.

Verifies:
1. create_dispatch_closures returns a 3-tuple (llm_query_async, llm_query_batched_async, flush_fn)
2. flush_fn returns accumulated state (dispatch counts, latencies)
3. flush_fn resets accumulators after call
4. Dispatch works without event_queue (events consumed and discarded)

Updated for Phase 3: child orchestrator dispatch (no more WorkerPool internals).
"""

from unittest.mock import MagicMock, patch

import pytest

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_invocation_context(invocation_id: str = "test") -> MagicMock:
    """Build a mock InvocationContext for dispatch closure tests."""
    ctx = MagicMock()
    ctx.invocation_id = invocation_id
    ctx.session.state = {}
    return ctx


def _make_mock_child(answer: str, output_key: str = "reasoning_output@d1"):
    """Create a mock child orchestrator that writes answer to session state."""
    child = MagicMock()
    child.persistent = False
    child.repl = None
    reasoning = MagicMock()
    reasoning.output_key = output_key
    child.reasoning_agent = reasoning

    async def mock_run_async(ctx):
        ctx.session.state[output_key] = answer
        return
        yield

    child.run_async = mock_run_async
    return child


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
        ctx = _make_invocation_context()

        child = _make_mock_child("done")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("test prompt")

        delta = flush_fn()
        assert isinstance(delta, dict)
        assert "obs:child_dispatch_count" in delta
        assert delta["obs:child_dispatch_count"] >= 1
        assert "obs:child_dispatch_latency_ms" in delta

    @pytest.mark.asyncio
    async def test_flush_fn_resets_accumulators(self):
        """After flush_fn is called, accumulators should be reset to zero."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        ctx = _make_invocation_context()

        child = _make_mock_child("done")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("test prompt")

        # First flush: should have counts
        delta1 = flush_fn()
        assert delta1["obs:child_dispatch_count"] >= 1

        # Second flush: should be reset
        delta2 = flush_fn()
        assert delta2["obs:child_dispatch_count"] == 0
        assert delta2["obs:child_dispatch_latency_ms"] == []

    @pytest.mark.asyncio
    async def test_dispatch_without_event_queue_works(self):
        """Dispatch should work (events consumed by child orchestrator)."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        ctx = _make_invocation_context()

        child = _make_mock_child("result text")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            result = await llm_query_async("test prompt")

        assert str(result) == "result text"
