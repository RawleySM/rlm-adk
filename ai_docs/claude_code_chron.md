# Claude Code Scheduled Tasks & Cron Jobs

Anthropic has recently introduced native support for scheduled tasks and recurring prompts in **Claude Code** (starting around v2.1.71). This allows developers to automate background tasks directly within their CLI workflow, such as monitoring pull requests, running background builds, or performing periodic code reviews.

## How It Works

Claude Code handles scheduling in two primary ways:

1. **Native Session Loops (`/loop`)**: This is the built-in, session-scoped method. It runs a task repeatedly at a specified interval *as long as your Claude Code session remains open*. 
2. **System-Level Automation**: This involves leveraging your operating system's native schedulers (like `cron` on Linux) to execute Claude Code commands using the `claude -p` (print/headless) flag. This approach survives session restarts and system reboots.

### Key Architectural Details
- **Execution Model**: Scheduled tasks in native loops fire between your active turns. If Claude is busy, the task waits in a queue until the current operation finishes.
- **Token Usage**: Every loop execution triggers a new prompt. Frequent loops (e.g., every 1 minute) can accumulate high token costs.
- **Limits**: A single session typically handles up to 50 concurrent tasks, and native recurring tasks usually expire automatically after 3 days to prevent runaway billing.

## How to Set Up

### 1. Using Native `/loop` (Session-Scoped)

You can invoke a loop directly in the Claude Code prompt using the `/loop` command.

**Syntax:**
`/loop [interval] [prompt]`

**Interval Units:**
- `s` (seconds, often rounded up to the nearest minute)
- `m` (minutes)
- `h` (hours)
- `d` (days)

**Examples:**
- `/loop 5m check if the deployment finished and tell me what happened`
- `/loop 1h /review-pr 1234`
- `/loop in 2 hours remind me to merge the PR` (One-time delayed execution)

**Management:**
Ask Claude:
- *"what scheduled tasks do I have?"*
- *"cancel the loop monitoring the deployment"*

### 2. Using System Cron (System-Level & Persistent)

For tasks that need to run overnight or indefinitely without an active interactive session, you wrap Claude Code in a shell script and use standard Linux `cron`.

**Command Pattern:**
```bash
claude -p "Review the latest changes in the git log and summarize them" > /tmp/claude_daily_summary.md
```

**Setting up in Linux:**
1. Open crontab: `crontab -e`
2. Add an entry (e.g., run every weekday at 9 AM):
   `0 9 * * 1-5 cd /home/rawley-stanhope/dev/rlm-adk && claude -p "Run the test suite and summarize failures" > tests.log`

## System Nuances: Linux vs. Windows

Since your operating system is **Linux**, here are the nuances to be aware of compared to Windows:

| Feature | Linux (Your System) | Windows |
| :--- | :--- | :--- |
| **Native Scheduler** | `cron` or `systemd` timers. | Task Scheduler. |
| **Persistence** | You can use `tmux` or `screen` to keep an interactive Claude Code session alive indefinitely, running `/loop` tasks overnight. | Requires third-party tools or running in WSL2 for similar `tmux` behavior. |
| **Permissions** | Cron jobs running `claude` will execute as the user owning the crontab. Ensure that environment variables (like your `ANTHROPIC_API_KEY`) are explicitly set in the cron environment, as cron does not load standard bash profiles by default. | Task Scheduler can run tasks as SYSTEM or specific users, with its own credential management. |
| **Piping Output** | Linux excels at piping Claude's headless output (`claude -p "..." | grep "Error"`) directly into other Unix utilities. | Powershell piping handles text differently, sometimes requiring string conversions. |

**Linux Pro-Tip for Cron:** Always export your API key in the bash script that cron calls:
```bash
#!/bin/bash
export ANTHROPIC_API_KEY="your-key-here"
cd /path/to/project
claude -p "Analyze the server logs" >> server_analysis.md
```

## Advanced Patterns Emerging from the Community

Developers on Reddit, Dev.to, and Hacker News are sharing sophisticated ways to use these new capabilities:

### 1. The "Verification Loop" (Test-Driven Agent)
Instead of Claude just writing code and waiting for you, developers set up a background loop to constantly test the implementation.
- **Workflow:** An interactive Claude instance writes code. A background `/loop` watches for file changes, runs `pytest` (or your test runner), and pipes errors back into the chat context. 
- **Benefit:** The agent gets immediate feedback on its own work without blocking the main conversational thread.

### 2. Auto-Memory Integration
Power users combine `/loop` with the Auto Memory feature. 
- A loop is set to monitor application logs or error outputs. When it spots recurring issues, it saves the pattern and the solution to the project's `MEMORY.md` file. Future interactive prompts or other agents automatically read this memory, speeding up debugging.

### 3. Multi-Agent Orchestration via Bash Parallelism
Using the CLI's bash execution capabilities, developers are using Claude Code as a supervisor.
- Claude spawns other CLI tools (like `gemini-cli` or `codex-cli`) in the background.
- It can delegate specific research or specialized refactoring tasks to these other agents and wait for their output files to update, acting as an orchestrator for a multi-agent system.

### 4. The "Bilu Board" State Machine
An autonomous workflow where a background system cron job continuously reads a `TODO.md` file. 
- The script reads the top task and executes `claude -p "Fix the following task: [Task Details]"`.
- Claude commits the result and updates the `TODO.md` file to mark it as done.
- The loop repeats until the file is empty, creating an autonomous asynchronous worker.

### 5. Safeguarding with Environment Variables
To prevent expensive accidents in automated or shared environments, the community recommends using the environment variable `CLAUDE_CODE_DISABLE_CRON=1` to enforce that no background loops can be initialized during sensitive or highly-token-intensive sessions.