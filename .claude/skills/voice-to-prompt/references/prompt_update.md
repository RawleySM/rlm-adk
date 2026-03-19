# Prompt Template: UPDATE

This template is used when the transcription's Target is classified as **UPDATE** — the user wants to build, change, fix, refactor, add, or implement something in the codebase.

## Framing: What Voice-to-Prompt Does vs. What the Prompt Says

**Voice-to-prompt's job is to write a prompt file.** That file is the deliverable. A *future* agent will read the prompt file and execute the work described in it. Everything below describes what text to write into the prompt file — voice-to-prompt does not execute any of the steps it writes.

## Write the Engineered Prompt

Create a markdown file in a `prompts/` subdirectory within the current working directory, creating the directory if it doesn't already exist. Use a descriptive name derived from the task (e.g., `fix_dispatch_retry_logic.md`, `add_skill_hot_reload.md`, `refactor_repl_tracing.md`).

The prompt file must contain these sections:

### Header
Write this header into the prompt file:
```markdown
<!-- generated: YYYY-MM-DD -->
<!-- source: voice transcription via voice-to-prompt skill -->
<!-- classification: UPDATE -->
# [Descriptive Task Title]
```

### Context
Write a 2-3 sentence summary of what needs to happen and why, written for a coding agent that has never seen this codebase before.

### Original Transcription
Write the user's raw text, preserved verbatim in a blockquote. This ensures the original intent is always recoverable.

### Refined Instructions

Write this delegation directive into the prompt file immediately after the `## Refined Instructions` heading:

```markdown
> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.
```

Then write clear, numbered steps that tell a future agent what to do. **Each step must be phrased as a teammate spawn directive.** Derive a short, descriptive agent identifier from the step's purpose. Format:

```
1. **Spawn a `<AgentName>` teammate to [action description targeting exact file/function].**
```

For example:
- `1. **Spawn a `Retry-Agent` teammate to add retry-with-backoff to `_run_child()` in `rlm_adk/dispatch.py` (line 383).**`
- `2. **Spawn a `Schema-Guard` teammate to fix error classification priority at line 504 in `rlm_adk/dispatch.py`.**`

Each step you write should:
- Reference exact file paths (not "the orchestrator file" but `rlm_adk/orchestrator.py`)
- Name specific functions or classes when relevant
- Explain what to change, review, or document, and why
- Include constraints the user implied but didn't state explicitly (e.g., "don't break the existing test suite", "preserve AR-CRIT-001 compliance")

If the transcription was missing steps that a competent agent would need, add them with a note like: *[Added — the transcription didn't mention this, but X requires Y because Z.]*

### Provider-Fake Fixture & TDD

For any task that introduces new behavior (new features, new skills, bug fixes with observable behavior changes), write a dedicated section into the prompt file specifying provider-fake fixture requirements. This is not optional — it is part of the refined prompt output.

The section you write should:

1. **Name the fixture file** — e.g., `tests_rlm_adk/fixtures/provider_fake/worker_health_check.json`
2. **List essential requirements the fixture must capture** — Focus on *intent validation*, not just error-free execution. What behavior proves the feature works correctly? What would a reward-hacked test miss? For example:
   - "The fixture must verify that the health check dispatches exactly N concurrent queries (not 1 sequential query repeated N times)"
   - "The fixture must include at least one worker that returns an error, verifying the skill correctly reports partial failures"
   - "The fixture must verify latency measurement is non-zero and plausible (not hardcoded)"
3. **Specify the TDD sequence** — Which test to write first (red), what minimal implementation makes it green, then what the next test should cover.
4. **Include a showboat demo step** — After implementation, the teammate runs `uvx showboat` to generate an executable demo document proving the feature works.

Example of what to write into the prompt file:
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

### Considerations
Write anything the future coding agent should be aware of:
- Related subsystems that might be affected
- Testing requirements
- State mutation rules (AR-CRIT-001 if dispatch/state work is involved)
- Potential gotchas from the ADK framework

### Appendix: Code References

Write a table of every file, class, and function referenced in the instructions:

```markdown
## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/orchestrator.py` | `RLMOrchestratorAgent._run_async_impl` | L278 | Main orchestrator loop being modified |
| `rlm_adk/dispatch.py` | `create_dispatch_closures` | L1378 | Dispatch closure factory |
| `rlm_adk/state.py` | `depth_key()` | L42 | Depth-scoped state key helper |
```

Line numbers must be verified against the current source — do not guess. Use Grep with line number output to confirm.

### Priming References
End the prompt file with pointers for the future coding agent:

```markdown
## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow branch links relevant to this task)
```
