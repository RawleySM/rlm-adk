Here's the implementation task list in commit-sized chunks for the coding agent.

This plan assumes the following fixed contract:

* the reasoning `LlmAgent` continues to expose exactly two terminally meaningful tool choices in the collapsed loop: `execute_code` and `set_model_response(schema)`
* successful `set_model_response` is the terminal structured-output signal
* lineage moves to `LlmResponse.custom_metadata` plus direct SQLite telemetry
* session state is reduced to working/control state only
* `_rlm_terminal_completion: CompletionEnvelope` is the unified completion attr on both reasoning agents and orchestrators — the legacy `_rlm_completion: dict` is deleted

## Invariants the agent must preserve

Do not change these behaviors:

* `create_child_orchestrator(..., output_schema=...)` still yields a child reasoning agent that can either recurse via `execute_code` or finish via `set_model_response` in the same loop. The child must not switch to ADK's automatic output-schema mode on the `LlmAgent` itself.
* `make_worker_tool_callbacks()` continues to scope retry/reflection behavior specifically to `set_model_response`. `execute_code` must not be treated as a structured-output terminal path.
* no schema-level `is_final` / terminal boolean is introduced
* root default `ReasoningOutput.final_answer` remains valid content schema, not a control-plane flag.
* all dynamic attrs on Pydantic agents must use `object.__setattr__()` — normal assignment raises `ValidationError`.
* step-mode functionality (`STEP_MODE_ENABLED`, `STEP_MODE_PAUSED_AGENT`, `STEP_MODE_PAUSED_DEPTH`, `STEP_MODE_ADVANCE_COUNT`) is preserved unchanged throughout.

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

`render_completion_text` requires `import json` — already present in `types.py`.

### Pseudocode target

```python
import json
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

Add:

* `FINAL_RESPONSE_TEXT = "final_response_text"`

Rename all writes from `FINAL_ANSWER` → `FINAL_RESPONSE_TEXT`.

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
* `REASONING_SUMMARY`

Do not delete all of them in this chunk if it causes churn. Rename and stop depending on them first.

### Concrete edits

* update `EXPOSED_STATE_KEYS`
* update `DEPTH_SCOPED_KEYS` so only keys still required for runtime continuity remain
* update `depth_key(FINAL_ANSWER, ...)` callsites to `depth_key(FINAL_RESPONSE_TEXT, ...)`
* grep for string literal `"final_answer"` in `sqlite_tracing.py` `_CURATED_EXACT` and `_categorize_key` — update those too
* step-mode constants (`STEP_MODE_ENABLED`, `STEP_MODE_PAUSED_AGENT`, `STEP_MODE_PAUSED_DEPTH`, `STEP_MODE_ADVANCE_COUNT`) are unchanged

### Done when

* project imports cleanly
* `FINAL_RESPONSE_TEXT` constant is importable from `state.py`
* grep shows no writes to `FINAL_ANSWER` (Python symbol) across all source files
* string literal `"final_answer"` no longer appears in `sqlite_tracing.py` capture sets
* state constants now clearly reflect "working state only"

---

# Chunk 3 — Wire runtime lineage attrs + move callback observability out of state

**Commit message:** `wire lineage attrs and move callback observability to agent metadata`

### Files

* `rlm_adk/agent.py`
* `rlm_adk/orchestrator.py`
* `rlm_adk/callbacks/reasoning.py`
* `rlm_adk/plugins/observability.py`

### Rationale for merging attr wiring with callback changes

The callbacks in `reasoning.py` read `_rlm_fanout_idx`, `_rlm_parent_depth`, `_rlm_output_schema_name` etc. from agent attrs via `getattr`. If we change the callbacks before the orchestrator sets those attrs, there is a regression window where `LineageEnvelope` objects have incomplete data. Merging these into one commit eliminates the gap.

### Edit in `agent.py`

No architectural changes to factory behavior. Only ensure child orchestrators supply:

* `depth`
* `fanout_idx`
* parent scope

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
* `_rlm_base_lineage = None`

### Edit in `callbacks/reasoning.py`

Keep the existing instruction merge behavior in `reasoning_before_model()`.

Replace state-writing observability with agent-local metadata:

#### `reasoning_before_model()`

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

Use `getattr(agent, '_rlm_fanout_idx', None)` with defaults throughout — callbacks are defensive since they fire for all agents.

#### `reasoning_after_model()`

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

### Edit in `plugins/observability.py`

Update `ObservabilityPlugin.after_model_callback()` to read `prompt_chars` and `system_chars` from `agent._rlm_pending_request_meta` instead of state keys `REASONING_PROMPT_CHARS`, `REASONING_SYSTEM_CHARS`, `CONTEXT_WINDOW_SNAPSHOT`.

This prevents the per-iteration breakdown from losing prompt char data.

### Required helper additions

Add internal helpers in `reasoning.py`:

* `_agent_runtime(callback_context)` — docstring should note `inv.branch` and `inv.invocation_id` are private ADK attributes
* `_build_lineage(callback_context)`

### Done when

* every reasoning agent instance can build lineage without reading session state
* root and child agents both carry explicit runtime scope
* canonical callbacks no longer require session state for response observability
* `llm_response.custom_metadata` contains JSON-serializable `rlm` lineage payload
* ObservabilityPlugin per-iteration breakdown still populates correctly

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

* keep `agent._structured_result = tool_response` (via `object.__setattr__`)
* create `CompletionEnvelope(terminal=True, mode="structured", ...)`
* set `agent._rlm_terminal_completion` (via `object.__setattr__`)
* update or create `agent._rlm_lineage_status` (via `_set_lineage_status` helper using `object.__setattr__`)

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

* `_set_lineage_status(agent, **updates)` — **must use `object.__setattr__()` since agent is a Pydantic LlmAgent**

### Import

```python
from rlm_adk.types import CompletionEnvelope, render_completion_text
```

### Reasoning summary extraction

Extract `reasoning_summary` safely — only call `.get("reasoning_summary")` when `tool_response` is a `dict`:

```python
rs = tool_response.get("reasoning_summary", "") if isinstance(tool_response, dict) else ""
```

### Do not change

* `_patch_output_schema_postprocessor()`
* the `_SET_MODEL_RESPONSE_TOOL_NAME` guard
* retry payload detection

### Done when

* terminal completion is created at structured-output success time
* orchestrator no longer needs session-state reasoning keys to know a child/root finished structurally
* all `_rlm_*` attrs set via `object.__setattr__()`

---

# Chunk 5 — Simplify orchestrator completion collection

**Commit message:** `orchestrator finalizes from completion envelope`

### Files

* `rlm_adk/orchestrator.py`

### Edit

Replace `_collect_reasoning_completion()` with a new helper centered on `CompletionEnvelope`.

Suggested new helper:

* `_collect_completion(...)`

### Priority order

1. `reasoning_agent._rlm_terminal_completion`
2. fallback from `output_key` — derive `finish_reason` from `reasoning_agent._rlm_last_response_meta["finish_reason"]`, NOT from session state
3. fallback from plain-text response candidate if available
4. synthesize terminal error envelope

### Also change final state writes

At the end of `_run_async_impl`, emit only:

* `depth_key(FINAL_RESPONSE_TEXT, self.depth)` — depth-scoped via `depth_key()` at all depths
* `depth_key(SHOULD_STOP, self.depth)`

Remove emission of:

* `REASONING_RAW_OUTPUT`
* `REASONING_PARSED_OUTPUT`
* `REASONING_SUMMARY`
* other reasoning observability state deltas as part of finalization

### Set `_rlm_terminal_completion` on the orchestrator

After collecting completion, set on `self`:

```python
object.__setattr__(self, "_rlm_terminal_completion", completion)
```

Delete the old `_rlm_completion: dict` pattern.

### Also change artifact save

`save_final_answer()` should receive the rendered `completion.display_text` (still a string).

If `save_final_answer()` in `artifacts.py` needs signature changes, add `rlm_adk/artifacts.py` to the file list.

### Done when

* orchestrator completion does not depend on response observability state keys
* terminal structured output and fallback text paths both still work
* final emitted text is deterministic
* `_rlm_completion` (dict) is no longer set — replaced by `_rlm_terminal_completion` (CompletionEnvelope)

---

# Chunk 6 — Stop propagating child lineage through parent state + Make SQLite authoritative lineage sink

**Commit message:** `remove child lineage state mirroring, persist lineage in sqlite`

### Rationale for merging dispatch cleanup with SQLite

If we delete the state transport in dispatch (Chunk 7 in v1) without simultaneously updating the SQLite tracer, there is a silent data loss window where child lineage disappears from telemetry. Merging these into one commit eliminates the gap.

### Files

* `rlm_adk/dispatch.py`
* `rlm_adk/plugins/sqlite_tracing.py`

### Edit in `dispatch.py`

Delete lineage transport through state.

Specifically remove:

* `_CHILD_PROPAGATION_KEYS`
* `_acc_child_depth_state`
* propagation loop that copies child depth-scoped keys into parent delta
* merging `_acc_child_depth_state` into `flush_fn()` delta

Keep:

* child orchestration
* semaphore control
* `LLMResult` construction
* optional parent skill-instruction restoration

Rename: `flush_fn()` → `post_dispatch_state_patch_fn()`

**All call sites to update:**
1. Function definition inside `create_dispatch_closures`
2. `return` tuple (third element)
3. `orchestrator.py` unpacking
4. `REPLTool.__init__` parameter name
5. `orchestrator.py` `REPLTool(...)` constructor call keyword arg

Keep it minimal:

```python
def post_dispatch_state_patch_fn() -> dict[str, Any]:
    delta = {}
    if _parent_skill_instruction is not None:
        delta[DYN_SKILL_INSTRUCTION] = _parent_skill_instruction
    return delta
```

### Change `_read_child_completion()` in `dispatch.py`

Rewrite using `_rlm_terminal_completion` as the first-class source:

1. `child._rlm_terminal_completion` (CompletionEnvelope on orchestrator)
2. `child.reasoning_agent._rlm_terminal_completion` (CompletionEnvelope on reasoning agent)
3. fallback to `_structured_result`
4. fallback to `output_key`
5. error

**Do not** read `REASONING_PARSED_OUTPUT`, `REASONING_RAW_OUTPUT`, `REASONING_VISIBLE_OUTPUT_TEXT`, `REASONING_THOUGHT_TEXT`, `REASONING_INPUT_TOKENS`, `REASONING_OUTPUT_TOKENS`, or `REASONING_FINISH_REASON` from `child_state` or `shared_state`.

### Change `_run_child()` in `dispatch.py`

```python
completion = getattr(child, "_rlm_terminal_completion", None)
if completion is None:
    completion = getattr(child.reasoning_agent, "_rlm_terminal_completion", None)

if isinstance(completion, CompletionEnvelope):
    answer = completion.display_text
    parsed_payload = completion.validated_output if isinstance(completion.validated_output, dict) else None
    raw_payload = completion.raw_output
    is_error = completion.error
    error_category = completion.error_category
else:
    ... fallback logic ...
```

### Edit in `sqlite_tracing.py`

#### Schema migration

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

#### `before_model_callback()`

Stop depending on `CONTEXT_WINDOW_SNAPSHOT` in state. Compute request-side metrics directly from `llm_request` and agent attrs.

**Guard all `_rlm_*` attr reads with `getattr(agent, '_rlm_depth', None)`** — the plugin fires for all agents, not just reasoning agents.

Populate:

* depth
* fanout
* parent scope
* output schema name
* prompt/system char counts
* branch
* session/invocation identifiers

#### `after_model_callback()`

Parse `llm_response.custom_metadata.get("rlm")` and persist it directly.

#### `before_tool_callback()` / `after_tool_callback()`

Persist actual tool decision.

For `set_model_response`, read `_rlm_lineage_status` from `tool_context._invocation_context.agent`:

```python
agent = tool_context._invocation_context.agent
lineage_status = getattr(agent, "_rlm_lineage_status", None) or {}

if tool.name == "set_model_response":
    update_kwargs["decision_mode"] = "set_model_response"
    update_kwargs["structured_outcome"] = lineage_status.get("structured_outcome")
    update_kwargs["terminal_completion"] = int(bool(lineage_status.get("terminal")))
    update_kwargs["validated_output_json"] = json.dumps(tool_response, default=str)
elif tool.name == "execute_code":
    update_kwargs["decision_mode"] = "execute_code"
```

#### Reduce `session_state_events`

Update `_CURATED_EXACT` to working-state keys only:

```python
_CURATED_EXACT = frozenset({
    CURRENT_DEPTH,
    ITERATION_COUNT,
    SHOULD_STOP,
    FINAL_RESPONSE_TEXT,
    LAST_REPL_RESULT,
    DYN_SKILL_INSTRUCTION,
})
```

Remove `REASONING_*` keys from curated capture. Narrow or remove broad `"obs:"` prefix.

### Done when

* child sibling lineage no longer travels through parent state
* dispatch is no longer a telemetry mirror layer
* state patching is minimal and explicitly working-state only
* `_read_child_completion()` uses `_rlm_terminal_completion` as primary source
* lineage can be reconstructed from telemetry rows alone
* session-state events are no longer needed to understand structured-output completion or child scope

---

# Chunk 7 — Update REPL tool to use minimal post-dispatch patching

**Commit message:** `repl tool applies minimal post dispatch state patch`

### Files

* `rlm_adk/tools/repl_tool.py`

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

# Chunk 8 — Trim `ObservabilityPlugin` down to summary-only state

**Commit message:** `remove lineage persistence from observability plugin`

### Files

* `rlm_adk/plugins/observability.py`

### Edit

Delete or reduce any plugin logic that writes model-call lineage into state and then re-persists it through `after_agent_callback`.

Specifically delete the `_EPHEMERAL_FIXED_KEYS` workaround. This is safe because Chunk 6 already updated `SqliteTracingPlugin.before_model_callback` to compute prompt/system chars directly from `llm_request` and agent attrs.

### Remove dependence on

* `CONTEXT_WINDOW_SNAPSHOT`
* `REASONING_PROMPT_CHARS` / `REASONING_SYSTEM_CHARS`
* per-call token/state persistence solely for tracer visibility

### Keep only if useful

* lightweight run summary counters in state
* tool invocation summary if you still want it exposed to agent logic

### Done when

* there is no duplicate lineage path in both SQLite telemetry and session state
* plugin no longer depends on ephemeral plugin-callback state workaround for core observability
* `_EPHEMERAL_FIXED_KEYS` workaround is removed

---

# Chunk 9 — Slim `_rlm_state` and REPL state exposure

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
* step mode (`STEP_MODE_ENABLED` — no change)
* max depth/max iterations
* `LAST_REPL_RESULT`
* `SHOULD_STOP`
* maybe `FINAL_RESPONSE_TEXT` if useful

Remove:

* lineage-heavy `obs:*`
* response raw/parsed/tokens/thought fields
* child summary payloads

Step-mode confirmation: `STEP_MODE_ENABLED` remains in `EXPOSED_STATE_KEYS` unchanged. `STEP_MODE_PAUSED_AGENT`, `STEP_MODE_PAUSED_DEPTH`, `STEP_MODE_ADVANCE_COUNT` are not added to `EXPOSED_STATE_KEYS` (the REPL should not need to read pause state). None of the step-mode keys are removed from `state.py`.

### Done when

* the REPL has working-state introspection
* but lineage lives outside shared session state
* `_rlm_state` does not contain `obs:child_*` or `reasoning_input_tokens` keys

---

# Chunk 10 — Rewrite tests around the new contract

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
* use `object.__setattr__` to read `agent._rlm_terminal_completion` in assertions, following the existing mock pattern in `test_fmea_e2e.py`

#### State minimization

* session state does not require reasoning raw/parsed/tokens/visible/thought lineage keys
* child sibling lineage is absent from parent session-state transport

#### `post_dispatch_state_patch_fn` contract

* after child dispatch, flushed delta contains only `DYN_SKILL_INSTRUCTION` (when instruction router is set) or empty dict (when not set)
* no `obs:child_*` or `reasoning_*` lineage keys in the delta

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

# Chunk 11 — Update docs to match the new architecture

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
* `_rlm_lineage_status` flows into SQLite via tool callbacks directly, not via `custom_metadata`

### Active removal

Remove any wording that implies `flush_fn`, `state_delta`, or depth-scoped `reasoning_*` keys are the authoritative lineage transport for child calls.

### Done when

* the three docs files do not contain text implying `flush_fn`, `state_delta`, or depth-scoped `reasoning_*` keys are the authoritative lineage transport for child calls
* docs match code behavior

---

# Recommended execution order

Run the chunks in this exact order:

1. Chunk 1 — types (CompletionEnvelope, LineageEnvelope, render_completion_text)
2. Chunk 2 — state rename (FINAL_ANSWER → FINAL_RESPONSE_TEXT, add constant)
3. Chunk 3 — wire attrs + callbacks + ObservabilityPlugin prompt char migration
4. Chunk 4 — worker_retry terminal completion
5. Chunk 5 — orchestrator completion simplification
6. Chunk 6 — dispatch cleanup + SQLite lineage sink (merged to prevent data loss window)
7. Chunk 7 — REPL tool minimal patching
8. Chunk 8 — ObservabilityPlugin trim
9. Chunk 9 — REPL state exposure slim
10. Chunk 10 — tests
11. Chunk 11 — docs

### Rationale for ordering changes from v1

The v1 ordering deferred Chunk 2 (state rename) to position 10, but Chunk 5/6 need `FINAL_RESPONSE_TEXT` to be importable. Moving it to position 2 (additive rename) eliminates import errors.

The v1 ordering had Chunk 3 (callbacks) at position 2 and Chunk 5 (attr wiring) at position 4, creating a window where callbacks read uninitialized attrs. Merging attr wiring into Chunk 3 eliminates this regression window.

The v1 ordering had dispatch cleanup (Chunk 7) at position 6 and SQLite (Chunk 9) at position 8, creating a silent data loss window for child lineage. Merging them into Chunk 6 eliminates the gap.

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
* `_rlm_terminal_completion` is the unified completion attr on both reasoning agents and orchestrators
* `_rlm_lineage_status` feeds into SQLite telemetry via tool callbacks
* step-mode functionality is preserved unchanged
* `post_dispatch_state_patch_fn` emits only working-state restoration (no lineage keys)

---

# Revision block — v2 changes from v1

Applied targeted fixes based on cross-document review against REFACTOR.md and codebase verification.

## Critical ordering fixes

| # | Issue | Fix applied |
|---|-------|-------------|
| C-01 | Chunk 2 deferred to position 10 — `FINAL_RESPONSE_TEXT` symbol missing when Chunk 6 needs it | Moved Chunk 2 to position 2 (immediately after Chunk 1). Additive rename runs first so downstream chunks can import. |
| C-02 | Chunk 3 (position 2) reads `_rlm_fanout_idx` etc. that Chunk 5 (position 4) hasn't written yet | Merged v1 Chunk 5 (attr wiring in orchestrator/agent) into Chunk 3. One commit, no regression window. |
| C-03 | Chunk 7 (dispatch cleanup) kills state transport → silent data loss until Chunk 9 (SQLite) catches up | Merged v1 Chunk 7 (dispatch) and v1 Chunk 9 (SQLite) into single Chunk 6. No telemetry gap. |
| C-04 | Chunk 7 "Done when" didn't require `_read_child_completion()` to stop preferring state-sourced values | Chunk 6 now explicitly requires `_read_child_completion()` to use `_rlm_terminal_completion` as primary source with 5-item priority order. State keys listed that must not be read. |

## Important detail fixes

| # | Issue | Fix applied |
|---|-------|-------------|
| I-05 | Chunk 4 `_set_lineage_status` missing `object.__setattr__` for Pydantic agents | Added to invariants section and Chunk 4 helper spec |
| I-06 | `_rlm_base_lineage` missing from Chunk 5 zero-init list | Added to Chunk 3 (merged) attr initialization |
| I-07 | Chunk 2 "Done when" criteria unreachable / missed hardcoded string literals | Fixed: criteria now include sqlite_tracing.py string literal grep |
| I-08 | Chunk 8 `flush_fn` rename doesn't list `orchestrator.py` call site | Chunk 6 now lists all 5 call sites |
| I-09 | `REASONING_PROMPT_CHARS`/`REASONING_SYSTEM_CHARS`/`REASONING_SUMMARY` missing from deprecation lists | Added to Chunk 2 deprecation list |
| I-10 | `child._rlm_completion` type change from dict to CompletionEnvelope not clarified | Unified: `_rlm_terminal_completion: CompletionEnvelope` everywhere. Legacy `_rlm_completion: dict` deleted. Added to invariants. |
| I-11 | Step-mode state mentioned in REFACTOR but zero chunks address it | Added explicit step-mode preservation note to invariants, Chunk 2, Chunk 9, and acceptance checklist |
| I-12 | Chunk 3 "Done when" breaks ObservabilityPlugin breakdown for 4 positions | ObservabilityPlugin prompt char migration merged into Chunk 3 scope |
| I-13 | SQLite `before_model_callback` needs `getattr` guard for non-reasoning agents | Added to Chunk 6 spec |
| I-14 | Chunk 6 mentions `save_final_answer()` but `artifacts.py` missing from files | Added note in Chunk 5 to include `artifacts.py` if signature changes |
| I-15 | Chunk 12 tests need `object.__setattr__` guidance | Added to Chunk 10 completion envelope test section |

## Structural changes

- v1 had 13 chunks; v2 has 11 chunks (two merges)
- v1 Chunk 5 (attr wiring) merged into v2 Chunk 3 (callbacks)
- v1 Chunk 7 (dispatch) + v1 Chunk 9 (SQLite) merged into v2 Chunk 6
- v1 Chunks 8, 10, 11, 12, 13 renumbered to v2 Chunks 7, 8, 9, 10, 11
- Execution order simplified: 1→2→3→4→5→6→7→8→9→10→11 (linear, no reordering needed)
- Added `post_dispatch_state_patch_fn` contract test to Chunk 10
- Added unified completion naming to invariants and acceptance checklist
