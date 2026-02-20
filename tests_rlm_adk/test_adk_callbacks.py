"""AR-HIGH-006: Callback completeness.

Reasoning and worker agents shall each have defined
before/after callback behavior for prompt injection and output extraction.
"""

from unittest.mock import MagicMock

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.callbacks.reasoning import (
    reasoning_after_model,
    reasoning_before_model,
)
from rlm_adk.callbacks.worker import worker_after_model, worker_before_model
from rlm_adk.state import (
    LAST_REASONING_RESPONSE,
    MESSAGE_HISTORY,
    REASONING_CALL_START,
)


def _make_callback_context(state: dict | None = None, agent: MagicMock | None = None):
    """Build a mock CallbackContext with .state dict and ._invocation_context.agent.

    Mirrors the production CallbackContext hierarchy where agent is accessed
    via callback_context._invocation_context.agent (see ReadonlyContext).
    """
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    if agent is not None:
        invocation_context = MagicMock()
        invocation_context.agent = agent
        ctx._invocation_context = invocation_context
    return ctx


def _make_llm_response(text: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        ),
    )


# ── Reasoning Callbacks ──────────────────────────────────────────────────


class TestReasoningBeforeModel:
    """Reasoning before_model_callback injects message_history into LlmRequest."""

    def test_injects_user_messages(self):
        state = {
            MESSAGE_HISTORY: [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
        }
        ctx = _make_callback_context(state)
        request = LlmRequest(model="test", contents=[])

        result = reasoning_before_model(ctx, request)

        assert result is None  # amend pattern: returns None to proceed
        assert len(request.contents) == 2
        assert request.contents[0].role == "user"
        assert request.contents[1].role == "model"  # assistant -> model

    def test_sets_reasoning_call_start(self):
        state = {MESSAGE_HISTORY: []}
        ctx = _make_callback_context(state)
        request = LlmRequest(model="test", contents=[])

        reasoning_before_model(ctx, request)

        assert REASONING_CALL_START in ctx.state

    def test_empty_history(self):
        state = {MESSAGE_HISTORY: []}
        ctx = _make_callback_context(state)
        request = LlmRequest(model="test", contents=[])

        result = reasoning_before_model(ctx, request)
        assert result is None
        assert request.contents == []


class TestReasoningAfterModel:
    """Reasoning after_model_callback extracts text to state."""

    def test_extracts_text_to_state(self):
        state = {}
        ctx = _make_callback_context(state)
        response = _make_llm_response("The answer is 42.")

        result = reasoning_after_model(ctx, response)

        assert result is None  # observe only
        assert state[LAST_REASONING_RESPONSE] == "The answer is 42."

    def test_empty_response(self):
        state = {}
        ctx = _make_callback_context(state)
        response = LlmResponse(content=None)

        reasoning_after_model(ctx, response)
        assert state[LAST_REASONING_RESPONSE] == ""

    def test_filters_thought_parts(self):
        """Non-thought parts only should be extracted."""
        state = {}
        ctx = _make_callback_context(state)
        response = LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part.from_text(text="visible"),
                    types.Part(text="thinking", thought=True),
                ],
            )
        )

        reasoning_after_model(ctx, response)
        assert state[LAST_REASONING_RESPONSE] == "visible"


# ── Worker Callbacks ─────────────────────────────────────────────────────


class TestWorkerBeforeModel:
    """Worker before_model_callback injects _pending_prompt into LlmRequest."""

    def test_injects_string_prompt(self):
        agent = MagicMock()
        agent._pending_prompt = "What is 2+2?"
        ctx = _make_callback_context(agent=agent)
        request = LlmRequest(model="test", contents=[])

        result = worker_before_model(ctx, request)

        assert result is None
        assert len(request.contents) == 1
        assert request.contents[0].role == "user"

    def test_injects_message_list_prompt(self):
        agent = MagicMock()
        agent._pending_prompt = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        ctx = _make_callback_context(agent=agent)
        request = LlmRequest(model="test", contents=[])

        worker_before_model(ctx, request)

        assert len(request.contents) == 2
        assert request.contents[0].role == "user"
        assert request.contents[1].role == "model"

    def test_no_pending_prompt(self):
        agent = MagicMock()
        agent._pending_prompt = None
        ctx = _make_callback_context(agent=agent)
        request = LlmRequest(model="test", contents=[])

        result = worker_before_model(ctx, request)
        assert result is None


class TestWorkerAfterModel:
    """Worker after_model_callback writes response to output_key in state."""

    def test_writes_to_output_key(self):
        agent = MagicMock()
        agent.output_key = "worker_1_output"
        state = {}
        ctx = _make_callback_context(state=state, agent=agent)
        response = _make_llm_response("4")

        result = worker_after_model(ctx, response)

        assert result is None
        assert state["worker_1_output"] == "4"

    def test_no_output_key(self):
        agent = MagicMock()
        agent.output_key = None
        state = {}
        ctx = _make_callback_context(state=state, agent=agent)
        response = _make_llm_response("4")

        worker_after_model(ctx, response)
        # Should not crash, state unchanged
        assert len(state) == 0
