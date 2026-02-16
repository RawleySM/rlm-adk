# Repomix ADK Session State Integration Spec

## 1. Problem Statement

The RLM agent currently loads individual source files into ADK session state as separate `gh_file:SpendMend/{repo}/{path}` keys (see `fetcher_agent.py:80-107`). This approach:

- Caps at 10 files with a naive `rglob("*")` walk (`max_files=10`)
- Misses the repository's directory structure and file relationships
- Produces many small state keys that the REPL must reassemble into a `context['files']` dict

Repomix generates a single XML document containing the full directory tree plus all file contents, purpose-built for LLM consumption. This spec defines how to deliver repomix output through ADK session state to the REPL orchestrator.

## 2. Current State Contract

### 2.1 Fetcher writes (fetcher_agent.py:80-112)

| Key pattern | Type | Example |
|---|---|---|
| `gh_file:SpendMend/{repo}/{path}` | `str` (file content) | `gh_file:SpendMend/Explorer/backend/routes/clients.py` |
| `fetched_files` | `list[str]` (key names) | `["gh_file:SpendMend/Explorer/backend/routes/clients.py", ...]` |
| `jira:{ticket}` | `dict` (structured ticket data) | `jira:DATA-1234` |

### 2.2 REPL reads (repl_orchestrator.py:217-223)

```python
gh_files = {k: v for k, v in state.items() if k.startswith("gh_file:")}
ns["context"] = {
    "text": state.get("context", ""),
    "files": gh_files,
    "search_results": state.get("last_repo_search_rows", []),
}
```

### 2.3 Thinker references (agent.py:63-70)

The thinker instruction tells the LLM:
- `{fetched_files?}` -- lightweight list of what was loaded
- `context['files']` is a dict mapping `gh_file:Owner/Repo/path` to file content strings
- `context['search_results']` holds repo search results

### 2.4 Sub-LM consumption pattern

The RLM architecture uses sub-LM dispatch (`llm_query`/`llm_query_batched`), so repo content flows through REPL code into sub-LM calls, **not** into the thinker's own context window. This means:

```python
# Current pattern (per-file)
result = llm_query(f"Analyze this file:\n{context['files']['gh_file:SpendMend/repo/path']}")

# Proposed pattern (full repomix XML)
result = llm_query(f"Analyze this codebase:\n{context['repomix_xml']}")
```

Because sub-LMs handle ~500K characters, a typical repomix output (~400KB) fits comfortably in a single sub-LM call.

## 3. Proposed State Schema

### 3.1 New keys written by fetcher

| Key | Type | Scope | Description |
|---|---|---|---|
| `repomix_xml` | `str` | Session (no prefix) | Full repomix XML output. Single string, typically 100KB-1MB. |
| `repomix_tree` | `str` | Session (no prefix) | Directory structure section only (extracted from `<directory_structure>` tag). Lightweight (~2-5KB). |
| `repomix_repo` | `str` | Session (no prefix) | Repository name, e.g. `"SpendMend/Explorer"`. |
| `repomix_file_count` | `int` | Session (no prefix) | Number of files packed in the XML. |
| `fetched_files` | `list[str]` | Session (no prefix) | **Retained.** List of file paths from the repomix output (extracted from `<file path="...">` tags). Keeps backward compatibility with thinker instruction `{fetched_files?}`. |

### 3.2 Deprecated keys (phased out)

| Key pattern | Status | Migration |
|---|---|---|
| `gh_file:*` | **Deprecated.** | Stop writing individual file keys. The REPL will read from `repomix_xml` instead. |

### 3.3 Prefix rationale

All keys use **no prefix** (session scope) because:
- Repomix output is specific to the current session's ticket/repo
- It must persist across LoopAgent iterations (rules out `temp:`)
- It is not user-level or app-level data (rules out `user:` and `app:`)

### 3.4 Size budget

| Constraint | Value | Notes |
|---|---|---|
| ADK state value max | No hard limit in InMemorySessionService | Values are Python objects in memory; no serialization size cap for in-memory sessions |
| DatabaseSessionService | Limited by DB column size (typically TEXT/LONGTEXT) | For future persistent sessions; repomix XML at ~400KB is well within MySQL LONGTEXT (4GB) or PostgreSQL TEXT (unlimited) |
| Practical ceiling | ~2MB per state value | Beyond this, session event append and state merge become slow. Repomix with `--compress` or file filtering should keep output under 1MB. |
| Namespace snapshot cap | 500KB (repl_orchestrator.py:259) | The pickled REPL namespace is capped at 500KB. Repomix XML should NOT be pickled into the namespace -- it should be injected fresh each iteration from state. |

## 4. REPL Context Rebuild

### 4.1 Updated `_build_namespace` (repl_orchestrator.py:212-236)

The REPL currently builds `context` from `gh_file:*` state keys. The updated logic:

```python
def _build_namespace(self, ctx: InvocationContext) -> dict:
    state = ctx.session.state
    ns = self._restore_namespace(ctx)

    # Repomix path (preferred)
    repomix_xml = state.get("repomix_xml", "")
    if repomix_xml:
        # Parse file paths and contents from XML for backward-compat dict
        parsed_files = _parse_repomix_files(repomix_xml)
        ns["context"] = {
            "text": state.get("context", ""),
            "files": parsed_files,              # dict[str, str] -- backward compat
            "repomix_xml": repomix_xml,          # full XML for sub-LM consumption
            "tree": state.get("repomix_tree", ""),
            "search_results": state.get("last_repo_search_rows", []),
        }
    else:
        # Legacy fallback: individual gh_file:* keys
        gh_files = {k: v for k, v in state.items() if k.startswith("gh_file:")}
        ns["context"] = {
            "text": state.get("context", ""),
            "files": gh_files,
            "search_results": state.get("last_repo_search_rows", []),
        }

    # ... rest of namespace setup unchanged ...
```

### 4.2 Repomix XML parser helper

A lightweight parser extracts individual files from the repomix XML format:

```python
import re

def _parse_repomix_files(xml: str) -> dict[str, str]:
    """Extract file path -> content mapping from repomix XML.

    Repomix format:
        <file path="backend/routes/clients.py">
        ... file content ...
        </file>
    """
    files = {}
    for match in re.finditer(
        r'<file\s+path="([^"]+)">\n?(.*?)</file>',
        xml,
        re.DOTALL,
    ):
        path, content = match.group(1), match.group(2)
        files[path] = content
    return files
```

This gives REPL code two access patterns:
1. **Granular**: `context['files']['backend/routes/clients.py']` -- individual file access
2. **Holistic**: `context['repomix_xml']` -- pass entire XML to sub-LM

### 4.3 Key difference in file key format

| Source | Key format | Example |
|---|---|---|
| Legacy `gh_file:*` | `gh_file:SpendMend/Explorer/backend/routes/clients.py` | Full GitHub-style path with org prefix |
| Repomix parsed | `backend/routes/clients.py` | Relative path within repo (matches repomix `<file path="...">`) |

The thinker instruction and REPL code should be updated to use relative paths. Existing code that accesses `context['files']` by iterating keys will work unchanged; code that constructs keys with the `gh_file:` prefix will need updating.

## 5. Thinker Instruction Updates

### 5.1 Updated instruction fragment (agent.py:63-82)

The thinker's dynamic instruction should be updated to describe the new context structure:

```
"The fetcher agent loaded {repomix_file_count?} files from {repomix_repo?} into the REPL context.\n\n"
"File list: {fetched_files?}\n\n"
"**`context` structure**: The `context` variable in the REPL is a dict with keys:\n"
"- `'repomix_xml'`: Full repository content as XML (pass to llm_query for holistic analysis)\n"
"- `'files'`: Dict mapping relative file paths to content strings (for targeted file access)\n"
"- `'tree'`: Directory structure of the repository\n"
"- `'search_results'`: Repo search results if available\n"
"- `'text'`: Initial context string\n\n"
"**Recommended patterns**:\n"
"- For broad codebase analysis: `llm_query(f'Analyze: {context[\"repomix_xml\"]}')`\n"
"- For targeted file analysis: `content = context['files']['path/to/file.py']`\n"
"- For directory overview: `print(context['tree'])`\n"
```

### 5.2 Static instruction (prompts_explorer.py)

No changes needed. The static instruction already describes `context` generically and uses `llm_query` patterns that work with both approaches.

## 6. Fetcher Agent Changes

### 6.1 Repomix invocation

The fetcher agent (`fetcher_agent.py`) replaces the file-walking loop (lines 80-105) with a repomix CLI call:

```python
import subprocess

def _run_repomix(self, local_path: str, repo_name: str) -> tuple[str, list[str]]:
    """Run repomix on a local repo clone. Returns (xml_output, file_paths)."""
    result = subprocess.run(
        [
            "repomix",
            "--style", "xml",
            "--output", "-",           # stdout
            "--include", ",".join(f"**/*{ext}" for ext in self.file_extensions),
        ],
        cwd=local_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    xml = result.stdout
    # Extract file paths for fetched_files list
    paths = re.findall(r'<file\s+path="([^"]+)">', xml)
    return xml, paths
```

### 6.2 Updated state delta

```python
xml, file_paths = self._run_repomix(local_path, repo_name)
tree = _extract_directory_structure(xml)  # extract <directory_structure> section

delta["repomix_xml"] = xml
delta["repomix_tree"] = tree
delta["repomix_repo"] = f"SpendMend/{repo_name}"
delta["repomix_file_count"] = len(file_paths)
delta["fetched_files"] = file_paths  # list of relative paths
```

### 6.3 Helper: extract directory structure

```python
def _extract_directory_structure(xml: str) -> str:
    """Extract the <directory_structure> section from repomix XML."""
    match = re.search(
        r'<directory_structure>\n?(.*?)</directory_structure>',
        xml,
        re.DOTALL,
    )
    return match.group(1).strip() if match else ""
```

## 7. Backward Compatibility

### 7.1 Migration strategy: parallel write (Phase 1)

During the transition, the fetcher writes BOTH old and new keys:

```python
# New repomix keys
delta["repomix_xml"] = xml
delta["repomix_tree"] = tree
delta["repomix_repo"] = f"SpendMend/{repo_name}"
delta["repomix_file_count"] = len(file_paths)

# Legacy keys (for any code still reading gh_file:*)
for path, content in _parse_repomix_files(xml).items():
    delta[f"gh_file:SpendMend/{repo_name}/{path}"] = content

delta["fetched_files"] = [
    f"gh_file:SpendMend/{repo_name}/{p}" for p in file_paths
]
```

### 7.2 Phase 2: drop legacy keys

Once the REPL and thinker instructions are updated (sections 4 and 5), remove the legacy `gh_file:*` writes. The `fetched_files` key persists but switches to relative paths.

### 7.3 REPL code compatibility

The REPL `_build_namespace` detects which format is available (section 4.1). This means:
- Old sessions (no `repomix_xml`) continue to work via `gh_file:*` fallback
- New sessions get the repomix-enhanced context
- REPL code that iterates `context['files']` works either way (different key format, same value type)

## 8. Namespace Snapshot Considerations

The REPL namespace is pickled and stored in `temp:repl_namespace` (capped at 500KB, see `repl_orchestrator.py:259`). The repomix XML should **not** be included in the pickled namespace because:

1. It is already available in session state and rebuilt fresh each iteration
2. Including it would blow the 500KB cap for any non-trivial repo

The `_build_namespace` method already rebuilds `context` fresh each iteration (line 217: "ALWAYS rebuild context from current state -- no conditional"). The `_snapshot_namespace` method snapshots non-callable entries, so `context` (a dict) would be included. To prevent this:

```python
def _snapshot_namespace(self, ns: dict) -> str:
    safe = {
        k: v for k, v in ns.items()
        if not callable(v) and k != "__builtins__"
        and k != "_tool_requests"
        and k != "context"          # <-- exclude context; rebuilt from state
        and _is_picklable(v)
    }
    # ... rest unchanged
```

This is safe because `context` is always rebuilt from state at the start of each iteration.

## 9. Token Efficiency Analysis

### 9.1 Current approach: per-file sub-LM calls

```
Thinker context:  ~2K tokens (instruction + iteration history)
Sub-LM per file:  ~5-50K tokens each, 10 files = 50-500K tokens total
Total per iteration: ~50-500K tokens across sub-LM calls
```

### 9.2 Repomix approach: holistic sub-LM calls

```
Thinker context:  ~2K tokens (instruction + iteration history)
Sub-LM holistic:  ~100-300K tokens (full XML in one call)
Total per iteration: ~100-300K tokens in fewer, larger sub-LM calls
```

The repomix approach trades slightly higher per-call token usage for:
- **Better context**: sub-LM sees the full repository structure and cross-file relationships
- **Fewer round-trips**: one sub-LM call instead of 10+ sequential/batched calls
- **No file selection bias**: the thinker does not need to guess which files are relevant upfront

### 9.3 Chunking strategy for large repos

For repos where repomix output exceeds ~500K characters (rare with filtering), the REPL code can chunk the XML:

```python
# In REPL code (thinker writes this)
xml = context['repomix_xml']
if len(xml) > 400_000:
    # Split by <file> boundaries for clean chunking
    files = context['files']
    keys = list(files.keys())
    mid = len(keys) // 2
    chunk1 = "\n".join(files[k] for k in keys[:mid])
    chunk2 = "\n".join(files[k] for k in keys[mid:])
    answers = llm_query_batched([
        f"Analyze this first half of the codebase:\n{chunk1}",
        f"Analyze this second half of the codebase:\n{chunk2}",
    ])
else:
    answer = llm_query(f"Analyze this codebase:\n{xml}")
```

## 10. Summary of Changes

| Component | File | Change |
|---|---|---|
| Fetcher | `fetcher_agent.py` | Replace `rglob` file walk with `repomix` CLI call; write `repomix_xml`, `repomix_tree`, `repomix_repo`, `repomix_file_count` to state |
| REPL | `repl_orchestrator.py` | Update `_build_namespace` to prefer `repomix_xml` from state; add `_parse_repomix_files` helper; exclude `context` from namespace snapshot |
| Thinker instruction | `agent.py` | Update dynamic instruction to describe new context structure and recommended patterns |
| Static instruction | `prompts_explorer.py` | No changes needed |

## 11. Open Questions

1. **Repomix filtering**: Should we use `--include` to match the current `file_extensions` tuple, or let repomix use its default gitignore-based filtering? Default filtering may be more comprehensive.

2. **Repomix `--compress`**: Repomix has a `--compress` flag that removes comments and whitespace. Should we use it for large repos to stay under size budgets? Tradeoff: compressed output loses comments that may be relevant for understanding intent.

3. **Python SDK vs CLI**: Repomix has a Python SDK (`python-repomix`). Should the fetcher use the SDK for tighter integration, or shell out to the CLI for simplicity? The CLI is simpler and avoids adding a Python dependency.

4. **Multiple repos**: Some Jira tickets span multiple repos. Should we support concatenating repomix output from multiple repos into a single `repomix_xml` value, or use separate keys like `repomix_xml:{repo}`?
