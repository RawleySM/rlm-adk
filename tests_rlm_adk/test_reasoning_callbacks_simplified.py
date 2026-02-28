"""Phase 3 Part C: Simplified reasoning callbacks tests.

Tests that the reasoning callbacks have been simplified for tool-calling mode:
1. reasoning_before_model does NOT write to llm_request.contents
2. reasoning_before_model DOES write system_instruction
3. reasoning_after_model DOES write token accounting keys
4. reasoning_after_model STILL writes LAST_REASONING_RESPONSE (backward compat
   with legacy orchestrator loop -- removal deferred to Phase 4)

RED: These tests will fail until callbacks/reasoning.py is modified.
"""

from unittest.mock import MagicMock

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from rlm_adk.callbacks.reasoning import (
    reasoning_after_model,
    reasoning_before_model,
)
from rlm_adk.state import (
    LAST_REASONING_RESPONSE,
    MESSAGE_HISTORY,
    REASONING_CALL_START,
    REASONING_INPUT_TOKENS,
    REASONING_OUTPUT_TOKENS,
)


def _make_callback_context(state: dict | None = None, *, tool_calling: bool = False):
    """Build a mock CallbackContext with .state dict.

    Args:
        state: Initial state dict.
        tool_calling: If True, simulate tool-calling mode by setting
            agent.tools to a non-empty list.  If False (default),
            simulate legacy mode (no tools).
    """
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    # Set up _invocation_context.agent.tools for mode detection
    agent = MagicMock()
    agent.tools = [MagicMock()] if tool_calling else []
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


def _make_usage_metadata(prompt_tokens: int = 100, candidates_tokens: int = 50):
    """Build a mock usage_metadata object."""
    meta = MagicMock()
    meta.prompt_token_count = prompt_tokens
    meta.candidates_token_count = candidates_tokens
    return meta


class TestSimplifiedBeforeModel:
    """reasoning_before_model in tool-calling mode should NOT inject contents."""

    def test_does_not_write_contents_in_tool_calling_mode(self):
        """In tool-calling mode, ADK manages history via include_contents='default'.
        The callback should NOT overwrite llm_request.contents with message_history."""
        state = {
            MESSAGE_HISTORY: [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
        }
        ctx = _make_callback_context(state, tool_calling=True)

        # Simulate ADK having pre-populated contents (tool-calling mode)
        existing_contents = [
            types.Content(role="user", parts=[types.Part.from_text(text="ADK managed")])
        ]
        request = LlmRequest(model="test", contents=existing_contents)

        reasoning_before_model(ctx, request)

        # Contents should NOT be replaced with message_history entries.
        # The callback must leave ADK-managed contents untouched.
        assert len(request.contents) == 1
        assert request.contents[0].parts[0].text == "ADK managed"
        # Verify it was NOT replaced with the 2 message_history entries
        assert not any(
            c.parts[0].text == "Hello" for c in request.contents
            if c.parts
        )

    def test_does_inject_contents_in_legacy_mode(self):
        """In legacy mode (no tools), callback injects message_history into contents."""
        state = {
            MESSAGE_HISTORY: [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
            ],
        }
        ctx = _make_callback_context(state, tool_calling=False)
        request = LlmRequest(model="test", contents=[])

        reasoning_before_model(ctx, request)

        # Legacy mode: contents injected from message_history
        assert len(request.contents) == 2
        assert request.contents[0].role == "user"
        assert request.contents[1].role == "model"

    def test_still_writes_system_instruction(self):
        """System instruction merge (static + dynamic) should still happen."""
        state = {MESSAGE_HISTORY: []}
        ctx = _make_callback_context(state, tool_calling=True)

        request = LlmRequest(model="test", contents=[])
        request.config = types.GenerateContentConfig(
            system_instruction="static prompt here"
        )

        reasoning_before_model(ctx, request)

        # system_instruction should still be set
        assert request.config is not None
        assert request.config.system_instruction is not None

    def test_still_sets_reasoning_call_start(self):
        """Token accounting timestamp should still be set."""
        state = {MESSAGE_HISTORY: []}
        ctx = _make_callback_context(state, tool_calling=True)
        request = LlmRequest(model="test", contents=[])

        reasoning_before_model(ctx, request)

        assert REASONING_CALL_START in ctx.state


class TestSimplifiedAfterModel:
    """reasoning_after_model in simplified mode preserves backward compat."""

    def test_still_writes_last_reasoning_response_for_legacy_compat(self):
        """LAST_REASONING_RESPONSE is still written for the legacy orchestrator
        loop which reads it to extract code blocks and FINAL answers.
        Removal is deferred to Phase 4 when the orchestrator is also updated."""
        state = {}
        ctx = _make_callback_context(state)
        response = _make_llm_response("The answer is 42.")

        reasoning_after_model(ctx, response)

        assert state[LAST_REASONING_RESPONSE] == "The answer is 42."

    def test_still_writes_token_accounting(self):
        """Token accounting from usage_metadata should still be written."""
        state = {}
        ctx = _make_callback_context(state, tool_calling=True)
        response = _make_llm_response("answer")
        response.usage_metadata = _make_usage_metadata(
            prompt_tokens=200, candidates_tokens=80
        )

        reasoning_after_model(ctx, response)

        assert state.get(REASONING_INPUT_TOKENS) == 200
        assert state.get(REASONING_OUTPUT_TOKENS) == 80

    def test_returns_none(self):
        """Callback should return None (observe-only)."""
        state = {}
        ctx = _make_callback_context(state, tool_calling=True)
        response = _make_llm_response("answer")

        result = reasoning_after_model(ctx, response)
        assert result is None
