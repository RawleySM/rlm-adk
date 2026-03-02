# Bug 009: Worker dispatch has no timeout — stalled API calls block forever

## Severity: HIGH

## Summary
When a Gemini API call silently stalls (no response, no error, no timeout),
the worker's `run_async(ctx)` generator never completes. The dispatch closure
blocks indefinitely on `async for event in worker.run_async(ctx)` (or
`parallel.run_async(ctx)` for batches), hanging the entire orchestrator loop.

The `on_model_error_callback` (added in Fix 5) only fires when the API
*returns* an error. A silently dropped HTTP connection never triggers it.

## Observed Behavior
During e2e replay with `test_structured_pipeline.json` against `google/adk-python`:

1. Iteration 6 dispatched 40 worker queries (8 chunks × 5 agents) via
   `llm_query_batched`, processed as batches of 4 via `ParallelAgent`.
2. In the final batch, 3 of 4 workers returned successfully (200 responses
   at 09:14:40, 09:15:23, 09:15:25 per agent log).
3. The 4th worker's API call never returned — no 200, no 429, no exception.
4. `ParallelAgent.run_async(ctx)` blocked waiting for all sub-agents.
5. The process was killed after ~16 minutes (exit code 143 / SIGTERM).

## Root Cause
Neither the ADK framework nor the `google.genai` client enforces a
per-request timeout by default:

- `google.genai` client uses `httpx` under the hood. The default httpx
  timeout is 5 minutes for connect but no hard ceiling on read.
- ADK's `BaseLlmFlow._call_llm_async` has no `asyncio.wait_for` wrapper.
- `ParallelAgent` uses `asyncio.TaskGroup` (or `create_task` + gather),
  which waits for ALL tasks — one stalled task blocks the entire group.
- The dispatch closure's `async for event in parallel.run_async(ctx)` has
  no timeout either.

The failure chain:
```
Gemini API stalls
  → httpx read hangs (no read timeout)
    → BaseLlmFlow._call_llm_async hangs
      → worker.run_async(ctx) never yields final event
        → ParallelAgent.run_async(ctx) never completes
          → dispatch closure blocks forever
            → REPL code blocks forever
              → orchestrator iteration never finishes
```

## Impact
- Single stalled API call hangs the entire pipeline permanently
- No error message, no retry, no graceful degradation
- Requires external process termination (SIGTERM/SIGKILL)
- Especially likely under high load when Gemini rate-limits or
  load-balances connections, potentially dropping some silently

## Proposed Fix

### Option A: Timeout in dispatch closure (minimal, recommended)

Wrap the `run_async` calls in `asyncio.wait_for` with a configurable
timeout. When the timeout fires, mark timed-out workers as errored:

```python
# dispatch.py — single worker case
WORKER_TIMEOUT = float(os.getenv("RLM_WORKER_TIMEOUT_SECS", "120"))

async def _drain_with_timeout(agent, ctx, event_queue, timeout):
    """Run a single agent with timeout, draining events to queue."""
    async def _drain():
        async for event in agent.run_async(ctx):
            event_queue.put_nowait(event)
    try:
        await asyncio.wait_for(_drain(), timeout=timeout)
    except asyncio.TimeoutError:
        agent._result = f"[Worker {agent.name} error: TimeoutError: no response after {timeout}s]"
        agent._result_ready = True
        agent._result_error = True
        agent._result_usage = {"input_tokens": 0, "output_tokens": 0}

# Usage:
if len(workers) == 1:
    await _drain_with_timeout(workers[0], ctx, event_queue, WORKER_TIMEOUT)
else:
    parallel = ParallelAgent(
        name=f"batch_{batch_num}_{len(workers)}",
        sub_agents=list(workers),
    )
    try:
        await asyncio.wait_for(
            _consume_events(parallel.run_async(ctx), event_queue),
            timeout=WORKER_TIMEOUT * 1.5,  # extra headroom for batch
        )
    except asyncio.TimeoutError:
        # Mark any workers that didn't complete
        for worker in workers:
            if not worker._result_ready:
                worker._result = f"[Worker {worker.name} error: TimeoutError: batch timeout]"
                worker._result_ready = True
                worker._result_error = True
                worker._result_usage = {"input_tokens": 0, "output_tokens": 0}
```

### Option B: httpx-level timeout (defense in depth)

Configure the `google.genai` client with explicit read timeouts:

```python
# In agent.py or wherever the genai client is configured
import httpx
client = genai.Client(
    http_options={"timeout": httpx.Timeout(connect=10, read=120, write=30, pool=30)}
)
```

This would cause the stalled call to raise `httpx.ReadTimeout`, which
would then be caught by `on_model_error_callback`.

### Recommendation
Implement both: Option B as the primary defense (raises an exception that
`on_model_error_callback` handles gracefully), and Option A as a backstop
for any timeout scenarios the httpx layer doesn't catch.

## Environment Variables
- `RLM_WORKER_TIMEOUT_SECS`: Per-worker timeout in seconds (default: 120)

## Reproduction
Run the structured pipeline replay against a large repository that
triggers many concurrent API calls:
```
adk run --replay tests_rlm_adk/replay/test_structured_pipeline.json rlm_adk
```
The hang typically occurs when dispatching ≥20 concurrent prompts with
large payloads (400KB+ per prompt), which saturates the Gemini API
token-per-minute quota and may cause connection drops.

## Related
- Fix 5 (`on_model_error_callback`): Handles errors that are *raised*, not stalls
- Bug 001 (orchestrator retry): Retries transient *errors*, not timeouts
- ADK source: `google.adk.flows.llm_flows.base_llm_flow.BaseLlmFlow._call_llm_async`
- ADK source: `google.adk.agents.parallel_agent.ParallelAgent._run_async_impl`
