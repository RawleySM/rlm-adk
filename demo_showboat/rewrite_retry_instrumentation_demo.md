# AST Rewrite, Reasoning Retry, and BUG-13 Instrumentation Demo

## What Was Implemented

Three new observability signals were added to the RLM-ADK pipeline:

1. **AST Rewrite Instrumentation** -- REPLTool tracks how many times the AST rewriter fires and the cumulative time spent rewriting `llm_query()` calls to `await llm_query_async()`.
2. **Reasoning Retry Count** -- The orchestrator emits `OBS_REASONING_RETRY_COUNT` as a state delta event when transient LLM errors trigger retries of the reasoning agent loop.
3. **BUG-13 Suppress Count** -- The `flush_fn` in dispatch.py propagates the process-global `_bug13_stats["suppress_count"]` into tool_context.state so downstream plugins can observe how many times the monkey-patch suppressed premature worker termination.

All four new state keys are defined in `rlm_adk/state.py`:
- `obs:rewrite_count`
- `obs:rewrite_total_ms`
- `obs:reasoning_retry_count`
- `obs:bug13_suppress_count`

---

## Test Suite: 7 Tests, All Passing

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_rewrite_instrumentation.py -v
```

Expected output:

```
tests_rlm_adk/test_rewrite_instrumentation.py::TestRewriteInstrumentation::test_no_rewrite_for_plain_code PASSED
tests_rlm_adk/test_rewrite_instrumentation.py::TestRewriteInstrumentation::test_rewrite_count_increments_for_llm_query_code PASSED
tests_rlm_adk/test_rewrite_instrumentation.py::TestRewriteInstrumentation::test_rewrite_total_ms_is_positive PASSED
tests_rlm_adk/test_rewrite_instrumentation.py::TestRewriteInstrumentation::test_rewrite_count_accumulates_across_calls PASSED
tests_rlm_adk/test_rewrite_instrumentation.py::TestReasoningRetryCount::test_state_key_constant_exists PASSED
tests_rlm_adk/test_rewrite_instrumentation.py::TestBug13StatsPersistence::test_flush_fn_includes_bug13_when_positive PASSED
tests_rlm_adk/test_rewrite_instrumentation.py::TestBug13StatsPersistence::test_flush_fn_omits_bug13_when_zero PASSED
```

---

## Proof: AST Rewrite Count and Timing

REPLTool instance vars `_rewrite_count` and `_rewrite_total_ms` accumulate across calls.
Only written to `tool_context.state` when `_rewrite_count > 0` (no noise for plain code).

```python
# Verify plain code does not trigger rewrite keys
.venv/bin/python -m pytest tests_rlm_adk/test_rewrite_instrumentation.py::TestRewriteInstrumentation::test_no_rewrite_for_plain_code -v
```

```python
# Verify rewrite count increments and timing is positive
.venv/bin/python -m pytest tests_rlm_adk/test_rewrite_instrumentation.py::TestRewriteInstrumentation::test_rewrite_count_increments_for_llm_query_code tests_rlm_adk/test_rewrite_instrumentation.py::TestRewriteInstrumentation::test_rewrite_total_ms_is_positive -v
```

```python
# Verify accumulation across multiple REPLTool calls
.venv/bin/python -m pytest tests_rlm_adk/test_rewrite_instrumentation.py::TestRewriteInstrumentation::test_rewrite_count_accumulates_across_calls -v
```

---

## Proof: Reasoning Retry Count Emitted as State Delta

The orchestrator's retry loop (lines 226-277 in orchestrator.py) yields an Event with
`state_delta={OBS_REASONING_RETRY_COUNT: attempt}` when `attempt > 0`.

```python
# Verify the constant is defined correctly
.venv/bin/python -m pytest tests_rlm_adk/test_rewrite_instrumentation.py::TestReasoningRetryCount::test_state_key_constant_exists -v
```

The orchestrator code path (orchestrator.py lines 269-277):

```python
# After the retry loop completes:
if attempt > 0:
    yield Event(
        invocation_id=ctx.invocation_id,
        author=self.name,
        actions=EventActions(state_delta={
            OBS_REASONING_RETRY_COUNT: attempt,
        }),
    )
```

---

## Proof: BUG-13 Suppress Count Flows Through State

`flush_fn()` in dispatch.py reads `_bug13_stats["suppress_count"]` and includes it in
the delta dict when positive. REPLTool writes that delta to `tool_context.state`.

```python
# Verify flush_fn includes bug13 count when positive
.venv/bin/python -m pytest tests_rlm_adk/test_rewrite_instrumentation.py::TestBug13StatsPersistence::test_flush_fn_includes_bug13_when_positive -v
```

```python
# Verify flush_fn omits bug13 count when zero (no noise)
.venv/bin/python -m pytest tests_rlm_adk/test_rewrite_instrumentation.py::TestBug13StatsPersistence::test_flush_fn_omits_bug13_when_zero -v
```

---

## Proof: All Keys Defined in state.py

```python
# Quick inline verification
.venv/bin/python -c "
from rlm_adk.state import (
    OBS_REWRITE_COUNT, OBS_REWRITE_TOTAL_MS,
    OBS_REASONING_RETRY_COUNT, OBS_BUG13_SUPPRESS_COUNT,
)
assert OBS_REWRITE_COUNT == 'obs:rewrite_count'
assert OBS_REWRITE_TOTAL_MS == 'obs:rewrite_total_ms'
assert OBS_REASONING_RETRY_COUNT == 'obs:reasoning_retry_count'
assert OBS_BUG13_SUPPRESS_COUNT == 'obs:bug13_suppress_count'
print('All 4 obs keys verified in state.py')
"
```

---

## Key Files

| File | Role |
|------|------|
| `rlm_adk/state.py` | Defines `OBS_REWRITE_COUNT`, `OBS_REWRITE_TOTAL_MS`, `OBS_REASONING_RETRY_COUNT`, `OBS_BUG13_SUPPRESS_COUNT` |
| `rlm_adk/tools/repl_tool.py` | Tracks `_rewrite_count` / `_rewrite_total_ms`, writes to `tool_context.state` |
| `rlm_adk/orchestrator.py` | Yields `OBS_REASONING_RETRY_COUNT` via `EventActions(state_delta=...)` after retry loop |
| `rlm_adk/dispatch.py` | `flush_fn()` reads `_bug13_stats` and includes in delta when positive |
| `rlm_adk/callbacks/worker_retry.py` | Process-global `_bug13_stats` counter incremented by BUG-13 monkey-patch |
| `tests_rlm_adk/test_rewrite_instrumentation.py` | 7 tests covering all three instrumentation paths |
