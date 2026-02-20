# Bug 007: Worker parent_agent conflict across ParallelAgent batches

## Severity: BLOCKING

## Summary
When `llm_query_batched` dispatches more prompts than `max_concurrent` (default 4),
the prompts are split into sequential batches. Each batch creates a new `ParallelAgent`
with acquired workers as `sub_agents`. ADK's `BaseAgent.model_post_init` sets
`parent_agent` on each sub-agent. After batch 1 completes, workers still have
`parent_agent` set, so batch 2+ fails Pydantic validation:

```
ValueError: Agent `worker_1` already has a parent agent,
current parent: `batch_1_4`, trying to add: `batch_2_4`
```

## Root Cause
`dispatch.py` `llm_query_batched_async` reuses `LlmAgent` workers across batches
but did not clear `worker.parent_agent` after each batch. ADK's `BaseAgent.__set_parent_agent_for_sub_agents`
(base_agent.py:608-617) checks if `parent_agent is not None` and raises if so.

## Impact
- Any batched dispatch with >4 prompts fails for all batches after the first
- Only the first `max_concurrent` prompts succeed; all subsequent batches return error strings
- The reasoning agent receives "Error: ..." strings instead of LM responses

## Fix
In `dispatch.py`, in the `finally` block of the batch loop, set `worker.parent_agent = None`
before releasing the worker back to the pool:

```python
finally:
    for worker in workers:
        worker._pending_prompt = None
        worker.parent_agent = None  # <-- NEW: detach from ParallelAgent
        await worker_pool.release(worker, model)
```

## Verification
Ran structured pipeline replay with 75 worker dispatches (15 chunks x 5 agents)
across 19 batches. All 75 queries completed successfully with 0 errors.

## Related
- ADK source: `google.adk.agents.base_agent.BaseAgent.__set_parent_agent_for_sub_agents`
- ADK note: "an agent can ONLY be added as sub-agent once" — but our workers are ephemeral
  pool resources, not permanent tree members, so detaching is correct behavior.
