---
name: voice-to-prompt
description: "Refine raw voice transcriptions into engineered coding prompts for this codebase. Use this skill whenever the user pastes or provides rough text from a voice memo, dictation, speech-to-text transcription, or any informal/stream-of-consciousness description of a coding task they want done in this project. Also trigger when the user says 'refine this prompt', 'clean up my transcription', 'turn this into a prompt', 'voice memo', 'I dictated this', or provides text that reads like spoken language with vague file references, casual phrasing, or incomplete sentences describing code changes."
---

# Voice-to-Prompt: Transcription Refiner for RLM-ADK

You are transforming raw, informal text (typically from voice transcription) into a precise, actionable engineering prompt. The person who dictated this text is a senior engineer who knows what they want but spoke casually — your job is to preserve their intent exactly while adding the rigor and specificity a coding agent needs to execute without guesswork.

## Mandatory Workflow

Follow these steps in strict order. Do not skip or reorder them.

### Step 1: Read the Polya "Understand" Reference

Before doing anything else, read `references/polya_understand.md` (bundled with this skill). This document describes Polya's methodology for the "Understand" phase of problem-solving. You will apply this methodology to the transcription in Step 2.

The reason this comes first: voice transcriptions are inherently ambiguous — they contain implied context, vague references, and assumed knowledge. Polya's Understand phase gives you a systematic way to surface what's missing, identify hidden assumptions, and distinguish facts from inferences before you touch any code.

### Step 2: Apply "Understand" to the Transcription

With Polya's framework fresh in mind, read the user's transcription and work through a lightweight Understand pass:

- **Restate**: What is the user actually asking to be built, changed, or fixed?
- **Target**: What is the concrete deliverable? (A new file? A refactored module? A bug fix? A test?)
- **Givens**: What information did the user explicitly provide? (File names, class names, behavior descriptions, constraints)
- **Unknowns**: What references are vague or possibly wrong? ("the orchestrator file", "that retry thing", "the test for dispatch")
- **Assumptions**: What is the user assuming you already know? What might they have misspoken about?

Write this analysis down internally — it guides everything that follows.

### Step 3: Prime on Codebase Structure

Read these two documents to ground yourself in the actual codebase:

1. **`repomix-architecture-flow-compressed.xml`** (project root) — A compressed XML snapshot of the core source files. This gives you the class names, function signatures, file structure, and module relationships. Read this to resolve vague references like "the orchestrator" or "the dispatch thing" into exact file paths and function names.

2. **`rlm_adk_docs/UNDERSTAND.md`** — The documentation entrypoint. It provides a branch index to detailed docs on Core Loop, Dispatch & State, Observability, Testing, Skills & Prompts, Configuration, and Vision. If the transcription touches a specific subsystem, follow the relevant branch link to get deeper context.

### Step 4: Resolve References Against the Codebase

Now search the actual codebase to verify and correct every file, class, function, and component the user mentioned:

- Use Glob and Grep to find exact file paths, class definitions, function signatures
- Verify line numbers for any code the prompt will reference
- Correct misspellings, wrong file names, outdated class names
- If the user said "the retry callback" and meant `WorkerRetryPlugin` in `rlm_adk/callbacks/worker_retry.py`, resolve it precisely
- If the user referenced a file that doesn't exist, find the closest match and note the correction

### Step 5: Write the Engineered Prompt

Create a markdown file in `./prompts/` with a descriptive name derived from the task (e.g., `fix_dispatch_retry_logic.md`, `add_skill_hot_reload.md`, `refactor_repl_tracing.md`).

The prompt file must contain these sections:

#### Header
```markdown
<!-- generated: YYYY-MM-DD -->
<!-- source: voice transcription via voice-to-prompt skill -->
# [Descriptive Task Title]
```

#### Context
A 2-3 sentence summary of what needs to happen and why, written for a coding agent that has never seen this codebase before.

#### Original Transcription
The user's raw text, preserved verbatim in a blockquote. This ensures the original intent is always recoverable.

#### Refined Instructions

Immediately after the `## Refined Instructions` heading, emit this delegation directive:

```markdown
> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.
```

Then transform the transcription into clear, numbered steps. **Each step must be phrased as a teammate spawn directive.** Derive a short, descriptive agent identifier from the step's purpose. Format:

```
1. **Spawn a `<AgentName>` teammate to [action description targeting exact file/function].**
```

For example:
- `1. **Spawn a `Retry-Agent` teammate to add retry-with-backoff to `_run_child()` in `rlm_adk/dispatch.py` (line 383).**`
- `2. **Spawn a `Schema-Guard` teammate to fix error classification priority at line 504 in `rlm_adk/dispatch.py`.**`

Each step should:
- Reference exact file paths (not "the orchestrator file" but `rlm_adk/orchestrator.py`)
- Name specific functions or classes when relevant
- Explain what to change and why
- Include constraints the user implied but didn't state explicitly (e.g., "don't break the existing test suite", "preserve AR-CRIT-001 compliance")

If the transcription was missing steps that a competent agent would need, add them with a note like: *[Added — the transcription didn't mention this, but X requires Y because Z.]*

#### Provider-Fake Fixture & TDD

For any task that introduces new behavior (new features, new skills, bug fixes with observable behavior changes), include a dedicated section specifying provider-fake fixture requirements. This is not optional — it is part of the refined prompt output.

The section should:

1. **Name the fixture file** — e.g., `tests_rlm_adk/fixtures/provider_fake/worker_health_check.json`
2. **List essential requirements the fixture must capture** — Focus on *intent validation*, not just error-free execution. What behavior proves the feature works correctly? What would a reward-hacked test miss? For example:
   - "The fixture must verify that the health check dispatches exactly N concurrent queries (not 1 sequential query repeated N times)"
   - "The fixture must include at least one worker that returns an error, verifying the skill correctly reports partial failures"
   - "The fixture must verify latency measurement is non-zero and plausible (not hardcoded)"
3. **Specify the TDD sequence** — Which test to write first (red), what minimal implementation makes it green, then what the next test should cover.
4. **Include a showboat demo step** — After implementation, the teammate runs `uvx showboat` to generate an executable demo document proving the feature works.

```markdown
## Provider-Fake Fixture & TDD

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/<fixture_name>.json`

**Essential requirements the fixture must capture:**
- [Requirement 1 — what intent does this validate?]
- [Requirement 2 — what would a naive test miss?]
- [Requirement 3 — edge case that proves correctness]

**TDD sequence:**
1. Red: Write test asserting [specific behavior]. Run, confirm failure.
2. Green: Implement [minimal change]. Run, confirm pass.
3. Red: Write test asserting [next behavior]. Continue.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the implementation works end-to-end.
```

#### Considerations
Anything the coding agent should be aware of:
- Related subsystems that might be affected
- Testing requirements
- State mutation rules (AR-CRIT-001 if dispatch/state work is involved)
- Potential gotchas from the ADK framework

#### Appendix: Code References

A table of every file, class, and function referenced in the instructions:

```markdown
## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/orchestrator.py` | `RLMOrchestratorAgent._run_async_impl` | L278 | Main orchestrator loop being modified |
| `rlm_adk/dispatch.py` | `create_dispatch_closures` | L1378 | Dispatch closure factory |
| `rlm_adk/state.py` | `depth_key()` | L42 | Depth-scoped state key helper |
```

Line numbers must be verified against the current source — do not guess. Use Grep with line number output to confirm.

#### Priming References
End with pointers for the coding agent that will execute this prompt:

```markdown
## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow branch links relevant to this task)
```

### Step 6: Report to User

Tell the user:
- The path to the generated prompt file
- A one-sentence summary of what the refined prompt asks for
- Any corrections you made to their references (wrong file names, outdated class names, etc.)
- Any steps you added that weren't in the original transcription, and why

## Output Quality Standards

- **Preserve intent**: The refined prompt must do what the user asked for, not what you think they should have asked for. If you think they're making a mistake, note it in Considerations — don't silently redirect.
- **Be specific**: Every file reference must be a real path. Every function reference must exist. Every line number must be current.
- **Fill gaps, don't invent**: Add missing steps that logically follow from the user's intent. Do not add features, refactors, or improvements they didn't ask for.
- **Respect scope**: If the transcription describes a small fix, the prompt should describe a small fix — not a redesign of the surrounding architecture.

## Files

| File | Purpose |
|------|---------|
| `references/polya_understand.md` | Polya's "Understand" phase methodology — read first, always |
| `repomix-architecture-flow-compressed.xml` (project root) | Compressed source code snapshot for structural priming |
| `rlm_adk_docs/UNDERSTAND.md` (project root) | Documentation entrypoint with branch index to detailed docs |
