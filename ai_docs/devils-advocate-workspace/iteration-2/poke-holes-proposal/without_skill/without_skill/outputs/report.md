# Devil's Advocate Review: design_observability_enriched_benchmark_evaluation.md

## Verdict: Overcomplicated in structure, under-leveraging what already exists

The plan proposes five agent teammates producing five design documents to answer a question that the existing infrastructure is 80% ready to answer with direct code changes. The ratio of design ceremony to implementation complexity is inverted. Below are the specific holes, organized by the two questions you asked: overcomplexity and missed callback opportunities.

---

## Part 1: Where the plan overcomplicates things

### 1.1 Five teammates for a two-component problem

The plan spawns five agent teammates (Telemetry-Mapper, Polya-Phase-Analyst, Benchmark-Evaluator-Architect, Data-Flow-Storyteller, Integration-Synthesizer). The actual deliverable is two things:

1. A `ProcessEvaluator` that reads `PluginContractResult` and scores process quality.
2. Fixture schema extensions (`expected_process` in JSON) to assert against those scores.

The Telemetry-Mapper (step 1) and Data-Flow-Storyteller (step 4) are research tasks that produce catalogs and narrative builders, but neither is a prerequisite for the evaluator. You can build the evaluator directly by querying `traces.db` -- the telemetry schema is already documented in `sqlite_tracing.py` lines 258-294. The "telemetry gap" analysis is valuable but can be done incrementally as you discover what the evaluator actually needs, rather than cataloging everything upfront.

**Actionable alternative:** Collapse steps 1, 3, and 5 into a single implementation task: build `ProcessEvaluator` that queries `traces.db`, wire it into `check_expectations()`, and extend the fixture schema. Do the telemetry catalog (step 1) and narrative builder (step 4) as follow-on features only if the evaluator reveals gaps.

### 1.2 The TraceNarrative is a feature, not a prerequisite

Step 4 proposes a `TraceNarrative` data structure, a chronological reconstruction builder, and a judge LLM evaluator -- all before any scoring rubric exists. This is premature. You do not need a human-readable narrative to score process quality. The `telemetry` table already stores chronological rows with `start_time`, `duration_ms`, `repl_llm_calls`, `repl_trace_summary`, and `skill_instruction`. A `ProcessEvaluator` can query these rows directly with SQL.

The plan even acknowledges this risk in the Considerations section ("Judge LLM evaluator cost... consider whether a deterministic rubric can substitute for most cases") but then still proposes building the narrative system in Phase 3. If deterministic rubrics handle most cases, the narrative builder may never be needed.

### 1.3 The scoring rubric is topology-specific but the infrastructure is topology-agnostic

The plan asks step 2 to define per-topology behavioral indicators (T1 should show X, T3 should show Y, T4 should show Z). But the telemetry infrastructure (`telemetry` table, `session_state_events`, `repl_trace_summary`) captures data identically regardless of topology. The topology is just a string in `skill_instruction`.

This means the "Polya-Phase-Analyst" teammate needs to produce something the evaluator can use: a configuration object mapping topology -> scoring thresholds. That is a JSON file, not a design document. The plan asks for a design document that proposes "measurable behavioral indicators derived from traces" -- but the indicators are straightforward reads from existing state keys:

- `obs:child_dispatch_count_total` -- how many children were dispatched
- `obs:child_total_batch_dispatches` -- how many batch rounds occurred (T3's re-probe shows as 2+)
- `data_flow_edges` in `repl_trace_summary` -- whether child responses fed into subsequent prompts
- `repl_llm_calls` per tool call row -- how many LLM calls per REPL execution

These are already captured. The "research" is reading 4 skill files and writing a JSON config. A design document phase for this is overhead.

### 1.4 Three-phase implementation plan for a single-phase problem

The proposed phases are:
- Phase 1: Telemetry gap fills + ProcessEvaluator skeleton
- Phase 2: Per-topology scoring rubrics + fixture schema extensions
- Phase 3: TraceNarrative builder + judge LLM integration

Phases 1 and 2 are inseparable in practice -- you cannot test the ProcessEvaluator skeleton without at least one scoring rubric, and you cannot validate the rubric without the evaluator running. This should be one phase. Phase 3 (narrative + LLM judge) should be a separate, optional project, not a phase of this one.

---

## Part 2: Missed callback opportunities

### 2.1 `after_tool_callback` already captures everything the evaluator needs

The plan does not mention that `SqliteTracingPlugin.after_tool_callback` (line 1021) already writes rich REPL telemetry to the `telemetry` table for every `execute_code` call:
- `repl_has_errors`, `repl_has_output`, `repl_llm_calls`
- `repl_trace_summary` (full JSON including `data_flow_edges`, `llm_call_count`, `wall_time_ms`)
- `repl_stdout`, `repl_stderr`, `repl_stdout_len`, `repl_stderr_len`
- `skill_instruction` (which topology was active)
- `result_payload` (full tool result JSON)

The `ProcessEvaluator` could be implemented as a pure SQL query against the `telemetry` table with no new callbacks at all. The plan's step 1 (Telemetry-Mapper) is essentially re-discovering what `after_tool_callback` already captures.

### 2.2 `on_event_callback` in SqliteTracingPlugin captures all state deltas -- use it

`SqliteTracingPlugin.on_event_callback` (line 1096) writes every `state_delta` key to `session_state_events`. This means the entire dispatch accumulator flush (`obs:child_dispatch_count`, `obs:child_error_counts`, `obs:child_dispatch_latency_ms`, `obs:child_total_batch_dispatches`, and the cumulative `*_total` variants) is already persisted as individual rows with timestamps and author attribution.

The evaluator can reconstruct the full dispatch timeline by querying:
```sql
SELECT state_key, value_int, value_json, event_time, event_author
FROM session_state_events
WHERE state_key LIKE 'obs:child_%'
ORDER BY seq
```

No new instrumentation is needed for dispatch behavior analysis. The plan does not call this out.

### 2.3 Missing opportunity: `before_tool_callback` for skill-aware tagging

The plan proposes capturing "what tools were used in understanding that context" but misses that `ObservabilityPlugin.before_tool_callback` (line 254) already maintains `OBS_TOOL_INVOCATION_SUMMARY` -- a dict of `{tool_name: count}`. However, this is tool-name-level only (`execute_code`). It does not tag which *skill* was being executed.

The missed opportunity: `REPL_DID_EXPAND` and `REPL_SKILL_EXPANSION_META` are written by `REPLTool.run_async` (line 175-183) *during* tool execution, but they land in `tool_context.state` which fires as a state_delta event *after* the tool completes. A `before_tool_callback` or early `after_tool_callback` on the evaluator plugin could read `tool_args["code"]` and detect skill import lines (`from rlm_repl_skills.polya_understand_t3_adaptive import ...`) to tag the REPL call with its skill topology *before* execution, rather than relying on post-hoc `skill_instruction` matching.

But honestly, `skill_instruction` in the `telemetry` table already captures the active skill at the time of the tool call (written by `SqliteTracingPlugin.before_model_callback` line 851 and propagated through state). So even this "missed" callback is already covered -- just not by the mechanism the plan envisions.

### 2.4 Missing opportunity: `after_run_callback` for aggregate process scoring

The plan proposes a standalone `ProcessEvaluator` component that runs after the fixture completes. But `BasePlugin.after_run_callback` fires at the end of every run and has access to `invocation_context` (including `session.state` and `artifact_service`). A `ProcessScoringPlugin` could:

1. Query the `traces.db` from `after_run_callback` (the DB path is known to the plugin)
2. Compute the `ProcessScore` dimensions
3. Save the score as a JSON artifact via `artifact_service`

This would make process scoring automatic for every run (including non-benchmark runs), not just benchmark fixture runs. The plan treats process evaluation as a test-only concern, but the callback infrastructure supports making it a runtime feature.

### 2.5 Missing opportunity: leverage `PluginContractResult.events` directly

`PluginContractResult` already contains the full `events` list (line 94 of `contract_runner.py`). The `_extract_event_parts()` function (line 540 of `fixtures.py`) already normalizes these into a structured list of `function_call`, `function_response`, and `text` parts with event indices.

The evaluator could work entirely from `events` without touching `traces.db` at all:
- Count `function_call` parts where `name == "execute_code"` -> number of REPL iterations
- Extract `function_response` results -> parse `total_llm_calls`, `has_errors`, `trace_summary`
- Look at `state_delta` on events -> extract `obs:child_*` keys

This is simpler than querying SQLite and does not require `SqliteTracingPlugin` to be enabled. The plan's evaluator design (step 3) couples itself to `traces_db_path` unnecessarily. The `events` list is always available; `traces_db_path` is optional.

### 2.6 `check_expectations()` already supports `expected_state` -- extend it, don't replace it

The plan proposes new fixture schema extensions (`expected_process` section). But `check_expectations()` already supports `expected_state` with rich matching operators (line 472-494 of `fixtures.py`). You can already assert:

```json
{
  "expected_state": {
    "obs:child_dispatch_count_total": {"$gte": 3},
    "obs:child_total_batch_dispatches": {"$gte": 2}
  }
}
```

This is process evaluation -- asserting that the agent dispatched at least 3 children across at least 2 batch rounds. The plan does not acknowledge that `expected_state` with matcher operators already provides a simple, working process assertion mechanism. Many of the "process quality" checks could be expressed as `expected_state` matchers today with zero new code.

The gap is computed dimensions (e.g., "ratio of re-probes to initial probes" or "data flow edge density") that require arithmetic over multiple state keys. *That* requires a `ProcessEvaluator` -- but the scope is much narrower than the plan suggests.

---

## Part 3: Specific risks and contradictions

### 3.1 The plan contradicts itself on code changes

The plan says "No code changes in this phase" (Considerations) but then asks step 3 to "Design a ProcessEvaluator component" with specific return types, integration points, and fixture schema extensions. This is implementation design, not research. If the design is specific enough to define `ProcessScore` fields and `check_expectations()` integration, it is specific enough to implement directly. The "design phase" creates a document that needs to be translated into code -- adding a translation step between design and implementation that introduces drift.

### 3.2 LLM judge evaluator is a cost/reliability liability

Step 4 proposes "scored by a judge LLM evaluator (an `llm_query()` call within the benchmark)." This means every benchmark run now requires a live LLM API call for *evaluation*, not just for the agent under test. This:
- Breaks determinism (provider-fake fixtures are deterministic; LLM judge is not)
- Adds cost per run
- Adds a network dependency to benchmark evaluation
- Creates a recursive problem (how do you evaluate the evaluator?)

The plan's Considerations section flags cost but not determinism or the recursive evaluation problem.

### 3.3 DataFlowTracker's fingerprinting is too coarse for scoring

The plan relies heavily on `data_flow_edges` from `DataFlowTracker` as evidence of "iterative refinement." But `DataFlowTracker.check_prompt()` (trace.py line 136) uses a naive substring match: it checks if the first 40 characters of a previous response appear in a later prompt. This means:
- Common prefixes (e.g., "Based on the analysis...") trigger false positive edges
- Paraphrased or summarized reuse is invisible (false negatives)
- The edge count is not a reliable quality metric

The plan should acknowledge this limitation and propose improving `DataFlowTracker` before using it as a scoring signal, or use it only as a binary "did chaining occur?" signal rather than a quality dimension.

---

## Summary of recommendations

| Issue | Recommendation |
|-------|---------------|
| 5 teammates, 5 documents | Collapse to 2 tasks: (a) build ProcessEvaluator, (b) write per-topology threshold config |
| TraceNarrative as prerequisite | Defer entirely; score from SQL/events first |
| 3-phase implementation | Single phase: evaluator + fixture extensions + one topology config |
| Telemetry-Mapper research | Skip; `telemetry` table schema + `after_tool_callback` already documents what is captured |
| LLM judge evaluator | Replace with deterministic rubric; add LLM judge only for subjective dimensions that cannot be scored deterministically |
| New fixture schema (`expected_process`) | Start with `expected_state` matchers for simple assertions; add `expected_process` only for computed dimensions |
| DataFlowTracker as scoring signal | Use as binary signal only; do not weight in numeric scores until fingerprinting is improved |
| Evaluate from `traces.db` | Evaluate from `PluginContractResult.events` first (always available); fall back to `traces.db` for richer queries |
| Design-only phase | Implement directly with TDD; the existing test infrastructure (`run_fixture_contract_with_plugins`, `expected_state`) supports iterative development without a separate design phase |
