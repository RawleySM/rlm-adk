"""Tests for step-mode state key constants."""

import pytest

from rlm_adk.state import (
    EXPOSED_STATE_KEYS,
    STEP_MODE_ADVANCE_COUNT,
    STEP_MODE_ENABLED,
    STEP_MODE_PAUSED_AGENT,
    STEP_MODE_PAUSED_DEPTH,
)


@pytest.mark.provider_fake_contract
def test_step_mode_enabled_value():
    assert STEP_MODE_ENABLED == "step:mode_enabled"


@pytest.mark.provider_fake_contract
def test_step_mode_paused_agent_value():
    assert STEP_MODE_PAUSED_AGENT == "step:paused_agent"


@pytest.mark.provider_fake_contract
def test_step_mode_paused_depth_value():
    assert STEP_MODE_PAUSED_DEPTH == "step:paused_depth"


@pytest.mark.provider_fake_contract
def test_step_mode_advance_count_value():
    assert STEP_MODE_ADVANCE_COUNT == "step:advance_count"


@pytest.mark.provider_fake_contract
def test_step_mode_enabled_in_exposed_state_keys():
    assert STEP_MODE_ENABLED in EXPOSED_STATE_KEYS
