# Prompt Template: REVIEW

This template is used when the transcription's Target is classified as **REVIEW** — the user wants to review, audit, inspect, evaluate, or critique existing code, tests, or architecture.

## Framing: What Voice-to-Prompt Does vs. What the Prompt Says

**Voice-to-prompt's job is to write a prompt file.** That file is the deliverable. A *future* agent will read the prompt file and execute the work described in it. Voice-to-prompt does NOT run `/devils-advocate`, spawn review agents, or examine fixtures — it writes instructions telling a future agent to do those things.

## Write the Engineered Prompt

Create a markdown file in a `prompts/` subdirectory within the current working directory, creating the directory if it doesn't already exist. Use a descriptive name derived from the review subject (e.g., `review_dispatch_error_handling.md`, `audit_worker_pool_fixtures.md`, `evaluate_repl_tracing.md`).

The prompt file must contain these sections:

### Header
Write this header into the prompt file:
```markdown
<!-- generated: YYYY-MM-DD -->
<!-- source: voice transcription via voice-to-prompt skill -->
<!-- classification: REVIEW -->
# Review: [Descriptive Subject Title]
```

### Context
Write a 2-3 sentence summary of what is being reviewed and why, written for a future agent that has never seen this codebase before. State the review's motivation — is the user suspicious of something? Trying to gain confidence before a change? Auditing for compliance?

### Original Transcription
Write the user's raw text, preserved verbatim in a blockquote. This ensures the original intent is always recoverable.

### Refined Instructions

Write this delegation directive into the prompt file immediately after the `## Refined Instructions` heading:

```markdown
> **Delegation:** This is a REVIEW task. The final step invokes `/devils-advocate` against the review subject. Earlier steps scope the review and gather context for the devil's advocate team.
```

Then write clear, numbered steps that tell a future agent what to do. **Each step must be phrased as a teammate spawn directive.** The final step should always instruct the future agent to invoke `/devils-advocate`. Format:

```
1. **Spawn a `<AgentName>` teammate to [review action targeting exact file/function].**
```

For example, write steps like:
- `1. **Spawn a `Scope-Agent` teammate to identify all files, fixtures, and tests in scope for this review by tracing from `rlm_adk/dispatch.py` outward.**`
- `2. **Spawn a `Context-Agent` teammate to read the identified files and summarize the current behavior, noting any code smells or inconsistencies.**`
- `3. **Run `/devils-advocate` against the files identified in step 1.** The devil's advocate team (ADK Callback Expert, Vision Alignment Challenger, Prior-Art Researcher) will stress-test the subject from multiple adversarial angles.`

Each step you write should:
- Reference exact file paths (not "the orchestrator file" but `rlm_adk/orchestrator.py`)
- Name specific functions or classes when relevant
- Explain what to review, what lens to apply, and what kind of findings the user cares about
- Include constraints the user implied but didn't state explicitly (e.g., "focus on AR-CRIT-001 violations", "check for observability blind spots")

If the transcription was missing steps that a thorough review would need, add them with a note like: *[Added — the transcription didn't mention this, but reviewing X requires also examining Y because Z.]*

### Review Provider-Fake Fixtures

For any review that touches code with associated test fixtures, write a dedicated section into the prompt file instructing the future agent to examine those fixtures with adversarial skepticism. This section exists because **test fixtures are the most common vector for reward hacking** — tests that pass without actually validating intent.

Write this section into the prompt file, filling in the specific fixture paths relevant to the review subject:

```markdown
## Review Provider-Fake Fixtures

**Fixtures in scope:** [List all fixture files associated with the code under review, e.g.:]
- `tests_rlm_adk/fixtures/provider_fake/worker_retry_backoff.json`
- `tests_rlm_adk/fixtures/provider_fake/dispatch_error_classification.json`

**Review with a skeptical eye — assume reward hacking until proven otherwise:**

1. **Intent vs. mechanics** — Does each fixture actually test the *behavior the user cares about*, or does it merely test that code runs without errors? A fixture that asserts "no exception raised" when it should assert "retry happened exactly 3 times with exponential backoff" is reward-hacked.

2. **Hardcoded golden paths** — Are fixture responses suspiciously perfect? Real provider responses include noise, partial failures, unexpected formats. A fixture where every response is clean JSON with exactly the right fields is testing the happy path while pretending to test resilience.

3. **Missing negative cases** — For every positive assertion in a fixture, ask: "What's the corresponding failure case?" If there isn't one, the fixture suite has a blind spot.

4. **State mutation coverage** — Do fixtures verify that state was mutated correctly (via `tool_context.state`, `callback_context.state`, `EventActions`), or do they only check return values? Return values can be correct while state is silently corrupted.

5. **Temporal ordering** — For fixtures testing async/parallel behavior, do they verify ordering constraints? A fixture that passes regardless of execution order isn't testing concurrency — it's testing sequential code that happens to use async syntax.

6. **Coverage theater** — Are there fixtures that exist purely to inflate coverage numbers without testing meaningful behavior? A fixture that exercises a code path but makes no meaningful assertions is worse than no fixture (it creates false confidence).

**Output:** For each fixture, provide a verdict: SOUND / SUSPECT / REWARD-HACKED, with specific evidence supporting the classification.
```

### Considerations
Write anything the future reviewing agent should be aware of:
- What the user is specifically suspicious about
- Related subsystems that the review should or should not extend into
- Whether the review should produce recommendations only, or also generate fix prompts
- State mutation rules (AR-CRIT-001 if dispatch/state work is in scope)

### Appendix: Code References

Write a table of every file, class, and function in the review scope:

```markdown
## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/dispatch.py` | `create_dispatch_closures` | L1378 | Primary review subject |
| `tests_rlm_adk/test_fmea_e2e.py` | `TestWorkerRetry` | L142 | Associated test class |
| `tests_rlm_adk/fixtures/provider_fake/worker_retry.json` | — | — | Fixture under review |
```

Line numbers must be verified against the current source — do not guess. Use Grep with line number output to confirm.

### Priming References
End the prompt file with pointers for the future reviewing agent:

```markdown
## Priming References

Before starting the review, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow branch links relevant to this review)
```
