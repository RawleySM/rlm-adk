# Lineage Telemetry Data-Flow Gap: 5 columns always NULL in traces.db

**Plan**: `~/.claude/plans/cached-swinging-scott.md`

## Severity

**Medium** — The lineage control plane refactor introduced 5 telemetry columns (`decision_mode`, `structured_outcome`, `terminal_completion`, `custom_metadata_json`, `validated_output_json`) in `traces.db`. Despite correct schema definitions and code paths that read/write these columns, all 5 were empty in production data. No runtime errors occurred; the data simply never arrived in the database rows.

## Symptom

Querying the telemetry table after a multi-depth run:

```sql
SELECT decision_mode, structured_outcome, terminal_completion,
       custom_metadata_json, validated_output_json
FROM telemetry
WHERE event_type IN ('model_call', 'tool_call');
```

All 5 columns returned NULL for every row.

## Location

`rlm_adk/plugins/sqlite_tracing.py` — `after_model_callback`, `before_tool_callback`, `after_tool_callback`

## Root Cause

Three independent data-flow gaps, all rooted in the ADK callback execution order: **plugins fire BEFORE agent callbacks** (confirmed in `base_llm_flow.py:981-1002` and `functions.py:487-549`).

### Gap A: `decision_mode` never set for `execute_code` tool calls

REPLTool's finalizer (`make_telemetry_finalizer`) pops the pending telemetry entry from `_pending_tool_telemetry` **during** tool execution, before `after_tool_callback` fires. So `after_tool_callback`'s `if pending:` block never executes for `execute_code` tools. The `decision_mode` assignment at line 1275 was dead code for these rows.

### Gap B: `custom_metadata_json` always NULL for model calls

The plugin's `after_model_callback` read `llm_response.custom_metadata["rlm"]` to build `custom_metadata_json`. But this metadata is injected by `reasoning_after_model` (an **agent** callback), which fires AFTER the plugin's callback. The plugin always saw an empty dict.

### Gap C: `structured_outcome`, `terminal_completion`, `validated_output_json` always NULL

The plugin's `after_tool_callback` read `agent._rlm_lineage_status` to get structured outcome data. But `_rlm_lineage_status` is set by `worker_retry.after_tool_cb` (an **agent** tool callback), which fires AFTER the plugin's tool callback. The plugin always saw `None`.

## Fix

Three self-contained fixes in `sqlite_tracing.py` (no changes to `reasoning.py`, `worker_retry.py`, or `orchestrator.py`):

### Fix A: `decision_mode` in INSERT

Set `decision_mode=tool_name` in the `_insert_telemetry()` call within `before_tool_callback`. The tool name is known at INSERT time, so `decision_mode` is populated even when the finalizer consumes the pending entry before `after_tool_callback`.

```python
# before_tool_callback INSERT
self._insert_telemetry(
    telemetry_id, "tool_call", start_time,
    tool_name=tool_name,
    ...,
    decision_mode=tool_name,  # <-- added
)
```

### Fix B: `custom_metadata_json` from agent attrs

Replaced the `llm_response.custom_metadata["rlm"]` read with direct agent attribute reads. The agent's `_rlm_depth`, `_rlm_fanout_idx`, `_rlm_output_schema_name`, etc. are set by `reasoning_before_model` (which runs before the model call), so they're available when the plugin's `after_model_callback` fires.

```python
# after_model_callback — build lineage directly from agent attrs
inv_ctx = getattr(callback_context, "_invocation_context", None)
agent = getattr(inv_ctx, "agent", None) if inv_ctx else None
if agent is not None:
    rlm_meta = {
        "agent_name": getattr(agent, "name", "unknown"),
        "depth": getattr(agent, "_rlm_depth", 0),
        "fanout_idx": getattr(agent, "_rlm_fanout_idx", None),
        ...
    }
```

Removed the `lineage_kwargs` projection block that attempted to extract `decision_mode`/`structured_outcome`/`terminal_completion` from model-call metadata (these are tool-level concepts, not model-level).

### Fix C: Deferred flush for structured output fields

Introduced a deferred write pattern:

1. `__init__`: Added `self._deferred_tool_lineage: list[dict]`
2. `after_tool_callback`: For `set_model_response` calls, appends `{telemetry_id, agent, result}` to the deferred list instead of reading `_rlm_lineage_status` immediately.
3. New `_flush_deferred_tool_lineage()` method: Iterates deferred entries, reads `_rlm_lineage_status` from each agent (now populated), and issues UPDATE with `structured_outcome`, `terminal_completion`, `validated_output_json`.
4. Flush call sites: `before_model_callback` (start), `after_agent_callback`, `after_run_callback` — points where agent callbacks have completed.

## Files Modified

| File | Change |
|------|--------|
| `rlm_adk/plugins/sqlite_tracing.py` | `__init__`, `before_run_callback`, `before_model_callback`, `after_model_callback`, `before_tool_callback`, `after_tool_callback`, `after_agent_callback`, `after_run_callback`, new `_flush_deferred_tool_lineage` |
| `tests_rlm_adk/test_telemetry_lineage_columns.py` | NEW — 5 tests |

## Files NOT Modified (by design)

| File | Reason |
|------|--------|
| `rlm_adk/callbacks/reasoning.py` | Still injects lineage into `llm_response.custom_metadata` for non-plugin consumers |
| `rlm_adk/callbacks/worker_retry.py` | Still sets `_rlm_lineage_status` on agent for non-plugin consumers |
| `rlm_adk/orchestrator.py` | Initialization of `_rlm_lineage_status = None` remains correct |

## Tests

5 new tests in `test_telemetry_lineage_columns.py`, all using the `lineage_completion_planes` fixture:

| Test | Asserts |
|------|---------|
| `test_execute_code_decision_mode` | All execute_code rows have `decision_mode='execute_code'` |
| `test_set_model_response_decision_mode_and_outcome` | All set_model_response rows have correct `decision_mode`; >= 1 with `structured_outcome='validated'` and `terminal_completion=1` |
| `test_validated_output_json_populated` | Terminal rows have non-null `validated_output_json` parseable as non-empty dict |
| `test_model_call_custom_metadata_json` | Model calls at depth >= 1 have `custom_metadata_json` with `agent_name`, `depth`, `output_schema_name` |
| `test_all_tool_calls_have_decision_mode` | Every tool_call row has `decision_mode` in `{execute_code, set_model_response}` |

## Verification

```bash
# New tests (5/5 pass):
.venv/bin/python -m pytest tests_rlm_adk/test_telemetry_lineage_columns.py -m agent_challenge -x -q

# Existing lineage tests (6/6 pass, no regressions):
.venv/bin/python -m pytest tests_rlm_adk/test_provider_fake_e2e.py -k lineage -m agent_challenge -x -q

# Default suite (282 pass, 0 fail):
.venv/bin/python -m pytest tests_rlm_adk/ -x -q -k "not request_body_comprehensive"
```

## Key Insight

The ADK plugin/agent callback ordering creates a fundamental data-flow challenge for observe-only plugins: data written by agent callbacks is invisible to plugin callbacks at the same lifecycle point. The deferred flush pattern (collect references during plugin callback, resolve values at a later lifecycle point) is the correct general solution when the plugin needs data that agent callbacks produce.
