# HIGH Gap Verification Report

**Date**: 2026-03-25
**Scope**: All 8 HIGH-priority gaps from the Thread Bridge Gap Audit
**Method**: 8 parallel specialist agents investigated each gap independently, reading source code, tests, and documentation

---

## Executive Summary

| Gap | Claimed | Verdict | Action |
|-----|---------|---------|--------|
| GAP-TH-001 | WONTFIX | DISAGREE | Document the serialization guarantee |
| GAP-TH-002 | WONTFIX | PARTIALLY AGREE | Justified — `max_depth` is the real guard |
| GAP-TH-003 | FIXED | TRULY FIXED | No action needed |
| GAP-CB-001 | WONTFIX | **DISAGREE** | Code still has the bug — demo is premature |
| GAP-EL-001 | WONTFIX | PARTIALLY AGREE | Loop-closed mitigated; orphan scenario unaddressed |
| GAP-EL-004 | WONTFIX | **DISAGREE** | 30s/300s timeout mismatch is a real resource leak |
| GAP-OB-003 | FIXED | TRULY FIXED | No action needed |
| GAP-OB-007 | FIXED | TRULY FIXED | No action needed |

**Bottom line**: 3/3 FIXED gaps are confirmed. 2/5 WONTFIX gaps have legitimate concerns that warrant reopening. 2/5 WONTFIX gaps are partially justified. 1/5 WONTFIX is technically safe but poorly documented.

---

## FIXED Gaps (All Confirmed)

### GAP-TH-003 — `execute_sync` overwrites sys.stdout [TRULY FIXED]

**What was done**: Added `capture_output: bool` parameter to `execute_sync()` in `ipython_executor.py`. When `_TaskLocalStream` proxy is active (production), `capture_output=False` preserves the proxy. When pytest replaces stdout (testing), `capture_output=True` uses StringIO fallback.

**Key files**: `ipython_executor.py` (lines 126-218), `local_repl.py` (lines 370-408)

**Test coverage**: 4 dedicated tests verify both proxy-preserving and StringIO-fallback paths, including a comprehensive async ContextVar routing test.

### GAP-OB-003 — `execution_mode` not in telemetry DB [TRULY FIXED]

**What was done**: Added `execution_mode TEXT` column to schema (`sqlite_tracing.py:225`), migration list (`:408`), and two extraction paths: `after_tool_callback` (`:1340`) and `_finalize` closure (`:502`). REPLTool writes `execution_mode` ("sync" or "thread_bridge") in all 3 return paths (normal, exception, cancelled).

**Test coverage**: 7 dedicated tests in `test_execution_mode_telemetry.py` — all passing. Covers schema, migration, both extraction paths, and all 3 REPLTool return paths.

### GAP-OB-007 — Trace timing broken on timeout [TRULY FIXED]

**What was done**: Changed `REPLTrace.start_time`/`end_time` sentinel from `0.0` (falsy) to `None`. Updated all guards from truthiness (`if self.start_time`) to explicit (`if self.start_time is not None`). Added `trace.end_time = time.perf_counter()` in both sync and threaded timeout handlers plus REPLTool error handlers.

**Test coverage**: 7 test classes with 27+ assertions in `test_repl_trace_timing.py`, including explicit regression tests that document why `0.0` is falsy.

---

## WONTFIX Gaps Requiring Action

### GAP-CB-001 — `_extract_adk_dynamic_instruction` duplicates history [DISAGREE with WONTFIX]

**Finding**: The demo file (`demo_GAP-CB-001.md`) claims the function was deleted and `reasoning_before_model` is now observe-only. **The current code contradicts this** — `_extract_adk_dynamic_instruction()` still exists at `reasoning.py:49-63` and is still called at line 165, with results appended to `system_instruction` via `append_instructions()` at line 171.

**Impact**: On every model call, the entire conversation history (all `llm_request.contents`) is concatenated and duplicated into the system instruction. Token waste escalates with each turn — potentially thousands of wasted tokens in multi-turn interactions.

**Root cause of discrepancy**: Either the fix was never merged, was rolled back, or the demo was written before implementation.

**ADK context**: ADK 1.27's `_add_instructions_to_user_content()` already positions the dynamic instruction correctly. The relocation was a workaround for older ADK versions and is no longer needed.

**Recommendation**: **Reopen as HIGH**. Delete `_extract_adk_dynamic_instruction()` and remove lines 165-171 from `reasoning_before_model()`. Update one test hook and one fixture. Low-risk fix with measurable token savings.

### GAP-EL-004 — Executor shutdown leaks on timeout [DISAGREE with WONTFIX]

**Finding**: A structural timeout mismatch exists between `local_repl.py` (`sync_timeout=30s`, line 506) and `thread_bridge.py` (`timeout=300s`, line 37). When a code block times out at 30s, the orphaned worker thread can still call `llm_query()` with a 300s timeout window — spawning child orchestrators that consume API quota with no observability.

**What's missing**:
- No cancellation token shared between executor and thread bridge
- No tracking of orphaned in-flight futures
- `executor.shutdown(wait=False)` doesn't cancel the running thread
- The `loop.is_closed()` check (GAP-EL-007) only catches one scenario

**Impact**: Orphaned child orchestrators consume API quota invisibly. Each orphan can spawn deeper orphans, creating cascade resource leaks. No logging or observability exists for this path.

**Recommendation**: **Reopen as HIGH**. Minimum fix: align timeouts so thread bridge timeout <= parent sync_timeout. Better fix: share a `threading.Event` cancellation flag between executor and thread bridge closures.

---

## WONTFIX Gaps With Justified Rationale

### GAP-TH-002 — `_THREAD_DEPTH` ContextVar broken across threads [PARTIALLY AGREE]

**Finding**: The ContextVar genuinely doesn't propagate across `run_in_executor` boundaries — each worker thread resets to 0. However, `dispatch.py`'s `max_depth` parameter (line 281) is the **real** recursion guard. It uses integer parameters passed through closures, not ContextVars, and correctly accumulates across all thread boundaries.

**Real risk**: LOW. The system is protected against infinite recursion by `max_depth`. `_THREAD_DEPTH` is a secondary defense-in-depth guard that only catches within-thread recursion (e.g., a skill calling itself).

**Recommendation**: WONTFIX is acceptable. Optionally add a code comment explaining the design assumption. A one-line fix (`ctx = contextvars.copy_context(); ctx.run(...)`) exists but provides minimal real-world benefit.

### GAP-EL-001 — Dangling thread after timeout [PARTIALLY AGREE]

**Finding**: Two scenarios exist:
1. **Loop closed** (Runner finished): FIXED by GAP-EL-007's `loop.is_closed()` check — clean RuntimeError raised.
2. **Loop still running** (normal timeout): NOT mitigated — orphaned thread can call `llm_query()` successfully, spawning invisible child orchestrators.

**Real risk**: MEDIUM for scenario 2. Low probability (requires long-running REPL code + `llm_query()` call after timeout), but impact is silent API quota consumption with no observability.

**Recommendation**: WONTFIX is partially acceptable because scenario 2 is low-probability. However, the INDEX should distinguish the two scenarios and note that only scenario 1 is mitigated. Overlaps significantly with GAP-EL-004.

### GAP-TH-001 — IPython singleton shared across threads [TECHNICALLY SAFE]

**Finding**: The agent found the risk **does not manifest in practice** because:
1. Each child orchestrator creates its own `LocalREPL` → `IPythonDebugExecutor`
2. `asyncio.gather` runs children asynchronously on the event loop thread, not in parallel worker threads
3. The thread bridge blocks the parent REPL thread until the child completes
4. Children never execute their IPython `run_cell()` concurrently

**Real risk**: LOW currently. The safety depends on the async serialization model — if children ever ran in parallel worker threads, the race condition would instantly materialize.

**Recommendation**: WONTFIX is acceptable but the safety invariant should be documented in a code comment in `ipython_executor.py`. No tests currently verify the serialization guarantee.

---

## Recommendations Summary

### Immediate Action Required (2 gaps)

1. **GAP-CB-001**: Reopen. Delete `_extract_adk_dynamic_instruction()` and lines 165-171 in `reasoning_before_model()`. ~10 lines changed, 1 test fixture update. Stops escalating token waste.

2. **GAP-EL-004**: Reopen. Align thread bridge timeout to `<= sync_timeout`. Add `threading.Event` cancellation flag. Prevents orphaned child orchestrator API quota leaks.

### Documentation Improvements (3 gaps)

3. **GAP-TH-001**: Add code comment in `ipython_executor.py` documenting the serialization safety invariant.

4. **GAP-TH-002**: Add code comment in `thread_bridge.py` explaining that `_THREAD_DEPTH` is secondary to `max_depth`.

5. **GAP-EL-001**: Update INDEX to distinguish the two scenarios (loop-closed = fixed, loop-running = accepted risk).

### No Action Needed (3 gaps)

6. **GAP-TH-003**: Truly fixed with comprehensive tests.
7. **GAP-OB-003**: Truly fixed with 7 passing tests.
8. **GAP-OB-007**: Truly fixed with 27+ assertions.
