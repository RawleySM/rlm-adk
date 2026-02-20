"""BUG-003: Verify worker callbacks access agent via _invocation_context.agent.

These tests create a mock CallbackContext that faithfully mirrors the
production CallbackContext / ReadonlyContext hierarchy:

    callback_context._invocation_context.agent

The tests confirm that:
  - worker_before_model reads _pending_prompt from _invocation_context.agent
  - worker_after_model writes output_key from _invocation_context.agent
"""

from unittest.mock import MagicMock

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.callbacks.worker import worker_after_model, worker_before_model


def _make_invocation_context_mock(agent: MagicMock, state: dict | None = None):
    """Build a mock CallbackContext with _invocation_context.agent set correctly.

    This mirrors the real Google ADK hierarchy:
        ReadonlyContext.__init__ stores invocation_context as self._invocation_context
        CallbackContext extends ReadonlyContext
        Agent is accessed via self._invocation_context.agent
    """
    invocation_context = MagicMock()
    invocation_context.agent = agent

    ctx = MagicMock()
    ctx._invocation_context = invocation_context
    ctx.state = state if state is not None else {}
    return ctx


def _make_llm_response(text: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        ),
    )


class TestWorkerBeforeModelInvocationContext:
    """worker_before_model reads _pending_prompt via _invocation_context.agent."""

    def test_string_prompt_injected_via_invocation_context(self):
        agent = MagicMock()
        agent._pending_prompt = "What is 2+2?"
        ctx = _make_invocation_context_mock(agent)
        request = LlmRequest(model="test", contents=[])

        result = worker_before_model(ctx, request)

        assert result is None
        assert len(request.contents) == 1
        assert request.contents[0].role == "user"
        assert request.contents[0].parts[0].text == "What is 2+2?"

    def test_message_list_prompt_injected_via_invocation_context(self):
        agent = MagicMock()
        agent._pending_prompt = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        ctx = _make_invocation_context_mock(agent)
        request = LlmRequest(model="test", contents=[])

        worker_before_model(ctx, request)

        assert len(request.contents) == 2
        assert request.contents[0].role == "user"
        assert request.contents[1].role == "model"

    def test_no_pending_prompt_via_invocation_context(self):
        agent = MagicMock()
        agent._pending_prompt = None
        ctx = _make_invocation_context_mock(agent)
        request = LlmRequest(model="test", contents=[])

        result = worker_before_model(ctx, request)
        assert result is None
        # contents should remain empty
        assert request.contents == []


class TestWorkerAfterModelInvocationContext:
    """worker_after_model writes to output_key via _invocation_context.agent."""

    def test_writes_to_output_key_via_invocation_context(self):
        agent = MagicMock()
        agent.output_key = "worker_1_output"
        state = {}
        ctx = _make_invocation_context_mock(agent, state=state)
        response = _make_llm_response("4")

        result = worker_after_model(ctx, response)

        assert result is None
        assert state["worker_1_output"] == "4"

    def test_no_output_key_via_invocation_context(self):
        agent = MagicMock()
        agent.output_key = None
        state = {}
        ctx = _make_invocation_context_mock(agent, state=state)
        response = _make_llm_response("4")

        worker_after_model(ctx, response)
        # State should have no output entry (only token accounting keys at most)
        assert "worker_1_output" not in state
