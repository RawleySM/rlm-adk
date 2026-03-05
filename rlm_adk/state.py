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
LAST_REPL_RESULT = "last_repl_result"
FINAL_ANSWER = "final_answer"

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
CONTEXT_WINDOW_SNAPSHOT = "context_window_snapshot"


# Finish Reason Tracking (written by ObservabilityPlugin)
OBS_FINISH_SAFETY_COUNT = "obs:finish_safety_count"
OBS_FINISH_RECITATION_COUNT = "obs:finish_recitation_count"
OBS_FINISH_MAX_TOKENS_COUNT = "obs:finish_max_tokens_count"


# Structured Output Observability (written by dispatch closures)
OBS_STRUCTURED_OUTPUT_FAILURES = "obs:structured_output_failures"

# Child Dispatch Observability Keys (session-scoped)
OBS_CHILD_DISPATCH_COUNT = "obs:child_dispatch_count"
OBS_CHILD_ERROR_COUNTS = "obs:child_error_counts"
OBS_CHILD_DISPATCH_LATENCY_MS = "obs:child_dispatch_latency_ms"
OBS_CHILD_TOTAL_BATCH_DISPATCHES = "obs:child_total_batch_dispatches"


def child_obs_key(depth: int, fanout_idx: int) -> str:
    """Return fanout-suffixed obs key: obs:child_summary@d{depth}f{fanout_idx}."""
    return f"obs:child_summary@d{depth}f{fanout_idx}"

# API/Messaging Keys
REQUEST_ID = "request_id"
IDEMPOTENCY_KEY = "idempotency_key"
USER_LAST_SUCCESSFUL_CALL_ID = "user:last_successful_call_id"

# Test Hook State Keys (session-scoped, written by test-only callbacks)
CB_REASONING_CONTEXT = "cb_reasoning_context"
CB_WORKER_CONTEXT = "cb_worker_context"
CB_ORCHESTRATOR_CONTEXT = "cb_orchestrator_context"
CB_TOOL_CONTEXT = "cb_tool_context"

# Artifact Tracking Keys (session-scoped)
ARTIFACT_SAVE_COUNT = "artifact_save_count"
ARTIFACT_LOAD_COUNT = "artifact_load_count"
ARTIFACT_TOTAL_BYTES_SAVED = "artifact_total_bytes_saved"
ARTIFACT_LAST_SAVED_FILENAME = "artifact_last_saved_filename"
ARTIFACT_LAST_SAVED_VERSION = "artifact_last_saved_version"

# Artifact Observability Keys (session-scoped)
OBS_ARTIFACT_SAVES = "obs:artifact_saves"
OBS_ARTIFACT_BYTES_SAVED = "obs:artifact_bytes_saved"

# Artifact Configuration Keys (app-scoped)
APP_ARTIFACT_OFFLOAD_THRESHOLD = "app:artifact_offload_threshold"

# Migration Status Keys (session-scoped, naming convention only)
MIGRATION_STATUS = "migration:status"
MIGRATION_TIMESTAMP = "migration:timestamp"
MIGRATION_ERROR = "migration:error"


DEPTH_SCOPED_KEYS: set[str] = {
    MESSAGE_HISTORY, ITERATION_COUNT,
    FINAL_ANSWER, LAST_REPL_RESULT, SHOULD_STOP,
}
# NOTE: Only iteration-local keys that need independent state per depth
# level are included. Global observability keys are excluded.


def depth_key(key: str, depth: int = 0) -> str:
    """Return a depth-scoped state key.

    At depth 0 the original key is returned unchanged.
    At depth N > 0 the key is suffixed with ``@dN`` so nested
    reasoning agents operate on independent state.
    """
    if depth == 0:
        return key
    return f"{key}@d{depth}"


def obs_model_usage_key(model_name: str) -> str:
    """Generate the observability key for a specific model's usage stats."""
    return f"obs:model_usage:{model_name}"
