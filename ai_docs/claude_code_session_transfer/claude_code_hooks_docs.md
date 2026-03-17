# Claude Code Hooks & Session Management Research

> Compiled 2026-03-13 from official Claude Code documentation at code.claude.com/docs

---

## Table of Contents

1. [Hook System Overview](#1-hook-system-overview)
2. [Hook Types](#2-hook-types)
3. [Hook Events Reference](#3-hook-events-reference)
4. [Configuration & Placement](#4-configuration--placement)
5. [Hook Input/Output Protocol](#5-hook-inputoutput-protocol)
6. [Context Window Monitoring](#6-context-window-monitoring)
7. [Session Management & Transfer](#7-session-management--transfer)
8. [Detecting Session Limit / Remaining Context](#8-detecting-session-limit--remaining-context)
9. [Practical Recipes](#9-practical-recipes)
10. [Environment Variables Reference](#10-environment-variables-reference)
11. [Limitations & Gaps](#11-limitations--gaps)

---

## 1. Hook System Overview

Hooks are user-defined shell commands, HTTP endpoints, or LLM prompts that execute automatically at specific points in Claude Code's lifecycle. They provide **deterministic control** over Claude Code's behavior, ensuring certain actions always happen rather than relying on the LLM to choose to run them.

### Lifecycle Flow

```
SessionStart --> [Agentic Loop] --> SessionEnd
                    |
            UserPromptSubmit
            PreToolUse
            PermissionRequest
            PostToolUse / PostToolUseFailure
            Notification
            SubagentStart / SubagentStop
            Stop
            TeammateIdle
            TaskCompleted
            PreCompact

Standalone (async):
  WorktreeCreate, WorktreeRemove, InstructionsLoaded, ConfigChange
```

Hooks fire at specific points during a session. When an event fires and a matcher matches, Claude Code passes JSON context about the event to the hook handler. For command hooks, input arrives on **stdin**. For HTTP hooks, it arrives as the POST request body. The handler can inspect the input, take action, and optionally return a decision.

---

## 2. Hook Types

### 2.1 Command Hooks (`type: "command"`)

Run a shell command. Script receives JSON on stdin, communicates via exit codes and stdout/stderr.

```json
{
  "type": "command",
  "command": "/path/to/script.sh",
  "timeout": 600,
  "async": false
}
```

- `async: true` runs in background without blocking (cannot return decisions)
- `timeout` in seconds (default 600 for command hooks)

### 2.2 HTTP Hooks (`type: "http"`)

POST event data to a URL endpoint. Same JSON input format as command hooks.

```json
{
  "type": "http",
  "url": "http://localhost:8080/hooks/tool-use",
  "headers": {
    "Authorization": "Bearer $MY_TOKEN"
  },
  "allowedEnvVars": ["MY_TOKEN"],
  "timeout": 30
}
```

### 2.3 Prompt Hooks (`type: "prompt"`)

Single-turn LLM evaluation. Claude Code sends your prompt + hook input to a Claude model (Haiku by default). Returns `{"ok": true}` or `{"ok": false, "reason": "..."}`.

```json
{
  "type": "prompt",
  "prompt": "Check if all tasks are complete. $ARGUMENTS",
  "model": "haiku",
  "timeout": 30
}
```

### 2.4 Agent Hooks (`type: "agent"`)

Multi-turn verification with tool access. Spawns a subagent that can Read, Grep, Glob, etc. Same `ok`/`reason` response format as prompt hooks.

```json
{
  "type": "agent",
  "prompt": "Verify all tests pass. Run the test suite. $ARGUMENTS",
  "timeout": 120
}
```

### Supported Hook Types per Event

**All four types** (`command`, `http`, `prompt`, `agent`):
- PermissionRequest, PostToolUse, PostToolUseFailure, PreToolUse, Stop, SubagentStop, TaskCompleted, UserPromptSubmit

**Command only**:
- ConfigChange, InstructionsLoaded, Notification, PreCompact, SessionEnd, SessionStart, SubagentStart, TeammateIdle, WorktreeCreate, WorktreeRemove

---

## 3. Hook Events Reference

### Complete Event Table

| Event | When it fires | Matcher field | Can block? |
|:------|:-------------|:-------------|:-----------|
| `SessionStart` | Session begins/resumes | `startup`, `resume`, `clear`, `compact` | No |
| `UserPromptSubmit` | User submits prompt | No matcher support | Yes |
| `PreToolUse` | Before tool executes | Tool name (`Bash`, `Edit\|Write`, `mcp__.*`) | Yes |
| `PermissionRequest` | Permission dialog shown | Tool name | Yes |
| `PostToolUse` | After tool succeeds | Tool name | No (feedback only) |
| `PostToolUseFailure` | After tool fails | Tool name | No (feedback only) |
| `Notification` | Notification sent | `permission_prompt`, `idle_prompt`, `auth_success`, `elicitation_dialog` | No |
| `SubagentStart` | Subagent spawned | Agent type name | No |
| `SubagentStop` | Subagent finishes | Agent type name | Yes |
| `Stop` | Claude finishes responding | No matcher support | Yes |
| `TeammateIdle` | Agent team teammate goes idle | No matcher support | Yes |
| `TaskCompleted` | Task marked complete | No matcher support | Yes |
| `PreCompact` | Before compaction | `manual`, `auto` | No |
| `ConfigChange` | Config file changes | `user_settings`, `project_settings`, etc. | Yes |
| `WorktreeCreate` | Worktree being created | No matcher support | Yes (via exit code) |
| `WorktreeRemove` | Worktree being removed | No matcher support | No |
| `InstructionsLoaded` | CLAUDE.md loaded | No matcher support | No |
| `SessionEnd` | Session terminates | `clear`, `logout`, `prompt_input_exit`, `other` | No |

### Key Events for Session Monitoring

**`PreCompact`** - Fires before context compaction. Matcher values: `manual` (user ran `/compact`) or `auto` (context window full). This is the closest signal to "context window is filling up."

**`SessionStart` with `compact` matcher** - Fires after compaction completes, when the session "restarts" with summarized context. Use this to re-inject critical context post-compaction.

**`Stop`** - Fires when Claude finishes responding. Input includes `stop_hook_active` (boolean) and `last_assistant_message`. Use to enforce quality gates or continuation logic.

**`SessionEnd`** - Fires on session termination. Use for cleanup, logging, or triggering state persistence.

---

## 4. Configuration & Placement

### Settings File Locations

| Location | Scope | Shareable |
|:---------|:------|:----------|
| `~/.claude/settings.json` | All projects (user) | No |
| `.claude/settings.json` | Single project | Yes (commit to repo) |
| `.claude/settings.local.json` | Single project | No (gitignored) |
| Managed policy settings | Organization-wide | Admin-controlled |
| Plugin `hooks/hooks.json` | When plugin enabled | Bundled with plugin |
| Skill/agent frontmatter | While component active | Defined in component |

### Configuration Structure

```json
{
  "hooks": {
    "<EventName>": [
      {
        "matcher": "<regex pattern>",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/script.sh",
            "timeout": 600,
            "async": false,
            "statusMessage": "Running validation..."
          }
        ]
      }
    ]
  }
}
```

Three nesting levels:
1. **Hook event** (lifecycle point)
2. **Matcher group** (filter when it fires)
3. **Hook handler(s)** (what runs when matched)

### Interactive Configuration

Type `/hooks` in Claude Code to open the interactive hooks manager. Changes made through `/hooks` take effect immediately. Direct file edits require session restart or `/hooks` review.

### Disabling Hooks

- Set `"disableAllHooks": true` in settings
- Or use toggle at bottom of `/hooks` menu

---

## 5. Hook Input/Output Protocol

### Common Input Fields (all events)

Every hook receives these JSON fields on stdin (command) or POST body (HTTP):

| Field | Description |
|:------|:-----------|
| `session_id` | Current session identifier |
| `transcript_path` | Path to conversation JSON file |
| `cwd` | Current working directory |
| `permission_mode` | `"default"`, `"plan"`, `"acceptEdits"`, `"dontAsk"`, or `"bypassPermissions"` |
| `hook_event_name` | Name of the event that fired |

When running with `--agent` or inside a subagent, two additional fields:
- `agent_id` - Unique subagent identifier
- `agent_type` - Agent name (e.g., `"Explore"`, `"security-reviewer"`)

### Exit Code Protocol

| Exit Code | Meaning | Behavior |
|:----------|:--------|:---------|
| **0** | Success/allow | Action proceeds. Stdout parsed for JSON. For `UserPromptSubmit` and `SessionStart`, stdout added as context. |
| **2** | Block | Action blocked. Stderr fed back to Claude as error message. |
| **Other** | Non-blocking error | Action proceeds. Stderr logged (visible in verbose mode). |

### JSON Output Format

On exit 0, your hook can print a JSON object to stdout for fine-grained control:

```json
{
  "continue": true,
  "stopReason": "Build failed",
  "suppressOutput": false,
  "systemMessage": "Warning: approaching rate limit",
  "decision": "block",
  "reason": "Tests must pass first",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Use rg instead of grep",
    "updatedInput": { "command": "rg pattern" },
    "additionalContext": "Extra info for Claude"
  }
}
```

**Universal fields:**
- `continue` (default `true`) - If `false`, Claude stops entirely
- `stopReason` - Message shown to user when `continue` is `false`
- `suppressOutput` - If `true`, hides stdout from verbose mode
- `systemMessage` - Warning shown to user

### Decision Control by Event

| Events | Pattern | Key fields |
|:-------|:--------|:-----------|
| UserPromptSubmit, PostToolUse, PostToolUseFailure, Stop, SubagentStop, ConfigChange | Top-level `decision` | `decision: "block"`, `reason` |
| TeammateIdle, TaskCompleted | Exit code or `continue: false` | Exit 2 blocks with stderr feedback |
| PreToolUse | `hookSpecificOutput` | `permissionDecision` (allow/deny/ask), `permissionDecisionReason` |
| PermissionRequest | `hookSpecificOutput` | `decision.behavior` (allow/deny) |

---

## 6. Context Window Monitoring

### Status Line - The Official Way to Monitor Context

The **status line** is the primary mechanism for real-time context window monitoring. It is a customizable bar at the bottom of Claude Code that runs a shell script and receives JSON session data on stdin.

#### Key Context Window Fields Available to Status Line

```json
{
  "context_window": {
    "total_input_tokens": 15234,
    "total_output_tokens": 4521,
    "context_window_size": 200000,
    "used_percentage": 8,
    "remaining_percentage": 92,
    "current_usage": {
      "input_tokens": 8500,
      "output_tokens": 1200,
      "cache_creation_input_tokens": 5000,
      "cache_read_input_tokens": 2000
    }
  },
  "exceeds_200k_tokens": false
}
```

| Field | Description |
|:------|:-----------|
| `context_window.context_window_size` | Max context window in tokens (200000 default, 1000000 for 1M models) |
| `context_window.used_percentage` | Pre-calculated % of context used |
| `context_window.remaining_percentage` | Pre-calculated % remaining |
| `context_window.current_usage` | Token counts from the most recent API call |
| `context_window.total_input_tokens` | Cumulative input tokens across session |
| `context_window.total_output_tokens` | Cumulative output tokens across session |
| `exceeds_200k_tokens` | Boolean: total tokens from last API call exceed 200k |

**Important:** `used_percentage` is calculated from **input tokens only**: `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. It does NOT include `output_tokens`.

#### Example: Context Window Progress Bar (Status Line)

```bash
#!/bin/bash
input=$(cat)
MODEL=$(echo "$input" | jq -r '.model.display_name')
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)

BAR_WIDTH=10
FILLED=$((PCT * BAR_WIDTH / 100))
EMPTY=$((BAR_WIDTH - FILLED))
BAR=""
[ "$FILLED" -gt 0 ] && BAR=$(printf "%${FILLED}s" | tr ' ' '▓')
[ "$EMPTY" -gt 0 ] && BAR="${BAR}$(printf "%${EMPTY}s" | tr ' ' '░')"

echo "[$MODEL] $BAR $PCT%"
```

Configure in `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.sh"
  }
}
```

Or use `/statusline` with natural language:

```
/statusline show model name and context percentage with a progress bar
```

### Auto-Compaction

Claude Code auto-compacts when context approaches the limit (~95% by default for subagents). Control with:

- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` environment variable - set to a lower number (e.g., `50`) to trigger compaction earlier
- `/compact` command - manual compaction with optional focus: `/compact focus on the API changes`
- `/context` command - see what is using context space

### PreCompact Hook for Compaction Awareness

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "auto",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/on-auto-compact.sh"
          }
        ]
      }
    ]
  }
}
```

The PreCompact hook fires BEFORE compaction. The input includes:
- `trigger`: `"manual"` or `"auto"`
- `custom_instructions`: what the user passed to `/compact` (empty for auto)

### SessionStart with `compact` Matcher for Post-Compaction Context Injection

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'Reminder: use Bun, not npm. Run bun test before committing.'"
          }
        ]
      }
    ]
  }
}
```

Anything printed to stdout by a `SessionStart` hook is added to Claude's context. This is the official way to re-inject critical context after compaction.

---

## 7. Session Management & Transfer

### Session Persistence

Sessions are stored locally per project directory. The transcript is saved as JSONL at the path in `transcript_path`.

### Resume & Fork Sessions

```bash
# Continue most recent conversation in current directory
claude --continue

# Resume specific session by ID or name
claude --resume auth-refactor

# Resume from pull request
claude --from-pr 123

# Fork a session (new ID, preserving conversation history)
claude --continue --fork-session
```

From inside a session: `/resume` opens an interactive session picker.

### Session Naming

```
/rename auth-refactor
```

Then resume later:
```bash
claude --resume auth-refactor
```

### Remote Control (Cross-Device Session Access)

Remote Control connects claude.ai/code or the Claude mobile app to a session running on your local machine. The session executes locally; the web/mobile interface is just a window into it.

```bash
# Dedicated server mode
claude remote-control --name "My Project"

# Interactive session with remote access
claude --remote-control "My Project"

# From inside an existing session
/remote-control
```

### Teleport (Web-to-Local Transfer)

```bash
# Pull a web session into your local terminal
claude --teleport
```

### Desktop Handoff

```
/desktop
```

Hands off a terminal session to the Desktop app for visual diff review.

### Programmatic Session Continuation (Agent SDK / CLI)

```bash
# First request
claude -p "Review this codebase for performance issues" --output-format json

# Capture session ID
session_id=$(claude -p "Start a review" --output-format json | jq -r '.session_id')

# Continue specific session
claude -p "Continue that review" --resume "$session_id"

# Continue most recent
claude -p "Now focus on the database queries" --continue
```

### JSON Output Format (for programmatic use)

```bash
claude -p "query" --output-format json
```

Returns JSON with `result`, `session_id`, and metadata including usage/cost info.

### Stream JSON for Real-Time Token Monitoring

```bash
claude -p "query" --output-format stream-json --verbose --include-partial-messages
```

Each line is a JSON object. `message_delta` events include usage metadata.

---

## 8. Detecting Session Limit / Remaining Context

### What Is Available

There is **no direct API to query "remaining context percentage" from within a hook**. However, there are several indirect methods:

#### Method 1: Status Line Data (Best for Display)

The status line receives `context_window.used_percentage` and `context_window.remaining_percentage` as pre-calculated fields. The status line script runs after each assistant message, so it has near-real-time data.

**Limitation:** Status line data is NOT available to hook scripts. Status line and hooks are separate mechanisms.

#### Method 2: Parse the Transcript File

Every hook receives `transcript_path` in its JSON input. The transcript is a JSONL file containing the full conversation history. You can parse it to estimate context usage, but this is complex and the transcript format is not formally documented as a stable API.

#### Method 3: PreCompact Hook as a Threshold Signal

The `PreCompact` hook with `"matcher": "auto"` fires when auto-compaction triggers, which happens when the context window is nearly full (~95% by default, or configurable via `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`). This acts as a high-water-mark signal.

```bash
#!/bin/bash
# on-auto-compact.sh - fires when context is ~95% full
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
TRIGGER=$(echo "$INPUT" | jq -r '.trigger')

if [ "$TRIGGER" = "auto" ]; then
    # Log the compaction event
    echo "$(date -Iseconds) auto-compact session=$SESSION_ID" >> ~/.claude/compact-events.log

    # Send notification
    notify-send "Claude Code" "Context window compacted (session: $SESSION_ID)"
fi

exit 0
```

#### Method 4: PostToolUse + External Token Counter

A `PostToolUse` hook runs after every tool call. You could maintain an external token counter by tracking tool inputs/outputs. However, you would need to estimate token counts externally (e.g., using tiktoken or a similar tokenizer), and this is approximate.

#### Method 5: `--output-format json` for Programmatic Sessions

When running Claude Code in print mode (`-p`), use `--output-format json` to get structured output including session metadata. The JSON output includes usage statistics.

#### Method 6: Combine Status Line + Hook via Shared File

The status line can write context data to a temp file, and hooks can read that file:

**Status line script** (`~/.claude/statusline-with-export.sh`):

```bash
#!/bin/bash
input=$(cat)
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
REMAINING=$(echo "$input" | jq -r '.context_window.remaining_percentage // 100' | cut -d. -f1)
SESSION_ID=$(echo "$input" | jq -r '.session_id')
CONTEXT_SIZE=$(echo "$input" | jq -r '.context_window.context_window_size // 200000')

# Export to shared file for hooks to read
cat > /tmp/claude-context-${SESSION_ID}.json <<EOF
{
  "used_percentage": $PCT,
  "remaining_percentage": $REMAINING,
  "context_window_size": $CONTEXT_SIZE,
  "timestamp": "$(date -Iseconds)"
}
EOF

# Display status
MODEL=$(echo "$input" | jq -r '.model.display_name')
echo "[$MODEL] Context: ${PCT}%"
```

**Hook script** (e.g., a PostToolUse or Stop hook):

```bash
#!/bin/bash
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')

CONTEXT_FILE="/tmp/claude-context-${SESSION_ID}.json"
if [ -f "$CONTEXT_FILE" ]; then
    REMAINING=$(jq -r '.remaining_percentage' "$CONTEXT_FILE")
    if [ "$REMAINING" -lt 20 ]; then
        echo "WARNING: Context window is ${REMAINING}% remaining" >&2
        # Could trigger a session transfer, log, notify, etc.
    fi
fi

exit 0
```

---

## 9. Practical Recipes

### Recipe 1: Desktop Notification When Context Gets Low

Uses the status line + shared file + Notification hook pattern.

**Status line** (`~/.claude/statusline-context-monitor.sh`):

```bash
#!/bin/bash
input=$(cat)
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
SESSION_ID=$(echo "$input" | jq -r '.session_id')

# Write to shared state file
echo "$PCT" > "/tmp/claude-context-pct-${SESSION_ID}"

# Color-coded display
if [ "$PCT" -ge 90 ]; then COLOR='\033[31m'
elif [ "$PCT" -ge 70 ]; then COLOR='\033[33m'
else COLOR='\033[32m'; fi
RESET='\033[0m'

MODEL=$(echo "$input" | jq -r '.model.display_name')
FILLED=$((PCT / 10)); EMPTY=$((10 - FILLED))
BAR=$(printf "%${FILLED}s" | tr ' ' '▓')$(printf "%${EMPTY}s" | tr ' ' '░')
echo -e "[$MODEL] ${COLOR}${BAR} ${PCT}%${RESET}"
```

**Settings** (`~/.claude/settings.json`):

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline-context-monitor.sh"
  },
  "hooks": {
    "PreCompact": [
      {
        "matcher": "auto",
        "hooks": [
          {
            "type": "command",
            "command": "notify-send 'Claude Code' 'Context window auto-compacting - approaching limit'"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'Context was compacted. Key reminders: [your project conventions here]'"
          }
        ]
      }
    ]
  }
}
```

### Recipe 2: Auto-Save State Before Compaction

```json
{
  "hooks": {
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/save-session-state.sh"
          }
        ]
      }
    ]
  }
}
```

`~/.claude/hooks/save-session-state.sh`:

```bash
#!/bin/bash
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path')
TRIGGER=$(echo "$INPUT" | jq -r '.trigger')
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

SAVE_DIR="$HOME/.claude/session-snapshots"
mkdir -p "$SAVE_DIR"

# Save metadata
cat > "$SAVE_DIR/${SESSION_ID}_${TIMESTAMP}.json" <<EOF
{
  "session_id": "$SESSION_ID",
  "transcript_path": "$TRANSCRIPT",
  "trigger": "$TRIGGER",
  "timestamp": "$TIMESTAMP"
}
EOF

# Optionally copy the transcript
if [ -f "$TRANSCRIPT" ]; then
    cp "$TRANSCRIPT" "$SAVE_DIR/${SESSION_ID}_${TIMESTAMP}.jsonl"
fi

exit 0
```

### Recipe 3: Stop Hook That Checks Task Completion

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Check if all tasks from the user's original request are complete. Context: $ARGUMENTS. If not, respond with {\"ok\": false, \"reason\": \"what remains\"}.",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

**Important:** Check `stop_hook_active` to prevent infinite loops:

```bash
#!/bin/bash
INPUT=$(cat)
if [ "$(echo "$INPUT" | jq -r '.stop_hook_active')" = "true" ]; then
    exit 0  # Allow Claude to stop - we already triggered continuation
fi
# ... rest of validation logic
```

### Recipe 4: Block Edits to Protected Files

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/protect-files.sh"
          }
        ]
      }
    ]
  }
}
```

```bash
#!/bin/bash
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

PROTECTED_PATTERNS=(".env" "package-lock.json" ".git/" "credentials")
for pattern in "${PROTECTED_PATTERNS[@]}"; do
    if [[ "$FILE_PATH" == *"$pattern"* ]]; then
        echo "Blocked: $FILE_PATH matches protected pattern '$pattern'" >&2
        exit 2
    fi
done
exit 0
```

### Recipe 5: SessionEnd Cleanup & State Persistence

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/session-cleanup.sh"
          }
        ]
      }
    ]
  }
}
```

```bash
#!/bin/bash
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
REASON=$(echo "$INPUT" | jq -r '.reason')
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path')

# Log session end
echo "$(date -Iseconds) end session=$SESSION_ID reason=$REASON" >> ~/.claude/session-log.txt

# Clean up temp files
rm -f "/tmp/claude-context-${SESSION_ID}"
rm -f "/tmp/claude-context-pct-${SESSION_ID}"

exit 0
```

**Note:** SessionEnd hooks have a default timeout of 1.5 seconds. Increase with `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` env var if needed.

### Recipe 6: Trigger Session Transfer via Stop Hook

A Stop hook that detects high context usage and prompts action:

```bash
#!/bin/bash
# stop-context-check.sh
INPUT=$(cat)

# Don't loop if already in a stop hook
if [ "$(echo "$INPUT" | jq -r '.stop_hook_active')" = "true" ]; then
    exit 0
fi

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id')
CONTEXT_FILE="/tmp/claude-context-${SESSION_ID}.json"

if [ -f "$CONTEXT_FILE" ]; then
    REMAINING=$(jq -r '.remaining_percentage' "$CONTEXT_FILE")
    if [ "$REMAINING" -lt 15 ]; then
        # Context is critically low - output reason to continue
        cat <<ENDJSON
{
  "decision": "block",
  "reason": "IMPORTANT: Context window is critically low (${REMAINING}% remaining). Before stopping, please: 1) Save a summary of current work state to .claude/session-handoff.md, 2) List all pending tasks, 3) Commit any changes with a descriptive message."
}
ENDJSON
        exit 0
    fi
fi

exit 0
```

---

## 10. Environment Variables Reference

### Context & Compaction

| Variable | Purpose |
|:---------|:--------|
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | Override auto-compaction threshold percentage (default ~95%). Set to e.g. `50` for earlier compaction |
| `CLAUDE_CODE_DISABLE_1M_CONTEXT` | Set to `1` to disable 1M token context window variants |

### Session Behavior

| Variable | Purpose |
|:---------|:--------|
| `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` | Timeout for SessionEnd hooks in ms (default 1500) |
| `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` | Set to `1` to disable background subagent functionality |

### Model & Thinking

| Variable | Purpose |
|:---------|:--------|
| `ANTHROPIC_MODEL` | Set default model (alias like `opus` or full name) |
| `CLAUDE_CODE_EFFORT_LEVEL` | `low`, `medium`, or `high` - controls adaptive reasoning depth |
| `MAX_THINKING_TOKENS` | Limit thinking token budget (set to `0` to disable) |
| `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING` | Set to `1` to revert to fixed thinking budget |

### Cost Control

| Variable | Purpose |
|:---------|:--------|
| `--max-budget-usd` | CLI flag (not env var) - max dollar spend before stopping (print mode only) |
| `--max-turns` | CLI flag - limit agentic turns (print mode only) |

### Hook-Related

| Variable | Purpose |
|:---------|:--------|
| `CLAUDE_PROJECT_DIR` | Available in hook commands - the project root directory |
| `CLAUDE_PLUGIN_ROOT` | Available in plugin hook commands - the plugin's root directory |
| `CLAUDE_ENV_FILE` | Available in SessionStart hooks only - write `export` statements to persist env vars |
| `CLAUDE_CODE_REMOTE` | Set to `"true"` in remote web environments |

### Prompt Caching

| Variable | Purpose |
|:---------|:--------|
| `DISABLE_PROMPT_CACHING` | Set to `1` to disable for all models |
| `DISABLE_PROMPT_CACHING_HAIKU` | Set to `1` to disable for Haiku only |
| `DISABLE_PROMPT_CACHING_SONNET` | Set to `1` to disable for Sonnet only |
| `DISABLE_PROMPT_CACHING_OPUS` | Set to `1` to disable for Opus only |

### MCP Tool Search

| Variable | Purpose |
|:---------|:--------|
| `ENABLE_TOOL_SEARCH` | `auto:<N>` triggers tool search when MCP tools exceed N% of context |

---

## 11. Limitations & Gaps

### What Is NOT Available

1. **No hook-accessible context percentage API.** Hooks do NOT receive `context_window.used_percentage` or any token counts in their JSON input. This data is only available to the status line mechanism. The workaround is the shared-file pattern described in Section 8, Method 6.

2. **No direct session state transfer API.** There is no built-in mechanism to "transfer" a session's state to a new session. You can:
   - Resume the same session (`--continue` / `--resume`)
   - Fork a session (`--fork-session`)
   - Teleport a web session to local (`--teleport`)
   - Use Remote Control for cross-device access
   - Manually persist key state to files and re-inject via SessionStart hooks

3. **No token count in hook inputs.** Hook events like `Stop`, `PreToolUse`, etc. do not include current token counts or context utilization.

4. **SessionEnd hooks are time-limited.** Default 1.5 second timeout. Must be fast. No async option.

5. **PermissionRequest hooks don't fire in print mode (`-p`).** Use `PreToolUse` instead for automated permission decisions.

6. **Stop hooks fire on every response completion,** not only at "task completion." They also do NOT fire on user interrupts.

7. **Compaction is lossy.** Instructions from early in the conversation can be lost. Put persistent rules in CLAUDE.md. Add "Compact Instructions" section to CLAUDE.md to control what is preserved.

8. **No streaming token counts in hooks.** The `stream-json` output format includes `message_delta` events with usage metadata, but this is only available via the CLI's `-p` mode, not from within hook scripts.

### Recommended Architecture for Session Limit Monitoring

Given these limitations, the most robust architecture is:

```
[Status Line Script]
    |
    |--> Writes context % to /tmp/claude-context-<session_id>.json
    |
[PreCompact Hook (auto)]
    |
    |--> Fires at ~95% (or CLAUDE_AUTOCOMPACT_PCT_OVERRIDE)
    |--> Send notification / save state
    |
[SessionStart Hook (compact)]
    |
    |--> Re-inject critical context after compaction
    |
[Stop Hook]
    |
    |--> Reads /tmp/claude-context-<session_id>.json
    |--> If remaining < threshold:
    |      |--> Instruct Claude to save handoff state
    |      |--> Trigger external notification/action
    |
[SessionEnd Hook]
    |
    |--> Cleanup temp files
    |--> Log session stats
```

This gives you:
- **Real-time monitoring** via status line
- **Threshold alerts** via PreCompact hook
- **Context preservation** via SessionStart compact hook
- **Proactive state saving** via Stop hook + shared file
- **Clean shutdown** via SessionEnd hook
