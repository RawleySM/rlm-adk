# Plan: Context Window Token Dashboard (NiceGUI)

## Overview

A NiceGUI dashboard that graphically visualizes context window token composition for the `reasoning_agent` and `worker` agents at every iteration turn of an RLM session. Users navigate between iterations with forward/backward arrows, seeing which context chunks (system prompts, user prompts, LLM responses, REPL code/output, context vars) consume what fraction of the token budget — color-coded by class with hover/collapsible text previews. A Google Cloud API token usage panel cross-references local tracking against server-side billing, flagging mismatches.

---

## 1. Data Model

### 1.1 Session Summary

Top-level metadata loaded when a session is selected.

```python
@dataclass
class SessionSummary:
    session_id: str
    app_name: str
    user_id: str
    model: str                           # e.g. "gemini-3-pro-preview"
    total_iterations: int                # from ITERATION_COUNT
    total_input_tokens: int              # from OBS_TOTAL_INPUT_TOKENS
    total_output_tokens: int             # from OBS_TOTAL_OUTPUT_TOKENS
    total_calls: int                     # from OBS_TOTAL_CALLS
    total_execution_time: float          # from OBS_TOTAL_EXECUTION_TIME
    worker_total_dispatches: int
    start_time: float
    end_time: float
```

Source: `sessions` table `state` JSON column contains all `obs:` keys after run completes.

### 1.2 Per-Iteration

```python
@dataclass
class IterationData:
    iteration_index: int                 # 0-based
    reasoning_window: ContextWindow
    worker_windows: list[ContextWindow]  # empty if no workers dispatched
    reasoning_input_tokens: int
    reasoning_output_tokens: int
    worker_input_tokens: int             # sum across all workers
    worker_output_tokens: int
    has_workers: bool
    timestamp_start: float
    timestamp_end: float
```

### 1.3 Context Window & Chunks

```python
@dataclass
class ContextWindow:
    agent_type: str                      # "reasoning" | "worker"
    agent_name: str                      # e.g. "reasoning_agent" or "worker_7"
    iteration: int
    chunks: list[ContextChunk]
    total_chars: int
    total_tokens: int                    # from usage_metadata.prompt_token_count
    output_tokens: int                   # from usage_metadata.candidates_token_count
    model: str

@dataclass
class ContextChunk:
    chunk_id: str
    category: ChunkCategory
    title: str                           # descriptive label
    char_count: int
    estimated_tokens: int                # proportional from known total
    iteration_origin: int                # which iteration generated this content
    text_preview_head: str               # first 5 lines
    text_preview_tail: str               # last 5 lines
    full_text: str                       # for expand view
```

### 1.4 Chunk Categories

```python
class ChunkCategory(str, Enum):
    STATIC_INSTRUCTION  = "static_instruction"   # RLM_STATIC_INSTRUCTION
    DYNAMIC_INSTRUCTION = "dynamic_instruction"   # resolved {repo_url?}, {root_prompt?}
    USER_PROMPT         = "user_prompt"           # build_user_prompt() output
    LLM_RESPONSE        = "llm_response"          # assistant messages (reasoning output)
    REPL_CODE           = "repl_code"             # code execution submissions
    REPL_OUTPUT         = "repl_output"           # stdout/stderr/print() from REPL
    CONTEXT_VAR         = "context_var"           # injected context variables from REPL
    WORKER_PROMPT       = "worker_prompt"         # prompt sent to a worker
    WORKER_RESPONSE     = "worker_response"       # response from a worker
```

### 1.5 API Token Reconciliation

```python
@dataclass
class APITokenUsage:
    source: str                          # "local_obs" | "gcloud_monitoring" | "gcloud_billing"
    total_input_tokens: int
    total_output_tokens: int
    total_calls: int
    per_model: dict[str, ModelTokenUsage]

@dataclass
class TokenReconciliation:
    local_input_tokens: int
    local_output_tokens: int
    api_input_tokens: int
    api_output_tokens: int
    input_delta: int
    output_delta: int
    input_match: bool                    # abs(delta) < 5% threshold
    output_match: bool
    error_message: str | None
```

---

## 2. Existing Data Sources

The codebase already captures most of what the dashboard needs. Three sources, in order of richness:

### 2.1 Debug YAML (`rlm_adk_debug.yaml`)

Written by `DebugLoggingPlugin.after_run_callback`. Contains:
- `final_state`: full session state dict with all `obs:` keys
- `traces`: list of per-event trace entries with `event` type, `timestamp`, `prompt_preview` (first 500 chars per content part), `system_instruction_preview` (first 500 chars), `response_preview`, `usage`, `token_accounting`, `context_window_snapshot`

**Richest source** for context window decomposition — has actual text previews.

### 2.2 SQLite Traces DB (`.adk/traces.db`)

Written by `SqliteTracingPlugin`. Contains:
- `traces` table: per-invocation summaries
- `spans` table: per-callback spans with `attributes` JSON containing `input_tokens`, `output_tokens`, model info

Good for iteration-level token counts. Missing prompt text content.

### 2.3 Session State DB (`.adk/session.db`)

Written by ADK `SqliteSessionService`, queryable via `TraceReader` (DuckDB-backed). Contains:
- `sessions.state` JSON: all accumulated state keys including `obs:per_iteration_token_breakdown`
- `events.event_data` JSON: per-event payloads with `state_delta`

### 2.4 Key State Keys (from `rlm_adk/state.py`)

| Key | Description |
|---|---|
| `CONTEXT_WINDOW_SNAPSHOT` | Per-turn dict: agent_type, content_count, prompt_chars, system_chars, history_msg_count |
| `OBS_PER_ITERATION_TOKEN_BREAKDOWN` | List of per-call dicts with reasoning/worker token details |
| `REASONING_INPUT_TOKENS` / `REASONING_OUTPUT_TOKENS` | From `usage_metadata` at reasoning callback |
| `temp:worker_input_tokens` / `temp:worker_output_tokens` | Aggregated from worker objects in dispatch closure |
| `REASONING_PROMPT_CHARS` / `REASONING_SYSTEM_CHARS` | Character counts for context sizing |
| `temp:worker_prompt_chars` / `temp:worker_content_count` | Worker context sizing |
| `temp:worker_dispatch_count` | Number of workers dispatched this iteration |

### 2.5 Gap: Full Text Capture

Current `prompt_preview` is truncated to 500 chars. For full text in the expand/collapse view, a new **`ContextWindowSnapshotPlugin`** writes complete JSONL snapshots at each `before_model_callback`. See Phase 1 below.

---

## 3. Color Scheme

Colorblind-safe, WCAG contrast-compliant palette:

| Category | Color | Hex |
|---|---|---|
| `STATIC_INSTRUCTION` | Slate Blue | `#475569` |
| `DYNAMIC_INSTRUCTION` | Indigo | `#6366F1` |
| `USER_PROMPT` | Emerald | `#10B981` |
| `LLM_RESPONSE` | Amber | `#F59E0B` |
| `REPL_CODE` | Cyan | `#06B6D4` |
| `REPL_OUTPUT` | Teal | `#14B8A6` |
| `CONTEXT_VAR` | Purple | `#8B5CF6` |
| `WORKER_PROMPT` | Rose | `#F43F5E` |
| `WORKER_RESPONSE` | Pink | `#EC4899` |

---

## 4. Component Architecture

### 4.1 Page Layout

```
+-----------------------------------------------------------------------+
| HEADER: "RLM Context Window Dashboard"  |  Session Selector Dropdown  |
+-----------------------------------------------------------------------+
| SESSION SUMMARY BAR                                                    |
| model | iterations | total_tokens | total_time | workers_dispatched    |
+-----------------------------------------------------------------------+
| NAVIGATION: [ << ] [ < ] Iteration 3 of 12 [ > ] [ >> ]              |
+-----------------------------------------------------------------------+
| LEFT PANEL (70%)                    | RIGHT PANEL (30%)                |
|                                      |                                 |
| REASONING AGENT CONTEXT WINDOW       | API TOKEN USAGE                |
| [=== stacked horizontal bar ====]    | local: 1,234,567 in / 45,678 o |
|                                      | gcloud: 1,234,600 in / 45,700 o|
| Segments: (clickable/hoverable)      | delta: +33 in / +22 out        |
| [static][dyn][user][llm][repl][...]  | [!] WARNING if mismatch        |
|                                      |                                 |
| WORKER CONTEXT WINDOWS (if any)      | PER-ITERATION BREAKDOWN        |
| Worker 1: [====== bar ==========]    | iter 0: 4,336 in / 274 out     |
| Worker 2: [====== bar ==========]    | iter 1: 5,750 in / 361 out     |
| Worker 3: [====== bar ==========]    | iter 2*: 24,512 in / 1,200 out |
|                                      |   (* = has workers)             |
|                                      |                                 |
| CHUNK DETAIL PANEL (expand below)    | CUMULATIVE TOKEN LINE CHART     |
| [collapsible: first/last 5 lines]    | (running totals over iters)     |
+-----------------------------------------------------------------------+
```

### 4.2 Component Hierarchy

```
DashboardApp
├── HeaderBar
│   ├── ui.label (title)
│   └── SessionSelector (ui.select dropdown)
├── SessionSummaryBar (ui.row of stat cards)
├── IterationNavigator
│   ├── ui.button ("<<", "<", ">", ">>")
│   ├── ui.label ("Iteration N of M [W]")
│   └── Keyboard shortcuts: Left/Right arrows, Home/End
├── MainLayout (ui.row, splitter=70/30)
│   ├── LeftPanel (ui.column)
│   │   ├── ReasoningWindowChart (ui.echart — stacked horizontal bar)
│   │   ├── WorkerWindowsPanel (conditional, ui.column)
│   │   │   └── WorkerWindowChart[i] (ui.echart per worker)
│   │   └── ChunkDetailPanel (ui.expansion, toggled on segment click)
│   │       └── ui.code (first/last 5 lines, syntax highlighted)
│   └── RightPanel (ui.column)
│       ├── APITokenUsageCard (reconciliation table + status indicator)
│       ├── PerIterationBreakdownList (ui.table)
│       └── CumulativeTokenChart (ui.echart — line chart)
└── ColorLegend (horizontal row of category color swatches)
```

### 4.3 State Management

Single reactive state object. NiceGUI `@ui.refreshable` for sections that re-render on navigation.

```python
@dataclass
class DashboardState:
    available_sessions: list[SessionSummary]
    selected_session_id: str | None
    session_summary: SessionSummary | None
    iterations: list[IterationData]
    current_iteration: int               # 0-based
    selected_chunk: ContextChunk | None  # hovered/expanded chunk
    api_usage: APITokenUsage | None
    reconciliation: TokenReconciliation | None
```

State flow:
1. User selects session → `load_session(session_id)` populates summary + iterations
2. `current_iteration` defaults to 0; arrows increment/decrement
3. Iteration change triggers `@ui.refreshable` redraw of bar charts + worker panels
4. Segment click/hover populates `selected_chunk` → detail panel updates
5. API reconciliation loads async in background

---

## 5. Interaction Design

### 5.1 Bar Chart Rendering

ECharts stacked horizontal bar (`ui.echart`). One series per chunk category, `stack: 'total'`.

- **X-axis**: token count (total session tokens = full span)
- **Y-axis**: one category row per agent (reasoning on top, workers below)
- Each segment's width = its proportional token count
- Tooltip on hover: chunk title, token count, percentage of iteration total

```python
# ECharts series shape (per category):
{
    "name": "Static Instruction",
    "type": "bar",
    "stack": "total",
    "data": [3200],
    "itemStyle": {"color": "#475569"},
    "emphasis": {"itemStyle": {"borderWidth": 2, "borderColor": "#fff"}}
}
```

### 5.2 Hover / Click Detail

On segment click (ECharts `on_point_click`):
1. Tooltip shows chunk title, token count, % of context
2. `ChunkDetailPanel` below chart shows:
   - Title: e.g. "LLM Response (from iter 2)"
   - Stats: "4,521 chars | ~1,130 tokens | 18% of context"
   - Preview: first 5 + last 5 lines in `ui.code` block
3. "Show full text" `ui.expansion` reveals complete text (scrollable, max-height 400px)

### 5.3 Worker Panel

- < 6 workers: individual bars shown
- ≥ 6 workers: collapsed summary bar ("75 workers: 1.2M total tokens") with expand toggle
- Worker bars only rendered for iterations where `has_workers == True`

### 5.4 API Token Usage Panel

Two-column table: **Local | GCloud | Delta** for Input Tokens, Output Tokens, Total Calls.
- Green checkmark if within 5% tolerance
- Red warning icon + yellow banner if mismatched
- Fallback: "Cloud usage data unavailable — showing local metrics only" if no GCloud creds

### 5.5 Cumulative Token Chart

ECharts line chart in right panel:
- X-axis: iteration index (0 to N)
- Y-axis: cumulative tokens
- Two lines: "Cumulative Input" (blue), "Cumulative Output" (orange)
- Vertical dotted lines at iterations with worker dispatches (token "jumps")

---

## 6. Token Estimation Strategy

For chunks where we have char counts but not per-chunk token counts, distribute the known total proportionally:

```python
def estimate_tokens_for_chunks(chunks: list[ContextChunk], known_total_tokens: int):
    total_chars = sum(c.char_count for c in chunks)
    if total_chars == 0:
        return
    for chunk in chunks:
        chunk.estimated_tokens = round(known_total_tokens * chunk.char_count / total_chars)
```

This calibrates to the actual Gemini tokenizer output for the specific request, more accurate than a flat chars/4 heuristic.

---

## 7. Data Pipeline

### 7.1 Loading Flow

```
DashboardDataLoader
├── load_session(session_id) → SessionSummary + list[IterationData]
│   ├── _load_from_debug_yaml(path) → RawSessionData
│   │     Read YAML, parse final_state, parse traces list
│   │     Extract obs:per_iteration_token_breakdown from final_state
│   │
│   ├── _load_from_snapshots_jsonl(path) → list[ContextSnapshot]
│   │     Read JSONL from ContextWindowSnapshotPlugin (full text)
│   │
│   ├── _load_from_traces_db(db_path) → RawSpanData
│   │     Query traces + spans tables, group by iteration
│   │
│   └── _build_context_windows(raw_data) → list[IterationData]
│         For each iteration:
│           1. system_instruction → ContextChunk(STATIC_INSTRUCTION)
│           2. dynamic instruction → ContextChunk(DYNAMIC_INSTRUCTION)
│           3. message_history decomposed into:
│              - User prompts → ContextChunk(USER_PROMPT)
│              - Assistant responses → ContextChunk(LLM_RESPONSE)
│              - Code blocks → ContextChunk(REPL_CODE)
│              - REPL output → ContextChunk(REPL_OUTPUT)
│           4. context vars → ContextChunk(CONTEXT_VAR)
│           5. estimate_tokens_for_chunks() from known total
│           6. Workers: parse worker_prompt_chars list → ContextChunk(WORKER_PROMPT)
```

### 7.2 Context Window Reconstruction

Ground truth for how context is assembled lives in:
- `callbacks/reasoning.py:69-155` (`reasoning_before_model`): builds `system_instruction` from static + dynamic, builds `contents` from `MESSAGE_HISTORY`
- `callbacks/worker.py:57-66` (`worker_before_model`): stores `_prompt_chars`, `_content_count` on agent object

The dashboard's decomposition must mirror this logic exactly.

---

## 8. GCloud API Integration

### 8.1 Cloud Monitoring API (preferred)

Query `serviceruntime.googleapis.com/api/request_count` and token count metrics for `generativelanguage.googleapis.com`, filtered by session time range and `GenerateContent` method.

### 8.2 BigQuery Billing Export (most accurate)

Query billing export table for `service.id = "generativelanguage.googleapis.com"`, sum `usage.amount` grouped by SKU (input vs output tokens).

### 8.3 Fallback

If no GCloud credentials, show local metrics only with "N/A" for reconciliation.

---

## 9. File Structure

```
rlm_adk/
  dashboard/
    __init__.py                     # exports launch_dashboard()
    app.py                          # NiceGUI entry point, page routing, ui.run()
    state.py                        # DashboardState dataclass, reactive state
    data_loader.py                  # reads YAML / JSONL / traces.db
    data_models.py                  # all dataclasses, enums, CATEGORY_COLORS
    components/
      __init__.py
      header.py                     # HeaderBar, SessionSelector
      summary_bar.py                # SessionSummaryBar (stat cards)
      navigator.py                  # IterationNavigator (arrows + label)
      context_bar.py                # ECharts stacked horizontal bar rendering
      chunk_detail.py               # expand/collapse text preview panel
      api_usage.py                  # APITokenUsageCard + reconciliation
      token_charts.py               # PerIterationBreakdownList + cumulative chart
    gcloud_usage.py                 # Cloud Monitoring / BigQuery integration
  plugins/
    context_snapshot.py             # NEW: ContextWindowSnapshotPlugin (JSONL)
```

### Dependencies (pyproject.toml)

```toml
[project.optional-dependencies]
dashboard = ["nicegui>=2.0"]
```

ECharts is bundled with NiceGUI (no extra dep). Chosen over Plotly for lower overhead and first-class stacked bar support.

### Entry Point

```bash
python -m rlm_adk.dashboard          # launches NiceGUI at http://localhost:8080/dashboard
```

---

## 10. New Plugin: ContextWindowSnapshotPlugin

Captures full (non-truncated) context window decomposition at each `before_model_callback`. Writes to `.adk/context_snapshots.jsonl`.

```jsonl
{"timestamp":1771600847.6,"iteration":0,"agent_type":"reasoning","agent_name":"reasoning_agent","model":"gemini-3-pro-preview","chunks":[{"category":"static_instruction","title":"RLM System Prompt","char_count":13284,"text":"You are tasked with...","iteration_origin":-1},{"category":"user_prompt","title":"User Prompt (iter 0)","char_count":426,"text":"You have not interacted...","iteration_origin":0}],"input_tokens":4336,"output_tokens":274,"total_chars":16335}
```

Wire into `agent.py` `_default_plugins()` as opt-in (enabled when `RLM_CONTEXT_SNAPSHOTS=1`).

---

## 11. Implementation Phases

### Phase 1 — Data Infrastructure
1. Create `rlm_adk/dashboard/data_models.py` (all dataclasses, enums, color map)
2. Create `rlm_adk/plugins/context_snapshot.py` (JSONL snapshot plugin)
3. Create `rlm_adk/dashboard/data_loader.py` (reads debug YAML + JSONL + traces.db)

### Phase 2 — Dashboard Core
4. Create `rlm_adk/dashboard/state.py` (DashboardState management)
5. Create `rlm_adk/dashboard/app.py` (NiceGUI page structure + `__main__.py`)
6. Create `rlm_adk/dashboard/components/header.py` + `navigator.py`

### Phase 3 — Visualization
7. Create `rlm_adk/dashboard/components/context_bar.py` (ECharts stacked bars)
8. Create `rlm_adk/dashboard/components/chunk_detail.py` (hover/expand text)
9. Create `rlm_adk/dashboard/components/token_charts.py` (cumulative line chart)
10. Create `rlm_adk/dashboard/components/summary_bar.py` (stat cards)

### Phase 4 — API Integration
11. Create `rlm_adk/dashboard/gcloud_usage.py` (Cloud Monitoring / BigQuery)
12. Create `rlm_adk/dashboard/components/api_usage.py` (reconciliation panel)

### Phase 5 — Wiring
13. Wire `ContextWindowSnapshotPlugin` into `agent.py` `_default_plugins()`
14. Add `dashboard` optional dependency group to `pyproject.toml`
15. Add `rlm_adk/dashboard/__main__.py` CLI entry point

---

## 12. Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Charting library | ECharts via `ui.echart` | Bundled with NiceGUI, stacked bars + click events are first-class, no extra dependency |
| Snapshot storage | JSONL file | Avoids coupling to traces.db schema, trivially appendable, small (<1MB) |
| Token estimation | Proportional from known total | Calibrates to actual Gemini tokenizer output, more accurate than chars/4 |
| Data primary source | Debug YAML (text previews) + JSONL (full text) | YAML already exists; JSONL adds full text as opt-in enhancement |
| GCloud API | Cloud Monitoring (primary) + BigQuery (fallback) | Monitoring is real-time; BigQuery is most accurate but requires billing export setup |
| Worker collapse | Auto-collapse at ≥6 workers | Prevents visual overload while preserving drill-down ability |

---

## 13. Critical Source Files

These files contain the ground-truth logic the dashboard must mirror:

| File | Lines | What It Does |
|---|---|---|
| `rlm_adk/callbacks/reasoning.py` | 69-155 | Exact context window construction (system_instruction + contents from MESSAGE_HISTORY) |
| `rlm_adk/callbacks/worker.py` | 57-66, 92-100 | Worker context sizing + token extraction |
| `rlm_adk/plugins/observability.py` | 109-190 | Per-iteration token breakdown accumulation (`OBS_PER_ITERATION_TOKEN_BREAKDOWN`) |
| `rlm_adk/plugins/debug_logging.py` | 128-215 | Trace recording: prompt_preview, system_instruction_preview, token_accounting |
| `rlm_adk/state.py` | all | All state key constants read by dashboard |
| `rlm_adk/eval/trace_reader.py` | all | DuckDB-backed analytics over SQLite (existing query infrastructure) |
