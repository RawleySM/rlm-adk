# Claude Code Hooks Documentation

> **Source**: https://code.claude.com/docs/en/hooks (redirected from https://docs.anthropic.com/en/docs/claude-code/hooks)
>
> **Fetched**: 2026-03-26

---

## Overview

Hooks are user-defined shell commands, HTTP endpoints, LLM prompts, or agents that execute automatically at specific points in Claude Code's lifecycle. They allow you to:

- Inspect and control tool execution before and after they run
- Add context to conversations dynamically
- Enforce security policies and permission controls
- Automate environment setup and teardown
- React to file changes and configuration updates
- Audit and log activity

Hooks receive JSON context about events via stdin (for command hooks) or HTTP POST bodies (for HTTP hooks), and can return decisions to allow, deny, or modify actions.

---

## Hook Lifecycle

Hooks fire at specific points during a Claude Code session. The main lifecycle phases are:

1. **Session Setup**: `SessionStart`, `InstructionsLoaded`
2. **User Input**: `UserPromptSubmit`
3. **Agentic Loop** (repeating):
   - `PreToolUse` - Before tool execution
   - `PermissionRequest` - When permission dialog appears
   - `PostToolUse` - After successful tool execution
   - `PostToolUseFailure` - After tool failure
   - `SubagentStart`/`SubagentStop` - Subagent lifecycle
   - `TaskCreated`/`TaskCompleted` - Task management
4. **Async Events**: `FileChanged`, `CwdChanged`, `ConfigChange`, `Notification`, `WorktreeCreate`/`WorktreeRemove`
5. **Session End**: `PreCompact`, `PostCompact`, `TeammateIdle`, `Stop`/`StopFailure`, `SessionEnd`

---

## Configuration Structure

Hooks are configured in JSON settings files with three levels of nesting.

### Hook Locations

| Location | Scope | Shareable |
|----------|-------|-----------|
| `~/.claude/settings.json` | All projects | No, local to machine |
| `.claude/settings.json` | Single project | Yes, commit to repo |
| `.claude/settings.local.json` | Single project | No, gitignored |
| Managed policy settings | Organization-wide | Yes, admin-controlled |
| Plugin `hooks/hooks.json` | When plugin enabled | Yes, bundled |
| Skill/agent frontmatter | While component active | Yes, defined in file |

### Basic Configuration Schema

```json
{
  "hooks": {
    "HookEventName": [
      {
        "matcher": "regex_pattern_or_*",
        "hooks": [
          {
            "type": "command|http|prompt|agent",
            "timeout": 600,
            "statusMessage": "Custom message",
            "once": false
          }
        ]
      }
    ]
  },
  "disableAllHooks": false
}
```

### Command Hook Configuration

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/block-rm.sh",
            "async": false,
            "shell": "bash",
            "timeout": 600,
            "statusMessage": "Validating command..."
          }
        ]
      }
    ]
  }
}
```

**Fields**:
- `type`: `"command"`
- `command`: Shell command to execute
- `async`: If `true`, runs in background without blocking (see async hooks section)
- `shell`: `"bash"` (default) or `"powershell"`
- `timeout`: Seconds before canceling (default: 600)
- `statusMessage`: Spinner message while running

### HTTP Hook Configuration

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8080/hooks/pre-tool-use",
            "headers": {
              "Authorization": "Bearer $MY_TOKEN",
              "X-Custom": "value"
            },
            "allowedEnvVars": ["MY_TOKEN"],
            "timeout": 30,
            "statusMessage": "Validating..."
          }
        ]
      }
    ]
  }
}
```

**Fields**:
- `type`: `"http"`
- `url`: Endpoint URL
- `headers`: HTTP headers with `$VAR_NAME` interpolation
- `allowedEnvVars`: List of variables allowed in headers
- `timeout`: Seconds before timeout (default: 30)
- `statusMessage`: Spinner message while running

### Prompt Hook Configuration

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Is this command safe? $ARGUMENTS",
            "model": "fast-model",
            "timeout": 30,
            "statusMessage": "Evaluating..."
          }
        ]
      }
    ]
  }
}
```

**Fields**:
- `type`: `"prompt"`
- `prompt`: Prompt text. Use `$ARGUMENTS` for hook input JSON
- `model`: Model to use (defaults to fast model)
- `timeout`: Seconds before timeout (default: 30)
- `statusMessage`: Spinner message

### Agent Hook Configuration

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "agent",
            "prompt": "Verify this command is safe: $ARGUMENTS",
            "model": "sonnet",
            "timeout": 60,
            "statusMessage": "Verifying..."
          }
        ]
      }
    ]
  }
}
```

**Fields**:
- `type`: `"agent"`
- `prompt`: Prompt text. Use `$ARGUMENTS` for hook input JSON
- `model`: Model to use
- `timeout`: Seconds before timeout (default: 60)
- `statusMessage`: Spinner message

### Environment Variable Reference

Reference hook scripts relative to project or plugin root:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/check-style.sh"
          }
        ]
      }
    ]
  }
}
```

**Available variables**:
- `$CLAUDE_PROJECT_DIR` - Project root
- `${CLAUDE_PLUGIN_ROOT}` - Plugin installation directory
- `${CLAUDE_PLUGIN_DATA}` - Plugin persistent data directory
- `$CLAUDE_ENV_FILE` - Path to env file (SessionStart, CwdChanged, FileChanged only)

### Plugin Hooks

Define in `hooks/hooks.json` with optional `description`:

```json
{
  "description": "Automatic code formatting",
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/format.sh",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

### Skills and Agents Frontmatter

```yaml
---
name: secure-operations
description: Perform operations with security checks
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/security-check.sh"
---
```

Hooks are scoped to component lifetime and cleaned up when component finishes.

---

## Hook Input and Output

### Common Input Fields

All hooks receive these fields plus event-specific fields:

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/my-project",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "agent_id": "optional_agent_id",
  "agent_type": "optional_agent_type"
}
```

**Fields**:
- `session_id`: Current session identifier
- `transcript_path`: Path to conversation JSON
- `cwd`: Current working directory
- `permission_mode`: `"default"`, `"plan"`, `"acceptEdits"`, `"auto"`, `"dontAsk"`, `"bypassPermissions"`
- `hook_event_name`: Event type that fired
- `agent_id`: Subagent identifier (when in subagent)
- `agent_type`: Agent name (when in subagent or with `--agent`)

### Exit Code Behavior

#### Exit Code 0 - Success

- Stdout parsed for JSON output
- Non-JSON text added as context (for events that support it)
- Shown in verbose mode (`Ctrl+O`)
- Hook allows action to proceed

```bash
exit 0
```

#### Exit Code 1 - Non-blocking Error

- Stderr shown in verbose mode
- stdout ignored
- Execution continues
- No decision made

```bash
echo "Warning: something unexpected happened" >&2
exit 1
```

#### Exit Code 2 - Blocking Error

- stderr fed back as feedback/error message
- stdout ignored
- Effect depends on event type

Blocking events (PreToolUse, PermissionRequest, UserPromptSubmit, etc.):
- Prevents action from proceeding
- stderr shown to Claude or user

Non-blocking events (PostToolUse, Notification, SessionEnd, etc.):
- stderr shown to user or in verbose mode
- Execution continues

```bash
echo "Blocked: rm commands are not allowed" >&2
exit 2
```

#### Exit Code 2 Behavior Per Event

| Hook Event | Can Block? | Exit 2 Behavior |
|-----------|-----------|-----------------|
| `PreToolUse` | Yes | Blocks tool call |
| `PermissionRequest` | Yes | Denies permission |
| `UserPromptSubmit` | Yes | Blocks prompt, erases it |
| `Stop` | Yes | Prevents Claude stop |
| `SubagentStop` | Yes | Prevents subagent stop |
| `TeammateIdle` | Yes | Teammate continues working |
| `TaskCreated` | Yes | Task not created |
| `TaskCompleted` | Yes | Task not marked complete |
| `ConfigChange` | Yes | Change blocked (not for policy) |
| `Elicitation` | Yes | Elicitation denied |
| `ElicitationResult` | Yes | Response blocked |
| `WorktreeCreate` | Yes | Creation fails |
| `PostToolUse` | No | stderr shown (tool already ran) |
| `PostToolUseFailure` | No | stderr shown |
| `Notification` | No | stderr shown to user |
| `SubagentStart` | No | stderr shown |
| `SessionStart` | No | stderr shown |
| `SessionEnd` | No | stderr shown |
| `CwdChanged` | No | stderr shown |
| `FileChanged` | No | stderr shown |
| `PreCompact` | No | stderr shown |
| `PostCompact` | No | stderr shown |
| `WorktreeRemove` | No | stderr shown in debug |
| `StopFailure` | No | Output ignored |
| `InstructionsLoaded` | No | Exit code ignored |

### JSON Output Format

Exit with code 0 and print JSON to stdout for structured control:

```json
{
  "continue": true,
  "stopReason": null,
  "suppressOutput": false,
  "systemMessage": null,
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow"
  }
}
```

**Universal fields**:
- `continue` (default: `true`): If `false`, Claude stops entirely
- `stopReason`: Message shown when `continue` is `false`
- `suppressOutput` (default: `false`): Hide stdout from verbose output
- `systemMessage`: Warning message shown to user

**Note**: Only process JSON on exit 0. If you exit 2, any JSON is ignored.

### Common Output Patterns

**Allow an action**:
```bash
exit 0
```

**Block an action with reason**:
```bash
echo "Not allowed because..." >&2
exit 2
```

**Add context to Claude**:
```bash
cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Current deployment status: staging"
  }
}
EOF
exit 0
```

**Modify tool input**:
```bash
cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "updatedInput": {
      "command": "npm run lint"
    }
  }
}
EOF
exit 0
```

**Stop Claude entirely**:
```bash
cat <<'EOF'
{
  "continue": false,
  "stopReason": "Build failed, fix errors before continuing"
}
EOF
exit 0
```

---

## HTTP Hook Response Handling

HTTP hooks use status codes and response bodies instead of exit codes:

- **2xx with empty body**: Success, equivalent to exit 0
- **2xx with plain text body**: Success, text added as context
- **2xx with JSON body**: Success, parsed like command hook JSON output
- **Non-2xx status**: Non-blocking error, execution continues
- **Connection failure or timeout**: Non-blocking error, execution continues

Unlike command hooks, HTTP hooks cannot signal blocking via status codes alone. To block, return 2xx with JSON containing decision fields:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Database writes are not allowed"
  }
}
```

---

## Matcher Patterns

The `matcher` field is a regex string. Use `"*"`, `""`, or omit to match all. Each event type matches on a different field.

### Matcher Values by Event

| Event | Matches On | Examples |
|-------|-----------|----------|
| PreToolUse, PostToolUse, PostToolUseFailure, PermissionRequest | tool_name | `Bash`, `Edit\|Write`, `mcp__.*` |
| SessionStart | how session started | `startup`, `resume`, `clear`, `compact` |
| SessionEnd | why session ended | `clear`, `resume`, `logout`, `other` |
| Notification | notification_type | `permission_prompt`, `idle_prompt`, `auth_success` |
| SubagentStart, SubagentStop | agent_type | `Bash`, `Explore`, `Plan`, custom names |
| PreCompact, PostCompact | trigger | `manual`, `auto` |
| ConfigChange | source | `user_settings`, `project_settings`, `local_settings`, `policy_settings`, `skills` |
| FileChanged | basename | `.envrc`, `.env`, any filename |
| StopFailure | error_type | `rate_limit`, `authentication_failed`, `billing_error`, `invalid_request`, `server_error`, `max_output_tokens`, `unknown` |
| InstructionsLoaded | load_reason | `session_start`, `nested_traversal`, `path_glob_match`, `include`, `compact` |
| Elicitation, ElicitationResult | mcp_server | Your configured MCP server names |
| UserPromptSubmit, Stop, TeammateIdle, TaskCreated, TaskCompleted, WorktreeCreate, WorktreeRemove, CwdChanged | None | Always fires |

### MCP Tool Naming

MCP tools follow pattern: `mcp__<server>__<tool>`

Examples:
- `mcp__memory__create_entities` - Memory server create tool
- `mcp__filesystem__read_file` - Filesystem read
- `mcp__github__search_repositories` - GitHub search

Regex patterns:
- `mcp__memory__.*` - All memory server tools
- `mcp__.*__write.*` - All write tools from any server

### Example Matchers

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [...]
      },
      {
        "matcher": "Edit|Write",
        "hooks": [...]
      },
      {
        "matcher": "mcp__memory__.*",
        "hooks": [...]
      },
      {
        "matcher": "mcp__.*__write.*",
        "hooks": [...]
      }
    ]
  }
}
```

---

## Complete Hook Event Reference

### SessionStart

**When it fires**: When a session begins or resumes

**Matcher values**:
- `startup` - New session
- `resume` - `--resume`, `--continue`, or `/resume`
- `clear` - `/clear` command
- `compact` - After auto or manual compaction

**Supported hook types**: Command hooks only

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "SessionStart",
  "source": "startup",
  "model": "claude-sonnet-4-6",
  "agent_type": "optional_agent_name"
}
```

#### Decision Control

- **Exit 0**: Success. Stdout text added as context.
- **Exit 2**: Non-blocking error. Stderr shown in verbose mode.
- **JSON output**:
  ```json
  {
    "hookSpecificOutput": {
      "hookEventName": "SessionStart",
      "additionalContext": "My additional context here"
    }
  }
  ```

#### Persist Environment Variables

SessionStart hooks have access to `CLAUDE_ENV_FILE`:

```bash
#!/bin/bash
if [ -n "$CLAUDE_ENV_FILE" ]; then
  echo 'export NODE_ENV=production' >> "$CLAUDE_ENV_FILE"
  echo 'export DEBUG_LOG=true' >> "$CLAUDE_ENV_FILE"
  echo 'export PATH="$PATH:./node_modules/.bin"' >> "$CLAUDE_ENV_FILE"
fi
exit 0
```

---

### InstructionsLoaded

**When it fires**: When `CLAUDE.md` or `.claude/rules/*.md` file is loaded into context

**Matcher values**:
- `session_start` - Files loaded at session start
- `nested_traversal` - Nested CLAUDE.md files
- `path_glob_match` - Path glob pattern matches
- `include` - Included from other files
- `compact` - After compaction

**Supported hook types**: All types

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/my-project",
  "hook_event_name": "InstructionsLoaded",
  "file_path": "/Users/my-project/CLAUDE.md",
  "memory_type": "Project",
  "load_reason": "session_start",
  "globs": ["path/glob/pattern"],
  "trigger_file_path": "/optional/path",
  "parent_file_path": "/optional/parent"
}
```

#### Decision Control

No decision control. Used for audit logging and observability only.

---

### UserPromptSubmit

**When it fires**: When the user submits a prompt, before Claude processes it

**Matcher support**: None (fires on every prompt)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "UserPromptSubmit",
  "prompt": "Write a function to calculate the factorial of a number"
}
```

#### Decision Control

```json
{
  "decision": "block",
  "reason": "Explanation for decision",
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "My additional context here"
  }
}
```

- **decision**: `"block"` prevents prompt processing and erases it
- **reason**: Shown to user when blocked
- **additionalContext**: Added to Claude's context
- Plain stdout text also added as context

---

### PreToolUse

**When it fires**: After Claude creates tool parameters and before the tool executes

**Matcher values**: Tool names - `Bash`, `Edit`, `Write`, `Read`, `Glob`, `Grep`, `Agent`, `WebFetch`, `WebSearch`, MCP tools (`mcp__<server>__<tool>`)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "npm test",
    "description": "Run test suite",
    "timeout": 120000,
    "run_in_background": false
  },
  "tool_use_id": "toolu_01ABC123..."
}
```

#### Tool Input Fields by Type

**Bash**:
```json
{
  "command": "npm test",
  "description": "Run test suite",
  "timeout": 120000,
  "run_in_background": false
}
```

**Write**:
```json
{
  "file_path": "/path/to/file.txt",
  "content": "file content"
}
```

**Edit**:
```json
{
  "file_path": "/path/to/file.txt",
  "old_string": "original text",
  "new_string": "replacement text",
  "replace_all": false
}
```

**Read**:
```json
{
  "file_path": "/path/to/file.txt",
  "offset": 10,
  "limit": 50
}
```

**Glob**:
```json
{
  "pattern": "**/*.ts",
  "path": "/path/to/dir"
}
```

**Grep**:
```json
{
  "pattern": "TODO.*fix",
  "path": "/path/to/dir",
  "glob": "*.ts",
  "output_mode": "content",
  "-i": true,
  "multiline": false
}
```

**WebFetch**:
```json
{
  "url": "https://example.com/api",
  "prompt": "Extract the API endpoints"
}
```

**WebSearch**:
```json
{
  "query": "react hooks best practices",
  "allowed_domains": ["docs.example.com"],
  "blocked_domains": ["spam.example.com"]
}
```

**Agent**:
```json
{
  "prompt": "Find all API endpoints",
  "description": "Find API endpoints",
  "subagent_type": "Explore",
  "model": "sonnet"
}
```

#### Decision Control

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow|deny|ask",
    "permissionDecisionReason": "Reason text",
    "updatedInput": {
      "field_to_modify": "new value"
    },
    "additionalContext": "Current environment: production. Proceed with caution."
  }
}
```

- **permissionDecision**:
  - `"allow"` - Skip permission prompt
  - `"deny"` - Prevent tool call
  - `"ask"` - Prompt user to confirm
- **permissionDecisionReason**: Shown to user
- **updatedInput**: Modify tool parameters before execution
- **additionalContext**: Added to Claude's context

---

### PermissionRequest

**When it fires**: When a permission dialog appears

**Matcher values**: Tool names (same as PreToolUse)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "PermissionRequest",
  "tool_name": "Bash",
  "tool_input": {
    "command": "rm -rf node_modules",
    "description": "Remove node_modules directory"
  },
  "permission_suggestions": [
    {
      "type": "addRules",
      "rules": [{ "toolName": "Bash", "ruleContent": "rm -rf node_modules" }],
      "behavior": "allow",
      "destination": "localSettings"
    }
  ]
}
```

#### Decision Control

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow|deny",
      "updatedInput": {
        "command": "npm run lint"
      },
      "updatedPermissions": [
        {
          "type": "addRules|replaceRules|removeRules|setMode|addDirectories|removeDirectories",
          "rules": [],
          "behavior": "allow|deny|ask",
          "destination": "session|localSettings|projectSettings|userSettings"
        }
      ],
      "message": "Reason for denial"
    }
  }
}
```

- **behavior**: `"allow"` or `"deny"`
- **updatedInput**: Modify tool parameters (allow only)
- **updatedPermissions**: Permission rule changes
- **message**: Shown to Claude on deny
- **interrupt**: If `true` on deny, stop Claude

#### Permission Update Entry Types

```json
{
  "type": "addRules",
  "rules": [{ "toolName": "Bash", "ruleContent": "command pattern" }],
  "behavior": "allow|deny|ask",
  "destination": "session|localSettings|projectSettings|userSettings"
}
```

```json
{
  "type": "replaceRules",
  "rules": [],
  "behavior": "allow|deny|ask",
  "destination": "session|localSettings|projectSettings|userSettings"
}
```

```json
{
  "type": "removeRules",
  "rules": [{ "toolName": "Bash" }],
  "behavior": "allow|deny|ask",
  "destination": "session|localSettings|projectSettings|userSettings"
}
```

```json
{
  "type": "setMode",
  "mode": "default|acceptEdits|dontAsk|bypassPermissions|plan",
  "destination": "session|localSettings|projectSettings|userSettings"
}
```

```json
{
  "type": "addDirectories",
  "directories": ["/path/to/dir"],
  "destination": "session|localSettings|projectSettings|userSettings"
}
```

```json
{
  "type": "removeDirectories",
  "directories": ["/path/to/dir"],
  "destination": "session|localSettings|projectSettings|userSettings"
}
```

---

### PostToolUse

**When it fires**: Immediately after a tool completes successfully

**Matcher values**: Tool names (same as PreToolUse)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "PostToolUse",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "/path/to/file.txt",
    "content": "file content"
  },
  "tool_response": {
    "filePath": "/path/to/file.txt",
    "success": true
  },
  "tool_use_id": "toolu_01ABC123..."
}
```

#### Decision Control

```json
{
  "decision": "block",
  "reason": "Explanation for decision",
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "Additional information for Claude",
    "updatedMCPToolOutput": "replacement output for MCP tools only"
  }
}
```

- **decision**: `"block"` prompts Claude with reason
- **reason**: Shown to Claude when blocked
- **additionalContext**: Added to Claude's context
- **updatedMCPToolOutput**: Replace MCP tool output (MCP tools only)

---

### PostToolUseFailure

**When it fires**: When a tool execution fails

**Matcher values**: Tool names (same as PreToolUse)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "PostToolUseFailure",
  "tool_name": "Bash",
  "tool_input": {
    "command": "npm test",
    "description": "Run test suite"
  },
  "tool_use_id": "toolu_01ABC123...",
  "error": "Command exited with non-zero status code 1",
  "is_interrupt": false
}
```

#### Decision Control

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUseFailure",
    "additionalContext": "Additional information about the failure for Claude"
  }
}
```

- **additionalContext**: Context added alongside error

---

### Notification

**When it fires**: When Claude Code sends notifications

**Matcher values**:
- `permission_prompt` - Permission needed
- `idle_prompt` - Claude idle
- `auth_success` - Authentication successful
- `elicitation_dialog` - MCP server requests input

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "Notification",
  "message": "Claude needs your permission to use Bash",
  "title": "Permission needed",
  "notification_type": "permission_prompt"
}
```

#### Decision Control

No blocking capability. For side effects and logging only.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "Notification",
    "additionalContext": "String added to Claude's context"
  }
}
```

---

### SubagentStart

**When it fires**: When a Claude Code subagent is spawned via the Agent tool

**Matcher values**: Agent type names (`Bash`, `Explore`, `Plan`, or custom agent names)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "SubagentStart",
  "agent_id": "agent-abc123",
  "agent_type": "Explore"
}
```

#### Decision Control

No blocking. Can inject context into subagent.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SubagentStart",
    "additionalContext": "Follow security guidelines for this task"
  }
}
```

---

### SubagentStop

**When it fires**: When a Claude Code subagent has finished responding

**Matcher values**: Agent type names (same as SubagentStart)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "~/.claude/projects/.../abc123.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "SubagentStop",
  "stop_hook_active": false,
  "agent_id": "def456",
  "agent_type": "Explore",
  "agent_transcript_path": "~/.claude/projects/.../abc123/subagents/agent-def456.jsonl",
  "last_assistant_message": "Analysis complete. Found 3 potential issues..."
}
```

#### Decision Control

```json
{
  "decision": "block",
  "reason": "Must be provided when blocking subagent stop"
}
```

- **decision**: `"block"` prevents subagent from stopping
- **reason**: Tells Claude why it should continue

---

### Stop

**When it fires**: When the main Claude Code agent has finished responding

**Matcher support**: None (fires on every stop)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "~/.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "Stop",
  "stop_hook_active": true,
  "last_assistant_message": "I've completed the refactoring. Here's a summary..."
}
```

#### Decision Control

```json
{
  "decision": "block",
  "reason": "Must be provided when Claude is blocked from stopping"
}
```

- **decision**: `"block"` prevents Claude from stopping
- **reason**: Required when blocking. Tells Claude why to continue

---

### StopFailure

**When it fires**: When the turn ends due to an API error (instead of Stop)

**Matcher values**:
- `rate_limit` - Rate limit exceeded
- `authentication_failed` - Auth problem
- `billing_error` - Billing issue
- `invalid_request` - Invalid request
- `server_error` - Server error
- `max_output_tokens` - Token limit reached
- `unknown` - Unknown error

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "StopFailure",
  "error": "rate_limit",
  "error_details": "429 Too Many Requests",
  "last_assistant_message": "API Error: Rate limit reached"
}
```

#### Decision Control

No decision control. Used for notification and logging only.

---

### TaskCreated

**When it fires**: When a task is being created via `TaskCreate` tool

**Matcher support**: None (fires on every task creation)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "TaskCreated",
  "task_id": "task-001",
  "task_subject": "Implement user authentication",
  "task_description": "Add login and signup endpoints",
  "teammate_name": "implementer",
  "team_name": "my-project"
}
```

#### Decision Control

```bash
#!/bin/bash
INPUT=$(cat)
TASK_SUBJECT=$(echo "$INPUT" | jq -r '.task_subject')

if [[ ! "$TASK_SUBJECT" =~ ^\[TICKET-[0-9]+\] ]]; then
  echo "Task subject must start with a ticket number" >&2
  exit 2  # Blocks task creation
fi

exit 0
```

- **Exit 2**: Task not created, stderr fed back as feedback
- **JSON with `continue: false`**: Stops teammate entirely
  ```json
  {
    "continue": false,
    "stopReason": "Task creation blocked due to validation failure"
  }
  ```

---

### TaskCompleted

**When it fires**: When a task is being marked as completed

**Matcher support**: None (fires on every task completion)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "TaskCompleted",
  "task_id": "task-001",
  "task_subject": "Implement user authentication",
  "task_description": "Add login and signup endpoints",
  "teammate_name": "implementer",
  "team_name": "my-project"
}
```

#### Decision Control

```bash
#!/bin/bash
INPUT=$(cat)

# Run the test suite
if ! npm test 2>&1; then
  echo "Tests not passing. Fix failing tests before completing." >&2
  exit 2  # Task not marked as completed
fi

exit 0
```

- **Exit 2**: Task not marked as completed, stderr fed back as feedback
- **JSON with `continue: false`**: Stops teammate entirely
  ```json
  {
    "continue": false,
    "stopReason": "Task completion blocked - tests failing"
  }
  ```

---

### TeammateIdle

**When it fires**: When an agent team teammate is about to go idle after finishing its turn

**Matcher support**: None (fires on every teammate idle)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "TeammateIdle",
  "teammate_name": "researcher",
  "team_name": "my-project"
}
```

#### Decision Control

```bash
#!/bin/bash

if [ ! -f "./dist/output.js" ]; then
  echo "Build artifact missing. Run the build before stopping." >&2
  exit 2  # Teammate continues working
fi

exit 0
```

- **Exit 2**: Teammate continues working with stderr as feedback
- **JSON with `continue: false`**: Stops teammate entirely
  ```json
  {
    "continue": false,
    "stopReason": "Build output missing"
  }
  ```

---

### ConfigChange

**When it fires**: When a configuration file changes during a session

**Matcher values**:
- `user_settings` - `~/.claude/settings.json`
- `project_settings` - `.claude/settings.json`
- `local_settings` - `.claude/settings.local.json`
- `policy_settings` - Managed policy settings
- `skills` - Skill files in `.claude/skills/`

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "ConfigChange",
  "source": "project_settings",
  "file_path": "/Users/.../my-project/.claude/settings.json"
}
```

#### Decision Control

```json
{
  "decision": "block",
  "reason": "Configuration changes to project settings require admin approval"
}
```

- **decision**: `"block"` prevents change from being applied
- **reason**: Shown to user when blocked
- **Note**: `policy_settings` changes cannot be blocked

---

### CwdChanged

**When it fires**: When the working directory changes (e.g., `cd` command)

**Matcher support**: None (fires on every change)

**Supported hook types**: Command hooks only

**Special feature**: Access to `CLAUDE_ENV_FILE` for persisting environment variables

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/my-project/src",
  "hook_event_name": "CwdChanged",
  "old_cwd": "/Users/my-project",
  "new_cwd": "/Users/my-project/src"
}
```

#### Decision Control

No blocking capability. Can set dynamic watch paths:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "CwdChanged",
    "watchPaths": ["/absolute/path1", "/absolute/path2"]
  }
}
```

- **watchPaths**: Array of absolute paths to watch with FileChanged hooks
- Replaces current dynamic watch list
- Empty array clears dynamic watch list

---

### FileChanged

**When it fires**: When a watched file changes on disk

**Matcher values**: Pipe-separated basenames (`.envrc|.env`)

**Supported hook types**: Command hooks only

**Special feature**: Access to `CLAUDE_ENV_FILE` for persisting environment variables

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/my-project",
  "hook_event_name": "FileChanged",
  "file_path": "/Users/my-project/.envrc",
  "event": "change|add|unlink"
}
```

#### Decision Control

No blocking capability. Can update dynamic watch paths:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "FileChanged",
    "watchPaths": ["/absolute/path1"]
  }
}
```

---

### WorktreeCreate

**When it fires**: When a worktree is being created via `--worktree` or `isolation: "worktree"`

**Matcher support**: None (fires on every creation)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/my-project",
  "hook_event_name": "WorktreeCreate",
  "base_path": "/Users/my-project",
  "worktree_id": "wt-abc123"
}
```

#### Decision Control

Return the worktree path via stdout (command hook) or `hookSpecificOutput.worktreePath`:

```bash
#!/bin/bash
# Create worktree and return path
git worktree add /tmp/worktree-abc123
echo "/tmp/worktree-abc123"
exit 0
```

```json
{
  "hookSpecificOutput": {
    "hookEventName": "WorktreeCreate",
    "worktreePath": "/tmp/worktree-abc123"
  }
}
```

- Hook failure or missing path fails creation

---

### WorktreeRemove

**When it fires**: When a worktree is being removed

**Matcher support**: None (fires on every removal)

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/my-project",
  "hook_event_name": "WorktreeRemove",
  "base_path": "/Users/my-project",
  "worktree_path": "/tmp/worktree-abc123",
  "worktree_id": "wt-abc123"
}
```

#### Decision Control

No decision control. Failures logged in debug mode only.

---

### PreCompact

**When it fires**: Before context compaction

**Matcher values**:
- `manual` - Manual compaction
- `auto` - Automatic compaction

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "PreCompact",
  "trigger": "manual|auto"
}
```

#### Decision Control

No decision control. Used for observability.

---

### PostCompact

**When it fires**: After context compaction completes

**Matcher values**:
- `manual` - Manual compaction
- `auto` - Automatic compaction

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "PostCompact",
  "trigger": "manual|auto"
}
```

#### Decision Control

No decision control. Used for observability.

---

### Elicitation

**When it fires**: When an MCP server requests user input during a tool call

**Matcher values**: MCP server names from configuration

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "Elicitation",
  "mcp_server": "example-server",
  "tool_name": "mcp__example__request_input",
  "fields": [
    {
      "name": "username",
      "type": "string",
      "required": true,
      "description": "User account name"
    }
  ]
}
```

#### Decision Control

```json
{
  "hookSpecificOutput": {
    "hookEventName": "Elicitation",
    "action": "accept|decline|cancel",
    "content": {
      "username": "auto-provided-value"
    }
  }
}
```

- **action**: `"accept"` (auto-submit), `"decline"` (skip), `"cancel"` (abort tool)
- **content**: Form field values for accept action

---

### ElicitationResult

**When it fires**: After user responds to MCP elicitation, before response sent back to server

**Matcher values**: MCP server names

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "ElicitationResult",
  "mcp_server": "example-server",
  "tool_name": "mcp__example__request_input",
  "result": {
    "username": "user-provided-value"
  }
}
```

#### Decision Control

```json
{
  "hookSpecificOutput": {
    "hookEventName": "ElicitationResult",
    "action": "accept|decline|cancel",
    "content": {
      "username": "override-value"
    }
  }
}
```

- **action**: Override user's decision
- **content**: Override form field values

---

### SessionEnd

**When it fires**: When a session terminates

**Matcher values**:
- `clear` - `/clear` command
- `resume` - Resumed session
- `logout` - User logout
- `prompt_input_exit` - Prompt input ended
- `bypass_permissions_disabled` - Permissions re-enabled
- `other` - Other reason

**Supported hook types**: Command, HTTP, Prompt, Agent

#### Input Schema

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
  "cwd": "/Users/...",
  "hook_event_name": "SessionEnd",
  "reason": "other"
}
```

#### Decision Control

No decision control. Used for cleanup and logging.

---

## Advanced Features

### Run Hooks in the Background (Async)

Set `"async": true` on command hooks to run without blocking:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "curl -X POST http://metrics.example.com/log",
            "async": true
          }
        ]
      }
    ]
  }
}
```

- Runs in background without blocking execution
- Useful for logging, metrics, notifications
- Output not processed
- Failures not reported

### Prompt-Based Hooks

Send hook input to Claude for evaluation:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "Is this bash command safe to run? $ARGUMENTS",
            "model": "fast-model",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

- Claude responds with yes/no decision as JSON
- `$ARGUMENTS` replaced with hook input JSON
- Useful for flexible validation logic

### Agent-Based Hooks

Spawn subagent to verify conditions before allowing action:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "agent",
            "prompt": "Review this command for security issues: $ARGUMENTS",
            "model": "sonnet",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

- Full agent with tool access (Read, Grep, Glob, etc.)
- Can verify conditions before allowing action
- Use for complex validation requiring file inspection

### Deduplicate Hooks

All matching hooks run in parallel. Identical handlers deduplicated:

- **Command**: Deduplicated by command string
- **HTTP**: Deduplicated by URL
- **Prompt/Agent**: Not deduplicated

### The `/hooks` Menu

Type `/hooks` in Claude Code to browse configured hooks:

- Read-only browser showing all hooks
- Organized by event type with counts
- Shows hook source: User, Project, Local, Plugin, Session, Built-in
- Filter by event and matcher
- Detail view shows full configuration

---

## Complete Examples

### Block Destructive Shell Commands

`.claude/hooks/block-rm.sh`:
```bash
#!/bin/bash

# Read the JSON input
COMMAND=$(jq -r '.tool_input.command' < /dev/stdin)

# Block rm -rf
if echo "$COMMAND" | grep -q 'rm -rf'; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: "Destructive command blocked by hook"
    }
  }'
else
  exit 0  # Allow
fi
```

Configuration:
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/block-rm.sh"
          }
        ]
      }
    ]
  }
}
```

### Style Checking After File Writes

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/check-style.sh"
          }
        ]
      }
    ]
  }
}
```

### Auto-Approve Safe Commands

```bash
#!/bin/bash

COMMAND=$(jq -r '.tool_input.command' < /dev/stdin)

# Auto-approve read-only commands
if echo "$COMMAND" | grep -qE '^(ls|cat|grep|npm test|npm lint)'; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "allow"
    }
  }'
else
  exit 0  # Let normal permission flow handle it
fi
```

### Environment Setup on Directory Change

```bash
#!/bin/bash

if [ -n "$CLAUDE_ENV_FILE" ]; then
  if [ -f .envrc ]; then
    # Load direnv variables
    eval "$(direnv export bash)" >> "$CLAUDE_ENV_FILE"
  fi
fi

exit 0
```

### Validate Task Naming Convention

```bash
#!/bin/bash

INPUT=$(cat)
TASK_SUBJECT=$(echo "$INPUT" | jq -r '.task_subject')

# Enforce TICKET-XXX format
if [[ ! "$TASK_SUBJECT" =~ ^\[TICKET-[0-9]+\] ]]; then
  echo "Task subject must start with [TICKET-XXX] format" >&2
  exit 2
fi

exit 0
```

### Require Tests Before Completion

```bash
#!/bin/bash

# Run tests
if ! npm test 2>&1; then
  echo "Tests failing. Fix before marking task complete." >&2
  exit 2
fi

exit 0
```

### HTTP Hook with Authentication

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "http",
            "url": "http://localhost:8080/hooks/validate",
            "headers": {
              "Authorization": "Bearer $MY_TOKEN"
            },
            "allowedEnvVars": ["MY_TOKEN"],
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

### MCP Tool Logging

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "mcp__memory__.*",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'Memory operation initiated' >> ~/mcp-ops.log"
          }
        ]
      },
      {
        "matcher": "mcp__.*__write.*",
        "hooks": [
          {
            "type": "command",
            "command": "/home/user/scripts/validate-mcp-write.py"
          }
        ]
      }
    ]
  }
}
```

---

## Disable or Remove Hooks

Remove hook entry from settings JSON:

```json
// Before
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [...] }
    ]
  }
}

// After
{
  "hooks": {
    "PreToolUse": []
  }
}
```

Temporarily disable all hooks without removing:

```json
{
  "disableAllHooks": true
}
```

**Note**: Managed settings `disableAllHooks` cannot disable user/project/local hooks. Only `disableAllHooks` at managed level can disable managed hooks.

---

## Best Practices

1. **Keep hooks fast** - Use exit codes for simple decisions, not external API calls
2. **Use async for side effects** - Logging, metrics, notifications with `"async": true`
3. **Reference scripts by path** - Use `$CLAUDE_PROJECT_DIR` for portability
4. **Validate JSON carefully** - Your shell profile shouldn't print on startup (interferes with JSON parsing)
5. **Test matchers** - Use regex carefully, test with actual tool names
6. **Don't block indefinitely** - Set reasonable `timeout` values
7. **Document your hooks** - Add comments explaining what hooks do
8. **Use `/hooks` menu** - Verify configuration is applied correctly
9. **Specific matchers** - Use `Edit|Write` not `.*` to avoid unnecessary processing
10. **Error messages** - Provide clear feedback in stderr when blocking actions

---

## File Locations Summary

| Path | Purpose |
|------|---------|
| `~/.claude/settings.json` | User-level hooks (all projects) |
| `.claude/settings.json` | Project hooks (commit to repo) |
| `.claude/settings.local.json` | Local project hooks (gitignored) |
| `.claude/hooks/*.sh` | Hook script files |
| `.claude/skills/` | Skill frontmatter hooks |
| `.claude/agents/` | Agent frontmatter hooks |
| Plugin `hooks/hooks.json` | Plugin-bundled hooks |
