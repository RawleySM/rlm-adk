# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**IMPORTANT: Before starting any task, read `rlm_adk_docs/UNDERSTAND.md` first.** It is the single entrypoint for understanding this codebase. It provides a progressive disclosure index — identify which branch(es) your task touches, then read only the linked doc(s) for those branches. Do not read unrelated documentation files.

## Build & Run

```bash
# Install dependencies
uv sync

# Run the agent (ADK CLI)
.venv/bin/adk run rlm_adk

# Run with replay fixture
.venv/bin/adk run --replay tests_rlm_adk/replay/recursive_ping.json rlm_adk

# Lint
ruff check rlm_adk/ tests_rlm_adk/
ruff format --check rlm_adk/ tests_rlm_adk/
```

## State Mutation Rules (AR-CRIT-001)

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

Dispatch closures use **local accumulators** + `flush_fn()` to snapshot into `tool_context.state` after each REPL execution.
