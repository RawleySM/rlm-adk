"""Phase 3: LiteLLM error handling integration tests.

Tests that _classify_error and is_transient_error correctly handle
LiteLLM exception types (which use status_code instead of code).
"""

import pytest

pytestmark = [pytest.mark.unit_nondefault]


class TestClassifyLiteLLMErrors:
    """Verify _classify_error maps LiteLLM exceptions to correct categories."""

    def test_rate_limit_error(self):
        import litellm

        from rlm_adk.callbacks.worker import _classify_error

        exc = litellm.RateLimitError("rate limited", "openai", model="gpt-4o")
        assert _classify_error(exc) == "RATE_LIMIT"

    def test_server_error(self):
        import litellm

        from rlm_adk.callbacks.worker import _classify_error

        exc = litellm.InternalServerError("internal error", "openai", model="gpt-4o")
        assert _classify_error(exc) == "SERVER"

    def test_auth_error(self):
        import litellm

        from rlm_adk.callbacks.worker import _classify_error

        exc = litellm.AuthenticationError("bad key", "openai", model="gpt-4o")
        assert _classify_error(exc) == "AUTH"

    def test_service_unavailable_error(self):
        import litellm

        from rlm_adk.callbacks.worker import _classify_error

        exc = litellm.ServiceUnavailableError("unavailable", "openai", model="gpt-4o")
        assert _classify_error(exc) == "SERVER"

    def test_bad_request_error(self):
        import litellm

        from rlm_adk.callbacks.worker import _classify_error

        exc = litellm.BadRequestError("bad request", "gpt-4o", "openai")
        assert _classify_error(exc) == "CLIENT"

    def test_timeout_error(self):
        import litellm

        from rlm_adk.callbacks.worker import _classify_error

        exc = litellm.Timeout("timed out", "gpt-4o", "openai")
        assert _classify_error(exc) == "TIMEOUT"


class TestIsTransientLiteLLM:
    """Verify is_transient_error for LiteLLM exception types."""

    def test_rate_limit_is_transient(self):
        import litellm

        from rlm_adk.orchestrator import is_transient_error

        exc = litellm.RateLimitError("rate limited", "openai", model="gpt-4o")
        assert is_transient_error(exc) is True

    def test_auth_is_not_transient(self):
        import litellm

        from rlm_adk.orchestrator import is_transient_error

        exc = litellm.AuthenticationError("bad key", "openai", model="gpt-4o")
        assert is_transient_error(exc) is False

    def test_server_error_is_transient(self):
        import litellm

        from rlm_adk.orchestrator import is_transient_error

        exc = litellm.InternalServerError("internal error", "openai", model="gpt-4o")
        assert is_transient_error(exc) is True

    def test_timeout_is_transient(self):
        import litellm

        from rlm_adk.orchestrator import is_transient_error

        exc = litellm.Timeout("timed out", "gpt-4o", "openai")
        assert is_transient_error(exc) is True

    def test_service_unavailable_is_transient(self):
        import litellm

        from rlm_adk.orchestrator import is_transient_error

        exc = litellm.ServiceUnavailableError("unavailable", "openai", model="gpt-4o")
        assert is_transient_error(exc) is True

    def test_bad_request_is_not_transient(self):
        import litellm

        from rlm_adk.orchestrator import is_transient_error

        exc = litellm.BadRequestError("bad request", "gpt-4o", "openai")
        assert is_transient_error(exc) is False


class TestExistingGeminiErrorsUnchanged:
    """Verify existing google.genai error classification still works."""

    def test_gemini_server_error_transient(self):
        from google.genai.errors import ServerError

        from rlm_adk.orchestrator import is_transient_error

        exc = ServerError.__new__(ServerError)
        object.__setattr__(exc, "code", 500)
        object.__setattr__(exc, "args", ("server error",))
        assert is_transient_error(exc) is True

    def test_gemini_client_error_429_transient(self):
        from google.genai.errors import ClientError

        from rlm_adk.orchestrator import is_transient_error

        exc = ClientError.__new__(ClientError)
        object.__setattr__(exc, "code", 429)
        object.__setattr__(exc, "args", ("rate limited",))
        assert is_transient_error(exc) is True

    def test_gemini_client_error_400_not_transient(self):
        from google.genai.errors import ClientError

        from rlm_adk.orchestrator import is_transient_error

        exc = ClientError.__new__(ClientError)
        object.__setattr__(exc, "code", 400)
        object.__setattr__(exc, "args", ("bad request",))
        assert is_transient_error(exc) is False

    def test_classify_gemini_server_error(self):
        from google.genai.errors import ServerError

        from rlm_adk.callbacks.worker import _classify_error

        exc = ServerError.__new__(ServerError)
        object.__setattr__(exc, "code", 500)
        object.__setattr__(exc, "args", ("server error",))
        assert _classify_error(exc) == "SERVER"

    def test_classify_gemini_rate_limit(self):
        from google.genai.errors import ClientError

        from rlm_adk.callbacks.worker import _classify_error

        exc = ClientError.__new__(ClientError)
        object.__setattr__(exc, "code", 429)
        object.__setattr__(exc, "args", ("rate limited",))
        assert _classify_error(exc) == "RATE_LIMIT"

    def test_asyncio_timeout_still_works(self):
        from rlm_adk.orchestrator import is_transient_error

        exc = TimeoutError()
        assert is_transient_error(exc) is True

    def test_classify_asyncio_timeout(self):
        from rlm_adk.callbacks.worker import _classify_error

        exc = TimeoutError()
        assert _classify_error(exc) == "TIMEOUT"
