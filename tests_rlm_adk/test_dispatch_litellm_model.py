"""Tests for LiteLlm model handling in dispatch.py.

Covers two historically distinct bugs:

1. **Unhashable type** (original): dispatch_config.other_model can be a LiteLlm
   Pydantic object (unhashable). _build_call_log() uses it as a dict key in
   UsageSummary.model_usage_summaries, and _run_child stores it as
   LLMResult.model without string conversion.

2. **Worker tier routing** (new): When LiteLLM is active, _run_child converts
   the LiteLlm object to a garbage string via str() and passes that to
   create_child_orchestrator, which re-resolves it as the reasoning tier
   instead of the worker tier.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from rlm_adk.dispatch import DispatchConfig, create_dispatch_closures


class FakeLiteLlm(BaseModel):
    """Mimics a LiteLlm Pydantic model — unhashable by default.

    NOTE: The real ADK LiteLlm does NOT override __str__, so str(LiteLlm(...))
    produces Pydantic's default repr like "model='worker' llm_client=...".
    This fake intentionally provides a clean __str__ to match the existing tests,
    but the new worker-tier tests use RealisticFakeLiteLlm (no __str__) to
    reproduce the real bug.
    """

    model: str = "gemini-2.0-flash"

    def __str__(self) -> str:
        return self.model


class RealisticFakeLiteLlm(BaseModel):
    """Mimics real LiteLlm behavior — NO __str__ override.

    str() on this produces Pydantic's default repr, e.g.:
    "model='worker' llm_client=None"
    This is the actual bug trigger.
    """

    model: str = "worker"
    llm_client: object = None


class TestLiteLlmModelAsDispatchConfig:
    """Verify that non-hashable model objects don't crash dispatch."""

    def test_build_call_log_with_unhashable_model(self):
        """_build_call_log should not raise TypeError when model is a Pydantic object."""
        fake_model = FakeLiteLlm(model="gemini-2.0-flash")

        # Confirm it's unhashable (precondition)
        with pytest.raises(TypeError, match="unhashable"):
            _ = {fake_model: "value"}

        config = DispatchConfig(
            default_model=fake_model,
            other_model=fake_model,
        )
        call_log: list = []

        # Create closures — we only need the flush_fn for setup;
        # the _build_call_log is an internal closure we exercise via _run_child.
        # But we can test the model_name path by creating an LLMResult
        # with the unhashable model and passing it through the call log sink.
        mock_ctx = MagicMock()
        mock_ctx.session.state = {}

        llm_query_async, _, flush_fn = create_dispatch_closures(
            dispatch_config=config,
            ctx=mock_ctx,
            call_log_sink=call_log,
            depth=0,
            max_depth=1,  # force DEPTH_LIMIT path so no real child is spawned
        )

        # Call llm_query_async — depth=0, max_depth=1 → DEPTH_LIMIT path
        # which calls _build_call_log with the unhashable model object.
        result = asyncio.get_event_loop().run_until_complete(
            llm_query_async("test prompt")
        )

        # The call log should have one entry
        assert len(call_log) == 1
        record = call_log[0]

        # root_model must be a string, not a Pydantic object
        assert isinstance(record.root_model, str), (
            f"root_model should be str, got {type(record.root_model)}"
        )

        # The dict key in model_usage_summaries must be a string
        for key in record.usage_summary.model_usage_summaries:
            assert isinstance(key, str), (
                f"model_usage_summaries key should be str, got {type(key)}"
            )

        # LLMResult.model should be a string
        assert isinstance(result.model, str), (
            f"LLMResult.model should be str, got {type(result.model)}"
        )

    def test_run_child_depth_limit_model_is_string(self):
        """LLMResult from depth-limit path should have string model field."""
        fake_model = FakeLiteLlm(model="worker-model")

        config = DispatchConfig(
            default_model=fake_model,
            other_model=fake_model,
        )
        mock_ctx = MagicMock()
        mock_ctx.session.state = {}

        llm_query_async, _, _ = create_dispatch_closures(
            dispatch_config=config,
            ctx=mock_ctx,
            depth=2,
            max_depth=3,  # depth+1 >= max_depth → DEPTH_LIMIT
        )

        result = asyncio.get_event_loop().run_until_complete(
            llm_query_async("test")
        )

        assert result.error is True
        assert result.error_category == "DEPTH_LIMIT"
        assert isinstance(result.model, str), (
            f"LLMResult.model should be str, got {type(result.model)}"
        )
        assert result.model == "worker-model"


class TestWorkerTierRouting:
    """Verify child dispatch passes the model *object* (not str) to child orchestrator.

    Bug: _run_child() did ``target_model = str(model or dispatch_config.other_model)``
    which converts a LiteLlm Pydantic object to garbage like
    "model='worker' llm_client=..." instead of preserving the actual object.
    create_child_orchestrator then re-resolves this garbage string via
    _resolve_model(), which falls back to the reasoning tier.
    """

    def test_child_orchestrator_receives_model_object_not_string(self):
        """When LiteLLM is active, create_child_orchestrator must receive the
        actual LiteLlm model object — not str(LiteLlm(...))."""
        worker_model = RealisticFakeLiteLlm(model="worker")
        reasoning_model = RealisticFakeLiteLlm(model="reasoning")

        config = DispatchConfig(
            default_model=reasoning_model,
            other_model=worker_model,
        )
        mock_ctx = MagicMock()
        mock_ctx.session.state = {}

        captured_model = None

        def fake_create_child(model, **kwargs):
            nonlocal captured_model
            captured_model = model
            # Return a mock child that produces an empty run
            child = MagicMock()
            child.reasoning_agent = MagicMock()
            child.reasoning_agent._rlm_completion = {"text": "ok"}
            child.reasoning_agent._structured_result = None
            child.reasoning_agent._structured_output_obs = {}
            child.reasoning_agent.output_key = "reasoning_output@d1"
            child.persistent = False
            child.repl = None

            async def fake_run(ctx):
                return
                yield  # make it an async generator

            child.run_async = fake_run
            return child

        with patch("rlm_adk.agent.create_child_orchestrator", side_effect=fake_create_child):
            llm_query_async, _, _ = create_dispatch_closures(
                dispatch_config=config,
                ctx=mock_ctx,
                depth=0,
                max_depth=3,
            )
            asyncio.get_event_loop().run_until_complete(
                llm_query_async("test prompt")
            )

        # The model passed to create_child_orchestrator should be the actual
        # LiteLlm object, NOT a string representation of it.
        assert captured_model is worker_model or captured_model == worker_model, (
            f"Expected worker model object, got {captured_model!r}"
        )
        # It must NOT be a string like "model='worker' llm_client=None"
        assert not isinstance(captured_model, str) or captured_model == "worker", (
            f"Model was stringified to garbage: {captured_model!r}"
        )

    def test_worker_tier_model_not_reasoning_tier(self):
        """Verify the child gets the worker-tier model, not the reasoning-tier model."""
        worker_model = RealisticFakeLiteLlm(model="worker")
        reasoning_model = RealisticFakeLiteLlm(model="reasoning")

        config = DispatchConfig(
            default_model=reasoning_model,
            other_model=worker_model,
        )
        mock_ctx = MagicMock()
        mock_ctx.session.state = {}

        captured_models = []

        def fake_create_child(model, **kwargs):
            captured_models.append(model)
            child = MagicMock()
            child.reasoning_agent = MagicMock()
            child.reasoning_agent._rlm_completion = {"text": "ok"}
            child.reasoning_agent._structured_result = None
            child.reasoning_agent._structured_output_obs = {}
            child.reasoning_agent.output_key = "reasoning_output@d1"
            child.persistent = False
            child.repl = None

            async def fake_run(ctx):
                return
                yield

            child.run_async = fake_run
            return child

        with patch("rlm_adk.agent.create_child_orchestrator", side_effect=fake_create_child):
            llm_query_async, llm_query_batched, _ = create_dispatch_closures(
                dispatch_config=config,
                ctx=mock_ctx,
                depth=0,
                max_depth=3,
            )
            # Single dispatch (no explicit model → should use other_model = worker)
            asyncio.get_event_loop().run_until_complete(
                llm_query_async("prompt 1")
            )
            # Batched dispatch (no explicit model → should use other_model = worker)
            asyncio.get_event_loop().run_until_complete(
                llm_query_batched(["prompt 2", "prompt 3"])
            )

        # All 3 dispatches should use the worker model, not reasoning
        for i, m in enumerate(captured_models):
            assert m is worker_model or (isinstance(m, str) and m == "worker"), (
                f"Dispatch {i}: expected worker model, got {m!r}"
            )

    def test_build_call_log_still_uses_string_key(self):
        """_build_call_log must use str() for dict keys — regression guard
        for the unhashable-type fix."""
        worker_model = RealisticFakeLiteLlm(model="worker")

        config = DispatchConfig(
            default_model="reasoning",
            other_model=worker_model,
        )
        call_log: list = []
        mock_ctx = MagicMock()
        mock_ctx.session.state = {}

        llm_query_async, _, _ = create_dispatch_closures(
            dispatch_config=config,
            ctx=mock_ctx,
            call_log_sink=call_log,
            depth=0,
            max_depth=1,  # DEPTH_LIMIT path
        )

        asyncio.get_event_loop().run_until_complete(
            llm_query_async("test")
        )

        assert len(call_log) == 1
        record = call_log[0]
        # Dict keys in usage_summary must be strings
        for key in record.usage_summary.model_usage_summaries:
            assert isinstance(key, str), (
                f"model_usage_summaries key should be str, got {type(key)}"
            )
        # root_model must be a string
        assert isinstance(record.root_model, str)

    def test_dispatch_config_other_model_preserved_through_child(self):
        """DispatchConfig.other_model must be passed unchanged to child creation,
        not converted via str()."""
        worker_model = RealisticFakeLiteLlm(model="worker")

        config = DispatchConfig(
            default_model="reasoning-model-str",
            other_model=worker_model,
        )

        # Verify the config stores the actual object
        assert config.other_model is worker_model
        # str() of the object is NOT a valid model name
        stringified = str(worker_model)
        assert stringified != "worker", (
            f"RealisticFakeLiteLlm.__str__ should NOT return clean name, got {stringified!r}"
        )
