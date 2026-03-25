"""GAP-CB-001: _extract_adk_dynamic_instruction must be deleted.

It duplicates the entire conversation history into system_instruction
on every model call. ADK 1.27 handles dynamic instruction placement
natively via its request processors.

These tests verify:
1. _extract_adk_dynamic_instruction no longer exists
2. reasoning_before_model does NOT modify system_instruction
3. reasoning_before_model does NOT modify contents
4. Token accounting still works correctly
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import types

pytestmark = pytest.mark.provider_fake_contract


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_skill_toolset_integration.py)
# ---------------------------------------------------------------------------


def _make_llm_request(*, system_instruction="", contents=None):
    """Build a minimal LlmRequest with system_instruction and optional contents."""
    config = types.GenerateContentConfig(system_instruction=system_instruction)
    req = LlmRequest(model="gemini-2.0-flash", config=config)
    if contents is not None:
        req.contents = contents
    return req


def _make_callback_context():
    """Build a mock CallbackContext for reasoning_before_model."""
    ctx = MagicMock()
    ctx.state.get.return_value = 0  # ITERATION_COUNT
    # _invocation_context.agent with expected attrs
    agent = MagicMock()
    agent.name = "test_reasoning"
    agent._rlm_depth = 0
    agent._rlm_fanout_idx = 0
    agent._rlm_parent_depth = None
    agent._rlm_parent_fanout_idx = None
    agent._rlm_output_schema_name = None
    agent._rlm_pending_request_meta = None
    inv = MagicMock()
    inv.agent = agent
    inv.branch = None
    inv.invocation_id = "test-inv-001"
    inv.session.id = "test-sess-001"
    ctx._invocation_context = inv
    return ctx


class TestExtractAdkDynamicInstructionDeleted:
    """The buggy _extract_adk_dynamic_instruction function must not exist."""

    def test_function_not_importable(self) -> None:
        """_extract_adk_dynamic_instruction must not be importable from the module."""
        import rlm_adk.callbacks.reasoning as mod

        assert not hasattr(mod, "_extract_adk_dynamic_instruction"), (
            "_extract_adk_dynamic_instruction still exists in reasoning.py. "
            "It must be deleted — it duplicates the entire conversation "
            "history into system_instruction."
        )

    def test_function_not_in_module_dict(self) -> None:
        """Double-check via module __dict__ that the function is gone."""
        import rlm_adk.callbacks.reasoning as mod

        assert "_extract_adk_dynamic_instruction" not in dir(mod), (
            "_extract_adk_dynamic_instruction found in dir(reasoning). "
            "The function must be fully removed."
        )


class TestReasoningBeforeModelNoHistoryDuplication:
    """reasoning_before_model must NOT append contents text to system_instruction."""

    def test_system_instruction_unchanged_after_callback(self) -> None:
        """system_instruction must be identical before and after the callback.

        The bug was that _extract_adk_dynamic_instruction read ALL text from
        contents (the entire conversation history) and appended it to
        system_instruction via append_instructions. After the fix,
        system_instruction must remain exactly as ADK set it.
        """
        from rlm_adk.callbacks.reasoning import reasoning_before_model

        original_si = "You are a reasoning agent.\n\n<available_skills>...</available_skills>"
        conversation_history = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text="Hello, what is 2+2?")],
            ),
            types.Content(
                role="model",
                parts=[types.Part.from_text(text="Let me think about that.")],
            ),
            types.Content(
                role="user",
                parts=[types.Part.from_text(text="execute_code result: 4")],
            ),
        ]

        llm_request = _make_llm_request(
            system_instruction=original_si,
            contents=conversation_history,
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        # system_instruction must be EXACTLY unchanged
        assert llm_request.config.system_instruction == original_si, (
            f"reasoning_before_model modified system_instruction! "
            f"Expected: {original_si!r}, "
            f"Got: {llm_request.config.system_instruction!r}"
        )

    def test_contents_unchanged_after_callback(self) -> None:
        """contents must not be modified by reasoning_before_model.

        The callback should be observe-only — it reads contents for token
        accounting but must not alter them.
        """
        from rlm_adk.callbacks.reasoning import reasoning_before_model

        original_contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text="Dynamic instruction here")],
            ),
            types.Content(
                role="model",
                parts=[types.Part.from_text(text="Model response")],
            ),
        ]
        # Capture original text for comparison
        original_texts = [
            part.text
            for content in original_contents
            if content.parts
            for part in content.parts
        ]

        llm_request = _make_llm_request(
            system_instruction="Static instruction",
            contents=original_contents,
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        # Contents must be the same objects with same text
        assert len(llm_request.contents) == len(original_contents)
        after_texts = [
            part.text
            for content in llm_request.contents
            if content.parts
            for part in content.parts
        ]
        assert after_texts == original_texts, (
            f"reasoning_before_model modified contents! "
            f"Before: {original_texts}, After: {after_texts}"
        )

    def test_observe_only_with_large_history(self) -> None:
        """With a large conversation history, system_instruction must not grow.

        This is the core of GAP-CB-001: the old code would concatenate
        ALL text from ALL contents into system_instruction, duplicating
        potentially megabytes of conversation history.
        """
        from rlm_adk.callbacks.reasoning import reasoning_before_model

        original_si = "Static system prompt."
        # Simulate a large conversation history (many tool calls/responses)
        large_history = []
        for i in range(20):
            large_history.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=f"User message {i} " * 100)],
                )
            )
            large_history.append(
                types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=f"Model response {i} " * 100)],
                )
            )

        llm_request = _make_llm_request(
            system_instruction=original_si,
            contents=large_history,
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        # system_instruction must NOT have grown
        assert llm_request.config.system_instruction == original_si, (
            f"system_instruction grew from {len(original_si)} chars to "
            f"{len(llm_request.config.system_instruction)} chars. "
            f"This is the GAP-CB-001 bug: conversation history was "
            f"duplicated into system_instruction."
        )


class TestTokenAccountingStillWorks:
    """Token accounting must still function after removing the extraction logic."""

    def test_request_meta_stored_on_agent(self) -> None:
        """reasoning_before_model must still store request metadata on the agent.

        The _rlm_pending_request_meta attribute should contain prompt_chars,
        system_chars, content_count, and lineage.
        """
        from rlm_adk.callbacks.reasoning import reasoning_before_model

        system_text = "You are a reasoning agent."
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text="Hello world")],
            ),
        ]

        llm_request = _make_llm_request(
            system_instruction=system_text,
            contents=contents,
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        # Verify metadata was stored on the agent
        agent = callback_ctx._invocation_context.agent
        # object.__setattr__ was called, so we check via the mock's call record
        # Since it's a MagicMock, object.__setattr__ works directly
        meta = agent._rlm_pending_request_meta
        assert meta is not None, "request_meta was not stored on agent"

    def test_system_chars_reflects_actual_system_instruction(self) -> None:
        """system_chars must reflect the real system_instruction length.

        After the fix, system_chars should be the length of the static
        instruction + any SkillToolset XML — NOT inflated by conversation
        history text that was erroneously appended.
        """
        from rlm_adk.callbacks.reasoning import reasoning_before_model

        system_text = "Static instruction content."
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text="A" * 10000)],
            ),
        ]

        llm_request = _make_llm_request(
            system_instruction=system_text,
            contents=contents,
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        agent = callback_ctx._invocation_context.agent
        meta = agent._rlm_pending_request_meta
        assert meta["system_chars"] == len(system_text), (
            f"system_chars should be {len(system_text)}, got {meta['system_chars']}"
        )
        assert meta["prompt_chars"] == 10000, (
            f"prompt_chars should be 10000, got {meta['prompt_chars']}"
        )
        assert meta["content_count"] == 1, (
            f"content_count should be 1, got {meta['content_count']}"
        )

    def test_callback_returns_none(self) -> None:
        """reasoning_before_model must return None (observe-only)."""
        from rlm_adk.callbacks.reasoning import reasoning_before_model

        llm_request = _make_llm_request(
            system_instruction="Test",
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text="Hello")],
                ),
            ],
        )
        callback_ctx = _make_callback_context()

        result = reasoning_before_model(callback_ctx, llm_request)
        assert result is None, (
            f"reasoning_before_model should return None, got {result!r}"
        )

    def test_empty_contents_does_not_crash(self) -> None:
        """Callback handles empty/None contents gracefully."""
        from rlm_adk.callbacks.reasoning import reasoning_before_model

        llm_request = _make_llm_request(system_instruction="Test")
        # contents is None by default
        callback_ctx = _make_callback_context()

        result = reasoning_before_model(callback_ctx, llm_request)
        assert result is None

        agent = callback_ctx._invocation_context.agent
        meta = agent._rlm_pending_request_meta
        assert meta["prompt_chars"] == 0
        assert meta["content_count"] == 0

    def test_empty_system_instruction_does_not_crash(self) -> None:
        """Callback handles empty system_instruction gracefully."""
        from rlm_adk.callbacks.reasoning import reasoning_before_model

        req = _make_llm_request(system_instruction="")
        callback_ctx = _make_callback_context()

        result = reasoning_before_model(callback_ctx, req)
        assert result is None

        agent = callback_ctx._invocation_context.agent
        meta = agent._rlm_pending_request_meta
        assert meta["system_chars"] == 0
