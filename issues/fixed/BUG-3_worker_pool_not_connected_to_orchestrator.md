# BUG-3: WorkerPool never connected to the orchestrator

## Location

- `rlm_adk/agent.py` lines 156-160 (WorkerPool construction)
- `rlm_adk/agent.py` lines 183-189 (orchestrator creation -- no pool reference)
- `rlm_adk/orchestrator.py` lines 80-83 (REPL creation -- no dispatch closures injected)
- `rlm_adk/dispatch.py` lines 138-240 (`create_dispatch_closures` -- never called)

## Description

`RLMAdkEngine.__init__` creates a `WorkerPool` instance:

```python
self.worker_pool = WorkerPool(
    default_model=model,
    other_model=self.other_model,
    pool_size=worker_pool_size,
)
```

But `acompletion()` never passes the pool to the orchestrator, and the orchestrator never calls `create_dispatch_closures()`. The orchestrator creates a `LocalREPL` without injecting `llm_query` or `llm_query_batched` functions:

```python
repl = LocalREPL(
    context_payload=self.context_payload,
    depth=1,
)
```

The `LocalREPL.__init__` accepts `llm_query_fn` and `llm_query_batched_fn` kwargs, and also has `set_llm_query_fns()` and `set_async_llm_query_fns()` methods, but none of these are ever called by the orchestrator.

## Impact

Any LM-generated code that calls `llm_query(...)` or `llm_query_batched(...)` inside a ```` ```repl``` ```` block will raise `NameError: name 'llm_query' is not defined` at runtime. Sub-LM calls -- the core differentiator of RLM -- are completely broken.

The entire `dispatch.py` module (`WorkerPool`, `create_dispatch_closures`, `llm_query_async`, `llm_query_batched_async`) is dead code at runtime.

## Fix

The orchestrator needs to:

1. Accept a `WorkerPool` reference (either as a Pydantic field or passed to `_run_async_impl`)
2. Create an `asyncio.Queue` for collecting worker events
3. Call `create_dispatch_closures(worker_pool, ctx, event_queue)` to get the async closures
4. Inject them into the REPL via `repl.set_async_llm_query_fns(llm_query_async, llm_query_batched_async)`
5. Also create sync wrappers or use the AST rewriter path to bridge sync `llm_query` calls to the async closures

Sketch:

```python
# In _run_async_impl, after creating the REPL:
event_queue = asyncio.Queue()
llm_query_async, llm_query_batched_async = create_dispatch_closures(
    self.worker_pool, ctx, event_queue
)
repl.set_async_llm_query_fns(llm_query_async, llm_query_batched_async)
```

This also requires `worker_pool` to be a field on `RLMOrchestratorAgent` or passed through from `RLMAdkEngine`.

## Affected SRS requirements

- FR-011 (Sub-LM Query Support)
- AR-HIGH-005 (Routing Semantics)
- AR-CRIT-002 (Async Bridge via AST Rewrite)
