# Devil's Advocate Review: Observability-Enriched Benchmark Evaluation for Polya Understand Skills

## Reference Key

| Prefix | Section | Source |
|--------|---------|--------|
| A | ADK Callback Opportunities | ADK Callback Expert |
| V | Vision Alignment Recommendations | Vision Alignment Challenger |
| P | Prior Art Findings | Prior-Art Researcher |
| X | Cross-Cutting Themes | Synthesis (multi-critic) |
| R | Prioritized Recommendations | Synthesis (all critics) |

> **Usage:** Reference any finding by its ID (e.g., "implement A2, V1, and R3") to direct follow-up work.

---

## ADK Callback Opportunities

The proposal describes five teammates producing design documents, but never asks whether ADK's callback and plugin system could *be* the evaluation infrastructure rather than a separate "ProcessEvaluator" component bolted on afterward. Several concrete callback under-utilizations follow.

### A1. ProcessEvaluator as a BasePlugin, not a standalone component

- **What the plan does now** -- Step 3 designs a `ProcessEvaluator` component that "takes a `PluginContractResult`" and "queries `traces.db` for the telemetry and session_state_events tables" post-hoc. This is a separate, offline analysis step that runs after the agent has finished.
- **What ADK callback/plugin could replace it** -- A `BenchmarkEvaluationPlugin` extending `BasePlugin` could implement `after_tool_callback` (to score each REPL execution as it happens), `after_model_callback` (to evaluate reasoning quality per-step), and `after_run_callback` (to compute the final `ProcessScore`). Because plugins fire globally for all agents added to the Runner, this would capture evaluation signals in real-time during the benchmark run itself -- no post-hoc SQLite querying needed.
- **Benefit** -- Real-time scoring eliminates the need for a separate evaluation pass. The plugin's `after_run_callback` can write the `ProcessScore` directly to state via `callback_context.state`, making it available in the same `PluginContractResult` that `check_expectations()` already validates. This also means `expected_process` fixture assertions can use the existing matcher operator infrastructure (`$gt`, `$gte`, etc.) without schema extensions.

### A2. Behavioral indicator detection via before_model_callback

- **What the plan does now** -- Step 2 (Polya-Phase-Analyst) proposes defining "trace patterns that indicate *reward hacking*" (e.g., agent produces SUFFICIENT without dispatching investigators) and "trace patterns that indicate *shallow understanding*." These are described as post-hoc trace analysis rules.
- **What ADK callback/plugin could replace it** -- A `before_model_callback` on the reasoning agent can inspect `callback_context.state` for dispatch metrics (`obs:child_dispatch_count`, `obs:child_dispatch_count_total`) *before* the model produces its next response. If the model is about to emit a final verdict but cumulative dispatch count is zero, the callback can inject a system instruction warning ("You have not dispatched any investigators yet -- are you sure you have enough evidence?") or even short-circuit by returning a `Content` that forces the model to explain its reasoning before proceeding.
- **Benefit** -- This transforms passive "detect bad behavior after the fact" into active "prevent bad behavior as it happens." The same behavioral indicators become both evaluation metrics AND runtime guardrails, reusable across production runs and benchmarks.

### A3. Per-topology scoring via before_agent_callback with conditional skip

- **What the plan does now** -- Step 2 proposes "a scoring rubric per topology with specific telemetry thresholds." The plan assumes these rubrics are applied post-hoc by the evaluator.
- **What ADK callback/plugin could replace it** -- A `before_agent_callback` can read the active skill instruction from `DYN_SKILL_INSTRUCTION` state key to determine which topology (T1-T4) is running. It can then load the topology-specific rubric and attach it to the plugin instance for use in subsequent `after_tool_callback` and `after_model_callback` invocations. This gives the evaluation plugin topology-awareness without the evaluator needing to infer topology from traces after the fact.
- **Benefit** -- The evaluation plugin *knows* the topology at runtime rather than inferring it from trace patterns. This eliminates an entire class of "topology detection" logic that the Benchmark-Evaluator-Architect would otherwise have to build.

### A4. Data flow edge detection is already a callback opportunity

- **What the plan does now** -- Step 4 (Data-Flow-Storyteller) proposes a `TraceNarrative` builder that "uses `data_flow_edges` to show information flow." The `DataFlowTracker` already detects these edges, but only at trace level >= 1.
- **What ADK callback/plugin could replace it** -- The existing `after_tool_callback` in `SqliteTracingPlugin` already extracts REPL enrichment data including `repl_trace_summary` which embeds `data_flow_edges`. Rather than building a new narrative builder that re-parses this data, the evaluation plugin's `after_tool_callback` could consume these edges in real-time, maintaining a running narrative graph as an instance variable. The `after_run_callback` then serializes this graph as the `TraceNarrative`.
- **Benefit** -- No new data capture needed. The narrative is built incrementally during execution rather than reconstructed from cold storage. This also means the narrative is available for the interactive dashboard (vision alignment, see V4) in real-time.

### A5. on_event_callback for real-time process scoring

- **What the plan does now** -- The plan proposes that the evaluator queries `session_state_events` post-hoc to reconstruct the agent's state trajectory.
- **What ADK callback/plugin could replace it** -- `on_event_callback` fires on every state-delta event. An evaluation plugin implementing this hook can maintain a running score, updating dimensions (coverage_thoroughness, question_quality, synthesis_depth, iterative_refinement, appropriate_tool_use) as each relevant state key changes. For example, when `obs:child_dispatch_count` changes, increment the `coverage_thoroughness` dimension; when `obs:child_error_counts` changes, adjust the `appropriate_tool_use` dimension.
- **Benefit** -- The process score is always current. If combined with the interactive dashboard (V4), this enables live process-quality visualization during benchmark runs -- you can watch the score change as the agent works.

### A6. Fixture schema extension is unnecessary for process assertions

- **What the plan does now** -- Step 3 proposes "fixture schema extensions needed (e.g., `expected_process` section in fixture JSON)."
- **What ADK callback/plugin could replace it** -- If the evaluation plugin writes its `ProcessScore` dimensions to `callback_context.state` with `obs:process_*` prefixed keys, then the *existing* `expected_state` fixture mechanism already supports process assertions. For example: `"expected_state": {"obs:process_coverage_thoroughness": {"$gte": 0.7}}`. The existing `_match_value()` infrastructure handles this without any schema changes.
- **Benefit** -- Zero schema migration. Zero new matcher code. The existing fixture format and `check_expectations()` flow work unchanged. This is a significant simplification.

**Confidence rating:** **Significant restructuring opportunity.** The plan's central architecture -- a separate post-hoc ProcessEvaluator -- is the wrong abstraction for a system that already has a rich real-time plugin/callback pipeline. Re-architecting around a `BenchmarkEvaluationPlugin` would eliminate roughly half the proposed new components (ProcessEvaluator, TraceNarrative builder as standalone, fixture schema extensions) and integrate naturally with the existing contract runner and dashboard.

---

## Vision Alignment Assessment

| Vision Area | Alignment | Assessment |
|-------------|-----------|------------|
| Polya Topology | **Advances** | Directly evaluates Polya understand topology effectiveness; per-topology rubrics will provide the signal needed for topology optimization. |
| Dynamic Skill Loading | **Neutral** | The plan does not address how process evaluation results feed back into skill embedding metadata or future retrieval weighting. |
| Continuous Runtime | **Neutral** | No connection to cron-triggered autonomous evaluation or gap audit automation. |
| Interactive Dashboard | **Partially Advances** | The plan mentions "markdown output suitable for benchmark reports" but does not leverage the NiceGUI studio shell or live visualization. |

### V1. Feed process scores into dynamic skill loading embeddings

The dynamic skill loading vision (`rlm_adk_docs/vision/dynamic_skill_loading/dynamic_skill_loading.md`) specifies an embedding metadata schema that includes `execution_outcome` (success/error/partial). The proposal's `ProcessScore` dimensions (coverage_thoroughness, synthesis_depth, etc.) are strictly richer signals than binary success/error. If process scores are captured as part of the embedding metadata, future skill retrieval can prefer not just "successful executions" but "executions that demonstrated thorough understanding." This is a direct improvement to the dynamic skill loading pipeline and costs nothing extra if the evaluation plugin already computes the score.

**Concrete change:** Add `process_score: dict[str, float]` to the planned embedding metadata schema. Wire the evaluation plugin's `after_run_callback` to persist process dimensions alongside the existing `execution_outcome` field.

### V2. Connect to continuous runtime gap audit

The autonomous self-improvement vision (`autonomous_self_improvement.md`) describes a "Gap Audit" cron task that scans for open observability/test gaps. The proposal designs a rich evaluation framework but never addresses how its results feed the gap registry. If benchmark process scores consistently show T3 underperforming on `iterative_refinement` (e.g., it never triggers round 2 re-probing), that should automatically create a gap entry.

**Concrete change:** Add a phase 3.5 to the implementation plan: wire process score thresholds to gap registry entries. A topology that scores below threshold on any ProcessScore dimension for 3+ consecutive benchmark runs creates an auto-generated gap.

### V3. The TraceNarrative is the wrong output format for the dashboard

The plan proposes TraceNarrative producing "markdown output suitable for benchmark reports." But the interactive dashboard vision (`interactive_dashboard.md`) specifies a NiceGUI studio shell with "direct manipulation of live Python objects" and "time-scrubbing the agent's process." Markdown is the wrong substrate. The narrative data structure should be a typed Python dataclass (or Pydantic model) with temporal ordering, so the dashboard can bind `ui.slider()` to the narrative timeline and render each step interactively.

**Concrete change:** Design `TraceNarrative` as a Pydantic model with `steps: list[NarrativeStep]` where each step has `timestamp`, `event_type`, `data_flow_edges`, `score_snapshot`. The markdown rendering becomes a `.to_markdown()` method -- one of many possible views, not the primary representation.

### V4. Live process scoring enables "Inventing on Principle" for benchmarks

Bret Victor's core principle -- "creators need an immediate connection to what they are creating" -- applies directly to benchmark development. Currently, you run a benchmark, wait for it to finish, then read a report. If the evaluation plugin computes process scores in real-time (see A5), and the dashboard can bind to those scores, then benchmark development becomes interactive: you watch the process score change as the agent runs, you see *when* it drops, you scrub back to that moment, and you understand *why*.

**Concrete change:** Ensure the evaluation plugin writes score snapshots to a state key (e.g., `obs:process_score_snapshot`) at each callback invocation. The live dashboard's `LiveDashboardLoader` can poll this key alongside existing trace data.

### V5. The Codex proposal's "Capture Mode" should consume process scores

The dynamic skill loading codex proposal reframed (`codex_proposal_reframed.md`) describes a Capture Mode that "transforms a live successful session into a workflow topology artifact." The "success gate" currently uses blunt signals (non-error completion, acceptable finish reason). Process scores would give the Capture Mode gate a much richer success signal: only promote topologies whose process evaluation exceeds thresholds on all five dimensions.

**Concrete change:** Add process score thresholds to the Capture Mode "Detect" phase gating criteria. A topology is "promotion-eligible" only if `coverage_thoroughness >= 0.7 AND synthesis_depth >= 0.6 AND iterative_refinement >= 0.5`.

**Overall verdict:** This plan is **partially aligned** with the project vision because it focuses exclusively on evaluation-as-measurement while the vision calls for evaluation-as-feedback-signal. The process scores this plan would generate are exactly what dynamic skill loading, continuous runtime, and topology optimization need -- but the plan never connects the dots.

---

## Prior Art Findings

The plan proposes building five core capabilities. Here is what already exists for each.

### P1. Trace-based process quality scoring (ProcessEvaluator)

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| DeepEval | [deepeval.com/docs/metrics-step-efficiency](https://deepeval.com/docs/metrics-step-efficiency) | `StepEfficiencyMetric` evaluates whether an agent completes tasks without unnecessary steps by analyzing the full execution trace. Also provides `PlanAdherenceMetric` for plan-following assessment. | **High** | Adapt concepts; their trace schema differs from ADK's but the scoring rubric patterns (LLM-as-judge on traces) are directly portable. |
| MAESTRO (arXiv 2601.00481) | [arxiv.org/abs/2601.00481](https://arxiv.org/abs/2601.00481) | Multi-agent evaluation suite that exports framework-agnostic execution traces and measures cost-latency-accuracy trade-offs. Addresses retry logic, failure categorization, and output quality. | **Medium** | Study their trace export format for cross-framework compatibility ideas. Their finding that "MAS architecture is the dominant driver of resource profiles" validates per-topology rubrics. |
| Opik (Comet ML) | [github.com/comet-ml/opik](https://github.com/comet-ml/opik) | Open-source platform with tracing, automated evaluations, and production-ready dashboards. Captures spans and traces for post-hoc analysis. | **Medium** | Their evaluator pipeline (trace -> metric computation -> dashboard) is architecturally similar to what the plan proposes. Review their evaluator plugin API. |
| AgentBoard (T-Eval) | [arxiv.org/html/2507.21504v1](https://arxiv.org/html/2507.21504v1) | Proposes "Progress Rate" metric comparing agent trajectory against expected trajectory. Captures per-step alignment scoring. | **Medium** | The "Progress Rate" concept maps well to `coverage_thoroughness` -- how much of the expected investigation the agent actually performed. |

**Assessment:** 4 of 4 surveyed tools provide trace-based process scoring. None of them operate within the ADK callback/plugin system, so direct library adoption is not possible. However, the *scoring patterns* (step efficiency, plan adherence, progress rate) are well-established and should inform the rubric design rather than being reinvented.

### P2. Behavioral indicator detection (Polya-Phase-Analyst rubrics)

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| MMAR-Rubrics (Interspeech 2026) | [arxiv.org/html/2602.14224v1](https://arxiv.org/html/2602.14224v1) | Instance-level protocol for assessing factuality and logic of reasoning chains. Novel rubric for evaluating *process* rigor, not just output accuracy. | **Medium** | Directly relevant rubric methodology for scoring Chain-of-Thought quality. Their rubric design process (criteria -> scoring levels -> inter-annotator agreement) should be studied before building per-topology rubrics. |
| DeepEval Agent Metrics | [deepeval.com/guides/guides-ai-agent-evaluation-metrics](https://deepeval.com/guides/guides-ai-agent-evaluation-metrics) | Comprehensive metric taxonomy: task success, trajectory correctness, tool correctness, plan quality, plan adherence. Applied at both session and node level. | **High** | Their metric taxonomy is more mature than what the plan proposes. The five ProcessScore dimensions (coverage_thoroughness, question_quality, synthesis_depth, iterative_refinement, appropriate_tool_use) should be validated against DeepEval's taxonomy to avoid reinventing inferior versions. |

**Assessment:** The behavioral indicator work has substantial prior art. The specific innovation in the proposal -- topology-specific rubrics tied to Polya understand dimensions -- does not exist in the literature and is genuinely novel. But the *rubric framework* should be informed by MMAR-Rubrics methodology.

### P3. Trace narrative reconstruction (Data-Flow-Storyteller)

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| Langfuse | [langfuse.com/blog/2024-07-ai-agent-observability-with-langfuse](https://langfuse.com/blog/2024-07-ai-agent-observability-with-langfuse) | Trace visualization with nested span trees, timing waterfall charts, and cost attribution. Already integrated with RLM-ADK via LangfuseTracingPlugin. | **Medium** | Langfuse already renders execution traces as visual narratives. The plan should consider whether TraceNarrative *duplicates* what Langfuse already provides, or whether it adds genuinely new value (Polya-specific narrative framing). |
| OpenLLMetry | [github.com/traceloop/openllmetry](https://github.com/traceloop/openllmetry) | OpenTelemetry-based observability for GenAI. Exports traces in standard OTel format compatible with Datadog, Honeycomb, etc. | **Low** | Different architectural approach (OTel spans vs. SQLite tables). Not directly useful but validates the industry direction toward structured trace export. |

**Assessment:** Trace narrative reconstruction is partially covered by existing tools (Langfuse already provides visual trace narratives). The novel contribution is *Polya-specific narrative framing* -- "the agent selected dimensions X and Y, probed them, found gaps in Y, re-probed with sharpened questions" is not something Langfuse can generate. But the raw trace visualization is a solved problem.

### P4. LLM-as-judge for narrative scoring

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| DeepEval G-Eval | [deepeval.com/docs/metrics-llm-evals](https://deepeval.com/docs/metrics-llm-evals) | G-Eval metric uses LLM-as-judge with chain-of-thought scoring. Provides structured evaluation of text quality with calibrated scores. | **High** | The plan proposes "a judge LLM evaluator (an `llm_query()` call within the benchmark)." G-Eval is exactly this pattern, already implemented and validated. Consider whether DeepEval's G-Eval can be wrapped rather than reimplemented. |
| LangSmith Evaluators | [langchain.com/langsmith/observability](https://www.langchain.com/langsmith/observability) | Built-in LLM-as-judge evaluators for scoring production traces on factuality, schema compliance, and custom criteria. | **Medium** | Validates the approach but locked to LangChain ecosystem. |

**Assessment:** LLM-as-judge scoring is a well-solved problem. The plan's consideration section already flags API cost concerns. The recommendation is clear: use deterministic rubrics for the five ProcessScore dimensions (these are numeric/structural checks on trace data) and reserve LLM-as-judge *only* for the narrative quality assessment where deterministic scoring is insufficient.

### P5. Telemetry gap analysis (Telemetry-Mapper)

| Source | URL | What It Does | Coverage | Recommendation |
|--------|-----|-------------|----------|----------------|
| NIKA (Network Arena) | [arxiv.org/html/2512.16381v1](https://arxiv.org/html/2512.16381v1) | Adopts OTel formats to integrate observability with agent reasoning traces. Released 900+ reasoning traces as public dataset. | **Low** | Different domain (network troubleshooting) but their approach of systematically mapping telemetry signals to reasoning behaviors is exactly what the Telemetry-Mapper teammate would do. |

**Assessment:** Telemetry gap analysis for a custom agent framework is inherently bespoke. No prior art covers RLM-ADK's specific telemetry signals. This capability genuinely needs custom development. However, the *methodology* of systematic signal-to-behavior mapping is documented in NIKA and should be referenced.

**Summary:** 3 of 5 planned capabilities have substantial prior art that could save development time. The two genuinely novel contributions are (1) Polya-topology-specific behavioral rubrics and (2) telemetry gap analysis for RLM-ADK's specific observability stack.

---

## Cross-Cutting Themes

### X1. Post-hoc evaluation is the wrong architecture for a callback-rich system (flagged by: A1, A5, A6, P1)

The proposal's central design decision -- build a `ProcessEvaluator` that queries `traces.db` after the run completes -- ignores that RLM-ADK already has a mature real-time callback/plugin system that fires on every model call, tool invocation, and state change. Multiple critics converge on this: the ADK callback expert identifies six specific hooks that could provide real-time scoring (A1-A6); the prior art researcher notes that modern evaluation frameworks (DeepEval, Opik) are moving toward trace-level evaluation during execution, not after; and the plan's own acknowledgment that "existing telemetry is rich" argues for consumption at the callback level rather than post-hoc SQL queries. This is the highest-confidence finding in the review.

### X2. Five teammates is over-scoped for a design phase (flagged by: A1, A6, P3, P4)

The plan spawns five specialized teammates, but the findings suggest significant overlap:
- The Telemetry-Mapper (step 1) catalogs signals that the evaluation plugin would consume in callbacks -- this is implementation design, not separate research.
- The Data-Flow-Storyteller (step 4) builds a narrative that Langfuse already partially provides (P3), and that a plugin's `after_tool_callback` can construct incrementally (A4).
- The Integration-Synthesizer (step 5) reconciles four proposals into one -- but if the architecture is "one BenchmarkEvaluationPlugin," there is far less to reconcile.

A more efficient decomposition: (1) one teammate designs the BenchmarkEvaluationPlugin with per-topology rubrics, (2) one teammate defines the rubrics themselves using Polya methodology, (3) one teammate handles fixture integration and TDD sequence. Three teammates, not five.

### X3. The plan disconnects evaluation from the feedback loops it should feed (flagged by: V1, V2, V5)

Three separate vision alignment findings identify the same gap: the plan generates rich process quality signals but never connects them to downstream consumers. Dynamic skill loading needs process scores in embedding metadata (V1). Continuous runtime needs process thresholds to trigger gap audits (V2). Capture Mode needs process scores for promotion gating (V5). The plan treats evaluation as a terminal output ("produce a ProcessScore"), but the project vision treats evaluation as a feedback signal that drives system evolution. This is a strategic misalignment, not a technical one.

### X4. Judge LLM cost is a real concern but deterministic scoring is underexplored (flagged by: A2, P2, P4)

The plan's considerations section flags "Judge LLM evaluator cost" and asks "whether a deterministic rubric can substitute for most cases." The prior art strongly suggests yes: DeepEval's StepEfficiencyMetric and PlanAdherenceMetric are LLM-as-judge, but the metrics they evaluate (did the agent take unnecessary steps? did it follow its plan?) can largely be answered by the structural trace data RLM-ADK already captures. If `obs:child_dispatch_count_total` is zero when the agent claims SUFFICIENT, that is a deterministic check -- no judge LLM needed. Reserve LLM-as-judge for the one dimension that resists deterministic scoring: `question_quality` (evaluating whether the probing questions were well-formulated).

---

## Prioritized Recommendations

### R1. Replace ProcessEvaluator with a BenchmarkEvaluationPlugin

**Traces to:** A1, A5, A6, X1, P1

Redesign the core architecture. Instead of a standalone `ProcessEvaluator` that queries `traces.db` post-hoc, implement a `BenchmarkEvaluationPlugin(BasePlugin)` that computes process scores in real-time via `after_model_callback`, `after_tool_callback`, and `on_event_callback`. Write score dimensions to `callback_context.state` with `obs:process_*` keys. Assert on them in fixtures using the existing `expected_state` mechanism with matcher operators. This eliminates the need for fixture schema extensions, a separate evaluator component, and post-hoc SQL queries. It is the single highest-impact change because it simplifies the architecture from five new components to one.

### R2. Reduce from five teammates to three

**Traces to:** X2, A1, P3

The five-teammate decomposition produces overlapping work and an unnecessary integration step. Consolidate to: (1) **Plugin Architect** -- designs the BenchmarkEvaluationPlugin, its callback hooks, and how it integrates with the contract runner; (2) **Rubric Designer** -- defines per-topology behavioral indicators using Polya methodology, informed by DeepEval's metric taxonomy and MMAR-Rubrics methodology; (3) **Fixture Engineer** -- designs the TDD sequence, fixture extensions (using existing `expected_state`, not new schema), and the phased implementation plan. The Data-Flow-Storyteller's work becomes a method on the plugin. The Integration-Synthesizer is unnecessary when the architecture is one plugin.

### R3. Use deterministic scoring for 4 of 5 ProcessScore dimensions

**Traces to:** X4, P4, A2

Define deterministic rules for `coverage_thoroughness` (dispatch count vs expected), `synthesis_depth` (synthesizer dispatch presence), `iterative_refinement` (round-2 re-probe detection via batch count), and `appropriate_tool_use` (error count thresholds). Reserve LLM-as-judge exclusively for `question_quality`, which requires semantic evaluation of probe question formulation. This reduces benchmark API cost by roughly 80% compared to using LLM-as-judge for all five dimensions, and makes 4 of 5 dimensions fully deterministic and reproducible.

### R4. Wire process scores to vision feedback loops

**Traces to:** X3, V1, V2, V5

Add process score fields to the dynamic skill loading embedding metadata schema. Wire process score thresholds to the gap registry (auto-create gaps when topology scores below threshold for N consecutive runs). Add process score thresholds to Capture Mode promotion gates. This is not implementation work for this phase -- but the *data structure design* must accommodate these downstream consumers now, or a costly refactor will be needed later. Specifically: design `ProcessScore` as a Pydantic model with serialization to both state keys and embedding metadata.

### R5. Design TraceNarrative as a Pydantic model, not markdown

**Traces to:** V3, V4, A4

The TraceNarrative should be a typed `Pydantic BaseModel` with `steps: list[NarrativeStep]`, where each step carries `timestamp`, `event_type`, `topology`, `data_flow_edges`, and `score_snapshot`. The markdown representation becomes `.to_markdown()` -- one view among many. This ensures the dashboard can bind to the narrative timeline for interactive "time-scrubbing" (Bret Victor principle), and the same data structure serves benchmark reports, dashboard visualization, and future Capture Mode analysis.

### R6. Study DeepEval and MMAR-Rubrics before designing rubrics

**Traces to:** P2, P4, X4

Before the Rubric Designer begins work, they should study: (1) DeepEval's agent evaluation metric taxonomy (StepEfficiency, PlanAdherence, ToolCorrectness, TaskSuccess, TrajectoryCorrectness) to validate that the five proposed ProcessScore dimensions are not reinventing inferior versions; (2) MMAR-Rubrics' instance-level scoring protocol (criteria definition, scoring levels, inter-annotator agreement) to adopt a validated rubric design methodology. This is a few hours of research that prevents weeks of rubric redesign.

### R7. Leverage existing Langfuse integration before building narrative visualization

**Traces to:** P3, V4

RLM-ADK already has `LangfuseTracingPlugin` integrated. Before investing in custom narrative visualization, verify what Langfuse's trace UI already provides for Polya understand runs. If it already shows the dispatch fan-out, timing waterfall, and error paths, then the TraceNarrative builder should focus exclusively on the Polya-specific semantic layer (dimension selection narrative, gap-detection narrative, re-probe narrative) that Langfuse cannot provide. Do not rebuild general trace visualization.

---

## Sources

- [DeepEval - The LLM Evaluation Framework](https://github.com/confident-ai/deepeval)
- [DeepEval Step Efficiency Metric](https://deepeval.com/docs/metrics-step-efficiency)
- [DeepEval Agent Evaluation Metrics](https://deepeval.com/guides/guides-ai-agent-evaluation-metrics)
- [DeepEval G-Eval (LLM-as-Judge)](https://deepeval.com/docs/metrics-llm-evals)
- [MAESTRO: Multi-Agent Evaluation Suite (arXiv 2601.00481)](https://arxiv.org/abs/2601.00481)
- [Evaluation and Benchmarking of LLM Agents: A Survey (arXiv 2507.21504)](https://arxiv.org/html/2507.21504v1)
- [MMAR-Rubrics: Evaluating Reasoning Process Quality (arXiv 2602.14224)](https://arxiv.org/html/2602.14224v1)
- [NIKA: Network Arena with OTel Reasoning Traces (arXiv 2512.16381)](https://arxiv.org/html/2512.16381v1)
- [Opik: LLM Tracing and Evaluation Platform](https://github.com/comet-ml/opik)
- [OpenLLMetry: OpenTelemetry for GenAI](https://github.com/traceloop/openllmetry)
- [Langfuse: AI Agent Observability](https://langfuse.com/blog/2024-07-ai-agent-observability-with-langfuse)
- [LangSmith: LLM Observability Platform](https://www.langchain.com/langsmith/observability)
- [AgentBench: Comprehensive LLM Agent Benchmark](https://github.com/THUDM/AgentBench)
- [Evaluating Agent Systems (Trilogy AI Substack)](https://trilogyai.substack.com/p/evaluating-agent-systems-and-human)
- [AI Agent Benchmarks are Broken (Daniel Kang Substack)](https://ddkang.substack.com/p/ai-agent-benchmarks-are-broken)
