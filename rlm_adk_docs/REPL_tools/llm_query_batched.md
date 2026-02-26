# llm_query_batched

Query multiple sub-LLMs concurrently from within the REPL environment.

## Signature

```python
llm_query_batched(prompts: list[str], model: str | None = None) -> list[str]
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompts` | `list[str]` | required | List of text prompts to send concurrently. Each prompt can include up to ~500K characters. |
| `model` | `str \| None` | `None` | Optional model name override. `None` uses the depth-based default. |

## Returns

`list[str]` — List of LM text responses, in the same order as the input prompts.

## How It Works

Prompts are dispatched through the `WorkerPool` using ADK's `ParallelAgent`. When the number of prompts exceeds `max_concurrent` (the pool size), they are split into sequential batches — each batch runs its prompts in parallel, then the next batch starts.

All state mutations from workers are emitted as `Event` objects via the event queue (AR-CRIT-001 compliance). After each `ParallelAgent` batch completes, `worker.parent_agent` is cleared to allow worker reuse (Bug-7 fix).

The AST rewriter converts `llm_query_batched(...)` to `await llm_query_batched_async(...)` automatically.

## REPL Usage

```repl
# Analyze multiple chunks concurrently
chunks = [data[i:i+100000] for i in range(0, len(data), 100000)]
prompts = [f"Summarize this section:\n\n{chunk}" for chunk in chunks]
summaries = llm_query_batched(prompts)

for i, s in enumerate(summaries):
    print(f"Chunk {i}: {s[:200]}...")

# Aggregate results
combined = "\n---\n".join(f"Part {i+1}:\n{s}" for i, s in enumerate(summaries))
final = llm_query(f"Synthesize these summaries:\n\n{combined}")
print(final)
```

## Notes

- Much faster than sequential `llm_query` calls for independent queries.
- Results are always returned in the same order as the input prompts.
- The pool auto-creates on-demand workers if needed (capped at pool size after release).
- For a single query, `llm_query` is equivalent and simpler to use.

## Source

- Closure created in: `rlm_adk/dispatch.py` (`create_dispatch_closures`)
- Injected into REPL globals by: `rlm_adk/orchestrator.py` (via `repl.set_async_llm_query_fns`)
- AST rewrite: `rlm_adk/repl/ast_rewriter.py` (`llm_query_batched` -> `await llm_query_batched_async`)
