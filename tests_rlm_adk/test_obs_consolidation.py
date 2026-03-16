"""Tests for ObservabilityPlugin consolidation (Phases 2+3).

Phase 2: ObservabilityPlugin enhancement — new summary fields, verbose flag,
          ephemeral re-persist for child summaries and context snapshots.
Phase 3: DebugLoggingPlugin removal — plugin deleted, imports fail,
          _default_plugins no longer has debug parameter.
"""

import inspect
import logging
from unittest.mock import MagicMock

import pytest

from rlm_adk.state import (
    CONTEXT_WINDOW_SNAPSHOT,
    FINAL_ANSWER,
    LAST_REPL_RESULT,
    OBS_ARTIFACT_BYTES_SAVED,
    OBS_ARTIFACT_SAVES,
    OBS_CHILD_DISPATCH_LATENCY_MS,
    OBS_CHILD_TOTAL_BATCH_DISPATCHES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_invocation_context(state=None):
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _make_callback_context(state=None):
    ctx = MagicMock()
    ctx.state = state if state is not None else {}
    ctx._invocation_context.session.state = ctx.state
    return ctx


# ---------------------------------------------------------------------------
# Phase 2: ObservabilityPlugin enhancement
# ---------------------------------------------------------------------------

class TestObsAfterRunDispatchLatency:
    """after_run_callback should log dispatch latency stats."""

    @pytest.mark.asyncio
    async def test_after_run_logs_dispatch_latency(self, caplog):
        from rlm_adk.plugins.observability import ObservabilityPlugin

        plugin = ObservabilityPlugin()
        state = {
            OBS_CHILD_DISPATCH_LATENCY_MS: [100.5, 200.3],
        }
        ctx = _make_invocation_context(state)

        with caplog.at_level(logging.INFO):
            await plugin.after_run_callback(invocation_context=ctx)

        log_text = caplog.text
        # Should contain latency stats (min/max/mean)
        assert "latency" in log_text.lower() or "dispatch_latency" in log_text.lower(), (
            f"Expected latency stats in log output, got: {log_text}"
        )


class TestObsAfterRunBatchDispatches:
    """after_run_callback should log batch dispatch count."""

    @pytest.mark.asyncio
    async def test_after_run_logs_batch_dispatches(self, caplog):
        from rlm_adk.plugins.observability import ObservabilityPlugin

        plugin = ObservabilityPlugin()
        state = {
            OBS_CHILD_TOTAL_BATCH_DISPATCHES: 3,
        }
        ctx = _make_invocation_context(state)

        with caplog.at_level(logging.INFO):
            await plugin.after_run_callback(invocation_context=ctx)

        log_text = caplog.text
        assert "batch_dispatches=3" in log_text, (
            f"Expected batch_dispatches=3 in log, got: {log_text}"
        )


class TestObsAfterRunAnswerLen:
    """after_run_callback should log answer_len."""

    @pytest.mark.asyncio
    async def test_after_run_logs_answer_len(self, caplog):
        from rlm_adk.plugins.observability import ObservabilityPlugin

        plugin = ObservabilityPlugin()
        state = {
            FINAL_ANSWER: "hello world",
        }
        ctx = _make_invocation_context(state)

        with caplog.at_level(logging.INFO):
            await plugin.after_run_callback(invocation_context=ctx)

        log_text = caplog.text
        assert "answer_len=11" in log_text, (
            f"Expected answer_len=11 in log, got: {log_text}"
        )


class TestObsAfterRunArtifactStats:
    """after_run_callback should log artifact stats."""

    @pytest.mark.asyncio
    async def test_after_run_logs_artifact_stats(self, caplog):
        from rlm_adk.plugins.observability import ObservabilityPlugin

        plugin = ObservabilityPlugin()
        # AR-CRIT-001: artifact saves are accumulated on the plugin instance
        plugin._artifact_saves_acc = 2
        state = {
            OBS_ARTIFACT_BYTES_SAVED: 4096,
        }
        ctx = _make_invocation_context(state)

        with caplog.at_level(logging.INFO):
            await plugin.after_run_callback(invocation_context=ctx)

        log_text = caplog.text
        assert "artifact_saves=2" in log_text
        assert "artifact_bytes=4096" in log_text


class TestObsChildSummaryRePersist:
    """obs:child_summary@* keys must survive in persisted state."""

    @pytest.mark.asyncio
    async def test_child_summary_prefix_in_ephemeral_repersist(self):
        from rlm_adk.plugins.observability import ObservabilityPlugin

        plugin = ObservabilityPlugin()
        state = {}
        session_state = {"obs:child_summary@d1f0": "some summary"}
        ctx = _make_callback_context(state)
        ctx._invocation_context.session.state = session_state

        agent = MagicMock()
        await plugin.after_agent_callback(agent=agent, callback_context=ctx)

        assert state.get("obs:child_summary@d1f0") == "some summary"


class TestObsContextWindowRePersist:
    """CONTEXT_WINDOW_SNAPSHOT must survive in persisted state."""

    @pytest.mark.asyncio
    async def test_context_window_snapshot_repersisted(self):
        from rlm_adk.plugins.observability import ObservabilityPlugin

        plugin = ObservabilityPlugin()
        state = {}
        session_state = {CONTEXT_WINDOW_SNAPSHOT: {"tokens": 1000}}
        ctx = _make_callback_context(state)
        ctx._invocation_context.session.state = session_state

        agent = MagicMock()
        await plugin.after_agent_callback(agent=agent, callback_context=ctx)

        assert state.get(CONTEXT_WINDOW_SNAPSHOT) == {"tokens": 1000}


class TestObsVerboseFlag:
    """verbose=True should print summary to stdout with [RLM] prefix."""

    @pytest.mark.asyncio
    async def test_verbose_prints_to_stdout(self, capsys, caplog):
        from rlm_adk.plugins.observability import ObservabilityPlugin

        plugin = ObservabilityPlugin(verbose=True)
        state = {
            FINAL_ANSWER: "test answer",
        }
        ctx = _make_invocation_context(state)

        with caplog.at_level(logging.INFO):
            await plugin.after_run_callback(invocation_context=ctx)

        captured = capsys.readouterr()
        assert "[RLM]" in captured.out, (
            f"Expected [RLM] prefix in stdout, got: {captured.out}"
        )


# ---------------------------------------------------------------------------
# Phase 3: DebugLoggingPlugin removal
# ---------------------------------------------------------------------------

class TestDebugLoggingPluginRemoved:
    """DebugLoggingPlugin should no longer be importable."""

    def test_debug_logging_plugin_not_importable(self):
        with pytest.raises(ImportError):
            from rlm_adk.plugins.debug_logging import DebugLoggingPlugin  # noqa: F401

    def test_debug_logging_not_in_plugin_exports(self):
        with pytest.raises(ImportError):
            from rlm_adk.plugins import DebugLoggingPlugin  # noqa: F401


class TestDefaultPluginsNoDebugParam:
    """_default_plugins should not have a debug parameter."""

    def test_default_plugins_no_debug_param(self):
        from rlm_adk.agent import _default_plugins

        sig = inspect.signature(_default_plugins)
        assert "debug" not in sig.parameters, (
            f"Expected no 'debug' parameter, but found: {list(sig.parameters.keys())}"
        )
