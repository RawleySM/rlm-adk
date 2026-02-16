"""PS-004 + AR-CRIT-001: State schema conformance and state delta discipline.

PS-004:
- Key names/scopes shall match declared schema (app:, temp:, user:, session).
- Values written to state should be JSON-serializable.

AR-CRIT-001:
- No direct ctx.session.state[key] = value writes in orchestrator loop.
- All orchestrator state mutations must be emitted through EventActions(state_delta=...).
"""

import ast
import json

from rlm_adk.state import (
    APP_MAX_DEPTH,
    APP_MAX_ITERATIONS,
    CACHE_HIT_COUNT,
    CACHE_LAST_HIT_KEY,
    CACHE_MISS_COUNT,
    CACHE_STORE,
    CONTEXT_COUNT,
    HISTORY_COUNT,
    OBS_ITERATION_TIMES,
    OBS_TOOL_INVOCATION_SUMMARY,
    OBS_TOTAL_CALLS,
    OBS_TOTAL_EXECUTION_TIME,
    OBS_TOTAL_INPUT_TOKENS,
    OBS_TOTAL_OUTPUT_TOKENS,
    TEMP_CURRENT_CODE_BLOCKS,
    TEMP_CURRENT_DEPTH,
    TEMP_DEPTH_GUARD_BLOCKED,
    TEMP_FINAL_ANSWER,
    TEMP_IDEMPOTENCY_KEY,
    TEMP_INVOCATION_START_TIME,
    TEMP_ITERATION_COUNT,
    TEMP_LAST_REASONING_RESPONSE,
    TEMP_LAST_REPL_RESULT,
    TEMP_MESSAGE_HISTORY,
    TEMP_POLICY_VIOLATION,
    TEMP_REASONING_CALL_START,
    TEMP_REQUEST_ID,
    TEMP_SHOULD_STOP,
    TEMP_USED_DEFAULT_ANSWER,
    TEMP_VALIDATION_ERRORS,
    TEMP_VALIDATION_PASS,
    USER_LAST_SUCCESSFUL_CALL_ID,
    context_payload_key,
    message_history_key,
    obs_model_usage_key,
)


class TestStateScopeConventions:
    """PS-004: Key scoping conventions are followed."""

    def test_app_keys_prefixed(self):
        assert APP_MAX_DEPTH.startswith("app:")
        assert APP_MAX_ITERATIONS.startswith("app:")

    def test_temp_keys_prefixed(self):
        temp_keys = [
            TEMP_CURRENT_DEPTH,
            TEMP_ITERATION_COUNT,
            TEMP_SHOULD_STOP,
            TEMP_USED_DEFAULT_ANSWER,
            TEMP_DEPTH_GUARD_BLOCKED,
            TEMP_POLICY_VIOLATION,
            TEMP_MESSAGE_HISTORY,
            TEMP_CURRENT_CODE_BLOCKS,
            TEMP_LAST_REPL_RESULT,
            TEMP_FINAL_ANSWER,
            TEMP_LAST_REASONING_RESPONSE,
            TEMP_INVOCATION_START_TIME,
            TEMP_REASONING_CALL_START,
            TEMP_VALIDATION_PASS,
            TEMP_VALIDATION_ERRORS,
            TEMP_REQUEST_ID,
            TEMP_IDEMPOTENCY_KEY,
        ]
        for key in temp_keys:
            assert key.startswith("temp:"), f"{key} should start with 'temp:'"

    def test_user_keys_prefixed(self):
        assert USER_LAST_SUCCESSFUL_CALL_ID.startswith("user:")

    def test_obs_keys_prefixed(self):
        obs_keys = [
            OBS_TOTAL_INPUT_TOKENS,
            OBS_TOTAL_OUTPUT_TOKENS,
            OBS_TOTAL_CALLS,
            OBS_ITERATION_TIMES,
            OBS_TOOL_INVOCATION_SUMMARY,
            OBS_TOTAL_EXECUTION_TIME,
        ]
        for key in obs_keys:
            assert key.startswith("obs:"), f"{key} should start with 'obs:'"

    def test_cache_keys_prefixed(self):
        cache_keys = [CACHE_STORE, CACHE_HIT_COUNT, CACHE_MISS_COUNT, CACHE_LAST_HIT_KEY]
        for key in cache_keys:
            assert key.startswith("cache:"), f"{key} should start with 'cache:'"

    def test_session_keys_no_prefix(self):
        """Session-scoped keys have no special prefix."""
        assert ":" not in CONTEXT_COUNT
        assert ":" not in HISTORY_COUNT


class TestDynamicKeyGenerators:
    """Dynamic key generators produce consistent patterns."""

    def test_obs_model_usage_key(self):
        key = obs_model_usage_key("gemini-2.5-flash")
        assert key == "obs:model_usage:gemini-2.5-flash"
        assert key.startswith("obs:")

    def test_context_payload_key(self):
        assert context_payload_key(0) == "context_payload_0"
        assert context_payload_key(5) == "context_payload_5"

    def test_message_history_key(self):
        assert message_history_key(0) == "message_history_0"
        assert message_history_key(3) == "message_history_3"


class TestStateValueSerializability:
    """PS-004: Values written to state should be JSON-serializable."""

    def test_typical_state_values_serializable(self):
        """Common state values must survive JSON round-trip."""
        typical_state = {
            APP_MAX_DEPTH: 2,
            APP_MAX_ITERATIONS: 30,
            TEMP_CURRENT_DEPTH: 1,
            TEMP_ITERATION_COUNT: 5,
            TEMP_SHOULD_STOP: False,
            TEMP_FINAL_ANSWER: "42",
            TEMP_MESSAGE_HISTORY: [{"role": "user", "content": "hello"}],
            CACHE_HIT_COUNT: 3,
            CACHE_MISS_COUNT: 7,
            OBS_TOTAL_CALLS: 10,
            OBS_TOTAL_INPUT_TOKENS: 1000,
            OBS_TOTAL_OUTPUT_TOKENS: 500,
        }
        serialized = json.dumps(typical_state)
        restored = json.loads(serialized)
        assert restored[APP_MAX_DEPTH] == 2
        assert restored[TEMP_FINAL_ANSWER] == "42"

    def test_model_usage_dict_serializable(self):
        usage = {"calls": 5, "input_tokens": 100, "output_tokens": 50}
        serialized = json.dumps(usage)
        restored = json.loads(serialized)
        assert restored["calls"] == 5

    def test_cache_store_entry_serializable(self):
        entry = {
            "fingerprint_abc": {
                "response": {"text": "cached answer"},
                "timestamp": 1700000000.0,
            }
        }
        serialized = json.dumps(entry)
        assert "cached answer" in serialized


class TestNoDirectStateWritesInOrchestrator:
    """AR-CRIT-001: Orchestrator must use EventActions(state_delta=...) only.

    This is a static analysis test that inspects the orchestrator source
    to verify no direct state writes occur in _run_async_impl.
    """

    def test_no_direct_state_subscript_assign_in_orchestrator(self):
        """The orchestrator must not contain ctx.session.state[...] = ... assignments."""
        import inspect
        import textwrap

        from rlm_adk.orchestrator import RLMOrchestratorAgent

        source = textwrap.dedent(inspect.getsource(RLMOrchestratorAgent._run_async_impl))

        # Parse AST and look for subscript assignments to ctx.session.state
        tree = ast.parse(source)
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if _is_state_subscript(target):
                        violations.append(ast.dump(target))

        assert violations == [], (
            f"AR-CRIT-001 violation: direct state writes found in orchestrator: {violations}"
        )


def _is_state_subscript(node: ast.AST) -> bool:
    """Check if AST node is a subscript assignment to *.state[...]."""
    if not isinstance(node, ast.Subscript):
        return False
    value = node.value
    if isinstance(value, ast.Attribute) and value.attr == "state":
        return True
    return False
