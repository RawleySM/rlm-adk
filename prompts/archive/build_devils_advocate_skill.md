<!-- generated: 2026-03-18 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Build a Devil's Advocate Review Skill

## Context

Build a new Claude Code skill (`/devils-advocate`) that, when invoked against a plan, proposal, or set of code files, delegates to a team of specialized agents. Each agent primes its context by reading domain-specific reference documents, then critiques the subject matter from a devil's advocate perspective. The skill orchestrates three parallel review tracks: ADK callback utilization, vision alignment, and prior-art research.

## Original Transcription

> Build a devil's advocate skill that instructs the model to delegate to an agent team the review of some plan, proposal or set of code files, spawning a set of agents that first prime their context by reading a document related to their personality or expertise, then review the subject matter from a devil's advocate perspective. The skill should spawn a google-adk callback expert that asks where the implementation or plan is under-utilizing the ADK global (plugins) or local (agent, model, tool) callbacks. This agent should read `ai_docs/adk_callbacks.md`. Another agent should be spawned to review vision documents in `rlm_adk_docs/vision` and challenge the implementation plan's scope. What could be updated to better align the progress from the plan to Rawley's vision? A third agent should be spawned to review the plan and ask the question "Are we re-inventing the wheel? Are there resources online in open source repos, public datasets, substack tutorials, etc, that pre-package most of what's encompassed in this plan?" This devil's advocate should construct search queries and then spawn a set of online explorers, each assigned to one of the following: substack (see `ai_docs/substack_scraping.md`), reddit, arxiv, and github, and the general web.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step and documents the change with a demo via `uvx showboat --help`.

### Phase 1: Skill Scaffold

1. **Spawn a `Skill-Scaffold` teammate to create the skill directory and SKILL.md at `.claude/skills/devils-advocate/SKILL.md`.**

   The SKILL.md frontmatter must follow the convention established by existing skills (`voice-to-prompt`, `pythonista-nicegui`). Use this structure:

   ```yaml
   ---
   name: devils-advocate
   description: "Devil's advocate review of plans, proposals, or code. Spawns a team of specialized critics — an ADK callback expert, a vision alignment challenger, and a prior-art researcher — to stress-test the subject from multiple adversarial angles. Use when the user says 'challenge this', 'devil's advocate', 'critique this plan', 'review this proposal', 'stress test', 'poke holes', or invokes /devils-advocate with a plan file or description."
   ---
   ```

   The skill body must instruct Claude Code to perform the following workflow when invoked:

   **Step 0 — Identify the Subject Matter.** The user will provide either: (a) a path to a plan/proposal markdown file, (b) a set of code file paths, or (c) inline text describing a plan. The skill must parse the arguments to determine which. If no arguments are provided, ask the user what to review.

   **Step 1 — Spawn Three Devil's Advocate Agents in Parallel.** Use the Agent tool to launch all three simultaneously (a single message with three Agent tool calls). Each agent gets a complete, self-contained prompt describing:
   - What reference document(s) to read first (priming)
   - The subject matter to critique (the plan/proposal/code)
   - The specific adversarial lens to apply
   - The output format expected

   **Step 2 — Synthesize.** After all three agents return, synthesize their findings into a single structured report with sections for each critic, key themes that appeared across multiple critics, and a prioritized list of actionable recommendations.

### Phase 2: Agent Definitions (within SKILL.md)

2. **Spawn a `Callback-Critic-Author` teammate to write the ADK Callback Expert agent specification within the SKILL.md.**

   This agent's prompt template (embedded in SKILL.md) must instruct it to:

   - **Prime:** Read `ai_docs/adk_callbacks.md` (1191 lines — comprehensive ADK callback documentation covering `before_agent`, `after_agent`, `before_model`, `after_model`, `before_tool`, `after_tool` callbacks, plus plugin architecture).
   - **Review:** Read the subject matter (plan/proposal/code files).
   - **Critique from this lens:** "Where is this plan under-utilizing ADK's callback and plugin system?" Specifically:
     - Are there places where `before_model_callback` / `after_model_callback` could add guardrails, caching, or request modification that the plan implements manually?
     - Are there places where `before_tool_callback` / `after_tool_callback` could handle validation, logging, or result transformation that the plan handles inline?
     - Are there places where a global `BasePlugin` (with `on_event_callback`, `before_run_callback`, `after_run_callback`) could replace scattered per-agent logic?
     - Does the plan miss opportunities for state management via `callback_context.state` or `tool_context.state`?
     - Could `before_agent_callback` implement conditional skipping that the plan handles with explicit branching?
   - **Output format:** Numbered findings, each with: (a) what the plan does now, (b) what ADK callback/plugin could replace it, (c) benefit of the callback approach (less code, better separation, event tracking, etc.).

3. **Spawn a `Vision-Critic-Author` teammate to write the Vision Alignment Challenger agent specification within the SKILL.md.**

   This agent's prompt template must instruct it to:

   - **Prime:** Read all documents under `rlm_adk_docs/vision/`. The directory contains these subdirectories and files:
     - `polya_topology/` — Polya understand-to-topology proposals, JTBD intake, Gemini and ChatGPT perspectives (4 files)
     - `dynamic_skill_loading/` — Codex proposal, reframed proposal, dynamic skill loading design (3 files)
     - `continous_runtime/` — Autonomous self-improvement, evolution principles (2 files)
     - `inventing_on_principle_dashboard/` — Interactive dashboard, Inventing on Principle philosophy, NiceGUI dashboard ideas (3 files)
   - **Review:** Read the subject matter.
   - **Critique from this lens:** "Does this plan advance Rawley's vision, or does it drift?" Specifically:
     - Does the plan move toward the Polya topology engine (horizontal/vertical/hybrid workflows via dynamic instructions)?
     - Does it contribute to dynamic skill loading from REPL execution history?
     - Does it align with the autonomous self-improvement via cron-triggered agents vision?
     - Does it support the interactive dashboard ("Inventing on Principle" philosophy)?
     - What could be changed to better align progress with these vision documents?
     - Is the plan's scope too narrow (missing vision opportunities) or too wide (doing things the vision doesn't call for)?
   - **Output format:** For each vision document, state whether the plan advances it, is neutral, or conflicts. Then provide specific recommendations for tighter alignment.

4. **Spawn a `Prior-Art-Critic-Author` teammate to write the "Are We Reinventing the Wheel?" researcher agent specification within the SKILL.md.**

   This agent's prompt template must instruct it to:

   - **Prime:** Read `ai_docs/substack_scraping.md` for context on Substack research tooling.
   - **Analyze:** Read the subject matter and extract 3-5 core capabilities or components the plan proposes to build.
   - **Construct search queries:** For each capability, generate 2-3 targeted search queries optimized for each platform.
   - **Spawn 5 explorer sub-agents in parallel** (a single message with 5 Agent tool calls), each assigned to one channel:
     1. **Substack Explorer** — Search Substack newsletters and posts. Use the `/substack-research` skill if available, or construct queries using the patterns from `ai_docs/substack_scraping.md`. Focus on tutorials, implementation walkthroughs, and "how I built X" posts.
     2. **Reddit Explorer** — Search Reddit (r/MachineLearning, r/LocalLLaMA, r/artificial, r/Python, r/googlecloud) for discussions, implementations, and recommendations related to each capability. Use WebSearch with `site:reddit.com` queries.
     3. **arXiv Explorer** — Search arXiv for papers that describe systems, frameworks, or techniques that overlap with the plan's capabilities. Use WebSearch with `site:arxiv.org` queries. Focus on implementation papers, not just theory.
     4. **GitHub Explorer** — Search GitHub for repositories that implement similar capabilities. Use WebSearch with `site:github.com` queries. Look for repos with recent activity, meaningful star counts, and good documentation.
     5. **General Web Explorer** — Broad web search for blog posts, documentation, tutorials, and tools that address the plan's capabilities. Focus on practical implementations, not marketing pages.
   - **Synthesize:** After all 5 explorers return, compile findings into a report organized by capability, listing for each: existing tools/repos/articles found, how much of the planned work they cover, and a recommendation (use as-is, adapt, or build from scratch).
   - **Output format:** A table per capability with columns: Source, URL, Coverage (%), Recommendation. Then a summary: "X of Y planned capabilities have substantial prior art that could save development time."

### Phase 3: Integration

5. **Spawn an `Integration` teammate to verify the skill works end-to-end.**

   - Verify the SKILL.md parses correctly (valid YAML frontmatter, well-formed markdown).
   - Verify all referenced file paths exist in the codebase (`ai_docs/adk_callbacks.md`, `ai_docs/substack_scraping.md`, `rlm_adk_docs/vision/` and its subdirectories).
   - Verify the skill description triggers on appropriate phrases: "devil's advocate", "challenge this", "critique this plan", "poke holes", "stress test".
   - Test that the skill can be listed via the skill system (check that `.claude/skills/devils-advocate/SKILL.md` is discoverable).

   *[Added — the transcription didn't mention integration testing, but a skill that spawns nested agent teams is complex enough to warrant verification that the SKILL.md is well-formed and all file references resolve.]*

## Considerations

- **Agent tool parallelism:** The skill's instructions must explicitly tell Claude to launch all three devil's advocate agents in a *single message* with three Agent tool calls. This is critical for performance — serial agent spawning would triple wall-clock time.
- **Sub-agent nesting:** The Prior-Art Critic itself spawns 5 explorer sub-agents. This means the skill creates a two-level agent hierarchy. Ensure prompts are self-contained at each level (sub-agents don't inherit parent context).
- **File path stability:** The skill references `ai_docs/adk_callbacks.md` and `rlm_adk_docs/vision/` by path. If these move, the skill breaks. The SKILL.md should reference these as relative paths from project root.
- **Subject matter injection:** Each agent needs the subject matter (plan/proposal) injected into its prompt. The SKILL.md must template this — e.g., `{{SUBJECT_MATTER}}` or explicit instructions to "Read the file at [path provided by user]".
- **WebSearch availability:** The Prior-Art explorer agents depend on WebSearch and WebFetch tools. If these are unavailable (e.g., in offline mode), the skill should gracefully note that prior-art research requires internet access.
- **Existing skill convention:** Follow the patterns in `.claude/skills/voice-to-prompt/SKILL.md` and `.claude/skills/pythonista-nicegui/SKILL.md` for frontmatter format, description phrasing, and instruction structure.

## Appendix: Code References

| File | Item | Relevance |
|------|------|-----------|
| `.claude/skills/voice-to-prompt/SKILL.md` | Existing skill definition | Convention reference for SKILL.md format |
| `.claude/skills/pythonista-nicegui/SKILL.md` | Existing skill definition | Convention reference for frontmatter and description |
| `ai_docs/adk_callbacks.md` | ADK callback documentation (1191 lines) | Priming document for ADK Callback Expert agent |
| `ai_docs/substack_scraping.md` | Substack scraping tool rankings | Priming document for Prior-Art researcher |
| `rlm_adk_docs/vision/polya_topology/` | 4 files: JTBD_intake.md, polya_understand_2_topology_proposals.md, polya_understand.chatGPT_5-4.md, polya_understand_gemini.md | Priming for Vision Alignment agent |
| `rlm_adk_docs/vision/dynamic_skill_loading/` | 3 files: codex_proposal.md, codex_proposal_reframed.md, dynamic_skill_loading.md | Priming for Vision Alignment agent |
| `rlm_adk_docs/vision/continous_runtime/` | 2 files: autonomous_self_improvement.md, evolution_principles.md | Priming for Vision Alignment agent |
| `rlm_adk_docs/vision/inventing_on_principle_dashboard/` | 3 files: interactive_dashboard.md, inventing_on_principle.md, NiceGUI_agent_dashboard_ideas.md | Priming for Vision Alignment agent |
| `rlm_adk_docs/UNDERSTAND.md` | Codebase orientation guide | General context for agents reviewing code |

## Priming References

Before starting implementation, read these in order:
1. `.claude/skills/voice-to-prompt/SKILL.md` — existing skill to match conventions
2. `.claude/skills/pythonista-nicegui/SKILL.md` — second skill convention reference
3. `ai_docs/adk_callbacks.md` — understand what the Callback Expert agent will be priming on
4. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow Vision & Roadmap branch)
