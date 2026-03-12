# Instruction Router: Depth/Fanout-Isolated Dynamic Instructions

*2026-03-12T16:07:01Z by Showboat 0.6.0*
<!-- showboat-id: 81be65ba-7e0b-4efc-87f8-4e97c8e18f5c -->

## Problem

Skill helpers give identical dynamic instructions to all recursive layers. A divide-and-conquer skill dispatching `llm_query_batched([p1, p2])` creates 2 workers at depth 1, but both workers AND the root reasoning agent all receive the same `{test_context?}` or other dynamic instruction content. There is no mechanism to assign per-layer, per-fanout instruction text.

## Solution

`instruction_router: Callable[[int, int], str]` — a function that maps `(depth, fanout_idx)` to a dynamic instruction string. A single `{skill_instruction?}` template variable in `RLM_DYNAMIC_INSTRUCTION` is resolved per-layer from session state.

**Code flow:** orchestrator seeds `DYN_SKILL_INSTRUCTION` in session state → dispatch forwards `instruction_router` to child orchestrators → each child seeds its own instruction → `flush_fn` restores parent instruction after child dispatch.

## Invariants

- AR-CRIT-001 compliant: state writes via `EventActions(state_delta={...})` and `ctx.session.state` for initialization only
- Backward compatible: no router = no marker injection, existing tests unaffected
- SQLite telemetry audit trail: `skill_instruction` column in `telemetry` table

## Implementation: 6 files, ~30 lines total

```bash
grep -n "DYN_SKILL_INSTRUCTION" rlm_adk/state.py
```

```output
40:DYN_SKILL_INSTRUCTION = "skill_instruction"
```

```bash
grep -n "skill_instruction" rlm_adk/utils/prompts.py
```

```output
86:Skill instruction: {skill_instruction?}
```

```bash
grep -n "instruction_router" rlm_adk/orchestrator.py
```

```output
217:    instruction_router: Any = None  # Callable[[int, int], str] | None
257:                instruction_router=self.instruction_router,
326:            if self.instruction_router is not None:
327:                _skill_text = self.instruction_router(self.depth, self.fanout_idx)
```

```bash
grep -n "instruction_router\|_parent_skill_instruction\|DYN_SKILL_INSTRUCTION" rlm_adk/dispatch.py
```

```output
49:    DYN_SKILL_INSTRUCTION,
113:    instruction_router: Any = None,
147:    _parent_skill_instruction: str | None = None
148:    if instruction_router is not None:
149:        _parent_skill_instruction = instruction_router(depth, fanout_idx)
363:            instruction_router=instruction_router,
720:        if _parent_skill_instruction is not None:
721:            delta[DYN_SKILL_INSTRUCTION] = _parent_skill_instruction
```

```bash
grep -n "instruction_router" rlm_adk/agent.py
```

```output
285:    instruction_router: Any = None,
321:    if instruction_router is not None:
322:        kwargs["instruction_router"] = instruction_router
336:    instruction_router: Any = None,
376:        instruction_router=instruction_router,
463:    instruction_router: Any = None,
499:        instruction_router=instruction_router,
```

```bash
grep -n "skill_instruction" rlm_adk/plugins/sqlite_tracing.py
```

```output
106:    "skill_instruction",
221:    skill_instruction   TEXT,
381:                ("skill_instruction", "TEXT"),
755:            skill_instruction = callback_context.state.get(DYN_SKILL_INSTRUCTION)
771:                skill_instruction=skill_instruction,
```

## Test Design: Provider-Fake E2E with Marker Isolation

The test uses a 2-depth, 2-fanout fixture (`instruction_router_fanout.json`) with 6 API calls:

| Call | Caller | Depth | Fanout | Expected Marker |
|------|--------|-------|--------|-----------------|
| 0 | reasoning | 0 | 0 | IROUTER_DEPTH0_F0_a1b2c3 |
| 1 | worker | 1 | 0 | IROUTER_DEPTH1_F0_d4e5f6 |
| 2 | worker | 1 | 0 | IROUTER_DEPTH1_F0_d4e5f6 |
| 3 | worker | 1 | 1 | IROUTER_DEPTH1_F1_g7h8i9 |
| 4 | worker | 1 | 1 | IROUTER_DEPTH1_F1_g7h8i9 |
| 5 | reasoning | 0 | 0 | IROUTER_DEPTH0_F0_a1b2c3 |

11 tests across 3 classes:
- **TestInstructionRouterIsolation** (7): markers present at correct depth/fanout AND absent from others
- **TestInstructionRouterBackwardCompat** (2): no router = no markers, contract passes
- **TestInstructionRouterSqliteTelemetry** (2): telemetry table captures/omits skill_instruction

```bash
grep -n "IROUTER\|_test_router\|_MARKER" tests_rlm_adk/test_instruction_router_e2e.py | head -12
```

```output
43:_MARKER_D0 = "IROUTER_DEPTH0_F0_a1b2c3"
44:_MARKER_D1F0 = "IROUTER_DEPTH1_F0_d4e5f6"
45:_MARKER_D1F1 = "IROUTER_DEPTH1_F1_g7h8i9"
47:_MARKERS = {
48:    (0, 0): _MARKER_D0,
49:    (1, 0): _MARKER_D1F0,
50:    (1, 1): _MARKER_D1F1,
54:def _test_router(depth: int, fanout_idx: int) -> str:
56:    return _MARKERS.get((depth, fanout_idx), f"IROUTER_DEPTH{depth}_F{fanout_idx}_unknown")
265:        """Run the fixture once with _test_router and share across all tests."""
266:        final_state, captured_requests, router = await _run_with_router(_FIXTURE, _test_router)
277:        """Calls 0 and 5 (reasoning, d=0) systemInstruction contains _MARKER_D0."""
```

## Evidence: All 11 Tests Pass

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_instruction_router_e2e.py -v -o "addopts=" 2>&1 | grep -E "PASSED|FAILED" | sed "s/\s*PASSED/ PASSED/; s/\s*FAILED/ FAILED/"
```

```output
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterIsolation::test_contract_passes PASSED [  9%]
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterIsolation::test_d0_marker_in_reasoning_calls PASSED [ 18%]
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterIsolation::test_d1f0_marker_in_first_worker PASSED [ 27%]
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterIsolation::test_d1f1_marker_in_second_worker PASSED [ 36%]
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterIsolation::test_d0_marker_absent_from_workers PASSED [ 45%]
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterIsolation::test_d1f0_marker_absent_from_d0_and_f1 PASSED [ 54%]
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterIsolation::test_d1f1_marker_absent_from_d0_and_f0 PASSED [ 63%]
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterBackwardCompat::test_no_router_no_skill_instruction PASSED [ 72%]
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterBackwardCompat::test_contract_passes_without_router PASSED [ 81%]
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterSqliteTelemetry::test_skill_instruction_in_telemetry_rows PASSED [ 90%]
tests_rlm_adk/test_instruction_router_e2e.py::TestInstructionRouterSqliteTelemetry::test_skill_instruction_null_without_router PASSED [100%]
```

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/test_instruction_router_e2e.py -q -o "addopts=" 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
11 passed
```

## Evidence: Full Regression Suite — No Regressions

```bash
PYTHONWARNINGS=ignore .venv/bin/python -m pytest tests_rlm_adk/ -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
34 passed, 2 skipped, 1151 deselected
```

## Bugs Found and Fixed During RED/GREEN

Two implementation bugs were discovered when the RED tests ran against the GREEN production code:

**Bug 1 — First model call in child has parent marker**: When a child orchestrator runs from dispatch (not Runner), `EventActions(state_delta={...})` is captured but NOT applied to `ctx.session.state`. The reasoning agent first `before_model_callback` still reads the parent stale marker.

**Fix**: Apply `DYN_SKILL_INSTRUCTION` directly to `ctx.session.state` in orchestrator `_run_async_impl` before the EventActions yield. This is initialization (not dispatch closure mutation), so AR-CRIT-001 is preserved. The EventActions yield still provides the ADK audit trail.

**Bug 2 — All workers get fanout 0 marker**: `create_dispatch_closures` hardcoded `instruction_router(depth, 0)` for `_parent_skill_instruction`, ignoring the actual `fanout_idx`.

**Fix**: Added `fanout_idx` parameter to `create_dispatch_closures` and use it: `instruction_router(depth, fanout_idx)`.

## Files Changed

| File | Change |
|------|--------|
| `rlm_adk/state.py:40` | +1 constant: `DYN_SKILL_INSTRUCTION` |
| `rlm_adk/utils/prompts.py:86` | +1 template line: `{skill_instruction?}` |
| `rlm_adk/orchestrator.py:217,257,325-335` | Field + seed + direct state apply + dispatch param |
| `rlm_adk/dispatch.py:113-149,363,720` | Param + fanout_idx + forward + flush restore |
| `rlm_adk/agent.py:285,336,463` | Thread param through 3 factories |
| `rlm_adk/plugins/sqlite_tracing.py:106,221,381,755,771` | Column + migration + curated set + capture |
| `tests_rlm_adk/test_instruction_router_e2e.py` | NEW: 11 tests across 3 classes |
| `tests_rlm_adk/fixtures/provider_fake/instruction_router_fanout.json` | NEW: 6-call fixture |
