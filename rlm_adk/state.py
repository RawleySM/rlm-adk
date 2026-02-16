"""State key constants for the RLM ADK application.

ADK state key prefix scoping:
- (none): Session scope - persists within session
- user: : User scope - persists across sessions for same user
- app: : Application scope - persists across all users/sessions
- temp: : Invocation scope - discarded after invocation

Note: cache: and obs: prefixes are naming conventions only (session-scoped).
"""

# Flow Control Keys
APP_MAX_DEPTH = "app:max_depth"
APP_MAX_ITERATIONS = "app:max_iterations"
TEMP_CURRENT_DEPTH = "temp:current_depth"
TEMP_ITERATION_COUNT = "temp:iteration_count"
TEMP_SHOULD_STOP = "temp:should_stop"
TEMP_USED_DEFAULT_ANSWER = "temp:used_default_answer"
TEMP_DEPTH_GUARD_BLOCKED = "temp:depth_guard_blocked"
TEMP_POLICY_VIOLATION = "temp:policy_violation"

# REPL Execution Keys
TEMP_MESSAGE_HISTORY = "temp:message_history"
TEMP_CURRENT_CODE_BLOCKS = "temp:current_code_blocks"
TEMP_LAST_REPL_RESULT = "temp:last_repl_result"
TEMP_FINAL_ANSWER = "temp:final_answer"
TEMP_LAST_REASONING_RESPONSE = "temp:last_reasoning_response"

# Context and Persistence Keys
CONTEXT_COUNT = "context_count"
HISTORY_COUNT = "history_count"
# context_payload_{N} and message_history_{N} are dynamic

# Caching Keys (session-scoped despite : separator)
CACHE_STORE = "cache:store"
CACHE_HIT_COUNT = "cache:hit_count"
CACHE_MISS_COUNT = "cache:miss_count"
CACHE_LAST_HIT_KEY = "cache:last_hit_key"

# Observability Keys (session-scoped)
OBS_TOTAL_INPUT_TOKENS = "obs:total_input_tokens"
OBS_TOTAL_OUTPUT_TOKENS = "obs:total_output_tokens"
OBS_TOTAL_CALLS = "obs:total_calls"
OBS_ITERATION_TIMES = "obs:iteration_times"
OBS_TOOL_INVOCATION_SUMMARY = "obs:tool_invocation_summary"
OBS_TOTAL_EXECUTION_TIME = "obs:total_execution_time"
TEMP_INVOCATION_START_TIME = "temp:invocation_start_time"
TEMP_REASONING_CALL_START = "temp:reasoning_call_start"

# Type Validation Keys
TEMP_VALIDATION_PASS = "temp:validation_pass"
TEMP_VALIDATION_ERRORS = "temp:validation_errors"
OBS_VALIDATION_FAIL_COUNT = "obs:validation_fail_count"

# API/Messaging Keys
TEMP_REQUEST_ID = "temp:request_id"
TEMP_IDEMPOTENCY_KEY = "temp:idempotency_key"
USER_LAST_SUCCESSFUL_CALL_ID = "user:last_successful_call_id"


def obs_model_usage_key(model_name: str) -> str:
    """Generate the observability key for a specific model's usage stats."""
    return f"obs:model_usage:{model_name}"


def context_payload_key(index: int) -> str:
    """Generate the session state key for a context payload."""
    return f"context_payload_{index}"


def message_history_key(index: int) -> str:
    """Generate the session state key for a message history."""
    return f"message_history_{index}"
