# CLAUDE.md

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

## Testing

```bash
# Default test run (~28 contract tests, ~22s) — USE THIS
.venv/bin/python -m pytest tests_rlm_adk/

# Run specific test file(s) — USE THIS for TDD / focused work
.venv/bin/python -m pytest tests_rlm_adk/test_your_file.py -x -q
```

**NEVER run `pytest -m ""`** for routine verification. The `-m ""` flag disables marker filtering and runs the **full 970+ test suite** (5+ minutes). It is reserved for pre-merge CI validation, not for development iteration or regression checks. For regression checking, run the default suite (no `-m` flag) plus your specific test file(s).

## State Mutation Rules (AR-CRIT-001)

**NEVER** write `ctx.session.state[key] = value` in dispatch closures — this bypasses ADK event tracking. Correct mutation paths:
- `tool_context.state[key]` (in tools)
- `callback_context.state[key]` (in callbacks)
- `EventActions(state_delta={...})` (in events)
- `output_key` (for agent output)

Dispatch closures use **local accumulators** + `flush_fn()` to snapshot into `tool_context.state` after each REPL execution.

