# Progressive Disclosure Patterns for AI Agent Consumption of Codebases

Research compiled March 2026. Focused on patterns where AI coding agents (Claude Code, Cursor, Copilot, Aider, Codex) consume codebase documentation with minimal-but-sufficient context.

---

## Table of Contents

1. [Core Principle: Progressive Disclosure for Agents](#1-core-principle-progressive-disclosure-for-agents)
2. [Context Window Optimization Strategies](#2-context-window-optimization-strategies)
3. [Agent-Oriented Documentation Formats](#3-agent-oriented-documentation-formats)
4. [Multi-Agent Documentation Strategies](#4-multi-agent-documentation-strategies)
5. [Open-Source Examples and Real-World Patterns](#5-open-source-examples-and-real-world-patterns)
6. [Vector Store / Embeddings vs. Agentic Search](#6-vector-store--embeddings-vs-agentic-search)
7. [Pattern Evaluation Matrix](#7-pattern-evaluation-matrix)
8. [Recommended Architecture](#8-recommended-architecture)

---

## 1. Core Principle: Progressive Disclosure for Agents

Progressive disclosure is an information architecture pattern borrowed from UX design: reveal complexity gradually rather than all at once. For AI agents, this means **loading the minimum context needed to make the next decision, then expanding only when the task requires it**.

### Why This Matters for LLMs

Counterintuitively, giving LLMs more context often makes them perform *worse*, not better. Current-generation models struggle to maintain attention across large contexts, particularly with complex instruction sets. The failure mode is not hallucination but *instruction dropping* -- the model silently ignores rules buried in a wall of text.

The goal is not "provide less information" but "provide the right information at the right time."

### The Three-Level Loading Model

Anthropic's Agent Skills architecture formalizes this into three tiers:

| Level | What Loads | When It Loads | Token Cost |
|-------|-----------|---------------|------------|
| **L1: Metadata** | YAML frontmatter (name, description, triggers) | Session start -- every skill's metadata is in the system prompt | ~100 tokens per skill |
| **L2: Instructions** | SKILL.md body (workflows, rules, procedures) | On invocation -- when the agent decides this skill is relevant | ~500-5,000 tokens |
| **L3: References** | Supporting files (specs, examples, data) | On demand -- only when instructions explicitly reference them | Unbounded (read as needed) |

This is the canonical progressive disclosure pattern for agent documentation. The key insight: **L1 must be sufficient for the agent to decide whether to load L2, and L2 must be sufficient to decide whether to load L3.**

### Anti-Patterns

- **Monolithic CLAUDE.md**: A single file exceeding 500 lines that covers everything from build commands to architecture to gotchas. The agent loads all of it on every conversation, burning tokens on irrelevant sections.
- **Flat reference dumps**: Concatenating all source files into one massive document (repomix-style) without an index or hierarchy. The agent must scan everything to find anything.
- **Implicit knowledge**: Assuming the agent will "figure out" which files to read. Without explicit pointers (file paths, section headers), the agent wastes tool calls on exploration.

---

## 2. Context Window Optimization Strategies

### 2.1 Layered Documentation (Overview to Detail)

The most effective pattern is a strict hierarchy where each layer links to the next:

```
CLAUDE.md (root)              -- ~100 lines: build, test, critical rules
  |
  +-- ARCHITECTURE.md         -- ~200-400 lines: system design, core flow, module map
  |     |
  |     +-- Module-level docs -- per-module AGENTS.md or inline docstrings
  |           |
  |           +-- Source code  -- the actual implementation
  |
  +-- .claude/skills/          -- task-specific procedural knowledge
        |
        +-- SKILL.md           -- workflow instructions
              |
              +-- references/  -- specs, examples, data files
```

**Key rule**: Each layer should contain explicit file paths pointing to the next layer. The agent should never need to `find` or `glob` to discover where deeper documentation lives.

### 2.2 Token Budget Awareness

Different tools handle token budgets differently:

| Tool | Strategy | Default Budget |
|------|----------|---------------|
| **Aider** | Tree-sitter repo map with PageRank graph ranking. Dynamically sizes the map based on chat state. | ~1,024 tokens for repo map |
| **Claude Code** | Agentic search (Grep/Glob/Read tools). No pre-built index. | No fixed budget; reads files on demand |
| **Cursor** | .cursor/rules loaded at prompt level + semantic index | Rules always loaded; index queried per-turn |
| **Repomix** | Full codebase concatenation with `--compress` option using tree-sitter | Entire repo (compress reduces ~60%) |

The tradeoff: pre-built indexes (Aider, Cursor) are fast but stale; agentic search (Claude Code) is always fresh but burns more tokens on exploration.

### 2.3 Index Files with Explicit File Paths

The single highest-ROI pattern is an **index file** that maps concepts to file paths:

```markdown
## Key Modules

| Concept | File | What It Does |
|---------|------|-------------|
| Orchestrator | `rlm_adk/orchestrator.py` | Top-level agent, delegates to reasoning_agent |
| Dispatch | `rlm_adk/dispatch.py` | WorkerPool, llm_query closures, flush_fn |
| REPL Tool | `rlm_adk/tools/repl_tool.py` | Code execution, AST detection, call limits |
| State Keys | `rlm_adk/state.py` | All state constants + depth_key() |
```

This eliminates the most expensive agent operation: **exploratory glob/grep to locate relevant files.** The agent reads the index (~200 tokens), identifies the 1-2 files it needs, and reads only those.

### 2.4 Decision Trees for Context Selection

For agents that serve multiple roles, a decision tree in the root doc can route them to the right context:

```markdown
## What Do You Need?

- **Building/running the project?** See "Build & Run" below
- **Understanding the architecture?** Read `ARCHITECTURE.md`
- **Writing a new test?** Read `tests_rlm_adk/README.md`
- **Debugging a state mutation bug?** Read "State Mutation Rules" below, then `rlm_adk/state.py`
- **Adding a new plugin?** See `.claude/skills/gap-audit/SKILL.md` for the pattern
```

This is more token-efficient than a flat structure because the agent can skip entire sections.

---

## 3. Agent-Oriented Documentation Formats

### 3.1 What LLMs Parse Well

Based on observed performance across Claude, GPT-4, and Gemini:

**High signal-to-noise formats:**
- Markdown tables (module maps, API references, configuration matrices)
- Bullet lists with bold lead terms (`**NEVER** write ctx.session.state directly`)
- Code blocks with inline comments for "do this, not that" patterns
- ASCII diagrams for data flow (parsed more reliably than Mermaid)
- Explicit file paths (absolute preferred, always with backtick formatting)

**Low signal-to-noise formats:**
- Prose paragraphs explaining "why" without actionable rules
- Deeply nested headers (more than 3 levels becomes noise)
- Mermaid/PlantUML diagrams (unreliable parsing; fall back to ASCII trees)
- Links to external URLs (the agent cannot follow them unless it has web access)

### 3.2 Structured Markdown Conventions

The most effective CLAUDE.md files share these structural patterns:

1. **Imperative voice**: "Run `pytest tests/`" not "You can run the tests with pytest"
2. **Bold warnings for critical rules**: `**NEVER**`, `**IMPORTANT**`, `**DO NOT**`
3. **Concrete examples over abstract descriptions**: Show the command, the file path, the code snippet
4. **Section headers as retrieval anchors**: The agent uses headers to skip sections. Make them specific: "State Mutation Rules (AR-CRIT-001)" not "Important Notes"
5. **Token-counted skill metadata**: Include line counts, token estimates, and file sizes in indexes so the agent can budget

### 3.3 The CLAUDE.md "100-Line Rule"

Anthropic's guidance: keep root CLAUDE.md under 100 lines. This file loads on every conversation, so every line has a per-session token cost. Content that belongs elsewhere:

| Content Type | Where It Goes | Why |
|-------------|--------------|-----|
| Build/test commands | Root CLAUDE.md | Needed every session |
| Critical invariants (3-5 max) | Root CLAUDE.md | Prevents catastrophic mistakes |
| Architecture overview | ARCHITECTURE.md (linked) | Only needed for design tasks |
| Module-specific rules | Nested AGENTS.md in subdirectory | Only loaded when editing that module |
| Workflow procedures | .claude/skills/*/SKILL.md | Only loaded when that workflow is invoked |
| API references, specs | .claude/skills/*/references/ | Only loaded on explicit demand |

### 3.4 Nested AGENTS.md Pattern

Most modern AI coding tools (Claude Code, Cursor, Copilot, Codex) support hierarchical instruction files. A nested AGENTS.md in a subdirectory provides context only when the agent is working in that directory:

```
project/
  AGENTS.md                    -- global rules (always loaded)
  rlm_adk/
    AGENTS.md                  -- package-level rules (loaded when editing rlm_adk/)
    plugins/
      AGENTS.md                -- plugin-specific rules (loaded when editing plugins/)
  tests_rlm_adk/
    AGENTS.md                  -- test-specific rules (loaded when editing tests/)
```

Priority resolution: the file closest to the edited file takes precedence, with ancestors providing fallback context. This naturally implements progressive disclosure at the filesystem level.

---

## 4. Multi-Agent Documentation Strategies

### 4.1 Role-Specific Context Needs

Different agent roles need fundamentally different slices of documentation:

| Role | Primary Context | Secondary Context | Should NOT See |
|------|----------------|-------------------|----------------|
| **Planner** | Architecture overview, module map, capability inventory | Dependency graph, known limitations | Implementation details, test fixtures |
| **Implementer** | Module-specific code, API contracts, state mutation rules, gotchas | Architecture for cross-module work | Test infrastructure, deployment docs |
| **Reviewer** | Coding conventions, critical invariants, test expectations | Architecture for design review | Build commands, deployment details |
| **Tester** | Test infrastructure docs, fixture patterns, assertion conventions | Module APIs being tested | Architecture philosophy, deployment |
| **Debugger** | State flow diagrams, observability stack, known bugs | Full architecture, dispatch internals | Test fixtures, build commands |

### 4.2 Artifact-Centric Communication

In multi-agent systems (like AgentMesh, VS Code Agents, or Claude Code sub-agents), agents communicate primarily through artifacts rather than shared context. The documentation strategy should mirror this:

1. **Planner** writes a plan document (structured markdown with task breakdown)
2. **Implementer** reads the plan + relevant module docs, writes code
3. **Reviewer** reads the code + coding conventions doc, writes review comments
4. **Tester** reads the code + test infrastructure docs, writes tests

Each agent loads only its role-specific documentation. The shared artifact (code, plan, review) is the communication channel.

### 4.3 Scoped Sub-Agent Instructions

For recursive or hierarchical agent systems (like RLM-ADK itself), documentation can be scoped per depth level:

```markdown
## Sub-Agent Context Loading

When spawning a child agent via llm_query():
- **Always include**: The task description and expected output schema
- **Include if relevant**: The specific module doc for the code being analyzed
- **Never include**: Parent's full conversation history, architecture overview, build commands
```

The principle: child agents should receive the minimum viable context for their specific task, not a copy of the parent's full context window.

---

## 5. Open-Source Examples and Real-World Patterns

### 5.1 Codified Context Infrastructure (Vasilopoulos, 2026)

**Paper**: "Codified Context: Infrastructure for AI Agents in a Complex Codebase" (arXiv:2602.20478)
**Repo**: github.com/arisvas4/codified-context-infrastructure

The most rigorous treatment of this problem. Developed during construction of a 108,000-line C# distributed system across 283 development sessions. Three components:

1. **Hot Memory (Constitution)**: Always-loaded document encoding conventions, retrieval hooks, and orchestration protocols. Equivalent to CLAUDE.md but more structured -- includes explicit "how to find X" directives.

2. **Domain-Expert Agents** (19 total): Each agent has a scoped constitution fragment. A "Database Agent" loads DB-specific conventions; a "Security Agent" loads security policies. This is the multi-agent pattern from Section 4 made concrete.

3. **Cold Memory (Knowledge Base)**: 34 on-demand specification documents loaded via MCP retrieval. The constitution references these by name; agents load them only when the task requires deep domain knowledge.

**Key finding**: Context documents use tables, code blocks, and explicit patterns rather than prose. Agents parse structured content more reliably than natural language descriptions.

**Quantitative result**: Measured across 283 sessions, codified context prevented recurring failures and maintained consistency that single-file approaches (cursorrules, CLAUDE.md alone) could not sustain beyond ~10K lines of code.

### 5.2 Anthropic's Agent Skills (2025-2026)

**Docs**: platform.claude.com/docs/en/agents-and-tools/agent-skills/
**Blog**: anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills

The canonical implementation of three-level progressive disclosure:
- L1 metadata in YAML frontmatter (~100 tokens, loaded at startup)
- L2 instructions in SKILL.md body (~5K tokens, loaded on invocation)
- L3 references in supporting files (unbounded, loaded on demand)

Published as an open standard (December 2025) for cross-platform portability. The key constraint: **SKILL.md body should stay under 500 lines** for optimal performance.

### 5.3 Aider's Repository Map

**Docs**: aider.chat/docs/repomap.html

Uses tree-sitter to parse source files and extract symbol definitions (functions, classes, methods). Builds a dependency graph where files are nodes and imports are edges. Applies PageRank-style graph ranking to select the most relevant files for the current context.

Key innovation: **dynamic budget allocation**. The repo map expands when no files are in the chat (agent needs broad orientation) and shrinks when specific files are added (agent has focused context). Default budget: ~1,024 tokens.

### 5.4 Cursor Rules (.cursor/rules/)

**Docs**: docs.cursor.com/context/rules

MDC (Markdown-based) format files in .cursor/rules/. Each rule file can specify:
- `globs`: file patterns that trigger the rule (e.g., `*.test.ts`)
- `alwaysApply`: whether to load on every conversation
- `description`: for the agent to decide relevance

This is progressive disclosure at the rule level: rules with `alwaysApply: false` and a description are loaded only when the agent decides they are relevant (analogous to Claude Skills L1/L2).

### 5.5 Repomix Skill Pattern

**Repo**: github.com/yamadashy/repomix

Generates a Claude Code skill from an entire repository:
- `SKILL.md` -- index with usage instructions
- `references/summary.md` -- statistics and format explanation
- `references/project-structure.md` -- directory tree with line counts
- `references/files.md` -- all file contents (the "cold memory")
- `references/tech-stack.md` -- languages, frameworks, dependencies

The progressive disclosure here is: SKILL.md (L2) tells the agent to search in `files.md` (L3) using grep patterns like `## File: src/utils/helpers.ts`. The agent never loads the full files.md; it reads the index, greps for the relevant section, and reads only that.

### 5.6 jCodeMunch MCP Server

**Repo**: github.com/jgravelle/jcodemunch-mcp

Tree-sitter-based AST indexing exposed via MCP. On session start, a Go binary builds a complete dependency graph. Agents query by symbol name rather than file path, getting back only the relevant function/class definition.

Token efficiency is high (returns only the requested symbol, not the full file), but requires a build step and is language-limited (TypeScript, JavaScript, Python, Go as of early 2026).

### 5.7 Kaushik Gopal's "One Source of Truth" Pattern

**Blog**: kau.sh/blog/agents-md/

Advocates for a single AGENTS.md as the canonical source, with tool-specific files (.cursorrules, CLAUDE.md) generated from it. Prevents drift between instruction files for different tools. Uses a build step or CI check to keep derived files in sync.

---

## 6. Vector Store / Embeddings vs. Agentic Search

### 6.1 The RAG Debate (2025-2026)

Claude Code's development team (Boris Cherny, Anthropic) explicitly tried and abandoned local vector DB-based RAG in early versions, finding that agentic search (Grep/Glob/Read tools) generally works better for code navigation.

**Why agentic search won for Claude Code:**

| Dimension | Vector RAG | Agentic Search |
|-----------|-----------|----------------|
| **Freshness** | Stale until re-indexed | Always reads current files |
| **Privacy** | Embeddings may leak to external service | Data never leaves the machine |
| **Reliability** | Index corruption, version mismatch | Standard filesystem operations |
| **Setup cost** | Embedding model + vector DB + indexing pipeline | Zero setup |
| **Concept search** | Strong (semantic similarity) | Weak (literal text matching) |
| **Large repos** | O(1) retrieval regardless of repo size | O(n) grep over files |

### 6.2 Where Embeddings Still Win

The 2026 consensus is not "RAG is dead" but "agentic search is the backbone, with semantic indexing only where needed":

1. **Concept search**: Finding code related to "authentication flow" when no file is named `auth`. Embeddings capture semantic similarity that grep cannot.
2. **Massive repos**: In repos with 100K+ files, grep-based exploration becomes impractically slow. A pre-built index gives O(1) retrieval.
3. **Non-code knowledge**: Design docs, decision records, meeting notes -- content that is relevant but not discoverable by code-oriented search patterns.
4. **Cross-session memory**: Embeddings can persist across sessions, giving agents long-term memory that filesystem search cannot provide.

### 6.3 Hybrid Approaches

The strongest pattern combines both:

```
Agent Query
  |
  +-- Fast path: Check index files / CLAUDE.md / AGENTS.md
  |     (structured, explicit pointers -- zero embedding cost)
  |
  +-- Focused search: Grep/Glob for specific symbols, patterns
  |     (agentic search -- always fresh, zero indexing cost)
  |
  +-- Semantic fallback: Query vector index for concept search
        (embedding-based -- handles ambiguous/conceptual queries)
```

The key insight: **well-structured documentation (Sections 2-3) reduces the need for semantic search**. If the index file maps concepts to files, the agent does not need embeddings to find them. Embeddings become a fallback for genuinely ambiguous queries.

### 6.4 Graph RAG for Codebases

An emerging pattern (code-graph-rag, Vertex AI RAG Engine) uses knowledge graphs rather than flat vector stores:

1. Build a dependency graph (tree-sitter AST parsing)
2. Embed nodes (functions, classes, modules) with structural context
3. Query via semantic search to find entry nodes
4. Traverse the graph for relational context (callers, callees, dependencies)

This gives both semantic discovery (embeddings) and structural navigation (graph traversal). The maintenance burden is higher than either pure approach, but accuracy is also higher for cross-cutting queries like "what happens when a worker fails?"

---

## 7. Pattern Evaluation Matrix

| Pattern | Token Efficiency | Accuracy | Staleness Risk | Maintenance Burden |
|---------|-----------------|----------|----------------|-------------------|
| **Monolithic CLAUDE.md** | Low (loads everything every session) | Medium (all info present but attention degrades) | Low (single file to update) | Low |
| **Three-level Skills** | High (L1 ~100 tok, L2 ~5K tok, L3 on demand) | High (right context at right time) | Medium (must update skill when code changes) | Medium |
| **Nested AGENTS.md** | High (only loads for active directory) | High (scoped to relevant module) | Medium (per-directory files to maintain) | Medium |
| **Aider repo map** | High (dynamic budget, ~1K tokens) | Medium-High (graph ranking is heuristic) | Low (rebuilt from AST each session) | Low (automatic) |
| **Repomix full dump** | Very Low (entire codebase in context) | Medium (everything present, attention issues) | Low (regenerated on demand) | Low (one command) |
| **Codified Context (hot/cold)** | High (constitution always, specs on demand) | Very High (structured for machine parsing) | Medium (34 spec docs to maintain) | High (283-session study shows it pays off) |
| **Vector RAG** | High (retrieves only relevant chunks) | Medium-High (depends on embedding quality) | High (requires re-indexing) | High (embedding pipeline + vector DB) |
| **Agentic search (Grep/Glob)** | Medium (exploration burns tokens) | High (reads actual current code) | None (always fresh) | None |
| **Index files with paths** | Very High (~200 tokens to locate any file) | Very High (explicit, deterministic) | Medium (must update when files move) | Low-Medium |

### Cost-Accuracy Frontier

The best cost-accuracy tradeoff for most projects:

1. **Index file** (very high efficiency, very high accuracy) -- always include
2. **Three-level skills** for complex workflows -- include for projects with >5 distinct workflows
3. **Nested AGENTS.md** for monorepos or projects with distinct modules -- include if >3 major modules
4. **Agentic search** as fallback -- free, always available
5. **Vector RAG** only for repos >50K files or heavy concept-search needs

---

## 8. Recommended Architecture

Based on the research above, here is a proposed layered documentation structure optimized for AI agent consumption. The design targets the intersection of high token efficiency, high accuracy, low staleness risk, and manageable maintenance burden.

### Layer 0: Root Instructions (Always Loaded)

**File**: `CLAUDE.md` (also symlinked or generated as `AGENTS.md` for cross-tool compatibility)
**Budget**: Under 100 lines (~1,500 tokens)
**Loads**: Every session, every conversation

**Contains**:
- Build and test commands (the 5 commands an agent runs most often)
- 3-5 critical invariants that prevent catastrophic mistakes (e.g., state mutation rules)
- A "Navigation" section with explicit file paths to Layer 1 docs
- A decision tree: "What are you trying to do?" pointing to the right Layer 1 doc

**Does NOT contain**: Architecture details, module descriptions, workflow procedures, API references, historical context.

```markdown
# CLAUDE.md

## Build & Test
[5-10 lines of commands]

## Critical Rules
- **NEVER** do X -- see `docs/architecture.md#state-mutation` for details
- **ALWAYS** do Y before Z

## Navigation
- Architecture overview: `docs/ARCHITECTURE.md`
- Module map: `docs/MODULE_INDEX.md`
- Test infrastructure: `tests/README.md`
- Adding a plugin: `.claude/skills/plugin-template/SKILL.md`
```

### Layer 1: Architecture and Index (Loaded on Demand)

**Files**: `ARCHITECTURE.md`, `MODULE_INDEX.md`, per-directory `AGENTS.md`
**Budget**: 200-500 lines each (~3,000-7,500 tokens)
**Loads**: When the agent needs orientation or is working in a specific module

**ARCHITECTURE.md** contains:
- System design in 1 page (core flow diagram, key abstractions, data flow)
- Module table mapping concepts to file paths
- Cross-cutting concerns (state management, error handling, observability)
- Links to Layer 2 for each module

**MODULE_INDEX.md** contains:
- Every source file with a one-line description and line count
- Grouped by module/directory
- Token estimate per file (so the agent can budget reads)

**Per-directory AGENTS.md** contains:
- Module-specific conventions and patterns
- "If you are editing this module, you must know:" rules
- Links to relevant Layer 2 docs

### Layer 2: Skills and Procedures (Loaded on Invocation)

**Files**: `.claude/skills/*/SKILL.md`
**Budget**: Under 500 lines each
**Loads**: When the agent decides a specific workflow is needed

Each skill encapsulates a complete workflow:
- Gap audit procedure
- Test fixture creation
- Plugin development
- Release process
- Debugging a specific class of bug

The SKILL.md body contains step-by-step instructions with explicit file paths, commands, and validation steps. It references Layer 3 files for deep detail.

### Layer 3: Deep Reference (Loaded on Explicit Demand)

**Files**: `.claude/skills/*/references/`, `ai_docs/`, specification documents
**Budget**: Unbounded (loaded file-by-file as needed)
**Loads**: Only when Layer 2 instructions explicitly reference them

Contains:
- API references and specifications
- Full source code snapshots (repomix-style, for cross-repo reference)
- Research documents, design decisions, historical context
- Test fixture catalogs, example configurations

### Cross-Cutting: The Index File Pattern

The single highest-impact addition to any documentation structure is a machine-readable index that maps concepts to files:

```markdown
# MODULE_INDEX.md

## Source Modules

| Module | File | Lines | Tokens | Description |
|--------|------|------:|-------:|-------------|
| Orchestrator | `rlm_adk/orchestrator.py` | 180 | ~2,700 | Top-level agent delegation |
| Dispatch | `rlm_adk/dispatch.py` | 350 | ~5,250 | WorkerPool + llm_query closures |
| REPL Tool | `rlm_adk/tools/repl_tool.py` | 220 | ~3,300 | Code execution + AST detection |
| State | `rlm_adk/state.py` | 90 | ~1,350 | State key constants + depth_key() |

## Test Infrastructure

| Component | File | Lines | Description |
|-----------|------|------:|-------------|
| Fake server | `tests_rlm_adk/provider_fake/server.py` | 150 | FakeGeminiServer (aiohttp) |
| Contract runner | `tests_rlm_adk/provider_fake/contract_runner.py` | 200 | Runs fixtures, collects results |
| Fixtures | `tests_rlm_adk/fixtures/provider_fake/*.json` | -- | Canned model responses |
```

This index costs ~200 tokens to read and eliminates the need for exploratory grep in 80%+ of cases.

### Multi-Agent Scoping

For projects using sub-agents or agent teams, each agent role should have a context profile:

```markdown
## Agent Context Profiles

### Planner
Load: ARCHITECTURE.md, MODULE_INDEX.md
Skip: Test infrastructure, plugin details, build commands

### Implementer
Load: Root CLAUDE.md, relevant module's AGENTS.md, relevant source files
Skip: Architecture philosophy, test fixtures, deployment

### Reviewer
Load: Root CLAUDE.md (critical rules), relevant module's AGENTS.md
Skip: Build commands, architecture overview, test infrastructure

### Tester
Load: tests/README.md, relevant fixture catalog, module API being tested
Skip: Architecture, build commands, deployment
```

This can be formalized as a `.claude/context_profiles.json` that automated harnesses use to pre-select documents per role.

### Maintenance Strategy

1. **Automated staleness detection**: CI check that validates all file paths in index files actually exist. The codified-context-infrastructure repo demonstrates this with a validation script on session start.
2. **Line count / token count refresh**: A pre-commit hook or CI job that updates MODULE_INDEX.md with current line counts (trivially scriptable with `wc -l`).
3. **Skill body size monitoring**: Alert when a SKILL.md exceeds 500 lines -- signal to split into sub-skills or move content to references.
4. **Single source of truth**: If using multiple tools (Claude Code + Cursor + Copilot), generate tool-specific files from AGENTS.md rather than maintaining parallel copies.

### Summary: What to Build First

For immediate impact on an existing codebase, prioritize in this order:

1. **Trim root CLAUDE.md to <100 lines** with a navigation section pointing to deeper docs
2. **Create MODULE_INDEX.md** mapping every source file with line counts and one-line descriptions
3. **Add per-directory AGENTS.md** for the 2-3 most complex modules
4. **Convert complex workflows to Skills** (.claude/skills/*/SKILL.md with references/)
5. **Add a CI validation step** that checks all documented file paths still exist

These five steps cover 90% of the value with manageable maintenance burden. Vector/embedding approaches should be deferred until agentic search demonstrably fails for the codebase's scale.

---

## Sources

- [Anthropic: Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic: Equipping Agents for the Real World with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Anthropic: Skill Authoring Best Practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- [Claude Code Skills Documentation](https://code.claude.com/docs/en/skills)
- [Codified Context: Infrastructure for AI Agents in a Complex Codebase (arXiv:2602.20478)](https://arxiv.org/abs/2602.20478)
- [codified-context-infrastructure (GitHub)](https://github.com/arisvas4/codified-context-infrastructure)
- [Will Larson: Building an Internal Agent -- Progressive Disclosure and Handling Large Files](https://lethain.com/agents-large-files/)
- [Will Larson: Building an Internal Agent -- Context Window Compaction](https://lethain.com/agents-context-compaction/)
- [Aider: Repository Map](https://aider.chat/docs/repomap.html)
- [Aider: Building a Better Repository Map with Tree-Sitter](https://aider.chat/2023/10/22/repomap.html)
- [Cursor: Rules](https://docs.cursor.com/context/rules)
- [Repomix](https://repomix.com/)
- [AGENTS.md Specification](https://agents.md/)
- [Kaushik Gopal: Keep Your AGENTS.md in Sync](https://kau.sh/blog/agents-md/)
- [SmartScope: Settling the RAG Debate -- Why Claude Code Dropped Vector DB-Based RAG](https://smartscope.blog/en/ai-development/practices/rag-debate-agentic-search-code-exploration/)
- [SmartScope: AGENTS.md Cross-Tool Unified Management Guide](https://smartscope.blog/en/generative-ai/github-copilot/github-copilot-agents-md-guide/)
- [alexop.dev: Stop Bloating Your CLAUDE.md -- Progressive Disclosure for AI Coding Tools](https://alexop.dev/posts/stop-bloating-your-claude-md-progressive-disclosure-ai-coding-tools/)
- [Lee Han Chung: Claude Agent Skills -- A First Principles Deep Dive](https://leehanchung.github.io/blogs/2025/10/26/claude-skills-deep-dive/)
- [Matthew Groff: Implementing CLAUDE.md and Agent Skills in Your Repository](https://www.groff.dev/blog/implementing-claude-md-agent-skills)
- [HumanLayer: Writing a Good CLAUDE.md](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Progressive Disclosure in AI Agent Skill Design (Towards AI)](https://pub.towardsai.net/progressive-disclosure-in-ai-agent-skill-design-b49309b4bc07)
- [Inferable: Progressive Context Enrichment for LLMs](https://www.inferable.ai/blog/posts/llm-progressive-context-encrichment)
- [jCodeMunch MCP Server (GitHub)](https://github.com/jgravelle/jcodemunch-mcp)
- [NVIDIA NeMo Agent Toolkit: Cursor Rules Developer Guide](https://docs.nvidia.com/nemo/agent-toolkit/1.2/extend/cursor-rules-developer-guide.html)
- [AgentMesh: A Cooperative Multi-Agent Framework (arXiv)](https://arxiv.org/html/2507.19902v1)
- [Augment Code: Spec-Driven AI Code Generation with Multi-Agent Systems](https://www.augmentcode.com/guides/spec-driven-ai-code-generation-with-multi-agent-systems)
- [VS Code Agents: Multi-Agent Workflow System (GitHub)](https://github.com/groupzer0/vs-code-agents)
- [Milvus Blog: Why I'm Against Claude Code's Grep-Only Retrieval](https://milvus.io/blog/why-im-against-claude-codes-grep-only-retrieval-it-just-burns-too-many-tokens.md)
- [Alberto Roura: Vector RAG? Agentic Search? Why Not Both?](https://albertoroura.com/vector-rag-agentic-search-why-not-both/)
- [DataLakehouse Hub: Context Management Strategies for Cursor (2026)](https://datalakehousehub.com/blog/2026-03-context-management-cursor/)
