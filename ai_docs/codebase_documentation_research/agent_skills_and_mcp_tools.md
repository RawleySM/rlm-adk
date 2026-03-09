# Agent Skills, MCP Servers, and Tools for Codebase Understanding

Research compiled 2026-03-09. Focus: tools and patterns for AI agents to navigate,
understand, and build memory over codebases — with feasibility notes for Google ADK integration.

---

## 1. MCP Servers for Code Understanding

### 1.1 Code Pathfinder (codepathfinder.dev)

AST-based code intelligence MCP server. Parses Python into ASTs, builds Control Flow
Graphs (CFG) and Data Flow Graphs (DFG), constructs call graphs via 5-pass analysis.
Exposes natural-language queries over symbol definitions, dependencies, and dataflow.

- **Language**: Python (others planned)
- **License**: AGPL-3.0, 100% local
- **Tools exposed**: call graph generation, symbol lookup, dependency tracing, dataflow analysis
- **ADK feasibility**: HIGH. Stdio-based MCP server, directly usable via `McpToolset(StdioConnectionParams(...))`. Python-only scope is fine for RLM-ADK. AST/dataflow analysis could feed into REPL code planning.

Source: [Code Pathfinder MCP](https://codepathfinder.dev/mcp)

### 1.2 claude-context (Zilliz)

Semantic code search MCP for Claude Code. Indexes codebase into vector embeddings,
performs hybrid BM25 + dense vector search. Uses Merkle trees for incremental re-indexing
of changed files only.

- **Embedding providers**: OpenAI, VoyageAI, Ollama, Gemini
- **Vector DB**: Milvus or Zilliz Cloud
- **Languages**: 14+ via AST-based code splitters (tree-sitter)
- **Performance**: 40%+ token reduction vs grep-only retrieval in testing
- **ADK feasibility**: HIGH. Standard MCP stdio transport. Could replace brute-force grep for context retrieval in agent planning phases. Gemini embeddings option means no extra API key needed.

Source: [zilliztech/claude-context](https://github.com/zilliztech/claude-context)

### 1.3 code-memory (kapillamba4)

Fully local MCP server with vector search, Git history, and semantic code search.

- **Parser**: tree-sitter (language-agnostic structural extraction)
- **Embeddings**: sentence-transformers (local, no API keys)
- **Search**: Hybrid BM25 + dense vector
- **Storage**: SQLite with sqlite-vec extension
- **Git integration**: git_search.py module for commit history search
- **ADK feasibility**: HIGH. Pure Python, SQLite storage, no external services. Could run as subprocess via StdioConnectionParams. The Git history search is particularly relevant for understanding code evolution.

Source: [kapillamba4/code-memory](https://github.com/kapillamba4/code-memory)

### 1.4 Code-Index-MCP (ViperJuice)

Indexes codebases by parsing source files into structural metadata (functions, classes,
imports, dependency graphs, cross-file call chains). Exposes 18 query tools via MCP.

- **Languages**: 48 via tree-sitter
- **Features**: Real-time file monitoring, structural metadata, cross-file call chains
- **ADK feasibility**: MEDIUM-HIGH. Large tool surface (18 tools) may overwhelm LLM tool selection. Could use McpToolset's tool_filter parameter to expose a subset.

Source: [Code-Index-MCP](https://mcpservers.org/servers/ViperJuice/Code-Index-MCP)

### 1.5 mcp-vector-search (bobmatnyc)

CLI-first semantic code search with MCP integration. ChromaDB backend with AST parsing.

- **Storage**: ChromaDB (local)
- **ADK feasibility**: MEDIUM. ChromaDB is heavier than SQLite-based alternatives but well-documented.

Source: [bobmatnyc/mcp-vector-search](https://github.com/bobmatnyc/mcp-vector-search)

### 1.6 AST-MCP-Server (angrysky56)

Transforms source code into a queryable Semantic Graph and structured AST. Bridges
"reading text" and "understanding structure" by providing spatial awareness for navigating
deep dependencies.

- **ADK feasibility**: MEDIUM. More experimental, but the semantic graph concept aligns well with RLM-ADK's recursive architecture.

Source: [angrysky56/ast-mcp-server](https://github.com/angrysky56/ast-mcp-server)

### 1.7 Qdrant MCP Server (official)

Official Qdrant Model Context Protocol server. General-purpose vector memory for AI agents.

- **ADK feasibility**: MEDIUM. Production-grade vector DB but requires running Qdrant server. Overkill for single-repo use cases unless scaling to multi-repo.

Source: [qdrant/mcp-server-qdrant](https://github.com/qdrant/mcp-server-qdrant)

---

## 2. Claude Code Skills for Codebase Understanding

### 2.1 How Skills Work

Skills are Claude Code's reusable prompt/workflow system, triggered via `/command` syntax.
Each skill is a directory containing a `SKILL.md` file with:

- **YAML frontmatter**: `description` (for auto-invocation matching), `disable-model-invocation` flag
- **Markdown body**: Instructions Claude follows when the skill is invoked

Skills can bundle scripts in any language, generate visual output (interactive HTML),
and be auto-invoked when Claude detects a matching user query based on the description field.

As of Claude Code v2.1.3, slash commands have been merged into the skills system.

Source: [Claude Code Skills Docs](https://code.claude.com/docs/en/skills)

### 2.2 Codebase Understanding Skill Patterns

Notable patterns from the community:

| Pattern | Description | Source |
|---------|-------------|--------|
| **codebase-visualizer** | Generates interactive tree view with expand/collapse, file sizes, color-coded types | Community skills |
| **audit-context-building** (Trail of Bits) | Deep architectural context via ultra-granular code analysis | [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) |
| **Architecture explainer** | Skills with description "Explains codebase architecture and logic flows" auto-invoke on architecture questions | Skills marketplace |

### 2.3 What Makes a Good Codebase Understanding Skill

Based on community patterns and the skills marketplace (63,000+ skills):

1. **Structured output**: Generate artifacts (HTML, JSON, diagrams) not just text
2. **Scoped queries**: Accept parameters (module name, depth level) rather than analyzing "everything"
3. **Script bundling**: Run tree-sitter, AST analysis, or git log commands as part of the skill
4. **Composability**: Skills that produce structured data other skills can consume
5. **Auto-invocation descriptions**: Precise description fields so Claude invokes them at the right time

### 2.4 Designing an `rlm_codebase` Skill

For RLM-ADK, a codebase understanding skill could:

- Parse the module dependency graph (orchestrator -> dispatch -> repl_tool -> local_repl)
- Map state key flows through depth-scoped keys
- Trace the llm_query dispatch path from AST rewrite to WorkerPool
- Generate a per-module summary with entry points, state mutations, and tool registrations
- Output structured JSON that could feed into REPL code planning

The skill would live at `.claude/skills/rlm_codebase/SKILL.md` with a description like
"Analyzes RLM-ADK module architecture, state flow, and dispatch paths."

---

## 3. Embeddings-Based Code Search

### 3.1 Embedding Models for Code

| Model | Provider | Context | Dimensions | Notes |
|-------|----------|---------|------------|-------|
| voyage-code-3 | Voyage AI | 16K tokens | 1024 | Best-in-class for code retrieval |
| voyage-4-large | Voyage AI | 32K tokens | 1024 (default), 256-2048 | General-purpose, multilingual |
| text-embedding-3-large | OpenAI | 8K tokens | 3072 | Good general purpose |
| text-embedding-ada-002 | OpenAI | 8K tokens | 1536 | Legacy, used by Cody |
| nomic-embed-text | Ollama (local) | 8K tokens | 768 | Recommended for local/offline |
| st-multi-qa-mpnet-base-dot-v1 | Sourcegraph | — | 768 | Cody's custom model |
| Gemini text-embedding-004 | Google | 2K tokens | 768 | Free tier available |

**ADK recommendation**: Gemini embeddings (no extra API key) for quick start, voyage-code-3
for production quality. For fully local: nomic-embed-text via Ollama or sentence-transformers.

### 3.2 Vector Stores Comparison

| Store | Type | Strengths | Weaknesses | ADK Fit |
|-------|------|-----------|------------|---------|
| **ChromaDB** | Embedded DB | Easy setup, LangChain integration, good for prototyping | Limited scale, Python-only | HIGH for prototyping |
| **SQLite + sqlite-vec** | Extension | Zero dependencies, single file, used by code-memory | Newer, less ecosystem | HIGH for embedded use |
| **FAISS** | Library | GPU acceleration, batch processing, Meta-backed | Not a full DB, no metadata filtering | MEDIUM (need wrapper) |
| **Qdrant** | Server | Production-grade, filtering, clustering | Requires running server | MEDIUM for single-repo |
| **Milvus/Zilliz** | Server | Enterprise scale, hybrid search built-in | Heavy infrastructure | LOW for local dev |
| **LanceDB** | Embedded DB | Rust-based, fast, columnar, used by Continue.dev | Newer ecosystem | HIGH for performance |
| **Turbopuffer** | Cloud | Used by Cursor, fast similarity search | Cloud-only, proprietary | LOW (vendor lock-in) |

**ADK recommendation**: ChromaDB for quick prototyping, LanceDB for production embedded use.
SQLite + sqlite-vec is compelling for zero-dependency deployment alongside the existing
SqliteTracingPlugin.

### 3.3 How Cursor Indexes Codebases (Reference Architecture)

Cursor's approach is instructive as a production-grade reference:

1. **AST-based chunking**: tree-sitter parses code into AST, depth-first traversal splits into sub-trees that fit token limits, sibling nodes merged to avoid tiny chunks
2. **Embedding**: Custom embedding model converts chunks to vectors
3. **Merkle tree change detection**: Hash tree of all files, sync only changed files
4. **Cache by chunk hash**: Same chunk content = same embedding, skip re-computation
5. **Privacy**: Only embeddings + obfuscated file paths stored remotely; source stays local
6. **Metadata**: Start/end line numbers, file paths stored alongside vectors

### 3.4 Sourcegraph Cody Architecture (Reference)

Multi-layered RAG approach:

1. **Local file context**: Immediate editor context
2. **Local repo context**: Embeddings over current codebase
3. **Remote repo context**: Code search across organization repos
4. **External context**: OpenCtx (Jira, Linear, Notion), MCP servers

Embedding models: OpenAI text-embedding-ada-002 or custom st-multi-qa-mpnet-base-dot-v1.
Context windows up to 1M tokens. Positioned as "Visionary" in 2025 Gartner Magic Quadrant.

Source: [Sourcegraph Cody](https://sourcegraph.com/cody)

### 3.5 Continue.dev Architecture (Reference)

Open-source AI coding assistant with pluggable embedding and reranking:

- **Embeddings**: Configurable (OpenAI, VoyageAI, Gemini, Ollama/nomic-embed-text for local)
- **Reranking**: Separate model determines relevance between query and code
- **Context providers**: File exploration, code search, Git integration
- **Fully local option**: Ollama + sentence-transformers, no external API calls

Source: [Continue.dev docs](https://docs.continue.dev/customize/model-roles/embeddings)

---

## 4. Self-Improving Documentation

### 4.1 The CLAUDE.md / AGENTS.md Feedback Loop

The dominant pattern in 2025-2026 for agent self-improvement:

- **CLAUDE.md**: Project-scoped instructions checked into repo. Sets coding standards,
  architecture decisions, preferred libraries, review checklists.
- **AGENTS.md**: Long-term semantic memory — accumulated wisdom of past runs.
  Creates a compound learning loop where every fix or pattern gets rolled into context
  for the next iteration.
- **MEMORY.md**: User-scoped persistent memory across conversations.

This is not "online learning" in the ML sense, but systematic outcome recording so that
the next iteration benefits from past learnings. Over dozens of iterations, agent
effectiveness increases as it stops repeating mistakes.

Source: [Addy Osmani - Self-Improving Coding Agents](https://addyosmani.com/blog/self-improving-agents/)

### 4.2 Documentation Quality Signals

Patterns for detecting when documentation needs updating:

1. **Lint/test failures after agent changes**: If CLAUDE.md says "use pattern X" but
   the agent keeps failing with pattern X, the documentation is wrong
2. **Repeated tool calls**: If the agent greps for the same information across sessions,
   it should be in CLAUDE.md
3. **State drift detection**: Sweep AI's approach — normalize LLM outputs and detect
   when the model's internal state diverges from documentation
4. **Review issue frequency**: If the same review comment appears 3+ times, add it
   to agent instructions

### 4.3 Auto-Correction Patterns

| Pattern | How It Works | Example |
|---------|--------------|---------|
| **Post-run documentation update** | Agent updates CLAUDE.md with lessons learned after task completion | "Added workaround for ADK Pydantic gotcha" |
| **Error-driven enrichment** | When agent hits an error, it documents the fix in AGENTS.md | Bug-13 monkey-patch documentation |
| **Convention extraction** | Agent analyzes successful PRs and extracts naming/structure patterns | "Functions in dispatch.py use _acc_ prefix for accumulators" |
| **Staleness detection** | Compare documentation claims against actual code; flag contradictions | LSP-based approach (see lsp_and_staleness_prevention.md) |

### 4.4 Sweep AI's Self-Correction Approach

Sweep's output normalization reduced code editing error rate from 13% to 8%:

- After each LLM output, normalize formatting before passing back as context
- When the LLM edits code later, it references the clean version
- Prevents state drift where accumulated formatting errors compound

This pattern is applicable to RLM-ADK's REPL execution: normalize code output before
storing in trace history to prevent drift in recursive llm_query chains.

---

## 5. Notable Implementations Summary

| Tool | Approach | Local? | ADK Integration | Best For |
|------|----------|--------|-----------------|----------|
| Code Pathfinder | AST + CFG + DFG | Yes | McpToolset (stdio) | Deep Python analysis |
| claude-context (Zilliz) | Hybrid vector search | Yes* | McpToolset (stdio) | Semantic code search |
| code-memory | tree-sitter + sentence-transformers | Yes | McpToolset (stdio) | Fully offline search + Git |
| Sourcegraph Cody | Multi-layer RAG | No | API integration | Enterprise multi-repo |
| Continue.dev | Pluggable embeddings + reranking | Yes | Reference architecture | Local-first assistant |
| Cursor indexing | AST chunking + Merkle tree | Partial | Reference architecture | High-performance indexing |
| Sweep AI | Output normalization + self-correction | No | Pattern adoption | Error reduction |

*Requires embedding API unless using Ollama

---

## 6. Vector Store for REPL Code History

This section addresses the specific goal of building embeddings over previously executed
REPL code with IO types and task metadata.

### 6.1 What to Embed

Each REPL execution in RLM-ADK produces rich structured data that can be embedded:

| Field | Source | Embedding Value |
|-------|--------|-----------------|
| **Code text** | REPLTool execute_code input | Primary semantic content |
| **Task prompt** | The llm_query prompt that triggered the code | Intent/goal context |
| **Output text** | REPL stdout/stderr | Execution result semantics |
| **IO type signature** | Input types -> output types of the code block | Structural matching |
| **Error class** | If failed: error type + message | Failure pattern retrieval |
| **Depth level** | depth_key scoping | Recursion context |
| **Iteration number** | Which iteration of the reasoning loop | Temporal context |
| **Parent task** | The top-level user query | Goal hierarchy |
| **llm_query calls** | Number and prompts of child dispatches | Composition patterns |
| **Duration** | Execution time | Performance baseline |

### 6.2 Chunking Strategy

REPL code blocks are natural chunks — each `execute_code` call is a self-contained unit.
However, enrichment is needed:

```
Chunk = {
    "code": "<the Python code>",
    "task_context": "<the prompt/goal that led to this code>",
    "io_signature": "List[str] -> Dict[str, int]",
    "outcome": "success|error|partial",
    "error_type": "TypeError|None",
    "depth": 0,
    "iteration": 3,
    "session_id": "abc-123",
    "timestamp": "2026-03-09T14:30:00Z",
    "llm_query_count": 2,
    "tags": ["data_processing", "aggregation"]
}
```

The embedding should be generated from a concatenation of `task_context + code + io_signature`
to capture both intent and implementation.

### 6.3 Retrieval Scenarios

| Query Type | Example | Retrieval Strategy |
|------------|---------|-------------------|
| "How did we parse JSON last time?" | Semantic search on code text | Dense vector similarity |
| "Code that takes List[dict] and returns DataFrame" | IO signature matching | Metadata filter + vector |
| "Failed attempts at API calls" | Error pattern retrieval | Filter outcome=error + semantic |
| "What code ran at depth 2?" | Structural query | Metadata filter on depth |
| "Similar tasks to 'analyze CSV file'" | Goal similarity | Embed task_context, compare |
| "Most reused code patterns" | Frequency analysis | Cluster embeddings, rank by count |

### 6.4 Recommended Architecture for RLM-ADK

```
REPLTool.run_async()
    |
    v
REPLTracingPlugin (existing) ──> repl_traces.json
    |
    v
CodeHistoryIndexer (new)
    |
    ├── Chunking: extract code + metadata from trace
    ├── Embedding: voyage-code-3 or Gemini text-embedding-004
    ├── Storage: ChromaDB (prototype) or LanceDB (production)
    └── Metadata: io_signature, depth, outcome, session_id, tags
         |
         v
CodeHistoryMCP (new MCP server)
    |
    ├── search_similar_code(query, filters)
    ├── search_by_io_type(input_type, output_type)
    ├── get_code_for_task(task_description)
    ├── get_failure_patterns(error_type)
    └── get_reuse_candidates(code_snippet)
         |
         v
McpToolset(StdioConnectionParams(...))
    |
    v
RLMOrchestratorAgent reasoning_agent tools
```

### 6.5 Integration with Existing Infrastructure

The RLM-ADK project already has the data pipeline:

1. **REPLTracingPlugin** (`rlm_adk/plugins/repl_tracing.py`) — saves `repl_traces.json`
   with per-code-block trace data including timing and variable snapshots
2. **REPLTrace dataclass** (`rlm_adk/repl/trace.py`) — accumulates trace data with
   DataFlowTracker for detecting when one llm_query response feeds into the next prompt
3. **SqliteTracingPlugin** (`rlm_adk/plugins/sqlite_tracing.py`) — persists traces to
   `.adk/traces.db`
4. **LLMResult subclass** — carries error/metadata alongside string result

The new CodeHistoryIndexer would consume the same trace data and:

- Run after each session (batch) or after each REPL execution (streaming)
- Extract code + metadata into embedding-ready chunks
- Store in a local vector DB alongside the existing SQLite traces
- Expose via MCP server for the reasoning agent to query

### 6.6 Implementation Phases

**Phase 1: Prototype (ChromaDB + Gemini embeddings)**
- New module: `rlm_adk/plugins/code_history.py`
- Consumes `repl_traces.json` post-session
- ChromaDB collection with code text + metadata
- Simple MCP server with `search_similar_code` tool
- Wire into agent via McpToolset

**Phase 2: Rich Metadata (IO type extraction)**
- AST analysis of REPL code to extract input/output type signatures
- Tag extraction from task prompts (NLP or LLM-based)
- Error classification alignment with existing `_classify_error` in callbacks
- Metadata-filtered search (by depth, outcome, io_type)

**Phase 3: Production (LanceDB + streaming indexing)**
- Replace ChromaDB with LanceDB for better performance
- Stream-index during REPL execution (not just post-session)
- Deduplication via code hash (similar to Cursor's chunk hash caching)
- Merkle tree change detection for re-indexing

**Phase 4: Self-improving retrieval**
- Track which retrieved code snippets were actually used by the agent
- Feedback signal: if agent uses retrieved code, boost its relevance score
- If agent ignores retrieved code, reduce relevance or flag for review
- Periodic re-embedding with updated model versions

### 6.7 Embedding Model Selection for Code History

For the REPL code history use case specifically:

- **voyage-code-3**: Best retrieval quality for code, but requires API key and costs per token
- **Gemini text-embedding-004**: Free tier (1,500 req/min), already have API access via ADK,
  768-dim embeddings. Good enough for prototype.
- **nomic-embed-text (Ollama)**: Fully local, no API costs, 768-dim. Best for privacy-sensitive
  deployments.
- **sentence-transformers (all-MiniLM-L6-v2)**: Used by code-memory project, fast and local,
  384-dim. Smallest footprint.

Recommendation: Start with Gemini text-embedding-004 (zero additional setup), graduate to
voyage-code-3 if retrieval quality is insufficient.

### 6.8 Schema Design for Vector Store

```python
# ChromaDB collection schema
collection = chroma_client.create_collection(
    name="repl_code_history",
    metadata={"hnsw:space": "cosine"}
)

# Document structure
collection.add(
    documents=["<task_context>\n\n<code>\n\n# IO: <io_signature>"],
    metadatas=[{
        "session_id": "abc-123",
        "depth": 0,
        "iteration": 3,
        "outcome": "success",
        "error_type": None,
        "io_input_types": "List[str]",
        "io_output_types": "Dict[str, int]",
        "llm_query_count": 2,
        "duration_ms": 450,
        "timestamp": "2026-03-09T14:30:00Z",
        "code_hash": "sha256:abcdef...",
        "tags": "data_processing,aggregation",
    }],
    ids=["exec_abc123_d0_i3"]
)
```

---

## 7. ADK Integration Patterns

### 7.1 McpToolset Connection

Google ADK provides `McpToolset` for connecting to any MCP server:

```python
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_toolset import StdioConnectionParams, StdioServerParameters

# In agent tools list
tools = [
    repl_tool,
    McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="python",
                args=["-m", "rlm_adk.mcp.code_history_server"],
            )
        ),
        tool_filter=["search_similar_code", "search_by_io_type"],
    ),
]
```

### 7.2 Tool Filtering

With 18+ tools from some MCP servers, filtering is essential to avoid overwhelming the LLM:

- `tool_filter` parameter on McpToolset accepts a list of tool names to expose
- Alternatively, create a wrapper BaseTool that aggregates multiple MCP queries

### 7.3 Considerations for RLM-ADK

1. **MCP server lifecycle**: McpToolset spawns the server as a subprocess. For
   code history, the server needs access to the ChromaDB/LanceDB storage.
2. **Async compatibility**: MCP tools are async-native, compatible with ADK's async runner.
3. **State isolation**: MCP tools return results as function call responses — they don't
   directly mutate ADK session state. Results flow through the normal tool_context path.
4. **Cost**: Each MCP tool call is a function call turn in the LLM conversation.
   Batch queries (search + filter in one call) are preferable to multiple round-trips.

---

## 8. Recommendations for RLM-ADK

### Immediate (Low Effort, High Value)

1. **Install code-memory MCP server** — fully local, SQLite-based, zero API keys.
   Provides semantic code search + Git history search out of the box.
   Wire via McpToolset with tool_filter for the 2-3 most useful tools.

2. **Create `/codebase` skill** — SKILL.md that runs tree-sitter AST analysis on
   the rlm_adk/ directory and produces a structured module dependency map.
   Auto-invokes on architecture questions.

### Medium Term (Moderate Effort)

3. **Build CodeHistoryIndexer plugin** — consume existing REPLTracingPlugin output,
   embed with Gemini, store in ChromaDB. Expose as MCP server with
   `search_similar_code` and `search_by_io_type` tools.

4. **Add self-improving CLAUDE.md updates** — after each session, compare agent's
   discovered patterns against CLAUDE.md content. Suggest additions for repeated
   patterns (gated behind human approval).

### Long Term (Significant Effort)

5. **Production code history with LanceDB** — streaming indexing during REPL execution,
   IO type extraction via AST, feedback loop on retrieval quality.

6. **Code Pathfinder integration** — deep Python dataflow analysis for security review
   and architecture exploration. Particularly valuable for tracing state mutation paths
   through the dispatch/callback/tool_context chain.

---

## Sources

- [Code Pathfinder MCP](https://codepathfinder.dev/mcp)
- [zilliztech/claude-context](https://github.com/zilliztech/claude-context)
- [kapillamba4/code-memory](https://github.com/kapillamba4/code-memory)
- [Code-Index-MCP](https://mcpservers.org/servers/ViperJuice/Code-Index-MCP)
- [angrysky56/ast-mcp-server](https://github.com/angrysky56/ast-mcp-server)
- [qdrant/mcp-server-qdrant](https://github.com/qdrant/mcp-server-qdrant)
- [Claude Code Skills Docs](https://code.claude.com/docs/en/skills)
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)
- [Voyage AI Embeddings](https://docs.voyageai.com/docs/embeddings)
- [Sourcegraph Cody](https://sourcegraph.com/cody)
- [Continue.dev Embeddings Docs](https://docs.continue.dev/customize/model-roles/embeddings)
- [How Cursor Indexes Your Codebase](https://towardsdatascience.com/how-cursor-actually-indexes-your-codebase/)
- [Addy Osmani - Self-Improving Coding Agents](https://addyosmani.com/blog/self-improving-agents/)
- [Google ADK MCP Tools](https://google.github.io/adk-docs/tools-custom/mcp-tools/)
- [Sweep AI Docs](https://docs.sweep.dev/agent)
- [LanceDB - Building RAG on Codebases](https://lancedb.com/blog/building-rag-on-codebases-part-1/)
- [Milvus Blog - Why Grep-Only Retrieval Burns Tokens](https://milvus.io/blog/why-im-against-claude-codes-grep-only-retrieval-it-just-burns-too-many-tokens.md)
- [bobmatnyc/mcp-vector-search](https://github.com/bobmatnyc/mcp-vector-search)
- [Agent Skills Marketplace](https://agent-skills.cc/)
- [Continue.dev Codebase Awareness Guide](https://docs.continue.dev/guides/codebase-documentation-awareness)
