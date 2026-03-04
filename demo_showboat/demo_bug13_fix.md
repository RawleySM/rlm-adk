# BUG-13 Fix: Structured Output Retry Self-Healing

*2026-02-28T12:13:52Z by Showboat 0.6.0*
<!-- showboat-id: f6220472-f96d-4386-a258-3f1799bd0b7c -->

## Problem

BUG-13: ADK `_output_schema_processor.get_structured_model_response()` unconditionally
terminates workers after any `set_model_response` function call — even when tool callbacks
(WorkerRetryPlugin) signal retry via a ToolFailureResponse. The postprocessor creates a
text-only final event, `is_final_response()` returns True, and the worker loop breaks
before the model gets a second turn.

## Fix

A module-level monkey-patch in `worker_retry.py` wraps `get_structured_model_response`
to detect the `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel in ToolFailureResponse dicts
and return None — suppressing the premature final event and allowing the agent loop to
continue for retry.

```bash
sed -n "145,200p" rlm_adk/callbacks/worker_retry.py
```

```output
# ---------------------------------------------------------------------------
# BUG-13 workaround: Patch ADK's output-schema postprocessor so that
# ToolFailureResponse dicts (retry guidance from ReflectAndRetryToolPlugin)
# are NOT treated as successful structured output.
#
# Without this patch, get_structured_model_response() matches any
# func_response with name=='set_model_response' and converts it to a
# text-only final event — terminating the worker loop before the model
# gets a second turn.  The patch inspects the response content for the
# REFLECT_AND_RETRY_RESPONSE_TYPE sentinel and returns None when found,
# allowing the agent loop to continue for retry.
#
# Call site in ADK (module-attribute lookup, patchable):
#   base_llm_flow.py:849  _output_schema_processor.get_structured_model_response(...)
# ---------------------------------------------------------------------------


def _patch_output_schema_postprocessor() -> None:
    """Install a retry-aware wrapper around get_structured_model_response.

    Idempotent — safe to call multiple times.
    """
    import google.adk.flows.llm_flows._output_schema_processor as _osp

    # Guard against double-patching
    if getattr(_osp.get_structured_model_response, "_rlm_patched", False):
        return

    _original = _osp.get_structured_model_response

    def _retry_aware_get_structured_model_response(
        function_response_event,
    ) -> str | None:
        result = _original(function_response_event)
        if result is None:
            return None
        try:
            parsed = _json.loads(result)
        except (ValueError, TypeError):
            return result
        if (
            isinstance(parsed, dict)
            and parsed.get("response_type") == REFLECT_AND_RETRY_RESPONSE_TYPE
        ):
            logger.debug(
                "BUG-13 patch: suppressing postprocessor for ToolFailureResponse"
            )
            return None
        return result

    _retry_aware_get_structured_model_response._rlm_patched = True  # type: ignore[attr-defined]
    _osp.get_structured_model_response = _retry_aware_get_structured_model_response


# Apply the patch at import time so it is active before any worker dispatch.
_patch_output_schema_postprocessor()
```

## Verification

The patch is installed at import time as a side-effect of `from rlm_adk.callbacks.worker_retry import ...`.
It is idempotent (double-patching returns the same function object) and process-global
(safe under asyncio single-threaded cooperative model).

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
from rlm_adk.callbacks.worker_retry import _patch_output_schema_postprocessor
import google.adk.flows.llm_flows._output_schema_processor as _osp
print('Patched:', getattr(_osp.get_structured_model_response, '_rlm_patched', False))
"

```

```output
Patched: True
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3 -c "
from rlm_adk.callbacks.worker_retry import _patch_output_schema_postprocessor
import google.adk.flows.llm_flows._output_schema_processor as _osp
fn1 = _osp.get_structured_model_response
_patch_output_schema_postprocessor()  # call again
fn2 = _osp.get_structured_model_response
print('Idempotent:', fn1 is fn2)
"

```

```output
Idempotent: True
```

## BUG-13 Test Results

These 9 tests previously failed with `ValueError: Tool set_model_response not found`
because the postprocessor terminated workers before retry callbacks could fire.

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_structured_output_e2e.py -k "retry" -q 2>&1 | grep -oP "^\d+ passed, \d+ deselected"
```

```output
7 passed, 5 deselected
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -k "test_fixture_contract[structured_output_retry" -q 2>&1 | grep -oP "^\d+ passed, \d+ deselected"
```

```output
2 passed, 22 deselected
```

## Full Suite

Full test suite confirms zero regressions from the patch.
The only 2 remaining failures are pre-existing (sqlite_tracing flag test, fragile repomix shard test).

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/ -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
2 failed, 665 passed, 1 skipped
```
