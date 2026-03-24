"""Tests for the flow builder and AST utility."""

from __future__ import annotations

import pytest

from rlm_adk.dashboard.flow_builder import build_flow_transcript, find_llm_query_lines
from rlm_adk.dashboard.flow_models import (
    FlowAgentCard,
    FlowArrow,
    FlowChildCard,
    FlowCodeCell,
    FlowOutputCell,
    FlowTranscript,
)
from rlm_adk.dashboard.live_models import (
    LiveChildSummary,
    LiveInvocation,
    LiveInvocationNode,
)

pytestmark = pytest.mark.provider_fake_contract

# ── find_llm_query_lines tests ──────────────────────────────────────


class TestFindLlmQueryLines:
    def test_simple_call(self) -> None:
        code = 'result = llm_query("summarize this")\n'
        lines = find_llm_query_lines(code)
        assert lines == [(1, "llm_query", None)]

    def test_batched_call(self) -> None:
        code = 'results = llm_query_batched(["q1", "q2"])\n'
        lines = find_llm_query_lines(code)
        assert lines == [(1, "llm_query_batched", None)]

    def test_with_output_schema(self) -> None:
        code = 'result = llm_query("prompt", output_schema=MySchema)\n'
        lines = find_llm_query_lines(code)
        assert lines == [(1, "llm_query", "MySchema")]

    def test_multiple_calls(self) -> None:
        code = (
            "x = llm_query('first')\n"
            "y = do_something(x)\n"
            "z = llm_query('second', output_schema=Result)\n"
        )
        lines = find_llm_query_lines(code)
        assert lines == [(1, "llm_query", None), (3, "llm_query", "Result")]

    def test_no_calls(self) -> None:
        code = "x = 1 + 2\nprint(x)\n"
        lines = find_llm_query_lines(code)
        assert lines == []

    def test_syntax_error_returns_empty(self) -> None:
        code = "def broken(\n"
        lines = find_llm_query_lines(code)
        assert lines == []

    def test_method_call_on_object(self) -> None:
        code = 'result = self.llm_query("prompt")\n'
        lines = find_llm_query_lines(code)
        assert lines == [(1, "llm_query", None)]

    def test_empty_code(self) -> None:
        lines = find_llm_query_lines("")
        assert lines == []

    def test_batched_with_schema(self) -> None:
        code = "results = llm_query_batched(prompts, output_schema=MySchema)\n"
        lines = find_llm_query_lines(code)
        assert lines == [(1, "llm_query_batched", "MySchema")]


# ── build_flow_transcript tests ─────────────────────────────────────


def _make_invocation(
    *,
    invocation_id: str = "inv-1",
    pane_id: str = "pane-1",
    depth: int = 0,
    fanout_idx: int | None = None,
    agent_name: str = "reasoning_agent",
    iteration: int = 0,
    repl_submission: str = "",
    repl_expanded_code: str = "",
    repl_stdout: str = "",
    repl_stderr: str = "",
    child_summaries: list[LiveChildSummary] | None = None,
) -> LiveInvocation:
    return LiveInvocation(
        invocation_id=invocation_id,
        pane_id=pane_id,
        depth=depth,
        fanout_idx=fanout_idx,
        agent_name=agent_name,
        model="gemini-3-pro",
        model_version=None,
        status="completed",
        iteration=iteration,
        input_tokens=100,
        output_tokens=50,
        thought_tokens=0,
        elapsed_ms=500.0,
        request_chunks=[],
        state_items=[],
        child_summaries=child_summaries or [],
        repl_submission=repl_submission,
        repl_expanded_code=repl_expanded_code,
        repl_stdout=repl_stdout,
        repl_stderr=repl_stderr,
        reasoning_visible_text="",
        reasoning_thought_text="",
        structured_output=None,
        raw_payload={},
    )


def _make_child_summary(
    *,
    depth: int = 1,
    fanout_idx: int = 0,
    error: bool = False,
) -> LiveChildSummary:
    return LiveChildSummary(
        parent_depth=depth - 1,
        depth=depth,
        fanout_idx=fanout_idx,
        model="gemini-3-pro",
        status="error" if error else "completed",
        error=error,
        elapsed_ms=200.0,
        prompt="test prompt",
        prompt_preview="test prompt",
        result_text="test result",
        final_answer="done",
        visible_output_text="test output",
        visible_output_preview="test output",
        thought_text="",
        thought_preview="",
        raw_output=None,
        raw_output_preview="",
        input_tokens=80,
        output_tokens=30,
        thought_tokens=0,
        finish_reason="STOP",
        error_message="something broke" if error else None,
        structured_output=None,
        event_time=1.0,
        seq=1,
    )


def _make_node(
    invocation: LiveInvocation,
    *,
    available_invocations: list[LiveInvocation] | None = None,
    child_nodes: list[LiveInvocationNode] | None = None,
) -> LiveInvocationNode:
    return LiveInvocationNode(
        pane_id=invocation.pane_id,
        invocation=invocation,
        available_invocations=available_invocations or [invocation],
        child_nodes=child_nodes or [],
    )


class TestBuildFlowTranscript:
    def test_empty_nodes(self) -> None:
        transcript = build_flow_transcript([])
        assert transcript == FlowTranscript()

    def test_single_node_no_code(self) -> None:
        inv = _make_invocation()
        node = _make_node(inv)
        transcript = build_flow_transcript([node])

        assert len(transcript.blocks) == 1
        assert isinstance(transcript.blocks[0], FlowAgentCard)
        card = transcript.blocks[0]
        assert card.agent_name == "reasoning_agent"
        assert card.depth == 0

    def test_single_node_with_code(self) -> None:
        inv = _make_invocation(
            repl_submission="x = 1\nprint(x)\n",
            repl_stdout="1\n",
        )
        node = _make_node(inv)
        transcript = build_flow_transcript([node])

        kinds = [b.kind for b in transcript.blocks]
        assert kinds == ["agent_card", "arrow", "code_cell", "output_cell"]

        arrow = transcript.blocks[1]
        assert isinstance(arrow, FlowArrow)
        assert arrow.arrow_kind == "execute_code"
        assert arrow.direction == "down"

        code_cell = transcript.blocks[2]
        assert isinstance(code_cell, FlowCodeCell)
        assert code_cell.code == "x = 1\nprint(x)\n"

        output = transcript.blocks[3]
        assert isinstance(output, FlowOutputCell)
        assert output.stdout == "1\n"

    def test_node_with_children(self) -> None:
        child_summary = _make_child_summary(depth=1, fanout_idx=0)
        code = 'result = llm_query("analyze this")\nprint(result)\n'
        inv = _make_invocation(
            repl_submission=code,
            repl_stdout="analyzed\n",
            child_summaries=[child_summary],
        )
        node = _make_node(inv)
        transcript = build_flow_transcript([node])

        kinds = [b.kind for b in transcript.blocks]
        # agent_card, arrow(down), code_cell, arrow(right), child_card, arrow(left), output_cell
        assert kinds == [
            "agent_card",
            "arrow",
            "code_cell",
            "arrow",
            "child_card",
            "arrow",
            "output_cell",
        ]

        # Check child card
        child_card = transcript.blocks[4]
        assert isinstance(child_card, FlowChildCard)
        assert child_card.depth == 1
        assert child_card.fanout_idx == 0
        assert not child_card.error

        # Check return arrow — shows "set_model_response" label per mockup
        return_arrow = transcript.blocks[5]
        assert isinstance(return_arrow, FlowArrow)
        assert return_arrow.direction == "left"
        assert return_arrow.arrow_kind == "return_value"
        assert return_arrow.label == "set_model_response"

    def test_error_child_uses_error_arrow(self) -> None:
        child = _make_child_summary(depth=1, fanout_idx=0, error=True)
        code = 'result = llm_query("fail")\n'
        inv = _make_invocation(repl_submission=code, child_summaries=[child])
        node = _make_node(inv)
        transcript = build_flow_transcript([node])

        return_arrow = [
            b for b in transcript.blocks if isinstance(b, FlowArrow) and b.direction == "left"
        ][0]
        assert return_arrow.arrow_kind == "set_model_response"
        assert return_arrow.label == "error"

    def test_inspector_populated(self) -> None:
        inv = _make_invocation()
        node = _make_node(inv)
        transcript = build_flow_transcript([node])

        assert transcript.inspector is not None
        assert transcript.inspector.selected_pane_id == "pane-1"

    def test_code_cell_detects_llm_query_lines(self) -> None:
        code = (
            "data = load()\n"
            "summary = llm_query('summarize', output_schema=Summary)\n"
            "print(summary)\n"
        )
        child = _make_child_summary()
        inv = _make_invocation(repl_submission=code, child_summaries=[child])
        node = _make_node(inv)
        transcript = build_flow_transcript([node])

        code_cell = [b for b in transcript.blocks if isinstance(b, FlowCodeCell)][0]
        assert len(code_cell.llm_query_lines) == 1
        info = code_cell.llm_query_lines[0]
        assert info.line_number == 2
        assert info.function_name == "llm_query"
        assert info.schema_name == "Summary"
