# Claude Code Remote Control

> Continue a local Claude Code session from your phone, tablet, or any browser.
> Works with claude.ai/code and the Claude mobile app (iOS/Android).

**Released**: February 25, 2026 (research preview)

## Overview

Remote Control connects claude.ai/code or the Claude mobile app to a Claude Code
session running on your local machine. Start a task at your desk, then pick it up
from your phone or a browser on another computer. Code never leaves your machine --
only messages and tool results travel through Anthropic's servers.

## Requirements

- **Subscription**: Max plan required (Pro plan support coming soon). API keys not supported.
- **Authentication**: Run `claude` and use `/login` to sign in through claude.ai.
- **Workspace trust**: Run `claude` in your project directory at least once to accept the workspace trust dialog.
- **Not available** on Team or Enterprise plans.

## Quick Start

### Option A: New Remote Control session

```bash
claude remote-control
```

Starts a new session in the terminal, displays a session URL and a QR code
(press spacebar to toggle QR). Stays running and waits for remote connections.

**Flags**:
- `--verbose` -- show detailed connection and session logs
- `--sandbox` / `--no-sandbox` -- enable or disable filesystem/network sandboxing (off by default)

### Option B: From an existing session

If you're already in a Claude Code session:

```
/remote-control
```

Shorthand: `/rc`

This carries over your current conversation history and displays the session URL + QR code.
The `--verbose`, `--sandbox`, and `--no-sandbox` flags are **not** available with this in-session command.

**Tip**: Use `/rename` before `/remote-control` to give the session a descriptive name
for easy identification across devices.

## Connecting from Another Device

Three ways to connect:

1. **Session URL** -- open the URL shown in the terminal in any browser (goes to claude.ai/code).
2. **QR code** -- scan the QR code to open directly in the Claude mobile app.
3. **Session list** -- open claude.ai/code or the Claude app and find the session by name.
   Remote Control sessions show a computer icon with a green status dot when online.

If you don't have the Claude app, use `/mobile` inside Claude Code to display a download QR code
for iOS or Android.

## Auto-Enable for All Sessions

To enable Remote Control automatically for every session:

1. Run `/config` inside Claude Code.
2. Set **Enable Remote Control for all sessions** to `true`.
3. Set back to `false` to disable.

Each Claude Code instance supports one remote session at a time. Multiple instances each
get their own environment and session.

## What Stays Local

Your full local environment stays available during remote sessions:
- Filesystem access
- MCP servers and tools
- Project configuration (`.claude/` settings)
- Credentials and environment variables

## What Travels Over the Wire

Only two things are transmitted through Anthropic's servers:
- Messages you type
- Tool results Claude generates

## Connection & Security

- **Outbound HTTPS only** -- your machine never opens inbound ports.
- **TLS transport** -- same security as any Claude Code session via the Anthropic API.
- **Short-lived credentials** -- multiple credentials, each scoped to a single purpose, expiring independently.
- **Auto-reconnect** -- if your laptop sleeps or network drops, the session reconnects automatically when the machine comes back online.

## Remote Control vs Claude Code on the Web

| Aspect                | Remote Control              | Claude Code on the Web       |
|-----------------------|-----------------------------|------------------------------|
| **Execution**         | Your local machine          | Anthropic cloud infra        |
| **Local env access**  | Full (files, MCP, tools)    | None (cloud sandbox)         |
| **Use case**          | Continue local work remotely | Kick off without local setup |
| **Parallel sessions** | One per CLI instance        | Multiple                     |

Use Remote Control when mid-task and want to continue from another device.
Use Claude Code on the web for repo work without cloning or parallel tasks.

## Limitations

- **One remote session at a time** per Claude Code instance.
- **Terminal must stay open** -- closing the terminal or stopping the `claude` process ends the session.
- **~10 minute timeout** -- if the machine is awake but unable to reach the network for more than roughly 10 minutes, the session times out and the process exits. Run `claude remote-control` again to restart.

## Pre-Remote-Control Workarounds (Historical)

Before Remote Control shipped, users relied on:
- **Tailscale** for secure tunneling
- **Termius / Termux** for mobile SSH access
- **tmux** for session persistence

These are no longer needed for the mobile-control use case.

## Sources

- [Claude Code Docs: Remote Control](https://code.claude.com/docs/en/remote-control)
- [VentureBeat: Anthropic releases Remote Control](https://venturebeat.com/orchestration/anthropic-just-released-a-mobile-version-of-claude-code-called-remote)
- [DevOps.com: Remote Control overview](https://devops.com/claude-code-remote-control-keeps-your-agent-local-and-puts-it-in-your-pocket/)
- [NxCode: Setup Guide + Tips](https://www.nxcode.io/resources/news/claude-code-remote-control-mobile-terminal-handoff-guide-2026)
