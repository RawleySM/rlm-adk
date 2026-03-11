"""Phase 1 foundation tests for LiteLLM Router integration.

RED/GREEN TDD: these tests are written first, then the implementation.
"""

import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = [pytest.mark.unit_nondefault]


# ---------------------------------------------------------------------------
# RouterLiteLlmClient
# ---------------------------------------------------------------------------
class TestRouterLiteLlmClient:
    def test_import(self):
        from rlm_adk.models.litellm_router import RouterLiteLlmClient

        assert RouterLiteLlmClient is not None

    def test_init_with_model_list(self):
        from rlm_adk.models.litellm_router import RouterLiteLlmClient

        client = RouterLiteLlmClient(
            model_list=[
                {"model_name": "test", "litellm_params": {"model": "openai/gpt-4o-mini"}},
            ]
        )
        assert client._router is not None

    @pytest.mark.asyncio
    async def test_acompletion_delegates_to_router(self):
        from rlm_adk.models.litellm_router import RouterLiteLlmClient

        client = RouterLiteLlmClient(
            model_list=[
                {"model_name": "test", "litellm_params": {"model": "openai/gpt-4o-mini"}},
            ]
        )
        mock_response = MagicMock()
        client._router.acompletion = AsyncMock(return_value=mock_response)
        result = await client.acompletion(model="test", messages=[], tools=None)
        client._router.acompletion.assert_called_once()
        assert result is mock_response

    def test_completion_delegates_to_router(self):
        from rlm_adk.models.litellm_router import RouterLiteLlmClient

        client = RouterLiteLlmClient(
            model_list=[
                {"model_name": "test", "litellm_params": {"model": "openai/gpt-4o-mini"}},
            ]
        )
        mock_response = MagicMock()
        client._router.completion = MagicMock(return_value=mock_response)
        result = client.completion(model="test", messages=[], tools=None, stream=False)
        client._router.completion.assert_called_once()
        assert result is mock_response


# ---------------------------------------------------------------------------
# build_model_list
# ---------------------------------------------------------------------------
class TestModelListBuilder:
    def test_returns_list_with_gemini_key(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_skips_missing_keys(self, monkeypatch):
        # Clear all provider keys
        for key in (
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "GROQ_API_KEY",
            "DASHSCOPE_API_KEY",
            "MINIMAX_API_KEY",
            "PERPLEXITY_API_KEY",
            "OPENROUTER_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_includes_correct_providers(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk")
        monkeypatch.setenv("OPENAI_API_KEY", "ok")
        # Clear others
        for key in (
            "DEEPSEEK_API_KEY",
            "GROQ_API_KEY",
            "DASHSCOPE_API_KEY",
            "MINIMAX_API_KEY",
            "PERPLEXITY_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        model_names = {entry["litellm_params"]["model"] for entry in result}
        # Gemini models
        assert any(m.startswith("gemini/") for m in model_names)
        # OpenAI models
        assert any(m.startswith("openai/") for m in model_names)

    def test_model_list_entries_have_tier(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        for entry in result:
            assert "model_name" in entry
            assert entry["model_name"] in ("reasoning", "worker", "search")


# ---------------------------------------------------------------------------
# create_litellm_model
# ---------------------------------------------------------------------------
class TestCreateLiteLlmModel:
    def test_returns_litellm_instance(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        # Reset singleton between tests
        import rlm_adk.models.litellm_router as mod

        mod._cached_client = None

        from rlm_adk.models.litellm_router import create_litellm_model

        model = create_litellm_model("reasoning")
        from google.adk.models.lite_llm import LiteLlm

        assert isinstance(model, LiteLlm)

    def test_model_name_is_logical(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        import rlm_adk.models.litellm_router as mod

        mod._cached_client = None

        from rlm_adk.models.litellm_router import create_litellm_model

        model = create_litellm_model("worker")
        assert model.model == "worker"


# ---------------------------------------------------------------------------
# Singleton safety
# ---------------------------------------------------------------------------
class TestSingletonSafety:
    def test_same_client_returned(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        import rlm_adk.models.litellm_router as mod

        mod._cached_client = None

        from rlm_adk.models.litellm_router import _get_or_create_client

        c1 = _get_or_create_client()
        c2 = _get_or_create_client()
        assert c1 is c2

    def test_thread_safety(self, monkeypatch):
        """Multiple threads calling _get_or_create_client get the same instance."""
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        import rlm_adk.models.litellm_router as mod

        mod._cached_client = None

        from rlm_adk.models.litellm_router import _get_or_create_client

        results = []
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()
            results.append(_get_or_create_client())

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(r is results[0] for r in results)


# ---------------------------------------------------------------------------
# Empty model list raises
# ---------------------------------------------------------------------------
class TestEmptyModelListError:
    def test_raises_runtime_error_when_no_keys(self, monkeypatch):
        for key in (
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "GROQ_API_KEY",
            "DASHSCOPE_API_KEY",
            "MINIMAX_API_KEY",
            "PERPLEXITY_API_KEY",
            "OPENROUTER_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        import rlm_adk.models.litellm_router as mod

        mod._cached_client = None

        from rlm_adk.models.litellm_router import _get_or_create_client

        with pytest.raises(RuntimeError, match="No LiteLLM provider"):
            _get_or_create_client()


# ---------------------------------------------------------------------------
# Env var configuration (CRIT-3)
# ---------------------------------------------------------------------------
class TestEnvVarConfiguration:
    def test_routing_strategy_from_env(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("RLM_LITELLM_ROUTING_STRATEGY", "least-busy")
        import rlm_adk.models.litellm_router as mod

        mod._cached_client = None

        from rlm_adk.models.litellm_router import _get_or_create_client

        client = _get_or_create_client()
        assert client._router.routing_strategy == "least-busy"

    def test_num_retries_from_env(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("RLM_LITELLM_NUM_RETRIES", "5")
        import rlm_adk.models.litellm_router as mod

        mod._cached_client = None

        from rlm_adk.models.litellm_router import _get_or_create_client

        client = _get_or_create_client()
        assert client._router.num_retries == 5

    def test_timeout_from_env(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("RLM_LITELLM_TIMEOUT", "120")
        import rlm_adk.models.litellm_router as mod

        mod._cached_client = None

        from rlm_adk.models.litellm_router import _get_or_create_client

        client = _get_or_create_client()
        assert client._router.timeout == 120
