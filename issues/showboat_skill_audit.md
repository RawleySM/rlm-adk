# Showboat Skill Audit: Duplication and Unnecessary Ceremony

**Date:** 2026-02-26
**Showboat version:** 0.6.0
**Skill:** `showboat-review` (SKILL.md + 2 reference files)
**Input:** BUG-12 friction report, showboat `--help` output, empirical testing

---

## Section 1: What Showboat Already Does

These are showboat's native capabilities relevant to the 6 friction points, confirmed by `uvx showboat --help` and direct testing.

### 1.1 `--workdir <dir>` (global option)

Sets the working directory for code execution. Confirmed working:

```
$ uvx showboat --workdir /home/.../rlm-adk exec doc.md bash 'pwd'
/home/.../rlm-adk
```

**However**, `--workdir` does NOT affect interpreter resolution for the `python3` lang. When `lang=python3`, showboat always uses its own isolated Python (`/home/.../.local/share/uv/tools/showboat/bin/python3`), regardless of `--workdir`. The `--workdir` flag only changes `cwd` for the subprocess, it does not modify `PATH` or activate any virtualenv.

**Verdict:** `--workdir` is useful for ensuring `bash` commands run in the project root, but it does NOT solve friction point 3 (wrong interpreter). The skill's recommendation to use `bash '.venv/bin/python3 ...'` remains necessary.

### 1.2 Stdin piping

Showboat's `--help` documents stdin support:

> Commands accept input from stdin when the text/code argument is omitted.
> For example:
>   echo "Hello world" | showboat note demo.md
>   cat script.sh | showboat exec demo.md bash

Confirmed working for both `python3` and `bash` langs:

```
$ echo 'print("hello")' | uvx showboat exec doc.md python3
hello

$ cat <<'PYEOF' | uvx showboat exec doc.md bash
.venv/bin/python3 -c "print('venv python')"
PYEOF
venv python
```

**Verdict:** Stdin piping is a native feature. The skill's heredoc pattern (Rule 1) does use this, but the skill wraps it in a convoluted quoting scheme (`'cat <<'"'"'PYEOF'"'"'`) that is itself a source of friction. A simpler approach using native stdin piping (pipe from outside showboat) would eliminate the quoting complexity entirely.

### 1.3 `exec` error handling

Showboat exec has NO built-in retry. On failure:
- The exit code is forwarded to the caller
- Output is printed to stdout
- The failed block IS appended to the document regardless of exit code

From `--help`:

> The "exec" command prints the captured shell output to stdout and exits with
> the same exit code as the executed command. [...] The output is still appended
> to the document regardless of exit code. Use "pop" to remove a failed entry.

**Verdict:** Showboat has zero error recovery. The skill's "pop on failure" pattern (Rule 5) is NOT duplication -- it is essential.

### 1.4 `pop` behavior

Removes the most recent entry. For exec entries, removes both the code block and output block. No flags, no options.

**Verdict:** Pop is the only recovery mechanism. The skill correctly documents this.

### 1.5 `verify` capabilities

`verify` has exactly one optional flag: `--output <file>` to write an updated copy. There are NO tolerance, ignore, regex, or fuzzy-match options. Verification is strict exact-string comparison.

From `--help`:

> Re-runs every code block [...] and compares actual output against the recorded
> output. Prints diffs and exits with code 1 if any output has changed.

Tested: `--tolerance`, `--ignore` are not recognized (treated as filenames, causing errors).

**Verdict:** The skill's verify-retry loop and deterministic output guidance (Rule 2, Phase 5) are NOT duplication. They are essential workarounds for verify's strict comparison. Showboat has no native non-determinism handling.

### 1.6 `init` behavior

`init` has NO `--force` or overwrite option. Tested directly:

```
$ uvx showboat init existing.md "Title"
error: file already exists: existing.md

$ uvx showboat init --force existing.md "Title"
error: file already exists: --force    # treated as filename
```

**Verdict:** The skill's file existence check (Phase 3) is NOT duplication. Showboat genuinely lacks overwrite support.

### 1.7 Language support

The `<lang>` argument to `exec` is used directly as the executable name. Showboat does not maintain a language registry or provide any interpreter configuration (`--python`, `--interpreter`, etc.). Whatever you pass as `<lang>` is what gets `exec()`'d from `PATH`.

Since `uvx showboat` runs in an isolated uv tool environment, its `PATH` contains showboat's own venv python, not the project's. This is the root cause of friction point 3.

### 1.8 Summary of native capabilities

| Capability | Status | Notes |
|---|---|---|
| `--workdir` | Exists | Changes cwd only, not interpreter |
| Stdin piping | Exists | Documented and working |
| `--force` on init | Does NOT exist | |
| `--python` / interpreter config | Does NOT exist | |
| Verify tolerance/ignore | Does NOT exist | Strict exact match only |
| Built-in retry on exec | Does NOT exist | |
| Error recovery | `pop` only | No undo, no selective removal |

---

## Section 2: Skill Duplication Map

| Skill Rule/Phase | What it does | Showboat handles natively? | Verdict |
|---|---|---|---|
| **Phase 0: Preflight** | Check uvx, venv, pytest | No | **KEEP** -- pure skill value-add |
| **Phase 1: Discovery** | Run `showboat --help` | N/A (meta) | **REMOVE** -- the agent already knows the tool; reading help wastes a tool call |
| **Phase 2: Plan** | Identify demo target, code paths, test runner, venv | No | **KEEP** -- project-specific discovery |
| **Phase 3: File existence check** | `test -f` before init | No (`--force` absent) | **KEEP** -- required workaround |
| **Rule 1: Heredoc pattern** | Bash + heredoc for Python exec | Partially (stdin piping exists) | **SIMPLIFY** -- the quoting scheme is overcomplicated; use native stdin piping instead |
| **Rule 2: Deterministic test output** | `-q \| tail -1` for pytest | No (verify has no tolerance) | **KEEP** -- essential |
| **Rule 3: Code snippets via grep/sed** | Show code via exec, not paste | No | **KEEP** -- good practice, not a workaround |
| **Rule 4: Warning suppression** | Filter noisy warnings | No | **KEEP** -- but could note `--workdir` is irrelevant here |
| **Rule 5: Pop on failure** | Pop immediately after failed exec | No (showboat records failures) | **KEEP** -- essential |
| **Rule 6: Rodney screenshots** | Integration with rodney | N/A (rodney is separate tool) | **KEEP** -- not showboat-related |
| **Phase 5: Verify retry loop** | Inspect diff, pop, re-record, re-verify | No (verify is pass/fail only) | **KEEP** -- essential |
| **Phase 1 rodney decision gate** | Evaluate if web UI demo | No | **KEEP** -- orchestration logic |
| **friction-mitigations.md (full file)** | Detailed solutions for all 6 frictions | No | **SIMPLIFY** -- significant overlap with SKILL.md rules; merge or remove |

---

## Section 3: Recommended Skill Simplification

### 3.1 REMOVE: Phase 1 Discovery ("run `showboat --help`")

The skill instructs the agent to run `uvx showboat --help` as a discovery step. This is a wasted tool call. The skill itself already encodes every relevant showboat capability. An agent following the skill does not need to re-discover what it already has documented.

**Action:** Delete Phase 1's `showboat --help` instruction. Keep only the rodney decision gate (which is real decision logic, not discovery).

### 3.2 SIMPLIFY: Rule 1 heredoc pattern

The current pattern is:

```bash
uvx showboat exec demo.md bash 'cat <<'"'"'PYEOF'"'"' | .venv/bin/python3
import ast
# ... code ...
PYEOF'
```

This quoting chain (`'...'` + `"'"` + `'PYEOF'` + `"'"` + `'...'`) is itself a friction source. It is an embedded heredoc inside a single-quoted bash argument, which requires 5-part quote concatenation to insert a literal single quote into the heredoc delimiter. This is exactly the "escaping hell" the skill is supposed to prevent.

Showboat natively supports stdin piping. The simpler approach:

```bash
cat <<'PYEOF' | uvx showboat --workdir "$PWD" exec demo.md bash
.venv/bin/python3 <<'PY'
import ast
# ... normal unescaped Python ...
PY
PYEOF
```

Or even simpler for Claude Code (which controls the shell directly):

```bash
cat <<'PYEOF' | uvx showboat exec demo.md bash
.venv/bin/python3 -c "
import ast
print(ast.dump(ast.parse('x=1')))
"
PYEOF
```

**Action:** Replace the 5-part quote concatenation pattern with a simple external `cat <<'DELIM' | uvx showboat exec ...` pipe. Document both the "pipe from outside" pattern (preferred) and the "inline for one-liners" pattern. Remove the quoting breakdown explanation from friction-mitigations.md.

### 3.3 SIMPLIFY: Warning suppression (Rule 4)

The skill says "append `2>&1 | grep -v Warning` or use `PYTHONWARNINGS=ignore`" but does not mention that `--workdir` is irrelevant to this problem. The warnings come from imported packages, not from the working directory.

**Action:** Keep the rule but state it more concisely: "Prefix Python commands with `PYTHONWARNINGS=ignore PYTHONDONTWRITEBYTECODE=1`." Drop the `grep -v` alternative, which is fragile (filters too broadly or too narrowly depending on the warning text).

### 3.4 MERGE OR REMOVE: `references/friction-mitigations.md`

This file duplicates 90% of the content already in SKILL.md's Rules section. The SKILL.md rules are more actionable (they give the exact command patterns); the friction-mitigations file adds background context (symptoms, causes) that the agent does not need at execution time.

**Action:** Either:
- (a) Delete friction-mitigations.md entirely and add a one-line "Why" comment to each SKILL.md rule, or
- (b) Keep friction-mitigations.md as a debugging reference but remove the "Fix" sections (which duplicate SKILL.md) and keep only "Symptom" and "Cause" for when the agent needs to diagnose an unexpected failure.

Option (a) is recommended. The agent should not read friction-mitigations.md during normal execution -- it adds ~120 lines of context for no actionable gain.

### 3.5 REPHRASE: Phase 3 init check

The skill currently uses a bash test + echo pattern:

```bash
test -f <target-file> && echo "FILE_EXISTS" || echo "FILE_OK"
```

This is fine but could be more concise. Since showboat lacks `--force`, the check is necessary. However, the skill should also document that a simple `rm -f <file>` before init is acceptable if the user has confirmed overwrite intent. The current skill says "ask the user or generate a timestamped name" which adds an unnecessary human-in-the-loop step for what is usually a stale artifact.

**Action:** Rephrase to: "If file exists, delete it (previous demos are stale artifacts). If the user explicitly requested a specific filename, confirm before overwriting."

### 3.6 NO CHANGE NEEDED: Pop on failure (Rule 5), verify retry loop (Phase 5), deterministic test output (Rule 2)

These are all essential workarounds for showboat limitations that have no native solutions. They should remain as-is.

---

## Section 4: Pre-Workflow Guidance

This is the actual value-add of the skill: things the agent must know before starting that showboat cannot handle natively. Everything else should reference showboat's own `--help` or be inlined as a one-line rule.

### 4.1 Interpreter isolation (critical)

`uvx showboat exec <file> python3` runs showboat's own Python, not the project's. This is an architectural constraint of `uvx` tool isolation. There is no `--python` flag. The only solution is `exec <file> bash '.venv/bin/python3 ...'` or stdin piping through bash.

**The agent must know this before the first exec call.**

### 4.2 Venv detection (project-specific)

Check for `.venv/`, `venv/`, or `.env/` and use whichever exists. Also check `pyproject.toml` for the test runner (pytest vs unittest vs other). This is project knowledge that showboat cannot discover.

### 4.3 Verify is strict exact-match (critical)

Any non-deterministic output (timestamps, durations, memory addresses, PIDs, UUIDs) will cause verify to fail. The agent must plan for deterministic output from the start, not after the first verify failure. For pytest specifically: `.venv/bin/python -m pytest tests/ -q 2>&1 | tail -1`.

### 4.4 Failed exec blocks are recorded (surprising behavior)

Showboat appends output to the document even when exec exits non-zero. The agent must `pop` immediately after any failure. This is not intuitive and must be stated explicitly.

### 4.5 Rodney decision gate (orchestration)

The decision of whether to use rodney is based on the feature type (web UI vs CLI), not on showboat's capabilities. This is skill-level orchestration that showboat has no opinion on.

### 4.6 Proposed lean pre-workflow block

```
BEFORE STARTING:
1. showboat exec python3 uses showboat's Python, NOT your project's.
   Always use: exec <file> bash '.venv/bin/python3 ...'
   For multi-line: cat <<'EOF' | uvx showboat exec <file> bash
2. showboat verify is strict exact-match. No tolerance flags exist.
   Strip timestamps, durations, PIDs from all output before recording.
   Pytest: .venv/bin/python -m pytest tests/ -q 2>&1 | tail -1
3. Failed exec blocks are recorded. Pop immediately on failure.
4. showboat init has no --force. Delete stale files before init.
5. Detect venv: ls -d .venv venv .env 2>/dev/null | head -1
6. Detect test runner: grep -A2 'tool.pytest' pyproject.toml
7. Does the feature involve a web UI? If yes, also use rodney.
```

This is 7 lines. It replaces ~170 lines of SKILL.md + ~120 lines of friction-mitigations.md with the same effective guidance. The remaining SKILL.md content (phases, rules) becomes a reference the agent consults only when it encounters a problem, not a mandatory pre-read.

---

## Appendix: Test Evidence

All claims above were verified empirically against showboat 0.6.0:

| Test | Command | Result |
|---|---|---|
| `--workdir` changes cwd | `--workdir /proj exec doc bash 'pwd'` | `/proj` -- works |
| `--workdir` does NOT change python3 interpreter | `--workdir /proj exec doc python3 'import sys; print(sys.executable)'` | showboat's python, not project's |
| `--force` on init | `init --force existing.md "T"` | `error: file already exists: --force` |
| Stdin piping to exec | `echo 'print(1)' \| exec doc python3` | works |
| Heredoc stdin to bash exec | `cat <<'EOF' \| exec doc bash` | works |
| Failed exec is recorded | `exec doc bash 'echo x && exit 1'` | output appended, exit 1 forwarded |
| Verify tolerance flags | `verify --tolerance 0.1 doc` | `error: opening file: open --tolerance` |
| Lang argument is literal exec | `exec doc node 'console.log(1)'` | runs `node` from PATH directly |
