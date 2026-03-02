"""AR-HIGH-006: Callback completeness.

Reasoning and worker agents shall each have defined
before/after callback behavior for prompt injection and output extraction.

Also covers FMEA items:
- FM-18 (item 7): _classify_error with json.JSONDecodeError returns 'PARSE_ERROR'
- FM-18 (item 20): worker_on_model_error with JSONDecodeError sets correct _call_record
- FM-20 (item 22): worker_after_model with unexpected Part types (no .text attr)
"""

import json
from unittest.mock import MagicMock

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.callbacks.reasoning import (
    reasoning_after_model,
    reasoning_before_model,
)
from rlm_adk.callbacks.worker import (
    _classify_error,
    worker_after_model,
    worker_before_model,
    worker_on_model_error,
)
from rlm_adk.state import (
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
    """Reasoning before_model_callback merges dynamic instruction into system_instruction.

    ADK manages contents via include_contents='default'. The callback
    only sets system_instruction and records token accounting.
    """

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
    """Reasoning after_model_callback no longer writes LAST_REASONING_RESPONSE.

    Phase 5B: The collapsed orchestrator reads the final answer from the
    output_key ("reasoning_output") instead of LAST_REASONING_RESPONSE.
    """

    def test_does_not_write_last_reasoning_response(self):
        state = {}
        ctx = _make_callback_context(state)
        response = _make_llm_response("The answer is 42.")

        result = reasoning_after_model(ctx, response)

        assert result is None  # observe only
        assert "last_reasoning_response" not in state

    def test_empty_response_does_not_write_state(self):
        state = {}
        ctx = _make_callback_context(state)
        response = LlmResponse(content=None)

        reasoning_after_model(ctx, response)
        assert "last_reasoning_response" not in state

    def test_thought_parts_do_not_write_state(self):
        """After model callback should not write response text to state."""
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
        assert "last_reasoning_response" not in state


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


# ── FM-18 (Item 7): _classify_error with json.JSONDecodeError ──────────


class TestClassifyErrorJsonDecode:
    """FM-18: _classify_error must return 'PARSE_ERROR' for json.JSONDecodeError."""

    def test_json_decode_error_returns_parse_error(self):
        err = json.JSONDecodeError("Expecting value", "doc", 0)
        assert _classify_error(err) == "PARSE_ERROR"

    def test_json_decode_error_with_complex_message(self):
        err = json.JSONDecodeError("Unterminated string starting at", '{"key": "val', 8)
        assert _classify_error(err) == "PARSE_ERROR"

    def test_value_error_with_json_in_message(self):
        err = ValueError("Invalid JSON response from server")
        assert _classify_error(err) == "PARSE_ERROR"

    def test_value_error_without_json_not_parse_error(self):
        err = ValueError("some other problem")
        result = _classify_error(err)
        assert result != "PARSE_ERROR"

    def test_runtime_error_returns_unknown(self):
        err = RuntimeError("unexpected failure")
        assert _classify_error(err) == "UNKNOWN"

    def test_timeout_error_returns_timeout(self):
        import asyncio
        err = asyncio.TimeoutError()
        assert _classify_error(err) == "TIMEOUT"


# ── FM-18 (Item 20): worker_on_model_error with JSONDecodeError ────────


class TestWorkerOnModelErrorJsonDecode:
    """FM-18: worker_on_model_error with JSONDecodeError sets _call_record fields."""

    def test_json_decode_error_call_record(self):
        agent = MagicMock()
        agent.name = "worker_test"
        agent._pending_prompt = "parse this json"
        ctx = _make_callback_context(state={}, agent=agent)
        error = json.JSONDecodeError("Expecting value", "doc", 0)
        request = LlmRequest(model="test", contents=[])

        result = worker_on_model_error(ctx, request, error)

        # Verify _call_record fields
        assert agent._call_record["error"] is True
        assert agent._call_record["error_category"] == "PARSE_ERROR"
        assert agent._call_record["http_status"] is None
        assert agent._call_record["input_tokens"] == 0
        assert agent._call_record["output_tokens"] == 0

        # Verify agent result carrier
        assert agent._result_ready is True
        assert agent._result_error is True
        assert "JSONDecodeError" in agent._result

        # Verify returns valid LlmResponse
        assert isinstance(result, LlmResponse)

    def test_json_decode_error_http_status_is_none(self):
        """json.JSONDecodeError has no .code attribute, so http_status must be None."""
        agent = MagicMock()
        agent.name = "worker_test"
        agent._pending_prompt = "test"
        ctx = _make_callback_context(state={}, agent=agent)
        error = json.JSONDecodeError("msg", "doc", 0)
        request = LlmRequest(model="test", contents=[])

        worker_on_model_error(ctx, request, error)
        assert agent._call_record["http_status"] is None


# ── FM-20 (Item 22): worker_after_model with unexpected Part types ─────


class TestWorkerAfterModelUnexpectedParts:
    """FM-20: worker_after_model handles unexpected Part types (no .text attr)."""

    def test_response_with_no_text_parts(self):
        """Parts that have no .text attr should not crash worker_after_model.

        The callback filters `part.text for part in parts if part.text`,
        so parts without .text are simply skipped.
        """
        agent = MagicMock()
        agent.name = "worker_test"
        agent.output_key = "worker_test_output"
        agent._pending_prompt = "test"
        state = {}
        ctx = _make_callback_context(state=state, agent=agent)

        # Create response with a Part that has text=None
        response = LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=None)],
            ),
        )

        result = worker_after_model(ctx, response)
        assert result is None
        assert agent._result == ""
        assert agent._result_ready is True

    def test_response_with_mixed_parts_text_and_none(self):
        """Mix of text and non-text parts: only text parts contribute to result."""
        agent = MagicMock()
        agent.name = "worker_test"
        agent.output_key = "worker_test_output"
        agent._pending_prompt = "test"
        state = {}
        ctx = _make_callback_context(state=state, agent=agent)

        response = LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(text=None),
                    types.Part.from_text(text="valid text"),
                    types.Part(text=None),
                ],
            ),
        )

        worker_after_model(ctx, response)
        assert agent._result == "valid text"
        assert agent._result_ready is True
        assert agent._call_record["error"] is False

    def test_response_with_empty_parts_list(self):
        """Empty parts list should produce empty string result."""
        agent = MagicMock()
        agent.name = "worker_test"
        agent.output_key = "worker_test_output"
        agent._pending_prompt = "test"
        state = {}
        ctx = _make_callback_context(state=state, agent=agent)

        response = LlmResponse(
            content=types.Content(
                role="model",
                parts=[],
            ),
        )

        worker_after_model(ctx, response)
        assert agent._result == ""
        assert agent._result_ready is True

    def test_response_with_thought_only_parts(self):
        """Thought-only parts are excluded from result text."""
        agent = MagicMock()
        agent.name = "worker_test"
        agent.output_key = "worker_test_output"
        agent._pending_prompt = "test"
        state = {}
        ctx = _make_callback_context(state=state, agent=agent)

        response = LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text="thinking step", thought=True)],
            ),
        )

        worker_after_model(ctx, response)
        assert agent._result == ""
        assert agent._result_ready is True
