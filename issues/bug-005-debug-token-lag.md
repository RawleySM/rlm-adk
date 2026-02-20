# Bug 005: per_agent_tokens in debug logging lags by one iteration

## Summary

In `DebugLoggingPlugin.after_model_callback`, the `per_agent_tokens` section of
each trace entry reads `REASONING_INPUT_TOKENS` and `REASONING_OUTPUT_TOKENS`
from session state. These values were written by the **previous** call's
`reasoning_after_model` callback, not the current one. The `usage:` field (read
directly from `llm_response.usage_metadata`) is correct and current. The result
is that `per_agent_tokens` always displays stale data from the prior iteration.

## Affected File

- `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/debug_logging.py`, lines 298-310

## Root Cause

The callback execution order within a single model invocation is:

1. `reasoning_before_model` (agent callback) -- writes prompt accounting to state
2. `DebugLoggingPlugin.before_model_callback` (plugin) -- reads prompt accounting from state (correct, already written)
3. **LLM call executes**
4. `DebugLoggingPlugin.after_model_callback` (plugin) -- reads `REASONING_INPUT_TOKENS` / `REASONING_OUTPUT_TOKENS` from state
5. `reasoning_after_model` (agent callback) -- writes `REASONING_INPUT_TOKENS` / `REASONING_OUTPUT_TOKENS` to state from `llm_response.usage_metadata`

The plugin's `after_model_callback` (step 4) fires **before** the agent's
`reasoning_after_model` callback (step 5). So when the plugin reads
`REASONING_INPUT_TOKENS` from state at step 4, it gets the value that was
written during the **previous** iteration's step 5 -- not the current one.

Meanwhile, the plugin already has access to `llm_response.usage_metadata`
directly (which it uses to populate the `usage:` field correctly at lines
229-237), but the `per_agent_tokens` section redundantly reads the same
information from state, where it is stale.

## Evidence from Debug YAML

The lag pattern is visible across every iteration in `rlm_adk_debug.yaml`:

### Call 2 (lines 543-548)
```yaml
  usage:
    prompt_tokens: 5218       # <-- current (from llm_response.usage_metadata)
    candidates_tokens: 277    # <-- current
  per_agent_tokens:
    reasoning_input_tokens: 3210   # <-- STALE: this is Call 1's prompt_tokens
    reasoning_output_tokens: 569   # <-- STALE: this is Call 1's candidates_tokens
```

### Call 3 (lines 695-700)
```yaml
  usage:
    prompt_tokens: 6530       # <-- current
    candidates_tokens: 107    # <-- current
  per_agent_tokens:
    reasoning_input_tokens: 5218   # <-- STALE: this is Call 2's prompt_tokens
    reasoning_output_tokens: 277   # <-- STALE: this is Call 2's candidates_tokens
```

### Call 4 (lines 857-862)
```yaml
  usage:
    prompt_tokens: 7273       # <-- current
    candidates_tokens: 56     # <-- current
  per_agent_tokens:
    reasoning_input_tokens: 6530   # <-- STALE: this is Call 3's prompt_tokens
    reasoning_output_tokens: 107   # <-- STALE: this is Call 3's candidates_tokens
```

The pattern is consistent: `per_agent_tokens.reasoning_input_tokens` in call N
always equals `usage.prompt_tokens` from call N-1. The same holds for output
tokens.

## Contrast with ObservabilityPlugin

The `ObservabilityPlugin.after_model_callback` (lines 107-188 of
`observability.py`) correctly reads token counts directly from
`llm_response.usage_metadata` rather than from state, avoiding this staleness
issue entirely.

## Impact

- Debug trace consumers (developers, automated analysis) who read
  `per_agent_tokens` will see misleading token counts that are always one
  iteration behind reality.
- The `usage:` field on the same trace entry shows the correct values, creating
  a confusing contradiction within a single trace record.
- The `per_agent_tokens` section is entirely redundant with `usage:` for the
  reasoning agent case, since both ultimately derive from the same
  `usage_metadata`, but the state-based path introduces the lag.

## Resolution

**Fixed in:** `rlm_adk/plugins/debug_logging.py`, `after_model_callback` method (lines 296-308).

**Change:** The `per_agent_tokens` section now reads token counts directly from
`llm_response.usage_metadata` (via the already-computed `tokens_in` /
`tokens_out` local variables) instead of from session state. Agent type
detection still uses state key presence (`REASONING_INPUT_TOKENS` /
`WORKER_INPUT_TOKENS`) as a sentinel to determine which agent label to apply,
but the actual numeric values come from the current response object.

The unused imports `REASONING_OUTPUT_TOKENS` and `WORKER_OUTPUT_TOKENS` were
removed from the import block since they are no longer referenced.

**Test coverage:** 4 new tests in `tests_rlm_adk/test_bug005_debug_token_lag.py`:
- `test_reasoning_tokens_match_current_response` -- stale reasoning state vs current response
- `test_worker_tokens_match_current_response` -- stale worker state vs current response
- `test_per_agent_tokens_matches_usage_field` -- consistency between `usage:` and `per_agent_tokens` within the same trace entry
- `test_no_usage_metadata_no_per_agent_tokens` -- when no usage_metadata, stale state values must not leak into per_agent_tokens

**Test results:** 248 passed (including 4 new), 13 failed (pre-existing from bugs 001, 002, 004).
