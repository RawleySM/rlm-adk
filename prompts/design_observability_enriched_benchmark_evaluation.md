<!-- generated: 2026-03-18 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Design Observability-Enriched Benchmark Evaluation for Polya Understand Skills

## Context

RLM-ADK has four Polya understand skill topologies (T1-T4) that assess context completeness before planning, plus a full observability stack (SqliteTracingPlugin, REPLTracingPlugin, DataFlowTracker, ObservabilityPlugin) that captures per-call telemetry, REPL traces, state deltas, and data flow edges. The current benchmark evaluates agents only by structured output completeness (whether the agent correctly identifies intentionally missing context chunks). This prompt asks an agent team to design how the observability telemetry can be used to evaluate the *process* of understanding — not just the final verdict — enabling deeper, trace-driven scoring of how an agent went about its Polya understand phase.

## Original Transcription

> Have an agent team review the RLM-ADK agent architecture, the understand skills that have been added (the four versions), and the observability system that we have developed with its introspection into the REPL environment. I want these agents to look at the following challenge from different perspectives and propose novel ways that we can enhance the benchmarks overlay with the observability of our system: Our benchmark rates agents by its completeness of the retrieval context structured output based on intentionally missing chunks of context to solve the problem. How can we evaluate through agent evaluators built into the benchmark — an inspection of every search and method used to understand the context, store what tools were used in understanding that context, and how these relate to the Polya understand methodology and thinking model of understanding a problem before entering plan mode? How can we evaluate at a deeper level than just the structured output through our telemetry traces and observability systems to tell a story of how the agent, using an iteration of the Polya skill, went about its way to understand the context?

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate researches their assigned area, produces a written proposal document, and references exact file paths and data structures from the codebase. No code changes in this phase — this is a design/research task.

1. **Spawn a `Telemetry-Mapper` teammate to catalog every telemetry signal available during a Polya understand skill execution and map each signal to what it reveals about the agent's understanding process.**

   The teammate should:
   - Read the four Polya understand skill files (`polya_understand_t1_workflow.py`, `polya_understand_t2_flat.py`, `polya_understand_t3_adaptive.py`, `polya_understand_t4_debate.py`) and the base `polya_understand.py`
   - Read the SqliteTracingPlugin schema (3 tables: `traces`, `telemetry`, `session_state_events`) in `rlm_adk/plugins/sqlite_tracing.py` (line 258+)
   - Read the REPLTrace dataclass (`rlm_adk/repl/trace.py` line 22) and DataFlowTracker (line 120)
   - Read the skill expansion observability keys (`REPL_EXPANDED_CODE`, `REPL_SKILL_EXPANSION_META`, `REPL_DID_EXPAND`) documented in `rlm_adk_docs/observability.md` section 9
   - Read the `_rlm_state` snapshot mechanism (`rlm_adk/state.py` line 158, `rlm_adk/orchestrator.py` line 330)
   - Read the dispatch accumulator / flush_fn path (`rlm_adk/dispatch.py` line 790)
   - Produce a table mapping each telemetry signal → what aspect of "understanding" it reveals (e.g., `data_flow_edges` → "whether the agent chained one child LLM response into the next query prompt, indicating iterative refinement"; `obs:child_dispatch_count` → "how many sub-queries the agent chose to spawn"; `repl_trace_summary.llm_calls[].prompt_len` → "how much context was passed to each child investigator")
   - Identify telemetry *gaps* — aspects of understanding that the current system does NOT capture but could

2. **Spawn a `Polya-Phase-Analyst` teammate to define what "good understanding behavior" looks like for each Polya topology and propose measurable behavioral indicators derived from traces.**

   The teammate should:
   - Read all four topology skill files to understand each topology's dispatch pattern:
     - T1 (Workflow-First 3-Layer): generates a task-adaptive workflow → step assessors → optional L2 chunk assessment
     - T2 (Flat Open-Ended): generates probing questions locally → dispatches investigators + synthesizer
     - T3 (Dimension-Adaptive Round-Trip): selects relevant Polya dimensions → probes → gap re-probing
     - T4 (Adversarial Debate): dispatches optimist + critic concurrently → judge adjudicates
   - Read Polya's "Understand" methodology reference (the 14-step framework from the voice-to-prompt skill at `.claude/skills/voice-to-prompt/references/polya_understand.md`)
   - For each topology, define:
     - What trace patterns indicate *thorough* understanding (e.g., T3 should show a re-probe round for gaps, visible as a second batch dispatch in `obs:child_total_batch_dispatches`)
     - What trace patterns indicate *shallow* understanding (e.g., T2 with only 1-2 probing questions when 5 were available)
     - What trace patterns indicate *reward hacking* (e.g., the agent produces a "SUFFICIENT" verdict without dispatching any child investigators)
   - Propose a scoring rubric per topology with specific telemetry thresholds

3. **Spawn a `Benchmark-Evaluator-Architect` teammate to design the agent evaluator component that reads traces and produces a "process quality" score alongside the existing structured output score.**

   The teammate should:
   - Read the existing benchmark infrastructure: `ContractResult` (`tests_rlm_adk/provider_fake/fixtures.py` line 193), `PluginContractResult` (`tests_rlm_adk/provider_fake/contract_runner.py` line 90), `run_fixture_contract_with_plugins()` (line 360), `ScenarioRouter` (line 241), and `check_expectations()` (line 398)
   - Read the existing fixture JSON schema (documented in `rlm_adk_docs/testing.md`)
   - Read the SqliteTracingPlugin's `on_event_callback` (line 1096) which captures `session_state_events` — the raw event stream that an evaluator could query
   - Read the `telemetry` table schema (enriched columns: `repl_has_errors`, `repl_has_output`, `repl_llm_calls`, `stdout_len`, `stderr_len`, `repl_trace_summary`, `skill_instruction`)
   - Design a `ProcessEvaluator` component that:
     - Takes a `PluginContractResult` (which includes `traces_db_path`, `events`, `final_state`)
     - Queries `traces.db` for the telemetry and session_state_events tables
     - Applies the scoring rubric from step 2
     - Returns a `ProcessScore` with dimensions: coverage_thoroughness, question_quality, synthesis_depth, iterative_refinement, appropriate_tool_use
   - Specify how `ProcessScore` integrates with the existing `ContractResult.passed` / `check_expectations()` flow
   - Define the fixture schema extensions needed (e.g., `expected_process` section in fixture JSON)

4. **Spawn a `Data-Flow-Storyteller` teammate to design a narrative reconstruction system that reads traces and produces a human-readable "understanding story" showing how the agent navigated the Polya understand phase.**

   The teammate should:
   - Read the `DataFlowTracker` class (`rlm_adk/repl/trace.py` line 120) — specifically `check_prompt()` and `data_flow_edges`
   - Read the `REPLTracingPlugin` (`rlm_adk/plugins/repl_tracing.py`) which aggregates traces by `d{depth}:i{iteration}`
   - Read the `repl_trace_summary` column in the `telemetry` table (`rlm_adk/plugins/sqlite_tracing.py` line 286)
   - Read the per-iteration token breakdown in `ObservabilityPlugin` (`rlm_adk/plugins/observability.py` line 222)
   - Design a `TraceNarrative` data structure and builder that:
     - Reconstructs the chronological sequence of: skill activation → question generation → child dispatch → response collection → synthesis → verdict
     - Uses `data_flow_edges` to show information flow (which child response fed into which subsequent prompt)
     - Uses `obs:child_dispatch_latency_ms` to show timing
     - Uses `obs:child_error_counts` to identify retries/failures in the understanding process
     - Produces markdown output suitable for benchmark reports
   - Propose how this narrative could be *scored* by a judge LLM evaluator (an `llm_query()` call within the benchmark that reads the narrative and rates understanding quality)

5. **Spawn a `Integration-Synthesizer` teammate to read the proposals from steps 1-4 and produce a unified design document with a phased implementation plan.**

   *[Added — the transcription didn't mention a synthesis step, but four independent proposals need to be reconciled into a coherent system before implementation begins.]*

   The teammate should:
   - Read all four proposals produced by steps 1-4
   - Identify overlaps, conflicts, and dependencies between the proposals
   - Produce a unified design that:
     - Defines the data flow from agent execution → trace capture → evaluator → process score → narrative
     - Specifies which components are new files vs extensions to existing files
     - Addresses AR-CRIT-001 compliance for any new state writes
     - Considers the `_rlm_state` read-only snapshot for making telemetry visible to REPL code during execution
   - Propose a 3-phase implementation plan:
     - Phase 1: Telemetry gap fills + ProcessEvaluator skeleton
     - Phase 2: Per-topology scoring rubrics + fixture schema extensions
     - Phase 3: TraceNarrative builder + judge LLM integration
   - For each phase, specify which existing test files need new fixtures and what the TDD sequence looks like

## Considerations

- **No code changes in this phase.** All five teammates produce design documents / proposals only. Implementation comes after the synthesized plan is reviewed.
- **Existing telemetry is rich.** The `traces.db` schema already captures per-call telemetry, REPL trace summaries, skill instructions, and state events. The design should maximize reuse of existing capture before proposing new instrumentation.
- **AR-CRIT-001 applies** to any proposed state writes in new evaluation hooks. All writes must flow through `tool_context.state`, `callback_context.state`, or `EventActions(state_delta={})`.
- **Worker observability path is separate** from plugin callbacks (ObservabilityPlugin does NOT fire for workers). Any evaluator inspecting child dispatch behavior must read from the dispatch accumulator path (`obs:child_*` keys), not from plugin hooks.
- **DataFlowTracker requires RLM_REPL_TRACE >= 1.** Benchmark fixtures should set `repl_trace_level=1` (already the default in `run_fixture_contract_with_plugins()`).
- **The `_rlm_state` snapshot** is built before code execution in REPLTool — it exposes dispatch metrics from *previous* turns to REPL code. The cumulative counters (`obs:*_total`) provide monotonically increasing values suitable for process evaluation.
- **Per-topology scoring must account for topology differences.** T4 (debate) naturally has fewer child dispatches than T3 (adaptive round-trip), so raw dispatch count is not a universal quality metric.
- **Judge LLM evaluator cost.** If the narrative scoring uses `llm_query()` within the benchmark, this adds API cost per fixture run. Consider whether a deterministic rubric can substitute for most cases.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/skills/polya_understand.py` | `POLYA_UNDERSTAND_SKILL` | L36 | Base Polya understand skill (1329 lines) |
| `rlm_adk/skills/polya_understand_t1_workflow.py` | `run_polya_understand_t1_workflow` | L615 | T1 Workflow-First 3-Layer topology (1042 lines) |
| `rlm_adk/skills/polya_understand_t2_flat.py` | `run_polya_understand_t2_flat` | L379 | T2 Flat Open-Ended topology (600 lines) |
| `rlm_adk/skills/polya_understand_t3_adaptive.py` | `run_polya_understand_t3_adaptive` | L759 | T3 Dimension-Adaptive Round-Trip topology (1162 lines) |
| `rlm_adk/skills/polya_understand_t4_debate.py` | `run_polya_understand_t4_debate` | L603 | T4 Adversarial Debate topology (906 lines) |
| `rlm_adk/skills/catalog.py` | `PROMPT_SKILL_REGISTRY` | L88 | Central skill catalog with T1-T4 registrations |
| `rlm_adk/plugins/sqlite_tracing.py` | `SqliteTracingPlugin` | L325 | 3-table trace schema (traces, telemetry, session_state_events) |
| `rlm_adk/plugins/sqlite_tracing.py` | `telemetry` table DDL | L258 | Per-call telemetry with REPL enrichment columns |
| `rlm_adk/plugins/sqlite_tracing.py` | `session_state_events` table DDL | L296 | Curated state key change capture |
| `rlm_adk/plugins/sqlite_tracing.py` | `on_event_callback` | L1096 | State delta event capture |
| `rlm_adk/plugins/sqlite_tracing.py` | `repl_trace_summary` column | L286 | Embedded REPL trace in telemetry rows |
| `rlm_adk/plugins/observability.py` | `ObservabilityPlugin` | L50 | Token accounting, finish reasons, per-iteration breakdown |
| `rlm_adk/plugins/observability.py` | Per-iteration breakdown entry | L222 | `{iteration, call_number, input_tokens, output_tokens, ...}` |
| `rlm_adk/plugins/repl_tracing.py` | `REPLTracingPlugin` | Class | Aggregates traces by `d{depth}:i{iteration}` |
| `rlm_adk/repl/trace.py` | `REPLTrace` | L22 | Per-code-block trace accumulator |
| `rlm_adk/repl/trace.py` | `DataFlowTracker` | L120 | Detects response→prompt chaining via substring fingerprint |
| `rlm_adk/tools/repl_tool.py` | `REPLTool` | L55 | REPL execution, skill expansion, trace injection |
| `rlm_adk/dispatch.py` | `create_dispatch_closures` | L168 | Child dispatch closures with local accumulators |
| `rlm_adk/dispatch.py` | `flush_fn` | L790 | Snapshots dispatch accumulators into tool_context.state |
| `rlm_adk/state.py` | `REPL_STATE_SNAPSHOT` (`_rlm_state`) | L158 | Read-only state snapshot injected into REPL namespace |
| `rlm_adk/orchestrator.py` | `_run_async_impl` | L230 | Orchestrator main loop, cumulative counter seeding |
| `rlm_adk/repl/skill_registry.py` | `expand_skill_imports` | L223 | Synthetic import expansion (skill source inlining) |
| `tests_rlm_adk/provider_fake/contract_runner.py` | `PluginContractResult` | L90 | Full result with events, final_state, traces_db_path |
| `tests_rlm_adk/provider_fake/contract_runner.py` | `run_fixture_contract_with_plugins` | L360 | Plugin-enabled fixture runner entry point |
| `tests_rlm_adk/provider_fake/fixtures.py` | `ContractResult` | L193 | Contract validation result with checks/call_summary |
| `tests_rlm_adk/provider_fake/fixtures.py` | `ScenarioRouter` | L241 | FIFO response dispatcher with fault injection |
| `tests_rlm_adk/provider_fake/fixtures.py` | `check_expectations` | L398 | Validates run output against fixture expectations |
| `.claude/skills/voice-to-prompt/references/polya_understand.md` | Polya methodology | Full file | 14-step Understand phase reference |
| `rlm_adk_docs/observability.md` | Section 8 (Worker Obs Path) | — | Dispatch accumulator → flush_fn → state flow |
| `rlm_adk_docs/observability.md` | Section 8.1 (Cumulative Keys) | — | Per-iteration vs cumulative dispatch counters |
| `rlm_adk_docs/observability.md` | Section 9 (Skill Expansion Keys) | — | REPL_EXPANDED_CODE, REPL_SKILL_EXPANSION_META |
| `rlm_adk_docs/testing.md` | Fixture JSON Schema | — | Full fixture format with matcher operators |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow branches: Observability, Testing, Skills & Prompts)
3. `rlm_adk_docs/observability.md` — full observability stack reference (sections 2, 3, 4, 8, 8.1, 9, 10)
4. `rlm_adk_docs/testing.md` — benchmark/fixture infrastructure reference
5. `rlm_adk_docs/skills_and_prompts.md` — skill system and source expansion mechanics
