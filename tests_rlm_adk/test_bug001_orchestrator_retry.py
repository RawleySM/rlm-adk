"""BUG-001: Orchestrator retry/error handling tests.

Sub-issue A: Error classification should use isinstance, not string matching.
Sub-issue B: Dead `reasoning_succeeded` code should be removed.
Sub-issue C: Agent factory should accept and pass through retry options.
Sub-issue D: Partial-event-yield retry test (FM-01).
Sub-issue E: is_transient_error boundary cases (FM-02).
Sub-issue F: 401 non-transient propagation test (FM-28).
"""

import asyncio
import ast
import inspect
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai.errors import ClientError, ServerError

from rlm_adk.orchestrator import RLMOrchestratorAgent, is_transient_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_orchestrator_source() -> str:
    """Return dedented source of _run_async_impl."""
    return textwrap.dedent(inspect.getsource(RLMOrchestratorAgent._run_async_impl))


def _make_server_error(code: int = 503, status: str = "UNAVAILABLE") -> ServerError:
    """Create a google.genai ServerError with given code."""
    return ServerError(code, {"error": {"message": "Service Unavailable", "status": status}})


def _make_client_error(code: int = 429, status: str = "RESOURCE_EXHAUSTED") -> ClientError:
    """Create a google.genai ClientError with given code."""
    return ClientError(code, {"error": {"message": "Too Many Requests", "status": status}})


# ===================================================================
# Sub-issue A: Type-based error classification
# ===================================================================

class TestErrorClassificationTypeBased:
    """Error classification must use isinstance checks, not string matching."""

    def test_server_error_503_is_transient(self):
        """A ServerError with code 503 should be classified as transient."""
        from rlm_adk.orchestrator import is_transient_error
        exc = _make_server_error(503, "UNAVAILABLE")
        assert is_transient_error(exc) is True

    def test_client_error_429_is_transient(self):
        """A ClientError with code 429 (rate limit) should be classified as transient."""
        from rlm_adk.orchestrator import is_transient_error
        exc = _make_client_error(429, "RESOURCE_EXHAUSTED")
        assert is_transient_error(exc) is True

    def test_generic_exception_with_503_in_message_is_not_transient(self):
        """A generic Exception containing '503' in its message must NOT be transient.

        This is the core regression test for the string-matching fragility.
        """
        from rlm_adk.orchestrator import is_transient_error
        exc = Exception("Error processing item 503 in batch")
        assert is_transient_error(exc) is False

    def test_generic_exception_with_429_in_message_is_not_transient(self):
        """A generic Exception containing '429' in its message must NOT be transient."""
        from rlm_adk.orchestrator import is_transient_error
        exc = Exception("Row 429 failed validation")
        assert is_transient_error(exc) is False

    def test_server_error_500_is_transient(self):
        """A ServerError with code 500 should also be treated as transient."""
        from rlm_adk.orchestrator import is_transient_error
        exc = _make_server_error(500, "INTERNAL")
        assert is_transient_error(exc) is True

    def test_client_error_400_is_not_transient(self):
        """A ClientError with code 400 (bad request) should NOT be transient."""
        from rlm_adk.orchestrator import is_transient_error
        exc = ClientError(400, {"error": {"message": "Bad Request", "status": "INVALID_ARGUMENT"}})
        assert is_transient_error(exc) is False

    def test_client_error_404_is_not_transient(self):
        """A ClientError with code 404 (not found) should NOT be transient."""
        exc = ClientError(404, {"error": {"message": "Not Found", "status": "NOT_FOUND"}})
        assert is_transient_error(exc) is False

    def test_client_error_408_is_transient(self):
        """A ClientError with code 408 (request timeout) should be transient."""
        exc = ClientError(408, {"error": {"message": "Request Timeout", "status": "DEADLINE_EXCEEDED"}})
        assert is_transient_error(exc) is True

    def test_validation_error_is_not_transient(self):
        """A ValidationError (or ValueError) should NOT be transient."""
        exc = ValueError("Invalid schema: missing required field 'answer'")
        assert is_transient_error(exc) is False

    def test_no_string_matching_in_source(self):
        """The orchestrator source should not contain string-based error classification."""
        source = _get_orchestrator_source()
        # The old fragile pattern: any(code in exc_str for code in ("503", ...))
        assert 'exc_str' not in source, (
            "Orchestrator still uses exc_str string matching for error classification"
        )
        assert '"503"' not in source, (
            "Orchestrator still has string literal '503' for error matching"
        )


# ===================================================================
# Sub-issue B: Dead reasoning_succeeded code removed
# ===================================================================

class TestReasoningSucceededDeadCodeRemoved:
    """The dead `reasoning_succeeded` variable and unreachable block should be gone."""

    def test_no_reasoning_succeeded_variable(self):
        """The variable `reasoning_succeeded` should not exist in _run_async_impl."""
        source = _get_orchestrator_source()
        assert "reasoning_succeeded" not in source, (
            "Dead variable `reasoning_succeeded` still present in orchestrator"
        )

    def test_no_unreachable_warning_block(self):
        """The unreachable 'reasoning agent did not succeed' warning should be gone."""
        source = _get_orchestrator_source()
        assert "did not succeed after retries" not in source, (
            "Unreachable warning message still present in orchestrator"
        )

    def test_orchestrator_class_still_valid(self):
        """After removing dead code, RLMOrchestratorAgent should still be importable."""
        assert hasattr(RLMOrchestratorAgent, "_run_async_impl")
        assert inspect.isfunction(RLMOrchestratorAgent._run_async_impl) or \
               inspect.ismethod(RLMOrchestratorAgent._run_async_impl)


# ===================================================================
# Sub-issue C: Agent factory retry config pass-through
# ===================================================================

class TestAgentFactoryRetryConfig:
    """Agent factory should accept and pass through retry configuration."""

    def test_create_reasoning_agent_accepts_retry_config(self):
        """create_reasoning_agent should accept a retry_config parameter."""
        from rlm_adk.agent import create_reasoning_agent
        sig = inspect.signature(create_reasoning_agent)
        assert "retry_config" in sig.parameters, (
            "create_reasoning_agent does not accept a retry_config parameter"
        )

    def test_create_rlm_orchestrator_accepts_retry_config(self):
        """create_rlm_orchestrator should accept a retry_config parameter."""
        from rlm_adk.agent import create_rlm_orchestrator
        sig = inspect.signature(create_rlm_orchestrator)
        assert "retry_config" in sig.parameters, (
            "create_rlm_orchestrator does not accept a retry_config parameter"
        )

    def test_create_reasoning_agent_passes_retry_config_to_model(self):
        """When retry_config is provided, it should reach the LlmAgent generate_content_config."""
        from rlm_adk.agent import create_reasoning_agent
        from google.genai.types import GenerateContentConfig

        # Create agent with a custom retry config
        agent = create_reasoning_agent(
            "test-model",
            retry_config={"attempts": 5},
        )
        # The agent should have a generate_content_config with retry settings
        gcc = agent.generate_content_config
        assert gcc is not None, "generate_content_config should be set when retry_config is provided"

    def test_create_reasoning_agent_default_has_retry(self):
        """By default, create_reasoning_agent should set up retry config (3 attempts)."""
        from rlm_adk.agent import create_reasoning_agent

        agent = create_reasoning_agent("test-model")
        gcc = agent.generate_content_config
        assert gcc is not None, (
            "Default create_reasoning_agent should include generate_content_config with retry"
        )

    def test_create_rlm_orchestrator_passes_retry_config(self):
        """create_rlm_orchestrator should forward retry_config to the reasoning agent."""
        from rlm_adk.agent import create_rlm_orchestrator

        orch = create_rlm_orchestrator(
            model="test-model",
            retry_config={"attempts": 5},
        )
        # The orchestrator's reasoning agent should have config set
        gcc = orch.reasoning_agent.generate_content_config
        assert gcc is not None, (
            "retry_config should be forwarded to reasoning agent's generate_content_config"
        )


# ===================================================================
# Sub-issue D: Partial-event-yield retry (FM-01)
# ===================================================================


class TestPartialEventYieldRetry:
    """Orchestrator retry loop must handle events yielded before a transient error.

    When reasoning_agent.run_async yields some events then raises a transient
    ServerError, the retry loop should retry and eventually produce a correct
    result from the second attempt.
    """

    @pytest.mark.asyncio
    async def test_retry_after_partial_events_yields_success(self):
        """Mock run_async to yield 2 events then raise ServerError(503) on first
        attempt, succeed with final answer on second attempt.  Verify the
        orchestrator retries and produces the correct final answer."""
        from google.adk.agents import LlmAgent
        from google.adk.events import Event, EventActions
        from google.genai import types

        from rlm_adk.state import FINAL_ANSWER

        # Build a real orchestrator with a real reasoning_agent (Pydantic model)
        reasoning_agent = LlmAgent(
            name="reasoning",
            model="test-model",
            output_key="reasoning_output",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
        )

        # Mock InvocationContext
        ctx = MagicMock()
        ctx.invocation_id = "inv-partial-retry"
        ctx.session.state = {}
        ctx.session.id = "sess-1"

        # Track call count to alternate behavior
        call_count = 0

        async def mock_run_async(run_ctx):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First attempt: yield 2 stale events then raise
                yield Event(
                    invocation_id=run_ctx.invocation_id,
                    author="reasoning",
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="Partial thought 1")],
                    ),
                )
                yield Event(
                    invocation_id=run_ctx.invocation_id,
                    author="reasoning",
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="Partial thought 2")],
                    ),
                )
                raise ServerError(503, {"error": {"message": "Service Unavailable", "status": "UNAVAILABLE"}})
            else:
                # Second attempt: succeed with final answer in output_key
                run_ctx.session.state["reasoning_output"] = "The correct final answer"
                yield Event(
                    invocation_id=run_ctx.invocation_id,
                    author="reasoning",
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="The correct final answer")],
                    ),
                )

        # Patch reasoning_agent.run_async and asyncio.sleep (to skip delay)
        object.__setattr__(reasoning_agent, 'run_async', mock_run_async)

        # Patch save_final_answer to avoid artifact service dependency
        with patch("rlm_adk.orchestrator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
             patch("rlm_adk.orchestrator.save_final_answer", new_callable=AsyncMock):
            events = []
            async for event in orch._run_async_impl(ctx):
                events.append(event)

        # Verify retry happened
        assert call_count == 2, f"Expected 2 calls to run_async, got {call_count}"

        # Verify asyncio.sleep was called (backoff delay)
        mock_sleep.assert_called_once()

        # Verify final answer was produced
        final_state_deltas = [
            e.actions.state_delta
            for e in events
            if e.actions and e.actions.state_delta and FINAL_ANSWER in (e.actions.state_delta or {})
        ]
        assert len(final_state_deltas) >= 1, "No FINAL_ANSWER state delta event found"
        assert final_state_deltas[-1][FINAL_ANSWER] == "The correct final answer"


# ===================================================================
# Sub-issue F: 401 non-transient propagation (FM-28)
# ===================================================================


class TestNonTransient401Propagation:
    """A ClientError(code=401) must propagate immediately without retry.

    The orchestrator must: (1) not retry, (2) not call asyncio.sleep,
    (3) still execute the finally block (tools=[], repl.cleanup).
    """

    @pytest.mark.asyncio
    async def test_401_propagates_without_retry(self):
        """ClientError(401) from reasoning_agent.run_async raises immediately,
        no retry, finally block runs."""
        from google.adk.agents import LlmAgent

        reasoning_agent = LlmAgent(
            name="reasoning",
            model="test-model",
            output_key="reasoning_output",
        )
        orch = RLMOrchestratorAgent(
            name="test_orch",
            reasoning_agent=reasoning_agent,
            sub_agents=[reasoning_agent],
        )

        ctx = MagicMock()
        ctx.invocation_id = "inv-401"
        ctx.session.state = {}
        ctx.session.id = "sess-1"

        call_count = 0

        async def mock_run_async_401(_ctx):
            nonlocal call_count
            call_count += 1
            raise ClientError(401, {"error": {"message": "Unauthorized", "status": "UNAUTHENTICATED"}})
            yield  # make it an async generator

        object.__setattr__(reasoning_agent, 'run_async', mock_run_async_401)

        with patch("rlm_adk.orchestrator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
             patch("rlm_adk.orchestrator.save_final_answer", new_callable=AsyncMock):
            with pytest.raises(ClientError) as exc_info:
                async for _event in orch._run_async_impl(ctx):
                    pass

        # Verify: exception propagated with correct code
        assert exc_info.value.code == 401

        # Verify: exactly 1 call (no retry)
        assert call_count == 1, f"Expected exactly 1 call, got {call_count}"

        # Verify: asyncio.sleep was never called (no backoff)
        mock_sleep.assert_not_called()

        # Verify: finally block ran -- tools should be reset to []
        assert reasoning_agent.tools == []
