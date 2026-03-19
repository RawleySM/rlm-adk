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
FINAL_RESPONSE_TEXT = "final_response_text"

# Context Metadata Keys (used by callbacks/observability)
REPO_URL = "repo_url"
ROOT_PROMPT = "root_prompt"
ENABLED_SKILLS = "enabled_skills"

# Dynamic Instruction State Keys (session-scoped for ADK instruction template resolution)
# These match the {var?} placeholders in RLM_DYNAMIC_INSTRUCTION so ADK can
# resolve them at runtime via its built-in state variable injection.
DYN_REPO_URL = "repo_url"
DYN_ROOT_PROMPT = "root_prompt"
DYN_SKILL_INSTRUCTION = "skill_instruction"

# User-Provided Context Keys (session-scoped)
USER_PROVIDED_CTX = "user_provided_ctx"
USER_PROVIDED_CTX_EXCEEDED = "user_provided_ctx_exceeded"
USR_PROVIDED_FILES_SERIALIZED = "usr_provided_files_serialized"
USR_PROVIDED_FILES_UNSERIALIZED = "usr_provided_files_unserialized"

# Dynamic Instruction State Key (for {user_ctx_manifest?} template injection)
DYN_USER_CTX_MANIFEST = "user_ctx_manifest"

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
INVOCATION_START_TIME = "invocation_start_time"

# Finish Reason Tracking (written by ObservabilityPlugin)
OBS_FINISH_SAFETY_COUNT = "obs:finish_safety_count"
OBS_FINISH_RECITATION_COUNT = "obs:finish_recitation_count"
OBS_FINISH_MAX_TOKENS_COUNT = "obs:finish_max_tokens_count"


# AST Rewrite Instrumentation (written by REPLTool)
OBS_REWRITE_COUNT = "obs:rewrite_count"
OBS_REWRITE_TOTAL_MS = "obs:rewrite_total_ms"
OBS_REWRITE_FAILURE_COUNT = "obs:rewrite_failure_count"
OBS_REWRITE_FAILURE_CATEGORIES = "obs:rewrite_failure_categories"

# Reasoning Retry Observability (written by orchestrator)
OBS_REASONING_RETRY_COUNT = "obs:reasoning_retry_count"
OBS_REASONING_RETRY_DELAY_MS = "obs:reasoning_retry_delay_ms"

# REPL Submitted-Code Observability Keys
REPL_SUBMITTED_CODE = "repl_submitted_code"
REPL_SUBMITTED_CODE_PREVIEW = "repl_submitted_code_preview"
REPL_SUBMITTED_CODE_HASH = "repl_submitted_code_hash"
REPL_SUBMITTED_CODE_CHARS = "repl_submitted_code_chars"

# Skill Expansion Observability Keys
REPL_EXPANDED_CODE = "repl_expanded_code"
REPL_EXPANDED_CODE_HASH = "repl_expanded_code_hash"
REPL_SKILL_EXPANSION_META = "repl_skill_expansion_meta"
REPL_DID_EXPAND = "repl_did_expand"


# API/Messaging Keys
REQUEST_ID = "request_id"
IDEMPOTENCY_KEY = "idempotency_key"
USER_LAST_SUCCESSFUL_CALL_ID = "user:last_successful_call_id"

# Test Hook State Keys (session-scoped, written by test-only callbacks)
CB_REASONING_CONTEXT = "cb_reasoning_context"
CB_ORCHESTRATOR_CONTEXT = "cb_orchestrator_context"
CB_TOOL_CONTEXT = "cb_tool_context"

# Artifact Tracking Keys (session-scoped)
ARTIFACT_SAVE_COUNT = "artifact_save_count"
ARTIFACT_LOAD_COUNT = "artifact_load_count"
ARTIFACT_TOTAL_BYTES_SAVED = "artifact_total_bytes_saved"
ARTIFACT_LAST_SAVED_FILENAME = "artifact_last_saved_filename"
ARTIFACT_LAST_SAVED_VERSION = "artifact_last_saved_version"

# LiteLLM Cost Tracking (session-scoped aggregate)
OBS_LITELLM_TOTAL_COST = "obs:litellm_total_cost"

# Artifact Observability Keys (session-scoped)
OBS_ARTIFACT_SAVES = "obs:artifact_saves"

# Artifact Configuration Keys (app-scoped)
APP_ARTIFACT_OFFLOAD_THRESHOLD = "app:artifact_offload_threshold"

# Migration Status Keys (session-scoped, naming convention only)
MIGRATION_STATUS = "migration:status"
MIGRATION_TIMESTAMP = "migration:timestamp"
MIGRATION_ERROR = "migration:error"

# Step-Mode Keys (session-scoped)
STEP_MODE_ENABLED = "step:mode_enabled"       # bool — is step mode active?
STEP_MODE_PAUSED_AGENT = "step:paused_agent"   # str — name of agent currently paused
STEP_MODE_PAUSED_DEPTH = "step:paused_depth"   # int — depth of paused agent
STEP_MODE_ADVANCE_COUNT = "step:advance_count"  # int — number of advances taken


# REPL State Introspection
REPL_STATE_SNAPSHOT = "_rlm_state"

EXPOSED_STATE_KEYS: frozenset[str] = frozenset(
    {
        ITERATION_COUNT,
        CURRENT_DEPTH,
        APP_MAX_ITERATIONS,
        APP_MAX_DEPTH,
        LAST_REPL_RESULT,
        STEP_MODE_ENABLED,
        SHOULD_STOP,
        FINAL_RESPONSE_TEXT,
    }
)


DEPTH_SCOPED_KEYS: set[str] = {
    MESSAGE_HISTORY,
    ITERATION_COUNT,
    FINAL_RESPONSE_TEXT,
    LAST_REPL_RESULT,
    SHOULD_STOP,
    REPL_SUBMITTED_CODE,
    REPL_SUBMITTED_CODE_PREVIEW,
    REPL_SUBMITTED_CODE_HASH,
    REPL_SUBMITTED_CODE_CHARS,
    REPL_EXPANDED_CODE,
    REPL_EXPANDED_CODE_HASH,
    REPL_SKILL_EXPANSION_META,
    REPL_DID_EXPAND,
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
