"""Tests for per-child summary writes via child_obs_key in dispatch flush_fn.

Verifies that after _run_child completes (success or error), flush_fn() returns
a dict containing child_obs_key(depth+1, fanout_idx) keys with at minimum:
  {model, elapsed_ms, error, error_category}

For batched calls, one key per fanout index must be present.
"""

from unittest.mock import MagicMock, patch

import pytest

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.state import child_obs_key


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_invocation_context(invocation_id: str = "test") -> MagicMock:
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
        yield  # make it an async generator

    child.run_async = mock_run_async
    return child


def _make_failing_child():
    """Create a mock child orchestrator that raises an exception."""
    child = MagicMock()
    child.persistent = False
    child.repl = None
    reasoning = MagicMock()
    reasoning.output_key = "reasoning_output@d1"
    child.reasoning_agent = reasoning

    async def mock_run_async(ctx):
        raise RuntimeError("simulated child failure")
        yield  # noqa: unreachable — makes it an async generator

    child.run_async = mock_run_async
    return child


# ── Tests ────────────────────────────────────────────────────────────────


class TestChildObsSummary:
    """flush_fn must include per-child summary dict keyed by child_obs_key."""

    @pytest.mark.asyncio
    async def test_single_dispatch_summary_key_present(self):
        """After a single llm_query_async, flush_fn contains child_obs_key(1, 0)."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_mock_child("hello world")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("test prompt")

        delta = flush_fn()
        expected_key = child_obs_key(1, 0)  # depth+1=1, fanout_idx=0
        assert expected_key in delta, (
            f"Expected key '{expected_key}' in flush delta, got keys: {list(delta.keys())}"
        )

    @pytest.mark.asyncio
    async def test_single_dispatch_summary_has_required_fields(self):
        """The child summary dict must contain model, elapsed_ms, error, error_category."""
        pool = WorkerPool(default_model="my-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_mock_child("answer text")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("test prompt")

        delta = flush_fn()
        summary = delta[child_obs_key(1, 0)]

        assert isinstance(summary, dict), f"Expected dict summary, got {type(summary)}"
        assert "model" in summary, "Summary missing 'model'"
        assert "elapsed_ms" in summary, "Summary missing 'elapsed_ms'"
        assert "error" in summary, "Summary missing 'error'"
        assert "error_category" in summary, "Summary missing 'error_category'"

    @pytest.mark.asyncio
    async def test_single_dispatch_summary_values_correct(self):
        """Summary values reflect the child result: model matches, error=False on success."""
        pool = WorkerPool(default_model="my-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_mock_child("the answer")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("test prompt")

        delta = flush_fn()
        summary = delta[child_obs_key(1, 0)]

        assert summary["model"] == "my-model", f"Expected model='my-model', got {summary['model']!r}"
        assert summary["error"] is False, f"Expected error=False, got {summary['error']!r}"
        assert summary["error_category"] is None, f"Expected error_category=None, got {summary['error_category']!r}"
        assert isinstance(summary["elapsed_ms"], (int, float)), (
            f"elapsed_ms should be numeric, got {type(summary['elapsed_ms'])}"
        )
        assert summary["elapsed_ms"] >= 0, f"elapsed_ms should be >= 0, got {summary['elapsed_ms']}"

    @pytest.mark.asyncio
    async def test_error_dispatch_summary_has_error_true(self):
        """When child raises an exception, summary records error=True with category."""
        pool = WorkerPool(default_model="my-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_failing_child()

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            result = await llm_query_async("test prompt")

        # The call itself should not raise (errors are wrapped)
        assert result.error is True

        delta = flush_fn()
        summary = delta.get(child_obs_key(1, 0))
        assert summary is not None, f"Expected summary key in delta, got: {list(delta.keys())}"
        assert summary["error"] is True, f"Expected error=True for failed child, got {summary['error']!r}"

    @pytest.mark.asyncio
    async def test_batch_dispatch_all_fanout_keys_present(self):
        """llm_query_batched_async with k=3 produces child_obs_key(1,0), (1,1), (1,2)."""
        pool = WorkerPool(default_model="batch-model", pool_size=3)
        ctx = _make_invocation_context()

        def make_child_for(idx):
            return _make_mock_child(f"answer-{idx}")

        children = [make_child_for(i) for i in range(3)]
        call_count = {"n": 0}

        def side_effect(**kwargs):
            c = children[call_count["n"]]
            call_count["n"] += 1
            return c

        with patch("rlm_adk.agent.create_child_orchestrator", side_effect=side_effect):
            _, llm_query_batched_async, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            results = await llm_query_batched_async(["p0", "p1", "p2"])

        assert len(results) == 3

        delta = flush_fn()
        for fanout_idx in range(3):
            key = child_obs_key(1, fanout_idx)
            assert key in delta, (
                f"Expected key '{key}' for fanout {fanout_idx} in delta, "
                f"got keys: {list(delta.keys())}"
            )

    @pytest.mark.asyncio
    async def test_flush_resets_child_summaries(self):
        """After flush_fn(), a second flush contains no child summary keys."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_mock_child("done")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("test prompt")

        delta1 = flush_fn()
        assert any("obs:child_summary@" in k for k in delta1), (
            "First flush should have child_summary keys"
        )

        delta2 = flush_fn()
        leftover = [k for k in delta2 if "obs:child_summary@" in k]
        assert leftover == [], f"Second flush should have no child_summary keys, got: {leftover}"

    @pytest.mark.asyncio
    async def test_depth_limit_does_not_write_summary(self):
        """When depth limit is hit (early return), no child_summary key is written."""
        pool = WorkerPool(default_model="test-model", pool_size=1)
        ctx = _make_invocation_context()

        # depth=2, max_depth=3 means depth+1=3 >= max_depth → early return
        with patch("rlm_adk.agent.create_child_orchestrator") as mock_create:
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=2, max_depth=3,
            )
            result = await llm_query_async("test prompt")

        # create_child_orchestrator should NOT have been called (early return)
        mock_create.assert_not_called()
        assert result.error is True
        assert result.error_category == "DEPTH_LIMIT"

        delta = flush_fn()
        summary_keys = [k for k in delta if "obs:child_summary@" in k]
        assert summary_keys == [], f"Depth-limited call should not write summary, got: {summary_keys}"
