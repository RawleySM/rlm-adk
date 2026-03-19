# Proposal 04: Data-Flow Storyteller -- Narrative Reconstruction from Polya Understand Traces

**Status:** Draft
**Date:** 2026-03-18
**Author:** Data-Flow-Storyteller teammate

---

## Motivation

The four Polya understand topologies (T1-T4) produce rich trace data across three persistence layers: `telemetry` rows, `session_state_events` rows, and `repl_trace_summary` JSON blobs. Today, this data is queryable but not narratable. A benchmark reviewer must mentally reconstruct the execution story from raw rows and JSON. This proposal designs a **TraceNarrative** system that reads these traces and produces a human-readable "understanding story" showing how the agent navigated the Polya understand phase.

---

## 1. TraceNarrative Data Structure

### 1.1 Core Dataclass

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NarrativeEvent:
    """A single event in the chronological narrative."""

    timestamp_ms: float
    """Wall-clock offset from invocation start, in milliseconds."""

    event_type: str
    """One of: SKILL_ACTIVATED, CONTEXT_PREPARED, QUESTION_GENERATED,
    CHILD_DISPATCHED, CHILD_RETURNED, CHILD_ERROR, GAP_DETECTED,
    REPROBE_DISPATCHED, REPROBE_RETURNED, SYNTHESIS_DISPATCHED,
    SYNTHESIS_RETURNED, VERDICT_RENDERED, DATA_FLOW_EDGE."""

    phase: str
    """Topology phase label (e.g., 'L0_WORKFLOW', 'L1_ASSESS', 'L2_CHUNK',
    'SELECT', 'PROBE_R1', 'GAP_ANALYSIS', 'REPROBE_R2', 'SYNTHESIZE',
    'ADVOCATE', 'JUDGE')."""

    depth: int
    """Recursion depth at which this event occurred (0 = root)."""

    fanout_idx: int | None
    """Child index within a batch dispatch (None for non-batched events)."""

    summary: str
    """Human-readable one-line description of what happened."""

    detail: dict[str, Any] = field(default_factory=dict)
    """Structured payload -- varies by event_type:
    - CHILD_DISPATCHED: {prompt_preview, prompt_len, model, batch_size}
    - CHILD_RETURNED: {response_preview, response_len, elapsed_ms,
                        input_tokens, output_tokens, finish_reason,
                        parsed_output_keys}
    - CHILD_ERROR: {error_category, error_message, elapsed_ms}
    - DATA_FLOW_EDGE: {source_call_index, target_call_index}
    - QUESTION_GENERATED: {question_text, generation_method}
    - GAP_DETECTED: {dimension_id, confidence, gaps_text}
    - VERDICT_RENDERED: {verdict, retrieval_count, confidence_map}
    """


@dataclass
class DataFlowLink:
    """A directed edge showing information flow between child dispatches.

    Derived from REPLTrace.data_flow_edges (source_index, target_index)
    in rlm_adk/repl/trace.py line 31. The DataFlowTracker (line 120)
    detects these via substring fingerprinting of response-to-prompt chains.
    """

    source_call_index: int
    """The llm_call index whose response fed into the target prompt."""

    target_call_index: int
    """The llm_call index whose prompt contained content from the source."""

    source_phase: str
    """Phase label of the source call (e.g., 'PROBE_R1', 'ADVOCATE')."""

    target_phase: str
    """Phase label of the target call (e.g., 'SYNTHESIZE', 'JUDGE')."""

    fingerprint_match: bool = True
    """Whether this was detected via DataFlowTracker fingerprinting (True)
    or inferred from topology structure (False)."""


@dataclass
class PhaseTimingBlock:
    """Aggregated timing for one topology phase."""

    phase: str
    """Phase label (same vocabulary as NarrativeEvent.phase)."""

    start_offset_ms: float
    """Offset from invocation start."""

    end_offset_ms: float
    """Offset from invocation start."""

    wall_time_ms: float
    """end - start."""

    child_count: int
    """Number of child dispatches in this phase."""

    error_count: int
    """Number of child errors in this phase."""

    total_input_tokens: int
    total_output_tokens: int


@dataclass
class NarrativeSummary:
    """Aggregate statistics for the entire narrative."""

    topology: str
    """Topology identifier: 'T1', 'T2', 'T3', 'T4'."""

    total_wall_time_ms: float
    total_child_dispatches: int
    total_batch_dispatches: int
    total_errors: int
    error_breakdown: dict[str, int]
    """Maps error_category -> count, from obs:child_error_counts."""

    total_input_tokens: int
    total_output_tokens: int
    total_data_flow_edges: int
    phases_completed: list[str]
    verdict: str | None
    """Final verdict string (topology-specific). None if not yet rendered."""

    retrieval_count: int
    """Number of items in the retrieval order."""


@dataclass
class TraceNarrative:
    """Complete narrative reconstruction of one Polya understand execution.

    Built from the three persistence layers:
    1. telemetry table rows (ordered by start_time)
    2. session_state_events table rows (ordered by seq)
    3. repl_trace_summary JSON blobs (from LAST_REPL_RESULT state deltas)
    """

    trace_id: str
    """The trace_id from the traces table, used as the join key across
    all three persistence layers."""

    topology: str
    """Detected topology: 'T1', 'T2', 'T3', 'T4', or 'UNKNOWN'."""

    events: list[NarrativeEvent] = field(default_factory=list)
    """Chronologically ordered list of narrative events."""

    data_flow_links: list[DataFlowLink] = field(default_factory=list)
    """Information flow edges detected by DataFlowTracker or inferred
    from topology structure."""

    phase_timings: list[PhaseTimingBlock] = field(default_factory=list)
    """Aggregated timing per phase."""

    summary: NarrativeSummary | None = None
    """Aggregate statistics. Populated after all events are collected."""

    raw_child_summaries: dict[str, dict] = field(default_factory=dict)
    """Per-child obs:child_summary@d{N}f{M} dicts from dispatch.py
    (line 564). Keyed by the obs key string."""
```

### 1.2 Field Source Mapping

Each field in `TraceNarrative` maps to a specific source in the codebase:

| Field | Source | Location |
|-------|--------|----------|
| `trace_id` | `traces.trace_id` | `sqlite_tracing.py` line 225 |
| `topology` | Inferred from `skill_instruction` column in `telemetry` table | `sqlite_tracing.py` line 287 |
| `events[].timestamp_ms` | `telemetry.start_time - traces.start_time` | `sqlite_tracing.py` lines 258-266 |
| `events[].depth` | `telemetry.depth` or `session_state_events.key_depth` | `sqlite_tracing.py` lines 264, 304 |
| `events[].fanout_idx` | `session_state_events.key_fanout` | `sqlite_tracing.py` line 305 |
| `data_flow_links` | `REPLTrace.data_flow_edges` | `trace.py` line 31 |
| `phase_timings[].wall_time_ms` | `obs:child_dispatch_latency_ms` list | `state.py` line 100 |
| `summary.error_breakdown` | `obs:child_error_counts` dict | `state.py` line 99 |
| `summary.total_child_dispatches` | `obs:child_dispatch_count_total` | `state.py` line 104 |
| `raw_child_summaries` | `obs:child_summary@d{N}f{M}` keys | `state.py` line 122-124, `dispatch.py` line 564 |

---

## 2. Narrative Builder Algorithm

### 2.1 Overview

The `NarrativeBuilder` reconstructs a `TraceNarrative` from SQLite data in five passes:

```
Pass 1: Load trace metadata         (traces table)
Pass 2: Load telemetry rows         (telemetry table, ordered by start_time)
Pass 3: Load state events           (session_state_events table, ordered by seq)
Pass 4: Load REPL trace summaries   (repl_trace_summary column + artifact)
Pass 5: Correlate, infer, assemble  (join all sources, detect topology, build events)
```

### 2.2 Pass 1: Load Trace Metadata

```sql
SELECT trace_id, session_id, start_time, end_time, status,
       child_dispatch_count, child_total_batch_dispatches,
       child_error_counts, per_iteration_breakdown,
       total_input_tokens, total_output_tokens, total_calls
FROM traces
WHERE trace_id = :trace_id;
```

This provides the invocation-level envelope. `start_time` becomes the zero reference for all `timestamp_ms` offsets.

### 2.3 Pass 2: Load Telemetry Rows

```sql
SELECT telemetry_id, event_type, agent_name, iteration, depth,
       call_number, start_time, end_time, duration_ms, model,
       input_tokens, output_tokens, thought_tokens, finish_reason,
       tool_name, tool_args_keys, result_preview,
       repl_has_errors, repl_has_output, repl_llm_calls,
       repl_trace_summary, skill_instruction,
       repl_stdout, repl_stderr,
       status, error_type, error_message
FROM telemetry
WHERE trace_id = :trace_id
ORDER BY start_time ASC;
```

Each `model_call` row becomes a candidate `NarrativeEvent`. Each `tool_call` row where `tool_name = 'execute_code'` is a REPL execution boundary that may contain child dispatch activity.

**Topology detection:** The `skill_instruction` column (captured at `before_model_callback` time, `sqlite_tracing.py` line 287) contains the active skill instruction text. The builder matches against known topology signatures:

| Pattern in `skill_instruction` | Topology |
|-------------------------------|----------|
| `polya-understand-t1-workflow` | T1 |
| `polya-understand-t2-flat` | T2 |
| `polya-understand-t3-adaptive` | T3 |
| `polya-understand-t4-debate` | T4 |

### 2.4 Pass 3: Load State Events

```sql
SELECT event_id, seq, event_author, event_time, state_key,
       key_category, key_depth, key_fanout,
       value_type, value_int, value_float, value_text, value_json
FROM session_state_events
WHERE trace_id = :trace_id
ORDER BY seq ASC;
```

Key state events and their narrative mapping:

| `state_key` pattern | Narrative event type | Source constant |
|---------------------|---------------------|----------------|
| `obs:child_dispatch_count` | (count update) | `state.py` line 98 |
| `obs:child_dispatch_latency_ms` | Phase timing | `state.py` line 100 |
| `obs:child_error_counts` | CHILD_ERROR details | `state.py` line 99 |
| `obs:child_summary@d{N}f{M}` | CHILD_RETURNED or CHILD_ERROR | `state.py` line 122-124 |
| `obs:structured_output_failures` | Schema validation failure count | `state.py` line 82 |
| `skill_instruction` | SKILL_ACTIVATED | `state.py` line 41 |
| `iteration_count` | Iteration boundary | `state.py` line 15 |
| `last_repl_result` | REPL execution boundary | `state.py` line 21 |

**Join key:** The `trace_id` column is present in both `telemetry` and `session_state_events`, providing the primary correlation key. Within a trace, temporal ordering is established by `telemetry.start_time` and `session_state_events.seq` (monotonic). Cross-table correlation uses `event_time` proximity: a state event with key `obs:child_summary@d1f0` is attributed to the nearest preceding `tool_call` telemetry row for `execute_code`.

### 2.5 Pass 4: Load REPL Trace Summaries

REPL trace data lives in two places:

1. **Inline:** The `repl_trace_summary` column in `telemetry` rows (`sqlite_tracing.py` line 286). This is a JSON string containing the `REPLTrace.summary()` dict (wall_time_ms, llm_call_count, failed_llm_calls, peak_memory_bytes, data_flow_edges count, submitted_code_chars, submitted_code_hash) -- see `trace.py` lines 107-117.

2. **Artifact:** The `repl_traces.json` artifact saved by `REPLTracingPlugin` (`repl_tracing.py` lines 71-98). This contains full trace data keyed by `d{depth}:i{iteration}` with the complete `trace_summary` dict including individual `llm_calls` entries with timing and data flow edges.

The builder reads both. The artifact provides the `data_flow_edges` list (tuples of `(source_index, target_index)`) that become `DataFlowLink` entries. For each edge, the builder maps call indices to their topology phase by cross-referencing with the chronological event list.

### 2.6 Pass 5: Correlate, Infer, Assemble

The assembly algorithm:

```
1. Set t0 = traces.start_time
2. Create SKILL_ACTIVATED event from first skill_instruction state event
3. For each telemetry row (ordered by start_time):
   a. If event_type == 'model_call' at depth 0:
      - This is a parent (L0) model call
      - Map to phase based on topology + call sequence position:
        T1: call 0 = L0_WORKFLOW, final call = SYNTHESIZE
        T2: (no L0 model call for question generation -- local Python)
        T3: call 0 = SELECT, final call = SYNTHESIZE
        T4: (no L0 model call before advocates)
   b. If event_type == 'tool_call' and tool_name == 'execute_code':
      - This is a REPL execution boundary
      - Look up state events with seq values between this tool_call
        and the next tool_call
      - Extract obs:child_summary@d{N}f{M} state events to build
        CHILD_DISPATCHED + CHILD_RETURNED event pairs
4. For each obs:child_summary state event:
   a. Parse the value_json payload
   b. Create CHILD_DISPATCHED event:
      summary = "Dispatched child d{depth}f{fanout} ({model})"
      detail = {prompt_preview, prompt_len, model, batch_size}
   c. Create CHILD_RETURNED or CHILD_ERROR event:
      If error == true:
        type = CHILD_ERROR
        summary = "Child d{depth}f{fanout} failed: {error_category}"
        detail = {error_category, error_message, elapsed_ms}
      Else:
        type = CHILD_RETURNED
        summary = "Child d{depth}f{fanout} returned ({elapsed_ms}ms)"
        detail = {response_preview, elapsed_ms, input_tokens, ...}
5. For each data_flow_edge (source_idx, target_idx) from REPL traces:
   a. Look up source and target calls in the chronological event list
   b. Create DATA_FLOW_EDGE event:
      summary = "Response from call {source_idx} fed into prompt of call {target_idx}"
   c. Create DataFlowLink with inferred phase labels
6. Build PhaseTimingBlock entries by grouping events by phase
7. Build NarrativeSummary from aggregated counts
8. Sort all events by timestamp_ms
```

### 2.7 Topology-Specific Phase Inference

Phase inference depends on the detected topology and the position of each child dispatch within the REPL execution sequence. The builder uses the `debug_log` output patterns from each topology skill as ground truth for phase ordering:

**T1 (Workflow-First 3-Layer):**
- `_RUN_POLYA_UNDERSTAND_T1_WORKFLOW_SRC` (line 614 of `polya_understand_t1_workflow.py`)
- Phase sequence: `CONTEXT_PREP` -> `L0_WORKFLOW` (1 llm_query) -> `L1_ASSESS` (N llm_query_batched) -> `L2_CHUNK` (conditional, M llm_query_batched) -> `SYNTHESIZE` (1 llm_query)
- Detection: First single dispatch = L0_WORKFLOW. First batch dispatch = L1_ASSESS. Second batch dispatch (if present) = L2_CHUNK. Final single dispatch = SYNTHESIZE.

**T2 (Flat Open-Ended):**
- `_RUN_POLYA_UNDERSTAND_T2_FLAT_SRC` (line 378 of `polya_understand_t2_flat.py`)
- Phase sequence: `CONTEXT_PREP` -> `QUESTION_GEN` (local Python, no LLM) -> `INVESTIGATE` (Q llm_query_batched) -> `SYNTHESIZE` (1 llm_query)
- Detection: First batch dispatch = INVESTIGATE. First single dispatch after batch = SYNTHESIZE. No L0 model call before the batch.

**T3 (Dimension-Adaptive Round-Trip):**
- `_RUN_POLYA_UNDERSTAND_T3_ADAPTIVE_SRC` (line 758 of `polya_understand_t3_adaptive.py`)
- Phase sequence: `CONTEXT_PREP` -> `SELECT` (1 llm_query) -> `PROBE_R1` (N llm_query_batched) -> `GAP_ANALYSIS` (local Python) -> `REPROBE_R2` (conditional, K llm_query_batched) -> `SYNTHESIZE` (1 llm_query)
- Detection: First single dispatch = SELECT. First batch dispatch = PROBE_R1. Second batch dispatch (if present) = REPROBE_R2. Final single dispatch = SYNTHESIZE.

**T4 (Adversarial Debate):**
- `_RUN_POLYA_UNDERSTAND_T4_DEBATE_SRC` (line 602 of `polya_understand_t4_debate.py`)
- Phase sequence: `CONTEXT_PREP` -> `ADVOCATE` (2 llm_query_batched, batch_size=2) -> `JUDGE` (1 llm_query)
- Detection: First batch dispatch with exactly 2 children = ADVOCATE. First single dispatch after batch = JUDGE.

---

## 3. Markdown Output Format

### 3.1 Template

```markdown
# Polya Understand Narrative: {topology} ({trace_id})

**Topology:** {topology_full_name}
**Trace ID:** {trace_id}
**Wall Time:** {total_wall_time_ms}ms
**Total LLM Calls:** {total_child_dispatches} ({total_batch_dispatches} batched)
**Total Tokens:** {total_input_tokens} in / {total_output_tokens} out
**Verdict:** {verdict}

---

## Timeline

{timeline_visualization}

---

## Data Flow

{data_flow_diagram}

---

## Phase Details

{per_phase_sections}

---

## Errors & Retries

{error_section}

---

## Summary Statistics

{summary_table}
```

### 3.2 Timeline Visualization (Text-Based)

The timeline uses a fixed-width text format showing phases as horizontal bars with timing:

```
TIMELINE (total: 4523ms)
========================

  0ms    500ms    1000ms   1500ms   2000ms   2500ms   3000ms   3500ms   4000ms   4500ms
  |--------|--------|--------|--------|--------|--------|--------|--------|--------|
  [===== SELECT (823ms) =====]
                              [============= PROBE_R1 (1847ms, 5 children) ==============]
                                                                                          [GAP]
                                                                                              [==== REPROBE_R2 (912ms, 2 children) ====]
                                                                                                                                        [===== SYNTHESIZE (941ms) =====]

  Legend: [===] = active phase   [GAP] = local Python (no LLM)
  Errors: * = child error within phase
```

For phases with errors, an asterisk marks the approximate position:

```
  [============= PROBE_R1 (1847ms, 5 children, 1 error*) ==============]
```

### 3.3 Data Flow Diagram (Text-Based)

Shows response-to-prompt chains using ASCII art:

```
DATA FLOW (3 edges detected)
=============================

  [SELECT]                      [PROBE_R1]                    [SYNTHESIZE]
  call_0 ----------------------> call_1 (dim=restatement)
  "Selected: restatement,       "EVIDENCE: The objective..."
   givens, unknowns..."          |
                                 +----------------------------> call_6
  call_0 ----------------------> call_2 (dim=givens)            "Combining R1 results:
  (same SELECT output)           "EVIDENCE: Documents..."       restatement evidence +
                                 |                              givens evidence +
                                 +----------------------------> call_6
  call_0 ----------------------> call_3 (dim=unknowns)          (synthesis prompt)"
                                 "EVIDENCE: Missing API..."
                                 |
                                 +----------------------------> call_6

  Edge notation: -----> = DataFlowTracker fingerprint match
                         (first 40 chars of response found in subsequent prompt)
```

### 3.4 Concrete Example Narratives

#### T1 Workflow-First Example

```markdown
# Polya Understand Narrative: T1 Workflow-First (trace-abc123)

**Topology:** T1 Workflow-First 3-Layer
**Trace ID:** trace-abc123
**Wall Time:** 8234ms
**Total LLM Calls:** 12 (2 batched dispatches)
**Total Tokens:** 45,230 in / 12,450 out
**Verdict:** 3 retrieval candidates identified

---

## Timeline

  0ms     1s      2s      3s      4s      5s      6s      7s      8s
  |-------|-------|-------|-------|-------|-------|-------|-------|
  [= L0_WORKFLOW (1.2s) =]
                           [======= L1_ASSESS (3.1s, 5 children) ========]
                                                                          [= L2_CHUNK (2.4s, 8 children, 1 err*) =]
                                                                                                                    [= SYNTHESIZE (1.5s) =]

## Narrative

1. **[0ms] SKILL_ACTIVATED** -- polya-understand-t1-workflow skill loaded
2. **[12ms] CONTEXT_PREPARED** -- 6 context packets prepared from 4 source files
3. **[15ms] L0_WORKFLOW dispatched** -- Manifest-only prompt (1,234 chars) sent to generate workflow steps
4. **[1,200ms] L0_WORKFLOW returned** -- 5 workflow steps generated:
   - "Verify API authentication credentials are documented"
   - "Check database schema definitions are present"
   - "Confirm deployment configuration exists"
   - "Validate test coverage documentation"
   - "Assess dependency version pinning"
5. **[1,210ms] L1_ASSESS dispatched (batch)** -- 5 step assessors dispatched via llm_query_batched
6. **[4,310ms] L1_ASSESS returned** -- 5 assessments received:
   - Step 1: STATUS=PARTIAL, L2_DISPATCH=YES
   - Step 2: STATUS=SUFFICIENT, L2_DISPATCH=NO
   - Step 3: STATUS=MISSING, L2_DISPATCH=YES
   - Step 4: STATUS=SUFFICIENT, L2_DISPATCH=NO
   - Step 5: STATUS=PARTIAL, L2_DISPATCH=NO
7. **[4,320ms] L2_CHUNK dispatched (batch)** -- 8 chunk assessors for steps 1,3 (4 packets x 2 steps)
8. **[5,100ms] CHILD_ERROR** -- Chunk assessor step_1_chunk_3 failed (UNKNOWN, "Child orchestrator produced no answer")
9. **[6,720ms] L2_CHUNK returned** -- 7/8 assessments received (1 error)
10. **[6,730ms] SYNTHESIZE dispatched** -- Synthesis prompt (8,432 chars) combining all assessments
11. **[8,234ms] SYNTHESIZE returned** -- Understanding complete with 3 retrieval candidates
```

#### T2 Flat Example

```markdown
# Polya Understand Narrative: T2 Flat (trace-def456)

**Topology:** T2 Flat Open-Ended
**Trace ID:** trace-def456
**Wall Time:** 5,120ms
**Total LLM Calls:** 6 (1 batched dispatch)
**Total Tokens:** 32,100 in / 8,900 out
**Verdict:** PARTIAL (2 gaps identified)

---

## Narrative

1. **[0ms] SKILL_ACTIVATED** -- polya-understand-t2-flat skill loaded
2. **[8ms] CONTEXT_PREPARED** -- Full context string built (24,500 chars)
3. **[10ms] QUESTION_GENERATED** -- 5 probing questions generated locally (no LLM):
   - "What is the core purpose of the auth refactor...?"
   - "What are the key components...?"
   - "What constraints govern...?"
   - "What are the primary risks...?"
   - "What dependencies does...?"
4. **[15ms] INVESTIGATE dispatched (batch)** -- 5 investigation children via llm_query_batched
5. **[3,800ms] INVESTIGATE returned** -- All 5 investigations complete (0 errors)
6. **[3,810ms] SYNTHESIZE dispatched** -- Synthesis prompt with all Q&A pairs
7. **[5,120ms] SYNTHESIZE returned** -- Verdict: PARTIAL
   - Understanding: "The auth module refactor has sufficient..."
   - Gaps: ["Missing API rate limit documentation", "No rollback procedure defined"]
```

#### T3 Adaptive Round-Trip Example

```markdown
# Polya Understand Narrative: T3 Adaptive (trace-ghi789)

**Topology:** T3 Dimension-Adaptive Round-Trip
**Trace ID:** trace-ghi789
**Wall Time:** 9,450ms
**Total LLM Calls:** 10 (2 batched dispatches)
**Total Tokens:** 52,300 in / 14,200 out
**Verdict:** 2 retrieval candidates, 2 cycles completed

---

## Narrative

1. **[0ms] SKILL_ACTIVATED** -- polya-understand-t3-adaptive skill loaded
2. **[10ms] CONTEXT_PREPARED** -- 8 context packets from 6 source files
3. **[15ms] SELECT dispatched** -- Dimension selection prompt (2,100 chars)
4. **[1,100ms] SELECT returned** -- 4 dimensions selected: [restatement, givens, unknowns, constraints]
5. **[1,110ms] PROBE_R1 dispatched (batch)** -- 4 probe children (1 per dimension)
6. **[4,200ms] PROBE_R1 returned** -- Results:
   - restatement: CONFIDENCE=HIGH
   - givens: CONFIDENCE=MEDIUM
   - unknowns: CONFIDENCE=LOW  <-- gap detected
   - constraints: CONFIDENCE=LOW  <-- gap detected
7. **[4,210ms] GAP_ANALYSIS** -- Local Python: 2 dimensions below MEDIUM threshold
8. **[4,215ms] REPROBE_R2 dispatched (batch)** -- 2 re-probe children for gap dimensions
9. **[6,800ms] REPROBE_R2 returned** -- Re-probe results:
   - unknowns: CONFIDENCE=MEDIUM (upgraded from LOW)
   - constraints: CONFIDENCE=LOW (unchanged)
10. **[6,810ms] SYNTHESIZE dispatched** -- Combining R1 + R2 results
11. **[9,450ms] SYNTHESIZE returned** -- Understanding with 2 retrieval candidates
```

#### T4 Debate Example

```markdown
# Polya Understand Narrative: T4 Debate (trace-jkl012)

**Topology:** T4 Adversarial Debate
**Trace ID:** trace-jkl012
**Wall Time:** 6,340ms
**Total LLM Calls:** 3 (1 batched dispatch)
**Total Tokens:** 41,200 in / 11,800 out
**Verdict:** CONDITIONAL

---

## Data Flow

  [ADVOCATE batch]                              [JUDGE]
  call_0 (optimist) --------------------------> call_2
  "ASSETS: config.yaml, auth.py..."             "VERDICT: CONDITIONAL
   READINESS_CASE: The project has..."           The optimist correctly identifies..."
                                                 |
  call_1 (critic) ----------------------------> call_2
  "GAPS: No API rate limit docs..."             ADJUDICATION: The critic raises
   BLOCKERS: Missing rollback plan..."           valid concerns about..."

  KEY INVARIANT: Judge sees ONLY advocate outputs, never raw context.

## Narrative

1. **[0ms] SKILL_ACTIVATED** -- polya-understand-t4-debate skill loaded
2. **[8ms] CONTEXT_PREPARED** -- Full context string built (28,300 chars)
3. **[12ms] ADVOCATE dispatched (batch=2)** -- Optimist + Critic via llm_query_batched
4. **[3,900ms] ADVOCATE returned** -- Both advocates complete:
   - Optimist: 4 assets, 3 links, coverage map, readiness case
   - Critic: 3 gaps, 2 risks, 1 ambiguity, 1 blocker, 2 retrieval needs
5. **[3,910ms] JUDGE dispatched** -- Judge prompt with advocate outputs only (no raw context)
6. **[6,340ms] JUDGE returned** -- VERDICT: CONDITIONAL
   - Confidence: {architecture=HIGH, testing=MEDIUM, deployment=LOW}
   - Retrieval order: ["Deployment rollback procedure", "API rate limit specs"]
   - Adjudication: "The critic raises valid concerns about deployment..."
```

### 3.5 Summary Statistics Section

```markdown
## Summary Statistics

| Metric | Value |
|--------|-------|
| Topology | T3 Dimension-Adaptive Round-Trip |
| Total wall time | 9,450ms |
| Total child dispatches | 10 |
| Batched dispatches | 2 |
| Errors | 0 |
| Total input tokens | 52,300 |
| Total output tokens | 14,200 |
| Data flow edges | 6 |
| Phases completed | SELECT, PROBE_R1, GAP_ANALYSIS, REPROBE_R2, SYNTHESIZE |
| Cycles completed | 2 |
| Retrieval candidates | 2 |

### Per-Phase Breakdown

| Phase | Wall Time | Children | Errors | In Tokens | Out Tokens |
|-------|-----------|----------|--------|-----------|------------|
| SELECT | 1,085ms | 1 | 0 | 4,200 | 1,100 |
| PROBE_R1 | 3,090ms | 4 | 0 | 28,400 | 6,800 |
| GAP_ANALYSIS | 5ms | 0 (local) | 0 | 0 | 0 |
| REPROBE_R2 | 2,585ms | 2 | 0 | 12,100 | 3,200 |
| SYNTHESIZE | 2,640ms | 1 | 0 | 7,600 | 3,100 |
```

---

## 4. Judge LLM Evaluator Design

### 4.1 When to Use Deterministic vs LLM Judge

| Assessment Dimension | Method | Rationale |
|---------------------|--------|-----------|
| Phase completion | Deterministic | Binary check: did all expected phases execute? |
| Child error rate | Deterministic | Threshold comparison: errors / total < 10%? |
| Data flow completeness | Deterministic | Count edges vs expected: T4 should have exactly 2 edges |
| Token efficiency | Deterministic | Ratio comparison: output_tokens / input_tokens within range? |
| Understanding quality | LLM Judge | Requires semantic evaluation of content |
| Gap identification accuracy | LLM Judge | Requires domain knowledge to assess |
| Verdict appropriateness | LLM Judge | Requires reasoning about evidence sufficiency |
| Synthesis coherence | LLM Judge | Requires evaluating logical structure |

**Cost rule:** Use the deterministic rubric for all structural and quantitative checks. Reserve the LLM judge for the 4 semantic dimensions above. At approximately 2,000 input tokens per judge call, the cost is ~$0.01 per evaluation with `gemini-2.0-flash` or ~$0.06 with `gemini-2.5-pro`.

### 4.2 The `llm_query()` Call Specification

The judge evaluator runs as a child dispatch within the benchmark harness (not inside the Polya topology itself). It uses the standard `llm_query()` mechanism with `output_schema`:

```python
from pydantic import BaseModel, Field


class NarrativeJudgment(BaseModel):
    """Structured output schema for the judge LLM's assessment."""

    understanding_quality: int = Field(
        ge=1, le=5,
        description=(
            "1=incoherent/empty, 2=partial but missing key elements, "
            "3=adequate coverage with some gaps, 4=thorough with minor omissions, "
            "5=comprehensive and well-structured"
        ),
    )
    understanding_rationale: str = Field(
        description="One-paragraph explanation of the understanding quality score."
    )

    gap_identification_accuracy: int = Field(
        ge=1, le=5,
        description=(
            "1=no gaps identified when they exist, 2=some gaps missed, "
            "3=most gaps identified but some spurious, 4=accurate with "
            "minor false positives, 5=precise and complete gap identification"
        ),
    )
    gap_rationale: str = Field(
        description="One-paragraph explanation of the gap identification score."
    )

    verdict_appropriateness: int = Field(
        ge=1, le=5,
        description=(
            "1=verdict contradicts evidence, 2=verdict weakly supported, "
            "3=verdict reasonable but debatable, 4=verdict well-supported, "
            "5=verdict clearly follows from evidence"
        ),
    )
    verdict_rationale: str = Field(
        description="One-paragraph explanation of the verdict appropriateness score."
    )

    synthesis_coherence: int = Field(
        ge=1, le=5,
        description=(
            "1=synthesis is disconnected from child responses, "
            "2=synthesis references some but not all child responses, "
            "3=synthesis covers most child responses with logical flow, "
            "4=synthesis integrates all responses with clear reasoning, "
            "5=synthesis demonstrates emergent insight beyond individual responses"
        ),
    )
    synthesis_rationale: str = Field(
        description="One-paragraph explanation of the synthesis coherence score."
    )

    overall_score: float = Field(
        ge=0.0, le=1.0,
        description="Weighted average: 0.3*understanding + 0.2*gaps + 0.2*verdict + 0.3*synthesis, normalized to [0,1]."
    )

    narrative_observations: str = Field(
        description=(
            "Free-form observations about the narrative that do not fit "
            "into the structured scores. Note any unusual patterns, "
            "surprising data flow paths, or topology-specific concerns."
        ),
    )
```

### 4.3 Judge Prompt Template

```python
JUDGE_PROMPT_TEMPLATE = """\
You are evaluating the quality of a Polya understand phase execution.
You will receive a structured narrative of how an RLM agent navigated the
understand phase using the {topology} topology.

Your task is to assess four dimensions of quality:
1. UNDERSTANDING QUALITY -- Is the synthesized understanding comprehensive?
2. GAP IDENTIFICATION ACCURACY -- Were genuine gaps found and spurious ones avoided?
3. VERDICT APPROPRIATENESS -- Does the verdict logically follow from the evidence?
4. SYNTHESIS COHERENCE -- Does the synthesis integrate child responses effectively?

IMPORTANT EVALUATION RULES:
- Score based on the NARRATIVE CONTENT, not on your own domain knowledge.
- A good understanding is one that correctly reflects what the children found,
  even if you personally know more about the topic.
- A good gap identification is one that flags genuinely missing information
  based on the context available, not information you happen to know exists.
- The verdict should be internally consistent with the evidence presented.

TOPOLOGY: {topology}
TOPOLOGY DESCRIPTION: {topology_description}
EXPECTED PHASE SEQUENCE: {expected_phases}

=== FULL NARRATIVE ===

{narrative_markdown}

=== DETERMINISTIC RUBRIC RESULTS ===

{deterministic_results}

=== END ===

Evaluate this narrative and return your structured judgment.
"""
```

### 4.4 Reproducibility

To make the judge evaluation reproducible:

1. **Temperature:** Set `temperature=0.0` on the judge model call.
2. **Seed:** Use a fixed seed if the model supports it.
3. **Prompt pinning:** The judge prompt template is version-controlled. Any change to the template increments a version number embedded in the output.
4. **Deterministic pre-filter:** The deterministic rubric results are computed before the LLM judge runs and included in its prompt, so the judge's job is purely semantic assessment -- it does not need to count tokens or check phase completion.
5. **Score normalization:** The `overall_score` field uses a fixed weighting formula (0.3 + 0.2 + 0.2 + 0.3 = 1.0) applied by the judge, making cross-run comparisons meaningful.

---

## 5. Per-Topology Narrative Templates

### 5.1 T1 Workflow-First 3-Layer

**Expected narrative shape:**

```
SKILL_ACTIVATED -> CONTEXT_PREPARED
  -> L0_WORKFLOW (1 single dispatch, manifest-only)
  -> L1_ASSESS (N batched dispatch, N = workflow steps)
  -> [L2_CHUNK (M batched dispatch, conditional)]
  -> SYNTHESIZE (1 single dispatch)
```

**Key narrative events to highlight:**
- How many workflow steps L0 generated (expected: 3-8, from `max_steps` parameter)
- Per-step STATUS distribution (SUFFICIENT / PARTIAL / MISSING)
- Whether L2 was triggered and why (L2_DISPATCH flag or packet count > l2_threshold)
- Chunk-level PRESENT/ABSENT distribution and relevance scores
- Gap assessment quality from synthesis

**Topology-specific narrative sections:**

```markdown
### Workflow Step Generation (L0)
- Steps generated: {count}
- Manifest items seen: {manifest_item_count}
- Prompt strategy: manifest-only (L0 never sees raw context)

### Step Assessment Distribution (L1)
| Step | Description | Status | L2 Requested |
|------|-------------|--------|--------------|
| ... | ... | ... | ... |

### Chunk Assessment (L2) {if used_l2}
| Step | Chunk | Status | Relevance | Summary |
|------|-------|--------|-----------|---------|
| ... | ... | ... | ... | ... |
```

**Source references:**
- `polya_understand_t1_workflow.py` line 614: `_RUN_POLYA_UNDERSTAND_T1_WORKFLOW_SRC`
- Phase 1 (L0): line 672 `workflow_prompt = build_workflow_prompt(...)`
- Phase 2 (L1): line 702 `assess_outputs = llm_query_batched(assess_prompts)`
- Phase 3 (L2): line 738 `chunk_outputs = llm_query_batched(chunk_prompts)`
- Phase 4 (Synthesis): line 767 `synthesis_output = str(llm_query(synthesis_prompt))`


### 5.2 T2 Flat Open-Ended

**Expected narrative shape:**

```
SKILL_ACTIVATED -> CONTEXT_PREPARED
  -> QUESTION_GENERATED (local Python, 0 LLM calls)
  -> INVESTIGATE (Q batched dispatch)
  -> SYNTHESIZE (1 single dispatch)
```

**Key narrative events to highlight:**
- That question generation used NO LLM calls (pure heuristic templates, `polya_understand_t2_flat.py` line 209)
- L0 sees FULL context (key departure from T1/T3 manifest-only approach)
- Per-investigation CONFIDENCE and GAP findings
- Final verdict (SUFFICIENT / PARTIAL / INSUFFICIENT)

**Topology-specific narrative sections:**

```markdown
### Question Generation (Local)
- Method: heuristic templates (no LLM call)
- Questions generated: {count}
- Template source: 10 fixed investigative templates

### Investigation Results
| Q# | Question (truncated) | Confidence | Gaps Found |
|----|---------------------|------------|------------|
| ... | ... | ... | ... |

### Verdict
- **{verdict}**: {understanding_preview}
- Coverage: {coverage_assessment}
- Gaps: {gap_count} identified
```

**Source references:**
- `polya_understand_t2_flat.py` line 378: `_RUN_POLYA_UNDERSTAND_T2_FLAT_SRC`
- Question generation: line 209 `_GENERATE_PROBING_QUESTIONS_SRC` (local, no LLM)
- Investigation: line 429 `investigation_outputs = llm_query_batched(investigation_prompts)`
- Synthesis: line 442 `synthesis_output = llm_query(synthesis_prompt)`


### 5.3 T3 Dimension-Adaptive Round-Trip

**Expected narrative shape:**

```
SKILL_ACTIVATED -> CONTEXT_PREPARED
  -> SELECT (1 single dispatch)
  -> PROBE_R1 (N batched dispatch)
  -> GAP_ANALYSIS (local Python, 0 LLM calls)
  -> [REPROBE_R2 (K batched dispatch, conditional)]
  -> SYNTHESIZE (1 single dispatch)
```

**Key narrative events to highlight:**
- Which dimensions were selected and which were excluded
- Per-dimension CONFIDENCE from round 1
- Whether GAP_ANALYSIS triggered round 2 (confidence below threshold)
- Confidence upgrades between round 1 and round 2
- Whether round 2 actually resolved the gaps

**Topology-specific narrative sections:**

```markdown
### Dimension Selection (SELECT)
- Dimensions available: {total_dimensions} (from POLYA_DIMENSIONS constant)
- Dimensions selected: {selected_count}
- Selected: {selected_ids}
- Selection prompt strategy: manifest-only

### Round 1 Probe Results
| Dimension | Confidence | Evidence Length | Gaps |
|-----------|-----------|----------------|------|
| ... | ... | ... | ... |

### Gap Analysis (Local Python)
- Threshold: {confidence_threshold}
- Gaps detected: {gap_count} dimensions below threshold
- Gap dimensions: {gap_dimension_ids}

### Round 2 Re-Probe Results {if cycles == 2}
| Dimension | R1 Confidence | R2 Confidence | Resolved? |
|-----------|---------------|---------------|-----------|
| ... | ... | ... | ... |
```

**Source references:**
- `polya_understand_t3_adaptive.py` line 758: `_RUN_POLYA_UNDERSTAND_T3_ADAPTIVE_SRC`
- SELECT: line 823 `select_output = llm_query(select_prompt)`
- PROBE R1: line 844 `probe_outputs = llm_query_batched(probe_prompts)`
- GAP ANALYSIS: line 856 `gaps = identify_gaps(round1_results, confidence_threshold)` (local Python)
- REPROBE R2: line 889 `r2_outputs = llm_query_batched(reprobe_prompts)` (conditional)
- SYNTHESIZE: line 911 `understanding = str(llm_query(synth_prompt))`


### 5.4 T4 Adversarial Debate

**Expected narrative shape:**

```
SKILL_ACTIVATED -> CONTEXT_PREPARED
  -> ADVOCATE (1 batched dispatch, batch_size=2)
  -> JUDGE (1 single dispatch)
```

**Key narrative events to highlight:**
- The structural invariant: Judge sees ONLY advocate outputs, never raw context (`polya_understand_t4_debate.py` line 15: "this is the key design invariant")
- Optimist's ASSETS / LINKS / COVERAGE_MAP / READINESS_CASE
- Critic's GAPS / RISKS / AMBIGUITIES / BLOCKERS / RETRIEVAL_NEEDS
- Judge's adjudication reasoning -- which advocate's arguments prevailed
- Confidence map per dimension

**Topology-specific narrative sections:**

```markdown
### Advocate Phase
**Optimist Case:**
- Assets identified: {assets_preview}
- Coverage map: {coverage_preview}
- Readiness argument: {readiness_preview}

**Critic Case:**
- Gaps identified: {gaps_preview}
- Risks flagged: {risks_preview}
- Blockers: {blockers_preview}
- Retrieval needs: {retrieval_needs_preview}

### Judge Phase
- **Context invariant:** Judge received 0 bytes of raw project context
- Verdict: **{verdict}** (PROCEED / HALT / CONDITIONAL)
- Adjudication: {adjudication_preview}

### Confidence Map
| Dimension | Confidence |
|-----------|-----------|
| ... | ... |

### Retrieval Order
{numbered_retrieval_list_or_NONE}
```

**Source references:**
- `polya_understand_t4_debate.py` line 602: `_RUN_POLYA_UNDERSTAND_T4_DEBATE_SRC`
- ADVOCATE: line 649 `advocate_outputs = llm_query_batched([optimist_prompt, critic_prompt])`
- JUDGE: line 665 `judge_output = llm_query(judge_prompt)`
- Judge invariant: line 547 `build_judge_prompt` takes exactly 3 args (objective, optimist_response, critic_response) -- no context parameter
- Confidence map: line 466 `_EXTRACT_CONFIDENCE_MAP_SRC`

---

## Appendix A: Deterministic Rubric Checks

These checks run before the LLM judge and their results are included in the judge prompt:

| Check | Pass Condition | Topology |
|-------|---------------|----------|
| Phase completeness | All expected phases appear in events list | All |
| No orphan dispatches | Every CHILD_DISPATCHED has a matching CHILD_RETURNED or CHILD_ERROR | All |
| Error rate | errors / total_dispatches < 0.20 | All |
| Token efficiency | output_tokens / input_tokens > 0.10 | All |
| Data flow minimum | data_flow_edges >= expected minimum for topology | All |
| T1 L2 trigger | L2 triggered iff L1 reported L2_DISPATCH=YES or packet_count > threshold | T1 |
| T2 no-LLM questions | QUESTION_GENERATED events have generation_method="heuristic" | T2 |
| T3 gap detection | GAP_DETECTED events match dimensions with CONFIDENCE < threshold | T3 |
| T3 round-2 conditional | REPROBE_R2 phase present iff gaps were detected | T3 |
| T4 judge isolation | JUDGE dispatch prompt contains 0 bytes from raw project_context | T4 |
| T4 batch size | ADVOCATE batch has exactly 2 children | T4 |

## Appendix B: Expected Data Flow Edge Counts

| Topology | Minimum Edges | Explanation |
|----------|--------------|-------------|
| T1 | N (step count) | Each L1 assessment feeds into synthesis |
| T2 | Q (question count) | Each investigation response feeds into synthesis |
| T3 | N + K | Round 1 probes + round 2 re-probes all feed into synthesis |
| T4 | 2 | Optimist + Critic both feed into judge |

These counts assume the DataFlowTracker (40-char fingerprint, `trace.py` line 127) successfully matches. Actual counts may be lower if responses are short or prompts are heavily reformatted.
