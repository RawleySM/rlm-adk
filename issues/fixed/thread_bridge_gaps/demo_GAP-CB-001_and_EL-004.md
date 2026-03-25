# GAP-CB-001 & GAP-EL-004: History Duplication Fix + Timeout Cancellation

*2026-03-25T10:13:34Z by Showboat 0.6.1*
<!-- showboat-id: 1f92b1f3-3a26-406e-86e2-5b302931b3f3 -->

## GAP-CB-001: _extract_adk_dynamic_instruction Deleted

**Problem**: `reasoning_before_model` read ALL text from `llm_request.contents` (the entire conversation history) and appended it to `system_instruction` via `append_instructions()`. This duplicated the full conversation into the system prompt on every model call — escalating token waste per turn.

**Fix**: Deleted `_extract_adk_dynamic_instruction()` entirely. `reasoning_before_model` is now observe-only (token accounting only). ADK 1.27 natively positions dynamic instructions correctly via `_add_instructions_to_user_content()`.

```bash
echo "### Verify _extract_adk_dynamic_instruction is deleted:" && grep -n "_extract_adk_dynamic_instruction\|append_instructions" rlm_adk/callbacks/reasoning.py || echo "(no matches — function and append logic fully removed)"
```

```output
### Verify _extract_adk_dynamic_instruction is deleted:
(no matches — function and append logic fully removed)
```

```bash
echo "### reasoning_before_model is now observe-only:" && grep -n "def reasoning_before_model\|Observe-only\|does NOT modify" rlm_adk/callbacks/reasoning.py
```

```output
### reasoning_before_model is now observe-only:
5:    processors.  This callback does NOT modify the LLM request.
95:def reasoning_before_model(
98:    """Observe-only: record per-invocation token accounting.
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_gap_cb_001_no_history_duplication.py -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
10 passed
```

## GAP-EL-004: Timeout Cancellation via threading.Event

**Problem**: 30s `sync_timeout` (local_repl) vs 300s `timeout` (thread_bridge) created a 270-second window where orphaned worker threads could spawn child orchestrators consuming API quota invisibly after the parent timed out.

**Fix**: Added cooperative cancellation via `threading.Event`:
- `LocalREPL.__init__` creates `self._cancelled = threading.Event()`
- `execute_code_threaded` clears it on entry, sets it on `TimeoutError`
- Both `make_sync_llm_query` and `make_sync_llm_query_batched` check `cancelled.is_set()` before `run_coroutine_threadsafe`

```bash
echo "### Cancellation wiring in thread_bridge.py:" && grep -n "cancelled" rlm_adk/repl/thread_bridge.py
```

```output
### Cancellation wiring in thread_bridge.py:
39:    cancelled: threading.Event | None = None,
54:    cancelled:
76:        if cancelled is not None and cancelled.is_set():
78:                "llm_query cancelled: parent code block timed out. "
98:    cancelled: threading.Event | None = None,
110:    cancelled:
124:        if cancelled is not None and cancelled.is_set():
126:                "llm_query cancelled: parent code block timed out. "
```

```bash
echo "### Cancellation wiring in local_repl.py:" && grep -n "_cancelled" rlm_adk/repl/local_repl.py
```

```output
### Cancellation wiring in local_repl.py:
199:        self._cancelled: threading.Event = threading.Event()
455:        self._cancelled.clear()
473:            self._cancelled.set()
```

```bash
PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests_rlm_adk/test_gap_el_004_timeout_cancellation.py -q -o "addopts=" 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
9 passed
```

## Summary

Both HIGH-priority gaps are now closed:
- **GAP-CB-001**: 10 tests prove `_extract_adk_dynamic_instruction` is deleted and `reasoning_before_model` is observe-only
- **GAP-EL-004**: 9 tests prove cooperative cancellation prevents orphaned child dispatches on timeout
- **Zero regressions** in existing contract tests
