# Deferred Observability Gaps

These items from [observability_gaps.md](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md) are intentionally deferred because they are redundant with the active Codex list, are lower-value implementation detail, or are outside the immediate goal of closing the LLM output observability gap.

## Redundant With Active Scope

1. Child dispatch prompt text.
[observability_gaps.md:23](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:23)
Why deferred:
- Already covered by the active child prompt/response persistence work in [observability_gaps_codex.md](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps_codex.md).

2. Child dispatch response text.
[observability_gaps.md:24](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:24)
Why deferred:
- Already covered by the active child-layer LLM output persistence work.

3. `REPLResult.llm_calls` always empty.
[observability_gaps.md:46](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:46)
Why deferred:
- Already covered by the active `call_log_sink` / child-call plumbing work.

4. Generated code string per `execute_code` as a separate backlog item.
[observability_gaps.md:26](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:26)
Why deferred:
- Duplicative of the active REPL submitted-code capture item.
- Full raw persistence may be unnecessary; preview/hash/token metrics are likely sufficient.

## Low-Value Implementation Detail

5. Post-rewrite AST source persistence.
[observability_gaps.md:25](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:25)
Why deferred:
- Pre-rewrite code is the actual LLM output.
- Post-rewrite code is framework-generated and not necessary for core output observability.

6. Per-child error detail map.
[observability_gaps.md:45](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:45)
[dispatch.py:178](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py:178)
Why deferred:
- Existing per-child summaries already include `error`, `error_category`, and `error_message`.
- Additional maps would be denormalized duplication.

7. Parent-child `parent_trace_id` / `dispatch_tree`.
[observability_gaps.md:37](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:37)
Why deferred:
- Current architecture already shares the invocation trace.
- Depth/fanout tagging is sufficient for current output-capture needs.

8. Policy violation on top-level trace row.
[observability_gaps.md:109](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:109)
[sqlite_tracing.py:867](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py:867)
Why deferred:
- Already captured in `session_state_events`.
- Missing summary-row denormalization does not block LLM output observability.

## Performance / Capacity Telemetry Outside Current Goal

9. SDK-internal retry timing details beyond the noted attempt-level addition.
[observability_gaps.md:55](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:55)
Why deferred:
- Useful for reliability/performance analysis, but not required to persist model outputs, thoughts, or REPL code.

10. Semaphore wait time and effective parallelism.
[observability_gaps.md:65](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:65)
Why deferred:
- Performance telemetry, not output-content persistence.

11. Child orchestrator creation and cleanup overhead.
[observability_gaps.md:74](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:74)
Why deferred:
- Useful for latency decomposition, not for capturing LLM outputs.

12. Critical path and wall-clock decomposition.
[observability_gaps.md:124](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:124)
Why deferred:
- Performance analysis work, not output observability closure.

13. `obs:child_total_batch_dispatches` as dispatch-volume telemetry beyond trace-row persistence.
[observability_gaps.md:108](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:108)
Why deferred:
- Only the trace-row persistence part is being pulled into active scope.
- Broader dispatch-volume analytics remain non-blocking.

## REPL Quality Analytics Deferred Until After Capture Exists

14. Variable state evolution / namespace diffs.
[observability_gaps.md:83](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:83)
Why deferred:
- Secondary diagnostic layer; not required to capture outputs or submitted code.

15. Code retry patterns.
[observability_gaps.md:84](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:84)
Why deferred:
- Useful after capture exists, but not a prerequisite.

16. REPL error classification by exception type.
[observability_gaps.md:85](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:85)
Why deferred:
- Helpful for diagnosis, not for persistence of outputs/code.

17. Error-recovery turns.
[observability_gaps.md:88](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:88)
Why deferred:
- Behavioral analytics, not output capture.

18. `format_execution_result()` variable values.
[observability_gaps.md:86](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:86)
Why deferred:
- Presentation/runtime formatting issue, not core observability persistence.

19. `REPLResult.execution_time` consumption.
[observability_gaps.md:87](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:87)
Why deferred:
- Perf/UI-level concern, not LLM output capture.

## Platform / Analytics Maturity Work

20. Run ordinal within session.
[observability_gaps.md:107](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:107)
Why deferred:
- Multi-session analytics feature, not current gap closure.

21. No normalized iteration table.
[observability_gaps.md:110](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:110)
Why deferred:
- Warehouse/queryability improvement, not required to store outputs.

22. No cost estimation metadata.
[observability_gaps.md:111](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:111)
Why deferred:
- Cost analytics, not output persistence.

23. System instruction not stored.
[observability_gaps.md:112](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:112)
Why deferred:
- Input provenance issue; useful, but outside the narrower “capture outputs + REPL code” target.

24. No artifact content hashing.
[observability_gaps.md:113](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:113)
Why deferred:
- Artifact integrity feature, not output observability.

25. No baseline/regression infrastructure.
[observability_gaps.md:114](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:114)
Why deferred:
- Monitoring platform work, not instrumentation gap closure.

## Miscellaneous Telemetry Consistency Issues

26. Parallel dispatch race condition visibility.
[observability_gaps.md:122](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:122)
Why deferred:
- Consistency concern, but not a primary blocker for output capture.

27. Exception-vs-error-value distinction.
[observability_gaps.md:123](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:123)
Why deferred:
- Semantic telemetry cleanup, not raw output persistence.

28. Stale worker token-key concern.
[observability_gaps.md:47](/home/rawley-stanhope/dev/rlm-adk/rlm_adk_docs/observability_gaps.md:47)
Why deferred:
- Appears tied to older worker-key assumptions and not the current child-orchestrator path.
