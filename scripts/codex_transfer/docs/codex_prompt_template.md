# Codex Prompt Template for Session Transfer

This file contains the prompt template that is piped via stdin to `codex exec` when transferring a task from Claude Code to Codex CLI.

---

## Template

Variables are marked with `{{VARIABLE_NAME}}`. The launcher script substitutes these before piping to codex.

```
You are picking up a task that was started in a Claude Code session. Your job is to continue the work described in the handoff document.

## Step 1: Read Repo Conventions

Read the file `AGENTS.md` at the repository root. It defines your role, conventions, and any child-agent configurations. Also read `CLAUDE.md` for additional codebase guidance. Follow all instructions in these files.

## Step 2: Explore the Codebase

Spawn sub-agents (codebase-explorers) to review the repository in parallel. Each sub-agent should focus on a different area:

**Sub-agent 1 -- Architecture Overview:**
- Read `rlm_adk_docs/UNDERSTAND.md` (the single entrypoint for understanding this codebase)
- Follow its progressive disclosure index to identify the key architectural branches
- Summarize the architecture, key abstractions, and module boundaries

**Sub-agent 2 -- Source Code Review:**
- Explore `rlm_adk/` to understand the current implementation
- Pay special attention to: `orchestrator.py`, `agent.py`, `dispatch.py`, `tools/repl_tool.py`, `callbacks/`, `plugins/`, `state.py`
- Identify patterns, conventions, and any state mutation rules

**Sub-agent 3 -- Test Suite Review:**
- Explore `tests_rlm_adk/` to understand test patterns and coverage
- Review replay fixtures in `tests_rlm_adk/replay/`
- Note any test utilities or mock patterns

**Sub-agent 4 -- Claude Code Session Context:**
- Read the Claude Code project memory at `{{CLAUDE_MEMORY_PATH}}`
- Review the Claude Code session data directory at `{{CLAUDE_SESSION_DIR}}`
- Extract any relevant context about recent work, known issues, and decisions made
- Pay attention to MEMORY.md for accumulated project knowledge

Wait for all sub-agents to complete before proceeding.

## Step 3: Read the Handoff Document

Read the handoff document at: `{{HANDOFF_DOC_PATH}}`

This document describes:
- What task was being worked on
- Current progress and status
- Remaining work to be done
- Any blockers or decisions needed
- Key files that were modified or are relevant

## Step 4: Continue the Task

Using the context gathered from steps 1-3, continue the task described in the handoff document. Follow all conventions from AGENTS.md and CLAUDE.md, particularly:

- **State Mutation Rules (AR-CRIT-001):** NEVER write `ctx.session.state[key] = value` in dispatch closures. Use `tool_context.state`, `callback_context.state`, `EventActions(state_delta={})`, or `output_key`.
- **Testing:** Run tests with `.venv/bin/python -m pytest tests_rlm_adk/ -v` after making changes.
- **Linting:** Run `ruff check rlm_adk/ tests_rlm_adk/` and `ruff format --check rlm_adk/ tests_rlm_adk/` before considering the task complete.
- **Commits:** Follow the existing commit message style visible in `git log --oneline -20`.

## Additional Context

{{ADDITIONAL_CONTEXT}}

## Output

When you complete the task (or reach a stopping point), write a completion report to `{{OUTPUT_REPORT_PATH}}` that includes:
1. Summary of what was accomplished
2. Files created or modified (with absolute paths)
3. Test results
4. Any remaining work or known issues
5. Decisions made and rationale
```

---

## Variable Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `{{HANDOFF_DOC_PATH}}` | Absolute path to the handoff document from Claude Code | `/home/rawley-stanhope/dev/rlm-adk/scripts/codex_transfer/handoff.md` |
| `{{CLAUDE_MEMORY_PATH}}` | Path to Claude Code's MEMORY.md for this project | `/home/rawley-stanhope/.claude/projects/-home-rawley-stanhope-dev-rlm-adk/memory/MEMORY.md` |
| `{{CLAUDE_SESSION_DIR}}` | Directory containing Claude Code session JSONL files | `/home/rawley-stanhope/.claude/projects/-home-rawley-stanhope-dev-rlm-adk/` |
| `{{ADDITIONAL_CONTEXT}}` | Optional extra instructions or context (can be empty) | `"Focus on the dispatch.py changes first"` |
| `{{OUTPUT_REPORT_PATH}}` | Where codex should write its completion report | `/home/rawley-stanhope/dev/rlm-adk/scripts/codex_transfer/completion_report.md` |
