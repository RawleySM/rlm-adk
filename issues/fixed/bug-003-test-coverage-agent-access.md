# Bug 003: Tests don't cover _invocation_context.agent access path

## Bug ID
BUG-003

## Title
Worker callback tests mock `ctx.agent` directly instead of `ctx._invocation_context.agent`, failing to cover the production access path

## Severity
**Medium** -- Tests provide false confidence; regressions on the private API access path would go undetected in CI.

## Affected Files

| File | Lines | Description |
|------|-------|-------------|
| `rlm_adk/callbacks/worker.py` | 30, 81 | Production code accesses `callback_context._invocation_context.agent` |
| `tests_rlm_adk/test_adk_callbacks.py` | 25-31 | `_make_callback_context` sets `ctx.agent = agent` directly |
| `tests_rlm_adk/test_adk_callbacks.py` | 131-165 | `TestWorkerBeforeModel` tests pass agent via `ctx.agent` |
| `tests_rlm_adk/test_adk_callbacks.py` | 167-191 | `TestWorkerAfterModel` tests pass agent via `ctx.agent` |

## Explanation of the Mock/Production Mismatch

### Production access path

In `rlm_adk/callbacks/worker.py`, both `worker_before_model` (line 30) and `worker_after_model` (line 81) retrieve the agent via:

```python
agent = callback_context._invocation_context.agent
```

This mirrors the real Google ADK `CallbackContext` hierarchy:
- `CallbackContext` extends `ReadonlyContext` (defined in `google.adk.agents.readonly_context`)
- `ReadonlyContext.__init__` stores the `InvocationContext` as `self._invocation_context`
- The agent is accessed via `self._invocation_context.agent`

There is no `CallbackContext.agent` property; the agent is only reachable through the `_invocation_context` indirection.

### Test mock structure

The test helper `_make_callback_context` (lines 25-31) builds a `MagicMock` and sets:

```python
ctx.agent = agent
```

This places the mock agent directly on `ctx.agent`, which does NOT set `ctx._invocation_context.agent`. Since `MagicMock` auto-creates any attribute access, `ctx._invocation_context.agent` returns a new auto-generated `MagicMock` rather than the explicitly configured agent with `_pending_prompt` and `output_key`.

### Consequence

- `worker_before_model` reads `_pending_prompt` from the auto-generated mock (which has no real value), so prompt injection silently does nothing. Tests that assert on `request.contents` fail.
- `worker_after_model` reads `output_key` from the auto-generated mock (which is itself a `MagicMock` object, not a string), so `callback_context.state[<MagicMock>]` is set instead of `callback_context.state["worker_1_output"]`. Tests that check for specific state keys fail.

## Evidence

Running the existing test suite produces 4 failures in the worker callback tests:

```
$ .venv/bin/python -m pytest tests_rlm_adk/test_adk_callbacks.py -v --tb=short

tests_rlm_adk/test_adk_callbacks.py::TestWorkerBeforeModel::test_injects_string_prompt FAILED
tests_rlm_adk/test_adk_callbacks.py::TestWorkerBeforeModel::test_injects_message_list_prompt FAILED
tests_rlm_adk/test_adk_callbacks.py::TestWorkerBeforeModel::test_no_pending_prompt PASSED
tests_rlm_adk/test_adk_callbacks.py::TestWorkerAfterModel::test_writes_to_output_key FAILED
tests_rlm_adk/test_adk_callbacks.py::TestWorkerAfterModel::test_no_output_key FAILED

FAILED test_injects_string_prompt - AssertionError: assert 0 == 1
  (request.contents was never populated because _pending_prompt was read from auto-mock)

FAILED test_injects_message_list_prompt - AssertionError: assert 0 == 2
  (same root cause)

FAILED test_writes_to_output_key - KeyError: 'worker_1_output'
  (output_key was a MagicMock object, not the string "worker_1_output")

FAILED test_no_output_key - AssertionError: assert 1 == 0
  (MagicMock auto-generated output_key is truthy, so state got an unexpected entry)

4 failed, 7 passed
```

The 7 passing tests are all reasoning callbacks that do not use the `agent` parameter; they are unaffected by this bug. The 4 failing worker tests confirm that the mock structure does not match the production `_invocation_context.agent` access path.

## Resolution

### Changes Made

1. **Updated `_make_callback_context` in `tests_rlm_adk/test_adk_callbacks.py` (lines 25-37)**:
   The helper now creates a separate `MagicMock` for `invocation_context`, assigns the agent to `invocation_context.agent`, and sets `ctx._invocation_context = invocation_context`. This mirrors the real `ReadonlyContext` hierarchy where `self._invocation_context` is set in `__init__` and the agent is accessed through it.

   Before:
   ```python
   ctx.agent = agent
   ```

   After:
   ```python
   invocation_context = MagicMock()
   invocation_context.agent = agent
   ctx._invocation_context = invocation_context
   ```

2. **Created `tests_rlm_adk/test_bug003_agent_access.py`**:
   A dedicated regression test file with 5 tests that explicitly verify the `_invocation_context.agent` access chain for both `worker_before_model` and `worker_after_model`. Tests cover string prompts, message list prompts, no-prompt edge case, output key writing, and the no-output-key edge case.

### Verification

All 16 tests pass across both test files:

```
$ .venv/bin/python -m pytest tests_rlm_adk/test_adk_callbacks.py tests_rlm_adk/test_bug003_agent_access.py -v --tb=short

tests_rlm_adk/test_adk_callbacks.py::TestReasoningBeforeModel::test_injects_user_messages PASSED
tests_rlm_adk/test_adk_callbacks.py::TestReasoningBeforeModel::test_sets_reasoning_call_start PASSED
tests_rlm_adk/test_adk_callbacks.py::TestReasoningBeforeModel::test_empty_history PASSED
tests_rlm_adk/test_adk_callbacks.py::TestReasoningAfterModel::test_extracts_text_to_state PASSED
tests_rlm_adk/test_adk_callbacks.py::TestReasoningAfterModel::test_empty_response PASSED
tests_rlm_adk/test_adk_callbacks.py::TestReasoningAfterModel::test_filters_thought_parts PASSED
tests_rlm_adk/test_adk_callbacks.py::TestWorkerBeforeModel::test_injects_string_prompt PASSED
tests_rlm_adk/test_adk_callbacks.py::TestWorkerBeforeModel::test_injects_message_list_prompt PASSED
tests_rlm_adk/test_adk_callbacks.py::TestWorkerBeforeModel::test_no_pending_prompt PASSED
tests_rlm_adk/test_adk_callbacks.py::TestWorkerAfterModel::test_writes_to_output_key PASSED
tests_rlm_adk/test_adk_callbacks.py::TestWorkerAfterModel::test_no_output_key PASSED
tests_rlm_adk/test_bug003_agent_access.py::TestWorkerBeforeModelInvocationContext::test_string_prompt_injected_via_invocation_context PASSED
tests_rlm_adk/test_bug003_agent_access.py::TestWorkerBeforeModelInvocationContext::test_message_list_prompt_injected_via_invocation_context PASSED
tests_rlm_adk/test_bug003_agent_access.py::TestWorkerBeforeModelInvocationContext::test_no_pending_prompt_via_invocation_context PASSED
tests_rlm_adk/test_bug003_agent_access.py::TestWorkerAfterModelInvocationContext::test_writes_to_output_key_via_invocation_context PASSED
tests_rlm_adk/test_bug003_agent_access.py::TestWorkerAfterModelInvocationContext::test_no_output_key_via_invocation_context PASSED

16 passed in 0.04s
```

### Regression Protection

If someone were to revert `worker.py` back to using `callback_context.agent` instead of `callback_context._invocation_context.agent`, both the updated `test_adk_callbacks.py` worker tests and the dedicated `test_bug003_agent_access.py` tests would immediately fail, catching the regression.
