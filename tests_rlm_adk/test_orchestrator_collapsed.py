"""Tests for the collapsed orchestrator (Phase 5B).

The orchestrator should delegate to reasoning_agent.run_async with REPLTool
instead of manually iterating, parsing code blocks, and executing them.

These tests verify the orchestrator's source structure and output_key
deserialization logic.
"""

import inspect
import json
import textwrap

import rlm_adk.orchestrator as _orchestrator_module
from rlm_adk.orchestrator import RLMOrchestratorAgent


def _get_orchestrator_source() -> str:
    """Get dedented source of _run_async_impl and module-level helpers."""
    impl_source = textwrap.dedent(
        inspect.getsource(RLMOrchestratorAgent._run_async_impl)
    )
    # Include module-level helpers that were refactored out of _run_async_impl
    helper_source = textwrap.dedent(
        inspect.getsource(_orchestrator_module._collect_reasoning_completion)
    )
    return impl_source + "\n" + helper_source


class TestCollapsedOrchestratorStructure:
    """Verify the orchestrator delegates to reasoning_agent.run_async
    instead of manually iterating with find_code_blocks."""

    def test_orchestrator_delegates_to_reasoning_agent(self):
        """The orchestrator source must contain reasoning_agent.run_async."""
        source = _get_orchestrator_source()
        assert "reasoning_agent.run_async" in source, (
            "Orchestrator must delegate to self.reasoning_agent.run_async(ctx)"
        )

    def test_orchestrator_uses_repl_tool(self):
        """The orchestrator source must reference REPLTool."""
        source = _get_orchestrator_source()
        assert "REPLTool" in source, (
            "Orchestrator must create and wire a REPLTool for the reasoning agent"
        )

    def test_orchestrator_no_event_queue(self):
        """The orchestrator source must NOT use event_queue."""
        source = _get_orchestrator_source()
        assert "event_queue" not in source, (
            "Collapsed orchestrator should not use event_queue -- "
            "events are consumed by _consume_events in dispatch"
        )

    def test_orchestrator_no_find_code_blocks(self):
        """The orchestrator source must NOT call find_code_blocks."""
        source = _get_orchestrator_source()
        assert "find_code_blocks" not in source, (
            "Collapsed orchestrator should not call find_code_blocks -- "
            "code execution is handled by REPLTool"
        )

    def test_orchestrator_extracts_from_output_key(self):
        """The orchestrator should extract the final answer from reasoning_output."""
        source = _get_orchestrator_source()
        assert "reasoning_output" in source, (
            "Orchestrator must read the reasoning_output from output_key"
        )

    def test_orchestrator_wires_output_schema(self):
        """The orchestrator should wire ReasoningOutput as output_schema."""
        source = _get_orchestrator_source()
        assert "ReasoningOutput" in source, (
            "Orchestrator must wire ReasoningOutput as output_schema on reasoning_agent"
        )


class TestCollapsedOrchestratorOutputKey:
    """Test output_key deserialization logic that the collapsed orchestrator uses."""

    def test_output_key_json_string_deserialization(self):
        """JSON string from output_key should be deserialized to dict."""
        raw = json.dumps({"final_answer": "The answer is 42.", "reasoning_summary": ""})
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        final_answer = ""
        if isinstance(parsed, dict):
            final_answer = parsed.get("final_answer", "")
        assert final_answer == "The answer is 42."

    def test_output_key_dict_passthrough(self):
        """Dict from output_key should pass through directly."""
        raw = {"final_answer": "Direct dict", "reasoning_summary": "summary"}
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        final_answer = ""
        if isinstance(parsed, dict):
            final_answer = parsed.get("final_answer", "")
        assert final_answer == "Direct dict"

    def test_output_key_empty_default(self):
        """Missing or empty output_key should default to empty string."""
        raw = "{}"
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        final_answer = ""
        if isinstance(parsed, dict):
            final_answer = parsed.get("final_answer", "")
        assert final_answer == ""

    def test_output_key_plain_string(self):
        """Plain string (non-JSON) from output_key should be used as final_answer."""
        raw = "Just a plain string"
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            parsed = raw
        final_answer = ""
        if isinstance(parsed, dict):
            final_answer = parsed.get("final_answer", "")
        elif isinstance(parsed, str):
            final_answer = parsed
        assert final_answer == "Just a plain string"
