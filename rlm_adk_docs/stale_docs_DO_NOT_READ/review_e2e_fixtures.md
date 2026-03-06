# E2E Fixture & Contract Runner Review: Recursive Worker Orchestrator Impact

## 1. Inventory of Affected Fixtures

### 1.1 Fixtures with `"caller": "worker"` Responses (Direct Worker Dispatch)

These fixtures script responses for leaf LlmAgent workers. When workers become child RLMOrchestratorAgents, each `"caller": "worker"` response must be restructured into a multi-turn child reasoning conversation (reasoning call + tool_call/tool_response + set_model_response or FINAL).

| Fixture | What It Tests | Worker Responses | Impact |
|---------|--------------|-----------------|--------|
| `request_body_comprehensive.json` | Dict dynamic instruction, REPL globals, chaining | 2 worker responses (call 1, 3) | **HIGH** - Tests request body structure of worker calls; child orchestrator has completely different request format |
| `request_body_roundtrip.json` | Request body capture with markers | 1 worker response (call 1) | **HIGH** - Verifies worker request body structure (include_contents='none', _pending_prompt injection) |
| `structured_output_batched_k3.json` | K=3 structured output batch | 3 worker set_model_response (calls 1-3) | **HIGH** - Workers use SetModelResponseTool; children use reasoning+REPL+set_model_response |
| `structured_output_batched_k3_with_retry.json` | K=3 structured output with 1 retry | 4 worker responses (calls 1-4, one retries) | **HIGH** - Tests BUG-13 suppression + retry within worker |
| `structured_output_batched_k3_mixed_exhaust.json` | K=3 batch, 1 worker exhausts retries | Multiple worker responses | **HIGH** - Mixed success/exhaustion in batch |
| `structured_output_batched_k3_multi_retry.json` | K=3 batch, multiple retries | Multiple worker responses | **HIGH** - Multi-retry structured output |
| `structured_output_retry_empty.json` | Empty value detection in retry | 2 worker responses | **HIGH** - WorkerRetryPlugin empty-value detection |
| `structured_output_retry_exhaustion.json` | Schema validation exhaustion | 3 worker responses (calls 1-3) | **HIGH** - FM-16 detection path |
| `structured_output_retry_exhaustion_pure_validation.json` | Pure validation exhaustion | 3 worker responses | **HIGH** - Pydantic validation path |
| `structured_output_retry_validation.json` | Retry with validation success | Worker responses | **HIGH** - Validates retry recovery |
| `worker_429_mid_batch.json` | K=3 batch, 1 worker gets 429 | 2 worker success + 2 fault injections | **HIGH** - Fault injection targets worker call_indexes |
| `worker_500_then_success.json` | SDK retry recovery from 500 | 1 worker response (call 2, after fault at 1) | **HIGH** - Fault injection at worker call_index |
| `worker_500_retry_exhausted.json` | SDK retry exhaustion | 0 worker success, 2 faults (calls 1-2) | **HIGH** - on_model_error_callback path |
| `worker_500_retry_exhausted_naive.json` | Naive retry exhaustion | Worker fault responses | **HIGH** |
| `all_workers_fail_batch.json` | K=3 all workers fail | 0 worker success, 6 faults (calls 1-6) | **HIGH** - 6 fault injections for 3 workers x 2 attempts |
| `worker_auth_error_401.json` | 401 auth error on worker | Fault injection | **HIGH** |
| `worker_empty_response.json` | K=2 batch, 1 empty (SAFETY) | 2 worker responses (valid + empty) | **HIGH** - SAFETY finish reason on worker |
| `worker_empty_response_finish_reason.json` | Finish reason variants | Worker responses | **HIGH** |
| `worker_safety_finish.json` | Single worker SAFETY finish | 1 worker response (empty, SAFETY) | **HIGH** - SAFETY error classification |
| `worker_malformed_json.json` | Malformed JSON from worker API | 0 worker success, 1 malformed fault | **HIGH** - on_model_error_callback path |
| `worker_max_tokens_truncated.json` | MAX_TOKENS truncation | 1 worker response | **HIGH** - Graceful non-error handling |
| `worker_max_tokens_naive.json` | Naive MAX_TOKENS handling | 1 worker response | **HIGH** |
| `repl_cancelled_during_async.json` | CancelledError during async dispatch | 1 worker response | **MEDIUM** - Worker dispatches successfully before cancel |
| `repl_error_then_retry.json` | KeyError after llm_query, retry | 2 worker responses | **MEDIUM** - Worker dispatches in both iterations |
| `repl_exception_then_retry.json` | RuntimeError after dispatch, retry | 2 worker responses | **MEDIUM** - Worker dispatches before exception |

### 1.2 Agent Challenge Fixtures (in `agent_challenge/` subdirectory)

These also have `"caller": "worker"` responses:
- `multi_iteration_with_workers.json`
- `happy_path_single_iteration.json` (if it has workers)
- `hierarchical_summarization.json` - 4 worker responses
- `polymorphic_dag_routing.json` - 6 worker responses
- `sliding_window_chunking.json` - 8 worker responses
- `structured_control_plane.json` - 3 worker responses
- `adaptive_confidence_gating.json` - 5 worker responses
- `multi_turn_repl_session.json` - 5 worker responses
- `structured_output_batched_k1.json` - 1 worker response
- `structured_output_happy_path.json` - 1 worker response
- `exec_sandbox_codegen.json` - 1 worker response
- `deterministic_guardrails.json` - 2 worker responses

### 1.3 Fixtures NOT Affected (No Worker Dispatch)

| Fixture | What It Tests |
|---------|--------------|
| `fault_429_then_success.json` | Reasoning-level 429 retry |
| `empty_reasoning_output.json` | Empty reasoning output handling |
| `empty_reasoning_output_safety.json` | Reasoning SAFETY finish |
| `max_iterations_exceeded.json` | REPLTool call limit |
| `max_iterations_exceeded_persistent.json` | Persistent call limit |
| `reasoning_safety_finish.json` | Reasoning-level SAFETY |
| `repl_syntax_error.json` | REPL SyntaxError self-correction |
| `repl_runtime_error.json` | REPL NameError recovery |
| `repl_runtime_error_partial_state.json` | Partial state non-persistence |

---

## 2. contract_runner.py Specific Changes

### 2.1 `_wire_test_hooks()` (Lines 42-102) — **Must Be Rewritten**

The current function (lines 88-102) monkey-patches `WorkerPool._create_worker` to chain `worker_test_state_hook` before `worker_before_model` on every new worker. This entire mechanism breaks because:

1. `WorkerPool` is being deleted/replaced with `ModelConfig`
2. `_create_worker()` no longer exists
3. Leaf `LlmAgent` workers no longer exist
4. `worker_before_model` / `worker_test_state_hook` are deleted

**What should replace it**:

The child orchestrator's reasoning_agent is the new "worker" equivalent. Test hooks for child orchestrators need to:
- Hook the child's reasoning_agent's `before_model_callback` to inject test state
- This requires hooking `create_child_orchestrator()` in `agent.py` instead of `WorkerPool._create_worker`
- Alternatively, the dispatch closure that creates children could accept a `child_hooks` factory function

**Recommendation**: Add an optional `child_before_model_hook` parameter to `create_dispatch_closures()` that gets wired onto each child orchestrator's reasoning_agent before `_run_async_impl`. The contract_runner would pass `reasoning_test_state_hook` through this parameter.

### 2.2 `_make_repl()` (Lines 156-179) — **No Change Needed**

This creates a LocalREPL pre-loaded with `initial_repl_globals` from fixture config. This is for the parent REPL, not workers. Unchanged.

### 2.3 `_make_runner_and_session()` (Lines 182-225) — **Minor Change**

Line 214: `if router.config.get("test_hooks"): _wire_test_hooks(app)` — the call to `_wire_test_hooks` needs updating as described above. The rest of the function is unchanged since it creates the parent app/runner.

### 2.4 `_set_env()` (Lines 144-152) — **Possible Addition**

May need `RLM_MAX_DEPTH` env var for recursive tests, and `RLM_MAX_CONCURRENT_CHILDREN` for concurrency control.

### 2.5 `run_fixture_contract_with_plugins()` (Lines 288-395) — **No Change Needed**

This function creates the runner and drives it to completion. The recursive child orchestrators are internal to the dispatch layer. The contract runner drives the parent; children are spawned implicitly by the REPL code calling `llm_query()`.

---

## 3. Fixture Format Gap Analysis: Single-Shot vs Multi-Turn

### 3.1 Current Format: Sequential FIFO Response Queue

The `ScenarioRouter` serves responses in FIFO order from a flat `responses` array. Each entry has a `call_index` and `caller` field. The router does NOT distinguish between reasoning and worker callers — it just serves the next response in sequence.

**This is actually an advantage**: The router doesn't need to know whether a call comes from a reasoning agent, a leaf worker, or a child orchestrator's reasoning agent. It just serves responses in order.

### 3.2 Current Worker Responses: Single-Shot

Current worker responses are **single-turn**: one request from the worker's `before_model_callback`, one response with text or `set_model_response` functionCall. The worker makes exactly 1 API call per dispatch (or N calls with SDK retry / structured output retry).

### 3.3 Child Orchestrator Responses: Multi-Turn

A child RLMOrchestratorAgent's reasoning_agent makes **multiple API calls** per dispatch:

1. **Reasoning call 1**: Child receives prompt, may call `execute_code` or `set_model_response`
2. **Tool response**: If `execute_code` was called, REPL executes and returns tool result
3. **Reasoning call 2**: Child sees tool result, produces FINAL or calls another tool
4. ...continues until FINAL or max iterations

**Each of these reasoning calls consumes a response from the ScenarioRouter**.

### 3.4 What Changes in Fixture Format

For a current single-worker dispatch (`llm_query("Analyze X")` returning `"Result A"`), the fixture currently has:

```json
{"call_index": 1, "caller": "worker", "body": {"candidates": [{"content": {"parts": [{"text": "Result A"}]}}]}}
```

Under the recursive model, this becomes a **minimum of 2 responses** (child reasoning call + FINAL):

```json
{"call_index": 1, "caller": "child_reasoning", "body": {"candidates": [{"content": {"parts": [{"text": "After analysis...\n\nFINAL(Result A)"}]}}]}}
```

Or, if the child uses `set_model_response`:

```json
{"call_index": 1, "caller": "child_reasoning", "body": {"candidates": [{"content": {"parts": [{"functionCall": {"name": "set_model_response", "args": {"result": "Result A"}}}]}}]}}
```

For children that use REPL + llm_query (recursive), the sequence grows further:

```json
{"call_index": 1, "caller": "child_reasoning", "body": {"candidates": [{"content": {"parts": [{"functionCall": {"name": "execute_code", "args": {"code": "result = llm_query(...)"}}}]}}]}}
{"call_index": 2, "caller": "grandchild_reasoning", "body": {...}}
{"call_index": 3, "caller": "child_reasoning", "body": {"candidates": [{"content": {"parts": [{"text": "FINAL(...)"}]}}]}}
```

### 3.5 Key Format Gap: `total_model_calls` Changes

Every fixture with `"total_model_calls"` in `expected` will need updating because:
- A single `llm_query()` that previously consumed 1 API call now consumes **at least 1** (child reasoning direct FINAL) and typically **2+** (child reasoning + execute_code tool loop)
- Fault injection `call_index` values shift because children interleave more calls

### 3.6 Key Format Gap: Request Body Structure

Current worker requests have:
- `include_contents='none'` (no conversation history)
- Prompt injected via `worker_before_model` into `llm_request.contents` as a single user Content
- No `systemInstruction` (workers have simple static instruction)

Child orchestrator reasoning requests have:
- `include_contents='default'` (full conversation history)
- `systemInstruction` with child static instruction
- `contents` with conversation history (user prompt + any tool results)
- This is fundamentally different from worker requests

**All request body verification tests must be rewritten**.

---

## 4. New Fixture Patterns for Recursive Scenarios

### 4.1 Pattern A: Simple Child (No REPL, Direct FINAL)

For `llm_query("simple question")` where the child answers directly:

```json
{
  "responses": [
    {"call_index": 0, "caller": "reasoning", "note": "Parent reasoning calls execute_code with llm_query", "body": {"candidates": [{"content": {"parts": [{"functionCall": {"name": "execute_code", "args": {"code": "result = llm_query('simple question')\nprint(result)"}}}]}}]}},
    {"call_index": 1, "caller": "child_reasoning", "note": "Child answers directly without REPL", "body": {"candidates": [{"content": {"parts": [{"text": "FINAL(The answer is 42)"}]}}]}},
    {"call_index": 2, "caller": "reasoning", "note": "Parent sees result, produces FINAL", "body": {"candidates": [{"content": {"parts": [{"text": "FINAL(42)"}]}}]}}
  ]
}
```

### 4.2 Pattern B: Child with REPL + set_model_response

For `llm_query("compute X", output_schema=MySchema)`:

```json
{
  "responses": [
    {"call_index": 0, "caller": "reasoning", "note": "Parent reasoning calls execute_code with llm_query(output_schema=...)", "body": {"candidates": [{"content": {"parts": [{"functionCall": {"name": "execute_code", "args": {"code": "result = llm_query('compute X', output_schema=MySchema)\nprint(result.parsed)"}}}]}}]}},
    {"call_index": 1, "caller": "child_reasoning", "note": "Child uses execute_code to compute", "body": {"candidates": [{"content": {"parts": [{"functionCall": {"name": "execute_code", "args": {"code": "x = 2 + 2\nprint(x)"}}}]}}]}},
    {"call_index": 2, "caller": "child_reasoning", "note": "Child submits structured output", "body": {"candidates": [{"content": {"parts": [{"functionCall": {"name": "set_model_response", "args": {"value": 4}}}]}}]}},
    {"call_index": 3, "caller": "reasoning", "note": "Parent sees structured result, FINAL", "body": {"candidates": [{"content": {"parts": [{"text": "FINAL(4)"}]}}]}}
  ]
}
```

### 4.3 Pattern C: Batched Children (K=3)

For `llm_query_batched(["A", "B", "C"])` with concurrent children:

The ScenarioRouter's FIFO order becomes critical. Children run concurrently via `asyncio.gather` with semaphore. The call_index order depends on which child's reasoning_agent makes its API call first. **This is non-deterministic** in the general case.

**Recommendation**: For K>1 tests, set `RLM_MAX_CONCURRENT_CHILDREN=1` to force serial execution of children, making call order deterministic in fixtures.

### 4.4 Pattern D: Fault Injection on Child Reasoning

For a child that hits a 500 error:

```json
{
  "fault_injections": [
    {"call_index": 1, "fault_type": "http_error", "status": 500, "note": "Child reasoning call 1 hits 500"}
  ],
  "responses": [
    {"call_index": 0, "caller": "reasoning", "body": {"candidates": [{"content": {"parts": [{"functionCall": {"name": "execute_code", "args": {"code": "result = llm_query('task')"}}}]}}]}},
    {"call_index": 2, "caller": "child_reasoning", "note": "Child retry succeeds after 500", "body": {"candidates": [{"content": {"parts": [{"text": "FINAL(recovered)"}]}}]}},
    {"call_index": 3, "caller": "reasoning", "body": {"candidates": [{"content": {"parts": [{"text": "FINAL(recovered)"}]}}]}}
  ]
}
```

---

## 5. FMEA Test Impact Assessment

### 5.1 Tests That Must Be Rewritten (Worker-Specific Behavior)

| Test Class | Fixture | Worker-Specific Assertions | Impact |
|-----------|---------|---------------------------|--------|
| `TestWorker429MidBatch` | `worker_429_mid_batch` | Asserts `WORKER_DISPATCH_COUNT`, partial batch failure | **REWRITE** - State key changes, error propagation differs |
| `TestWorkerEmptyResponse` | `worker_empty_response` | Asserts `WORKER_DISPATCH_COUNT`, SAFETY error_counts | **REWRITE** - Child SAFETY handling differs from worker SAFETY |
| `TestWorker500ThenSuccess` | `worker_500_then_success` | Asserts `WORKER_DISPATCH_COUNT`, `OBS_TOTAL_CALLS` | **REWRITE** - SDK retry is on child reasoning, not worker |
| `TestAllWorkersFail` | `all_workers_fail_batch` | Asserts all 3 failures, `WORKER_DISPATCH_COUNT` | **REWRITE** - All children fail scenario |
| `TestWorker500RetryExhausted` | `worker_500_retry_exhausted` | Asserts error in FINAL_ANSWER | **REWRITE** - Error propagation path changes |
| `TestWorkerSafetyFinish` | `worker_safety_finish` | Asserts SAFETY detection, `obs:finish_safety_count` | **REWRITE** - SAFETY on child reasoning, not worker |
| `TestWorkerMalformedJson` | `worker_malformed_json` | Asserts malformed JSON error detection | **REWRITE** - Error classification path changes |
| `TestWorkerMaxTokensTruncated` | `worker_max_tokens_truncated` | Asserts MAX_TOKENS non-error handling, dispatch latency | **REWRITE** - Truncation happens at child level |
| `TestStructuredOutputBatchedK3` | `structured_output_batched_k3` | Asserts `WORKER_DISPATCH_COUNT==3`, structured output | **REWRITE** - Children use reasoning+REPL+set_model_response |
| `TestStructuredOutputBatchedK3WithRetry` | `structured_output_batched_k3_with_retry` | Asserts BUG-13 patch invoked, retry recovery | **REWRITE** - BUG-13 relevance may change |
| `TestStructuredOutputRetryExhaustion` | `structured_output_retry_exhaustion` | Asserts `SCHEMA_VALIDATION_EXHAUSTED`, error counts | **REWRITE** - Exhaustion detection differs |

### 5.2 Tests That Are Partially Affected (Worker Dispatch Used But Not Central)

| Test Class | Fixture | What Changes |
|-----------|---------|-------------|
| `TestReplErrorThenRetry` | `repl_error_then_retry` | Fixture has 2 worker responses; must become 2 child reasoning sequences. Test assertions about KeyError, retry are still valid. |
| `TestReplCancelledDuringAsync` | `repl_cancelled_during_async` | Fixture has 1 worker response; child sequence changes. CancelledError injection tests are still valid. |
| `TestReplCancelledErrorInjection` | Same fixture | Same fixture change; monkeypatch target unchanged. `WORKER_DISPATCH_COUNT` assertion must change to `OBS_CHILD_DISPATCH_COUNT`. |
| `TestReplExceptionFlushFn` | Same fixture | `WORKER_DISPATCH_COUNT` assertion → `OBS_CHILD_DISPATCH_COUNT` |
| `TestReplExceptionThenRetry` | `repl_exception_then_retry` | Fixture has 2 worker responses; assertions about accumulator drift still valid |

### 5.3 Tests NOT Affected (No Worker Dispatch)

| Test Class | Fixture |
|-----------|---------|
| `TestReplSyntaxError` | `repl_syntax_error` |
| `TestMaxIterationsExceeded` | `max_iterations_exceeded` |
| `TestEmptyReasoningOutput` | `empty_reasoning_output` |
| `TestReplRuntimeError` | `repl_runtime_error` |
| `TestReplRuntimeErrorPartialState` | `repl_runtime_error_partial_state` |

### 5.4 Approximate Test Count Impact

Of the ~80 FMEA tests:
- **~45 tests** in 11 classes must be **rewritten** (worker-specific)
- **~10 tests** in 4 classes are **partially affected** (state key renames, fixture changes)
- **~25 tests** in 5 classes are **unaffected** (no worker dispatch)

---

## 6. Observability State Key Changes

The plan introduces `OBS_CHILD_DISPATCH_COUNT` and removes worker-specific keys. Impact on expected_state assertions:

| Current Key | Used In Fixtures | Replacement |
|------------|-----------------|-------------|
| `worker_dispatch_count` | 18+ fixtures | `obs:child_dispatch_count` |
| `obs:worker_total_batch_dispatches` | 5 fixtures | `obs:child_total_batch_dispatches` or remove |
| `obs:worker_dispatch_latency_ms` | 3 fixtures | `obs:child_dispatch_latency_ms` |
| `obs:worker_error_counts` | 6 fixtures | `obs:child_error_counts` or reasoning error categories |
| `obs:worker_pool_exhaustion_count` | 1 fixture | Remove (no pool) |
| `obs:structured_output_failures` | 1 fixture | Keep (still relevant on child) |

---

## 7. Recommendations for Plan Amendments

### R1: Serial Execution Mode for Fixture Determinism

Add `RLM_MAX_CONCURRENT_CHILDREN=1` to fixture configs for all K>1 batch tests. This makes call order deterministic so fixtures can script responses in FIFO order. Without this, concurrent children make call_index ordering unpredictable and fixtures will be fragile.

### R2: Fixture Migration Strategy — Phased Approach

Do NOT rewrite all fixtures simultaneously. Recommended order:
1. **Phase 3a**: Convert 3-5 simple worker fixtures first (e.g., `worker_500_then_success`, `worker_safety_finish`, `worker_empty_response`) to validate the new child orchestrator response pattern.
2. **Phase 3b**: Convert structured output fixtures (these are most complex because children now use reasoning + REPL + set_model_response).
3. **Phase 3c**: Convert batch fixtures (K>1) with serial execution mode.
4. **Phase 3d**: Convert request body verification fixtures.

### R3: New `"caller"` Values in Fixtures

Add `"caller": "child_reasoning"` alongside existing `"reasoning"` and `"worker"`. Update `_caller_to_model_name()` in `fixtures.py` to handle the new caller type. This preserves the diagnostic value of the request log.

### R4: `_wire_test_hooks()` Replacement

Replace the `WorkerPool._create_worker` monkey-patch with a `child_hooks` parameter on `create_dispatch_closures()`. This is cleaner than monkey-patching `create_child_orchestrator()` because the dispatch layer already owns the child lifecycle.

### R5: `total_model_calls` Expected Values

Every fixture with workers will have different `total_model_calls` because children make more API calls than leaf workers. The minimum increase is 0 (child FINAL on first call) but typically +1 per child (reasoning call + FINAL vs single worker call). Plan should document the expected call count formula.

### R6: BUG-13 Patch Relevance

With recursive children, `SetModelResponseTool` is used on child reasoning agents (not leaf workers). The BUG-13 patch targets `_output_schema_processor.get_structured_model_response()` which fires for any agent with `SetModelResponseTool`. The patch remains relevant but the test fixtures for BUG-13 verification (`structured_output_batched_k3_with_retry`) must be restructured. The `_bug13_stats["suppress_count"]` delta assertion is still valid.

### R7: Error Classification Path Change

Current path: `worker_on_model_error → _classify_error → _call_record → dispatch error_counts`

New path: Child orchestrator handles its own errors internally. The parent dispatch reads the child's `FINAL_ANSWER` which may contain error text, but structured error classification (`RATE_LIMIT`, `SERVER`, `SAFETY`, `PARSE_ERROR`) is no longer propagated back to the parent via worker carrier attributes.

**Recommendation**: The plan should specify how child-level errors are classified and propagated to the parent's observability accumulators. Options:
1. Child writes error category to depth-scoped state key, parent dispatch reads it
2. `_run_child()` in dispatch catches child exceptions and classifies them
3. Child orchestrator returns `LLMResult(error=True, error_category=...)` based on its final state

### R8: Request Body Verification Tests

The `request_body_comprehensive.json` and `request_body_roundtrip.json` fixtures verify the exact HTTP request body structure. These tests are deeply tied to the worker's `include_contents='none'` + `_pending_prompt` injection pattern. With child orchestrators using `include_contents='default'` + standard systemInstruction, these tests need fundamentally different assertions:
- Child reasoning requests will have `systemInstruction` (child static instruction)
- Child reasoning requests will have `contents` with user message (the prompt)
- No `_pending_prompt` injection pattern exists

**Recommendation**: Keep request body verification tests but rewrite expectations for child orchestrator request format. The guillemet-marked sentinel pattern is still useful for verifying prompt content flows through to child reasoning.

### R9: Fixture Exhaustion Fallback

The ScenarioRouter returns `"FINAL(fixture-exhausted)"` when it runs out of scripted responses. With children making more calls, fixtures are more likely to exhaust. Ensure all converted fixtures have enough responses, and consider increasing the fallback's visibility in diagnostics.
