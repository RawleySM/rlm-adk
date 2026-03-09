# Progressive Disclosure Documentation Plan for RLM-ADK

## Objective

Create a single-entrypoint documentation system (`rlm_adk_docs/UNDERSTAND.md`) that gives coding agents the **minimum essential context** for any given task. Every section beyond the overview links to a deeper file that agents read **only if their task requires it**.

---

## Design Principles

### From Research Findings

1. **100-Line Rule** (progressive_disclosure_patterns.md): The root document should fit in ~100-150 lines. Agents load the overview, identify the relevant branch, then deep-dive into exactly one or two linked files.

2. **Three-Level Loading** (code_to_doc_tools.md): Metadata → Instructions → References. UNDERSTAND.md is Layer 0 (metadata + routing). Linked docs are Layer 1 (instructions + architecture). Source code is Layer 2 (references).

3. **Staleness Prevention** (lsp_and_staleness_prevention.md): Use Griffe for API signature drift detection + git-diff timestamp comparison script + CI hook. Documents that drift from code become poison for agents.

4. **No Vector Store for Docs** (progressive_disclosure_patterns.md): Claude Code's own team found agentic search (Glob/Grep/Read) outperforms vector retrieval for code navigation. Progressive disclosure with explicit file paths is the right pattern. Vector stores are better suited for the REPL code history feature (future work).

---

## Document Tree Architecture

```
rlm_adk_docs/UNDERSTAND.md          ← Single entrypoint (~150 lines)
  │
  ├── rlm_adk_docs/core_loop.md              ← Orchestrator, REPL, AST rewriter, recursion
  ├── rlm_adk_docs/dispatch_and_state.md     ← WorkerPool, closures, AR-CRIT-001, depth scoping
  ├── rlm_adk_docs/observability.md          ← Plugins, callbacks, worker obs path, state keys
  ├── rlm_adk_docs/testing.md                ← Provider-fake, FMEA, fixtures, replay, markers
  ├── rlm_adk_docs/artifacts_and_session.md  ← FileArtifactService, SqliteSessionService, save helpers
  ├── rlm_adk_docs/skills_and_prompts.md     ← Skill system, static/dynamic instructions, child prompts
  ├── rlm_adk_docs/configuration.md          ← Env vars, pyproject.toml, factory functions
  └── rlm_adk_docs/adk_gotchas.md            ← Pydantic constraints, private API usage, known bugs
```

### Why This Tree

Each branch maps to a **domain of change**. An agent tasked with:
- "Add a new observability metric" → reads UNDERSTAND.md → follows link to `observability.md` → done
- "Create a new test fixture" → reads UNDERSTAND.md → follows link to `testing.md` → done
- "Wire the dynamic instruction parameter" → reads UNDERSTAND.md → follows `skills_and_prompts.md` + `dispatch_and_state.md`
- "Add a new REPL helper function" → reads UNDERSTAND.md → follows `core_loop.md`

### Future Work Branches (Planned)

These branches will be created when the features are implemented:

```
  ├── rlm_adk_docs/dynamic_skills.md         ← Vector store, REPL code embeddings, skill activation
  ├── rlm_adk_docs/polya_topology.md          ← Dynamic instruction engine, horizontal/vertical/hybrid
  └── rlm_adk_docs/self_improvement.md        ← Feedback loops, doc auto-correction, quality signals
```

---

## UNDERSTAND.md Content Structure

The entrypoint document contains these sections (all concise, all with deep-dive links):

### 1. What RLM-ADK Is (3-5 lines)
Current state: recursive LLM agent on Google ADK. One Gemini model serves as both parent and child. REPL-first architecture.

### 2. Vision: Personal Agent (3-5 lines)
Where it's going: Rawley Stanhope's personal agent. Self-improving through REPL code history, dynamic skill activation, and topology-aware workflows.

### 3. Vision: Self-Improvement (3-5 lines)
How it evolves: Embeddings over REPL execution history feed back into skill discovery. Dynamic instructions shape agent behavior per-task. The agent gets better at tasks it has done before.

### 4. Runtime Entrypoints (table)
- `adk run rlm_adk` → CLI
- `adk web rlm_adk` → Web UI
- `create_rlm_runner()` → Programmatic
- `create_rlm_app()` → App wrapper
- Link: `core_loop.md`

### 5. Core Loop (ASCII diagram + 3 lines)
The collapsed orchestrator → reasoning_agent → REPLTool → llm_query → recursion flow.
- Link: `core_loop.md`

### 6. Essential Services (table)
| Service | Purpose | Link |
|---------|---------|------|
| SqliteSessionService | Persistent state across invocations | `artifacts_and_session.md` |
| FileArtifactService | Versioned file persistence | `artifacts_and_session.md` |
| ObservabilityPlugin | Token accounting, finish reasons | `observability.md` |
| SqliteTracingPlugin | Traces/telemetry to .adk/traces.db | `observability.md` |
| REPLTracingPlugin | Per-block REPL traces | `observability.md` |
| LangfuseTracingPlugin | OTel → Langfuse UI | `observability.md` |

### 7. Testing (3 lines + link)
Provider-fake (deterministic, no network), FMEA failure modes, replay fixtures.
- Link: `testing.md`

### 8. State Management (3 lines + link)
AR-CRIT-001 rules, depth scoping, accumulator pattern.
- Link: `dispatch_and_state.md`

### 9. Skills & Prompts (3 lines + link)
YAML frontmatter skills, static/dynamic instructions, child instruction condensation.
- Link: `skills_and_prompts.md`

### 10. Configuration (3 lines + link)
Env vars (RLM_ADK_MODEL, RLM_MAX_ITERATIONS, etc.), factory functions, plugin wiring.
- Link: `configuration.md`

### 11. ADK Gotchas (3 lines + link)
Pydantic model constraints, private API usage, BUG-13 monkey-patch.
- Link: `adk_gotchas.md`

### 12. Staleness Policy (5 lines)
How docs stay accurate. See next section.

---

## Staleness Prevention Strategy

### Tier 1: Convention (Zero Cost)
- Each deep-dive doc has a `<!-- validated: YYYY-MM-DD -->` comment at the top
- UNDERSTAND.md has a `<!-- last-audit: YYYY-MM-DD -->` comment
- Any PR that modifies files in a documented module SHOULD update the corresponding doc

### Tier 2: Automated Detection (Low Cost)
- **Griffe API diff**: Run `griffe dump rlm_adk` on CI. Compare public API signatures against documented signatures in deep-dive docs. Flag drift.
- **Git timestamp script**: `ai_docs/scripts/check_staleness.sh` — for each deep-dive doc, compare its last-modified date against last-modified dates of the source files it documents. Warn if source is newer by >7 days.
- **Pre-commit hook**: Warn (not block) when modifying files in `rlm_adk/` without touching corresponding `rlm_adk_docs/` file.

### Tier 3: Agent Self-Correction (Future)
- After completing a task, the coding agent checks whether any doc it read was inaccurate
- If inaccurate, it updates the doc as part of its PR
- This creates a natural feedback loop: docs that get read get corrected

### What We Explicitly Avoid
- **Generated docs** (sphinx-autodoc, pdoc) — these produce bulk text that wastes agent context
- **Vector store over docs** — premature for a solo project; agentic search + progressive disclosure is sufficient
- **Monolithic architecture doc** — the existing STATE.md is 285 lines; useful for humans but too large for task-scoped agent context

---

## Task Mapping: How Future Features Route Through the Tree

### Feature: Dynamic Skill Loading via REPL Embeddings

An agent implementing this would need:
1. **UNDERSTAND.md** → identify relevant branches
2. **`skills_and_prompts.md`** → understand current skill system (YAML frontmatter, activation model)
3. **`core_loop.md`** → understand REPL execution, how code flows through LocalREPL
4. **`observability.md`** → understand REPLTracingPlugin (already captures per-block traces with metadata)
5. **`artifacts_and_session.md`** → understand artifact persistence (REPL code already saved as artifacts)

New doc to create: **`dynamic_skills.md`** covering:
- Vector store schema (code text, IO types, task context, embedding)
- Embedding pipeline (which model, chunking strategy, metadata extraction)
- Skill activation flow (user prompt → embedding similarity → skill injection into dynamic instruction)
- Integration points with existing REPL tracing and artifact pipelines

### Feature: Polya Topology Engine (Dynamic Instruction Injection)

An agent implementing this would need:
1. **UNDERSTAND.md** → identify relevant branches
2. **`skills_and_prompts.md`** → understand dynamic instruction parameter (currently empty template)
3. **`dispatch_and_state.md`** → understand depth scoping, how child orchestrators are created
4. **`core_loop.md`** → understand before_model callback chain where instructions get injected
5. **`configuration.md`** → understand env var and factory function patterns

New doc to create: **`polya_topology.md`** covering:
- Polya phases (Understanding → Planning → Implementation → Reflection) as state machine
- Topological variants:
  - **Horizontal**: Sequential parent turns, no depth increase. Each Polya phase is a REPL iteration.
  - **Vertical**: Each Polya phase delegates to a child orchestrator at depth+1. Parent synthesizes.
  - **Hybrid**: Horizontal parent loop with vertical delegation at specific phases.
- Dynamic instruction templates per topology
- Task classification → topology selection
- State keys for topology tracking (phase, strategy, depth allocation)
- Integration with before_agent_callback / before_model_callback

---

## Implementation Sequence

### Phase 1: Create Deep-Dive Docs (from explorer outputs)
Source material: `ai_docs/codebase_documentation_research/explorer_*.md`

1. `rlm_adk_docs/core_loop.md` ← from `explorer_core_loop.md` (distill to essentials)
2. `rlm_adk_docs/dispatch_and_state.md` ← from `explorer_dispatch_state_session.md`
3. `rlm_adk_docs/observability.md` ← from `explorer_observability_plugins.md`
4. `rlm_adk_docs/testing.md` ← from `explorer_testing_infrastructure.md`
5. `rlm_adk_docs/artifacts_and_session.md` ← extract from explorer_dispatch + explorer_observability
6. `rlm_adk_docs/skills_and_prompts.md` ← extract from explorer_core_loop (sections 7.1-7.4)
7. `rlm_adk_docs/configuration.md` ← extract from explorer_dispatch (section 5) + explorer_core_loop (section 14)
8. `rlm_adk_docs/adk_gotchas.md` ← extract from CLAUDE.md + explorer findings

### Phase 2: Create UNDERSTAND.md Entrypoint
- Write the ~150-line overview with links to all Phase 1 docs
- Add `<!-- validated: YYYY-MM-DD -->` comments to all docs

### Phase 3: Staleness Tooling
- Create `ai_docs/scripts/check_staleness.sh`
- Add Griffe to dev dependencies
- Add pre-commit hook (warn-only)

### Phase 4: Retire Redundant Docs
- Move `rlm_adk_docs/STATE.md` → `rlm_adk_docs/stale_docs_DO_NOT_READ/`
- Move `rlm_adk_docs/architecture_summary.md` → `rlm_adk_docs/stale_docs_DO_NOT_READ/`
- Update CLAUDE.md to reference UNDERSTAND.md instead of STATE.md

### Phase 5: Future Feature Docs (when implemented)
- Create `rlm_adk_docs/dynamic_skills.md`
- Create `rlm_adk_docs/polya_topology.md`
- Create `rlm_adk_docs/self_improvement.md`

---

## Research References

All research findings are persisted in `ai_docs/codebase_documentation_research/`:

| File | Contents |
|------|----------|
| `code_to_doc_tools.md` | Repomix, aider repo-map, Cursor indexing, code2prompt, llms.txt |
| `lsp_and_staleness_prevention.md` | LSP, tree-sitter, Griffe, staleness detection, CI hooks |
| `progressive_disclosure_patterns.md` | Layered docs, token budgets, multi-agent strategies, evaluation matrix |
| `agent_skills_and_mcp_tools.md` | MCP servers, embeddings, vector stores, REPL code history plan |
| `explorer_core_loop.md` | Full orchestrator/REPL/dispatch exploration |
| `explorer_testing_infrastructure.md` | Full testing system exploration |
| `explorer_observability_plugins.md` | Full observability stack exploration |
| `explorer_dispatch_state_session.md` | Full dispatch/state/session exploration |
