<!-- generated: 2026-03-18 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Close All 14 Live Dashboard Gaps

## Context

The RLM Live Recursive Dashboard (`/live`) has 14 documented gaps across state capture, telemetry completeness, display correctness, REPL visibility, and trace lifecycle. The root causes trace to two systemic issues: (1) `SqliteTracingPlugin.after_tool_callback` never fires for `execute_code` at depths 0-3 because the tool's `run_async()` awaits deeply nested child orchestrators before returning, and ADK's tool dispatch pipeline doesn't complete the callback pair for long-running async tools, and (2) child state deltas are collected into `_child_state` in `dispatch.py` `_run_child()` (L428-441) but consumed and discarded — never re-yielded to the parent event stream where `SqliteTracingPlugin.on_event_callback` can observe them. This plan addresses all 14 gaps in priority order, grouped by root cause.

**Sequencing constraint**: Steps 1, 2, and 5 all modify `rlm_adk/plugins/sqlite_tracing.py`. They MUST be executed sequentially (1 → 2 → 5), not in parallel. Steps 3, 4 can run in parallel with each other and with Phase 1. Steps 6-8 can run after Phase 1 completes.

## Original Transcription

> read @proposals/dashboard_gaps_report.md and generate an implementation plan to close these gaps

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

### Phase 1: P0 Root Causes (GAP-06, GAP-02)

1. **Spawn a `Tool-Finalize` teammate to fix tool call telemetry finalization for recursive REPL dispatches in `SqliteTracingPlugin.after_tool_callback()` at `rlm_adk/plugins/sqlite_tracing.py` (L1021).**

   GAP-06: Tool calls at depths 0-3 are inserted into the `telemetry` table via `before_tool_callback` but `after_tool_callback` never fires, leaving `end_time=NULL`, `result_payload=NULL`, and all REPL enrichment columns empty.

   **Root cause (confirmed by code review)**: `REPLTool.run_async()` at depths 0-3 internally awaits `_run_child()` in `dispatch.py` (L383), which spawns a child `RLMOrchestratorAgent` via `child.run_async(child_ctx)`. This creates a deeply nested async chain — 4 levels of recursive child orchestrators — before the tool `return` statement is reached. ADK's tool dispatch pipeline does not complete the `after_tool_callback` for these long-running async tools. Only depth 4 (which hits `DEPTH_LIMIT` and returns immediately) gets a complete callback pair.

   **Recommended fix — approach (a)**: Inject a `telemetry_finalizer: Callable[[int, dict], None] | None` parameter into `REPLTool.__init__` (alongside the existing `flush_fn`). The orchestrator wires it as a closure over the plugin's `_pending_tool_telemetry` dict and `_update_telemetry` method. `REPLTool` calls it at **all 4 return paths** in `run_async()`:
   1. The call-limit early exit (L133-140) — **do not forget this path**
   2. The cancellation handler
   3. The exception handler
   4. The normal return

   The finalizer signature: `finalize(tool_context_id: int, result: dict) -> None`. This mirrors the `flush_fn` injection pattern already used in the codebase.

   **Implementation detail**: The plugin's `_pending_key()` (L496-499) uses `id(tool_context)` — a Python memory address — as the lookup key into `_pending_tool_telemetry`. The finalizer must use the same `id(tool_context)` to pop the correct pending row. Thread safety: `_pending_tool_telemetry` is a plain dict accessed from async contexts; `id(tool_context)` is unique per `ToolContext` instance so collisions are low risk, but note this if concurrent dispatch patterns change.

   **Excluded approaches**:
   - (b) `on_event_callback` backfill — risky because there is no `tool_context` in `on_event_callback`, only `invocation_context`. Mapping function-response events back to pending rows requires fragile alternative keying.
   - (c) Dashboard loader fallback — display-only workaround that **cannot satisfy the database requirement** (`end_time IS NOT NULL`). `ContextWindowSnapshotPlugin` does not extract `execute_code` function call argument values into snapshot chunks, so "fall back to snapshot chunks" is not feasible.

   **Success criterion**: After a replay run, ALL tool call rows in `telemetry` for `execute_code` have non-NULL `end_time`, `duration_ms`, `result_preview`, and REPL enrichment columns (`repl_stdout`, `repl_stderr`, `repl_has_errors`, `repl_has_output`, `repl_llm_calls`).

   **Constraint**: Do not break the existing 28 contract tests. Preserve AR-CRIT-001 compliance — no `ctx.session.state[key] = value` in dispatch closures.

   **Cascading fixes**: Closing GAP-06 automatically fixes GAP-01 (repl_submitted_code), GAP-05 (REPL stdout/stderr), and partially GAP-11 (code chip visibility).

2. **Spawn a `State-Propagation` teammate to fix worker state event capture in `rlm_adk/dispatch.py` `_run_child()` (L428) and `create_dispatch_closures()`.**

   GAP-02: `session_state_events` contains zero rows at `key_depth > 0`. This is NOT `ParallelAgent` isolation — child dispatch uses `child.run_async(child_ctx)` directly in `_run_child()` at `dispatch.py` L428-441. Child state deltas ARE collected into the `_child_state` local dict (L439-441) but are consumed for result extraction only — they are never re-yielded to the parent event stream where `SqliteTracingPlugin.on_event_callback` can observe them.

   **Recommended fix — approach (a)**: Add a `_acc_child_depth_state: dict[str, Any]` accumulator as a `nonlocal` variable in `create_dispatch_closures()` (following the existing `_acc_child_summaries` pattern — note `_child_state` is a local inside `_run_child()` and cannot be accessed by `flush_fn` directly). In `_run_child()`'s `finally` block, after building the child summary, copy specific depth-scoped keys from `_child_state` into `_acc_child_depth_state`. Then `flush_fn()` includes these keys in its return dict, and `REPLTool`'s existing accumulator-write logic pushes them into `tool_context.state`. The plugin's `_should_capture()` (L153-160) already covers all these keys, so no schema changes are needed in `session_state_events`.

   Keys to propagate from `_child_state`: `reasoning_visible_output_text@dN`, `reasoning_thought_text@dN`, `reasoning_input_tokens@dN`, `reasoning_output_tokens@dN`, `reasoning_finish_reason@dN`, `repl_submitted_code@dN`, `last_repl_result@dN`, `iteration_count@dN`.

   **Fanout collision warning**: If `llm_query_batched_async()` dispatches multiple children at the same depth, their state keys collide under the same `@dN` scope (since `depth_key()` doesn't encode fanout). Decide: last-child-wins (overwrite) is acceptable for dashboard display purposes, or use a fanout-qualified key format if precision is needed.

   **Excluded approaches**:
   - (b) Register plugin on child agents — infeasible. Child orchestrators are spawned outside the Runner's managed plugin pipeline via direct `child.run_async(child_ctx)`.
   - (c) Dashboard loader synthesis — display-only, incomplete for REPL state keys, and depends on `RLM_CONTEXT_SNAPSHOTS=1`.

   **Success criterion**: After a replay run, `session_state_events` contains rows for `reasoning_thought_text`, `reasoning_visible_output_text`, `reasoning_input_tokens`, `reasoning_output_tokens`, `repl_submitted_code`, and `last_repl_result` at all active depths (0-4 for `recursive_ping`).

   **Cascading fixes**: Closing GAP-02 automatically fixes GAP-09 (no reasoning state for children) and GAP-12 (all state keys ~0 tok). GAP-04 (wrong paused depth) is fixed independently in step 4 via agent-name extraction — it does NOT depend on this step.

### Phase 2: P1 Display & Lifecycle Fixes (GAP-03, GAP-04, GAP-07)

3. **Spawn a `Agent-Name-Fix` teammate to fix `_display_agent_name()` in `rlm_adk/dashboard/components/live_invocation_tree.py` (L26).**

   GAP-03: Replace the synthetic name construction with the actual `invocation.agent_name` field. The current code constructs `parent_reasoning_agent_0` / `child_reasoning_agent_1` but actual names are `reasoning_agent` / `child_reasoning_d1`.

   Change:
   ```python
   def _display_agent_name(invocation: LiveInvocation) -> str:
       return invocation.agent_name
   ```

4. **Spawn a `Step-Depth-Fix` teammate to fix depth extraction in `StepModePlugin.before_model_callback()` at `rlm_adk/plugins/step_mode.py` (L18).**

   GAP-04: Replace `callback_context.state.get("current_depth", 0)` with agent-name-based depth extraction using the `_depth_from_agent()` pattern from `live_loader.py` (L64). The `current_depth` state key is never written at depth > 0.

   Add `import re` at module level (top of `step_mode.py`). Then change **only line 34** from:
   ```python
   depth = callback_context.state.get("current_depth", 0)
   ```
   to:
   ```python
   match = re.search(r"_d(\d+)", agent_name)
   depth = int(match.group(1)) if match else 0
   ```
   Lines 29-33 and 35-36 remain unchanged — they already extract `agent_name` correctly.

5. **Spawn a `Trace-Finalize` teammate to fix trace lifecycle finalization in `SqliteTracingPlugin.after_run_callback()` at `rlm_adk/plugins/sqlite_tracing.py` (L678) and `run_service.py`.**

   GAP-07: After a dashboard-launched replay completes, the trace row retains `status=running`, `end_time=None`, `total_calls=0`.

   **Important**: `after_run_callback` (L678) probably DOES fire, but it reads zero OBS keys from session state because GAP-06 prevents `flush_fn` from running — so `OBS_TOTAL_CALLS` etc. are never written. **Implement step 1 (GAP-06) first, then re-verify.** If GAP-07 self-resolves after GAP-06 is fixed, this step becomes unnecessary.

   **If GAP-07 persists after GAP-06 is fixed**: The replay runs via `handle.run()` in `rlm_adk/dashboard/run_service.py` (L30), which calls `runner.run_async()`. Add explicit trace finalization after `handle.run()` returns. Access the plugin instance via `runner.app.plugins` (iterate to find `SqliteTracingPlugin`), then call its finalization directly, or query telemetry counts and update the trace row.

   The result must ensure that after a replay run completes, `traces.status='completed'`, `traces.end_time` is set, and `traces.total_calls` reflects the actual count from `telemetry`.

   **Cascading fixes**: Closing GAP-07 automatically fixes GAP-08 (summary metrics) and GAP-14 (stale idle status).

### Phase 3: P2 Dashboard UI Polish (GAP-10, GAP-11, GAP-12)

6. **Spawn a `UI-Polish` teammate to fix three related dashboard display issues in `rlm_adk/dashboard/` files.**

   GAP-10: In `live_loader.py` `build_banner_items()` (L265), when `reasoning_visible_output_text` is empty and the invocation has tool events (i.e., the model responded with a function call, not text), set `display_value_preview` to `"(tool call — no text output)"` instead of leaving it empty. The detection condition: `not display_text and bool(invocation.tool_events)`. Token count remains 0, chip stays gray — only the tooltip/click content changes. This fix is independent of P0/P1 — `tool_events` is populated from telemetry start rows which exist even for incomplete tool calls.

   GAP-11: In `live_invocation_tree.py` `_repl_panel()` (L171), remove the `if node.parent_code_text.strip():` guard and **always render the `code` action chip**. When clicked on an empty code chip, show "No code captured yet" in the context viewer. Do NOT attempt to fall back to snapshot chunks — `ContextWindowSnapshotPlugin` does not extract `execute_code` function call argument values into any chunk category. Once GAP-06 is fixed, state events will populate `repl_submitted_code` and the chip will show real code.

   GAP-12: In `live_invocation_tree.py` `_context_chip()` (L212), when a state key has no value, display `n/a` instead of `~0 tok`. Use `item.display_value_preview` as the discriminant — no dataclass change needed:
   ```python
   if item.token_count == 0 and not item.display_value_preview:
       token_text = "n/a"
   elif item.token_count_is_exact:
       token_text = f"{item.token_count} tok"
   else:
       token_text = f"~{item.token_count} tok"
   ```

   **Per-gap acceptance criteria**:
   - GAP-10: Clicking `reasoning_visible_output_text` chip on a tool-call iteration shows "(tool call — no text output)" in the context viewer, not an empty panel.
   - GAP-11: The `code` chip appears in every child agent's REPL panel unconditionally. Clicking it when empty shows "No code captured yet".
   - GAP-12: State key chips with no value show `n/a`. State key chips with real values show `~N tok` with N > 0.

### Phase 4: P3 Presence Detection & Status (GAP-13, GAP-14)

7. **Spawn a `Status-Signal` teammate to fix status badge accuracy in `live_loader.py` `_normalize_status()` (L1109).**

   GAP-14: When `traces.total_calls=0` and `traces.status='running'`, fall back to counting model calls from `cache.telemetry_rows` (already loaded in memory — no additional SQL query needed). Add a `telemetry_model_count: int = 0` parameter to `_normalize_status()`:
   ```python
   @staticmethod
   def _normalize_status(status: str | None, *, total_calls: Any, telemetry_model_count: int = 0) -> str:
       if status == "completed":
           return "completed"
       if status == "error":
           return "error"
       effective_calls = _safe_int(total_calls) or telemetry_model_count
       return "running" if effective_calls > 0 else "idle"
   ```
   At call sites (L642, L724), compute: `telemetry_model_count = sum(1 for r in cache.telemetry_rows if r.get("event_type") == "model_call")`

   *[Added — the transcription didn't mention this separately, but GAP-14 has a simple independent fix that doesn't depend on GAP-07's trace finalization. Implementing both provides defense-in-depth.]*

8. **Spawn a `Presence-Fix` teammate to simplify state key presence detection in `live_loader.py` `build_banner_items()` (L330).**

   GAP-13: The current `preview[:80] in request_text` substring match produces false positives/negatives. Replace with a simple non-empty check: `present = bool(display_text)`. A state key with a non-empty value should always show as green (present); the context-window substring heuristic is unreliable.

   Also remove the REPL special-case branch at L331-332 — the simpler `bool(display_text)` rule covers it.

   **Sequencing**: This fix is only meaningful after GAP-02 is implemented (state values will be populated). Against the current broken data, both the old and new logic produce all-False. Implement after Phase 1.

## Provider-Fake Fixture & TDD

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/dashboard_telemetry_completeness.json`

**Fixture design**: Base this on the existing `recursive_ping` replay pattern — a root agent at depth 0 that dispatches children recursively to depth 4 (hitting `DEPTH_LIMIT` at depth 5). Use the provider-fake `ScenarioRouter` with 5 canned model responses (one per depth), each returning a `functionCall` to `execute_code` with a simple `llm_query()` call. The fixture should exercise the full dispatch → child → flush → state propagation → telemetry finalization pipeline. Refer to existing fixtures in `tests_rlm_adk/fixtures/provider_fake/` for the JSON schema format.

**Essential requirements the fixture must capture:**
- After a recursive_ping replay, ALL tool call telemetry rows have non-NULL `end_time` and `result_payload` — verifies GAP-06 fix is not just for leaf agents
- `session_state_events` contains `repl_submitted_code` entries at depth 0 AND depth > 0 — verifies GAP-02 fix propagates worker state
- `session_state_events` contains `reasoning_thought_text` and `reasoning_visible_output_text` at depths 1-4 — verifies child reasoning state capture
- `traces.status='completed'` and `traces.total_calls > 0` after run — verifies GAP-07 trace finalization
- Step mode paused label shows correct depth (e.g., `child_reasoning_d3 @ depth 3`, not `@ depth 0`) — verifies GAP-04 fix

**TDD sequence:**

*Phase 1 (P0):*
1. Red: Write test asserting `telemetry` tool call rows for `execute_code` at depth 0 have `end_time IS NOT NULL`. Run against current code, confirm failure.
2. Green: Implement Tool-Finalize fix (step 1). Run, confirm pass.
3. Red: Write test asserting `session_state_events` has `repl_submitted_code` rows at `key_depth=1`. Run, confirm failure.
4. Green: Implement State-Propagation fix (step 2). Run, confirm pass.

*Phase 2 (P1):*
5. Red: Write test asserting `traces.status='completed'` after replay. Run — may now pass if GAP-06 fix resolved this. If it passes, skip step 6. If it fails, continue.
6. Green: Implement Trace-Finalize fix (step 5). Run, confirm pass.
7. Red: Write test asserting step gate reports correct depth for `child_reasoning_d3`. Mock `CallbackContext` with `_invocation_context.agent` set to an object where `name="child_reasoning_d3"`. Verify `step_gate.paused_depth == 3`. Run, confirm failure.
8. Green: Implement Step-Depth-Fix (step 4). Run, confirm pass.
9. Red: Write test asserting `_display_agent_name()` returns `"reasoning_agent"` for depth-0 invocation and `"child_reasoning_d1"` for depth-1. Run, confirm failure.
10. Green: Implement Agent-Name-Fix (step 3). Run, confirm pass.

*Phase 3 (P2):*
11. Red: Write test asserting `_context_chip` renders `"n/a"` when `token_count==0` and `display_value_preview==""`. Run, confirm failure.
12. Green: Implement GAP-12 fix in `_context_chip()`. Run, confirm pass.
13. Red: Write test asserting `_repl_panel` always renders a `code` chip even when `parent_code_text=""`. Run, confirm failure.
14. Green: Implement GAP-11 fix (remove guard). Run, confirm pass.
15. Red: Write test asserting `build_banner_items()` sets `display_value_preview` to `"(tool call — no text output)"` when `reasoning_visible_output_text` is empty and `tool_events` is non-empty. Run, confirm failure.
16. Green: Implement GAP-10 fix. Run, confirm pass.

*Phase 4 (P3):*
17. Red: Write test asserting `present=True` when `display_text` is non-empty in `build_banner_items()`. Run, confirm failure (current logic uses substring match).
18. Green: Implement GAP-13 fix (`present = bool(display_text)`). Run, confirm pass.

**Demo:** Run `uvx showboat` to generate an executable demo document proving all 14 gaps are closed, using the `recursive_ping` replay fixture as evidence.

## E2E Dashboard Verification (Browser)

After all phases are implemented and unit/contract tests pass, run an end-to-end browser verification against the live dashboard. This is the acceptance gate — SQLite assertions prove data correctness, but only browser inspection proves the dashboard **renders** that data correctly.

### Setup

1. Ensure the dashboard server is running: `python -m rlm_adk.dashboard`
2. Ensure a Playwright-controlled Chrome is attached: `scripts/launch_dashboard_playwright_chrome.py`
3. Use `scripts/attach_dashboard_playwright.py --probe` OR `/chrome` (claude-in-chrome MCP) to read the dashboard DOM

### Verification Sequence

Launch a fresh `recursive_ping` replay from the dashboard (click "Launch Replay"), wait for completion, then verify:

**GAP-03 — Agent names**: Read the agent card headers. Verify they show `reasoning_agent` (not `parent_reasoning_agent_0`) and `child_reasoning_d1` through `child_reasoning_d4` (not `child_reasoning_agent_N`).

**GAP-04 — Step mode depth**: Enable step mode toggle, re-launch the replay. When paused, verify the label shows `Paused: child_reasoning_d3 @ depth 3` (not `@ depth 0`). Click "Next Step" and verify the next pause shows the correct depth for the next agent.

**GAP-05/06 — REPL content**: For the depth-0 agent card, click the `code` chip in the REPL panel. Verify it shows the Python code submitted by the model (not "No code captured"). Click `stdout` — verify it shows REPL output. Repeat for at least one child agent (depth 1 or 2).

**GAP-01/02 — State keys populated**: On each agent card, verify that `repl_submitted_code` shows a non-zero token estimate (not `~0 tok` or `n/a`). Verify `reasoning_thought_text` shows a non-zero token estimate for child agents. Click a state key chip to open the context viewer — verify it shows actual content.

**GAP-07/14 — Status badge**: After the replay completes, verify the status badge shows `completed` (not `idle`). Verify `model calls` metric chip shows `5` (not `0`).

**GAP-10 — Tool call indicator**: On the depth-0 agent card, verify `reasoning_visible_output_text` chip shows a descriptive label (e.g., tooltip mentioning "tool call") instead of just `~0 tok`.

**GAP-11 — Code chip always visible**: Verify the `code` chip appears in every child agent's REPL panel, even if the data is not yet loaded.

**GAP-12 — Token display**: Verify no state key chip shows `~0 tok` for keys that should have content. Keys with no value should show `n/a`.

### Browser Verification Tools

- **Playwright attach**: `scripts/attach_dashboard_playwright.py` — `read_dashboard_state()` returns structured state; extend with DOM queries for specific assertions.
- **Chrome MCP**: `mcp__claude-in-chrome__read_page` with `tabId` for the dashboard tab — returns accessibility tree with all rendered text.
- **Snap-happy**: `mcp__snap-happy__TakeScreenshot` — capture before/after screenshots for visual diff.

### Capture Artifacts

After verification, capture:
1. A full-page screenshot showing the completed replay with all agent cards expanded
2. A screenshot with a state key context viewer open showing populated content
3. A screenshot with step mode paused showing correct depth label

These artifacts serve as the visual proof that all 14 gaps are closed at the rendering layer, not just the data layer.

## Considerations

- **AR-CRIT-001**: Steps 1-2 touch state mutation paths. Never write `ctx.session.state[key] = value` in dispatch closures. Use `tool_context.state`, `callback_context.state`, or `EventActions(state_delta={})`.
- **ADK Framework Limitation**: GAP-02 stems from child orchestrators being spawned via direct `child.run_async(child_ctx)` inside `_run_child()`, outside the Runner's managed event pipeline. Child state deltas are collected but not re-yielded. The fix accumulates them in dispatch's `flush_fn` (approach a) and writes them through `tool_context.state`.
- **Backward Compatibility**: The `SqliteTracingPlugin` schema (`telemetry` and `session_state_events` tables) must remain backward-compatible. New columns are fine; changing existing column semantics is not.
- **Test Suite**: Run `.venv/bin/python -m pytest tests_rlm_adk/` (default ~28 contract tests) after each phase. Do NOT run `-m ""` (full 970+ suite) unless doing final pre-merge validation.
- **Plugin Ordering**: `SqliteTracingPlugin` fires after `ObservabilityPlugin` in the callback chain. Changes to state propagation must respect this ordering.
- **Step Mode Plugin**: Uses the `_invocation_context.agent` private API (ADK internal). The depth extraction fix (step 4) is more robust than relying on state.
- **Rollback safety**: Run `.venv/bin/python -m pytest tests_rlm_adk/` after each step (not just each phase). If a step causes a regression, revert it and investigate before proceeding. Steps 3, 4, 6, 7, 8 are low-risk (dashboard display only). Steps 1, 2, 5 touch the plugin/dispatch pipeline — test carefully. If step 1 (GAP-06) causes failures, check whether the finalizer is being called on a code path where `tool_context` is already cleaned up by ADK.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/plugins/sqlite_tracing.py` | `SqliteTracingPlugin` | L325 | Main tracing plugin class |
| `rlm_adk/plugins/sqlite_tracing.py` | `after_tool_callback()` | L1021 | Tool telemetry finalization (GAP-06) |
| `rlm_adk/plugins/sqlite_tracing.py` | `after_run_callback()` | L678 | Trace finalization (GAP-07) |
| `rlm_adk/plugins/sqlite_tracing.py` | `on_event_callback()` | L1096 | State event capture (GAP-02) |
| `rlm_adk/plugins/step_mode.py` | `StepModePlugin.before_model_callback()` | L18 | Paused depth extraction (GAP-04) |
| `rlm_adk/dashboard/components/live_invocation_tree.py` | `_display_agent_name()` | L26 | Agent name display (GAP-03) |
| `rlm_adk/dashboard/components/live_invocation_tree.py` | `_repl_panel()` | L171 | REPL code/stdout/stderr chips (GAP-11) |
| `rlm_adk/dashboard/live_loader.py` | `_depth_from_agent()` | L64 | Agent-name depth extraction pattern |
| `rlm_adk/dashboard/live_loader.py` | `build_banner_items()` | L265 | State key chip rendering (GAP-10, GAP-12, GAP-13) |
| `rlm_adk/dashboard/live_loader.py` | `_build_invocation()` | L890 | Invocation data assembly (GAP-05 fallback) |
| `rlm_adk/dashboard/live_loader.py` | `_normalize_status()` | L1109 | Status badge logic (GAP-14) |
| `rlm_adk/dashboard/live_loader.py` | `_estimate_token_count()` | L109 | Token estimation (GAP-12) |
| `rlm_adk/tools/repl_tool.py` | `REPLTool` | L1 | REPL execution, state writes |
| `rlm_adk/dispatch.py` | `create_dispatch_closures()` | L168 | Dispatch closure factory, flush_fn, accumulators |
| `rlm_adk/dispatch.py` | `_run_child()` | L383 | Child orchestrator dispatch, `_child_state` collection (L428-441) |
| `rlm_adk/callbacks/reasoning.py` | `reasoning_after_model()` | L168 | Writes depth-scoped reasoning state keys via `callback_context.state` |
| `rlm_adk/state.py` | `depth_key()` | L221 | Depth-scoped state key helper |
| `rlm_adk/dashboard/run_service.py` | `ReplayLaunchHandle.run()` | L30 | Replay execution entry point |
| `rlm_adk/step_gate.py` | `StepGate` | L8 | Async gate primitive for step mode |
| `proposals/dashboard_gaps_report.md` | Full gaps report | — | Evidence and root cause analysis |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow branch links relevant to this task)
3. `proposals/dashboard_gaps_report.md` — the gaps report with evidence, SQL queries, and dependency graph
