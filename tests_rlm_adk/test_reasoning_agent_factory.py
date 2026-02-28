"""Phase 3 Part A: Reasoning agent factory tests for tools + output_schema support.

Tests that create_reasoning_agent accepts optional tools and output_schema kwargs,
and that backward compatibility (no tools) still works.

RED: These tests will fail until create_reasoning_agent is updated in rlm_adk/agent.py.
"""

import pytest

from rlm_adk.agent import create_reasoning_agent
from rlm_adk.types import ReasoningOutput


class TestReasoningAgentFactory:
    def test_create_reasoning_agent_backward_compat_no_tools(self):
        """Without tools/output_schema, agent works as before."""
        agent = create_reasoning_agent(model="gemini-fake")
        assert agent.tools == []
        assert agent.output_schema is None

    def test_create_reasoning_agent_with_output_schema(self):
        """output_schema kwarg is passed through to the LlmAgent."""
        agent = create_reasoning_agent(
            model="gemini-fake",
            output_schema=ReasoningOutput,
        )
        assert agent.output_schema == ReasoningOutput

    def test_create_reasoning_agent_with_tools(self):
        """tools kwarg is passed through to the LlmAgent."""

        def dummy_tool(x: str) -> str:
            """A dummy tool."""
            return x

        agent = create_reasoning_agent(
            model="gemini-fake",
            tools=[dummy_tool],
        )
        # ADK auto-wraps plain functions in FunctionTool
        assert len(agent.tools) == 1

    def test_create_reasoning_agent_with_tools_and_output_schema(self):
        """Both tools and output_schema can be provided together."""

        def dummy_tool(x: str) -> str:
            """A dummy tool."""
            return x

        agent = create_reasoning_agent(
            model="gemini-fake",
            tools=[dummy_tool],
            output_schema=ReasoningOutput,
        )
        assert len(agent.tools) == 1
        assert agent.output_schema == ReasoningOutput

    def test_agent_name_unchanged(self):
        """Agent name should remain 'reasoning_agent'."""
        agent = create_reasoning_agent(model="gemini-fake")
        assert agent.name == "reasoning_agent"

    def test_agent_disallows_transfers(self):
        """Agent should disallow transfers to parent and peers."""
        agent = create_reasoning_agent(model="gemini-fake")
        assert agent.disallow_transfer_to_parent is True
        assert agent.disallow_transfer_to_peers is True
