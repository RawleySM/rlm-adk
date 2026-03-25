# GAP-CB-007: Child events lost on exception in reasoning agent retry loop

**Severity**: MEDIUM
**Category**: callback-lifecycle
**Files**: `rlm_adk/orchestrator.py` (lines 511-579, 652-667)

## Problem

When the reasoning agent raises an exception during the retry loop (line 523), the code yields an error event (lines 535-544) and then re-raises (line 545). Control jumps to the `finally` block at line 652, which cleans up the reasoning agent wiring but does NOT drain the `_child_event_queue`.

Any child events that accumulated during the failed execution (e.g., child state deltas, child completion events) are silently discarded. The final drain at lines 574-579 is only reached on the success path.

## Evidence

Success path drains child events at two points:
1. During reasoning loop iteration (lines 516-521) -- per-event drain
2. After reasoning loop completes (lines 574-579) -- final drain

Exception path:
```python
except Exception as exc:
    # ... yield error event ...
    raise  # <-- jumps to finally, skips lines 574-579
```

`finally` block (lines 652-667):
```python
finally:
    # Clean up reasoning_agent wiring
    object.__setattr__(self.reasoning_agent, "tools", [])
    # ... more cleanup ...
    if not self.persistent:
        repl.cleanup()
    # NOTE: No _child_event_queue drain here
```

## Impact

On transient errors that are retried (lines 546-559), child events from the failed attempt are lost. On fatal errors, child events from the partially-completed execution are lost. In both cases, the observability pipeline (sqlite_tracing, dashboard) will have incomplete child state evolution data for the failed run.

For root orchestrators (depth=0), this is a telemetry gap. For child orchestrators (depth>0), the lost events were only going to be re-emitted to the parent's queue, so the parent also loses visibility into the child's partial execution.

## Suggested Fix

Add a child event drain in the `finally` block:

```python
finally:
    # Drain any remaining child events before cleanup
    if _child_event_queue is not None:
        while not _child_event_queue.empty():
            try:
                yield _child_event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    # Clean up reasoning_agent wiring
    object.__setattr__(self.reasoning_agent, "tools", [])
    # ...
```

Note: Since `_run_async_impl` is an async generator, yielding in `finally` is valid Python.
