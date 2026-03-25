# Polya Understand Phase: GAP-OB-007 -- Trace Timing Broken on Timeout

## 1. Problem Restatement

`REPLTrace` uses `0.0` as the default sentinel for `start_time` and `end_time`. Because `0.0` is falsy in Python, every truthiness guard (`if trace.start_time`, `if trace.start_time and trace.end_time`) silently treats a legitimately-initialized-to-zero timestamp as "not set." This causes two classes of failure:

1. **Timeout paths never record `end_time`**: When `execute_code_threaded` or `execute_code` times out, no handler sets `trace.end_time`, so the trace reports `wall_time_ms: 0` for an execution that actually consumed `sync_timeout` seconds.
2. **Error-path guards skip timing repair**: `REPLTool`'s `CancelledError` and generic `Exception` handlers check `if trace.start_time and not trace.end_time` before setting `end_time`. When `start_time` is `0.0` (worker thread never ran the trace callback), the guard is falsy and the repair is skipped.

Additionally, when IPython is unavailable (`self._shell is None`), trace callbacks are never registered at all, leaving `start_time` and `end_time` permanently at `0.0` even for successful executions.

The net effect: trace `wall_time_ms` is silently zero in timeout, cancellation, early-failure, and IPython-fallback scenarios -- precisely the cases where observability matters most.

## 2. Exact Objective

Change the `REPLTrace` sentinel representation and all downstream guards so that:

- `wall_time_ms` correctly reflects actual elapsed time on all execution paths (success, timeout, cancellation, exception, IPython fallback).
- The sentinel for "not yet set" is unambiguously distinguishable from "set at time zero" (which is impossible for `time.perf_counter()` but is the current default).
- Timeout handlers explicitly record `end_time` before returning.
- No behavioral regression in the normal (non-timeout, non-error) path.

## 3. Knowns / Givens

### Data

| # | Given | Source |
|---|-------|--------|
| D1 | `REPLTrace.start_time: float = 0.0` and `end_time: float = 0.0` | `rlm_adk/repl/trace.py:25-26` |
| D2 | `wall_time_ms` computation: `round(max(0, self.end_time - self.start_time) * 1000, 2) if self.start_time and self.end_time else 0` | `trace.py:95,110` |
| D3 | IPython callbacks set `trace.start_time` / `trace.end_time` via `pre_run_cell` / `post_run_cell` | `ipython_executor.py:342-355` |
| D4 | Callbacks only registered when `self._shell is not None` | `ipython_executor.py:357-359` |
| D5 | `TRACE_HEADER` / `TRACE_HEADER_MEMORY` strings (code injection path) also set `start_time` / `end_time` | `trace.py:161-201` |
| D6 | `execute_code_threaded` TimeoutError handler does NOT set `trace.end_time` | `local_repl.py:461-467` |
| D7 | `execute_code` (sync) TimeoutError handler does NOT set `trace.end_time` | `local_repl.py:409-419` |
| D8 | `REPLTool` CancelledError guard: `if trace is not None and trace.start_time and not trace.end_time` | `repl_tool.py:195` |
| D9 | `REPLTool` generic Exception guard: same pattern | `repl_tool.py:227` |
| D10 | Trace callbacks are registered only when `trace_level >= 1` (env `RLM_REPL_TRACE`) | `local_repl.py:289,355` |
| D11 | `REPLResult` includes `trace=trace.to_dict() if trace else None` | `local_repl.py:430,477` |
| D12 | Prior related bug: negative `wall_time_ms` on failed runs already fixed with `max(0, ...)` clamp | `issues/bug-negative-repl-wall-time-on-failed-runs.md` |
| D13 | `LLMResult.wall_time_ms` is a separate field on the worker dispatch result (not the same as `REPLTrace.wall_time_ms`) | `types.py:117` |

### Rules

- `time.perf_counter()` returns a monotonically increasing float. Its absolute value has no defined epoch, but values are always positive and always increasing within a process.
- Python truthiness: `0.0` is falsy, `None` is falsy, any positive float is truthy.
- `REPLTrace` is a `@dataclass` -- changing field types from `float` to `float | None` requires updating the type annotation and default, plus all consumers that do arithmetic on the fields.

### Context

- Trace data feeds into `LAST_REPL_RESULT` (session state for observability), `repl_traces.json` (artifact), sqlite telemetry (`repl_trace_summary` column), and downstream dashboard/analysis.
- The thread bridge is the primary execution path after the Plan B migration. `execute_code_threaded` is the hot path; `execute_code` (sync) is legacy but still used in tests.

## 4. Unknowns

| # | Unknown | Relationship to Givens |
|---|---------|----------------------|
| U1 | Exact set of all `if trace.start_time` / `if trace.end_time` truthiness guards across the codebase | Derived from D2, D8, D9 but may exist in other files |
| U2 | Whether any downstream consumer performs arithmetic on `start_time` / `end_time` directly (not via `wall_time_ms`) | Must grep for `trace.start_time` and `trace.end_time` usage beyond the known locations |
| U3 | Whether the `TRACE_HEADER` / `TRACE_FOOTER` code-injection strings (D5) are still used anywhere, or if callback-based tracing fully replaced them | If still used, the injected code also needs the sentinel change |
| U4 | Whether `trace_level == 0` (default) is the common case in production, meaning trace callbacks are never registered and timing is always `0.0` | If so, the fix must also handle the `trace_level == 0` case or accept that `wall_time_ms` is only meaningful when `trace_level >= 1` |
| U5 | Whether the `exec()` fallback path (when `self._shell is None`) is reachable in production or only in degraded/test environments | Determines whether defect 7 matters in practice |
| U6 | Whether any serialization path (JSON, sqlite) breaks if `start_time` / `end_time` become `None` instead of `0.0` | `to_dict()` and `summary()` produce `wall_time_ms`, not raw timestamps, so likely safe -- but must verify no other serializer touches the raw fields |

### Resolution of Unknowns (from code reading)

- **U1**: Confirmed -- only 4 truthiness guards exist: `trace.py:95`, `trace.py:110`, `repl_tool.py:195`, `repl_tool.py:227`. All are identified in the 7-defect list.
- **U2**: No code outside `trace.py` does arithmetic on `start_time`/`end_time` directly. The `TRACE_HEADER`/`TRACE_FOOTER` strings write to them, and `to_dict()`/`summary()` read them. `repl_tool.py` writes `end_time` but never reads `start_time` for arithmetic.
- **U3**: `TRACE_HEADER` / `TRACE_FOOTER` strings are defined in `trace.py` but the callback-based approach in `ipython_executor.py` replaced them. They remain as dead-code constants. The fix should update them for correctness but they are not on the active execution path.
- **U4**: When `trace_level == 0`, trace callbacks are not registered. However, `REPLTool` still creates a `REPLTrace` object (D10 notwithstanding -- REPLTool creates the trace unconditionally when `self.trace_holder is not None`). So `trace` exists but `start_time`/`end_time` remain at `0.0` -- the sentinel fix ensures `wall_time_ms` correctly reports `0` (via `is not None` guard) rather than accidentally computing a value.
- **U5**: The `exec()` fallback is reachable when IPython fails to initialize. It is a degraded path but not impossible in CI or constrained environments.
- **U6**: `to_dict()` and `summary()` are the only serialization points. They output `wall_time_ms` (computed float), not raw `start_time`/`end_time`. Changing the sentinel to `None` has no serialization impact.

## 5. Definitions / Clarified Terms

| Term | Meaning in this context |
|------|------------------------|
| `wall_time_ms` | End-to-end elapsed time for a single REPL code block execution, in milliseconds. Computed from `(end_time - start_time) * 1000`. |
| `start_time` / `end_time` | Monotonic timestamps from `time.perf_counter()`. Not wall-clock timestamps. |
| `trace_level` | Integer 0-2 from env `RLM_REPL_TRACE`. Level 0 = no callbacks registered. Level 1 = timing + var snapshots. Level 2 = + tracemalloc. |
| `sentinel` | The default value that means "not yet set." Currently `0.0` (falsy). Proposed: `None`. |
| `thread bridge` | The `execute_code_threaded` path where REPL code runs in a worker thread and `llm_query()` calls dispatch back to the event loop via `run_coroutine_threadsafe`. |
| `exec fallback` | The `exec(code, namespace, namespace)` path in `ipython_executor.py:189` when IPython shell is unavailable (`self._shell is None`). |
| `truthiness guard` | A Python `if x` test that relies on the implicit bool conversion of `x`. Fails for `x == 0.0` because `bool(0.0)` is `False`. |

## 6. Constraints

### AR-CRIT-001 (State Mutation Rules)
- This fix does NOT touch session state mutation. `REPLTrace` is a local dataclass, not session state. The `wall_time_ms` value flows into session state only through `LAST_REPL_RESULT` in `repl_tool.py`, which already uses `tool_context.state[key] = value` (compliant). No constraint violation.

### Thread Safety
- `REPLTrace` is created per-`execute_code` call and is not shared across threads except between the worker thread (which writes `start_time`/`end_time`) and the event loop thread (which reads them after the worker completes or times out). The timeout handler in `execute_code_threaded` runs on the event loop thread after `asyncio.wait_for` raises `TimeoutError`, at which point the worker thread may still be running. Writing `trace.end_time` from the timeout handler is a data race in the strict sense, but:
  - The worker thread may or may not have set `end_time` yet.
  - The timeout handler's value (`time.perf_counter()` at timeout) is the correct value for the timeout case.
  - Python's GIL makes float assignment atomic.
  - The `executor.shutdown(wait=False)` call means the worker thread is abandoned, so its subsequent writes (if any) are harmless -- the trace is serialized immediately after the timeout handler.

### Backward Compatibility
- Changing `start_time: float = 0.0` to `start_time: float | None = None` changes the field type. Any code that does `trace.start_time + something` without a None check will raise `TypeError`. All such arithmetic is in `to_dict()` and `summary()` which already have guards -- but those guards must be updated from `if self.start_time` to `if self.start_time is not None`.
- The `TRACE_HEADER` / `TRACE_FOOTER` string constants (dead code) assign `_rlm_trace.start_time = _rlm_time.perf_counter()`. These still work with `float | None` type since the assigned value is always a float. No change needed there.
- `wall_time_ms` output value `0` (when timing is not recorded) is preserved. The fix changes the guard, not the fallback value.

### Scope
- **In scope**: Sentinel change, guard fixes, timeout handler additions (7 defect locations).
- **Out of scope**: Changing `trace_level` defaults, adding new trace fields, modifying sqlite schema, changing `LLMResult.wall_time_ms` (separate concern).

## 7. Facts vs Assumptions

### Confirmed Facts

1. `0.0` is falsy in Python -- `bool(0.0) is False`.
2. `time.perf_counter()` never returns exactly `0.0` in practice (it measures time since an arbitrary reference point, typically process start or system boot).
3. The `TimeoutError` handler in `execute_code_threaded` (line 461) does not set `trace.end_time`.
4. The `TimeoutError` handler in `execute_code` (line 409) does not set `trace.end_time`.
5. The `CancelledError` and `Exception` guards in `repl_tool.py` (lines 195, 227) use truthiness checks that fail when `start_time == 0.0`.
6. IPython trace callbacks are only registered when `self._shell is not None` AND `trace_level >= 1`.
7. The prior negative-wall-time bug was fixed by adding `max(0, ...)` clamp, but the root cause (falsy sentinel) was not addressed.
8. `REPLTrace` is a standard Python dataclass, not a Pydantic model.

### Assumptions

1. **No external consumer reads `start_time`/`end_time` raw fields.** Verified by grep -- only `trace.py` methods and `repl_tool.py` guards access them. SAFE assumption.
2. **The `TRACE_HEADER`/`TRACE_FOOTER` constants are dead code.** They are defined but the callback-based approach replaced their usage. If they are ever re-enabled, they would still work correctly since they assign float values. LOW RISK assumption.
3. **`trace_level == 0` is the production default.** Env var `RLM_REPL_TRACE` defaults to `"0"`. This means in default config, `start_time` and `end_time` are never set by callbacks, and `wall_time_ms` is always `0`. The sentinel fix does not change this behavior -- it just makes the `0` result intentional (None sentinel) rather than accidental (falsy guard). CONFIRMED assumption.
4. **The worker thread does not write to `trace.end_time` after the timeout handler does.** In practice the GIL + immediate serialization makes this safe, but it is not formally guaranteed. ACCEPTABLE RISK assumption.

## 8. Representation: Defect Map

```
REPLTrace dataclass (trace.py)
  start_time: float = 0.0  ← DEFECT 1: falsy sentinel
  end_time:   float = 0.0  ← DEFECT 1: falsy sentinel
  │
  ├─ to_dict()   → if self.start_time and self.end_time  ← DEFECT 2: falsy guard
  └─ summary()   → if self.start_time and self.end_time  ← DEFECT 2: falsy guard

Execution paths that set start_time/end_time:
  ┌─────────────────────────────────────────────────────────────────┐
  │ ipython_executor.register_trace_callbacks()                     │
  │   _pre_run_cell  → trace.start_time = perf_counter()           │
  │   _post_run_cell → trace.end_time   = perf_counter()           │
  │   BUT: only registered when self._shell is not None             │
  │         ← DEFECT 7: exec() fallback leaves times at 0.0/None   │
  └─────────────────────────────────────────────────────────────────┘

Timeout paths that SHOULD set end_time but DON'T:
  ┌─────────────────────────────────────────────────────────────────┐
  │ local_repl.execute_code_threaded()                              │
  │   except TimeoutError:                                          │
  │     # trace.end_time never set  ← DEFECT 3                     │
  │                                                                 │
  │ local_repl.execute_code()                                       │
  │   except concurrent.futures.TimeoutError:                       │
  │     # trace.end_time never set  ← DEFECT 4                     │
  └─────────────────────────────────────────────────────────────────┘

Error-recovery guards in REPLTool that use falsy checks:
  ┌─────────────────────────────────────────────────────────────────┐
  │ repl_tool.py CancelledError handler:                            │
  │   if trace.start_time and not trace.end_time  ← DEFECT 5       │
  │                                                                 │
  │ repl_tool.py Exception handler:                                 │
  │   if trace.start_time and not trace.end_time  ← DEFECT 6       │
  └─────────────────────────────────────────────────────────────────┘
```

## 9. Problem Type Classification

**Sentinel-value design defect causing silent data corruption in observability infrastructure.**

This is a classic instance of the "zero is a valid value but also the sentinel" anti-pattern. The fix is a type-level correction (changing the sentinel from an in-band value to an out-of-band value) combined with missing error-path coverage (timeout handlers that fail to record timing).

It is NOT a concurrency bug, NOT a state mutation bug, NOT an architectural issue. It is a data-representation defect with localized, mechanical fixes.

## 10. Edge Cases / Toy Examples

| Case | start_time | end_time | Current wall_time_ms | Correct wall_time_ms |
|------|-----------|----------|---------------------|---------------------|
| Normal execution, trace_level >= 1 | 1234.5 | 1234.9 | 400.0 | 400.0 (no change) |
| Normal execution, trace_level == 0 | 0.0 (now None) | 0.0 (now None) | 0 | 0 (no change) |
| Timeout after 30s, trace callback fired before timeout | 1234.5 | 0.0 (now None) | 0 (falsy guard) | ~30000.0 (timeout handler sets end_time) |
| Timeout after 30s, trace callback never fired | 0.0 (now None) | 0.0 (now None) | 0 | 0 (correctly: timing never started) |
| CancelledError, start_time was set | 1234.5 | 0.0 (now None) | 0 (falsy guard skips repair) | ~N ms (REPLTool guard now fires) |
| CancelledError, start_time was never set | 0.0 (now None) | 0.0 (now None) | 0 | 0 (correctly: no timing to repair) |
| exec() fallback (no IPython), trace_level >= 1 | 0.0 (now None) | 0.0 (now None) | 0 | 0 (known limitation; callbacks not registered) |

## 11. Well-Posedness Judgment

**Well-posed.** The problem is fully specified:

- All 7 defect locations are identified with exact file paths and line numbers.
- The root cause (falsy sentinel) is understood mechanically.
- The fix (change sentinel to `None`, update guards, add timeout handler end_time writes) is deterministic.
- No external dependencies, no ambiguous requirements, no missing information.
- The fix is purely internal to the tracing infrastructure with no ADK API surface changes.

## 12. Success Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| S1 | `REPLTrace.start_time` and `end_time` default to `None`, not `0.0` | Read `trace.py` field definitions |
| S2 | `to_dict()` and `summary()` use `is not None` guards, not truthiness | Read `trace.py:95,110` |
| S3 | `execute_code_threaded` TimeoutError handler sets `trace.end_time` | Read `local_repl.py` timeout handler |
| S4 | `execute_code` TimeoutError handler sets `trace.end_time` | Read `local_repl.py` timeout handler |
| S5 | `REPLTool` CancelledError guard uses `is not None` | Read `repl_tool.py:195` |
| S6 | `REPLTool` Exception guard uses `is not None` | Read `repl_tool.py:227` |
| S7 | `wall_time_ms > 0` when a timeout occurs and `start_time` was set by the trace callback | Unit test: create trace, set start_time, simulate timeout, verify wall_time_ms > 0 |
| S8 | `wall_time_ms == 0` when trace_level == 0 (no callbacks registered, start_time remains None) | Unit test: create trace with defaults, verify wall_time_ms == 0 |
| S9 | No regression: normal execution with trace_level >= 1 still produces correct positive wall_time_ms | Existing test suite passes |
| S10 | Type annotation `float | None` on both fields | Read `trace.py` type hints |
| S11 | `TRACE_HEADER` / `TRACE_FOOTER` constants (if still present) remain compatible | Inspect string constants |

## 13. Operational Problem Statement

**Given** a `REPLTrace` dataclass with `start_time` and `end_time` fields that default to `0.0` (falsy in Python), and 5 code locations that use truthiness guards to check whether these fields have been set:

**Change** the sentinel value from `0.0` to `None` (`float | None = None`), update all 4 truthiness guards to explicit `is not None` checks, and add `trace.end_time = time.perf_counter()` writes in both `TimeoutError` handlers (`execute_code_threaded` line 461 and `execute_code` line 409).

**Such that** `wall_time_ms` correctly reports actual elapsed time on timeout/error paths, correctly reports `0` when timing was never started, and introduces no behavioral change on the normal (non-error, non-timeout) execution path.

**Files to modify (7 defect locations across 4 files):**

1. `rlm_adk/repl/trace.py:25-26` -- change defaults to `None`, update type to `float | None`
2. `rlm_adk/repl/trace.py:95` -- change guard in `to_dict()` to `is not None`
3. `rlm_adk/repl/trace.py:110` -- change guard in `summary()` to `is not None`
4. `rlm_adk/repl/local_repl.py:461-467` -- add `trace.end_time = time.perf_counter()` in `execute_code_threaded` TimeoutError handler
5. `rlm_adk/repl/local_repl.py:409-419` -- add `trace.end_time = time.perf_counter()` in `execute_code` TimeoutError handler
6. `rlm_adk/tools/repl_tool.py:195` -- change `trace.start_time` truthiness to `trace.start_time is not None`
7. `rlm_adk/tools/repl_tool.py:227` -- change `trace.start_time` truthiness to `trace.start_time is not None`
