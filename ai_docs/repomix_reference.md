# Repomix v1.11.1 Reference

> Extracted from CLI `--help`, source inspection, and empirical testing on 2026-02-12.
> Binary: `/home/rawleysm/.nvm/versions/node/v20.19.5/bin/repomix`

## Overview

Repomix packs a repository into a single AI-consumable file. It supports four output formats (XML, Markdown, JSON, plain text), Tree-sitter-based structural compression for 16 languages, glob-based file selection, git context injection, and security scanning.

---

## CLI Flags (Complete)

### Output Format & Content

| Flag | Description | Default |
|---|---|---|
| `--style <type>` | Output format: `xml`, `markdown`, `json`, `plain` | `xml` |
| `-o, --output <file>` | Output file path. Use `-` for stdout | `repomix-output.xml` |
| `--stdout` | Write to stdout (suppresses all logging) | off |
| `--compress` | Tree-sitter structural extraction (see Compression section) | off |
| `--parsable-style` | Escape `<`, `>` as XML entities in file content (makes XML parseable) | off |
| `--output-show-line-numbers` | Prefix lines with `N: ` format | off |
| `--remove-comments` | Strip code comments (shebang lines also removed) | off |
| `--remove-empty-lines` | Remove blank lines | off |
| `--truncate-base64` | Truncate long base64 data strings | off |
| `--no-file-summary` | Omit the preamble/summary section | off |
| `--no-directory-structure` | Omit the directory tree | off |
| `--no-files` | Metadata only (no file contents) | off |
| `--header-text <text>` | Custom text at the start | none |
| `--instruction-file-path <path>` | Include custom instructions from file | none |
| `--split-output <size>` | Split into numbered parts (e.g., `1mb`, `500kb`). Fails if any top-level dir exceeds the limit. | off |
| `--no-git-sort-by-changes` | Disable git change frequency sorting | sorted by changes |
| `--include-diffs` | Add `<git_diffs>` section with working tree + staged diffs | off |
| `--include-logs` | Add `<git_logs>` section with commit history | off |
| `--include-logs-count <n>` | Number of recent commits for `--include-logs` | 50 |
| `--include-empty-directories` | Include empty folders in directory tree | off |
| `--include-full-directory-structure` | Show full tree even when using `--include` patterns | off |
| `--copy` | Copy output to clipboard | off |

### File Selection

| Flag | Description |
|---|---|
| `--include <patterns>` | Comma-separated globs: `"src/**/*.js,*.md"` |
| `-i, --ignore <patterns>` | Additional exclusion globs: `"*.test.js,docs/**"` |
| `--stdin` | Read file paths from stdin, one per line |
| `--no-gitignore` | Don't use `.gitignore` rules |
| `--no-dot-ignore` | Don't use `.ignore` rules |
| `--no-default-patterns` | Don't exclude `node_modules`, `.git`, `build/`, etc. |

### Token Counting

| Flag | Description | Default |
|---|---|---|
| `--token-count-encoding <enc>` | Tokenizer: `o200k_base` (GPT-4o), `cl100k_base` (GPT-3.5/4) | `o200k_base` |
| `--token-count-tree [threshold]` | Show file tree with token counts; optional min threshold | off |
| `--top-files-len <n>` | Top N largest files in summary | 5 |

### Remote & Config

| Flag | Description |
|---|---|
| `--remote <url>` | Clone and pack a remote repo (GitHub URL or `user/repo`) |
| `--remote-branch <name>` | Branch/tag/commit for remote clone |
| `-c, --config <path>` | Custom config file path |
| `--init` | Create `repomix.config.json` with defaults |
| `--global` | With `--init`, create in home directory |

### Security

| Flag | Description |
|---|---|
| `--no-security-check` | Skip scanning for API keys, passwords, etc. |

### Experimental

| Flag | Description |
|---|---|
| `--mcp` | Run as MCP (Model Context Protocol) server |
| `--skill-generate [name]` | Generate Claude Agent Skills format to `.claude/skills/<name>/` |
| `--skill-output <path>` | Skill output directory path |
| `-f, --force` | Skip confirmation prompts (e.g., overwrite skill dir) |

---

## Output Format Schemas

### XML (default)

```xml
This file is a merged representation of ...

<file_summary>
  <purpose>...</purpose>
  <file_format>...</file_format>
  <usage_guidelines>...</usage_guidelines>
  <notes>...</notes>
</file_summary>

<directory_structure>
backend/
  routes/
    users.py
frontend/
  src/
    App.tsx
</directory_structure>

<files>
This section contains the contents of the repository's files.

<file path="backend/routes/users.py">
... full file content ...
</file>

<file path="frontend/src/App.tsx">
... full file content ...
</file>
</files>
```

**Note**: File content is NOT XML-escaped by default. Use `--parsable-style` to escape `<` and `>` as `&lt;` / `&gt;` for valid XML parsing.

### With `--parsable-style`
File content has `<` -> `&lt;` and `>` -> `&gt;` escaping. No CDATA wrapping.

### With `--include-diffs` and `--include-logs`
Additional sections appear before `<files>`:
```xml
<git_diffs>
  <git_diff_work_tree>... diff output ...</git_diff_work_tree>
  <git_diff_staged>... diff output ...</git_diff_staged>
</git_diffs>

<git_logs>
  <git_log_commit>
    <date>2026-01-05 15:46:14 +0000</date>
    <message>commit message</message>
    <files>file1.py\nfile2.py</files>
  </git_log_commit>
</git_logs>
```

### Markdown

```markdown
# File Summary
## Purpose
...

# Directory Structure
\`\`\`
backend/
  routes/
    users.py
\`\`\`

## File: backend/routes/users.py
\`\`\`
... full file content ...
\`\`\`
```

### JSON

```json
{
  "fileSummary": {
    "generationHeader": "...",
    "purpose": "...",
    "fileFormat": "...",
    "usageGuidelines": "...",
    "notes": "..."
  },
  "directoryStructure": "backend/\n  routes/\n    users.py\n...",
  "files": {
    "backend/routes/users.py": "... full file content ...",
    "frontend/src/App.tsx": "... full file content ..."
  }
}
```

**JSON is the easiest format to parse programmatically** -- `files` is a flat `{path: content}` dict.

### Plain

```
================================================================
File Summary
================================================================
Purpose:
...

================================================================
Directory Structure
================================================================
backend/
  routes/
    users.py

================================================================
File: backend/routes/users.py
================================================================
... full file content ...
```

---

## Compression (`--compress`)

### How It Works

Tree-sitter parses supported source files into ASTs, then extracts structural elements (class/function signatures, interfaces, key statements). Chunks are separated by `⋮----` delimiters. Non-structural code (function bodies, loops, etc.) is elided.

### Supported Languages (Tree-sitter Grammars)

From `languageConfig.js` in repomix v1.11.1:

| Language | Extensions | Parse Strategy |
|---|---|---|
| JavaScript | `.js`, `.jsx`, `.cjs`, `.mjs`, `.mjsx` | TypeScript |
| TypeScript | `.ts`, `.tsx`, `.mts`, `.mtsx`, `.cts` | TypeScript |
| Python | `.py` | Python |
| Go | `.go` | Go |
| Rust | `.rs` | Default |
| Java | `.java` | Default |
| C# | `.cs` | Default |
| Ruby | `.rb` | Default |
| PHP | `.php` | Default |
| Swift | `.swift` | Default |
| C | `.c`, `.h` | Default |
| C++ | `.cpp`, `.hpp` | Default |
| CSS | `.css` | CSS |
| Solidity | `.sol` | Default |
| Vue | `.vue` | Vue |
| Dart | `.dart` | Default |

### UNSUPPORTED file types (passed through UNCHANGED)

Files without Tree-sitter grammars are included with their **full original content**. They are NOT dropped, NOT mangled, NOT compressed. Verified empirically:

| Extension | Behavior with `--compress` |
|---|---|
| `.sql` | **Unchanged** (ratio 1.00) |
| `.yml` / `.yaml` | **Unchanged** (ratio 1.00) |
| `.json` | **Unchanged** (ratio 1.00) |
| `.md` | **Unchanged** (ratio 1.00) |
| `.csv` | **Unchanged** (ratio 1.00) |
| `.html` | **Unchanged** (ratio 1.00) |
| `.toml` | **Unchanged** (ratio 1.00) |
| `.cfg` | **Unchanged** (ratio 1.00) |
| `.sh` | **Unchanged** (ratio 1.00) |
| `.bat` | **Unchanged** (ratio 1.00) |
| `.tf` (Terraform) | **Unchanged** (ratio 1.00) |
| `.hcl` | **Unchanged** (ratio 1.00) |
| `.conf` | **Unchanged** (ratio 1.00) |
| `.svg` | **Unchanged** (ratio 1.00) |
| `.gitignore` | **Unchanged** (ratio 1.00) |
| `.ipynb` | **Unchanged** (ratio 1.00) |

**Source code confirmation**: In `fileProcessContent.js` line 45-48, when `parseFile()` returns `undefined` (unsupported language), the original content is used: `processedContent = parsedContent ?? processedContent`.

### Compression Ratios (Empirical)

Tested on SpendMend repos:

| File Type | Typical Ratio | Notes |
|---|---|---|
| `.py` (Python) | 0.25 - 0.65 | Heavy compression; keeps signatures, docstrings |
| `.tsx` (React) | 0.14 | Very heavy compression on JSX |
| `.ts` (TypeScript) | 0.41 | Moderate compression |
| `.js` (JavaScript) | 0.08 | Very heavy (most content is in function bodies) |
| `.css` | 0.34 | Moderate compression |
| All non-code | 1.00 | **No change** |

### Compressed Output Example

Normal Python:
```python
class TrullaLogging(logging.Logger):
    """A custom logging class..."""
    def __init__(self, log_name=None, ...):
        if log_name is None:
            self.log_name = os.path.basename(sys.argv[0])
        else:
            self.log_name = log_name
        super().__init__(self.log_name, level=log_level)
        # ... 30 more lines ...
```

Compressed:
```
class TrullaLogging(logging.Logger)
⋮----
"""
    A custom logging class that allows for logging to a file, stream, and AWS CloudWatch Logs.
    """
⋮----
file_handler = logging.FileHandler(self.log_file)
⋮----
stream_handler = logging.StreamHandler()
⋮----
cloudwatch_handler = CloudwatchLogsHandler(...)
```

**Key observation**: Compressed output preserves class/function signatures, docstrings, and key assignment statements. It elides control flow, loops, and implementation details.

---

## Performance

| Repo | Files | Normal | Compressed | Time (normal) | Time (compressed) |
|---|---|---|---|---|---|
| TrullaPyModules | 9 | 9,399 tokens | 5,090 tokens | <1s | <1s |
| sm-audit-os | 243 | ~1.4M chars | ~406K chars | 2.3s | 2.1s |
| SpendMend-Data-Transform | 1,082 | ~1.5M chars | ~1.45M chars | ~12s | ~12s |

SDT barely changed with compress because it's 92% SQL (no Tree-sitter grammar). Compression does NOT add overhead for unsupported file types.

---

## Python SDK (`repomix` on PyPI, v0.4.1)

### Installation

```bash
uv pip install repomix  # or: pip install repomix
```

### API

```python
from repomix import (
    RepoProcessor,
    RepomixConfig,
    RepomixConfigOutput,
    RepomixOutputStyle,
    RepoProcessorResult,
)

# Configure
config = RepomixConfig()
config.output.style = 'xml'          # or 'json', 'markdown', 'plain'
config.output.compress = True         # WARNING: does NOT work (see below)
config.output.show_directory_structure = True
config.output.show_line_numbers = False
config.security.enable_security_check = False

# Process a local directory
proc = RepoProcessor(
    directory='/path/to/repo',
    config=config,
)

# Optional: restrict to specific files
proc.set_predefined_file_paths(['src/main.py', 'README.md'])

# Run (write_output=False returns content without writing to disk)
result: RepoProcessorResult = proc.process(write_output=False)

print(result.total_files)      # int
print(result.total_chars)      # int
print(result.total_tokens)     # int (always 0 -- token counting not implemented)
print(result.output_content)   # str: the full packed output
print(result.file_char_counts) # dict[str, int]
```

### RepoProcessor Constructor

```python
RepoProcessor(
    directory: str | Path | None = None,  # Local repo path
    repo_url: str | None = None,          # Remote repo URL
    branch: str | None = None,            # Branch for remote
    config: RepomixConfig | None = None,  # Configuration
    config_path: str | None = None,       # Config file path
    cli_options: dict | None = None,      # CLI-style overrides
)
```

### RepoProcessorResult Fields

```python
@dataclass
class RepoProcessorResult:
    config: RepomixConfig
    file_tree: dict[str, str | list]
    total_files: int
    total_chars: int
    total_tokens: int                  # Always 0 (not implemented)
    file_char_counts: dict[str, int]
    file_token_counts: dict[str, int]  # Always 0 (not implemented)
    output_content: str                # The packed output string
    suspicious_files_results: list[SuspiciousFileResult]
```

### RepomixConfig Defaults

```python
RepomixConfig(
    input=RepomixConfigInput(max_file_size=52428800),  # 50MB
    output=RepomixConfigOutput(
        file_path='repomix-output.md',
        style='markdown',           # NOTE: defaults to markdown, not xml
        compress=False,
        show_line_numbers=False,
        show_directory_structure=True,
        parsable_style=False,
        truncate_base64=False,
        remove_comments=False,
        remove_empty_lines=False,
        top_files_length=5,
        copy_to_clipboard=False,
        include_empty_directories=False,
        include_full_directory_structure=False,
        split_output=None,
        git=RepomixConfigGit(
            sort_by_changes=True,
            sort_by_changes_max_commits=100,
            include_diffs=False,
            include_logs=False,
            include_logs_count=50,
        ),
    ),
    security=RepomixConfigSecurity(
        enable_security_check=True,
        exclude_suspicious_files=True,
    ),
    ignore=RepomixConfigIgnore(
        custom_patterns=[],
        use_gitignore=True,
        use_default_ignore=True,
    ),
    compression=RepomixConfigCompression(
        enabled=False,
        keep_signatures=True,
        keep_docstrings=True,
        keep_interfaces=True,
    ),
    include=[],
)
```

### CRITICAL LIMITATION: Python SDK `compress` Does NOT Work

The Python SDK's `--compress` flag has **no effect** (tested: output is identical with compress=True and compress=False, ratio 1.00). The Python SDK does NOT include Tree-sitter bindings. Tree-sitter compression only works in the **Node.js CLI**.

### Python SDK vs CLI Output Differences

The Python SDK generates slightly different XML than the CLI:
- Uses `<repository>` root element and `<repository_structure>` instead of `<directory_structure>`
- Token counts are always 0 (no tiktoken/tokenizer integration)
- Default output style is `markdown` (CLI defaults to `xml`)

### When to Use Python SDK vs CLI

| Scenario | Recommendation |
|---|---|
| Need `--compress` | **CLI only** (Python SDK lacks Tree-sitter) |
| Need token counts | **CLI only** |
| Programmatic integration (no compress) | Python SDK works well |
| Specific file selection | Both work (`set_predefined_file_paths` or `--stdin`) |
| Async integration in ADK agent | CLI via subprocess (see below) |

---

## Alternative Python Packages

### `repopack` (PyPI v0.1.4)

Simpler Python-native tool. API:
```python
import repopack
result = repopack.pack(root_dir="/path/to/repo", config={}, output_path="output.txt")
```
- No Tree-sitter compression
- No XML output format
- Much smaller feature set than repomix

### `code2prompt` (PyPI v0.8.1)

Requires `tiktoken` (needs Rust compiler to build). Not tested due to build dependency.

---

## Subprocess Integration Pattern (Recommended for ADK)

For the RLM agent, calling the CLI via subprocess is recommended over the Python SDK because:
1. Only the CLI supports `--compress` (Tree-sitter)
2. Only the CLI produces accurate token counts
3. JSON output is trivially parseable

### Async Python Pattern

```python
import asyncio
import json
from pathlib import Path

REPOMIX_BIN = "/home/rawleysm/.nvm/versions/node/v20.19.5/bin/repomix"

async def pack_repo(
    repo_path: str | Path,
    include: list[str] | None = None,
    compress: bool = False,
    style: str = "json",
    timeout: float = 120.0,
) -> dict:
    """Pack a repository using repomix CLI and return parsed output."""
    cmd = [
        REPOMIX_BIN,
        str(repo_path),
        "--style", style,
        "--stdout",
        "--no-security-check",
        "--quiet",
    ]
    if compress:
        cmd.append("--compress")
    if include:
        cmd.extend(["--include", ",".join(include)])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(repo_path),
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(), timeout=timeout
    )

    if proc.returncode != 0:
        raise RuntimeError(f"repomix failed: {stderr.decode()}")

    if style == "json":
        return json.loads(stdout.decode())
    return {"raw": stdout.decode()}


async def pack_repo_files(
    repo_path: str | Path,
    file_paths: list[str],
    compress: bool = False,
    style: str = "json",
    timeout: float = 120.0,
) -> dict:
    """Pack specific files from a repo using stdin file list."""
    cmd = [
        REPOMIX_BIN,
        str(repo_path),
        "--stdin",
        "--style", style,
        "--stdout",
        "--no-security-check",
        "--quiet",
    ]
    if compress:
        cmd.append("--compress")

    input_data = "\n".join(file_paths).encode()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(repo_path),
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=input_data), timeout=timeout
    )

    if proc.returncode != 0:
        raise RuntimeError(f"repomix failed: {stderr.decode()}")

    if style == "json":
        return json.loads(stdout.decode())
    return {"raw": stdout.decode()}
```

### Usage in ADK Tool

```python
# As a FunctionTool for an ADK agent
async def fetch_repo_context(
    repo_name: str,
    include_patterns: str = "",
    compress: bool = True,
) -> str:
    """Fetch repository context as packed XML for analysis."""
    repo_path = f"/tmp/spendmend-repos/{repo_name}"
    include = [p.strip() for p in include_patterns.split(",") if p.strip()] or None

    result = await pack_repo(
        repo_path=repo_path,
        include=include,
        compress=compress,
        style="xml",
    )
    return result["raw"]
```

---

## Recommended Flag Combinations

### For RLM Agent (full context, token-efficient)
```bash
repomix /path/to/repo --style xml --compress --no-file-summary --no-security-check --stdout
```
- Compress reduces Python/TS/JS significantly
- SQL/YAML/MD pass through unchanged (safe)
- `--no-file-summary` saves ~500 tokens of boilerplate

### For JSON programmatic access
```bash
repomix /path/to/repo --style json --no-security-check --stdout
```
- Trivially parseable: `json.loads(stdout)`
- `files` dict keyed by path

### For debugging / code review
```bash
repomix /path/to/repo --style xml --output-show-line-numbers --include-diffs --include-logs
```

### For cost estimation
```bash
repomix /path/to/repo --token-count-tree --no-files --quiet
```
- Shows token counts per file without producing full output

### For large repos
```bash
repomix /path/to/repo --style xml --compress --include "src/**/*.py,src/**/*.ts" --no-security-check --stdout
```
- Use `--include` to narrow scope
- `--compress` reduces code tokens
- `--split-output 2mb` if output exceeds context window

---

## File Ordering

By default, files are sorted by **git change frequency** (most-changed files last). This puts the most actively developed files at the end of the output, which is useful for LLM context (recent tokens are more likely to be in the attention window).

Disable with `--no-git-sort-by-changes` for alphabetical ordering.

---

## Security Scanning

Enabled by default. Scans for:
- API keys, tokens, passwords in file content
- Files matching suspicious patterns (`.env`, `credentials.*`, etc.)

Disable with `--no-security-check` for trusted/internal repos.

---

## MCP Server Mode

`repomix --mcp` runs as a Model Context Protocol server, allowing AI tools (Claude Desktop, etc.) to call repomix as a tool. Not tested in this reference -- see repomix documentation for MCP protocol details.
