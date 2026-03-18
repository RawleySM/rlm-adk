<!-- validated: 2026-03-17 -->

# ADK v1.27.0 Observability & OpenTelemetry Enhancements -- RLM-ADK Impact Proposal

This document evaluates the observability and OpenTelemetry changes in Google ADK v1.27.0 against the current RLM-ADK observability stack. It maps each upstream change to the affected codebase files, classifies what is automatic vs requires code, and proposes concrete enhancements.

**Current ADK pin:** `google-adk>=1.2.0` (in `pyproject.toml`)
**Target:** `google-adk>=1.27.0`

---

## 1. v1.27.0 Observability Changes Explained

### 1.1 `gen_ai.agent.version` Span Attribute (Telemetry)

ADK v1.27.0 adds a new `gen_ai.agent.version` span attribute to every OTel span emitted by the framework. This attribute carries the agent's version identifier, enabling version-correlated trace analysis. When `GoogleADKInstrumentor().instrument()` is active, all spans (model calls, tool invocations, agent transitions) will automatically include this attribute.

**Relevance to RLM-ADK:** RLM-ADK currently has no version tag on its agents. The `RLMOrchestratorAgent`, `reasoning_agent`, and child orchestrators are all created without a `version` field. Upstream ADK may populate this from agent metadata if available, or leave it empty.

### 1.2 `gen_ai.tool.definitions` (Experimental Semantic Convention)

A new experimental OTel semantic convention attribute `gen_ai.tool.definitions` is added to spans. This captures the JSON schema definitions of tools available to the agent at the time of a model call. It provides a structured record of tool capabilities visible to the model.

**Relevance to RLM-ADK:** The reasoning agent has two tools wired at runtime: `REPLTool` (name: `execute_code`) and `SetModelResponseTool` (schema-driven). Both have `FunctionDeclaration` definitions. Child orchestrators at depth > 0 also wire these tools. The tool definitions would be automatically captured if the instrumentor supports them.

### 1.3 `gen_ai.client.inference.operation.details` Event (Experimental)

A new experimental OTel event type that carries per-inference-call metadata: model parameters, token counts, latency breakdown, and operation-specific details. This is richer than the existing span attributes -- it captures the full request/response envelope as a structured event within the span.

**Relevance to RLM-ADK:** This would provide a framework-native alternative to the custom per-iteration token breakdown that `ObservabilityPlugin.after_model_callback` (line 218-244 of `observability.py`) manually builds and stores in `OBS_PER_ITERATION_TOKEN_BREAKDOWN`.

### 1.4 Missing Token Usage Span Attributes Fix

ADK v1.27.0 fixes a bug where `prompt_token_count` and `candidates_token_count` were not always written to OTel span attributes during model usage. This fix ensures token counts appear in spans even for streaming responses and edge cases.

**Relevance to RLM-ADK:** Both `LangfuseTracingPlugin` and `GoogleCloudTracingPlugin` rely on `GoogleADKInstrumentor` for auto-instrumentation. Currently, missing token attributes in Langfuse/Cloud Trace mean gaps in cost analysis. This fix directly improves data quality in both tracing backends with zero code changes.

### 1.5 Tool Execution Error Code Capture in OTel Spans

ADK v1.27.0 captures tool execution error codes (exception types, HTTP status codes) as attributes on the tool invocation OTel span. Previously, tool errors were logged but not structured into span attributes.

**Relevance to RLM-ADK:** `REPLTool.run_async()` catches exceptions and returns structured error dicts (lines 215-273 of `repl_tool.py`). Child dispatch errors are classified by `_classify_error()` in `dispatch.py` (line 58-97) into categories: RATE_LIMIT, AUTH, SERVER, CLIENT, NETWORK, TIMEOUT, PARSE_ERROR, UNKNOWN. These error codes would now flow into OTel spans automatically, making them queryable in Langfuse and Cloud Trace without custom instrumentation.

### 1.6 BigQuery Plugin Enhancements (Fork Safety, Auto Views, Trace Continuity)

ADK v1.27.0 upgrades the `BigQueryAgentAnalyticsPlugin` with:
- **Schema upgrades:** Automatic table schema migration when new columns are added
- **Fork safety:** Safe to use with multiprocessing (relevant for batch evaluation)
- **Auto views:** Automatic creation of BigQuery views for common query patterns
- **Trace continuity:** Better correlation between BQ rows and OTel traces
- **Enhanced error reporting:** Structured error metadata in BQ rows

**Relevance to RLM-ADK:** `GoogleCloudAnalyticsPlugin` (`google_cloud_analytics.py`) wraps `BigQueryAgentAnalyticsPlugin` and delegates `after_run_callback`. It currently passes through the invocation context as-is. The upstream schema upgrades would apply automatically, but the auto-views and trace continuity features may require passing additional configuration.

---

## 2. Mapping to Current Observability Architecture

### 2.1 Plugin-by-Plugin Impact

| Plugin | File | v1.27.0 Impact | Auto/Code |
|--------|------|----------------|-----------|
| **ObservabilityPlugin** | `rlm_adk/plugins/observability.py` | Token fix improves `usage_metadata` reliability in `after_model_callback` (line 182). Tool error codes complement manual `OBS_TOOL_INVOCATION_SUMMARY`. | Mostly auto; optional code to consume new error codes |
| **SqliteTracingPlugin** | `rlm_adk/plugins/sqlite_tracing.py` | No direct OTel dependency. Could add `gen_ai.agent.version` to traces table. Tool error telemetry rows already capture `error_type` + `error_message` (lines 900-903, 947-949). | Code changes to add version column |
| **LangfuseTracingPlugin** | `rlm_adk/plugins/langfuse_tracing.py` | All five changes benefit automatically via `GoogleADKInstrumentor`. Token fix, error codes, tool definitions, agent version, inference events all flow to Langfuse with zero changes. | **Fully automatic** |
| **GoogleCloudTracingPlugin** | `rlm_adk/plugins/google_cloud_tracing.py` | Same as Langfuse -- `GoogleADKInstrumentor` propagates new attributes to Cloud Trace spans automatically. | **Fully automatic** |
| **GoogleCloudAnalyticsPlugin** | `rlm_adk/plugins/google_cloud_analytics.py` | BQ schema upgrades, fork safety, auto views, trace continuity all apply when the wrapped `BigQueryAgentAnalyticsPlugin` is instantiated. May want to pass new config options. | Mostly auto; optional config code |
| **REPLTracingPlugin** | `rlm_adk/plugins/repl_tracing.py` | No direct impact (file-based JSON traces, not OTel). | None |

### 2.2 Can `gen_ai.tool.definitions` Capture REPLTool + SetModelResponseTool Schemas?

**Yes, with conditions.**

`REPLTool._get_declaration()` (line 91-105 of `repl_tool.py`) returns a `FunctionDeclaration` with a well-defined `Schema`:

```python
FunctionDeclaration(
    name="execute_code",
    description="Execute Python code in a persistent REPL environment...",
    parameters=Schema(
        type=Type.OBJECT,
        properties={"code": Schema(type=Type.STRING, description="Python code...")},
        required=["code"],
    ),
)
```

`SetModelResponseTool` (from `google.adk.tools.set_model_response_tool`) is initialized with `output_schema` (a Pydantic `BaseModel` subclass). ADK generates its `FunctionDeclaration` from the Pydantic schema.

If v1.27.0's `gen_ai.tool.definitions` attribute is populated from `LlmRequest.tools_dict` at the time of each model call, then both tool schemas would be captured automatically. The key question is **when** the tools list is serialized:

- Tools are wired at runtime via `object.__setattr__(self.reasoning_agent, 'tools', [repl_tool, set_model_response_tool])` in `orchestrator.py` line 309.
- ADK's `BaseLLMFlow` reads `agent.tools` during each step to build `tools_dict` in `LlmRequest`.
- At that point, both tools are present, so `gen_ai.tool.definitions` should capture both.

**Verification needed:** Confirm that `GoogleADKInstrumentor` reads `tools_dict` from the `LlmRequest` (not from agent construction time). If it does, the runtime-wired tools will be captured correctly.

### 2.3 Can Tool Error Codes Flow into OTel Spans for Child Dispatch Errors?

**Partially -- with an important gap.**

For **reasoning-agent-level tool errors** (REPLTool exceptions, SetModelResponseTool validation failures), the v1.27.0 error code capture works directly. These tools execute within the reasoning agent's `BaseLLMFlow`, so their exceptions are caught by the framework's tool execution span and recorded as OTel attributes.

For **child dispatch errors**, the situation is different:
- Child orchestrators run inside `_run_child()` in `dispatch.py` (line 383-653).
- Errors are caught in the `except Exception as e` block (line 501-516) and classified by `_classify_error()`.
- The error category (RATE_LIMIT, SERVER, etc.) and message are stored in local accumulators (`_acc_child_error_counts`) and flushed to session state via `flush_fn`.
- These errors occur **inside** the child's `run_async()` invocation, which is **within** the parent's `REPLTool.run_async()` execution.

The v1.27.0 tool error capture would record the **outer** REPLTool span as having an error if the REPL code raises an exception. However, child dispatch errors are **caught and converted to `LLMResult` objects** (not re-raised), so they would appear as successful tool executions from the framework's perspective.

**Gap:** To get child dispatch error codes into OTel spans, we would need to manually add span attributes from the dispatch accumulators. This could be done in `REPLTool.run_async()` after `flush_fn()` completes, using the OpenTelemetry span API directly.

---

## 3. Proposed Enhancements

### 3.1 Add `gen_ai.agent.version` to Existing Tracing

**What:** Propagate an RLM-ADK version identifier through agent spans.

**Where to set it:**
- Define a version constant in `rlm_adk/__init__.py` (or read from `importlib.metadata`).
- Set it on agents via a metadata field or custom span attribute.

**Files to modify:**

1. **`rlm_adk/__init__.py`** -- Add `__version__` constant:
   ```python
   __version__ = "0.1.0"  # or importlib.metadata.version("rlms")
   ```

2. **`rlm_adk/plugins/observability.py`** -- Record version in `before_agent_callback`:
   ```python
   from rlm_adk import __version__
   # In before_agent_callback:
   state["app:rlm_adk_version"] = __version__
   ```

3. **`rlm_adk/plugins/sqlite_tracing.py`** -- Add `agent_version TEXT` column to `traces` table. Populate in `before_agent_callback` or `after_run_callback`:
   ```python
   # In _finalize_trace:
   update_kwargs["agent_version"] = state.get("app:rlm_adk_version", "unknown")
   ```

4. **`rlm_adk/agent.py`** -- If ADK v1.27.0 exposes a `version` field on `BaseAgent` or `LlmAgent`, set it during construction. Otherwise, rely on the state key approach above.

**State key to add to `rlm_adk/state.py`:**
```python
APP_RLM_ADK_VERSION = "app:rlm_adk_version"
```

**Effort:** S | **Impact:** Medium | **Risk:** Low

### 3.2 Leverage Tool Execution Error Codes in ObservabilityPlugin

**What:** Extend `ObservabilityPlugin` to capture tool-level error information, complementing the existing `OBS_TOOL_INVOCATION_SUMMARY` (invocation counts only).

**Where:** `rlm_adk/plugins/observability.py` -- new or extended `after_tool_callback`.

**Proposed implementation:**

```python
# New state key in state.py:
OBS_TOOL_ERROR_SUMMARY = "obs:tool_error_summary"

# In ObservabilityPlugin.after_tool_callback (new method):
async def after_tool_callback(
    self,
    *,
    tool: BaseTool,
    tool_args: dict[str, Any],
    tool_context: ToolContext,
    result: dict,
) -> dict | None:
    try:
        tool_name = getattr(tool, "name", str(tool))
        state = tool_context.state
        # Track tool errors (stderr presence for execute_code, or error key)
        if isinstance(result, dict):
            has_error = bool(result.get("stderr")) or bool(result.get("error"))
            if has_error:
                error_summary: dict = state.get(OBS_TOOL_ERROR_SUMMARY, {})
                error_summary[tool_name] = error_summary.get(tool_name, 0) + 1
                state[OBS_TOOL_ERROR_SUMMARY] = error_summary
    except Exception:
        pass
    return None
```

This complements the v1.27.0 automatic OTel tool error spans with session-state-level error tracking that feeds into the SqliteTracingPlugin and dashboard.

**Effort:** S | **Impact:** Medium | **Risk:** Low

### 3.3 Use `gen_ai.client.inference.operation.details` for Per-Call Breakdown

**What:** If the new OTel inference event carries structured per-call metadata (model params, token breakdown, latency), consider whether it can replace or supplement the manually-built `OBS_PER_ITERATION_TOKEN_BREAKDOWN` in `ObservabilityPlugin.after_model_callback`.

**Assessment:** The manual breakdown entry (lines 222-244 of `observability.py`) includes RLM-specific fields not present in the OTel event:
- `iteration` (REPL iteration counter, depth-scoped)
- `agent_type` ("reasoning" vs "worker")
- `prompt_chars` and `system_chars` (character-level accounting)
- `context_snapshot` (detailed context window composition)

**Recommendation:** Do **not** replace the manual breakdown. Instead, use the OTel event as a complementary data source in Langfuse/Cloud Trace for cross-system correlation. The RLM-specific fields are essential for the local dashboard and SqliteTracingPlugin, and the OTel event does not carry them.

**Action:** No code changes needed. The OTel event flows automatically through `GoogleADKInstrumentor`. Document the complementary relationship so future developers know both sources exist.

**Effort:** None (auto) | **Impact:** Low (additive) | **Risk:** None

### 3.4 Enhance GoogleCloudAnalyticsPlugin with BQ Schema Upgrades

**What:** Update `GoogleCloudAnalyticsPlugin` to pass new v1.27.0 configuration options to `BigQueryAgentAnalyticsPlugin`.

**Where:** `rlm_adk/plugins/google_cloud_analytics.py`

**Proposed changes:**

1. **Pass `location` parameter** from env var for multi-region support:
   ```python
   location = os.getenv("RLM_BQ_LOCATION", "US")
   ```

2. **Enable auto views** if the upstream plugin exposes a config option. Check `BigQueryLoggerConfig` for a `create_views` or `auto_views` parameter after upgrading.

3. **Add trace correlation** by passing the active OTel trace ID to the BQ plugin. This connects BQ analytics rows to Cloud Trace spans:
   ```python
   # In after_run_callback, before delegating:
   try:
       from opentelemetry import trace as otel_trace
       current_span = otel_trace.get_current_span()
       if current_span and current_span.get_span_context().trace_id:
           # The BQ plugin may read this from the span context automatically
           pass
   except ImportError:
       pass
   ```

4. **Forward additional obs keys** to enrich BQ rows. Currently the plugin only delegates `after_run_callback`. Consider also implementing `after_model_callback` and `after_tool_callback` to forward per-call telemetry to BQ if the upstream schema supports it.

**Effort:** M | **Impact:** Medium | **Risk:** Low (BQ plugin handles schema migration)

### 3.5 Child Dispatch Error Codes in OTel Spans (Custom Enrichment)

**What:** Bridge the gap identified in section 2.3 by manually adding child dispatch error information to the active OTel span.

**Where:** `rlm_adk/tools/repl_tool.py` -- after `flush_fn()` call.

**Proposed pattern:**

```python
# In REPLTool.run_async(), after flush_fn() (line 277-281):
if self._flush_fn is not None:
    acc = self._flush_fn()
    for k, v in acc.items():
        tool_context.state[k] = v
    total_llm_calls = acc.get(OBS_CHILD_DISPATCH_COUNT, 0)

    # Enrich active OTel span with child dispatch error summary
    child_errors = acc.get(OBS_CHILD_ERROR_COUNTS)
    if child_errors:
        try:
            from opentelemetry import trace as otel_trace
            span = otel_trace.get_current_span()
            if span and span.is_recording():
                span.set_attribute("rlm.child_dispatch.error_counts",
                                   json.dumps(child_errors))
                span.set_attribute("rlm.child_dispatch.total", total_llm_calls)
        except ImportError:
            pass  # OTel not installed
```

This makes child dispatch errors visible in Langfuse and Cloud Trace at the tool-span level, searchable and filterable.

**State keys consumed:** `OBS_CHILD_ERROR_COUNTS`, `OBS_CHILD_DISPATCH_COUNT` (from `rlm_adk/state.py`)

**Effort:** S | **Impact:** High | **Risk:** Low (additive, OTel import is optional)

---

## 4. Automatic vs Code Changes Matrix

| Change | What Happens on `pip install google-adk>=1.27.0` | Code Changes Needed |
|--------|--------------------------------------------------|-------------------|
| `gen_ai.agent.version` span attribute | Attribute appears on all spans (value may be empty) | Set version on agents or via state key (section 3.1) |
| `gen_ai.tool.definitions` | REPLTool + SetModelResponseTool schemas captured in spans | **None** (auto via runtime tool wiring) |
| `gen_ai.client.inference.operation.details` event | Per-call inference events appear in Langfuse/Cloud Trace | **None** (auto, complementary to manual breakdown) |
| Token usage span attribute fix | Token counts reliably appear in all OTel spans | **None** (auto, fixes data gaps) |
| Tool error codes in OTel spans | REPLTool/SetModelResponseTool errors captured in spans | **None** for direct tool errors. Section 3.5 for child dispatch errors. |
| BQ schema upgrades + fork safety | Auto-migration on existing `BigQueryAgentAnalyticsPlugin` | Optional config updates (section 3.4) |
| BQ auto views | Depends on `BigQueryLoggerConfig` options | May need config pass-through (section 3.4) |
| BQ trace continuity | OTel trace IDs correlated with BQ rows | Likely auto if OTel is active alongside BQ plugin |

---

## 5. Opportunity Ratings

| Enhancement | Effort | Impact | Risk | Priority |
|-------------|--------|--------|------|----------|
| **Upgrade ADK to >=1.27.0** (gate for all below) | S | High | Medium (API breakage check needed for BUG-13 patch, `_invocation_context` private API) | P0 |
| 3.1 Agent version in tracing | S | Medium | Low | P1 |
| 3.2 Tool error summary in ObservabilityPlugin | S | Medium | Low | P1 |
| 3.3 Inference operation details (auto) | None | Low | None | P3 (no action) |
| 3.4 BQ plugin config enhancement | M | Medium | Low | P2 |
| 3.5 Child dispatch errors in OTel spans | S | High | Low | P1 |

### Upgrade Risk Assessment

The ADK version jump from >=1.2.0 to >=1.27.0 is significant. Key risk areas:

1. **BUG-13 monkey-patch** (`rlm_adk/callbacks/worker_retry.py`): Patches `_output_schema_processor.get_structured_model_response`. If ADK v1.27.0 restructures this module or changes the function signature, the patch breaks. **Mitigation:** The patch has a graceful fallback (returns original function result if detection fails). Test with `_bug13_stats["suppress_count"]` assertion.

2. **`CallbackContext._invocation_context` private API** (used in `callbacks/reasoning.py`, `plugins/observability.py`, `callbacks/worker_retry.py`): If ADK changes the internal structure, callbacks lose agent access. **Mitigation:** Pin to a specific minor version initially; add a version-gated compatibility shim.

3. **Plugin callback wiring gap** (`base_llm_flow.py` not wiring `event_actions` for plugin `after_model_callback`): If v1.27.0 fixes this, the `ObservabilityPlugin.after_agent_callback` ephemeral-key workaround becomes unnecessary (but harmless). **Mitigation:** Keep the workaround; it is idempotent.

4. **`openinference-instrumentation-google-adk` compatibility**: Current pin is `>=0.1.9`. The v1.27.0 ADK may require a newer instrumentor version. **Mitigation:** Check release notes and update pin.

### Recommended Upgrade Path

1. Bump `google-adk>=1.27.0` in `pyproject.toml`
2. Run full test suite (`.venv/bin/python -m pytest tests_rlm_adk/ -m ""`) to catch breakage
3. Verify BUG-13 patch: check `_bug13_stats["suppress_count"]` in FMEA tests
4. Verify ephemeral keys still reach `final_state` via `after_agent_callback`
5. Spot-check Langfuse UI for new span attributes (`gen_ai.agent.version`, `gen_ai.tool.definitions`)
6. Implement P1 enhancements (sections 3.1, 3.2, 3.5)

---

## 6. File Reference

| File | Role in This Proposal |
|------|----------------------|
| `rlm_adk/plugins/observability.py` | Primary enhancement target (sections 3.1, 3.2) |
| `rlm_adk/plugins/sqlite_tracing.py` | Version column addition (section 3.1) |
| `rlm_adk/plugins/langfuse_tracing.py` | Automatic beneficiary (no changes) |
| `rlm_adk/plugins/google_cloud_tracing.py` | Automatic beneficiary (no changes) |
| `rlm_adk/plugins/google_cloud_analytics.py` | BQ config enhancement (section 3.4) |
| `rlm_adk/tools/repl_tool.py` | Child dispatch OTel enrichment (section 3.5) |
| `rlm_adk/dispatch.py` | Source of child error classification consumed by section 3.5 |
| `rlm_adk/state.py` | New state key for version (section 3.1), tool errors (section 3.2) |
| `rlm_adk/agent.py` | Version wiring on agent construction (section 3.1) |
| `rlm_adk/callbacks/worker_retry.py` | BUG-13 patch compatibility check (upgrade risk) |
| `rlm_adk/callbacks/reasoning.py` | `_invocation_context` private API compatibility check (upgrade risk) |
| `pyproject.toml` | ADK version pin update |
