"""Tests for per-child summary writes via child_obs_key in dispatch flush_fn.

Verifies that after _run_child completes (success or error), flush_fn() returns
a dict containing child_obs_key(depth+1, fanout_idx) keys with at minimum:
  {model, elapsed_ms, error, error_category, prompt_preview, result_preview}

For batched calls, one key per fanout index must be present.
"""

from unittest.mock import MagicMock, patch

import pytest
from google.adk.events import Event, EventActions

from rlm_adk.dispatch import WorkerPool, create_dispatch_closures
from rlm_adk.state import (
    OBS_REASONING_RETRY_COUNT,
    OBS_REASONING_RETRY_DELAY_MS,
    REASONING_FINISH_REASON,
    REASONING_PARSED_OUTPUT,
    REASONING_RAW_OUTPUT,
    REASONING_THOUGHT_TEXT,
    REASONING_THOUGHT_TOKENS,
    REASONING_VISIBLE_OUTPUT_TEXT,
    child_obs_key,
    depth_key,
)


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


def _make_mock_child_with_obs(
    answer: str,
    *,
    depth: int = 1,
    output_key: str | None = None,
    structured_obs: dict | None = None,
    structured_result: dict | None = None,
):
    """Create a child orchestrator that emits child-local state deltas."""
    output_key = output_key or f"reasoning_output@d{depth}"
    child = MagicMock()
    child.persistent = False
    child.repl = None
    reasoning = MagicMock()
    reasoning.output_key = output_key
    if structured_obs is not None:
        reasoning._structured_output_obs = structured_obs
    if structured_result is not None:
        reasoning._structured_result = structured_result
    child.reasoning_agent = reasoning

    async def mock_run_async(ctx):
        ctx.session.state[output_key] = answer
        yield Event(
            invocation_id="test-inv",
            author=f"child_orchestrator_d{depth}",
            actions=EventActions(state_delta={
                output_key: answer,
                depth_key(REASONING_VISIBLE_OUTPUT_TEXT, depth): answer,
                depth_key(REASONING_THOUGHT_TEXT, depth): "hidden child chain",
                depth_key(REASONING_THOUGHT_TOKENS, depth): 4,
                depth_key(REASONING_FINISH_REASON, depth): "STOP",
                depth_key(REASONING_RAW_OUTPUT, depth): {"raw": answer},
                depth_key(REASONING_PARSED_OUTPUT, depth): {
                    "final_answer": answer,
                    "reasoning_summary": "child summary",
                },
                OBS_REASONING_RETRY_COUNT: 1,
                OBS_REASONING_RETRY_DELAY_MS: 250,
            }),
        )

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
    async def test_single_dispatch_summary_has_prompt_preview(self):
        """Child summary must include prompt_preview truncated to 500 chars."""
        pool = WorkerPool(default_model="my-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_mock_child("the answer")

        long_prompt = "x" * 700
        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async(long_prompt)

        delta = flush_fn()
        summary = delta[child_obs_key(1, 0)]

        assert "prompt_preview" in summary, "Summary missing 'prompt_preview'"
        assert isinstance(summary["prompt_preview"], str)
        assert len(summary["prompt_preview"]) <= 500, (
            f"prompt_preview should be <= 500 chars, got {len(summary['prompt_preview'])}"
        )
        assert summary["prompt_preview"] == long_prompt[:500]

    @pytest.mark.asyncio
    async def test_single_dispatch_summary_has_result_preview(self):
        """Child summary must include result_preview truncated to 500 chars."""
        pool = WorkerPool(default_model="my-model", pool_size=1)
        ctx = _make_invocation_context()
        long_answer = "y" * 700
        child = _make_mock_child(long_answer)

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("test prompt")

        delta = flush_fn()
        summary = delta[child_obs_key(1, 0)]

        assert "result_preview" in summary, "Summary missing 'result_preview'"
        assert isinstance(summary["result_preview"], str)
        assert len(summary["result_preview"]) <= 500, (
            f"result_preview should be <= 500 chars, got {len(summary['result_preview'])}"
        )
        assert summary["result_preview"] == long_answer[:500]

    @pytest.mark.asyncio
    async def test_short_prompt_not_truncated(self):
        """Short prompts should be preserved in full."""
        pool = WorkerPool(default_model="my-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_mock_child("answer")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("short prompt")

        delta = flush_fn()
        summary = delta[child_obs_key(1, 0)]
        assert summary["prompt_preview"] == "short prompt"

    @pytest.mark.asyncio
    async def test_error_dispatch_has_error_detail_in_summary(self):
        """When child raises, summary includes error_category and error_message."""
        pool = WorkerPool(default_model="my-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_failing_child()

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("test prompt")

        delta = flush_fn()
        summary = delta[child_obs_key(1, 0)]
        assert summary["error"] is True
        assert "error_message" in summary, "Summary missing 'error_message'"
        assert "simulated child failure" in summary["error_message"]

    @pytest.mark.asyncio
    async def test_success_dispatch_has_no_error_message(self):
        """On success, error_message should be None."""
        pool = WorkerPool(default_model="my-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_mock_child("good answer")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("test prompt")

        delta = flush_fn()
        summary = delta[child_obs_key(1, 0)]
        assert summary["error_message"] is None

    @pytest.mark.asyncio
    async def test_batch_dispatch_summaries_have_previews(self):
        """Batched dispatch: each fanout child summary has prompt_preview and result_preview."""
        pool = WorkerPool(default_model="batch-model", pool_size=3)
        ctx = _make_invocation_context()

        prompts = ["prompt-0", "prompt-1", "prompt-2"]
        children = [_make_mock_child(f"answer-{i}") for i in range(3)]
        call_count = {"n": 0}

        def side_effect(**kwargs):
            c = children[call_count["n"]]
            call_count["n"] += 1
            return c

        with patch("rlm_adk.agent.create_child_orchestrator", side_effect=side_effect):
            _, llm_query_batched_async, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_batched_async(prompts)

        delta = flush_fn()
        for i in range(3):
            summary = delta[child_obs_key(1, i)]
            assert "prompt_preview" in summary, f"fanout {i} missing prompt_preview"
            assert "result_preview" in summary, f"fanout {i} missing result_preview"
            assert summary["prompt_preview"] == f"prompt-{i}"
            assert summary["result_preview"] == f"answer-{i}"

    @pytest.mark.asyncio
    async def test_summary_persists_hidden_child_outputs_and_retry_state(self):
        """Child summary should persist hidden output details even if parent never prints them."""
        pool = WorkerPool(default_model="my-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_mock_child_with_obs("hidden answer")

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("silent prompt")

        summary = flush_fn()[child_obs_key(1, 0)]
        assert summary["final_answer"] == "hidden answer"
        assert summary["visible_output_preview"] == "hidden answer"
        assert summary["thought_preview"] == "hidden child chain"
        assert summary["raw_output_preview"] == '{"raw": "hidden answer"}'
        assert summary["parsed_output"] == {
            "final_answer": "hidden answer",
            "reasoning_summary": "child summary",
        }
        assert summary["reasoning_retry"] == {
            "count": 1,
            "delay_ms": 250,
            "used": True,
        }

    @pytest.mark.asyncio
    async def test_summary_persists_structured_output_compliance(self):
        """Structured-output children should record retry/compliance outcome in summary."""
        pool = WorkerPool(default_model="schema-model", pool_size=1)
        ctx = _make_invocation_context()
        child = _make_mock_child_with_obs(
            "negative",
            structured_obs={
                "attempts": 2,
                "retry_count": 1,
                "events": [
                    {"attempt": 1, "outcome": "retry_requested", "args_keys": ["confidence", "sentiment"]},
                    {"attempt": 2, "outcome": "validated", "args_keys": ["confidence", "sentiment"]},
                ],
            },
            structured_result={"sentiment": "negative", "confidence": 0.82},
        )

        class SentimentResult:  # simple stand-in for schema name assertions
            __name__ = "SentimentResult"

        with patch("rlm_adk.agent.create_child_orchestrator", return_value=child):
            llm_query_async, _, flush_fn = create_dispatch_closures(
                pool, ctx, depth=0, max_depth=3,
            )
            await llm_query_async("schema prompt", output_schema=SentimentResult)

        summary = flush_fn()[child_obs_key(1, 0)]
        assert summary["structured_output"] == {
            "expected": True,
            "schema_name": "SentimentResult",
            "attempts": 2,
            "retry_count": 1,
            "outcome": "retry_recovered",
            "validated_result": {"sentiment": "negative", "confidence": 0.82},
            "events": [
                {"attempt": 1, "outcome": "retry_requested", "args_keys": ["confidence", "sentiment"]},
                {"attempt": 2, "outcome": "validated", "args_keys": ["confidence", "sentiment"]},
            ],
        }

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
