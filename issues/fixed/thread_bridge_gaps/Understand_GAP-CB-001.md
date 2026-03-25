# Polya Understand: GAP-CB-001

**`_extract_adk_dynamic_instruction` duplicates conversation history into system_instruction**

Status: **Fix never applied.** The demo doc (`issues/thread_bridge_gaps/demo_GAP-CB-001.md`) claims the function was deleted, but the code still contains it. This understand doc is verified against the current codebase as of 2026-03-25.

---

## A. Restate

The `reasoning_before_model` callback in `rlm_adk/callbacks/reasoning.py` calls `_extract_adk_dynamic_instruction()`, which reads ALL text from every `Content` in `llm_request.contents` -- the full conversation history including all prior tool calls, tool responses, model responses, and user messages -- concatenates it into a single string, and appends that string to `system_instruction` via `llm_request.append_instructions()`. This duplicates the entire conversation history into the system prompt. The function's docstring at line 50 claims it "extracts and removes" the dynamic instruction, but it never removes anything. ADK 1.27 already handles dynamic instruction placement correctly via its request processors, making this relocation unnecessary and actively harmful.

---

## B. Target

Delete the `_extract_adk_dynamic_instruction` function and the extraction+append logic in `reasoning_before_model`, leaving `reasoning_before_model` as a pure token-accounting callback that observes but does not modify the LLM request.

The deliverable is:
1. A clear specification for the code deletion.
2. Identification of all downstream dependencies that must be updated.
3. Confirmation that the fix is safe given ADK 1.27's native instruction handling.

---

## C. Givens

### C.1 ADK Request Processing Pipeline (verified from source)

The exact execution order for each LLM call within `_run_one_step_async` is:

1. **`_preprocess_async`** runs all request processors in order:
   - `basic.request_processor`
   - `auth_preprocessor.request_processor`
   - `request_confirmation.request_processor`
   - **`instructions.request_processor`** -- builds instructions
   - `identity.request_processor`
   - `compaction.request_processor`
   - **`contents.request_processor`** -- builds full conversation history
   - `context_cache_processor.request_processor`
   - `interactions_processor.request_processor`
   - `_nl_planning.request_processor`
   - `_code_execution.request_processor`
   - `_output_schema_processor.request_processor`

2. **`_call_llm_async`** is invoked:
   - **`_handle_before_model_callback`** fires (plugins first, then agent callbacks)
   - Actual LLM call
   - `_handle_after_model_callback`

Source: `.venv/lib/python3.12/site-packages/google/adk/flows/llm_flows/single_flow.py`, `base_llm_flow.py`.

### C.2 Instructions Processor Behavior

`instructions.request_processor` (`_build_instructions()` in `instructions.py`) handles three cases:

- **`instruction` set, no `static_instruction`**: Resolves template, appends to `system_instruction` via `append_instructions([si])`.
- **Both `instruction` and `static_instruction` set**: Resolves `static_instruction` into `system_instruction`, then creates a `user`-role `Content` for the dynamic instruction and appends it to `llm_request.contents`.
- **`static_instruction` only**: Appends to `system_instruction`.

The RLM reasoning agent uses **both** `static_instruction` and `instruction` (see `agent.py` lines 258-263). Therefore ADK places the static instruction into `system_instruction` and the dynamic instruction into `contents` as a user Content.

### C.3 Contents Processor Behavior

`contents.request_processor` runs AFTER `instructions.request_processor`. It:

1. Saves whatever is already in `llm_request.contents` as `instruction_related_contents` (this is the dynamic instruction Content from the instructions processor).
2. Replaces `llm_request.contents` with the full session event history via `_get_contents()`.
3. Re-inserts the saved `instruction_related_contents` at the correct position in the conversation via `_add_instructions_to_user_content()`.

So after contents processing, `llm_request.contents` contains: the full conversation history (all prior tool calls/responses, user messages, model responses) with the dynamic instruction content inserted at the appropriate position before the last user content batch.

### C.4 The Bug in `_extract_adk_dynamic_instruction` (lines 49-63 of reasoning.py)

```python
def _extract_adk_dynamic_instruction(llm_request: LlmRequest) -> str:
    """Extract the resolved instruction template that ADK placed in contents.

    When both static_instruction and instruction are set, ADK resolves the
    instruction template and appends it to contents as a user Content.
    We extract and remove it so it can be relocated to system_instruction.
    """
    dynamic_text = ""
    if llm_request.contents:
        for content in llm_request.contents:
            if content.parts:
                for part in content.parts:
                    if part.text:
                        dynamic_text += part.text
    return dynamic_text.strip()
```

This function iterates ALL contents and concatenates ALL text from ALL parts. By the time `reasoning_before_model` fires (step 2 above, after all request processors), `llm_request.contents` contains the entire conversation history. The function returns the concatenation of ALL text -- not just the dynamic instruction.

Then `reasoning_before_model` at lines 164-171 appends this blob to `system_instruction`:

```python
    # --- Extract dynamic instruction from contents ---
    dynamic_instruction = _extract_adk_dynamic_instruction(llm_request)

    # --- Append dynamic metadata to system_instruction ---
    # Uses append_instructions to preserve existing content (static instruction
    # + SkillToolset XML) that is already in system_instruction.
    if dynamic_instruction:
        llm_request.append_instructions([dynamic_instruction])
```

`append_instructions` (list[str] overload) concatenates with `\n\n` to the existing `system_instruction` string.

### C.5 The Agent Configuration (agent.py lines 258-276)

The reasoning agent is created with:
- `instruction=dynamic_instruction` (template with `{var?}` placeholders)
- `static_instruction=static_instruction` (stable system prompt)
- `before_model_callback=reasoning_before_model`
- `after_model_callback=reasoning_after_model`
- `on_model_error_callback=reasoning_on_model_error`

### C.6 The Test Hook Dependency (reasoning.py lines 264-308)

`reasoning_test_state_hook` (lines 264-308) patches content text in `llm_request.contents` and relies on `reasoning_before_model` running next to extract all content text into `system_instruction`. The comment at line 296-297 explicitly states:

> `reasoning_before_model runs next and extracts all content text into systemInstruction, so this patch flows through automatically.`

This hook is chained before `reasoning_before_model` in `_wire_test_hooks()` (contract_runner.py lines 75-79). It patches a placeholder `"Callback state: \n"` in contents to include the test state dict, and relies on the (buggy) full-contents extraction to move that patched text into `system_instruction`.

The chaining mechanism in `contract_runner.py`:

```python
def chained_reasoning_before_model(callback_context, llm_request):
    reasoning_test_state_hook(callback_context, llm_request)
    if original_reasoning_cb:
        return original_reasoning_cb(callback_context=callback_context, llm_request=llm_request)
    return reasoning_before_model(callback_context, llm_request)
```

### C.7 The Fixture Dependency

Only one fixture uses `test_hooks=true`: `tests_rlm_adk/fixtures/provider_fake/request_body_comprehensive.json`. This fixture:
- Sets `"test_hooks": true` in its config
- Uses initial state with guillemet-marked dict structures
- Is exercised by `test_fixture_contract[request_body_comprehensive]` in `test_provider_fake_e2e.py` (parametrized over all fixture files not in the exclusion set)
- Was also exercised by `test_request_body_comprehensive.py` which has been deleted (only `.pyc` cache remains)

The fixture's `expected_contract` asserts on tool results, stdout contents, variable persistence, and worker response chaining. It does NOT directly assert on system instruction content in its JSON expectations. The test hook's effect is that it writes to `callback_context.state[CB_REASONING_CONTEXT]`, which flows into the dynamic instruction template via `{cb_reasoning_context?}` -- but the fixture expectations verify state and REPL behavior, not system instruction text.

### C.8 The Docstring vs. Reality

The docstring at line 50-55 says: *"We extract and remove it so it can be relocated to system_instruction."* But the function never removes anything from contents. It only reads. The "remove" claim is false.

### C.9 The Dynamic Instruction Template Augmentation (contract_runner.py lines 256-267)

When `test_hooks=true`, `_make_runner_and_session()` appends placeholder lines to the dynamic instruction:

```python
dynamic_instruction = (
    RLM_DYNAMIC_INSTRUCTION
    + "Callback state: {cb_reasoning_context?}\n"
    + "Orchestrator state: {cb_orchestrator_context?}\n"
    + "Tool state: {cb_tool_context?}\n"
)
```

ADK resolves these `{key?}` placeholders from session state. On iteration 0, `cb_reasoning_context` is not yet in state, so the placeholder resolves to empty. The `reasoning_test_state_hook` then patches the resolved text in contents, replacing `"Callback state: \n"` with `"Callback state: {dict}\n"`, so the dict appears on the FIRST iteration too.

### C.10 Token Accounting Measurement Order (reasoning.py lines 138-151)

Token accounting currently measures `system_chars` and `total_prompt_chars` BEFORE the `append_instructions` call at line 171. This means `system_chars` reflects the pre-modification system instruction (static instruction + SkillToolset XML), and `total_prompt_chars` reflects the full contents. The accounting is therefore already correct relative to the LLM's actual input -- the `append_instructions` at line 171 modifies system_instruction AFTER measurement, so the duplicated text is NOT double-counted in the accounting metrics. However, the duplication still wastes tokens sent to the model.

---

## D. Conditions / Constraints

1. **Must not break token accounting.** The `reasoning_before_model` callback computes `total_prompt_chars`, `system_chars`, `content_count` for observability (lines 142-151). Since accounting is measured BEFORE the append, removing the append does not change accounting values. This is a no-op for accounting.

2. **Must not break `reasoning_test_state_hook`.** This hook explicitly relies on the bug (line 296-297 comment). When the extraction+append is removed, the patched text in contents will no longer be duplicated into `system_instruction`. The hook itself writes to `callback_context.state[CB_REASONING_CONTEXT]` which is the correct behavior. The only question is whether any test expects the patched text to appear in `system_instruction`. The fixture's JSON expectations do not assert on system instruction content -- they assert on state, tool results, and stdout. So the hook can be simplified to just write to state.

3. **Must not break SkillToolset.** The docstring at lines 130-133 warns about using `append_instructions()` instead of direct assignment to preserve SkillToolset XML. Removing the extraction+append entirely eliminates this concern -- SkillToolset XML in `system_instruction` is left untouched.

4. **ADK manages contents correctly.** ADK's `_add_instructions_to_user_content` already positions the dynamic instruction content at the right place in the conversation. There is no need to relocate it.

5. **Must not break the `request_body_comprehensive` fixture.** The fixture is currently exercised by `test_fixture_contract[request_body_comprehensive]` in `test_provider_fake_e2e.py`. Its JSON expectations verify state, tool results, variable persistence, and stdout -- NOT system instruction content.

---

## E. Unknowns

### E.1 Was the relocation ever necessary?

The docstring mentions "Gemini role alternation" as a motivation. In older ADK versions, placing dynamic instruction as user content might have caused role-alternation violations (user-user consecutive contents). In ADK 1.27, `_add_instructions_to_user_content` handles positioning explicitly, inserting before the last continuous batch of user content. This is correct behavior.

**Judgment**: The relocation was a workaround for an older ADK version's content handling. It is no longer necessary.

### E.2 Does any captured-request test assert on system instruction content?

The `captured_requests_comprehensive.json` file in `tests_rlm_adk/provider_fake/build_docs/` contains captured request data that might reference system instruction content. However, this is a build doc (documentation artifact), not a test assertion source. The actual test assertions come from the fixture JSON's `expected` and `expected_contract` fields, which do not assert on system instruction content.

### E.3 Does the comment in `reasoning_test_state_hook` need updating?

Yes. Lines 294-297 say the patched text "flows through automatically" via `reasoning_before_model`. After the fix, this comment is wrong. The hook should be updated to remove this reliance claim. The hook's actual purpose (writing to `callback_context.state`) is independent of the extraction+append behavior.

---

## F. Definitions

- **`system_instruction`**: The system-level prompt sent via `GenerateContentConfig.system_instruction`. The model sees this as system context, separate from the conversation.
- **`contents`**: The conversation history sent as `llm_request.contents`. Includes user messages, model responses, tool calls/responses, and any instruction-related user Content that ADK injected.
- **`append_instructions()`**: Method on `LlmRequest` that concatenates strings to `system_instruction` with `\n\n` separator.
- **Request processors**: ADK pipeline stages that run BEFORE `before_model_callback`. They build the system instruction, conversation history, tool declarations, etc.
- **`CB_REASONING_CONTEXT`**: State key (`"cb_reasoning_context"`) used by `reasoning_test_state_hook` to store a guillemet-marked dict.
- **`test_hooks`**: Fixture config flag that enables test state hooks for verifying callback -> state -> systemInstruction flow in provider-fake runs.

---

## G. Representation

### Pipeline Execution Order (per LLM call) -- Current (Buggy)

```
instructions.request_processor
  |
  +--> static_instruction --> system_instruction
  +--> dynamic instruction --> contents (as user Content)
  |
contents.request_processor
  |
  +--> saves instruction contents
  +--> replaces contents with full session history
  +--> re-inserts instruction contents at correct position
  |
[... other processors ...]
  |
before_model_callback (reasoning_before_model)
  |
  +--> token accounting (reads system_instruction + contents BEFORE modification)
  |
  +--> _extract_adk_dynamic_instruction()            [LINE 165]
  |      reads ALL contents text (history + dynamic instruction)
  |      returns concatenation of everything
  |
  +--> append_instructions([gigantic_blob])           [LINE 171]
  |      appends to system_instruction
  |
  +--> Result: system_instruction now contains:
  |      static_instruction + SkillToolset XML + ENTIRE_CONVERSATION_HISTORY
  |      (and contents ALSO contains the full history -- duplication)
  |
LLM call (model receives duplicated text)
```

### After Fix

```
instructions.request_processor
  +--> static_instruction --> system_instruction
  +--> dynamic instruction --> contents (as user Content)
  |
contents.request_processor
  +--> full conversation history + dynamic instruction in contents
  |
before_model_callback (reasoning_before_model)
  +--> token accounting only (reads clean system_instruction + contents)
  +--> stores request metadata on agent
  +--> returns None (observe only, no modification)
  |
LLM call (model receives clean, non-duplicated request)
```

---

## H. Assumptions

| # | Assumption | Risk |
|---|-----------|------|
| 1 | ADK 1.27's `_add_instructions_to_user_content` correctly positions dynamic instruction in contents for all multi-turn scenarios | LOW -- verified from source, handles role alternation |
| 2 | No other code outside `reasoning_before_model` relies on the dynamic instruction being duplicated into `system_instruction` | LOW -- grep confirms only the test hook depends on this |
| 3 | The `request_body_comprehensive` fixture is the only test fixture affected (only fixture with `test_hooks=true`) | LOW -- grep confirms `test_hooks` appears in only one fixture |
| 4 | Token accounting becoming more accurate (no duplicated text sent to model) will not break any observability assertions | LOW -- accounting is already measured before the append, so values do not change |
| 5 | The `test_request_body_comprehensive.py` test file deletion means there are no additional test assertions beyond the parametrized contract test | LOW -- confirmed only `.pyc` remains, the `.py` is gone |

---

## I. Well-Posedness

**Well-posed.** The problem is fully specified:

- The root cause is clear: `_extract_adk_dynamic_instruction` reads all contents, not just the dynamic instruction.
- The docstring's claim of "extract and remove" is provably false (no removal code exists).
- The fix is deterministic: delete `_extract_adk_dynamic_instruction()` (lines 49-63), remove the extraction+append block (lines 164-171), update `reasoning_test_state_hook` comment (lines 294-297), and verify the `request_body_comprehensive` fixture still passes.
- No external dependencies or ambiguous requirements.
- The demo doc (`issues/thread_bridge_gaps/demo_GAP-CB-001.md`) already describes the intended end state -- it just was never applied to the code.

---

## J. Success Criteria

1. **`_extract_adk_dynamic_instruction` is deleted.** The function at lines 49-63 no longer exists. No code reads all contents text and appends it to system_instruction.

2. **`reasoning_before_model` does token accounting only.** It reads `system_instruction` and `contents` for character counts, stores request metadata on the agent, and returns `None` without modifying `llm_request`.

3. **`reasoning_before_model` docstring is updated.** It no longer claims to "append dynamic instruction to system_instruction" (current line 116). It should describe itself as a pure token-accounting / request-metadata observer.

4. **`reasoning_test_state_hook` comment is updated.** Lines 294-297 no longer claim that `reasoning_before_model` extracts content text into systemInstruction. The hook's actual behavior (writing to `callback_context.state`) does not depend on the buggy extraction.

5. **`request_body_comprehensive` fixture passes.** The parametrized `test_fixture_contract[request_body_comprehensive]` in `test_provider_fake_e2e.py` still passes.

6. **All other contract tests pass** (excluding the pre-existing exclusions in `_WORKER_FIXTURE_EXCLUSIONS`).

7. **`system_instruction` sent to the model is clean.** After the fix, `system_instruction` contains only: static instruction + SkillToolset XML (if skills enabled). No conversation history duplication.

---

## Problem Type

**Dead code / legacy workaround removal.** The extraction+append logic was a workaround for an earlier ADK version's content handling. ADK 1.27 handles instruction positioning natively. The workaround now causes harmful duplication -- the entire conversation history is duplicated into `system_instruction` on every LLM call, wasting tokens proportional to conversation length. The fix is deletion plus downstream comment cleanup.

---

## Edge Cases

1. **First turn (minimal history)**: Contents has only the initial user prompt + dynamic instruction. Duplication is small but still incorrect -- dynamic instruction text appears in both system_instruction and contents.

2. **Multi-turn with tool calls**: Contents grows with every tool call/response. The entire accumulated history gets duplicated into system_instruction. This is where the bug causes the most damage -- potentially megabytes of duplicated text sent to the model, consuming context window and money.

3. **Skills enabled**: SkillToolset appends L1 XML to system_instruction BEFORE `reasoning_before_model` fires. The current code preserves this via `append_instructions()`. After the fix, SkillToolset XML is also preserved because we simply stop calling `append_instructions()` at all -- the XML remains in system_instruction undisturbed.

4. **Child orchestrators**: Child reasoning agents use `include_contents="none"`, which limits contents to current-turn only. The bug still affects them (current turn contents get duplicated into system_instruction) but the blast radius is smaller.

5. **`reasoning_test_state_hook` patching**: The hook patches the placeholder `"Callback state: \n"` in contents (line 299-307). After the fix, this patched text stays in contents (where the model sees it anyway) but is no longer also duplicated into `system_instruction`. The test hook still writes `CB_REASONING_CONTEXT` to state correctly, and ADK resolves `{cb_reasoning_context?}` on subsequent iterations from state. The only difference: on iteration 0, the patched text in contents is visible to the model in contents but not in system_instruction. This should not affect any fixture assertions since none assert on system instruction content.

---

## Files to Modify

| File | Change |
|------|--------|
| `rlm_adk/callbacks/reasoning.py` (lines 49-63) | Delete `_extract_adk_dynamic_instruction()` function. |
| `rlm_adk/callbacks/reasoning.py` (lines 113-173) | Remove extraction+append logic from `reasoning_before_model()` (lines 164-171). Update docstring (lines 116-133) to describe the callback as pure token-accounting / request-metadata observer. |
| `rlm_adk/callbacks/reasoning.py` (lines 294-297) | Update comment in `reasoning_test_state_hook` to remove the claim about `reasoning_before_model` extracting content text into systemInstruction. |
| `tests_rlm_adk/fixtures/provider_fake/request_body_comprehensive.json` | Verify fixture still passes. Update expectations only if any currently assert on system instruction content (current analysis: they do not). |

---

## Summary

`_extract_adk_dynamic_instruction` is a legacy workaround at `rlm_adk/callbacks/reasoning.py` lines 49-63 that now causes active harm. It reads the entire conversation history (not just the dynamic instruction) and duplicates it into `system_instruction` on every LLM call. ADK 1.27 already handles dynamic instruction placement correctly through its request processors. The fix was specified in the original understand doc (`issues/thread_bridge_gaps/Understand_GAP-CB-001.md`) and described as completed in the demo doc (`issues/thread_bridge_gaps/demo_GAP-CB-001.md`), but was **never applied to the source code**. The function and its invocation still exist. The fix is to delete the function, remove the extraction+append block (lines 164-171), update docstrings and comments, and verify that the `request_body_comprehensive` fixture continues to pass.
