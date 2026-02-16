# BUG-1: REPLResult field name mismatch between annotation and implementation

## Location

`rlm_adk/types.py` lines 120-152

## Description

The `REPLResult` dataclass declares `llm_calls: list["RLMChatCompletion"]` as a field annotation (line 126), but the `__init__` method uses `rlm_calls` as the parameter name and assigns `self.rlm_calls` (lines 134, 140). The `__str__` method (line 143) and `to_dict` method (line 151) also reference `self.rlm_calls`.

This means:

- `result.llm_calls` raises `AttributeError` at runtime
- `result.rlm_calls` works but doesn't match the declared field type annotation
- Static type checkers and IDE autocomplete will suggest `.llm_calls` (wrong) instead of `.rlm_calls` (correct)

## Reproduction

```python
from rlm_adk.types import REPLResult

r = REPLResult(stdout="", stderr="", locals={})
print(r.rlm_calls)   # works: []
print(r.llm_calls)   # AttributeError: 'REPLResult' object has no attribute 'llm_calls'
```

## Fix

Pick one name and use it consistently. `llm_calls` aligns with the broader ADK naming (`llm_query`, `LlmAgent`, `LlmRequest`). Rename `rlm_calls` to `llm_calls` in `__init__`, `__str__`, and `to_dict`:

```python
def __init__(
    self,
    stdout: str,
    stderr: str,
    locals: dict,
    execution_time: float = None,
    llm_calls: list["RLMChatCompletion"] = None,   # was rlm_calls
):
    # ...
    self.llm_calls = llm_calls or []                # was self.rlm_calls
```

Then update all call sites in `local_repl.py` that reference `self._pending_llm_calls` and assign to `rlm_calls=`.

## Affected SRS requirements

- DT-001 (Core Dataclass Behavior)
- FR-013 (Usage Tracking)
