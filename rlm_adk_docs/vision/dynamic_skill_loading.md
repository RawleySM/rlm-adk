<!-- validated: 2026-03-09 -->

# Dynamic Skill Loading via REPL Embeddings

**Status:** Planned — research complete (`ai_docs/codebase_documentation_research/agent_skills_and_mcp_tools.md`)

**What it does:** Every REPL code block executed by the agent gets embedded into a vector store with metadata (IO types, task context, execution outcome, structured output schema). When a new prompt arrives, similar past executions are retrieved and injected as skill context — the agent remembers how it solved similar problems.

---

## Architecture

```
User Prompt
  → Embed prompt via Gemini text-embedding-004
  → Query vector store for similar past REPL executions
  → Retrieve top-K matches with metadata
  → Inject as skill context into dynamic instruction
  → Agent runs with primed skills
  → New execution gets embedded back into store (feedback loop)
```

## Key Integration Points

- **REPLTracingPlugin** already captures per-block traces with timing, variable snapshots, data flow edges → source of embedding metadata
- **Artifact service** already persists `repl_code_d{D}_f{F}_iter_{N}_turn_{M}.py` files → source of code text
- **Dynamic instruction** (`RLM_DYNAMIC_INSTRUCTION` in `utils/prompts.py`) is the injection target — currently a template with `{repo_url?}` and `{root_prompt?}`, ready for extension
- **Vector store:** ChromaDB for prototyping → LanceDB for production (see research doc for schema)

## Embedding Metadata Schema (Planned)

```python
{
    "code": str,                    # REPL code text
    "code_hash": str,               # SHA256 for dedup
    "task_context": str,            # Root prompt that triggered this execution
    "io_types": {
        "inputs": list[str],        # Variable types consumed
        "outputs": list[str],       # Variable types produced
    },
    "structured_output_schema": str | None,  # Pydantic schema name if used
    "execution_outcome": str,       # "success" | "error" | "partial"
    "depth": int,                   # Recursion depth where this ran
    "llm_calls_made": int,          # Child dispatches from this block
    "data_flow_edges": list[tuple], # Which outputs fed into next inputs
    "wall_time_ms": float,          # Execution duration
    "timestamp": str,               # ISO 8601
}
```

## Related Docs

- [skills_and_prompts.md](../skills_and_prompts.md) — current skill system
- [observability.md](../observability.md) — REPL tracing pipeline
- [artifacts_and_session.md](../artifacts_and_session.md) — artifact persistence

## Research References

- `ai_docs/codebase_documentation_research/agent_skills_and_mcp_tools.md`
