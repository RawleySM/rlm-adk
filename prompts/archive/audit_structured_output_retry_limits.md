<!-- generated: 2026-03-17 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Audit Structured Output Retry Limits and Model Turn Count

## Context

The user observed ~15 model turns during a live replay of the recursive ping fixture (`adk run --replay`). They suspect the structured output retry loop may be unbounded or misconfigured, allowing excessive model turns before termination. This audit confirms the retry wiring is correct, reviews the max limits, and identifies whether the observed turn count is expected behavior or a bug.

## Original Transcription

> Have an agent delegated to look into the, retry loop and max retries for structured outputs. I believe we have a bug there because I have seen, like, on the order of 15 different model turns over the live replay of the model ping, and I want to make sure that's resolved before we run anymore. Go ahead and confirm that's wired properly. And review the max limit we have set for retries when we run the live replay test fixtures.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

1. **Spawn a `Retry-Auditor` teammate to trace the full structured output retry path and confirm wiring correctness.**

   The audit should trace these three independent retry mechanisms and confirm each is properly bounded:

   **A. Structured output validation retry** (`WorkerRetryPlugin` / `ReflectAndRetryToolPlugin`):
   - `orchestrator.py:316` calls `make_worker_tool_callbacks(max_retries=2)` — this creates a `WorkerRetryPlugin(max_retries=2)` instance
   - `WorkerRetryPlugin.__init__` at `worker_retry.py:86-87` passes `max_retries=2` to `super().__init__(max_retries=max_retries)` (ADK's `ReflectAndRetryToolPlugin`)
   - The retry guard is at `reflect_retry_tool_plugin.py:256`: `if current_retries <= self.max_retries` — allows 2 retries (3 total attempts), then raises on the 3rd consecutive failure
   - Counter isolation: `_reset_failures_for_tool` at `reflect_retry_tool_plugin.py:279-287` only resets the counter for the specific tool that succeeded (e.g., `execute_code` success does NOT reset `set_model_response` counter)
   - When `throw_exception_if_retry_exceeded=True` (the default), the exception propagates through ADK's agent loop and terminates the reasoning agent's run

   **B. Transient HTTP error retry** (orchestrator-level):
   - `orchestrator.py:443`: `max_retries = int(os.getenv("RLM_LLM_MAX_RETRIES", "3"))`
   - Only fires for `is_transient_error()` exceptions (429, 500, 502, 503, 504, timeouts, network errors)
   - This is a completely separate mechanism from structured output retry — it retries the entire `reasoning_agent.run_async(ctx)` call

   **C. REPL call limit** (tool-level):
   - `orchestrator.py:288`: `max_calls=max_iterations` (default 30 for root via `RLM_MAX_ITERATIONS` env var)
   - `repl_tool.py:133`: `if self._call_count > self._max_calls` — returns error message instead of executing code
   - For children: `agent.py:344` defaults `max_iterations=10`
   - This only limits `execute_code` invocations, NOT total model turns

   **Key finding to validate:** The ~15 model turns observed during recursive ping is likely **normal operation**, not a retry bug. Each REPL iteration requires at minimum 2 model turns (model generates code → model receives result). A recursive ping that dispatches child queries, processes results, and calls `set_model_response` at the end would naturally produce 10-15 model turns. The teammate should confirm this by counting the turns in the replay fixture.

2. **Spawn a `Schema-Double-Inject-Auditor` teammate to verify there is no double `SetModelResponseTool` injection for children with `output_schema`.**

   There is a potential compounding issue when `output_schema` is set on both:
   - The `LlmAgent` field (set in `create_reasoning_agent` at `agent.py:278`: `output_schema=output_schema`)
   - The manual tool injection (set in `orchestrator.py:303-305`: `SetModelResponseTool(schema)` added to tools list)

   ADK's `_output_schema_processor.py:43-54` checks `agent.output_schema` and `agent.tools` — if both are truthy and the model cannot natively combine output_schema with tools (`can_use_output_schema_with_tools` returns False), ADK injects ANOTHER `SetModelResponseTool` into the LLM request.

   For the **root orchestrator**, `output_schema=None` is passed to `create_reasoning_agent` (from `create_rlm_orchestrator`), so no double injection occurs.

   For **children** where `output_schema` is provided (e.g., `llm_query("prompt", output_schema=MySchema)`), both paths may fire. The teammate should:
   - Check what `can_use_output_schema_with_tools` returns for the project's Gemini model
   - If it returns False, confirm whether double `SetModelResponseTool` in the tool list causes any behavioral issues (duplicate tool declarations, confusion for the model, etc.)
   - If this is a real bug, fix it by either (a) NOT setting `output_schema` on the `LlmAgent` for children (let the orchestrator handle it manually), or (b) NOT manually adding `SetModelResponseTool` when `output_schema` is already on the agent

3. **Spawn a `Replay-Turn-Counter` teammate to instrument the recursive ping replay and count actual model turns.**

   Run the live replay fixture and count the exact number of model turns:
   ```bash
   RLM_REPL_TRACE=1 .venv/bin/adk run --replay tests_rlm_adk/replay/recursive_ping.json rlm_adk
   ```

   Capture:
   - Total model turns (LLM calls)
   - How many are `execute_code` tool calls vs `set_model_response` tool calls
   - Whether any `set_model_response` calls triggered retry (look for `ToolFailureResponse` / `REFLECT_AND_RETRY_RESPONSE_TYPE` in the event stream)
   - The BUG-13 suppress count (`_bug13_stats["suppress_count"]`)

   If the turn count is genuinely excessive (i.e., model is retrying `set_model_response` more than 2 times), this proves a wiring bug. If the turns are all normal `execute_code` iterations, the retry wiring is correct and the observed behavior is expected.

   *[Added — the transcription didn't mention this, but empirical verification against the replay fixture is necessary to distinguish "retry bug" from "normal iteration count."]*

## Provider-Fake Fixture & TDD

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/structured_output_retry_exhaustion.json`

**Essential requirements the fixture must capture:**
- A child dispatch with `output_schema` where the model provides an invalid `set_model_response` payload 3 times consecutively (exceeding `max_retries=2`), proving the retry limit is enforced
- The fixture must verify that after retry exhaustion, the child returns an `LLMResult` with `error=True` and `error_category="SCHEMA_VALIDATION_EXHAUSTED"` — not an infinite loop
- The fixture must include at least one successful `execute_code` call between failed `set_model_response` attempts to prove the failure counter is per-tool (not reset by unrelated tool success)

**TDD sequence:**
1. Red: Write test asserting that a child with `output_schema` terminates after 3 failed `set_model_response` attempts (max_retries=2). Run, confirm failure (no fixture yet).
2. Green: Create the fixture JSON with 3 consecutive invalid structured output responses. Run, confirm pass.
3. Red: Write test asserting that `_structured_output_obs["retry_count"]` equals 2 and `_structured_output_obs["events"][-1]["outcome"]` equals `"exhausted"`. Continue.
4. Red: Write test asserting intervening `execute_code` success does NOT reset the `set_model_response` failure counter.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the retry limit enforcement works end-to-end.

## Considerations

- **AR-CRIT-001 compliance**: The structured output retry mechanism operates entirely within ADK's tool callback system (`after_tool_callback` / `on_tool_error_callback`), not dispatch closures. No state mutation violations are expected.
- **BUG-13 interaction**: The monkey-patch in `worker_retry.py:238-284` suppresses ADK's premature worker termination when `ToolFailureResponse` is returned. If this patch fails to fire, the worker terminates on the FIRST `set_model_response` call (before any retry). Verify `_bug13_stats["suppress_count"]` increments during retry scenarios.
- **`ReflectAndRetryToolPlugin` scope**: Default scope is `TrackingScope.INVOCATION`, meaning failure counters are keyed by `tool_context.invocation_id`. Each child orchestrator gets its own invocation context, so counters are properly isolated per-child.
- **The `_scoped_failure_counters` dict** on the `WorkerRetryPlugin` instance is shared across the entire reasoning agent run (one plugin instance per `_run_async_impl` call). If the model tries `set_model_response`, fails, goes back to `execute_code`, then tries `set_model_response` again — the failure counter persists (not reset). This is correct behavior.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/orchestrator.py` | `_run_async_impl` | L227 | Orchestrator entry point, wires retry callbacks |
| `rlm_adk/orchestrator.py` | `make_worker_tool_callbacks(max_retries=2)` | L316 | Where structured output retry limit is set |
| `rlm_adk/orchestrator.py` | `max_retries` (transient) | L443 | Separate HTTP error retry (env: `RLM_LLM_MAX_RETRIES`, default 3) |
| `rlm_adk/orchestrator.py` | `SetModelResponseTool(schema)` | L304 | Manual tool injection |
| `rlm_adk/callbacks/worker_retry.py` | `WorkerRetryPlugin.__init__` | L86 | Passes max_retries=2 to parent |
| `rlm_adk/callbacks/worker_retry.py` | `make_worker_tool_callbacks` | L112 | Factory creating plugin + callback wrappers |
| `rlm_adk/callbacks/worker_retry.py` | `_patch_output_schema_postprocessor` | L238 | BUG-13 monkey-patch |
| `rlm_adk/tools/repl_tool.py` | `REPLTool.__init__` | L63 | max_calls parameter (default 60, overridden to 30) |
| `rlm_adk/tools/repl_tool.py` | `_call_count > _max_calls` | L133 | REPL call limit enforcement |
| `rlm_adk/agent.py` | `create_child_orchestrator` | L339 | Child max_iterations default=10 |
| `rlm_adk/agent.py` | `create_reasoning_agent` | L261 | LlmAgent construction with output_schema |
| `rlm_adk/dispatch.py` | `_run_child` | L383 | Child orchestrator dispatch |
| `.venv/.../reflect_retry_tool_plugin.py` | `_handle_tool_error` | L225 | Core retry logic: `current_retries <= self.max_retries` |
| `.venv/.../reflect_retry_tool_plugin.py` | `_reset_failures_for_tool` | L279 | Per-tool counter reset on success |
| `.venv/.../_output_schema_processor.py` | `request_processor` | L43 | Potential double SetModelResponseTool injection |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow branch links for Core Loop, Dispatch & State, and Testing)
