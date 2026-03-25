# GAP-TH-008: `trace_holder[0]` shared mutable reference accessed from both event loop and worker thread without synchronization

**Severity**: LOW
**Category**: threading
**Files**: `rlm_adk/tools/repl_tool.py`, `rlm_adk/dispatch.py`

## Problem

`REPLTool.run_async` creates a `REPLTrace` and stores it in `trace_holder[0]` (lines 149-159). The `trace_holder` list is shared with dispatch closures (passed as `trace_sink` to `create_dispatch_closures` at orchestrator.py line 297).

The access pattern:
1. **Event loop thread** (in `REPLTool.run_async`): Creates `REPLTrace`, writes it to `trace_holder[0]` (line 157)
2. **Event loop thread** (in dispatch closures): Reads `trace_sink[0]` to get the current trace (dispatch.py line 431: `current_trace = trace_sink[0] if trace_sink else None`)
3. **Worker thread** (in `_execute_code_threadsafe`): The `trace` argument is the same `REPLTrace` object. Trace callbacks registered with IPython write to `trace.start_time`, `trace.end_time`, `trace.peak_memory_bytes`

The `REPLTrace` object is read and written from both the worker thread (via trace callbacks) and the event loop thread (via dispatch closures recording LLM call timing). Since `REPLTrace` is a dataclass with simple attribute assignments, CPython's GIL makes individual attribute writes atomic. But there's no memory ordering guarantee that the worker thread's writes to `trace.start_time` are visible to the event loop thread reading `trace.summary()`.

In practice, the timing of access is sequential enough (the dispatch closure runs DURING the worker thread's execution, but they access different fields -- dispatch writes `llm_calls`, worker writes `start_time`/`end_time`), so corruption is unlikely. But this is a textbook data race in the formal sense.

## Evidence

```python
# repl_tool.py lines 149-157
trace = REPLTrace(...)
if self.trace_holder:
    self.trace_holder[0] = trace  # Event loop thread writes

# dispatch.py line 431
current_trace = trace_sink[0] if trace_sink else None  # Event loop reads

# dispatch.py lines 436-438 (event loop thread)
current_trace._call_counter += 1
current_trace.record_llm_start(call_index, prompt, "single")

# ipython_executor.py line 343 (worker thread, via trace callback)
trace.start_time = time.perf_counter()
```

## Suggested Fix

This is low risk because:
1. The dispatch closures run on the event loop thread when `llm_query_async` is called, which happens DURING the worker thread's execution but accesses different REPLTrace fields
2. CPython GIL ensures individual attribute assignments are atomic
3. The trace is consumed (via `trace.summary()`) only after `execute_code_threaded` returns, which is after the worker thread has joined

For defense-in-depth, consider making `_call_counter` an `threading.Lock`-protected counter, or use `dataclasses.field` with a lock for the `llm_calls` list. But this is likely over-engineering for the current use case.
