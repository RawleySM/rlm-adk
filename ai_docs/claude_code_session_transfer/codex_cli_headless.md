# Codex CLI Headless Mode & Agent Handoff Research

Research date: 2026-03-13

---

## Table of Contents

1. [Codex CLI Non-Interactive Mode (`codex exec`)](#1-codex-cli-non-interactive-mode-codex-exec)
2. [Passing Context and State to Codex CLI](#2-passing-context-and-state-to-codex-cli)
3. [Full-Auto and Approval Bypass Modes](#3-full-auto-and-approval-bypass-modes)
4. [Programmatic Invocation via SDK](#4-programmatic-invocation-via-sdk)
5. [Codex as MCP Server (Agents SDK Integration)](#5-codex-as-mcp-server-agents-sdk-integration)
6. [Claude Code / Codex CLI Interop & Session Transfer](#6-claude-code--codex-cli-interop--session-transfer)
7. [Alternative Headless Coding Agents](#7-alternative-headless-coding-agents)
8. [Comparison Matrix](#8-comparison-matrix)
9. [Sources](#9-sources)

---

## 1. Codex CLI Non-Interactive Mode (`codex exec`)

The `codex exec` (alias `codex e`) subcommand runs Codex without the interactive TUI. It processes a task prompt, executes agent actions, and exits -- suitable for CI/CD pipelines, scripting, and agent-to-agent handoff.

### Basic Syntax

```bash
# Positional prompt
codex exec "Refactor the auth module to use JWT tokens"

# Stdin piping
echo "Fix the failing test in test_auth.py" | codex exec -

# From file
codex exec - < task_description.txt

# With image attachments
codex exec -i screenshot.png "Fix the bug shown in this image"
```

### Output Modes

**Human-readable (default):** Progress streams to stderr, final agent message prints to stdout.

```bash
codex exec "Summarize the codebase" > summary.txt
```

**JSON Lines (`--json`):** Every event emits as JSONL to stdout for programmatic consumption.

```bash
codex exec --json "Diagnose test failures" | jq '.type'
```

Event types: `thread.started`, `turn.started`, `turn.completed`, `turn.failed`, `item.*`, `error`

Sample event:
```json
{"type":"item.completed","item":{"id":"item_3","type":"agent_message","text":"Fixed 3 test failures..."}}
```

**File output (`-o`):** Write only the final message to a file.

```bash
codex exec "Generate release notes" -o release_notes.md
```

**Structured output (`--output-schema`):** Constrain the final response to a JSON Schema for downstream automation.

```bash
codex exec "Extract project metadata" \
  --output-schema ./schema.json \
  -o ./project-metadata.json
```

### Permission Levels

| Mode | Command | Effect |
|------|---------|--------|
| Read-only (default) | `codex exec "task"` | No file writes |
| Edit-enabled | `codex exec --full-auto "task"` | Workspace-write sandbox |
| Unrestricted | `codex exec --sandbox danger-full-access "task"` | Full filesystem access |
| YOLO | `codex exec --yolo "task"` | No approvals, no sandbox |

### Session Management

```bash
# Resume last session with a follow-up
codex exec resume --last "Continue the refactoring"

# Resume by session ID
codex exec resume abc123-def456

# Code review mode
codex exec review --base main "Analyze changes for security issues"
```

### Ephemeral Mode

Skip session file persistence (useful in CI where replay is not needed):

```bash
codex exec --ephemeral "Run linting and fix all issues"
```

### Key Flags Reference

| Flag | Description |
|------|-------------|
| `--json` | JSONL event stream to stdout |
| `-o, --output-last-message PATH` | Write final message to file |
| `--output-schema PATH` | JSON Schema for structured output |
| `--ephemeral` | No session persistence |
| `--full-auto` | Workspace-write + on-request approvals |
| `--yolo` | Bypass all approvals and sandbox |
| `--sandbox MODE` | `read-only` / `workspace-write` / `danger-full-access` |
| `-m, --model MODEL` | Override model (e.g., `o3`, `o4-mini`, `gpt-5`) |
| `--skip-git-repo-check` | Allow execution outside git repos |
| `--color MODE` | `always` / `never` / `auto` |
| `-i, --image PATH` | Attach image(s) to prompt |
| `--enable FEATURE` | Enable feature flag (e.g., `web_search`) |
| `--disable FEATURE` | Disable feature flag |

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `CODEX_API_KEY` | API key (preferred for CI) |
| `OPENAI_API_KEY` | Alternative API key |
| `CODEX_HOME` | Override config directory (default: `~/.codex`) |
| `CODEX_CONFIG` | Override config file path |
| `CODEX_MODEL` | Override model selection |

### Git Requirement

Codex requires a Git repository by default (safety mechanism for destructive changes). Bypass with `--skip-git-repo-check` or `--yolo` in controlled environments.

---

## 2. Passing Context and State to Codex CLI

### Stdin Piping

The `-` argument reads the prompt from stdin, enabling pipe-based context injection:

```bash
# Pipe a complex multi-line prompt
cat <<'EOF' | codex exec --full-auto -
You are continuing work from a previous Claude Code session.

## Context
- Repository: rlm-adk (Google ADK-based agent framework)
- Current task: Implement retry logic for worker dispatch
- Files modified so far: rlm_adk/dispatch.py, rlm_adk/callbacks/worker_retry.py
- Key constraint: Never write ctx.session.state[key] = value in dispatch closures

## Task
Complete the retry logic implementation and add tests.
EOF
```

### AGENTS.md for Repository Context

Codex reads `AGENTS.md` (analogous to Claude's `CLAUDE.md`) from the repository root for persistent context:

```markdown
# AGENTS.md
## Build Commands
- `uv sync` to install dependencies
- `ruff check` for linting

## Architecture
- ADK-based orchestrator with REPLTool
- Worker pool with async dispatch
```

### Working Directory

```bash
# Set working directory explicitly
codex exec --cd /path/to/project "Analyze the codebase"

# Grant additional directory access
codex exec --add-dir /path/to/shared-libs "task"
```

### Structured Input with Images

```bash
codex exec -i error_screenshot.png -i architecture_diagram.png \
  "Fix the error shown in the screenshot, following the architecture diagram"
```

### Multi-Turn Context via Session Resume

```bash
# First turn: establish context
codex exec --full-auto --json "Analyze the test failures in tests_rlm_adk/" \
  | tee first_turn.jsonl

# Extract session/thread ID
THREAD_ID=$(jq -r 'select(.type=="thread.started") | .threadId' first_turn.jsonl)

# Second turn: continue with context preserved
codex exec resume "$THREAD_ID" "Now fix the root cause"
```

---

## 3. Full-Auto and Approval Bypass Modes

### Approval Policy Options

| Policy | Behavior |
|--------|----------|
| `untrusted` | Prompts for every command (default) |
| `on-request` | Prompts only when agent requests |
| `never` | No prompts (for automation) |

### Achieving Full Autonomy

For completely autonomous operation (e.g., CI/CD, agent handoff), you need:

```bash
# Option 1: --full-auto (workspace-write sandbox + on-request approvals)
codex exec --full-auto "task"

# Option 2: --yolo (no sandbox, no approvals -- dangerous)
codex exec --yolo "task"

# Option 3: Explicit flags
codex exec --sandbox danger-full-access -a never "task"
```

### Configuration File (`~/.codex/config.toml`)

```toml
[exec]
approval_policy = "never"
sandbox = "workspace-write"

[exec.full_auto]
full-auto = true
bypass-approvals = true
bypass-sandbox = true
trusted-workspace = true
```

### CI/CD Pattern

```bash
# GitHub Actions example
CODEX_API_KEY=${{ secrets.CODEX_API_KEY }} \
  codex exec --full-auto --json --ephemeral \
  "Run the test suite, fix any failures, and commit the fixes" \
  | jq 'select(.type=="item.completed")'
```

---

## 4. Programmatic Invocation via SDK

### TypeScript SDK

```bash
npm install @openai/codex-sdk
```

```typescript
import { Codex } from "@openai/codex-sdk";

const codex = new Codex();
const thread = codex.startThread();

// First turn
const result = await thread.run(
  "Diagnose and fix the CI failures in the auth module"
);
console.log(result.finalResponse);

// Continue on the same thread (context preserved)
const result2 = await thread.run("Now add tests for the fix");
console.log(result2.finalResponse);

// Resume a previous thread later
const thread2 = codex.resumeThread("<thread-id>");
const result3 = await thread2.run("Pick up where you left off");
```

### Python SDK

```bash
pip install openai-codex-sdk
```

```python
import asyncio
from openai_codex_sdk import Codex

async def main():
    codex = Codex()
    thread = codex.start_thread()

    # Basic run
    turn = await thread.run("Refactor the dispatch module")
    print(turn.final_response)

    # With structured output
    schema = {
        "type": "object",
        "properties": {
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": "string"},
            "tests_passing": {"type": "boolean"}
        },
        "required": ["files_changed", "summary", "tests_passing"]
    }
    turn = await thread.run("Analyze what changed", {"output_schema": schema})
    print(turn.final_response)

    # Streaming events
    async for event in thread.run_streamed("Continue the work"):
        print(event)

asyncio.run(main())
```

**Python SDK Details:**
- Package: `openai-codex-sdk` (v0.1.11, Apache-2.0)
- Requires: Python 3.10+
- Auth: `CODEX_API_KEY` env var or `Codex.login_with_auth_json()`
- Wraps the bundled Codex binary, exchanges JSONL events over stdin/stdout
- Config: `codex_path_override`, `working_directory`, `skip_git_repo_check`, `env`

---

## 5. Codex as MCP Server (Agents SDK Integration)

Codex CLI can run as a Model Context Protocol (MCP) server, exposing itself as a callable tool for the OpenAI Agents SDK. This is the most powerful integration pattern for multi-agent orchestration.

### Starting the MCP Server

```bash
codex mcp-server
```

### MCP Tools Exposed

**`codex` tool** -- Start a new Codex session:

| Property | Type | Purpose |
|----------|------|---------|
| `prompt` | string (required) | Initial task prompt |
| `approval-policy` | string | `untrusted` / `on-request` / `never` |
| `sandbox` | string | `read-only` / `workspace-write` / `danger-full-access` |
| `model` | string | Override model |
| `config` | object | Settings overriding config.toml |
| `base-instructions` | string | Custom system instructions |
| `cwd` | string | Working directory |
| `include-plan-tool` | boolean | Enable planning |

**`codex-reply` tool** -- Continue an existing session:

| Property | Type | Purpose |
|----------|------|---------|
| `prompt` | string (required) | Follow-up message |
| `threadId` | string (required) | Thread ID from prior response |

### Single-Agent Example

```python
import asyncio
from agents import Agent, Runner
from agents.mcp import MCPServerStdio

async def main():
    async with MCPServerStdio(
        name="Codex CLI",
        params={
            "command": "npx",
            "args": ["-y", "codex", "mcp-server"],
        },
        client_session_timeout_seconds=360000,
    ) as codex_mcp_server:

        developer = Agent(
            name="Developer",
            instructions=(
                "You are an expert developer. "
                'Always call codex with '
                '{"approval-policy":"never","sandbox":"workspace-write"}.'
            ),
            mcp_servers=[codex_mcp_server],
        )

        result = await Runner.run(developer, "Fix the auth module tests")
        print(result.final_output)

asyncio.run(main())
```

### Multi-Agent Orchestration Pattern

```python
from agents import Agent, Runner, ModelSettings, Reasoning
from agents.mcp import MCPServerStdio
from agents.tool import WebSearchTool

async def multi_agent_workflow():
    async with MCPServerStdio(
        name="Codex CLI",
        params={"command": "npx", "args": ["-y", "codex", "mcp-server"]},
        client_session_timeout_seconds=360000,
    ) as codex_mcp_server:

        # Specialized agents
        designer = Agent(
            name="Designer",
            instructions="Create design specs. Deliverables: design_spec.md, wireframe.md",
            model="gpt-5",
            tools=[WebSearchTool()],
            mcp_servers=[codex_mcp_server],
            handoffs=[],  # Will be set after PM is defined
        )

        frontend_dev = Agent(
            name="Frontend Developer",
            instructions="Implement UI from design specs.",
            model="gpt-5",
            mcp_servers=[codex_mcp_server],
            handoffs=[],
        )

        backend_dev = Agent(
            name="Backend Developer",
            instructions="Implement APIs and server logic.",
            model="gpt-5",
            mcp_servers=[codex_mcp_server],
            handoffs=[],
        )

        tester = Agent(
            name="Tester",
            instructions="Write and run tests against all deliverables.",
            model="gpt-5",
            mcp_servers=[codex_mcp_server],
            handoffs=[],
        )

        # Project Manager coordinates all agents
        pm = Agent(
            name="Project Manager",
            instructions=(
                "Create REQUIREMENTS.md, AGENT_TASKS.md, TEST.md. "
                "Gate handoffs on file existence checks."
            ),
            model="gpt-5",
            model_settings=ModelSettings(reasoning=Reasoning(effort="medium")),
            handoffs=[designer, frontend_dev, backend_dev, tester],
            mcp_servers=[codex_mcp_server],
        )

        # Bidirectional handoffs back to PM
        designer.handoffs = [pm]
        frontend_dev.handoffs = [pm]
        backend_dev.handoffs = [pm]
        tester.handoffs = [pm]

        result = await Runner.run(pm, "Build a task management app", max_turns=30)
        print(result.final_output)
```

### Tracing

All executions automatically record traces (prompts, responses, tool invocations, handoffs) accessible via the OpenAI Traces dashboard.

---

## 6. Claude Code / Codex CLI Interop & Session Transfer

### `continues` -- Cross-Agent Session Transfer Tool

The [`continues`](https://github.com/yigitkonur/cli-continues) tool enables seamless session handoff between 14 AI coding agents (182 possible cross-tool paths), including Claude Code and Codex CLI.

**Installation:**
```bash
npm install -g continues
# or
npx continues
```

**Session discovery and transfer:**
```bash
# Interactive TUI picker showing all sessions across tools
continues

# Resume latest Claude Code session in Codex
continues resume <session-id> --in codex

# With Codex-specific flags
continues resume <session-id> --in codex --yolo --search

# List Claude Code sessions
continues list --source claude --json

# Inspect a session before transfer
continues inspect <session-id>
```

**How it works:**
1. **Discovery** -- Scans all 14 tool directories for active sessions
2. **Parsing** -- Reads each tool's native format (Claude: JSONL in `~/.claude/projects/`, Codex: JSONL in `~/.codex/sessions/`)
3. **Extraction** -- Retrieves recent messages, file changes, tool activity (bash commands, file edits, grep ops, MCP calls, token usage)
4. **Handoff** -- Generates a structured context document injected into the target tool

**Verbosity presets:**

| Preset | Messages | Tool Samples | Use Case |
|--------|----------|--------------|----------|
| `minimal` | 3 | None | Token-constrained targets |
| `standard` | 10 | 5 | Default balance |
| `verbose` | 20 | 10 | Complex debugging |
| `full` | 50 | All | Complete capture |

### Direct Handoff via Subprocess

Without `continues`, you can manually hand off from Claude Code to Codex:

```bash
# In Claude Code headless mode, generate a handoff document
claude -p "Summarize your work so far as a handoff document for another agent. \
Include: files changed, decisions made, remaining tasks, key constraints." \
  --output-format json | jq -r '.result' > handoff.md

# Pass the handoff to Codex
cat handoff.md | codex exec --full-auto -
```

### Claude Code Headless Mode (for comparison)

Claude Code's headless mode mirrors Codex exec in many ways:

```bash
# Basic headless execution
claude -p "Fix the failing tests" --output-format json

# Multi-turn with session persistence
SESSION_ID=$(claude -p "Analyze the codebase" --output-format json | jq -r '.session_id')
claude -p "Now implement the fix" --resume "$SESSION_ID"

# With tool permissions
claude -p "Run tests and fix failures" \
  --allowedTools "Bash(cmd:pytest*)" "Read" "Edit"
```

---

## 7. Alternative Headless Coding Agents

### Aider

**Non-interactive mode:**
```bash
# Single-shot task execution
aider --message "Add docstrings to all functions" --yes myfile.py

# Batch processing
for FILE in *.py; do
    aider --message "Add type hints to all functions" --yes "$FILE"
done

# From file
aider --message-file task.txt --yes --no-auto-commits src/
```

**Python API (unofficial):**
```python
from aider.coders import Coder
from aider.models import Model
from aider.io import InputOutput

io = InputOutput(yes=True)  # Auto-approve all confirmations
model = Model("gpt-4-turbo")
coder = Coder.create(main_model=model, fnames=["src/auth.py"], io=io)
coder.run("Implement JWT token validation")
coder.run("Add unit tests for the validation logic")
```

**Key flags for automation:**

| Flag | Purpose |
|------|---------|
| `--message/-m` | Single instruction, then exit |
| `--message-file/-f` | Read instruction from file |
| `--yes` | Auto-approve all confirmations |
| `--no-auto-commits` | Disable automatic git commits |
| `--dry-run` | Preview without modifying files |
| `--commit` | Commit pending changes, then exit |

**Environment variables:** `AIDER_MESSAGE`, `AIDER_YES`, `AIDER_AUTO_COMMITS`

### Gemini CLI

**Headless mode:**
```bash
# Basic headless execution
gemini -p "Analyze the test failures and suggest fixes"

# JSON output for programmatic parsing
gemini -p "Summarize the codebase" --json

# Piped input
echo "Fix the linting errors" | gemini -p -
```

- Free tier: Gemini 2.5 Pro, 1M token context, 60 requests/min, 1000/day
- Reads `GEMINI.md` from repo root for context (analogous to `CLAUDE.md` / `AGENTS.md`)

### Continue CLI (`cn`)

**Headless mode:**
```bash
# Headless execution (final response only)
cn -p "Review this PR for security issues"

# CI authentication
CONTINUE_API_KEY=<key> cn -p "Run code quality checks"
```

- Runs async agents on PRs with source-controlled checks
- Headless mode outputs only the final response (Unix-philosophy friendly)
- Cloud-based agent execution for CI/CD

### Claude Code

**Headless mode:**
```bash
# Single prompt, exit after response
claude -p "Fix the auth module" --output-format json

# Streaming JSON
claude -p "Refactor dispatch.py" --output-format stream-json

# Multi-turn session
claude -p "Step 1" --session-id my-session --output-format json
claude -p "Step 2" --resume my-session --output-format json

# Tool permissions for full autonomy
claude -p "Run tests and fix failures" \
  --allowedTools "Bash(cmd:*)" "Read" "Edit" "Write" \
  --no-user-prompt
```

---

## 8. Comparison Matrix

| Feature | Codex CLI | Claude Code | Aider | Gemini CLI | Continue CLI |
|---------|-----------|-------------|-------|------------|--------------|
| **Headless flag** | `codex exec` | `-p` / `--print` | `--message` | `-p` / `--prompt` | `-p` |
| **JSON output** | `--json` (JSONL) | `--output-format json` | N/A | `--json` | N/A |
| **Structured output** | `--output-schema` | N/A | N/A | N/A | N/A |
| **Session resume** | `codex exec resume` | `--resume SESSION` | N/A | N/A | N/A |
| **Full autonomy** | `--full-auto` / `--yolo` | `--allowedTools` | `--yes` | N/A | `CONTINUE_API_KEY` |
| **Stdin piping** | `codex exec -` | Pipe to `-p` | `--message-file` | Pipe to `-p` | N/A |
| **SDK (programmatic)** | TS + Python SDK | Claude SDK (TS) | Python API (unofficial) | N/A | N/A |
| **MCP server mode** | `codex mcp-server` | N/A | N/A | N/A | N/A |
| **Multi-agent orchestration** | Agents SDK + MCP | Subagents / Agent teams | N/A | N/A | N/A |
| **Sandbox levels** | read-only / workspace-write / full | Bash permissions | Git-based | N/A | N/A |
| **Context file** | `AGENTS.md` | `CLAUDE.md` | `.aider*` config | `GEMINI.md` | `.continue/` |
| **Cross-agent transfer** | via `continues` | via `continues` | via `continues` | via `continues` | N/A |
| **Open source** | Yes (Apache-2.0) | No | Yes (Apache-2.0) | Yes (Apache-2.0) | Yes |
| **Default model** | o3 / gpt-5 | Claude Sonnet/Opus | Configurable | Gemini 2.5 Pro | Configurable |

---

## 9. Sources

- [Codex CLI Non-Interactive Mode](https://developers.openai.com/codex/noninteractive/)
- [Codex CLI Command Line Reference](https://developers.openai.com/codex/cli/reference)
- [Codex CLI Features](https://developers.openai.com/codex/cli/features)
- [Codex CLI Overview](https://developers.openai.com/codex/cli/)
- [Codex SDK Documentation](https://developers.openai.com/codex/sdk)
- [openai-codex-sdk on PyPI](https://pypi.org/project/openai-codex-sdk/)
- [Use Codex with the Agents SDK](https://developers.openai.com/codex/guides/agents-sdk/)
- [Building Consistent Workflows with Codex CLI & Agents SDK (Cookbook)](https://developers.openai.com/cookbook/examples/codex/codex_mcp_agents_sdk/building_consistent_workflows_codex_cli_agents_sdk)
- [Codex Configuration Reference](https://developers.openai.com/codex/config-reference/)
- [Codex Advanced Configuration](https://developers.openai.com/codex/config-advanced/)
- [Headless Execution Mode - DeepWiki](https://deepwiki.com/openai/codex/4.2-headless-execution-mode-(codex-exec))
- [GitHub: openai/codex](https://github.com/openai/codex)
- [GitHub: Headless Mode Issue #4219](https://github.com/openai/codex/issues/4219)
- [continues -- Cross-Agent Session Transfer](https://github.com/yigitkonur/cli-continues)
- [Claude Code with Codex (ShakaCode)](https://github.com/shakacode/claude-code-commands-skills-agents/blob/main/docs/claude-code-with-codex.md)
- [Claude Code Headless Mode](https://code.claude.com/docs/en/headless)
- [Aider Scripting](https://aider.chat/docs/scripting.html)
- [Gemini CLI Headless Mode](https://google-gemini.github.io/gemini-cli/docs/cli/headless.html)
- [Continue CLI Guide](https://docs.continue.dev/guides/cli)
- [Continue Blog: Building Cloud Agents](https://blog.continue.dev/building-async-agents-with-continue-cli)
- [GitHub: Pick Your Agent (Claude + Codex on Agent HQ)](https://github.blog/news-insights/company-news/pick-your-agent-use-claude-and-codex-on-agent-hq/)
