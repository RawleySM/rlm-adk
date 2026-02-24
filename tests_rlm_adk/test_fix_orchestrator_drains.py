"""Tests for orchestrator event queue drain fixes:

Fix 3: Final-iteration event loss - drain event queue before yielding
       final answer events AND before max-iterations exhausted path.

Fix 7: Mid-iteration event queue drain - drain event queue after code
       block execution and BEFORE find_final_answer() is called.

These tests use static analysis of the orchestrator source to verify
the drain patterns exist in the correct locations.
"""

import inspect
import textwrap

from rlm_adk.orchestrator import RLMOrchestratorAgent


def _get_orchestrator_source() -> str:
    """Get dedented source of _run_async_impl."""
    return textwrap.dedent(
        inspect.getsource(RLMOrchestratorAgent._run_async_impl)
    )


class TestFinalAnswerDrain:
    """Fix 3: The orchestrator must drain the event queue BEFORE yielding
    the final answer state delta and content events.

    This prevents worker events from being lost when the final answer is
    detected and the generator returns immediately.
    """

    def test_drain_before_final_answer_yield(self):
        """The source must contain an event_queue drain within the
        'if final_answer is not None:' block, BEFORE the FINAL_ANSWER state delta."""
        source = _get_orchestrator_source()
        lines = source.split("\n")

        # Find lines by content
        final_answer_check_line = None
        drain_line = None
        final_answer_state_delta_line = None

        for i, line in enumerate(lines):
            if "if final_answer is not None:" in line:
                final_answer_check_line = i
            # After we find the final_answer check, look for drain and FINAL_ANSWER
            if final_answer_check_line is not None:
                if "event_queue" in line and "empty" in line and drain_line is None:
                    drain_line = i
                if "FINAL_ANSWER" in line and "final_answer" in line and "state_delta" not in line:
                    # This is the FINAL_ANSWER: final_answer line in the state_delta dict
                    pass
                if "FINAL_ANSWER:" in line and final_answer_state_delta_line is None:
                    final_answer_state_delta_line = i

        assert final_answer_check_line is not None, (
            "Could not find 'if final_answer is not None:' block"
        )
        assert drain_line is not None, (
            "No event_queue drain found after final_answer check. "
            "Worker events will be lost when final answer is detected."
        )
        assert final_answer_state_delta_line is not None, (
            "Could not find FINAL_ANSWER in state_delta"
        )
        assert drain_line < final_answer_state_delta_line, (
            f"Event queue drain (line {drain_line}) must come BEFORE "
            f"FINAL_ANSWER state delta (line {final_answer_state_delta_line})"
        )


class TestMaxIterationsDrain:
    """The orchestrator must drain the event queue before the
    max-iterations-exhausted path."""

    def test_drain_before_max_iterations_exhausted(self):
        """The source must contain an event_queue drain before
        the max iterations exhausted section."""
        source = _get_orchestrator_source()
        lines = source.split("\n")

        exhausted_line = None
        last_drain_before_exhausted = None

        for i, line in enumerate(lines):
            if "max_iterations" in line and "exhausted" in line.lower():
                if exhausted_line is None:
                    exhausted_line = i
                continue

            # Track drain lines that appear before exhausted
            if exhausted_line is None:
                if "event_queue" in line and ("empty" in line or "get_nowait" in line):
                    last_drain_before_exhausted = i

        assert exhausted_line is not None, (
            "Could not find max_iterations exhausted section"
        )
        assert last_drain_before_exhausted is not None, (
            "No event_queue drain found before max_iterations exhausted section. "
            "Worker events will be lost when max iterations is reached."
        )


class TestMidIterationDrain:
    """Fix 7: The orchestrator must drain the event queue after code block
    execution and BEFORE find_final_answer() is called.

    This ensures worker events from llm_query calls within code blocks
    are yielded to the Runner before the orchestrator checks for the
    final answer.
    """

    def test_drain_after_code_blocks_before_final_check(self):
        """The source must contain an event_queue drain between the
        code block execution loop and find_final_answer()."""
        source = _get_orchestrator_source()
        lines = source.split("\n")

        # Find lines with key markers
        last_save_repl_output_line = None
        find_final_answer_line = None
        mid_drain_line = None

        for i, line in enumerate(lines):
            stripped = line.strip()

            if "save_repl_output" in stripped:
                last_save_repl_output_line = i

            if "find_final_answer" in stripped and "=" in stripped:
                if find_final_answer_line is None:
                    find_final_answer_line = i

            # Mid-iteration drain between code blocks and find_final_answer
            if last_save_repl_output_line is not None and find_final_answer_line is None:
                if "event_queue" in stripped and ("empty" in stripped or "get_nowait" in stripped):
                    mid_drain_line = i

        assert find_final_answer_line is not None, (
            "Could not find find_final_answer() call"
        )
        assert mid_drain_line is not None, (
            "No mid-iteration event_queue drain found between code block "
            "execution and find_final_answer(). Worker events from llm_query "
            "calls in code blocks will not be yielded until the next iteration."
        )
        assert mid_drain_line < find_final_answer_line, (
            f"Mid-iteration drain (line {mid_drain_line}) must come BEFORE "
            f"find_final_answer (line {find_final_answer_line})"
        )


class TestMidIterationDrainPrintsCount:
    """Fix 7: The mid-iteration drain should print the count when events are drained."""

    def test_mid_iteration_drain_prints_message(self):
        source = _get_orchestrator_source()
        assert "mid-iteration worker_events_drained" in source, (
            "Mid-iteration drain should print a diagnostic message with drain count"
        )
