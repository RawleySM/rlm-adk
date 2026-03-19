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

### Step 2: Apply "Understand" to the Transcription and Classify

With Polya's framework fresh in mind, read the user's transcription and work through a lightweight Understand pass:

- **Restate**: What is the user actually asking to be built, changed, or fixed?
- **Target**: What is the concrete deliverable? (A new file? A refactored module? A bug fix? A test?)
- **Givens**: What information did the user explicitly provide? (File names, class names, behavior descriptions, constraints)
- **Unknowns**: What references are vague or possibly wrong? ("the orchestrator file", "that retry thing", "the test for dispatch")
- **Assumptions**: What is the user assuming you already know? What might they have misspoken about?

Write this analysis down internally — it guides everything that follows.

#### Classify the Target

Based on your Understand pass, classify the transcription's Target into one of three categories. This classification determines which prompt template you use in Step 5.

| Classification | The user wants to... | Synonyms / signals in transcription |
|----------------|----------------------|-------------------------------------|
| **UPDATE** | Build, change, fix, or ship something | build, add, implement, create, fix, refactor, migrate, upgrade, wire up, hook in, swap out, replace, rename, move, delete, remove, ship, deploy, "make it so that..." |
| **REVIEW** | Inspect, audit, or evaluate existing code | review, audit, check, inspect, evaluate, assess, examine, critique, look at, verify, validate, "is this right?", "does this look good?", "what's wrong with...", "sanity check" |
| **PROPOSAL** | Brainstorm, explore, or design before committing | brainstorm, propose, explore, ideate, design, consider, "what if", spitball, sketch out, think through, "how should we...", "what's the best way to...", "I'm torn between...", "should we...", prototype, draft, RFC |

**When in doubt:** If the transcription mixes categories (e.g., "review the dispatch code and then fix the retry logic"), classify by the *primary* intent. A review that leads to fixes is still an UPDATE — the user wants something changed. A proposal that includes "and then build it" is still a PROPOSAL if the brainstorming hasn't happened yet.

Record the classification — it determines which prompt template Step 5 uses.

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

Read the prompt template reference file that matches the classification from Step 2, then follow its instructions to write the engineered prompt:

| Classification | Template file |
|----------------|---------------|
| **UPDATE** | `references/prompt_update.md` (bundled with this skill) |
| **REVIEW** | `references/prompt_review.md` (bundled with this skill) |
| **PROPOSAL** | `references/prompt_proposal.md` (bundled with this skill) |

Read the selected template file now, then follow its structure exactly to produce the output prompt file in `prompts/`.

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
| `references/prompt_update.md` | Prompt template for UPDATE classifications (build/change/fix) |
| `references/prompt_review.md` | Prompt template for REVIEW classifications (audit/inspect/evaluate) — integrates devil's advocate |
| `references/prompt_proposal.md` | Prompt template for PROPOSAL classifications (brainstorm/explore/design) — brainstorm agents + devil's advocate |
| `.claude/skills/devils-advocate/SKILL.md` (project root) | Devil's advocate adversarial review workflow — used by REVIEW and PROPOSAL templates |
| `repomix-architecture-flow-compressed.xml` (project root) | Compressed source code snapshot for structural priming |
| `rlm_adk_docs/UNDERSTAND.md` (project root) | Documentation entrypoint with branch index to detailed docs |
