# Dashboard Data Mismatch Report: `skill_arch_test` Provider-Fake Run

**Date:** 2026-03-25
**Session:** `011da421-6328-4abc-927a-c28d8e95f660`
**Trace:** `5f0ba70e6ce84284a910de17eb3c5ced`
**Fixture:** `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json`

---

## Section 1: Data Inventory

### Source 1: SQLite Telemetry (`traces.db`)

| Table | Row Count | Key Fields |
|-------|-----------|------------|
| `traces` | 1 | total_calls=8, iterations=2, max_depth_reached=2, child_dispatch_count=5, status=completed |
| `telemetry` | 16 | 8 model_call + 8 tool_call rows across depths 0, 1, 2 |
| `session_state_events` | 60 | seq 0-59, key_depth values: 0, 1, 2 |

**Telemetry breakdown by depth and agent:**

| # | event_type | agent_name | depth | iteration | call_number | tool_name | fanout_idx |
|---|-----------|------------|-------|-----------|-------------|-----------|------------|
| 1 | model_call | reasoning_agent | 0 | 0 | 1 | - | 0 |
| 2 | tool_call | reasoning_agent | 0 | 0 | 1 | execute_code | 0 |
| 3 | model_call | child_reasoning_d1 | 1 | 1 | 2 | - | 0 |
| 4 | tool_call | child_reasoning_d1 | 1 | - | 1 | execute_code | 0 |
| 5 | model_call | child_reasoning_d2 | 2 | 1 | 3 | - | 0 |
| 6 | tool_call | child_reasoning_d2 | 2 | - | - | set_model_response | 0 |
| 7 | model_call | child_reasoning_d1 | 1 | 1 | 4 | - | 0 |
| 8 | tool_call | child_reasoning_d1 | 1 | 1 | - | set_model_response | 0 |
| 9 | model_call | reasoning_agent | 0 | 1 | 5 | - | 0 |
| 10 | tool_call | reasoning_agent | 0 | 1 | 2 | execute_code | 0 |
| 11 | model_call | child_reasoning_d1 | 1 | 2 | 6 | - | 0 |
| 12 | model_call | child_reasoning_d1 | 1 | 2 | 7 | - | 1 |
| 13 | tool_call | child_reasoning_d1 | 1 | 1 | - | set_model_response | 0 |
| 14 | tool_call | child_reasoning_d1 | 1 | 1 | - | set_model_response | 1 |
| 15 | model_call | reasoning_agent | 0 | 2 | 8 | - | 0 |
| 16 | tool_call | reasoning_agent | 0 | 2 | - | set_model_response | 0 |

**Session state events by depth:**
- depth=0: 44 events (seq 0-12, 35-44, 57-59, plus depth=0 `key_depth` from child `repl_skill_globals_injected` and `artifact_*` keys)
- depth=1: 12 events (seq 13-14, 16-25, 32-34, 45-56)
- depth=2: 4 events (seq 26-31)

**Depths covered:** 0, 1, 2 (all three recursion levels)

### Source 2: ADK Session DB (`session.db`)

| Table | Row Count | Key Fields |
|-------|-----------|------------|
| `sessions` | 1 | id=011da421..., single invocation_id e-6196ce6d... |
| `events` | 26 | All under invocation_id e-6196ce6d..., timestamps spanning 1774445509.42 to 1774445511.05 |

**Event composition:** User prompt (1), rlm_orchestrator state deltas (4), reasoning_agent model responses (3), reasoning_agent tool responses (2), child re-emitted events (16 with `rlm_child_event: true` in custom_metadata)

### Source 3: Fixture Runtime Output

| Field | Value |
|-------|-------|
| contract_passed | true |
| total checks | 11 (all ok) |
| total_iterations | 2 (actual=2) |
| total_model_calls | 8 (actual=8) |
| captured_requests | 8 model API calls |
| total_elapsed_s | 1.505s |
| final_answer | "Pipeline verified: depth=2 chain succeeded..." |

### Source 4: Fixture Definition

| Field | Value |
|-------|-------|
| responses | 8 (call_index 0-7) |
| depths exercised | 0 (root, 3 turns), 1 (chain child + 2 batch children), 2 (grandchild) |
| reasoning turns at depth=0 | 3 (execute_code, execute_code, set_model_response) |
| expected total_iterations | 2 |
| expected total_model_calls | 8 |

### Source 5: Dashboard Screenshot Evidence

| Metric | Displayed Value |
|--------|----------------|
| model calls | 8 |
| active depth | 0 |
| iteration_count | 2 |
| should_stop | True |
| Flow view code visible | Only last iteration's code (llm_query_batched call) |
| Child cards visible | 2 (batched children) |
| Depth=2 chain | NOT visible in main flow |

---

## Section 2: Alignments

These data points are correctly represented and consistent across all sources.

### 2.1 Total Model Calls
- **Fixture definition:** 8 responses
- **Fixture runtime:** total_model_calls=8
- **SQLite traces:** total_calls=8
- **SQLite telemetry:** 8 `model_call` rows
- **Dashboard screenshot:** model calls: 8
- **Status:** Fully aligned

### 2.2 Total Iterations
- **Fixture definition:** expected total_iterations=2
- **Fixture runtime:** actual iteration_count=2
- **SQLite traces:** iterations=2
- **SQLite SSE:** iteration_count at depth=0 reaches 2 (seq 43, value_int=2)
- **Dashboard screenshot:** iteration_count=2
- **Status:** Fully aligned

### 2.3 Final Answer Text
- **Fixture definition:** expected $contains "depth=2 chain succeeded"
- **Fixture runtime:** "Pipeline verified: depth=2 chain succeeded (depth2_leaf_ok via child), batched dispatch returned 2 results (finding_A_summary, finding_B_summary)."
- **SQLite traces:** final_answer_length=146
- **SQLite SSE seq 58:** final_response_text at depth=0 matches exactly
- **SQLite telemetry row 16:** validated_output_json contains matching final_answer
- **Status:** Fully aligned

### 2.4 Session Identity
- **Session ID:** `011da421-6328-4abc-927a-c28d8e95f660` consistent across all 5 sources
- **Trace ID:** `5f0ba70e6ce84284a910de17eb3c5ced` consistent across telemetry + SSE + traces
- **Invocation ID:** `e-6196ce6d-201d-45a9-8329-e749044ce469` consistent across all telemetry, session events, and session DB
- **Status:** Fully aligned

### 2.5 Max Depth Reached
- **Fixture definition:** depth=2 chain (root -> child_d1 -> grandchild_d2)
- **SQLite traces:** max_depth_reached=2
- **SQLite telemetry:** agent `child_reasoning_d2` at depth=2 present
- **SQLite SSE:** key_depth=2 events present (seq 26-31)
- **Status:** Fully aligned

### 2.6 Completion Status
- **Fixture runtime:** contract_passed=true, should_stop=true
- **SQLite traces:** status="completed"
- **SQLite SSE seq 59:** should_stop at depth=0, value_int=1
- **Dashboard screenshot:** COMPLETED
- **Status:** Fully aligned

### 2.7 Token Totals
- **SQLite traces:** total_input_tokens=2390, total_output_tokens=320
- **Fixture responses sum:** input = 400+150+80+200+600+80+80+800 = 2390, output = 80+40+20+30+60+15+15+60 = 320
- **SQLite traces model_usage_summary:** gemini-fake calls=8, input_tokens=2390, output_tokens=320
- **Status:** Fully aligned

### 2.8 Child Dispatch Count
- **SQLite traces:** child_dispatch_count=5
- **Fixture structure:** 5 child dispatches (1 via run_test_skill at d1, 1 grandchild at d2, 1 chain-child returning, 2 batch children)
- **Status:** Aligned (though interpretation depends on counting convention)

### 2.9 Tool Invocation Summary
- **SQLite traces:** tool_invocation_summary = `{"execute_code": 3, "set_model_response": 5}`
- **Telemetry verification:** 3 execute_code tool_calls (d0 iter 0, d1 iter 1, d0 iter 1) + 5 set_model_response tool_calls (d2, d1 chain, d1 batch-A, d1 batch-B, d0 root)
- **Status:** Fully aligned

### 2.10 REPL Execution Mode
- **All tool_call telemetry rows for execute_code:** execution_mode="thread_bridge"
- **Fixture runtime state:** last_repl_result.execution_mode="thread_bridge"
- **SQLite session state:** All last_repl_result values contain "execution_mode": "thread_bridge"
- **Status:** Fully aligned

### 2.11 Depth=1 Chain Child REPL Output
- **SQLite telemetry (row 4):** repl_stdout contains "grandchild_said=depth2_leaf_ok\nd1_depth=1\nd1_iteration=1"
- **SQLite SSE seq 25:** last_repl_result@d1 stdout matches
- **Fixture response call_index=1:** code contains `llm_query('Return the leaf value: depth2_leaf_ok')`
- **Status:** Fully aligned in SQLite; not visible in dashboard main flow (by design, requires child window drill-down)

### 2.12 Batch Results
- **SQLite telemetry (row 10, execute_code at d0 iter 1):** stdout contains "batch_0=finding_A_summary\nbatch_1=finding_B_summary\nbatch_count=2"
- **Fixture runtime:** last_repl_result.stdout matches
- **Dashboard screenshot:** 2 child cards visible
- **Status:** Fully aligned

---

## Section 3: Misalignments

### Mismatch 1: Iteration 1 REPL Code Not Visible in Dashboard Flow View

- **What:** The flow view shows only the LAST iteration's REPL code (`llm_query_batched` call from Turn 2), not Turn 1's `run_test_skill` call.
- **Evidence:**
  - SQLite SSE seq 3: `repl_submitted_code` at depth=0 = Turn 1 code (`run_test_skill(...)`, 571 chars, hash `c726a93a...`)
  - SQLite SSE seq 35: `repl_submitted_code` at depth=0 = Turn 2 code (`llm_query_batched(...)`, 445 chars, hash `790954289b...`)
  - Session DB final state: `repl_submitted_code` = Turn 2 code only (last-write-wins)
  - Dashboard screenshot: Only Turn 2 code visible in FlowCodeCell
  - Fixture definition: Turn 1 (call_index 0) has 571-char code block; Turn 2 (call_index 4) has 445-char code block. Both should be navigable.
- **Root cause:** Pipeline analysis Gap 2 -- all `LiveInvocation` objects at a depth share the same `state_items` snapshot. `REPL_SUBMITTED_CODE` reflects only the last submission. The loader at line 1040 reads `repl_submitted_code` from the shared latest-state snapshot, not per-iteration telemetry.
- **Impact:** User sees only the final iteration's code block. The `run_test_skill` call from Turn 1 -- which triggered the entire depth=2 chain -- is invisible. User cannot understand what caused the depth=2 dispatch.
- **Severity:** Critical -- data loss in display. Turn 1's code IS in the telemetry (row 2, result_payload contains the code), but the dashboard never surfaces it.

### Mismatch 2: No Iteration Navigation in Flow View

- **What:** The flow view has 3 iterations at depth=0 but no UI to switch between them.
- **Evidence:**
  - SQLite telemetry: 3 `model_call` rows at depth=0 (iterations 0, 1, 2)
  - Pipeline analysis: `FlowAgentCard.available_iteration_ids` is populated with 3 entries but `render_flow_reasoning_pane` ignores the field
  - Dashboard screenshot: Only the latest iteration visible, no navigation controls
- **Root cause:** Pipeline analysis Gap 1 -- `render_flow_reasoning_pane` does not render any navigation widget for `available_iteration_ids`. The data flows correctly through loader -> controller -> flow_builder but stops at rendering.
- **Impact:** User cannot navigate to Turn 1 (run_test_skill) or Turn 2 (llm_query_batched) individually. They only see Turn 3 (set_model_response) which has no code cell. Combined with Mismatch 1, this means 2 out of 3 reasoning turns are effectively invisible in the flow view.
- **Severity:** High -- misleading display. The user sees iteration_count=2 in the header but only one "turn" in the flow.

### Mismatch 3: Turn 1 Child Dispatch (Depth=2 Chain) Not Visible in Flow View

- **What:** The depth=2 chain from Turn 1 (root -> child_d1 -> grandchild_d2) is not represented in the flow view's child cards.
- **Evidence:**
  - SQLite telemetry: 6 rows for the depth=2 chain (rows 3-8: child_reasoning_d1 model+tool at depth=1, child_reasoning_d2 model+tool at depth=2, child_reasoning_d1 resume model+tool at depth=1)
  - SQLite SSE: 22 events at depth=1 and depth=2 for the chain (seq 13-34)
  - Dashboard screenshot: Only 2 child cards visible (the batched children from Turn 2)
  - Fixture: Turn 1 dispatches 1 child at depth=1 which dispatches 1 grandchild at depth=2
- **Root cause:** Pipeline analysis Gap 3 -- `LivePane.child_summaries` only includes the latest iteration's child summaries. The flow_builder at lines 142-179 only renders `FlowChildCard` blocks for `inv.child_summaries`. Since the dashboard shows the latest iteration (which is Turn 3's `set_model_response` with no children), Turn 1's children are lost. Even if Turn 2 were shown, it would only show the batched children.
- **Impact:** The user cannot see that a depth=2 chain occurred at all from the main flow view. The entire `run_test_skill -> child_d1 -> grandchild_d2` execution is invisible.
- **Severity:** Critical -- the most interesting part of the run (recursive depth=2 dispatch) is completely hidden.

### Mismatch 4: Fanout Index Inconsistency in Telemetry Metadata

- **What:** Two batch child model_call rows at depth=1 have swapped fanout_idx between the `fanout_idx` column and the embedded `custom_metadata_json`.
- **Evidence:**
  - Telemetry row 11 (call_number=6): column `fanout_idx=0`, but `custom_metadata_json` contains `"fanout_idx": 1`
  - Telemetry row 12 (call_number=7): column `fanout_idx=1`, but `custom_metadata_json` contains `"fanout_idx": 0`
  - The tool_call rows 13-14 have consistent fanout_idx values (0 and 1 respectively matching their result_preview content)
- **Root cause:** The `fanout_idx` column is set at write time by the sqlite_tracing plugin from one source, while `custom_metadata_json` is populated from the ADK event's custom_metadata which may be set at a different point in the dispatch lifecycle. The two sources are not synchronized for model_call events during batched dispatch.
- **Impact:** If the dashboard used `custom_metadata_json.fanout_idx` instead of the column, child cards could be incorrectly matched to their parent code lines. Currently the dashboard uses the column value, so the visual impact is limited, but any debugging that reads the JSON metadata would be confused.
- **Severity:** Medium -- data inconsistency. The column values appear correct (matching the chronological order of prompts), but the metadata is wrong.

### Mismatch 5: `has_errors=true` in Turn 1 REPL Result Despite No Real Error

- **What:** Turn 1's `last_repl_result` shows `has_errors: true` in the session state, but the only "error" is a benign UserWarning from `worker_retry.py`.
- **Evidence:**
  - SQLite SSE seq 12: `last_repl_result` at depth=0 contains `"has_errors": true`
  - Telemetry row 2: `repl_has_errors=1`, `repl_stderr_len=311`
  - The stderr content: `/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker_retry.py:89: UserWarning: [EXPERIMENTAL] ReflectAndRetryToolPlugin...`
  - Turn 2's `last_repl_result` has `has_errors: false` with empty stderr
  - Fixture runtime: contract passes, no real errors
- **Root cause:** REPLTool sets `has_errors=true` whenever stderr is non-empty, regardless of whether stderr contains actual errors or just warnings. The `UserWarning` about the experimental feature is written to stderr by Python's warning system.
- **Impact:** Dashboard may show an error indicator for Turn 1 when there is no actual error. This is misleading if the dashboard uses `has_errors` to render error styling.
- **Severity:** Low -- cosmetic/misleading. The warning is benign and the pipeline succeeded.

### Mismatch 6: Turn 1 REPL stdout Differs Between Telemetry and Fixture Runtime

- **What:** Turn 1's REPL stdout in the telemetry DB is shorter than in the fixture runtime output.
- **Evidence:**
  - SQLite telemetry row 2: `repl_stdout_len=1052`, stdout contains `[TEST_SKILL:...]` lines through `[DYN_INSTR:...]` lines
  - Fixture runtime: `last_repl_result.stdout` for the same call contains extensive `[PLUGIN:before_agent:...]` and `[PLUGIN:after_model:...]` lines (2000+ chars with plugin instrumentation)
  - The telemetry stdout lacks the `[PLUGIN:...]`, `[STATE:...]`, and `[TIMING:...]` prefixed lines
- **Root cause:** The fixture runtime output includes plugin-injected print statements that are captured in the live stdout during execution, but the telemetry sqlite_tracing plugin captures stdout from the REPL result payload which is the clean execution output. The fixture diagnostic dump captures a different stdout path (possibly from the instrumented_runner's capture_plugin).
- **Impact:** When debugging, the fixture runtime output has richer data than what the dashboard shows from telemetry. Not a dashboard bug per se, but a discrepancy between what the test harness captures vs what the tracing pipeline records.
- **Severity:** Low -- informational. The telemetry data is correct for its purpose; the fixture dump has extra instrumentation.

### Mismatch 7: Depth=2 State Events Present But Not Surfaced

- **What:** Depth=2 state events exist in the SSE table but the dashboard has no way to display them in the main flow view.
- **Evidence:**
  - SQLite SSE: 4 events at key_depth=2 (seq 26-31): current_depth@d2=2, iteration_count@d2=0, reasoning_output@d2, final_response_text@d2="depth2_leaf_ok", should_stop@d2=true
  - Pipeline analysis: `_latest_state_by_depth` (line 961) correctly groups these by depth=2
  - Flow view: Only root pane content is rendered; depth=2 state requires child window drill-down through depth=1 first
- **Root cause:** Pipeline analysis Gap 5 -- the flow view is designed to show only root-pane content. Depth=2 content is accessible via the child window route (`/live/session/{id}/pane/{pane_id}`) but requires two levels of drill-down.
- **Impact:** User must know to click "Open window" on a depth=1 child card to see depth=1 content, then navigate further to see depth=2. Since Turn 1's depth=1 child is not even visible as a child card (Mismatch 3), the depth=2 chain is completely unreachable.
- **Severity:** High -- combined with Mismatch 3, creates an unreachable data path. The depth=2 chain data exists but has no visible entry point.

### Mismatch 8: `child_total_batch_dispatches` Is NULL in Traces

- **What:** The `child_total_batch_dispatches` column in the traces table is NULL despite a batch dispatch of 2 occurring.
- **Evidence:**
  - SQLite traces: `child_total_batch_dispatches: null`
  - Fixture: Turn 2 calls `llm_query_batched(['Summarize finding A', 'Summarize finding B'])` -- 1 batch dispatch of size 2
  - SQLite telemetry: Two model_call rows (call_number 6, 7) at depth=1 iteration=2 confirm the batch
  - Fixture runtime: `last_repl_result.total_llm_calls=2`
- **Root cause:** The `child_total_batch_dispatches` column is not being populated by the sqlite_tracing plugin's trace-finalization logic. The data exists in telemetry but is not aggregated into the trace summary row.
- **Impact:** Dashboard trace-level summary metrics are incomplete. Any dashboard widget that relies on `child_total_batch_dispatches` to show batch dispatch counts would show nothing.
- **Severity:** Medium -- missing aggregation. The data exists in telemetry rows but the summary column is not computed.

---

## Section 4: Gap Classification

### Data Loading Gaps (Data exists in SQLite but doesn't reach dashboard models)

| Gap | Description | Affected Data |
|-----|-------------|---------------|
| DL-1 | Per-iteration REPL code not loaded per-invocation | Turn 1's `run_test_skill` code exists in SSE (seq 3) and telemetry (row 2 result_payload) but loader reads only the latest `state_items` snapshot, so all invocations see Turn 2's code |
| DL-2 | Child summaries from earlier iterations not preserved | Turn 1's child dispatch (depth=2 chain) produced `obs:child_summary` events that are overwritten by Turn 2's batch children in `latest.child_summaries` |

### Model Assembly Gaps (Data reaches models but incorrectly assembled)

| Gap | Description | Affected Data |
|-----|-------------|---------------|
| MA-1 | Fanout index swap in telemetry custom_metadata_json vs column | Batch child model_call rows 11-12 have inconsistent fanout_idx between the DB column and embedded JSON |
| MA-2 | `has_errors` flag includes benign warnings | Turn 1 marked `has_errors=true` due to stderr containing a Python UserWarning, not an actual error |

### Rendering Gaps (Data is in models correctly but not rendered)

| Gap | Description | Affected Data |
|-----|-------------|---------------|
| RG-1 | Iteration navigation not rendered | `FlowAgentCard.available_iteration_ids` has 3 entries but `render_flow_reasoning_pane` renders no navigation widget |
| RG-2 | Depth=2 chain unreachable from flow view | Depth=2 pane exists in the model tree but has no visible entry point because Turn 1's depth=1 child card is not rendered (it belongs to a non-displayed iteration) |

### Missing UI Features (Data is available but no UI exists)

| Gap | Description | Affected Data |
|-----|-------------|---------------|
| MU-1 | No multi-iteration flow transcript | The flow_builder processes only one iteration (the selected/latest one). No way to see a "full run" timeline showing all iterations sequentially |
| MU-2 | No inline child expansion in flow view | Child content requires opening a separate browser tab. No accordion/inline expansion of child panes in the main flow |
| MU-3 | No batch dispatch grouping visualization | The 2 batch children are shown as individual child cards but there is no visual indication that they were part of a single `llm_query_batched` call |
| MU-4 | No REPL code diff between iterations | Earlier iteration code exists in telemetry result_payload but there is no UI to diff code across iterations at the same depth |

---

## Section 5: Recommendations

Ordered by impact and feasibility (highest first).

### Priority 1: Wire Iteration Navigation in Flow View (fixes Mismatches 1, 2, 3)

**Impact:** Critical -- unlocks visibility of all 3 reasoning turns and their respective child dispatches
**Feasibility:** High -- the data pipeline is fully wired through to `FlowAgentCard.available_iteration_ids`. Only the renderer needs a navigation widget.

**Implementation:**
1. In `render_flow_reasoning_pane` (flow_reasoning_pane.py), read `FlowAgentCard.available_iteration_ids`
2. Render a segmented control or dropdown with iteration labels (e.g., "Turn 1", "Turn 2", "Turn 3")
3. On selection change, call `controller.select_iteration(pane_id, invocation_id)` which already exists and is fully wired
4. This single change makes Turn 1's run_test_skill code, Turn 1's child cards, and Turn 2's batch code all navigable

### Priority 2: Source Per-Iteration REPL Code from Telemetry (fixes Mismatch 1 root cause)

**Impact:** Critical -- ensures each iteration displays its own code block, not just the latest
**Feasibility:** Medium -- requires changing the loader to source `repl_submitted_code` per-invocation from telemetry `tool_call` rows (which have `result_payload` containing the submitted code) rather than from the shared `state_items` snapshot.

**Implementation:**
1. In `_build_invocation` (live_loader.py ~line 1040), match the invocation's timestamp to the closest `tool_call` telemetry row where `tool_name="execute_code"`
2. Extract `repl_submitted_code` from the matched telemetry row's `result_payload` or from the corresponding SSE event at that timestamp
3. Fall back to `state_items` if no match found

### Priority 3: Preserve Per-Iteration Child Summaries (fixes Mismatch 3 root cause)

**Impact:** Critical -- ensures each iteration's child cards are displayed when that iteration is selected
**Feasibility:** Medium -- requires changing `_build_child_summaries` to index child summaries by iteration number rather than using only `latest.child_summaries`.

**Implementation:**
1. In `_build_child_summaries`, timestamp-correlate each `obs:child_summary` SSE event with the iteration that produced it
2. Store as `dict[int, list[LiveChildSummary]]` keyed by iteration
3. In `_build_invocation`, select the child_summaries matching the current invocation's iteration number

### Priority 4: Fix Fanout Index Metadata Inconsistency (fixes Mismatch 4)

**Impact:** Medium -- prevents potential misattribution in future features that read custom_metadata_json
**Feasibility:** High -- likely a one-line fix in the telemetry writer to ensure `custom_metadata_json` fanout_idx is sourced from the same value as the column.

**Implementation:**
1. In the sqlite_tracing plugin's model_call event handler, ensure `fanout_idx` in `custom_metadata_json` is written from the same source as the column value
2. Or: drop `fanout_idx` from `custom_metadata_json` since it duplicates the column

### Priority 5: Populate `child_total_batch_dispatches` in Traces (fixes Mismatch 8)

**Impact:** Medium -- completes trace-level summary for batch operations
**Feasibility:** High -- aggregate from telemetry rows during trace finalization.

**Implementation:**
1. In the trace finalization logic, count distinct batch groups by looking at telemetry rows where multiple children share the same parent iteration and timestamp window
2. Write the count to `child_total_batch_dispatches`

### Priority 6: Distinguish Warnings from Errors in `has_errors` (fixes Mismatch 5)

**Impact:** Low -- prevents false error indicators
**Feasibility:** High -- check stderr content for actual tracebacks vs Python warnings.

**Implementation:**
1. In REPLTool, only set `has_errors=true` if stderr contains an actual exception traceback (look for `Traceback (most recent call last):` or similar patterns)
2. Alternatively, add a separate `has_warnings` field

### Priority 7: Add Inline Child Expansion (addresses MU-2)

**Impact:** High -- eliminates the need to open separate browser tabs for child content
**Feasibility:** Low -- significant UI rework needed.

**Implementation:**
1. Add an expand/collapse button to `FlowChildCard`
2. On expand, call `build_flow_transcript([child_node])` and render inline
3. Recursively support expansion for grandchild nodes

---

## Appendix: Data Flow Diagram

```
Fixture (8 responses)
  |
  v
Pipeline Execution
  |
  +--> SQLite traces.db
  |      |-- traces (1 row): total_calls=8, iterations=2, max_depth=2  [CORRECT]
  |      |-- telemetry (16 rows): all depths, all calls                [CORRECT]
  |      |-- session_state_events (60 rows): all depths                [CORRECT]
  |
  +--> SQLite session.db
  |      |-- sessions (1 row)                                          [CORRECT]
  |      |-- events (26 rows): includes 16 re-emitted child events     [CORRECT]
  |
  +--> Dashboard Loader
  |      |-- _refresh_trace_row: reads traces row                      [CORRECT]
  |      |-- _refresh_telemetry: reads all 16 telemetry rows           [CORRECT]
  |      |-- _refresh_sse: reads all 60 SSE rows                       [CORRECT]
  |      |-- _build_snapshot:
  |           |-- state_items: LAST-WRITE-WINS per depth               [GAP: DL-1]
  |           |-- child_summaries: LATEST iteration only               [GAP: DL-2]
  |           |-- pane grouping: correct depth extraction              [CORRECT]
  |
  +--> Dashboard Controller
  |      |-- invocation_tree: correct root/child hierarchy             [CORRECT]
  |      |-- available_invocations: 3 entries for depth=0              [CORRECT]
  |      |-- select_iteration: fully wired                             [CORRECT]
  |
  +--> Flow Builder
  |      |-- FlowAgentCard: available_iteration_ids populated          [CORRECT]
  |      |-- FlowCodeCell: shows LAST iteration's code only            [GAP: inherits DL-1]
  |      |-- FlowChildCard: shows LAST iteration's children only       [GAP: inherits DL-2]
  |
  +--> Renderer
         |-- render_flow_reasoning_pane: NO iteration nav widget       [GAP: RG-1]
         |-- Flow view: root pane only, children via drill-down        [BY DESIGN]
         |-- Depth=2 chain: UNREACHABLE (no entry point)               [GAP: RG-2]
```

---

## Summary

The SQLite telemetry pipeline captures ALL data correctly: 16 telemetry rows across 3 depths, 60 state events, and accurate trace summaries. The data loading pipeline also retrieves everything. The failures are concentrated in two areas:

1. **Per-iteration data isolation** (Mismatches 1, 3): The loader shares state snapshots across all iterations at a depth, losing per-iteration REPL code and child summaries. This is the root cause of the most critical visibility gaps.

2. **Missing iteration navigation UI** (Mismatch 2): The controller and flow_builder correctly prepare iteration navigation data, but the renderer never displays it. This is the single highest-impact fix because it would unlock the per-iteration data that is already partially available.

Fixing Priority 1 (iteration navigation widget) alone would substantially improve the dashboard, even before Priority 2 and 3 fix the underlying per-iteration data sourcing.
