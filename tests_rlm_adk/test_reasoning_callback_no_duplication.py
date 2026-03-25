"""GAP-CB-006: Token accounting must not double-count appended dynamic instruction.

reasoning_before_model computes system_chars and total_prompt_chars for
telemetry.  If the accounting runs AFTER append_instructions modifies
system_instruction, then system_chars includes the dynamic text that was
just appended -- a self-referential measurement that inflates the count.

These tests verify that system_chars reflects only the ORIGINAL
system_instruction (static prompt + SkillToolset XML) and does NOT include
the dynamic instruction text appended by the callback itself.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from rlm_adk.callbacks.reasoning import reasoning_before_model


# ---------------------------------------------------------------------------
# Helpers (reused from test_skill_toolset_integration patterns)
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
    ctx.state.get.return_value = 0
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


# ---------------------------------------------------------------------------
# GAP-CB-006 tests
# ---------------------------------------------------------------------------


class TestTokenAccountingNoDuplication:
    """system_chars must reflect the pre-modification system_instruction."""

    def test_system_chars_excludes_appended_dynamic_text(self) -> None:
        """system_chars should equal len(original system_instruction), not
        len(original + appended dynamic text).

        The dynamic_text is 40 chars.  The static instruction is 27 chars.
        If accounting runs AFTER append_instructions, system_chars will be
        >= 27 + 40 (plus separator).  If it runs BEFORE, system_chars == 27.
        """
        static_instruction = "You are a reasoning agent."  # 26 chars
        dynamic_text = "Current iteration: 1, root prompt: test"  # 39 chars
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=dynamic_text)],
            )
        ]

        llm_request = _make_llm_request(
            system_instruction=static_instruction,
            contents=contents,
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        # Extract the stored request_meta from the agent mock
        agent = callback_ctx._invocation_context.agent
        # object.__setattr__ was called on the mock -- read the attr directly
        meta = agent._rlm_pending_request_meta
        assert meta is not None, "request_meta was not stored on agent"

        system_chars = meta["system_chars"]
        expected_system_chars = len(static_instruction)

        assert system_chars == expected_system_chars, (
            f"system_chars={system_chars} but expected {expected_system_chars}. "
            f"The dynamic text ({len(dynamic_text)} chars) was counted in "
            f"system_chars, proving token accounting runs AFTER "
            f"append_instructions (GAP-CB-006)."
        )

    def test_system_chars_with_skill_xml_excludes_dynamic(self) -> None:
        """When SkillToolset XML is already in system_instruction,
        system_chars should include the XML but NOT the dynamic text."""
        static_instruction = "You are a reasoning agent."
        skill_xml = (
            "\n\nYou can use specialized 'skills'...\n\n"
            "<available_skills>\n"
            "<skill><name>ping</name>"
            "<description>A diagnostic skill</description></skill>\n"
            "</available_skills>"
        )
        combined_si = static_instruction + skill_xml
        dynamic_text = "Iteration: 2, prompt: analyze data"
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=dynamic_text)],
            )
        ]

        llm_request = _make_llm_request(
            system_instruction=combined_si,
            contents=contents,
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        agent = callback_ctx._invocation_context.agent
        meta = agent._rlm_pending_request_meta
        system_chars = meta["system_chars"]
        expected = len(combined_si)

        assert system_chars == expected, (
            f"system_chars={system_chars} but expected {expected} "
            f"(static + skill XML only). Dynamic text was included "
            f"in system_chars (GAP-CB-006)."
        )

    def test_prompt_chars_unaffected_by_reorder(self) -> None:
        """total_prompt_chars should still reflect the contents text."""
        static_instruction = "System prompt."
        dynamic_text = "Some dynamic content here"
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=dynamic_text)],
            )
        ]

        llm_request = _make_llm_request(
            system_instruction=static_instruction,
            contents=contents,
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        agent = callback_ctx._invocation_context.agent
        meta = agent._rlm_pending_request_meta
        prompt_chars = meta["prompt_chars"]

        assert prompt_chars == len(dynamic_text), (
            f"prompt_chars={prompt_chars} but expected {len(dynamic_text)}."
        )

    def test_no_dynamic_content_system_chars_unchanged(self) -> None:
        """When contents is empty, system_chars should just be the static text."""
        static_instruction = "You are an agent."

        llm_request = _make_llm_request(
            system_instruction=static_instruction,
            contents=[],
        )
        callback_ctx = _make_callback_context()

        reasoning_before_model(callback_ctx, llm_request)

        agent = callback_ctx._invocation_context.agent
        meta = agent._rlm_pending_request_meta
        system_chars = meta["system_chars"]

        assert system_chars == len(static_instruction), (
            f"system_chars={system_chars} but expected {len(static_instruction)}."
        )
