Here’s the implementation task list in commit-sized chunks for the coding agent.

This plan assumes the following fixed contract:

* the reasoning `LlmAgent` continues to expose exactly two terminally meaningful tool choices in the collapsed loop: `execute_code` and `set_model_response(schema)`  
* successful `set_model_response` is the terminal structured-output signal
* lineage moves to `LlmResponse.custom_metadata` plus direct SQLite telemetry
* session state is reduced to working/control state only  

## Invariants the agent must preserve

Do not change these behaviors:

* `create_child_orchestrator(..., output_schema=...)` still yields a child reasoning agent that can either recurse via `execute_code` or finish via `set_model_response` in the same loop. The child must not switch to ADK’s automatic output-schema mode on the `LlmAgent` itself.  
* `make_worker_tool_callbacks()` continues to scope retry/reflection behavior specifically to `set_model_response`. `execute_code` must not be treated as a structured-output terminal path. 
* no schema-level `is_final` / terminal boolean is introduced
* root default `ReasoningOutput.final_answer` remains valid content schema, not a control-plane flag. 

---

# Chunk 1 — Introduce explicit completion and lineage runtime models

**Commit message:** `add completion and lineage envelopes`

### Files

* `rlm_adk/types.py`

### Edit

Add two new Pydantic models and a renderer:

* `CompletionEnvelope`
* `LineageEnvelope`
* `render_completion_text(validated_output, fallback_text="")`

### Required details

`CompletionEnvelope` must carry:

* `terminal`
* `mode` (`"structured" | "text" | "error"`)
* `output_schema_name`
* `validated_output`
* `raw_output`
* `display_text`
* `reasoning_summary`
* `finish_reason`
* `error`
* `error_category`

`LineageEnvelope` must carry:

* `version="v1"`
* `agent_name`
* `depth`
* `fanout_idx`
* `parent_depth`
* `parent_fanout_idx`
* `branch`
* `invocation_id`
* `session_id`
* `output_schema_name`
* `decision_mode`
* `structured_outcome`
* `terminal`

### Pseudocode target

```python
class CompletionEnvelope(BaseModel): ...
class LineageEnvelope(BaseModel): ...

def render_completion_text(validated_output: Any, fallback_text: str = "") -> str:
    ...
```

### Done when

* file imports cleanly
* no existing callers are broken yet
* no behavior changes outside type addition

---

# Chunk 2 — Shrink and rename the state contract

**Commit message:** `reduce session state to working control plane`

### Files

* `rlm_adk/state.py`
* any file importing `FINAL_ANSWER`

### Edit

Rename:

* `FINAL_ANSWER` → `FINAL_RESPONSE_TEXT`

Reduce `EXPOSED_STATE_KEYS` to working/control keys only.

Mark these keys as deprecated for removal from runtime correctness:

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

Do not delete all of them in this chunk if it causes churn. Rename and stop depending on them first.

### Concrete edits

* update `EXPOSED_STATE_KEYS`
* update `DEPTH_SCOPED_KEYS` so only keys still required for runtime continuity remain
* update `depth_key(FINAL_ANSWER, ...)` callsites to `depth_key(FINAL_RESPONSE_TEXT, ...)`

### Done when

* project imports cleanly
* grep shows no writes to `FINAL_ANSWER`
* state constants now clearly reflect “working state only”

---

# Chunk 3 — Move request/response observability out of state in canonical callbacks

**Commit message:** `move reasoning callback observability to agent metadata`

### Files

* `rlm_adk/callbacks/reasoning.py`

### Edit

Keep the existing instruction merge behavior in `reasoning_before_model()`. That part is still correct because it supports the dynamic instruction composition path. 

Replace state-writing observability with agent-local metadata:

### `reasoning_before_model()`

Remove writes of:

* `REASONING_PROMPT_CHARS`
* `REASONING_SYSTEM_CHARS`
* `CONTEXT_WINDOW_SNAPSHOT`

Instead:

* compute prompt chars, system chars, content count
* build a base `LineageEnvelope`
* store both on the agent via `object.__setattr__()`

Suggested runtime attrs:

* `_rlm_pending_request_meta`
* `_rlm_base_lineage`

### `reasoning_after_model()`

Remove writes of:

* visible text
* thought text
* finish reason
* input/output/thought token counts
* reasoning summary to session state 

Instead:

* compute visible text / thought text
* build final `LineageEnvelope`
* attach it into `llm_response.custom_metadata["rlm"]`
* store parsed response-side metadata on the agent:

  * `_rlm_last_response_meta`

### Required helper additions

Add internal helpers:

* `_agent_runtime(callback_context)`
* `_build_lineage(callback_context)`

### Done when

* canonical callbacks no longer require session state for response observability
* `llm_response.custom_metadata` contains JSON-serializable `rlm` lineage payload
* no state delta is required for lineage in model callbacks

---

# Chunk 4 — Make `set_model_response` own terminal completion

**Commit message:** `set_model_response creates terminal completion envelope`

### Files

* `rlm_adk/callbacks/worker_retry.py`

### Edit

Preserve all existing BUG-13 and retry logic. That file already owns the structured-output terminal seam. 

### Change `after_tool_cb()`

For `tool.name == "set_model_response"`:

If validated result succeeds and is not a reflect-and-retry payload:

* keep `agent._structured_result = tool_response`
* create `CompletionEnvelope(terminal=True, mode="structured", ...)`
* set `agent._rlm_terminal_completion`
* update or create `agent._rlm_lineage_status`

If reflect-and-retry payload:

* set lineage status:

  * `decision_mode="set_model_response"`
  * `structured_outcome="retry_requested"`
  * `terminal=False`

### Change `on_tool_error_cb()`

For `set_model_response`:

* on retryable error, update lineage status only
* on exhaustion path, create terminal error `CompletionEnvelope`

### Add helper

* `_set_lineage_status(agent, **updates)`

### Do not change

* `_patch_output_schema_postprocessor()`
* the `_SET_MODEL_RESPONSE_TOOL_NAME` guard
* retry payload detection

### Done when

* terminal completion is created at structured-output success time
* orchestrator no longer needs session-state reasoning keys to know a child/root finished structurally

---

# Chunk 5 — Wire runtime lineage attrs onto reasoning agents

**Commit message:** `tag reasoning agents with runtime lineage attributes`

### Files

* `rlm_adk/agent.py`
* `rlm_adk/orchestrator.py`

### Edit in `agent.py`

No architectural changes to factory behavior. Keep:

* `create_reasoning_agent()`
* `create_child_orchestrator()` semantics as they are today 

Only ensure child orchestrators have enough fields available to supply:

* `depth`
* `fanout_idx`
* parent scope if needed

If `RLMOrchestratorAgent` does not yet have `parent_depth` / `parent_fanout_idx`, add them as optional fields.

### Edit in `orchestrator.py`

Inside `_run_async_impl`, when wiring `reasoning_agent`, set runtime attrs with `object.__setattr__()`:

* `_rlm_depth`
* `_rlm_fanout_idx`
* `_rlm_parent_depth`
* `_rlm_parent_fanout_idx`
* `_rlm_output_schema_name`
* `_rlm_terminal_completion = None`
* `_rlm_lineage_status = None`
* `_rlm_pending_request_meta = None`
* `_rlm_last_response_meta = None`

### Done when

* every reasoning agent instance can build lineage without reading session state
* root and child agents both carry explicit runtime scope

---

# Chunk 6 — Simplify orchestrator completion collection

**Commit message:** `orchestrator finalizes from completion envelope`

### Files

* `rlm_adk/orchestrator.py`

### Edit

Replace `_collect_reasoning_completion()` with a new helper centered on `CompletionEnvelope`.

Suggested new helper:

* `_collect_completion(...)`

### Priority order

1. `reasoning_agent._rlm_terminal_completion`
2. fallback from `output_key`
3. fallback from plain-text response candidate if available
4. synthesize terminal error envelope

### Also change final state writes

At the end of `_run_async_impl`, emit only:

* `depth_key(FINAL_RESPONSE_TEXT, self.depth)`
* `depth_key(SHOULD_STOP, self.depth)`

Remove emission of:

* `REASONING_RAW_OUTPUT`
* `REASONING_PARSED_OUTPUT`
* `REASONING_SUMMARY`
* other reasoning observability state deltas as part of finalization 

### Also change artifact save

`save_final_answer()` should receive the rendered `completion.display_text`.

### Done when

* orchestrator completion does not depend on response observability state keys
* terminal structured output and fallback text paths both still work
* final emitted text is deterministic

---

# Chunk 7 — Stop propagating child lineage through parent state

**Commit message:** `remove child lineage state mirroring from dispatch`

### Files

* `rlm_adk/dispatch.py`

### Edit

Delete lineage transport through state.

Specifically remove:

* `_CHILD_PROPAGATION_KEYS`
* `_acc_child_depth_state`
* propagation loop that copies child depth-scoped keys into parent delta
* merging `_acc_child_depth_state` into `flush_fn()` delta 

### Keep

* child orchestration
* semaphore control
* `LLMResult` construction
* optional parent skill-instruction restoration

### Rename

`flush_fn()` → `post_dispatch_state_patch_fn()`

Keep it minimal:

* restore `DYN_SKILL_INSTRUCTION` if still required for parent working state
* nothing else unless a true working-state need exists

### Change `_run_child()`

Use:

* `child._rlm_completion`
* `child.reasoning_agent._rlm_terminal_completion`
* then fallback to `output_key`

Build `LLMResult` from that result, not from child state deltas.

### Done when

* child sibling lineage no longer travels through parent state
* dispatch is no longer a telemetry mirror layer
* state patching is minimal and explicitly working-state only

---

# Chunk 8 — Update REPL tool to use minimal post-dispatch patching

**Commit message:** `repl tool applies minimal post dispatch state patch`

### Files

* `rlm_adk/tools/repl_tool.py`
* any constructor callsites

### Edit

Rename constructor arg:

* `flush_fn` → `post_dispatch_state_patch_fn`

Inside `run_async()`:

* call the renamed function after code execution
* write only its returned minimal working-state patch into `tool_context.state`

Do not assume child lineage or structured-output details arrive through this patch anymore.

### Keep

* `LAST_REPL_RESULT`
* code submission observability
* AST rewrite metrics if still desired
* `_rlm_state` injection path

### Done when

* REPL tool still supports child dispatch
* but no longer acts as the main lineage transport layer

---

# Chunk 9 — Make SQLite tracing the authoritative lineage sink

**Commit message:** `persist lineage directly in sqlite telemetry`

### Files

* `rlm_adk/plugins/sqlite_tracing.py`

### Schema edits

Add telemetry columns:

* `fanout_idx`
* `parent_depth`
* `parent_fanout_idx`
* `branch`
* `invocation_id`
* `session_id`
* `output_schema_name`
* `decision_mode`
* `structured_outcome`
* `terminal_completion`
* `custom_metadata_json`
* `validated_output_json`

Add them to:

* `_SCHEMA_SQL`
* `_migrate_schema()`

### `before_model_callback()`

Stop depending on `CONTEXT_WINDOW_SNAPSHOT` in state. Compute request-side metrics directly from `llm_request` and agent attrs. 

Populate:

* depth
* fanout
* parent scope
* output schema name
* prompt/system char counts
* branch
* session/invocation identifiers

### `after_model_callback()`

Parse `llm_response.custom_metadata.get("rlm")` and persist it directly.

### `before_tool_callback()` / `after_tool_callback()`

Persist actual tool decision:

* `execute_code` → `decision_mode="execute_code"`
* `set_model_response` → `decision_mode="set_model_response"`

For `set_model_response`, also persist:

* `structured_outcome`
* `terminal_completion`
* `validated_output_json`

### `on_event_callback()`

Keep only curated working-state capture.

Remove reliance on SSE rows for lineage-heavy reasoning data.

### Done when

* lineage can be reconstructed from telemetry rows alone
* session-state events are no longer needed to understand structured-output completion or child scope

---

# Chunk 10 — Trim `ObservabilityPlugin` down to summary-only state

**Commit message:** `remove lineage persistence from observability plugin`

### Files

* `rlm_adk/plugins/observability.py`
* docs if needed in same chunk or next

### Edit

Delete or reduce any plugin logic that writes model-call lineage into state and then re-persists it through `after_agent_callback`.

That workaround exists because the plugin currently tries to use state/event deltas as a telemetry bus. After the refactor, that should no longer be true. Your docs explicitly call that out today. 

### Keep only if useful

* lightweight run summary counters in state
* tool invocation summary if you still want it exposed to agent logic

### Remove dependence on

* `CONTEXT_WINDOW_SNAPSHOT`
* per-call token/state persistence solely for tracer visibility

### Done when

* there is no duplicate lineage path in both SQLite telemetry and session state
* plugin no longer depends on ephemeral plugin-callback state workaround for core observability

---

# Chunk 11 — Slim `_rlm_state` and REPL state exposure

**Commit message:** `slim repl state snapshot to working state only`

### Files

* `rlm_adk/state.py`
* wherever `_rlm_state` snapshot is built
* likely `rlm_adk/tools/repl_tool.py`

### Edit

Ensure `_rlm_state` only exposes stable working-state values the model may need for reasoning continuity.

Keep:

* depth
* iteration
* step mode
* max depth/max iterations
* `LAST_REPL_RESULT`
* maybe `FINAL_RESPONSE_TEXT` if useful

Remove:

* lineage-heavy `obs:*`
* response raw/parsed/tokens/thought fields
* child summary payloads

### Done when

* the REPL has working-state introspection
* but lineage lives outside shared session state

---

# Chunk 12 — Rewrite tests around the new contract

**Commit message:** `rewrite tests for completion lineage split`

### Files

* structured output tests
* dispatch tests
* provider-fake / e2e tests
* sqlite tracing tests

### Add or update tests

#### Structured output / terminality

* child `llm_query(..., output_schema=Schema)` returns parsed result via validated `set_model_response`
* no schema-level terminal bool is required
* `execute_code` does not set terminal completion

#### Completion envelope

* successful `set_model_response` creates `CompletionEnvelope(terminal=True, mode="structured")`
* retry exhaustion creates terminal error envelope

#### State minimization

* session state does not require reasoning raw/parsed/tokens/visible/thought lineage keys
* child sibling lineage is absent from parent session-state transport

#### SQLite telemetry

* telemetry row contains:

  * depth
  * fanout_idx
  * output_schema_name
  * decision_mode
  * structured_outcome
  * terminal_completion
  * custom metadata JSON

#### Root rendering

* if validated payload has `final_answer`, rendered text uses it
* otherwise rendered text falls back to JSON or validated string

### Done when

* the test suite encodes the new architecture rather than the old state-mirroring design

---

# Chunk 13 — Update docs to match the new architecture

**Commit message:** `update docs for state lineage completion split`

### Files

* `rlm_adk_docs/core_loop.md`
* `rlm_adk_docs/dispatch_and_state.md`
* `rlm_adk_docs/observability.md`

### Required doc changes

State clearly that:

* session state is for control plane and working memory
* lineage is attached to responses via `custom_metadata` and persisted directly to SQLite telemetry
* terminal structured output is defined by successful `set_model_response`
* dispatch no longer mirrors child lineage into parent state as a primary observability mechanism
* `post_dispatch_state_patch_fn()` exists only for working-state restoration, not telemetry transport

### Done when

* a reader no longer thinks state deltas are required for lineage
* docs match code behavior

---

# Recommended execution order

Run the chunks in this exact order:

1. Chunk 1
2. Chunk 3
3. Chunk 4
4. Chunk 5
5. Chunk 6
6. Chunk 7
7. Chunk 8
8. Chunk 9
9. Chunk 10
10. Chunk 2
11. Chunk 11
12. Chunk 12
13. Chunk 13

Reason: move runtime completion and lineage first, then collapse old state dependencies, then clean up constants and exposure.

---

# Final acceptance checklist

The refactor is complete only when all are true:

* root and child orchestrators still run the same collapsed ADK loop with both `execute_code` and `set_model_response(schema)` available on the reasoning step  
* successful structured completion is detected from `set_model_response`, not from a schema flag 
* session state is no longer the primary lineage bus
* sibling child lineage is not mirrored into parent state
* `LlmResponse.custom_metadata["rlm"]` exists for model-call lineage 
* SQLite telemetry can reconstruct lineage directly without mining session-state events
* final user-visible text still renders deterministically from structured output or fallback text

If you want, I can turn this into a **single prompt addressed to Claude Code** with explicit tasks, guardrails, and expected deliverables.
