<!-- validated: 2026-03-09 -->
# Vision & Roadmap

> **For agents picking up autonomous tasks.** This doc describes where RLM-ADK is going, what features are planned, and how self-improvement works. Read this when you are spawned by a cron job, assigned a roadmap task, or need to understand the product direction before planning an implementation.

---

## What RLM-ADK Is Becoming

RLM-ADK is Rawley Stanhope's **personal agent** — a recursive, self-improving system that gets better at every task it has done before. It is not a multi-tenant platform. Every design decision optimizes for a single power user who wants an agent that:

1. **Learns from its own execution history** — past REPL code, IO signatures, and task outcomes become retrievable knowledge
2. **Shapes its own workflow per-task** — dynamic instructions configure topology (horizontal, vertical, hybrid) based on task classification
3. **Improves autonomously** — cron-triggered agents audit gaps, refactor patterns, and extend capabilities without human prompting

---

## Planned Features

### 1. Dynamic Skill Loading via REPL Embeddings

**Status:** Planned — research complete (`ai_docs/codebase_documentation_research/agent_skills_and_mcp_tools.md`)

**What it does:** Every REPL code block executed by the agent gets embedded into a vector store with metadata (IO types, task context, execution outcome, structured output schema). When a new prompt arrives, similar past executions are retrieved and injected as skill context — the agent remembers how it solved similar problems.

**Architecture:**

```
User Prompt
  → Embed prompt via Gemini text-embedding-004
  → Query vector store for similar past REPL executions
  → Retrieve top-K matches with metadata
  → Inject as skill context into dynamic instruction
  → Agent runs with primed skills
  → New execution gets embedded back into store (feedback loop)
```

**Key integration points:**
- **REPLTracingPlugin** already captures per-block traces with timing, variable snapshots, data flow edges → source of embedding metadata
- **Artifact service** already persists `repl_code_iter_N_turn_M.py` files → source of code text
- **Dynamic instruction** (`RLM_DYNAMIC_INSTRUCTION` in `utils/prompts.py`) is the injection target — currently a template with `{repo_url?}` and `{root_prompt?}`, ready for extension
- **Vector store:** ChromaDB for prototyping → LanceDB for production (see research doc for schema)

**Embedding metadata schema (planned):**

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

**Docs to read:** [skills_and_prompts.md](skills_and_prompts.md) (current skill system), [observability.md](observability.md) (REPL tracing pipeline), [artifacts_and_session.md](artifacts_and_session.md) (artifact persistence)

---

### 2. Polya Topology Engine (Dynamic Instruction Injection)

**Status:** Planned — research complete (`ai_docs/codebase_documentation_research/progressive_disclosure_patterns.md`, `rlm_adk_docs/codex_polya_workflow.md`)

**What it does:** Every agent run is structured as a Polya-inspired workflow: **Understand → Plan → Implement → Reflect**. The topology (how these phases map to agent turns and recursion depth) is configured per-task via dynamic instructions.

**Three topology variants:**

| Topology | How Polya Phases Execute | Best For |
|----------|-------------------------|----------|
| **Horizontal** | Each phase is a sequential REPL iteration at the same depth. Parent handles everything. | Simple tasks, code generation, quick analysis |
| **Vertical** | Each phase delegates to a child orchestrator at depth+1. Parent synthesizes. | Complex tasks requiring focused sub-agents per phase |
| **Hybrid** | Horizontal parent loop with vertical delegation at specific phases (e.g., Understand horizontally, Implement vertically) | Large tasks with mixed complexity |

**Integration points:**
- **Dynamic instruction** (`instructions` parameter on `LlmAgent`) — currently empty template, will carry topology configuration
- **`before_agent_callback`** — inspect incoming prompt, classify task, select topology
- **`before_model_callback`** — inject phase-specific instructions based on current state (which Polya phase, what depth)
- **State keys** — new keys for phase tracking: `polya_phase`, `polya_topology`, `polya_phase_history`
- **Depth scoping** — vertical topology uses existing `depth_key()` mechanism for per-phase state isolation

**Task classification → topology selection (planned):**

```
User prompt arrives
  → before_agent_callback fires
  → Classify prompt: complexity, domain, estimated depth
  → Select topology variant (horizontal/vertical/hybrid)
  → Inject topology config into dynamic instruction
  → Agent executes under selected topology
  → Reflect phase evaluates: was this topology effective?
  → Log topology choice + outcome for future classification improvement
```

**Docs to read:** [skills_and_prompts.md](skills_and_prompts.md) (dynamic instruction slot), [dispatch_and_state.md](dispatch_and_state.md) (depth scoping, state keys), [core_loop.md](core_loop.md) (callback chain, orchestrator lifecycle)

---

### 3. Autonomous Self-Improvement (Cron-Triggered Agents)

**Status:** Conceptual — no implementation yet

**What it does:** Agents are spawned on a schedule (cron or event-driven) to perform maintenance, improvement, and audit tasks without human prompting. Each autonomous agent reads this vision doc to understand the product direction, then executes its assigned task.

**Planned autonomous task types:**

| Task | Trigger | What It Does |
|------|---------|-------------|
| **Gap Audit** | Daily cron | Scan `rlm_adk_docs/gap_registry.json` for open observability/test gaps. Propose fixes or close resolved gaps. |
| **Doc Staleness Check** | Daily cron | Compare `<!-- validated: -->` dates against source file modification times. Flag or update stale docs. |
| **Test Coverage Expansion** | Weekly cron | Identify untested failure modes from FMEA matrix. Generate new fixture JSON files for uncovered scenarios. |
| **REPL Pattern Mining** | After each run | Analyze recent REPL executions for reusable patterns. Extract candidates for new skills. |
| **Dependency Audit** | Weekly cron | Check for outdated dependencies, security advisories, ADK version changes that affect monkey-patches. |
| **Performance Baseline** | Weekly cron | Run provider-fake contract suite, compare timing against historical baselines. Flag regressions. |

**Architecture for autonomous agents:**

```
Cron / Event Trigger
  → Spawn coding agent with task-specific prompt
  → Agent reads UNDERSTAND.md → vision.md → identifies relevant branches
  → Agent reads branch docs for task context
  → Agent executes task (code changes, doc updates, fixture generation)
  → Agent creates PR or updates tracking artifacts
  → Results logged for self-improvement feedback loop
```

**Constraints for autonomous agents:**
- Must operate within a worktree (isolated from main branch)
- Must create PRs, never push directly to main
- Must run tests before proposing changes
- Must update any docs they find stale during their work
- Must log their actions for auditability

**Open design questions:**
- How does the agent decide task priority when multiple gaps/issues exist?
- What's the feedback signal for "this autonomous improvement was valuable"?
- How do we prevent autonomous agents from creating churn (low-value PRs)?
- Should autonomous agents have a token/cost budget per run?

---

## Evolution Principles

### The agent should get better at tasks it has done before
Every execution produces artifacts (REPL traces, code, structured outputs) that feed back into the skill activation pipeline. The more the agent works, the richer its retrieval context becomes.

### The agent should know what it doesn't know
Gap registries, FMEA matrices, and observability metrics expose blind spots. Autonomous agents should prioritize closing the highest-impact gaps.

### The agent should maintain its own documentation
Stale docs are worse than no docs — they poison agent context. Every coding task that modifies documented behavior must update the corresponding doc. Autonomous staleness checks catch drift that humans miss.

### The agent should optimize its own topology
Polya phase outcomes (did Understanding lead to a good Plan? did the Plan survive Implementation?) provide signal for topology selection. Over time, the agent learns which topology works best for which task types.

---

## Research References

Detailed research on planned features is in `ai_docs/codebase_documentation_research/`:

| File | Relevant To |
|------|-------------|
| `agent_skills_and_mcp_tools.md` | Dynamic skill loading, REPL code vector store, MCP servers |
| `progressive_disclosure_patterns.md` | Polya topology, dynamic instruction patterns |
| `lsp_and_staleness_prevention.md` | Autonomous doc staleness detection (Griffe, tree-sitter) |
| `code_to_doc_tools.md` | Codebase indexing approaches for self-improvement |

---

## Recent Changes

> Append entries here when modifying source files documented by this branch. A stop hook (`ai_docs/scripts/check_doc_staleness.py`) will remind you.

- **2026-03-09 13:00** — Initial branch doc created from codebase exploration.

<!-- Example entry format:
- **YYYY-MM-DD HH:MM** — `filename.py`: Brief description of what changed
-->
