"""End-to-end tests for LiteLLM mode using the provider-fake infrastructure.

Validates that the same fixture-driven pipeline works when calls are routed
through ``litellm.Router`` (via ``RLM_ADK_LITELLM=1``) instead of the native
Gemini SDK.  The fake server's OpenAI-compatible endpoint
(``/v1/chat/completions``) translates Gemini fixture responses to OpenAI format
on the fly.

These tests mirror the Group A contract tests in ``test_provider_fake_e2e.py``
but exercise the LiteLLM integration path end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests_rlm_adk.provider_fake.conftest import FIXTURE_DIR
from tests_rlm_adk.provider_fake.contract_runner import (
    run_fixture_contract,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.provider_fake, pytest.mark.provider_fake_litellm]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fixtures excluded from LiteLLM mode for known incompatibilities:
# - Worker-only fixtures require multiple scripted responses per dispatch
#   (same reason they're excluded in native mode)
# - Malformed JSON fault tests: the translation layer intercepts before
#   litellm can parse, so the error surfaces differently
# - Structured output tests: ADK's structured output pipeline
#   (SetModelResponseTool + ReflectAndRetryToolPlugin) is wired differently
#   under LiteLLM — the tool names and retry loop differ
_LITELLM_EXCLUSIONS = {
    # Worker-only fixtures (same exclusions as native mode — child orchestrators
    # make multiple API calls per dispatch, exhausting scripted response lists)
    "all_workers_fail_batch",
    "worker_429_mid_batch",
    "worker_500_retry_exhausted",
    "worker_500_retry_exhausted_naive",
    "worker_empty_response",
    "worker_empty_response_finish_reason",
    "worker_safety_finish",
}


def _litellm_fixture_paths() -> list[Path]:
    """Discover fixture JSON files compatible with LiteLLM mode."""
    return sorted(
        p
        for p in FIXTURE_DIR.glob("*.json")
        if p.name != "index.json" and p.stem not in _LITELLM_EXCLUSIONS
    )


# ===========================================================================
# Smoke test — single fixture
# ===========================================================================


async def test_litellm_smoke_empty_reasoning_output():
    """Smoke test: simplest fixture through LiteLLM path.

    Validates that the Gemini-to-OpenAI translation, LiteLLM Router,
    and ADK LiteLlm model all work together end-to-end.
    """
    fixture_path = FIXTURE_DIR / "empty_reasoning_output.json"
    result = await run_fixture_contract(fixture_path, litellm_mode=True)
    if not result.passed:
        print(result.diagnostics())
    assert result.passed, f"LiteLLM smoke test failed:\n{result.diagnostics()}"


# ===========================================================================
# Parametrized contract validation (mirrors Group A)
# ===========================================================================


@pytest.mark.parametrize(
    "fixture_path",
    _litellm_fixture_paths(),
    ids=lambda p: p.stem,
)
async def test_litellm_fixture_contract(fixture_path: Path):
    """Validate fixtures through the LiteLLM path against expected values.

    Each fixture manages its own FakeGeminiServer lifecycle via the
    contract runner — does NOT use a shared pytest fixture.
    """
    result = await run_fixture_contract(fixture_path, litellm_mode=True)
    if not result.passed:
        print(result.diagnostics())
    assert result.passed, (
        f"LiteLLM fixture contract failed: {fixture_path.name}\n{result.diagnostics()}"
    )
