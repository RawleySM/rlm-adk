"""Tests for Phase 2: LiteLLM factory integration in agent.py.

Validates that _is_litellm_active(), _resolve_model(), and create_reasoning_agent()
correctly gate Gemini-specific constructs (BuiltInPlanner, GenerateContentConfig)
when RLM_ADK_LITELLM is enabled, and leave the existing Gemini path untouched
when disabled.

MED-4: All tests mock create_litellm_model to avoid instantiating a real
litellm.Router.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit_nondefault]


@pytest.fixture(autouse=True)
def _clear_litellm_env(monkeypatch):
    """Ensure RLM_ADK_LITELLM is unset by default in every test."""
    monkeypatch.delenv("RLM_ADK_LITELLM", raising=False)


@pytest.fixture()
def _mock_create_litellm_model(monkeypatch):
    """MED-4: Mock create_litellm_model to avoid real Router instantiation.

    Returns a real LiteLlm instance with a mocked llm_client so Pydantic
    validation passes (LlmAgent.model accepts str | BaseLlm).
    """
    from google.adk.models.lite_llm import LiteLlm, LiteLLMClient

    mock_client = MagicMock(spec=LiteLLMClient)
    mock_model = LiteLlm(model="reasoning", llm_client=mock_client)
    monkeypatch.setattr(
        "rlm_adk.models.litellm_router.create_litellm_model",
        lambda *a, **kw: mock_model,
    )
    return mock_model


class TestIsLiteLLMActive:
    def test_flag_off_by_default(self):
        from rlm_adk.agent import _is_litellm_active

        assert _is_litellm_active() is False

    def test_flag_on_with_1(self, monkeypatch):
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        from rlm_adk.agent import _is_litellm_active

        assert _is_litellm_active() is True

    def test_flag_on_with_true(self, monkeypatch):
        monkeypatch.setenv("RLM_ADK_LITELLM", "true")
        from rlm_adk.agent import _is_litellm_active

        assert _is_litellm_active() is True

    def test_flag_on_with_yes(self, monkeypatch):
        monkeypatch.setenv("RLM_ADK_LITELLM", "yes")
        from rlm_adk.agent import _is_litellm_active

        assert _is_litellm_active() is True

    def test_flag_off_with_0(self, monkeypatch):
        monkeypatch.setenv("RLM_ADK_LITELLM", "0")
        from rlm_adk.agent import _is_litellm_active

        assert _is_litellm_active() is False


class TestResolveModel:
    def test_passthrough_when_flag_off(self):
        from rlm_adk.agent import _resolve_model

        result = _resolve_model("gemini-2.5-pro")
        assert result == "gemini-2.5-pro"
        assert isinstance(result, str)

    def test_returns_litellm_when_flag_on(self, monkeypatch, _mock_create_litellm_model):
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        from rlm_adk.agent import _resolve_model

        result = _resolve_model("gemini-2.5-pro")
        assert result is _mock_create_litellm_model
        assert not isinstance(result, str)

    def test_passthrough_for_litellm_object(self, monkeypatch):
        """CRIT-1: _resolve_model must not double-wrap LiteLlm objects."""
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        from rlm_adk.agent import _resolve_model

        existing_litellm_obj = MagicMock()  # Simulates an already-resolved LiteLlm
        result = _resolve_model(existing_litellm_obj)
        assert result is existing_litellm_obj

    def test_uses_tier_param(self, monkeypatch, _mock_create_litellm_model):
        """When tier is passed, it should be used as the logical name."""
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        calls = []
        monkeypatch.setattr(
            "rlm_adk.models.litellm_router.create_litellm_model",
            lambda *a, **kw: calls.append(a) or _mock_create_litellm_model,
        )
        from rlm_adk.agent import _resolve_model

        _resolve_model("gemini-2.5-pro", tier="worker")
        assert len(calls) == 1
        assert calls[0][0] == "worker"


class TestFactoryLiteLLMGating:
    def test_litellm_flag_off_uses_gemini(self):
        """When flag is off, model should be a plain string."""
        from rlm_adk.agent import create_reasoning_agent

        agent = create_reasoning_agent("gemini-2.5-pro", thinking_budget=0)
        assert isinstance(agent.model, str)
        assert agent.model == "gemini-2.5-pro"

    def test_litellm_flag_on_returns_litellm_model(self, monkeypatch, _mock_create_litellm_model):
        """When flag is on, model should be a LiteLlm mock object."""
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        from rlm_adk.agent import create_reasoning_agent

        agent = create_reasoning_agent("reasoning", thinking_budget=0)
        assert agent.model is _mock_create_litellm_model

    def test_planner_skipped_for_litellm(self, monkeypatch, _mock_create_litellm_model):
        """BuiltInPlanner must be None when LiteLLM is active (even with thinking_budget > 0)."""
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        from rlm_adk.agent import create_reasoning_agent

        agent = create_reasoning_agent("reasoning", thinking_budget=1024)
        assert agent.planner is None

    def test_generate_content_config_no_http_options_for_litellm(
        self, monkeypatch, _mock_create_litellm_model
    ):
        """Gemini-specific HttpOptions/retry config must not be set when LiteLLM is active.

        Pydantic may coerce None to a default GenerateContentConfig(), so we
        check the meaningful field (http_options) rather than None-ness.
        """
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        from rlm_adk.agent import create_reasoning_agent

        agent = create_reasoning_agent("reasoning", thinking_budget=0)
        gcc = agent.generate_content_config
        # Either None or an empty default (no Gemini HttpOptions)
        if gcc is not None:
            assert gcc.http_options is None

    def test_existing_gemini_path_unchanged(self):
        """Regression: default path must still produce planner and gcc."""
        from rlm_adk.agent import create_reasoning_agent

        agent = create_reasoning_agent("gemini-2.5-pro", thinking_budget=1024)
        assert agent.planner is not None
        assert agent.generate_content_config is not None
        assert isinstance(agent.model, str)

    def test_existing_gemini_path_no_planner_when_zero_budget(self):
        """Regression: thinking_budget=0 disables planner even for Gemini."""
        from rlm_adk.agent import create_reasoning_agent

        agent = create_reasoning_agent("gemini-2.5-pro", thinking_budget=0)
        assert agent.planner is None
        assert agent.generate_content_config is not None


# ---------------------------------------------------------------------------
# Phase 4: Dispatch Integration
# ---------------------------------------------------------------------------


class TestDispatchConfigLiteLLM:
    """Verify DispatchConfig accepts LiteLlm objects (not just strings)."""

    def test_dispatch_config_accepts_litellm_model(self):
        """DispatchConfig must accept non-string model objects (e.g. LiteLlm)."""
        from rlm_adk.dispatch import DispatchConfig

        mock_model = MagicMock()
        mock_model.__bool__ = lambda self: True
        mock_other = MagicMock()
        mock_other.__bool__ = lambda self: True

        dc = DispatchConfig(default_model=mock_model, other_model=mock_other)
        assert dc.default_model is mock_model
        assert dc.other_model is mock_other

    def test_dispatch_config_other_model_defaults_to_default(self):
        """When other_model is None, it should fall back to default_model."""
        from rlm_adk.dispatch import DispatchConfig

        mock_model = MagicMock()
        mock_model.__bool__ = lambda self: True

        dc = DispatchConfig(default_model=mock_model)
        assert dc.other_model is mock_model


class TestWorkerTierFromEnvVar:
    """Verify RLM_LITELLM_WORKER_TIER env var is consumed in create_rlm_orchestrator."""

    def test_worker_tier_default(self, monkeypatch, _mock_create_litellm_model):
        """When RLM_LITELLM_WORKER_TIER is unset, 'worker' tier should be used."""
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        monkeypatch.delenv("RLM_LITELLM_WORKER_TIER", raising=False)

        calls: list[tuple] = []
        original_mock = _mock_create_litellm_model

        def _capture_create(*args, **kwargs):
            calls.append(args)
            return original_mock

        monkeypatch.setattr(
            "rlm_adk.models.litellm_router.create_litellm_model",
            _capture_create,
        )

        from rlm_adk.agent import create_rlm_orchestrator

        create_rlm_orchestrator("reasoning")
        # The worker pool should have been created with the worker tier
        worker_calls = [c for c in calls if c and c[0] == "worker"]
        assert len(worker_calls) >= 1, (
            f"Expected at least one create_litellm_model('worker') call, got: {calls}"
        )

    def test_worker_tier_from_env(self, monkeypatch, _mock_create_litellm_model):
        """RLM_LITELLM_WORKER_TIER should override the default 'worker' tier."""
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        monkeypatch.setenv("RLM_LITELLM_WORKER_TIER", "fast-worker")

        calls: list[tuple] = []
        original_mock = _mock_create_litellm_model

        def _capture_create(*args, **kwargs):
            calls.append(args)
            return original_mock

        monkeypatch.setattr(
            "rlm_adk.models.litellm_router.create_litellm_model",
            _capture_create,
        )

        from rlm_adk.agent import create_rlm_orchestrator

        create_rlm_orchestrator("reasoning")
        worker_calls = [c for c in calls if c and c[0] == "fast-worker"]
        assert len(worker_calls) >= 1, (
            f"Expected at least one create_litellm_model('fast-worker') call, got: {calls}"
        )

    def test_no_worker_pool_override_when_litellm_off(self, monkeypatch):
        """When LiteLLM is off, create_rlm_orchestrator should use default WorkerPool."""
        monkeypatch.delenv("RLM_ADK_LITELLM", raising=False)

        from rlm_adk.agent import create_rlm_orchestrator

        result = create_rlm_orchestrator("gemini-2.5-pro")
        # worker_pool.default_model should be the plain string
        assert result.worker_pool.default_model == "gemini-2.5-pro"
        assert isinstance(result.worker_pool.default_model, str)


class TestResolveModelPassthroughPreservesLiteLLM:
    """CRIT-1: Verify LiteLlm objects pass through _resolve_model unchanged."""

    def test_litellm_object_not_double_wrapped(self, monkeypatch):
        """A LiteLlm object must pass through _resolve_model unchanged."""
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        from google.adk.models.lite_llm import LiteLlm, LiteLLMClient

        mock_client = MagicMock(spec=LiteLLMClient)
        existing = LiteLlm(model="worker", llm_client=mock_client)

        from rlm_adk.agent import _resolve_model

        result = _resolve_model(existing)
        assert result is existing

    def test_non_string_non_litellm_passes_through(self, monkeypatch):
        """Any non-string object should pass through (CRIT-1 guard)."""
        monkeypatch.setenv("RLM_ADK_LITELLM", "1")
        from rlm_adk.agent import _resolve_model

        sentinel = object()
        result = _resolve_model(sentinel)
        assert result is sentinel
