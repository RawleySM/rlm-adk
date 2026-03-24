Here’s the file-by-file implementation checklist I’d hand to a coding agent.

The target state is:

* **session state = working/control plane only**
* **`LlmResponse.custom_metadata` + SQLite telemetry = lineage plane**
* **agent-local `CompletionEnvelope` = completion plane**

This keeps your current “one reasoning loop, two tools” architecture intact: each reasoning step can still choose either `execute_code` or `set_model_response`, and structured output remains the terminal path when validation succeeds. The orchestrator already wires those two tools manually, and the retry logic is already scoped to `set_model_response`, which is exactly the seam we want to preserve.   

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
* step-mode keys if still used
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
* child summary state transport keys as a design pattern

You can keep constants temporarily during migration, but the end-state should stop relying on them. Right now those keys are heavily tied to callback/state-delta telemetry and SQLite session-state events, which is exactly what we are removing as the primary lineage carrier.  

### Add

Optional helper for runtime-scoped lineage naming if needed, but prefer not to create new state keys for lineage.

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

---

## 3) `rlm_adk/callbacks/reasoning.py`

### Goal

Convert canonical callbacks from “write response observability into session state” to “build lineage and agent-local request/response metadata.”

### Current problem

`reasoning_before_model()` and `reasoning_after_model()` currently write prompt/system counts, visible text, thought text, finish reason, and token counts into session state. That is the old architecture. 

### New behavior

#### `reasoning_before_model`

* keep the instruction merge behavior
* stop writing observability into state
* compute request-side metadata and stash it on the agent:

  * prompt chars
  * system chars
  * content count
  * output schema name
  * depth/fanout/parent lineage scope

#### `reasoning_after_model`

* compute visible/thought text and usage counts
* create/update a `LineageEnvelope`
* attach it to `llm_response.custom_metadata["rlm"]`
* store lightweight response meta on the agent, not in state

### Pseudocode patch

```python
from rlm_adk.types import LineageEnvelope

def _agent_runtime(callback_context):
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
    object.__setattr__(agent, "_rlm_pending_request_meta", {
        "prompt_chars": total_prompt_chars,
        "system_chars": system_chars,
        "content_count": len(contents),
        "lineage": _build_lineage(callback_context).model_dump(),
    })
    return None

def reasoning_after_model(callback_context, llm_response):
    inv, agent = _agent_runtime(callback_context)
    visible_text, thought_text = _extract_response_text(llm_response)
    lineage = _build_lineage(callback_context)
    meta = dict(llm_response.custom_metadata or {})
    meta["rlm"] = lineage.model_dump()
    llm_response.custom_metadata = meta

    object.__setattr__(agent, "_rlm_last_response_meta", {
        "visible_text": visible_text,
        "thought_text": thought_text,
        "finish_reason": ...,
        "input_tokens": ...,
        "output_tokens": ...,
        "thought_tokens": ...,
        "custom_metadata": meta,
    })
    return None
```

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
from rlm_adk.types import CompletionEnvelope

def _set_lineage_status(agent, **updates):
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
            agent._structured_result = tool_response
            object.__setattr__(agent, "_rlm_terminal_completion",
                CompletionEnvelope(
                    terminal=True,
                    mode="structured",
                    output_schema_name=getattr(agent, "_rlm_output_schema_name", None),
                    validated_output=tool_response,
                    raw_output=tool_response,
                    display_text=render_completion_text(tool_response),
                    reasoning_summary=str(tool_response.get("reasoning_summary", "") or ""),
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
CompletionEnvelope(
    terminal=True,
    mode="error",
    error=True,
    error_category="SCHEMA_VALIDATION_EXHAUSTED",
    display_text="..."
)
```

---

## 5) `rlm_adk/orchestrator.py`

### Goal

Make orchestrator finalization read agent-local completion, not session-state telemetry.

### Current behavior

The orchestrator reconstructs completion via `_collect_reasoning_completion()` from:

* `output_key`
* `_structured_result`
* state keys for visible/thought/raw/parsed/tokens. 

### New behavior

#### When wiring the reasoning agent

Set runtime attrs:

```python
object.__setattr__(self.reasoning_agent, "_rlm_depth", self.depth)
object.__setattr__(self.reasoning_agent, "_rlm_fanout_idx", self.fanout_idx)
object.__setattr__(self.reasoning_agent, "_rlm_parent_depth", getattr(self, "parent_depth", None))
object.__setattr__(self.reasoning_agent, "_rlm_parent_fanout_idx", getattr(self, "parent_fanout_idx", None))
object.__setattr__(self.reasoning_agent, "_rlm_output_schema_name", getattr(schema, "__name__", None))
object.__setattr__(self.reasoning_agent, "_rlm_terminal_completion", None)
object.__setattr__(self.reasoning_agent, "_rlm_lineage_status", None)
```

#### Replace `_collect_reasoning_completion()`

Use priority order:

1. `reasoning_agent._rlm_terminal_completion`
2. fallback from `output_key`
3. fallback from raw text candidate
4. error envelope

#### End-of-run state writes

Emit only:

* `FINAL_RESPONSE_TEXT`
* `SHOULD_STOP`

Do not emit raw/parsed/tokens/thought state deltas.

### Pseudocode patch

```python
def _collect_completion(reasoning_agent, session_state, output_schema):
    completion = getattr(reasoning_agent, "_rlm_terminal_completion", None)
    if completion is not None:
        return completion

    raw = session_state.get(reasoning_agent.output_key or "reasoning_output")
    if raw is not None:
        payload = parse_reasoning_output(raw)
        return CompletionEnvelope(
            terminal=True,
            mode="structured" if payload.parsed_output is not None else "text",
            output_schema_name=getattr(reasoning_agent, "_rlm_output_schema_name", None),
            validated_output=payload.parsed_output,
            raw_output=payload.raw_output,
            display_text=render_completion_text(payload.parsed_output, payload.final_answer),
            reasoning_summary=payload.reasoning_summary,
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

Artifact saving should use `completion.display_text`.

---

## 6) `rlm_adk/dispatch.py`

### Goal

Remove lineage transport through parent state and reduce flush to working-state patching.

### Remove

* `_CHILD_PROPAGATION_KEYS`
* `_acc_child_depth_state`
* propagation of child depth-scoped reasoning keys into parent flush delta
* `obs:child_summary@d{D}f{F}` as a required session-state transport

Today this is the main artifact-like observability bus. It should go away. 

### Keep

* child orchestration
* semaphores
* `LLMResult` return path
* parent skill instruction restoration if still necessary

### Rename

`flush_fn()` → `post_dispatch_state_patch_fn()`

### Change `_run_child()`

Use child/or agent local completion first:

```python
completion = getattr(child, "_rlm_completion", None)
if completion is None:
    completion = getattr(child.reasoning_agent, "_rlm_terminal_completion", None)
```

Then build `LLMResult` from that.

### Pseudocode patch

```python
def post_dispatch_state_patch_fn() -> dict[str, Any]:
    delta = {}
    if _parent_skill_instruction is not None:
        delta[DYN_SKILL_INSTRUCTION] = _parent_skill_instruction
    return delta
```

And in `_run_child()`:

```python
completion = getattr(child, "_rlm_completion", None)
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

Child lineage should not be mirrored into session state anymore.

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

* accept renamed `post_dispatch_state_patch_fn`
* write only that minimal patch into `tool_context.state`
* stop assuming child lineage arrives via dispatch delta

### Pseudocode patch

```python
delta = post_dispatch_state_patch_fn() if post_dispatch_state_patch_fn else {}
for key, value in delta.items():
    tool_context.state[key] = value
```

No child reasoning raw/parsed/visible/thought mirror keys.

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

### before_model_callback

Stop using `CONTEXT_WINDOW_SNAPSHOT` from state as the source of request-side observability. Compute directly from `llm_request` and agent attrs.

### after_model_callback

Persist:

* `custom_metadata_json`
* lineage fields from `llm_response.custom_metadata["rlm"]`

### before_tool_callback / after_tool_callback

Persist actual tool decision:

* `execute_code`
* `set_model_response`

For `set_model_response`, also persist:

* structured outcome
* terminal completion
* validated output JSON

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

Tool path:

```python
if tool_name == "set_model_response":
    update_kwargs["decision_mode"] = "set_model_response"
    update_kwargs["terminal_completion"] = 1
    update_kwargs["validated_output_json"] = json.dumps(result, default=str)
elif tool_name == "execute_code":
    update_kwargs["decision_mode"] = "execute_code"
```

### Reduce `session_state_events`

Keep only working-state capture. Remove lineage-heavy exact keys.

---

## 9) `rlm_adk/plugins/observability.py`

### Goal

Stop using state as a second lineage channel.

### Change

Either:

* reduce plugin to run-summary counters only
* or disable most per-call state writes entirely

### Specifically delete

The workaround where plugin `after_model_callback` writes state and `after_agent_callback` re-persists it for event visibility. That was only necessary because state/event deltas were being used as the telemetry bus. After this refactor, they should not be. Your docs explicitly call out that workaround today. 

---

## 10) Tests

### Rewrite/add

* `test_structured_output_terminality_is_set_model_response`
* `test_child_llm_query_output_schema_returns_llmresult_parsed_without_state_mirroring`
* `test_no_reasoning_lineage_keys_written_to_session_state`
* `test_sqlite_tracing_persists_rlm_custom_metadata`
* `test_tool_decision_mode_execute_code_vs_set_model_response`
* `test_root_completion_renderer_uses_final_answer_when_present`
* `test_root_completion_renderer_json_fallback_when_no_final_answer_field`

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
* `flush_fn` no longer exists as the main observability transport

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

If you want the next pass, I’ll turn this into a literal implementation task list in the format “edit file X, change function Y, add test Z” with commit-sized chunks.
