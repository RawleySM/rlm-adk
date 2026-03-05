"""Tests for worker-object result carrier pattern (Fixes 1+2+6).

After worker_after_model runs, results must be written directly onto the
worker agent object (_result, _result_ready, _call_record) rather than
relying on state dirty-reads.

Also tests:
- worker_on_model_error callback produces graceful error result
- The list-append token accounting code is REMOVED from callbacks
"""

from unittest.mock import MagicMock

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.callbacks.worker import (
    worker_before_model,
    worker_after_model,
    worker_on_model_error,
)


def _make_callback_context(state: dict | None = None, agent: MagicMock | None = None):
    """Build a mock CallbackContext with .state dict and .agent."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    if agent is not None:
        ctx._invocation_context.agent = agent
    return ctx


def _make_agent(name: str = "worker_1", prompt: str = "test prompt"):
    """Build a mock agent with _pending_prompt and output_key."""
    agent = MagicMock()
    agent.name = name
    agent._pending_prompt = prompt
    agent.output_key = f"{name}_output"
    return agent


def _make_llm_request_with_content(text: str) -> LlmRequest:
    return LlmRequest(
        model="test",
        contents=[
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=text)],
            )
        ],
    )


def _make_llm_response_with_usage(
    text: str, prompt_tokens: int, output_tokens: int
) -> LlmResponse:
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt_tokens,
        candidates_token_count=output_tokens,
    )
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        ),
        usage_metadata=usage,
    )


class TestWorkerAfterModelSetsAgentAttributes:
    """worker_after_model must write _result, _result_ready, _result_usage on agent."""

    def test_sets_result_on_agent(self):
        agent = _make_agent(name="worker_1")
        ctx = _make_callback_context(state={}, agent=agent)
        response = _make_llm_response_with_usage("hello world", 100, 50)
        worker_after_model(ctx, response)
        assert agent._result == "hello world"

    def test_sets_result_ready_on_agent(self):
        agent = _make_agent(name="worker_1")
        ctx = _make_callback_context(state={}, agent=agent)
        response = _make_llm_response_with_usage("hello", 100, 50)
        worker_after_model(ctx, response)
        assert agent._result_ready is True

    def test_sets_call_record_on_agent(self):
        agent = _make_agent(name="worker_1")
        ctx = _make_callback_context(state={}, agent=agent)
        response = _make_llm_response_with_usage("hello", 100, 50)
        worker_after_model(ctx, response)
        assert agent._call_record["input_tokens"] == 100
        assert agent._call_record["output_tokens"] == 50
        assert agent._call_record["response"] == "hello"
        assert agent._call_record["error"] is False

    def test_still_writes_to_output_key_in_state(self):
        """The callback_context.state[output_key] write must be preserved for ADK persistence."""
        agent = _make_agent(name="worker_1")
        state = {}
        ctx = _make_callback_context(state=state, agent=agent)
        response = _make_llm_response_with_usage("result text", 100, 50)
        worker_after_model(ctx, response)
        assert state["worker_1_output"] == "result text"


class TestWorkerCallbacksNoListAppendAccounting:
    """List-append token accounting must be REMOVED from callbacks.

    The callbacks should NOT write worker_prompt_chars, worker_content_count,
    worker_input_tokens, or worker_output_tokens to state. That accounting
    now happens in the dispatch closure by reading from worker objects.
    (Constants removed from state.py in Phase 1 key dedup.)
    """

    def test_before_model_does_not_write_prompt_chars_to_state(self):
        state = {}
        agent = _make_agent(name="worker_1", prompt="test")
        ctx = _make_callback_context(state=state, agent=agent)
        request = _make_llm_request_with_content("test")
        worker_before_model(ctx, request)
        assert "worker_prompt_chars" not in state

    def test_before_model_does_not_write_content_count_to_state(self):
        state = {}
        agent = _make_agent(name="worker_1", prompt="test")
        ctx = _make_callback_context(state=state, agent=agent)
        request = _make_llm_request_with_content("test")
        worker_before_model(ctx, request)
        assert "worker_content_count" not in state

    def test_after_model_does_not_write_input_tokens_to_state(self):
        state = {}
        agent = _make_agent(name="worker_1")
        ctx = _make_callback_context(state=state, agent=agent)
        response = _make_llm_response_with_usage("hello", 100, 50)
        worker_after_model(ctx, response)
        assert "worker_input_tokens" not in state

    def test_after_model_does_not_write_output_tokens_to_state(self):
        state = {}
        agent = _make_agent(name="worker_1")
        ctx = _make_callback_context(state=state, agent=agent)
        response = _make_llm_response_with_usage("hello", 100, 50)
        worker_after_model(ctx, response)
        assert "worker_output_tokens" not in state


class TestWorkerOnModelErrorCallback:
    """worker_on_model_error must handle errors gracefully."""

    def test_callback_exists(self):
        assert callable(worker_on_model_error)

    def test_sets_error_result_on_agent(self):
        agent = _make_agent(name="worker_1")
        ctx = _make_callback_context(state={}, agent=agent)
        error = RuntimeError("LLM service unavailable")
        request = _make_llm_request_with_content("test")
        worker_on_model_error(ctx, request, error)
        assert agent._result_ready is True
        assert agent._result_error is True
        assert "RuntimeError" in agent._result
        assert "LLM service unavailable" in agent._result
        assert agent._call_record["input_tokens"] == 0
        assert agent._call_record["output_tokens"] == 0
        assert agent._call_record["error"] is True

    def test_returns_llm_response_with_error_text(self):
        agent = _make_agent(name="worker_1")
        ctx = _make_callback_context(state={}, agent=agent)
        error = ValueError("bad input")
        request = _make_llm_request_with_content("test")
        result = worker_on_model_error(ctx, request, error)
        assert isinstance(result, LlmResponse)
        assert result.content is not None
        parts = result.content.parts
        assert parts is not None
        assert parts[0].text is not None
        assert "ValueError" in parts[0].text
