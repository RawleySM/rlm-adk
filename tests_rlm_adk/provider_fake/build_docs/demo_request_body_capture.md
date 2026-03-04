# Request Body Capture — Evidence-Based Demo

## 1. Feature Overview

The provider-fake test infrastructure captures full request bodies sent to the
fake Gemini server, enabling programmatic verification that content flows intact
through the reasoning-agent / worker-dispatch / REPL pipeline. Every
`generateContent` call's JSON body is deep-copied into
`ScenarioRouter._captured_requests` and surfaced through
`ContractResult.captured_requests`.

Guillemet markers (`<<START>>` / `<<END>>`) embedded in fixture responses act as
programmatic anchors -- if a marker pair survives the full round-trip through
ADK's tool-calling loop, REPL execution, and worker dispatch, we know the
content was not truncated or mangled.

## 2. Architecture

```
initial_state (test_context) ──┐
                                v
FakeGeminiServer ──► server.py parses request body
                     │
                     v
ScenarioRouter.next_response() ──► deep-copies request_body into _captured_requests
                     │
                     v
ContractResult.captured_requests ──► list[dict] available to test assertions
                     │
                     v
save_captured_requests() ──► persists to JSON file on disk
```

Data flow through the 3-call fixture:

```
Call 0  reasoning_agent (iter 1)
  IN:  systemInstruction with skill XML + dynamic context markers
       contents with user prompt
       tools with execute_code declaration
  OUT: functionCall(execute_code) with REPL code containing artifact dict + llm_query

Call 1  worker (dispatched by llm_query inside REPL)
  IN:  contents with artifact markers + instruction markers
       systemInstruction with worker prompt
       NO tools (workers are text-only)
  OUT: text with worker response markers

Call 2  reasoning_agent (iter 2)
  IN:  systemInstruction (same as call 0)
       contents with full conversation history:
         user prompt, model functionCall, user functionResponse (REPL stdout),
         dynamic instruction re-injection
       tools with execute_code declaration
  OUT: text with FINAL() answer containing final answer markers
```

## 3. What's Verified

23 tests in `tests_rlm_adk/test_request_body_verification.py`, organized by category:

### Original Marker Roundtrip Tests (10)

| Test | Verifies |
|------|----------|
| `test_fixture_passes` | Contract expectations hold |
| `test_captured_request_count` | Exactly 3 captured requests |
| `test_reasoning_request_has_system_instruction` | Call 0 systemInstruction contains `execute_code` |
| `test_reasoning_request_has_tools` | Call 0 tools has `execute_code` function declaration |
| `test_worker_request_contains_artifact_markers` | Call 1 has `ARTIFACT_START`/`END` |
| `test_worker_request_contains_instruction_markers` | Call 1 has `WORKER_INSTRUCTION_START`/`END` |
| `test_reasoning_iter2_contains_worker_response_markers` | Call 2 has `WORKER_RESPONSE_START`/`END` |
| `test_reasoning_iter2_contains_stdout_sentinel` | Call 2 has `STDOUT_SENTINEL_START`/`END` |
| `test_marker_content_not_truncated` | Content between each marker pair is non-empty with expected substrings |
| `test_save_captured_requests_roundtrip` | JSON save/reload preserves all markers |

### Skill Frontmatter Verification (1)

| Test | Verifies |
|------|----------|
| `test_reasoning_request_has_skill_frontmatter` | Calls 0 and 2 systemInstruction has `<available_skills>` XML and `repomix-repl-helpers` |

### Structural Composition Tests (10)

| Test | Verifies |
|------|----------|
| `test_reasoning_request_has_generation_config` | Call 0 has `generationConfig` |
| `test_reasoning_iter2_has_generation_config` | Call 2 has `generationConfig` |
| `test_reasoning_call0_contents_structure` | Call 0 has contents with user-role parts |
| `test_worker_request_has_contents_with_prompt` | Call 1 has contents with dispatched prompt text |
| `test_reasoning_iter2_has_function_response_parts` | Call 2 has `functionResponse` parts (REPL tool result) |
| `test_reasoning_iter2_has_function_call_parts` | Call 2 has `functionCall` parts (model's prior tool call) |
| `test_reasoning_iter2_contents_has_both_roles` | Call 2 has both `user` and `model` roles |
| `test_worker_request_lacks_tools` | Call 1 does NOT have `execute_code` tools (workers are text-only) |
| `test_reasoning_requests_have_tools_consistently` | Both calls 0 and 2 have `execute_code` tools |
| `test_reasoning_requests_have_system_instruction_consistently` | Both calls 0 and 2 have systemInstruction |

### Dynamic Instruction Injection (2)

| Test | Verifies |
|------|----------|
| `test_reasoning_request_contains_dynamic_context_markers` | Call 0 systemInstruction has `DYNAMIC_CONTEXT_START`/`END` |
| `test_reasoning_iter2_contains_dynamic_context` | Call 2 systemInstruction has `DYNAMIC_CONTEXT_START`/`END` (persists across iterations) |

## 4. Evidence: Captured Request Bodies

Persisted file: `tests_rlm_adk/provider_fake/build_docs/captured_requests.json` (23,032 bytes)

### Call 0 -- reasoning_agent (iteration 1)

```
Top-level keys: ['contents', 'generationConfig', 'systemInstruction', 'tools']
Serialized length: 9305 chars
systemInstruction length: 8432 chars
tools count: 1
contents count: 3
content roles: ['user', 'user', 'user']
```

**systemInstruction** (abbreviated):
```json
{
  "parts": [{
    "text": "You are tasked with answering a query. You have access to two tools:\n\n1. execute_code(code=\"...\") ...
    ...
    <available_skills>\n<skill>\n<name>\nrepomix-repl-helpers\n</name> ...
    ...
    Additional context: <<DYNAMIC_CONTEXT_START>> This test context was injected via dynamic instruction template {test_key: test_value, marker: roundtrip_check} <<DYNAMIC_CONTEXT_END>>\n ..."
  }],
  "role": "user"
}
```

**tools**:
```json
[{
  "functionDeclarations": [{
    "description": "Execute Python code in a persistent REPL environment. ...",
    "name": "execute_code",
    "parameters": {
      "properties": { "code": { "type": "STRING" } },
      "required": ["code"],
      "type": "OBJECT"
    }
  }]
}]
```

**contents** (3 user-role entries):
```
[0] dynamic instruction: "Repository URL: \nOriginal query: \nAdditional context: <<DYNAMIC_CONTEXT_START>> ... <<DYNAMIC_CONTEXT_END>>"
[1] user prompt: "test prompt"
[2] orchestrator context: "For context:" + "[rlm_orchestrator] said: Analyze and answer the query."
```

### Call 1 -- worker (dispatched by llm_query)

```
Top-level keys: ['contents', 'generationConfig', 'systemInstruction']
Serialized length: 651 chars
systemInstruction length: 209 chars
contents count: 1
content roles: ['user']
```

**contents** (the dispatched prompt with markers visible):
```
<<WORKER_INSTRUCTION_START>> Analyze this code artifact and summarize its purpose <<WORKER_INSTRUCTION_END>>

{'<<ARTIFACT_START>>': True, 'repo_name': 'test-repo', 'files': {'main.py': "print('hello')",
'utils.py': 'def add(a,b): return a+b'}, 'metadata': {'token_estimate': 42, 'shard_index': 0},
'<<ARTIFACT_END>>': True}
```

**systemInstruction**: `"Answer the user's query directly and concisely.\n\nYou are an agent. Your internal name is \"worker_1\". ..."`

**No tools key** -- workers are text-only LLM calls.

### Call 2 -- reasoning_agent (iteration 2)

```
Top-level keys: ['contents', 'generationConfig', 'systemInstruction', 'tools']
Serialized length: 10752 chars
systemInstruction length: 8430 chars
tools count: 1
contents count: 5
content roles: ['user', 'user', 'model', 'user', 'user']
```

**contents** (5-entry conversation history):
```
[0] role=user:  "test prompt"
[1] role=user:  "For context:" + "[rlm_orchestrator] said: Analyze and answer the query."
[2] role=model: functionCall execute_code with code containing <<ARTIFACT_START>>, <<WORKER_INSTRUCTION_START>>, <<STDOUT_SENTINEL_START>> markers
[3] role=user:  functionResponse with stdout:
    "<<WORKER_RESPONSE_START>> The code artifact contains a simple Python project ... <<WORKER_RESPONSE_END>>
     <<STDOUT_SENTINEL_START>> This is a known stdout string from iteration 1 <<STDOUT_SENTINEL_END>>"
    + variables dict with artifact and result
[4] role=user:  dynamic instruction re-injection with <<DYNAMIC_CONTEXT_START>>...<<DYNAMIC_CONTEXT_END>>
```

## 5. Evidence: Marker Extraction

Content extracted between each guillemet marker pair from the captured request bodies:

| Marker Pair | Call | Content |
|-------------|------|---------|
| `ARTIFACT_START..ARTIFACT_END` | 1 | `': True, 'repo_name': 'test-repo', 'files': {'main.py': "print('hello')", 'utils.py': 'def add(a,b): return a+b'}, 'metadata': {'token_estimate': 42, 'shard_index': 0}, '` (172 chars) |
| `WORKER_INSTRUCTION_START..END` | 1 | ` Analyze this code artifact and summarize its purpose ` (54 chars) |
| `WORKER_RESPONSE_START..END` | 2 | ` The code artifact contains a simple Python project with a main entry point and utility functions for basic arithmetic ` (119 chars) |
| `STDOUT_SENTINEL_START..END` | 2 | ` This is a known stdout string from iteration 1 ` (48 chars) |
| `DYNAMIC_CONTEXT_START..END` | 0 | ` This test context was injected via dynamic instruction template {test_key: test_value, marker: roundtrip_check} ` (113 chars) |
| `DYNAMIC_CONTEXT_START..END` | 2 | ` This test context was injected via dynamic instruction template {test_key: test_value, marker: roundtrip_check} ` (113 chars) |

All 6 marker extractions present. No truncation detected.

## 6. Evidence: Dynamic Instruction Injection

The `request_body_roundtrip.json` fixture sets `initial_state.test_context`:

```json
"initial_state": {
  "test_context": "<<DYNAMIC_CONTEXT_START>> This test context was injected via dynamic instruction template {test_key: test_value, marker: roundtrip_check} <<DYNAMIC_CONTEXT_END>>"
}
```

This flows through `RLM_DYNAMIC_INSTRUCTION` in `rlm_adk/utils/prompts.py`:

```
Additional context: {test_context?}
```

ADK replaces `{test_context?}` with the session state value at runtime. The captured request bodies confirm the dynamic context appears in:

- **Call 0 systemInstruction** (8432 chars) -- contains the full dynamic context
- **Call 0 contents[0]** -- dynamic instruction as first user-role content
- **Call 2 systemInstruction** (8430 chars) -- persists across iterations
- **Call 2 contents[4]** -- re-injected as final user-role content

## 7. Prove It Works

### Request body verification (23 tests):

```
tests_rlm_adk/test_request_body_verification.py::test_fixture_passes PASSED
tests_rlm_adk/test_request_body_verification.py::test_captured_request_count PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_request_has_system_instruction PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_request_has_tools PASSED
tests_rlm_adk/test_request_body_verification.py::test_worker_request_contains_artifact_markers PASSED
tests_rlm_adk/test_request_body_verification.py::test_worker_request_contains_instruction_markers PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_iter2_contains_worker_response_markers PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_iter2_contains_stdout_sentinel PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_request_has_skill_frontmatter PASSED
tests_rlm_adk/test_request_body_verification.py::test_marker_content_not_truncated PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_request_has_generation_config PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_iter2_has_generation_config PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_call0_contents_structure PASSED
tests_rlm_adk/test_request_body_verification.py::test_worker_request_has_contents_with_prompt PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_iter2_has_function_response_parts PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_iter2_has_function_call_parts PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_iter2_contents_has_both_roles PASSED
tests_rlm_adk/test_request_body_verification.py::test_worker_request_lacks_tools PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_requests_have_tools_consistently PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_requests_have_system_instruction_consistently PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_request_contains_dynamic_context_markers PASSED
tests_rlm_adk/test_request_body_verification.py::test_reasoning_iter2_contains_dynamic_context PASSED
tests_rlm_adk/test_request_body_verification.py::test_save_captured_requests_roundtrip PASSED

23 passed, 4 warnings in 0.48s
```

### Provider-fake e2e suite (41 tests):

```
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[all_workers_fail_batch] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[empty_reasoning_output] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[empty_reasoning_output_safety] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[fault_429_then_success] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[max_iterations_exceeded] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[max_iterations_exceeded_persistent] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[reasoning_safety_finish] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[repl_cancelled_during_async] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[repl_error_then_retry] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[repl_exception_then_retry] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[repl_runtime_error] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[repl_runtime_error_partial_state] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[repl_syntax_error] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[request_body_roundtrip] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[structured_output_batched_k3] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[structured_output_batched_k3_mixed_exhaust] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[structured_output_batched_k3_multi_retry] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[structured_output_batched_k3_with_retry] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[structured_output_retry_empty] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[structured_output_retry_exhaustion] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[structured_output_retry_exhaustion_pure_validation] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[structured_output_retry_validation] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_429_mid_batch] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_500_retry_exhausted] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_500_retry_exhausted_naive] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_500_then_success] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_auth_error_401] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_empty_response] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_empty_response_finish_reason] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_malformed_json] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_max_tokens_naive] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_max_tokens_truncated] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_fixture_contract[worker_safety_finish] PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_observability_state_happy_path PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_artifact_persistence_happy_path PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_artifact_persistence_multi_iteration PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_sqlite_traces_recorded_happy_path PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_sqlite_traces_recorded_multi_iteration PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_repl_trace_in_events_multi_iteration PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_captured_requests_populated PASSED
tests_rlm_adk/test_provider_fake_e2e.py::test_save_captured_requests_to_json PASSED

41 passed, 152 warnings in 30.06s
```

## 8. Verification Commands

Run the evidence capture script (persists `captured_requests.json` and prints marker extraction):

```bash
.venv/bin/python tests_rlm_adk/provider_fake/build_docs/capture_evidence.py
```

Run the 23 request body verification tests:

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_request_body_verification.py -v
```

Run alongside the full provider-fake e2e suite:

```bash
.venv/bin/python -m pytest tests_rlm_adk/test_request_body_verification.py tests_rlm_adk/test_provider_fake_e2e.py -v
```

Inspect the persisted captured requests:

```bash
python -m json.tool tests_rlm_adk/provider_fake/build_docs/captured_requests.json | head -80
```
