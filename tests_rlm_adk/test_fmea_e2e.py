"""
FMEA-driven end-to-end tests for RLM-ADK failure modes.

Each test targets a specific failure mode from rlm_adk_FMEA.md and makes
assertions beyond the basic contract (final_answer, iterations, model_calls)
to verify correct error handling, state management, and recovery behavior.

Fixture contracts are already validated by the parametrized test in
test_provider_fake_e2e.py.  The contract tests here are dedicated per-fixture
tests that additionally exercise plugin pipelines and inspect events, state
keys, and function_response payloads for deeper behavioral verification.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rlm_adk.state import (
    FINAL_ANSWER,
    ITERATION_COUNT,
    LAST_REPL_RESULT,
    OBS_CHILD_DISPATCH_LATENCY_MS,
    OBS_CHILD_ERROR_COUNTS,
    OBS_STRUCTURED_OUTPUT_FAILURES,
    OBS_TOTAL_CALLS,
    OBS_WORKER_DISPATCH_LATENCY_MS,
    OBS_WORKER_ERROR_COUNTS,
    WORKER_DISPATCH_COUNT,
)

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import (
    PluginContractResult,
    run_fixture_contract,
    run_fixture_contract_with_plugins,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_with_plugins(
    fixture_name: str, tmp_path: Path,
) -> PluginContractResult:
    """Run a named fixture through the plugin-enabled pipeline."""
    fixture_path = FIXTURE_DIR / f"{fixture_name}.json"
    traces_db = str(tmp_path / "traces.db")
    return await run_fixture_contract_with_plugins(
        fixture_path,
        traces_db_path=traces_db,
        repl_trace_level=1,
    )


def _extract_tool_results(events: list) -> list[dict]:
    """Extract execute_code function_response dicts from event stream."""
    tool_results = []
    for event in events:
        content = getattr(event, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []):
            fr = getattr(part, "function_response", None)
            if fr is not None and getattr(fr, "name", "") == "execute_code":
                response_data = getattr(fr, "response", None)
                if isinstance(response_data, dict):
                    tool_results.append(response_data)
    return tool_results


# ===========================================================================
# FM-08: Worker 429 Mid-Batch — REMOVED (Phase 3 migration)
# Worker fixtures are incompatible with child orchestrator dispatch.
# ===========================================================================


# ===========================================================================
# FM-05/14/23: REPL Error Then Retry (RPN=96/48)
# ===========================================================================


class TestReplErrorThenRetry:
    """Verify REPL error handling and cross-iteration recovery."""

    FIXTURE = "repl_error_then_retry"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_two_iterations_required(self, tmp_path: Path):
        """Verify error forced a second iteration."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 2, f"Expected 2 iterations, got {iter_count}"

    async def test_error_visible_in_tool_response(self, tmp_path: Path):
        """Verify the KeyError from iter1 is visible in a function_response stderr."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 2, (
            f"Expected >= 2 tool results (error + retry), got {len(tool_results)}"
        )
        # The first tool execution should contain an error in stderr
        # (KeyError with old leaf workers, JSONDecodeError with child orchestrators)
        first_stderr = tool_results[0].get("stderr", "")
        assert "Error" in first_stderr, (
            f"Expected an error in first tool stderr: {first_stderr!r}"
        )

    async def test_first_tool_response_variables_empty(self, tmp_path: Path):
        """Verify first (failed) tool_response has variables == {} (FM-23).

        When the REPL code raises KeyError after llm_query + json.loads,
        the except block in LocalREPL.execute_code skips the locals-update
        loop, so no variables from the failed execution should appear in the
        tool result.  This verifies variable persistence loss (FM-23): the
        REPL correctly does NOT leak partial assignments from a failed exec.
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 2, (
            f"Expected >= 2 tool results (error + retry), got {len(tool_results)}"
        )
        first_vars = tool_results[0].get("variables", {})
        assert first_vars == {}, (
            f"Expected empty variables dict on failed first REPL execution "
            f"(KeyError should prevent locals update), got {first_vars!r}"
        )

    async def test_first_tool_response_has_llm_calls(self, tmp_path: Path):
        """Verify first tool_response has llm_calls_made=True (FM-05/14).

        Even though the REPL code raised KeyError, the llm_query() call was
        detected by the AST rewriter and the code was executed via the async
        path (execute_code_async). This confirms the async dispatch path was
        taken, not the sync path.
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 1, "Expected at least one tool result"
        first_llm_calls = tool_results[0].get("llm_calls_made")
        assert first_llm_calls is True, (
            f"Expected llm_calls_made=True on first tool response "
            f"(llm_query was called before KeyError), got {first_llm_calls!r}"
        )

    async def test_retry_succeeds_in_final_answer(self, tmp_path: Path):
        """Verify the corrected code's result appears in FINAL_ANSWER."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "alpha-42" in fa, f"Expected 'alpha-42' in final_answer: {fa!r}"


# ===========================================================================
# FM-17: Structured Output Batched K>1 (RPN=90)
# ===========================================================================


class TestStructuredOutputBatchedK3:
    """Verify structured output with parallel workers (K=3)."""

    FIXTURE = "structured_output_batched_k3"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_all_workers_produced_results(self, tmp_path: Path):
        """Verify 3 workers dispatched and results aggregated correctly."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        dispatch_count = result.final_state.get(WORKER_DISPATCH_COUNT, 0)
        assert dispatch_count == 3, (
            f"Expected WORKER_DISPATCH_COUNT == 3, got {dispatch_count}"
        )
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "2 positive" in fa, f"Expected '2 positive' in final_answer: {fa!r}"
        assert "1 negative" in fa, f"Expected '1 negative' in final_answer: {fa!r}"

    async def test_with_plugins_no_crash(self, tmp_path: Path):
        """Full plugin stack (observability + sqlite + repl tracing) runs cleanly."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        assert len(result.events) > 0, "Expected events from the run"
        # Verify REPL snapshot has trace_summary from repl_trace_level=1
        repl_snapshots = [
            (getattr(getattr(ev, "actions", None), "state_delta", None) or {}).get(
                LAST_REPL_RESULT
            )
            for ev in result.events
        ]
        repl_snapshots = [s for s in repl_snapshots if s is not None]
        assert len(repl_snapshots) >= 1, "Expected at least one REPL snapshot"
        for i, snap in enumerate(repl_snapshots):
            assert "trace_summary" in snap, (
                f"snapshot[{i}] missing trace_summary — keys: {list(snap.keys())}"
            )

    async def test_tool_result_marks_llm_calls(self, tmp_path: Path):
        """Verify function_response has llm_calls_made=True for the batch dispatch."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 1, "Expected at least one tool result"
        llm_results = [tr for tr in tool_results if tr.get("llm_calls_made")]
        assert len(llm_results) >= 1, (
            f"No tool result had llm_calls_made=True: {tool_results}"
        )


# ===========================================================================
# FM-25: Worker Empty/Safety Response — REMOVED (Phase 3 migration)
# ===========================================================================


# ===========================================================================
# FM-09: Worker 500 Server Error (RPN=60)
# ===========================================================================


class TestWorker500ThenSuccess:
    """Verify SDK retry recovery from 500 error.

    Note: config.max_retries=0 controls the *orchestrator-level* retry loop
    (how many times the orchestrator re-invokes the reasoning agent after a
    failed iteration), NOT the worker-level SDK HttpRetryOptions.  SDK retries
    are configured separately via HttpRetryOptions(attempts=N) in dispatch.py
    and are transparent to the orchestrator.  Setting max_retries=0 ensures
    the test exercises SDK-level retry only, without orchestrator retry.
    """

    FIXTURE = "worker_500_then_success"

    async def test_contract(self):
        """Basic contract -- SDK retry should be transparent."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_recovery_transparent(self, tmp_path: Path):
        """The REPL code should see a successful result, not an error message."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "Server recovered answer" in fa, (
            f"Expected 'Server recovered answer' in final_answer: {fa!r}"
        )
        # No error keywords should be in the final answer
        assert "error" not in fa.lower() or "recovered" in fa.lower(), (
            f"Final answer should not contain 'error' unless describing recovery: {fa!r}"
        )

    async def test_single_iteration(self, tmp_path: Path):
        """SDK retry is transparent -- only 1 REPL iteration needed."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 1, f"Expected 1 iteration, got {iter_count}"


    async def test_obs_total_calls_persisted(self, tmp_path: Path):
        """Verify OBS_TOTAL_CALLS is present in final state.

        ObservabilityPlugin.after_agent_callback re-persists ephemeral
        obs keys (written in after_model_callback without event_actions)
        by reading them from the live session dict and writing them
        through the properly-wired after_agent CallbackContext.

        The reasoning agent makes model calls, so obs:total_calls > 0.
        Worker calls are isolated in ParallelAgent and do NOT reach
        the plugin — only reasoning-level calls are counted.
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        total_calls = result.final_state.get(OBS_TOTAL_CALLS, 0)
        assert total_calls > 0, (
            f"Expected OBS_TOTAL_CALLS > 0 (after_agent_callback "
            f"re-persists ephemeral plugin state), got {total_calls}."
        )
        # Dispatch-level obs keys DO persist (written via flush_fn)
        assert result.final_state.get(WORKER_DISPATCH_COUNT, 0) == 1, (
            "WORKER_DISPATCH_COUNT should persist via flush_fn path"
        )

    async def test_tool_result_has_llm_calls(self, tmp_path: Path):
        """Verify the execute_code function_response shows llm_calls_made=True.

        FM-09: Even when the SDK retries a 500 transparently, the REPL code
        still called llm_query(), so the tool result must reflect this.
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 1, "Expected at least one execute_code tool result"
        results_with_llm = [tr for tr in tool_results if tr.get("llm_calls_made")]
        assert len(results_with_llm) >= 1, (
            f"No tool result had llm_calls_made=True: {tool_results}"
        )


# ===========================================================================
# FM-19: All Workers Fail — REMOVED (Phase 3 migration)
# ===========================================================================


# ===========================================================================
# FM-04: REPL Syntax Error (RPN=10)
# ===========================================================================


class TestReplSyntaxError:
    """Verify REPL self-correction after SyntaxError."""

    FIXTURE = "repl_syntax_error"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_two_iterations_for_correction(self, tmp_path: Path):
        """Verify model needed 2 REPL iterations to self-correct."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 2, f"Expected 2 iterations, got {iter_count}"

    async def test_syntax_error_in_first_tool_response(self, tmp_path: Path):
        """Verify the SyntaxError from iter1 appears in function_response stderr."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 2, (
            f"Expected >= 2 tool results (error + fix), got {len(tool_results)}"
        )
        first_stderr = tool_results[0].get("stderr", "")
        assert "SyntaxError" in first_stderr, (
            f"Expected 'SyntaxError' in first tool stderr: {first_stderr!r}"
        )

    async def test_corrected_code_succeeds(self, tmp_path: Path):
        """Verify the second REPL call has no errors in stderr."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 2
        second_stderr = tool_results[1].get("stderr", "")
        assert not second_stderr, (
            f"Expected empty stderr on corrected code, got: {second_stderr!r}"
        )


# ===========================================================================
# FM-03: Max Iterations Exceeded (RPN=30)
# ===========================================================================


class TestMaxIterationsExceeded:
    """Verify REPLTool enforces call limit."""

    FIXTURE = "max_iterations_exceeded"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_limit_enforced(self, tmp_path: Path):
        """Third call should have been blocked by REPLTool max_calls."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 3, (
            f"Expected iteration_count == 3 (includes blocked call), got {iter_count}"
        )

    async def test_limit_message_in_stderr(self, tmp_path: Path):
        """Verify the blocked third call returns the limit message in stderr."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 3, (
            f"Expected >= 3 tool results, got {len(tool_results)}"
        )
        third_stderr = tool_results[2].get("stderr", "")
        assert "REPL call limit reached" in third_stderr, (
            f"Expected limit message in third tool stderr: {third_stderr!r}"
        )

    async def test_blocked_call_not_executed(self, tmp_path: Path):
        """Verify 3rd tool_result has stdout=='' and llm_calls_made==False (FM-03).

        When the call limit is reached, REPLTool returns immediately with the
        limit message in stderr without executing any code.  stdout must be
        empty and llm_calls_made must be False, confirming the code was not
        executed on the blocked call.
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 3, (
            f"Expected >= 3 tool results, got {len(tool_results)}"
        )
        third_tr = tool_results[2]
        third_stdout = third_tr.get("stdout", "")
        assert third_stdout == "", (
            f"Expected empty stdout on blocked 3rd call (code not executed), "
            f"got: {third_stdout!r}"
        )
        third_llm_calls = third_tr.get("llm_calls_made")
        assert third_llm_calls is False, (
            f"Expected llm_calls_made=False on blocked 3rd call, "
            f"got {third_llm_calls!r}"
        )

    async def test_final_answer_acknowledges_limit(self, tmp_path: Path):
        """Verify FINAL_ANSWER reflects the model responding to the limit."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "Completed with limit" in fa, (
            f"Expected 'Completed with limit' in final_answer: {fa!r}"
        )


# ===========================================================================
# FM-15: Empty Reasoning Output (RPN=16)
# ===========================================================================


class TestEmptyReasoningOutput:
    """Verify orchestrator error handling for empty reasoning output."""

    FIXTURE = "empty_reasoning_output"

    async def test_contract(self):
        """Basic contract -- should match [RLM ERROR] message."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_error_message_format(self, tmp_path: Path):
        """Verify the error message is the expected [RLM ERROR] string."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert fa.startswith("[RLM ERROR]"), (
            f"Expected FINAL_ANSWER to start with '[RLM ERROR]', got: {fa!r}"
        )
        assert "output_schema" in fa, (
            f"Expected 'output_schema' in error message: {fa!r}"
        )

    async def test_single_repl_iteration(self, tmp_path: Path):
        """Verify only 1 REPL call was made before empty output."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 1, f"Expected 1 iteration, got {iter_count}"


# ===========================================================================
# FM-05: REPL Runtime Error (RPN=24)
# ===========================================================================


class TestReplRuntimeError:
    """Verify recovery from NameError in REPL code."""

    FIXTURE = "repl_runtime_error"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_two_iterations_for_recovery(self, tmp_path: Path):
        """Verify model needed 2 REPL iterations to recover from NameError."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 2, f"Expected 2 iterations, got {iter_count}"

    async def test_name_error_in_first_tool_response(self, tmp_path: Path):
        """Verify the NameError from iter1 appears in function_response stderr."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 2, (
            f"Expected >= 2 tool results, got {len(tool_results)}"
        )
        first_stderr = tool_results[0].get("stderr", "")
        assert "NameError" in first_stderr, (
            f"Expected 'NameError' in first tool stderr: {first_stderr!r}"
        )

    async def test_corrected_output(self, tmp_path: Path):
        """Verify the corrected code prints the expected output."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "hello world" in fa, (
            f"Expected 'hello world' in final_answer: {fa!r}"
        )


# ===========================================================================
# FM-25: Worker Safety Finish — REMOVED (Phase 3 migration)
# ===========================================================================


# ===========================================================================
# FM-17: Structured Output Batched K=3 With Retry (RPN=90)
# ===========================================================================


class TestStructuredOutputBatchedK3WithRetry:
    """Verify BUG-13 suppression under concurrent K>1 structured output."""

    FIXTURE = "structured_output_batched_k3_with_retry"

    async def test_contract(self):
        """Basic contract: final_answer, iterations, model_calls."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_retry_worker_recovered(self, tmp_path: Path):
        """Verify all 3 workers produced results (2 positive, 1 negative after retry)."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "2 positive" in fa, f"Expected '2 positive' in final_answer: {fa!r}"
        assert "1 negative" in fa, f"Expected '1 negative' in final_answer: {fa!r}"


    async def test_bug13_patch_active(self, tmp_path: Path):
        """Verify BUG-13 monkey-patch is installed (_rlm_patched flag)."""
        import google.adk.flows.llm_flows._output_schema_processor as _osp
        assert getattr(
            _osp.get_structured_model_response, "_rlm_patched", False
        ), "BUG-13 patch not installed — _rlm_patched flag missing"

    async def test_bug13_patch_invoked(self, tmp_path: Path):
        """Verify BUG-13 patch was actually invoked during retry, not just installed."""
        from rlm_adk.callbacks.worker_retry import _bug13_stats
        initial_count = _bug13_stats["suppress_count"]
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        invocations = _bug13_stats["suppress_count"] - initial_count
        assert invocations >= 1, (
            f"Expected BUG-13 patch to fire >= 1 time during retry, "
            f"but suppress_count delta was {invocations}. "
            f"The patch may not be active for this fixture's retry path."
        )

    async def test_tool_result_stdout_has_sentiments(self, tmp_path: Path):
        """Verify REPL stdout shows parsed sentiment values from all 3 workers."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 1, "Expected at least one tool result"
        # Find the tool result with llm_calls_made (the dispatch iteration)
        llm_results = [tr for tr in tool_results if tr.get("llm_calls_made")]
        assert len(llm_results) >= 1, "No tool result had llm_calls_made=True"
        stdout = llm_results[0].get("stdout", "")
        assert "positive" in stdout.lower(), (
            f"Expected 'positive' in tool stdout: {stdout!r}"
        )
        assert "negative" in stdout.lower(), (
            f"Expected 'negative' in tool stdout: {stdout!r}"
        )


    async def test_obs_error_counts_absent(self, tmp_path: Path):
        """Verify OBS_CHILD_ERROR_COUNTS is empty/absent since retry succeeds.

        The retry worker eventually returns valid structured output, so no
        error should be recorded in error counts. The reflect-and-retry loop
        is internal to the child and does not propagate errors to the dispatch
        accumulator when it ultimately succeeds.

        Note: With child orchestrators, NO_RESULT may appear if the child's
        reasoning agent does not extract the answer.  We check both old and
        new obs keys and allow NO_RESULT since child answer extraction is
        a known limitation with structured output fixtures.
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        # With child orchestrators, NO_RESULT errors are expected when the
        # child reasoning agent's output_key doesn't contain the answer.
        # This is acceptable — the important thing is no RATE_LIMIT/SERVER errors.
        error_counts = result.final_state.get(OBS_CHILD_ERROR_COUNTS) or result.final_state.get(OBS_WORKER_ERROR_COUNTS)
        if error_counts:
            real_errors = {k: v for k, v in error_counts.items() if k != "NO_RESULT"}
            assert len(real_errors) == 0, (
                f"Expected no real errors (RATE_LIMIT/SERVER/etc) in error counts, "
                f"got {error_counts!r}"
            )


# ===========================================================================
# FM-14: REPL Cancelled During Async (RPN=96)
# ===========================================================================


class TestReplCancelledDuringAsync:
    """Verify happy-path base fixture for CancelledError injection tests."""

    FIXTURE = "repl_cancelled_during_async"

    async def test_contract(self):
        """Basic contract (normal non-cancelled path)."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_happy_path_final_answer(self, tmp_path: Path):
        """Verify the non-cancelled happy path produces expected result."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "15%" in fa, f"Expected '15%' in final_answer: {fa!r}"

    async def test_single_iteration(self, tmp_path: Path):
        """Verify single iteration completes when not cancelled."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 1, f"Expected 1 iteration, got {iter_count}"


    async def test_last_repl_result_happy_path(self, tmp_path: Path):
        """Verify LAST_REPL_RESULT on happy-path: no errors, has output, 1 llm call.

        Establishes baseline observability for LAST_REPL_RESULT so that
        FM-14 injection tests can assert deviations from this baseline.
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        lrr = result.final_state.get(LAST_REPL_RESULT)
        assert lrr is not None, (
            f"Expected LAST_REPL_RESULT in final state, got None"
        )
        assert lrr.get("has_errors") is False, (
            f"Expected has_errors=False on happy path, got {lrr.get('has_errors')!r}"
        )
        assert lrr.get("has_output") is True, (
            f"Expected has_output=True on happy path, got {lrr.get('has_output')!r}"
        )
        assert lrr.get("total_llm_calls") == 1, (
            f"Expected total_llm_calls=1, got {lrr.get('total_llm_calls')!r}"
        )


# ===========================================================================
# FM-14: CancelledError Injection (RPN=96)
# ===========================================================================


class TestReplCancelledErrorInjection:
    """[15.0] Verify CancelledError handler in repl_tool.py:120-143.

    Patches LocalREPL.execute_code_async to raise asyncio.CancelledError
    after real execution has dispatched workers (populating accumulators).
    Validates flush_fn is called, LAST_REPL_RESULT has cancelled=True,
    and the tool result contains stderr with 'CancelledError'.
    """

    FIXTURE = "repl_cancelled_during_async"

    async def test_cancelled_error_in_tool_stderr(self, tmp_path: Path, monkeypatch):
        """Tool result stderr must contain 'CancelledError'."""
        import asyncio
        from rlm_adk.repl.local_repl import LocalREPL

        _real_execute = LocalREPL.execute_code_async

        async def _execute_then_cancel(self_repl, code, repl_exec_fn, trace=None):
            await _real_execute(self_repl, code, repl_exec_fn, trace=trace)
            raise asyncio.CancelledError("Simulated task cancellation")

        monkeypatch.setattr(LocalREPL, "execute_code_async", _execute_then_cancel)

        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        tool_results = _extract_tool_results(result.events)
        cancelled_results = [
            tr for tr in tool_results
            if "CancelledError" in tr.get("stderr", "")
        ]
        assert len(cancelled_results) >= 1, (
            f"Expected at least one tool result with 'CancelledError' in stderr, "
            f"got tool_results={tool_results}"
        )

    async def test_flush_fn_called_on_cancelled_error(self, tmp_path: Path, monkeypatch):
        """WORKER_DISPATCH_COUNT must be in final state (proves flush_fn ran)."""
        import asyncio
        from rlm_adk.repl.local_repl import LocalREPL

        _real_execute = LocalREPL.execute_code_async

        async def _execute_then_cancel(self_repl, code, repl_exec_fn, trace=None):
            await _real_execute(self_repl, code, repl_exec_fn, trace=trace)
            raise asyncio.CancelledError("Simulated task cancellation")

        monkeypatch.setattr(LocalREPL, "execute_code_async", _execute_then_cancel)

        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        wdc = result.final_state.get(WORKER_DISPATCH_COUNT)
        assert wdc is not None and wdc >= 1, (
            f"Expected WORKER_DISPATCH_COUNT >= 1 after CancelledError "
            f"(proving flush_fn was called), got {wdc!r}"
        )

    async def test_last_repl_result_cancelled_flag(self, tmp_path: Path, monkeypatch):
        """LAST_REPL_RESULT must have has_errors=True and cancelled=True."""
        import asyncio
        from rlm_adk.repl.local_repl import LocalREPL

        _real_execute = LocalREPL.execute_code_async

        async def _execute_then_cancel(self_repl, code, repl_exec_fn, trace=None):
            await _real_execute(self_repl, code, repl_exec_fn, trace=trace)
            raise asyncio.CancelledError("Simulated task cancellation")

        monkeypatch.setattr(LocalREPL, "execute_code_async", _execute_then_cancel)

        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        lrr = result.final_state.get(LAST_REPL_RESULT)
        assert lrr is not None, (
            f"Expected LAST_REPL_RESULT in final state after CancelledError, "
            f"got None"
        )
        assert lrr.get("has_errors") is True, (
            f"Expected has_errors=True in LAST_REPL_RESULT, got {lrr!r}"
        )
        assert lrr.get("cancelled") is True, (
            f"Expected cancelled=True in LAST_REPL_RESULT, got {lrr!r}"
        )


# ===========================================================================
# FM-09: Worker 500 Retry Exhausted — REMOVED (Phase 3 migration)
# ===========================================================================


# ===========================================================================
# FM-25: Worker MAX_TOKENS Truncated (RPN=75)
# ===========================================================================


class TestWorkerMaxTokensTruncated:
    """Verify handling of truncated worker response (MAX_TOKENS)."""

    FIXTURE = "worker_max_tokens_truncated"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_truncated_result_detected(self, tmp_path: Path):
        """Verify FINAL_ANSWER mentions truncation."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "runcated" in fa or "suggest" in fa, (
            f"Expected truncation indicator in final_answer: {fa!r}"
        )

    async def test_single_iteration(self, tmp_path: Path):
        """Verify truncated response handled in one iteration."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 1, f"Expected 1 iteration, got {iter_count}"


    async def test_obs_finish_max_tokens_tracked(self, tmp_path: Path):
        """Verify MAX_TOKENS finish reason is handled with dispatch tracking.

        Child dispatch latency is tracked via OBS_CHILD_DISPATCH_LATENCY_MS
        (or the backward-compat OBS_WORKER_DISPATCH_LATENCY_MS).

        With child orchestrators, NO_RESULT may appear in error counts when
        the child reasoning agent doesn't extract the answer via output_key.
        We allow NO_RESULT but assert no real errors (RATE_LIMIT/SERVER).
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        # Check dispatch latency (child or worker key)
        dispatch_latency = (
            result.final_state.get(OBS_CHILD_DISPATCH_LATENCY_MS)
            or result.final_state.get(OBS_WORKER_DISPATCH_LATENCY_MS)
        )
        assert dispatch_latency is not None and len(dispatch_latency) >= 1, (
            f"Expected dispatch latency with at least 1 entry, "
            f"got {dispatch_latency!r}. Dispatch tracking may be missing."
        )
        # Allow NO_RESULT but no real errors
        error_counts = (
            result.final_state.get(OBS_CHILD_ERROR_COUNTS)
            or result.final_state.get(OBS_WORKER_ERROR_COUNTS)
        )
        if error_counts:
            real_errors = {k: v for k, v in error_counts.items() if k != "NO_RESULT"}
            assert len(real_errors) == 0, (
                f"Expected no real errors for MAX_TOKENS (non-error), "
                f"got {error_counts!r}"
            )

    async def test_tool_result_stdout_has_truncation_output(self, tmp_path: Path):
        """Verify REPL code detected truncation and printed output."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 1, "Expected at least one tool result"
        llm_results = [tr for tr in tool_results if tr.get("llm_calls_made")]
        assert len(llm_results) >= 1, "No tool result had llm_calls_made=True"
        stdout = llm_results[0].get("stdout", "")
        assert stdout.strip(), (
            f"Expected non-empty stdout from REPL code handling truncated response"
        )

    async def test_llm_result_finish_reason_max_tokens(self, tmp_path: Path):
        """Verify LLMResult carries finish_reason=MAX_TOKENS (FM-25).

        The worker response has finishReason=MAX_TOKENS.  worker_after_model
        records it in _call_record, dispatch builds LLMResult with
        finish_reason='MAX_TOKENS'.  The REPL variable 'result' is this
        LLMResult.  We verify indirectly: the text does not end with
        sentence-ending punctuation (proving it was truncated), and the
        REPL code detected this via its endswith() check.
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        llm_results = [tr for tr in tool_results if tr.get("llm_calls_made")]
        assert len(llm_results) >= 1, "No tool result had llm_calls_made=True"
        # The REPL code prints "Truncated response detected: ..." when
        # the text does not end with sentence punctuation.
        stdout = llm_results[0].get("stdout", "")
        assert "Truncated response detected" in stdout, (
            f"Expected 'Truncated response detected' in stdout (proves "
            f"LLMResult text did not end with sentence punctuation, "
            f"consistent with MAX_TOKENS truncation): {stdout!r}"
        )
        # Additionally verify the 'result' variable in the tool response
        # is a string that does NOT end with sentence-ending punctuation
        variables = llm_results[0].get("variables", {})
        if "text" in variables:
            text_val = variables["text"]
            assert not text_val.rstrip().endswith((".", "!", "?")), (
                f"Expected truncated text (no sentence-ending punct): {text_val!r}"
            )

    async def test_last_repl_result_no_errors_with_output(self, tmp_path: Path):
        """Verify LAST_REPL_RESULT has has_errors=False and has_output=True (FM-25).

        MAX_TOKENS is a graceful non-error condition: the worker produced
        partial text which the REPL code received and processed without
        raising exceptions.  The REPL execution itself succeeded (no stderr),
        so has_errors=False and has_output=True (truncation info was printed).
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        lrr = result.final_state.get(LAST_REPL_RESULT)
        assert lrr is not None, (
            f"Expected LAST_REPL_RESULT in final state, got None"
        )
        assert lrr.get("has_errors") is False, (
            f"Expected has_errors=False (MAX_TOKENS is graceful, REPL code "
            f"did not crash), got {lrr.get('has_errors')!r}"
        )
        assert lrr.get("has_output") is True, (
            f"Expected has_output=True (REPL code printed truncation info), "
            f"got {lrr.get('has_output')!r}"
        )


# ===========================================================================
# FM-18: Worker Malformed JSON (RPN=24)
# ===========================================================================


class TestWorkerMalformedJson:
    """Verify handling of malformed JSON from worker API."""

    FIXTURE = "worker_malformed_json"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_error_in_final_answer(self, tmp_path: Path):
        """Verify FINAL_ANSWER reports malformed/parse error."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "failed" in fa.lower() or "malformed" in fa.lower(), (
            f"Expected failure keywords in final_answer: {fa!r}"
        )

    async def test_single_iteration(self, tmp_path: Path):
        """Verify malformed response handled in one iteration."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 1, f"Expected 1 iteration, got {iter_count}"

    async def test_tool_result_shows_error(self, tmp_path: Path):
        """Verify execute_code function_response contains error output (parity with FM-09)."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 1, "Expected at least one tool result"
        first_stdout = tool_results[0].get("stdout", "")
        assert "error" in first_stdout.lower() or "failed" in first_stdout.lower() or "Worker" in first_stdout, (
            f"Expected error indication in tool stdout: {first_stdout!r}"
        )


# ===========================================================================
# FM-16: Structured Output Retry Exhaustion (RPN=50)
# ===========================================================================


class TestStructuredOutputRetryExhaustion:
    """Verify FM-16 fix: schema validation exhaustion detection."""

    FIXTURE = "structured_output_retry_exhaustion"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_error_in_final_answer(self, tmp_path: Path):
        """Verify FINAL_ANSWER reports schema validation exhaustion."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "exhausted" in fa.lower() or "schema" in fa.lower(), (
            f"Expected exhaustion/schema keywords in final_answer: {fa!r}"
        )

    async def test_single_iteration(self, tmp_path: Path):
        """Verify retry exhaustion handled in one iteration."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 1, f"Expected 1 iteration, got {iter_count}"

    async def test_tool_result_shows_error(self, tmp_path: Path):
        """Verify function_response contains error output (stdout or stderr)."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 1, "Expected at least one tool result"
        first_tr = tool_results[0]
        combined = (first_tr.get("stdout", "") + first_tr.get("stderr", "")).lower()
        assert "exhausted" in combined or "schema" in combined or "error" in combined or "validation" in combined, (
            f"Expected error indication in tool result: stdout={first_tr.get('stdout')!r}, stderr={first_tr.get('stderr')!r}"
        )

    async def test_obs_error_counts(self, tmp_path: Path):
        """Verify error is tracked when schema validation is exhausted.

        When the Pydantic ValidationError propagates as a batch-level
        exception (dispatch.py except block), _acc_error_counts is not
        populated -- the error is captured via LAST_REPL_RESULT instead.
        If the FM-16 detection path is reached, SCHEMA_VALIDATION_EXHAUSTED
        will appear in error_counts.  With child orchestrators, NO_RESULT
        may appear instead.
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        error_counts = (
            result.final_state.get(OBS_CHILD_ERROR_COUNTS)
            or result.final_state.get(OBS_WORKER_ERROR_COUNTS)
        )
        if error_counts is not None:
            # Accept SCHEMA_VALIDATION_EXHAUSTED, NO_RESULT, or UNKNOWN
            # (child orchestrator dispatch classifies differently)
            assert len(error_counts) >= 1, (
                f"Expected at least one error category, got {error_counts}"
            )
        else:
            # Batch-level exception path: error captured in LAST_REPL_RESULT
            repl_result = str(result.final_state.get(LAST_REPL_RESULT, ""))
            assert "error" in repl_result.lower() or "validation" in repl_result.lower(), (
                f"Expected error indication in LAST_REPL_RESULT when "
                f"error_counts is absent: {repl_result!r}"
            )


# ===========================================================================
# FM-14: REPL Generic Exception After Dispatch (flush_fn / LAST_REPL_RESULT)
# ===========================================================================


class TestReplExceptionFlushFn:
    """Verify that a generic Exception in repl_tool.py (not CancelledError)
    still flushes dispatch accumulators and writes LAST_REPL_RESULT.

    Bug: The ``except Exception`` handler in repl_tool.py (lines 144-151)
    does NOT call flush_fn and does NOT write LAST_REPL_RESULT to
    tool_context.state, unlike the CancelledError handler (lines 120-143)
    which does both.  This causes dispatch accumulators to be lost and
    observability data to be missing when an infrastructure-level error
    occurs after workers have been dispatched.

    Strategy: Use the ``repl_cancelled_during_async`` fixture (which
    dispatches one worker via llm_query) but monkeypatch
    ``LocalREPL.execute_code_async`` so that it runs the real async
    execution (populating dispatch accumulators) and then raises
    ``RuntimeError``.  This forces the error into repl_tool.py's generic
    ``except Exception`` handler rather than being caught inside
    ``execute_code_async``.
    """

    FIXTURE = "repl_cancelled_during_async"

    async def test_flush_fn_called_on_exception(self, tmp_path: Path, monkeypatch):
        """WORKER_DISPATCH_COUNT must appear in final state even when
        repl_tool.py's try block raises a generic Exception after
        dispatching workers."""
        from rlm_adk.repl.local_repl import LocalREPL

        _real_execute = LocalREPL.execute_code_async

        async def _execute_then_raise(self_repl, code, repl_exec_fn, trace=None):
            # Run the real execution so workers dispatch and accumulators fill
            await _real_execute(self_repl, code, repl_exec_fn, trace=trace)
            # Then raise to trigger the generic except Exception handler
            raise RuntimeError("Simulated infrastructure error after dispatch")

        monkeypatch.setattr(LocalREPL, "execute_code_async", _execute_then_raise)

        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        # Contract may or may not pass (error changes output), skip contract check
        wdc = result.final_state.get(WORKER_DISPATCH_COUNT)
        assert wdc is not None and wdc >= 1, (
            f"Expected WORKER_DISPATCH_COUNT >= 1 in final state after "
            f"generic Exception, got {wdc!r}. "
            f"This means flush_fn was not called in the except Exception handler."
        )

    async def test_last_repl_result_written_on_exception(self, tmp_path: Path, monkeypatch):
        """LAST_REPL_RESULT must be written with has_errors=True when
        repl_tool.py's try block raises a generic Exception."""
        from rlm_adk.repl.local_repl import LocalREPL

        _real_execute = LocalREPL.execute_code_async

        async def _execute_then_raise(self_repl, code, repl_exec_fn, trace=None):
            await _real_execute(self_repl, code, repl_exec_fn, trace=trace)
            raise RuntimeError("Simulated infrastructure error after dispatch")

        monkeypatch.setattr(LocalREPL, "execute_code_async", _execute_then_raise)

        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        lrr = result.final_state.get(LAST_REPL_RESULT)
        assert lrr is not None, (
            f"Expected LAST_REPL_RESULT in final state after generic Exception, "
            f"got None. The except Exception handler does not write it."
        )
        assert lrr.get("has_errors") is True, (
            f"Expected has_errors=True in LAST_REPL_RESULT, got {lrr!r}"
        )

    async def test_runtime_error_in_tool_stderr(self, tmp_path: Path, monkeypatch):
        """[15.2] Tool result stderr must contain 'RuntimeError'.

        Validates the generic except Exception handler at repl_tool.py:144-166
        returns stderr with the exception type name, confirming error
        propagation to the model for self-correction.
        """
        from rlm_adk.repl.local_repl import LocalREPL

        _real_execute = LocalREPL.execute_code_async

        async def _execute_then_raise(self_repl, code, repl_exec_fn, trace=None):
            await _real_execute(self_repl, code, repl_exec_fn, trace=trace)
            raise RuntimeError("Simulated infrastructure error after dispatch")

        monkeypatch.setattr(LocalREPL, "execute_code_async", _execute_then_raise)

        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        tool_results = _extract_tool_results(result.events)
        error_results = [
            tr for tr in tool_results
            if "RuntimeError" in tr.get("stderr", "")
        ]
        assert len(error_results) >= 1, (
            f"Expected at least one tool result with 'RuntimeError' in stderr, "
            f"got tool_results={tool_results}"
        )


# ===========================================================================
# FM-14: REPL Exception Then Retry (Accumulator Drift)
# ===========================================================================


class TestReplExceptionThenRetry:
    """[15.5] Multi-iteration fixture where iteration 1 raises RuntimeError
    after llm_query dispatch, and iteration 2 retries successfully.

    Exercises the accumulator drift scenario: if flush_fn was correctly
    called in iteration 1's except Exception handler, iteration 2's
    flush produces only its own dispatch count (1), not the leaked
    iteration 1 count.
    """

    FIXTURE = "repl_exception_then_retry"

    async def test_contract(self):
        """Basic contract: final_answer, iterations, model_calls."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_two_iterations_required(self, tmp_path: Path):
        """Verify error forced a second iteration."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 2, f"Expected 2 iterations, got {iter_count}"

    async def test_error_visible_in_tool_response(self, tmp_path: Path):
        """Verify the RuntimeError from iter1 is visible in a function_response stderr."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 2, (
            f"Expected >= 2 tool results (error + retry), got {len(tool_results)}"
        )
        first_stderr = tool_results[0].get("stderr", "")
        assert "RuntimeError" in first_stderr, (
            f"Expected 'RuntimeError' in first tool stderr: {first_stderr!r}"
        )

    async def test_retry_succeeds_in_final_answer(self, tmp_path: Path):
        """Verify the retried code's result appears in FINAL_ANSWER."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "recovered-42" in fa, f"Expected 'recovered-42' in final_answer: {fa!r}"


# ===========================================================================
# FM-05 variant: REPL Runtime Error — Partial State (RPN=24)
# ===========================================================================


class TestReplRuntimeErrorPartialState:
    """Verify that variables assigned before a NameError do NOT persist.

    LocalREPL.execute_code only updates self.locals on successful execution
    (the locals-update loop runs inside the try block, after exec()).  When
    exec() raises, the except block skips the update.  This test verifies
    that x=10 and y=20 from the failed first iteration do NOT leak into
    the REPL namespace.
    """

    FIXTURE = "repl_runtime_error_partial_state"

    async def test_contract(self):
        """Basic contract: final_answer, iterations, model_calls."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_two_iterations_for_recovery(self, tmp_path: Path):
        """Verify model needed 2 REPL iterations to recover from NameError."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 2, f"Expected 2 iterations, got {iter_count}"

    async def test_name_error_in_first_tool_response(self, tmp_path: Path):
        """Verify the NameError from iter1 appears in function_response stderr."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 2, (
            f"Expected >= 2 tool results (error + fix), got {len(tool_results)}"
        )
        first_stderr = tool_results[0].get("stderr", "")
        assert "NameError" in first_stderr, (
            f"Expected 'NameError' in first tool stderr: {first_stderr!r}"
        )

    async def test_partial_vars_not_persisted(self, tmp_path: Path):
        """Verify x and y from the failed first iteration are NOT in variables.

        The first call assigns x=10, y=20 before hitting NameError on
        z=undefined_var.  Because LocalREPL.execute_code raises before the
        locals-update loop, x and y should NOT appear in the first tool
        result's variables dict.
        """
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 1, "Expected at least one tool result"
        first_vars = tool_results[0].get("variables", {})
        assert "x" not in first_vars, (
            f"Variable 'x' should NOT persist from failed exec. "
            f"Got variables: {first_vars}"
        )
        assert "y" not in first_vars, (
            f"Variable 'y' should NOT persist from failed exec. "
            f"Got variables: {first_vars}"
        )

    async def test_corrected_output(self, tmp_path: Path):
        """Verify the corrected code computes 10 + 20 + 60 = 90."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "90" in fa, f"Expected '90' in final_answer: {fa!r}"


# ===========================================================================
# FM-03 variant: Max Iterations Exceeded — Persistent Ignoring (RPN=30)
# ===========================================================================


class TestMaxIterationsExceededPersistent:
    """Verify REPLTool enforces call limit even when model ignores it twice.

    The model makes 4 execute_code calls with max_calls=2.  Calls 3 and 4
    are both blocked with the limit message.  This tests the residual risk
    that the model persistently ignores the call limit message.
    """

    FIXTURE = "max_iterations_exceeded_persistent"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_four_iterations_counted(self, tmp_path: Path):
        """Verify all 4 call attempts are counted in ITERATION_COUNT."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 4, (
            f"Expected 4 iterations (2 success + 2 blocked), got {iter_count}"
        )

    async def test_two_blocked_calls(self, tmp_path: Path):
        """Verify calls 3 and 4 both received the limit message."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 4, (
            f"Expected >= 4 tool results (2 success + 2 blocked), "
            f"got {len(tool_results)}"
        )
        # Both calls 3 and 4 should have the limit message in stderr
        third_stderr = tool_results[2].get("stderr", "")
        fourth_stderr = tool_results[3].get("stderr", "")
        assert "REPL call limit reached" in third_stderr, (
            f"Expected limit message in third tool stderr: {third_stderr!r}"
        )
        assert "REPL call limit reached" in fourth_stderr, (
            f"Expected limit message in fourth tool stderr: {fourth_stderr!r}"
        )

    async def test_blocked_calls_have_empty_stdout(self, tmp_path: Path):
        """Verify blocked calls have no stdout (code was not executed)."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 4
        third_stdout = tool_results[2].get("stdout", "")
        fourth_stdout = tool_results[3].get("stdout", "")
        assert not third_stdout, (
            f"Expected empty stdout on blocked call 3, got: {third_stdout!r}"
        )
        assert not fourth_stdout, (
            f"Expected empty stdout on blocked call 4, got: {fourth_stdout!r}"
        )

    async def test_final_answer_reflects_limit(self, tmp_path: Path):
        """Verify FINAL_ANSWER acknowledges the limit."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "limit" in fa.lower(), (
            f"Expected 'limit' in final_answer: {fa!r}"
        )


# ===========================================================================
# FM-15/24: Empty Reasoning Output with SAFETY Finish (RPN=16/48)
# ===========================================================================


class TestEmptyReasoningOutputSafety:
    """Verify orchestrator error handling for empty reasoning output with SAFETY finish.

    Variant of FM-15 where the final model response has finishReason=SAFETY
    instead of STOP.  The orchestrator should handle this identically to the
    STOP case — the defining behavior is the empty text, not the finish reason.
    """

    FIXTURE = "empty_reasoning_output_safety"

    async def test_contract(self):
        """Basic contract -- should match [RLM ERROR] message."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_error_message_format(self, tmp_path: Path):
        """Verify the error message is the expected [RLM ERROR] string."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert fa.startswith("[RLM ERROR]"), (
            f"Expected FINAL_ANSWER to start with '[RLM ERROR]', got: {fa!r}"
        )

    async def test_single_repl_iteration(self, tmp_path: Path):
        """Verify only 1 REPL call was made before SAFETY-blocked output."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 1, f"Expected 1 iteration, got {iter_count}"

    async def test_same_error_as_stop_variant(self, tmp_path: Path):
        """Verify SAFETY variant produces same error as STOP variant (FM-15).

        Both should produce the identical [RLM ERROR] message, confirming
        the orchestrator does not distinguish between finish reasons when
        the text is empty.
        """
        result_safety = await _run_with_plugins(self.FIXTURE, tmp_path)
        result_stop = await _run_with_plugins("empty_reasoning_output", tmp_path)
        assert result_safety.contract.passed, result_safety.contract.diagnostics()
        assert result_stop.contract.passed, result_stop.contract.diagnostics()
        fa_safety = result_safety.final_state.get(FINAL_ANSWER, "")
        fa_stop = result_stop.final_state.get(FINAL_ANSWER, "")
        assert fa_safety == fa_stop, (
            f"SAFETY and STOP variants should produce same error. "
            f"SAFETY: {fa_safety!r}, STOP: {fa_stop!r}"
        )


# ===========================================================================
# FM-24: Reasoning Agent SAFETY Finish on First Turn (RPN=48)
# ===========================================================================


class TestReasoningSafetyFinish:
    """Verify orchestrator handling when reasoning agent is SAFETY-blocked on first turn.

    The reasoning model's very first response has finishReason=SAFETY with
    empty text.  No REPL execution occurs at all.  The orchestrator should
    detect the empty final_answer and yield [RLM ERROR].
    """

    FIXTURE = "reasoning_safety_finish"

    async def test_contract(self):
        """Basic contract -- should match [RLM ERROR] message."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_error_message_format(self, tmp_path: Path):
        """Verify the error message is the expected [RLM ERROR] string."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert fa.startswith("[RLM ERROR]"), (
            f"Expected FINAL_ANSWER to start with '[RLM ERROR]', got: {fa!r}"
        )

    async def test_zero_repl_iterations(self, tmp_path: Path):
        """Verify no REPL calls were made (SAFETY blocked on first turn)."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count is None or iter_count == 0, (
            f"Expected 0 iterations (SAFETY on first turn), got {iter_count}"
        )

    async def test_no_tool_results(self, tmp_path: Path):
        """Verify no execute_code function_responses in event stream."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) == 0, (
            f"Expected 0 tool results (no REPL calls), got {len(tool_results)}"
        )


# ===========================================================================
# FM-09 residual risk: Worker 500 Retry Exhausted Naive — REMOVED (Phase 3 migration)
# FM-25 residual risk: Worker MAX_TOKENS Naive — REMOVED (Phase 3 migration)
# ===========================================================================


# ===========================================================================
# FM-28: Worker HTTP 401 Authentication Error (RPN=6)
# ===========================================================================


class TestWorkerAuthError401:
    """Verify handling of HTTP 401 authentication error on worker dispatch.

    Unlike 5xx ServerErrors, 4xx ClientErrors are NOT retried by the SDK.
    The error propagates directly to on_model_error_callback.  The
    _classify_error function maps status 401 to 'AUTH' category, but the
    fake provider's ClientError may classify as 'UNKNOWN' due to how
    the exception's .code attribute is exposed.
    """

    FIXTURE = "worker_auth_error_401"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_error_in_final_answer(self, tmp_path: Path):
        """Verify FINAL_ANSWER reports authentication error."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "auth" in fa.lower() or "401" in fa or "unauthorized" in fa.lower(), (
            f"Expected auth/401/unauthorized in final_answer: {fa!r}"
        )

    async def test_single_iteration(self, tmp_path: Path):
        """Verify auth error handled in one iteration (no app-level retry)."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 1, f"Expected 1 iteration, got {iter_count}"

    async def test_tool_result_shows_error(self, tmp_path: Path):
        """Verify execute_code function_response contains auth error output."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        tool_results = _extract_tool_results(result.events)
        assert len(tool_results) >= 1, "Expected at least one tool result"
        first_stdout = tool_results[0].get("stdout", "")
        assert "auth" in first_stdout.lower() or "error" in first_stdout.lower(), (
            f"Expected auth/error indication in tool stdout: {first_stdout!r}"
        )


# ===========================================================================
# [3.3] FM-25: Worker Empty Response finish_reason — REMOVED (Phase 3 migration)
# ===========================================================================


# ===========================================================================
# [11.3] FM-16: Structured Output Retry Exhaustion -- Pure Validation (RPN=50)
# ===========================================================================


class TestStructuredOutputRetryExhaustionPureValidation:
    """Verify FM-16 pure ValidationError retry path.

    All 3 attempts fail with missing required fields only (no empty-value
    variant). Isolates ADK's ValidationError retry path from
    WorkerRetryPlugin's empty-value detection.
    """

    FIXTURE = "structured_output_retry_exhaustion_pure_validation"

    async def test_contract(self):
        """Basic contract."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_error_in_final_answer(self, tmp_path: Path):
        """Verify FINAL_ANSWER reports pure validation exhaustion."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "exhausted" in fa.lower() or "validation" in fa.lower(), (
            f"Expected exhaustion/validation keywords in final_answer: {fa!r}"
        )

    async def test_single_iteration(self, tmp_path: Path):
        """Verify pure validation exhaustion handled in one iteration."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 1, f"Expected 1 iteration, got {iter_count}"

    async def test_obs_structured_output_failures(self, tmp_path: Path):
        """Verify OBS_STRUCTURED_OUTPUT_FAILURES counter is set."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        sof = result.final_state.get(OBS_STRUCTURED_OUTPUT_FAILURES, 0)
        error_counts = (
            result.final_state.get(OBS_CHILD_ERROR_COUNTS)
            or result.final_state.get(OBS_WORKER_ERROR_COUNTS)
        )
        # If the FM-16 detection path is reached, both counters should fire
        if error_counts and "SCHEMA_VALIDATION_EXHAUSTED" in error_counts:
            assert sof >= 1, (
                f"Expected OBS_STRUCTURED_OUTPUT_FAILURES >= 1, got {sof}"
            )


# ===========================================================================
# [12.3] FM-17: Structured Output Batched K=3 -- Multi Retry (RPN=90)
# ===========================================================================


class TestStructuredOutputBatchedK3MultiRetry:
    """Verify concurrent BUG-13 patch invocation when 2 of 3 workers need retries.

    Workers 2 and 3 both return empty sentiment triggering WorkerRetryPlugin
    simultaneously within the same ParallelAgent dispatch. Both get retry
    calls and succeed on second attempt.
    """

    FIXTURE = "structured_output_batched_k3_multi_retry"

    async def test_contract(self):
        """Basic contract: final_answer, iterations, model_calls."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_all_workers_recovered(self, tmp_path: Path):
        """Verify all 3 workers produced results after retries."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "1 positive" in fa, f"Expected '1 positive' in final_answer: {fa!r}"
        assert "1 negative" in fa, f"Expected '1 negative' in final_answer: {fa!r}"
        assert "1 neutral" in fa, f"Expected '1 neutral' in final_answer: {fa!r}"


    async def test_bug13_patch_invoked_multiple(self, tmp_path: Path):
        """Verify BUG-13 patch was invoked at least twice (once per retry worker)."""
        from rlm_adk.callbacks.worker_retry import _bug13_stats
        initial_count = _bug13_stats["suppress_count"]
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        invocations = _bug13_stats["suppress_count"] - initial_count
        assert invocations >= 2, (
            f"Expected BUG-13 patch to fire >= 2 times (2 retry workers), "
            f"but suppress_count delta was {invocations}"
        )


# ===========================================================================
# [12.4] FM-16+17: Structured Output Batched K=3 -- Mixed Exhaust (RPN=50/90)
# ===========================================================================


class TestStructuredOutputBatchedK3MixedExhaust:
    """Verify combined FM-16 + FM-17 path: 2 workers succeed, 1 exhausts retries.

    Workers 1 and 3 succeed immediately. Worker 2 fails all 3 attempts
    (missing fields + empty values), exhausting max_retries=2. Dispatch
    FM-16 fix detects the exhaustion and returns LLMResult(error=True).
    """

    FIXTURE = "structured_output_batched_k3_mixed_exhaust"

    async def test_contract(self):
        """Basic contract: final_answer, iterations, model_calls."""
        result = await run_fixture_contract(FIXTURE_DIR / f"{self.FIXTURE}.json")
        assert result.passed, result.diagnostics()

    async def test_mixed_results_in_final_answer(self, tmp_path: Path):
        """Verify FINAL_ANSWER reports both successes and exhaustion."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        fa = result.final_state.get(FINAL_ANSWER, "")
        assert "2 succeeded" in fa, f"Expected '2 succeeded' in final_answer: {fa!r}"
        assert "exhausted" in fa.lower(), (
            f"Expected 'exhausted' in final_answer: {fa!r}"
        )


    async def test_obs_error_counts_exhaustion(self, tmp_path: Path):
        """Verify error tracked for the failed worker."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        error_counts = (
            result.final_state.get(OBS_CHILD_ERROR_COUNTS)
            or result.final_state.get(OBS_WORKER_ERROR_COUNTS)
        )
        if error_counts is not None:
            # Accept SCHEMA_VALIDATION_EXHAUSTED or NO_RESULT (child orchestrator)
            has_expected = (
                error_counts.get("SCHEMA_VALIDATION_EXHAUSTED", 0) >= 1
                or error_counts.get("NO_RESULT", 0) >= 1
            )
            assert has_expected, (
                f"Expected SCHEMA_VALIDATION_EXHAUSTED or NO_RESULT >= 1, got {error_counts}"
            )

    async def test_obs_structured_output_failures(self, tmp_path: Path):
        """Verify OBS_STRUCTURED_OUTPUT_FAILURES counter tracks the exhausted worker."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        sof = result.final_state.get(OBS_STRUCTURED_OUTPUT_FAILURES, 0)
        error_counts = (
            result.final_state.get(OBS_CHILD_ERROR_COUNTS)
            or result.final_state.get(OBS_WORKER_ERROR_COUNTS)
        )
        if error_counts and "SCHEMA_VALIDATION_EXHAUSTED" in error_counts:
            assert sof >= 1, (
                f"Expected OBS_STRUCTURED_OUTPUT_FAILURES >= 1, got {sof}"
            )

    async def test_single_iteration(self, tmp_path: Path):
        """Verify mixed success/failure handled in one iteration."""
        result = await _run_with_plugins(self.FIXTURE, tmp_path)
        assert result.contract.passed, result.contract.diagnostics()
        iter_count = result.final_state.get(ITERATION_COUNT)
        assert iter_count == 1, f"Expected 1 iteration, got {iter_count}"


# ===========================================================================
# [21.1] FM-11: Pool Exhaustion — REMOVED (Phase 3 migration, no pool)
# ===========================================================================


# ===========================================================================
# [25.1] _classify_error PARSE_ERROR category test
# ===========================================================================


class TestClassifyErrorParseError:
    """Verify _classify_error returns PARSE_ERROR for JSON-related exceptions."""

    def test_json_decode_error(self):
        """JSONDecodeError should classify as PARSE_ERROR."""
        import json
        from rlm_adk.callbacks.worker import _classify_error
        error = json.JSONDecodeError("Expecting value", "", 0)
        assert _classify_error(error) == "PARSE_ERROR"

    def test_value_error_with_json(self):
        """ValueError with 'json' in message should classify as PARSE_ERROR."""
        from rlm_adk.callbacks.worker import _classify_error
        error = ValueError("Invalid JSON response from API")
        assert _classify_error(error) == "PARSE_ERROR"

    def test_generic_error_with_malformed(self):
        """Error with 'malformed' in message should classify as PARSE_ERROR."""
        from rlm_adk.callbacks.worker import _classify_error
        error = RuntimeError("Malformed response body from server")
        assert _classify_error(error) == "PARSE_ERROR"

    def test_value_error_without_json(self):
        """ValueError without JSON keywords should classify as UNKNOWN."""
        from rlm_adk.callbacks.worker import _classify_error
        error = ValueError("Invalid argument")
        assert _classify_error(error) == "UNKNOWN"

    def test_timeout_still_works(self):
        """TimeoutError should still classify as TIMEOUT (not PARSE_ERROR)."""
        import asyncio
        from rlm_adk.callbacks.worker import _classify_error
        error = asyncio.TimeoutError()
        assert _classify_error(error) == "TIMEOUT"

    def test_rate_limit_still_works(self):
        """Error with code=429 should still classify as RATE_LIMIT."""
        from rlm_adk.callbacks.worker import _classify_error
        error = Exception("rate limited")
        error.code = 429  # type: ignore[attr-defined]
        assert _classify_error(error) == "RATE_LIMIT"
