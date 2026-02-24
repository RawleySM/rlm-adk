"""State key constants for the RLM ADK application.

ADK state key prefix scoping:
- (none): Session scope - persists within session
- user: : User scope - persists across sessions for same user
- app: : Application scope - persists across all users/sessions

Note: cache: and obs: prefixes are naming conventions only (session-scoped).
"""

# Flow Control Keys
APP_MAX_DEPTH = "app:max_depth"
APP_MAX_ITERATIONS = "app:max_iterations"
CURRENT_DEPTH = "current_depth"
ITERATION_COUNT = "iteration_count"
SHOULD_STOP = "should_stop"
POLICY_VIOLATION = "policy_violation"

# REPL Execution Keys
MESSAGE_HISTORY = "message_history"
CURRENT_CODE_BLOCKS = "current_code_blocks"
LAST_REPL_RESULT = "last_repl_result"
FINAL_ANSWER = "final_answer"
LAST_REASONING_RESPONSE = "last_reasoning_response"

# Persistence Keys
HISTORY_COUNT = "history_count"
# message_history_{N} are dynamic

# Context Metadata Keys (used by callbacks/observability)
REPO_URL = "repo_url"
ROOT_PROMPT = "root_prompt"

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
INVOCATION_START_TIME = "invocation_start_time"
REASONING_CALL_START = "reasoning_call_start"

# Per-Invocation Token Accounting Keys
REASONING_PROMPT_CHARS = "reasoning_prompt_chars"
REASONING_SYSTEM_CHARS = "reasoning_system_chars"
REASONING_HISTORY_MSG_COUNT = "reasoning_history_msg_count"
REASONING_CONTENT_COUNT = "reasoning_content_count"
REASONING_INPUT_TOKENS = "reasoning_input_tokens"
REASONING_OUTPUT_TOKENS = "reasoning_output_tokens"
# Worker accounting keys use temp: prefix (scoped to current invocation,
# discarded after).  Values are aggregated from worker objects in the
# dispatch closure — no longer list-appended in callbacks.
WORKER_PROMPT_CHARS = "temp:worker_prompt_chars"
WORKER_CONTENT_COUNT = "temp:worker_content_count"
WORKER_INPUT_TOKENS = "temp:worker_input_tokens"
WORKER_OUTPUT_TOKENS = "temp:worker_output_tokens"
CONTEXT_WINDOW_SNAPSHOT = "context_window_snapshot"

# Type Validation Keys
VALIDATION_PASS = "validation_pass"
VALIDATION_ERRORS = "validation_errors"
OBS_VALIDATION_FAIL_COUNT = "obs:validation_fail_count"

# Worker Dispatch Lifecycle Keys (temp: scoped to current invocation)
WORKER_DISPATCH_COUNT = "temp:worker_dispatch_count"
WORKER_RESULTS_COMMITTED = "temp:worker_results_committed"
WORKER_DIRTY_READ_COUNT = "temp:worker_dirty_read_count"
WORKER_EVENTS_DRAINED = "temp:worker_events_drained"

# Worker Dispatch Timing Keys (temp: scoped to current invocation)
OBS_WORKER_DISPATCH_LATENCY_MS = "temp:obs_worker_dispatch_latency_ms"
OBS_WORKER_TOTAL_DISPATCHES = "temp:obs_worker_total_dispatches"
OBS_WORKER_TOTAL_BATCH_DISPATCHES = "temp:obs_worker_total_batch_dispatches"
OBS_WORKER_DIRTY_READ_MISMATCHES = "temp:obs_worker_dirty_read_mismatches"

# API/Messaging Keys
REQUEST_ID = "request_id"
IDEMPOTENCY_KEY = "idempotency_key"
USER_LAST_SUCCESSFUL_CALL_ID = "user:last_successful_call_id"

# Artifact Tracking Keys (session-scoped)
ARTIFACT_SAVE_COUNT = "artifact_save_count"
ARTIFACT_LOAD_COUNT = "artifact_load_count"
ARTIFACT_TOTAL_BYTES_SAVED = "artifact_total_bytes_saved"
ARTIFACT_LAST_SAVED_FILENAME = "artifact_last_saved_filename"
ARTIFACT_LAST_SAVED_VERSION = "artifact_last_saved_version"

# Artifact Observability Keys (session-scoped)
OBS_ARTIFACT_SAVES = "obs:artifact_saves"
OBS_ARTIFACT_LOADS = "obs:artifact_loads"
OBS_ARTIFACT_DELETES = "obs:artifact_deletes"
OBS_ARTIFACT_BYTES_SAVED = "obs:artifact_bytes_saved"
OBS_ARTIFACT_SAVE_LATENCY_MS = "obs:artifact_save_latency_ms"

# Artifact Configuration Keys (app-scoped)
APP_ARTIFACT_OFFLOAD_THRESHOLD = "app:artifact_offload_threshold"

# Migration Tracking Keys (app-scoped)
MIGRATION_LAST_MIGRATED_SESSION = "app:migration_last_migrated_session"
MIGRATION_LAST_MIGRATED_TIME = "app:migration_last_migrated_time"
MIGRATION_TOTAL_MIGRATED = "app:migration_total_migrated"

# Migration Status Keys (session-scoped, naming convention only)
MIGRATION_STATUS = "migration:status"
MIGRATION_TIMESTAMP = "migration:timestamp"
MIGRATION_ERROR = "migration:error"


def obs_worker_dispatch_key(worker_name: str) -> str:
    """Generate the observability key for a specific worker's dispatch timing."""
    return f"obs:worker_dispatch:{worker_name}"


def obs_model_usage_key(model_name: str) -> str:
    """Generate the observability key for a specific model's usage stats."""
    return f"obs:model_usage:{model_name}"


def message_history_key(index: int) -> str:
    """Generate the session state key for a message history."""
    return f"message_history_{index}"
