# Gap Fix Loop

Systematically close thread bridge gaps from `issues/thread_bridge_gaps/INDEX.md`. This command is designed to be run via `/loop 15m /loop_gap_fix`.

## Procedure

You are the team-lead for a gap-closing sprint. Each invocation closes at most 3 gaps, chosen by priority (CRITICAL > HIGH > MEDIUM > LOW). Only batch multiple gaps when they share the same root fix.

### Step 0: Check for remaining work

Read `issues/thread_bridge_gaps/INDEX.md`. Find the highest-priority OPEN gaps (status `[ ]`). If all gaps are closed (`[x]`, `[~]`, or `[d]`), announce completion and stop.

Skip any gaps marked `[d]` (duplicate) — these are closed when their primary is closed.

Select up to 3 gaps to close this iteration. Only select multiple gaps when they are closely related (same file, same fix). Prefer closing 1 gap well over 3 gaps poorly.

### Step 1: Read the gap files

For each selected gap, read `issues/thread_bridge_gaps/GAP-XX-NNN.md` to understand:
- The problem description
- The evidence (file paths, line numbers)
- The suggested fix

### Step 2: Spawn code-reviewer agent

Spawn a `feature-dev:code-reviewer` agent named `gap-reviewer` with this prompt:

> Review the code around gap(s) [GAP-IDs]. Read the gap file(s) at `issues/thread_bridge_gaps/GAP-XX-NNN.md`, then read the affected source files listed in each gap. Generate:
> 1. A list of relevant Google ADK documentation references from `ai_docs/adk_*.md` files that pertain to this gap
> 2. Assessment of whether the gap is real, overstated, or already mitigated
> 3. Any additional context needed for the fix
> Write your findings to stdout (do not create files).

Wait for the reviewer to complete and capture its findings.

### Step 3: Spawn polya-understand agent

Spawn a general-purpose agent named `gap-understand` with this prompt:

> You are performing a Polya "Understand" phase analysis for gap(s) [GAP-IDs].
>
> First, read `rlm_adk_docs/vision/polya_topology/polya_understand.chatGPT_5-4.md` to understand the methodology.
>
> Then read the gap file(s) at `issues/thread_bridge_gaps/GAP-XX-NNN.md`.
>
> Then read the ADK reference docs identified by the code reviewer: [list from Step 2].
>
> Apply the Polya Understand methodology to produce:
> - Problem restatement
> - Exact objective
> - Knowns / givens (from the gap file + code)
> - Unknowns
> - Constraints (AR-CRIT-001, thread safety, backward compatibility)
> - Facts vs assumptions
> - Problem type classification
> - Success criteria
> - Operational problem statement
>
> Write the result to `issues/thread_bridge_gaps/Understand_GAP-XX-NNN.md` (one file per gap, or combined if gaps share a fix).

Wait for completion.

### Step 4: Spawn implementor-TDD agent

Spawn a general-purpose agent named `gap-implementor` with this prompt:

> You are fixing gap(s) [GAP-IDs] via strict RED/GREEN TDD.
>
> Read:
> 1. The gap file(s): `issues/thread_bridge_gaps/GAP-XX-NNN.md`
> 2. The Understand analysis: `issues/thread_bridge_gaps/Understand_GAP-XX-NNN.md`
> 3. The affected source files listed in the gap
> 4. `CLAUDE.md` for build commands and AR-CRIT-001 rules
>
> Procedure:
> 1. RED: Write a test that fails because of the gap
> 2. GREEN: Make the minimum change to pass the test
> 3. Run `ruff check` on all modified files
> 4. Run the relevant unit test file(s) with `.venv/bin/python -m pytest <file> -x -q -o "addopts="`
> 5. Run the e2e regression to verify nothing is broken:
>    `.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py -x -q -m "provider_fake" 2>&1`
>    This is the ONLY broader pytest run beyond your RED/GREEN unit tests. Do NOT run the full test suite.
>
> For dead-code gaps: no TDD needed — just delete the dead code, run lint, then run the e2e regression above.
> For doc gaps: no TDD needed — just update the docs. No test run required.
>
> Report: what was changed, test results, any issues.

Wait for completion.

### Step 5: Spawn showboat-review agent

After implementation succeeds, spawn a general-purpose agent named `gap-demo` with this prompt:

> Write a showboat demo document for gap(s) [GAP-IDs] at `issues/thread_bridge_gaps/demo_GAP-XX-NNN.md`.
>
> The demo should:
> 1. State what gap was fixed
> 2. Show the before state (the problem)
> 3. Show the after state (the fix)
> 4. Include runnable verification commands
> 5. Include a "Verification Checklist" with checkboxes
>
> For dead-code gaps: show the grep that found the dead code, and the grep that confirms removal.
> For threading gaps: show the test that exercises the fix.
> For observability gaps: show the DB query or state inspection.
>
> Keep it concise — this is verification, not a tutorial.

Wait for completion.

### Step 6: Verify and close

1. Read the demo file to confirm it's complete
2. Run the verification commands from the demo to confirm they pass
3. Update `issues/thread_bridge_gaps/INDEX.md`: change `[ ]` to `[x]` for each closed gap
4. If a gap was determined to be invalid/wontfix, change `[ ]` to `[~]` and note why
5. Mark any duplicates as `[d]` if their primary gap was closed

### Step 7: Compact and pause

Run `/compact` to compress the conversation context.

The `/loop` scheduler will re-invoke this command in 15 minutes to close the next batch.

## Important Rules

- **Never batch unrelated gaps** — only combine gaps that share the same root fix
- **AR-CRIT-001**: Never write `ctx.session.state[key] = value` in dispatch closures
- **Test commands** always use `-o "addopts="` to bypass the default pytest marker filter
- **Dead code removal** does not need TDD — just delete, lint, test
- **Doc-only fixes** do not need TDD — just update, verify accuracy
- **If a fix breaks other tests**, revert and mark the gap for manual review
- **Do not modify files in `rlm_adk/skills/obsolete/`** — that directory is intentionally dead
