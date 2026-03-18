<!-- validated: 2026-03-17 -->
# ADK v1.27.0 Update: Callbacks, Retry, and BUG-13 Implications

**Baseline:** ADK v1.25.0 (installed), `pyproject.toml` pins `google-adk>=1.2.0`
**Target:** ADK v1.27.0

---

## 1. v1.27.0 Changes Relevant to RLM-ADK

### 1a. Before/After Tool Callbacks in Live Mode (closes #4704)

In v1.25.0, the Live (streaming) code path `_execute_single_function_call_live()` in `functions.py:642-730` fires `before_tool_callbacks` and `after_tool_callbacks` on the agent, but **does not fire `on_tool_error_callbacks`** and **does not invoke plugin-level tool callbacks** (`plugin_manager.run_before_tool_callback`, `plugin_manager.run_after_tool_callback`, `plugin_manager.run_on_tool_error_callback`). By contrast, the standard async path (`_execute_single_function_call_async`, line 420+) fires the full callback chain including plugin callbacks and `on_tool_error_callbacks`.

v1.27.0 closes this gap: tool callbacks now fire in Live mode with the same semantics as the standard path.

### 1b. Reusable Function Extraction from HITL and Auth Preprocessor

Internal refactoring of how auth and human-in-the-loop callbacks are invoked. Extracts shared logic into reusable functions. This is an infrastructure change inside `functions.py`'s `_postprocess_handle_function_calls_async` (line 824+) where auth/confirmation events are generated.

### 1c. LiteLLM Reasoning Extraction -- 'reasoning' Field (closes #3694)

The `_iter_reasoning_texts()` function in `lite_llm.py:338-373` already searches dict payloads for keys `("text", "content", "reasoning", "reasoning_content")`. The v1.25.0 code already includes the `"reasoning"` key (line 363). This change may have landed between v1.25.0 and v1.27.0, or the PR was merged before our snapshot. **Our installed version already has this fix.**

### 1d. Preserve thought_signature in LiteLLM Tool Calls (closes #4650)

In v1.25.0, `thought_signature` is **not present** in `lite_llm.py` (confirmed by grep). This is a new field that some providers (notably Anthropic via LiteLLM) attach to tool calls to maintain chain-of-thought continuity. v1.27.0 preserves it through the message conversion pipeline.

### 1e. Output Schema with Tools for LiteLLM Models (closes #3969)

In v1.25.0, `can_use_output_schema_with_tools()` in `output_schema_utils.py:31-38` returns `True` only for `VertexAI + Gemini 2+`. All other models (including LiteLLM-routed models) fall through to the `_OutputSchemaRequestProcessor` which injects `SetModelResponseTool` as a workaround. v1.27.0 extends this to LiteLLM models, potentially allowing native output_schema support alongside tools.

### 1f. JSON Schema Boolean Handling in Gemini Conversion

Bug fix for boolean schemas in JSON-to-Gemini schema conversion. Low relevance to RLM-ADK.

---

## 2. BUG-13 Patch Status Assessment

### Current Patch Mechanics

The BUG-13 monkey-patch lives in `rlm_adk/callbacks/worker_retry.py:238-288`. It:

1. Imports `google.adk.flows.llm_flows._output_schema_processor` as `_osp` (line 246)
2. Wraps `_osp.get_structured_model_response` with `_retry_aware_get_structured_model_response` (line 261-284)
3. The wrapper calls the original, then parses the JSON result looking for `response_type == REFLECT_AND_RETRY_RESPONSE_TYPE`
4. When the sentinel is found, returns `None` (suppressing premature worker termination)
5. Applies at import time (line 288) with idempotency guard (line 256)

The patch target is the module-level function `get_structured_model_response` at `_output_schema_processor.py:96-116`. This function is called from `base_llm_flow.py` at two sites:
- **Line 803:** Inside `_postprocess_handle_function_calls_live` (Live mode path)
- **Line 849:** Inside `_postprocess_handle_function_calls_async` (standard path)

Both call sites use module-attribute lookup (`_output_schema_processor.get_structured_model_response(...)`) which makes the patch effective -- replacing the module attribute intercepts all callers.

### Has v1.27.0 Changed the Module Structure?

**Risk: LOW-MEDIUM.** The patch imports a private module (`_output_schema_processor`) and patches a module-level function on it. Three things could break the patch:

1. **Module renamed/moved.** The `_output_schema_processor.py` file is a private module (underscore prefix). ADK could reorganize `flows/llm_flows/` internals. The patch has a defensive `try/except ImportError` (line 245-253) that degrades gracefully with a warning log.

2. **Function signature changed.** The patched function `get_structured_model_response(function_response_event)` takes a single `Event` argument and returns `str | None`. If the signature changes, the wrapper would fail at call time. However, since the wrapper delegates to the original and only post-processes the return value, most signature changes would be transparent.

3. **Call site changed from module lookup to direct import.** If `base_llm_flow.py` changed from `_output_schema_processor.get_structured_model_response(...)` to a direct `from ._output_schema_processor import get_structured_model_response`, the module-level patch would silently stop working. This is the most dangerous failure mode because it produces no error -- just broken retry behavior.

**Assessment for v1.27.0:** The "reusable function extraction from hitl and auth preprocessor" refactoring touches `_postprocess_handle_function_calls_async`, which is the same function that contains the BUG-13 call site (line 849). If the refactoring extracted the auth/hitl handling but kept the `_output_schema_processor` call site intact with module-attribute lookup, the patch remains valid. If the refactoring restructured the flow such that `get_structured_model_response` is called differently, the patch could break silently.

### Has the Underlying Issue Been Fixed Upstream?

**Assessment: UNLIKELY but PLAUSIBLE.** The core issue is that `get_structured_model_response` treats ANY `set_model_response` function response as a successful structured output, including `ToolFailureResponse` dicts from `ReflectAndRetryToolPlugin`. The fix would require `get_structured_model_response` to check for the `REFLECT_AND_RETRY_RESPONSE_TYPE` sentinel before converting to a final event.

In v1.25.0, `get_structured_model_response` (lines 96-116) does a naive check: it iterates over function responses, finds one with `name == 'set_model_response'`, and returns `json.dumps(func_response.response)`. There is no sentinel check. None of the v1.27.0 changelog items explicitly mention this issue, and the `ReflectAndRetryToolPlugin` changelog entry is about scope tracking, not about the postprocessor interaction.

**Verdict:** The underlying issue is **probably not fixed** in v1.27.0. The patch is still needed.

### Verification Strategy

After upgrading to v1.27.0:

1. **Import sanity check** (fast, no network):
   ```python
   python -c "from google.adk.flows.llm_flows._output_schema_processor import get_structured_model_response; print('Module import OK')"
   ```

2. **Patch installation check** (fast):
   ```python
   python -c "
   from rlm_adk.callbacks.worker_retry import _patch_output_schema_postprocessor
   import google.adk.flows.llm_flows._output_schema_processor as _osp
   print('Patched:', getattr(_osp.get_structured_model_response, '_rlm_patched', False))
   "
   ```

3. **Call-site verification** (must check manually):
   ```bash
   # Verify base_llm_flow.py still uses module-attribute lookup (not direct import)
   grep -n 'get_structured_model_response' .venv/lib/python3.12/site-packages/google/adk/flows/llm_flows/base_llm_flow.py
   # Must show: _output_schema_processor.get_structured_model_response(
   # Not: get_structured_model_response(  (direct import)
   ```

4. **Sentinel check in upstream** (check if fix landed):
   ```bash
   # Check if _output_schema_processor now filters REFLECT_AND_RETRY_RESPONSE_TYPE
   grep -n 'REFLECT_AND_RETRY\|response_type\|ToolFailureResponse' .venv/lib/python3.12/site-packages/google/adk/flows/llm_flows/_output_schema_processor.py
   # If matches found: upstream may have fixed it; compare logic to our patch
   ```

5. **Runtime regression test** (contract tests):
   ```bash
   .venv/bin/python -m pytest tests_rlm_adk/ -x -q
   ```
   Specifically, the FMEA tests in `test_fmea_e2e.py` exercise BUG-13 via `_bug13_stats["suppress_count"]` delta assertions.

---

## 3. Callback Infrastructure Assessment

### Does "Reusable Function Extraction" Affect Our Callback Signatures?

**Risk: LOW.** Our callbacks use the documented public API:

- `after_tool_callback(tool, args, tool_context, tool_response)` -- set via `object.__setattr__` on `reasoning_agent` at `orchestrator.py:321`
- `on_tool_error_callback(tool, args, tool_context, error)` -- set via `object.__setattr__` at `orchestrator.py:322`
- `before_model_callback(callback_context, llm_request)` -- set directly on `reasoning_agent`
- `after_model_callback(callback_context, llm_response)` -- set directly on `reasoning_agent`

The HITL/auth refactoring is internal to `functions.py`'s preprocessing pipeline and should not change how agent-level callbacks are dispatched. The callback signatures are part of LlmAgent's public type annotations (`AfterToolCallback`, `OnToolErrorCallback`).

**One concern:** ADK v1.25.0 uses `agent.canonical_after_tool_callbacks` (a list) and iterates with `for callback in agent.canonical_after_tool_callbacks:`. If v1.27.0 changes how `canonical_after_tool_callbacks` is built from the single `after_tool_callback` field, our single-callback wiring via `object.__setattr__` could be affected. However, this is a Pydantic computed property on LlmAgent, not something the functions.py refactoring would change.

### Do Tool Callbacks in Live Mode Affect Us?

**Risk: NEGLIGIBLE for current usage, BENEFICIAL for future usage.**

RLM-ADK does not currently use Live (streaming) mode. The orchestrator delegates to `reasoning_agent.run_async(ctx)` which uses the standard `SingleFlow` path, not the Live path. Therefore, the Live mode callback fix has **no impact on current behavior**.

However, if RLM-ADK ever adopts streaming/Live mode, this fix means our `after_tool_cb` and `on_tool_error_cb` from `make_worker_tool_callbacks()` will fire correctly in Live mode too -- a net positive.

**Important note:** In v1.25.0 Live mode, `on_tool_error_callbacks` are **never fired** (the Live path has no error handling delegation). v1.27.0 presumably adds this. If we were using Live mode with the current codebase, structured output retry would silently fail because errors from `set_model_response` would never reach our `on_tool_error_cb`.

---

## 4. LiteLLM Improvements Assessment

### 4a. Output Schema with Tools for LiteLLM Models

**Impact: MEDIUM -- potential simplification opportunity.**

Currently, RLM-ADK manually wires `SetModelResponseTool` in `orchestrator.py:308-309`:
```python
set_model_response_tool = SetModelResponseTool(schema)
object.__setattr__(self.reasoning_agent, "tools", [repl_tool, set_model_response_tool])
```

This is necessary because `_OutputSchemaRequestProcessor` only auto-injects `SetModelResponseTool` when `can_use_output_schema_with_tools()` returns `False`. For Gemini via google.genai (not LiteLLM), the processor skips injection entirely.

If v1.27.0 makes `can_use_output_schema_with_tools()` return `True` for LiteLLM models, then when using LiteLLM, ADK would natively support `output_schema` alongside tools -- meaning we could set `output_schema=ReasoningOutput` on the `LlmAgent` directly instead of manually injecting `SetModelResponseTool`.

**However:** This would only apply to LiteLLM-routed models, not to the default Gemini path via `google.genai`. The default path already has `can_use_output_schema_with_tools() == True` for Vertex AI + Gemini 2+, but for API-key-based Gemini (non-Vertex), it returns `False`. Our manual `SetModelResponseTool` injection covers all cases uniformly.

**Action:** No immediate change needed. The manual injection is correct and portable across all model backends. If we want to simplify the LiteLLM path specifically, we could conditionally skip manual injection when using LiteLLM and set `output_schema` directly on the agent. But this creates two code paths and isn't worth the complexity.

### 4b. thought_signature Preservation

**Impact: LOW -- no action needed.**

`thought_signature` is a provider-specific field (Anthropic) attached to tool calls to maintain chain-of-thought continuity across multi-turn tool use. In v1.25.0, LiteLLM's message conversion drops this field. v1.27.0 preserves it.

RLM-ADK's reasoning callback (`reasoning.py`) extracts thought text from `part.thought` attributes on `types.Part` objects (line 84: `getattr(part, "thought", False)`). The `thought_signature` field is metadata on the tool call, not on the response parts. Our callback does not read or depend on it.

**One nuance:** If preserving `thought_signature` causes the LiteLLM conversion to produce additional thought parts in follow-up model responses (because the model "remembers" its chain of thought), our `_extract_response_text` would correctly capture them as `thought_parts` and record them in `REASONING_THOUGHT_TEXT` / `REASONING_THOUGHT_TOKENS`. This is a net positive.

### 4c. Reasoning Extraction Expanded to Include 'reasoning' Field

**Impact: NONE -- already present.**

Verified in the installed v1.25.0 `lite_llm.py:363`:
```python
for key in ("text", "content", "reasoning", "reasoning_content"):
```

The `"reasoning"` key is already in the extraction loop. Either this was backported before our v1.25.0 install, or the PR was merged into a version we already have. No code change needed.

**Token accounting impact:** Our `reasoning_after_model` reads `usage.thoughts_token_count` from `llm_response.usage_metadata` (line 193). This is populated by ADK's model layer regardless of which key the reasoning text was extracted from. If more reasoning text is extracted (due to new key support), `thoughts_token_count` would increase accordingly, which our accounting handles correctly.

---

## 5. Proposed Actions

### P0 -- Must Do Before Upgrade

| # | Action | Why | Files |
|---|--------|-----|-------|
| 1 | **Run BUG-13 verification script** (Section 2, steps 1-4) | Silent patch breakage is the highest-risk failure mode | `worker_retry.py`, ADK internals |
| 2 | **Run default contract test suite** | Catch any callback signature or behavior changes | `tests_rlm_adk/` |
| 3 | **Inspect `_output_schema_processor.py` diff** between v1.25.0 and v1.27.0 | Determine if upstream fixed BUG-13 or changed the patch target | ADK source |

### P1 -- Should Do After Upgrade

| # | Action | Why | Files |
|---|--------|-----|-------|
| 4 | **Check if BUG-13 is fixed upstream** -- if `get_structured_model_response` now filters `REFLECT_AND_RETRY_RESPONSE_TYPE`, remove the patch and add a version guard | Reduce maintenance burden of monkey-patching private APIs | `worker_retry.py` |
| 5 | **Verify `_bug13_stats["suppress_count"]`** in FMEA tests still increments (if patch still needed) or is zero (if upstream fixed) | Confirms patch/fix is operational | `test_fmea_e2e.py` |

### P2 -- Nice to Have

| # | Action | Why | Files |
|---|--------|-----|-------|
| 6 | **Evaluate native output_schema for LiteLLM path** | Could eliminate manual SetModelResponseTool injection for LiteLLM models | `orchestrator.py`, `agent.py` |
| 7 | **Add `thought_signature` awareness to dispatch telemetry** | Richer observability for Anthropic-via-LiteLLM reasoning chains | `dispatch.py`, `reasoning.py` |

### Not Needed

| Item | Why |
|------|-----|
| Callback signature updates | Public API unchanged |
| Live mode adaptation | RLM-ADK does not use Live mode |
| Reasoning extraction changes | Already present in v1.25.0 |
| JSON Schema boolean fix | No known impact on RLM-ADK schemas |

---

## 6. Opportunity Rating

| Dimension | Rating | Rationale |
|-----------|--------|-----------|
| **Effort** | **S** (Small) | Upgrade is `uv add google-adk>=1.27.0` + verification script + test run. No code changes required unless BUG-13 is fixed upstream (which would be a deletion, not a write). |
| **Impact** | **Medium** | Primary value is risk reduction (ensuring BUG-13 patch survives) and future-proofing (Live mode callbacks, LiteLLM improvements). No new features unlocked immediately. |
| **Risk** | **Medium** | The BUG-13 monkey-patch targets a private module that could silently break. The mitigation is the 4-step verification script above. If the patch breaks, structured output retry stops working for all agents (reasoning + children). The `try/except ImportError` guard prevents crashes but degrades retry capability. |

**Recommendation:** Upgrade to v1.27.0 with the P0 verification checklist. The callback and LiteLLM changes are net-positive with zero required code changes. The BUG-13 patch is the only risk vector and has a clear verification protocol.

---

## Appendix: Key File References

| File | Role in this analysis |
|------|----------------------|
| `rlm_adk/callbacks/worker_retry.py` (lines 238-288) | BUG-13 monkey-patch |
| `rlm_adk/callbacks/reasoning.py` | Thought text/token extraction |
| `rlm_adk/orchestrator.py` (lines 299-322) | Tool and callback wiring |
| `rlm_adk/dispatch.py` (line 58-97) | `_classify_error` for child dispatch |
| `rlm_adk/models/litellm_router.py` | LiteLLM Router integration |
| `rlm_adk/plugins/litellm_cost_tracking.py` | LiteLLM cost tracking plugin |
| `.venv/.../flows/llm_flows/_output_schema_processor.py` | BUG-13 patch target (ADK internal) |
| `.venv/.../flows/llm_flows/base_llm_flow.py` (lines 803, 849) | BUG-13 call sites |
| `.venv/.../flows/llm_flows/functions.py` (lines 585-730) | Live mode callback handling |
| `.venv/.../plugins/reflect_retry_tool_plugin.py` | `ReflectAndRetryToolPlugin` base class |
| `.venv/.../utils/output_schema_utils.py` | `can_use_output_schema_with_tools` gate |
