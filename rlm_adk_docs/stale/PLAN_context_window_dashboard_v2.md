# Plan: Context Window Token Dashboard v2 (NiceGUI)

## Overview

A NiceGUI dashboard that visualizes context window token composition for the `reasoning_agent` and `worker` agents at every iteration turn of an RLM session. Users navigate between iterations with forward/backward arrows and keyboard shortcuts, seeing which context chunks (system prompts, dynamic instructions, user prompts, LLM responses, REPL code/output, context vars, worker prompts/responses) consume what fraction of the token budget -- color-coded by category with hover/collapsible full-text previews.

### Single-Source Architecture

**v2 uses a single data source**: `ContextWindowSnapshotPlugin` writing to `.adk/context_snapshots.jsonl`.

The v1 plan relied on three data sources (debug YAML, traces.db, session.db) plus a new JSONL plugin. This was over-engineered:

| v1 Source | Problem |
|-----------|---------|
| `rlm_adk_debug.yaml` | Monolithic dump written once at `after_run_callback`; `prompt_preview` truncated to 500 chars; not structured per-iteration |
| `.adk/traces.db` | Token counts but zero text content; schema-dependent SQL |
| `.adk/session.db` | Accumulated final snapshot, not per-turn; requires diffing state deltas; schema-dependent SQL |

The `ContextWindowSnapshotPlugin` fires at `before_model_callback` (one event per LLM call), capturing:
- Exact per-turn, per-agent context decomposition (mirrors `reasoning_before_model` and `worker_before_model` logic)
- Full text for every chunk (not truncated)
- Token counts from `usage_metadata` (via paired `after_model_callback`)
- Worker calls as separate entries with their own chunk decomposition

One JSONL file, one loader, one code path. GCloud reconciliation stays as a separate optional panel.

---

## 1. Data Model

### 1.1 SessionSummary

Top-level metadata computed by the loader when grouping JSONL entries by session.

```python
@dataclass
class SessionSummary:
    session_id: str
    app_name: str
    model: str                           # e.g. "gemini-3-pro-preview"
    total_iterations: int                # max(iteration) + 1 across reasoning entries
    total_input_tokens: int              # sum of all input_tokens
    total_output_tokens: int             # sum of all output_tokens
    total_calls: int                     # count of JSONL entries
    reasoning_calls: int                 # entries where agent_type == "reasoning"
    worker_calls: int                    # entries where agent_type == "worker"
    start_time: float                    # min(timestamp)
    end_time: float                      # max(timestamp)
```

### 1.2 IterationData

Per-iteration container grouping the reasoning call and any worker calls.

```python
@dataclass
class IterationData:
    iteration_index: int                 # 0-based
    reasoning_window: ContextWindow
    worker_windows: list[ContextWindow]  # empty if no workers dispatched
    reasoning_input_tokens: int
    reasoning_output_tokens: int
    worker_input_tokens: int             # sum across all workers this iteration
    worker_output_tokens: int
    has_workers: bool
    timestamp_start: float
    timestamp_end: float
```

### 1.3 ContextWindow and ContextChunk

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
    chunk_id: str                        # e.g. "iter0_reasoning_static_instruction"
    category: ChunkCategory
    title: str                           # descriptive label for UI
    char_count: int
    estimated_tokens: int                # proportional from known total
    iteration_origin: int                # which iteration generated this content (-1 for static)
    text_preview_head: str               # first 5 lines
    text_preview_tail: str               # last 5 lines
    full_text: str                       # for expand view
```

### 1.4 ChunkCategory

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
    source: str                          # "local" | "gcloud_monitoring"
    total_input_tokens: int
    total_output_tokens: int             # 0 for gcloud (not tracked in quota metrics)
    total_calls: int
    per_model: dict[str, ModelTokenUsage]

@dataclass
class ModelTokenUsage:
    model: str
    input_tokens: int
    output_tokens: int
    calls: int

@dataclass
class TokenReconciliation:
    local_input_tokens: int
    local_output_tokens: int
    api_input_tokens: int
    api_output_tokens: int               # 0 when unavailable from gcloud
    input_delta: int
    output_delta: int
    input_match: bool                    # abs(delta) < 5% threshold
    output_match: bool
    error_message: str | None
```

---

## 2. ContextWindowSnapshotPlugin Specification

### 2.1 Plugin Class

Extends `BasePlugin`. Opt-in via `RLM_CONTEXT_SNAPSHOTS=1` environment variable.

```python
class ContextWindowSnapshotPlugin(BasePlugin):
    """Captures full context window decomposition at each LLM call.

    Writes one JSONL line per before_model_callback (context decomposition)
    and patches it with token counts from the paired after_model_callback.

    Opt-in: enabled when RLM_CONTEXT_SNAPSHOTS=1.
    """

    def __init__(
        self,
        *,
        name: str = "context_snapshot",
        output_path: str = ".adk/context_snapshots.jsonl",
    ):
        super().__init__(name=name)
        self._output_path = Path(output_path)
        self._pending_entry: dict[str, Any] | None = None  # awaiting after_model token counts
        self._file_handle: IO | None = None
```

### 2.2 before_model_callback: Context Decomposition

This is the core capture point. It mirrors the logic in `reasoning_before_model` (lines 69-155 of `rlm_adk/callbacks/reasoning.py`) and `worker_before_model` (lines 20-68 of `rlm_adk/callbacks/worker.py`).

**Agent type detection**: The plugin must determine whether the current call is for the reasoning agent or a worker. It uses:
1. Check `callback_context._invocation_context.agent.name` -- if it equals `"reasoning_agent"`, it is a reasoning call. Otherwise, it is a worker.
2. Fallback: check if state key `REASONING_PROMPT_CHARS` was just set (reasoning) vs `WORKER_PROMPT_CHARS` (worker).

**For reasoning agents**, decompose the `LlmRequest` into chunks:

1. **system_instruction** (from `llm_request.config.system_instruction`):
   - Extract the full text. The reasoning callback builds this from `static_instruction` + `dynamic_instruction`.
   - Split into `STATIC_INSTRUCTION` and `DYNAMIC_INSTRUCTION` chunks by detecting the `"\n\nRepository URL:"` boundary (the start of `RLM_DYNAMIC_INSTRUCTION`).
   - If no boundary found, emit as single `STATIC_INSTRUCTION` chunk.

2. **contents** (from `llm_request.contents`):
   - These are the `message_history` entries injected by `reasoning_before_model`.
   - For each `Content` object, classify by role and content patterns:
     - `role="user"` with iteration-0 safeguard text or `USER_PROMPT` pattern -> `USER_PROMPT`
     - `role="user"` with `"Code executed:\n```python"` pattern -> `REPL_CODE` + `REPL_OUTPUT` (split at `"\n\nREPL output:\n"` boundary, per `format_iteration` in `parsing.py` line 98-102)
     - `role="model"` -> `LLM_RESPONSE`
     - `role="user"` with `"REPL variables:"` -> `CONTEXT_VAR`

3. Assign `iteration_origin` by tracking position in the contents list (messages accumulate iteration-by-iteration; the plugin can compute origin from the message pattern: each iteration adds 1 assistant + N user messages for code blocks).

**For worker agents**, decompose:

1. No system_instruction (workers use `instruction=` which becomes a user Content, but `include_contents='none'` means only the injected prompt arrives).
2. **contents**: The single prompt injected via `worker._pending_prompt` -> `WORKER_PROMPT` chunk.
3. If the prompt is a message list (multi-turn), decompose each message by role.

**Build the JSONL entry** (but do NOT write yet -- wait for `after_model_callback` to pair token counts):

```python
self._pending_entry = {
    "timestamp": time.time(),
    "session_id": session_id,
    "iteration": state.get(ITERATION_COUNT, 0),
    "agent_type": agent_type,
    "agent_name": agent_name,
    "model": llm_request.model or "unknown",
    "chunks": [chunk.to_dict() for chunk in chunks],
    "total_chars": sum(c.char_count for c in chunks),
    "input_tokens": None,   # filled by after_model_callback
    "output_tokens": None,  # filled by after_model_callback
}
```

### 2.3 after_model_callback: Token Count Pairing

Reads `llm_response.usage_metadata` to extract `prompt_token_count` and `candidates_token_count`. Patches the `_pending_entry` and flushes it to the JSONL file.

```python
async def after_model_callback(self, *, callback_context, llm_response):
    if self._pending_entry is None:
        return None

    usage = llm_response.usage_metadata
    if usage:
        self._pending_entry["input_tokens"] = getattr(usage, "prompt_token_count", 0) or 0
        self._pending_entry["output_tokens"] = getattr(usage, "candidates_token_count", 0) or 0
    else:
        self._pending_entry["input_tokens"] = 0
        self._pending_entry["output_tokens"] = 0

    self._flush_entry()
    self._pending_entry = None
    return None
```

### 2.4 Chunk Text Extraction

Helper that extracts full text from `Content` parts:

```python
def _extract_content_text(content: types.Content) -> str:
    if not content.parts:
        return ""
    return "".join(
        p.text for p in content.parts
        if isinstance(p, types.Part) and p.text
    )
```

### 2.5 Error Safety

All operations wrapped in try/except. Plugin failures must never crash the agent. If `before_model_callback` captures an entry but `after_model_callback` is not called (e.g., model error), the `on_model_error_callback` flushes the pending entry with `input_tokens=0, output_tokens=0, error=True`.

### 2.6 File Lifecycle

- File opened on first write (lazy), not at plugin init.
- Each JSONL line is flushed immediately (`file.flush()`) for crash safety.
- File closed in `after_run_callback`.
- Parent directory created if missing (`Path.mkdir(parents=True, exist_ok=True)`).

---

## 3. JSONL Schema

Each line is a JSON object. Two example entries follow.

### 3.1 Reasoning Agent Entry (iteration 2)

```json
{
  "timestamp": 1771600849.3,
  "session_id": "sess_abc123",
  "iteration": 2,
  "agent_type": "reasoning",
  "agent_name": "reasoning_agent",
  "model": "gemini-3-pro-preview",
  "chunks": [
    {
      "chunk_id": "iter2_reasoning_static_instruction",
      "category": "static_instruction",
      "title": "RLM System Prompt",
      "char_count": 13284,
      "text": "You are tasked with answering a query...",
      "iteration_origin": -1
    },
    {
      "chunk_id": "iter2_reasoning_dynamic_instruction",
      "category": "dynamic_instruction",
      "title": "Dynamic Context (repo_url, root_prompt)",
      "char_count": 187,
      "text": "Repository URL: https://github.com/...\nOriginal query: Analyze...",
      "iteration_origin": -1
    },
    {
      "chunk_id": "iter2_reasoning_user_prompt_0",
      "category": "user_prompt",
      "title": "User Prompt (iter 0)",
      "char_count": 426,
      "text": "You have not interacted with the REPL...",
      "iteration_origin": 0
    },
    {
      "chunk_id": "iter2_reasoning_llm_response_0",
      "category": "llm_response",
      "title": "LLM Response (iter 0)",
      "char_count": 3812,
      "text": "I'll start by loading the repository...",
      "iteration_origin": 0
    },
    {
      "chunk_id": "iter2_reasoning_repl_code_0_0",
      "category": "repl_code",
      "title": "REPL Code (iter 0, block 0)",
      "char_count": 245,
      "text": "from repomix import RepoProcessor...",
      "iteration_origin": 0
    },
    {
      "chunk_id": "iter2_reasoning_repl_output_0_0",
      "category": "repl_output",
      "title": "REPL Output (iter 0, block 0)",
      "char_count": 89,
      "text": "Files: 47, Tokens: 312500",
      "iteration_origin": 0
    },
    {
      "chunk_id": "iter2_reasoning_user_prompt_2",
      "category": "user_prompt",
      "title": "User Prompt (iter 2)",
      "char_count": 210,
      "text": "The history before is your previous...",
      "iteration_origin": 2
    }
  ],
  "total_chars": 24512,
  "input_tokens": 6128,
  "output_tokens": 1200
}
```

### 3.2 Worker Agent Entry (iteration 2, worker_7)

```json
{
  "timestamp": 1771600850.1,
  "session_id": "sess_abc123",
  "iteration": 2,
  "agent_type": "worker",
  "agent_name": "worker_7",
  "model": "gemini-3-pro-preview",
  "chunks": [
    {
      "chunk_id": "iter2_worker_7_prompt",
      "category": "worker_prompt",
      "title": "Worker Prompt",
      "char_count": 52300,
      "text": "Identify the key modules, public APIs...",
      "iteration_origin": 2
    }
  ],
  "total_chars": 52300,
  "input_tokens": 13075,
  "output_tokens": 842
}
```

### 3.3 Error Entry (worker failed)

```json
{
  "timestamp": 1771600851.5,
  "session_id": "sess_abc123",
  "iteration": 2,
  "agent_type": "worker",
  "agent_name": "worker_3",
  "model": "gemini-3-pro-preview",
  "chunks": [
    {
      "chunk_id": "iter2_worker_3_prompt",
      "category": "worker_prompt",
      "title": "Worker Prompt",
      "char_count": 48000,
      "text": "Summarize the following section...",
      "iteration_origin": 2
    }
  ],
  "total_chars": 48000,
  "input_tokens": 0,
  "output_tokens": 0,
  "error": true,
  "error_message": "ServerError: 503 Service Unavailable"
}
```

---

## 4. Data Loader

### 4.1 DashboardDataLoader

Single class that reads only the JSONL file. No SQL, no YAML, no DuckDB.

```python
class DashboardDataLoader:
    """Loads and structures context snapshot data from JSONL.

    Single source of truth: reads .adk/context_snapshots.jsonl
    and groups entries into SessionSummary + list[IterationData].
    """

    def __init__(self, jsonl_path: str = ".adk/context_snapshots.jsonl"):
        self._path = Path(jsonl_path)

    def list_sessions(self) -> list[str]:
        """Return distinct session_ids found in the JSONL file."""
        ...

    def load_session(self, session_id: str) -> tuple[SessionSummary, list[IterationData]]:
        """Load all entries for a session, build structured data."""
        entries = self._read_entries(session_id)
        summary = self._build_summary(entries)
        iterations = self._build_iterations(entries)
        return summary, iterations

    def _read_entries(self, session_id: str) -> list[dict]:
        """Read and filter JSONL lines by session_id."""
        ...

    def _build_summary(self, entries: list[dict]) -> SessionSummary:
        """Compute session-level aggregates from entries."""
        ...

    def _build_iterations(self, entries: list[dict]) -> list[IterationData]:
        """Group entries by iteration, build ContextWindow objects."""
        ...

    def _build_context_window(self, entry: dict) -> ContextWindow:
        """Convert a single JSONL entry to a ContextWindow."""
        chunks = []
        for chunk_data in entry["chunks"]:
            chunk = ContextChunk(
                chunk_id=chunk_data["chunk_id"],
                category=ChunkCategory(chunk_data["category"]),
                title=chunk_data["title"],
                char_count=chunk_data["char_count"],
                estimated_tokens=0,  # computed below
                iteration_origin=chunk_data["iteration_origin"],
                text_preview_head="\n".join(chunk_data["text"].split("\n")[:5]),
                text_preview_tail="\n".join(chunk_data["text"].split("\n")[-5:]),
                full_text=chunk_data["text"],
            )
            chunks.append(chunk)

        total_tokens = entry.get("input_tokens", 0)
        estimate_tokens_for_chunks(chunks, total_tokens)

        return ContextWindow(
            agent_type=entry["agent_type"],
            agent_name=entry["agent_name"],
            iteration=entry["iteration"],
            chunks=chunks,
            total_chars=entry["total_chars"],
            total_tokens=total_tokens,
            output_tokens=entry.get("output_tokens", 0),
            model=entry["model"],
        )
```

### 4.2 Token Estimation

Distribute the known total proportionally by character count:

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

## 5. Color Scheme

Colorblind-safe, WCAG contrast-compliant palette:

| Category | Color | Hex | Text Color |
|----------|-------|-----|------------|
| `STATIC_INSTRUCTION` | Slate Blue | `#475569` | `#ffffff` |
| `DYNAMIC_INSTRUCTION` | Indigo | `#6366F1` | `#ffffff` |
| `USER_PROMPT` | Emerald | `#10B981` | `#ffffff` |
| `LLM_RESPONSE` | Amber | `#F59E0B` | `#000000` |
| `REPL_CODE` | Cyan | `#06B6D4` | `#000000` |
| `REPL_OUTPUT` | Teal | `#14B8A6` | `#000000` |
| `CONTEXT_VAR` | Purple | `#8B5CF6` | `#ffffff` |
| `WORKER_PROMPT` | Rose | `#F43F5E` | `#ffffff` |
| `WORKER_RESPONSE` | Pink | `#EC4899` | `#ffffff` |

```python
CATEGORY_COLORS: dict[ChunkCategory, str] = {
    ChunkCategory.STATIC_INSTRUCTION:  "#475569",
    ChunkCategory.DYNAMIC_INSTRUCTION: "#6366F1",
    ChunkCategory.USER_PROMPT:         "#10B981",
    ChunkCategory.LLM_RESPONSE:        "#F59E0B",
    ChunkCategory.REPL_CODE:           "#06B6D4",
    ChunkCategory.REPL_OUTPUT:         "#14B8A6",
    ChunkCategory.CONTEXT_VAR:         "#8B5CF6",
    ChunkCategory.WORKER_PROMPT:       "#F43F5E",
    ChunkCategory.WORKER_RESPONSE:     "#EC4899",
}
```

---

## 6. Component Architecture

### 6.1 Controller Layer (UI Architecture Pattern)

Following the NiceGUI three-layer architecture (Data Layer, Business Logic Layer, UI Layer):

```python
# --- Data Layer ---
class DashboardDataLoader:
    """Pure data loading, no UI dependencies. Returns dataclasses."""
    def load_session(self, session_id: str) -> tuple[SessionSummary, list[IterationData]]: ...
    def list_sessions(self) -> list[str]: ...

class GCloudUsageClient:
    """Optional GCloud API data fetching. Returns APITokenUsage."""
    async def fetch_usage(self, start_time: float, end_time: float) -> APITokenUsage | None: ...

# --- Business Logic Layer ---
class DashboardController:
    """Coordinates data loading and state transitions. Fully testable."""
    def __init__(self, loader: DashboardDataLoader): ...

    async def select_session(self, session_id: str) -> None: ...
    def navigate(self, delta: int) -> None: ...
    def navigate_to(self, index: int) -> None: ...
    def select_chunk(self, chunk: ContextChunk) -> None: ...

# --- State ---
@dataclass
class DashboardState:
    available_sessions: list[str]
    selected_session_id: str | None = None
    session_summary: SessionSummary | None = None
    iterations: list[IterationData] = field(default_factory=list)
    current_iteration: int = 0               # 0-based
    selected_chunk: ContextChunk | None = None
    api_usage: APITokenUsage | None = None
    reconciliation: TokenReconciliation | None = None
    is_loading: bool = False
```

State flow:
1. User selects session -> `controller.select_session()` populates summary + iterations
2. `current_iteration` defaults to 0; arrows call `controller.navigate(+/-1)`
3. Iteration change triggers `@ui.refreshable` redraw of bar charts + worker panels
4. Segment click calls `controller.select_chunk()` -> detail panel refreshes
5. API reconciliation loads async in background

### 6.2 Component Hierarchy

```
DashboardApp (app.py)
+-- DashboardController (controller.py, business logic, no UI)
+-- HeaderBar (header.py)
|   +-- ui.label (title)
|   +-- SessionSelector (ui.select dropdown)
+-- SessionSummaryBar (summary_bar.py)
|   +-- StatCard[model, iterations, tokens_in, tokens_out, time, workers]
+-- IterationNavigator (navigator.py)
|   +-- ui.button ("<<", "<", ">", ">>")
|   +-- ui.label ("Iteration N of M [W workers]")
|   +-- Keyboard bindings: Left/Right arrows, Home/End
+-- MainLayout (explicit flex div, 70/30 split)
|   +-- LeftPanel (flex: 7; min-width: 0)
|   |   +-- ReasoningWindowChart (@ui.refreshable, ui.echart -- stacked horizontal bar)
|   |   +-- WorkerWindowsPanel (@ui.refreshable, conditional)
|   |   |   +-- WorkerWindowChart[i] (ui.echart per worker, collapse at >=6)
|   |   +-- ChunkDetailPanel (@ui.refreshable, ui.expansion, toggled on segment click)
|   |       +-- ui.code (first/last 5 lines, syntax highlighted)
|   |       +-- ui.expansion ("Show full text") -> ui.code (scrollable, max-height 400px)
|   +-- RightPanel (flex: 3; min-width: 0)
|       +-- APITokenUsageCard (reconciliation table + status indicator)
|       +-- PerIterationBreakdownList (ui.table, clickable rows)
|       +-- CumulativeTokenChart (ui.echart -- line chart)
+-- ColorLegend (horizontal row of category color swatches)
```

### 6.3 NiceGUI Styling Patterns

All UI components MUST follow these rules:

1. **Gap spacing**: ALWAYS use inline `style("gap: Xrem")`, NEVER Tailwind `gap-*` classes.
2. **Side-by-side charts**: Use `ui.element("div")` with explicit flexbox and `min-width: 0` on children.
3. **Height**: Use explicit `height:`, never `height: 100%` inside `max-height` containers.
4. **Scroll areas**: Only inside explicitly-heightened parents.

Example layout for the main 70/30 split:

```python
# Main 70/30 layout -- explicit flexbox with min-width: 0 on children
with ui.element("div").style(
    "display: flex; flex-direction: row; width: 100%; gap: 1.5rem"
):
    # Left panel (charts)
    with ui.element("div").style(
        "flex: 7; min-width: 0; display: flex; flex-direction: column"
    ).style("gap: 1rem"):
        reasoning_chart_section()
        worker_charts_section()
        chunk_detail_section()

    # Right panel (stats + line chart)
    with ui.element("div").style(
        "flex: 3; min-width: 0; display: flex; flex-direction: column"
    ).style("gap: 1rem"):
        api_usage_card()
        iteration_breakdown_table()
        cumulative_token_chart()
```

---

## 7. Page Layout (ASCII Mockup)

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
|                                      | gcloud: 1,234,600 in / N/A out |
| Segments: (clickable/hoverable)      | delta: +33 in                  |
| [static][dyn][user][llm][repl][...]  | [checkmark] MATCH              |
|                                      |                                 |
| WORKER CONTEXT WINDOWS (if any)      | PER-ITERATION BREAKDOWN        |
| Worker 7: [====== bar ==========]    | iter 0: 4,336 in / 274 out     |
| Worker 8: [====== bar ==========]    | iter 1: 5,750 in / 361 out     |
| Worker 9: [====== bar ==========]    | iter 2*: 24,512 in / 1,200 out |
|                                      |   (* = has workers)             |
|                                      |                                 |
| CHUNK DETAIL PANEL (expand below)    | CUMULATIVE TOKEN LINE CHART     |
| Category: LLM Response (from iter 1) | (running totals over iters)     |
| 4,521 chars | ~1,130 tokens | 18%    |                                 |
| [first 5 lines of text...]           |    _____------                  |
| [last 5 lines of text...]            |   /                             |
| [ Show full text v ]                 |  /  cumulative input             |
|                                      | /   cumulative output            |
+-----------------------------------------------------------------------+
| COLOR LEGEND: [static] [dynamic] [user] [llm] [code] [output] [...]  |
+-----------------------------------------------------------------------+
```

---

## 8. Interaction Design

### 8.1 Stacked Horizontal Bar Chart (ECharts)

Each reasoning/worker context window renders as a stacked horizontal bar via `ui.echart`. One series per chunk category, `stack: 'total'`.

- **X-axis**: token count (bar width proportional to estimated tokens)
- **Y-axis**: single row per agent ("Reasoning" or "Worker N")
- Tooltip on hover: chunk title, token count, percentage of iteration total, char count
- Click triggers `selected_chunk` update in controller

```python
def build_context_bar_options(window: ContextWindow) -> dict:
    """Build ECharts options for a stacked horizontal bar."""
    series = []
    for category in ChunkCategory:
        category_chunks = [c for c in window.chunks if c.category == category]
        if not category_chunks:
            continue
        total_tokens = sum(c.estimated_tokens for c in category_chunks)
        series.append({
            "name": category.value,
            "type": "bar",
            "stack": "total",
            "data": [total_tokens],
            "itemStyle": {"color": CATEGORY_COLORS[category]},
            "emphasis": {"itemStyle": {"borderWidth": 2, "borderColor": "#fff"}},
        })

    return {
        "tooltip": {
            "trigger": "item",
            "formatter": "{b}: {c} tokens ({d}%)",
        },
        "xAxis": {"type": "value", "show": False},
        "yAxis": {
            "type": "category",
            "data": [window.agent_name],
            "axisLabel": {"show": True},
        },
        "series": series,
        "grid": {"left": 120, "right": 20, "top": 10, "bottom": 10},
    }
```

### 8.2 Segment Click Detail

On ECharts `on_point_click` event:

1. Identify which chunk(s) belong to the clicked category for the current window
2. Update `controller.select_chunk(chunk)`
3. `ChunkDetailPanel` refreshes via `@ui.refreshable`:
   - Title: e.g. "LLM Response (from iter 2)"
   - Stats: "4,521 chars | ~1,130 tokens | 18% of context"
   - Preview: first 5 + last 5 lines in `ui.code` block
   - `ui.expansion("Show full text")` reveals complete text in scrollable `ui.code`

```python
@ui.refreshable
def chunk_detail_section():
    chunk = controller.state.selected_chunk
    if chunk is None:
        ui.label("Click a segment to view details").classes("text-body2 text-grey-7")
        return

    with ui.card().classes("w-full"):
        ui.label(chunk.title).classes("text-h6")
        with ui.row().style("gap: 0.75rem"):
            ui.badge(f"{chunk.char_count:,} chars").props("color=grey-7")
            ui.badge(f"~{chunk.estimated_tokens:,} tokens").props("color=primary")

        ui.code(chunk.text_preview_head).classes("w-full")
        if chunk.text_preview_tail != chunk.text_preview_head:
            ui.label("...").classes("text-center text-grey-6")
            ui.code(chunk.text_preview_tail).classes("w-full")

        with ui.expansion("Show full text").classes("w-full"):
            with ui.scroll_area().style("height: 400px"):
                ui.code(chunk.full_text).classes("w-full")
```

### 8.3 Worker Panel Collapse Rules

- 0 workers: panel hidden
- 1-5 workers: individual bars shown
- 6+ workers: collapsed summary bar ("75 workers: 1.2M total tokens") with `ui.expansion` toggle
- Worker bars only rendered for iterations where `has_workers == True`

### 8.4 Keyboard Navigation

```python
def setup_keyboard_nav():
    async def handle_key(e):
        if e.key == "ArrowLeft":
            controller.navigate(-1)
            refresh_all()
        elif e.key == "ArrowRight":
            controller.navigate(1)
            refresh_all()
        elif e.key == "Home":
            controller.navigate_to(0)
            refresh_all()
        elif e.key == "End":
            controller.navigate_to(len(controller.state.iterations) - 1)
            refresh_all()
    ui.keyboard(on_key=handle_key)
```

### 8.5 Cumulative Token Line Chart

ECharts line chart in right panel:
- X-axis: iteration index (0 to N)
- Y-axis: cumulative tokens
- Two lines: "Cumulative Input" (blue `#3B82F6`), "Cumulative Output" (orange `#F97316`)
- Vertical dotted line at current iteration
- Marker dots at iterations with worker dispatches (token "jumps")

```python
def build_cumulative_chart_options(
    iterations: list[IterationData], current_iter: int
) -> dict:
    cum_input = []
    cum_output = []
    running_in = 0
    running_out = 0
    for it in iterations:
        running_in += it.reasoning_input_tokens + it.worker_input_tokens
        running_out += it.reasoning_output_tokens + it.worker_output_tokens
        cum_input.append(running_in)
        cum_output.append(running_out)

    worker_iters = [i for i, it in enumerate(iterations) if it.has_workers]

    return {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": list(range(len(iterations)))},
        "yAxis": {"type": "value", "name": "Tokens"},
        "series": [
            {
                "name": "Cumulative Input",
                "type": "line",
                "data": cum_input,
                "lineStyle": {"color": "#3B82F6"},
                "itemStyle": {"color": "#3B82F6"},
                "markLine": {
                    "data": [{"xAxis": i} for i in worker_iters],
                    "lineStyle": {"type": "dashed", "color": "#F43F5E"},
                    "label": {"show": False},
                },
            },
            {
                "name": "Cumulative Output",
                "type": "line",
                "data": cum_output,
                "lineStyle": {"color": "#F97316"},
                "itemStyle": {"color": "#F97316"},
            },
        ],
        "markLine": {
            "data": [{"xAxis": current_iter}],
            "lineStyle": {"type": "dashed", "color": "#9CA3AF"},
        },
    }
```

### 8.6 Per-Iteration Breakdown Table

Clickable `ui.table` in right panel. Clicking a row navigates to that iteration.

- Columns: Iteration | Input Tokens | Output Tokens | Workers
- Current iteration row highlighted
- Rows with workers marked with asterisk

---

## 9. GCloud API Integration (Optional)

### 9.1 Cloud Monitoring API (primary)

Query `generativelanguage.googleapis.com/quota/generate_content_paid_tier_input_token_count/usage`, filtered by session time range. Uses `gcloud auth print-access-token` for OAuth bearer token.

**Available metrics** (from `ai_docs/gcloud_token_validation.md`):
- Input tokens per model per minute (paid tier)
- Request count per model per minute
- **Output tokens are NOT tracked** in Cloud Monitoring quota metrics

### 9.2 BigQuery Billing Export (fallback)

Query billing export table for `service.id = "generativelanguage.googleapis.com"`, sum `usage.amount` grouped by SKU. Requires billing export to be configured.

### 9.3 Graceful Degradation

```python
class GCloudUsageClient:
    """Fetches token usage from Google Cloud Monitoring API."""

    async def fetch_usage(
        self, start_time: float, end_time: float, project_id: str | None = None
    ) -> APITokenUsage | None:
        """Returns None if no credentials or API unavailable."""
        try:
            token = await self._get_access_token()
            if token is None:
                return None
            # ... query Cloud Monitoring REST API ...
        except Exception:
            return None
```

**Panel states**:
1. **Credentials available, data available**: Full reconciliation table with match/mismatch indicators
2. **Credentials available, no data**: "No Cloud Monitoring data for this time range"
3. **No credentials**: "Cloud usage data unavailable -- showing local metrics only"

### 9.4 Reconciliation Logic

```python
def reconcile(local: SessionSummary, gcloud: APITokenUsage | None) -> TokenReconciliation:
    if gcloud is None:
        return TokenReconciliation(
            local_input_tokens=local.total_input_tokens,
            local_output_tokens=local.total_output_tokens,
            api_input_tokens=0, api_output_tokens=0,
            input_delta=0, output_delta=0,
            input_match=True, output_match=True,
            error_message="Cloud usage data unavailable -- showing local metrics only",
        )
    input_delta = gcloud.total_input_tokens - local.total_input_tokens
    return TokenReconciliation(
        local_input_tokens=local.total_input_tokens,
        local_output_tokens=local.total_output_tokens,
        api_input_tokens=gcloud.total_input_tokens,
        api_output_tokens=0,  # Cloud Monitoring does not track output tokens
        input_delta=input_delta, output_delta=0,
        input_match=abs(input_delta) < local.total_input_tokens * 0.05,
        output_match=True,  # Cannot verify output tokens
        error_message=None,
    )
```

---

## 10. File Structure

```
rlm_adk/
  dashboard/
    __init__.py                     # exports launch_dashboard()
    __main__.py                     # python -m rlm_adk.dashboard
    app.py                          # NiceGUI entry point, page routing, ui.run()
    controller.py                   # DashboardController, DashboardState
    data_loader.py                  # DashboardDataLoader (reads JSONL only)
    data_models.py                  # all dataclasses, enums, CATEGORY_COLORS
    components/
      __init__.py
      header.py                     # HeaderBar, SessionSelector
      summary_bar.py                # SessionSummaryBar (stat cards)
      navigator.py                  # IterationNavigator (arrows + label + keyboard)
      context_bar.py                # ECharts stacked horizontal bar rendering
      chunk_detail.py               # expand/collapse text preview panel
      worker_panel.py               # WorkerWindowsPanel with collapse logic
      api_usage.py                  # APITokenUsageCard + reconciliation display
      token_charts.py               # PerIterationBreakdownList + cumulative line chart
      color_legend.py               # Horizontal color legend bar
    gcloud_usage.py                 # Cloud Monitoring / BigQuery integration
  plugins/
    context_snapshot.py             # NEW: ContextWindowSnapshotPlugin (JSONL writer)
```

### Dependencies (pyproject.toml addition)

```toml
[project.optional-dependencies]
dashboard = ["nicegui>=2.0"]
```

ECharts is bundled with NiceGUI (no extra dep). Chosen over Plotly for lower overhead and first-class stacked bar support.

### Entry Point

```bash
# Install with dashboard extras
pip install -e ".[dashboard]"

# Launch dashboard
python -m rlm_adk.dashboard          # NiceGUI at http://localhost:8080/dashboard

# Or via module function
python -c "from rlm_adk.dashboard import launch_dashboard; launch_dashboard()"
```

---

## 11. Implementation Phases

### Phase 1: Data Infrastructure (foundation)

1. Create `rlm_adk/dashboard/data_models.py` -- all dataclasses, enums, `CATEGORY_COLORS`, `estimate_tokens_for_chunks()`
2. Create `rlm_adk/plugins/context_snapshot.py` -- `ContextWindowSnapshotPlugin` with `before_model_callback` (context decomposition), `after_model_callback` (token pairing), `on_model_error_callback` (error flush), JSONL writer
3. Wire `ContextWindowSnapshotPlugin` into `rlm_adk/agent.py` `_default_plugins()` as opt-in (`RLM_CONTEXT_SNAPSHOTS=1`)
4. Create `rlm_adk/dashboard/data_loader.py` -- `DashboardDataLoader` that reads only JSONL

### Phase 2: Dashboard Core (app shell)

5. Create `rlm_adk/dashboard/controller.py` -- `DashboardController`, `DashboardState`
6. Create `rlm_adk/dashboard/app.py` -- NiceGUI page structure, main layout, keyboard setup
7. Create `rlm_adk/dashboard/__init__.py` and `__main__.py`
8. Create `rlm_adk/dashboard/components/header.py` + `navigator.py`

### Phase 3: Visualization (charts + detail)

9. Create `rlm_adk/dashboard/components/context_bar.py` -- ECharts stacked horizontal bar with click handler
10. Create `rlm_adk/dashboard/components/chunk_detail.py` -- hover/expand text preview panel
11. Create `rlm_adk/dashboard/components/worker_panel.py` -- worker bars with collapse logic
12. Create `rlm_adk/dashboard/components/token_charts.py` -- cumulative line chart + per-iteration table
13. Create `rlm_adk/dashboard/components/summary_bar.py` -- session stat cards
14. Create `rlm_adk/dashboard/components/color_legend.py` -- horizontal legend

### Phase 4: API Integration (optional panel)

15. Create `rlm_adk/dashboard/gcloud_usage.py` -- Cloud Monitoring REST API client
16. Create `rlm_adk/dashboard/components/api_usage.py` -- reconciliation panel

### Phase 5: Packaging

17. Add `dashboard` optional dependency group to `pyproject.toml`
18. Test with a real RLM session (enable `RLM_CONTEXT_SNAPSHOTS=1`, run a session, launch dashboard)

---

## 12. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data source | Single JSONL file | Eliminates 3 fragile data sources (YAML, traces.db, session.db); one loader, one code path, no schema coupling |
| Charting library | ECharts via `ui.echart` | Bundled with NiceGUI, stacked bars + click events are first-class, no extra dependency |
| Snapshot storage | Append-only JSONL | Trivially appendable, crash-safe with per-line flush, small (<5MB per session), no DB schema |
| Token estimation | Proportional from known total | Calibrates to actual Gemini tokenizer output via `usage_metadata`, more accurate than chars/4 |
| Plugin trigger point | `before_model` + `after_model` pair | `before_model` has the full LlmRequest (context text); `after_model` has `usage_metadata` (token counts) |
| Agent type detection | Agent name check (`reasoning_agent` vs `worker_*`) | Reliable -- agent names are stable, set at construction in `agent.py` and `dispatch.py` |
| GCloud token source | Cloud Monitoring (primary) | Real-time, exact match with local counts, no billing export setup needed |
| GCloud output tokens | Not reconciled | Cloud Monitoring quota metrics do not track output tokens |
| Worker collapse | Auto-collapse at >=6 workers | Prevents visual overload while preserving drill-down ability |
| UI architecture | Controller + thin UI handlers | NiceGUI best practice: business logic in testable controller, UI layer delegates |
| Gap spacing | Inline `style("gap: Xrem")` | NiceGUI bug #2171 causes broken spacing with Tailwind `gap-*` on Ubuntu |
| Chart layout | Explicit flexbox with `min-width: 0` | Prevents charts from forcing parent expansion; keeps 70/30 split stable |
| Opt-in activation | `RLM_CONTEXT_SNAPSHOTS=1` env var | Zero overhead in production; consistent with existing `RLM_ADK_DEBUG` pattern |
| system_instruction split | Detect `"\nRepository URL:"` boundary | Splits static (code examples) from dynamic (template-resolved metadata) cleanly |

---

## 13. Critical Source Files

These files contain the ground-truth logic the plugin must mirror:

| File | Key Lines | What It Does |
|------|-----------|--------------|
| `rlm_adk/callbacks/reasoning.py` | 69-155 | Exact context window construction: `system_instruction` from static + dynamic, `contents` from `MESSAGE_HISTORY` |
| `rlm_adk/callbacks/worker.py` | 20-68 | Worker prompt injection: `_pending_prompt` -> `LlmRequest.contents`, stores `_prompt_chars` and `_content_count` |
| `rlm_adk/utils/prompts.py` | 16-309 | `RLM_STATIC_INSTRUCTION`, `RLM_DYNAMIC_INSTRUCTION` template, `build_user_prompt()` |
| `rlm_adk/utils/parsing.py` | 71-103 | `format_iteration()` -- REPL code/output message format (pattern to detect in chunk decomposition) |
| `rlm_adk/orchestrator.py` | 92-435 | Iteration loop, worker dispatch timing, event queue drain points |
| `rlm_adk/dispatch.py` | 201-387 | Worker batch dispatch, `ParallelAgent` usage, token aggregation from worker objects |
| `rlm_adk/agent.py` | 241-274 | `_default_plugins()` -- where to wire in the new plugin with env-var opt-in |
| `rlm_adk/state.py` | all | All state key constants that the plugin reads |
| `rlm_adk/plugins/debug_logging.py` | 128-215 | Reference pattern for `before_model_callback` / `after_model_callback` in a plugin |
| `rlm_adk/plugins/observability.py` | 109-190 | Reference pattern for per-iteration token breakdown accumulation |
