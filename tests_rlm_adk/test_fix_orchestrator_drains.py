"""Tests for collapsed orchestrator structure (Phase 5B).

These tests verify that the orchestrator has been collapsed to delegate
to reasoning_agent.run_async with REPLTool instead of manually iterating
with find_code_blocks and event_queue drains.

Replaces the previous drain-pattern tests that verified event_queue drain
locations in the old manual iteration loop.
"""

import inspect
import textwrap

from rlm_adk.orchestrator import RLMOrchestratorAgent


def _get_orchestrator_source() -> str:
    """Get dedented source of _run_async_impl."""
    return textwrap.dedent(
        inspect.getsource(RLMOrchestratorAgent._run_async_impl)
    )


class TestCollapsedOrchestratorStructure:
    """Verify the orchestrator delegates to reasoning_agent.run_async
    instead of manually iterating with find_code_blocks."""

    def test_orchestrator_uses_reasoning_agent_run_async(self):
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

    def test_orchestrator_does_not_use_find_code_blocks(self):
        """The orchestrator source must NOT call find_code_blocks."""
        source = _get_orchestrator_source()
        assert "find_code_blocks" not in source, (
            "Collapsed orchestrator should not call find_code_blocks -- "
            "code execution is handled by REPLTool"
        )

    def test_orchestrator_does_not_drain_events(self):
        """The orchestrator source must NOT drain an event queue."""
        source = _get_orchestrator_source()
        # The collapsed orchestrator should not reference event draining
        assert "get_nowait" not in source, (
            "Collapsed orchestrator should not drain events via get_nowait"
        )

    def test_orchestrator_wires_reasoning_output(self):
        """The orchestrator should wire ReasoningOutput as output_schema."""
        source = _get_orchestrator_source()
        assert "ReasoningOutput" in source, (
            "Orchestrator must wire ReasoningOutput as output_schema on reasoning_agent"
        )


class TestMidIterationDrain:
    """Mid-iteration drain is no longer needed in collapsed mode.
    Verify the orchestrator does not contain mid-iteration drain patterns."""

    def test_no_mid_iteration_drain(self):
        source = _get_orchestrator_source()
        assert "mid-iteration" not in source.lower(), (
            "Collapsed orchestrator should not have mid-iteration drain logic"
        )


class TestMidIterationDrainPrintsCount:
    """Mid-iteration drain print is no longer needed in collapsed mode."""

    def test_no_mid_iteration_drain_print(self):
        source = _get_orchestrator_source()
        assert "mid-iteration worker_events_drained" not in source, (
            "Collapsed orchestrator should not print mid-iteration drain count"
        )
