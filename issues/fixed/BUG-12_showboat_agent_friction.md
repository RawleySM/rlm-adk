# BUG-12: Showboat Agent Friction -- Six Failure Modes When Claude Code Drives Showboat

**Date:** 2026-02-26
**Source:** Session trace `7726f950-a6ae-4de4-97f8-555d70be5d67.jsonl`, lines 1139-1232
**Severity:** Medium (no data loss, but significant token waste and context rot)
**Status:** Open -- informing skill design

## Summary

When Claude Code was asked to create a `demo.md` document using `uvx showboat`, the agent hit **6 distinct friction points** that required **4 `showboat pop` operations**, **3 full command rewrites**, and **2 verify-fix-verify cycles**. The showboat workflow ultimately succeeded, but burned approximately 15 extra tool calls and substantial output tokens on error recovery. Each friction point is a predictable, automatable failure that a skill should prevent.

---

## Friction Points

### 1. Pre-existing `demo.md` Blocks `showboat init`

- **What happened:** `uvx showboat init demo.md "Bug-009: AST Rewriter Double-Await Fix"` returned `error: file already exists: demo.md` (exit code 1).
- **Why:** A `demo.md` from a previous session was already present in the working directory. `showboat init` refuses to overwrite.
- **Impact:** 2 extra tool calls (`ls demo.md`, then `rm demo.md && uvx showboat init ...`). Minor token cost, but creates an avoidable error path.
- **Mitigation:** The skill should check for file existence before calling `init`. If the file exists, prompt the user or auto-generate a timestamped filename. Alternatively, use `showboat init --force` if/when such a flag is added.

### 2. F-String Backslash SyntaxError in `showboat exec python3`

- **What happened:** `uvx showboat exec demo.md python3 '<code>'` failed with `SyntaxError: f-string expression part cannot include a backslash` because the inline Python code contained `{\"await (await\" in src}` inside an f-string.
- **Why:** Python 3.12 does not allow backslash escapes inside f-string expression parts. The agent composed f-strings with escaped quotes (`\"`) in the expression portion, which is syntactically invalid. The bash-to-showboat-to-python quoting chain makes this nearly impossible to detect before execution.
- **Impact:** 1 failed `exec` + 1 `pop` + 1 full rewrite of the code block (~950 output tokens wasted on the first attempt). The rewrite replaced f-strings with separate `print()` calls and local variables.
- **Mitigation:** The skill instructions should include a rule: **Never use backslash escapes inside f-string expressions when passing code to `showboat exec python3`.** Prefer variable extraction: `val = "await (await" in src; print(f"Result: {val}")`. A preflight linter could also catch this.

### 3. `ModuleNotFoundError: No module named 'dotenv'` -- Wrong Python Interpreter

- **What happened:** `uvx showboat exec demo.md python3 '<code that imports rlm_adk>'` failed because showboat's `python3` resolved to the system Python, not the project's `.venv/bin/python3`. The import chain `rlm_adk.__init__ -> rlm_adk.agent -> dotenv` immediately failed.
- **Why:** `uvx showboat` runs in its own isolated environment. When it executes `python3`, it uses the system PATH, which does not include the project's virtualenv. The project has dependencies (`python-dotenv`, `google-adk`, etc.) that only exist in `.venv`.
- **Impact:** 1 failed `exec` + 1 `pop` + 1 full command restructure. The agent had to switch from `showboat exec demo.md python3 '<code>'` to `showboat exec demo.md bash '.venv/bin/python3 -c "<code>"'`, introducing an additional layer of quoting and escaping. This pattern persisted for all subsequent exec blocks (4 more), each requiring triple-escaped strings.
- **Mitigation:** The skill should detect the presence of a `.venv` and automatically use `showboat exec <file> bash '.venv/bin/python3 -c "..."'` (or `--workdir` if applicable) for Python code that imports project modules. A `--python` flag on showboat would eliminate this entirely. The skill should also set `PYTHONDONTWRITEBYTECODE=1` and suppress `RequestsDependencyWarning` via `-W ignore::DeprecationWarning` to keep output clean.

### 4. `showboat verify` Failure Due to Pytest Timing Jitter

- **What happened:** `uvx showboat verify demo.md` exited with code 1. The diff showed that block 14 (the full pytest `-v` output) recorded `34 passed, 1 warning in 0.06s` but the re-run produced `34 passed, 1 warning in 0.07s`. Every test passed identically -- the only difference was a 10ms timing fluctuation.
- **Why:** Showboat's verify does an exact string diff of captured output. Pytest's summary line includes wall-clock execution time, which is inherently non-deterministic. Any timing jitter causes a verify failure even when the actual test results are identical.
- **Impact:** This was the most expensive friction point. It triggered: 1 failed verify + 1 `pop` of the verbose test output + 1 new `exec` with `--tb=short | grep` filtering + 1 `pop` of that output (still not stable enough) + 1 final `exec` with a more aggressive grep pipeline. The agent also had to diagnose the diff output to understand that only timing differed. Total: ~5 extra tool calls and significant context spent analyzing the diff.
- **Mitigation:** The skill should **never record raw pytest `-v` output** in showboat documents. Instead, use a deterministic pipeline like:
  ```bash
  .venv/bin/python -m pytest <test_file> --tb=short -q 2>&1 | tail -1
  ```
  This produces only `34 passed, 1 warning` without the timing suffix. The skill instructions should include this as a hard rule for any test execution blocks.

### 5. Triple-Nested Escaping Hell for Bash-Wrapped Python

- **What happened:** After switching to `showboat exec demo.md bash '.venv/bin/python3 -c "..."'`, every Python string literal, triple-quote, and backslash required multiple layers of escaping: `\\\"` for quotes, `\\\"\\\"\\\"` for triple-quotes, `\\\\n` for newlines. Four consecutive exec blocks used this pattern.
- **Why:** The quoting chain is: JSON (Claude's tool input) -> bash (showboat's shell) -> bash (the inner `-c` command) -> Python (the actual code). Each layer consumes one level of escaping. The agent must mentally track 3-4 escaping levels simultaneously.
- **Impact:** While no additional failures occurred after the initial restructure, each exec block required ~300 output tokens of carefully escaped code. The fragility is high -- a single misplaced backslash would cause a silent failure requiring another pop-and-retry cycle. This is the primary source of context rot in the showboat workflow.
- **Mitigation:** The skill should use **stdin piping** instead of inline code for any non-trivial Python:
  ```bash
  cat <<'PYEOF' | .venv/bin/python3
  import ast
  from rlm_adk.repl.ast_rewriter import rewrite_for_async
  # ... normal unescaped Python ...
  PYEOF
  ```
  Then wrap as: `showboat exec demo.md bash '<heredoc command>'`. The single-quoted heredoc delimiter (`'PYEOF'`) prevents all shell interpolation, eliminating the escaping problem entirely. Showboat also supports stdin: `cat script.py | uvx showboat exec demo.md python3`.

### 6. Redundant Test Block After Verify Recovery

- **What happened:** After the verify failure on the verbose pytest output (friction point 4), the agent popped and re-recorded the test block, then popped and re-recorded it again with a different grep pattern. The final document contains two test output blocks (one verbose but filtered, one compact) because the agent over-corrected.
- **Why:** The agent didn't have a clear strategy for what "verify-stable" test output looks like. It tried three different approaches before landing on a stable one. The document ended up with a redundant `--tb=short | grep` block that adds no information beyond the verbose block above it.
- **Impact:** 2 extra `pop` + 2 extra `exec` operations, plus a slightly bloated final document. The wasted tokens are in the command construction and output processing.
- **Mitigation:** The skill should have a single canonical pattern for recording test results, established before any exec calls. This eliminates the iterative trial-and-error approach.

---

## Cost Summary

| Friction Point | Extra Tool Calls | Pop Operations | Root Cause |
|---|---|---|---|
| 1. File exists | 2 | 0 | No pre-check |
| 2. F-string backslash | 2 | 1 | Quoting chain opacity |
| 3. Wrong interpreter | 2 | 1 | System vs venv Python |
| 4. Timing jitter | 5 | 2 | Non-deterministic output |
| 5. Escaping hell | 0 (latent) | 0 | Architecture mismatch |
| 6. Redundant block | 4 | 2 | No canonical test pattern |
| **Total** | **~15** | **6** | |

---

## Key Takeaways for Skill Design

1. **Pre-flight checks eliminate 2 of 6 friction points.** Check for file existence before `init` and detect `.venv` before choosing the Python interpreter. These are zero-cost checks that prevent the most common first-attempt failures.

2. **Stdin piping eliminates the escaping problem.** The skill should always use heredoc-piped code instead of inline string arguments for multi-line Python. This removes the triple-escaping requirement entirely.

3. **Deterministic output is a hard requirement for verify.** Any code block whose output contains timestamps, durations, memory addresses, or random values will cause `showboat verify` to fail. The skill must strip or normalize non-deterministic output before recording. For pytest specifically, use `-q | tail -1` to capture only the pass/fail summary.

4. **The pop-exec-verify loop is the core retry primitive.** A skill should internalize this pattern: if `exec` fails, `pop` immediately, fix the command, and retry. If `verify` fails, inspect the diff for non-deterministic content, `pop` the offending block, re-record with a stable command, and re-verify. This loop should be automatic, not manual.

5. **`showboat exec <file> bash` should be the default for project code**, not `showboat exec <file> python3`. The bare `python3` lang option uses the system interpreter, which almost never has project dependencies. The skill should default to bash-wrapped `.venv/bin/python3 -c` and only use `python3` for stdlib-only demos.

6. **Warning suppression should be automatic.** The `RequestsDependencyWarning` from the `requests` package appeared in every single Python output block, adding noise. The skill should automatically add `-W ignore::DeprecationWarning` or `2>&1 | grep -v RequestsDependencyWarning` to keep captured output clean.
