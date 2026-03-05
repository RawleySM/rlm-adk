"""Tests for Phase 1: Key Dedup + Dead Code Removal.

Validates that:
- flush_fn() delta dict uses only canonical OBS_CHILD_* keys (no OBS_WORKER_* duplicates)
- Deleted constants raise ImportError when imported from rlm_adk.state
"""

import importlib
import pytest


class TestFlushFnCanonicalKeys:
    """flush_fn() must emit only canonical OBS_CHILD_* keys, not OBS_WORKER_* duplicates."""

    @pytest.fixture
    def flush_fn(self):
        """Create a flush_fn via create_dispatch_closures with minimal setup."""
        from unittest.mock import MagicMock

        from rlm_adk.dispatch import DispatchConfig, create_dispatch_closures

        config = DispatchConfig(default_model="test-model")
        ctx = MagicMock()
        ctx.session.state = {}

        _, _, flush = create_dispatch_closures(config, ctx)
        return flush

    def test_no_worker_dispatch_count_in_delta(self, flush_fn):
        delta = flush_fn()
        assert "worker_dispatch_count" not in delta

    def test_no_obs_worker_total_dispatches_in_delta(self, flush_fn):
        delta = flush_fn()
        assert "obs:worker_total_dispatches" not in delta

    def test_no_obs_worker_dispatch_latency_ms_in_delta(self, flush_fn):
        delta = flush_fn()
        assert "obs:worker_dispatch_latency_ms" not in delta

    def test_no_obs_worker_total_batch_dispatches_in_delta(self, flush_fn):
        delta = flush_fn()
        assert "obs:worker_total_batch_dispatches" not in delta

    def test_no_obs_worker_error_counts_in_delta(self, flush_fn):
        delta = flush_fn()
        assert "obs:worker_error_counts" not in delta

    def test_has_obs_child_dispatch_count(self, flush_fn):
        delta = flush_fn()
        assert "obs:child_dispatch_count" in delta

    def test_has_obs_child_dispatch_latency_ms(self, flush_fn):
        delta = flush_fn()
        assert "obs:child_dispatch_latency_ms" in delta


class TestDeletedConstantsRaiseImportError:
    """Fully removed constants must not be importable from rlm_adk.state."""

    @pytest.mark.parametrize("name", [
        "OBS_WORKER_TIMEOUT_COUNT",
        "OBS_WORKER_RATE_LIMIT_COUNT",
        "OBS_WORKER_POOL_EXHAUSTION_COUNT",
        "OBS_CHILD_SUMMARY_PREFIX",
        "OBS_ARTIFACT_LOADS",
        "OBS_ARTIFACT_DELETES",
        "OBS_ARTIFACT_SAVE_LATENCY_MS",
        "OBS_WORKER_ERROR_COUNTS",
        "OBS_WORKER_TOTAL_BATCH_DISPATCHES",
    ])
    def test_removed_constant_not_importable(self, name):
        import rlm_adk.state as mod
        importlib.reload(mod)
        assert not hasattr(mod, name), (
            f"{name} should have been removed from rlm_adk.state"
        )
