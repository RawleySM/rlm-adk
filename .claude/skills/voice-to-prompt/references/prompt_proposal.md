# Prompt Template: PROPOSAL

This template is used when the transcription's Target is classified as **PROPOSAL** — the user wants to brainstorm, explore, ideate, or propose something before committing to implementation.

## Framing: What Voice-to-Prompt Does vs. What the Prompt Says

**Voice-to-prompt's job is to write a prompt file.** That file is the deliverable. A *future* agent will read the prompt file and execute the work described in it. Voice-to-prompt does NOT spawn brainstorm agents, run `/devils-advocate`, or write proposals — it writes instructions telling a future agent to do those things.

A PROPOSAL prompt describes three phases for the future agent to execute:
1. **Brainstorm** — Spawn diverse-persona agents who each write an independent proposal
2. **Critique** — Run `/devils-advocate` against each proposal
3. **Synthesize** — Compare all proposals and reviews, recommend a path forward

## Write the Engineered Prompt

Create a markdown file in a `prompts/` subdirectory within the current working directory, creating the directory if it doesn't already exist. Use a descriptive name derived from the brainstorm topic (e.g., `propose_skill_hot_reload.md`, `brainstorm_worker_health_checks.md`, `explore_repl_caching.md`).

The prompt file must contain these sections:

### Header
Write this header into the prompt file:
```markdown
<!-- generated: YYYY-MM-DD -->
<!-- source: voice transcription via voice-to-prompt skill -->
<!-- classification: PROPOSAL -->
# Proposal: [Descriptive Topic Title]
```

### Context
Write a 2-3 sentence summary of the design space being explored and why, written for a future agent that has never seen this codebase before. State what the user is trying to decide or explore.

### Original Transcription
Write the user's raw text, preserved verbatim in a blockquote. This ensures the original intent is always recoverable.

### Refined Instructions

Write this delegation directive into the prompt file immediately after the `## Refined Instructions` heading:

```markdown
> **Delegation:** This is a PROPOSAL task with three phases. Phase 1 spawns Brainstorm Agent teammates who each write an independent proposal to `./proposals/`. Phase 2 runs `/devils-advocate` against each proposal, writing reviews to `./proposals/<proposal_name>_review_by_<devil_advocate_name>.md`. Phase 3 synthesizes all proposals and reviews into a recommendation. Phases must run sequentially; agents within each phase run in parallel.
```

#### Phase 1: Brainstorm Agents

Write instructions telling the future agent to spawn 3-5 brainstorm agents in parallel, each with a distinct persona. Each agent should write its proposal as a standalone markdown file in a `./proposals/` directory.

Choose personas appropriate to the transcription's subject matter. Write a persona table into the prompt file, selecting from (or inventing) personas like:

```markdown
| Persona | Lens | Good for |
|---------|------|----------|
| `Pragmatist` | Minimum viable change, ship fast, avoid over-engineering | Feature additions, quick wins |
| `Architect` | Long-term structure, extensibility, separation of concerns | System design, refactors |
| `Contrarian` | Challenge the premise — is this even the right problem? | Assumptions, scope questions |
| `User-Advocate` | End-user experience, DX, ergonomics, error messages | APIs, CLIs, dashboards |
| `Performance-Hawk` | Latency, memory, concurrency, scaling bottlenecks | Hot paths, data pipelines |
| `Security-Auditor` | Attack surface, input validation, secrets handling | Auth, external integrations |
| `Vision-Keeper` | Alignment with project north star (Polya topology, dynamic skills, continuous runtime, dashboard) | Strategic decisions |
| `Test-Skeptic` | How would you prove this works? What would reward-hacking look like? | Test strategy, fixtures |
```

Write each brainstorm agent spawn directive into the prompt file using this format:

```markdown
1. **Spawn a `Brainstorm-<Persona>` teammate** with the following instructions:
   - Read `repomix-architecture-flow-compressed.xml` and `rlm_adk_docs/UNDERSTAND.md` for codebase context
   - [Any persona-specific references to read]
   - Consider the problem: [restate the transcription's core question/goal]
   - Write your proposal to `./proposals/<topic>_<persona>.md` with these sections:
     - **## Approach** — What you'd build and how
     - **## Rationale** — Why this approach over alternatives
     - **## Trade-offs** — What you're giving up, what risks remain
     - **## Sketch** — Pseudocode, file structure, or architecture diagram (whatever fits)
     - **## Open Questions** — What you'd want answered before committing
```

Write guidance into the prompt file telling the future agent that each persona should:
- Reference exact file paths when proposing changes to existing code
- Be opinionated — proposals should take clear positions, not hedge
- Stay grounded in the actual codebase (read the architecture snapshot)
- Disagree with each other — that's the point

#### Phase 2: Devil's Advocate Review

Write instructions into the prompt file telling the future agent that after all Phase 1 brainstorm agents have completed, it should run `/devils-advocate` against each proposal file in `./proposals/`. Write this into the prompt:

```markdown
## Phase 2: Devil's Advocate Review

After all Phase 1 proposals exist in `./proposals/`, run `/devils-advocate` against each proposal file.

For each proposal, the three devil's advocate critics (ADK Callback Expert, Vision Alignment Challenger, Prior-Art Researcher) will each produce findings. Write each critic's review to `./proposals/<proposal_name>_review_by_<devil_advocate_name>.md`.

The review files must follow the devil's advocate output format (A-prefixed ADK findings, V-prefixed vision findings, P-prefixed prior-art findings, X-prefixed cross-cutting themes, R-prefixed prioritized recommendations).

**Sequencing is critical:** Phase 2 cannot start until all Phase 1 proposals exist. Within Phase 2, reviews of different proposals can run in parallel.
```

#### Phase 3: Synthesis

Write instructions into the prompt file telling the future agent to produce a final synthesis after all reviews are complete:

```markdown
## Phase 3: Synthesis

After all Phase 2 reviews are complete, write a synthesis document to `./proposals/SYNTHESIS.md` containing:
- A comparison table of all proposals (approach, key trade-off, devil's advocate verdict)
- Common themes across proposals (what did multiple personas converge on?)
- The strongest arguments from each devil's advocate review
- A recommended path forward (which proposal or combination of proposals to pursue, and why)
```

### Considerations
Write anything the future brainstorm and review agents should be aware of:
- Constraints the user mentioned that bound the design space
- Related subsystems or prior decisions that proposals must respect
- Whether the user is leaning toward a direction (note it, but don't let it suppress alternatives)
- State mutation rules (AR-CRIT-001 if dispatch/state work is in scope)

### Appendix: Code References

Write a table of every file, class, and function relevant to the design space:

```markdown
## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/orchestrator.py` | `RLMOrchestratorAgent._run_async_impl` | L278 | Orchestrator loop (may be affected) |
| `rlm_adk/dispatch.py` | `create_dispatch_closures` | L1378 | Dispatch closure factory |
```

Line numbers must be verified against the current source — do not guess. Use Grep with line number output to confirm.

### Priming References
End the prompt file with pointers for the future agents:

```markdown
## Priming References

Before starting, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow branch links relevant to this topic)
```
