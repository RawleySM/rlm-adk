"""Tests that StepModePlugin is wired into the default plugin stack."""

from rlm_adk.agent import _default_plugins
from rlm_adk.plugins.observability import ObservabilityPlugin
from rlm_adk.plugins.step_mode import StepModePlugin


def test_step_mode_plugin_in_default_plugins():
    plugins = _default_plugins()
    step_plugins = [p for p in plugins if isinstance(p, StepModePlugin)]
    assert len(step_plugins) == 1


def test_step_mode_before_observability():
    plugins = _default_plugins()
    step_idx = next(i for i, p in enumerate(plugins) if isinstance(p, StepModePlugin))
    obs_idx = next(i for i, p in enumerate(plugins) if isinstance(p, ObservabilityPlugin))
    assert step_idx < obs_idx, "StepModePlugin must be registered before ObservabilityPlugin"
