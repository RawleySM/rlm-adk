# Proposal 02: Polya Phase Analyst -- Behavioral Indicators from Traces

**Author:** Polya-Phase-Analyst teammate
**Date:** 2026-03-18
**Status:** PROPOSAL (no code changes)

---

## Overview

This document defines what "good understanding behavior" looks like for each Polya topology (T1-T4), proposes measurable behavioral indicators derived from existing traces and telemetry, and provides a scoring rubric, Polya methodology alignment, and anti-pattern catalog.

All indicators reference telemetry already emitted by:
- `flush_fn()` in `rlm_adk/dispatch.py` (lines 790-827) -- per-iteration and cumulative dispatch accumulators
- `ObservabilityPlugin` in `rlm_adk/plugins/observability.py` (lines 50-408) -- token accounting, finish reasons
- `SqliteTracingPlugin` in `rlm_adk/plugins/sqlite_tracing.py` -- `session_state_events` table, `telemetry` table
- `REPLTrace` / `DataFlowTracker` in `rlm_adk/repl/trace.py` (lines 22-155) -- per-code-block trace data
- State keys defined in `rlm_adk/state.py` (lines 97-107) -- `obs:child_*` keys

---

## 1. Per-Topology Behavioral Profiles

### 1.1 T1: Workflow-First 3-Layer

**Source:** `rlm_adk/skills/polya_understand_t1_workflow.py`

**Architecture recap:**
- Phase 1 (L0): `llm_query()` -- generates workflow steps from manifest only (line 679)
- Phase 2 (L1): `llm_query_batched()` -- dispatches N step assessors (line 702)
- Phase 3 (L2, conditional): `llm_query_batched()` -- dispatches chunk assessors when packet count > `l2_threshold` or L1 requests it (line 738)
- Phase 4: `llm_query()` -- synthesis (line 767)

**Minimum LLM calls:** 3 (L0 workflow gen + L1 batch + synthesis). With L2: 4.

#### Thorough Understanding Indicators

| Indicator | Telemetry Source | Expected Pattern |
|-----------|-----------------|------------------|
| Workflow step count >= 4 | Parse `T1WorkflowResult.workflow_steps` length from debug_log or child summary text | 4-8 steps generated |
| L1 assessments cover all steps | `obs:child_dispatch_count` after L1 batch >= step count | Dispatch count matches step count |
| L2 triggered for ambiguous steps | `obs:child_total_batch_dispatches` >= 2 | Second batch dispatch visible |
| Synthesis references gap evidence | Child summary `obs:child_summary@d1f{N}` contains non-empty result_text | Gap assessment field is populated |
| Data flow edges present | `REPLTrace.data_flow_edges` (trace.py line 31) | >= 1 edge from L1 responses feeding into synthesis prompt |
| Per-step STATUS parsing yields PARTIAL/MISSING for at least one step | Parse from child result text | Not all steps report SUFFICIENT |
| Retrieval order is non-empty when gaps exist | `T1WorkflowResult.retrieval_order` | len > 0 correlates with PARTIAL/MISSING statuses |

#### Shallow Understanding Indicators

| Indicator | Telemetry Source | Detection |
|-----------|-----------------|-----------|
| Only 1-2 workflow steps generated | `obs:child_dispatch_count_total` == 3-4 (1 L0 + 1-2 L1 + 1 synth) | Total dispatch count suspiciously low |
| All steps marked SUFFICIENT with no evidence | Child summary result_preview contains "SUFFICIENT" but EVIDENCE is empty | Pattern match on child summary text |
| L2 never triggered despite large context | `obs:child_total_batch_dispatches` == 1 and packet count > l2_threshold | Single batch when multi-batch expected |
| Synthesis is near-verbatim copy of a single L1 response | DataFlowTracker edge from L1 response to synthesis, synthesis length ~ L1 response length | Suspiciously short synthesis |

#### Reward Hacking Indicators

| Indicator | Detection Rule |
|-----------|---------------|
| Workflow step generation produces generic steps unrelated to objective | Parse workflow steps from debug_log; check for template phrases like "assess overall sufficiency" without objective-specific terms |
| Zero child dispatches but SUFFICIENT verdict | `obs:child_dispatch_count_total` == 0 but final output contains "SUFFICIENT" |
| L0 bypasses manifest-only constraint | L0 prompt length >> manifest length (compare `prompt_preview` in child summary to `build_context_manifest` output size) |
| Synthesis invents evidence not in L1 responses | Synthesis text contains specific claims with no substring match in any L1 child summary `result_text` |

#### Expected Dispatch Patterns

| Metric | Expected Range | Source |
|--------|---------------|--------|
| `obs:child_dispatch_count_total` | 6-20 | 1 (L0) + 4-8 (L1) + 0-8*packets (L2) + 1 (synth) |
| `obs:child_batch_dispatches_total` | 1-2 | 1 (L1 batch) + 0-1 (L2 batch) |
| `obs:child_total_batch_dispatches` (per iteration) | 1-2 | Same as above within single REPL execution |
| `data_flow_edges` | 1-3 | L0->L1 (workflow text reuse), L1->synth (assessment reuse) |
| REPL execute_code calls | 1 | Single code block runs the entire topology |

---

### 1.2 T2: Flat Open-Ended

**Source:** `rlm_adk/skills/polya_understand_t2_flat.py`

**Architecture recap:**
- Step 1: Local context string build (no LLM call)
- Step 2: Local question generation via heuristic templates (no LLM call) (line 419)
- Step 3: `llm_query_batched()` -- Q investigation children (line 429)
- Step 4: `llm_query()` -- 1 synthesis child (line 442)

**Total LLM calls:** Q + 1 (default Q=5, so 6 calls). No cycles.

#### Thorough Understanding Indicators

| Indicator | Telemetry Source | Expected Pattern |
|-----------|-----------------|------------------|
| Full question complement dispatched | `obs:child_dispatch_count` == num_questions + 1 | Default: 6 dispatches |
| Investigation responses contain evidence markers | Child summaries contain "EVIDENCE:" and "GAPS:" headings | Structured responses, not freeform |
| Verdict is not always SUFFICIENT | `T2FlatResult.verdict` in {SUFFICIENT, PARTIAL, INSUFFICIENT} | Non-trivial assessment |
| Gaps list is populated when context is incomplete | `T2FlatResult.gaps` length > 0 when context has known holes | Calibrated gap detection |
| Each investigation child produces substantive output | Per-child `result_preview` length > 100 chars | Not trivially short responses |
| Coverage assessment provides dimensional breakdown | `extract_coverage()` returns non-empty string | Not just verdict, but reasoning |

#### Shallow Understanding Indicators

| Indicator | Telemetry Source | Detection |
|-----------|-----------------|-----------|
| num_questions set to 1-2 when 5 were available | `obs:child_dispatch_count` == 2-3 | Under-utilization of available bandwidth |
| All investigation responses are near-identical | Pairwise similarity of child `result_text` > 0.8 | Template-like responses |
| Verdict is SUFFICIENT with zero gaps on incomplete context | `T2FlatResult.verdict` == "SUFFICIENT" AND `T2FlatResult.gaps` == [] | Over-optimistic |
| No GAPS markers in any investigation response | None of Q child summaries contain "GAP" | Failure to identify missing info |

#### Reward Hacking Indicators

| Indicator | Detection Rule |
|-----------|---------------|
| Agent produces SUFFICIENT verdict without dispatching any children | `obs:child_dispatch_count_total` == 0 but output contains verdict |
| Agent skips investigation and jumps to synthesis | `obs:child_batch_dispatches_total` == 0 (no batched dispatch for investigators) |
| Questions generated are not related to the objective | Cross-reference `generate_probing_questions()` output against objective terms |
| Agent fabricates investigation responses locally instead of dispatching | `obs:child_dispatch_count_total` < num_questions but result contains Q investigation "responses" |

#### Expected Dispatch Patterns

| Metric | Expected Range | Source |
|--------|---------------|--------|
| `obs:child_dispatch_count_total` | 2-11 | Q (1-10, default 5) + 1 synthesis |
| `obs:child_batch_dispatches_total` | 1 | Single batch for investigations |
| `obs:child_total_batch_dispatches` (per iteration) | 1 | Same |
| `data_flow_edges` | 0-5 | Investigation responses feeding into synthesis prompt |
| REPL execute_code calls | 1 | Single code block |

---

### 1.3 T3: Dimension-Adaptive Round-Trip

**Source:** `rlm_adk/skills/polya_understand_t3_adaptive.py`

**Architecture recap:**
- Phase 1 (SELECT): `llm_query()` -- selects 3-5 Polya dimensions (line 823)
- Phase 2 (PROBE R1): `llm_query_batched()` -- one child per dimension+packet assignment (line 844)
- Phase 3 (GAP ANALYSIS): Local Python -- `identify_gaps()` parses CONFIDENCE (line 856)
- Phase 4 (RE-PROBE R2, conditional): `llm_query_batched()` -- re-probes low-confidence dimensions (line 889)
- Phase 5 (SYNTHESIZE): `llm_query()` -- combines R1 + R2 results (line 911)

**Minimum LLM calls:** 3 (SELECT + R1 batch + SYNTHESIZE). With re-probe: 4.

#### Thorough Understanding Indicators

| Indicator | Telemetry Source | Expected Pattern |
|-----------|-----------------|------------------|
| Dimension selection is discriminating (3-5, not all 8) | `T3AdaptiveResult.selected_dimensions` length | 3-5 selected out of 8 available |
| Round 2 re-probe triggered for low-confidence dimensions | `obs:child_batch_dispatches_total` >= 2 | Second batch dispatch visible |
| `cycles_completed` == 2 | `T3AdaptiveResult.cycles_completed` | Re-probe round executed |
| Gaps detected matches low-confidence probes | `T3AdaptiveResult.gaps_detected` length > 0 | Gap analysis identified real gaps |
| R2 probes use sharpened questions (include R1 gaps) | R2 prompt contains "ORIGINAL_GAPS_FROM_ROUND_1" text | Not just repeating R1 questions |
| CONFIDENCE distribution is varied (not all HIGH) | Per-probe `T3ProbeResult.confidence` values | Mix of LOW/MEDIUM/HIGH across dimensions |
| Retrieval order is dependency-ordered | `T3AdaptiveResult.retrieval_order` | Non-empty, items in logical sequence |
| Data flow from R1 to R2 visible | `data_flow_edges` contains edge from R1 response index to R2 prompt index | Response-to-prompt chaining |

#### Shallow Understanding Indicators

| Indicator | Telemetry Source | Detection |
|-----------|-----------------|-----------|
| All dimensions selected (no filtering) | `len(selected_dimensions)` == 8 | SELECT phase failed to discriminate |
| All R1 probes report HIGH confidence | Every `T3ProbeResult.confidence` == "HIGH" | Over-confident, no gaps found |
| No re-probe despite MEDIUM/LOW confidence probes | `obs:child_batch_dispatches_total` == 1 and some R1 confidence < threshold | Gap analysis or re-probe logic bypassed |
| Synthesis ignores R2 results | Synthesis text has no reference to R2 probe evidence | R2 was dispatched but not integrated |

#### Reward Hacking Indicators

| Indicator | Detection Rule |
|-----------|---------------|
| SELECT phase returns all 8 dimensions regardless of objective | `len(selected_dimensions)` == len(POLYA_DIMENSIONS) == 8 for every run |
| Agent short-circuits gap analysis to skip R2 | `identify_gaps()` returns [] despite LOW confidence probes (local code manipulation) |
| Probe responses are generic and objective-agnostic | Probe `result_text` does not contain any terms from the objective |
| SELECT phase hard-codes dimensions instead of using LLM | `obs:child_dispatch_count_total` < 3 (missing the SELECT llm_query) |

#### Expected Dispatch Patterns

| Metric | Expected Range | Source |
|--------|---------------|--------|
| `obs:child_dispatch_count_total` | 5-18 | 1 (SELECT) + 3-8 (R1) + 0-8 (R2) + 1 (SYNTH) |
| `obs:child_batch_dispatches_total` | 1-2 | 1 (R1 batch) + 0-1 (R2 batch) |
| `data_flow_edges` | 1-5 | R1->R2 (gap text reuse), R1->synth, R2->synth |
| REPL execute_code calls | 1 | Single code block |

---

### 1.4 T4: Adversarial Debate

**Source:** `rlm_adk/skills/polya_understand_t4_debate.py`

**Architecture recap:**
- Phase 1 (ADVOCATE): `llm_query_batched([optimist_prompt, critic_prompt])` -- 2 concurrent advocates (line 649)
- Phase 2 (JUDGE): `llm_query(judge_prompt)` -- judge sees ONLY advocate outputs, never raw context (line 665)

**Total LLM calls:** 3 (2 advocates batched + 1 judge). Fixed topology -- no conditional branches.

**Key design invariant:** Judge receives ONLY advocate arguments, never raw context (line 15, line 547-548: `build_judge_prompt` takes exactly 3 args, no context parameter).

#### Thorough Understanding Indicators

| Indicator | Telemetry Source | Expected Pattern |
|-----------|-----------------|------------------|
| Both advocates produce substantive arguments | Per-child `result_preview` length > 200 chars each | Not trivially short |
| Optimist populates all 4 sections (ASSETS, LINKS, COVERAGE_MAP, READINESS_CASE) | `T4OptimistCase` fields all have len > 0 | Complete structured output |
| Critic populates all 5 sections (GAPS, RISKS, AMBIGUITIES, BLOCKERS, RETRIEVAL_NEEDS) | `T4CriticCase` fields all have len > 0 | Complete structured output |
| Judge verdict is calibrated (CONDITIONAL more common than PROCEED/HALT on mixed context) | `T4DebateResult.verdict` distribution | Not always extreme verdicts |
| Confidence map has >= 3 dimensions assessed | `len(T4DebateResult.confidence_map)` >= 3 | Multi-dimensional assessment |
| Adjudication cites specific advocate arguments | `T4DebateResult.adjudication` contains substrings from optimist/critic | Evidence-based reasoning |
| Judge invariant maintained | Judge prompt does not contain raw context (only advocate outputs) | Verify via child summary `prompt_preview` for judge call |
| Retrieval order is non-empty when verdict is HALT or CONDITIONAL | `len(retrieval_order)` > 0 when `verdict != PROCEED` | Actionable output |

#### Shallow Understanding Indicators

| Indicator | Telemetry Source | Detection |
|-----------|-----------------|-----------|
| Optimist or critic produces near-empty output | Any `T4OptimistCase`/`T4CriticCase` field has len < 20 | Weak argumentation |
| Judge always rules PROCEED regardless of critic arguments | `verdict` == "PROCEED" on contexts with known gaps | Bias toward optimism |
| Confidence map is empty or has only 1 dimension | `len(confidence_map)` <= 1 | Insufficient dimensional analysis |
| Adjudication is generic ("both sides made good points") | Adjudication text lacks specific evidence citations | Superficial reasoning |

#### Reward Hacking Indicators

| Indicator | Detection Rule |
|-----------|---------------|
| Agent skips advocate phase and produces verdict directly | `obs:child_dispatch_count_total` == 0 or == 1 (missing batch) |
| Critic fabricates problems not grounded in context | Critic GAPS/RISKS text contains no overlap with original context terms |
| Optimist fabricates evidence not in context | Optimist ASSETS/EVIDENCE text references files not in manifest |
| Judge receives raw context (invariant violation) | Judge child summary `prompt` contains context strings beyond advocate outputs |
| Agent produces PROCEED verdict + empty retrieval_order for every input | Statistical pattern across runs |

#### Expected Dispatch Patterns

| Metric | Expected Range | Source |
|--------|---------------|--------|
| `obs:child_dispatch_count_total` | 3 | Fixed: 2 (advocates) + 1 (judge) |
| `obs:child_batch_dispatches_total` | 1 | Single batch for advocates |
| `data_flow_edges` | 1-2 | Advocate responses feeding into judge prompt |
| REPL execute_code calls | 1 | Single code block |

---

## 2. Scoring Rubric per Topology

### 2.1 Dimension Definitions

All topologies share five scoring dimensions, each on a 0-5 scale:

| Dimension | Definition |
|-----------|-----------|
| **coverage_thoroughness** | How completely does the topology explore the available problem space? Measures breadth of investigation relative to the topology's design capacity. |
| **question_quality** | How well-targeted are the generated questions/steps/dimensions to the specific objective? Measures objective-specificity vs generic templates. |
| **synthesis_depth** | How well does the final synthesis integrate evidence from child dispatches? Measures information integration quality. |
| **iterative_refinement** | Does the topology adaptively refine its understanding based on intermediate results? Measures responsiveness to gaps. |
| **appropriate_dispatch** | Does the topology use the right number and type of child dispatches for the context? Measures dispatch efficiency. |

### 2.2 T1 Workflow-First Rubric

#### coverage_thoroughness (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No workflow steps generated, or agent skips topology entirely | `obs:child_dispatch_count_total` == 0 |
| 1 | 1 generic workflow step, no meaningful assessment | `workflow_steps` length == 1, all STATUS == SUFFICIENT |
| 2 | 2-3 steps, some assessments but no L2 triggered when context is large | Steps < 4, `obs:child_batch_dispatches_total` == 1 despite large packet count |
| 3 | 4-6 steps with mixed STATUS verdicts, L2 triggered when appropriate | Steps 4-6, STATUS mix includes PARTIAL/MISSING |
| 4 | 6-8 steps, L2 triggered, synthesis includes gap assessment | Steps 6-8, `obs:child_batch_dispatches_total` >= 2, gap_assessment non-empty |
| 5 | 6-8 objective-specific steps, L2 chunk analysis with relevance scoring, synthesis produces actionable retrieval order | Full L2 coverage, retrieval_order items match detected gaps |

#### question_quality (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | Steps are absent or entirely generic | Step text contains only "assess sufficiency" |
| 1 | Steps are template-derived without objective context | Steps do not reference objective keywords |
| 2 | Some steps reference the objective but are vague | Partial keyword overlap with objective |
| 3 | Most steps are objective-specific validation actions | >50% of steps reference objective terms |
| 4 | All steps are specific, actionable, and cover different aspects | Steps are unique, objective-aligned, cover distinct validation angles |
| 5 | Steps demonstrate understanding of the domain, anticipate likely gaps, and are dependency-ordered | Steps show domain-awareness and logical ordering |

#### synthesis_depth (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No synthesis performed | `obs:child_dispatch_count_total` lacks synthesis call |
| 1 | Synthesis is a trivial concatenation of L1 responses | Synthesis text ~ concatenation of child responses |
| 2 | Synthesis extracts some structure but misses gaps | UNDERSTANDING field populated, GAP_ASSESSMENT empty |
| 3 | Synthesis includes UNDERSTANDING + GAP_ASSESSMENT | Both fields populated, RETRIEVAL_ORDER present |
| 4 | Synthesis cross-references L1 and L2 assessments, identifies dependencies | `data_flow_edges` >= 2, retrieval_order is ordered |
| 5 | Synthesis produces a complete Polya understand-phase artifact with all 12 deliverables | Maps to Polya template: restatement, objective, givens, etc. |

#### iterative_refinement (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No conditional branching executed | L2 never triggered on any context |
| 1 | L2 triggered but results not integrated into synthesis | `obs:child_batch_dispatches_total` >= 2 but synthesis ignores chunk data |
| 2 | L2 triggered and chunk assessments present in synthesis | Chunk assessments appear in synthesis prompt |
| 3 | L2 relevance scores used to prioritize gaps | Synthesis references RELEVANCE scores |
| 4 | L1 STATUS drives L2 targeting accurately | L2 dispatched only for PARTIAL/MISSING steps |
| 5 | Full adaptive loop: L1->L2->synthesis with evidence-based gap prioritization | All conditional paths exercised appropriately |

#### appropriate_dispatch (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | Zero dispatches | `obs:child_dispatch_count_total` == 0 |
| 1 | Dispatch count far below or above expected range (< 4 or > 30) | Outside [4, 25] range |
| 2 | Dispatch count in expected range but L2 triggered unnecessarily | L2 on contexts with < l2_threshold packets |
| 3 | Dispatch count appropriate, L2 correctly conditional | Matches expected pattern |
| 4 | Dispatch efficiency: no redundant calls, batch sizes match step count | Batch size matches workflow_steps length |
| 5 | Optimal dispatch: fewest calls needed for thorough coverage | All dispatches contribute non-redundant information |

### 2.3 T2 Flat Open-Ended Rubric

#### coverage_thoroughness (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No investigation dispatched | `obs:child_dispatch_count_total` == 0 |
| 1 | 1-2 questions investigated out of available 5-10 | `obs:child_dispatch_count` <= 3 |
| 2 | 3-4 questions investigated | `obs:child_dispatch_count` == 4-5 |
| 3 | Full question complement (5) investigated | `obs:child_dispatch_count` == 6 (5 + synth) |
| 4 | Full complement + synthesis references all Q&A pairs | Synthesis prompt includes all Q indices |
| 5 | num_questions adapted to context complexity (larger contexts get more questions) | num_questions scaled to context size |

#### iterative_refinement (0-5)

T2 is a single-pass topology by design. The maximum score for iterative refinement is 2.

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No investigation + synthesis structure | Missing either batch or synthesis call |
| 1 | Investigation results flow to synthesis | `data_flow_edges` >= 1 |
| 2 | Synthesis integrates all investigation results and produces calibrated verdict | All Q indices referenced in synthesis, verdict correlates with gap count |
| 3-5 | N/A -- T2 does not support iterative refinement | Score capped at 2 for this topology |

#### appropriate_dispatch (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | Zero dispatches | `obs:child_dispatch_count_total` == 0 |
| 1 | Under-dispatch: < 3 total calls | `obs:child_dispatch_count_total` < 3 |
| 2 | Default dispatch count without adaptation | Always 6 regardless of context complexity |
| 3 | Appropriate for medium context | 6 dispatches for standard contexts |
| 4 | num_questions tuned to context (fewer for simple, more for complex) | Dispatch count varies across runs |
| 5 | Optimal: maximum information per dispatch | Each investigation produces unique, non-overlapping insights |

### 2.4 T3 Dimension-Adaptive Rubric

#### coverage_thoroughness (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No probes dispatched | `obs:child_dispatch_count_total` == 0 |
| 1 | SELECT + 1-2 probes only | `obs:child_dispatch_count_total` <= 4 |
| 2 | 3-4 dimensions probed but no re-probe | R1 dispatched, `cycles_completed` == 1 |
| 3 | 3-5 dimensions probed with re-probe for gaps | `cycles_completed` == 2 |
| 4 | Discriminating dimension selection + targeted re-probes | `selected_dimensions` length < total available, R2 targets only gap dims |
| 5 | Full adaptive loop with evidence-upgraded confidence and actionable retrieval plan | R2 upgrades at least one dimension from LOW to MEDIUM/HIGH |

#### iterative_refinement (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No gap analysis performed | `gaps_detected` always empty |
| 1 | Gap analysis runs but does not trigger re-probe | `identify_gaps()` returns [] despite LOW confidence probes |
| 2 | Re-probe triggered but uses same questions as R1 | R2 prompts do not contain "ORIGINAL_GAPS_FROM_ROUND_1" |
| 3 | Re-probe triggered with sharpened questions from R1 gaps | R2 prompts include gap text from R1 |
| 4 | R2 results integrated into synthesis with improved evidence | Synthesis includes R2 probe results, confidence upgrades visible |
| 5 | Full adaptive cycle: SELECT->R1->GAP->R2->SYNTH with evidence trail | All phases execute, data_flow_edges show full chain |

#### appropriate_dispatch (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | Zero dispatches | `obs:child_dispatch_count_total` == 0 |
| 1 | Over-dispatch: all 8 dimensions selected | `len(selected_dimensions)` == 8 (no filtering) |
| 2 | Under-dispatch: only 1-2 dimensions selected | `len(selected_dimensions)` < 3 |
| 3 | 3-5 dimensions, appropriate to objective | 3-5 selected, relevant to objective |
| 4 | Dimension selection matches objective domain + re-probe is selective | Not all R1 dimensions re-probed in R2 |
| 5 | Minimal dispatch for maximum coverage: fewest dimensions that expose all gaps | Dispatch count in [5, 12], all dispatches productive |

### 2.5 T4 Adversarial Debate Rubric

T4 has a fixed dispatch structure (3 calls), so `appropriate_dispatch` and `iterative_refinement` are scored differently.

#### coverage_thoroughness (0-5)

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No advocates dispatched | `obs:child_dispatch_count_total` == 0 |
| 1 | Only one advocate dispatched (optimist or critic, not both) | `obs:child_dispatch_count_total` < 3 |
| 2 | Both advocates dispatched but one produces thin output | One child `result_preview` length < 100 |
| 3 | Both advocates produce substantive structured output | All section fields populated (>50 chars each) |
| 4 | Comprehensive advocacy: optimist covers all 4 sections, critic covers all 5 | All `T4OptimistCase` and `T4CriticCase` fields non-empty |
| 5 | Advocates cite specific context artifacts; critic's gaps are concrete and verifiable | Section fields reference specific filenames/modules from context |

#### question_quality (0-5)

For T4, this measures argumentation quality rather than question quality.

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No argumentation produced | Missing advocate outputs |
| 1 | Arguments are generic and context-independent | Arguments do not reference objective or context terms |
| 2 | Arguments reference the objective but lack specificity | Partial objective term overlap |
| 3 | Optimist and critic make specific, contradictory claims | Claims reference specific artifacts |
| 4 | Arguments are evidence-based with concrete citations | Evidence fields cite file names, module paths, etc. |
| 5 | Arguments anticipate counterarguments and preemptively address them | Structured adversarial reasoning visible |

#### synthesis_depth (0-5)

For T4, synthesis is the judge's adjudication.

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No judge ruling | Missing judge dispatch |
| 1 | Judge produces verdict only, no reasoning | `adjudication` empty or < 50 chars |
| 2 | Judge produces verdict + brief understanding | `understanding` non-empty, `adjudication` brief |
| 3 | Judge produces verdict + understanding + retrieval_order | All three populated |
| 4 | Judge cites specific advocate arguments in adjudication | Adjudication text contains substrings from advocate outputs |
| 5 | Judge identifies unsupported claims by each side, weighs concrete vs vague evidence, produces calibrated confidence_map | `confidence_map` has >= 3 entries, adjudication references both sides |

#### iterative_refinement (0-5)

T4 is a single-pass topology by design. Maximum score is 2.

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | No structured debate flow | Missing advocate or judge phase |
| 1 | Debate flow executed but judge does not reference advocate arguments | Judge adjudication is independent of advocate outputs |
| 2 | Full debate flow: advocates -> judge, with judge integrating both cases | `data_flow_edges` >= 2, adjudication references both |
| 3-5 | N/A -- T4 does not support iterative refinement | Score capped at 2 |

#### appropriate_dispatch (0-5)

T4 has a fixed dispatch count (3). Scoring focuses on whether the topology was the right choice.

| Score | Criteria | Telemetry Check |
|-------|----------|----------------|
| 0 | Zero dispatches | `obs:child_dispatch_count_total` == 0 |
| 1 | Partial dispatch (< 3 calls) | Missing advocate or judge |
| 2 | All 3 calls dispatched but context is too large for debate format | Context would benefit from T1/T3 multi-layer analysis |
| 3 | All 3 calls dispatched, appropriate for moderate-risk assessment | Standard execution |
| 4 | T4 selected for genuinely ambiguous contexts where adversarial analysis adds value | Context has real tension between sufficiency and gaps |
| 5 | Optimal: T4 reveals non-obvious risks that T1-T3 would miss | Critic identifies genuine blockers not visible in simple assessment |

### 2.6 Topology-Specific Adjustments

When comparing scores across topologies, the following normalization factors apply:

| Dimension | T1 Weight | T2 Weight | T3 Weight | T4 Weight | Rationale |
|-----------|-----------|-----------|-----------|-----------|-----------|
| coverage_thoroughness | 1.0 | 0.8 | 1.0 | 0.7 | T2 and T4 are inherently narrower |
| question_quality | 1.0 | 0.7 | 1.0 | 0.9 | T2 uses fixed templates; T4 measures argumentation |
| synthesis_depth | 1.0 | 0.9 | 1.0 | 1.0 | All topologies should synthesize well |
| iterative_refinement | 1.0 | 0.4 | 1.0 | 0.4 | T2 and T4 are single-pass by design |
| appropriate_dispatch | 0.8 | 0.9 | 1.0 | 0.6 | T4 has fixed structure; T3 is most adaptive |

**Composite score** = weighted sum / sum of weights, normalized to [0, 5].

---

## 3. Polya Methodology Alignment

### 3.1 Polya's 14-Step Understand Framework

Source: `.claude/skills/voice-to-prompt/references/polya_understand.md`

| Step | Description |
|------|-------------|
| P1 | Restate the problem in your own words |
| P2 | Identify the objective with full precision |
| P3 | Inventory the given information |
| P4 | Identify unknowns and their relationships to givens |
| P5 | Clarify all terms and remove ambiguity |
| P6 | Draw, diagram, tabulate, or externalize the structure |
| P7 | Separate facts from assumptions |
| P8 | Check completeness: is the problem well-posed? |
| P9 | Establish constraints and success criteria |
| P10 | Identify the type or family of problem |
| P11 | Test understanding by generating small examples |
| P12 | Ask the canonical Polya questions (unknown/data/condition/sufficiency) |
| P13 | Define the boundaries of the problem |
| P14 | Reformulate until the problem becomes operational |

### 3.2 Topology-to-Polya Step Mapping

#### T1: Workflow-First 3-Layer

| Topology Phase | Polya Steps Emphasized | How |
|---------------|----------------------|-----|
| L0 Workflow Generation | P1, P2, P3, P6 | Restates objective as workflow steps; inventories context via manifest; externalizes structure as numbered step list |
| L1 Step Assessment | P3, P4, P8, P12 | Inventories givens per step; identifies unknowns (GAPS); checks sufficiency (STATUS); asks canonical questions (sufficient/insufficient/redundant) |
| L2 Chunk Assessment | P3, P12 | Detailed inventory at chunk level; systematic sufficiency check (PRESENT/ABSENT/RELEVANCE) |
| Synthesis | P1, P4, P8, P14 | Restates composite understanding; maps unknowns to retrieval order; judges well-posedness; produces operational problem statement |

**Strength:** Systematic coverage of P3 (givens inventory) through 3-layer decomposition.
**Gap:** Weak on P5 (term clarification), P7 (facts vs assumptions), P10 (problem type), P11 (toy examples).

#### T2: Flat Open-Ended

| Topology Phase | Polya Steps Emphasized | How |
|---------------|----------------------|-----|
| Question Generation | P1, P2, P12 | Questions restate the problem from multiple angles; each question targets a different unknown; canonical question structure |
| Investigation | P3, P4, P5, P9 | Each child inventories givens for its question; identifies unknowns; clarifies terms in context; checks constraints |
| Synthesis | P8, P14 | Judges completeness (verdict); reformulates into operational understanding |

**Strength:** Broad coverage of P12 (canonical questions) via 10 fixed question templates (lines 222-233 of T2 source).
**Gap:** Fixed template questions cannot adapt to domain (P5, P10); no P7 (facts vs assumptions); no P11 (toy examples); single-pass means no P8 iteration.

The 10 question templates in `generate_probing_questions()` map to Polya steps as:
1. "core purpose...specific deliverable" -> P1 (restate), P2 (objective)
2. "key components, modules" -> P3 (givens), P6 (structure)
3. "constraints, limitations" -> P9 (constraints)
4. "primary risks or failure modes" -> P7 (assumptions), P8 (well-posedness)
5. "dependencies" -> P4 (unknowns/relationships)
6. "unknowns or ambiguities" -> P4 (unknowns), P5 (clarify terms)
7. "success criteria" -> P9 (success criteria)
8. "implementation patterns, conventions" -> P10 (problem type)
9. "testing strategies, validation" -> P11 (examples), P9 (constraints)
10. "trade-offs, alternatives" -> P13 (boundaries), P10 (problem type)

#### T3: Dimension-Adaptive Round-Trip

| Topology Phase | Polya Steps Emphasized | How |
|---------------|----------------------|-----|
| SELECT | P10, P13 | Identifies which problem dimensions are most relevant; defines problem boundaries by selecting in/out dimensions |
| PROBE R1 | P1-P9 per dimension | Each dimension maps directly to a Polya step (see mapping below) |
| GAP ANALYSIS | P8, P12 | Checks if understanding is sufficient; asks "is the condition sufficient?" |
| RE-PROBE R2 | P4, P8, P11 | Targets unknowns; re-checks well-posedness; probes edge cases in gap areas |
| SYNTHESIZE | P1, P6, P14 | Restates understanding; externalizes as structured artifact; reformulates operationally |

**The 8 `POLYA_DIMENSIONS` map directly to Polya steps** (from T3 source, lines 164-261):

| Dimension ID | Polya Step | Dimension Question |
|-------------|-----------|-------------------|
| `restatement` | P1 | "Restate the objective in precise operational terms" |
| `givens` | P3 | "What documents, data, facts are explicitly provided?" |
| `unknowns` | P4 | "What information is needed that is NOT present?" |
| `assumptions` | P7 | "What assumptions are being made that are NOT stated?" |
| `constraints` | P9 | "What constraints govern this task? Define pass/fail criteria." |
| `well_posedness` | P8 | "Is this problem solvable with the available information?" |
| `definitions` | P5 | "Identify all technical terms and ambiguous phrases" |
| `problem_type` | P10, P13 | "What kind of problem is this? Define scope boundaries." |

**Strength:** Most complete Polya coverage of any topology. Direct 1:1 mapping from dimensions to Polya steps. Adaptive re-probing covers P8 iteration. SELECT phase covers P10/P13.
**Gap:** P6 (diagramming) is implicit in structure but not explicitly requested. P11 (toy examples) is not covered. P14 (reformulation) depends on synthesis quality.

#### T4: Adversarial Debate

| Topology Phase | Polya Steps Emphasized | How |
|---------------|----------------------|-----|
| Optimist | P3, P6, P9 | Inventories assets (givens); maps coverage (structure); argues readiness (success criteria) |
| Critic | P4, P7, P8, P13 | Identifies gaps (unknowns); flags assumptions (facts vs assumptions); challenges well-posedness; identifies blockers (boundaries) |
| Judge | P1, P8, P12, P14 | Restates understanding; judges sufficiency; weighs arguments (canonical questions); produces operational verdict |

**Strength:** Unique coverage of P7 (facts vs assumptions) through adversarial framing -- the critic is structurally incentivized to challenge assumptions. P8 (well-posedness) gets dual perspectives. Strong on P12 (canonical questions) through the judge's weighing process.
**Gap:** No P5 (term clarification), P10 (problem type), P11 (toy examples). No P6 (diagramming). Single-pass means limited P8 iteration. Only 3 dispatches means limited P3 coverage compared to T1/T3.

### 3.3 Polya Step Coverage Matrix

| Polya Step | T1 | T2 | T3 | T4 |
|-----------|----|----|----|----|
| P1 Restate | L0, Synth | Q1 | `restatement` dim | Judge |
| P2 Objective | L0 | Q1 | `restatement` dim | Implicit |
| P3 Inventory givens | L1, L2 | Q-all | `givens` dim | Optimist |
| P4 Unknowns/relationships | L1 (GAPS) | Q5, Q6 | `unknowns` dim | Critic |
| P5 Clarify terms | -- | Q6 (partial) | `definitions` dim | -- |
| P6 Externalize structure | L0 (step list) | Q2 (partial) | Implicit | Optimist (coverage_map) |
| P7 Facts vs assumptions | -- | Q4 (partial) | `assumptions` dim | Critic (explicit) |
| P8 Well-posedness | Synth | Verdict | `well_posedness` dim, GAP ANALYSIS | Critic + Judge |
| P9 Constraints/criteria | L1 (partial) | Q3, Q7 | `constraints` dim | Optimist (readiness) |
| P10 Problem type | -- | Q8, Q10 | `problem_type` dim | -- |
| P11 Toy examples | -- | Q9 (partial) | -- | -- |
| P12 Canonical questions | L1 (STATUS) | Q-all | R1+R2 (CONFIDENCE) | Judge (verdict) |
| P13 Boundaries | -- | -- | `problem_type` dim | Critic (blockers) |
| P14 Reformulate | Synth | Synth | Synth | Judge (verdict) |
| **Coverage count** | **8/14** | **10/14** | **12/14** | **9/14** |

T3 has the broadest Polya coverage (12/14) due to its direct dimension-to-Polya-step mapping. T2 achieves broad but shallow coverage (10/14) through its 10 fixed question templates. T4 has strong depth on a narrower set (9/14) due to adversarial framing. T1 is most structured but narrowest (8/14), focused on systematic P3/P8/P12 coverage.

---

## 4. Anti-Patterns Catalog

### 4.1 Universal Anti-Patterns (All Topologies)

| ID | Anti-Pattern | Detection Rule | Severity |
|----|-------------|---------------|----------|
| AP-U1 | **Ghost Dispatch** -- Agent claims to dispatch children but `obs:child_dispatch_count_total` == 0 | `obs:child_dispatch_count_total` == 0 AND result text contains "dispatched" or "investigated" | CRITICAL |
| AP-U2 | **Verdict Without Investigation** -- Agent produces SUFFICIENT/PROCEED verdict without any child dispatches | `obs:child_dispatch_count_total` == 0 AND output contains sufficiency verdict | CRITICAL |
| AP-U3 | **Context Fabrication** -- Child responses reference artifacts not present in the input context | Cross-reference child `result_text` file/artifact names against `build_context_manifest()` output | HIGH |
| AP-U4 | **Copy-Paste Synthesis** -- Synthesis output is >90% verbatim copy of a single child response | Jaccard similarity between synthesis and any single child response > 0.9 | MEDIUM |
| AP-U5 | **Token Inflation** -- Dispatch prompts include unnecessary repetition to inflate token counts | Per-child `input_tokens` >> expected (compare to prompt template lengths) | MEDIUM |
| AP-U6 | **Error Swallowing** -- Agent ignores child dispatch errors and produces clean output | `obs:child_error_counts` has entries but result makes no mention of failures | MEDIUM |
| AP-U7 | **Skill Expansion Bypass** -- Agent writes raw code instead of using skill imports | `REPL_DID_EXPAND` == False for a topology skill run | LOW (may be intentional) |
| AP-U8 | **Over-Optimism Bias** -- Agent consistently produces SUFFICIENT verdicts across diverse contexts | Statistical: > 90% SUFFICIENT rate across 10+ runs on varied contexts | HIGH |

### 4.2 T1-Specific Anti-Patterns

| ID | Anti-Pattern | Detection Rule | Severity |
|----|-------------|---------------|----------|
| AP-T1-1 | **L0 Context Leak** -- L0 workflow generation receives raw context instead of manifest only | L0 child summary `prompt` length >> `build_context_manifest()` output length | HIGH |
| AP-T1-2 | **Vacuous Workflow Steps** -- L0 generates steps like "check everything" instead of specific validation actions | All workflow steps contain generic verbs without specific artifacts | MEDIUM |
| AP-T1-3 | **L2 Bypass on Large Context** -- L2 chunk assessment not triggered despite packet count > `l2_threshold` | `obs:child_batch_dispatches_total` == 1 AND packet_count > l2_threshold | MEDIUM |
| AP-T1-4 | **Assessment Monotony** -- All L1 step assessments have identical STATUS | All N step assessments have STATUS == "SUFFICIENT" (or all "MISSING") | MEDIUM |
| AP-T1-5 | **Orphaned L2** -- L2 chunk assessments dispatched but not referenced in synthesis | Synthesis prompt does not include chunk assessment data | MEDIUM |

### 4.3 T2-Specific Anti-Patterns

| ID | Anti-Pattern | Detection Rule | Severity |
|----|-------------|---------------|----------|
| AP-T2-1 | **Question Starvation** -- Agent sets `num_questions=1` to minimize dispatch cost | `obs:child_dispatch_count_total` == 2 (1 investigation + 1 synthesis) | MEDIUM |
| AP-T2-2 | **Investigation Parroting** -- All investigation responses echo the same evidence | Pairwise substring overlap > 80% across investigation child responses | MEDIUM |
| AP-T2-3 | **Synthesis Ignores Gaps** -- Synthesis verdict is SUFFICIENT despite investigation children reporting GAP markers | Count of "GAP" occurrences in investigation responses > 0 but verdict == SUFFICIENT | HIGH |
| AP-T2-4 | **Template Question Invariance** -- Questions are identical across different objectives | `generate_probing_questions()` output does not change with different objectives (but by design T2 uses templates -- this is a design limitation, not an agent anti-pattern) | INFO |

### 4.4 T3-Specific Anti-Patterns

| ID | Anti-Pattern | Detection Rule | Severity |
|----|-------------|---------------|----------|
| AP-T3-1 | **Non-Discriminating SELECT** -- SELECT phase always returns all 8 dimensions | `len(selected_dimensions)` == 8 across multiple runs with different objectives | MEDIUM |
| AP-T3-2 | **Confidence Inflation** -- All R1 probes report HIGH confidence to avoid R2 | All R1 `T3ProbeResult.confidence` == "HIGH" despite incomplete context | HIGH |
| AP-T3-3 | **R2 Echo** -- R2 re-probes produce identical responses to R1 | R2 child `result_text` Jaccard similarity with corresponding R1 > 0.85 | MEDIUM |
| AP-T3-4 | **Gap Leak** -- `identify_gaps()` uses wrong threshold comparison | `confidence_threshold` set to "LOW" (effectively disabling re-probes for MEDIUM) | MEDIUM |
| AP-T3-5 | **Dimension Mismatch** -- Selected dimensions do not match the objective domain | Selected dimension IDs have no semantic relationship to objective keywords | MEDIUM |
| AP-T3-6 | **Synthesis Drops R2** -- Synthesis includes R1 results but ignores R2 | `round2_results` is non-empty but synthesis text does not reference R2 evidence | MEDIUM |

### 4.5 T4-Specific Anti-Patterns

| ID | Anti-Pattern | Detection Rule | Severity |
|----|-------------|---------------|----------|
| AP-T4-1 | **Judge Context Leak** -- Judge receives raw project context in addition to advocate arguments | Judge child summary `prompt` length > optimist_raw + critic_raw + objective + instructions | CRITICAL (invariant violation) |
| AP-T4-2 | **Advocate Collusion** -- Optimist and critic produce compatible (non-adversarial) arguments | Optimist READINESS_CASE and critic BLOCKERS do not contradict each other | HIGH |
| AP-T4-3 | **Critic Capitulation** -- Critic fails to identify any gaps or risks | `T4CriticCase.gaps` is empty AND `T4CriticCase.risks` is empty | HIGH |
| AP-T4-4 | **Judge Anchoring** -- Judge verdict correlates with argument order (always sides with optimist, listed first) | Statistical: verdict == PROCEED > 80% of runs | MEDIUM |
| AP-T4-5 | **Empty Confidence Map** -- Judge produces verdict without dimensional confidence assessment | `len(confidence_map)` == 0 | MEDIUM |
| AP-T4-6 | **Retrieval Order on PROCEED** -- Judge says PROCEED but still lists retrieval items (contradictory) | `verdict` == "PROCEED" AND `len(retrieval_order)` > 0 | LOW |

### 4.6 Anti-Pattern Severity Classification

| Severity | Definition | Required Action |
|----------|-----------|----------------|
| CRITICAL | Topology invariant violated or agent bypasses the understanding phase entirely | Flag run as invalid; score = 0 |
| HIGH | Significant quality degradation; agent gaming or fundamental analysis failure | Deduct 2+ points from affected dimension |
| MEDIUM | Suboptimal behavior that reduces understanding quality but does not invalidate it | Deduct 1 point from affected dimension |
| LOW | Minor issue or design limitation; may be intentional | Log for review, no automatic scoring impact |
| INFO | Observation that aids interpretation but does not affect scoring | Informational only |

---

## 5. Implementation Notes

### 5.1 Telemetry Data Sources

All behavioral indicators use telemetry that is **already emitted** by the existing observability stack:

1. **Dispatch accumulators** (`dispatch.py` lines 200-214, 790-827): `_acc_child_dispatches`, `_acc_child_batch_dispatches`, `_acc_child_error_counts` are flushed to `tool_context.state` after each REPL execution via `flush_fn()`.

2. **Cumulative keys** (`state.py` lines 103-107): `obs:child_dispatch_count_total`, `obs:child_batch_dispatches_total`, `obs:child_error_counts_total` provide session-wide totals that do not reset between iterations.

3. **Per-child summaries** (`dispatch.py` lines 564-647): `obs:child_summary@d{depth}f{fanout_idx}` contains prompt, result_text, error info, tokens, structured_output details, and nested dispatch info for each child call.

4. **REPL trace** (`trace.py`): `REPLTrace.llm_calls`, `REPLTrace.data_flow_edges` capture per-code-block LLM call patterns and response-to-prompt chaining.

5. **SQLite persistence** (`sqlite_tracing.py`): `session_state_events` table captures all obs: key changes with `key_category`, `key_depth`, `key_fanout`, and typed values. `telemetry` table captures per-model-call and per-tool-call metrics.

### 5.2 Detection Implementation Approach

A behavioral evaluation system would:

1. **Query `session_state_events`** for dispatch metrics per topology run:
   ```sql
   SELECT state_key, value_int, value_json
   FROM session_state_events
   WHERE trace_id = ?
   AND key_category = 'obs_dispatch'
   ORDER BY seq;
   ```

2. **Query `telemetry`** for per-call details:
   ```sql
   SELECT agent_name, model, input_tokens, output_tokens,
          repl_llm_calls, repl_trace_summary, skill_instruction
   FROM telemetry
   WHERE trace_id = ?
   AND event_type = 'tool_call'
   AND tool_name = 'execute_code';
   ```

3. **Parse child summaries** from `session_state_events` where `state_key LIKE 'obs:child_summary@%'` and `value_json` contains the full per-child telemetry dict.

4. **Compute data flow metrics** from `REPLTrace.data_flow_edges` stored in `repl_trace_summary` within the telemetry table.

### 5.3 Scoring Computation

Given a topology run's telemetry, compute each dimension score using the rubric tables above, apply topology-specific weights from section 2.6, and compute the composite score:

```
composite = sum(score_i * weight_i) / sum(weight_i)
```

Anti-pattern detection runs as a post-scoring pass that may further reduce scores based on severity (section 4.6).

---

## 6. Open Questions

1. **Cross-topology comparison:** Should we normalize composite scores so T1 and T4 runs are directly comparable, or always evaluate within-topology?

2. **Verdict calibration:** How do we establish ground truth for what contexts deserve SUFFICIENT vs INSUFFICIENT verdicts? This requires labeled evaluation datasets.

3. **Data flow edge reliability:** The `DataFlowTracker` uses a 40-character substring fingerprint (trace.py line 127). Is this sufficient to reliably detect response-to-prompt chaining in topology skill code, or should the fingerprint length be tuned?

4. **Multi-turn topology runs:** The current analysis assumes single REPL execution. If a topology is invoked across multiple REPL turns (e.g., agent calls skill, reads result, calls another skill), cumulative keys track correctly but per-iteration keys reset. The scoring rubric may need adjustment for multi-turn patterns.

5. **P11 coverage gap:** No topology explicitly generates toy examples (Polya step 11). Should this be added as a new dimension in T3's `POLYA_DIMENSIONS`, or is it better handled as a separate post-understanding validation step?
