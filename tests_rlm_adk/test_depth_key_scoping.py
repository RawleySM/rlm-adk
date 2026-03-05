import pytest
from rlm_adk.state import (
    depth_key, DEPTH_SCOPED_KEYS,
    MESSAGE_HISTORY, ITERATION_COUNT, FINAL_ANSWER,
    LAST_REPL_RESULT, SHOULD_STOP,
)
# Import some global keys that should NOT be in DEPTH_SCOPED_KEYS
from rlm_adk.state import OBS_TOTAL_INPUT_TOKENS, OBS_CHILD_DISPATCH_COUNT, CACHE_HIT_COUNT


class TestDepthKeyFunction:
    def test_depth_zero_returns_original_key(self):
        assert depth_key("message_history", 0) == "message_history"

    def test_depth_nonzero_returns_suffixed_key(self):
        assert depth_key("message_history", 2) == "message_history@d2"

    def test_all_scoped_keys_unchanged_at_depth_zero(self):
        for key in DEPTH_SCOPED_KEYS:
            assert depth_key(key, 0) == key

    def test_global_keys_not_in_scoped_set(self):
        for key in [OBS_TOTAL_INPUT_TOKENS, OBS_CHILD_DISPATCH_COUNT, CACHE_HIT_COUNT]:
            assert key not in DEPTH_SCOPED_KEYS


class TestDepthKeyIntegration:
    def test_two_depths_write_independent_values(self):
        state = {}
        state[depth_key(MESSAGE_HISTORY, 0)] = ["msg_a"]
        state[depth_key(MESSAGE_HISTORY, 1)] = ["msg_b"]
        assert state["message_history"] == ["msg_a"]
        assert state["message_history@d1"] == ["msg_b"]
