<!-- generated: 2026-03-18 -->
<!-- source: voice transcription via voice-to-prompt skill -->
<!-- plan-review: confirmed wiggly-seeking-narwhal.md approach — all line numbers verified -->
# Fix _rlm_state Snapshot Staleness: Cumulative Dispatch Counters

## Context

The `_rlm_state` dict injected into REPL globals shows stale/oscillating values for dispatch observability keys. `flush_fn()` in `rlm_adk/dispatch.py` resets per-iteration accumulators after each REPL turn, so dashboards see `1→0→1→0` instead of a monotonically increasing count. Additionally, on the first REPL turn, dispatch keys are entirely ABSENT because no flush has occurred yet. The fix adds cumulative (non-resetting) counters parallel to the existing per-iteration ones — purely additive, no breaking changes.

## Original Transcription

> review the plan in ~/.claude/plans/wiggly-seeking-narwhal.md, review code, confirm or reject the approach and generate plan for red/green tdd implication. Reminder, you are taking this transcription and the references and packaging into a prompt for a coding agent. You are NOT to actually implement the changes

## Plan Review Verdict: CONFIRMED

The approach in `wiggly-seeking-narwhal.md` is correct and complete:

- **Root cause diagnosis** is accurate: `flush_fn()` resets `_acc_child_dispatches = 0` (line 806 of `dispatch.py`) after every REPL turn.
- **Why timing doesn't help**: The `_rlm_state` snapshot is built from `tool_context.state` BEFORE code execution (line 186 of `repl_tool.py`), so code can never see its own iteration's post-execution values. The fix must be in the state VALUES, not the snapshot timing.
- **Additive cumulative counters** is the right pattern: new `_total` keys that never reset, existing per-iteration keys keep exact same semantics.
- **No cumulative latency list** is correct (unbounded growth concern).
- **Seeding scalars in `initial_state`** prevents ABSENT on turn 1. Not seeding `error_counts_total` (dict) is intentional — absent means "no errors ever."
- All line numbers in the plan verified against current source.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn a `State-Constants` teammate to add 4 new cumulative key constants to `rlm_adk/state.py` and register the scalar ones in `EXPOSED_STATE_KEYS`.**

   After the existing child dispatch obs keys (line 101), add:
   ```python
   OBS_CHILD_DISPATCH_COUNT_TOTAL = "obs:child_dispatch_count_total"
   OBS_CHILD_BATCH_DISPATCHES_TOTAL = "obs:child_batch_dispatches_total"
   OBS_CHILD_ERROR_COUNTS_TOTAL = "obs:child_error_counts_total"
   OBS_STRUCTURED_OUTPUT_FAILURES_TOTAL = "obs:structured_output_failures_total"
   ```
   Add `OBS_CHILD_DISPATCH_COUNT_TOTAL`, `OBS_CHILD_BATCH_DISPATCHES_TOTAL`, and `OBS_STRUCTURED_OUTPUT_FAILURES_TOTAL` to `EXPOSED_STATE_KEYS` (line 154). Do NOT add `OBS_CHILD_ERROR_COUNTS_TOTAL` (dict-valued, not suitable for flat snapshot).

   **Constraint:** Do not modify any existing constants or their positions. Import order must remain alphabetical within the existing group.

2. **Spawn a `Dispatch-Accumulators` teammate to add cumulative accumulators to `rlm_adk/dispatch.py` and wire them into `flush_fn()`.**

   In `create_dispatch_closures()`, after the existing accumulators (lines 200-206), add:
   ```python
   _cum_child_dispatches = 0
   _cum_child_batch_dispatches = 0
   _cum_child_error_counts: dict[str, int] = {}
   _cum_structured_output_failures = 0
   ```

   Increment at the same code sites as per-iteration counterparts:
   - Lines 724-725 (`_acc_child_dispatches += k`): also `_cum_child_dispatches += k`
   - Line 727 (`_acc_child_batch_dispatches += 1`): also `_cum_child_batch_dispatches += 1`
   - Line 751 area (error accumulation loop): also `_cum_child_error_counts[cat] = _cum_child_error_counts.get(cat, 0) + 1`
   - Lines 466, 485, 508 (`_acc_structured_output_failures += 1`): also `_cum_structured_output_failures += 1`

   In `flush_fn()` (after line 799, before the reset block at line 806), write cumulative values with NO reset:
   ```python
   delta[OBS_CHILD_DISPATCH_COUNT_TOTAL] = _cum_child_dispatches
   if _cum_child_batch_dispatches > 0:
       delta[OBS_CHILD_BATCH_DISPATCHES_TOTAL] = _cum_child_batch_dispatches
   if _cum_child_error_counts:
       delta[OBS_CHILD_ERROR_COUNTS_TOTAL] = dict(_cum_child_error_counts)
   if _cum_structured_output_failures > 0:
       delta[OBS_STRUCTURED_OUTPUT_FAILURES_TOTAL] = _cum_structured_output_failures
   ```

   **Constraint:** AR-CRIT-001 compliance — cumulative accumulators are closure-local variables, written to `tool_context.state` only via `flush_fn()` → REPLTool. Never write to `ctx.session.state` directly.

3. **Spawn a `Orchestrator-Seed` teammate to seed cumulative counters in `rlm_adk/orchestrator.py` initial state.**

   Extend the `initial_state` dict (line 322) so cumulative keys are present from turn 1:
   ```python
   OBS_CHILD_DISPATCH_COUNT_TOTAL: 0,
   OBS_CHILD_BATCH_DISPATCHES_TOTAL: 0,
   OBS_STRUCTURED_OUTPUT_FAILURES_TOTAL: 0,
   ```
   Do NOT seed `OBS_CHILD_ERROR_COUNTS_TOTAL` — it should be absent when no errors exist.

   Add the necessary imports from `rlm_adk.state`.

4. **Spawn a `Snapshot-Docs` teammate to update the snapshot-timing comment in `rlm_adk/tools/repl_tool.py`.**

   Update the comment at line 185 to explain the pre-execution timing and the distinction between per-iteration keys (reset each turn) and cumulative `_total` keys (monotonically non-decreasing). This is a comment-only change.

5. **Spawn a `Sqlite-Tracing` teammate to prefer cumulative keys in `rlm_adk/plugins/sqlite_tracing.py` trace finalization.**

   At lines 756-759, use fallback pattern:
   ```python
   state.get("obs:child_dispatch_count_total", state.get("obs:child_dispatch_count"))
   ```
   Apply the same `_total`-with-fallback pattern for batch dispatches, error counts, and structured output failures.

6. **Spawn a `Test-Audit` teammate to update existing diagnostic tests and add cumulative counter assertions.**

   - `tests_rlm_adk/test_rlm_state_snapshot_audit.py`: Add assertions that cumulative keys (`obs:child_dispatch_count_total`) are monotonically non-decreasing across turns and are present (not ABSENT) on turn 1 in `_rlm_state`.
   - `tests_rlm_adk/test_state_accuracy_diagnostic.py`: Add `obs:child_dispatch_count_total`, `obs:child_batch_dispatches_total`, `obs:child_error_counts_total`, `obs:structured_output_failures_total` to `TRACKED_KEYS` (line 24). Add monotonicity assertions in `test_state_accuracy_audit`.
   - Update `fake_recursive_ping.json` expected values: add `obs:child_dispatch_count_total: 1` to `expected_state` (or add `expected_state` if absent).
   - Update `repl_error_then_retry.json`: add `obs:child_dispatch_count_total: 2` to `expected_state`.

   *[Added — the plan mentions removing diagnostic test files "after verification." Do NOT remove them. They are permanent regression tests, not temporary diagnostics.]*

7. **Spawn a `Docs-Update` teammate to update `rlm_adk_docs/dispatch_and_state.md` and `rlm_adk_docs/observability.md`.**

   Add a "Per-Iteration vs Cumulative Keys" section explaining:
   - Per-iteration keys (`obs:child_dispatch_count`) reset to 0 after each REPL turn via `flush_fn()`. Useful for per-step analysis.
   - Cumulative keys (`obs:child_dispatch_count_total`) never reset. Monotonically non-decreasing. Useful for dashboards and `_rlm_state` introspection.
   - Table mapping per-iteration → cumulative key names.

## Provider-Fake Fixture & TDD

**Fixture:** No new fixture file required. Existing `fake_recursive_ping.json` and `repl_error_then_retry.json` are extended with `expected_state` assertions.

**Essential requirements the fixtures must capture:**
- `obs:child_dispatch_count_total` is 0 (not ABSENT) in `_rlm_state` on turn 1 — proves seeding in `initial_state` works
- `obs:child_dispatch_count_total` is monotonically non-decreasing across all turns — proves cumulative semantics
- `obs:child_dispatch_count` (per-iteration) continues to oscillate 1→0 — proves existing behavior is NOT broken
- `obs:child_dispatch_count_total` in final state equals the total number of child dispatches across all iterations (not just the last one)
- For `repl_error_then_retry`: cumulative count is 2 (one dispatch per iteration, two iterations) while per-iteration count in final state is 0 (last turn had zero dispatches after retry)

**TDD sequence:**

1. **Red:** In `test_rlm_state_snapshot_audit.py`, add assertion: `turn1_state.get("obs:child_dispatch_count_total") == 0` (present, not ABSENT). Run, confirm failure (key doesn't exist yet).

2. **Green:** Add `OBS_CHILD_DISPATCH_COUNT_TOTAL` to `state.py`, seed it in `orchestrator.py` `initial_state`, add to `EXPOSED_STATE_KEYS`. Run, confirm pass.

3. **Red:** Add assertion: after turn 1 (which dispatches a child), `turn2_state.get("obs:child_dispatch_count_total") == 1`. Run, confirm failure (key is seeded at 0 but never incremented).

4. **Green:** Add `_cum_child_dispatches` accumulator to `dispatch.py`, increment alongside `_acc_child_dispatches`, write to `flush_fn()` delta. Run, confirm pass.

5. **Red:** Add assertion: `final_state.get("obs:child_dispatch_count") == 0` AND `final_state.get("obs:child_dispatch_count_total") == 1`. Run, confirm pass for both (this should be green immediately — validates that per-iteration reset is preserved alongside cumulative).

6. **Red:** Add same pattern for `obs:child_batch_dispatches_total`, `obs:child_error_counts_total`, `obs:structured_output_failures_total`. Write tests in `test_state_accuracy_diagnostic.py` that assert these keys appear in TRACKED_KEYS output. Run, confirm failure.

7. **Green:** Add remaining 3 cumulative accumulators + flush_fn writes + state.py constants. Run, confirm pass.

8. **Red:** In `test_state_accuracy_audit` for `repl_error_then_retry`, assert `final_state.get("obs:child_dispatch_count_total") == 2`. Run, confirm failure (fixture doesn't have cumulative keys yet).

9. **Green:** Cumulative accumulators already wired from step 7. If fixture contract checks `expected_state`, add `expected_state` block to fixture JSON. Run, confirm pass.

**Demo:** Run `uvx showboat` to generate an executable demo document proving cumulative keys are present on turn 1, monotonically non-decreasing, and final values match total dispatches across all iterations.

## Considerations

- **AR-CRIT-001 compliance**: All cumulative accumulators are closure-local variables in `create_dispatch_closures()`. They are only written to state via `flush_fn()` → `tool_context.state`. No `ctx.session.state` writes.
- **Existing test suite**: Run `.venv/bin/python -m pytest tests_rlm_adk/` after each TDD step. Never use `-m ""`. The default ~28 contract tests must continue passing.
- **No breaking changes**: Per-iteration keys keep exact same semantics. Cumulative keys are additive. Downstream consumers that don't know about `_total` keys are unaffected.
- **Depth scoping**: Cumulative keys are NOT depth-scoped (they are global observability counters). Do not add them to `DEPTH_SCOPED_KEYS`.
- **BUG-13 interaction**: `OBS_BUG13_SUPPRESS_COUNT` is already cumulative (never reset in `flush_fn()`). The new cumulative keys follow the same pattern.
- **Lint**: Run `ruff check rlm_adk/ tests_rlm_adk/` and `ruff format --check rlm_adk/ tests_rlm_adk/` after all changes.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/state.py` | `OBS_CHILD_DISPATCH_COUNT` | L98 | Existing per-iteration key — new `_TOTAL` added after L101 |
| `rlm_adk/state.py` | `OBS_CHILD_TOTAL_BATCH_DISPATCHES` | L101 | Last existing child dispatch key — insert point |
| `rlm_adk/state.py` | `EXPOSED_STATE_KEYS` | L154 | Frozenset controlling `_rlm_state` snapshot — add new scalar keys |
| `rlm_adk/state.py` | `DEPTH_SCOPED_KEYS` | L177 | Do NOT add cumulative keys here |
| `rlm_adk/dispatch.py` | `create_dispatch_closures()` | L167 | Closure factory — all accumulator changes happen inside |
| `rlm_adk/dispatch.py` | `_acc_child_dispatches` | L200 | Existing per-iteration accumulator — add `_cum_*` siblings after L206 |
| `rlm_adk/dispatch.py` | `_acc_child_dispatches += k` | L725 | Increment site — add `_cum_child_dispatches += k` |
| `rlm_adk/dispatch.py` | `_acc_child_batch_dispatches += 1` | L727 | Increment site — add `_cum_child_batch_dispatches += 1` |
| `rlm_adk/dispatch.py` | `_acc_child_error_counts[cat]` | L751 | Error accumulation — add `_cum_child_error_counts[cat]` |
| `rlm_adk/dispatch.py` | `_acc_structured_output_failures += 1` | L466, L485, L508 | Three increment sites — add `_cum_structured_output_failures += 1` |
| `rlm_adk/dispatch.py` | `flush_fn()` | L783 | Snapshot function — add cumulative writes before reset block (L806) |
| `rlm_adk/orchestrator.py` | `initial_state` | L322 | Dict seeded before `reasoning_agent.run_async` — add cumulative seeds |
| `rlm_adk/tools/repl_tool.py` | `_state_snapshot` build | L185-192 | Pre-execution snapshot — update comment only |
| `rlm_adk/plugins/sqlite_tracing.py` | `state.get("obs:child_dispatch_count")` | L756 | Trace finalization — prefer `_total` with fallback |
| `tests_rlm_adk/test_rlm_state_snapshot_audit.py` | `test_rlm_state_dispatch_count_timing` | L134 | Primary timing test — add cumulative assertions |
| `tests_rlm_adk/test_state_accuracy_diagnostic.py` | `TRACKED_KEYS` | L24 | Key set — add 4 cumulative keys |
| `tests_rlm_adk/fixtures/provider_fake/fake_recursive_ping.json` | fixture | — | 2-iteration recursive ping, add `expected_state` |
| `tests_rlm_adk/fixtures/provider_fake/repl_error_then_retry.json` | fixture | — | 2-iteration error recovery, add `expected_state` |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow branch links for **Dispatch & State** and **Observability**)
3. `rlm_adk_docs/dispatch_and_state.md` — full dispatch closure / flush_fn / state key documentation
4. `rlm_adk_docs/observability.md` — plugin architecture and worker obs path
5. `rlm_adk_docs/testing.md` — fixture schema, contract runner API, how to add expected_state
