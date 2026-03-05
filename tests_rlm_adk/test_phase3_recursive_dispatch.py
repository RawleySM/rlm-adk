"""Tests for Phase 3 recursive dispatch — child orchestrator dispatch.

Verifies:
1. Depth limit returns DEPTH_LIMIT LLMResult
2. Child orchestrator runs and produces result
3. Batched children run concurrently
4. Semaphore limits concurrency
5. Child state isolation (depth-scoped keys)
6. Output schema forwarding
7. flush_fn includes child metrics
8. DispatchConfig backward compat (WorkerPool alias)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rlm_adk.dispatch import DispatchConfig, WorkerPool, create_dispatch_closures
from rlm_adk.types import LLMResult


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_ctx(invocation_id: str = "test") -> MagicMock:
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
        yield  # make it an async generator

    child.run_async = mock_run_async
    return child


def _make_mock_child_with_schema(answer_dict: dict, output_key: str = "reasoning_output@d1"):
    """Create a mock child that writes a JSON dict to state."""
    import json

    child = MagicMock()
    child.persistent = False
    child.repl = None

    reasoning = MagicMock()
    reasoning.output_key = output_key
    child.reasoning_agent = reasoning

    async def mock_run_async(ctx):
        ctx.session.state[output_key] = json.dumps(answer_dict)
        return
        yield

    child.run_async = mock_run_async
    return child


def _make_error_child(error: Exception, output_key: str = "reasoning_output@d1"):
    """Create a mock child that raises during run_async."""
    child = MagicMock()
    child.persistent = False
    child.repl = None

    reasoning = MagicMock()
    reasoning.output_key = output_key
    child.reasoning_agent = reasoning

    async def mock_run_async(ctx):
        raise error
        yield  # noqa: unreachable

    child.run_async = mock_run_async
    return child


# ── Tests ────────────────────────────────────────────────────────────────


class TestDepthLimitReturnsError:
    """At max_depth, llm_query returns DEPTH_LIMIT LLMResult."""

    @pytest.mark.asyncio
    async def test_depth_equals_max_minus_one(self):
        """depth+1 >= max_depth should trigger DEPTH_LIMIT."""
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        llm_query, _, _ = create_dispatch_closures(
            config, ctx, depth=2, max_depth=3,
        )
        result = await llm_query("test prompt")
        assert isinstance(result, LLMResult)
        assert result.error
        assert result.error_category == "DEPTH_LIMIT"
        assert "DEPTH_LIMIT" in str(result)

    @pytest.mark.asyncio
    async def test_depth_exceeds_max(self):
        """depth+1 > max_depth should also trigger DEPTH_LIMIT."""
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        llm_query, _, _ = create_dispatch_closures(
            config, ctx, depth=5, max_depth=3,
        )
        result = await llm_query("test prompt")
        assert result.error
        assert result.error_category == "DEPTH_LIMIT"


class TestChildRunsAndProducesResult:
    """Mock child reasoning to return answer; verify llm_query returns it."""

    @pytest.mark.asyncio
    async def test_basic_child_result(self):
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        child = _make_mock_child("The answer is 42")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query, _, _ = create_dispatch_closures(
                config, ctx, depth=0, max_depth=3,
            )
            result = await llm_query("What is the answer?")

        assert not result.error
        assert str(result) == "The answer is 42"

    @pytest.mark.asyncio
    async def test_child_json_result_extracts_final_answer(self):
        """When child writes JSON with final_answer key, extract it."""
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        child = _make_mock_child_with_schema(
            {"final_answer": "Extracted answer", "reasoning_summary": "done"}
        )

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query, _, _ = create_dispatch_closures(
                config, ctx, depth=0, max_depth=3,
            )
            result = await llm_query("Extract this")

        assert not result.error
        assert result == "Extracted answer"

    @pytest.mark.asyncio
    async def test_child_empty_result_returns_error(self):
        """When child produces empty answer, return NO_RESULT error."""
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        child = _make_mock_child("")  # empty answer

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query, _, _ = create_dispatch_closures(
                config, ctx, depth=0, max_depth=3,
            )
            result = await llm_query("test")

        assert result.error
        assert result.error_category == "NO_RESULT"

    @pytest.mark.asyncio
    async def test_child_exception_returns_error(self):
        """When child raises an exception, return error LLMResult."""
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        child = _make_error_child(RuntimeError("child failed"))

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query, _, _ = create_dispatch_closures(
                config, ctx, depth=0, max_depth=3,
            )
            result = await llm_query("test")

        assert result.error
        assert "child failed" in str(result)


class TestBatchedChildrenConcurrent:
    """3 prompts; all 3 return results."""

    @pytest.mark.asyncio
    async def test_three_prompts_return_three_results(self):
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        call_count = 0

        def make_child(**kwargs):
            nonlocal call_count
            call_count += 1
            idx = call_count
            return _make_mock_child(f"answer_{idx}")

        with patch("rlm_adk.agent.create_child_orchestrator", side_effect=make_child):
            _, llm_query_batched, _ = create_dispatch_closures(
                config, ctx, depth=0, max_depth=3,
            )
            results = await llm_query_batched(["p1", "p2", "p3"])

        assert len(results) == 3
        assert all(not r.error for r in results)
        answers = {str(r) for r in results}
        assert answers == {"answer_1", "answer_2", "answer_3"}


class TestSemaphoreLimitsConcurrency:
    """semaphore=1; verify serial execution."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_to_one(self):
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        max_concurrent_seen = 0
        current_concurrent = 0

        def make_child(**kwargs):
            nonlocal max_concurrent_seen, current_concurrent

            child = MagicMock()
            child.persistent = False
            child.repl = None
            reasoning = MagicMock()
            reasoning.output_key = f"reasoning_output@d1"
            child.reasoning_agent = reasoning

            async def mock_run(run_ctx):
                nonlocal max_concurrent_seen, current_concurrent
                current_concurrent += 1
                if current_concurrent > max_concurrent_seen:
                    max_concurrent_seen = current_concurrent
                await asyncio.sleep(0.01)
                run_ctx.session.state[reasoning.output_key] = "result"
                current_concurrent -= 1
                return
                yield

            child.run_async = mock_run
            return child

        with patch("rlm_adk.agent.create_child_orchestrator", side_effect=make_child):
            with patch.dict("os.environ", {"RLM_MAX_CONCURRENT_CHILDREN": "1"}):
                _, llm_query_batched, _ = create_dispatch_closures(
                    config, ctx, depth=0, max_depth=3,
                )
                results = await llm_query_batched(["p1", "p2", "p3"])

        assert len(results) == 3
        assert max_concurrent_seen == 1


class TestChildStateIsolation:
    """Parent and child write to different depth-scoped keys."""

    @pytest.mark.asyncio
    async def test_depth_scoped_output_keys(self):
        """Child at depth=1 uses output_key 'reasoning_output@d1'."""
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()
        # Pre-set parent state
        ctx.session.state["reasoning_output"] = "parent_answer"

        child = _make_mock_child("child_answer", output_key="reasoning_output@d1")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query, _, _ = create_dispatch_closures(
                config, ctx, depth=0, max_depth=3,
            )
            result = await llm_query("test")

        # Child wrote to depth-scoped key
        assert ctx.session.state["reasoning_output@d1"] == "child_answer"
        # Parent key unchanged
        assert ctx.session.state["reasoning_output"] == "parent_answer"
        assert str(result) == "child_answer"


class TestChildWithOutputSchema:
    """output_schema is forwarded to create_child_orchestrator."""

    @pytest.mark.asyncio
    async def test_output_schema_passed_to_child(self):
        from pydantic import BaseModel

        class MySchema(BaseModel):
            value: str

        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        child = _make_mock_child("schema result")
        captured_kwargs = {}

        def capture_child(**kwargs):
            captured_kwargs.update(kwargs)
            return child

        with patch("rlm_adk.agent.create_child_orchestrator", side_effect=capture_child):
            llm_query, _, _ = create_dispatch_closures(
                config, ctx, depth=0, max_depth=3,
            )
            await llm_query("test", output_schema=MySchema)

        assert captured_kwargs.get("output_schema") is MySchema


class TestFlushFnIncludesChildMetrics:
    """flush_fn returns child dispatch count and latencies."""

    @pytest.mark.asyncio
    async def test_flush_fn_after_dispatch(self):
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        child = _make_mock_child("answer")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query, _, flush_fn = create_dispatch_closures(
                config, ctx, depth=0, max_depth=3,
            )
            await llm_query("test")

        delta = flush_fn()
        assert delta["obs:child_dispatch_count"] == 1
        assert len(delta["obs:child_dispatch_latency_ms"]) == 1
        assert delta["obs:child_dispatch_latency_ms"][0] > 0

    @pytest.mark.asyncio
    async def test_flush_fn_resets_after_call(self):
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        child = _make_mock_child("answer")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query, _, flush_fn = create_dispatch_closures(
                config, ctx, depth=0, max_depth=3,
            )
            await llm_query("test")

        delta1 = flush_fn()
        assert delta1["obs:child_dispatch_count"] == 1

        delta2 = flush_fn()
        assert delta2["obs:child_dispatch_count"] == 0
        assert delta2["obs:child_dispatch_latency_ms"] == []

    @pytest.mark.asyncio
    async def test_flush_fn_includes_error_counts(self):
        """Error results should appear in flush_fn error counts."""
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        # depth=2, max_depth=3 -> DEPTH_LIMIT
        llm_query, _, flush_fn = create_dispatch_closures(
            config, ctx, depth=2, max_depth=3,
        )
        await llm_query("test")

        delta = flush_fn()
        assert "obs:child_error_counts" in delta
        assert delta["obs:child_error_counts"].get("DEPTH_LIMIT", 0) >= 1

    @pytest.mark.asyncio
    async def test_flush_fn_batch_dispatches(self):
        """Batch dispatch of >1 prompts should increment batch count."""
        config = DispatchConfig(default_model="test-model")
        ctx = _make_ctx()

        call_count = 0

        def make_child(**kwargs):
            nonlocal call_count
            call_count += 1
            return _make_mock_child(f"answer_{call_count}")

        with patch("rlm_adk.agent.create_child_orchestrator", side_effect=make_child):
            _, llm_batched, flush_fn = create_dispatch_closures(
                config, ctx, depth=0, max_depth=3,
            )
            await llm_batched(["p1", "p2"])

        delta = flush_fn()
        assert delta["obs:child_dispatch_count"] == 2
        assert delta.get("obs:child_total_batch_dispatches", 0) == 1


class TestDispatchConfigBackwardCompat:
    """WorkerPool alias works for backward compatibility."""

    def test_worker_pool_is_dispatch_config(self):
        assert WorkerPool is DispatchConfig

    def test_worker_pool_constructor(self):
        pool = WorkerPool(default_model="test-model", other_model="other-model")
        assert pool.default_model == "test-model"
        assert pool.other_model == "other-model"

    def test_ensure_initialized_is_noop(self):
        pool = WorkerPool(default_model="test-model")
        pool.ensure_initialized()  # should not raise

    def test_create_dispatch_closures_returns_3_tuple(self):
        config = WorkerPool(default_model="test-model")
        ctx = _make_ctx()
        result = create_dispatch_closures(config, ctx)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert callable(result[2])  # flush_fn
