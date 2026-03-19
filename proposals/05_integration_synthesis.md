# Proposal 05: Integration Synthesis -- Observability-Enriched Benchmark Evaluation

**Author:** Integration-Synthesizer teammate
**Date:** 2026-03-18
**Status:** PROPOSAL (no code changes)
**Depends on:** Proposals 01, 02, 03, 04

---

## 1. Overlap and Conflict Analysis

### 1.1 Agreement Points

All four proposals converge on these foundational decisions:

1. **SQLite as the primary query backend.** Proposals 01, 03, and 04 all center on `traces.db` written by `SqliteTracingPlugin` (`rlm_adk/plugins/sqlite_tracing.py`, line 325) as the durable queryable store. No proposal introduces an alternative persistence layer.

2. **`obs:child_summary@d{N}f{M}` as the richest per-child signal.** Proposal 01 (section 1.1) identifies it as "the single richest signal." Proposal 02 (section 5.1) derives all behavioral indicators from it. Proposal 03 (Q2, Q3, Q4, Q5) queries it for coverage and question quality. Proposal 04 (section 2.6, step 4) uses it to construct CHILD_DISPATCHED/CHILD_RETURNED narrative events.

3. **Cumulative keys over per-iteration keys.** All proposals prefer `obs:child_dispatch_count_total` over `obs:child_dispatch_count` for cross-turn analysis, consistent with the oscillation caveat documented in `rlm_adk_docs/observability.md` section 8.1.

4. **Advisory scoring, not blocking.** Proposal 03 (section 2.1) explicitly states `ProcessScore.passed` is advisory and does not override `ContractResult.passed`. Proposal 02 and 04 implicitly agree by providing scoring rubrics and judge evaluations that are supplementary to the existing pass/fail contract.

5. **Five scoring dimensions.** Proposals 02 and 03 independently arrive at the same five dimensions: `coverage_thoroughness`, `question_quality`, `synthesis_depth`, `iterative_refinement`, and `appropriate_tool_use` (proposal 03 calls the last one `appropriate_tool_use`; proposal 02 calls it `appropriate_dispatch`). The core intent is identical.

### 1.2 Divergences Requiring Reconciliation

#### D1: Scoring Scale -- 0.0-1.0 vs 0-5

**Proposal 02** uses a 0-5 integer scale per dimension (section 2.1-2.5 rubric tables).
**Proposal 03** uses a 0.0-1.0 float scale per dimension (`DimensionScore.score`).
**Proposal 04** uses a 1-5 integer scale for the judge LLM's semantic dimensions.

**Resolution:** Adopt proposal 03's 0.0-1.0 normalized float as the canonical `DimensionScore.score`. Proposal 02's 0-5 rubric scores map to 0.0-1.0 by dividing by 5. Proposal 04's 1-5 judge scores map to 0.0-1.0 by `(score - 1) / 4`. The `raw_value` field on `DimensionScore` retains the original scale for diagnostics.

#### D2: Topology Vocabulary

**Proposal 02** uses topology names: T1, T2, T3, T4.
**Proposal 03** uses generic topology archetypes: `flat`, `recursive`, `fanout`, `debate`.
**Proposal 04** uses the same T1-T4 names as proposal 02.

**Resolution:** Use the T1-T4 names as the canonical topology identifiers since they map 1:1 to concrete skill files. Proposal 03's generic archetypes (`flat`, `recursive`, `fanout`, `debate`) become a secondary classification layer for non-Polya topologies. The `ProcessEvaluator._detect_topology()` method should first check for Polya topology markers (Gap 1 from proposal 01 -- the new `repl_skill_topology` key), then fall back to the generic dispatch-pattern heuristic from proposal 03.

#### D3: Where Topology-Specific Rubrics Live

**Proposal 02** defines per-topology rubric tables inline (sections 2.1-2.5) with topology-specific weights (section 2.6).
**Proposal 03** defines topology branching inside `ProcessEvaluator._eval_*()` methods with a `_TOPOLOGY_DEFAULTS` dict.
**Proposal 04** defines topology-specific phase inference rules (section 2.7) and narrative templates (section 5).

**Resolution:** The rubric tables from proposal 02 become the source of truth for scoring thresholds, encoded as a `_TOPOLOGY_RUBRICS` dict in the `ProcessEvaluator` class from proposal 03. This dict is keyed by `(topology, dimension)` and contains `{min_expected, max_expected, weight}` entries. Proposal 04's phase inference rules feed into the `NarrativeBuilder` which is a separate component consumed *by* the evaluator, not embedded in it.

#### D4: Deterministic vs LLM Judge Boundary

**Proposal 03** is entirely deterministic -- SQL queries + Python threshold comparisons.
**Proposal 04** (section 4.1) explicitly delineates: deterministic for structural checks, LLM judge for semantic quality.

**Resolution:** The `ProcessEvaluator` from proposal 03 handles all deterministic scoring (5 dimensions). The `NarrativeJudge` from proposal 04 is an *optional overlay* that adds 4 semantic dimensions (`understanding_quality`, `gap_identification_accuracy`, `verdict_appropriateness`, `synthesis_coherence`) only when explicitly opted in via an `expected_process.judge` section in the fixture JSON or a runtime flag. This separation keeps the default test suite fast (no API calls) while enabling deep evaluation for benchmark runs.

#### D5: Phase-Level vs Call-Level Granularity

**Proposal 01** (Gap 2) identifies the absence of phase labels on `llm_calls[]` entries.
**Proposal 02** references phase labels throughout its rubrics but assumes they exist.
**Proposal 04** (section 2.7) defines phase inference heuristics that reconstruct phase labels from call patterns.

**Resolution:** Two-track approach:
- **Short term (Phase 1):** Use proposal 04's heuristic phase inference from call patterns (call sequence position + batch vs single dispatch + topology). This requires no changes to the dispatch closure signatures.
- **Medium term (Phase 2):** Implement Gap 2 from proposal 01 -- add an optional `phase: str` parameter to `llm_query_async()` / `llm_query_batched_async()` that flows into the trace entry dict and `obs:child_summary`. This makes phase labels first-class rather than inferred.

#### D6: Anti-Pattern Detection Scope

**Proposal 02** defines a comprehensive anti-pattern catalog (27 anti-patterns across 5 categories, section 4).
**Proposal 03** does not address anti-patterns.
**Proposal 04** includes deterministic rubric checks (Appendix A) that overlap with some anti-patterns.

**Resolution:** Anti-pattern detection becomes a post-scoring pass within `ProcessEvaluator.evaluate()`. After computing the 5 dimension scores, the evaluator runs an `_detect_anti_patterns()` method that checks for proposal 02's critical and high-severity anti-patterns and applies score penalties per section 4.6 of proposal 02. Anti-pattern results are attached to the `ProcessScore` as a `anti_patterns: list[dict]` field.

### 1.3 Dependencies Between Proposals

```
Proposal 01 (Telemetry Catalog)
  |
  |-- Gap 1 (topology ID) --> consumed by Proposals 02, 03, 04 (topology detection)
  |-- Gap 2 (phase labels) --> consumed by Proposals 02, 04 (phase-level scoring/narrative)
  |-- Gap 8 (dimension metadata) --> consumed by Proposal 02 (dimension-specific scoring)
  |
  v
Proposal 02 (Behavioral Rubrics)
  |
  |-- Rubric tables --> consumed by Proposal 03 (ProcessEvaluator dimension scoring)
  |-- Anti-pattern catalog --> consumed by Proposal 03 (post-scoring penalties)
  |-- Topology weights --> consumed by Proposal 03 (weighted composite score)
  |
  v
Proposal 03 (ProcessEvaluator)
  |
  |-- ProcessScore output --> consumed by Proposal 04 (deterministic_results in judge prompt)
  |-- PluginContractResult extension --> consumed by Proposal 04 (NarrativeBuilder input)
  |
  v
Proposal 04 (TraceNarrative + Judge)
```

---

## 2. Unified Data Flow

### 2.1 End-to-End Pipeline

```
STAGE 1: Agent Execution (existing)
  adk run / run_fixture_contract_with_plugins()
    |
    v
  Reasoning agent -> REPL -> dispatch closures -> child workers
    |
    v
  Observability stack:
    ObservabilityPlugin  -> callback_context.state (reasoning tokens)
    flush_fn()           -> tool_context.state (dispatch accumulators)
    REPLTrace            -> LAST_REPL_RESULT.trace_summary
    SqliteTracingPlugin  -> traces.db (traces + telemetry + session_state_events)
    REPLTracingPlugin    -> repl_traces.json artifact

STAGE 2: Contract Check (existing)
  ScenarioRouter.check_expectations() -> ContractResult (pass/fail)

STAGE 3: Process Evaluation (NEW -- proposal 03)
  ProcessEvaluator(PluginContractResult, expected_process, topology)
    |
    +-- _detect_topology()           uses Gap 1 key or heuristic (D2 resolution)
    +-- _eval_coverage_thoroughness()  SQL Q1-Q3 from proposal 03
    +-- _eval_question_quality()       SQL Q4-Q5 from proposal 03
    +-- _eval_synthesis_depth()        SQL Q6-Q8 from proposal 03
    +-- _eval_iterative_refinement()   SQL Q9-Q11 from proposal 03
    +-- _eval_appropriate_tool_use()   SQL Q12-Q15 from proposal 03
    +-- _apply_topology_rubrics()      rubric tables from proposal 02 (D3 resolution)
    +-- _detect_anti_patterns()        catalog from proposal 02, section 4
    |
    v
  ProcessScore (5 DimensionScores + composite + anti_patterns)

STAGE 4: Narrative Construction (NEW -- proposal 04)
  NarrativeBuilder(traces_db_path, trace_id)
    |
    +-- Pass 1: Load trace metadata
    +-- Pass 2: Load telemetry rows
    +-- Pass 3: Load state events
    +-- Pass 4: Load REPL trace summaries
    +-- Pass 5: Correlate, infer phases, assemble
    |
    v
  TraceNarrative (events + data_flow_links + phase_timings + summary)
    |
    +-- render_markdown()  -> human-readable narrative

STAGE 5: Judge LLM Evaluation (NEW, OPT-IN -- proposal 04)
  NarrativeJudge(narrative_markdown, deterministic_results, topology)
    |
    +-- Build judge prompt from template
    +-- llm_query(prompt, output_schema=NarrativeJudgment)
    |
    v
  NarrativeJudgment (4 semantic scores + overall_score + observations)

STAGE 6: Aggregation
  PluginContractResult
    .contract           = ContractResult (pass/fail)          [existing]
    .process_score      = ProcessScore (5 dimensions)         [new]
    .trace_narrative    = TraceNarrative (optional)            [new]
    .narrative_judgment = NarrativeJudgment (optional)         [new]
```

### 2.2 Data Source Mapping

Each component reads from specific sources. No component writes back to agent state during evaluation -- all processing is post-hoc and read-only.

| Component | Reads From | Produces |
|-----------|-----------|----------|
| `ProcessEvaluator` | `traces.db` (SQL), `PluginContractResult.final_state`, `PluginContractResult.events` | `ProcessScore` |
| `NarrativeBuilder` | `traces.db` (SQL), `repl_traces.json` artifact | `TraceNarrative` |
| `NarrativeJudge` | `TraceNarrative.render_markdown()`, `ProcessScore.diagnostics()` | `NarrativeJudgment` |

---

## 3. Component Inventory

### 3.1 New Files to Create

| File Path | Contents | Phase |
|-----------|----------|-------|
| `rlm_adk/evaluation/__init__.py` | Package init, re-exports `ProcessEvaluator`, `ProcessScore`, `DimensionScore` | 1 |
| `rlm_adk/evaluation/process_evaluator.py` | `ProcessEvaluator` class, `ProcessScore`, `DimensionScore` dataclasses, all 5 `_eval_*()` methods, `_detect_topology()`, `_detect_anti_patterns()`, `_TOPOLOGY_RUBRICS` dict | 1-2 |
| `rlm_adk/evaluation/topology_rubrics.py` | `_TOPOLOGY_RUBRICS` dict encoding proposal 02's per-topology scoring thresholds and weights, anti-pattern detection rules from proposal 02 section 4 | 2 |
| `rlm_adk/evaluation/narrative_builder.py` | `NarrativeBuilder` class, 5-pass assembly algorithm, topology-specific phase inference from proposal 04 section 2.7 | 3 |
| `rlm_adk/evaluation/narrative_types.py` | `TraceNarrative`, `NarrativeEvent`, `DataFlowLink`, `PhaseTimingBlock`, `NarrativeSummary` dataclasses from proposal 04 section 1.1 | 3 |
| `rlm_adk/evaluation/narrative_judge.py` | `NarrativeJudge` class, `NarrativeJudgment` Pydantic model, judge prompt template from proposal 04 sections 4.2-4.3 | 3 |
| `tests_rlm_adk/test_process_evaluator.py` | Unit tests for `ProcessEvaluator` using existing fixture traces.db files | 1 |
| `tests_rlm_adk/test_narrative_builder.py` | Unit tests for `NarrativeBuilder` using existing fixture traces.db files | 3 |

### 3.2 Extensions to Existing Files

| File Path | What Changes | Phase |
|-----------|-------------|-------|
| `rlm_adk/state.py` | Add `REPL_SKILL_TOPOLOGY = "repl_skill_topology"` constant; add to `DEPTH_SCOPED_KEYS`; add to `EXPOSED_STATE_KEYS` | 1 |
| `rlm_adk/tools/repl_tool.py` | After `expand_skill_imports()` completes (~line 180), extract topology identifier from `expansion.expanded_modules` and write `REPL_SKILL_TOPOLOGY` to `tool_context.state` (Gap 1 fill) | 1 |
| `rlm_adk/plugins/sqlite_tracing.py` | Add `"repl_skill_topology"` to `_CURATED_EXACT` set (~line 125); add `"repl_skill_topology"` categorization in `_categorize_key()` as `"repl"` | 1 |
| `tests_rlm_adk/provider_fake/contract_runner.py` | Add `process_score: ProcessScore | None = None` field to `PluginContractResult` (~line 90); add optional `ProcessEvaluator` invocation after `check_expectations()` (~line 484) | 1 |
| `tests_rlm_adk/provider_fake/fixtures.py` | Add `self.expected_process: dict = fixture.get("expected_process", {})` to `ScenarioRouter.__init__()` (~line 249) | 1 |
| `tests_rlm_adk/fixtures/provider_fake/repl_error_then_retry.json` | Add `expected_process` section (proposal 03 section 3.3 example) | 2 |
| `tests_rlm_adk/fixtures/provider_fake/fake_recursive_ping.json` | Add `expected_process` section (proposal 03 section 3.4 example) | 2 |
| `tests_rlm_adk/fixtures/provider_fake/fake_polya_t4_debate.json` | Add `expected_process` section with T4-specific rubric thresholds | 2 |
| `tests_rlm_adk/fixtures/provider_fake/structured_output_batched_k3.json` | Add `expected_process` section with fanout-specific thresholds | 2 |
| `rlm_adk/repl/trace.py` | (Phase 2, Gap 2) Add optional `phase: str` field to `llm_calls` entry dicts in `REPLTrace`; extend `DataFlowTracker.register_response()` to accept optional `label` parameter (Gap 4) | 2 |
| `rlm_adk/dispatch.py` | (Phase 2, Gap 2) Add optional `phase: str` and `metadata: dict` parameters to `llm_query_async()` / `llm_query_batched_async()` closures; pass through to trace recording and child summary construction | 2 |

### 3.3 Files NOT Modified

The following files are read-only inputs to this design and require no changes:

- `rlm_adk/plugins/observability.py` -- existing callbacks are sufficient
- `rlm_adk/plugins/repl_tracing.py` -- existing artifact format is sufficient
- `rlm_adk/callbacks/worker.py` -- `_call_record` structure is sufficient
- `rlm_adk/callbacks/reasoning.py` -- existing token accounting is sufficient
- `rlm_adk/orchestrator.py` -- no changes needed (cumulative counter seeding is already in place)

---

## 4. AR-CRIT-001 Compliance

### 4.1 New State Writes Proposed Across All Proposals

Only **one new state write** is introduced by this synthesis:

| Key | Written Where | Written How | AR-CRIT-001 Status |
|-----|-------------|-------------|-------------------|
| `repl_skill_topology` | `REPLTool.run_async()` (~line 180) | `tool_context.state[depth_key(REPL_SKILL_TOPOLOGY, depth)] = topology_id` | COMPLIANT -- written via `tool_context.state`, same pattern as existing `REPL_DID_EXPAND` at line 178 |

### 4.2 Compliance Audit of All 4 Proposals

**Proposal 01:** Identifies 8 telemetry gaps. Gaps 1 and 8 propose new state writes. Gap 1 (`repl_skill_topology`) is compliant via `tool_context.state` as shown above. Gap 8 proposes adding `metadata` to the `llm_query_async()` closure signature -- this flows through the dispatch closure's local accumulators and is flushed via `flush_fn()`, which writes to `tool_context.state`. COMPLIANT.

**Proposal 02:** Pure analysis proposal. Defines rubrics and anti-patterns but proposes no state writes. N/A.

**Proposal 03:** The `ProcessEvaluator` is a post-hoc read-only analyzer. It reads from `traces.db` and `PluginContractResult.final_state` but never writes to agent state. COMPLIANT by design.

**Proposal 04:** The `NarrativeBuilder` and `NarrativeJudge` are post-hoc read-only analyzers. The judge LLM evaluator runs *outside* the agent execution loop -- it is a benchmark harness component, not a dispatch closure. COMPLIANT by design.

### 4.3 Potential Violation in Proposal 01 Gap 3

Gap 3 (Probe Response Quality Scoring) suggests "the skill could write structured quality metrics to a REPL variable." This is safe -- writing to a REPL local variable (e.g., `probe_quality = {...}`) does not touch `ctx.session.state`. The data flows through `repl_stdout` or `var_snapshots`, both of which are captured by existing observability infrastructure without state writes.

### 4.4 Potential Violation in Proposal 01 Gap 5

Gap 5 (Cross-Cycle Comparison) suggests the skill code "compute and print a delta summary." Same analysis as Gap 3 -- printing to stdout flows through `repl_stdout`, not `ctx.session.state`. COMPLIANT.

---

## 5. `_rlm_state` Integration

### 5.1 Current State

The `_rlm_state` read-only snapshot is built by `REPLTool.run_async()` at line 192 from `EXPOSED_STATE_KEYS` defined in `rlm_adk/state.py` line 160. It is injected into REPL globals before each code block executes.

### 5.2 New Key Exposure

The new `REPL_SKILL_TOPOLOGY` key should be added to `EXPOSED_STATE_KEYS` so that REPL code can introspect which topology is active:

```python
# In rlm_adk/state.py, add to EXPOSED_STATE_KEYS:
REPL_SKILL_TOPOLOGY,  # "t1_workflow", "t2_flat", "t3_adaptive", "t4_debate"
```

This enables Polya skill code to conditionally adjust behavior based on the detected topology, and enables future self-aware evaluation where the agent can inspect its own process metrics during execution.

### 5.3 Self-Aware Understanding via _rlm_state

The cumulative dispatch keys already exposed in `_rlm_state` (`obs:child_dispatch_count_total`, `obs:child_batch_dispatches_total`, `obs:child_error_counts_total`, `obs:structured_output_failures_total`) provide a foundation for self-aware understanding. A Polya skill could, in a multi-cycle execution:

1. Read `_rlm_state["obs:child_dispatch_count_total"]` at cycle start to know how many probes have been dispatched so far.
2. Read `_rlm_state["obs:child_error_counts_total"]` to detect systemic reliability issues and adapt (e.g., reduce batch size, simplify prompts).
3. Read `_rlm_state["obs:total_input_tokens"]` to monitor token budget consumption and decide whether to continue iterating.

No additional `_rlm_state` keys are needed for the evaluation pipeline itself, since evaluation is post-hoc. The self-aware scenario is an orthogonal enhancement for the Polya skill code, not for the evaluator.

### 5.4 Relationship to Evaluation Pipeline

The evaluation pipeline (ProcessEvaluator, NarrativeBuilder, NarrativeJudge) does NOT use `_rlm_state`. It reads from `traces.db` and `PluginContractResult.final_state` after execution completes. The `_rlm_state` snapshot is relevant only for real-time self-aware behavior during execution, which is out of scope for the evaluation system but is a synergistic enhancement.

---

## 6. Three-Phase Implementation Plan

### Phase 1: Telemetry Gap Fills + ProcessEvaluator Skeleton

**Goal:** Fill the most critical telemetry gap (topology identification), create the ProcessEvaluator class with all 5 dimension evaluators, and wire it into the contract runner pipeline. All evaluation logic uses default thresholds only (no topology-specific rubrics yet).

#### Step 1.1: Fill Gap 1 -- Topology Identification

**Files modified:**
- `rlm_adk/state.py` -- add `REPL_SKILL_TOPOLOGY` constant, add to `DEPTH_SCOPED_KEYS`, add to `EXPOSED_STATE_KEYS`
- `rlm_adk/tools/repl_tool.py` -- after `expand_skill_imports()` at ~line 180, extract topology ID from `expansion.expanded_modules` list. Parse module name: `rlm_repl_skills.polya_understand_t3_adaptive` -> `"t3_adaptive"`. Write to `tool_context.state[depth_key(REPL_SKILL_TOPOLOGY, depth)]`.
- `rlm_adk/plugins/sqlite_tracing.py` -- add `"repl_skill_topology"` to `_CURATED_EXACT` at ~line 125; add categorization as `"repl"` in `_categorize_key()`.

**Estimated effort:** 15-20 lines of production code.

#### Step 1.2: ProcessEvaluator Skeleton

**New files:**
- `rlm_adk/evaluation/__init__.py`
- `rlm_adk/evaluation/process_evaluator.py`

**Contents of `process_evaluator.py`:**
- `DimensionScore` dataclass (from proposal 03 section 1.1)
- `ProcessScore` dataclass with 5 dimension fields + `composite_score` property + `diagnostics()` method + `anti_patterns: list[dict]` field
- `ProcessEvaluator` class with:
  - `__init__(result, expected_process, topology)` -- opens `traces.db` connection
  - `evaluate() -> ProcessScore` -- calls all 5 `_eval_*()` methods
  - `close()` -- closes SQLite connection
  - `_detect_topology()` -- checks for `repl_skill_topology` in final_state first; falls back to dispatch-pattern heuristic from proposal 03
  - `_eval_coverage_thoroughness()` -- SQL Q1-Q3 from proposal 03
  - `_eval_question_quality()` -- SQL Q4-Q5 from proposal 03
  - `_eval_synthesis_depth()` -- SQL Q6-Q8 from proposal 03
  - `_eval_iterative_refinement()` -- SQL Q9-Q11 from proposal 03
  - `_eval_appropriate_tool_use()` -- SQL Q12-Q15 from proposal 03
  - `_get_trace_id()` -- SQL from proposal 03 section 4.6

All dimension evaluators use **default thresholds** (not topology-specific) in Phase 1. Threshold values come from proposal 03's `expected_process` field spec.

#### Step 1.3: Wire into Contract Runner

**Files modified:**
- `tests_rlm_adk/provider_fake/fixtures.py` -- add `self.expected_process` property to `ScenarioRouter`
- `tests_rlm_adk/provider_fake/contract_runner.py` -- add `process_score` field to `PluginContractResult`; invoke `ProcessEvaluator` after `check_expectations()` when `router.expected_process` is non-empty

#### Step 1.4: TDD Sequence

```
1. test_process_evaluator_no_db
   -- ProcessEvaluator with traces_db_path=None returns degraded scores
   -- All DimensionScore objects have score >= 0.0

2. test_process_evaluator_topology_detection
   -- Mock final_state with repl_skill_topology="t3_adaptive"
   -- Assert _detect_topology() returns "t3_adaptive"
   -- Mock final_state without repl_skill_topology but with dispatch keys
   -- Assert heuristic detection returns expected archetype

3. test_process_evaluator_happy_path_fixture
   -- Run repl_error_then_retry fixture through contract_with_plugins
   -- Assert PluginContractResult.process_score is None (no expected_process yet)

4. test_dimension_score_normalization
   -- Verify DimensionScore.score is always in [0.0, 1.0]
   -- Verify ProcessScore.composite_score is the mean of dimension scores

5. test_coverage_thoroughness_queries
   -- Create a test traces.db with known child_summary rows
   -- Run _eval_coverage_thoroughness()
   -- Assert score matches expected based on dispatch counts

6. test_appropriate_tool_use_queries
   -- Create a test traces.db with known telemetry rows
   -- Run _eval_appropriate_tool_use()
   -- Assert REPL call ratio computation is correct
```

**Test file:** `tests_rlm_adk/test_process_evaluator.py`
**Run command:** `.venv/bin/python -m pytest tests_rlm_adk/test_process_evaluator.py -x -q`

---

### Phase 2: Per-Topology Scoring Rubrics + Fixture Schema Extensions

**Goal:** Encode proposal 02's topology-specific rubric tables and weights into the ProcessEvaluator. Extend existing provider-fake fixtures with `expected_process` sections. Implement anti-pattern detection for critical and high-severity patterns.

#### Step 2.1: Topology Rubrics Module

**New file:** `rlm_adk/evaluation/topology_rubrics.py`

Encodes the following from proposal 02:

- **T1 rubric tables** (section 2.1): coverage_thoroughness expects `obs:child_batch_dispatches_total >= 1`, L0 + L1 + optional L2 + synthesis structure.
- **T2 rubric tables** (section 2.2): question_quality expects 5+ investigation children with distinct prompts, no-LLM question generation.
- **T3 rubric tables** (section 2.3): iterative_refinement expects conditional R2 re-probe when R1 confidence < threshold.
- **T4 rubric tables** (section 2.4): appropriate_dispatch expects exactly 3 calls (2 advocates + 1 judge), judge isolation invariant.
- **Topology-specific weights** (section 2.6): `{(T1, iterative_refinement): 1.0, (T2, iterative_refinement): 0.4, ...}`
- **Anti-pattern rules** (section 4): each rule as a `{id, severity, detection_fn, affected_dimension, penalty}` dict.

Data structure:

```python
TOPOLOGY_RUBRICS: dict[str, dict[str, dict]] = {
    "t1_workflow": {
        "coverage_thoroughness": {
            "expected_dispatch_count": {"$gte": 3},  # L0 + L1 batch + synth minimum
            "expected_batch_dispatches": {"$gte": 1},
            "weight": 1.0,
        },
        "question_quality": {"weight": 1.0, ...},
        "synthesis_depth": {"weight": 1.0, ...},
        "iterative_refinement": {"weight": 1.0, ...},
        "appropriate_dispatch": {"weight": 0.8, ...},
    },
    "t2_flat": { ... },
    "t3_adaptive": { ... },
    "t4_debate": { ... },
}

ANTI_PATTERNS: list[dict] = [
    {
        "id": "AP-U1",
        "name": "Ghost Dispatch",
        "severity": "CRITICAL",
        "topologies": ["all"],
        "detection": "dispatch_count_total == 0 and output contains dispatch language",
        "penalty": {"score_override": 0.0},
    },
    # ... 26 more from proposal 02 section 4
]
```

#### Step 2.2: Integrate Rubrics into ProcessEvaluator

**File modified:** `rlm_adk/evaluation/process_evaluator.py`

- Import `TOPOLOGY_RUBRICS` and `ANTI_PATTERNS` from `topology_rubrics.py`
- `_eval_*()` methods now check `self._topology` against rubric tables to get topology-specific thresholds. When `expected_process` provides explicit thresholds, those override rubric defaults (same deep-merge pattern as `fixtures.py` line 27).
- Add `_detect_anti_patterns()` method that runs all applicable anti-pattern rules against the trace data and returns `list[dict]` with `{id, name, severity, detected, detail}` entries.
- `ProcessScore.composite_score` now uses topology-specific weights from rubric tables.

#### Step 2.3: Fill Gap 2 -- Phase Labels (Optional Enhancement)

**Files modified:**
- `rlm_adk/repl/trace.py` -- add optional `phase: str` to `llm_calls` entry dicts; extend `DataFlowTracker` with label support
- `rlm_adk/dispatch.py` -- add optional `phase: str` and `metadata: dict` parameters to `llm_query_async()` and `llm_query_batched_async()` closure signatures

This step is **optional in Phase 2** -- the heuristic phase inference from proposal 04 section 2.7 works without it. Implementing this provides higher-fidelity phase data but requires touching the dispatch closure API and all 5 Polya skill source strings.

**Decision point:** If modifying the dispatch closure signatures is considered too invasive for Phase 2, defer Gap 2 to Phase 3 and continue using heuristic inference.

#### Step 2.4: Extend Existing Fixtures

Add `expected_process` sections to these fixtures:

| Fixture | Topology | Key Assertions |
|---------|----------|---------------|
| `repl_error_then_retry.json` | flat | `iterative_refinement.expected_error_recovery_rate >= 1.0`, `appropriate_tool_use.max_repl_error_rate <= 0.5` |
| `fake_recursive_ping.json` | recursive | `coverage_thoroughness.expected_dispatch_count >= 1`, `synthesis_depth.expected_data_flow_edges >= 0` |
| `fake_polya_t4_debate.json` | t4_debate | `coverage_thoroughness.expected_dispatch_count >= 3`, `appropriate_dispatch` checks for exactly 2+1 pattern |
| `structured_output_batched_k3.json` | fanout | `coverage_thoroughness.expected_dispatch_count >= 3`, `question_quality.expected_unique_ratio >= 0.8` |

Each fixture's `expected_process` uses matcher operators (`$gte`, `$lte`) from the existing `_match_value()` system in `fixtures.py`.

#### Step 2.5: TDD Sequence

```
1. test_topology_rubrics_structure
   -- Verify TOPOLOGY_RUBRICS has entries for all 4 topologies
   -- Verify each topology has all 5 dimensions
   -- Verify all weights are in (0.0, 2.0] range

2. test_anti_pattern_detection_ghost_dispatch
   -- Create mock PluginContractResult with dispatch_count_total=0
   -- Run _detect_anti_patterns()
   -- Assert AP-U1 (Ghost Dispatch) detected with CRITICAL severity

3. test_anti_pattern_detection_t4_judge_isolation
   -- Create mock with T4 topology and large judge prompt
   -- Assert AP-T4-1 (Judge Context Leak) detected

4. test_weighted_composite_score_t4
   -- Verify T4's iterative_refinement weight is 0.4 (single-pass topology)
   -- Verify composite score reflects reduced weight

5. test_expected_process_fixture_override
   -- Load fixture with explicit expected_process thresholds
   -- Verify fixture thresholds override rubric defaults

6. test_repl_error_retry_with_process_score
   -- Run repl_error_then_retry fixture (now with expected_process)
   -- Assert process_score is not None
   -- Assert iterative_refinement.score > 0.5

7. test_fake_recursive_ping_with_process_score
   -- Run fake_recursive_ping fixture (now with expected_process)
   -- Assert coverage_thoroughness.score > 0.5
```

**Test file:** `tests_rlm_adk/test_process_evaluator.py` (extended)
**Run command:** `.venv/bin/python -m pytest tests_rlm_adk/test_process_evaluator.py -x -q`

---

### Phase 3: TraceNarrative Builder + Judge LLM Integration

**Goal:** Implement proposal 04's narrative reconstruction system and the opt-in LLM judge evaluator. Wire the narrative and judge into the evaluation pipeline.

#### Step 3.1: Narrative Type Definitions

**New file:** `rlm_adk/evaluation/narrative_types.py`

Implement all dataclasses from proposal 04 section 1.1:
- `NarrativeEvent`
- `DataFlowLink`
- `PhaseTimingBlock`
- `NarrativeSummary`
- `TraceNarrative`

#### Step 3.2: NarrativeBuilder

**New file:** `rlm_adk/evaluation/narrative_builder.py`

Implements the 5-pass algorithm from proposal 04 section 2.1-2.6:

1. Load trace metadata (SQL from section 2.2)
2. Load telemetry rows (SQL from section 2.3)
3. Load state events (SQL from section 2.4)
4. Load REPL trace summaries (section 2.5)
5. Correlate, infer phases, assemble (section 2.6)

Phase inference uses topology-specific rules from section 2.7:
- T1: first single dispatch = L0_WORKFLOW, first batch = L1_ASSESS, second batch (if present) = L2_CHUNK, final single = SYNTHESIZE
- T2: first batch = INVESTIGATE, first single after batch = SYNTHESIZE
- T3: first single = SELECT, first batch = PROBE_R1, second batch (if present) = REPROBE_R2, final single = SYNTHESIZE
- T4: first batch with exactly 2 children = ADVOCATE, first single after batch = JUDGE

`TraceNarrative` includes a `render_markdown()` method producing the output format from proposal 04 section 3.

#### Step 3.3: NarrativeJudge

**New file:** `rlm_adk/evaluation/narrative_judge.py`

Implements:
- `NarrativeJudgment` Pydantic model from proposal 04 section 4.2
- `NarrativeJudge` class with `evaluate(narrative, deterministic_results, topology) -> NarrativeJudgment`
- Judge prompt template from proposal 04 section 4.3
- Topology description constants for each T1-T4 variant
- Temperature=0.0, version-pinned prompt template

**When to use deterministic vs LLM judge** (proposal 04 section 4.1):

| Assessment | Method | Reason |
|-----------|--------|--------|
| Phase completion | Deterministic (ProcessEvaluator) | Binary structural check |
| Child error rate | Deterministic (ProcessEvaluator) | Threshold comparison |
| Data flow completeness | Deterministic (ProcessEvaluator) | Edge count vs expected |
| Token efficiency | Deterministic (ProcessEvaluator) | Ratio comparison |
| Understanding quality | LLM Judge | Requires semantic evaluation |
| Gap identification accuracy | LLM Judge | Requires domain knowledge |
| Verdict appropriateness | LLM Judge | Requires reasoning about evidence |
| Synthesis coherence | LLM Judge | Requires evaluating logical structure |

#### Step 3.4: Cost Analysis and Opt-In Mechanisms

**API cost per judge evaluation:**
- Input: ~2,000 tokens (narrative markdown + deterministic results + prompt template)
- Output: ~500 tokens (structured judgment)
- Cost with `gemini-2.0-flash`: ~$0.01 per evaluation
- Cost with `gemini-2.5-pro`: ~$0.06 per evaluation

**Opt-in mechanisms:**

1. **Fixture-level:** Add `"judge": {"enabled": true, "model": "gemini-2.0-flash"}` to the `expected_process` section. When `judge.enabled` is absent or false, no LLM call is made.

2. **Environment variable:** `RLM_EVAL_JUDGE=1` enables the judge for all fixtures that have `expected_process` sections. Default: off.

3. **Programmatic:** `ProcessEvaluator(result, expected_process, topology, judge_model="gemini-2.0-flash")` constructor parameter.

**Budget guard:** The judge evaluator tracks cumulative cost within a test session and refuses to make further calls once a configurable ceiling is reached (default: $1.00). This prevents runaway costs if someone accidentally enables the judge for the full 970+ test suite.

#### Step 3.5: Wire into PluginContractResult

**File modified:** `tests_rlm_adk/provider_fake/contract_runner.py`

Add optional fields:
```python
@dataclasses.dataclass
class PluginContractResult:
    # ... existing fields ...
    process_score: ProcessScore | None = None
    trace_narrative: TraceNarrative | None = None
    narrative_judgment: NarrativeJudgment | None = None
```

In `run_fixture_contract_with_plugins()`, after process evaluation:
- If `expected_process.get("narrative", False)` is truthy, construct `NarrativeBuilder` and produce `TraceNarrative`.
- If `expected_process.get("judge", {}).get("enabled", False)` is truthy and `RLM_EVAL_JUDGE` env var is set, run `NarrativeJudge`.

#### Step 3.6: TDD Sequence

```
1. test_narrative_types_construction
   -- Construct TraceNarrative with sample events
   -- Assert all fields serialize correctly

2. test_narrative_builder_pass1_metadata
   -- Create a traces.db with known trace row
   -- Run NarrativeBuilder pass 1
   -- Assert trace_id and start_time extracted correctly

3. test_narrative_builder_pass5_t4_phase_inference
   -- Create traces.db with T4 call pattern (2 batched + 1 single)
   -- Run full NarrativeBuilder
   -- Assert phases detected: ADVOCATE, JUDGE
   -- Assert data_flow_links has 2 edges (optimist->judge, critic->judge)

4. test_narrative_builder_pass5_t3_phase_inference
   -- Create traces.db with T3 call pattern
   -- Assert phases: SELECT, PROBE_R1, GAP_ANALYSIS (if applicable), SYNTHESIZE
   -- Assert conditional REPROBE_R2 detected when gap dimensions exist

5. test_narrative_render_markdown
   -- Build a TraceNarrative for T4
   -- Call render_markdown()
   -- Assert output contains expected sections
   -- Assert timeline visualization is well-formed

6. test_narrative_judge_structured_output
   -- Mock the LLM response for the judge
   -- Run NarrativeJudge.evaluate()
   -- Assert NarrativeJudgment has all 4 semantic scores
   -- Assert overall_score is computed correctly

7. test_narrative_judge_budget_guard
   -- Set budget ceiling to $0.01
   -- Attempt 10 judge evaluations
   -- Assert calls stop after budget exceeded

8. test_end_to_end_with_narrative
   -- Run fake_polya_t4_debate fixture with expected_process.narrative=true
   -- Assert trace_narrative is not None
   -- Assert trace_narrative.topology == "T4"
   -- Assert trace_narrative.events has ADVOCATE and JUDGE events
```

**Test file:** `tests_rlm_adk/test_narrative_builder.py`
**Run command:** `.venv/bin/python -m pytest tests_rlm_adk/test_narrative_builder.py -x -q`

---

## 7. Risk Assessment

### R1: Judge LLM API Cost

**Risk:** Enabling the judge LLM for large test suites could incur significant costs.
**Likelihood:** Medium (requires explicit opt-in, but a CI misconfiguration could enable it).
**Mitigation:** Triple opt-in (fixture-level + env var + budget guard). Default: off. Budget guard caps at $1.00 per session. The judge uses `gemini-2.0-flash` by default (cheapest option at ~$0.01/call).

### R2: Test Suite Performance Impact

**Risk:** Adding ProcessEvaluator to every fixture run slows the default ~22s test suite.
**Likelihood:** Low. Per proposal 03 section 5.3, evaluation overhead is <10ms per fixture. With 28 fixtures, worst case is ~280ms (<2% of runtime).
**Mitigation:** Evaluation only runs when `expected_process` is present in the fixture JSON. Fixtures without it pay zero overhead.

### R3: Topology-Specific Rubric Maintenance Burden

**Risk:** Each new Polya topology (or topology revision) requires updating the rubric tables, anti-pattern catalog, and phase inference rules.
**Likelihood:** Medium (new topologies are planned but infrequent).
**Mitigation:** All topology-specific configuration is centralized in `topology_rubrics.py`. Adding a new topology requires: (1) add an entry to `TOPOLOGY_RUBRICS`, (2) add topology-specific anti-patterns if any, (3) add phase inference rules to `NarrativeBuilder`. The `_detect_topology()` fallback heuristic handles unknown topologies with generic scoring.

### R4: Phase Inference Fragility

**Risk:** The heuristic phase inference from proposal 04 section 2.7 depends on call sequence patterns. If a topology's dispatch pattern changes (e.g., T3 adds a third round), the inference breaks.
**Likelihood:** Medium (topology code is under active development).
**Mitigation:** Phase inference rules are topology-versioned. The `repl_skill_topology` key (Gap 1) includes version info when available. When the heuristic cannot determine a phase, it assigns `"UNKNOWN"` rather than crashing. Phase 2's Gap 2 (explicit `phase` parameter on `llm_query`) eliminates this risk entirely for topologies that adopt it.

### R5: SQLite Query Correctness

**Risk:** The 15 SQL queries from proposal 03 section 4 assume specific `key_category` and `state_key` values. Changes to `_categorize_key()` or `_should_capture()` in `sqlite_tracing.py` could silently break queries.
**Likelihood:** Low (the curated capture set is stable and well-documented).
**Mitigation:** Each SQL query is tested against a known traces.db in the TDD sequence. The `test_process_evaluator.py` tests create synthetic traces.db files with expected rows and verify query results.

### R6: Proposal 02 Rubric Scoring Subjectivity

**Risk:** Several rubric criteria in proposal 02 require semantic judgment that is difficult to automate deterministically (e.g., "arguments reference specific artifacts" in T4 question_quality score level 4).
**Likelihood:** High (many rubric levels require text content analysis).
**Mitigation:** Phase 2 implements only the deterministically checkable rubric levels. Semantic rubric levels (scores 4-5 in most dimensions) are deferred to Phase 3's LLM judge. The deterministic evaluator returns a ceiling score that may be upgraded by the judge.

### R7: Data Flow Edge Reliability

**Risk:** The `DataFlowTracker`'s 40-character substring fingerprint (at `rlm_adk/repl/trace.py` line 127) may produce false negatives for short responses or false positives for common boilerplate.
**Likelihood:** Medium (noted as open question in proposal 02 section 6.3).
**Mitigation:** Edge counts in rubric thresholds use `$gte` (minimum), not exact counts. Missing edges degrade the score but do not fail the test. The NarrativeBuilder can supplement DataFlowTracker edges with topology-inferred edges (e.g., T4 always has exactly 2 advocate->judge edges by structure).

---

## 8. Open Questions

### Q1: Should ProcessScore affect ContractResult.passed?

Current design: advisory only. However, should CRITICAL anti-patterns (AP-U1 Ghost Dispatch, AP-T4-1 Judge Context Leak) that indicate broken invariants cause the contract to fail? This would require `check_expectations()` to consult process evaluation.

**Recommendation:** Keep them separate in Phase 1-2. Revisit in Phase 3 after gathering data on false positive rates.

### Q2: How to handle fixtures that intentionally trigger anti-patterns?

Example: `repl_error_then_retry.json` intentionally has REPL errors. If an anti-pattern rule flags "high error rate," it would penalize a fixture that is specifically testing error recovery.

**Recommendation:** Fixtures can declare `expected_process.suppress_anti_patterns: ["AP-U6"]` to explicitly suppress specific anti-pattern checks. This is analogous to how `expected_state` can use `$absent` to assert key absence.

### Q3: Cross-topology normalization for comparative analysis

Proposal 02 section 6.1 asks whether T1 and T4 scores should be directly comparable.

**Recommendation:** No. Each topology has fundamentally different "good behavior." Compare within-topology across runs (e.g., "is this T3 run better than the last T3 run?"), not cross-topology. The topology-specific weights from proposal 02 section 2.6 already normalize for structural differences within the composite score, but the composite itself should not be compared across topologies.

### Q4: Where do Polya skill source modifications live?

Proposals 01 Gaps 2, 3, 5, 6, 7, and 8 all require modifying the 5 Polya skill source strings (`rlm_adk/skills/polya_understand*.py`). These modifications are not part of the evaluation pipeline itself but are telemetry enrichment prerequisites.

**Recommendation:** Defer all Polya skill source modifications to a separate task/branch. The evaluation pipeline works with existing telemetry in Phases 1-2. Phase 3 benefits from Gap 2 (phase labels) but can use heuristic inference without it.

### Q5: Should NarrativeBuilder output be persisted?

The `render_markdown()` output is useful for debugging but currently lives only in memory as part of `PluginContractResult.trace_narrative`.

**Recommendation:** Optionally save as a file artifact alongside `traces.db` (e.g., `narrative.md`). This is low-priority and can be added after Phase 3.

### Q6: How does the judge LLM evaluator interact with provider-fake tests?

Provider-fake tests use `FakeGeminiServer` with canned responses. The judge LLM call would hit the fake server, which would need a canned judge response in the fixture.

**Recommendation:** The judge evaluator should be skipped entirely in provider-fake tests (it requires real API access). The opt-in mechanism (env var `RLM_EVAL_JUDGE=1`) naturally excludes it from CI. For testing the judge *code*, mock the LLM response in unit tests.

### Q7: What is the minimum traces.db schema version required?

The SQL queries assume the current 3-table schema with all columns present. If `SqliteTracingPlugin` adds new columns via migration, the evaluator needs to handle both old and new schemas.

**Recommendation:** The evaluator should check for required columns before running queries and degrade gracefully (return neutral 0.5 scores) when columns are missing. This is already the pattern proposed in proposal 03 section 5.1 for the "no traces.db" case.

### Q8: Polya v1 (iterative) topology coverage

The proposals focus on T1-T4 but also mention v1 (the original iterative topology in `rlm_adk/skills/polya_understand.py`). Should v1 have its own rubric?

**Recommendation:** Yes, but defer to after Phase 2. v1 is the most complex topology (multi-cycle with REFRAME, PROBE, SYNTHESIZE, VALIDATE, REFLECT phases and a CONTINUE/HALT verdict loop). Its rubric requires all 5 dimensions plus multi-cycle comparison metrics from proposal 01 Gap 5.

---

## Source File Reference

| File | Role in This Design |
|------|-------------------|
| `rlm_adk/state.py` (lines 160-183) | `EXPOSED_STATE_KEYS` set -- add `REPL_SKILL_TOPOLOGY` |
| `rlm_adk/tools/repl_tool.py` (lines 164-198) | Skill expansion + `_rlm_state` build -- add topology extraction |
| `rlm_adk/plugins/sqlite_tracing.py` (lines 113-160) | Curated capture set -- add `repl_skill_topology` |
| `rlm_adk/plugins/sqlite_tracing.py` (lines 258-321) | DDL schema -- read by ProcessEvaluator and NarrativeBuilder |
| `rlm_adk/dispatch.py` (lines 564-655) | Child summary construction -- source for coverage/quality queries |
| `rlm_adk/dispatch.py` (lines 790-829) | `flush_fn()` -- source for dispatch accumulator state |
| `rlm_adk/repl/trace.py` (lines 22-155) | REPLTrace + DataFlowTracker -- source for synthesis depth queries |
| `rlm_adk/plugins/observability.py` (lines 50-408) | ObservabilityPlugin -- source for reasoning-level metrics |
| `rlm_adk/plugins/repl_tracing.py` (lines 25-98) | REPLTracingPlugin -- source for `repl_traces.json` artifact |
| `tests_rlm_adk/provider_fake/fixtures.py` (lines 46-130) | `_match_value()` matchers -- reused for `expected_process` |
| `tests_rlm_adk/provider_fake/fixtures.py` (lines 241-527) | `ScenarioRouter` -- add `expected_process` property |
| `tests_rlm_adk/provider_fake/contract_runner.py` (lines 89-101) | `PluginContractResult` -- add `process_score`, `trace_narrative`, `narrative_judgment` fields |
| `tests_rlm_adk/provider_fake/contract_runner.py` (lines 360-500) | `run_fixture_contract_with_plugins()` -- add evaluator invocation |
| `tests_rlm_adk/fixtures/provider_fake/repl_error_then_retry.json` | First fixture to get `expected_process` |
| `tests_rlm_adk/fixtures/provider_fake/fake_recursive_ping.json` | Recursive dispatch fixture for process eval |
| `tests_rlm_adk/fixtures/provider_fake/fake_polya_t4_debate.json` | T4 topology fixture for topology-specific eval |
| `rlm_adk/skills/polya_understand_t1_workflow.py` | T1 skill source (read by phase inference) |
| `rlm_adk/skills/polya_understand_t2_flat.py` | T2 skill source (read by phase inference) |
| `rlm_adk/skills/polya_understand_t3_adaptive.py` | T3 skill source (read by phase inference) |
| `rlm_adk/skills/polya_understand_t4_debate.py` | T4 skill source (read by phase inference) |
| `rlm_adk_docs/observability.md` (sections 8, 8.1) | Worker obs path + cumulative keys documentation |
| `rlm_adk_docs/testing.md` (lines 44-185) | ContractResult + fixture schema documentation |
