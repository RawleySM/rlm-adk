# Dynamic Instruction Design — User Context Injection and Verification

**Author**: Dynamic-Instructor Agent
**Date**: 2026-03-24
**Status**: Design Plan (not yet implemented)

---

## Overview

This document specifies how user-provided context flows into the ADK dynamic instruction (`RLM_DYNAMIC_INSTRUCTION`), how to seed that context through the `skill_arch_test.json` fixture's `initial_state`, and how to verify that template placeholders are resolved correctly in the outgoing `systemInstruction` that the LLM model receives.

The design covers:
1. The `initial_state` config block for the `skill_arch_test.json` fixture
2. How each `{var?}` placeholder is resolved at runtime
3. What the test runner should capture from the `llm_request` and assert
4. Example resolved `systemInstruction` content
5. Test assertions that verify the full dynamic instruction flow
6. A proposed `EXPOSED_STATE_KEYS` extension so `_rlm_state` also surfaces the manifest

---

## 1. Background: How Dynamic Instruction Resolution Works

### 1.1 The template

`RLM_DYNAMIC_INSTRUCTION` (`rlm_adk/utils/prompts.py:93`) is:

```
Repository URL: {repo_url?}
Original query: {root_prompt?}
Additional context: {test_context?}
Skill instruction: {skill_instruction?}
User context: {user_ctx_manifest?}
```

This string is passed as `instruction=` to the `LlmAgent` (not `static_instruction=`). ADK processes `instruction=` templates by substituting `{var?}` placeholders with matching session state keys at the time of each model call. Missing keys are silently omitted (the `?` suffix).

### 1.2 State keys and their placeholder names

| Placeholder in template | State key constant | Key string |
|---|---|---|
| `{repo_url?}` | `DYN_REPO_URL` | `"repo_url"` |
| `{root_prompt?}` | `DYN_ROOT_PROMPT` | `"root_prompt"` |
| `{test_context?}` | *(no constant — raw key)* | `"test_context"` |
| `{skill_instruction?}` | `DYN_SKILL_INSTRUCTION` | `"skill_instruction"` |
| `{user_ctx_manifest?}` | `DYN_USER_CTX_MANIFEST` | `"user_ctx_manifest"` |

### 1.3 Orchestrator's Path B for pre-seeded context

When `initial_state` contains `user_provided_ctx` (a dict), the orchestrator's Path B code block (`orchestrator.py:428-468`) runs:

1. Reads the dict from `ctx.session.state[USER_PROVIDED_CTX]`
2. Builds a manifest string from the dict's keys and their char counts
3. Writes `initial_state[DYN_USER_CTX_MANIFEST]` with the manifest string
4. Writes `initial_state[USER_PROVIDED_CTX_EXCEEDED]`, `USR_PROVIDED_FILES_SERIALIZED`, `USR_PROVIDED_FILES_UNSERIALIZED`
5. Pre-loads `repl.globals["user_ctx"] = _pre_seeded`
6. Yields `Event(actions=EventActions(state_delta=initial_state))`

After this event is processed by the ADK Runner, all state keys are available for template resolution on the first model call.

---

## 2. `initial_state` Config Block for `skill_arch_test.json`

The fixture's `config` section needs an `initial_state` block that seeds all five dynamic instruction placeholders plus the user context dict.

```json
"initial_state": {
  "user_provided_ctx": {
    "arch_context.txt": "Architecture validation context: this is a provider-fake e2e test for the rlm_adk pipeline. The test validates skill expansion, child dispatch, and dynamic instruction resolution.",
    "test_metadata.json": "{\"scenario\": \"skill_arch_test\", \"pipeline\": \"provider_fake\", \"depth\": 0}"
  },
  "repo_url": "https://test.example.com/arch-test",
  "root_prompt": "Run the architecture introspection skill and verify all pipeline components.",
  "test_context": "Provider-fake e2e run: skill expansion + child dispatch + dynamic instruction verification.",
  "skill_instruction": "Use run_test_skill() from rlm_repl_skills.test_skill to exercise the full pipeline."
}
```

### Why each key is included

- **`user_provided_ctx`**: Triggers Path B in the orchestrator, which builds `user_ctx_manifest` and pre-loads `repl.globals["user_ctx"]`. Without this, `{user_ctx_manifest?}` resolves to empty.
- **`repo_url`**: Seeds both `REPO_URL` (for context metadata callbacks) and `DYN_REPO_URL` (for `{repo_url?}` resolution). The orchestrator writes both when `self.repo_url` is set, but since we're seeding via `initial_state` directly, both keys must be present.
- **`root_prompt`**: Seeds both `ROOT_PROMPT` and `DYN_ROOT_PROMPT`. Same dual-write pattern.
- **`test_context`**: A raw session state key that maps directly to `{test_context?}`. No constant in `state.py` — it's a plain string key.
- **`skill_instruction`**: Seeds `DYN_SKILL_INSTRUCTION` which maps to `{skill_instruction?}`. In normal operation the orchestrator's `instruction_router` sets this; here we seed it directly so the test verifies end-to-end template resolution without needing a skill router.

### Critical note on orchestrator dual-write

The orchestrator at lines 376-381 writes both `ROOT_PROMPT` and `DYN_ROOT_PROMPT` (same string, different keys). When seeding via `initial_state`, the orchestrator's `if self.root_prompt:` branch does NOT fire (because `self.root_prompt` is `None` — the fixture runner doesn't set it as a constructor field). This means:

- `root_prompt` in `initial_state` flows through as a raw session state key
- Since `DYN_ROOT_PROMPT = "root_prompt"` (same string), the single key `"root_prompt"` in `initial_state` is sufficient for both the observability callbacks and the template resolution
- Same for `repo_url` / `DYN_REPO_URL`

This is not a bug — it is why the key constants are named identically to their string values.

---

## 3. How Each Template Placeholder Gets Resolved

ADK resolves `{var?}` placeholders in the `instruction=` string by looking up `var` in the session state at model-call time. The state is populated by the time the first model call fires because the orchestrator yields its `initial_state` event before delegating to `reasoning_agent.run_async(ctx)`.

### Resolution chain per placeholder

**`{repo_url?}` → `"https://test.example.com/arch-test"`**

Flow:
1. `initial_state["repo_url"] = "https://test.example.com/arch-test"` (from fixture config)
2. Orchestrator yields `Event(state_delta=initial_state)` — ADK Runner writes to `ctx.session.state["repo_url"]`
3. First model call: ADK resolves `{repo_url?}` → `"https://test.example.com/arch-test"`

**`{root_prompt?}` → `"Run the architecture introspection skill..."`**

Flow: identical to `repo_url` above, using key `"root_prompt"`.

**`{test_context?}` → `"Provider-fake e2e run: skill expansion..."`**

Flow: `initial_state["test_context"]` is passed directly through. No orchestrator rewrite touches this key.

**`{skill_instruction?}` → `"Use run_test_skill() from rlm_repl_skills.test_skill..."`**

Flow: `initial_state["skill_instruction"]` seeds the key. The `_seed_skill_instruction` before_agent_callback is only wired when `instruction_router` is not None; in the fixture run it is None, so the key is set only through the initial state event. This is sufficient for template resolution since the event is processed before the first model call.

**`{user_ctx_manifest?}` → multi-line manifest string**

Flow:
1. `initial_state["user_provided_ctx"]` = dict with `arch_context.txt` and `test_metadata.json`
2. Orchestrator's Path B code runs (`ctx.session.state.get(USER_PROVIDED_CTX)` returns the pre-seeded dict)
3. Path B builds the manifest string:
   ```
   Pre-loaded context variable: user_ctx (dict)
   Pre-loaded files (access via user_ctx["<filename>"]):
     - arch_context.txt (N chars)
     - test_metadata.json (N chars)
   Total: 2 files, 2 pre-loaded
   ```
4. Path B writes `initial_state[DYN_USER_CTX_MANIFEST]` = that manifest string
5. The merged state delta event includes `"user_ctx_manifest"` = manifest
6. ADK resolves `{user_ctx_manifest?}` to the manifest string on the first model call

### Sequencing guarantee

The orchestrator yields `Event(state_delta=initial_state)` synchronously before entering the retry loop for `reasoning_agent.run_async(ctx)`. ADK's Runner processes this event and applies the state delta before the reasoning agent's first step. Therefore all five placeholders are in session state before the first `systemInstruction` is assembled.

---

## 4. What the Runner Should Capture from `llm_request`

### 4.1 Where `systemInstruction` lives in the LLM request

In ADK, the `LlmRequest` object (passed to `before_model_callback`) contains the assembled request that will be sent to the Gemini API. The `systemInstruction` field corresponds to `llm_request.config.system_instruction` — this is where ADK places the combined `static_instruction` + resolved `instruction=` template.

The FakeGeminiServer receives the raw POST body at `/v1beta/models/{model}:generateContent`. In that body, the `systemInstruction` key holds the assembled system prompt including the resolved template.

### 4.2 Capturing from `before_model_callback`

The test runner captures the `llm_request` from the reasoning agent's `before_model_callback`. The existing `reasoning_before_model` callback (`rlm_adk/callbacks/reasoning.py`) does not currently expose the full `systemInstruction` to session state, but the `test_hooks` mechanism in `contract_runner.py` already chains a custom `chained_reasoning_before_model`.

The instrumented runner for dynamic instruction verification should:

```python
captured_system_instructions: list[str] = []

def dyn_instr_capture_hook(callback_context, llm_request):
    """Capture systemInstruction text before each model call."""
    # ADK stores the assembled system instruction as a Content object.
    # The text is in llm_request.config.system_instruction.parts[0].text
    # or equivalently in the serialized "systemInstruction" field.
    sys_instr = getattr(llm_request, "config", None)
    if sys_instr is not None:
        si = getattr(sys_instr, "system_instruction", None)
        if si is not None and hasattr(si, "parts"):
            full_text = "\n".join(
                p.text for p in si.parts if hasattr(p, "text")
            )
            captured_system_instructions.append(full_text)
            # Also write to session state for assertability after run
            callback_context.state["_captured_system_instruction_0"] = full_text[:2000]
    return None  # do not short-circuit
```

This hook is chained before the existing `reasoning_before_model` callback, exactly like `reasoning_test_state_hook` in `contract_runner.py`.

### 4.3 The FakeGeminiServer's captured request bodies

`FakeGeminiServer` does not currently expose a log of captured request bodies for post-run inspection. However:

1. The `ScenarioRouter.next_response()` receives the full request body
2. The `FakeGeminiServer._handle_generate_content` logs `bool(body.get("systemInstruction"))` at DEBUG level

To capture request bodies for assertions, the `ScenarioRouter` can store them:

```python
# In ScenarioRouter (tests_rlm_adk/provider_fake/fixtures.py):
self._captured_requests: list[dict] = []  # populated by next_response()

def next_response(self, request_body, request_meta=None):
    self._captured_requests.append(request_body)  # store for inspection
    ...
```

Then in the test:
```python
router = result.router
first_request = router._captured_requests[0]
system_instruction_content = first_request.get("systemInstruction", {})
# system_instruction_content is {"role": "user", "parts": [{"text": "..."}]}
# or {"parts": [{"text": "..."}]} depending on ADK version
si_text = "".join(
    p.get("text", "") for p in system_instruction_content.get("parts", [])
)
```

For the dynamic instruction test, the `before_model_callback` hook approach is preferred over parsing the `ScenarioRouter`'s captured requests, because the callback gives direct access to the already-assembled `LlmRequest` before serialization.

---

## 5. Example `systemInstruction` After Template Resolution

After all state keys are populated, ADK assembles `systemInstruction` as:

```
[RLM_STATIC_INSTRUCTION content — ~80 lines of tool descriptions and strategy patterns]

Repository URL: https://test.example.com/arch-test
Original query: Run the architecture introspection skill and verify all pipeline components.
Additional context: Provider-fake e2e run: skill expansion + child dispatch + dynamic instruction verification.
Skill instruction: Use run_test_skill() from rlm_repl_skills.test_skill to exercise the full pipeline.
User context: Pre-loaded context variable: user_ctx (dict)
Pre-loaded files (access via user_ctx["<filename>"]):
  - arch_context.txt (N chars)
  - test_metadata.json (N chars)
Total: 2 files, 2 pre-loaded
```

### What must NOT appear in the resolved systemInstruction

If placeholder resolution failed, the raw template syntax would appear:

```
Repository URL: {repo_url?}          ← WRONG: placeholder not resolved
User context: {user_ctx_manifest?}   ← WRONG: placeholder not resolved
```

The test assertions must confirm the literal brace syntax is absent.

---

## 6. Test Assertions That Verify Dynamic Instruction Flow

### 6.1 State-level assertions (via `expected_state` in fixture JSON)

These run through `ScenarioRouter.check_expectations()` after the run:

```json
"expected_state": {
  "user_provided_ctx": {
    "$not_none": true
  },
  "user_ctx_manifest": {
    "$contains": "arch_context.txt"
  },
  "user_ctx_manifest": {
    "$contains": "test_metadata.json"
  },
  "usr_provided_files_serialized": {
    "$type": "list",
    "$not_empty": true
  },
  "user_provided_ctx_exceeded": false,
  "repo_url": {
    "$contains": "test.example.com"
  },
  "root_prompt": {
    "$contains": "architecture introspection"
  },
  "skill_instruction": {
    "$contains": "run_test_skill"
  }
}
```

### 6.2 Captured `systemInstruction` assertions (via custom runner hook)

In the test module (`test_skill_arch_e2e.py`), after running the fixture:

```python
def _extract_system_instruction_text(events: list) -> str | None:
    """Extract the _captured_system_instruction_0 state key from final state."""
    # Written by dyn_instr_capture_hook to session state after first model call.
    # Access via plugin_result.final_state.
    return plugin_result.final_state.get("_captured_system_instruction_0")

# --- Core dynamic instruction assertions ---

si_text = _extract_system_instruction_text(plugin_result.events)
assert si_text is not None, "No system instruction captured"

# 1. No unresolved placeholders remain
assert "{repo_url?}" not in si_text, "repo_url placeholder not resolved"
assert "{root_prompt?}" not in si_text, "root_prompt placeholder not resolved"
assert "{test_context?}" not in si_text, "test_context placeholder not resolved"
assert "{skill_instruction?}" not in si_text, "skill_instruction placeholder not resolved"
assert "{user_ctx_manifest?}" not in si_text, "user_ctx_manifest placeholder not resolved"

# 2. Resolved values are present
assert "https://test.example.com/arch-test" in si_text, "repo_url value missing"
assert "architecture introspection" in si_text, "root_prompt value missing"
assert "Provider-fake e2e run" in si_text, "test_context value missing"
assert "run_test_skill" in si_text, "skill_instruction value missing"
assert "arch_context.txt" in si_text, "user_ctx_manifest filename missing"
assert "test_metadata.json" in si_text, "user_ctx_manifest filename missing"
assert "Pre-loaded context variable: user_ctx" in si_text, "manifest header missing"

# 3. Print verification tags for debugging
for key, value in [
    ("DYN_INSTR:repo_url", "https://test.example.com/arch-test"),
    ("DYN_INSTR:root_prompt_resolved", str("architecture introspection" in si_text)),
    ("DYN_INSTR:manifest_resolved", str("arch_context.txt" in si_text)),
    ("DYN_INSTR:no_raw_placeholders", str("{repo_url?}" not in si_text)),
]:
    print(f"[{key}={value}]")
```

### 6.3 REPL-level assertions via `_rlm_state` (requires EXPOSED_STATE_KEYS extension)

If `EXPOSED_STATE_KEYS` is extended (see Section 7), the `test_skill`'s `_rlm_state` snapshot will include `user_ctx_manifest` and the test can assert:

```python
# From [TEST_SKILL:state_keys=...] stdout tag:
tags = _parse_test_skill_tags(repl_stdout)
assert "user_ctx_manifest" in tags["state_keys"], \
    "user_ctx_manifest not visible in _rlm_state"

# From _rlm_state dict inside the skill:
# state_snapshot["user_ctx_manifest"] should contain "arch_context.txt"
```

Without the extension, `user_ctx_manifest` is only verifiable from session state post-run (already covered by 6.1 above) and from the captured `systemInstruction` text (covered by 6.2).

### 6.4 `user_ctx` REPL global assertion

The fixture's REPL code should access `user_ctx` to prove Path B loaded it:

```python
# In a fixture response, REPL code verifies user_ctx is available:
"code": "print(list(user_ctx.keys()))\nprint(user_ctx['arch_context.txt'][:50])"
```

This produces stdout like:
```
['arch_context.txt', 'test_metadata.json']
Architecture validation context: this is a provide
```

The fixture's `tool_results.stdout_contains` can then assert:
```json
"tool_results": {
  "stdout_contains": ["arch_context.txt", "Architecture validation context"]
}
```

---

## 7. Proposed `EXPOSED_STATE_KEYS` Extension

The Skill-Proposer (Task #1) proposed extending `EXPOSED_STATE_KEYS` in `state.py` to include `DYN_USER_CTX_MANIFEST` and `DYN_SKILL_INSTRUCTION` so they appear in `_rlm_state` inside REPL code.

### Recommended minimal extension

```python
# In rlm_adk/state.py — EXPOSED_STATE_KEYS:
EXPOSED_STATE_KEYS: frozenset[str] = frozenset(
    {
        ITERATION_COUNT,
        CURRENT_DEPTH,
        APP_MAX_ITERATIONS,
        APP_MAX_DEPTH,
        LAST_REPL_RESULT,
        STEP_MODE_ENABLED,
        SHOULD_STOP,
        FINAL_RESPONSE_TEXT,
        # Extensions for dynamic instruction verification:
        DYN_USER_CTX_MANIFEST,    # "user_ctx_manifest" — manifest of loaded files
        DYN_SKILL_INSTRUCTION,    # "skill_instruction" — injected skill instruction text
        USER_PROVIDED_CTX,        # "user_provided_ctx" — presence check (not content)
        REPL_DID_EXPAND,          # "repl_did_expand" — skill expansion occurred
    }
)
```

### Why not include `USER_PROVIDED_CTX` content

`USER_PROVIDED_CTX` is a dict that may be large (up to `RLM_USER_CTX_MAX_CHARS` chars). Including the full dict in `_rlm_state` on every REPL execution would inject potentially megabytes of data into REPL globals. The extension above includes `USER_PROVIDED_CTX` only as a presence-check key (the value being the dict itself is already in `repl.globals["user_ctx"]`). Skill code should access content via `user_ctx["filename"]`, not via `_rlm_state["user_provided_ctx"]`.

A safer alternative: expose only a boolean or count:
```python
# In REPLTool._build_state_snapshot() — not EXPOSED_STATE_KEYS:
snapshot["user_ctx_loaded"] = bool(ctx_state.get(USER_PROVIDED_CTX))
```

This is a `repl_tool.py` change rather than a state key extension, and is lower-risk. The design defers this to the implementer's judgment.

### Implementation location

The change is purely in `rlm_adk/state.py`, `EXPOSED_STATE_KEYS` frozenset. No `repl_tool.py` changes are needed — `REPLTool._build_state_snapshot()` already iterates over `EXPOSED_STATE_KEYS` to populate `_rlm_state`.

---

## 8. Required Fixture JSON Changes (Summary)

The `skill_arch_test.json` fixture from the Skill-Proposer's design needs:

### 8.1 Add `initial_state` to `config`

```json
"config": {
  "model": "gemini-fake",
  "thinking_budget": 0,
  "max_iterations": 5,
  "retry_delay": 0.0,
  "initial_state": {
    "user_provided_ctx": {
      "arch_context.txt": "Architecture validation context: this is a provider-fake e2e test for the rlm_adk pipeline. The test validates skill expansion, child dispatch, and dynamic instruction resolution.",
      "test_metadata.json": "{\"scenario\": \"skill_arch_test\", \"pipeline\": \"provider_fake\", \"depth\": 0}"
    },
    "repo_url": "https://test.example.com/arch-test",
    "root_prompt": "Run the architecture introspection skill and verify all pipeline components.",
    "test_context": "Provider-fake e2e run: skill expansion + child dispatch + dynamic instruction verification.",
    "skill_instruction": "Use run_test_skill() from rlm_repl_skills.test_skill to exercise the full pipeline."
  }
}
```

### 8.2 Add `expected_state` block

```json
"expected_state": {
  "user_provided_ctx": {
    "$not_none": true
  },
  "user_ctx_manifest": {
    "$contains": "arch_context.txt"
  },
  "usr_provided_files_serialized": {
    "$type": "list",
    "$not_empty": true
  },
  "user_provided_ctx_exceeded": false,
  "repo_url": {
    "$contains": "test.example.com"
  },
  "skill_instruction": {
    "$contains": "run_test_skill"
  }
}
```

### 8.3 Add `user_ctx` access to first REPL call

In `responses[0]` (call_index=0, caller=reasoning), the REPL code should include a `user_ctx` access to prove Path B loaded the dict into REPL globals:

```json
"code": "from rlm_repl_skills.test_skill import run_test_skill\n\n# Verify user_ctx was loaded by Path B\nprint('[DYN_INSTR:user_ctx_keys=' + str(sorted(user_ctx.keys())) + ']')\nprint('[DYN_INSTR:arch_context_preview=' + user_ctx['arch_context.txt'][:40] + ']')\n\nresult = run_test_skill(\n    child_prompt='Reply with exactly: arch_test_ok',\n    emit_debug=True,\n)\nprint(f'result={result!r}')"
```

This adds two `[DYN_INSTR:...]` tagged lines to stdout, parseable by the same `_parse_test_skill_tags`-style parser.

### 8.4 Add `tool_results.stdout_contains` check for user_ctx keys

```json
"tool_results": {
  "count": 1,
  "stdout_contains": [
    "[TEST_SKILL:COMPLETE=True]",
    "arch_test_ok",
    "arch_context.txt"
  ]
}
```

---

## 9. Runner Provisions for Dynamic Instruction Capture

The instrumented runner described in Task #2's design should include a `dyn_instruction_capture_hook` that:

1. Is chained as `before_model_callback` on the `reasoning_agent` (same mechanism as `reasoning_test_state_hook` in `contract_runner.py`)
2. On the first call (call_index=0), extracts and stores the full `systemInstruction` text to `callback_context.state["_captured_system_instruction_0"]`
3. Prints `[DYN_INSTR:placeholder=resolved_value]` lines for each expected key

```python
_DYN_INSTR_KEYS = {
    "{repo_url?}": "repo_url",
    "{root_prompt?}": "root_prompt",
    "{test_context?}": "test_context",
    "{skill_instruction?}": "skill_instruction",
    "{user_ctx_manifest?}": "user_ctx_manifest",
}

def make_dyn_instr_capture_hook(expected_keys: dict[str, str] | None = None):
    """Factory returning a before_model_callback that captures systemInstruction."""
    _call_count = [0]

    def hook(callback_context, llm_request):
        if _call_count[0] > 0:
            _call_count[0] += 1
            return None  # only capture first call
        _call_count[0] += 1

        # Extract system instruction text
        si_text = ""
        config = getattr(llm_request, "config", None)
        if config:
            si = getattr(config, "system_instruction", None)
            if si and hasattr(si, "parts"):
                si_text = "\n".join(
                    p.text for p in si.parts
                    if hasattr(p, "text") and p.text
                )

        callback_context.state["_captured_system_instruction_0"] = si_text[:4000]

        # Print verification tags
        keys_to_check = expected_keys or _DYN_INSTR_KEYS
        for placeholder, state_key in keys_to_check.items():
            resolved = placeholder not in si_text
            state_val = callback_context.state.get(state_key, "<missing>")
            print(f"[DYN_INSTR:{state_key}=resolved={resolved}]")
            if resolved and isinstance(state_val, str):
                print(f"[DYN_INSTR:{state_key}_preview={state_val[:60]}]")

        return None  # never short-circuit

    return hook
```

The hook is wired in the test module's custom runner setup (before calling `run_fixture_contract_with_plugins`), by patching `reasoning_agent.before_model_callback` via `object.__setattr__`.

---

## 10. Key Design Decisions

### Decision 1: Seed via `initial_state`, not orchestrator constructor fields

The fixture runner (`contract_runner.py`) passes `initial_state = router.config.get("initial_state")` directly to `session_service.create_session(state=initial_state)`. This is the established pattern (see `user_context_preseeded.json`). The orchestrator detects `ctx.session.state.get(USER_PROVIDED_CTX)` in Path B and builds the manifest automatically. No changes to the fixture runner are needed.

### Decision 2: `user_provided_ctx` dict with two files for manifest richness

A single-file dict would exercise the manifest builder, but two files produce a more meaningful multi-line manifest and better verifies that the manifest includes file sizes and the total count line. The files are small ASCII strings to avoid any char-limit effects.

### Decision 3: `test_context` is a raw key, not a constant

`test_context` does not appear as a constant in `state.py`. It is a raw session state key that matches the `{test_context?}` placeholder in `RLM_DYNAMIC_INSTRUCTION` by string equality. Seeding `"test_context"` in `initial_state` directly is correct and complete.

### Decision 4: `skill_instruction` seeded via `initial_state`, not `instruction_router`

In the fixture runner, `instruction_router=None` (it's not a field the test runner sets). The orchestrator's `if self.instruction_router is not None:` block at line 383 is therefore skipped. But `DYN_SKILL_INSTRUCTION = "skill_instruction"` is a session-scoped key, so seeding it in `initial_state` is equivalent. The `before_agent_callback` that would otherwise seed it is also skipped, but since the initial state event fires before the first model call, timing is not an issue.

### Decision 5: Assert absence of raw placeholders, not just presence of resolved values

Both assertions are needed. A value could appear coincidentally in a non-placeholder part of the instruction. Checking that `"{repo_url?}"` is absent confirms the ADK template resolution ran, not just that the string happened to appear somewhere.

### Decision 6: Store captured `systemInstruction` in session state for portability

Rather than requiring the test to hold an in-memory capture list (which would require test-specific runner plumbing), the hook writes to `callback_context.state["_captured_system_instruction_0"]`. This makes the captured instruction visible in `plugin_result.final_state` with no extra data passing between fixture runner and test assertions.

---

## 11. Files to Create or Modify

| File | Action | What Changes |
|------|--------|-------------|
| `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json` | **Modify** | Add `initial_state`, `expected_state`, extend REPL code to print `[DYN_INSTR:...]` tags, add `stdout_contains` entries |
| `rlm_adk/state.py` | **Optional modify** | Extend `EXPOSED_STATE_KEYS` with `DYN_USER_CTX_MANIFEST`, `DYN_SKILL_INSTRUCTION`, `REPL_DID_EXPAND` |
| `tests_rlm_adk/test_skill_arch_e2e.py` | **Modify** (in Task #2 scope) | Add `make_dyn_instr_capture_hook` wiring and the six `systemInstruction` assertions from Section 6.2 |
