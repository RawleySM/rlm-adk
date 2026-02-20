# Langfuse + Google ADK Integration

> **Status**: Deployed (self-hosted, local Docker Compose)
> **Langfuse version**: 3.154.1
> **Tracing library**: `openinference-instrumentation-google-adk` 0.1.9
> **SDK**: `langfuse` 3.14.4

---

## A. Overview

Langfuse provides LLM observability: traces, token usage, latency, cost tracking, and evaluation for every model call, tool invocation, and agent transition in the RLM ADK pipeline.

The integration uses **OpenTelemetry (OTel)** under the hood. The `GoogleADKInstrumentor` from the `openinference` ecosystem monkey-patches Google ADK to emit OTel spans for every operation. The Langfuse SDK ships its own OTel exporter that forwards those spans to the Langfuse server.

### What gets traced automatically

| ADK Operation | Langfuse Representation |
|---|---|
| `LlmAgent` model call | **Generation** span with model, tokens, latency |
| Tool invocations | **Span** with tool name, args, result |
| Agent transitions (sub-agent dispatch) | Nested **trace** hierarchy |
| `RLMOrchestratorAgent` iterations | Parent spans grouping each loop cycle |
| `WorkerPool` parallel dispatch | Parallel child spans under the iteration |

No manual instrumentation code is required. The `GoogleADKInstrumentor` handles all of this by patching ADK internals at import time.

---

## B. Architecture

```
rlm_adk process
  |
  +-- LangfuseTracingPlugin (rlm_adk/plugins/langfuse_tracing.py)
  |     |
  |     +-- langfuse.get_client()          # authenticates with Langfuse server
  |     +-- GoogleADKInstrumentor()         # patches ADK to emit OTel spans
  |           |
  |           +-- OTel TracerProvider       # managed by langfuse SDK
  |                 |
  |                 +-- Langfuse OTel Exporter --> HTTP POST to Langfuse API
  |
  +-- ADK Agent execution (auto-instrumented)
        |
        +-- reasoning_agent (LlmAgent)     --> Generation span
        +-- worker_agent_N (LlmAgent)      --> Generation span
        +-- tool calls                     --> Span
```

### Langfuse Server Stack (Docker Compose)

```
Host machine (localhost)
  |
  +-- langfuse-web       :3100  (UI + API, Next.js)
  +-- langfuse-worker    :3030  (background processing)
  +-- postgres           :5432  (primary database, migrations, project data)
  +-- clickhouse    :8123/:9000  (analytics, trace storage, aggregations)
  +-- redis              :6379  (queue, cache, pub/sub)
  +-- minio         :9090/:9091  (S3-compatible blob storage for events/media)
```

All infrastructure services bind to `127.0.0.1` except `langfuse-web` (port 3100) and `minio` API (port 9090), which accept external connections.

---

## C. Self-Hosted Deployment

### C.1 Prerequisites

- Docker Engine 29+ and Docker Compose v5+
- 4 cores, 16 GB RAM, 100 GB storage (recommended for production)

### C.2 File Locations

| Path | Purpose |
|---|---|
| `~/dev/langfuse/` | Cloned Langfuse repository |
| `~/dev/langfuse/docker-compose.yml` | Docker Compose service definitions |
| `~/dev/langfuse/.env` | Secrets and configuration (DO NOT commit) |

### C.3 Services

| Service | Image | Host Port | Purpose |
|---|---|---|---|
| `langfuse-web` | `langfuse/langfuse:3` | **3100** | Web UI, API, migrations |
| `langfuse-worker` | `langfuse/langfuse-worker:3` | 3030 | Background jobs |
| `postgres` | `postgres:17` | 5432 | Primary relational DB |
| `clickhouse` | `clickhouse/clickhouse-server` | 8123, 9000 | Analytics / trace storage |
| `redis` | `redis:7` | 6379 | Queue / cache |
| `minio` | `cgr.dev/chainguard/minio` | 9090, 9091 | S3-compatible blob storage |

> Port 3100 is used instead of the default 3000 because `zeroclaw` occupies port 3000 on this machine.

### C.4 Operations

**Start the stack:**

```bash
sudo docker compose -f ~/dev/langfuse/docker-compose.yml up -d
```

**Stop the stack:**

```bash
sudo docker compose -f ~/dev/langfuse/docker-compose.yml down
```

**Check container health:**

```bash
sudo docker compose -f ~/dev/langfuse/docker-compose.yml ps
```

**View logs (web container):**

```bash
sudo docker compose -f ~/dev/langfuse/docker-compose.yml logs langfuse-web --tail 50
```

**Health check API:**

```bash
curl http://localhost:3100/api/public/health
# {"status":"OK","version":"3.154.1"}
```

**Full reset (destroy volumes and re-create):**

```bash
sudo docker compose -f ~/dev/langfuse/docker-compose.yml down -v
sudo docker compose -f ~/dev/langfuse/docker-compose.yml up -d
```

### C.5 Access

| | |
|---|---|
| **URL** | http://localhost:3100 |
| **Email** | rawley.stanhope@gmail.com |
| **Password** | langfuse123 |
| **Project** | rlm-adk |
| **Public Key** | `pk-lf-rlm-local` |
| **Secret Key** | `sk-lf-rlm-local` |

These are auto-provisioned via `LANGFUSE_INIT_*` env vars in the Langfuse `.env` file.

---

## D. RLM ADK Integration

### D.1 Python Dependencies

Added to `pyproject.toml`:

```toml
"langfuse>=3.14.0",
"openinference-instrumentation-google-adk>=0.1.9",
```

Install:

```bash
.venv/bin/python -m pip install langfuse openinference-instrumentation-google-adk
```

### D.2 Environment Variables

Added to `rlm-adk/.env`:

```
LANGFUSE_PUBLIC_KEY=pk-lf-rlm-local
LANGFUSE_SECRET_KEY=sk-lf-rlm-local
LANGFUSE_BASE_URL=http://localhost:3100
```

The `langfuse` SDK reads these automatically via `get_client()`. No manual client construction is needed.

### D.3 Plugin: `LangfuseTracingPlugin`

**File:** `rlm_adk/plugins/langfuse_tracing.py`

The plugin follows the same `BasePlugin` pattern as `ObservabilityPlugin` and `DebugLoggingPlugin`. It is a thin initialization wrapper -- all actual tracing is handled by the OTel instrumentor.

**Initialization sequence:**

1. Plugin constructor calls `_init_langfuse_instrumentation()`
2. Checks for required env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`)
3. Calls `langfuse.get_client()` and runs `auth_check()` to verify connectivity
4. Calls `GoogleADKInstrumentor().instrument()` to patch ADK
5. Sets module-level `_INSTRUMENTED = True` to prevent double-init

**Safety properties:**

- If env vars are missing, the plugin logs a warning and stays disabled. No error raised.
- If `langfuse` or `openinference` packages are not installed, the plugin catches `ImportError` and stays disabled.
- If Langfuse server is unreachable, `auth_check()` returns `False` and the plugin stays disabled.
- The `_INSTRUMENTED` module guard prevents double-instrumentation if multiple plugin instances are created.

### D.4 Plugin Wiring

In `rlm_adk/agent.py`, `_default_plugins()` includes `LangfuseTracingPlugin` by default:

```python
def _default_plugins(*, debug: bool = True, langfuse: bool = True) -> list[BasePlugin]:
    plugins: list[BasePlugin] = [ObservabilityPlugin()]
    # ... debug plugin ...
    _langfuse_env = os.getenv("RLM_ADK_LANGFUSE", "").lower() in ("1", "true", "yes")
    if langfuse or _langfuse_env:
        plugins.append(LangfuseTracingPlugin())
    return plugins
```

**Enable/disable:**

| Method | How |
|---|---|
| Default | Enabled (plugin included, but silently disabled if env vars missing) |
| Env var override | Set `RLM_ADK_LANGFUSE=1` to force-enable even when `langfuse=False` is passed |
| Programmatic | `create_rlm_app(..., plugins=[...])` to exclude it entirely |
| No env vars | Plugin self-disables with a log warning |

### D.5 Plugin Hierarchy

Updated component map including Langfuse:

```
agent.py (create_rlm_app / create_rlm_runner)
  |
  +-- orchestrator.py (RLMOrchestratorAgent: BaseAgent)
  |     +-- reasoning_agent (LlmAgent)
  |     +-- dispatch.py (WorkerPool + ParallelAgent)
  |
  +-- plugins/
        +-- observability.py      (ObservabilityPlugin: token totals, per-iteration breakdowns)
        +-- debug_logging.py      (DebugLoggingPlugin: YAML trace dumps, stdout prints)
        +-- langfuse_tracing.py   (LangfuseTracingPlugin: OTel auto-instrumentation)
        +-- policy.py             (PolicyPlugin)
        +-- cache.py              (CachePlugin)
```

**Relationship between ObservabilityPlugin and LangfuseTracingPlugin:**

These are complementary, not redundant:

- `ObservabilityPlugin` writes metrics to ADK session state (token counts, call counts, timings, per-iteration breakdowns). These are available programmatically within the ADK session.
- `LangfuseTracingPlugin` exports traces externally to Langfuse for visualization, search, cost analysis, evaluation, and historical comparison. It captures spans automatically via OTel without touching session state.

Both can run simultaneously. Neither depends on the other.

---

## E. Verifying the Integration

### E.1 Quick smoke test

```python
import os
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-rlm-local"
os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-rlm-local"
os.environ["LANGFUSE_BASE_URL"] = "http://localhost:3100"

from rlm_adk.plugins.langfuse_tracing import LangfuseTracingPlugin

plugin = LangfuseTracingPlugin()
print(f"Plugin enabled: {plugin.enabled}")  # Should print True
```

### E.2 Auth check only

```python
from langfuse import get_client

client = get_client()
print(client.auth_check())  # True if Langfuse server is reachable
```

### E.3 Full ADK run with tracing

```python
from rlm_adk import create_rlm_runner
from google.genai import types

runner = create_rlm_runner(model="gemini-2.5-flash")
session = await runner.session_service.create_session(
    app_name="rlm_adk", user_id="test",
)
content = types.Content(
    role="user",
    parts=[types.Part(text="What is 2+2?")],
)
async for event in runner.run_async(
    user_id="test", session_id=session.id, new_message=content,
):
    if event.is_final_response():
        print(event.content.parts[0].text)
```

After running, navigate to http://localhost:3100 to see the trace in the Langfuse UI. The trace will show the full agent execution hierarchy with model calls, token usage, and latency.

---

## F. Troubleshooting

### Langfuse containers won't start

**Port conflict:** Check if port 3100, 5432, 6379, 8123, 9000, 9090 are already in use:

```bash
sudo ss -tlnp | grep -E '3100|5432|6379|8123|9000|9090'
```

**Database migration failure:** The `langfuse-web` container runs migrations on startup. If postgres isn't ready, it crash-loops. Fix with:

```bash
sudo docker compose -f ~/dev/langfuse/docker-compose.yml restart langfuse-web
```

### Plugin reports "disabled"

Check these in order:

1. **Env vars set?** `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` must all be present.
2. **Langfuse server running?** `curl http://localhost:3100/api/public/health`
3. **Packages installed?** `.venv/bin/python -c "import langfuse; from openinference.instrumentation.google_adk import GoogleADKInstrumentor"`
4. **Auth check?** Run the auth check snippet from section E.2.

### Traces not appearing in UI

- Traces are sent asynchronously. Wait 5-10 seconds after the run completes.
- Check the `langfuse-worker` logs for ingestion errors.
- Verify the project keys match between `rlm-adk/.env` and the Langfuse project settings.

### Resetting Langfuse data

To wipe all trace data and start fresh:

```bash
sudo docker compose -f ~/dev/langfuse/docker-compose.yml down -v
sudo docker compose -f ~/dev/langfuse/docker-compose.yml up -d
```

This destroys all Docker volumes (Postgres, ClickHouse, MinIO data). The init user and project will be re-provisioned automatically.
