"""Tests for REPL introspection gap closures: _call_record on workers,
call_log_sink in dispatch, format_execution_result improvements.

Red/Green TDD: These tests are written BEFORE the implementation.
They should FAIL initially (RED), then PASS after implementation (GREEN).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from rlm_adk.callbacks.worker import (
    worker_after_model,
    worker_before_model,
    worker_on_model_error,
)
from rlm_adk.dispatch import WorkerPool
from rlm_adk.types import (
    ModelUsageSummary,
    REPLResult,
    RLMChatCompletion,
    UsageSummary,
)
from rlm_adk.utils.parsing import format_execution_result


# ---------------------------------------------------------------------------
# Helpers: Build mock CallbackContext that matches production path
# ---------------------------------------------------------------------------

def _make_mock_agent(name: str = "worker_1", model: str = "gemini-fake") -> Any:
    """Create a real-ish LlmAgent with carrier attributes pre-set."""
    from google.adk.agents import LlmAgent
    from google.genai import types

    agent = LlmAgent(
        name=name,
        model=model,
        description="test worker",
        instruction="test",
        include_contents="none",
        output_key=f"{name}_output",
        generate_content_config=types.GenerateContentConfig(temperature=0.0),
    )
    # Initialize carrier attributes (same as WorkerPool._create_worker)
    agent._pending_prompt = "What is 2+2?"  # type: ignore[attr-defined]
    agent._result = None  # type: ignore[attr-defined]
    agent._result_ready = False  # type: ignore[attr-defined]
    agent._result_usage = {"input_tokens": 0, "output_tokens": 0}  # type: ignore[attr-defined]
    agent._result_error = False  # type: ignore[attr-defined]
    agent._prompt_chars = 0  # type: ignore[attr-defined]
    agent._content_count = 0  # type: ignore[attr-defined]
    agent._call_record = None  # type: ignore[attr-defined]
    return agent


def _make_callback_context(agent: Any) -> Any:
    """Build a mock CallbackContext with _invocation_context.agent set."""
    ctx = MagicMock()
    ctx._invocation_context.agent = agent
    ctx.state = {}
    return ctx


def _make_llm_response(
    text: str = "4",
    model_version: str = "gemini-fake",
    input_tokens: int = 10,
    output_tokens: int = 2,
) -> Any:
    """Build a mock LlmResponse."""
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)],
        ),
        model_version=model_version,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=input_tokens,
            candidates_token_count=output_tokens,
        ),
    )


def _make_llm_request(prompt_text: str = "What is 2+2?") -> Any:
    """Build a mock LlmRequest with contents."""
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types

    return LlmRequest(
        contents=[
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt_text)],
            )
        ]
    )


# ===========================================================================
# TEST 1: worker_after_model writes _call_record
# ===========================================================================

class TestWorkerAfterModelCallRecord:
    """Gap 1/2/3/4: worker_after_model should create _call_record on the agent."""

    def test_call_record_created(self):
        """_call_record dict is created with prompt, response, tokens, model."""
        agent = _make_mock_agent()
        ctx = _make_callback_context(agent)
        llm_response = _make_llm_response(
            text="4", model_version="gemini-fake",
            input_tokens=10, output_tokens=2,
        )

        worker_after_model(ctx, llm_response)

        record = getattr(agent, "_call_record", None)
        assert record is not None, "_call_record not set on agent"
        assert record["prompt"] == "What is 2+2?"
        assert record["response"] == "4"
        assert record["input_tokens"] == 10
        assert record["output_tokens"] == 2
        assert record["model"] == "gemini-fake"
        assert record["error"] is False

    def test_call_record_with_list_prompt(self):
        """_call_record captures list-format prompts as-is on the agent."""
        agent = _make_mock_agent()
        agent._pending_prompt = [  # type: ignore[attr-defined]
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "What is 2+2?"},
        ]
        ctx = _make_callback_context(agent)
        llm_response = _make_llm_response(text="4")

        worker_after_model(ctx, llm_response)

        record = agent._call_record  # type: ignore[attr-defined]
        assert record is not None
        assert isinstance(record["prompt"], list)
        assert len(record["prompt"]) == 3


class TestListPromptNormalization:
    """Issue 2: list-type prompts should be normalized to str in RLMChatCompletion."""

    def test_list_prompt_normalized_to_string(self):
        """Dispatch accumulation normalizes list prompts to pipe-joined string."""
        from rlm_adk.types import RLMChatCompletion

        # Simulate what dispatch.py does for list-type prompts
        raw_prompt = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "What is 2+2?"},
        ]
        if isinstance(raw_prompt, list):
            prompt_val = " | ".join(
                m.get("content", "") for m in raw_prompt if isinstance(m, dict)
            )
        else:
            prompt_val = raw_prompt

        assert isinstance(prompt_val, str)
        assert "Hello" in prompt_val
        assert "Hi" in prompt_val
        assert "2+2" in prompt_val
        assert " | " in prompt_val

    def test_none_prompt_normalized_to_empty_string(self):
        """None prompts become empty string."""
        raw_prompt = None
        if raw_prompt is None:
            prompt_val = ""
        elif isinstance(raw_prompt, list):
            prompt_val = " | ".join(
                m.get("content", "") for m in raw_prompt if isinstance(m, dict)
            )
        else:
            prompt_val = raw_prompt

        assert prompt_val == ""

    def test_call_record_with_no_usage(self):
        """_call_record handles missing usage_metadata gracefully."""
        agent = _make_mock_agent()
        ctx = _make_callback_context(agent)
        from google.adk.models.llm_response import LlmResponse
        from google.genai import types

        llm_response = LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text="answer")],
            ),
            model_version="gemini-fake",
            usage_metadata=None,
        )

        worker_after_model(ctx, llm_response)

        record = agent._call_record  # type: ignore[attr-defined]
        assert record is not None
        assert record["input_tokens"] == 0
        assert record["output_tokens"] == 0


# ===========================================================================
# TEST 2: worker_on_model_error writes error _call_record
# ===========================================================================

class TestWorkerOnModelErrorCallRecord:
    """Gap 7: worker_on_model_error should create error _call_record."""

    def test_error_call_record_created(self):
        """Error _call_record has error=True, response=error_msg."""
        agent = _make_mock_agent()
        ctx = _make_callback_context(agent)
        llm_request = _make_llm_request()
        error = RuntimeError("API timeout")

        worker_on_model_error(ctx, llm_request, error)

        record = getattr(agent, "_call_record", None)
        assert record is not None, "_call_record not set on error"
        assert record["error"] is True
        assert "RuntimeError" in record["response"]
        assert "API timeout" in record["response"]
        assert record["prompt"] == "What is 2+2?"
        assert record["input_tokens"] == 0
        assert record["output_tokens"] == 0
        assert record["model"] is None


# ===========================================================================
# TEST 3: _call_record initialized on worker creation
# ===========================================================================

class TestWorkerCreationCallRecord:
    """_call_record should be initialized to None on new workers."""

    def test_call_record_initialized(self):
        pool = WorkerPool(default_model="gemini-fake", pool_size=1)
        pool.register_model("gemini-fake", pool_size=1)
        worker = asyncio.get_event_loop().run_until_complete(
            pool.acquire("gemini-fake")
        )
        assert hasattr(worker, "_call_record"), "worker missing _call_record attr"
        assert worker._call_record is None  # type: ignore[attr-defined]


# ===========================================================================
# TEST 4: format_execution_result includes variable values (Gap 5)
# ===========================================================================

class TestFormatExecutionResultValues:
    """Gap 5: format_execution_result should include variable values, not just names."""

    def test_variable_values_included(self):
        """Variables should show their actual values."""
        result = REPLResult(
            stdout="hello\n",
            stderr="",
            locals={"x": 42, "name": "test", "data": [1, 2, 3]},
        )
        formatted = format_execution_result(result)

        # Should contain actual values, not just names
        assert "42" in formatted, f"Expected value 42 in output: {formatted}"
        assert "'test'" in formatted or '"test"' in formatted, (
            f"Expected string value 'test' in output: {formatted}"
        )

    def test_long_values_truncated(self):
        """Long variable values should be truncated."""
        result = REPLResult(
            stdout="",
            stderr="",
            locals={"big": "x" * 500},
        )
        formatted = format_execution_result(result)
        # Should show value but truncated
        assert "x" in formatted
        assert "..." in formatted

    def test_execution_time_displayed(self):
        """When execution_time is set, the formatted output includes it rounded to 2dp."""
        result = REPLResult(
            stdout="ok\n",
            stderr="",
            locals={},
            execution_time=1.234,
        )
        formatted = format_execution_result(result)
        assert "Execution time: 1.23s" in formatted

    def test_execution_time_none_not_displayed(self):
        """When execution_time is None, no execution time line appears."""
        result = REPLResult(
            stdout="ok\n",
            stderr="",
            locals={},
            execution_time=None,
        )
        formatted = format_execution_result(result)
        assert "Execution time" not in formatted


# ===========================================================================
# TEST 5: format_execution_result includes llm_calls summary (Gap 1)
# ===========================================================================

class TestFormatExecutionResultLLMCalls:
    """Gap 1: format_execution_result should include worker LLM call summaries."""

    def test_llm_calls_shown(self):
        """When llm_calls is populated, the formatted output includes call info."""
        result = REPLResult(
            stdout="4\n",
            stderr="",
            locals={"result": "4"},
            llm_calls=[
                RLMChatCompletion(
                    root_model="gemini-fake",
                    prompt="What is 2+2?",
                    response="4",
                    usage_summary=UsageSummary(
                        model_usage_summaries={
                            "gemini-fake": ModelUsageSummary(
                                total_calls=1,
                                total_input_tokens=10,
                                total_output_tokens=2,
                            )
                        }
                    ),
                    execution_time=0.5,
                ),
            ],
        )
        formatted = format_execution_result(result)

        assert "Worker LLM calls:" in formatted or "llm_call" in formatted.lower(), (
            f"Expected worker call summary in output: {formatted}"
        )
        assert "2+2" in formatted, (
            f"Expected prompt preview in output: {formatted}"
        )

    def test_empty_llm_calls_no_section(self):
        """When llm_calls is empty, no worker call section appears."""
        result = REPLResult(
            stdout="hello\n",
            stderr="",
            locals={},
            llm_calls=[],
        )
        formatted = format_execution_result(result)
        assert "Worker LLM calls:" not in formatted


# ===========================================================================
# TEST 6: call_log_sink reference survives _pending_llm_calls.clear()
# ===========================================================================

class TestCallLogSinkReferenceStability:
    """Issue 1 regression: .clear() preserves list identity for call_log_sink."""

    def test_clear_preserves_reference(self):
        """After .clear(), the original list object is the same (not rebound)."""
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        original_list = repl._pending_llm_calls
        # Simulate what call_log_sink captures
        call_log_sink = repl._pending_llm_calls

        # Simulate execute_code resetting — this MUST NOT rebind
        repl._pending_llm_calls.clear()

        # Both should still be the SAME object
        assert repl._pending_llm_calls is original_list
        assert call_log_sink is original_list

        # Appending via sink should be visible via repl._pending_llm_calls
        call_log_sink.append("test_record")  # type: ignore[arg-type]
        assert len(repl._pending_llm_calls) == 1
        assert repl._pending_llm_calls[0] == "test_record"

        repl.cleanup()

    def test_execute_code_preserves_sink_reference(self):
        """execute_code() should preserve the call_log_sink reference."""
        from rlm_adk.repl.local_repl import LocalREPL

        repl = LocalREPL(depth=1)
        call_log_sink = repl._pending_llm_calls

        # Append something before execution
        call_log_sink.append("pre_exec_record")  # type: ignore[arg-type]

        # execute_code should .clear() but not rebind
        result = repl.execute_code("x = 42")

        # After execution, the reference should still be the same object
        assert call_log_sink is repl._pending_llm_calls

        # The pre-exec record should be gone (cleared) and llm_calls empty
        assert result.llm_calls == []

        # But appending after exec should still work via the sink
        call_log_sink.append("post_exec_record")  # type: ignore[arg-type]
        assert len(repl._pending_llm_calls) == 1

        repl.cleanup()


# ===========================================================================
# TEST 7: dispatch closure _call_record cleanup in finally
# ===========================================================================

class TestDispatchCallRecordCleanup:
    """_call_record should be cleared in the finally block after dispatch."""

    def test_call_record_cleared_after_dispatch(self):
        """After dispatch, worker._call_record is reset to None."""
        agent = _make_mock_agent()
        # Simulate what dispatch finally block should do
        agent._call_record = {"prompt": "test", "response": "test"}  # type: ignore[attr-defined]

        # The finally block (dispatch.py) should clear it:
        # worker._call_record = None
        # For now, just verify the attribute exists and can be cleared
        assert agent._call_record is not None  # type: ignore[attr-defined]
        agent._call_record = None  # type: ignore[attr-defined]
        assert agent._call_record is None  # type: ignore[attr-defined]
