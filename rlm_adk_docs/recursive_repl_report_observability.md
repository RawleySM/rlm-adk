# Recursive REPL Worker Report: Observability and Tracing

## Current Telemetry Model
- Global `ObservabilityPlugin` increments aggregate counters from callback state (`rlm_adk/plugins/observability.py:152-233`).
- Request correlation uses a single `request_id` key from session state (`rlm_adk/plugins/observability.py:69-71`, `rlm_adk/plugins/observability.py:269-277`).
- Dispatch metrics are flushed from closure accumulators into tool state (`rlm_adk/dispatch.py:625-659`) and written by `REPLTool` (`rlm_adk/tools/repl_tool.py:168-185`).
- REPL trace persistence uses `LAST_REPL_RESULT.trace_summary` indexed by `iteration_count` (`rlm_adk/plugins/repl_tracing.py:38-45`).

## Recursive Observability Gaps
- Counter pollution: nested workers will update the same global aggregate keys (`obs:total_calls`, token totals, finish counts).
- Correlation ambiguity: child operations may overwrite/read `request_id` without parent-child lineage.
- Trace overwrite risk: nested workers writing `iteration_count` + `last_repl_result` can clobber trace indexing.
- Event blindness: dispatcher consumes worker events internally (`rlm_adk/dispatch.py:216-219`), so nested spans are not externally visible unless explicitly re-emitted.

## Required Attribution Fields
- `obs:lineage_id`: stable lineage path (`root.1.3`).
- `obs:depth`: numeric depth of current orchestrator.
- `obs:worker_call_id`: unique per dispatch invocation.
- `obs:parent_request_id`: immutable root request ID.
- `obs:agent_role`: `root_orchestrator`, `recursive_worker`, `leaf_worker`.

## Event/State Propagation Design
1. Add lineage-aware metric buckets.
- Keep existing global totals for backward compatibility.
- Add per-lineage dict buckets (for example `obs:lineage:<id>:totals`) for deterministic drill-down.

2. Scope REPL result snapshots.
- Store nested snapshots under scoped keys (`last_repl_result@dN#lineage`) and keep root alias at top level.

3. Propagate summarized child telemetry to parent.
- Child returns normalized metrics payload in `LLMResult` metadata.
- Parent merges payload into both lineage bucket and global rollup.

4. Preserve plugin compatibility.
- `REPLTracingPlugin` should read both legacy `LAST_REPL_RESULT` and scoped variants.
- ObservabilityPlugin should append lineage tags to per-iteration breakdown entries.

## Backward Compatibility
- Maintain existing key names and log format for root-only runs.
- Additive lineage fields only; no breaking removals in plugin outputs.
- Keep `request_id` semantics for existing dashboards; add child IDs rather than replacing root ID.

## Test Matrix
1. Root-only regression.
- Existing telemetry snapshots unchanged when recursion gate is off.

2. Nested lineage attribution.
- Two child workers produce distinct lineage IDs and independent per-lineage counters.

3. Trace retention.
- Multiple nested REPL executions persist all trace summaries without overwrite.

4. Rollup consistency.
- Sum of per-lineage token counters equals global token counters for one invocation.

5. Timeout/error attribution.
- Nested timeout increments both lineage timeout counter and global timeout aggregate.
