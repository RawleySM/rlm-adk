# Migration Plan: `custom_metadata` Dispatch Simplification

**Status**: Experiment PASSED (all 5 hypotheses confirmed)
**Date**: 2026-03-19
**Experiment files**:
- `experiments/custom_metadata_callback.py` -- experimental `after_model_callback`
- `experiments/test_custom_metadata_e2e.py` -- 5-hypothesis e2e validation

---

## 1. Experiment Results Summary

| Hypothesis | Result | What it proves |
|---|---|---|
| **H1** | PASS | `custom_metadata` set in `after_model_callback` propagates to yielded `Event` objects. ADK's `_finalize_model_response_event` merges `llm_response.model_dump(exclude_none=True)` into the Event, so `custom_metadata` survives the entire yield path. |
| **H2** | PASS | `callback_context.state` writes via the canonical (agent-level) `after_model_callback` arrive in `event.actions.state_delta`. This confirms the canonical callback path is correctly wired to `model_response_event.actions`, unlike the plugin path (see BUG-13 assessment in `ai_docs/chatGPT_bug13_assessment.md`). |
| **H3** | PASS | K=2 children at the same depth have distinct token counts in their respective `custom_metadata` dicts. No key collision occurs because `custom_metadata` is per-event, not per-session-state-key. This eliminates the need for `depth_key()` scoping on the metadata channel. |
| **H4** | PASS | `custom_metadata` carries equivalents for all LLMResult metadata fields that matter for observability: `visible_output_text`, `thought_text`, `finish_reason`, `input_tokens`, `output_tokens`, `thoughts_tokens`, `rlm_depth`. |
| **H5** | PASS | Child completion metadata is readable directly from `custom_metadata` on child events, confirming that `_read_child_completion` can be simplified to prefer event metadata over depth-scoped state key reads. |

---

## 2. LLMResult Field to custom_metadata Mapping

Current `LLMResult` fields from `rlm_adk/types.py` lines 110-122:

| LLMResult field | custom_metadata key | Notes |
|---|---|---|
| `error` | N/A | Error flows via exception path in `_run_child` (lines 447-504 of `dispatch.py`), not metadata |
| `error_category` | N/A | Same -- classified by `_classify_error()` at dispatch.py line 65 |
| `http_status` | N/A | Same -- extracted from exception `.code` / `.status_code` attrs |
| `finish_reason` | `finish_reason` | From `llm_response.finish_reason.name` (reasoning.py line 182) |
| `input_tokens` | `input_tokens` | From `usage_metadata.prompt_token_count` (reasoning.py line 187) |
| `output_tokens` | `output_tokens` | From `usage_metadata.candidates_token_count` (reasoning.py line 189) |
| `thoughts_tokens` | `thoughts_tokens` | From `usage_metadata.thoughts_token_count` (reasoning.py line 192) |
| `model` | N/A | Available from `invocation_context.agent.model` at runtime; no need to duplicate in metadata |
| `wall_time_ms` | Could add to callback | Would need `time.perf_counter()` wrapper in callback or computed at dispatch site (already done at dispatch.py line 465) |
| `visible_text` | `visible_output_text` | From `_extract_response_text()` (reasoning.py line 179) |
| `thought_text` | `thought_text` | From `_extract_response_text()` (reasoning.py line 179) |
| `raw_output` | N/A | Available from `llm_response.content` directly on the Event; no need to duplicate |
| `parsed` | N/A | Available from `agent._structured_result` set by `SetModelResponseTool` pipeline; not a callback concern |

**Summary**: 6 of 13 fields map directly to `custom_metadata` keys. 3 fields (error/error_category/http_status) flow through the exception path and do not need metadata transport. 4 fields (model/wall_time_ms/raw_output/parsed) are available from other sources at the consumption site.

---

## 3. `_read_child_completion` Simplification

**Current implementation**: `rlm_adk/dispatch.py` lines 295-400

`_read_child_completion` currently reads from 4 sources:

### Source 1: `child._rlm_completion` / `agent._rlm_completion` (lines 310-313)
Dynamic attrs set by the orchestrator's `_run_async_impl`. Contains the completion dict with `text`, `error`, `parsed_output`, `raw_output`, `visible_output_text`, `thought_text`, `finish_reason`, `input_tokens`, `output_tokens`, `thoughts_tokens`.

**With custom_metadata**: The metadata fields (`visible_output_text`, `thought_text`, `finish_reason`, `input_tokens`, `output_tokens`, `thoughts_tokens`) can be read from the child's final model response event's `custom_metadata` instead of from the `_rlm_completion` dict. The `_rlm_completion` dict would still be needed for `text`, `error`, `parsed_output`, `raw_output`, and `reasoning_summary`.

### Source 2: Depth-scoped state keys via `_child_obs_value()` (lines 370-389)
Reads `depth_key(KEY, child_depth)` from `child_state` or `shared_state` for: `REASONING_VISIBLE_OUTPUT_TEXT`, `REASONING_THOUGHT_TEXT`, `REASONING_FINISH_REASON`, `REASONING_INPUT_TOKENS`, `REASONING_OUTPUT_TOKENS`, `REASONING_THOUGHT_TOKENS`.

**With custom_metadata**: This entire source can be replaced. These 6 keys are exactly the fields confirmed by H4 to exist in `custom_metadata`. The `_child_obs_value()` helper and the `_CHILD_PROPAGATION_KEYS` tuple (lines 223-232) entries for these 6 keys become redundant.

Specifically, these `_CHILD_PROPAGATION_KEYS` entries can be removed:
- `REASONING_VISIBLE_OUTPUT_TEXT`
- `REASONING_THOUGHT_TEXT`
- `REASONING_INPUT_TOKENS`
- `REASONING_OUTPUT_TOKENS`
- `REASONING_FINISH_REASON`

These entries must remain (not carried by `custom_metadata`):
- `REPL_SUBMITTED_CODE` -- REPL execution artifact, not model response metadata
- `LAST_REPL_RESULT` -- REPL execution artifact
- `ITERATION_COUNT` -- flow control, not model response metadata

### Source 3: `output_key` / shared state (lines 334-356)
Reads `child_state.get(output_key, shared_state.get(output_key))` for the text answer and structured JSON parsing.

**With custom_metadata**: Still needed. The `output_key` carries the agent's final answer text, which is the primary return value. `custom_metadata` carries metadata *about* the response, not the response content itself.

### Source 4: `agent._structured_result` (lines 358-364)
Reads the validated structured output from `SetModelResponseTool`.

**With custom_metadata**: Still needed. Structured output validation is handled by the `SetModelResponseTool` + `ReflectAndRetryToolPlugin` pipeline, which stores its result on the agent object. This is orthogonal to `custom_metadata`.

### Concrete change to `_run_child` event loop

Currently (dispatch.py lines 455-459), the `_run_child` event loop only collects `state_delta`:

```python
async for _event in child.run_async(child_ctx):
    actions = getattr(_event, "actions", None)
    state_delta = getattr(actions, "state_delta", None)
    if isinstance(state_delta, dict):
        _child_state.update(state_delta)
```

After migration, it should also capture `custom_metadata` from the last model response event:

```python
_last_custom_metadata: dict[str, Any] | None = None
async for _event in child.run_async(child_ctx):
    actions = getattr(_event, "actions", None)
    state_delta = getattr(actions, "state_delta", None)
    if isinstance(state_delta, dict):
        _child_state.update(state_delta)
    if getattr(_event, "custom_metadata", None) is not None:
        _last_custom_metadata = _event.custom_metadata
```

Then pass `_last_custom_metadata` to `_read_child_completion` as an additional parameter.

---

## 4. `_collect_reasoning_completion` Simplification

**Current implementation**: `rlm_adk/orchestrator.py` lines 142-196

This function normalizes the final reasoning payload for dispatch and finalization. It reads from 3 sources:

### Source A: `session_state.get(output_key)` (line 151)
The reasoning agent's output_key (`"reasoning_output"`). This is the primary answer text.

**With custom_metadata**: Still needed -- same rationale as Source 3 above.

### Source B: `session_state.get(depth_key(KEY, depth))` (lines 153-155, 192-194)
Reads depth-scoped state keys for:
- `REASONING_VISIBLE_OUTPUT_TEXT` (line 153)
- `REASONING_THOUGHT_TEXT` (line 154)
- `REASONING_FINISH_REASON` (line 155)
- `REASONING_INPUT_TOKENS` (line 192)
- `REASONING_OUTPUT_TOKENS` (line 193)
- `REASONING_THOUGHT_TOKENS` (line 194)

**With custom_metadata**: These 6 reads can be replaced by reading from the last model response event's `custom_metadata`. The orchestrator's `_run_async_impl` already iterates over events from `reasoning_agent.run_async(ctx)` -- it can capture the last `custom_metadata` dict and pass it to `_collect_reasoning_completion`.

The function signature would change from:
```python
def _collect_reasoning_completion(
    *, reasoning_agent, session_state, depth, output_schema
) -> dict[str, Any]:
```

To:
```python
def _collect_reasoning_completion(
    *, reasoning_agent, session_state, depth, output_schema,
    custom_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

And the 6 `session_state.get(depth_key(...))` reads would first check `custom_metadata`, falling back to the existing state reads for backward compatibility.

### Source C: `agent._structured_result` (line 152)
Validated structured output from `SetModelResponseTool`.

**With custom_metadata**: Still needed -- same rationale as Source 4 above.

### Net simplification

Lines 153-155 (3 state reads) and lines 192-194 (3 state reads) become:
```python
visible_text = (custom_metadata or {}).get("visible_output_text", "") or \
    session_state.get(depth_key(REASONING_VISIBLE_OUTPUT_TEXT, depth)) or ""
```
...with the state-key fallback removed in Phase 3 once Phase 2 is validated.

---

## 5. Phased Migration Path

### Phase 1: Add custom_metadata writing to production callback (alongside existing state writes)

**Scope**: `rlm_adk/callbacks/reasoning.py` lines 168-213

**Change**: In `reasoning_after_model()`, add a `custom_metadata` write to `llm_response` alongside the existing `callback_context.state[depth_key(...)]` writes. This mirrors exactly what `experiments/custom_metadata_callback.py` does in its dual-channel approach.

**Concrete diff** (after line 196 in reasoning.py, before the JSON parsing block):
```python
# --- custom_metadata channel (Phase 1: additive, no consumers yet) ---
llm_response.custom_metadata = {
    "rlm_depth": depth,
    "visible_output_text": visible_text,
    "thought_text": thought_text,
    "finish_reason": finish_reason,
    "input_tokens": callback_context.state[depth_key(REASONING_INPUT_TOKENS, depth)],
    "output_tokens": callback_context.state[depth_key(REASONING_OUTPUT_TOKENS, depth)],
    "thoughts_tokens": callback_context.state[depth_key(REASONING_THOUGHT_TOKENS, depth)],
}
```

**Risk**: Zero. This is additive-only -- no existing code reads `custom_metadata` yet. All existing state writes remain. All existing tests continue to pass unchanged.

**Validation**: Run default test suite (`.venv/bin/python -m pytest tests_rlm_adk/`). Also run the experiment tests to confirm dual-channel parity.

---

### Phase 2: Update `_read_child_completion` to prefer custom_metadata

**Scope**: `rlm_adk/dispatch.py` lines 295-400 and 447-459

**Changes**:
1. Modify `_run_child` event loop (lines 455-459) to capture `_last_custom_metadata` from child events (as described in Section 3).
2. Add `custom_metadata: dict[str, Any] | None = None` parameter to `_read_child_completion`.
3. Update the return dict construction (lines 373-389) to prefer `custom_metadata` values, falling back to existing `_child_obs_value()` reads:

```python
_cm = custom_metadata or {}
return {
    # ... existing text/error/parsed fields unchanged ...
    "visible_output_text": (
        _cm.get("visible_output_text")
        or _read(REASONING_VISIBLE_OUTPUT_TEXT)
        or normalized.get("visible_output_text")
    ),
    "thought_text": (
        _cm.get("thought_text")
        or _read(REASONING_THOUGHT_TEXT)
        or normalized.get("thought_text")
    ),
    "finish_reason": (
        _cm.get("finish_reason")
        or _read(REASONING_FINISH_REASON)
        or normalized.get("finish_reason")
    ),
    "input_tokens": (
        _cm.get("input_tokens")
        or _read(REASONING_INPUT_TOKENS)
        or normalized.get("input_tokens")
    ),
    "output_tokens": (
        _cm.get("output_tokens")
        or _read(REASONING_OUTPUT_TOKENS)
        or normalized.get("output_tokens")
    ),
    "thoughts_tokens": (
        _cm.get("thoughts_tokens")
        or _read(REASONING_THOUGHT_TOKENS)
        or normalized.get("thoughts_tokens")
    ),
    # ... existing obs fields unchanged ...
}
```

4. Similarly update `_collect_reasoning_completion` in `rlm_adk/orchestrator.py` to accept and prefer `custom_metadata`.

**Risk**: Low. The fallback chain ensures backward compatibility. If `custom_metadata` is absent (e.g., replaying old fixtures), the existing path handles it.

**Validation**: Run default test suite. Run FMEA e2e suite (`tests_rlm_adk/test_fmea_e2e.py`). Verify observability counters are unchanged.

---

### Phase 3: Remove redundant state reads

**Scope**: `rlm_adk/dispatch.py`, `rlm_adk/orchestrator.py`, `rlm_adk/state.py`, `rlm_adk/callbacks/reasoning.py`

**Changes**:

1. **Remove fallback state reads from `_read_child_completion`** -- delete the `_read(KEY)` fallback calls for the 6 metadata keys. The `custom_metadata` path becomes the sole source.

2. **Remove depth-scoped state writes from `reasoning_after_model`** -- delete `callback_context.state[depth_key(REASONING_VISIBLE_OUTPUT_TEXT, depth)]` and the other 5 analogous writes (lines 180-198 of reasoning.py). The `custom_metadata` write becomes the sole metadata channel.

3. **Trim `_CHILD_PROPAGATION_KEYS`** (dispatch.py lines 223-232) -- remove the 5 entries listed in Section 3. Keep `REPL_SUBMITTED_CODE`, `LAST_REPL_RESULT`, `ITERATION_COUNT`.

4. **Trim `DEPTH_SCOPED_KEYS`** (state.py lines 193-216) -- remove `REASONING_INPUT_TOKENS`, `REASONING_OUTPUT_TOKENS`, `REASONING_FINISH_REASON`, `REASONING_VISIBLE_OUTPUT_TEXT`, `REASONING_THOUGHT_TEXT`, `REASONING_THOUGHT_TOKENS` from the set. These no longer need depth-scoped state keys since metadata flows through `custom_metadata`.

5. **Update `_collect_reasoning_completion`** -- remove the `session_state.get(depth_key(...))` reads for the 6 metadata keys. Read exclusively from `custom_metadata`.

6. **Remove `_child_obs_value` helper** (dispatch.py lines 239-249) if no remaining callers use it. (Check if `REASONING_PARSED_OUTPUT` and `REASONING_RAW_OUTPUT` still use it -- if so, those reads can also migrate to `_rlm_completion` dict or `custom_metadata`.)

**Risk**: Medium. This is the first phase that removes existing functionality. Requires full test suite validation.

**Validation**: Run default test suite. Run FMEA e2e suite. Run experiment tests. Manually verify observability dashboard output is unchanged.

---

### Phase 4: Deprecate LLMResult in favor of simpler dataclass

**Scope**: `rlm_adk/types.py` lines 95-134, all consumers in `dispatch.py`, REPL skill functions

**Rationale**: `LLMResult(str)` is a `str` subclass hack that exists because metadata had to be smuggled alongside the return value through the REPL's string-oriented interface. With `custom_metadata` as the metadata channel, the return value from `llm_query_async()` can be a simple string, and metadata is available on the event stream.

**Changes**:
1. Create a new `@dataclass` or Pydantic `BaseModel` for structured dispatch results (used internally by `_run_child`):
   ```python
   @dataclass
   class ChildResult:
       text: str
       error: bool = False
       error_category: str | None = None
       parsed: dict | None = None
       wall_time_ms: float = 0.0
   ```

2. Keep `LLMResult(str)` as a deprecated alias with a deprecation warning on construction. REPL code that inspects `.error`, `.parsed` continues to work during the transition.

3. Update `llm_query_async()` to return plain `str` for the happy path, `LLMResult` only for error cases (preserving `.error` / `.error_category` inspection in user REPL code).

4. Eventually remove `LLMResult` entirely once all REPL skill functions are updated.

**Risk**: Highest of all phases. This changes the REPL-facing API. Requires a backward-compatibility period with deprecation warnings.

**Validation**: Full test suite. Manual testing with existing REPL scripts that inspect `LLMResult` metadata. Deprecation warning audit.

---

## 6. AR-CRIT-001 Implications

### Canonical `after_model_callback` state writes are safe

The canonical (agent-level) `after_model_callback` in `reasoning_after_model` receives a `CallbackContext` constructed with `event_actions=model_response_event.actions` at `base_llm_flow.py` lines 1035-1036 (confirmed in `ai_docs/chatGPT_bug13_assessment.md`). This means `callback_context.state[key] = value` writes are tracked into the yielded event's `actions.state_delta`. This is the correct AR-CRIT-001-compliant mutation path.

### This is NOT subject to the plugin BUG-13 wiring issue

The BUG-13 assessment (`ai_docs/chatGPT_bug13_assessment.md`) documents that **plugin** `after_model_callback` receives a fresh, unwired `CallbackContext(invocation_context)` -- so plugin state writes do NOT land in `state_delta`. However, our `reasoning_after_model` is wired as the **canonical agent-level** callback (set on `reasoning_agent.after_model_callback`), which uses the correctly wired context. The BUG-13 monkey-patch in `rlm_adk/callbacks/worker_retry.py` addresses a different issue (premature worker termination by `_output_schema_processor`), not callback state wiring.

### `custom_metadata` is an orthogonal data channel

`LlmResponse.custom_metadata` is a `dict[str, Any]` field on the Pydantic model. It does not interact with `state_delta` tracking at all -- they are independent channels:
- `state_delta`: Written via `callback_context.state[key] = value`, tracked by `EventActions`, merged into session state by the Runner.
- `custom_metadata`: Written via `llm_response.custom_metadata = {...}`, propagated through `_finalize_model_response_event` which calls `llm_response.model_dump(exclude_none=True)` and merges the result into the Event object.

Both channels work independently and can carry all needed metadata, as proven by H1 and H2.

### `model_dump` propagation path

`_finalize_model_response_event` in `base_llm_flow.py` merges `llm_response.model_dump(exclude_none=True)` into the Event at lines 98-100. Since `custom_metadata` is a public Pydantic field on `LlmResponse`, it is included in `model_dump()` output when non-None. The Event class also has a `custom_metadata: dict[str, Any] | None` field (confirmed by the Event constructor signature), so the merge populates it correctly.

### The experiment proves both channels work independently

- H1 proves `custom_metadata` propagates through the event yield path.
- H2 proves canonical `callback_context.state` writes appear in `state_delta`.
- H3 proves per-event `custom_metadata` avoids the key-collision problems that depth-scoped state keys were designed to solve.

---

## 7. Risks and Mitigations

### Risk 1: ADK version upgrade changes `_finalize_model_response_event` behavior

`_finalize_model_response_event` is an internal ADK method that merges `LlmResponse` fields into Event objects. If a future ADK version changes the merge logic (e.g., excludes `custom_metadata`), the metadata channel breaks silently.

**Mitigation**:
- Pin ADK version in `pyproject.toml` (already done).
- Add a regression test asserting that `custom_metadata` set in `after_model_callback` appears on the yielded Event. This test should run in the default test suite and fail loudly if the propagation path breaks.
- The experiment test `test_h1_custom_metadata_propagates` can be promoted to a permanent contract test.

### Risk 2: `custom_metadata` field is undocumented or unstable

**Mitigation**:
- `custom_metadata` is a public field on `LlmResponse` with a docstring (confirmed at `google.adk.models.llm_response`). It was explicitly added in ADK v0.3.0 for tagging responses from `after_model_callback` (per the BUG-13 assessment's reference to the CHANGELOG).
- It is also a public field on `Event` (confirmed by the Event constructor signature: `custom_metadata: dict[str, Any] | None = None`).
- ADK's own `RunConfig.custom_metadata` uses the same field in `runners.py`, indicating it is part of the intended API surface.

### Risk 3: Phase 4 (LLMResult deprecation) breaks REPL code that inspects `.error`, `.parsed`

REPL skill functions may use patterns like:
```python
result = await llm_query_async("prompt")
if result.error:
    handle_error(result.error_category)
if result.parsed:
    process_structured(result.parsed)
```

**Mitigation**:
- Phase 4 is deliberately last, after Phases 1-3 are validated in production.
- Maintain a backward-compatibility period where `LLMResult` still works but emits a `DeprecationWarning`.
- For the `.error` use case, errors can be communicated via a sentinel prefix in the string (already used: `"[RLM ERROR]"` prefix at dispatch.py line 366).
- For the `.parsed` use case, structured output can be returned as a dict directly (the REPL already handles dict return values).

### Risk 4: `_rlm_completion` dict and `_structured_result` still needed after migration

Even with `custom_metadata`, Sources 1, 3, and 4 from Section 3 remain necessary for the answer text, error status, and structured output. The migration simplifies metadata transport but does not eliminate these other data flows.

**Mitigation**: The plan explicitly scopes each phase. Phases 1-3 target only the 6 metadata fields. The `_rlm_completion` dict continues to carry `text`, `error`, `error_category`, `parsed_output`, `raw_output`, and `reasoning_summary`. No over-removal.

### Risk 5: Replay fixtures lack `custom_metadata`

Existing provider-fake fixtures and replay JSON files do not produce `custom_metadata` in their events (the experimental callback is not wired in fixture runs).

**Mitigation**: Phase 2's fallback chain (`custom_metadata` -> `state_delta` -> `_rlm_completion`) ensures existing fixtures continue to work. Phase 3 (removing fallbacks) should only proceed after all fixtures are updated to wire the production callback that writes `custom_metadata`.
