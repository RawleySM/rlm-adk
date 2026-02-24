"""Tests for temp: prefix migration of worker dispatch and token accounting keys.

Worker dispatch lifecycle keys and worker token accounting keys must use the
temp: prefix to scope them to the current invocation and prevent them from
persisting across invocations (which would cause stale data accumulation).
"""

from rlm_adk.state import (
    WORKER_DISPATCH_COUNT,
    WORKER_RESULTS_COMMITTED,
    WORKER_DIRTY_READ_COUNT,
    WORKER_EVENTS_DRAINED,
    OBS_WORKER_DISPATCH_LATENCY_MS,
    OBS_WORKER_TOTAL_DISPATCHES,
    OBS_WORKER_TOTAL_BATCH_DISPATCHES,
    OBS_WORKER_DIRTY_READ_MISMATCHES,
    WORKER_PROMPT_CHARS,
    WORKER_CONTENT_COUNT,
    WORKER_INPUT_TOKENS,
    WORKER_OUTPUT_TOKENS,
)


class TestWorkerDispatchKeysUseTempPrefix:
    """Worker dispatch lifecycle keys must use temp: prefix."""

    def test_worker_dispatch_count_temp(self):
        assert WORKER_DISPATCH_COUNT.startswith("temp:"), (
            f"WORKER_DISPATCH_COUNT should start with 'temp:', got '{WORKER_DISPATCH_COUNT}'"
        )

    def test_worker_results_committed_temp(self):
        assert WORKER_RESULTS_COMMITTED.startswith("temp:"), (
            f"WORKER_RESULTS_COMMITTED should start with 'temp:', got '{WORKER_RESULTS_COMMITTED}'"
        )

    def test_worker_dirty_read_count_temp(self):
        assert WORKER_DIRTY_READ_COUNT.startswith("temp:"), (
            f"WORKER_DIRTY_READ_COUNT should start with 'temp:', got '{WORKER_DIRTY_READ_COUNT}'"
        )

    def test_worker_events_drained_temp(self):
        assert WORKER_EVENTS_DRAINED.startswith("temp:"), (
            f"WORKER_EVENTS_DRAINED should start with 'temp:', got '{WORKER_EVENTS_DRAINED}'"
        )


class TestWorkerObsKeysUseTempPrefix:
    """Worker observability keys must use temp: prefix."""

    def test_obs_worker_dispatch_latency_ms_temp(self):
        assert OBS_WORKER_DISPATCH_LATENCY_MS.startswith("temp:"), (
            f"OBS_WORKER_DISPATCH_LATENCY_MS should start with 'temp:', got '{OBS_WORKER_DISPATCH_LATENCY_MS}'"
        )

    def test_obs_worker_total_dispatches_temp(self):
        assert OBS_WORKER_TOTAL_DISPATCHES.startswith("temp:"), (
            f"OBS_WORKER_TOTAL_DISPATCHES should start with 'temp:', got '{OBS_WORKER_TOTAL_DISPATCHES}'"
        )

    def test_obs_worker_total_batch_dispatches_temp(self):
        assert OBS_WORKER_TOTAL_BATCH_DISPATCHES.startswith("temp:"), (
            f"OBS_WORKER_TOTAL_BATCH_DISPATCHES should start with 'temp:', got '{OBS_WORKER_TOTAL_BATCH_DISPATCHES}'"
        )

    def test_obs_worker_dirty_read_mismatches_temp(self):
        assert OBS_WORKER_DIRTY_READ_MISMATCHES.startswith("temp:"), (
            f"OBS_WORKER_DIRTY_READ_MISMATCHES should start with 'temp:', got '{OBS_WORKER_DIRTY_READ_MISMATCHES}'"
        )


class TestWorkerTokenKeysUseTempPrefix:
    """Worker token accounting keys must use temp: prefix."""

    def test_worker_prompt_chars_temp(self):
        assert WORKER_PROMPT_CHARS.startswith("temp:"), (
            f"WORKER_PROMPT_CHARS should start with 'temp:', got '{WORKER_PROMPT_CHARS}'"
        )

    def test_worker_content_count_temp(self):
        assert WORKER_CONTENT_COUNT.startswith("temp:"), (
            f"WORKER_CONTENT_COUNT should start with 'temp:', got '{WORKER_CONTENT_COUNT}'"
        )

    def test_worker_input_tokens_temp(self):
        assert WORKER_INPUT_TOKENS.startswith("temp:"), (
            f"WORKER_INPUT_TOKENS should start with 'temp:', got '{WORKER_INPUT_TOKENS}'"
        )

    def test_worker_output_tokens_temp(self):
        assert WORKER_OUTPUT_TOKENS.startswith("temp:"), (
            f"WORKER_OUTPUT_TOKENS should start with 'temp:', got '{WORKER_OUTPUT_TOKENS}'"
        )
