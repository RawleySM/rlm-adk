# Codex CLI Headless Reference

> Codex CLI v0.114.0 (`~/.npm-global/bin/codex`)
> Config: `~/.codex/config.toml`

## Core Command

The headless (non-interactive) entry point is `codex exec`:

```bash
codex exec [OPTIONS] [PROMPT]
```

If `PROMPT` is omitted or set to `-`, instructions are read from **stdin**.

---

## Key Flags

### Sandbox / Approval Bypass

| Flag | Effect |
|------|--------|
| `--dangerously-bypass-approvals-and-sandbox` | Skip ALL confirmation prompts, execute commands without ANY sandboxing. The most permissive mode. |
| `-s danger-full-access` | Sandbox policy that grants full filesystem and network access, but still shows approval prompts for commands unless combined with `--full-auto`. |
| `--full-auto` | Convenience alias: sets approvals to on-request + sandbox to `workspace-write`. Less permissive than danger-full-access. |

**For true YOLO headless operation, use `--dangerously-bypass-approvals-and-sandbox`.** This is the only flag that eliminates ALL interactive prompts.

### Feature Flags

| Flag | Effect |
|------|--------|
| `--enable <FEATURE>` | Enable a feature flag (repeatable). Equivalent to `-c features.<name>=true`. |
| `--disable <FEATURE>` | Disable a feature flag (repeatable). |

Key experimental features (as of v0.114.0):

| Feature | Status | Purpose |
|---------|--------|---------|
| `multi_agent` | experimental | Enables sub-agent spawning (agent can create child agents) |
| `child_agents_md` | under development | Enables AGENTS.md-driven child agent configuration |
| `apps` | experimental | App server functionality |
| `js_repl` | experimental | JavaScript REPL tool |
| `memories` | under development | Persistent memory across sessions |

### Model Selection

| Flag | Effect |
|------|--------|
| `-m <MODEL>` | Override the model (e.g., `-m gpt-5.4`, `-m o3`) |
| `-c model_reasoning_effort="high"` | Set reasoning effort level |

### Working Directory

| Flag | Effect |
|------|--------|
| `-C <DIR>` | Set the agent's working root directory |
| `--add-dir <DIR>` | Additional writable directories (repeatable) |
| `--skip-git-repo-check` | Allow running outside a git repository |

### Output

| Flag | Effect |
|------|--------|
| `-o <FILE>` / `--output-last-message <FILE>` | Write the agent's final message to a file |
| `--json` | Print all events to stdout as JSONL (structured output) |
| `--output-schema <FILE>` | Path to JSON Schema constraining the model's final response shape |

### Session Management

| Flag | Effect |
|------|--------|
| `--ephemeral` | Do not persist session files to disk |

### Config Overrides

The `-c` flag accepts dotted TOML paths for arbitrary config overrides:

```bash
codex exec -c model="o3" -c 'sandbox_permissions=["disk-full-read-access"]' ...
```

---

## Piping a Prompt via stdin

When the prompt is long or dynamically generated, pipe it via stdin. Either omit the positional `PROMPT` argument or pass `-` explicitly:

```bash
# Omit PROMPT argument -- reads from stdin
echo "Analyze this codebase" | codex exec --dangerously-bypass-approvals-and-sandbox -C /path/to/repo

# Explicit stdin marker
cat prompt.txt | codex exec --dangerously-bypass-approvals-and-sandbox -C /path/to/repo -

# Heredoc
codex exec --dangerously-bypass-approvals-and-sandbox -C /path/to/repo - <<'EOF'
Your multi-line prompt here.
EOF
```

---

## Capturing Output

### Final message to a file

```bash
codex exec -o result.md --dangerously-bypass-approvals-and-sandbox -C /path "do the thing"
```

### Full JSONL event stream

```bash
codex exec --json --dangerously-bypass-approvals-and-sandbox -C /path "do the thing" > events.jsonl 2>stderr.log
```

### Both

```bash
codex exec --json -o result.md --dangerously-bypass-approvals-and-sandbox -C /path "do the thing" > events.jsonl 2>stderr.log
```

---

## Running Detached (Survives Parent Exit)

### Option A: nohup

```bash
nohup codex exec --dangerously-bypass-approvals-and-sandbox \
  -C /path/to/repo \
  -o /tmp/codex_result.md \
  --json \
  - < prompt.txt \
  > /tmp/codex_events.jsonl 2>/tmp/codex_stderr.log &

echo "Codex PID: $!"
```

### Option B: setsid (fully detached from terminal)

```bash
setsid codex exec --dangerously-bypass-approvals-and-sandbox \
  -C /path/to/repo \
  -o /tmp/codex_result.md \
  --json \
  - < prompt.txt \
  > /tmp/codex_events.jsonl 2>/tmp/codex_stderr.log &
```

### Option C: tmux / screen session

```bash
tmux new-session -d -s codex-transfer \
  'codex exec --dangerously-bypass-approvals-and-sandbox -C /path/to/repo -o result.md - < prompt.txt 2>stderr.log'
```

---

## Enabling Sub-Agents / Multi-Agent

Sub-agent support requires two feature flags:

1. **`multi_agent`** (experimental, stable enough) -- enables the agent to spawn child agents
2. **`child_agents_md`** (under development) -- enables reading `AGENTS.md` files to configure child agents with specialized roles

Enable via CLI flags:

```bash
codex exec --enable multi_agent --enable child_agents_md ...
```

Or via config overrides:

```bash
codex exec -c features.multi_agent=true -c features.child_agents_md=true ...
```

Or permanently in `~/.codex/config.toml`:

```toml
[features]
multi_agent = true
child_agents_md = true
```

---

## Complete Examples

### Minimal headless with full access

```bash
codex exec --dangerously-bypass-approvals-and-sandbox -C ~/dev/rlm-adk "Analyze the codebase structure"
```

### Full-featured headless with sub-agents, output capture, detached

```bash
nohup codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --enable multi_agent \
  --enable child_agents_md \
  -m gpt-5.4 \
  -C /home/rawley-stanhope/dev/rlm-adk \
  -o /tmp/codex_result.md \
  --json \
  - < /tmp/codex_prompt.txt \
  > /tmp/codex_events.jsonl 2>/tmp/codex_stderr.log &
```

### With config overrides for reasoning effort

```bash
codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --enable multi_agent \
  --enable child_agents_md \
  -c model_reasoning_effort="high" \
  -m gpt-5.4 \
  -C /home/rawley-stanhope/dev/rlm-adk \
  -o result.md \
  "Read AGENTS.md and then implement the feature described in handoff.md"
```

### Ephemeral run (no session persistence)

```bash
codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --ephemeral \
  -C /home/rawley-stanhope/dev/rlm-adk \
  "Quick one-off analysis"
```

### Resume a previous session

```bash
codex exec resume --last
codex exec resume <SESSION_ID>
```
