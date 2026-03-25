# Dashboard Data Pipeline Analysis: `skill_arch_test` Provider-Fake Run

**Date:** 2026-03-25
**Fixture:** `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json`
**Expected run shape:** 8 model calls total across 3 depths — 3 reasoning turns at depth=0, a depth=1 child dispatched by `run_test_skill`'s internal `llm_query`, a depth=2 grandchild via the child's `execute_code -> llm_query`, plus 2 batched children from the root's third turn.

---

## Stage 1: Data Loading (`live_loader.py`)

### 1.1 Entry point: `load_session` (line 268)

`LiveDashboardLoader.load_session` is called both at page load and on every 1-second poll. It drives four incremental refresh methods in sequence:

**`_refresh_trace_row` (line 538):** Queries `traces.db` for the latest `traces` row matching `session_id`. Resets the cache if the `trace_id` changed (line 555-560). If no trace row exists, returns an `"idle"` snapshot immediately and skips all other loading.

**`_refresh_telemetry` (line 569):** Queries `telemetry WHERE trace_id = ? AND start_time > {watermark}`. No depth filter. Retrieves `model_call` and `tool_call` rows from ALL depths. Columns fetched include `depth`, `agent_name`, `iteration`, `repl_stdout`, `repl_stderr`, `result_payload`, and `repl_trace_summary`. All 8 model call rows accumulate here.

**`_refresh_sse` (line 632):** Queries `session_state_events WHERE trace_id = ? AND seq > {watermark}`. Again no depth filter. Retrieves state mutations from all depths via the child re-emission bridge. The `key_depth` column identifies which recursion depth wrote each key.

**`_refresh_jsonl` (line 657):** Called twice — for `context_snapshots.jsonl` and `model_outputs.jsonl`. Both files are seeked to the stored byte-offset watermark and scanned forward, filtering by `session_id` at line 682. These JSONL files are the primary source for request chunks, per-iteration context windows, and model output text.

All four sources accumulate in a per-session `_SessionCache`. Nothing is discarded between polls.

### 1.2 Snapshot assembly: `_build_snapshot` (line 695)

This is where raw rows are turned into `LivePane` and `LiveInvocation` objects.

**Step 1 — Child summaries (line 702):** `_build_child_summaries` scans SSE rows for `state_key == "obs:child_summary"`. Each matched row is decoded as a JSON payload and grouped by `depth`. For `skill_arch_test` this will capture depth=1 children (written by the root dispatcher) and depth=2 grandchildren (only if the child re-emission bridge propagated their `obs:child_summary` writes upward into the root SSE stream).

**Step 2 — Fanout matching (line 703):** `_match_child_summaries` (line 919) assigns `fanout_idx` values to snapshots by matching prompt text or timestamps. The matching is heuristic: it tries substring match between the child summary's `prompt_preview` and the snapshot's chunk text (lines 937-943), then falls back to the closest-timestamp snapshot (lines 944-958). If prompt previews don't overlap or are empty, the fallback governs.

**Step 3 — Pane grouping (lines 714-737):** For every snapshot from the JSONL files, `_depth_from_agent(snapshot["agent_name"])` extracts the depth. At line 86-90, this regex parses `_d(\d+)` from the name string. The special case `"reasoning_agent"` maps to 0. Worker agents must follow the naming convention `*_d1`, `*_d2`, etc. The `(depth, fanout_idx)` pair forms the pane key. All snapshots sharing a key accumulate into one pane's `invocations` list — this is how 3 reasoning turns at depth=0 produce 3 `LiveInvocation` entries.

**Step 4 — State items (line 704):** `_latest_state_by_depth` (line 961) scans all SSE rows and keeps the latest value per `(depth, base_key)` tuple. The result is a `dict[int, list[LiveStateItem]]` indexed by depth. Every `LiveInvocation` at the same depth receives the identical `state_items` list — the snapshot of the full latest state for that depth.

**Step 5 — Model events grouping (lines 707-712):** Telemetry rows of type `model_call` are grouped by depth and passed to `_build_invocation` where they are filtered by a 10ms timestamp window against the snapshot timestamp (line 1031: `abs(start_time - snapshot_timestamp) < 0.01`).

**Step 6 — Pane object construction (lines 757-809):** For each `(depth, fanout_idx)`, a `LivePane` is built. Key assignments:
- `parent_pane_id` at line 790: for depth=1, always `"d0:root"` regardless of fanout. For depth>1, `_pane_id(depth-1, fanout_idx)`.
- `invocations` at line 806: the full list of all `LiveInvocation` objects seen at this pane, ordered by snapshot time.
- `iteration` at line 783: `max(inv.iteration for inv in invocations)`.
- Token sums aggregate across all iterations at lines 785-788.
- `child_summaries` at line 795: from `latest.child_summaries` (the most recent iteration only).

### 1.3 What is NOT loaded

- Individual per-iteration REPL code is not preserved per-invocation. `state_items` is the same latest-state snapshot for all iterations at a depth, so `REPL_SUBMITTED_CODE` in state reflects only the last submission.
- The `_build_invocation` at line 1040 reads `REPL_SUBMITTED_CODE` from this shared `state_items` list.

---

## Stage 2: Data Models (`live_models.py`)

### 2.1 `LiveInvocation` (line 180)

Represents one model request event (one snapshot entry). Notable:
- `child_summaries: list[LiveChildSummary]` at line 196: populated at loader line 1045 with `[child for child in child_summaries if child.parent_depth == depth]`. A depth=0 invocation only sees depth=1 children. A depth=1 invocation only sees depth=2 children.
- `repl_submission: str` at line 198: sourced from `state_items[REPL_SUBMITTED_CODE].value`, which is the same for all invocations at that depth. All 3 depth=0 iterations show the same (last) code block.
- `model_events: list[LiveModelEvent]` at line 204: matched per-snapshot by timestamp (10ms window). The 3 model calls at depth=0 are each attached to their respective snapshot IF the timestamp alignment holds.

### 2.2 `LivePane` (line 208)

Aggregates all invocations at a `(depth, fanout_idx)` pair. The `invocations` field at line 242 is the full iteration history, enabling multi-iteration navigation. The `iteration` scalar at line 222 is the maximum.

### 2.3 `LiveChildSummary` (line 106)

Sourced from `obs:child_summary` SSE events. Contains `parent_depth`, `depth`, `fanout_idx`, prompt/result text (truncated), token counts, and `structured_output`. No direct linkage to the child `LiveInvocation` or `pane_id` — only the `(depth, fanout_idx)` coordinates.

### 2.4 `LiveInvocationNode` (line 271)

Built by the controller. Contains the selected `invocation`, all `available_invocations` in the time window, `child_nodes` recursively for child panes, and the ancestor `lineage`. This is the full tree node used by both the flow builder and the tree renderer.

### 2.5 `LiveDashboardState` (line 316)

Application-level mutable state. Key fields:
- `selected_invocation_id_by_pane: dict[str, str]` (line 330): maps `pane_id` to the currently-selected `invocation_id`. Defaults to the latest.
- `view_mode: str = "flow"` (line 343): controls whether the `invocation_section` renders the flow view or the tree view.
- `auto_follow: bool = True` (line 333): when true, the active pane automatically tracks the most recently active pane.

---

## Stage 3: Flow Building (`flow_builder.py`)

### 3.1 `build_flow_transcript` (line 58)

Called by `controller.flow_transcript()` (controller line 413-415). Receives the list returned by `controller.invocation_tree()` — this list contains ONLY root-level nodes (those with `parent_pane_id is None`). For `skill_arch_test` that is one node: the depth=0 root.

The function iterates over that list and calls `_process_node` on each. No recursion into `child_nodes`. The child nodes are present in the tree structure but deliberately not traversed here.

### 3.2 `_process_node` (line 74)

For one `LiveInvocationNode`, emits these blocks in order:

1. **`FlowAgentCard`** (line 82-103): always emitted. Contains `available_iteration_ids` at line 90-92 — a list of `(iteration_number, invocation_id)` tuples for all available iterations. For 3 reasoning turns this contains 3 entries. The `iteration` field is the selected iteration's number.

2. **`FlowArrow` + `FlowCodeCell`** (lines 106-140): emitted only if `inv.repl_submission` is non-empty. The code cell's `llm_query_lines` (line 113) are found by AST-parsing the code and matched positionally to `inv.child_summaries`.

3. **`FlowArrow` + `FlowChildCard` + `FlowArrow`** per child (lines 142-179): one triplet per `LiveChildSummary` in `inv.child_summaries`. These show as inline child agent cards with prompt preview, result preview, and token counts. The `pane_id` field on `FlowChildCard` is looked up via `_find_child_pane_id` from `node.child_nodes`.

4. **`FlowOutputCell`** (lines 194-203): stdout/stderr from `inv.repl_stdout` / `inv.repl_stderr`.

The comment at lines 213-215 explicitly documents the design decision: "Child nodes are accessed via drill-down (child window route), not inlined in the main transcript."

### 3.3 What the flow transcript shows for `skill_arch_test`

Given 3 reasoning turns at depth=0 and the latest iteration selected:
- One `FlowAgentCard` with `available_iteration_ids` having 3 entries (but no UI to navigate them)
- One `FlowCodeCell` with the last reasoning turn's code (the `llm_query_batched` call)
- Two `FlowChildCard` blocks for the two batched children at depth=1
- One `FlowOutputCell`

The depth=1 child's code execution (calling `llm_query` to produce the grandchild), the depth=2 grandchild invocation, and the first two reasoning turns' code are all absent from the main flow view.

---

## Stage 4: Controller State Management (`live_controller.py`)

### 4.1 `invocation_tree` (line 402)

```python
roots = [pane for pane in self.state.snapshot.panes if pane.parent_pane_id is None]
```

Only panes with no parent are roots. All others are embedded in the tree as `child_nodes`.

### 4.2 `_build_invocation_node` (line 530)

Handles the complex timestamp-windowing logic for multi-iteration trees:

- `visible_invocations` are filtered by `lower_bound <= timestamp < upper_bound`. Initially `lower_bound = -inf`, `upper_bound = +inf` for the root.
- `_dedupe_invocations_by_iteration` (line 648) keeps the latest snapshot per iteration number.
- The selected invocation defaults to the latest; `select_iteration` can override it.
- Children's `lower_bound` is set to `prev_ts` (the previous iteration's timestamp) at line 569, which keeps children visible across iteration changes.
- Child panes are found via `child.parent_pane_id == pane.pane_id` at line 560.

### 4.3 Iteration navigation mechanism

`select_iteration` (line 349) writes to `selected_invocation_id_by_pane`. When a user changes the iteration, descendant pane selections are cleared (line 357-358). `_refresh_run_state` is called to rebuild the full tree and flow transcript.

This mechanism is fully wired in the controller. The gap is that no UI component exposes iteration navigation in the flow view.

### 4.4 `available_iteration_ids` data path

1. `LivePane.invocations` (loader, line 806): accumulates all iterations
2. `_build_invocation_node` visible_invocations (controller, line 541-546): time-filtered subset
3. `_dedupe_invocations_by_iteration` (controller, line 648): one per iteration number
4. Passed as `available_invocations` into `LiveInvocationNode` (controller, line 593)
5. Read in `_process_node` at flow_builder.py line 90-92 into `FlowAgentCard.available_iteration_ids`
6. Passed to `render_flow_reasoning_pane` as part of the `FlowAgentCard` object
7. `render_flow_reasoning_pane` in `flow_reasoning_pane.py` does NOT read `available_iteration_ids`. No widget renders it.

---

## Stage 5: Rendering

### 5.1 Main page wiring (`live_app.py`)

`invocation_section` at line 441 branches on `controller.state.view_mode`:
- `"flow"` (default): calls `_render_flow_view` at line 444
- `"tree"`: calls `render_live_invocation_tree` at line 446

`_render_flow_view` (line 918) calls `controller.flow_transcript()` then `render_flow_transcript`. The flow transcript contains blocks only for the root pane.

"Open window" on a `FlowChildCard` triggers `_open_child_window` at line 992-1000, which opens `/live/session/{session_id}/pane/{child.pane_id}` in a new browser tab.

### 5.2 Flow transcript renderer (`flow_transcript.py`)

`render_flow_transcript` iterates over `transcript.blocks` and dispatches each to a renderer by `block.kind`. The full rendering pipeline:

- `"agent_card"` → `render_flow_reasoning_pane` (`flow_reasoning_pane.py`)
- `"arrow"` → `render_flow_arrow` (`flow_connectors.py`)
- `"code_cell"` → `render_flow_code_pane` (`flow_code_pane.py`)
- `"child_card"` → `render_flow_child_card` (`flow_connectors.py`)
- `"output_cell"` → `render_flow_output_cell` (`flow_output_cell.py`)

### 5.3 Tree view renderer (`live_invocation_tree.py`)

`_render_node` at line 57 renders the node then calls `_render_child_row` for each item in `node.child_nodes` (line 75-80). `_render_child_row` recursively calls `_render_node`, so the full depth tree is rendered. The tree view shows ALL depths in one scrollable column.

Each node shows:
- Header: agent name, context token count, status, depth/fanout
- `_child_summary_bar` (line 176): `node.invocation.child_summaries` as clickable cards. Clicking opens a text viewer with prompt + result + thought text.
- `_model_call_detail` (line 253): one chip per `LiveModelEvent` showing iteration, tokens, finish reason, duration.
- `_scope_groups` (line 291): context banner items grouped by scope.
- REPL panel (line 321): code/stdout/stderr buttons that open a text viewer with `node.parent_code_text` etc.

The `_loop_detection_warning` (line 142) is the only place `node.available_invocations` is used in either renderer, purely to detect repeated code hashes.

### 5.4 Child window (`flow_child_page.py`)

Route `/live/session/{session_id}/pane/{pane_id}` at line 32. Uses `_find_subtree_node` to DFS-search the full tree for the target pane. Calls `build_flow_transcript([target_node])` to render that pane as the root of its own flow transcript. The child's code cells, grandchild dispatch arrows, and output cell are all visible here.

---

## Critical Questions: Direct Answers

### Does the dashboard load data from ALL 8 model calls or only root-level ones?

All 8 are loaded. `_refresh_telemetry` queries `telemetry WHERE trace_id = ?` with no depth restriction. `stats.total_live_model_calls` at loader line 821 counts every `model_call` row regardless of agent depth. The "model calls" metric chip in the header reflects the true total.

### Are child invocations at depth=1 and depth=2 loaded and renderable?

Loaded: yes, if context_snapshots.jsonl contains entries from those agents. State: yes, via SSE re-emission. Renderable in the tree view: yes, recursively. Renderable in the flow view main page: only as `FlowChildCard` summaries (prompt preview + result + tokens). The actual code execution and further child dispatch at depth=1 and depth=2 require the child window route.

### Does the flow transcript show ALL reasoning turns (iterations) or just one?

One — the selected iteration (default: latest). The 3 reasoning turns at depth=0 produce 3 `LiveInvocation` objects and 3 entries in `available_iteration_ids`, but no UI in the flow view renders navigation controls for them. Switching turns requires the tree view (which shows the selected iteration only) or the future implementation of iteration navigation in `render_flow_reasoning_pane`.

### How does the `available_iteration_ids` mechanism work?

The data flows correctly through every layer (loader → pane.invocations → controller visible_invocations → LiveInvocationNode.available_invocations → FlowAgentCard.available_iteration_ids). The final step — rendering navigation controls — is not implemented. The field is populated but the renderer ignores it.

### Is there a route/UI to view child invocations (drill-down)?

Yes: `/live/session/{session_id}/pane/{pane_id}` via `flow_child_page.py`. Triggered from "Open window" buttons on `FlowChildCard` elements (flow_connectors.py line 141-147). This opens a fresh flow transcript rooted at the child pane, showing the child's code cells, grandchild dispatch, and output. No in-page expansion exists.

---

## Identified Gaps

**Gap 1 — Iteration navigation not wired** (`flow_reasoning_pane.py`, `_header_row`): `FlowAgentCard.available_iteration_ids` is populated but `render_flow_reasoning_pane` does not render any navigation widget. Users cannot switch between the 3 reasoning turns in the flow view.

**Gap 2 — `repl_submission` shared across iterations** (loader line 1040-1087): All `LiveInvocation` objects at a depth share the same `state_items` snapshot. `REPL_SUBMITTED_CODE` reflects only the last submitted code block. Earlier iterations' code is not reconstructable per-invocation from current data.

**Gap 3 — Child summaries only from latest iteration** (loader line 795): `LivePane.child_summaries` and the flow transcript's `FlowChildCard` blocks reflect `latest.child_summaries`. Earlier iterations that dispatched different children are not represented.

**Gap 4 — `_depth_from_agent` agent name dependency** (loader line 86-90): Child agent depth is extracted from the agent name string via the `_d(\d+)` regex pattern. If the skill system or thread bridge creates child agents under different naming conventions, depth extraction silently returns 0 and those agents merge into the root pane.

**Gap 5 — Flow view does not inline child depth content** (flow_builder.py line 213-215): Design choice, not a bug — but means the main flow view shows only root-pane content. The depth=1 code execution and depth=2 dispatch for `skill_arch_test` are only visible through the child window route.

**Gap 6 — Model events 10ms timestamp window** (loader line 1031): Model events are attached to snapshots using `abs(start_time - snapshot_timestamp) < 0.01`. On slower machines or under load, model calls and snapshot writes may be far enough apart in wall time that model events do not attach, leaving `model_events = []` on some invocations.
