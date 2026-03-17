# Claude Code: Hooks, Session Transfer, Monitoring, Agent Handoff & Context Management

Research compiled: 2026-03-13

---

## Table of Contents

1. [Claude Code Hook Implementations](#1-claude-code-hook-implementations)
2. [Session State Transfer Between AI Coding Agents](#2-session-state-transfer-between-ai-coding-agents)
3. [Monitoring Claude Code Usage/Limits Programmatically](#3-monitoring-claude-code-usagelimits-programmatically)
4. [Handoff Patterns Between Claude Code and Other CLI Agents](#4-handoff-patterns-between-claude-code-and-other-cli-agents)
5. [Context Window Management Strategies for Long Coding Sessions](#5-context-window-management-strategies-for-long-coding-sessions)

---

## 1. Claude Code Hook Implementations

### Overview

Hooks are user-defined shell commands that execute automatically at specific points in Claude Code's lifecycle. They were released in early 2026 and provide 12 lifecycle events for attaching custom logic. Three handler types exist: **command** hooks (shell scripts), **prompt** hooks (semantic evaluation), and **agent** hooks (deep analysis requiring tool access).

Configuration lives in `.claude/settings.json` (project-level, shared via git) or `~/.claude/settings.json` (user-level, global). A new interactive `/hooks` command (2026) enables menu-based configuration without manual JSON editing.

### Hook Input/Output Protocol

Hooks receive JSON on stdin describing the event:

```json
{
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "ls -la /home/user/project"
  },
  "session_id": "abc123...",
  "cwd": "/home/user/project"
}
```

Exit codes: `0` = allow, `2` = block (PreToolUse only), other = error.

### Practical Example: Auto-Format on File Save (PostToolUse)

Source: [Serenities AI - Claude Code Hooks Guide 2026 (Dev.to)](https://dev.to/serenitiesai/claude-code-hooks-guide-2026-automate-your-ai-coding-workflow-dde)

```bash
#!/bin/bash
# .claude/hooks/auto-format.sh
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then exit 0; fi

EXT="${FILE##*.}"
case "$EXT" in
  js|jsx|ts|tsx|json|css|md) npx prettier --write "$FILE" 2>/dev/null ;;
  py) black --quiet "$FILE" 2>/dev/null ;;
  go) gofmt -w "$FILE" 2>/dev/null ;;
  rs) rustfmt "$FILE" 2>/dev/null ;;
esac
```

Configuration:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write|MultiEdit",
      "hooks": [{
        "type": "command",
        "command": ".claude/hooks/auto-format.sh",
        "statusMessage": "Formatting..."
      }]
    }]
  }
}
```

### Practical Example: Block Dangerous Commands (PreToolUse)

Source: [Serenities AI - Claude Code Hooks Guide 2026 (Dev.to)](https://dev.to/serenitiesai/claude-code-hooks-guide-2026-automate-your-ai-coding-workflow-dde)

```bash
#!/bin/bash
COMMAND=$(cat | jq -r '.tool_input.command // empty')
if [ -z "$COMMAND" ]; then exit 0; fi

PATTERNS=('rm\s+-rf\s+/' 'mkfs\.' 'dd\s+if=' 'chmod\s+-R\s+777\s+/' 'curl.*\|\s*bash' '>\s*/dev/sd[a-z]')

for p in "${PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qE "$p"; then
    jq -n --arg r "Blocked: $p detected" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
    exit 0
  fi
done
exit 0
```

### Practical Example: Quality Gate Before Commit (PreToolUse)

Source: [Blake Crosley - Claude Code Hooks Tutorial: 5 Production Hooks From Scratch](https://blakecrosley.com/blog/claude-code-hooks-tutorial) (March 10, 2026)

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{
        "type": "command",
        "command": "bash -c 'INPUT=$(cat); CMD=$(echo \"$INPUT\" | jq -r \".tool_input.command\"); if echo \"$CMD\" | grep -qE \"^git\\s+commit\"; then if ! LINT_OUTPUT=$(ruff check . --select E,F,W 2>&1); then echo \"LINT FAILED -- fix before committing:\" >&2; echo \"$LINT_OUTPUT\" >&2; exit 2; fi; fi'"
      }]
    }]
  }
}
```

Exit code 2 blocks the commit, forcing Claude to fix lint violations before proceeding.

### Practical Example: Auto-Run Tests After Changes (PostToolUse, async)

Source: [Serenities AI (Dev.to)](https://dev.to/serenitiesai/claude-code-hooks-guide-2026-automate-your-ai-coding-workflow-dde)

```bash
#!/bin/bash
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')
if [ -z "$FILE" ]; then exit 0; fi
if ! echo "$FILE" | grep -qE '\.(js|ts|py|go|rs)$'; then exit 0; fi

if [ -f "package.json" ]; then
  npx jest --findRelatedTests "$FILE" --no-coverage >> /tmp/claude-tests.txt 2>&1
elif [ -f "pyproject.toml" ]; then
  python -m pytest --tb=short >> /tmp/claude-tests.txt 2>&1
fi
```

Use `"async": true` in configuration to allow Claude to continue without waiting.

### Practical Example: Tool Usage Logging (PostToolUse)

Source: [Serenities AI (Dev.to)](https://dev.to/serenitiesai/claude-code-hooks-guide-2026-automate-your-ai-coding-workflow-dde)

```bash
#!/bin/bash
INPUT=$(cat)
mkdir -p "$HOME/.claude/logs"
TOOL=$(echo "$INPUT" | jq -r '.tool_name // "unknown"')
SESSION=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
TINPUT=$(echo "$INPUT" | jq -c '.tool_input // {}')

jq -n --arg ts "$(date -Iseconds)" --arg t "$TOOL" --arg s "$SESSION" \
  --argjson i "$TINPUT" \
  '{timestamp:$ts,tool:$t,session:$s,input:$i}' >> \
  "$HOME/.claude/logs/tool-usage.jsonl"
```

### Practical Example: Desktop/Slack Notifications (Stop Event)

Source: [Serenities AI (Dev.to)](https://dev.to/serenitiesai/claude-code-hooks-guide-2026-automate-your-ai-coding-workflow-dde)

```bash
#!/bin/bash
INPUT=$(cat)
EVENT=$(echo "$INPUT" | jq -r '.hook_event_name')
case "$EVENT" in
  Notification) MSG=$(echo "$INPUT" | jq -r '.message // "Notification"') ;;
  Stop) MSG="Claude finished responding." ;;
esac

command -v notify-send &>/dev/null && notify-send "Claude Code" "$MSG"

[ -n "$SLACK_WEBHOOK_URL" ] && curl -s -X POST "$SLACK_WEBHOOK_URL" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg t "$MSG" '{text:$t}')" || true
```

### Post-Compaction Context Injection (Workaround)

Source: [Dicklesworthstone/post_compact_reminder (GitHub)](https://github.com/Dicklesworthstone/post_compact_reminder)

Since a dedicated PostCompact hook event does not exist yet (feature requests: [#14258](https://github.com/anthropics/claude-code/issues/14258), [#17237](https://github.com/anthropics/claude-code/issues/17237)), the community has developed workarounds:

**Marker File Pattern**: A PreCompact hook writes a marker file when compaction is about to happen. A UserPromptSubmit hook checks for the marker on your next message. If the marker exists, it injects a reminder (e.g., to re-read AGENTS.md) and deletes the marker.

**PostToolUse with Compact Matcher**: Use the PostToolUse lifecycle event with the `compact` matcher. When compaction happens, this hook fires and its stdout gets injected as a system message.

Source: [mvara-ai/precompact-hook (GitHub)](https://github.com/mvara-ai/precompact-hook) -- LLM-interpreted recovery summaries before context compaction.

### Boris Cherny's Setup (Creator of Claude Code)

Source: [Twitter/X thread by @bcherny](https://twitter-thread.com/t/2007179832300581177) | [Threads post](https://www.threads.com/@boris_cherny/post/DTBVlMIkpcm/)

- Uses **PostToolUse** hook for code formatting ("handles the last 10%")
- Uses **Stop** hook for deterministic verification of long-running tasks
- Runs 5+ terminal instances simultaneously plus 5-10 on claude.ai/code
- Exclusively uses Opus 4.5 with thinking for everything
- Starts sessions in Plan mode (shift+tab twice), refines, then switches to auto-accept
- Maintains shared `CLAUDE.md` updated multiple times weekly documenting mistakes Claude makes

### Additional Hook Resources

- [Claude Code Hooks: Complete Guide with 20+ Examples (Dev.to)](https://dev.to/lukaszfryc/claude-code-hooks-complete-guide-with-20-ready-to-use-examples-2026-dcg)
- [Claude Code Hooks: Complete Guide to All 12 Lifecycle Events (ClaudeFast)](https://claudefa.st/blog/tools/hooks/hooks-guide)
- [Steve Kinney - Claude Code Hook Examples](https://stevekinney.com/courses/ai-development/claude-code-hook-examples)
- [DataCamp - Claude Code Hooks: A Practical Guide](https://www.datacamp.com/tutorial/claude-code-hooks)
- [Pixelmojo - All 12 Lifecycle Events with CI/CD Patterns](https://www.pixelmojo.io/blogs/claude-code-hooks-production-quality-ci-cd-patterns)
- [disler/claude-code-hooks-mastery (GitHub)](https://github.com/disler/claude-code-hooks-mastery)
- [JP Caparas - Claude Code Hooks: Git Automation Guide (Reading.sh/Medium)](https://reading.sh/claude-code-hooks-a-bookmarkable-guide-to-git-automation-11b4516adc5d)
- [Official Hooks Reference](https://code.claude.com/docs/en/hooks)

---

## 2. Session State Transfer Between AI Coding Agents

### Claude Code Session Memory System

Source: [ClaudeFast - Claude Code Session Memory: Automatic Cross-Session Context](https://claudefa.st/blog/guide/mechanics/session-memory)

Session Memory is Claude Code's automatic background system that maintains context across sessions:

- **Storage**: Markdown files at `~/.claude/projects/<project-hash>/<session-id>/session-memory/summary.md`
- **Extraction cadence**: First extraction at ~10,000 tokens; subsequent updates every ~5,000 tokens or 3 tool calls
- **Cross-session recall**: New sessions automatically inject relevant summaries from prior work
- **Terminal indicators**: "Recalled X memories" at session start; "Wrote X memories" during work; `ctrl+o` to inspect
- **The `/remember` command**: Reviews session memories, identifies patterns, proposes updates to `CLAUDE.local.md`
- **Instant compaction**: `/compact` completes instantly since Session Memory pre-writes summaries continuously
- **Availability**: Requires Anthropic's native API (Pro/Max); not available on Bedrock/Vertex/Foundry

### The Handoff Protocol (MCP-Based)

Source: [Black Dog Labs - Claude Code Decoded: The Handoff Protocol](https://blackdoglabs.io/blog/claude-code-decoded-handoff-protocol)

An MCP server stores handoff states as JSON files in `~/.handoffs/` with three core tools:

1. **save_handoff**: Captures current session state
2. **load_handoff**: Restores previous session state
3. **list_handoffs**: Shows available saved sessions

What gets captured:
- **Task Context**: Objective, status (in_progress/blocked/needs_review), progress summary
- **File References**: Paths with relevance explanations, specific line ranges (no full file contents)
- **Decision Log**: Each decision with rationale and timestamps
- **Next Steps**: Prioritized action items (high/medium/low)

What is excluded: full file contents, complete conversation history, code already in files, failed attempts.

Token savings: Traditional handoff ~38,000 tokens vs. protocol-based ~28,900 tokens (24% reduction). Context restoration drops from 5-10 minutes to 30 seconds.

### CLI-Continues: Cross-Tool Session Transfer

Source: [yigitkonur/cli-continues (GitHub)](https://github.com/yigitkonur/cli-continues)

A Node.js utility enabling seamless handoffs between 14 AI coding agents with 182 possible cross-platform handoff paths:

Supported agents: Claude Code, Codex, GitHub Copilot CLI, Gemini CLI, Cursor, Amp, Cline, Roo Code, Kilo Code, Kiro, Crush, OpenCode, Factory Droid, Antigravity

Transfer process:
1. **Discovery** -- scans all 14 tool directories
2. **Parsing** -- reads native formats (JSONL, JSON, SQLite, YAML)
3. **Extraction** -- retrieves messages, file changes, and reasoning
4. **Handoff** -- injects structured context into target tool

Usage:
```bash
npx continues                              # Interactive picker
continues claude                           # Resume latest Claude session
continues codex 3                          # Resume 3rd most recent Codex session
continues resume abc123 --in gemini        # Cross-tool handoff
continues inspect abc123 --preset full --write-md handoff.md  # Export
```

Four verbosity presets: minimal, standard, verbose, full.

### Continuous Claude v3: Ledger-Based Context Management

Source: [parcadei/Continuous-Claude-v3 (GitHub)](https://github.com/parcadei/Continuous-Claude-v3)

A comprehensive context management system using YAML handoffs and continuity ledgers:

- **Continuity Ledger System**: `CONTINUITY_*.md` files function as persistent state records. On session start: load ledger; during work: track changes; at session end: save state.
- **Memory Recall**: Semantic search against archived learnings stored in PostgreSQL with pgvector embeddings
- **TLDR 5-Layer Code Analysis**: ~1,200 tokens vs 23,000 raw (95% savings) using AST, call graph, control flow, data flow, and program dependence graph layers
- **32 specialized agents** including plan-agent, kraken (code generator), arbiter (testing), phoenix (refactoring), warden (review)
- **Meta-skill orchestration chains**: e.g., `/build greenfield`: discovery -> plan-agent -> validate -> kraken -> commit

Hooks at five critical junctures:
1. **Context Hooks** (session start): Load ledger, recall memory, warm TLDR cache
2. **PostToolUse Hooks**: Index handoffs, provide skill hints, increment dirty flags
3. **UserPrompt Hooks**: Inject skill activation context
4. **SubagentStop Hooks**: Capture agent reports
5. **PreCompaction Hooks**: Auto-generate handoffs when dirty count exceeds threshold

### Handoff Skills and Plugins

- [petekp/claude-code-setup/handoff (Playbooks.com)](https://playbooks.com/skills/petekp/claude-code-setup/handoff) -- Captures what you're doing, what's done/not done, what failed, key decisions, and how to continue.
- [Handoff Context Skill (MCPMarket)](https://mcpmarket.com/tools/skills/handoff-context) -- Auto-captures Git state, project metadata, conversation summaries, and pending tasks into YAML on triggers like "handoff".
- [willseltzer/claude-handoff (GitHub)](https://github.com/willseltzer/claude-handoff)
- [Session Handoff for Claude Code (MCPMarket)](https://mcpmarket.com/tools/skills/session-handoff-context-manager)

### Feature Request: Official Session Export/Import

Source: [anthropics/claude-code Issue #18645](https://github.com/anthropics/claude-code/issues/18645) | [Issue #11455](https://github.com/anthropics/claude-code/issues/11455)

No official export/import mechanism exists for cross-machine session portability as of early 2026. Users working across multiple devices face challenges. The community has built workarounds (see above).

### Agent Swarms and Persistent Tasks

Source: [Simone Callegari - Claude Code: Tasks Persisting Between Sessions and Swarms (Dev.to)](https://dev.to/simone_callegari_1f56a902/claude-code-new-tasks-persisting-between-sessions-and-swarms-of-agents-against-context-rot-5dan)

Since Claude Code 2.1.16+, tasks are saved to files (with status, dependencies, and broadcasts), replacing the old "To-dos" that were lost on session close. Key architectural shifts:

- **Persistent Task Storage**: Tasks survive session crashes via `CLAUDE_CODE_TASK_LIST_ID` env var
- **Orchestrator Pattern**: Main session delegates execution, spawns specialized sub-agents
- **Isolated Agent Contexts**: Each agent gets a clean context window with only necessary files
- **Model Selection**: Haiku for simple tasks, Sonnet/Opus for complex reasoning
- **Multi-Session Coordination**: Sessions A-D can coordinate via shared task lists

---

## 3. Monitoring Claude Code Usage/Limits Programmatically

### OAuth Usage API Endpoint

Source: [CodeLynx - How to Show Claude Code Usage Limits in Your Statusline](https://codelynx.dev/posts/claude-code-usage-limits-statusline)

**Endpoint**: `GET https://api.anthropic.com/api/oauth/usage`

**Required Headers**:
```
Accept: application/json, text/plain, */*
Content-Type: application/json
User-Agent: claude-code/2.0.32
Authorization: Bearer sk-ant-oat01-...
anthropic-beta: oauth-2025-04-20
```

**Response format**:
```json
{
  "five_hour": {
    "utilization": 6.0,
    "resets_at": "2025-11-04T04:59:59.943648+00:00"
  },
  "seven_day": {
    "utilization": 35.0,
    "resets_at": "2025-11-06T03:59:59.943679+00:00"
  },
  "seven_day_opus": {
    "utilization": 0.0,
    "resets_at": null
  }
}
```

**Credential retrieval** (macOS):
```bash
security find-generic-password -s "Claude Code-credentials" -w
```

Returns JSON containing the OAuth access token.

**TypeScript implementation**:
```typescript
export async function fetchUsageLimits(token: string): Promise<UsageLimits | null> {
  const response = await fetch("https://api.anthropic.com/api/oauth/usage", {
    method: "GET",
    headers: {
      Accept: "application/json, text/plain, */*",
      "Content-Type": "application/json",
      "User-Agent": "claude-code/2.0.31",
      Authorization: `Bearer ${token}`,
      "anthropic-beta": "oauth-2025-04-20",
    },
  });
  if (!response.ok) return null;
  return response.json();
}
```

Automated setup: `pnpm dlx aiblueprint-cli claude-code statusline`

### OpenTelemetry Metrics Dashboard

Source: [Sealos Blog - Claude Code Metrics Dashboard: Grafana Setup (2026)](https://sealos.io/blog/claude-code-metrics/)

Claude Code exports OTLP-formatted metrics for eight primary dimensions: sessions, token usage (input/output/cache read/cache creation), cost tracking (USD per call), lines of code (additions/removals), commits and PRs, and active time.

**Enable telemetry**:
```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

Pipeline: Claude Code -> OpenTelemetry Collector (ports 4317/4318) -> Prometheus (port 9090) -> Grafana (port 3000)

Key KPIs:
- **Cache efficiency**: `cacheRead / (cacheRead + input) * 100`
- **Productivity ratio**: CLI processing time / user input time
- **Cost per 1K output tokens**: Model efficiency trend

Note: Environment variables are read once at launch; restart Claude Code after changes. Default metric export every 60 seconds; Prometheus scrapes every 15 seconds; 75-90 seconds before data appears in dashboards.

### Claude Code Usage Monitor (CLI Tool)

Source: [Maciek-roboblog/Claude-Code-Usage-Monitor (GitHub)](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)

Real-time terminal monitoring with ML-based predictions:

```bash
uv tool install claude-monitor
claude-monitor  # or cmonitor/ccmonitor aliases
```

Tracks three dimensions: token usage, message count, cost usage ("most important metric for long sessions").

Plan-specific limits: Pro ~44,000 tokens, Max5 ~88,000, Max20 ~220,000, Custom P90-based auto-detection from 192-hour history.

Key CLI parameters: `--plan [custom|pro|max5|max20]`, `--view [realtime|daily|monthly]`, `--refresh-rate 1-60`, `--theme [light|dark|classic|auto]`.

### ccusage CLI Tool

Source: [Shipyard - How to Track Claude Code Usage + Analytics](https://shipyard.build/blog/claude-code-track-usage/)

Analyzes Claude's local JSONL files:
```bash
npx ccusage@latest report daily
```

Provides usage breakdowns by date, session, or project. Particularly useful for Pro/Max subscribers who cannot access the Anthropic Console.

### Other Monitoring Methods

- **`/context` command**: In-session view of current token consumption and available tokens
- **`/status` command**: Monitor remaining allocation
- **`ANTHROPIC_LOG=debug`**: Detailed token logging per API call
- **Anthropic Console**: `console.anthropic.com` for API users -- team-wide adoption metrics
- **Usage & Cost Admin API**: Programmatic access to historical API usage and cost data for organizations

Source: [Shipyard Blog](https://shipyard.build/blog/claude-code-track-usage/) | [Anthropic Docs - Usage and Cost API](https://platform.claude.com/docs/en/build-with-claude/usage-cost-api)

### Third-Party Tools

- [TylerGallenbeck/claude-code-limit-tracker (GitHub)](https://github.com/TylerGallenbeck/claude-code-limit-tracker) -- Real-time quota monitoring in statusline
- [Apidog - Mastering Claude Code Usage Limits](https://apidog.com/blog/claude-code-usage-monitor/)
- [Hypereal - How to Monitor Claude Code Usage & Costs (2026)](https://hypereal.tech/a/claude-code-usage-monitor)

---

## 4. Handoff Patterns Between Claude Code and Other CLI Agents

### AgentAPI: Universal HTTP Control Layer

Source: [coder/agentapi (GitHub)](https://github.com/coder/agentapi)

A standardized HTTP interface to control 11+ AI coding agents through a terminal emulator abstraction layer:

Supported agents: Claude Code, Aider, Goose, GitHub Copilot, Amazon Q, Gemini CLI, OpenCode, Sourcegraph Amp, Codex, Auggie, Cursor CLI

**Four core endpoints**:
- `GET /messages` -- Full conversation history
- `POST /message` -- Submit user input
- `GET /status` -- Agent state ("stable" or "running")
- `GET /events` -- Server-Sent Events stream

Architecture: In-memory terminal emulator translates API calls into keystrokes while parsing agent responses into discrete messages. Diffing outputs isolates new responses and removes TUI artifacts.

Vision: Universal adapter enabling developers to switch between agents without changing their code.

### Multi-Agent Orchestration Patterns

Source: [Zen Van Riel - Claude Code Swarms: Multi-Agent AI Coding](https://zenvanriel.com/ai-engineer-blog/claude-code-swarms-multi-agent-orchestration/)

Three orchestration patterns:
1. **Pipeline** (sequential handoff): Architect -> Implementer -> Tester -> Documenter
2. **Fan-out/Fan-in** (parallel decomposition): Split task, parallel execution, merge results
3. **Feedback Loop** (iterative refinement): Build -> Test -> Refine cycle

Handoff artifacts serve as communication bridges:
- Architecture decisions guide implementation
- Implementation notes inform testing
- Test results trigger refinement

### Running 10+ Claude Instances in Parallel

Source: [Brian Redmond - Multi-Agent Orchestration (Dev.to)](https://dev.to/bredmond1019/multi-agent-orchestration-running-10-claude-instances-in-parallel-part-3-29da)

Architecture components:
- **Meta-Agent Orchestrator**: Analyzes requirements, creates task dependency graphs using topological sorting
- **Specialized Worker Agents**: Frontend, backend, testing, documentation roles
- **Centralized Task Queue**: Redis-based distribution with conflict prevention

File conflict prevention: Redis-based distributed locks with 300-second timeout, atomic "set if not exists" operations.

Real-world results: 12,000+ lines refactored in 2 hours vs. estimated 2 days manual work, 100% test pass rate, zero file conflicts.

### Subagent Patterns: Parallel vs Sequential

Source: [ClaudeFast - Sub-Agent Best Practices](https://claudefa.st/blog/guide/agents/sub-agent-best-practices)

**Parallel dispatch** (all conditions must be met): 3+ unrelated tasks, no shared state, clear file boundaries.

**Sequential dispatch** (any condition): Tasks have dependencies, shared files/state, unclear scope.

**Background dispatch**: Research/analysis, non-blocking results. Activate via `Ctrl+B` or automatic backgrounding.

Model selection: `export CLAUDE_CODE_SUBAGENT_MODEL="claude-sonnet-4-5-20250929"` -- main session on Opus, sub-agents on Sonnet for cost reduction.

Define specialist agents as Markdown files with YAML frontmatter in `.claude/agents/` for project-specific reuse.

### Cross-Tool Workflow Pattern

Source: [Sankalp's Blog - Guide to Claude Code 2.0](https://sankalp.bearblog.dev/my-experience-with-claude-code-20-and-how-to-get-better-at-using-coding-agents/)

Practical multi-tool workflow:
1. **Explore** -- Ask clarifying questions, understand requirements
2. **Analyze** -- Use `/ultrathink` for rigorous review
3. **Execute** -- Claude Code writes code with monitoring
4. **Review** -- GPT-5.2-Codex for bug detection (reported as superior for this step)

The author maintains Claude Code as executor, Codex for complex tasks/review, and Cursor for manual edits. Custom `/handoff` command creates summaries when ending sessions.

### GitHub Agent HQ

Source: [GitHub Blog - Pick Your Agent: Use Claude and Codex on Agent HQ](https://github.blog/news-insights/company-news/pick-your-agent-use-claude-and-codex-on-agent-hq/)

GitHub Agent HQ allows using Claude and Codex together -- move from idea to implementation using different agents for different steps without switching tools or losing context.

### VS Code Unified Agent Experience

Source: [VS Code Blog - A Unified Experience for All Coding Agents](https://code.visualstudio.com/blogs/2025/11/03/unified-agent-experience) | [Multi-Agent Development (Feb 2026)](https://code.visualstudio.com/blogs/2026/02/05/multi-agent-development)

VS Code provides a unified hosting environment for multiple coding agents including Claude Code, Codex, and others with shared context and coordination.

### Awesome Agent Skills (Cross-Agent Compatible)

Source: [VoltAgent/awesome-agent-skills (GitHub)](https://github.com/VoltAgent/awesome-agent-skills)

500+ agent skills from official dev teams and the community, compatible with Claude Code, Codex, Antigravity, Gemini CLI, Cursor, and others.

---

## 5. Context Window Management Strategies for Long Coding Sessions

### Context Window Specifications

- Claude Code has a **200K token context window**
- Performance degrades around **147K-152K tokens**
- Auto-compaction triggers at **64-75% capacity** (~128K-150K tokens)
- Reserved "working memory" of ~50K tokens (25% of window) for reasoning

Source: [Morph - Claude Code Context Window Guide](https://www.morphllm.com/claude-code-context-window) | [HyperDev Matsuoka - How Claude Code Got Better by Protecting More Context](https://hyperdev.matsuoka.com/p/how-claude-code-got-better-by-protecting)

### Built-in Commands

- **`/compact`** -- Strategically reduces context size. Now completes instantly since Session Memory pre-writes summaries.
- **`/compact` with instructions** -- `/compact "preserve the database schema decisions"`
- **`/clear`** -- Fresh session start
- **`/context`** -- Debug context issues, see token consumption
- **`Esc+Esc` or `/rewind`** -- Select a checkpoint, choose "Summarize from there" to condense forward messages while keeping earlier context intact
- **Plan mode** (`shift+tab` twice) -- Iterate on approach before committing tokens to execution

Source: [Claude Code Best Practices (Official)](https://code.claude.com/docs/en/best-practices) | [ClaudeLog - Claude Code Limits](https://claudelog.com/claude-code-limits/)

### Strategic Best Practices

Source: [Limited Edition Jonathan - Ultimate Guide: Fixing Context Limits (Substack)](https://limitededitionjonathan.substack.com/p/ultimate-guide-fixing-claude-hit-a94)

1. **Put persistent rules in CLAUDE.md** -- Moves stable information outside the context window
2. **Run `/compact` at logical breakpoints** -- Don't wait for auto-compaction; do it proactively with preservation instructions
3. **Use `/clear` between distinct tasks** -- Don't carry irrelevant context forward
4. **Delegate large-output tasks to subagents** -- Each gets an isolated context window
5. **Strategic checkpointing at 70% capacity** -- Document decisions, current state, open questions, next steps (your priorities, not the algorithm's)
6. **Use Projects with RAG** -- Upload documentation without burning context tokens

### Context Engineering Mindset

Source: [Sankalp's Blog](https://sankalp.bearblog.dev/my-experience-with-claude-code-20-and-how-to-get-better-at-using-coding-agents/)

Treat context as an "attention budget," not infinite storage. Everything gets added -- tool calls and their results rapidly consume tokens during agentic operations. Start fresh or use `/compact` when reaching 60% capacity on complex tasks.

### Parallel Session Architecture

Source: [Official Agent Teams Docs](https://code.claude.com/docs/en/agent-teams) | [ClaudeFast - Agent Teams Guide](https://claudefa.st/blog/guide/agents/agent-teams)

Agent teams (Claude Code v2.1.32+): One session acts as team lead coordinating work; teammates work independently in their own context windows and communicate directly with each other.

Each Claude Code session is separate. Spin up parallel sessions for different parts of work instead of forcing everything into one conversation.

### Headless Mode for Automation

Source: [Claude Code Headless Docs (Official)](https://code.claude.com/docs/en/headless) | [SFEIR Institute - Headless Mode Cheatsheet](https://institute.sfeir.com/en/claude-code/claude-code-headless-mode-and-ci-cd/cheatsheet/)

```bash
claude -p "Analyze current project code quality"           # Single prompt
claude -p "prompt" --session-id my-session                 # Multi-turn with session persistence
claude -p "Analyze codebase" --allowedTools "Read,Glob,Grep"  # Read-only tools
claude -p "prompt" --output-format json                    # Structured output
```

Multi-turn sessions: `--session-id` maintains context between successive calls. Context stored server-side and auto-reloaded.

Output formats: text, json, stream-json. Integrates natively into GitHub Actions, GitLab CI, and Jenkins.

### Context Rot Prevention via Agent Swarms

Source: [Simone Callegari (Dev.to)](https://dev.to/simone_callegari_1f56a902/claude-code-new-tasks-persisting-between-sessions-and-swarms-of-agents-against-context-rot-5dan)

LLMs experience **20-50% performance degradation** as context grows from 10K to 100K+ tokens (Chroma Research). Agent swarms combat this by:

- Distributing work across focused agents with clean context windows
- Persisting task state in files (not conversation history)
- Using orchestrator pattern: main session delegates, never accumulates
- Model-appropriate routing: Haiku for simple tasks, Sonnet/Opus for complex reasoning
- Disposable agents: return only results to orchestrator, then terminate

### Complementary Tools for Context Efficiency

- **CLAUDE.md**: Persistent project instructions (outside context window)
- **Session Memory**: Auto-extracts important details, surfaces in new sessions
- **Artifacts**: Separate substantive work from navigation discussions
- **Skills**: Load metadata first, full instructions only when needed
- **Subagents**: Isolated context windows per task domain
- **`/remember`**: Bridges session memory with permanent project knowledge in `CLAUDE.local.md`

Source: [ClaudeFast - Session Memory](https://claudefa.st/blog/guide/mechanics/session-memory)

---

## Comprehensive Source Index

### Official Documentation
- [Hooks Reference](https://code.claude.com/docs/en/hooks)
- [Best Practices](https://code.claude.com/docs/en/best-practices)
- [Headless Mode](https://code.claude.com/docs/en/headless)
- [Agent Teams](https://code.claude.com/docs/en/agent-teams)
- [Subagents](https://code.claude.com/docs/en/sub-agents)
- [Context Windows](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [Sessions (Agent SDK)](https://platform.claude.com/docs/en/agent-sdk/sessions)
- [Rate Limits](https://platform.claude.com/docs/en/api/rate-limits)
- [Usage and Cost API](https://platform.claude.com/docs/en/build-with-claude/usage-cost-api)

### Blog Posts and Articles
- [Serenities AI - Claude Code Hooks Guide 2026 (Dev.to)](https://dev.to/serenitiesai/claude-code-hooks-guide-2026-automate-your-ai-coding-workflow-dde)
- [Blake Crosley - 5 Production Hooks From Scratch](https://blakecrosley.com/blog/claude-code-hooks-tutorial)
- [Lukasz Fryc - Complete Guide with 20+ Examples (Dev.to)](https://dev.to/lukaszfryc/claude-code-hooks-complete-guide-with-20-ready-to-use-examples-2026-dcg)
- [JP Caparas - Git Automation Guide (Reading.sh)](https://reading.sh/claude-code-hooks-a-bookmarkable-guide-to-git-automation-11b4516adc5d)
- [Simone Callegari - Tasks, Sessions, Swarms (Dev.to)](https://dev.to/simone_callegari_1f56a902/claude-code-new-tasks-persisting-between-sessions-and-swarms-of-agents-against-context-rot-5dan)
- [Brian Redmond - Multi-Agent Orchestration Part 3 (Dev.to)](https://dev.to/bredmond1019/multi-agent-orchestration-running-10-claude-instances-in-parallel-part-3-29da)
- [Zen Van Riel - Claude Code Swarms](https://zenvanriel.com/ai-engineer-blog/claude-code-swarms-multi-agent-orchestration/)
- [Black Dog Labs - Handoff Protocol](https://blackdoglabs.io/blog/claude-code-decoded-handoff-protocol)
- [HyperDev Matsuoka - Context Protection](https://hyperdev.matsuoka.com/p/how-claude-code-got-better-by-protecting)
- [Limited Edition Jonathan - Context Limit Guide (Substack)](https://limitededitionjonathan.substack.com/p/ultimate-guide-fixing-claude-hit-a94)
- [Sankalp's Blog - Claude Code 2.0 Experience](https://sankalp.bearblog.dev/my-experience-with-claude-code-20-and-how-to-get-better-at-using-coding-agents/)
- [CodeLynx - Usage Limits in Statusline](https://codelynx.dev/posts/claude-code-usage-limits-statusline)
- [Sealos - Grafana Metrics Dashboard](https://sealos.io/blog/claude-code-metrics/)
- [Shipyard - Track Claude Code Usage](https://shipyard.build/blog/claude-code-track-usage/)
- [eesel.ai - Claude Code Hooks Practical Guide](https://www.eesel.ai/blog/hooks-in-claude-code)
- [eesel.ai - Claude Code Automation Guide](https://www.eesel.ai/blog/claude-code-automation)
- [Angelo Lima - CI/CD and Headless Mode](https://angelo-lima.fr/en/claude-code-cicd-headless-en/)
- [Apidog - Mastering Usage Limits](https://apidog.com/blog/claude-code-usage-monitor/)
- [Hypereal - Monitor Usage & Costs (2026)](https://hypereal.tech/a/claude-code-usage-monitor)
- [ikangai - Agentic Coding Tools Setup Guide](https://www.ikangai.com/agentic-coding-tools-explained-complete-setup-guide-for-claude-code-aider-and-cli-based-ai-development/)
- [TURION.AI - Multi-Agents and Subagents Guide](https://turion.ai/blog/claude-code-multi-agents-subagents-guide/)

### ClaudeFast Guides
- [Session Memory](https://claudefa.st/blog/guide/mechanics/session-memory)
- [Agent Teams Guide](https://claudefa.st/blog/guide/agents/agent-teams)
- [Sub-Agent Best Practices](https://claudefa.st/blog/guide/agents/sub-agent-best-practices)
- [Async Workflows](https://claudefa.st/blog/guide/agents/async-workflows)
- [Task Management](https://claudefa.st/blog/guide/development/task-management)
- [Hooks Guide (All 12 Events)](https://claudefa.st/blog/tools/hooks/hooks-guide)
- [Context Recovery Hook](https://claudefa.st/blog/tools/hooks/context-recovery-hook)

### Courses and Tutorials
- [Steve Kinney - Claude Code Hook Examples](https://stevekinney.com/courses/ai-development/claude-code-hook-examples)
- [DataCamp - Claude Code Hooks Tutorial](https://www.datacamp.com/tutorial/claude-code-hooks)
- [SFEIR Institute - Headless Mode and CI/CD](https://institute.sfeir.com/en/claude-code/claude-code-headless-mode-and-ci-cd/cheatsheet/)
- [ClaudeWorld - Hooks Development Guide](https://claude-world.com/articles/hooks-development-guide/)

### GitHub Repositories and Tools
- [coder/agentapi](https://github.com/coder/agentapi) -- HTTP API for Claude Code, Goose, Aider, Gemini, Amp, Codex
- [yigitkonur/cli-continues](https://github.com/yigitkonur/cli-continues) -- Resume any AI coding session in another tool
- [parcadei/Continuous-Claude-v3](https://github.com/parcadei/Continuous-Claude-v3) -- Context management with ledgers and handoffs
- [willseltzer/claude-handoff](https://github.com/willseltzer/claude-handoff) -- Session handoff tool
- [Dicklesworthstone/post_compact_reminder](https://github.com/Dicklesworthstone/post_compact_reminder) -- Post-compaction context injection
- [mvara-ai/precompact-hook](https://github.com/mvara-ai/precompact-hook) -- Pre-compaction recovery summaries
- [disler/claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery) -- Master Claude Code Hooks
- [wesammustafa/Claude-Code-Everything-You-Need-to-Know](https://github.com/wesammustafa/Claude-Code-Everything-You-Need-to-Know) -- All-in-one guide
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) -- 500+ cross-agent skills
- [barkain/claude-code-workflow-orchestration](https://github.com/barkain/claude-code-workflow-orchestration) -- Multi-step workflow orchestration
- [wshobson/agents](https://github.com/wshobson/agents) -- Intelligent automation and multi-agent orchestration
- [Maciek-roboblog/Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) -- Real-time usage monitor
- [TylerGallenbeck/claude-code-limit-tracker](https://github.com/TylerGallenbeck/claude-code-limit-tracker) -- Quota tracking in statusline
- [kieranklaassen/claude-code-swarm-orchestration (Gist)](https://gist.github.com/kieranklaassen/4f2aba89594a4aea4ad64d753984b2ea) -- Swarm orchestration skill

### Social Media / Threads
- [Boris Cherny (Claude Code creator) - Twitter/X thread](https://twitter-thread.com/t/2007179832300581177) -- Personal setup and hook recommendations
- [Boris Cherny - Threads post](https://www.threads.com/@boris_cherny/post/DTBVlMIkpcm/) -- Same content on Threads

### Marketplaces
- [Session Handoff for Claude Code (MCPMarket)](https://mcpmarket.com/tools/skills/session-handoff-context-manager)
- [Handoff Context Skill (MCPMarket)](https://mcpmarket.com/tools/skills/handoff-context)
- [Headless Mode Skill (MCPMarket)](https://mcpmarket.com/tools/skills/headless-mode-ci-cd-integration)

### GitHub Issues (Feature Requests)
- [#18645 - Session Export/Import for Cross-Machine Portability](https://github.com/anthropics/claude-code/issues/18645)
- [#11455 - Session Handoff / Continuity Support](https://github.com/anthropics/claude-code/issues/11455)
- [#14258 - PostCompact Hook Event](https://github.com/anthropics/claude-code/issues/14258)
- [#17237 - PreCompact and PostCompact Hooks](https://github.com/anthropics/claude-code/issues/17237)
- [#15923 - Pre-compaction Hook to Preserve History](https://github.com/anthropics/claude-code/issues/15923)
- [#6559 - Context Limit Exceeded Bug](https://github.com/anthropics/claude-code/issues/6559)

### Platform Announcements
- [GitHub Blog - Agent HQ](https://github.blog/news-insights/company-news/pick-your-agent-use-claude-and-codex-on-agent-hq/)
- [VS Code Blog - Unified Agent Experience](https://code.visualstudio.com/blogs/2025/11/03/unified-agent-experience)
- [VS Code Blog - Multi-Agent Development](https://code.visualstudio.com/blogs/2026/02/05/multi-agent-development)
