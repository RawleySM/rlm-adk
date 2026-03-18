<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Propose Alternative Topologies for `polya_understand_2`

## Context

The existing `polya-understand` REPL skill (`rlm_adk/skills/polya_understand.py`) implements a 5-phase loop (REFRAME → PROBE → SYNTHESIZE → VALIDATE → REFLECT) with rigid, dimension-locked prompt templates across 8 Polya dimensions. It is complex (~1330 lines, 17 source-expandable REPL exports) and prescriptive — every child receives a single Polya dimension + a single context packet and returns a structured response in a fixed format. The parent only sees a manifest, never raw context.

The goal is to **propose several alternative topologies** for a second skill, `polya_understand_2`, that is simpler and more open-ended. One candidate topology should match the 3-layer "workflow-first" approach described below. **Do not implement anything yet** — this is a design proposal only.

## Original Transcription

> The current polya_understand skill is very complicated and I'm interested in running it, but I'm not sure it's gonna work. I envision the understand to be derived from the `rlm_adk_docs` folder — there is a file called `polya_understand.chatGPT_5-4.md` and this file shows the Polya understand breakdown in how a problem space is fully assessed with different probing questions. I would like to have the polya_understand skill have a second version, namely `_2` version of the polya_understand, that is more open and involves the parent RLM at layer zero considering the user query or the objective provided in the prompt, and in stages, using its world model and knowledge of the problem to describe a workflow that it would consider to achieve the objective. It would then be up to the `llm_query` functions to parse out the various ways to look at that problem space to the children agents, reflecting on one of the perspectives of the Polya understand process, considering the workflow that's presented by the parent and assessing the completeness of the context variable that it's assigned. So in this instance, the parent is considering the workflow that might be undertaken, and then possibly the layer one child takes that objective and divides up the context or the codebase or whatever the context variable is to maybe a third layer — so layer two — which would be the agents responsible for assessing their chunk and summarizing what is actually there with respect to the workflow that was passed down from layer zero. Your job is to propose a different, simpler polya_understand_2 that we can run against the first version, and I would like you to, before you even develop that skill, propose a couple other topologies that we might consider building. So don't go ahead and build yet, but let's go ahead and propose several topologies, one of which would be the one I tried to describe.

## Refined Instructions

> **Delegation:** This is a **design proposal task**, not an implementation task. The deliverable is a topology comparison document. No code should be written.

1. **Study the existing `polya-understand` v1 skill in `rlm_adk/skills/polya_understand.py` (all 1330 lines).** Map its dispatch pattern: which calls use `llm_query()` (single child), which use `llm_query_batched()` (parallel fanout), and how context is chunked/distributed. Count the total LLM calls per cycle (1 REFRAME + N PROBE + 1 SYNTHESIZE + 1 VALIDATE + 1 REFLECT = N+4 per cycle, where N = number of dimension-packet assignments). Note the rigidity: every child gets a fixed Polya dimension question template and must return structured headings.

2. **Read the Polya methodology reference at `rlm_adk_docs/vision/polya_topology/polya_understand.chatGPT_5-4.md`** to understand the theoretical framework v1 was derived from. Also read `rlm_adk_docs/vision/polya_topology/JTBD_intake.md` for the JTBD intake template that influenced the validation phases.

3. **Propose at least 4 candidate topologies for `polya_understand_2`**, including the user's described "workflow-first" 3-layer approach as one candidate. Each topology proposal must include:
   - **Name**: A short descriptive label (e.g., "Workflow-First 3-Layer", "Flat Open-Ended", etc.)
   - **Layer diagram**: ASCII showing L0 → L1 → L2 (if applicable) with what each layer does
   - **Dispatch pattern**: Which calls use `llm_query()` vs `llm_query_batched()`, and how many total LLM calls result for a typical run
   - **What the parent (L0) does**: Does it see raw context or just a manifest? Does it generate a workflow plan, probing questions, or something else?
   - **What children do**: What do they receive? What do they return? How prescriptive vs open-ended are their prompts?
   - **How context flows**: Does context go to L1, L2, or both? Is it chunked, sharded, or passed whole?
   - **Simplicity assessment**: How many source-expandable REPL exports would this require? How many phase-specific prompt constants? Compare to v1's 17 exports and 5 phase instruction constants.
   - **Strengths**: What would this topology do better than v1?
   - **Weaknesses**: What would it lose compared to v1?
   - **Risk**: What could go wrong at runtime? (e.g., model drifts off-task without structured constraints, context overflow, child results too vague to synthesize)

4. **One of the 4 topologies MUST be the user's described approach**, which works as follows:
   - **L0 (Parent)**: Receives the objective + context manifest. Uses its world model to describe a multi-step **workflow** it would follow to achieve the objective. Does NOT use Polya dimension templates.
   - **L1 (Workflow Assessors)**: Each child receives one step of the workflow + the full context (or a relevant partition). Assesses whether the assigned context is complete enough to execute that workflow step. May subdivide the context and dispatch to L2.
   - **L2 (Chunk Assessors)**: Each child receives a chunk of context + the workflow step from L0. Summarizes what is actually present in the chunk with respect to the workflow step. Returns a completeness assessment.
   - The final synthesis happens at L0 or L1 after collecting L2 results.

5. **Include a comparison table** at the end summarizing all topologies across these axes:
   - Total LLM calls (typical case)
   - Max recursion depth used
   - Prompt rigidity (high/medium/low)
   - Context visibility at L0 (manifest only / full / partial)
   - Implementation complexity (estimated REPL exports count)
   - Risk of model drift
   - Best suited for (large repos? small tasks? unknown domains?)

6. **End with a recommendation** of which 1-2 topologies to build first, and why. Consider that the purpose is to run `polya_understand_2` against `polya_understand` (v1) on the same inputs and compare output quality.

## Considerations

- The dispatch primitives available are `llm_query()` (spawns 1 child RLMOrchestratorAgent at depth+1) and `llm_query_batched()` (spawns K children concurrently via semaphore-limited ParallelAgent). Both are available in REPL code. Children at depth+1 have their own REPLs and can recursively dispatch further.
- `RLM_MAX_DEPTH` (default 3) limits recursion. A 3-layer topology (L0 → L1 → L2) uses depth 0, 1, 2 — which fits within the default limit but leaves no headroom for children to dispatch further.
- The existing v1 skill is a **source-expandable REPL skill**: the parent's REPL code calls `from rlm_repl_skills.polya_understand import run_polya_understand`, which expands into inline Python source before the AST rewriter transforms `llm_query()` calls to async. Any new topology must follow the same pattern (registered via `ReplSkillExport` in `rlm_adk/repl/skill_registry.py`).
- AR-CRIT-001 state mutation rules apply to any skill that writes to session state. The v1 skill does NOT directly write state — it returns a `PolyaUnderstandResult` object and the parent REPL code decides what to do with it. This is a good pattern to preserve.
- The user explicitly wants "simpler" — fewer phase-specific prompt constants, less rigid output structure, more reliance on the model's natural reasoning ability. The tradeoff is that less structure means more risk of model drift.
- The reference doc `polya_understand.chatGPT_5-4.md` is identical in content to the voice-to-prompt skill's `references/polya_understand.md` — it is the detailed 14-step Polya methodology. The `polya_understand_gemini.md` is a more compact 4-section version (Core Questions, Practical Actions, Diagnostic Prompts, Key Quotes).

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/skills/polya_understand.py` | `POLYA_UNDERSTAND_SKILL` | L36 | V1 skill definition being compared against |
| `rlm_adk/skills/polya_understand.py` | `run_polya_understand` (src) | L822 | V1 main orchestrator function (source-expandable) |
| `rlm_adk/skills/polya_understand.py` | `POLYA_DIMENSIONS` (src) | L172 | V1's 8 fixed dimension definitions |
| `rlm_adk/skills/catalog.py` | `PROMPT_SKILL_REGISTRY` | L72 | Where new skill would be registered |
| `rlm_adk/skills/catalog.py` | `PromptSkillRegistration` | L30 | Registration dataclass for prompt-visible skills |
| `rlm_adk/dispatch.py` | `create_dispatch_closures` | L167 | Factory for `llm_query` / `llm_query_batched` closures |
| `rlm_adk/dispatch.py` | `llm_query_async` | L655 | Single-child dispatch (spawns child orchestrator) |
| `rlm_adk/dispatch.py` | `llm_query_batched_async` | L695 | Parallel multi-child dispatch |
| `rlm_adk/orchestrator.py` | `RLMOrchestratorAgent` | L196 | Base orchestrator class (parent and child) |
| `rlm_adk/orchestrator.py` | `_run_async_impl` | L227 | Orchestrator execution entry point |
| `rlm_adk/repl/skill_registry.py` | `register_skill_export` | L219 | Source-expandable REPL export registration |
| `rlm_adk_docs/vision/polya_topology/polya_understand.chatGPT_5-4.md` | Full doc | L1 | Polya methodology reference (14-step breakdown) |
| `rlm_adk_docs/vision/polya_topology/polya_understand_gemini.md` | Full doc | L1 | Compact Polya reference (4-section) |
| `rlm_adk_docs/vision/polya_topology/JTBD_intake.md` | Full doc | L1 | JTBD intake template influencing validation phases |

## Priming References

Before starting, read these in order:
1. `rlm_adk/skills/polya_understand.py` — the full v1 skill (1330 lines) to understand what you are proposing alternatives to
2. `rlm_adk_docs/vision/polya_topology/polya_understand.chatGPT_5-4.md` — the Polya methodology v1 was derived from
3. `rlm_adk_docs/vision/polya_topology/JTBD_intake.md` — the JTBD intake template
4. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow the Skills & Prompts and Core Loop branches)
5. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for dispatch mechanics context
