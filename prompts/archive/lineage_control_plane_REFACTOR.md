Here is the refactor plan I would hand to a coding agent.

First, the current `output_schema` path, because that shapes the split.

Your runtime already treats each reasoning step as a **two-tool decision surface**. The orchestrator wires `REPLTool(name="execute_code")` and `SetModelResponseTool(schema)` onto the same `reasoning_agent` at runtime. It does **not** rely on `LlmAgent(output_schema=...)` for children; `create_child_orchestrator()` explicitly avoids that and leaves manual `SetModelResponseTool` injection to `orchestrator.py` to prevent duplicate synthesized tools.  

When parent-generated REPL code calls `llm_query(..., output_schema=SomeSchema)`, that schema is passed through dispatch into `create_child_orchestrator(..., output_schema=...)`. The child still runs the same collapsed loop: the model can either call `execute_code` again or terminate via `set_model_response`.  

The structured-output retry logic is already scoped correctly: `make_worker_tool_callbacks()` only intercepts the synthesized `set_model_response` tool, captures validated payloads on `agent._structured_result`, and drives retry/reflection only for that tool. It intentionally does **not** treat `execute_code` the same way. 

And ADK’s `SetModelResponseTool` itself validates and returns different shapes depending on schema type: dict for `BaseModel`, list-of-dicts for list-of-`BaseModel`, and raw `response` for non-`BaseModel` schemas. So the completion path already has a clean terminal signal: a successful `set_model_response` call. You do **not** need a second terminal flag embedded inside arbitrary user schemas to know that the agent is done. 

That leads to the core design decision:

## Design decision

Use three separate planes.

**State plane**
Keep only values required for runtime control, prompt templating, REPL continuity, and final user-visible completion.

**Lineage plane**
Put per-model-call and per-tool-call provenance into `LlmResponse.custom_metadata` plus direct SQLite telemetry writes.

**Completion plane**
Normalize successful `set_model_response` outputs into an in-memory completion envelope on the agent/orchestrator, not into a large pile of session state keys.

That means the refactor should stop treating session state as the default observability bus. Right now the tracer is heavily state/event-delta driven, and dispatch mirrors child details back into parent state through `flush_fn()` and propagated depth-scoped keys. That is an implementation artifact of the current closure-based dispatch topology, not the right long-term contract.   

## Final-answer contract

Do **not** add an `is_final_answer` or similar boolean into arbitrary `output_schema` payloads.

Reason:

* terminality is already signaled by successful `set_model_response`; adding a second flag is redundant and fragile.  
* arbitrary child schemas should remain arbitrary.
* the root default schema can still keep `ReasoningOutput.final_answer: str` because that field is user-facing content, not a control flag. 

The coding agent should implement this rule:

**Terminality = validated `set_model_response`, not a field inside the payload.**

For the root orchestrator, emit user-visible text using a deterministic renderer:

1. if parsed structured output contains `final_answer: str`, use it
2. else if the validated output is a string, use it
3. else render compact JSON text

That keeps the completion contract simple and avoids forcing every schema to carry a terminal flag.

---

# Refactor plan

## 1) Introduce explicit runtime objects for completion and lineage

Create two new models in `rlm_adk/types.py` or a new `rlm_adk/lineage.py`.

### A. `CompletionEnvelope`

Purpose: one canonical in-memory result object per reasoning run.

Suggested fields:

```python
class CompletionEnvelope(BaseModel):
    terminal: bool
    mode: Literal["structured", "text", "error"]
    output_schema_name: str | None = None
    validated_output: Any = None
    raw_output: Any = None
    display_text: str = ""
    reasoning_summary: str = ""
    finish_reason: str | None = None
    error: bool = False
    error_category: str | None = None
```

Use it as the authoritative completion record for both root and child orchestrators. This replaces the current mix of `output_key`, `_structured_result`, parsed output, raw output, visible text, and depth-scoped reasoning keys being mined in multiple places. Today `_read_child_completion()` and `_collect_reasoning_completion()` reconstruct completion from that mixture.  

### B. `LineageEnvelope`

Purpose: one canonical provenance payload per model/tool decision.

Suggested fields:

```python
class LineageEnvelope(BaseModel):
    version: Literal["v1"] = "v1"
    agent_name: str
    depth: int
    fanout_idx: int | None = None
    parent_depth: int | None = None
    parent_fanout_idx: int | None = None
    branch: str | None = None
    invocation_id: str | None = None
    session_id: str | None = None
    output_schema_name: str | None = None
    decision_mode: Literal["execute_code", "set_model_response", "unknown"] = "unknown"
    structured_outcome: Literal[
        "not_applicable", "validated", "retry_requested",
        "retry_exhausted", "incomplete", "error"
    ] = "not_applicable"
    terminal: bool = False
```

This is what should go into `LlmResponse.custom_metadata["rlm"]` and also what the SQLite tracer should persist directly. ADK’s `LlmResponse` supports a JSON-serializable `custom_metadata` dict specifically for response labeling. 

## 2) Shrink the session-state contract aggressively

Refactor `rlm_adk/state.py` so that session state is only used for:

* control plane: `CURRENT_DEPTH`, `ITERATION_COUNT`, `SHOULD_STOP`, request IDs, app limits
* prompt-template inputs: `ROOT_PROMPT`, `REPO_URL`, `DYN_SKILL_INSTRUCTION`, user context keys, enabled skills
* REPL continuity: `LAST_REPL_RESULT`
* final root user-visible completion text
* step-mode state if that feature remains active

Everything else should leave session state.

### Remove from state as authoritative lineage data

These should no longer be required for control flow:

* `REASONING_VISIBLE_OUTPUT_TEXT`
* `REASONING_THOUGHT_TEXT`
* `REASONING_THOUGHT_TOKENS`
* `REASONING_RAW_OUTPUT`
* `REASONING_PARSED_OUTPUT`
* `REASONING_FINISH_REASON`
* `REASONING_INPUT_TOKENS`
* `REASONING_OUTPUT_TOKENS`
* `REASONING_PROMPT_CHARS`
* `REASONING_SYSTEM_CHARS`
* `CONTEXT_WINDOW_SNAPSHOT`
* per-child `obs:child_summary@d{D}f{F}` mirror keys as a state transport
* child propagated depth/fanout observability keys
* most `obs:*` counters unless you deliberately want them as agent-readable working memory

Today these keys are either written by callbacks to state or harvested from state/events by the SQLite tracer. That should stop.   

### Rename the root final text key

Because early-stage cleanup is allowed, rename the session key `FINAL_ANSWER` to something clearer like `FINAL_RESPONSE_TEXT`.

Reason:

* `ReasoningOutput.final_answer` is content in a schema. 
* the session key should describe what it stores: rendered text emitted to the user and saved as an artifact.
* terminality should continue to be controlled by `SHOULD_STOP`, not by the presence of a “final_answer” field.

Update all references accordingly.

## 3) Make canonical callbacks write lineage and agent-local completion, not state

Refactor `rlm_adk/callbacks/reasoning.py`.

Today `reasoning_before_model()` writes prompt/system counts and context snapshots into state, and `reasoning_after_model()` writes visible text, thought text, finish reason, and token counts into depth-scoped session keys. 

Replace that with this pattern:

### A. `reasoning_before_model`

Do not write observability into session state.

Instead:

* compute request-side metadata directly from `llm_request`
* store that metadata on the agent as `_rlm_pending_request_meta`
* compute a `LineageEnvelope` base scope from agent attrs:

  * `_rlm_depth`
  * `_rlm_fanout_idx`
  * `_rlm_parent_depth`
  * `_rlm_parent_fanout_idx`
  * `_rlm_output_schema_name`
  * invocation branch/session identifiers from `callback_context._invocation_context`

Because the agent is a Pydantic model, use `object.__setattr__()` for these runtime attrs. That is already the repo pattern.  

### B. `reasoning_after_model`

Do not write response observability to state.

Instead:

* build/complete `LineageEnvelope`
* attach it to `llm_response.custom_metadata["rlm"]`
* compute visible text, thought text, finish reason, token counts
* store them on the agent as `_rlm_last_response_meta`
* if the model produced plain text and did not terminate structurally, optionally set `_rlm_last_text_candidate`

This callback should become the canonical source for response-side lineage, not the session state.

## 4) Move structured-output completion ownership into the `set_model_response` callback path

Refactor `rlm_adk/callbacks/worker_retry.py`.

This file is already the right seam because it already owns:

* successful validated `set_model_response`
* retry requests
* retry exhaustion
* `_structured_result` capture
* BUG-13 suppression behavior for retried structured output. 

### Change `after_tool_cb`

When `tool.name == "set_model_response"` and validation succeeds:

* set `agent._structured_result` as today
* create `CompletionEnvelope(terminal=True, mode="structured", ...)`
* set it on `agent._rlm_terminal_completion`
* update an agent-local lineage status object:

  * `decision_mode = "set_model_response"`
  * `structured_outcome = "validated"`
  * `terminal = True`

When retry is requested:

* update lineage status to `structured_outcome = "retry_requested"`
* do not create terminal completion

### Change `on_tool_error_cb`

When structured validation or set-model-response errors occur:

* update lineage status to `structured_outcome = "retry_requested"` or `retry_exhausted`
* if retries exhaust, set `agent._rlm_terminal_completion` to an error `CompletionEnvelope`

This makes successful structured completion an in-memory contract, not a session-state mining exercise.

## 5) Simplify orchestrator finalization around `CompletionEnvelope`

Refactor `rlm_adk/orchestrator.py`.

Today the orchestrator reconstructs final completion by reading `output_key` from session state, maybe `_structured_result`, and various reasoning state keys, then writes reasoning raw/parsed output back into session state again. 

Replace that with a clean priority order:

### After `reasoning_agent.run_async(ctx)` finishes

1. if `reasoning_agent._rlm_terminal_completion` exists, use it
2. else if a fallback `output_key` value exists, normalize it into a `CompletionEnvelope`
3. else if there is a plain-text response candidate, normalize that
4. else emit an error envelope

### Rendering

Use a dedicated helper such as `render_completion_text()`:

* parsed dict with `final_answer: str` → use that
* validated string → use that
* other validated payload → compact JSON
* error → error text

### State writes at the end

Emit only:

* `FINAL_RESPONSE_TEXT` with rendered display text
* `SHOULD_STOP`
* maybe `ITERATION_COUNT` if needed
* prompt/template keys remain untouched

Do **not** emit `REASONING_RAW_OUTPUT`, `REASONING_PARSED_OUTPUT`, token counts, or response text/thought keys back into session state.

### Agent attributes to set before running

When wiring the reasoning agent, set:

* `_rlm_depth`
* `_rlm_fanout_idx`
* `_rlm_parent_depth`
* `_rlm_parent_fanout_idx`
* `_rlm_output_schema_name`

The child factory already knows depth and fanout, so this is straightforward.  

## 6) Remove child-lineage propagation through shared session state

Refactor `rlm_adk/dispatch.py`.

Today dispatch carries a large amount of child observability by:

* accumulating summaries locally
* mirroring them into `flush_fn()`
* propagating selected child depth-scoped keys into `_acc_child_depth_state`
* pushing them through `tool_context.state` so they surface as parent-visible state deltas and SQLite session-state events. 

That should stop.

### Delete these mechanisms

Remove:

* `_CHILD_PROPAGATION_KEYS`
* `_acc_child_depth_state`
* child depth-scoped reasoning-key propagation into parent state
* session-state transport of per-child lineage summaries purely for SQLite visibility

### Keep only what is actually needed in dispatch

Dispatch should return child results through:

* the child’s in-memory `_rlm_completion`
* `LLMResult` fields (`parsed`, `raw_output`, `visible_text`, `thought_text`, etc.)
* optional small working-state restoration such as parent `DYN_SKILL_INSTRUCTION`

### Keep or reduce `flush_fn()`

Do not delete `flush_fn()` blindly.

It still has one legitimate job: restoring parent working state that child runs may have clobbered, especially `DYN_SKILL_INSTRUCTION`. Your docs already note that this restoration exists to prevent child dispatch from leaving the wrong skill instruction in shared state. 

So reduce `flush_fn()` to a minimal post-dispatch state patcher, then rename it to something clearer like `post_dispatch_state_patch_fn()`.

It should not be the primary telemetry transport anymore.

## 7) Turn SQLite tracing into the authoritative lineage sink

Refactor `rlm_adk/plugins/sqlite_tracing.py`.

Right now the tracer has two strong dependencies on state:

* it reads request/model context from state keys like `CONTEXT_WINDOW_SNAPSHOT`
* it captures lots of curated observability through `on_event_callback` and `session_state_events` rows. 

Move it to direct lineage capture.

### Schema changes

Add these columns to `telemetry`:

* `fanout_idx INTEGER`
* `parent_depth INTEGER`
* `parent_fanout_idx INTEGER`
* `branch TEXT`
* `invocation_id TEXT`
* `session_id TEXT`
* `output_schema_name TEXT`
* `decision_mode TEXT`
* `structured_outcome TEXT`
* `terminal_completion INTEGER`
* `custom_metadata_json TEXT`
* `validated_output_json TEXT`

Keep migrations additive.

### before_model_callback

Stop depending on `CONTEXT_WINDOW_SNAPSHOT` in state.

Instead:

* read `depth/fanout/schema` from agent attrs
* compute `prompt_chars/system_chars/num_contents` directly from `llm_request`
* insert a telemetry row with these values immediately

### after_model_callback

In addition to tokens and finish reason:

* serialize `llm_response.custom_metadata`
* persist the `rlm` lineage envelope if present
* persist response previews if useful

### before_tool_callback / after_tool_callback

Add direct lineage capture for actual tool selection:

* `tool_name == "execute_code"` → `decision_mode = "execute_code"`
* `tool_name == "set_model_response"` → `decision_mode = "set_model_response"`

For `set_model_response`, also persist:

* validated output payload
* structured outcome
* terminal completion flag

This is the correct place to record which of the two tools the model actually chose.

### Reduce `session_state_events`

Keep `session_state_events` only for real working-state changes:

* current depth
* iteration count
* stop flag
* final response text
* prompt/template inputs if useful

Do not rely on session-state events for reasoning lineage anymore.

## 8) Slim or repurpose `ObservabilityPlugin`

Your observability docs currently say plugin `after_model_callback` state writes are ephemeral enough that `after_agent_callback` re-persists them via a workaround. That workaround exists because the plugin is trying to use state as a telemetry path. 

After this refactor:

* remove plugin-side persistence of model-call lineage into state
* either delete those per-call observability writes entirely
* or keep `ObservabilityPlugin` only for lightweight run-summary counters if you still want them in state

Do not let it remain a second telemetry bus that duplicates the SQLite lineage plane.

## 9) Rework `_rlm_state` exposure for REPL introspection

Refactor `EXPOSED_STATE_KEYS` in `state.py` and the REPL snapshot injection path in `REPLTool`.

After this change, `_rlm_state` should expose only stable working-state values the model might legitimately use while reasoning.

Recommended exposed keys:

* `ITERATION_COUNT`
* `CURRENT_DEPTH`
* `APP_MAX_ITERATIONS`
* `APP_MAX_DEPTH`
* `SHOULD_STOP`
* `LAST_REPL_RESULT`
* `REPL_SUBMITTED_CODE_CHARS`
* maybe `STEP_MODE_ENABLED`

Do not expose telemetry-heavy `obs:*` lineage or token-accounting keys by default.

## 10) Update child result normalization to stop mining shared state

Refactor `_read_child_completion()` in `dispatch.py`.

Today it reads from:

* `child._rlm_completion`
* `_structured_result`
* `output_key`
* child-local state deltas
* shared session state
* depth-scoped observability keys. 

Change it to:

1. use `child._rlm_completion` if present
2. else use `child.reasoning_agent._rlm_terminal_completion`
3. else fallback to `_structured_result`
4. else fallback to `output_key`
5. else error

No more reading child visible/thought/tokens from shared state.

## 11) Tests to add or rewrite

### Structured output behavior

* `llm_query("...", output_schema=MySchema)` returns `LLMResult.parsed` from validated `set_model_response`
* `execute_code` path does not set terminal completion
* retry flow still works for invalid `set_model_response` payloads
* BUG-13 suppression still allows retry continuation. 

### State minimization

* session state no longer contains depth-scoped reasoning response/tokens/raw/parsed lineage keys after a run
* child dispatch no longer writes sibling-overwritable `@dN` mirrored lineage into parent state
* `_rlm_state` contains only approved working-state keys

### Telemetry correctness

* telemetry rows include `depth`, `fanout_idx`, `branch`, `output_schema_name`
* `set_model_response` calls are marked `decision_mode="set_model_response"` and `terminal_completion=1`
* `execute_code` calls are marked `decision_mode="execute_code"`
* `custom_metadata_json` includes the `rlm` lineage envelope

### Root completion rendering

* default `ReasoningOutput` still renders user-visible text from `final_answer`
* non-default root schema renders deterministic JSON text when no `final_answer` field exists
* no boolean `is_final` field is required in schemas

## 12) Docs to update

Update these files to reflect the new contract:

* `rlm_adk_docs/core_loop.md`
* `rlm_adk_docs/dispatch_and_state.md`
* `rlm_adk_docs/observability.md`

Especially remove any wording that implies session-state deltas are the required carrier for child lineage or structured-output observability.

---

# Concrete split to implement

## Keep in state

* app/session control keys
* prompt-template keys
* user context keys
* `LAST_REPL_RESULT`
* root final rendered response text
* stop/step-mode flow control

## Put in lineage

* depth/fanout/parent lineage
* branch/invocation lineage
* prompt/system char counts
* tokens
* finish reason
* thought/visible text
* raw structured payload
* parsed structured payload
* structured validation attempts/retry outcome
* actual tool decision (`execute_code` vs `set_model_response`)
* child summaries and sibling-specific completion details

## Keep as in-memory completion

* validated structured output
* rendered display text
* terminal flag
* error classification
* schema name

That is the cleanest split for your current architecture because it preserves the real runtime contract — `execute_code` versus validated `set_model_response` on the same reasoning loop — while removing the accidental dependence on session-state mirroring as the main observability channel.   

If you want, I can turn this into a file-by-file implementation checklist with pseudocode patches for each module.

---

# Implementation summary

## Legacy code removal

The following sections contain directives to **stop**, **remove**, or **delete** existing behavior as part of this refactor.

Status key: DONE = already implemented in production code. REMAINING = code still to change.

### — Design decision

**Directive:** **stop** treating session state as the default observability bus

**Status: DONE.** Production callbacks write to agent-local attrs, not state. SQLite tracer reads `llm_request` directly. `post_dispatch_state_patch_fn` writes only `DYN_SKILL_INSTRUCTION`.

---

### 2) Shrink the session-state contract aggressively

**Directive:** **remove** lineage data from state; callbacks should **stop** writing it

**Status: DONE.** All `REASONING_*` constants removed from `state.py`. Zero production write sites. Residual dead references in non-production files:

| Key | Dead reference sites |
|---|---|
| `REASONING_VISIBLE_OUTPUT_TEXT` | `experiments/custom_metadata_callback.py:27,112` (import+write); `experiments/test_custom_metadata_e2e.py:41,755-756,590,763` (import+reads); `tests_rlm_adk/test_dashboard_ui_gaps.py:24` (local string constant for UI tests) |
| `REASONING_THOUGHT_TEXT` | `experiments/custom_metadata_callback.py:25,113`; `experiments/test_custom_metadata_e2e.py:39,591` |
| `REASONING_THOUGHT_TOKENS` | `experiments/custom_metadata_callback.py:26,118`; `experiments/test_custom_metadata_e2e.py:40,595` |
| `REASONING_FINISH_REASON` | `experiments/custom_metadata_callback.py:22,115`; `experiments/test_custom_metadata_e2e.py:36,592` |
| `REASONING_INPUT_TOKENS` | `experiments/custom_metadata_callback.py:23,116`; `experiments/test_custom_metadata_e2e.py:37,349,363,593,615` |
| `REASONING_OUTPUT_TOKENS` | `experiments/custom_metadata_callback.py:24,117`; `experiments/test_custom_metadata_e2e.py:38,594` |
| `REASONING_RAW_OUTPUT` | No live `.py` references |
| `REASONING_PARSED_OUTPUT` | No live `.py` references |
| `REASONING_PROMPT_CHARS` | No live `.py` references (computed inline in `sqlite_tracing.py:1013-1035`) |
| `REASONING_SYSTEM_CHARS` | No live `.py` references (computed inline in `sqlite_tracing.py:1026-1035`) |
| `CONTEXT_WINDOW_SNAPSHOT` | No live `.py` references (removal documented in `sqlite_tracing.py:1014` comment) |
| `obs:child_summary` | No production write sites. Read-only consumers: `dashboard/live_loader.py:753`; `eval/session_report.py:543` |
| `obs:worker_error_counts` | No production write sites. Read-only consumer: `eval/trace_reader.py:606` |

**REMAINING:** Clean up `experiments/custom_metadata_callback.py` broken imports. Dashboard/eval readers for `obs:child_summary` and `obs:worker_error_counts` are harmless (query SSE rows from historical data) but could be documented as legacy-only.

---

### 3) Make canonical callbacks write lineage and agent-local completion, not state

**Directive:** **do not** write observability into session state (before_model); **do not** write response observability to state (after_model)

**Status: DONE.** `reasoning_before_model` writes only to `agent._rlm_pending_request_meta` via `object.__setattr__` (`callbacks/reasoning.py:167`). `reasoning_after_model` writes only to `agent._rlm_last_response_meta` (`callbacks/reasoning.py:227`). Zero session-state writes. Two test-only hooks (`cb_reasoning_context` at line 265, `cb_tool_context` at line 310) are correctly segregated.

---

### 5) Simplify orchestrator finalization around `CompletionEnvelope`

**Directive:** **do not** emit `REASONING_RAW_OUTPUT`, `REASONING_PARSED_OUTPUT`, token counts, or response text/thought keys back into session state

**Status: DONE.** None of these keys exist in `orchestrator.py`. Completion reconstructed from agent-local attrs via `_collect_completion` (`orchestrator.py:123-206`): priority chain reads `_rlm_terminal_completion` (line 139), `_rlm_last_response_meta` (line 144), `_structured_result` (line 151), `output_key` (line 149-150). `CompletionEnvelope` defined in `types.py:245`, `render_completion_text` at `types.py:279`. Orchestrator emits only: `FINAL_RESPONSE_TEXT`, `SHOULD_STOP`, `CURRENT_DEPTH`, `ITERATION_COUNT`, `REQUEST_ID`, prompt/skill keys, and two retry-obs keys (`OBS_REASONING_RETRY_COUNT` at line 543, `OBS_REASONING_RETRY_DELAY_MS` at line 544).

---

### 6) Remove child-lineage propagation through shared session state

**Directive:** **remove** `_CHILD_PROPAGATION_KEYS`, `_acc_child_depth_state`; **delete** session-state transport of per-child lineage summaries; **stop** using `flush_fn()` as telemetry transport

**Status: DONE.** `_CHILD_PROPAGATION_KEYS` and `_acc_child_depth_state` were never implemented — exist only in planning docs. `flush_fn` renamed to `post_dispatch_state_patch_fn` (`dispatch.py:550-559`), writes only `DYN_SKILL_INSTRUCTION`. No child `@dN` key propagation into parent state. Child results returned via agent-local `_rlm_terminal_completion` and `LLMResult` fields.

---

### 7) Turn SQLite tracing into the authoritative lineage sink

**Directive:** **stop** depending on `CONTEXT_WINDOW_SNAPSHOT` in state; **stop** relying on session-state events for reasoning lineage

**Status: DONE.** `CONTEXT_WINDOW_SNAPSHOT` removed; `before_model_callback` computes `prompt_chars`/`system_chars` directly from `llm_request` (`sqlite_tracing.py:1013-1035`; removal documented at line 1014). Zero `REASONING_*` reads. `session_state_events` captures only curated working-state keys via `_CURATED_EXACT` (lines 113-120: `current_depth`, `iteration_count`, `should_stop`, `final_response_text`, `last_repl_result`, `skill_instruction`) and `_CURATED_PREFIXES` (lines 103-111: `obs:artifact_*`, `artifact_*`, `repl_*` code keys).

---

### 8) Slim or repurpose `ObservabilityPlugin`

**Directive:** **remove** plugin-side persistence of model-call lineage into state; **delete** per-call observability writes that duplicate the SQLite lineage plane

**Status: REMAINING.** `ObservabilityPlugin` (`plugins/observability.py`) still writes 7 `obs:` keys to session state:

| Key | Written at | Mechanism |
|---|---|---|
| `obs:total_calls` | `observability.py:148` (after_model), `:98` (after_agent re-persist) | `callback_context.state` |
| `obs:total_input_tokens` | `observability.py:163` (after_model), `:98` (after_agent re-persist) | `callback_context.state` |
| `obs:total_output_tokens` | `observability.py:167` (after_model), `:98` (after_agent re-persist) | `callback_context.state` |
| `obs:model_usage:<model>` | `observability.py:187` (after_model) | `callback_context.state` |
| `obs:finish_<reason>_count` | `observability.py:215-217` (after_model) | `callback_context.state` |
| `obs:tool_invocation_summary` | `observability.py:241-242` (before_tool) | `tool_context.state` |
| `obs:artifact_saves` | `observability.py:103` (after_agent) | deferred from `on_event_callback` accumulator |

The `after_agent_callback` re-persistence workaround (lines 83-103) exists specifically because `after_model_callback` state writes are ephemeral. `INVOCATION_START_TIME` written at `observability.py:65`.

**Decision needed:** keep as lightweight run-summary counters, or delete and let SQLite telemetry be the sole source. `sqlite_tracing.py` already derives these independently from telemetry rows (`_build_trace_summary_from_telemetry`).

---

### 9) Rework `_rlm_state` exposure for REPL introspection

**Directive:** **do not** expose telemetry-heavy `obs:*` lineage or token-accounting keys by default

**Status: DONE.** `EXPOSED_STATE_KEYS` (`state.py:129-140`) is a `frozenset` of exactly 8 approved keys: `ITERATION_COUNT`, `CURRENT_DEPTH`, `APP_MAX_ITERATIONS`, `APP_MAX_DEPTH`, `LAST_REPL_RESULT`, `STEP_MODE_ENABLED`, `SHOULD_STOP`, `FINAL_RESPONSE_TEXT`. Zero `obs:` keys. Tests explicitly assert exclusion (`test_repl_state_snapshot.py:88`, `test_rlm_state_snapshot_audit.py:136`). REPL snapshot built at `repl_tool.py:201-220`, adds only 3 lineage metadata keys (`_rlm_depth`, `_rlm_fanout_idx`, `_rlm_agent_name`).

---

### 10) Update child result normalization to stop mining shared state

**Directive:** **stop** reading child visible/thought/tokens from shared state

**Status: DONE.** `_read_child_completion` (`dispatch.py:182-276`) uses agent-attr priority chain: P1 `child._rlm_terminal_completion` (line 202), P2 `agent._rlm_terminal_completion` (line 206), P3 `agent._structured_result` (line 224), P4 `child_state[output_key]` from local event-delta accumulator (line 244), P5 error sentinel. No shared session state reads. `_collect_completion` (`orchestrator.py:123-206`) mirrors the same pattern. `CompletionEnvelope` at `types.py:245`.

---

### 12) Docs to update

**Directive:** **remove** wording that implies session-state deltas carry child lineage or structured-output observability

**Status: REMAINING.** Files to audit: `rlm_adk_docs/core_loop.md`, `rlm_adk_docs/dispatch_and_state.md`, `rlm_adk_docs/observability.md`. `observability.md` still references `CONTEXT_WINDOW_SNAPSHOT` at lines 66, 250, 302, 521 as a removed/legacy key (confirm wording is accurate, not prescriptive).
