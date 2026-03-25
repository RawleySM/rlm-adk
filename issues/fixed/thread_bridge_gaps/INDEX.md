# Thread Bridge Gap Audit Index

Audit date: 2026-03-24
Auditors: 5 specialist agents (ADK callback, threading, event-loop, dead-code, observability)

## Summary

55 gaps identified. 1 CRITICAL, 8 HIGH, 15 MEDIUM, 17 LOW (+ 14 duplicates across auditors).

Legend: `[ ]` = OPEN, `[x]` = CLOSED, `[~]` = WONTFIX, `[d]` = DUPLICATE

---

## CRITICAL

| Status | ID | Auditor | Category | Title |
|--------|-----|---------|----------|-------|
| [x] | GAP-DC-009 | dead-code | fixture-integrity | Five broken fixtures not excluded from CI |

## HIGH

| Status | ID | Auditor | Category | Title |
|--------|-----|---------|----------|-------|
| [~] | GAP-TH-001 | threading | threading | IPython singleton shell shared across concurrent worker threads |
| [~] | GAP-TH-002 | threading | threading | `_THREAD_DEPTH` ContextVar doesn't propagate across `run_coroutine_threadsafe` |
| [x] | GAP-TH-003 | threading | threading | `execute_sync` overwrites sys.stdout, destroying `_TaskLocalStream` proxy |
| [x] | GAP-CB-001 | callbacks | callback-lifecycle | `_extract_adk_dynamic_instruction` duplicates conversation history into system_instruction |
| [~] | GAP-EL-001 | event-loop | event-loop | Dangling worker thread after timeout calls `run_coroutine_threadsafe` on closed loop |
| [x] | GAP-EL-004 | event-loop | event-loop | Executor shutdown allows resource leak on timeout with in-flight dispatches |
| [x] | GAP-OB-003 | observability | observability | `execution_mode` not stored in telemetry DB schema |
| [x] | GAP-OB-007 | observability | observability | Trace timing broken on timeout (start_time=0.0 is falsy) |

## MEDIUM

| Status | ID | Auditor | Category | Title |
|--------|-----|---------|----------|-------|
| [x] | GAP-DC-001 | dead-code | dead-code | Dead AST rewrite observability constants in state.py |
| [x] | GAP-DC-002 | dead-code | dead-code | Dead AST rewrite keys in dashboard live_loader.py |
| [x] | GAP-DC-003 | dead-code | dead-code | Dead `execute_async` method in IPythonDebugExecutor |
| [x] | GAP-DC-007 | dead-code | dead-code | Stale documentation references to deleted AST rewriter |
| [x] | GAP-DC-012 | dead-code | dead-code | `_execute_code_inner` and sync `execute_code` unused in production |
| [x] | GAP-DC-013 | dead-code | dead-code | test_skill_arch_e2e.py exists but documented as deleted |
| [x] | GAP-CB-003 | callbacks | callback-lifecycle | `on_model_error_callback` not wired on child reasoning agents |
| [x] | GAP-CB-005 | callbacks | callback-lifecycle | `llm_query_batched` lacks `_THREAD_DEPTH` enforcement |
| [x] | GAP-CB-006 | callbacks | callback-lifecycle | Token accounting double-counts duplicated content |
| [x] | GAP-CB-007 | callbacks | callback-lifecycle | Child events lost when reasoning agent raises in retry loop |
| [x] | GAP-EL-003 | event-loop | event-loop | `CancelledError` type mismatch between `concurrent.futures` and `asyncio` |
| [~] | GAP-EL-005 | event-loop | event-loop | ADK Runner completion leaves orphaned coroutines |
| [x] | GAP-EL-007 | event-loop | event-loop | No loop-aliveness check before `run_coroutine_threadsafe` |
| [d] | GAP-OB-001 | observability | observability | Dead `OBS_REWRITE_*` constants with zero writers |
| [x] | GAP-OB-002 | observability | observability | Dashboard `repl_expanded_code` vestigial empty string |
| [x] | GAP-OB-006 | observability | observability | DataFlowTracker edges overwritten on each batched call |

## LOW

| Status | ID | Auditor | Category | Title |
|--------|-----|---------|----------|-------|
| [~] | GAP-DC-004 | dead-code | dead-code | Obsolete skills directory imports from deleted module |
| [x] | GAP-DC-005 | dead-code | dead-code | Fully commented-out test_catalog_activation.py |
| [x] | GAP-DC-006 | dead-code | dead-code | Legacy fixture files for deleted skill expansion |
| [x] | GAP-DC-008 | dead-code | dead-code | Legacy fixture descriptions reference deleted async path |
| [x] | GAP-DC-010 | dead-code | dead-code | Stale agent_findings reference deleted modules |
| [x] | GAP-DC-011 | dead-code | dead-code | Stale repomix XML snapshots contain deleted source |
| [x] | GAP-DC-014 | dead-code | reward-hack | Thread bridge test doesn't verify bridge path |
| [x] | GAP-DC-015 | dead-code | reward-hack | Orchestrator wiring test asserts callable, not dispatch |
| [x] | GAP-DC-016 | dead-code | reward-hack | Orchestrator import test trivially true |
| [~] | GAP-DC-017 | dead-code | reward-hack | Skill state key tests verify constants, not behavior |
| [x] | GAP-DC-018 | dead-code | reward-hack | Telemetry finalizer tests mock out execute_code_threaded |
| [x] | GAP-DC-019 | dead-code | reward-hack | Skill loader orchestrator tests use incomplete mock |
| [x] | GAP-DC-020 | dead-code | unwired | No test verifies breaking bridge causes failure |
| [~] | GAP-DC-021 | dead-code | unwired | collect_skill_repl_globals None repl_globals edge case |
| [x] | GAP-DC-022 | dead-code | unwired | `_execute_code_inner` and `execute_code` only in tests |
| [~] | GAP-CB-002 | callbacks | callback-lifecycle | Worker callbacks file deletion (verified correct) |
| [~] | GAP-CB-004 | callbacks | callback-lifecycle | `_finalize_telemetry` skipped on pre-execution error |
| [d] | GAP-CB-008 | callbacks | callback-lifecycle | `_THREAD_DEPTH` never accumulates across dispatch |
| [x] | GAP-TH-004 | threading | threading | `__builtins__` dict shared by reference, permanently mutated |
| [~] | GAP-TH-005 | threading | threading | Unbounded thread creation under recursive dispatch |
| [d] | GAP-TH-006 | threading | threading | Orphaned thread after timeout mutates `self.locals` |
| [~] | GAP-TH-007 | threading | threading | `_pending_llm_calls.clear()` race with orphaned child |
| [~] | GAP-TH-008 | threading | threading | `trace_holder`/`REPLTrace` accessed from both threads |
| [d] | GAP-TH-009 | threading | threading | `llm_query_batched` doesn't check `_THREAD_DEPTH` |
| [~] | GAP-TH-010 | threading | threading | `repl.globals` mutations not atomic with lazy reads |
| [d] | GAP-EL-002 | event-loop | event-loop | `_THREAD_DEPTH` doesn't track actual recursive depth |
| [d] | GAP-EL-006 | event-loop | event-loop | `llm_query_batched` in thread bridge lacks depth tracking |
| [x] | GAP-OB-004 | observability | observability | REPLCapturePlugin documents deleted globals |
| [~] | GAP-OB-005 | observability | observability | DataFlowTracker cross-call detection pre-existing limitation |
| [d] | GAP-OB-008 | observability | observability | observability.md documents deleted state keys |

## Cross-Auditor Duplicates

These gaps were independently found by multiple auditors, confirming their validity:

| Primary | Duplicates | Theme |
|---------|-----------|-------|
| GAP-TH-002 | GAP-EL-002, GAP-CB-008 | `_THREAD_DEPTH` ContextVar broken across boundaries |
| GAP-CB-005 | GAP-TH-009, GAP-EL-006 | `llm_query_batched` missing depth check |
| GAP-DC-001 | GAP-OB-001 | Dead `OBS_REWRITE_*` constants |
| GAP-DC-007 | GAP-OB-008 | Stale docs referencing deleted AST rewriter |
| GAP-EL-001 | GAP-TH-006 | Dangling thread after timeout |

## Verified Clean (No Gap)

1. No orphaned imports from deleted modules in production code
2. `load_adk_skills()` IS called by orchestrator
3. `_wrap_with_llm_query_injection()` IS used in collect path
4. `collect_skill_repl_globals()` DOES receive real REPL globals
5. `execute_code_threaded` IS used by REPLTool (old sync path removed)
6. No tests mock `LocalREPL.execute_code` to hide bridge bugs
7. SkillToolset `process_llm_request` ordering is correct (fires BEFORE `before_model_callback`)
8. AR-CRIT-001 has no violations in new code
9. `flush_fn`/`post_dispatch_state_patch_fn` called at right time in all code paths
10. Child event re-emission queue works correctly with thread bridge
11. Langfuse/OTel instruments BaseTool regardless of internal execution path
12. No deadlock: event loop stays free during `run_in_executor`
