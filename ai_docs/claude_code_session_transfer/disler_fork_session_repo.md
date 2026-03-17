# Disler Fork Terminal Skill - Research Document

## Repository

- **URL**: https://github.com/disler/fork-repository-skill
- **Author**: Dan Disler (IndyDevDan) - https://github.com/disler
- **Created**: 2025-11-24
- **Last Updated**: 2026-03-13
- **Stars**: 138 | **Forks**: 73
- **Description**: "Take your current agent running in your terminal and fork it N times to smoothly branch your engineering work."
- **YouTube Tutorial**: https://youtu.be/X2ciJedw2vU (builds the skill from scratch)
- **YouTube Channel**: https://www.youtube.com/@indydevdan

---

## What It Does

A Claude Code **skill** (not a slash command, not an MCP server) that enables an AI agent to spawn new terminal windows on demand. The spawned terminals can run:

1. **Claude Code** (another instance)
2. **Codex CLI** (OpenAI)
3. **Gemini CLI** (Google)
4. **Raw CLI commands** (arbitrary)

Key use cases:
- **Delegate/offload context** to a parallel agent
- **Branch engineering work** into parallel streams
- **Race multiple agents** on the same task (Claude vs Codex vs Gemini)
- **Context handoff** - summarize current conversation and pass it to the forked agent

---

## Architecture

```
.claude/skills/fork-terminal/
├── SKILL.md                              # Skill definition, triggers, workflow
├── cookbook/
│   ├── cli-command.md                    # Raw CLI instructions
│   ├── claude-code.md                    # Claude Code agent config
│   ├── codex-cli.md                      # Codex CLI config
│   └── gemini-cli.md                     # Gemini CLI config
├── prompts/
│   └── fork_summary_user_prompt.md       # Template for context handoff
└── tools/
    └── fork_terminal.py                  # Cross-platform terminal spawner (Python)
```

---

## How It Works

### 1. Skill Discovery (Automatic)

Unlike slash commands which require explicit `/command` invocation, Claude Code skills are **automatically discovered** when user requests match the skill's description. The `SKILL.md` frontmatter defines triggers:

```yaml
---
name: Fork Terminal Skill
description: Fork a terminal session to a new terminal window. Use this when the user
  requests 'fork terminal' or 'create a new terminal' or 'new terminal: <command>'
  or 'fork session: <command>'.
---
```

When a user says "fork terminal use claude code to analyze this file", Claude automatically detects the matching skill, reads the SKILL.md instructions, and executes the workflow.

### 2. Cookbook Selection

Based on the user's request, Claude selects the appropriate cookbook file. Each cookbook defines:
- **Model defaults**: DEFAULT_MODEL, HEAVY_MODEL, BASE_MODEL, FAST_MODEL
- **CLI flags**: interactive mode, permission bypasses, model arguments

**Claude Code cookbook** (`claude-code.md`):
```markdown
## Variables
DEFAULT_MODEL: opus
HEAVY_MODEL: opus
BASE_MODEL: sonnet
FAST_MODEL: haiku

## Instructions
- Always use interactive mode (so leave off -p)
- For the --model argument, use the DEFAULT_MODEL if not specified.
  If 'fast' is requested, use FAST_MODEL. If 'heavy' is requested, use HEAVY_MODEL.
- Always run with `--dangerously-skip-permissions`
```

**Codex CLI cookbook** (`codex-cli.md`):
```markdown
## Variables
DEFAULT_MODEL: gpt-5.1-codex-max
FAST_MODEL: gpt-5.1-codex-mini

## Instructions
- Always use interactive mode (leave off -p, use positional prompt if needed)
- Always run with `--dangerously-bypass-approvals-and-sandbox`
```

**Gemini CLI cookbook** (`gemini-cli.md`):
```markdown
## Variables
DEFAULT_MODEL: gemini-3-pro-preview
FAST_MODEL: gemini-2.5-flash

## Instructions
- Always use interactive mode with -i flag as the last flag
- Always run with `--yolo` (or `-y` for short)
```

### 3. Terminal Spawning (fork_terminal.py)

The core Python tool that opens a new OS terminal window:

```python
#!/usr/bin/env -S uv run
"""Fork a new terminal window with a command."""

import os
import platform
import subprocess


def fork_terminal(command: str) -> str:
    """Open a new Terminal window and run the specified command."""
    system = platform.system()
    cwd = os.getcwd()

    if system == "Darwin":  # macOS
        shell_command = f"cd '{cwd}' && {command}"
        escaped_shell_command = shell_command.replace("\\", "\\\\").replace('"', '\\"')
        try:
            result = subprocess.run(
                ["osascript", "-e",
                 f'tell application "Terminal" to do script "{escaped_shell_command}"'],
                capture_output=True, text=True,
            )
            output = (f"stdout: {result.stdout.strip()}\n"
                      f"stderr: {result.stderr.strip()}\n"
                      f"return_code: {result.returncode}")
            return output
        except Exception as e:
            return f"Error: {str(e)}"

    elif system == "Windows":
        full_command = f'cd /d "{cwd}" && {command}'
        subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", full_command], shell=True)
        return "Windows terminal launched"

    else:  # Linux
        raise NotImplementedError(f"Platform {system} not supported")
```

**Key detail**: On macOS it uses AppleScript to tell Terminal.app to open a new window and run the command. On Windows it uses `cmd /k` via `start`. Linux is **not yet implemented**.

### 4. Context Handoff (Summary Mode)

When the user says "summarize work so far", the skill reads a prompt template and fills it with conversation history:

```markdown
# Prompt

## History
<fill_in_conversation_summary_here>
```yaml
- history:
    - user_prompt: <user prompt summary>
      agent_response: <agent response summary>
```
</fill_in_conversation_summary_here>

## Next User Request
<fill_in_next_user_request_here>
  <user prompt here exactly as it was requested>
</fill_in_next_user_request_here>
```

**Important**: The SKILL.md explicitly says "don't update the file directly, just read it, fill it out IN YOUR MEMORY and use it to craft a new prompt." The template is a structural guide, not a file to write to.

---

## Supported Tools and Model Tiers

| Tool | Trigger | Default | Fast | Heavy |
|------|---------|---------|------|-------|
| Claude Code | "fork terminal use claude code to..." | opus | haiku | opus |
| Codex CLI | "fork terminal use codex to..." | gpt-5.1-codex-max | gpt-5.1-codex-mini | gpt-5.1-codex-max |
| Gemini CLI | "fork terminal use gemini to..." | gemini-3-pro-preview | gemini-2.5-flash | gemini-3-pro-preview |
| Raw CLI | "fork terminal run..." | N/A | N/A | N/A |

---

## Platform Support

| Platform | Status | Method |
|----------|--------|--------|
| macOS | Supported | AppleScript -> Terminal.app |
| Windows | Supported | `cmd /k` via `start` |
| Linux | **Not implemented** | -- |

---

## Installation

Copy `.claude/skills/fork-terminal/` to either:
- Project-specific: `<project>/.claude/skills/fork-terminal/`
- Global (all projects): `~/.claude/skills/fork-terminal/`

No dependencies beyond Python stdlib. The shebang `#!/usr/bin/env -S uv run` means `uv` will handle execution.

---

## Usage Examples

```
# Basic fork to Claude Code
"fork terminal use claude code to analyze SKILL.md and write a summary"

# Fast model for quick tasks
"fork terminal use claude code fast to fix the typo in utils.py"

# Fork to Codex CLI
"fork terminal use codex to write tests for the API"

# Raw CLI command
"new terminal: npm run dev"

# Context handoff (conversation summary passed to new agent)
"fork terminal use claude code to implement the feature we discussed, summarize work so far"

# Multi-agent race
"fork three terminals: claude code, codex, and gemini - each should read README.md
 and write improvement suggestions"
```

---

## Adaptation for Session Transfer to Codex CLI

### What This Skill Does Well

1. **Terminal spawning**: OS-native new terminal window creation
2. **CLI construction**: Builds the right command line for each agent tool
3. **Context handoff via prompt template**: Summarizes conversation history into a structured prompt for the forked agent

### What It Does NOT Do

1. **No programmatic session state transfer** - Context is passed as a natural language summary in the prompt, not as structured session data (files modified, git state, tool outputs, etc.)
2. **No shared state** - The forked agent starts fresh with only the prompt summary
3. **No return channel** - No mechanism for the forked agent to report results back to the parent
4. **No Linux support** - Would need `gnome-terminal`, `xterm`, `tmux`, or similar

### Adaptation Strategy for RLM-ADK Session Transfer to Codex

To build a more robust session transfer mechanism, consider these enhancements:

#### 1. Structured State Export (Beyond Natural Language Summary)

Instead of just a conversation summary, export structured context:

```python
session_state = {
    "files_modified": [...],          # From git diff
    "current_branch": "...",          # From git status
    "task_description": "...",        # Original user intent
    "progress_summary": "...",        # What's been done
    "remaining_work": "...",          # What's left
    "key_decisions": [...],           # Architectural decisions made
    "relevant_files": [...],          # Files the next agent should read
    "environment": {...},             # Env vars, tool versions
}
```

#### 2. File-Based Handoff Protocol

Write a handoff file that Codex CLI can consume:

```python
# Write structured handoff to a known location
handoff_path = ".claude/handoff/session_transfer.md"
# Codex CLI reads this via its system prompt or initial instructions
```

#### 3. Linux Terminal Spawning

Add Linux support to `fork_terminal.py`:

```python
elif system == "Linux":
    # Option A: tmux (best for headless/SSH)
    if shutil.which("tmux"):
        subprocess.run(["tmux", "new-window", "-n", "fork", shell_command])
    # Option B: gnome-terminal
    elif shutil.which("gnome-terminal"):
        subprocess.run(["gnome-terminal", "--", "bash", "-c", shell_command])
    # Option C: xterm fallback
    elif shutil.which("xterm"):
        subprocess.Popen(["xterm", "-e", shell_command])
```

#### 4. Bidirectional Communication

For a return channel from the forked agent:

```python
# Parent writes task + expects result at known path
result_path = f".claude/handoff/result_{task_id}.md"
# Poll or use inotify/fswatch for completion
```

#### 5. Codex CLI Specific Flags

From the codex-cli cookbook, the key flags for non-interactive Codex execution:

```bash
codex -m gpt-5.1-codex-max --dangerously-bypass-approvals-and-sandbox "prompt here"
```

For programmatic (non-interactive) handoff, use `-p` (pipe mode) instead of interactive mode, contrary to the skill's default which uses interactive mode.

### Key Takeaway

Disler's skill is a **UX-level fork** (spawn a new terminal for a human to watch), not a **programmatic session transfer**. For RLM-ADK's needs, the valuable patterns are:

1. The **skill-based auto-discovery** pattern (SKILL.md frontmatter)
2. The **cookbook pattern** for per-tool configuration
3. The **prompt template** approach for context handoff
4. The **OS-level terminal spawning** code (needs Linux extension)

But a true session transfer would need structured state export, a file-based handoff protocol, and ideally a return channel - none of which exist in this skill today.

---

## Related Resources

- [Claude Code Skills Documentation](https://code.claude.com/docs/en/skills)
- [IndyDevDan YouTube Channel](https://www.youtube.com/@indydevdan)
- [Build Video (YouTube)](https://youtu.be/X2ciJedw2vU)
- [Awesome Claude Code Skills](https://github.com/hesreallyhim/awesome-claude-code)
- [Awesome Agent Skills (VoltAgent)](https://github.com/VoltAgent/awesome-agent-skills)
- [Tactical Agentic Coding Course](https://agenticengineer.com/tactical-agentic-coding)
- [MCP Market - Fork Terminal](https://mcpmarket.com/tools/skills/fork-terminal)
