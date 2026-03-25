# GAP-TH-007: `_pending_llm_calls.clear()` in `execute_code_threaded` races with child dispatch appending to it

**Severity**: LOW
**Category**: threading
**Files**: `rlm_adk/repl/local_repl.py`, `rlm_adk/dispatch.py`

## Problem

At the start of `execute_code_threaded` (line 447):

```python
self._pending_llm_calls.clear()
```

This clears the list on the event loop thread. Then execution proceeds to the worker thread. Inside the worker thread, REPL code calls `llm_query()`, which dispatches to the event loop where `_build_call_log` (dispatch.py line 156-182) appends to `call_log_sink`, which is the same `repl._pending_llm_calls` list (wired at orchestrator.py line 296: `call_log_sink=repl._pending_llm_calls`).

`list.append()` in CPython is thread-safe due to the GIL, so individual appends won't corrupt the list structure. However, `list.clear()` is also a GIL-atomic operation. The issue is a logic race, not a memory corruption:

If `execute_code_threaded` is called again quickly (shouldn't happen normally since ADK serializes tool calls), `clear()` could remove call log entries that were appended by a still-running child dispatch from the previous execution.

This is LOW severity because:
1. ADK serializes tool calls within a single reasoning agent -- `execute_code_threaded` won't be called again until the previous one returns
2. The `clear()` at the start of each call is intentional (reset for the new execution)
3. CPython GIL protects individual list operations

The real risk is in the timeout case (GAP-TH-006): after timeout, the orphaned thread's child dispatches may still be appending to `_pending_llm_calls` while the next execution has already cleared it.

## Evidence

```python
# local_repl.py line 447
self._pending_llm_calls.clear()  # Event loop thread

# dispatch.py lines 156-162 (_build_call_log, runs on event loop thread)
def _build_call_log(prompt, result, elapsed_ms):
    if call_log_sink is None:
        return
    call_log_sink.append(RLMChatCompletion(...))  # Same list object

# orchestrator.py line 296
call_log_sink=repl._pending_llm_calls,  # Shared list
```

## Suggested Fix

This is low risk under normal operation. For defense-in-depth:

1. Use a per-execution list instead of clearing the shared one. Pass a fresh list to the dispatch closures for each `execute_code_threaded` call.
2. Alternatively, accept the current design and document that `_pending_llm_calls` is only valid between `clear()` and the `REPLResult` construction at the end of `execute_code_threaded`.
