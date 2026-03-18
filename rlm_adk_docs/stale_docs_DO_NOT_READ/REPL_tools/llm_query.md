# llm_query

Query a sub-LLM from within the REPL environment.

## Signature

```python
llm_query(prompt: str, model: str | None = None) -> str
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | `str` | required | The text prompt to send to the sub-LM. Can include up to ~500K characters of context. |
| `model` | `str \| None` | `None` | Optional model name override. `None` uses the depth-based default (same model as the worker pool). |

## Returns

`str` — The LM's text response.

## How It Works

Under the hood, `llm_query` delegates to `llm_query_batched` with a single-element list (K=1 case). The AST rewriter transparently converts `llm_query(...)` calls to `await llm_query_async(...)` so the orchestrator's async event loop is not blocked.

The call is dispatched through the `WorkerPool`, which acquires a pre-configured `LlmAgent` worker, runs it via ADK's `ParallelAgent`, and returns the text response. State mutations from the worker are emitted as `Event` objects on the event queue (not written directly to session state).

## REPL Usage

```repl
# Simple query
answer = llm_query("What is the capital of France?")
print(answer)

# Query with context from a file
data = open("/path/to/document.txt").read()
summary = llm_query(f"Summarize this document:\n\n{data}")
print(summary)

# Query with a lot of context (sub-LLMs handle ~500K chars)
chunk = open("/path/to/large_file.txt").read()[:400000]
analysis = llm_query(f"Analyze this data:\n\n{chunk}")
print(analysis)
```

## Notes

- Do **not** call `llm_query()` synchronously in ADK mode — the AST rewriter handles the async conversion automatically.
- If the AST rewriter fails to detect the call, a `RuntimeError` is raised with a diagnostic message.
- For multiple independent queries, prefer `llm_query_batched` for concurrent execution.

## Source

- Closure created in: `rlm_adk/dispatch.py` (`create_dispatch_closures`)
- Injected into REPL globals by: `rlm_adk/orchestrator.py` (via `repl.set_async_llm_query_fns`)
- AST rewrite: `rlm_adk/repl/ast_rewriter.py` (`llm_query` -> `await llm_query_async`)
