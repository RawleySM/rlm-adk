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

## Managed Launchers

Two launcher scripts now support the dashboard outside the bare
`python -m rlm_adk.dashboard` path:

- [`scripts/launch_dashboard_chrome.sh`](/home/rawley-stanhope/dev/rlm-adk/scripts/launch_dashboard_chrome.sh)
  manages the dashboard server lifecycle, reuses matching instances, and
  restarts stale `rlm_adk.dashboard` processes when the dashboard code
  fingerprint changes.
- [`scripts/launch_dashboard_playwright_chrome.py`](/home/rawley-stanhope/dev/rlm-adk/scripts/launch_dashboard_playwright_chrome.py)
  launches the dashboard in a Playwright-controlled Chrome dev-mode browser
  so agents can inspect and interact with the live UI.

The managed shell launcher writes instance metadata to
`rlm_adk/.adk/dashboard_instance.json` and uses
`rlm_adk/plugins/dashboard_auto_launch.py` to compute the dashboard
fingerprint and choose whether to reuse, restart, or skip a process.

### Managed Shell Launcher

Basic invocation:

```bash
scripts/launch_dashboard_chrome.sh
```

What it does:

- Starts the dashboard if no reusable instance exists
- Reuses the current managed dashboard if the fingerprint matches
- Replaces a stale `rlm_adk.dashboard` listener without killing unrelated
  services on the port
- Opens Chrome in a new window when a GUI/browser is available
- When `DASHBOARD_DEV=1` or `RLM_DASHBOARD_DEV=1`, opens the dashboard through
  `scripts/launch_dashboard_playwright_chrome.py` instead of a regular Chrome window

### Playwright Chrome Dev Mode

The Playwright launcher assumes the dashboard is already reachable, then opens
it in a persistent Chrome context using `channel="chrome"`.

Basic invocation:

```bash
.venv/bin/python scripts/launch_dashboard_playwright_chrome.py
```

Print the resolved configuration without launching:

```bash
.venv/bin/python scripts/launch_dashboard_playwright_chrome.py --print-config
```

What it does:

- Verifies the dashboard is reachable, by default at
  `http://127.0.0.1:8080/live`
- Copies the selected Chrome profile into
  `rlm_adk/.adk/chrome-dev-profile`
- Launches a persistent Chrome context with Playwright
- Enables remote debugging, by default on port `9222`
- Prints a JSON summary that includes the dev profile path and CDP websocket
  endpoint so another agent or tool can attach

### Playwright Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RLM_DASHBOARD_URL` | `http://127.0.0.1:8080/live` | Dashboard URL to open |
| `RLM_PLAYWRIGHT_CHROME_SOURCE_ROOT` | platform default Chrome user-data root | Source Chrome profile root to copy |
| `RLM_PLAYWRIGHT_CHROME_PROFILE_DIR` | `Default` | Profile directory inside the source root |
| `RLM_PLAYWRIGHT_CHROME_DEV_ROOT` | `rlm_adk/.adk/chrome-dev-profile` | Destination dev-mode profile root |
| `RLM_PLAYWRIGHT_CHROME_REMOTE_DEBUGGING_PORT` | `9222` | Remote debugging port exposed by Chrome |
| `RLM_PLAYWRIGHT_CHROME_HEADLESS` | unset / false | Set to `1` for headless mode |
| `RLM_PLAYWRIGHT_CHROME_REFRESH_PROFILE` | unset / false | Set to `1` to recopy profile data before launch |

Default source-profile locations are:

- Linux: `~/.config/google-chrome`
- macOS: `~/Library/Application Support/Google/Chrome`
- Windows: `%LOCALAPPDATA%/Google/Chrome/User Data`

### Profile and Auth Behavior

The Playwright launcher is designed to preserve your primary Chrome session:

- It does not point Playwright directly at your live Chrome user-data dir
- It copies `Local State` and the chosen profile into a dev root first
- It skips lock/cache artifacts such as `Singleton*`, `LOCK`, and cache dirs

This means the dev browser can usually inherit your Google auth on the same
machine without locking or mutating your main Chrome profile.

### Remote Debugging and Agent Interaction

The Playwright launcher enables Chrome remote debugging so agents can inspect
or interact with the live dashboard through the launched dev-mode browser.
The script prints the resolved `cdp_ws_endpoint` when available, which makes it
possible for a follow-on agent or tool to attach to the browser session.

### Caveats

- If your Chrome auth changed after the dev profile was first copied, rerun
  with `RLM_PLAYWRIGHT_CHROME_REFRESH_PROFILE=1` to refresh the copied data.
- Some Chrome secrets are backed by the OS keyring. On the same machine and
  same user account this usually works, but a copied profile may still require
  a refresh or a fresh login.
- The Playwright launcher does not start the dashboard for you; use the managed
  shell launcher or another dashboard start path first.

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
