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
TEMP_POLICY_VIOLATION = "temp:policy_violation"

# REPL Execution Keys
TEMP_MESSAGE_HISTORY = "temp:message_history"
TEMP_CURRENT_CODE_BLOCKS = "temp:current_code_blocks"
TEMP_LAST_REPL_RESULT = "temp:last_repl_result"
TEMP_FINAL_ANSWER = "temp:final_answer"
TEMP_LAST_REASONING_RESPONSE = "temp:last_reasoning_response"

# Persistence Keys
HISTORY_COUNT = "history_count"
# message_history_{N} are dynamic

# Context Metadata Keys (invocation-scoped, used by callbacks/observability)
TEMP_REPO_URL = "temp:repo_url"
TEMP_ROOT_PROMPT = "temp:root_prompt"

# Dynamic Instruction State Keys (session-scoped for ADK instruction template resolution)
# These match the {var?} placeholders in RLM_DYNAMIC_INSTRUCTION so ADK can
# resolve them at runtime via its built-in state variable injection.
DYN_REPO_URL = "repo_url"
DYN_ROOT_PROMPT = "root_prompt"

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
OBS_PER_ITERATION_TOKEN_BREAKDOWN = "obs:per_iteration_token_breakdown"
TEMP_INVOCATION_START_TIME = "temp:invocation_start_time"
TEMP_REASONING_CALL_START = "temp:reasoning_call_start"

# Per-Invocation Token Accounting Keys (temp-scoped)
TEMP_REASONING_PROMPT_CHARS = "temp:reasoning_prompt_chars"
TEMP_REASONING_SYSTEM_CHARS = "temp:reasoning_system_chars"
TEMP_REASONING_HISTORY_MSG_COUNT = "temp:reasoning_history_msg_count"
TEMP_REASONING_CONTENT_COUNT = "temp:reasoning_content_count"
TEMP_REASONING_INPUT_TOKENS = "temp:reasoning_input_tokens"
TEMP_REASONING_OUTPUT_TOKENS = "temp:reasoning_output_tokens"
TEMP_WORKER_PROMPT_CHARS = "temp:worker_prompt_chars"
TEMP_WORKER_CONTENT_COUNT = "temp:worker_content_count"
TEMP_WORKER_INPUT_TOKENS = "temp:worker_input_tokens"
TEMP_WORKER_OUTPUT_TOKENS = "temp:worker_output_tokens"
TEMP_CONTEXT_WINDOW_SNAPSHOT = "temp:context_window_snapshot"

# Type Validation Keys
TEMP_VALIDATION_PASS = "temp:validation_pass"
TEMP_VALIDATION_ERRORS = "temp:validation_errors"
OBS_VALIDATION_FAIL_COUNT = "obs:validation_fail_count"

# Worker Dispatch Lifecycle Keys (invocation-scoped)
TEMP_WORKER_DISPATCH_COUNT = "temp:worker_dispatch_count"
TEMP_WORKER_RESULTS_COMMITTED = "temp:worker_results_committed"
TEMP_WORKER_DIRTY_READ_COUNT = "temp:worker_dirty_read_count"
TEMP_WORKER_EVENTS_DRAINED = "temp:worker_events_drained"

# Worker Dispatch Timing Keys (session-scoped for cross-invocation tracking)
OBS_WORKER_DISPATCH_LATENCY_MS = "obs:worker_dispatch_latency_ms"
OBS_WORKER_TOTAL_DISPATCHES = "obs:worker_total_dispatches"
OBS_WORKER_TOTAL_BATCH_DISPATCHES = "obs:worker_total_batch_dispatches"
OBS_WORKER_DIRTY_READ_MISMATCHES = "obs:worker_dirty_read_mismatches"

# API/Messaging Keys
TEMP_REQUEST_ID = "temp:request_id"
TEMP_IDEMPOTENCY_KEY = "temp:idempotency_key"
USER_LAST_SUCCESSFUL_CALL_ID = "user:last_successful_call_id"


def obs_worker_dispatch_key(worker_name: str) -> str:
    """Generate the observability key for a specific worker's dispatch timing."""
    return f"obs:worker_dispatch:{worker_name}"


def obs_model_usage_key(model_name: str) -> str:
    """Generate the observability key for a specific model's usage stats."""
    return f"obs:model_usage:{model_name}"


def message_history_key(index: int) -> str:
    """Generate the session state key for a message history."""
    return f"message_history_{index}"
