# Proposal 03: ProcessEvaluator -- Observability-Enriched Benchmark Evaluation

**Author:** Benchmark-Evaluator-Architect teammate
**Date:** 2026-03-18
**Status:** Proposal (no code changes)

---

## Motivation

The existing benchmark infrastructure measures **outcome correctness** via `ContractResult.passed` and `check_expectations()` (in `tests_rlm_adk/provider_fake/fixtures.py`, line 398). It verifies that the agent produced the right final answer, consumed the expected number of model calls, and left the expected state keys behind. What it cannot measure today is **process quality** -- whether the agent's reasoning path was efficient, whether it asked good sub-questions, whether it recovered gracefully from errors, and whether its tool usage was appropriate for the task.

This proposal introduces `ProcessEvaluator`, a post-hoc trace analyzer that reads from the `traces.db` written by `SqliteTracingPlugin` (`rlm_adk/plugins/sqlite_tracing.py`, line 325) and produces a multi-dimensional `ProcessScore` alongside the existing pass/fail verdict.

---

## 1. ProcessEvaluator Component Design

### 1.1 Data Structures

```python
import dataclasses
from typing import Any


@dataclasses.dataclass
class DimensionScore:
    """Score for a single process quality dimension."""
    name: str                  # e.g. "coverage_thoroughness"
    score: float               # 0.0 - 1.0 normalized
    raw_value: float           # the unnormalized metric value
    expected_range: tuple[float, float]  # (min_expected, max_expected)
    detail: str                # human-readable explanation
    checks: list[dict[str, Any]]  # individual sub-checks, same format as ContractResult.checks


@dataclasses.dataclass
class ProcessScore:
    """Multi-dimensional process quality assessment."""
    coverage_thoroughness: DimensionScore
    question_quality: DimensionScore
    synthesis_depth: DimensionScore
    iterative_refinement: DimensionScore
    appropriate_tool_use: DimensionScore

    @property
    def dimensions(self) -> list[DimensionScore]:
        return [
            self.coverage_thoroughness,
            self.question_quality,
            self.synthesis_depth,
            self.iterative_refinement,
            self.appropriate_tool_use,
        ]

    @property
    def composite_score(self) -> float:
        """Weighted average across all dimensions. Default: equal weights."""
        scores = [d.score for d in self.dimensions]
        return sum(scores) / len(scores) if scores else 0.0

    @property
    def passed(self) -> bool:
        """Advisory pass: composite score above threshold."""
        return self.composite_score >= 0.5

    def diagnostics(self) -> str:
        lines = [f"ProcessScore: {self.composite_score:.2f} ({'PASS' if self.passed else 'FAIL'})"]
        for d in self.dimensions:
            lines.append(f"  {d.name}: {d.score:.2f} (raw={d.raw_value:.2f}, "
                         f"range={d.expected_range}) -- {d.detail}")
            for check in d.checks:
                mark = "ok" if check["ok"] else "MISS"
                lines.append(f"    [{mark}] {check['field']}: "
                             f"expected={check['expected']!r} actual={check['actual']!r}")
        return "\n".join(lines)
```

### 1.2 ProcessEvaluator Class Interface

```python
import sqlite3
from pathlib import Path
from tests_rlm_adk.provider_fake.contract_runner import PluginContractResult


class ProcessEvaluator:
    """Evaluates agent process quality from traces.db telemetry.

    Takes a PluginContractResult (which includes traces_db_path, events,
    final_state) and produces a ProcessScore by querying the telemetry
    and session_state_events tables.

    Args:
        result: A PluginContractResult from run_fixture_contract_with_plugins().
        expected_process: Optional dict from fixture JSON's "expected_process"
            section. When None, default rubric thresholds are used.
        topology: Optional string identifying the agent topology for
            topology-specific rubric adjustments ("flat", "recursive",
            "fanout", "debate"). Defaults to auto-detection.
    """

    def __init__(
        self,
        result: PluginContractResult,
        expected_process: dict[str, Any] | None = None,
        topology: str | None = None,
    ):
        self._result = result
        self._expected = expected_process or {}
        self._topology = topology or self._detect_topology()
        self._conn: sqlite3.Connection | None = None
        if result.traces_db_path and Path(result.traces_db_path).exists():
            self._conn = sqlite3.connect(result.traces_db_path)
            self._conn.row_factory = sqlite3.Row

    def evaluate(self) -> ProcessScore:
        """Run all dimension evaluators and return a ProcessScore."""
        return ProcessScore(
            coverage_thoroughness=self._eval_coverage_thoroughness(),
            question_quality=self._eval_question_quality(),
            synthesis_depth=self._eval_synthesis_depth(),
            iterative_refinement=self._eval_iterative_refinement(),
            appropriate_tool_use=self._eval_appropriate_tool_use(),
        )

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- Topology detection ---

    def _detect_topology(self) -> str:
        """Auto-detect topology from final_state dispatch keys."""
        state = self._result.final_state
        dispatch_total = state.get("obs:child_dispatch_count_total", 0)
        batch_total = state.get("obs:child_batch_dispatches_total", 0)
        max_depth = self._max_depth_from_state()

        if dispatch_total == 0:
            return "flat"      # No child dispatches
        if max_depth > 1:
            return "recursive" # Depth > 1 means recursive chains
        if batch_total > 0:
            return "fanout"    # Batch dispatches = parallel fan-out
        return "flat"          # Single-depth single dispatch

    def _max_depth_from_state(self) -> int:
        """Read max depth reached from traces or state."""
        if self._conn:
            row = self._conn.execute(
                "SELECT max_depth_reached FROM traces LIMIT 1"
            ).fetchone()
            if row and row[0] is not None:
                return row[0]
        # Fallback: scan state keys for @dN suffixes
        max_d = 0
        for key in self._result.final_state:
            if "@d" in key:
                try:
                    d = int(key.split("@d")[1].split("f")[0])
                    max_d = max(max_d, d)
                except (ValueError, IndexError):
                    pass
        return max_d

    # --- Dimension evaluators (see Section 4 for SQL queries) ---

    def _eval_coverage_thoroughness(self) -> DimensionScore: ...
    def _eval_question_quality(self) -> DimensionScore: ...
    def _eval_synthesis_depth(self) -> DimensionScore: ...
    def _eval_iterative_refinement(self) -> DimensionScore: ...
    def _eval_appropriate_tool_use(self) -> DimensionScore: ...
```

### 1.3 Dimension Definitions

Each dimension measures a specific aspect of the agent's reasoning process:

**coverage_thoroughness** -- Did the agent ask enough sub-questions to cover the problem space? Measured by: total child dispatches vs expected dispatch count, unique prompt topics vs expected topics, ratio of successful dispatches to total.

**question_quality** -- Were the sub-questions well-formed and distinct? Measured by: prompt length distribution (not too short/repetitive), prompt uniqueness (Jaccard distance between dispatch prompts), absence of verbatim prompt repetition.

**synthesis_depth** -- Did the agent combine child results into a coherent answer? Measured by: data flow edges (from `repl_trace_summary`), final answer length relative to child result count, presence of synthesis code in REPL (JSON parsing, aggregation patterns).

**iterative_refinement** -- Did the agent improve across iterations when errors occurred? Measured by: error recovery rate (errors followed by successful retries), monotonic decrease in stderr across iterations, absence of identical code resubmission after errors.

**appropriate_tool_use** -- Did the agent use the REPL and dispatch tools correctly? Measured by: ratio of execute_code calls to total model calls, absence of unnecessary model calls (text-only responses before final answer), REPL error rate, structured output success rate.

---

## 2. Integration with Existing Infrastructure

### 2.1 Relationship to ContractResult.passed / check_expectations()

`ProcessScore` is **advisory, not blocking**. The existing `ContractResult.passed` verdict (computed by `ScenarioRouter.check_expectations()` at `fixtures.py` line 398) remains the source of truth for pass/fail. Process scores provide supplementary insight.

Rationale: Process quality is subjective and task-dependent. A fixture that tests error recovery (e.g., `repl_error_then_retry.json`) legitimately has a low `appropriate_tool_use` score (because the REPL errors are intentional). Failing the contract on that basis would be wrong.

The integration is strictly additive:

```
ContractResult.passed  =  all outcome checks pass     (unchanged)
ProcessScore.passed    =  composite_score >= 0.5       (advisory)
ProcessScore.composite =  mean of 5 dimension scores   (informational)
```

### 2.2 Extension to PluginContractResult

Add `process_score` as an optional field on `PluginContractResult` (`contract_runner.py`, line 90):

```python
@dataclasses.dataclass
class PluginContractResult:
    contract: ContractResult
    events: list[Any]
    final_state: dict[str, Any]
    artifact_service: BaseArtifactService
    traces_db_path: str | None
    session_db_path: str | None
    artifact_root: str | None
    router: ScenarioRouter
    process_score: ProcessScore | None = None  # NEW
```

### 2.3 Integration Point in the Fixture Runner Pipeline

Process evaluation is a **post-processing step** after the contract check completes. It runs inside `run_fixture_contract_with_plugins()` (`contract_runner.py`, line 360), after line 484 (where `contract = router.check_expectations(...)` is called) and before the `PluginContractResult` is returned at line 486:

```python
# After line 484:
contract = router.check_expectations(final_state, fixture_path, elapsed, ...)

# NEW: Process evaluation (opt-in via fixture's expected_process section)
process_score = None
if router.expected_process and traces_db_path:
    evaluator = ProcessEvaluator(
        result=PluginContractResult(  # partial construction for eval
            contract=contract,
            events=events,
            final_state=final_state,
            artifact_service=artifact_service,
            traces_db_path=traces_db_path,
            session_db_path=session_db_path,
            artifact_root=artifact_root,
            router=router,
        ),
        expected_process=router.expected_process,
    )
    try:
        process_score = evaluator.evaluate()
    finally:
        evaluator.close()

# Line 486 becomes:
return PluginContractResult(
    ...,
    process_score=process_score,
)
```

The `ScenarioRouter` needs a new property to expose the fixture's `expected_process` section. Add to `ScenarioRouter.__init__()` (`fixtures.py`, line 249):

```python
self.expected_process: dict[str, Any] = fixture.get("expected_process", {})
```

### 2.4 Test Consumption Pattern

FMEA test classes and contract tests consume `ProcessScore` as advisory assertions:

```python
class TestReplErrorThenRetry:
    FIXTURE = "repl_error_then_retry"

    async def test_contract(self, fmea_result: PluginContractResult):
        assert fmea_result.contract.passed, fmea_result.contract.diagnostics()

    async def test_process_quality(self, fmea_result: PluginContractResult):
        """Advisory: process score is logged but does not fail the test."""
        ps = fmea_result.process_score
        if ps is not None:
            print(ps.diagnostics())
            # Advisory assertions -- log but do not fail
            assert ps.iterative_refinement.score >= 0.5, (
                f"Advisory: iterative refinement low: {ps.diagnostics()}"
            )
```

---

## 3. Fixture Schema Extensions

### 3.1 The `expected_process` Section

A new top-level key `expected_process` is added to the fixture JSON schema. It is entirely optional -- fixtures without it skip process evaluation entirely (zero overhead).

```json
{
  "scenario_id": "repl_error_then_retry",
  "description": "...",
  "config": { ... },
  "responses": [ ... ],
  "expected": { ... },
  "expected_state": { ... },
  "expected_contract": { ... },

  "expected_process": {
    "topology": "flat",

    "coverage_thoroughness": {
      "expected_dispatch_count": { "$gte": 1 },
      "expected_unique_prompts": { "$gte": 1 },
      "dispatch_success_ratio": { "$gte": 0.5 }
    },

    "question_quality": {
      "min_prompt_length": 10,
      "max_prompt_repetition_ratio": 0.5,
      "expected_unique_ratio": { "$gte": 0.8 }
    },

    "synthesis_depth": {
      "expected_data_flow_edges": { "$gte": 0 },
      "min_final_answer_length": 5,
      "synthesis_code_patterns": ["json.loads", "json.dumps"]
    },

    "iterative_refinement": {
      "expected_error_recovery_rate": { "$gte": 0.5 },
      "max_identical_resubmissions": 0,
      "stderr_decrease_required": true
    },

    "appropriate_tool_use": {
      "expected_repl_ratio": { "$gte": 0.3, "$lte": 1.0 },
      "max_repl_error_rate": { "$lte": 0.5 },
      "max_wasted_model_calls": 1,
      "structured_output_success_rate": { "$gte": 0.8 }
    },

    "weights": {
      "coverage_thoroughness": 1.0,
      "question_quality": 1.0,
      "synthesis_depth": 1.0,
      "iterative_refinement": 2.0,
      "appropriate_tool_use": 1.5
    },

    "pass_threshold": 0.5
  }
}
```

### 3.2 Field Reference

All matcher operators from the existing system (`$gt`, `$gte`, `$lt`, `$lte`, `$not_none`, `$not_empty`, `$contains`, `$type`, etc.) are reused here via `_match_value()` from `fixtures.py` (line 46). No new operators are needed.

**`topology`** -- Optional string. When provided, overrides auto-detection. Valid values: `"flat"`, `"recursive"`, `"fanout"`, `"debate"`. Used to select topology-specific default rubric thresholds.

**`coverage_thoroughness`**:
- `expected_dispatch_count` -- Expected total child dispatches (`obs:child_dispatch_count_total`). Uses matcher operators.
- `expected_unique_prompts` -- Expected count of unique dispatch prompts (distinct `prompt_preview` values in child summary state keys).
- `dispatch_success_ratio` -- Ratio of non-error dispatches to total dispatches.

**`question_quality`**:
- `min_prompt_length` -- Minimum acceptable average prompt length in characters.
- `max_prompt_repetition_ratio` -- Maximum fraction of prompt pairs that are near-duplicates (Jaccard > 0.8).
- `expected_unique_ratio` -- Ratio of unique prompts to total prompts.

**`synthesis_depth`**:
- `expected_data_flow_edges` -- Expected data flow edges from `DataFlowTracker` (stored in `repl_trace_summary`).
- `min_final_answer_length` -- Minimum character length of the final answer.
- `synthesis_code_patterns` -- List of substrings that should appear in submitted REPL code (indicating the agent performed synthesis, not just passthrough).

**`iterative_refinement`**:
- `expected_error_recovery_rate` -- Fraction of errors followed by successful retry.
- `max_identical_resubmissions` -- Maximum count of consecutive identical REPL code submissions (by hash).
- `stderr_decrease_required` -- When true, stderr length must decrease across consecutive iterations that had errors.

**`appropriate_tool_use`**:
- `expected_repl_ratio` -- Ratio of execute_code tool calls to total model calls. Uses matcher operators.
- `max_repl_error_rate` -- Maximum fraction of REPL executions that have errors.
- `max_wasted_model_calls` -- Maximum text-only model responses before the final answer (non-tool, non-final responses).
- `structured_output_success_rate` -- Ratio of successful structured output validations to total attempts.

**`weights`** -- Per-dimension weights for the composite score. Default: all 1.0.

**`pass_threshold`** -- Composite score threshold for the advisory pass. Default: 0.5.

### 3.3 Example Fixture: repl_error_then_retry with expected_process

This extends the existing `repl_error_then_retry.json` fixture (which tests error recovery with 2 iterations, 5 model calls, 2 child dispatches):

```json
{
  "scenario_id": "repl_error_then_retry",
  "description": "...",
  "config": { "model": "gemini-fake", "thinking_budget": 0, "max_iterations": 5, "retry_delay": 0.0 },
  "responses": [ "..." ],
  "expected": {
    "final_answer": "Retry succeeded: alpha-42",
    "total_iterations": 2,
    "total_model_calls": 5
  },
  "expected_state": {
    "obs:child_dispatch_count": 1,
    "obs:child_dispatch_count_total": 2
  },

  "expected_process": {
    "topology": "flat",

    "coverage_thoroughness": {
      "expected_dispatch_count": { "$gte": 2 },
      "dispatch_success_ratio": { "$gte": 0.9 }
    },

    "iterative_refinement": {
      "expected_error_recovery_rate": { "$gte": 1.0 },
      "max_identical_resubmissions": 0,
      "stderr_decrease_required": true
    },

    "appropriate_tool_use": {
      "expected_repl_ratio": { "$gte": 0.3 },
      "max_repl_error_rate": { "$lte": 0.5 }
    },

    "weights": {
      "iterative_refinement": 3.0,
      "appropriate_tool_use": 2.0,
      "coverage_thoroughness": 1.0,
      "question_quality": 0.5,
      "synthesis_depth": 0.5
    }
  }
}
```

### 3.4 Example Fixture: fake_recursive_ping with expected_process

This extends the existing `fake_recursive_ping.json` fixture (3-layer recursive dispatch):

```json
{
  "expected_process": {
    "topology": "recursive",

    "coverage_thoroughness": {
      "expected_dispatch_count": { "$gte": 1 },
      "dispatch_success_ratio": 1.0
    },

    "synthesis_depth": {
      "expected_data_flow_edges": { "$gte": 0 },
      "min_final_answer_length": 1,
      "synthesis_code_patterns": ["json.loads"]
    },

    "appropriate_tool_use": {
      "expected_repl_ratio": { "$gte": 0.2 },
      "max_repl_error_rate": { "$lte": 0.0 }
    }
  }
}
```

---

## 4. SQL Queries

All queries target the `traces.db` file whose path is available via `PluginContractResult.traces_db_path`. The database uses the 3-table schema defined in `sqlite_tracing.py` (DDL at line 258).

### 4.1 Coverage Thoroughness

**Q1: Total child dispatch count (cumulative)**

```sql
-- Read from session_state_events for the single trace in this run.
-- state_key = 'obs:child_dispatch_count_total', key_category = 'obs_dispatch'
SELECT value_int
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'obs:child_dispatch_count_total'
ORDER BY seq DESC
LIMIT 1;
```

**Q2: Count of unique dispatch prompts**

Child summaries are stored as state keys with pattern `obs:child_summary@d{N}f{M}` and `value_json` contains a JSON object with a `prompt_preview` field.

```sql
-- Each child summary is a separate SSE row with state_key like 'obs:child_summary'
-- and key_depth/key_fanout identifying the child. The value_json has prompt_preview.
SELECT COUNT(DISTINCT json_extract(value_json, '$.prompt_preview'))
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'obs:child_summary'
  AND key_category = 'other';
```

Note: `obs:child_summary` keys are categorized as `"other"` by `_categorize_key()` (line 69) because they start with `obs:child_` but the exact prefix `obs:child_summary` matches `obs_dispatch` via the `obs:child_` prefix check at line 73. The key has depth/fanout suffixes parsed by `_parse_key()` (line 52), so `state_key` in the DB is the base key `obs:child_summary`.

**Q3: Dispatch success ratio**

```sql
-- Count non-error dispatches from child summaries
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN json_extract(value_json, '$.error') = 0 THEN 1 ELSE 0 END) AS successes
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'obs:child_summary'
  AND value_json IS NOT NULL;
```

### 4.2 Question Quality

**Q4: Prompt length statistics**

```sql
SELECT
    AVG(LENGTH(json_extract(value_json, '$.prompt_preview'))) AS avg_len,
    MIN(LENGTH(json_extract(value_json, '$.prompt_preview'))) AS min_len,
    MAX(LENGTH(json_extract(value_json, '$.prompt_preview'))) AS max_len,
    COUNT(*) AS total_prompts
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'obs:child_summary'
  AND value_json IS NOT NULL;
```

**Q5: Prompt uniqueness (for repetition detection)**

```sql
-- Retrieve all prompt previews for pairwise comparison in Python
SELECT json_extract(value_json, '$.prompt_preview') AS prompt
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'obs:child_summary'
  AND value_json IS NOT NULL
ORDER BY seq;
```

Pairwise Jaccard distance is computed in Python after fetching prompts. SQLite does not have built-in set similarity functions.

### 4.3 Synthesis Depth

**Q6: Data flow edges from REPL trace summary**

```sql
-- repl_trace_summary is stored as a JSON column in telemetry rows for
-- execute_code tool calls (event_type = 'tool_call', tool_name = 'execute_code')
SELECT repl_trace_summary
FROM telemetry
WHERE trace_id = :trace_id
  AND event_type = 'tool_call'
  AND tool_name = 'execute_code'
  AND repl_trace_summary IS NOT NULL;
```

Each `repl_trace_summary` JSON may contain `data_flow_edges` (list of `[source, target]` pairs). Parsed in Python:

```python
import json
total_edges = 0
for row in cursor.fetchall():
    summary = json.loads(row["repl_trace_summary"])
    edges = summary.get("data_flow_edges", [])
    total_edges += len(edges)
```

**Q7: Final answer length**

```sql
SELECT LENGTH(value_text) AS answer_len
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'final_answer'
ORDER BY seq DESC
LIMIT 1;
```

**Q8: Synthesis code patterns in submitted code**

```sql
-- Check for synthesis patterns in submitted REPL code
SELECT value_text
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'repl_submitted_code'
  AND key_depth = 0
ORDER BY seq;
```

Pattern matching is done in Python: `any(pattern in code for pattern in synthesis_patterns)`.

### 4.4 Iterative Refinement

**Q9: Error-then-recovery sequence detection**

```sql
-- Get REPL results in sequence to detect error -> success patterns
SELECT
    seq,
    json_extract(value_json, '$.has_errors') AS has_errors,
    json_extract(value_json, '$.stderr') AS stderr_text
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'last_repl_result'
  AND key_depth = 0
ORDER BY seq;
```

Recovery rate is computed in Python by iterating over consecutive pairs: if row N has `has_errors=1` and row N+1 has `has_errors=0`, that is one recovery. Rate = recoveries / errors.

**Q10: Identical code resubmission detection**

```sql
-- Get submitted code hashes in order to detect identical resubmissions
SELECT seq, value_text AS code_hash
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'repl_submitted_code_hash'
  AND key_depth = 0
ORDER BY seq;
```

Count consecutive identical hashes in Python. If hash[i] == hash[i+1], that is one identical resubmission.

**Q11: Stderr length progression**

```sql
SELECT
    seq,
    CAST(json_extract(value_json, '$.stderr_len') AS INTEGER) AS stderr_len
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'last_repl_result'
  AND key_depth = 0
  AND json_extract(value_json, '$.has_errors') = 1
ORDER BY seq;
```

### 4.5 Appropriate Tool Use

**Q12: REPL call ratio (execute_code calls vs total model calls)**

```sql
-- From telemetry: count tool calls vs model calls
SELECT
    (SELECT COUNT(*) FROM telemetry
     WHERE trace_id = :trace_id AND event_type = 'tool_call'
       AND tool_name = 'execute_code') AS repl_calls,
    (SELECT COUNT(*) FROM telemetry
     WHERE trace_id = :trace_id AND event_type = 'model_call') AS model_calls;
```

Ratio = `repl_calls / model_calls` (guarded against division by zero).

**Q13: REPL error rate**

```sql
SELECT
    COUNT(*) AS total_repl,
    SUM(repl_has_errors) AS error_repl
FROM telemetry
WHERE trace_id = :trace_id
  AND event_type = 'tool_call'
  AND tool_name = 'execute_code';
```

Error rate = `error_repl / total_repl`.

**Q14: Wasted model calls (text-only non-final responses)**

```sql
-- Model calls that produced text but no tool call and are not the final call.
-- These are "wasted" because in the RLM pattern, the model should either
-- call execute_code or produce a final answer, not emit intermediate text.
SELECT COUNT(*) AS wasted
FROM telemetry t1
WHERE t1.trace_id = :trace_id
  AND t1.event_type = 'model_call'
  AND t1.finish_reason = 'STOP'
  AND NOT EXISTS (
      SELECT 1 FROM telemetry t2
      WHERE t2.trace_id = t1.trace_id
        AND t2.event_type = 'tool_call'
        AND t2.start_time > t1.start_time
        AND t2.start_time < t1.start_time + 0.5
  )
  AND t1.call_number < (
      SELECT MAX(call_number) FROM telemetry
      WHERE trace_id = :trace_id AND event_type = 'model_call'
  );
```

Note: This query is approximate. A more reliable approach is to use the event stream from `PluginContractResult.events` directly, checking for `text`-only model responses that are not the final response. The SQL approach is provided for traces.db-only analysis; the evaluator should prefer the events list when available.

**Q15: Structured output success rate**

```sql
-- From child summaries: structured_output.outcome field
SELECT
    COUNT(*) AS total_structured,
    SUM(CASE
        WHEN json_extract(value_json, '$.structured_output.outcome') = 'validated' THEN 1
        WHEN json_extract(value_json, '$.structured_output.outcome') = 'retry_recovered' THEN 1
        ELSE 0
    END) AS successful
FROM session_state_events
WHERE trace_id = :trace_id
  AND state_key = 'obs:child_summary'
  AND json_extract(value_json, '$.structured_output.expected') = 1;
```

### 4.6 Obtaining the trace_id

All queries above require `:trace_id`. Since each fixture run produces exactly one trace:

```sql
SELECT trace_id FROM traces ORDER BY start_time DESC LIMIT 1;
```

---

## 5. Edge Cases

### 5.1 traces.db Does Not Exist (Non-Plugin Runs)

When `PluginContractResult.traces_db_path` is `None` or the file does not exist:

- `ProcessEvaluator.__init__()` sets `self._conn = None`.
- Each dimension evaluator checks `if self._conn is None` and falls back to **state-only evaluation**, using `self._result.final_state` and `self._result.events` instead of SQL queries.
- State-only evaluation provides degraded but still meaningful scores for most dimensions:
  - `coverage_thoroughness`: reads `obs:child_dispatch_count_total` from `final_state`.
  - `question_quality`: uses `events` list to extract dispatch prompts from child summary state keys.
  - `iterative_refinement`: uses `events` list to sequence `last_repl_result` state deltas.
  - `appropriate_tool_use`: counts `function_call:execute_code` events from the event stream.
  - `synthesis_depth`: limited -- returns a score of 0.5 (neutral) with a detail message explaining that trace data is unavailable.

This ensures that `run_fixture_contract()` (which uses a temp directory for traces.db, `contract_runner.py` line 348) still gets process scores, while programmatic runs without `SqliteTracingPlugin` degrade gracefully.

### 5.2 Topology-Specific Scoring

Different topologies have fundamentally different "good process" characteristics:

| Topology | Key Difference |
|----------|---------------|
| `flat` | No child dispatches. `coverage_thoroughness` and `question_quality` are scored only on REPL usage. Dispatch-related sub-checks return score 1.0 (not applicable). |
| `recursive` | Deep chains. `synthesis_depth` is weighted higher (child results bubble up through multiple layers). `coverage_thoroughness` counts dispatches per depth level, not just total. |
| `fanout` | Parallel batches. `question_quality` is critical (are the K prompts distinct?). `coverage_thoroughness` checks batch count. |
| `debate` | Multiple conflicting perspectives. `synthesis_depth` checks for aggregation/voting patterns. `question_quality` checks that prompts encode different viewpoints. |

**Implementation:** Each dimension evaluator receives `self._topology` and adjusts its rubric:

```python
def _eval_coverage_thoroughness(self) -> DimensionScore:
    if self._topology == "flat":
        # Score based on REPL iterations, not dispatch count
        return self._eval_coverage_flat()
    elif self._topology == "recursive":
        # Score based on per-depth dispatch counts
        return self._eval_coverage_recursive()
    else:
        return self._eval_coverage_default()
```

Default thresholds per topology are hardcoded in a `_TOPOLOGY_DEFAULTS` dict. Fixture-level `expected_process` values override these defaults when present, using the same `_deep_merge()` pattern from `fixtures.py` (line 27).

### 5.3 Performance Considerations

**Query time:** All SQL queries hit a single-file SQLite database with WAL mode (`sqlite_tracing.py` line 384) and the indexed columns `trace_id`, `state_key`, and `seq` (indices at lines 317-321). For provider-fake fixtures (typically 2-10 model calls, 5-30 state events), each query returns in <1ms. Total evaluation overhead per fixture: <10ms.

**Impact on test suite speed:** The default contract test suite runs ~28 fixtures in ~22s. Adding process evaluation to fixtures that have `expected_process` sections (initially zero fixtures until authors opt in) adds zero overhead. When all 28 fixtures opt in, worst case adds ~280ms (10ms x 28), which is <2% of total runtime.

**Memory:** `ProcessEvaluator` holds a `sqlite3.Connection` (lightweight) and reads rows lazily. No in-memory caching of the full database.

**Opt-in design:** Fixtures without `expected_process` skip evaluation entirely. The `ScenarioRouter` constructor checks `fixture.get("expected_process", {})` -- when empty, `run_fixture_contract_with_plugins()` skips `ProcessEvaluator` construction and returns `process_score=None`.

### 5.4 Fixture Author Guidance

When adding `expected_process` to a fixture:

1. Run the fixture once to produce `traces.db`.
2. Use the draft SQL queries to inspect actual values.
3. Set `expected_process` thresholds based on observed values with appropriate tolerance.
4. Use matcher operators (`$gte`, `$lte`) for ranges rather than exact values -- process metrics vary more than outcome metrics.
5. Set dimension weights to emphasize the aspect being tested (e.g., `iterative_refinement: 3.0` for error recovery fixtures).

---

## Appendix A: Source File Reference

| File | Line(s) | Relevance |
|------|---------|-----------|
| `tests_rlm_adk/provider_fake/fixtures.py` | 46-130 | `_match_value()`, matcher operators |
| `tests_rlm_adk/provider_fake/fixtures.py` | 192-238 | `ContractResult` dataclass |
| `tests_rlm_adk/provider_fake/fixtures.py` | 241-527 | `ScenarioRouter`, `check_expectations()` |
| `tests_rlm_adk/provider_fake/contract_runner.py` | 89-101 | `PluginContractResult` dataclass |
| `tests_rlm_adk/provider_fake/contract_runner.py` | 360-500 | `run_fixture_contract_with_plugins()` |
| `rlm_adk/plugins/sqlite_tracing.py` | 258-321 | DDL schema (traces, telemetry, session_state_events) |
| `rlm_adk/plugins/sqlite_tracing.py` | 69-110 | `_categorize_key()` -- key category mapping |
| `rlm_adk/plugins/sqlite_tracing.py` | 115-160 | `_CURATED_PREFIXES`, `_should_capture()` |
| `rlm_adk/plugins/sqlite_tracing.py` | 586-628 | `_insert_sse()` -- row insertion logic |
| `rlm_adk/plugins/sqlite_tracing.py` | 1096-1120 | `on_event_callback` -- event capture |
| `rlm_adk/plugins/observability.py` | 50-407 | `ObservabilityPlugin` -- all callback hooks |
| `rlm_adk/dispatch.py` | 168-829 | `create_dispatch_closures()`, accumulators, `flush_fn()` |
| `rlm_adk/state.py` | 58-107 | Observability state key constants |
| `rlm_adk/state.py` | 122-124 | `child_obs_key()` function |
| `rlm_adk/state.py` | 214-223 | `depth_key()` function |
| `rlm_adk_docs/observability.md` | 288-335 | Worker observability path (section 8) |
| `rlm_adk_docs/observability.md` | 357-407 | Per-iteration vs cumulative keys (section 8.1) |
| `rlm_adk_docs/observability.md` | 439-480 | REPL trace infrastructure (section 10) |
| `rlm_adk_docs/testing.md` | 44-58 | ContractResult documentation |
| `rlm_adk_docs/testing.md` | 70-85 | PluginContractResult documentation |
| `rlm_adk_docs/testing.md` | 92-185 | Fixture JSON schema and matcher operators |

## Appendix B: Future Extensions

- **LLM-as-judge dimension:** A sixth dimension where a secondary LLM evaluates the reasoning chain quality. This requires network access and is out of scope for provider-fake tests, but could be added for live benchmark runs.
- **Comparative scoring:** Score relative to a known-good baseline trace rather than absolute thresholds. Requires a trace archive (not yet built).
- **Dashboard integration:** Surface `ProcessScore` in the Streamlit dashboard (`rlm_adk/dashboard/`) as a radar chart alongside the existing token/timing panels.
- **Aggregate reports:** After running the full fixture suite, produce a cross-fixture process quality report showing which dimensions are consistently weak.
