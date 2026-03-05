# Objective
Implement an export-ready local observability strategy by creating a `LocalTelemetryBridge` plugin. This plugin will capture OpenTelemetry spans (Traces) and session metrics (Telemetry) and persist them to local JSONL files (`.adk/traces.jsonl` and `.adk/telemetry.jsonl`), enabling $0-cost prototyping with a seamless transition to Google Cloud Trace and BigQuery Agent Analytics.

# Key Files & Context
- **`rlm_adk/plugins/local_telemetry.py`** (New File): The new plugin that bridges ADK observability to local JSONL files.
- **`rlm_adk/agent.py`**: Will be updated to register the new plugin.
- **`pyproject.toml`** / **`uv.lock`**: May need `opentelemetry-sdk` added if not already present.

# Implementation Steps

## 1. Create the `LocalTelemetryBridgePlugin`
Create `rlm_adk/plugins/local_telemetry.py` with the following responsibilities:
- **Trace Exporting**: Configure an OpenTelemetry `TracerProvider` with a custom file-based `SpanExporter` that appends JSON-serialized spans to `.adk/traces.jsonl`.
- **Telemetry Scraping**: Implement an ADK plugin callback (e.g., `after_agent_callback` for the root agent or `on_event` if capturing the final state) that reads all `obs:` prefixed keys from the session state.
- **BigQuery-Ready JSON**: Format the scraped metrics into a structured JSON payload that matches the `BigQueryAgentAnalyticsPlugin` schema:
  ```json
  {
    "timestamp": "...",
    "event_type": "SESSION_SUMMARY",
    "trace_id": "...",
    "agent": "...",
    "content": {
      "metrics": { ...obs keys... }
    }
  }
  ```
- **File Writing**: Append this JSON payload to `.adk/telemetry.jsonl`.

## 2. Register the Plugin
Update the main application builder (likely in `rlm_adk/agent.py`) to instantiate `LocalTelemetryBridgePlugin` and add it to the `plugins` list passed to the `App` or `Runner`. Ensure the `.adk` directory exists before initialization.

## 3. Dependency Check
Verify that the `opentelemetry-sdk` is installed in the current environment (via `uv run pip install opentelemetry-sdk` or by adding it to `pyproject.toml`), as the ADK relies on OpenTelemetry for tracing.

# Verification & Testing
1. Run a sample interaction using the REPL or a script.
2. Verify that `.adk/traces.jsonl` is created and contains valid OpenTelemetry span JSON objects.
3. Verify that `.adk/telemetry.jsonl` is created and contains the `SESSION_SUMMARY` event with all expected `obs:` metrics.
4. Ensure that the standard `SqliteSessionService` continues to work normally.

# Migration Strategy (For Future Production)
When ready for production on Google Cloud:
1. Replace the file-based OpenTelemetry exporter with `CloudTraceExporter` from `google-cloud-opentelemetry-traces`.
2. Replace the local telemetry file writing logic with the official `BigQueryAgentAnalyticsPlugin` from `google.adk.plugins.bigquery_agent_analytics_plugin`.
3. No changes to agent logic or state keys will be required.