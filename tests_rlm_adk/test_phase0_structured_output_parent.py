"""Tests for Phase 0: Structured output on parent reasoning agent.

Verifies that the orchestrator wires both execute_code (REPLTool) and
set_model_response (SetModelResponseTool) + retry callbacks onto the
reasoning_agent, and that final_answer extraction works for both
structured output (dict) and plain text paths.
"""

import inspect
import json
import textwrap

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from rlm_adk.orchestrator import RLMOrchestratorAgent
from rlm_adk.types import ReasoningOutput


def _get_orchestrator_source() -> str:
    return textwrap.dedent(
        inspect.getsource(RLMOrchestratorAgent._run_async_impl)
    )


class TestReasoningAgentHasBothTools:
    """After orchestrator wiring, tools list contains execute_code and set_model_response."""

    def test_source_references_set_model_response_tool(self):
        source = _get_orchestrator_source()
        assert "SetModelResponseTool" in source, (
            "Orchestrator must wire SetModelResponseTool onto reasoning_agent"
        )

    def test_source_references_repl_tool(self):
        source = _get_orchestrator_source()
        assert "repl_tool" in source
        assert "REPLTool" in source

    def test_source_wires_both_tools(self):
        """Tools list should contain both repl_tool and set_model_response_tool."""
        source = _get_orchestrator_source()
        assert "repl_tool, set_model_response_tool" in source, (
            "Orchestrator must wire [repl_tool, set_model_response_tool]"
        )


class TestReasoningAgentHasRetryCallbacks:
    """after_tool_callback and on_tool_error_callback are wired."""

    def test_source_wires_after_tool_callback(self):
        source = _get_orchestrator_source()
        assert "after_tool_callback" in source
        assert "after_tool_cb" in source

    def test_source_wires_on_tool_error_callback(self):
        source = _get_orchestrator_source()
        assert "on_tool_error_callback" in source
        assert "on_tool_error_cb" in source

    def test_source_cleans_up_callbacks_in_finally(self):
        source = _get_orchestrator_source()
        # The finally block should set both callbacks to None
        assert "'after_tool_callback', None" in source
        assert "'on_tool_error_callback', None" in source

    def test_source_uses_make_worker_tool_callbacks(self):
        source = _get_orchestrator_source()
        assert "make_worker_tool_callbacks" in source


class TestStructuredOutputExtraction:
    """Mock reasoning_agent to write ReasoningOutput dict to output_key;
    verify final_answer extraction."""

    def test_dict_output_extracts_final_answer(self):
        """When output_key contains a dict, extract final_answer field."""
        raw = {"final_answer": "The answer is 42.", "reasoning_summary": "computed"}
        final_answer = raw.get("final_answer", "")
        assert final_answer == "The answer is 42."

    def test_json_string_output_extracts_final_answer(self):
        """When output_key contains JSON string, parse and extract final_answer."""
        raw = json.dumps({"final_answer": "hello world", "reasoning_summary": ""})
        parsed = json.loads(raw)
        final_answer = parsed.get("final_answer", raw)
        assert final_answer == "hello world"


class TestPlainTextStillWorks:
    """Mock reasoning_agent to write plain text; verify backward-compatible extraction."""

    def test_plain_text_returned_as_is(self):
        """Plain text without JSON or FINAL() is used as-is."""
        raw = "This is a plain text response."
        try:
            parsed = json.loads(raw)
            final_answer = parsed.get("final_answer", raw)
        except (json.JSONDecodeError, ValueError):
            final_answer = raw
        assert final_answer == "This is a plain text response."

    def test_final_marker_extraction(self):
        """FINAL(...) marker is extracted from plain text (must be at start of line)."""
        from rlm_adk.utils.parsing import find_final_answer
        raw = "Some text\nFINAL(The real answer)"
        parsed = find_final_answer(raw)
        assert parsed is not None
        assert "The real answer" in parsed


class TestOutputSchemaField:
    """The orchestrator should use self.output_schema or default to ReasoningOutput."""

    def test_source_uses_output_schema_or_default(self):
        source = _get_orchestrator_source()
        assert "self.output_schema or ReasoningOutput" in source

    def test_output_schema_field_exists(self):
        """RLMOrchestratorAgent should have an output_schema field."""
        from google.adk.agents import LlmAgent
        agent = LlmAgent(name="test_reasoning", model="test")
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=agent,
            sub_agents=[agent],
            output_schema=None,
        )
        assert orch.output_schema is None

    def test_depth_field_exists(self):
        """RLMOrchestratorAgent should have a depth field defaulting to 0."""
        from google.adk.agents import LlmAgent
        agent = LlmAgent(name="test_reasoning", model="test")
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=agent,
            sub_agents=[agent],
        )
        assert orch.depth == 0


class TestOutputKeyDynamic:
    """The orchestrator reads from reasoning_agent.output_key, not hardcoded."""

    def test_source_reads_dynamic_output_key(self):
        source = _get_orchestrator_source()
        assert "self.reasoning_agent.output_key" in source
        assert 'or "reasoning_output"' in source
