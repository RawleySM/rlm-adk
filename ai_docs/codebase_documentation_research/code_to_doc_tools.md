# Codebase-to-Documentation Tools for AI Agent Consumption

> Research compiled March 2026. Covers tools and methods for converting codebases into formats that AI agents (LLMs) can effectively consume.

## Summary Table

| Tool / Method | Approach | Output Format | Progressive Disclosure | Staleness Risk | Best For |
|---|---|---|---|---|---|
| **Repomix** | Pack entire repo into single file | XML, Markdown, JSON, Plain text | Partial (compress mode via tree-sitter) | High — static snapshot | One-shot full-context prompts |
| **Aider repo-map** | Tree-sitter AST + PageRank graph ranking | Condensed signature map (text) | Yes — dynamic token-budget sizing | Low — regenerated per turn | Ongoing coding sessions with large repos |
| **Cursor indexing** | Embeddings + Merkle tree + vector DB | Semantic vector index (internal) | Yes — retrieves only relevant chunks | Low — incremental 10-min sync | IDE-integrated semantic code search |
| **Claude Code** | Agentic search (Glob/Grep/Read) + CLAUDE.md | On-demand file reads + memory markdown | Yes — multi-layer (memory hierarchy + sub-agents) | None — always live | Agent-driven exploration and editing |
| **code2prompt** | Concat files with Handlebars templates | Single prompt text (stdout/clipboard) | No | High — static snapshot | Quick prompt generation with custom templates |
| **Gitingest** | Repo-to-text dump (web or CLI) | Plain text digest | No | High — static snapshot | Fast repo ingestion via URL swap |
| **Sourcegraph Cody** | RAG: code search + vector embeddings | Internal retrieval context | Yes — multi-layer (local + remote) | Low — indexed continuously | Enterprise-scale multi-repo search |
| **llms.txt** | Standardized markdown file at /llms.txt | Markdown (spec format) | Yes — llms.txt (summary) vs llms-full.txt (complete) | Medium — requires manual updates | Library/API documentation for LLM consumption |

---

## 1. Repomix

**What it does:** Packs an entire repository into a single AI-friendly file. Respects `.gitignore`, runs Secretlint for sensitive data detection, and provides token counts per file and total.

**How it works:**
1. Traverses the repo, respecting `.gitignore` and `.git/info/exclude`
2. Builds a directory tree structure
3. Concatenates file contents with metadata headers
4. Optionally compresses using tree-sitter to extract only signatures/structure (~70% token reduction)
5. Outputs token counts using configurable tokenizer (o200k_base default for GPT-4o, cl100k_base for GPT-3.5/4)

**Output format (XML default):**
```xml
<file_summary>(Metadata and AI instructions)</file_summary>
<directory_structure>
  src/index.ts
  utils/helper.ts
</directory_structure>
<files>
  <file path="src/index.ts">// File contents</file>
</files>
<git_logs>(Commit history)</git_logs>
```
Also supports Markdown (heading hierarchy + fenced code blocks), JSON, and plain text (divider-separated sections).

**Strengths:**
- Dead simple — one command, one file output
- Multiple output formats including XML (which Claude handles well)
- Security scanning via Secretlint catches leaked secrets
- `--compress` mode with tree-sitter extracts signatures only, cutting tokens ~70%
- MCP server integration available for real-time agent use
- Token counting built in with multiple tokenizer support
- Git log inclusion provides change context

**Limitations:**
- Static snapshot — stale the moment code changes
- Full repo dump can exceed context windows for large projects (even with compression)
- No semantic ranking — every file gets equal treatment unless manually filtered
- Compression is all-or-nothing (compressed vs full), no fine-grained levels

**Progressive disclosure:** Partial. The `--compress` flag provides a two-level system: full file contents vs. signatures-only. No intermediate levels. Glob-based include/exclude patterns allow manual scoping.

**References:**
- [Repomix documentation](https://repomix.com/guide/)
- [Repomix GitHub](https://github.com/yamadashy/repomix)
- [Code Compression docs](https://repomix.com/guide/code-compress)

---

## 2. Aider's repo-map

**What it does:** Builds a concise map of an entire repository showing class/function/method signatures, ranked by importance using graph analysis. Designed to give LLMs structural awareness without consuming full-file token budgets.

**How it works:**
1. **Tree-sitter parsing:** Parses every source file into an AST using `py-tree-sitter-languages`, extracting definitions (functions, classes, methods, types) and their references
2. **Dependency graph:** Builds a graph where nodes are source files and edges represent cross-file references (imports, function calls, type usage)
3. **PageRank ranking:** Runs a PageRank-style algorithm on the dependency graph to identify the most-referenced (most important) symbols
4. **Token-budget fitting:** Selects the top-ranked symbols that fit within the configured token budget (`--map-tokens`, default 1024 tokens)
5. **Dynamic adjustment:** Expands the map when no files are in chat context; shrinks it as specific files are added

**Output format:**
```
aider/coders/base_coder.py:
|class Coder:
|    abs_fnames = None
|    @classmethod
|    def create(self, main_model, edit_format, io, ...)
|    def run(self, with_message=None):

aider/commands.py:
|class Commands:
|    def get_commands(self):
|    def run(self, inp):
```

**Strengths:**
- Semantic ranking — shows the symbols that matter most, not just everything
- Token-efficient — fits entire repo structure into ~1K tokens by default
- Dynamic — regenerated per turn based on chat context, so never stale during a session
- Language-agnostic via tree-sitter (supports most popular languages)
- Enables the LLM to self-identify which files to request in full

**Limitations:**
- Signatures only — no implementation details, no docstrings (by design)
- PageRank can produce odd rankings for repos with unusual dependency structures
- Requires tree-sitter grammar support for the target language
- Not useful as a standalone artifact — designed for aider's interactive loop
- ZeroDivisionError edge case when isolated files have no references (GitHub issue #1536)

**Progressive disclosure:** Yes, inherently. The map is a summary layer; the LLM requests full files on demand. The token budget dynamically adjusts based on what's already in context. This is a two-tier system: map (signatures) then full file content.

**References:**
- [Building a better repository map with tree-sitter](https://aider.chat/2023/10/22/repomap.html)
- [Repository map docs](https://aider.chat/docs/repomap.html)

---

## 3. Cursor's Codebase Indexing

**What it does:** Creates a semantic vector index of an entire codebase for retrieval-augmented code navigation. Queries return the most semantically relevant code chunks at inference time.

**How it works (5-step pipeline):**
1. **Local chunking:** Splits code into semantically meaningful pieces locally (AST-based using tree-sitter, not arbitrary line/character boundaries)
2. **Merkle tree construction:** Computes a Merkle tree of file hashes; syncs tree structure to server to establish baseline
3. **Embedding generation:** Creates vector embeddings from chunks using OpenAI's embedding API or a custom model
4. **Vector storage:** Stores embeddings in Turbopuffer (vector database) with obfuscated file paths. Original source code is NOT stored — only numerical embeddings and metadata
5. **Incremental sync:** Every 10 minutes, checks for Merkle tree hash mismatches; only re-processes changed files

**Retrieval at inference:**
- User query is embedded using the same model
- Nearest-neighbor search in Turbopuffer returns ranked code chunks
- File paths and line ranges are used to retrieve original code locally
- Retrieved chunks are injected as context alongside the query to the LLM

**Output format:** Internal — not a user-facing artifact. The "output" is a set of retrieved code chunks ranked by semantic similarity, injected into LLM context automatically.

**Strengths:**
- Semantic search — finds code by meaning, not just text matching
- Incremental updates via Merkle tree — efficient for large, actively developed repos
- AST-aware chunking preserves function/class boundaries
- Privacy-conscious — source code not persisted on servers, only embeddings
- Scales to very large codebases

**Limitations:**
- Proprietary — tightly coupled to Cursor IDE, not extractable
- Requires server round-trip for embedding generation
- Embedding quality depends on the model; may miss domain-specific semantics
- `.cursorignore` must be manually maintained
- No user visibility into what's indexed or how chunks are formed
- 10-minute sync interval means brief staleness windows

**Progressive disclosure:** Yes. The system retrieves only the most relevant chunks for a given query, not the entire codebase. Different queries surface different code. However, the user has no control over the granularity — it's fully automatic.

**References:**
- [How Cursor Indexes Codebases Fast (Engineer's Codex)](https://read.engineerscodex.com/p/how-cursor-indexes-codebases-fast)
- [How Cursor Actually Indexes Your Codebase (Towards Data Science)](https://towardsdatascience.com/how-cursor-actually-indexes-your-codebase/)

---

## 4. Claude Code's Approach

**What it does:** Uses an agentic search pattern — no pre-built index or embeddings. The agent explores the codebase on-demand using filesystem tools, guided by a layered memory hierarchy of CLAUDE.md files.

**How it works:**

### Agentic Search (no indexing)
- **Glob:** Fast file pattern matching (e.g., `**/*.py`), returns paths sorted by modification time
- **Grep:** ripgrep-powered content search with regex support, returns matching lines or file paths
- **Read:** Loads specific file contents (supports code, images, PDFs, notebooks)
- **Sub-agents:** Spawns lightweight Explore agents (running on Haiku) that search independently in their own context window and return summaries — not raw file contents — to the main agent

Anthropic's internal testing found agentic search outperformed vector-based retrieval significantly.

### Memory Hierarchy (CLAUDE.md)
- **Directory-scoped:** Claude searches upward from CWD to root, loading every `CLAUDE.md` found. Subdirectory files add specificity while inheriting parent context
- **Auto-memory:** Claude saves notes across sessions (build commands, architecture insights, debugging discoveries) in `~/.claude/projects/<path>/memory/MEMORY.md`
- **CLAUDE.local.md:** Per-developer overrides (gitignored)
- **Optimal size:** Under 200 lines per file achieves >92% rule adherence; >400 lines drops to ~71%

### Context Optimization
- 92% prompt prefix reuse rate across agentic loop turns (massive caching benefit)
- Tool Search defers loading of MCP tools, saving ~85% tokens with 10+ tools
- Explore sub-agents isolate search token costs from main conversation context

**Output format:** Not applicable — Claude Code doesn't produce a static artifact. It dynamically gathers context per-task. CLAUDE.md files are the closest to a "documentation format" — plain markdown with project-specific instructions.

**Strengths:**
- Never stale — reads live filesystem state every time
- Naturally progressive — starts broad (Glob/Grep), narrows to specific files (Read)
- Sub-agent isolation prevents exploration from consuming main context
- Memory hierarchy provides layered project knowledge without re-discovery
- No infrastructure dependency — works on any codebase immediately
- The agent decides what's relevant, not a pre-computed index

**Limitations:**
- Requires multiple tool calls per exploration — latency cost for each search
- No persistent semantic index — repeated sessions re-discover the same things (mitigated by CLAUDE.md memory)
- Effectiveness depends heavily on CLAUDE.md quality and the agent's search strategy
- Token cost per exploration is non-trivial (though cached via prefix reuse)
- Memory files require curation — auto-memory can accumulate noise

**Progressive disclosure:** Yes, deeply. The entire approach is progressive:
1. CLAUDE.md provides top-level project knowledge (loaded at session start)
2. Glob/Grep provide structural overview (file names, pattern matches)
3. Read provides full file content (on demand)
4. Explore sub-agents handle deep multi-file investigations in isolation

**References:**
- [Claude Code memory documentation](https://code.claude.com/docs/en/memory)
- [Claude Code Doesn't Index Your Codebase](https://vadim.blog/claude-code-no-indexing)
- [Claude Code Tool System Explained](https://callsphere.tech/blog/claude-code-tool-system-explained)

---

## 5. code2prompt

**What it does:** CLI tool (Rust) that converts a codebase into a single LLM prompt with source tree, customizable Handlebars templates, and token counting.

**How it works:**
1. Traverses directory, respecting `.gitignore` and glob include/exclude patterns
2. Applies a Handlebars template to format the output
3. Counts tokens using tiktoken-rs (cl100k, p50k, r50k_bas encodings)
4. Outputs to stdout, clipboard, or file

**Output format:** Customizable via Handlebars templates. Default includes source tree + file contents. Users can define custom variables and formatting.

**Strengths:**
- Template system allows highly customized output for specific LLM workflows
- Built in Rust — fast even on large repos
- TUI (Terminal User Interface) for interactive configuration
- Git diff inclusion option (staged files) for change-focused prompts
- Flexible filtering with glob patterns

**Limitations:**
- Static snapshot — no incremental updates
- No semantic analysis or ranking — purely structural
- No compression/signature extraction mode
- Template authoring required for non-default formats

**Progressive disclosure:** No built-in mechanism. Filtering via globs is manual.

**References:**
- [code2prompt GitHub](https://github.com/mufeedvh/code2prompt)

---

## 6. Gitingest

**What it does:** Converts any Git repository into a plain text digest optimized for LLM consumption. Available as a web service (swap `github.com` with `gitingest.com` in any URL), CLI, and Python package.

**How it works:**
1. Clones or reads the repository
2. Formats code with structure-preserving layout
3. Generates file tree visualization
4. Estimates token counts
5. Outputs as plain text digest

**Output format:** Plain text with file structure visualization and code contents.

**Strengths:**
- Frictionless web interface — just change the URL domain
- Browser extensions for Chrome/Firefox
- Local batch processing — no code leaves your machine in CLI mode
- Simple, no configuration needed for basic use

**Limitations:**
- Static snapshot only
- No semantic analysis or ranking
- No compression or signature-only mode
- Plain text only — no structured formats (XML, JSON)
- Limited filtering capabilities compared to Repomix/code2prompt

**Progressive disclosure:** No.

**References:**
- [Gitingest](https://gitingest.com/)

---

## 7. Sourcegraph Cody

**What it does:** Enterprise-grade RAG system combining code search with vector embeddings across multiple repositories. Provides AI-assisted code understanding with deep codebase context.

**How it works:**
- **Three context layers:** Local file context (editor), local repo context (current codebase), remote repo context (code search across org)
- Uses Sourcegraph's code search platform as the retrieval backbone
- Vector embeddings for semantic search
- Agentic chat mode with autonomous tool use (code search, file access, terminal, web)

**Output format:** Internal — context is injected into LLM prompts automatically. Not a standalone artifact.

**Strengths:**
- Multi-repo search — can pull context from across an entire organization
- Combines keyword search with semantic embeddings
- Agentic mode can autonomously gather context
- Enterprise-grade with access controls

**Limitations:**
- Enterprise-only (Free/Pro plans discontinued July 2025)
- Requires Sourcegraph infrastructure
- Not open-source in a meaningful way for self-hosting
- Proprietary context engine — no visibility into ranking decisions

**Progressive disclosure:** Yes — three-tier context (local file, local repo, remote repos) with automatic relevance ranking.

**References:**
- [How Cody understands your codebase](https://sourcegraph.com/blog/how-cody-understands-your-codebase)
- [Cody documentation](https://sourcegraph.com/docs/cody)

---

## 8. llms.txt Standard

**What it does:** A proposed web standard for providing LLM-friendly documentation at a well-known URL path (`/llms.txt`). Not a codebase tool per se, but relevant for library/API documentation consumed by coding agents.

**How it works:**
- Website serves `/llms.txt` — a markdown file with structured summary of the site's content
- Optionally serves `/llms-full.txt` — complete documentation in markdown
- Format is both human-readable and machine-parseable (supports regex/parser processing)
- Proposed by Jeremy Howard (Answer.AI) in September 2024

**Output format:** Markdown with specific structural conventions. Summary (llms.txt) links to detailed pages; full version (llms-full.txt) contains everything.

**Strengths:**
- Two-tier progressive disclosure by design (summary vs. full)
- Standard location — agents can discover it automatically
- Human-readable — doubles as documentation
- Growing adoption (Anthropic, Cursor, thousands of Mintlify-hosted docs)

**Limitations:**
- Not yet officially adopted by major LLM providers for crawling
- Requires manual maintenance — no auto-generation from code
- Designed for web documentation, not source code
- Adoption is still fragmented

**Progressive disclosure:** Yes, by design. `/llms.txt` is the summary layer with links; `/llms-full.txt` is the complete content.

**References:**
- [llms.txt specification](https://llmstxt.org/)
- [What is llms.txt? (Mintlify)](https://www.mintlify.com/blog/what-is-llms-txt)

---

## Key Findings and Recommendations

### The spectrum of approaches

These tools fall on a spectrum from **static snapshot** to **dynamic agentic**:

```
Static Snapshot ←————————————————————→ Dynamic Agentic
Gitingest  code2prompt  Repomix  llms.txt  Aider  Cursor  Cody  Claude Code
```

### For AI agent consumption specifically:

1. **Best for one-shot analysis:** Repomix with `--compress` mode. Produces a single file an agent can consume in one prompt. Good for code review, architecture analysis, migration planning.

2. **Best for ongoing coding sessions:** Aider's repo-map approach. The PageRank-ranked signature map gives structural awareness at minimal token cost, with full files on demand.

3. **Best for large-scale navigation:** Cursor's embedding approach or Sourcegraph Cody. Semantic search scales to massive codebases where enumeration-based approaches fail.

4. **Best for agent autonomy:** Claude Code's agentic search pattern. No pre-computation, no staleness, fully adaptive to the task at hand. The CLAUDE.md memory hierarchy is the closest thing to "progressive disclosure documentation" that's also human-maintainable.

5. **Best for library documentation:** llms.txt standard. Purpose-built for the use case of "an LLM needs to understand this API."

### Progressive disclosure is the key differentiator

The tools that support progressive disclosure (layered detail levels) are dramatically more effective for agent consumption than those that don't. An agent rarely needs the entire codebase at once — it needs to understand the structure first, then drill into specific areas. The ideal system provides:

- **Layer 0:** Project purpose, architecture, key conventions (CLAUDE.md / llms.txt)
- **Layer 1:** File tree + symbol signatures (repo-map / Repomix compress)
- **Layer 2:** Full file contents for specific files (on-demand retrieval)
- **Layer 3:** Cross-repo context (Sourcegraph Cody / multi-repo search)

No single tool covers all four layers well. A practical approach combines CLAUDE.md (Layer 0) with either agentic search (Claude Code) or repo-map + retrieval (Aider/Cursor) for Layers 1-2.
