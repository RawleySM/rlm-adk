# OpenAI Codex CLI Documentation

> **Sources**:
> - https://github.com/openai/codex (README)
> - https://developers.openai.com/codex/cli (CLI Overview)
> - https://developers.openai.com/codex/cli/reference (CLI Reference)
> - https://developers.openai.com/codex/cli/features (CLI Features)
> - https://developers.openai.com/codex/cli/slash-commands (Slash Commands)
>
> **Fetched**: 2026-03-26

---

## Overview

Codex CLI is OpenAI's coding agent that runs locally from your terminal. It is open-source (Apache-2.0), built in Rust, and enables developers to read, change, and run code within selected directories. It operates with code execution in sandboxed environments with network isolation.

The GitHub repo is at https://github.com/openai/codex.

**Note**: The repo README covers a legacy TypeScript version; the current production version is written in Rust.

---

## Installation

### Package Manager

```shell
# Install using npm
npm install -g @openai/codex

# Install using Homebrew
brew install --cask codex
```

### GitHub Releases

Download platform-specific binaries from https://github.com/openai/codex/releases/latest:

- **macOS**:
  - Apple Silicon/arm64: `codex-aarch64-apple-darwin.tar.gz`
  - x86_64 (older Mac hardware): `codex-x86_64-apple-darwin.tar.gz`
- **Linux**:
  - x86_64: `codex-x86_64-unknown-linux-musl.tar.gz`
  - arm64: `codex-aarch64-unknown-linux-musl.tar.gz`

Each archive contains a single entry with the platform baked into the name (e.g., `codex-x86_64-unknown-linux-musl`), so rename it to `codex` after extracting.

### Upgrade

```shell
npm i -g @openai/codex@latest
```

### System Requirements

- macOS 12+, Ubuntu 20.04+/Debian 10+, or Windows 11 via WSL2
- Node.js 16+ (version 20 LTS recommended)
- 4GB RAM minimum

---

## Authentication

### ChatGPT Account

Run `codex` and select **Sign in with ChatGPT**. Included with ChatGPT Plus, Pro, Team, Business, Edu, and Enterprise plans.

### API Key

```shell
# Interactive API key login
codex login --with-api-key

# Check login status (exit 0 if logged in)
codex login status

# OAuth device code flow
codex login --device-auth

# Logout
codex logout
```

---

## Supported Platforms

- macOS (native)
- Linux (native)
- Windows 11 via WSL2 (experimental)

---

## Global Flags

These flags apply to the base `codex` command and all subcommands:

| Flag | Type | Description |
|------|------|-------------|
| `--add-dir` | path | Grant write access to additional directories alongside the workspace (repeatable) |
| `--ask-for-approval, -a` | `untrusted \| on-request \| never` | Control approval prompts before command execution |
| `--cd, -C` | path | Set working directory before processing requests |
| `--config, -c` | key=value | Override configuration values (repeatable) |
| `--dangerously-bypass-approvals-and-sandbox, --yolo` | boolean | Run commands without approvals or sandboxing (high-risk) |
| `--disable` | feature | Force-disable a feature flag (repeatable) |
| `--enable` | feature | Force-enable a feature flag (repeatable) |
| `--full-auto` | boolean | Preset for low-friction work: `on-request` approvals and `workspace-write` sandbox |
| `--image, -i` | path[,path...] | Attach image files to initial prompt |
| `--model, -m` | string | Override configured model |
| `--no-alt-screen` | boolean | Disable alternate screen mode for TUI |
| `--oss` | boolean | Use local open source provider (requires Ollama) |
| `--profile, -p` | string | Load configuration profile from `~/.codex/config.toml` |
| `--sandbox, -s` | `read-only \| workspace-write \| danger-full-access` | Set sandbox policy for generated commands |
| `--search` | boolean | Enable live web search instead of cached results |
| `PROMPT` | string | Optional initial instruction (omit to launch TUI) |

---

## Command Reference

### All Commands

| Command | Maturity | Purpose |
|---------|----------|---------|
| `codex` | Stable | Launch interactive terminal UI |
| `codex app` | Stable | Launch Codex desktop app (macOS only) |
| `codex app-server` | Experimental | Start app server for development |
| `codex apply` | Stable | Apply Cloud task diffs locally (alias: `a`) |
| `codex cloud` | Experimental | Manage Cloud tasks from terminal (alias: `cloud-tasks`) |
| `codex completion` | Stable | Generate shell completion scripts |
| `codex debug app-server send-message-v2` | Experimental | Debug app-server message flow |
| `codex exec` | Stable | Run non-interactively (alias: `e`) |
| `codex execpolicy` | Experimental | Evaluate execution policy rules |
| `codex features` | Stable | Manage feature flags |
| `codex fork` | Stable | Fork previous interactive session |
| `codex login` | Stable | Authenticate via OAuth or API key |
| `codex logout` | Stable | Remove stored credentials |
| `codex mcp` | Experimental | Manage Model Context Protocol servers |
| `codex mcp-server` | Experimental | Run Codex as MCP server |
| `codex resume` | Stable | Continue previous session |
| `codex sandbox` | Experimental | Run commands in isolated sandbox |

---

## Non-Interactive Mode: `codex exec`

The `codex exec` command (alias `codex e`) runs tasks without human interaction. This is the primary mechanism for scripting, CI workflows, and headless operation.

### Flags

| Flag | Type | Description |
|------|------|-------------|
| `--cd, -C` | path | Set workspace root |
| `--color` | `always \| never \| auto` | Control ANSI colors |
| `--dangerously-bypass-approvals-and-sandbox, --yolo` | boolean | Bypass protections (dangerous) |
| `--ephemeral` | boolean | Skip persisting session files |
| `--full-auto` | boolean | Apply low-friction preset |
| `--image, -i` | path[,path...] | Attach images (repeatable) |
| `--json, --experimental-json` | boolean | Output newline-delimited JSON events |
| `--model, -m` | string | Override configured model |
| `--oss` | boolean | Use local open source provider |
| `--output-last-message, -o` | path | Write final message to file |
| `--output-schema` | path | JSON Schema for response validation |
| `--profile, -p` | string | Select configuration profile |
| `--sandbox, -s` | `read-only \| workspace-write \| danger-full-access` | Set sandbox policy |
| `--skip-git-repo-check` | boolean | Allow running outside Git repositories |
| `-c, --config` | key=value | Inline configuration override |
| `PROMPT` | string or `-` | Task instruction (use `-` for stdin) |

### Usage Examples

```shell
# Basic non-interactive execution
codex exec "fix the CI failure"

# Read prompt from stdin
echo "explain this codebase" | codex exec -

# Full auto with JSON output for CI
codex exec --full-auto --json "run tests and report" > output.jsonl

# Save final message to file
codex exec -o result.txt "summarize the README"

# With structured output validation
codex exec --output-schema schema.json "extract API endpoints"

# Ephemeral (no session persistence)
codex exec --ephemeral "one-off task"
```

### Resume from exec

```shell
codex exec resume [SESSION_ID]
codex exec resume --all          # Search sessions across directories
codex exec resume --last         # Continue most recent session
codex exec resume --last "Fix race conditions"  # With follow-up prompt
codex exec resume --last --image screenshot.png  # With image
```

---

## Interactive Mode

Running `codex` without arguments launches a full-screen terminal UI.

### Key Capabilities

- Send prompts, code snippets, or screenshots directly into the composer
- Review Codex's plan before changes and approve/reject steps inline
- View syntax-highlighted markdown and diffs in the terminal
- Navigate draft history with Up/Down arrows
- Press `Ctrl+G` to open external editor (uses `VISUAL` or `EDITOR` env var)
- Type `@` to fuzzy-search workspace files
- Press Enter during execution to inject instructions
- Prefix lines with `!` to run local shell commands
- Press Esc twice to edit previous messages

### Launch with prompt

```shell
codex "Explain this codebase to me"
```

### Exit

- `Ctrl+C` or `/exit` or `/quit`

---

## Approval Modes

Control what Codex can do without asking:

| Mode | Description | Flag |
|------|-------------|------|
| **Auto** (default) | Read files, edit, and run commands within working directory; prompts for network access | `-a on-request` |
| **Read-only** | Browse files without making changes | Built-in via `/permissions` |
| **Full Access** | Work across machine with network access without confirmation | `-a never` |
| **Untrusted** | Prompt for everything | `-a untrusted` |

Configure mid-session via `/permissions` slash command.

---

## Sandbox Policies

Control file system and network access:

| Policy | Description |
|--------|-------------|
| `read-only` | No writes allowed |
| `workspace-write` | Write only within workspace directory |
| `danger-full-access` | Unrestricted file system access |

### Platform-Specific Sandboxing

- **macOS**: Apple Seatbelt
- **Linux**: Docker containerization with firewall rules (Landlock also available)
- Network access is disabled by default across all platforms

### Selective Access

Use `--add-dir` to grant write access to specific additional directories without opening full access:

```shell
codex --add-dir /tmp/build --sandbox workspace-write "build the project"
```

### Run arbitrary commands in sandbox

```shell
# macOS (Seatbelt)
codex sandbox [--config key=value] [--full-auto] -- COMMAND

# Linux (Landlock)
codex sandbox [--config key=value] [--full-auto] -- COMMAND
```

---

## Configuration

### Config File

Configuration lives at `~/.codex/config.toml`. Supports YAML or JSON as well.

### Profiles

Load named profiles:

```shell
codex --profile my-profile "task"
```

### Inline Overrides

```shell
codex -c model=gpt-5.4 -c sandbox=workspace-write "task"
```

### Configuration Precedence

Command-line overrides take precedence over `~/.codex/config.toml` defaults and profile settings.

---

## Models and Reasoning

GPT-5.4 is the recommended model. ChatGPT Pro subscribers access GPT-5.3-Codex-Spark in research preview.

Switch models:
- At launch: `codex --model gpt-5.4`
- Mid-session: `/model` command

---

## AGENTS.md

Codex supports project-level instructions via `AGENTS.md` files in the repository root. Generate a scaffold with:

```shell
codex /init
```

This creates an `AGENTS.md` file you can refine and commit.

---

## Session Management

### Resume

```shell
codex resume              # Picker of recent sessions
codex resume --all        # Sessions beyond current directory
codex resume --last       # Most recent session
codex resume <SESSION_ID> # Specific session
```

### Fork

Clone current conversation into a new thread:

```shell
codex fork              # Picker
codex fork --all        # Show all directories
codex fork --last       # Fork most recent
codex fork <SESSION_ID> # Specific session
```

---

## Image Input

```shell
codex -i screenshot.png "Explain this error"
codex --image img1.png,img2.jpg "Summarize these diagrams"
```

Supports PNG and JPEG formats.

---

## Web Search

Codex ships with a first-party web search tool, enabled by default for local tasks, serving cached results from OpenAI-maintained indexes.

- Live results: `--search` flag or `web_search = "live"` in config
- Disable: `web_search = "disabled"` in config

---

## MCP (Model Context Protocol) Integration

Connect additional tools by configuring MCP servers:

```shell
# Add stdio server
codex mcp add my-server -- node server.js

# Add HTTP server
codex mcp add my-server --url http://localhost:3000

# With environment variables
codex mcp add my-server --env API_KEY=xxx -- node server.js

# With bearer token
codex mcp add my-server --bearer-token-env-var MY_TOKEN --url http://localhost:3000

# List servers
codex mcp list
codex mcp list --json

# Show configuration
codex mcp get my-server

# OAuth login
codex mcp login my-server --scopes scope1,scope2

# Remove
codex mcp remove my-server
```

Codex auto-launches configured servers and exposes their tools alongside built-ins.

### Run Codex as MCP Server

```shell
codex mcp-server
```

---

## Cloud Tasks

Interact with Codex Cloud from terminal:

```shell
# Execute cloud task
codex cloud exec --env ENV_ID "Summarize open bugs"

# With multiple attempts (best-of-N)
codex cloud exec --env ENV_ID --attempts 3 "task"

# List recent tasks
codex cloud list
codex cloud list --env ENV_ID --json --limit 10

# Apply cloud task diffs locally
codex apply TASK_ID
```

---

## Feature Flags

```shell
codex features list                    # Show flags and maturity stages
codex features enable unified_exec     # Persistently enable
codex features disable shell_snapshot  # Persistently disable
```

Changes persist to `~/.codex/config.toml` or profile-specific configuration.

Can also use CLI flags:

```shell
codex --enable unified_exec --disable shell_snapshot "task"
```

---

## Shell Completions

```shell
codex completion bash
codex completion zsh
codex completion fish
codex completion power-shell
codex completion elvish

# Install for zsh
eval "$(codex completion zsh)"
```

---

## Execution Policy

Evaluate execution policy rules before saving:

```shell
codex execpolicy --rules policy.json --pretty COMMAND...
```

| Flag | Description |
|------|-------------|
| `--rules, -r` | Policy rule file (repeatable) |
| `--pretty` | Pretty-print JSON output |
| `COMMAND...` | Command to evaluate |

---

## Subagents

Codex can parallelize larger tasks using subagent workflows. Subagents spawn only upon explicit request and consume additional tokens compared to single-agent runs.

View subagent work with `/agent` slash command.

---

## Code Review

Type `/review` to open review presets:

- **Review against base branch**: Diffs work against upstream
- **Review uncommitted changes**: Inspects staged, unstaged, or untracked files
- **Review a commit**: Analyzes specific SHA changesets
- **Custom review instructions**: Apply personalized prompts

Uses current session model by default; override with `review_model` in config.

---

## Slash Commands Reference

Access slash commands by typing `/` in the composer during interactive mode.

### Model and Performance Control

| Command | Purpose |
|---------|---------|
| `/model` | Switch between available models (e.g., `gpt-4.1-mini`, `gpt-4.1`, `gpt-5.4`) |
| `/fast` | Toggle Fast mode for GPT-5.4 (`/fast on`, `/fast off`, `/fast status`) |

### Session Management

| Command | Purpose |
|---------|---------|
| `/clear` | Reset terminal and start fresh conversation |
| `/new` | Start new conversation within same CLI session (preserves terminal view) |
| `/resume` | Reload saved conversation from session list |
| `/fork` | Clone current conversation into new thread with fresh ID |
| `/quit` / `/exit` | Exit the CLI immediately |

### Configuration and Permissions

| Command | Purpose |
|---------|---------|
| `/permissions` | Adjust approval requirements (Auto, Read Only, Full Access) mid-session |
| `/personality` | Choose communication style (friendly, pragmatic, none) |
| `/sandbox-add-read-dir` | Grant read access to directories (Windows only) |
| `/experimental` | Toggle experimental features like Apps or Smart Approvals |

### Information and Inspection

| Command | Purpose |
|---------|---------|
| `/status` | Display active model, approval policy, token usage |
| `/debug-config` | Print config layer diagnostics and precedence |
| `/diff` | Show Git diff including untracked files |
| `/mcp` | List available Model Context Protocol tools |
| `/ps` | Show background terminal status and recent output |

### Content and Workflow

| Command | Purpose |
|---------|---------|
| `/copy` | Copy latest completed Codex output to clipboard |
| `/mention` | Attach files to conversation (`/mention src/lib/api.ts`) |
| `/compact` | Summarize visible conversation to free tokens |
| `/review` | Request working tree analysis |

### Planning and Execution

| Command | Purpose |
|---------|---------|
| `/plan` | Switch to plan mode with optional inline prompt (`/plan Propose a migration strategy`) |

### File and Repository

| Command | Purpose |
|---------|---------|
| `/init` | Generate `AGENTS.md` scaffold in current directory |

### Agent and App Management

| Command | Purpose |
|---------|---------|
| `/agent` | Switch active agent thread to inspect subagent work |
| `/apps` | Browse and insert apps into prompt (inserts as `$app-slug`) |

### Account and Debugging

| Command | Purpose |
|---------|---------|
| `/logout` | Clear local credentials for current user |
| `/feedback` | Submit logs and diagnostics to maintainers |
| `/statusline` | Configure footer status-line items (toggle and reorder: model, context, git, tokens, etc.) |

---

## Syntax Highlighting and Themes

The TUI syntax-highlights markdown code blocks and diffs.

```shell
/theme          # Preview and save theme selection
```

Custom `.tmTheme` files can be added to `$CODEX_HOME/themes`.

---

## Safety Guidelines

- Combine `--full-auto` with `--dangerously-bypass-approvals-and-sandbox` only in dedicated sandbox VMs
- Prefer `--add-dir` over `--sandbox danger-full-access` for selective access
- Pair `--json` with `--output-last-message` in CI workflows
- Avoid `--yolo` flag in untrusted execution environments

---

## CI/Scripting Patterns

### Basic CI Usage

```shell
# Non-interactive with full auto and JSON output
codex exec --full-auto --json "run the test suite" > results.jsonl

# Save just the final message
codex exec --full-auto -o summary.txt "analyze code quality"

# Read prompt from stdin (pipe)
cat instructions.txt | codex exec -

# With structured output
codex exec --output-schema response-schema.json "extract all TODO items"
```

### Headless/Unattended

```shell
# Full auto bypasses most approval prompts
codex exec --full-auto "fix linting errors"

# YOLO mode for fully trusted environments only
codex exec --yolo "refactor the auth module"

# Ephemeral (no session files written)
codex exec --ephemeral --full-auto "one-off analysis"
```

---

## Environment Variables

- `VISUAL` / `EDITOR` - External editor for prompt editing (`Ctrl+G`)
- `CODEX_HOME` - Custom config/themes directory
- API keys configured via `codex login` or environment variables

---

## App Server (Experimental)

```shell
# Launch with stdio transport
codex app-server --listen stdio://

# Launch with WebSocket transport
codex app-server --listen ws://127.0.0.1:8080
```

### Debug

```shell
codex debug app-server send-message-v2 "test message"
```

---

## Desktop App (macOS)

```shell
codex app              # Launch desktop app
codex app /path/to/dir # Open specific workspace
codex app --download-url https://custom-url/codex.dmg  # Custom DMG
```
