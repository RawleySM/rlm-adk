"""OpenRouter provider tests for LiteLLM Router integration.

RED/GREEN TDD: tests written first, then implementation.
"""

import pytest

pytestmark = [pytest.mark.unit_nondefault]

# All provider keys that might be set in the environment
_ALL_PROVIDER_KEYS = (
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "DASHSCOPE_API_KEY",
    "MINIMAX_API_KEY",
    "PERPLEXITY_API_KEY",
    "OPENROUTER_API_KEY",
)


def _clear_all_keys(monkeypatch):
    """Clear all provider API keys."""
    for key in _ALL_PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)


def _clear_openrouter_env(monkeypatch):
    """Clear OpenRouter-specific env vars."""
    for key in (
        "RLM_OPENROUTER_REASONING_MODEL",
        "RLM_OPENROUTER_WORKER_MODEL",
        "RLM_OPENROUTER_FALLBACK_MODELS",
        "RLM_LITELLM_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)


def _reset_singleton():
    import rlm_adk.models.litellm_router as mod

    mod._cached_client = None


# ---------------------------------------------------------------------------
# OpenRouter config inclusion/exclusion
# ---------------------------------------------------------------------------
class TestOpenRouterConfig:
    def test_openrouter_config_included_when_key_set(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        models = {e["litellm_params"]["model"] for e in result}
        assert any(m.startswith("openrouter/") for m in models)

    def test_openrouter_config_excluded_when_key_missing(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        models = {e["litellm_params"]["model"] for e in result}
        assert not any(m.startswith("openrouter/") for m in models)


# ---------------------------------------------------------------------------
# Default and overridden models
# ---------------------------------------------------------------------------
class TestOpenRouterModels:
    def test_openrouter_default_models(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        models = {e["litellm_params"]["model"] for e in result}
        assert "openrouter/google/gemini-3.1-pro-preview" in models
        assert "openrouter/anthropic/claude-sonnet-4.6" in models

    def test_openrouter_reasoning_model_override(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        monkeypatch.setenv("RLM_OPENROUTER_REASONING_MODEL", "anthropic/claude-sonnet-4")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        models = {e["litellm_params"]["model"] for e in result}
        assert "openrouter/anthropic/claude-sonnet-4" in models
        assert "openrouter/google/gemini-3.1-pro-preview" not in models

    def test_openrouter_worker_model_override(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        monkeypatch.setenv("RLM_OPENROUTER_WORKER_MODEL", "meta-llama/llama-3.3-70b")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        models = {e["litellm_params"]["model"] for e in result}
        assert "openrouter/meta-llama/llama-3.3-70b" in models
        assert "openrouter/anthropic/claude-sonnet-4.6" not in models


# ---------------------------------------------------------------------------
# Provider filter
# ---------------------------------------------------------------------------
class TestProviderFilter:
    def test_provider_filter_openrouter_only(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        monkeypatch.setenv("GEMINI_API_KEY", "g-fake-key")
        monkeypatch.setenv("RLM_LITELLM_PROVIDER", "openrouter")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        for entry in result:
            assert entry["litellm_params"]["model"].startswith("openrouter/")

    def test_provider_filter_gemini_only(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        monkeypatch.setenv("GEMINI_API_KEY", "g-fake-key")
        monkeypatch.setenv("RLM_LITELLM_PROVIDER", "gemini")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        assert len(result) > 0
        for entry in result:
            assert entry["litellm_params"]["model"].startswith("gemini/")

    def test_provider_filter_unset_includes_all(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        monkeypatch.setenv("GEMINI_API_KEY", "g-fake-key")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        models = {e["litellm_params"]["model"] for e in result}
        assert any(m.startswith("openrouter/") for m in models)
        assert any(m.startswith("gemini/") for m in models)

    def test_provider_filter_case_insensitive(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        monkeypatch.setenv("GEMINI_API_KEY", "g-fake-key")
        monkeypatch.setenv("RLM_LITELLM_PROVIDER", "OpenRouter")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        assert len(result) > 0
        for entry in result:
            assert entry["litellm_params"]["model"].startswith("openrouter/")

    def test_pinned_openrouter_single_deployment_per_tier(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        monkeypatch.setenv("RLM_LITELLM_PROVIDER", "openrouter")
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        tiers = [e["model_name"] for e in result]
        assert tiers.count("reasoning") == 1
        assert tiers.count("worker") == 1


# ---------------------------------------------------------------------------
# Error message
# ---------------------------------------------------------------------------
class TestErrorMessage:
    def test_error_message_includes_openrouter(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        _reset_singleton()
        from rlm_adk.models.litellm_router import _get_or_create_client

        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY") as exc_info:
            _get_or_create_client()
        assert "OPENROUTER_API_KEY" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Fallback models
# ---------------------------------------------------------------------------
class TestFallbackModels:
    def test_fallback_models_env_var(self, monkeypatch):
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        monkeypatch.setenv(
            "RLM_OPENROUTER_FALLBACK_MODELS",
            "z-ai/glm-5,openai/gpt-5.4,moonshotai/kimi-k2.5",
        )
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        or_entries = [e for e in result if e["litellm_params"]["model"].startswith("openrouter/")]
        assert len(or_entries) > 0
        for entry in or_entries:
            extra_body = entry["litellm_params"].get("extra_body", {})
            assert "models" in extra_body
            assert extra_body["models"] == [
                "z-ai/glm-5",
                "openai/gpt-5.4",
                "moonshotai/kimi-k2.5",
            ]

    def test_fallback_models_truncated_to_three(self, monkeypatch):
        """OpenRouter limits models array to 3; verify truncation."""
        _clear_all_keys(monkeypatch)
        _clear_openrouter_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake-key")
        monkeypatch.setenv(
            "RLM_OPENROUTER_FALLBACK_MODELS",
            "a/1,b/2,c/3,d/4,e/5",
        )
        from rlm_adk.models.litellm_router import build_model_list

        result = build_model_list()
        or_entries = [e for e in result if e["litellm_params"]["model"].startswith("openrouter/")]
        for entry in or_entries:
            models = entry["litellm_params"]["extra_body"]["models"]
            assert len(models) == 3
            assert models == ["a/1", "b/2", "c/3"]
