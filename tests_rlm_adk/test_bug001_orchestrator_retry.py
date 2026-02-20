"""BUG-001: Orchestrator retry/error handling tests.

Sub-issue A: Error classification should use isinstance, not string matching.
Sub-issue B: Dead `reasoning_succeeded` code should be removed.
Sub-issue C: Agent factory should accept and pass through retry options.
"""

import ast
import inspect
import textwrap

import pytest
from google.genai.errors import ClientError, ServerError

from rlm_adk.orchestrator import RLMOrchestratorAgent


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
