# Live Recursive Dashboard Spec

## Goal

Build a live NiceGUI dashboard for recursive RLM execution that shows the active reasoning layer, active child fan-out, live REPL activity, and the exact model-facing context for the currently active pane.

This spec is based on the current dashboard/UI structure in [app.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/app.py#L37), [controller.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/controller.py#L23), and the existing observability paths in [context_snapshot.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py#L47), [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L1), [repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L106), and [dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L106).

## Non-goals

- Do not extend the existing context-window dashboard page in place as the primary live workflow.
- Do not make the live page depend on in-process Python object references.
- Do not treat full-session iteration navigation as the primary interaction model.

## Current Constraints

- The current page is a fixed, post-hoc layout assembled from summary cards, charts, and three static detail panels. It is not recursive-pane aware: [app.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/app.py#L209).
- The current controller state models iterations and selected chunks, not live panes, active depth, or active fan-out: [controller.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/controller.py#L23).
- The current dashboard data model is context-window centric, not event centric: [data_models.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/data_models.py#L64).
- Live JSONL snapshots already flush during model calls, but the current loader reads them as completed session history: [context_snapshot.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py#L108), [data_loader.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/data_loader.py#L72).

## Recommendation

Add a new page, `"/live"`, with a separate controller and loader pair:

- `rlm_adk/dashboard/live_app.py`
- `rlm_adk/dashboard/live_controller.py`
- `rlm_adk/dashboard/live_models.py`
- `rlm_adk/dashboard/live_loader.py`
- `rlm_adk/dashboard/components/live_context_banner.py`
- `rlm_adk/dashboard/components/live_layer_strip.py`
- `rlm_adk/dashboard/components/live_layer_pane.py`
- `rlm_adk/dashboard/components/live_detail_tabs.py`

Keep the existing `"/dashboard"` page intact for post-run analysis.

## Visual Direction

- Dark mode only for v1. Match the current dashboard’s dark posture from `ui.dark_mode(True)`, but use a more explicit surface system than ad hoc per-component colors: [app.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/app.py#L49).
- Define page-level CSS variables once on page load:
  - `--bg-0: #0b1020`
  - `--bg-1: #131a2b`
  - `--bg-2: #1a2338`
  - `--border-1: #2e3a57`
  - `--text-0: #e6edf7`
  - `--text-1: #9fb0d1`
  - `--accent-root: #57c7ff`
  - `--accent-child: #ff6b9f`
  - `--accent-active: #7ef0a0`
  - `--accent-warning: #ffd166`
- Use inline `style("gap: ...")`, explicit `min-width: 0`, and explicit heights for scroll areas.

## Page Layout

The page has three vertical bands:

1. Sticky run header
2. Sticky pinned context banner
3. Live recursive layer strip

### 1. Sticky Run Header

Render a top bar that remains visible during horizontal and vertical scrolling.

Contents:

- Title: `RLM Live Recursive Dashboard`
- Session selector
- Run status badge: `running`, `idle`, `completed`, `error`
- Auto-follow toggle
- Pause live updates toggle
- Depth/fan-out breadcrumb for the active pane
- Small stats row: total live model calls, active depth, active children

Implementation note:

- Reuse the current `build_header` style structure as the starting point, but move the live-specific state into the live controller: [header.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/components/header.py#L12).

### 2. Sticky Context Banner

This banner is pinned under the header and always reflects only the invocation context of the active pane.

Rules:

- Show every possible state key / dynamic instruction parameter / model-input-bearing variable known to the system.
- Render keys present in the active pane’s invocation context in green.
- Render keys absent from the active pane muted.
- When the active pane changes, clear the banner state and rebuild it from that pane only.
- Do not union keys across siblings, parent layers, or prior active panes.
- For every displayed item, append token quantity in parentheses next to the label.
- If the quantity is exact, show `123 tok`.
- If the quantity is estimated, show `~123 tok`.

Example labels:

- `repo_url (18 tok)`
- `root_prompt (92 tok)`
- `skill_instruction (~140 tok)`
- `repl_submitted_code@d1 (~220 tok)`
- `reasoning_visible_output_text@d2 (311 tok)`

Banner groups:

- Dynamic instruction params
- Depth-scoped state keys
- Context chunks hitting the active LLM request
- Tool-originated variables promoted into the active request

Implementation semantics:

- Source the known key universe from [state.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L11), plus the dynamic instruction template in [prompts.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/utils/prompts.py#L82).
- Treat `repo_url`, `root_prompt`, and `skill_instruction` as first-class banner items because they are explicitly injected into `instruction=` and then merged into `system_instruction`: [prompts.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/utils/prompts.py#L82), [reasoning.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py#L109).
- Use the context snapshot chunks as the authoritative list of text fragments that hit the model request for the active pane: [context_snapshot.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py#L126).

### 3. Live Recursive Layer Strip

This is the primary workspace.

Rules:

- The strip is horizontally scrollable.
- At most 3 layer panes are fully visible at once.
- If more than 3 panes exist in the active lineage, allow sideways scrolling.
- If exactly 1 child worker is active, render a single pane that fills the available width.
- Only the active recursive layer pane is expanded.
- Non-active panes collapse to a narrow summary rail.
- Pane headers must clearly show:
  - layer depth
  - fan-out index
  - agent name
  - status

Header format:

- `Layer 0 | Fan-out root | reasoning_agent`
- `Layer 1 | Fan-out 0 | child_orchestrator_d1`
- `Layer 2 | Fan-out 3 | child_orchestrator_d2`

Width behavior:

- Single active pane: `flex: 1 1 100%`
- 2 active-lineage panes: each roughly `min(50%, 900px)`
- 3 visible panes: each roughly `min(33.333%, 720px)`
- Additional panes: horizontal scroll, preserve same width contract
- Collapsed panes: fixed rail width `88px`

Implementation note:

- Use `display: flex`, `overflow-x: auto`, and `min-width: 0` on pane wrappers.
- Do not use `ui.row().classes("gap-*")`; use inline style gaps.

## Pane Behavior

Each pane represents one active invocation layer, not one iteration.

Pane states:

- `active-expanded`
- `inactive-collapsed`
- `completed-collapsed`
- `error-collapsed`

Only one pane can be `active-expanded` at a time.

Interaction rules:

- Clicking a collapsed pane makes it active and expands it.
- Auto-follow, when enabled, shifts active focus to the newest active child layer.
- If a child layer completes and control returns to the parent, the parent becomes active again and its pane expands.
- If a batched dispatch creates multiple children, the strip should show only the active child lineage by default plus sibling summary chips in the parent pane header.

## Pane Internal Layout

Expanded pane structure:

1. Pane header
2. Context window summary row
3. Detail tabs
4. Optional sibling fan-out rail

### Pane Header

Contents:

- Layer depth badge
- Fan-out badge
- Agent/model label
- Iteration / tool-call number
- Status badge
- Input / output / thought token badges

### Context Window Summary Row

Compact badges:

- total prompt tokens
- total output tokens
- thought tokens
- chunk count
- model name
- elapsed time

### Detail Tabs

Tabs:

- `Request`
- `Reasoning`
- `Code`
- `Children`
- `Structured`
- `Stdout`
- `Stderr`
- `Raw`

Tab semantics:

- `Request`: exact LLM request decomposition for this pane
- `Reasoning`: visible answer plus thought trace if available
- `Code`: latest `execute_code` submission and expanded code if skill expansion occurred
- `Children`: child `llm_query` / `llm_query_batched` prompts and child summaries
- `Structured`: child structured output result and retry metadata
- `Stdout`: full REPL stdout
- `Stderr`: full REPL stderr
- `Raw`: raw JSON payload for debugging

### Sibling Fan-out Rail

When the parent pane spawned multiple children:

- Show a horizontal rail of sibling chips inside the parent pane header or just beneath it.
- Each chip label: `f0`, `f1`, `f2`, plus status color.
- Clicking a sibling chip re-roots the active lineage on that sibling.

## Data Model

Add new live models rather than overloading `IterationData`.

Required models:

- `LiveRunState`
- `LivePane`
- `LiveInvocation`
- `LiveContextItem`
- `LiveContextBannerItem`
- `LiveChildSummary`
- `LiveToolEvent`
- `LiveModelEvent`

### LivePane

Fields:

- `pane_id`
- `depth`
- `fanout_idx | None`
- `agent_name`
- `model`
- `status`
- `is_active`
- `is_expanded`
- `iteration`
- `latest_tool_call_number | None`
- `input_tokens`
- `output_tokens`
- `thought_tokens`
- `request_chunks`
- `state_items`
- `child_summaries`
- `repl_submission`
- `repl_stdout`
- `repl_stderr`
- `reasoning_visible_text`
- `reasoning_thought_text`
- `structured_output`

### LiveContextBannerItem

Fields:

- `label`
- `raw_key`
- `scope`
- `present`
- `token_count`
- `token_count_is_exact`
- `source_kind`
- `display_value_preview`

`source_kind` values:

- `dynamic_instruction_param`
- `state_key`
- `request_chunk`
- `tool_variable`

## Data Sources

Use a composite live loader.

### Primary source: SQLite telemetry

Use `.adk/traces.db` as the default cross-process live source because it already persists:

- model call rows
- tool call rows
- curated state-delta rows

Relevant behavior:

- Curated state capture and depth/fanout parsing already exist: [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L45).
- Model-call telemetry already stores `skill_instruction`, `prompt_chars`, and `system_chars`: [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L740).
- Tool telemetry already stores REPL summary fields: [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L909).

### Secondary source: Context snapshot JSONL

Use `.adk/context_snapshots.jsonl` for exact request decomposition because it stores full chunks that hit each model call: [context_snapshot.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py#L139).

Use `.adk/model_outputs.jsonl` for output text where available: [context_snapshot.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py#L156).

### Existing live data already available

- Root reasoning request chunks: yes
- Worker request chunks: yes
- Root reasoning output text: yes
- Worker output text: yes
- REPL submitted code: yes, via depth-scoped state keys
- REPL summary: yes
- Child summary with depth/fan-out: yes
- Structured child result summary: yes

### Existing live data not persisted in full yet

- Full reasoning thought text is written to state but not captured by SQLite’s curated state set: [reasoning.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py#L176), [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L92).
- Full REPL stdout/stderr bodies are returned from `execute_code`, but SQLite stores only lengths and summary flags: [repl_tool.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/tools/repl_tool.py#L310), [sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L909).
- Child summaries currently store only prompt/result previews at 500 chars for several fields: [dispatch.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dispatch.py#L499).

## Required Runtime Additions

These are required for the live page to satisfy the user-facing requirements fully.

### 1. Persist full reasoning thought text

Expand SQLite curated capture to include:

- `reasoning_visible_output_text`
- `reasoning_thought_text`
- `reasoning_raw_output`
- `reasoning_parsed_output`

This allows the active pane’s `Reasoning` tab to show full trace text live.

### 2. Persist full REPL stdout/stderr

Add one of these:

- Preferred: store full `stdout` and `stderr` in a new `tool_payloads` table keyed by telemetry id
- Acceptable v1: store them in `telemetry.result_preview_json` without truncation and gate behind env var

### 3. Persist full child prompt/result payloads

Keep current summary keys, but add non-preview fields for:

- `prompt`
- `visible_output_text`
- `thought_text`
- `raw_output`

The active child pane needs the full content, not previews.

## Context Banner Token Accounting

The banner must display token quantities next to each variable-like item that hit the model API.

### Exact counts

These are exact today:

- total request input tokens for a model call from `usage_metadata.prompt_token_count`
- total output tokens from `usage_metadata.candidates_token_count`
- total thought tokens from `usage_metadata.thoughts_token_count`
- worker prompt/input tokens from worker callback records

Sources:

- [reasoning.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/reasoning.py#L184)
- [worker.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/callbacks/worker.py#L131)
- [context_snapshot.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/context_snapshot.py#L129)

### Estimated per-item counts

Per-variable and per-chunk token counts are estimated today by proportional character distribution in the dashboard loader: [data_loader.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/data_loader.py#L270).

Use these rules:

- For context chunks in a single request, use proportional estimates and prefix with `~`.
- For dynamic instruction fields (`repo_url`, `root_prompt`, `skill_instruction`), compute an estimated token count from the actual rendered text length within the request decomposition and prefix with `~` unless an exact item-level tokenizer is added.
- For fields that are stored separately with exact token counts in the future, drop the `~`.

### Banner presence logic

An item is `present` only if it contributes text to the active pane’s actual invocation context.

Examples:

- `repo_url` absent if empty in the rendered dynamic instruction
- `skill_instruction` absent if not present in the active depth’s instruction routing
- `repl_submitted_code@d1` present only while that depth’s latest invocation actually includes it in the active model-facing history

## Interaction Model

### Auto-follow

- Default on
- When a child layer becomes active, scroll the strip so the new active pane is visible
- Keep the active pane in the center when possible

### Manual focus

- Clicking a pane disables auto-follow until re-enabled
- Clicking sibling fan-out chips swaps the active lineage

### Clearing behavior

- On pane switch, clear the context banner immediately
- Rebuild from the newly active pane snapshot
- Do not leave stale green items from the previously active pane

## NiceGUI Implementation Notes

- Use a dedicated `ui.timer(0.25, ...)` poll loop for the live controller.
- Poll with a watermark rather than reloading full files/tables every tick.
- Keep rendering thin; all event merging belongs in the live controller.
- Use a horizontal `div` strip instead of `ui.row` for the pane scroller so width and overflow are explicit.
- Use `ui.scroll_area` only inside pane tabs, not around the whole page.
- Use `min-width: 0` on all flex children that contain wide content.

## Build Plan

1. Add live models and controller state.
2. Add a composite live loader backed by SQLite + context snapshot JSONL.
3. Add the new `"/live"` page and sticky header/banner shell.
4. Implement the layer strip with max-3 visible panes and horizontal scroll.
5. Implement active-pane expansion and sibling fan-out switching.
6. Implement detail tabs with current persisted data.
7. Add the three runtime persistence upgrades for thought text, full stdout/stderr, and full child payloads.
8. Upgrade the context banner from estimated-only to mixed exact/estimated labeling where possible.

## Acceptance Criteria

- The live page runs while a session is still executing.
- Only one recursive layer pane is expanded at a time.
- When exactly one child worker is active, that pane fills the available workspace width.
- When more than three panes exist in the active lineage, the strip scrolls horizontally.
- Pane headers always show layer depth and fan-out clearly.
- The pinned context banner reflects only the active pane’s invocation context.
- Present banner items are green and absent items are muted.
- Every banner item displays a token quantity, exact or estimated.
- The active pane can show request, reasoning, code, child summaries, structured output, stdout, and stderr without requiring the session to end.
