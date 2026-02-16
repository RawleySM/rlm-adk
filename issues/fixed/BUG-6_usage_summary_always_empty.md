# BUG-6: Usage summary always returned empty

## Location

`rlm_adk/agent.py` lines 228-238 (post-run result construction in `acompletion`)

## Description

After the runner completes, `acompletion()` constructs the `RLMChatCompletion` with a hardcoded empty usage summary:

```python
# Build usage summary (populated by ObservabilityPlugin)
usage = UsageSummary(model_usage_summaries={})

return RLMChatCompletion(
    root_model=self.model,
    prompt=prompt,
    response=final_answer,
    usage_summary=usage,
    execution_time=time_end - time_start,
)
```

The comment "populated by ObservabilityPlugin" is aspirational -- even if ObservabilityPlugin were properly wired (see BUG-2), it writes usage data to session state keys (`obs:total_input_tokens`, `obs:total_output_tokens`, `obs:total_calls`, `obs:model_usage:{model_name}`), but `acompletion()` never reads those keys back from the session.

## Impact

- `RLMChatCompletion.usage_summary` is always `UsageSummary(model_usage_summaries={})` regardless of actual LLM usage
- Any caller that relies on usage data for cost tracking, billing, or diagnostics gets empty results
- FR-013 (Usage Tracking) and PT-006 (Usage Parity) can never pass

## Fix

After the runner loop completes, read observability state from the session and build the `UsageSummary`:

```python
from rlm_adk.state import (
    OBS_TOTAL_CALLS,
    OBS_TOTAL_INPUT_TOKENS,
    OBS_TOTAL_OUTPUT_TOKENS,
    obs_model_usage_key,
)
from rlm_adk.types import ModelUsageSummary

# After runner.run_async completes:
session_state = session.state  # or re-fetch session

model_summaries = {}
# Scan state for obs:model_usage:* keys
for key, value in session_state.items():
    if key.startswith("obs:model_usage:") and isinstance(value, dict):
        model_name = key.replace("obs:model_usage:", "")
        model_summaries[model_name] = ModelUsageSummary(
            total_calls=value.get("calls", 0),
            total_input_tokens=value.get("input_tokens", 0),
            total_output_tokens=value.get("output_tokens", 0),
        )

usage = UsageSummary(model_usage_summaries=model_summaries)
```

Note: this fix depends on BUG-2 being resolved first (plugins must be wired for ObservabilityPlugin to populate these state keys).

## Affected SRS requirements

- FR-001 (Completion Contract Parity -- `usage_summary` field)
- FR-013 (Usage Tracking)
- PT-006 (Usage Parity)
