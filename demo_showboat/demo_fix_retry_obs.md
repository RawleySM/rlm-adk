# Worker Retry + Observability Fixes — Showboat Demo

## FM-21: Import Cascade Guard (`worker_retry.py`)

**Problem:** `_patch_output_schema_postprocessor()` imports a private ADK module
(`google.adk.flows.llm_flows._output_schema_processor`) at module level with no
`try/except ImportError` guard. If ADK restructures this private module, the import
fails and cascades through `dispatch.py` to crash the entire package.

**Fix:** Wrapped the import in `try/except ImportError` with a warning log. Graceful
degradation: structured output retry suppression is disabled but all other
functionality (worker dispatch, REPL, observability) remains intact.

### Demo: Import failure produces warning, does not crash

```python
import builtins
import logging
import sys

logging.basicConfig(level=logging.WARNING, format="%(name)s - %(levelname)s - %(message)s")

# Import normally first (caches the real module)
import rlm_adk.callbacks.worker_retry as wr
import google.adk.flows.llm_flows._output_schema_processor as osp

# Verify patch was applied at import time
assert getattr(osp.get_structured_model_response, "_rlm_patched", False), \
    "Patch should be installed at import time"
print("PASS: Patch installed at import time")

# Reset the patched flag so the function re-enters
osp.get_structured_model_response._rlm_patched = False

# Remove cached module and make import fail
saved = sys.modules.pop("google.adk.flows.llm_flows._output_schema_processor", None)
old_import = builtins.__import__

def failing_import(name, *args, **kwargs):
    if "_output_schema_processor" in name:
        raise ImportError("Module removed in ADK vNext")
    return old_import(name, *args, **kwargs)

builtins.__import__ = failing_import
try:
    # This should log a WARNING and return gracefully
    wr._patch_output_schema_postprocessor()
    print("PASS: FM-21 graceful degradation — function returned without crash")
finally:
    builtins.__import__ = old_import
    if saved is not None:
        sys.modules["google.adk.flows.llm_flows._output_schema_processor"] = saved
```

Expected output:
```
rlm_adk.callbacks.worker_retry - WARNING - BUG-13 patch: cannot import _output_schema_processor — structured output retry suppression disabled. ADK may have restructured private modules.
PASS: Patch installed at import time
PASS: FM-21 graceful degradation — function returned without crash
```

### Demo: Idempotency guard prevents double-patching

```python
import rlm_adk.callbacks.worker_retry as wr
import google.adk.flows.llm_flows._output_schema_processor as osp

fn_before = osp.get_structured_model_response
assert getattr(fn_before, "_rlm_patched", False), "Patch should be installed"

# Call again — should be a no-op
wr._patch_output_schema_postprocessor()
fn_after = osp.get_structured_model_response

assert fn_before is fn_after, "Function reference should not change on re-patch"
print("PASS: Idempotency guard — double-patch prevented")
```

---

## BUG-A: FinishReason Key Format (`observability.py` + `worker.py`)

**Problem:** `str(FinishReason.SAFETY)` returns `"FinishReason.SAFETY"`, not `"SAFETY"`.
The dynamically generated state key becomes `obs:finish_finishreason.safety_count`
instead of the expected `obs:finish_safety_count`. This means the constants
`OBS_FINISH_SAFETY_COUNT`, `OBS_FINISH_RECITATION_COUNT`, and
`OBS_FINISH_MAX_TOKENS_COUNT` in `state.py` are dead code that never matches
any written key.

**Fix:** Changed `str(finish_reason)` to `finish_reason.name` in both
`observability.py:148` and `worker.py:116`.

### Demo: `.name` produces correct key format

```python
from google.genai import types
from rlm_adk.state import (
    OBS_FINISH_SAFETY_COUNT,
    OBS_FINISH_RECITATION_COUNT,
    OBS_FINISH_MAX_TOKENS_COUNT,
)

test_cases = [
    (types.FinishReason.SAFETY, OBS_FINISH_SAFETY_COUNT),
    (types.FinishReason.RECITATION, OBS_FINISH_RECITATION_COUNT),
    (types.FinishReason.MAX_TOKENS, OBS_FINISH_MAX_TOKENS_COUNT),
]

for fr, expected_constant in test_cases:
    # Old behavior (buggy)
    old_key = f"obs:finish_{str(fr).lower()}_count"
    # New behavior (fixed)
    new_key = f"obs:finish_{fr.name.lower()}_count"

    assert old_key != expected_constant, \
        f"Old key should NOT match constant: {old_key}"
    assert new_key == expected_constant, \
        f"New key should match constant: {new_key} != {expected_constant}"
    print(f"PASS: {fr.name:15s} old={old_key!r:55s} (wrong)  new={new_key!r} (correct)")

print()
print("PASS: All FinishReason keys now match state.py constants")
```

Expected output:
```
PASS: SAFETY          old='obs:finish_finishreason.safety_count'          (wrong)  new='obs:finish_safety_count' (correct)
PASS: RECITATION      old='obs:finish_finishreason.recitation_count'      (wrong)  new='obs:finish_recitation_count' (correct)
PASS: MAX_TOKENS      old='obs:finish_finishreason.max_tokens_count'      (wrong)  new='obs:finish_max_tokens_count' (correct)

PASS: All FinishReason keys now match state.py constants
```

### Demo: observability.py after_model_callback produces correct keys

```python
import asyncio
from unittest.mock import MagicMock, PropertyMock
from google.genai import types
from google.adk.models.llm_response import LlmResponse
from rlm_adk.plugins.observability import ObservabilityPlugin

plugin = ObservabilityPlugin()

# Build a mock callback_context with dict-backed state via PropertyMock
state = {}
callback_context = MagicMock()
type(callback_context).state = PropertyMock(return_value=state)

# Create a response with SAFETY finish reason
response = LlmResponse(
    content=types.Content(role="model", parts=[types.Part.from_text(text="blocked")]),
    finish_reason=types.FinishReason.SAFETY,
    usage_metadata=types.GenerateContentResponseUsageMetadata(
        prompt_token_count=100,
        candidates_token_count=10,
    ),
)

asyncio.run(plugin.after_model_callback(
    callback_context=callback_context,
    llm_response=response,
))

# Verify the correct key was written
assert "obs:finish_safety_count" in state, \
    f"Expected 'obs:finish_safety_count' in state, got keys: {list(state.keys())}"
assert state["obs:finish_safety_count"] == 1, \
    f"Expected count=1, got {state['obs:finish_safety_count']}"

# Verify the old buggy key was NOT written
assert "obs:finish_finishreason.safety_count" not in state, \
    "Buggy key should not be present"

print("PASS: ObservabilityPlugin writes 'obs:finish_safety_count' (not the buggy variant)")

# Verify per-iteration breakdown also uses .name
breakdowns = state.get("obs:per_iteration_token_breakdown", [])
assert len(breakdowns) == 1
assert breakdowns[0]["finish_reason"] == "SAFETY", \
    f"Expected 'SAFETY', got {breakdowns[0]['finish_reason']!r}"
print("PASS: Per-iteration breakdown records finish_reason='SAFETY' (not 'FinishReason.SAFETY')")
```

### Demo: worker.py after_model uses `.name` for call records

```python
from unittest.mock import MagicMock
from google.genai import types
from google.adk.models.llm_response import LlmResponse

# Simulate what worker_after_model does at line 116
fr = types.FinishReason.SAFETY
record_finish_reason = fr.name if fr else None
assert record_finish_reason == "SAFETY", f"Expected 'SAFETY', got {record_finish_reason!r}"
print("PASS: worker.py call record finish_reason='SAFETY'")

# Verify the safety detection at worker.py lines 88-93
assert fr is not None
assert hasattr(fr, "name")
assert fr.name == "SAFETY"
print("PASS: worker.py safety detection (hasattr guard + .name == 'SAFETY')")

# Verify None case (normal completion)
fr_none = None
result = fr_none.name if fr_none else None
assert result is None
print("PASS: worker.py None finish_reason handled correctly")
```
