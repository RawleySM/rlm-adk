Here's the file-by-file implementation checklist I'd hand to a coding agent.

The target state is:

* **session state = working/control plane only**
* **`LlmResponse.custom_metadata` + SQLite telemetry = lineage plane**
* **agent-local `CompletionEnvelope` = completion plane**

This keeps your current "one reasoning loop, two tools" architecture intact: each reasoning step can still choose either `execute_code` or `set_model_response`, and structured output remains the terminal path when validation succeeds. The orchestrator already wires those two tools manually, and the retry logic is already scoped to `set_model_response`, which is exactly the seam we want to preserve.

## Non-negotiable design rules

1. **Do not add a terminal boolean into arbitrary child schemas.**
   Successful `set_model_response` is already the terminal signal.

2. **Do not use session state as the default transport for lineage.**
   Only put values in state if the runtime needs them for control, prompt templating, or REPL continuity.

3. **Do not break the collapsed orchestrator loop.**
   Keep:

   * model call
   * tool choice
   * retry on `set_model_response`
   * final normalization in orchestrator

4. **No backward-compatibility preservation unless it directly protects runtime behavior.**
   This refactor is allowed to prune stale keys and simplify docs/tests.

5. **Unify completion naming.** After this refactor, the canonical completion attr is `_rlm_terminal_completion: CompletionEnvelope` on both the reasoning agent (set by `after_tool_cb`) and the orchestrator (copied from reasoning agent in finalization). The legacy `_rlm_completion: dict` is deleted. All lookups use `_rlm_terminal_completion`.

6. **`_rlm_lineage_status` flows into SQLite via tool callbacks directly**, not via `custom_metadata`. The timing is: `reasoning_after_model` builds a base `LineageEnvelope` into `custom_metadata["rlm"]` with `decision_mode="unknown"`. The SQLite tracer's `after_tool_callback` reads `_rlm_lineage_status` from the agent and updates the telemetry row directly. This two-phase pattern exists because `llm_response` is not available in tool callbacks.

---

# Implementation sequence

Do this in order.

## 1) `rlm_adk/types.py`

### Goal

Introduce explicit runtime objects for completion and lineage so the rest of the code stops reverse-engineering completion from session state, output keys, and callback side effects.

### Add

* `CompletionEnvelope`
* `LineageEnvelope`
* a deterministic text renderer for final user-visible output

### Pseudocode patch

```python
import json
from typing import Any, Literal
from pydantic import BaseModel, Field

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

def render_completion_text(validated_output: Any, fallback_text: str = "") -> str:
    """Deterministic renderer for final user-visible text.

    Requires `import json` — already present in types.py.
    """
    if isinstance(validated_output, dict):
        fa = validated_output.get("final_answer")
        if isinstance(fa, str) and fa.strip():
            return fa
        return json.dumps(validated_output, sort_keys=True)
    if isinstance(validated_output, str):
        return validated_output
    if validated_output is not None:
        return json.dumps(validated_output, sort_keys=True, default=str)
    return fallback_text
```

### Also change

Leave `ReasoningOutput` as-is for the root default flow. It remains content schema, not control schema.

---

## 2) `rlm_adk/state.py`

### Goal

Shrink the state surface.

### Keep

Control and working keys only:

* `APP_MAX_DEPTH`
* `APP_MAX_ITERATIONS`
* `CURRENT_DEPTH`
* `ITERATION_COUNT`
* `SHOULD_STOP`
* prompt/template keys
* user context keys
* `LAST_REPL_RESULT`
* step-mode keys (`STEP_MODE_ENABLED`, `STEP_MODE_PAUSED_AGENT`, `STEP_MODE_PAUSED_DEPTH`, `STEP_MODE_ADVANCE_COUNT`) — unchanged
* root final rendered response text

### Change

Rename:

* `FINAL_ANSWER` → `FINAL_RESPONSE_TEXT`

### Remove from authoritative use

These should no longer be required by runtime logic:

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
* child summary state transport keys as a design pattern

You can keep constants temporarily during migration, but the end-state should stop relying on them. Right now those keys are heavily tied to callback/state-delta telemetry and SQLite session-state events, which is exactly what we are removing as the primary lineage carrier.

### Add

`FINAL_RESPONSE_TEXT = "final_response_text"` — add this constant immediately so downstream chunks can import it.

### Pseudocode patch

```python
FINAL_RESPONSE_TEXT = "final_response_text"

EXPOSED_STATE_KEYS = frozenset({
    ITERATION_COUNT,
    CURRENT_DEPTH,
    APP_MAX_ITERATIONS,
    APP_MAX_DEPTH,
    LAST_REPL_RESULT,
    STEP_MODE_ENABLED,
    SHOULD_STOP,
    FINAL_RESPONSE_TEXT,
})
```

**Note:** This removes `obs:child_dispatch_count`, `obs:total_input_tokens`, and other `obs:*` keys from REPL introspection (`_rlm_state`). This is a breaking change for any existing REPL code that reads those counters for control flow. The REPL should not need lineage data for reasoning.

### Concrete edits required

* Update `EXPOSED_STATE_KEYS`
* Update `DEPTH_SCOPED_KEYS` so only keys still required for runtime continuity remain
* Update all `depth_key(FINAL_ANSWER, ...)` callsites to `depth_key(FINAL_RESPONSE_TEXT, ...)`
* Grep for string literal `"final_answer"` in `sqlite_tracing.py` `_CURATED_EXACT` and `_categorize_key` — update those too

### Done when

* project imports cleanly
* grep shows no writes to `FINAL_ANSWER` (Python symbol) or `"final_answer"` string literal in state writes
* `FINAL_RESPONSE_TEXT` constant is importable from `state.py`
* state constants now clearly reflect "working state only"
* step-mode constants are unchanged

---

## 3) `rlm_adk/callbacks/reasoning.py`

### Goal

Convert canonical callbacks from "write response observability into session state" to "build lineage and agent-local request/response metadata."

### Current problem

`reasoning_before_model()` and `reasoning_after_model()` currently write prompt/system counts, visible text, thought text, finish reason, and token counts into session state. That is the old architecture.

### New behavior

#### `reasoning_before_model()`

* keep the instruction merge behavior
* stop writing observability into state
* compute request-side metadata and stash it on the agent:

  * prompt chars
  * system chars
  * content count
  * output schema name
  * depth/fanout/parent lineage scope

**Important:** Use `getattr(agent, '_rlm_fanout_idx', None)` with defaults throughout. These attrs are initialized by the orchestrator (step 5), but callbacks must be defensive since they fire for all agents and attrs may not yet be set during the transition.

#### `reasoning_after_model()`

* compute visible/thought text and usage counts
* create/update a `LineageEnvelope`
* attach it to `llm_response.custom_metadata["rlm"]`
* store lightweight response meta on the agent, not in state

**Also update `ObservabilityPlugin.after_model_callback()`** to read from `_rlm_pending_request_meta` on the agent instead of `CONTEXT_WINDOW_SNAPSHOT`/`REASONING_PROMPT_CHARS`/`REASONING_SYSTEM_CHARS` from state. This prevents the regression window where ObservabilityPlugin's per-iteration breakdown loses prompt char data between this chunk and the ObservabilityPlugin trim chunk.

### Pseudocode patch

```python
from rlm_adk.types import LineageEnvelope

def _agent_runtime(callback_context):
    """Extract invocation context and agent. inv.branch and inv.invocation_id
    are private ADK attributes — access via getattr with None default,
    same pattern as _reasoning_depth."""
    inv = callback_context._invocation_context
    agent = inv.agent
    return inv, agent

def _build_lineage(callback_context) -> LineageEnvelope:
    inv, agent = _agent_runtime(callback_context)
    return LineageEnvelope(
        agent_name=getattr(agent, "name", "unknown"),
        depth=getattr(agent, "_rlm_depth", 0),
        fanout_idx=getattr(agent, "_rlm_fanout_idx", None),
        parent_depth=getattr(agent, "_rlm_parent_depth", None),
        parent_fanout_idx=getattr(agent, "_rlm_parent_fanout_idx", None),
        branch=getattr(inv, "branch", None),
        invocation_id=getattr(inv, "invocation_id", None),
        session_id=getattr(getattr(inv, "session", None), "id", None),
        output_schema_name=getattr(agent, "_rlm_output_schema_name", None),
    )

def reasoning_before_model(callback_context, llm_request):
    # existing instruction merge stays
    ...
    inv, agent = _agent_runtime(callback_context)
    request_meta = {
        "prompt_chars": total_prompt_chars,
        "system_chars": system_chars,
        "content_count": len(contents),
        "lineage": _build_lineage(callback_context).model_dump(),
    }
    object.__setattr__(agent, "_rlm_pending_request_meta", request_meta)
    return None

def reasoning_after_model(callback_context, llm_response):
    inv, agent = _agent_runtime(callback_context)
    visible_text, thought_text = _extract_response_text(llm_response)
    lineage = _build_lineage(callback_context)
    meta = dict(llm_response.custom_metadata or {})
    meta["rlm"] = lineage.model_dump()
    llm_response.custom_metadata = meta

    response_meta = {
        "visible_text": visible_text,
        "thought_text": thought_text,
        "finish_reason": ...,
        "input_tokens": ...,
        "output_tokens": ...,
        "thought_tokens": ...,
        "custom_metadata": meta,
    }
    object.__setattr__(agent, "_rlm_last_response_meta", response_meta)
    return None
```

### Done when

* canonical callbacks no longer write reasoning observability into session state
* `llm_response.custom_metadata` contains JSON-serializable `rlm` lineage payload
* no state delta is required for lineage in model callbacks
* `ObservabilityPlugin.after_model_callback()` reads prompt chars from `_rlm_pending_request_meta` instead of state

---

## 4) `rlm_adk/callbacks/worker_retry.py`

### Goal

Make successful `set_model_response` the authoritative completion event.

### Current behavior

This file already owns:

* successful validated structured result capture
* retry request emission
* retry exhaustion tracking
* BUG-13 suppression for retry continuation.

### New behavior

When `set_model_response` validates successfully:

* set `agent._structured_result`
* set `agent._rlm_terminal_completion = CompletionEnvelope(...)`
* set/update `agent._rlm_lineage_status`

When retry is requested:

* update lineage status only

When retries exhaust:

* create error `CompletionEnvelope`

### Pseudocode patch

```python
from rlm_adk.types import CompletionEnvelope, render_completion_text

def _set_lineage_status(agent, **updates):
    """Use object.__setattr__ — agent is a Pydantic LlmAgent model."""
    state = getattr(agent, "_rlm_lineage_status", {}) or {}
    state.update(updates)
    object.__setattr__(agent, "_rlm_lineage_status", state)

async def after_tool_cb(tool, args, tool_context, tool_response):
    result = await plugin.after_tool_callback(...)
    if tool.name == "set_model_response":
        agent = tool_context._invocation_context.agent
        is_retry_payload = ...
        if is_retry_payload:
            _set_lineage_status(agent, decision_mode="set_model_response",
                                structured_outcome="retry_requested",
                                terminal=False)
            return result

        if isinstance(tool_response, dict) and result is None:
            object.__setattr__(agent, "_structured_result", tool_response)
            # Extract reasoning_summary safely — only valid for dict payloads
            rs = tool_response.get("reasoning_summary", "") if isinstance(tool_response, dict) else ""
            object.__setattr__(agent, "_rlm_terminal_completion",
                CompletionEnvelope(
                    terminal=True,
                    mode="structured",
                    output_schema_name=getattr(agent, "_rlm_output_schema_name", None),
                    validated_output=tool_response,
                    raw_output=tool_response,
                    display_text=render_completion_text(tool_response),
                    reasoning_summary=str(rs or ""),
                    error=False,
                )
            )
            _set_lineage_status(agent, decision_mode="set_model_response",
                                structured_outcome="validated",
                                terminal=True)
    return result

async def on_tool_error_cb(tool, args, tool_context, error):
    ...
    if tool.name == "set_model_response":
        agent = tool_context._invocation_context.agent
        _set_lineage_status(agent, decision_mode="set_model_response",
                            structured_outcome="retry_requested",
                            terminal=False)
```

On exhaustion paths, set:

```python
object.__setattr__(agent, "_rlm_terminal_completion",
    CompletionEnvelope(
        terminal=True,
        mode="error",
        error=True,
        error_category="SCHEMA_VALIDATION_EXHAUSTED",
        display_text="..."
    )
)
```

### Done when

* terminal completion is created at structured-output success time
* orchestrator no longer needs session-state reasoning keys to know a child/root finished structurally
* all `_rlm_*` attrs set via `object.__setattr__()` (Pydantic model constraint)

---

## 5) `rlm_adk/agent.py` + `rlm_adk/orchestrator.py`

### Goal

Wire runtime lineage attrs onto reasoning agents and simplify orchestrator completion.

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

#### Wire runtime attrs

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

#### Replace `_collect_reasoning_completion()` with `_collect_completion()`

Use priority order:

1. `reasoning_agent._rlm_terminal_completion` (a `CompletionEnvelope`)
2. fallback from `output_key` — parse via `parse_reasoning_output()`, derive `finish_reason` from `reasoning_agent._rlm_last_response_meta["finish_reason"]` (not from state)
3. fallback from plain-text response candidate if available
4. synthesize terminal error envelope

**Important:** The fallback `CompletionEnvelope` must populate `finish_reason` from `reasoning_agent._rlm_last_response_meta`, not from session state (which no longer carries `REASONING_FINISH_REASON`). This preserves the `_infer_completion_error` logic for compliance finish reasons like `"SAFETY"` and `"RECITATION"`.

#### End-of-run state writes

Emit only:

* `depth_key(FINAL_RESPONSE_TEXT, self.depth)` — depth-scoped via `depth_key()` at all depths (required for child orchestrators to write isolated keys like `final_response_text@d1`)
* `depth_key(SHOULD_STOP, self.depth)`

Remove emission of:

* `REASONING_RAW_OUTPUT`
* `REASONING_PARSED_OUTPUT`
* `REASONING_SUMMARY`
* other reasoning observability state deltas as part of finalization

#### Set `_rlm_terminal_completion` on the orchestrator itself

After collecting completion, copy it onto `self`:

```python
object.__setattr__(self, "_rlm_terminal_completion", completion)
```

This replaces the old `_rlm_completion: dict` pattern. The canonical attr is now `_rlm_terminal_completion: CompletionEnvelope` on both reasoning agent and orchestrator.

#### Artifact save

`save_final_answer()` should receive `completion.display_text` (still a string — same call signature as today).

### Pseudocode patch

```python
from rlm_adk.types import CompletionEnvelope, render_completion_text
from rlm_adk.state import FINAL_RESPONSE_TEXT

def _collect_completion(reasoning_agent, session_state, depth, output_schema):
    completion = getattr(reasoning_agent, "_rlm_terminal_completion", None)
    if completion is not None:
        return completion

    # Fallback: read from output_key
    raw = session_state.get(reasoning_agent.output_key or "reasoning_output")
    if raw is not None:
        payload = parse_reasoning_output(raw)
        # Get finish_reason from agent-local meta, not from state
        response_meta = getattr(reasoning_agent, "_rlm_last_response_meta", {}) or {}
        return CompletionEnvelope(
            terminal=True,
            mode="structured" if payload.parsed_output is not None else "text",
            output_schema_name=getattr(reasoning_agent, "_rlm_output_schema_name", None),
            validated_output=payload.parsed_output,
            raw_output=payload.raw_output,
            display_text=render_completion_text(payload.parsed_output, payload.final_answer),
            reasoning_summary=payload.reasoning_summary,
            finish_reason=response_meta.get("finish_reason"),
            error=False,
        )

    return CompletionEnvelope(
        terminal=True,
        mode="error",
        display_text="[RLM ERROR] Reasoning agent completed without producing a final response.",
        error=True,
        error_category="NO_RESULT",
    )
```

Final event patch:

```python
yield Event(
    ...,
    actions=EventActions(state_delta={
        depth_key(FINAL_RESPONSE_TEXT, self.depth): completion.display_text,
        depth_key(SHOULD_STOP, self.depth): True,
    }),
)
```

### Done when

* every reasoning agent instance carries explicit runtime scope attrs
* root and child agents both carry `_rlm_terminal_completion`
* orchestrator completion does not depend on response observability state keys
* terminal structured output and fallback text paths both still work
* final emitted text is deterministic
* `_rlm_completion` (dict) is no longer set — replaced by `_rlm_terminal_completion` (CompletionEnvelope)

---

## 6) `rlm_adk/dispatch.py`

### Goal

Remove lineage transport through parent state and reduce flush to working-state patching.

### Remove

* `_CHILD_PROPAGATION_KEYS`
* `_acc_child_depth_state`
* propagation of child depth-scoped reasoning keys into parent flush delta
* `obs:child_summary@d{D}f{F}` as a required session-state transport
* merging `_acc_child_depth_state` into flush delta

Today this is the main artifact-like observability bus. It should go away.

### Keep

* child orchestration
* semaphores
* `LLMResult` return path
* parent skill instruction restoration if still necessary

### Rename

`flush_fn()` → `post_dispatch_state_patch_fn()`

**All four call sites that need updating:**
1. The function definition inside `create_dispatch_closures`
2. The `return` tuple at the end of `create_dispatch_closures` (third element)
3. `orchestrator.py` unpacking: `llm_query_async, llm_query_batched_async, post_dispatch_state_patch_fn = create_dispatch_closures(...)`
4. `REPLTool.__init__` parameter: `flush_fn` → `post_dispatch_state_patch_fn`
5. `orchestrator.py` `REPLTool(...)` constructor call: `post_dispatch_state_patch_fn=post_dispatch_state_patch_fn`

### Change `_read_child_completion()`

Rewrite to use `_rlm_terminal_completion` as the first-class source (REFACTOR §10):

1. `child._rlm_terminal_completion` (CompletionEnvelope on the orchestrator)
2. `child.reasoning_agent._rlm_terminal_completion` (CompletionEnvelope on reasoning agent)
3. fallback to `_structured_result`
4. fallback to `output_key`
5. error

**Do not** read `REASONING_PARSED_OUTPUT`, `REASONING_RAW_OUTPUT`, `REASONING_VISIBLE_OUTPUT_TEXT`, `REASONING_THOUGHT_TEXT`, `REASONING_INPUT_TOKENS`, `REASONING_OUTPUT_TOKENS`, or `REASONING_FINISH_REASON` from `child_state` or `shared_state`.

### Change `_run_child()`

Build `LLMResult` from `CompletionEnvelope`:

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

### Pseudocode for reduced `post_dispatch_state_patch_fn`

```python
def post_dispatch_state_patch_fn() -> dict[str, Any]:
    delta = {}
    if _parent_skill_instruction is not None:
        delta[DYN_SKILL_INSTRUCTION] = _parent_skill_instruction
    return delta
```

### Done when

* child sibling lineage no longer travels through parent state
* dispatch is no longer a telemetry mirror layer
* state patching is minimal and explicitly working-state only
* `_read_child_completion()` uses `_rlm_terminal_completion` as the primary source, not state-sourced values
* session state is not consulted for `REASONING_PARSED_OUTPUT` or `REASONING_RAW_OUTPUT` in `_read_child_completion()`

---

## 7) `rlm_adk/tools/repl_tool.py`

### Goal

Keep REPL continuity, stop acting as the telemetry dumping ground for child lineage.

### Keep

* submitted code observability
* AST rewrite observability if you still want it
* `LAST_REPL_RESULT`
* snapshot injection of `_rlm_state`

### Change

Rename constructor arg:

* `flush_fn` → `post_dispatch_state_patch_fn`

Inside `run_async()`:

* call the renamed function after code execution
* write only its returned minimal working-state patch into `tool_context.state`

Do not assume child lineage or structured-output details arrive through this patch anymore.

### Pseudocode patch

```python
delta = post_dispatch_state_patch_fn() if post_dispatch_state_patch_fn else {}
for key, value in delta.items():
    tool_context.state[key] = value
```

No child reasoning raw/parsed/visible/thought mirror keys.

### Done when

* REPL tool still supports child dispatch
* but no longer acts as the main lineage transport layer

---

## 8) `rlm_adk/plugins/sqlite_tracing.py`

### Goal

Make SQLite the authoritative lineage sink.

### Schema migration

Add columns to `telemetry`:

```sql
ALTER TABLE telemetry ADD COLUMN fanout_idx INTEGER;
ALTER TABLE telemetry ADD COLUMN parent_depth INTEGER;
ALTER TABLE telemetry ADD COLUMN parent_fanout_idx INTEGER;
ALTER TABLE telemetry ADD COLUMN branch TEXT;
ALTER TABLE telemetry ADD COLUMN invocation_id TEXT;
ALTER TABLE telemetry ADD COLUMN session_id TEXT;
ALTER TABLE telemetry ADD COLUMN output_schema_name TEXT;
ALTER TABLE telemetry ADD COLUMN decision_mode TEXT;
ALTER TABLE telemetry ADD COLUMN structured_outcome TEXT;
ALTER TABLE telemetry ADD COLUMN terminal_completion INTEGER;
ALTER TABLE telemetry ADD COLUMN custom_metadata_json TEXT;
ALTER TABLE telemetry ADD COLUMN validated_output_json TEXT;
```

### `before_model_callback()`

Stop using `CONTEXT_WINDOW_SNAPSHOT` from state as the source of request-side observability. Compute directly from `llm_request` and agent attrs.

**Guard all `_rlm_*` attr reads with `getattr(agent, '_rlm_depth', None)`** — the plugin fires for all agents (root orchestrator, reasoning agent, workers), not just reasoning agents.

### `after_model_callback()`

Persist:

* `custom_metadata_json`
* lineage fields from `llm_response.custom_metadata["rlm"]`

### `before_tool_callback()` / `after_tool_callback()`

Persist actual tool decision:

* `execute_code` → `decision_mode = "execute_code"`
* `set_model_response` → `decision_mode = "set_model_response"`

For `set_model_response`, also persist (reading from `agent._rlm_lineage_status` directly, since `llm_response` is not available in tool callbacks):

* `structured_outcome` from `_rlm_lineage_status`
* `terminal_completion` from `_rlm_lineage_status`
* `validated_output_json`

### Pseudocode patch

```python
def _extract_rlm_meta(llm_response):
    meta = getattr(llm_response, "custom_metadata", None) or {}
    rlm = meta.get("rlm")
    return rlm if isinstance(rlm, dict) else {}

async def after_model_callback(...):
    ...
    rlm = _extract_rlm_meta(llm_response)
    update_kwargs.update({
        "custom_metadata_json": json.dumps(llm_response.custom_metadata or {}, default=str),
        "fanout_idx": rlm.get("fanout_idx"),
        "parent_depth": rlm.get("parent_depth"),
        "parent_fanout_idx": rlm.get("parent_fanout_idx"),
        "branch": rlm.get("branch"),
        "invocation_id": rlm.get("invocation_id"),
        "session_id": rlm.get("session_id"),
        "output_schema_name": rlm.get("output_schema_name"),
        "decision_mode": rlm.get("decision_mode"),
        "structured_outcome": rlm.get("structured_outcome"),
        "terminal_completion": int(bool(rlm.get("terminal"))),
    })
```

Tool path — reads `_rlm_lineage_status` from agent:

```python
async def after_tool_callback(tool, tool_args, tool_context, tool_response):
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

### Reduce `session_state_events`

Update `_CURATED_EXACT` to keep only working-state keys:

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

Remove `REASONING_VISIBLE_OUTPUT_TEXT`, `REASONING_THOUGHT_TEXT`, `REASONING_RAW_OUTPUT`, `REASONING_PARSED_OUTPUT` from curated capture.

Reduce `_CURATED_PREFIXES` — remove or narrow the broad `"obs:"` prefix unless you want working-state obs counters in SSE.

### Done when

* lineage can be reconstructed from telemetry rows alone
* session-state events are no longer needed to understand structured-output completion or child scope
* `_rlm_lineage_status` is read directly from agent in tool callbacks
* `CONTEXT_WINDOW_SNAPSHOT` is not read from state

---

## 9) `rlm_adk/plugins/observability.py`

### Goal

Stop using state as a second lineage channel.

### Prerequisite

Step 3 must have already updated `ObservabilityPlugin.after_model_callback()` to read from `_rlm_pending_request_meta` instead of state. If step 3 was implemented as specified, this prerequisite is already met.

### Change

Either:

* reduce plugin to run-summary counters only
* or disable most per-call state writes entirely

### Specifically delete

The `_EPHEMERAL_FIXED_KEYS` workaround where plugin `after_model_callback` writes state and `after_agent_callback` re-persists it for event visibility. That was only necessary because state/event deltas were being used as the telemetry bus. After this refactor, they should not be. Your docs explicitly call out that workaround today.

**Note:** Removing the re-persistence of `CONTEXT_WINDOW_SNAPSHOT` is safe only because step 8 (SQLite tracing) already computes prompt/system chars directly from `llm_request` and agent attrs. This is a sequencing dependency.

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

## 10) Tests

### Rewrite/add

#### Structured output / terminality

* child `llm_query("...", output_schema=Schema)` returns parsed result via validated `set_model_response`
* no schema-level terminal bool is required
* `execute_code` does not set terminal completion

#### Completion envelope

* successful `set_model_response` creates `CompletionEnvelope(terminal=True, mode="structured")`
* retry exhaustion creates terminal error envelope
* use `object.__setattr__` to read `agent._rlm_terminal_completion` in assertions

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

## 11) Docs

Update:

* `rlm_adk_docs/core_loop.md`
* `rlm_adk_docs/dispatch_and_state.md`
* `rlm_adk_docs/observability.md`

### New wording to reflect

* session state is working memory/control plane
* lineage comes from `custom_metadata` + telemetry tables
* terminality comes from validated `set_model_response`
* `flush_fn` no longer exists as the main observability transport — renamed to `post_dispatch_state_patch_fn()` and exists only for working-state restoration
* `_rlm_lineage_status` flows into SQLite via tool callbacks directly, not via `custom_metadata`

### Active removal

Remove any wording that implies session-state deltas are the required carrier for child lineage or structured-output observability.

### Done when

* the three docs files do not contain text implying `flush_fn`, `state_delta`, or depth-scoped `reasoning_*` keys are the authoritative lineage transport for child calls
* docs match code behavior

---

# Acceptance criteria

The coding agent should consider the refactor done when all of this is true:

1. A child `llm_query(..., output_schema=...)` still works inside REPL-submitted code and still terminates through validated `set_model_response`.
2. The orchestrator emits only minimal working-state deltas at completion.
3. Session state no longer needs depth-scoped reasoning raw/parsed/tokens/visible/thought keys for correctness.
4. SQLite telemetry records lineage directly from callbacks and `custom_metadata`.
5. Child sibling lineage no longer risks overwriting through shared parent state transport.
6. No schema needs an `is_final` boolean.
7. The root still renders a final user-visible answer deterministically.
8. `_rlm_terminal_completion` is the unified completion attr on both reasoning agents and orchestrators.
9. `_rlm_lineage_status` feeds into SQLite telemetry via tool callbacks, not via `custom_metadata`.
10. Step-mode functionality is preserved unchanged.

---

# Revision block — v2 changes from v1

Applied targeted fixes based on cross-document review against REFACTOR.md and codebase verification.

## Critical fixes

| # | Issue | Fix applied |
|---|-------|-------------|
| W-01 | `_rlm_completion` (dict) vs `_rlm_terminal_completion` (CompletionEnvelope) naming split never reconciled | Added non-negotiable rule §5: unified naming to `_rlm_terminal_completion` everywhere. Step 5 now explicitly sets `_rlm_terminal_completion` on orchestrator, step 6 lookups use it. Legacy `_rlm_completion` deleted. |
| W-02 | REFACTOR §5 under-specifies `depth_key()` scoping for `FINAL_RESPONSE_TEXT` | Step 5 now explicitly states depth-scoped via `depth_key()` at all depths, required for child orchestrators |
| W-03 | `_rlm_lineage_status` set in tool callback but never flows into `LineageEnvelope` or SQLite — timing gap | Added non-negotiable rule §6: two-phase pattern. `reasoning_after_model` builds base `LineageEnvelope` with `decision_mode="unknown"`. SQLite tracer's `after_tool_callback` reads `_rlm_lineage_status` from agent directly. Step 8 pseudocode updated. |
| W-04 | `flush_fn` → `post_dispatch_state_patch_fn` rename ripple to caller sites not spelled out | Step 6 now lists all 5 call sites requiring update |
| W-05 | `_collect_completion` fallback reads `finish_reason` from state but state key is removed | Step 5 now sources `finish_reason` from `reasoning_agent._rlm_last_response_meta["finish_reason"]`. Preserves `_infer_completion_error` for compliance finish reasons. |

## Important fixes

| # | Issue | Fix applied |
|---|-------|-------------|
| W-06 | `EXPOSED_STATE_KEYS` reduction breaks REPL `_rlm_state` introspection for `obs:*` keys | Step 2 now includes explicit note about breaking change |
| W-07 | `inv.branch` and `inv.invocation_id` are private ADK APIs — not flagged | Step 3 `_agent_runtime` docstring now notes private API access pattern |
| W-08 | REFACTOR §10 (`_read_child_completion` rewrite) not a separate step in WORKFLOW | Step 6 now includes full `_read_child_completion()` rewrite spec with 5-item priority order and explicit list of state keys that must no longer be read |
| W-09 | SQLite `session_state_events` reduction missing concrete key lists | Step 8 now includes concrete `_CURATED_EXACT` and `_CURATED_PREFIXES` update targets |
| W-10 | ObservabilityPlugin `_EPHEMERAL_FIXED_KEYS` workaround has sequencing dependency on SQLite step | Step 9 now notes prerequisite and step 3 scope expanded to include ObservabilityPlugin prompt char read migration |
| W-11 | `after_tool_cb` pseudocode missing imports and unsafe `reasoning_summary` extraction | Step 4 pseudocode now includes imports and safe dict-guard for `reasoning_summary` |
| W-12 | No test for `post_dispatch_state_patch_fn` behavior contract | Step 10 now includes `post_dispatch_state_patch_fn` contract test |
| W-13 | `REASONING_SUMMARY` missing from removal lists | Step 2 removal list now includes `REASONING_SUMMARY` |
| W-14 | `render_completion_text` missing `import json` note | Step 1 pseudocode now includes `import json` and docstring note |
| W-15 | Docs step missing "Done when" criteria and active removal instruction | Step 11 now includes "Done when" criteria and active removal instruction |

## Structural changes

- Steps 5 and 6 from v1 merged into single step 5 (wire attrs + simplify completion collection) to prevent regression window where callbacks read uninitialized attrs
- ObservabilityPlugin prompt char migration added to step 3 scope to prevent per-iteration breakdown regression
- `_rlm_base_lineage = None` added to step 5 zero-initialization list
- Acceptance criteria expanded from 7 to 10 items
