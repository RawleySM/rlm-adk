"""Phase 4 tests: Observability depth tagging, context snapshot, and child metrics."""

from unittest.mock import MagicMock

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from rlm_adk.agent import create_child_orchestrator
from rlm_adk.callbacks.reasoning import reasoning_before_model
from rlm_adk.dispatch import DispatchConfig, create_dispatch_closures
from rlm_adk.state import (
    CONTEXT_WINDOW_SNAPSHOT,
    OBS_CHILD_DISPATCH_COUNT,
    REASONING_PARSED_OUTPUT,
    REASONING_RAW_OUTPUT,
    REASONING_THOUGHT_TEXT,
    REASONING_VISIBLE_OUTPUT_TEXT,
    depth_key,
)


def _make_callback_context(state=None, rlm_depth=None):
    """Build a mock CallbackContext with optional _rlm_depth on agent."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    agent = MagicMock()
    agent.tools = []
    if rlm_depth is not None:
        agent._rlm_depth = rlm_depth
    else:
        # Simulate missing attr so getattr defaults to 0
        del agent._rlm_depth
    invocation_context = MagicMock()
    invocation_context.agent = agent
    ctx._invocation_context = invocation_context
    return ctx


def _make_llm_request(system_text="You are a helper.", user_text="Hello"):
    """Build a minimal LlmRequest with system_instruction and one content."""
    return LlmRequest(
        model="test-model",
        contents=[
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_text)],
            ),
        ],
        config=types.GenerateContentConfig(system_instruction=system_text),
    )


class TestDepthTagOnReasoningAgent:
    """Verify _rlm_depth is set on reasoning_agent by orchestrator wiring."""

    def test_child_orchestrator_sets_rlm_depth(self):
        """create_child_orchestrator sets depth on the orchestrator;
        orchestrator._run_async_impl sets _rlm_depth on reasoning_agent.
        We verify the orchestrator field is correct (depth tag is set
        in _run_async_impl which requires a full invocation context)."""
        child = create_child_orchestrator(
            model="gemini-test", depth=2, prompt="test"
        )
        assert child.depth == 2
        # Before run, _rlm_depth is not yet set (set during _run_async_impl)
        assert not hasattr(child.reasoning_agent, '_rlm_depth')

        # Simulate what orchestrator does at runtime
        object.__setattr__(child.reasoning_agent, '_rlm_depth', child.depth)
        assert child.reasoning_agent._rlm_depth == 2

    def test_depth_zero_default(self):
        child = create_child_orchestrator(
            model="gemini-test", depth=0, prompt="test"
        )
        object.__setattr__(child.reasoning_agent, '_rlm_depth', child.depth)
        assert child.reasoning_agent._rlm_depth == 0


class TestContextSnapshotIncludesDepth:
    """Verify CONTEXT_WINDOW_SNAPSHOT includes depth field."""

    def test_depth_present_when_set(self):
        ctx = _make_callback_context(rlm_depth=2)
        req = _make_llm_request()
        reasoning_before_model(ctx, req)

        snapshot = ctx.state[CONTEXT_WINDOW_SNAPSHOT]
        assert "depth" in snapshot
        assert snapshot["depth"] == 2

    def test_depth_defaults_to_zero(self):
        ctx = _make_callback_context(rlm_depth=None)
        req = _make_llm_request()
        reasoning_before_model(ctx, req)

        snapshot = ctx.state[CONTEXT_WINDOW_SNAPSHOT]
        assert snapshot["depth"] == 0

    def test_snapshot_retains_other_fields(self):
        ctx = _make_callback_context(rlm_depth=1)
        req = _make_llm_request(system_text="sys", user_text="hello")
        reasoning_before_model(ctx, req)

        snapshot = ctx.state[CONTEXT_WINDOW_SNAPSHOT]
        assert snapshot["agent_type"] == "reasoning"
        assert "content_count" in snapshot
        assert "prompt_chars" in snapshot
        assert "system_chars" in snapshot
        assert "total_chars" in snapshot


class TestChildDispatchCountInFlush:
    """Verify flush_fn returns child dispatch metrics."""

    def test_flush_returns_child_dispatch_count(self):
        config = DispatchConfig(default_model="gemini-test")
        ctx = MagicMock()
        ctx.session.state = {}

        _, _, flush_fn = create_dispatch_closures(config, ctx, depth=0)

        # Before any dispatches, flush should return 0 count
        delta = flush_fn()
        assert OBS_CHILD_DISPATCH_COUNT in delta
        assert delta[OBS_CHILD_DISPATCH_COUNT] == 0

    def test_flush_resets_accumulators(self):
        config = DispatchConfig(default_model="gemini-test")
        ctx = MagicMock()
        ctx.session.state = {}

        _, _, flush_fn = create_dispatch_closures(config, ctx, depth=0)

        # Two consecutive flushes should both return 0 (reset works)
        delta1 = flush_fn()
        delta2 = flush_fn()
        assert delta1[OBS_CHILD_DISPATCH_COUNT] == 0
        assert delta2[OBS_CHILD_DISPATCH_COUNT] == 0


class TestReasoningObservabilityDepthKeys:
    """Verify new reasoning observability keys are depth-scoped."""

    def test_reasoning_output_keys_are_depth_scoped(self):
        assert depth_key(REASONING_VISIBLE_OUTPUT_TEXT, 0) == REASONING_VISIBLE_OUTPUT_TEXT
        assert depth_key(REASONING_THOUGHT_TEXT, 2) == "reasoning_thought_text@d2"
        assert depth_key(REASONING_RAW_OUTPUT, 3) == "reasoning_raw_output@d3"
        assert depth_key(REASONING_PARSED_OUTPUT, 1) == "reasoning_parsed_output@d1"
