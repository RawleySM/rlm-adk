# GAP-CB-002: Worker callbacks file deleted but audit scope references it

**Severity**: LOW
**Category**: callback-lifecycle
**Files**: `rlm_adk/callbacks/worker.py` (deleted), `rlm_adk/dispatch.py`

## Problem

`rlm_adk/callbacks/worker.py` no longer exists. The thread bridge migration replaced the old `WorkerPool` with leaf `LlmAgent` workers with `DispatchConfig` + child `RLMOrchestratorAgent` instances. The old worker `before_model`/`after_model` callbacks have been removed because child orchestrators now use their own `reasoning_before_model`/`reasoning_after_model` callbacks (wired via `create_reasoning_agent` in `agent.py` line 268-269).

This is architecturally correct -- child orchestrators are full orchestrators with their own reasoning agents, so they get the standard callback chain. The old flat worker callbacks are no longer needed.

## Evidence

- `rlm_adk/callbacks/worker.py` does not exist on disk (confirmed via glob)
- `rlm_adk/dispatch.py` creates child orchestrators via `create_child_orchestrator()` (line 299)
- `rlm_adk/agent.py` `create_child_orchestrator()` calls `create_reasoning_agent()` which wires `before_model_callback=reasoning_before_model` and `after_model_callback=reasoning_after_model` (lines 268-269)
- `rlm_adk/orchestrator.py` wires `after_tool_callback` and `on_tool_error_callback` from `make_worker_tool_callbacks()` at runtime (lines 378-380)

## Impact

No functional gap. The old worker callbacks are fully replaced by:
- `reasoning_before_model` / `reasoning_after_model` on child reasoning agents
- `make_worker_tool_callbacks()` for structured output retry on child reasoning agents
- `on_model_error_callback` is NOT wired on child reasoning agents (see GAP-CB-003)

## Suggested Fix

No action needed for the deletion itself. See GAP-CB-003 for the `on_model_error_callback` gap.
