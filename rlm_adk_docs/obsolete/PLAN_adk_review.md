# ADK Technical Review: Context Window Dashboard v2 Plan

**Reviewer**: Claude Opus 4.6 (automated ADK expert review)
**Date**: 2026-02-24
**Plan file**: `rlm_adk_docs/PLAN_context_window_dashboard_v2.md`

---

## Executive Summary

The plan is well-structured and demonstrates strong understanding of the codebase. Of the 10 verification points, **6 are correct**, **3 have issues requiring correction**, and **1 has a nuance worth documenting**. The most critical issues are around plugin execution order (plugins fire BEFORE agent callbacks, which changes what state is available), the worker prompt structure in the LlmRequest, and the system_instruction split heuristic. None of the issues are architectural blockers; all are fixable during implementation.

---

## 1. Plugin Callback Signatures

**Verdict: CORRECT**

The plan's `ContextWindowSnapshotPlugin` extends `BasePlugin` and uses `before_model_callback`, `after_model_callback`, and `on_model_error_callback`. The actual `BasePlugin` source (`google.adk.plugins.base_plugin`) confirms these exact signatures:

```python
# BasePlugin (verified from source: .venv/.../google/adk/plugins/base_plugin.py)
async def before_model_callback(
    self, *, callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]: ...

async def after_model_callback(
    self, *, callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]: ...

async def on_model_error_callback(
    self, *, callback_context: CallbackContext, llm_request: LlmRequest, error: Exception
) -> Optional[LlmResponse]: ...
```

The plan's section 2.3 shows:

```python
async def after_model_callback(self, *, callback_context, llm_response):
```

This is correct -- keyword-only arguments match the base class. However, the plan should add **type annotations** to match the existing plugin conventions used by `DebugLoggingPlugin` and `ObservabilityPlugin`:

```python
async def after_model_callback(
    self,
    *,
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> Optional[LlmResponse]:
```

**Important safety note**: All plugin callbacks must return `None` to allow the pipeline to proceed. Returning a non-None value short-circuits remaining plugins AND agent callbacks. The existing plugins correctly return `None` in all observe-only paths. The plan's code does return `None`, which is correct.

---

## 2. Agent Type Detection

**Verdict: ISSUE -- Plugin fires BEFORE agent callbacks; state keys are NOT yet set**

### What the plan says (Section 2.2):

> Check `callback_context._invocation_context.agent.name` -- if it equals `"reasoning_agent"`, it is a reasoning call. Otherwise, it is a worker.
>
> Fallback: check if state key `REASONING_PROMPT_CHARS` was just set (reasoning) vs `WORKER_PROMPT_CHARS` (worker).

### What actually happens:

The **agent name check** is correct and is the reliable method. The code confirms:
- Reasoning agent: `name="reasoning_agent"` (set in `agent.py` line 184)
- Worker agents: `name="worker_{N}"` (set in `dispatch.py` line 108)

However, there is a **critical subtlety** with the fallback approach. ADK's plugin execution order is:

> Plugins take precedence over agent callbacks. (BasePlugin docstring)

This means the plugin's `before_model_callback` fires **BEFORE** `reasoning_before_model` or `worker_before_model` agent callbacks. At the time the plugin executes:

- `REASONING_PROMPT_CHARS` has **NOT** been set yet (set by `reasoning_before_model`)
- `WORKER_PROMPT_CHARS` has **NOT** been set yet (it is a `temp:` key set by the dispatch closure, not by `worker_before_model`)
- The `LlmRequest.contents` have **NOT** been populated by `reasoning_before_model` (which injects `MESSAGE_HISTORY`)

This means **the plugin cannot decompose the LlmRequest contents** in `before_model_callback` because the agent callbacks have not yet run to build them.

### The correction:

**Option A (recommended)**: Move the snapshot capture to `after_model_callback` only. At that point, all agent callbacks have fired, state keys are populated, and `llm_response.usage_metadata` is available. The problem is that `after_model_callback` does not receive the `llm_request`, so the full prompt text is not available.

**Option B (best fit for the plan's goals)**: Use the plugin's `before_model_callback` to detect agent type via agent name, but understand that:
- For the **reasoning agent**: `llm_request.contents` will be **empty** (because `reasoning_before_model` has not run yet; `include_contents='none'` means ADK provides nothing, and the agent callback is what injects `MESSAGE_HISTORY`). The `system_instruction` WILL be set (ADK populates it from `static_instruction` before any callbacks). The dynamic instruction WILL be in `llm_request.contents` as a user Content (ADK resolves the template before callbacks).
- For **worker agents**: `llm_request.contents` will contain the ADK-resolved `instruction=` content as a single user message ("Answer the user's query directly and concisely."), but NOT the actual worker prompt (that is injected by `worker_before_model`).

**Option C (recommended for full accuracy)**: Register the plugin as the **last** plugin in the list, AND capture the snapshot in the agent's own callbacks rather than in the plugin. Alternatively, stash a reference to the LlmRequest in `before_model_callback` (after agent callbacks have mutated it -- but wait, plugins fire first).

**The actual correct approach**: Since plugins fire before agent callbacks, and the agent callbacks are what build the real request contents, the plugin must capture the request **after** the agent callback has modified it. The way to do this is:

1. In `before_model_callback` (plugin): record a reference or flag, but do NOT decompose yet. The `llm_request` object is **mutable** and will be modified in-place by the agent callback that runs after the plugin.
2. In `after_model_callback` (plugin): the `llm_request` modifications from the agent callback are now visible through the mutable reference. BUT `after_model_callback` does not receive `llm_request`.

**Best practical approach**: Store a reference to the `llm_request` in `before_model_callback`, and read its (now-mutated) contents in `after_model_callback`:

```python
async def before_model_callback(
    self, *, callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    # Store reference -- agent callbacks will mutate this IN-PLACE
    self._pending_request = llm_request
    self._pending_agent_name = callback_context._invocation_context.agent.name
    self._pending_state_snapshot = {
        "iteration": callback_context.state.get(ITERATION_COUNT, 0),
    }
    return None  # proceed; agent callback will now mutate llm_request

async def after_model_callback(
    self, *, callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    if self._pending_request is None:
        return None

    # NOW llm_request has been mutated by reasoning_before_model / worker_before_model
    llm_request = self._pending_request
    agent_name = self._pending_agent_name

    # Decompose the MUTATED llm_request here
    chunks = self._decompose_request(llm_request, agent_name)

    # Also read usage_metadata from llm_response
    usage = llm_response.usage_metadata
    ...

    self._pending_request = None
    return None
```

This works because Python objects are passed by reference. The `LlmRequest` object stored in `before_model_callback` is the same object that `reasoning_before_model` mutates. By the time `after_model_callback` fires, the mutations are visible.

**Verification**: This pattern is confirmed by the ADK docs:

> "Change Propagation: Plugins and agent callbacks can both modify the value of the input parameters... The modifications will be visible and passed to the next callback in the chain."

The `llm_request` object flows: Plugin.before_model -> Agent.before_model (mutates it) -> LLM call -> Agent.after_model -> Plugin.after_model. The plugin's stored reference sees the mutations.

---

## 3. Context Decomposition Accuracy

**Verdict: PARTIALLY CORRECT -- several details need adjustment**

### 3a. System Instruction Split Heuristic

**What the plan says (Section 2.2)**:

> Split into STATIC_INSTRUCTION and DYNAMIC_INSTRUCTION chunks by detecting the `"\n\nRepository URL:"` boundary (the start of RLM_DYNAMIC_INSTRUCTION).

**What the actual code does** (`reasoning_before_model`, lines 86-98):

```python
static_si = _extract_system_instruction_text(llm_request)    # from static_instruction
dynamic_instruction = _extract_adk_dynamic_instruction(llm_request)  # from contents

system_instruction_text = static_si
if dynamic_instruction:
    if system_instruction_text:
        system_instruction_text += "\n\n" + dynamic_instruction
    else:
        system_instruction_text = dynamic_instruction
```

The boundary between static and dynamic is literally `"\n\n"` + the dynamic instruction text. The dynamic instruction template is:

```python
RLM_DYNAMIC_INSTRUCTION = textwrap.dedent("""\
Repository URL: {repo_url?}
Original query: {root_prompt?}
""")
```

So after ADK resolves the template, the dynamic instruction might be:
```
Repository URL: https://github.com/...
Original query: Analyze...
```

The plan's heuristic of detecting `"\nRepository URL:"` is **almost correct** but should be `"\n\nRepository URL:"` (two newlines, as that is the separator used on line 96). However, there is a subtlety: if `repo_url` is empty/missing, ADK's `{repo_url?}` resolves to an empty string, and the line becomes `"Repository URL: \n"`. The heuristic should handle this edge case.

**Correction**: Use `"\n\nRepository URL:"` as the split boundary, and handle the case where dynamic instruction is empty (no split needed).

### 3b. Contents Decomposition for Reasoning Agent

**What the plan says (Section 2.2)**:

> contents from `llm_request.contents` -- These are the `message_history` entries injected by `reasoning_before_model`.

**What actually happens** (with the fix from Issue #2): After `reasoning_before_model` mutates the `LlmRequest`, `llm_request.contents` will contain the full message history. The plan's classification logic is correct:

- `role="user"` first message with safeguard text -> `USER_PROMPT` (iteration 0)
- `role="user"` with `"Code executed:\n```python"` -> split into `REPL_CODE` + `REPL_OUTPUT`
- `role="model"` -> `LLM_RESPONSE`
- `role="user"` with `"REPL variables:"` -> `CONTEXT_VAR`

The REPL split boundary is confirmed by `format_iteration` (parsing.py line 100):
```python
f"Code executed:\n```python\n{code}\n```\n\nREPL output:\n{result}"
```

So the split should be at `"\n\nREPL output:\n"`, which matches the plan's `"\n\nREPL output:\n"` description. **Correct**.

### 3c. CONTEXT_VAR Detection

The plan says to detect `"REPL variables:"` in user messages. Looking at the actual code in `format_execution_result` (parsing.py line 139):

```python
result_parts.append(f"REPL variables: {list(important_vars.keys())}\n")
```

This is appended as part of the REPL output, NOT as a separate Content message. It is embedded within the `"Code executed:..."` user message, in the result section after `"REPL output:\n"`. So `CONTEXT_VAR` should not be a separate Content-level chunk; it is a sub-section within `REPL_OUTPUT`.

**Correction**: Either remove `CONTEXT_VAR` as a top-level chunk category, or extract it as a sub-chunk within REPL_OUTPUT text by detecting the `"REPL variables:"` prefix within the output text.

### 3d. Worker Prompt Structure

**What the plan says (Section 2.2)**:

> No system_instruction (workers use `instruction=` which becomes a user Content, but `include_contents='none'` means only the injected prompt arrives).
> contents: The single prompt injected via `worker._pending_prompt` -> WORKER_PROMPT chunk.

**What actually happens**: Worker agents have `instruction="Answer the user's query directly and concisely."` (dispatch.py line 114) and `include_contents="none"`. When ADK processes this:
1. ADK places the resolved instruction into `llm_request.contents` as a user Content (since there is no `static_instruction`, instruction goes to contents).
2. `worker_before_model` then **overwrites** `llm_request.contents` entirely with the pending prompt (worker.py lines 36-54).

So after the agent callback mutates the request, `llm_request.contents` will contain ONLY the pending prompt content(s), not the instruction. The plan's description is **correct** for the final state of the request.

However, the worker's `instruction=` string will appear in `llm_request.config.system_instruction` if there is NO `static_instruction` -- actually, checking the ADK code: when only `instruction=` is set (no `static_instruction`), ADK resolves the template and places it as a user Content in `llm_request.contents`. Since `worker_before_model` overwrites `contents`, the instruction is lost. There is **no system_instruction** set for workers. **The plan is correct on this point.**

---

## 4. State Key Access

**Verdict: CORRECT with one note**

The plan references `ITERATION_COUNT` -- confirmed in `state.py` line 15:
```python
ITERATION_COUNT = "iteration_count"
```

The plan's JSONL entry includes `"iteration": state.get(ITERATION_COUNT, 0)`. This is correct.

**Note**: `REASONING_PROMPT_CHARS` and `WORKER_PROMPT_CHARS` are referenced in the fallback detection logic. As discussed in Issue #2, these are NOT available in the plugin's `before_model_callback` because the plugin fires first. However, they ARE available in `after_model_callback` (after agent callbacks have set them). The actual state key values are confirmed:

```python
REASONING_PROMPT_CHARS = "reasoning_prompt_chars"      # state.py line 58
WORKER_PROMPT_CHARS = "temp:worker_prompt_chars"       # state.py line 67
```

**Important detail**: `WORKER_PROMPT_CHARS` uses the `temp:` prefix, meaning it is NOT persisted across invocations. This is fine for the plugin since it reads during the same invocation. But note that the worker prompt chars are actually set by the **dispatch closure** (not by `worker_before_model`), via event_queue state_delta. The plugin should be aware that `WORKER_PROMPT_CHARS` may not be in `callback_context.state` at `after_model_callback` time if the event has not been drained yet.

**Safer approach**: Read prompt metrics directly from the `LlmRequest` contents (which the plugin has a reference to) rather than from state keys.

---

## 5. usage_metadata Access

**Verdict: CORRECT**

The plan uses:
```python
usage = llm_response.usage_metadata
self._pending_entry["input_tokens"] = getattr(usage, "prompt_token_count", 0) or 0
self._pending_entry["output_tokens"] = getattr(usage, "candidates_token_count", 0) or 0
```

Verified against `LlmResponse` source (line 105):
```python
usage_metadata: Optional[types.GenerateContentResponseUsageMetadata] = None
```

And the `GenerateContentResponseUsageMetadata` model fields (verified via runtime introspection):
```python
['cache_tokens_details', 'cached_content_token_count', 'candidates_token_count',
 'candidates_tokens_details', 'prompt_token_count', 'prompt_tokens_details',
 'thoughts_token_count', 'tool_use_prompt_token_count',
 'tool_use_prompt_tokens_details', 'total_token_count', 'traffic_type']
```

Both `prompt_token_count` and `candidates_token_count` are confirmed as valid fields. The `getattr(..., 0) or 0` pattern handles both missing attributes and `None` values. This matches the pattern used by `debug_logging.py` (line 232-237), `observability.py` (line 125-126), `reasoning.py` (line 173-178), and `worker.py` (line 95-96).

**Additional available fields the plan might want to capture**:
- `thoughts_token_count`: tokens used for thinking/planning (relevant since reasoning agent uses `BuiltInPlanner`)
- `cached_content_token_count`: tokens served from cache
- `total_token_count`: total across all categories

---

## 6. Plugin Wiring

**Verdict: CORRECT**

The plan says (Section 11, Phase 1, Step 3):

> Wire `ContextWindowSnapshotPlugin` into `rlm_adk/agent.py` `_default_plugins()` as opt-in (`RLM_CONTEXT_SNAPSHOTS=1`)

The actual `_default_plugins()` function (agent.py lines 241-274) follows exactly this pattern for optional plugins:

```python
def _default_plugins(*, debug=True, langfuse=False, sqlite_tracing=True) -> list[BasePlugin]:
    plugins: list[BasePlugin] = [ObservabilityPlugin()]
    _debug_env = os.getenv("RLM_ADK_DEBUG", "").lower() in ("1", "true", "yes")
    if debug or _debug_env:
        plugins.append(DebugLoggingPlugin())
    _sqlite_env = os.getenv("RLM_ADK_SQLITE_TRACING", "").lower() in ("1", "true", "yes")
    if sqlite_tracing or _sqlite_env:
        try:
            from rlm_adk.plugins.sqlite_tracing import SqliteTracingPlugin
            plugins.append(SqliteTracingPlugin())
        except ImportError:
            logger.debug("SqliteTracingPlugin not available, skipping")
    ...
```

The correct wiring would add a block like:

```python
_snapshot_env = os.getenv("RLM_CONTEXT_SNAPSHOTS", "").lower() in ("1", "true", "yes")
if _snapshot_env:
    from rlm_adk.plugins.context_snapshot import ContextWindowSnapshotPlugin
    plugins.append(ContextWindowSnapshotPlugin())
```

**Ordering consideration**: The snapshot plugin should be appended **last** (or at least after ObservabilityPlugin) so it does not interfere with other plugins. Since it returns `None` from all callbacks, ordering does not affect correctness, but it is good practice. Additionally, see Issue #2 -- the plugin relies on reading the mutated `LlmRequest`, which works regardless of plugin ordering because the mutation happens in agent callbacks (which all run after all plugins).

---

## 7. Error Handling

**Verdict: CORRECT**

The plan says (Section 2.5):

> If `before_model_callback` captures an entry but `after_model_callback` is not called (e.g., model error), the `on_model_error_callback` flushes the pending entry with `input_tokens=0, output_tokens=0, error=True`.

The `on_model_error_callback` signature from `BasePlugin` is confirmed:

```python
async def on_model_error_callback(
    self, *, callback_context: CallbackContext, llm_request: LlmRequest, error: Exception
) -> Optional[LlmResponse]: ...
```

This matches the pattern used by `DebugLoggingPlugin.on_model_error_callback` (line 318-345) and `worker_on_model_error` (worker.py line 109-133).

**Edge case to handle**: The plugin's `on_model_error_callback` receives `llm_request`, which at this point has been mutated by the agent callback. So the plugin can still decompose the request contents for the error entry. The plugin must:
1. Check if `self._pending_request` is set (from `before_model_callback`)
2. Flush with `error=True`, `error_message=str(error)`
3. Clear `self._pending_request`
4. Return `None` (so the error propagates normally)

**Important**: The plugin must NOT return a non-None `LlmResponse` from `on_model_error_callback` -- doing so would swallow the error and prevent the agent-level `on_model_error_callback` (e.g., `worker_on_model_error`) from handling it.

---

## 8. Content/Part Types

**Verdict: CORRECT**

The plan uses:
```python
def _extract_content_text(content: types.Content) -> str:
    if not content.parts:
        return ""
    return "".join(
        p.text for p in content.parts
        if isinstance(p, types.Part) and p.text
    )
```

This matches the pattern used throughout the codebase:
- `reasoning.py` line 45-48: `"".join(p.text for p in si.parts if isinstance(p, types.Part) and p.text)`
- `worker.py` line 82-84: `"".join(part.text for part in llm_response.content.parts if part.text and not part.thought)`

The `types.Content` and `types.Part` types are from `google.genai.types`, confirmed as the standard types used across the codebase. Content objects have a `.role` string and `.parts` list. Part objects have `.text` (optional string).

**Minor note**: Parts can also have `.thought` (boolean) for thinking tokens. The plan's extraction should consider filtering out thought parts if it wants to match only user-visible text:

```python
if isinstance(p, types.Part) and p.text and not getattr(p, 'thought', False)
```

This matches the pattern in `reasoning_after_model` (line 165) and `worker_after_model` (line 83).

---

## 9. Worker Prompt Structure

**Verdict: CORRECT with refinement needed**

### What the plan says:

> No system_instruction (workers use `instruction=` which becomes a user Content, but `include_contents='none'` means only the injected prompt arrives).
> contents: The single prompt injected via `worker._pending_prompt` -> WORKER_PROMPT chunk.

### What the code confirms:

In `worker_before_model` (worker.py lines 34-54):
```python
if isinstance(pending_prompt, str):
    llm_request.contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=pending_prompt)],
        )
    ]
elif isinstance(pending_prompt, list):
    # Message list format [{role: ..., content: ...}, ...]
    contents = []
    for msg in pending_prompt:
        role = msg.get("role", "user")
        adk_role = "model" if role == "assistant" else "user"
        contents.append(...)
    llm_request.contents = contents
```

The prompt can be either:
1. A single string -> becomes one user Content with one Part
2. A message list -> becomes multiple Content objects with different roles

The plan's decomposition logic handles the single-string case but should also handle the message-list case. When the prompt is a list, the plugin should decompose each Content as a separate sub-chunk (e.g., `WORKER_PROMPT` for user messages, `WORKER_RESPONSE` for model messages in multi-turn prompts).

---

## 10. Session ID Access

**Verdict: ISSUE -- Plan does not show the correct access path**

The plan's JSONL entry includes `"session_id": session_id` but does not show how `session_id` is obtained from the callback context.

### Correct access path:

From the `CallbackContext` source, it inherits from `ReadonlyContext` which stores `_invocation_context`. The session is accessible via:

```python
session_id = callback_context._invocation_context.session.id
```

Or using the public property:

```python
session_id = callback_context.session.id
```

The `ReadonlyContext` base class exposes a `session` property (line 59-61):
```python
@property
def session(self) -> Session:
    """The current session for this invocation."""
    return self._invocation_context.session
```

And `Session.id` is a string field (confirmed from the Session model: `id: str`).

**Recommended approach** (uses public API, avoids private `_invocation_context`):

```python
session_id = callback_context.session.id
```

The plan should document this. Using the public `callback_context.session.id` is preferred over accessing private `_invocation_context`.

---

## Additional Edge Cases

### A. Thread Safety for `_pending_request`

The plugin uses `self._pending_request` as instance state to bridge `before_model_callback` and `after_model_callback`. In the current architecture, the reasoning agent runs sequentially (one LLM call at a time), so this is safe. However, when workers run via `ParallelAgent`, multiple workers may fire their callbacks concurrently.

**The plugin is a singleton** (one instance in the plugins list), and `ParallelAgent` runs sub-agents concurrently. If two workers fire `before_model_callback` simultaneously, they will overwrite each other's `_pending_request`.

**Correction**: Use a dict keyed by agent name (or callback_context identity) instead of a single `_pending_request`:

```python
self._pending: dict[str, dict] = {}  # keyed by agent_name

async def before_model_callback(self, *, callback_context, llm_request):
    agent_name = callback_context._invocation_context.agent.name
    self._pending[agent_name] = {
        "request": llm_request,
        "timestamp": time.time(),
        "iteration": callback_context.state.get(ITERATION_COUNT, 0),
        "session_id": callback_context.session.id,
    }
    return None

async def after_model_callback(self, *, callback_context, llm_response):
    agent_name = callback_context._invocation_context.agent.name
    pending = self._pending.pop(agent_name, None)
    if pending is None:
        return None
    # ... decompose pending["request"] and write JSONL ...
    return None
```

### B. File Handle Thread Safety

The plan uses `self._file_handle` with `file.flush()`. With concurrent worker callbacks, multiple `after_model_callback` calls may write to the file simultaneously. JSONL lines must be written atomically.

**Correction**: Use a threading lock or write entire lines via `print(..., file=f, flush=True)` which is atomic for single lines on most platforms. Or use `asyncio.Lock` since all callbacks are async:

```python
self._write_lock = asyncio.Lock()

async def _flush_entry(self, entry: dict):
    import json
    line = json.dumps(entry)
    async with self._write_lock:
        self._ensure_file_open()
        self._file_handle.write(line + "\n")
        self._file_handle.flush()
```

### C. Model Field in LlmRequest

The plan captures `"model": llm_request.model or "unknown"`. The `LlmRequest.model` field may be an empty string rather than `None` when the agent inherits the model from its parent. The `or "unknown"` pattern handles both `None` and `""`, so this is correct.

For `after_model_callback`, the `LlmResponse.model_version` field provides the actual model version used (e.g., `"gemini-3-pro-preview-20260214"`). This is more precise than the requested model name. Consider capturing both:

```python
"model_requested": llm_request.model or "unknown",
"model_version": llm_response.model_version or "unknown",
```

### D. `after_run_callback` for File Cleanup

The plan mentions closing the file in `after_run_callback`. The signature from `BasePlugin` is:

```python
async def after_run_callback(self, *, invocation_context: InvocationContext) -> None:
```

This receives `InvocationContext`, not `CallbackContext`. The existing plugins (`debug_logging.py` line 429, `observability.py` line 254) confirm this signature. File close logic should go here and is correct.

### E. Dynamic Instruction Extraction

The plan needs to handle how the dynamic instruction arrives in the `LlmRequest`. The `_extract_adk_dynamic_instruction` function in `reasoning.py` (lines 52-66) extracts text from ALL contents in the request and strips it. After `reasoning_before_model` runs, the dynamic instruction has been removed from contents and appended to system_instruction.

So in the plugin's `after_model_callback` (reading the mutated request):
- `llm_request.config.system_instruction` contains static + dynamic (concatenated)
- `llm_request.contents` contains only the message history

The split heuristic `"\n\nRepository URL:"` will work on the concatenated system_instruction string.

---

## Summary of Required Changes

| # | Issue | Severity | Fix |
|---|-------|----------|-----|
| 1 | Plugin `before_model_callback` fires BEFORE agent callbacks; LlmRequest is not yet populated | **HIGH** | Store LlmRequest reference in `before_model_callback`, decompose in `after_model_callback` (object is mutated in-place by agent callbacks) |
| 2 | Thread safety: `_pending_request` singleton overwritten by concurrent workers | **HIGH** | Use dict keyed by agent name instead of single instance variable |
| 3 | Session ID access path not documented | **LOW** | Use `callback_context.session.id` (public API) |
| 4 | `CONTEXT_VAR` is embedded within REPL output, not a separate Content | **LOW** | Detect within REPL_OUTPUT text or remove as top-level chunk |
| 5 | System instruction split boundary should be `"\n\nRepository URL:"` (two newlines) | **LOW** | Fix the heuristic string |
| 6 | Worker multi-turn prompts need per-message decomposition | **LOW** | Handle `isinstance(pending_prompt, list)` case in chunk extraction |
| 7 | File write atomicity under concurrent workers | **MEDIUM** | Use `asyncio.Lock` for JSONL writes |
| 8 | Consider capturing `thoughts_token_count` from usage_metadata | **LOW** | Optional enhancement for thinking budget visibility |
