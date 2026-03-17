"""Integration tests for the RLM ADK Artifact Service.

Tests covering:
- FR-001: Runner factory accepts artifact_service parameter
- FR-008: ObservabilityPlugin tracks artifact events
- NFR-005: Backward compatibility
"""

from unittest.mock import MagicMock

import pytest

from rlm_adk.plugins.observability import ObservabilityPlugin


# ---------------------------------------------------------------------------
# Phase 4: Runner Integration (FR-001)
# ---------------------------------------------------------------------------

class TestRunnerArtifactService:
    """FR-001: create_rlm_runner accepts optional artifact_service parameter."""

    def test_create_rlm_runner_accepts_artifact_service(self):
        """Runner factory accepts a custom artifact_service."""
        from google.adk.artifacts import InMemoryArtifactService
        from rlm_adk.agent import create_rlm_runner
        service = InMemoryArtifactService()
        runner = create_rlm_runner(
            model="gemini-2.5-flash",
            artifact_service=service,
        )
        assert runner is not None
        assert runner.artifact_service is service

    def test_create_rlm_runner_without_artifact_service(self):
        """Runner factory works without artifact_service (backward compat, NFR-005)."""
        from rlm_adk.agent import create_rlm_runner
        runner = create_rlm_runner(model="gemini-2.5-flash")
        assert runner is not None
        # InMemoryRunner creates its own InMemoryArtifactService by default
        assert runner.artifact_service is not None

    def test_create_rlm_runner_none_artifact_service_uses_default(self):
        """Passing None explicitly still gets default InMemoryArtifactService."""
        from rlm_adk.agent import create_rlm_runner
        runner = create_rlm_runner(model="gemini-2.5-flash", artifact_service=None)
        assert runner is not None
        assert runner.artifact_service is not None


# ---------------------------------------------------------------------------
# Phase 5: Plugin Integration (FR-008, FR-009)
# ---------------------------------------------------------------------------

def _make_invocation_context(state=None):
    ctx = MagicMock()
    ctx.session.state = state if state is not None else {}
    return ctx


def _make_event_with_artifact_delta(artifact_delta, author="orchestrator"):
    event = MagicMock()
    event.actions.state_delta = {}
    event.actions.artifact_delta = artifact_delta
    event.author = author
    return event


def _make_event_with_state_delta(state_delta, author="orchestrator"):
    event = MagicMock()
    event.actions.state_delta = state_delta
    event.actions.artifact_delta = {}
    event.author = author
    return event


class TestObservabilityArtifactTracking:
    """FR-008: ObservabilityPlugin tracks artifact events."""

    async def test_on_event_tracks_artifact_delta(self):
        """on_event_callback detects artifact_delta and accumulates on plugin instance."""
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_invocation_context(state)
        event = _make_event_with_artifact_delta({"report.pdf": 0})

        await plugin.on_event_callback(invocation_context=ctx, event=event)

        # AR-CRIT-001: accumulated on plugin instance, not session state
        assert plugin._artifact_saves_acc == 1

    async def test_on_event_tracks_multiple_artifact_deltas(self):
        """Multiple artifacts in one event are all counted."""
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_invocation_context(state)
        event = _make_event_with_artifact_delta({"a.txt": 0, "b.txt": 0})

        await plugin.on_event_callback(invocation_context=ctx, event=event)

        assert plugin._artifact_saves_acc == 2

    async def test_on_event_accumulates_across_events(self):
        """Artifact save count accumulates across multiple events."""
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_invocation_context(state)

        event1 = _make_event_with_artifact_delta({"a.txt": 0})
        event2 = _make_event_with_artifact_delta({"b.txt": 0})

        await plugin.on_event_callback(invocation_context=ctx, event=event1)
        await plugin.on_event_callback(invocation_context=ctx, event=event2)

        assert plugin._artifact_saves_acc == 2

    async def test_after_run_includes_artifact_stats(self):
        """after_run_callback logs artifact stats if present."""
        plugin = ObservabilityPlugin()
        # Simulate prior accumulation from on_event_callback
        plugin._artifact_saves_acc = 3
        state = {
            "obs:artifact_bytes_saved": 15000,
        }
        ctx = _make_invocation_context(state)

        # Should not raise
        await plugin.after_run_callback(invocation_context=ctx)

    async def test_on_event_no_artifact_delta(self):
        """Events without artifact_delta do not affect artifact tracking."""
        plugin = ObservabilityPlugin()
        state = {}
        ctx = _make_invocation_context(state)
        event = _make_event_with_state_delta({"iteration_count": 1})

        await plugin.on_event_callback(invocation_context=ctx, event=event)

        assert plugin._artifact_saves_acc == 0


