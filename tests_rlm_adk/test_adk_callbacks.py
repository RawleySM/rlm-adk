"""AR-HIGH-006: Callback completeness.

Reasoning, worker, and default-answer agents shall each have defined
before/after callback behavior for prompt injection and output extraction.
"""

from unittest.mock import MagicMock

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.callbacks.default_answer import (
    DEFAULT_ANSWER_OUTPUT_KEY,
    default_after_model,
    default_before_model,
)
from rlm_adk.callbacks.reasoning import (
    reasoning_after_model,
    reasoning_before_model,
)
from rlm_adk.callbacks.worker import worker_after_model, worker_before_model
from rlm_adk.state import (
    TEMP_LAST_REASONING_RESPONSE,
    TEMP_MESSAGE_HISTORY,
    TEMP_REASONING_CALL_START,
    TEMP_USED_DEFAULT_ANSWER,
)


def _make_callback_context(state: dict | None = None, agent: MagicMock | None = None):
    """Build a mock CallbackContext with .state dict and .agent."""
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    if agent is not None:
        ctx.agent = agent
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
            TEMP_MESSAGE_HISTORY: [
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

    def test_system_messages_become_system_instruction(self):
        state = {
            TEMP_MESSAGE_HISTORY: [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ],
        }
        ctx = _make_callback_context(state)
        request = LlmRequest(model="test", contents=[])

        reasoning_before_model(ctx, request)

        assert len(request.contents) == 1  # only user, system is separate
        assert request.config.system_instruction == "You are helpful."

    def test_sets_reasoning_call_start(self):
        state = {TEMP_MESSAGE_HISTORY: []}
        ctx = _make_callback_context(state)
        request = LlmRequest(model="test", contents=[])

        reasoning_before_model(ctx, request)

        assert TEMP_REASONING_CALL_START in ctx.state

    def test_empty_history(self):
        state = {TEMP_MESSAGE_HISTORY: []}
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
        assert state[TEMP_LAST_REASONING_RESPONSE] == "The answer is 42."

    def test_empty_response(self):
        state = {}
        ctx = _make_callback_context(state)
        response = LlmResponse(content=None)

        reasoning_after_model(ctx, response)
        assert state[TEMP_LAST_REASONING_RESPONSE] == ""

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
        assert state[TEMP_LAST_REASONING_RESPONSE] == "visible"


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


# ── Default Answer Callbacks ─────────────────────────────────────────────


class TestDefaultBeforeModel:
    """Default answer before_model_callback injects full history + final instruction."""

    def test_injects_history_and_final_instruction(self):
        state = {
            TEMP_MESSAGE_HISTORY: [
                {"role": "system", "content": "System msg"},
                {"role": "user", "content": "Question"},
                {"role": "assistant", "content": "Partial answer"},
            ],
        }
        ctx = _make_callback_context(state)
        request = LlmRequest(model="test", contents=[])

        result = default_before_model(ctx, request)

        assert result is None
        # user + assistant + final instruction = 3 contents
        assert len(request.contents) == 3
        # Last content should be the "provide final answer" instruction
        last = request.contents[-1]
        assert last.role == "user"
        assert "final answer" in last.parts[0].text.lower()

    def test_system_instruction_set(self):
        state = {
            TEMP_MESSAGE_HISTORY: [
                {"role": "system", "content": "Be helpful"},
            ],
        }
        ctx = _make_callback_context(state)
        request = LlmRequest(model="test", contents=[])

        default_before_model(ctx, request)
        assert request.config.system_instruction == "Be helpful"


class TestDefaultAfterModel:
    """Default answer after_model_callback records answer and marks flag."""

    def test_records_answer(self):
        state = {}
        ctx = _make_callback_context(state)
        response = _make_llm_response("Best guess: 42")

        result = default_after_model(ctx, response)

        assert result is None
        assert state[DEFAULT_ANSWER_OUTPUT_KEY] == "Best guess: 42"
        assert state[TEMP_USED_DEFAULT_ANSWER] is True

    def test_empty_response(self):
        state = {}
        ctx = _make_callback_context(state)
        response = LlmResponse(content=None)

        default_after_model(ctx, response)
        assert state[DEFAULT_ANSWER_OUTPUT_KEY] == ""
