<!-- generated: 2026-03-19 -->
<!-- source: voice transcription via voice-to-prompt skill -->
# Experiment: Replace LLMResult + depth-scoped state reads with LlmResponse.custom_metadata and canonical after_model_callback

## Context

The current dispatch system (`rlm_adk/dispatch.py`) uses a complex state-reading pattern to extract child completion metadata: `_read_child_completion` reads depth-scoped keys like `session_state.get(depth_key(REASONING_VISIBLE_OUTPUT_TEXT, depth))` that were written by `reasoning_after_model` via `callback_context.state`. This works but creates tight coupling between callbacks and dispatch, requires the `_CHILD_PROPAGATION_KEYS` mechanism, and the `LLMResult(str)` subclass duplicates metadata already available on `LlmResponse`.

The ChatGPT BUG-13 assessment (`ai_docs/chatGPT_bug13_assessment.md`) confirms that **agent-level/canonical `after_model_callback`** receives a properly wired `CallbackContext` (bound to `model_response_event.actions`), meaning `callback_context.state[key] = value` correctly lands in the yielded event's `actions.state_delta`. Additionally, `LlmResponse.custom_metadata` is a supported dict field that propagates to the yielded `Event` via `_finalize_model_response_event` (which merges `llm_response.model_dump(exclude_none=True)` into the event). Together, these two ADK-native mechanisms could replace the current `LLMResult` + depth-scoped state reading pattern, simplifying `_read_child_completion` and eliminating `_CHILD_PROPAGATION_KEYS`.

This task is a **pre-implementation experiment** — a standalone proof-of-concept with a provider-fake fixture and e2e test script that demonstrates: (1) `custom_metadata` set in a canonical `after_model_callback` propagates to yielded events, (2) depth-scoped keys written via `callback_context.state` in a canonical callback arrive in child state deltas, (3) fan-out with multiple children at the same depth does not cause key collisions, and (4) the combination can carry all the metadata currently stored in `LLMResult`.

## Original Transcription

> review @ai_docs/chatGPT_bug13_assessment.md and inspect lines 95-133 of @rlm_adk/types.py and @rlm_adk/orchestrator.py. Then generate an implementation plan that replaces LLMResult with the adk-native llm_response.custom_metadata AND replaces all the instances of <var> = session_state.get(depth_key(<KEY_NAME>, depth)) or "" with the agent-level/canonical "after_model_callback" (NOT a plugin-level callback). I would like to see a plan AND subsequent pre-implementation experiment to show that custom_metadata can be used with child depth-scoping and fan-out, along with canonical agent/model callbacks, can simplify our current dispatch codebase. This is a direct challenge to the lines 56-64 or @rlm_adk_docs/dispatch_and_state.md; we do not need to right to ctx.session.state[key] since custom_metadata that is mutated by 'callback_context.state[key] = value' would not yield silent data loss. Your job is to plan and implement an experiment that uses a new provider-fake fixture and e2e python execution script to prototype and demonstrate we can do this without keys colliding

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

### Phase 1: Experiment Design and Fixture

1. **Spawn a `Fixture-Author` teammate to create the provider-fake fixture `tests_rlm_adk/fixtures/provider_fake/custom_metadata_experiment.json`.**

   This fixture must model a minimal 2-depth scenario: a root reasoning agent that dispatches 2 child queries (fan-out K=2), each child performing one REPL tool call then producing a `set_model_response` final answer. The fixture needs:
   - A root reasoning agent call (depth 0) that produces a `functionCall` for `execute_code` containing `llm_query_batched_async(["prompt_a", "prompt_b"])`
   - Two child reasoning agent sequences (depth 1, fanout_idx 0 and 1), each with:
     - One model response that calls `execute_code`
     - One model response that calls `set_model_response` with a structured answer
   - The child model responses must include `usageMetadata` with non-zero `promptTokenCount`, `candidatesTokenCount`, and `thoughtsTokenCount` (these are what `reasoning_after_model` reads)
   - A root final model response that calls `set_model_response` with the combined answer

   Reference existing fixture `structured_output_batched_k3.json` for the multi-child dispatch pattern. The fixture must exercise the full pipeline: root dispatch -> 2 concurrent children -> each child does REPL + final answer -> root collects results.

2. **Spawn a `Callback-Prototype` teammate to create the experimental `after_model_callback` in a new file `experiments/custom_metadata_callback.py`.**

   This callback replaces what `reasoning_after_model` in `rlm_adk/callbacks/reasoning.py` (lines 168-213) currently does, but uses `llm_response.custom_metadata` as the primary metadata transport instead of depth-scoped state keys. The callback must:

   a. Extract visible text and thought text from `llm_response.content.parts` (same logic as `_extract_response_text` at line 76)

   b. Read `usage_metadata` for token counts (same logic as lines 185-198)

   c. Read depth from `callback_context._invocation_context.agent._rlm_depth` (same logic as `_reasoning_depth` at line 91)

   d. **Instead of** writing to `callback_context.state[depth_key(REASONING_VISIBLE_OUTPUT_TEXT, depth)]` etc., pack all metadata into `llm_response.custom_metadata`:
   ```python
   llm_response.custom_metadata = {
       "rlm_depth": depth,
       "visible_output_text": visible_text,
       "thought_text": thought_text,
       "finish_reason": finish_reason,
       "input_tokens": input_tokens,
       "output_tokens": output_tokens,
       "thoughts_tokens": thought_tokens,
   }
   ```

   e. **Also** write to `callback_context.state` (the canonical path that correctly wires to `model_response_event.actions.state_delta`) so the experiment can verify both channels work:
   ```python
   callback_context.state[depth_key(REASONING_VISIBLE_OUTPUT_TEXT, depth)] = visible_text
   # ... etc for all keys
   ```

   f. Return `None` (observe-only, don't alter the response — same as production callback)

   **Critical constraint:** This must be an agent-level `after_model_callback` (set via `object.__setattr__(reasoning_agent, "after_model_callback", callback)`), NOT a plugin-level callback. The ChatGPT BUG-13 assessment confirms only the canonical path receives the wired `CallbackContext` (lines 1035-1036 of `base_llm_flow.py`).

3. **Spawn a `E2E-Script` teammate to create the experiment runner `experiments/test_custom_metadata_e2e.py`.**

   This is a standalone pytest test file (not integrated into the main test suite) that:

   a. Uses `create_rlm_runner()` from `rlm_adk/agent.py` to create a full pipeline with the provider-fake fixture from step 1

   b. Wires the experimental `after_model_callback` from step 2 onto the reasoning agent (both root and child agents)

   c. Runs the pipeline and collects all yielded events

   d. **Asserts the following experimental hypotheses:**

   **H1: custom_metadata propagates through events.** For each model response event, `event.custom_metadata` is not None and contains the expected keys (`rlm_depth`, `visible_output_text`, `input_tokens`, etc.).

   **H2: Depth-scoped state deltas arrive correctly.** For child events (depth 1), `event.actions.state_delta` contains the depth-scoped keys written by the canonical callback (e.g., `reasoning_visible_output_text@d1`).

   **H3: Fan-out does not cause key collisions.** With K=2 children at the same depth, each child's `custom_metadata` carries its own depth tag, and state deltas are isolated (child 0's tokens don't overwrite child 1's tokens) because children run in branched invocation contexts.

   **H4: custom_metadata can replace LLMResult metadata.** The experiment demonstrates that all fields currently carried by `LLMResult` (lines 110-122 of `rlm_adk/types.py`) — `error`, `error_category`, `http_status`, `finish_reason`, `input_tokens`, `output_tokens`, `thoughts_tokens`, `model`, `wall_time_ms`, `visible_text`, `thought_text`, `raw_output`, `parsed` — have equivalents available via `custom_metadata` + `event.actions.state_delta`, eliminating the need for the `LLMResult(str)` subclass.

   **H5: _read_child_completion can be simplified.** Instead of the current 100-line `_read_child_completion` function (lines 295-400 of `dispatch.py`) which reads from `_rlm_completion`, `_structured_result`, `output_key`, and multiple depth-scoped state keys, the experiment shows that a child's completion metadata can be read directly from the `custom_metadata` of the child's final model response event.

### Phase 2: Implementation Plan Document

4. **Spawn a `Plan-Author` teammate to create `experiments/PLAN_custom_metadata_migration.md` based on experimental results.**

   *[Added — the transcription asked for both a plan and an experiment; this step synthesizes the experiment results into a migration plan.]*

   After the experiment passes, this teammate writes a migration plan that:

   a. Maps each current `LLMResult` field to its `custom_metadata` / `state_delta` equivalent

   b. Identifies which parts of `_read_child_completion` (lines 295-400 of `dispatch.py`) can be replaced by reading `custom_metadata` from child events

   c. Identifies which parts of `_collect_reasoning_completion` (lines 142-196 of `orchestrator.py`) can be simplified

   d. Proposes a phased migration path: (1) add `custom_metadata` writing to production callback alongside existing state writes, (2) update `_read_child_completion` to prefer `custom_metadata`, (3) remove redundant state reads, (4) deprecate `LLMResult` in favor of a simpler dataclass

   e. Documents the AR-CRIT-001 implications: confirms that canonical `after_model_callback` state writes via `callback_context.state` are safe (not subject to the plugin BUG-13 wiring issue), and that `custom_metadata` on `LlmResponse` is an orthogonal data channel that doesn't interact with state delta tracking at all

## Provider-Fake Fixture & TDD

**Fixture:** `tests_rlm_adk/fixtures/provider_fake/custom_metadata_experiment.json`

**Essential requirements the fixture must capture:**
- The fixture must exercise fan-out dispatch (K=2) at depth 1 to prove key isolation across concurrent children — a single-child fixture would not test the collision hypothesis
- The fixture must include non-zero and *distinct* token counts per child (e.g., child 0: input=100, output=50; child 1: input=200, output=75) so the test can verify the correct tokens are associated with the correct child
- The fixture must include `usageMetadata` on model responses since `reasoning_after_model` reads from `llm_response.usage_metadata` — a fixture without usage metadata would silently produce all-zero token counts and the test would pass vacuously
- The fixture must exercise the `set_model_response` tool call path since that's how structured output produces `_structured_result`, which is one of the channels `_read_child_completion` currently reads from

**TDD sequence:**
1. Red: Write test asserting `event.custom_metadata` is not None on model response events. Run, confirm failure (no callback wired yet).
2. Green: Wire experimental `after_model_callback`, run, confirm `custom_metadata` populated.
3. Red: Write test asserting child 0 and child 1 have distinct token counts in their `custom_metadata`. Run, confirm pass (validates fan-out isolation).
4. Red: Write test asserting `event.actions.state_delta` contains depth-scoped keys from canonical callback. Run, confirm pass.
5. Red: Write mapping test asserting every `LLMResult` field has an equivalent in `custom_metadata` or `state_delta`. Run, confirm pass.

**Demo:** Run `uvx showboat` to generate an executable demo document proving the experiment passes end-to-end and all five hypotheses hold.

## Considerations

- **AR-CRIT-001 compliance:** The canonical `after_model_callback` path is safe — it receives `CallbackContext(invocation_context, event_actions=model_response_event.actions)` at line 1035-1036 of `base_llm_flow.py`. State writes via this path land in the yielded event's `actions.state_delta`. This is the documented and source-verified correct channel, unlike the plugin path (BUG-13).

- **custom_metadata is orthogonal to state_delta:** `custom_metadata` on `LlmResponse` propagates to `Event` via `_finalize_model_response_event` (line 98-101 of `base_llm_flow.py`) through `llm_response.model_dump(exclude_none=True)`. It does not interact with `EventActions.state_delta` at all — they are independent data channels. The experiment uses both to provide redundant verification.

- **Event.custom_metadata inherits from LlmResponse:** `Event(LlmResponse)` inherits the `custom_metadata` field at line 97 of `llm_response.py`. The `_finalize_model_response_event` function merges the LlmResponse fields into Event via Pydantic model_validate, so any `custom_metadata` set on the LlmResponse will appear on the yielded Event.

- **Branch isolation for fan-out:** The current `_run_child` in `dispatch.py` (line 452-454) creates a branched `child_ctx = ctx.model_copy()` for each child. This means children have isolated invocation contexts. The experiment must verify that depth-scoped state keys written by children don't collide despite sharing the same depth value, because they're in separate branches.

- **This experiment does NOT modify production code.** It creates new files in `experiments/` only. The migration plan (step 4) proposes production changes but does not implement them. This protects against regressions while proving the concept.

- **Existing tests must continue to pass.** Run `.venv/bin/python -m pytest tests_rlm_adk/` after the experiment to verify no regressions.

- **Do not use `-m ""` for test verification.** The default test suite (~28 contract tests) is sufficient for regression checking.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `ai_docs/chatGPT_bug13_assessment.md` | BUG-13 analysis | L1-100 | Confirms canonical callback is wired correctly, plugin callback is not |
| `rlm_adk/types.py` | `LLMResult` | L95-133 | String subclass carrying worker metadata — target for replacement |
| `rlm_adk/types.py` | `LLMResult.__new__` | L124-128 | How metadata fields are set via kwargs |
| `rlm_adk/orchestrator.py` | `_collect_reasoning_completion` | L142-196 | Current post-reasoning metadata normalization |
| `rlm_adk/orchestrator.py` | `RLMOrchestratorAgent._run_async_impl` | L230-614 | Orchestrator wiring reasoning_agent tools + callbacks |
| `rlm_adk/dispatch.py` | `_read_child_completion` | L295-400 | Current child completion reader — reads depth-scoped state keys |
| `rlm_adk/dispatch.py` | `_run_child` | L402-684 | Child lifecycle — builds `_child_state` from event state deltas |
| `rlm_adk/dispatch.py` | `_CHILD_PROPAGATION_KEYS` | L223-232 | Keys propagated from child state for dashboard visibility |
| `rlm_adk/dispatch.py` | `flush_fn` | L819-861 | Accumulator snapshot including child depth state merge |
| `rlm_adk/callbacks/reasoning.py` | `reasoning_after_model` | L168-213 | Current after_model_callback writing depth-scoped state keys |
| `rlm_adk/callbacks/reasoning.py` | `_reasoning_depth` | L91-96 | Reads `_rlm_depth` from agent via invocation context |
| `rlm_adk/callbacks/reasoning.py` | `_extract_response_text` | L76-88 | Splits visible/thought text from LlmResponse |
| `rlm_adk/state.py` | `depth_key()` | L42-48 | Depth-scoped state key helper |
| `rlm_adk_docs/dispatch_and_state.md` | AR-CRIT-001 | L56-64 | State mutation invariant being challenged |
| `.venv/.../base_llm_flow.py` | `_handle_after_model_callback` | L1004-1061 | Shows plugin vs canonical callback wiring (BUG-13) |
| `.venv/.../base_llm_flow.py` | `_finalize_model_response_event` | L80-110 | Merges LlmResponse into Event (custom_metadata propagation) |
| `.venv/.../llm_response.py` | `LlmResponse.custom_metadata` | L97-103 | The ADK-native metadata field |
| `rlm_adk/agent.py` | `create_child_orchestrator` | - | Factory for child orchestrators at depth+1 |

## Priming References

Before starting implementation, read these in order:
1. `repomix-architecture-flow-compressed.xml` — compressed source snapshot for structural context
2. `rlm_adk_docs/UNDERSTAND.md` — documentation entrypoint (follow "Dispatch & State" and "Core Loop" branches)
3. `ai_docs/chatGPT_bug13_assessment.md` — BUG-13 analysis confirming canonical callback safety
4. `rlm_adk/callbacks/reasoning.py` — current after_model_callback implementation (the baseline being challenged)
5. `rlm_adk/dispatch.py` lines 295-400 — `_read_child_completion` (the complexity being simplified)
6. `ai_docs/adk_api_reference.md` — verified ADK API signatures
