# polya_understand_2: Alternative Topology Proposals

**Date:** 2026-03-17
**Purpose:** Design proposal for `polya_understand_2` — four candidate topologies to replace or complement the existing v1 Polya understanding skill. Each topology is fully specified across 10 design axes. A unified comparison table and build-order recommendation follow.

---

## V1 Baseline Summary

The existing v1 skill (`polya_understand`) at `rlm_adk/skills/polya_understand.py` (~1330 lines):

- **5-phase loop:** REFRAME, PROBE, SYNTHESIZE, VALIDATE, REFLECT
- **8 fixed Polya dimensions:** restatement, givens, unknowns, assumptions, constraints, well_posedness, definitions, problem_type
- **23 source-expandable REPL exports** (6 constants, 2 classes, 15 functions)
- **6 instruction/data constants** (POLYA_DIMENSIONS + 5 phase instruction constants)
- **Total LLM calls per cycle:** P+4 (P ~ 8-10 packets), ~14/cycle, ~28 for 2 cycles
- Parent sees only manifest, never raw context
- Children get one Polya dimension + one context packet, return structured DIMENSION/EVIDENCE/GAPS/CONFIDENCE
- Very rigid: prescriptive prompt templates, fixed output formats, hardcoded dimension list
- Max depth used: 1 (L0 + L1 only)

---

## Topology 1: Workflow-First 3-Layer

### 1. Name

Workflow-First 3-Layer

### 2. Layer Diagram

```
L0 (Parent, depth 0)
  Receives: objective + context manifest
  Produces: multi-step WORKFLOW plan (W steps, typically 4-7)
  Dispatches: W children via llm_query_batched()
  Collects: W completeness reports
  Synthesizes: final understanding + gap assessment
      |
      | llm_query_batched(W prompts)
      |
  +---+---+-----------+
  |   |   |           |
  v   v   v           v
L1-a L1-b ... L1-w (Workflow Step Assessors, depth 1)
  Each receives: workflow step + context manifest + full/partitioned context
  If context small: assess directly
  If context large: chunk and dispatch to L2
      |
      | llm_query_batched() [conditional, per L1 child]
      |
  +---+---+---+
  v   v   v   v
L2-1 L2-2 ... L2-C (Chunk Assessors, depth 2)
  Each receives: one chunk + workflow step
  Returns: PRESENT / ABSENT / RELEVANCE per chunk
```

### 3. Dispatch Pattern

| Phase | Dispatch | Calls |
|---|---|---|
| L0: Generate workflow | `llm_query()` | 0-1 |
| L0 -> L1: Step assessment | `llm_query_batched(W)` | W (4-7) |
| L1 -> L2: Chunk assessment | `llm_query_batched(C)` per L1 | 0 to C per L1 |
| L0: Final synthesis | `llm_query()` | 1 |

Typical total: 6-9 (small context) to 22 (large context with L2).

### 4. What L0 Does

Sees manifest only (not raw context). Generates a multi-step workflow -- a concrete sequence of actions to achieve the objective. Each step becomes a unit of assessment dispatched to L1. After collecting L1 reports, runs a single synthesis call to consolidate step-level completeness assessments into a final understanding artifact with gap analysis and retrieval order.

### 5. What Children Do

**L1 (Workflow Step Assessors):** Receive one workflow step + context. Assess completeness for that step (SUFFICIENT/PARTIAL/MISSING). If context is large, chunk and dispatch L2.

**L2 (Chunk Assessors):** Receive one chunk + workflow step. Summarize what IS present relevant to the step. Return PRESENT/ABSENT/RELEVANCE.

### 6. How Context Flows

- **L0:** manifest only
- **L1:** full context or a partition (option a: all get full; option b: L0 provides partitioning hints)
- **L2:** one chunk each (subdivided by L1)

### 7. Simplicity Assessment

~16 exports (vs 23 in v1). 2 instruction constants (vs 6). ~30% fewer exports.

### 8. Strengths

- Task-adaptive workflow (not locked to fixed dimensions)
- Deeper context coverage via conditional L2
- Workflow output is directly actionable
- Conditional L2 saves tokens for small contexts

### 9. Weaknesses

- No systematic dimension coverage guarantee
- Harder to compare across runs (variable workflow steps)
- Consumes full depth budget (L0/L1/L2 = depths 0/1/2)
- Synthesis harder with heterogeneous L1 reports

### 10. Risk

- Workflow quality is the bottleneck -- bad workflow leads to bad assessment
- Context overflow at L1 if full context sent to every child
- L2 non-determinism complicates testing/fixtures
- Depth limit fragility -- no recovery at L2

---

## Topology 2: Flat Open-Ended

### 1. Name

Flat Open-Ended

### 2. Layer Diagram

```
L0 (Parent, depth 0)
  Receives: objective + FULL CONTEXT
  Phase 1: Generate 5-10 open-ended probing questions (no fixed dimensions)
  Phase 2: llm_query_batched(Q prompts) -- one child per question
  Phase 3: llm_query() -- synthesis child consolidates all results
      |
      | llm_query_batched(Q prompts)
      |
  +---+---+---+---+-------+
  v   v   v   v   v       v
L1-1 L1-2 ... L1-Q (Investigation Agents, depth 1)
  Each receives: one open-ended question + full context
  Returns: free-form investigation response (no required headings)
      |
      | llm_query(synthesis prompt)
      v
L1-synth (Synthesizer, depth 1)
  Receives: all Q investigation responses + objective
  Returns: understanding + coverage assessment + gaps + verdict
```

### 3. Dispatch Pattern

| Phase | Dispatch | Calls |
|---|---|---|
| L0: Generate questions | Local in REPL | 0 |
| L0 -> L1: Investigation | `llm_query_batched(Q)` | Q (5-10) |
| L0 -> L1: Synthesis | `llm_query()` | 1 |

Total: Q + 1 = 6-11 calls. Fixed, no cycles.

### 4. What L0 Does

Sees FULL context (key departure from v1). Generates 5-10 open-ended probing questions informed by actual context, not from a fixed dimension set. After investigation, dispatches synthesis child.

### 5. What Children Do

**L1 investigators:** Receive one question + full context. Return free-form responses with no required headings. Maximum model freedom.

**L1 synthesizer:** Receives all Q responses + objective. Returns semi-structured output (the only structured prompt in the topology).

### 6. How Context Flows

- **L0:** full context
- **L1 investigators:** full context (every child sees everything)
- **L1 synthesizer:** investigation responses only (not raw context)

### 7. Simplicity Assessment

~11 exports (vs 23 in v1). 1 instruction constant (vs 6). Over 50% fewer exports. Simplest viable topology.

### 8. Strengths

- Maximum simplicity (fastest to implement/test)
- Maximum model freedom (no structural constraints on investigation)
- Full context visibility eliminates information loss
- No cycles -- deterministic call count
- Easy to create provider-fake fixtures

### 9. Weaknesses

- No systematic coverage guarantee
- Token-expensive: O(Q x context_size) at L1
- No iteration/self-correction
- Free-form responses harder to synthesize
- Scales poorly to very large contexts (>200K tokens)

### 10. Risk

- Model drift on question generation (redundant or superficial questions)
- Context overflow for large repos
- Synthesis failure on heterogeneous inputs
- No self-correction mechanism

---

## Topology 3: Dimension-Adaptive Round-Trip

### 1. Name

Dimension-Adaptive Round-Trip

### 2. Layer Diagram

```
L0 (Parent, depth 0)
  Receives: objective + context manifest
      |
  +---v---- ROUND 1 -----+
  | SELECT: llm_query()    |  -> L0 selects 3-5 relevant Polya dimensions
  |                        |
  | PROBE: llm_query_      |  -> 3-5 children, one per selected dimension
  |   batched()            |    Each gets: dimension question + context packet
  |                        |    Returns: DIMENSION/EVIDENCE/GAPS/CONFIDENCE
  | GAP ANALYSIS:          |
  |   local Python         |  -> Parse CONFIDENCE markers, identify gaps
  +--------+---------------+
           |
       Has gaps? --no--> SYNTHESIZE (llm_query())
           |
           yes
           |
  +--------v-- ROUND 2 ---+
  | TARGETED RE-PROBE:     |  -> Only gap dimensions re-probed
  |   llm_query_batched()  |    with sharpened questions +
  |                        |    different context packets
  +--------+---------------+
           |
     SYNTHESIZE: llm_query()  -> Combine round 1 + round 2 results
```

### 3. Dispatch Pattern

| Phase | Dispatch | Calls |
|---|---|---|
| SELECT | `llm_query()` | 1 |
| PROBE round 1 | `llm_query_batched()` | 3-5 |
| GAP ANALYSIS | Local Python | 0 |
| RE-PROBE round 2 | `llm_query_batched()` | 0-3 (conditional) |
| SYNTHESIZE | `llm_query()` | 1 |

Typical total: 7-10 calls. Best: 6. Worst: 11.

### 4. What L0 Does

Sees manifest only (same as v1). SELECT phase: asks model which 3-5 of the 8 Polya dimensions are most relevant to this objective. After PROBE, performs local gap analysis by parsing CONFIDENCE markers. If gaps, dispatches round 2 with sharpened questions targeting specific gaps.

### 5. What Children Do

**L1 (Probers):** Same payload as v1 -- one Polya dimension question + one context packet. Return structured DIMENSION/EVIDENCE/GAPS/CONFIDENCE.

**Round 2 children:** Same format but with sharpened questions referencing specific round 1 gaps.

**L1 (Synthesizer):** Combines all probe results into final understanding + retrieval order.

### 6. How Context Flows

- **L0:** manifest only
- **L1:** one context packet per child (same as v1)
- **Round 2:** different packets than round 1 (rotation through un-assigned packets)
- No L2 -- max depth 1, leaves headroom

### 7. Simplicity Assessment

~16 exports (vs 23 in v1). 2 instruction constants (SELECT, PROBE). Reuses v1's POLYA_DIMENSIONS data constant and most context helpers.

### 8. Strengths

- Adaptive coverage (only probes relevant dimensions)
- Targeted iteration (re-probe gaps only, not full re-run)
- Preserves systematic Polya dimension scaffold
- ~50-65% fewer LLM calls than v1
- Depth headroom preserved

### 9. Weaknesses

- Dimension selection is a bottleneck (may miss important dimensions)
- No VALIDATE/REFLECT checks -- synthesis must do both
- Gap analysis is heuristic (confidence self-reporting may not correlate with quality)
- No explicit retrieval order mechanism separate from synthesis

### 10. Risk

- Dimension selection drift toward "easy" dimensions
- Round 2 non-convergence (no round 3)
- Confidence calibration issues (hallucinated high confidence)

---

## Topology 4: Adversarial Debate

### 1. Name

Adversarial Debate

### 2. Layer Diagram

```
L0 (Parent, depth 0)
  Receives: objective + context manifest
  Dispatches 2 advocates concurrently + 1 judge
      |
      | llm_query_batched([optimist_prompt, critic_prompt])
      |
  +---+----------------------+
  v                          v
L1: OPTIMIST (depth 1)     L1: CRITIC (depth 1)
  "Build strongest case      "Find every flaw, gap,
  we have enough context     missing piece, hidden
  to proceed. Inventory      assumption. Challenge
  every asset."              well-posedness."

  Gets: full context         Gets: full context
  (or dispatches L2 chunks)  (or dispatches L2 chunks)

  Returns:                   Returns:
  ASSETS, LINKS,             GAPS, RISKS,
  COVERAGE_MAP,              AMBIGUITIES, BLOCKERS,
  READINESS_CASE             RETRIEVAL_NEEDS
      |                          |
      +----------+---------------+
                 |
                 v llm_query(judge_prompt)
           L1: JUDGE (depth 1)
             Receives: both arguments + objective
             (no raw context -- arguments only)
             Returns: VERDICT, UNDERSTANDING,
             RETRIEVAL_ORDER, CONFIDENCE_MAP
```

### 3. Dispatch Pattern

| Phase | Dispatch | Calls |
|---|---|---|
| ADVOCATE | `llm_query_batched([opt, crit])` | 2 (concurrent) |
| JUDGE | `llm_query()` | 1 |

Base total: 3 LLM calls. With L2 chunk assessors: 9-13 total.

### 4. What L0 Does

Sees manifest only. Does NOT generate questions or select dimensions. Constructs two role-specific framing prompts (optimist + critic), dispatches concurrently, then dispatches judge with both arguments.

### 5. What Children Do

**Optimist:** Builds strongest case for proceeding. Returns ASSETS/LINKS/COVERAGE_MAP/READINESS_CASE. May dispatch L2 chunk assessors if context is large.

**Critic:** Finds every gap and flaw. Returns GAPS/RISKS/AMBIGUITIES/BLOCKERS/RETRIEVAL_NEEDS. May dispatch L2.

**Judge:** Receives both arguments (not raw context). Adjudicates, produces final VERDICT/UNDERSTANDING/RETRIEVAL_ORDER/CONFIDENCE_MAP. Uses rule: "Where they agree, confidence is high. Where they contradict, investigate which is better supported."

### 6. How Context Flows

- **Small context:** full context to both advocates. Judge sees only arguments.
- **Large context:** advocates dispatch L2 chunk assessors independently. Judge still sees only arguments.
- Judge input is bounded regardless of context size.

### 7. Simplicity Assessment

~14 exports (vs 23 in v1). 3 instruction constants (OPTIMIST, CRITIC, JUDGE). No dimension data constant. Minimal Python scaffolding.

### 8. Strengths

- Adversarial robustness (critic finds what optimist misses)
- Extreme simplicity (3 base calls, ~14 exports)
- Natural confidence detection from advocate tension
- Bounded judge input regardless of context size
- L2 optionality (emergent from advocate REPL, not hardcoded)

### 9. Weaknesses

- Context sent twice (to both advocates) -- token-expensive
- No Polya dimension scaffold
- Role adherence risk (model may not maintain adversarial stance)
- No iteration mechanism
- Judge as single point of failure

### 10. Risk

- Advocate degeneracy (same model produces similar outputs regardless of role)
- L2 coordination failure (advocates chunk differently)
- Judge hallucination (no ground truth to verify claims)
- Role prompt injection from user-provided context

---

## Unified Comparison Table

| Axis | V1 (Current) | T1: Workflow-First 3-Layer | T2: Flat Open-Ended | T3: Dimension-Adaptive | T4: Adversarial Debate |
|---|---|---|---|---|---|
| **Total LLM calls (typical)** | ~14/cycle, ~28 for 2 cycles | 8-22 | 6-11 | 7-10 | 3 (base), 9-13 (with L2) |
| **Max recursion depth** | 1 (L0+L1) | 2 (L0+L1+L2) | 1 (L0+L1) | 1 (L0+L1) | 2 (conditional L0+L1+L2) |
| **Prompt rigidity** | High | Medium | Low | Medium | Medium |
| **Context visibility at L0** | Manifest only | Manifest only | Full context | Manifest only | Manifest only |
| **Exports count** | 23 | ~16 | ~11 | ~16 | ~14 |
| **Instruction constants** | 6 | 2 | 1 | 2 | 3 |
| **Risk of model drift** | Low | Medium | High | Medium | Medium-High |
| **Iteration mechanism** | Full 5-phase loop | None | None | Targeted round 2 | None |
| **Coverage guarantee** | Strong (all 8 dims) | Weak (task-dependent) | None | Moderate (adaptive) | None (emergent) |
| **Token efficiency** | Good (1 packet/child) | Variable | Poor (full ctx x Q) | Good (1 packet/child) | Moderate (full ctx x 2) |
| **Best suited for** | Unknown domains, systematic audits | Task-oriented, large repos | Small tasks, exploration | Mixed domains | Ambiguous problems, red-teaming |

---

## Recommendation

**Build T2 (Flat Open-Ended) first, then T3 (Dimension-Adaptive Round-Trip).**

### Why T2 first

1. **Fastest to implement** -- 11 exports, no cycles, simplest dispatch pattern (fan-out + reduce).
2. **Most informative first experiment** -- answers the fundamental question: "Does the model need all of v1's structure, or can it produce comparable understanding with maximum freedom?" If T2 matches v1 quality, v1's complexity is provably unnecessary.
3. **Easiest to test** -- fixed dispatch structure maps cleanly to provider-fake fixtures. One fixture for L0 turns, Q fixtures for investigators, one for synthesis.
4. **Deterministic call count** -- no conditional branching, no cycles. Simplifies cost estimation and benchmark design.

### Why T3 second

1. **Most direct v1 comparison** -- same Polya dimension scaffold, same manifest-only L0, same structured probes. Tests the specific hypothesis: "Is adaptive selection better than exhaustive probing?"
2. **Shares v1 infrastructure** -- reuses POLYA_DIMENSIONS, packet preparation, probe response format. Lowest marginal implementation effort.
3. **Has iteration** -- the only proposed topology with a self-correction mechanism (round 2 re-probing), making it the fairest v1 comparison on complex inputs.

### Why not T1 or T4 first

- **T1 (Workflow-First)** is the user's described approach and should be built, but its conditional L2 dispatch makes testing significantly harder. Build after establishing T2 and T3 baselines.
- **T4 (Adversarial Debate)** is the most experimental and its risks (role degeneracy, judge hallucination) are least understood. Build last as an exploratory experiment.

### Suggested build order

1. **T2 (Flat Open-Ended)** -- baseline comparison
2. **T3 (Dimension-Adaptive Round-Trip)** -- structured comparison
3. **T1 (Workflow-First 3-Layer)** -- user's described approach
4. **T4 (Adversarial Debate)** -- experimental
