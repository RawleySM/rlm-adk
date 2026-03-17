# Codex Transfer System: Session Handoff to Headless Codex CLI

*2026-03-14T02:24:15Z by Showboat 0.6.0*
<!-- showboat-id: aff0177a-d29b-431f-a8f6-d9cfc988b6cc -->

The Codex Transfer system monitors Claude Code OAuth usage quotas and, when approaching limits, automatically generates a structured handoff document and launches headless Codex CLI to continue the work. This demo proves all components work end-to-end, including real codex exec invocations with full-access permissions and sub-agent features.

## Component Inventory

The system comprises 5 modules, a bash launcher, a prompt template, and 145 tests across unit, integration, and real codex CLI e2e suites.

```bash
find scripts/codex_transfer/ -name "*.py" -not -path "*__pycache__*" | sort
```

```output
scripts/codex_transfer/codex_launcher.py
scripts/codex_transfer/__init__.py
scripts/codex_transfer/quota_poller.py
scripts/codex_transfer/session_transfer_gate.py
scripts/codex_transfer/session_transfer_monitor.py
scripts/codex_transfer/statusline_quota.py
scripts/codex_transfer/tests/conftest.py
scripts/codex_transfer/tests/e2e/conftest.py
scripts/codex_transfer/tests/e2e/__init__.py
scripts/codex_transfer/tests/e2e/test_codex_headless.py
scripts/codex_transfer/tests/e2e/test_codex_prompt_quality.py
scripts/codex_transfer/tests/e2e/test_e2e_flow.py
scripts/codex_transfer/tests/__init__.py
scripts/codex_transfer/tests/test_codex_launcher.py
scripts/codex_transfer/tests/test_quota_poller.py
scripts/codex_transfer/tests/test_session_transfer_gate.py
scripts/codex_transfer/tests/test_session_transfer_monitor.py
scripts/codex_transfer/tests/test_statusline_quota.py
```

```bash
grep -c "def test_" scripts/codex_transfer/tests/test_*.py scripts/codex_transfer/tests/e2e/test_*.py 2>/dev/null | awk -F: '{s+=$2} END{print s " total test functions"}'
```

```output
145 total test functions
```

## 1. Unit Tests (95 tests across 5 modules)

All modules implemented via strict red/green TDD. Running the full unit test suite:

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest scripts/codex_transfer/tests/ -q -o "addopts=" 2>&1 | tail -1 | sed "s/ in [0-9.]*s.*//"
```

```output
145 passed
```

## 2. E2E Integration Tests (35 fast tests)

These tests prove the bridge file lifecycle, quota-to-monitor integration, threshold triggering, handoff doc detection, and full pipeline flow — all without calling the codex CLI (fast).

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest scripts/codex_transfer/tests/e2e/ -q -o "addopts=" -m "not codex" 2>&1 | tail -1 | sed "s/ in [0-9.]*s.*//"
```

```output
35 passed, 15 deselected
```

## 3. Codex CLI Headless E2E Tests (11 real invocations)

These tests invoke the REAL codex exec CLI with --dangerously-bypass-approvals-and-sandbox (full access / yolo mode), --enable multi_agent, and --enable child_agents_md. They prove headless execution, stdin prompt piping, JSON event streaming, output file capture, working directory override, sub-agent spawning, and detached (fire-and-forget) launch patterns.

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest scripts/codex_transfer/tests/e2e/test_codex_headless.py -q -o "addopts=" 2>&1 | tail -1 | sed "s/ in [0-9.]*s.*//"
```

```output
11 passed
```

## 4. Codex Launcher Script (codex_launch.sh)

The launcher script uses setsid for detached execution, passes --dangerously-bypass-approvals-and-sandbox for full access, enables multi_agent and child_agents_md features, pipes the prompt via stdin heredoc, and captures JSONL events + final output.

```bash
grep -n "dangerously-bypass\|enable multi_agent\|enable child_agents_md\|setsid\|start_new_session\|full-auto\|CODEX_BIN\|LOG_EVENTS\|LOG_RESULT" scripts/codex_transfer/codex_launch.sh
```

```output
14:#   CODEX_BIN            -- Path to codex binary (default: ~/.npm-global/bin/codex)
24:CODEX_BIN="${CODEX_BIN:-$HOME/.npm-global/bin/codex}"
52:if [ ! -x "$CODEX_BIN" ]; then
53:    echo "ERROR: Codex CLI not found at: $CODEX_BIN"
65:LOG_EVENTS="${LOG_DIR}/${RUN_ID}_events.jsonl"
67:LOG_RESULT="${LOG_DIR}/${RUN_ID}_result.md"
97:    echo "Event Log:       ${LOG_EVENTS}"
99:    echo "Result File:     ${LOG_RESULT}"
109:setsid "$CODEX_BIN" exec \
110:    --dangerously-bypass-approvals-and-sandbox \
111:    --enable multi_agent \
112:    --enable child_agents_md \
116:    -o "$LOG_RESULT" \
119:    > "$LOG_EVENTS" 2>"$LOG_STDERR" &
133:echo "  tail -f ${LOG_EVENTS}              # JSONL event stream"
134:echo "  cat ${LOG_RESULT}                  # final agent message (when done)"
```

## 5. Prompt Template with Sub-Agent Codebase Explorers

The prompt template instructs Codex to spawn 4 parallel sub-agents (codebase-explorers) that review the architecture, source code, test suite, and Claude Code session context before continuing the handoff task.

```bash
grep -n "Sub-agent\|codebase-explorer\|Spawn sub-agent\|AGENTS.md\|CLAUDE.md\|MEMORY.md" scripts/codex_transfer/docs/codex_prompt_template.md
```

```output
16:Read the file `AGENTS.md` at the repository root. It defines your role, conventions, and any child-agent configurations. Also read `CLAUDE.md` for additional codebase guidance. Follow all instructions in these files.
20:Spawn sub-agents (codebase-explorers) to review the repository in parallel. Each sub-agent should focus on a different area:
22:**Sub-agent 1 -- Architecture Overview:**
27:**Sub-agent 2 -- Source Code Review:**
32:**Sub-agent 3 -- Test Suite Review:**
37:**Sub-agent 4 -- Claude Code Session Context:**
41:- Pay attention to MEMORY.md for accumulated project knowledge
58:Using the context gathered from steps 1-3, continue the task described in the handoff document. Follow all conventions from AGENTS.md and CLAUDE.md, particularly:
86:| `{{CLAUDE_MEMORY_PATH}}` | Path to Claude Code's MEMORY.md for this project | `/home/rawley-stanhope/.claude/projects/-home-rawley-stanhope-dev-rlm-adk/memory/MEMORY.md` |
```

## 6. Codex Launcher Python Module

The codex_launcher.py module builds the prompt with codebase-explorer instructions and spawns codex as a detached subprocess using Popen(start_new_session=True).

```bash
grep -n "dangerously-bypass\|start_new_session\|multi_agent\|child_agents_md\|codebase-explorer\|sub-agent\|Spawn.*agent\|AGENTS.md" scripts/codex_transfer/codex_launcher.py
```

```output
17:    "IMPORTANT: Before starting any work, spawn agent codebase-explorers to "
58:        f"1. Spawn agent codebase-explorers to review the codebase at "
75:    Spawns a detached process using ``subprocess.Popen(start_new_session=True)``
94:        "--dangerously-bypass-approvals-and-sandbox",
95:        "--enable", "multi_agent",
96:        "--enable", "child_agents_md",
104:        start_new_session=True,
```

## Summary

All 145 tests pass across 3 test suites:
- 95 unit tests (red/green TDD) covering quota_poller, session_transfer_monitor, session_transfer_gate, codex_launcher, statusline_quota
- 35 fast E2E tests covering bridge file lifecycle, quota-to-monitor integration, threshold triggers, handoff detection, full pipeline flow
- 15 codex CLI e2e tests proving real headless execution with full-access permissions and sub-agent feature flags

The codex_launch.sh script and codex_launcher.py module both spawn codex exec with --dangerously-bypass-approvals-and-sandbox --enable multi_agent --enable child_agents_md, and the prompt template directs Codex to spawn 4 codebase-explorer sub-agents covering architecture, source, tests, and Claude Code session context.
