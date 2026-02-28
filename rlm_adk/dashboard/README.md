# RLM Context Window Dashboard

NiceGUI-based dashboard for visualizing token usage across reasoning and worker agent iterations.

## Quick Start

```bash
# Install optional dependency
uv pip install rlms[dashboard]

# Launch
python -m rlm_adk.dashboard
```

Open **http://localhost:8080/dashboard** in your browser.

### Programmatic Launch

```python
from rlm_adk.dashboard import launch_dashboard

launch_dashboard(host="0.0.0.0", port=8080, reload=False)
```

| Parameter | Default   | Description                        |
|-----------|-----------|------------------------------------|
| `host`    | `0.0.0.0` | Bind address                      |
| `port`    | `8080`    | Listen port                        |
| `reload`  | `False`   | NiceGUI hot-reload (dev mode)      |

## Data Sources

The dashboard reads two JSONL files from the project root:

| File                              | Required | Contents                                  |
|-----------------------------------|----------|-------------------------------------------|
| `.adk/context_snapshots.jsonl`    | Yes      | Context window chunks per iteration       |
| `.adk/model_outputs.jsonl`        | No       | Model response text and error metadata    |

Each line contains `session_id`, `iteration`, `agent_type`, `agent_name`, token counts, and either chunk data or output text.

### Generating Data with Live Gemini

Set `RLM_CONTEXT_SNAPSHOTS=1` (already in `.env`) and run normally:

```bash
adk run rlm_adk
```

### Generating Data with Fake Fixtures (Deterministic, No API Key)

The fake provider contract runner executes fixture JSON files against a local
HTTP stub that returns canned responses. No Gemini API key required.

```bash
# List available fixtures
python -m tests_rlm_adk.provider_fake --list

# Run a fixture by name (stem) with dashboard snapshots
python -m tests_rlm_adk.provider_fake --snapshot polymorphic_dag_routing

# Run by glob pattern
python -m tests_rlm_adk.provider_fake --snapshot "multi*"

# Run all fixtures
python -m tests_rlm_adk.provider_fake --snapshot

# Then launch the dashboard
python -m rlm_adk.dashboard
```

| Flag              | Effect                                                  |
|-------------------|---------------------------------------------------------|
| `--list`, `-l`    | Print available fixture names and exit                  |
| `--snapshot`, `-s`| Enable `ContextWindowSnapshotPlugin` (writes `.adk/` JSONL) |

Fixtures live in `tests_rlm_adk/fixtures/provider_fake/` and accept names,
globs, or full paths as positional arguments.

## Architecture

```
__main__.py          CLI entry point
__init__.py          Public API (launch_dashboard)
app.py               Page route + layout assembly
controller.py        State management + navigation logic
data_loader.py       JSONL parsing + token estimation
data_models.py       Dataclasses (ContextChunk, IterationData, SessionSummary, ...)
gcloud_usage.py      Optional GCloud Monitoring reconciliation
components/
  header.py          Title + session selector dropdown
  summary_bar.py     Stat cards (model, iterations, tokens, duration, calls)
  navigator.py       Iteration navigation buttons
  context_bar.py     ECharts stacked horizontal bar (context window)
  chunk_detail.py    Text preview with full-text expansion
  token_charts.py    Cumulative line chart + per-iteration table
  color_legend.py    Category color swatches
  api_usage.py       Horizontal worker badges bar
  output_panel.py    Reasoning output + per-worker summaries
  worker_panel.py    Worker context windows (auto-collapse at 6+)
```

### MVC Pattern

- **Model**: `data_models.py` dataclasses + `data_loader.py` (read-only JSONL)
- **View**: NiceGUI `@ui.refreshable` components in `components/`
- **Controller**: `DashboardController` manages `DashboardState`, coordinates navigation and selection

### Data Flow

```
.adk/context_snapshots.jsonl
        │
        ▼
DashboardDataLoader.load_session(session_id)
        │
        ▼
(SessionSummary, list[IterationData])
        │
        ▼
DashboardController.state  ──►  DashboardUI.refresh_all()
                                        │
                                        ▼
                                 NiceGUI components render
```

## Page Layout

```
┌─────────────────────────────────────────────────────┐
│  Header: Title + Session Selector                   │
├────────────┬──────────────────┬──────────────────────┤
│ Summary    │ Cumulative Token │ Per-Iteration Table  │
│ Bar        │ Chart            │ (clickable rows)     │
├────────────┴──────────────────┴──────────────────────┤
│  Navigator: << < [Iteration N of M] > >> [N workers] │
├──────────────────────────────────────────────────────┤
│  Reasoning Context Bar (stacked horizontal bar)      │
├──────────────────────────────────────────────────────┤
│  Workers Bar (clickable badges)                      │
├─────────────────┬──────────────────┬─────────────────┤
│  Chunk Detail   │  Output Panel    │  Worker Detail  │
│  (text preview) │  (reasoning +    │  (selected      │
│                 │   worker outputs)│   worker chunk) │
└─────────────────┴──────────────────┴─────────────────┘
```

## Keyboard Shortcuts

| Key   | Action                    |
|-------|---------------------------|
| `←`   | Previous iteration        |
| `→`   | Next iteration            |
| Home  | Jump to first iteration   |
| End   | Jump to last iteration    |

## Chunk Categories

| Category             | Color   | Description                  |
|----------------------|---------|------------------------------|
| Static Instruction   | Gray    | System prompts, fixed text   |
| Dynamic Instruction  | Indigo  | Runtime-injected instructions|
| User Prompt          | Green   | User input                   |
| LLM Response         | Amber   | Model output history         |
| REPL Code            | Cyan    | Executed Python code         |
| REPL Output          | Teal    | Code execution results       |
| Context Variable     | Purple  | State variables              |
| Worker Prompt        | Rose    | Sub-agent prompts            |
| Worker Response      | Pink    | Sub-agent responses          |

## GCloud Reconciliation

When `gcloud` CLI is available and authenticated, the dashboard can compare local token counts against GCloud Monitoring data. This is optional and degrades gracefully when unavailable.

## Dependencies

- `nicegui>=2.0` (optional extra: `uv pip install rlms[dashboard]`)
- `google.genai` (project dependency)
- Optional: `gcloud` CLI for token reconciliation
