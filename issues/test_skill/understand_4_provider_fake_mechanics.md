# Understand Agent 4: Provider-Fake Test Infrastructure Mechanics

## Problem Restatement (Polya Step 1)

This document answers one question precisely: **In a provider-fake test, what is real, what is fake, and how does each mechanism work at the code level?**

Prior agents analyzing this codebase made a critical error: claiming "fixture responses are immutable" and proposing a nonce pattern where the model generates random values. In provider-fake tests, the model *cannot generate anything*. Every model response is pre-scripted JSON. Only REPL code execution is real. This document establishes the exact boundary between real and fake, the mechanics of response routing, and the implications for fixture design and assertion strategy.

---

## Section 1: What Is Real vs What Is Fake

### Components That Execute For Real

1. **The full RLM pipeline initialization**: `create_rlm_app()` (or `create_rlm_runner()`) builds the real `RLMOrchestratorAgent`, real `LlmAgent` reasoning_agent, real `REPLTool`, real `SetModelResponseTool`, real `SkillToolset` (when skills are enabled), real `LocalREPL`, real skill loader.

2. **`RLMOrchestratorAgent._run_async_impl()`**: The real orchestrator runs. It yields initial state events, sets up the REPL, wires dispatch closures, creates the thread bridge, delegates to `reasoning_agent.run_async(ctx)`, drains child event queues, builds `CompletionEnvelope`, yields final state and content events. All of this is real code executing.

3. **REPLTool.run_async()**: When the fake model response contains a `functionCall` with `name: "execute_code"`, ADK's tool-calling loop invokes `REPLTool.run_async()` *for real*. The `code` field from the fixture's `args.code` is executed as actual Python in the persistent `LocalREPL` environment. This means:
   - `print()` statements produce real stdout
   - Variable assignments persist between calls
   - `import` statements run
   - `llm_query()` calls dispatch real child orchestrators through the thread bridge
   - Exceptions are real exceptions
   - `_rlm_state` reads reflect real pipeline state
   - `user_ctx` contains real data from `initial_state.user_provided_ctx`

4. **Thread bridge**: `make_sync_llm_query()` and `make_sync_llm_query_batched()` create real sync callables that use `asyncio.run_coroutine_threadsafe()` to dispatch from the REPL's worker thread to the event loop. This is fully real.

5. **Child orchestrator dispatch**: `create_dispatch_closures()` builds real `llm_query_async` / `llm_query_batched_async` closures. When REPL code calls `llm_query("prompt")`, a real child `RLMOrchestratorAgent` is spawned at `depth+1` via `create_child_orchestrator()`. That child has its own REPL, its own tools, its own reasoning agent. The child's reasoning agent then makes an API call to the fake server, which serves the next scripted response.

6. **State mutation**: All `tool_context.state[key] = value` writes, `EventActions(state_delta={...})` yields, and `callback_context.state[key] = value` writes are real ADK state mutations. The session service is a real `SqliteSessionService`. The final state is read back from the real session store.

7. **Plugins**: `ObservabilityPlugin`, `SqliteTracingPlugin`, `REPLTracingPlugin`, and `InstrumentationPlugin` all run for real. Their callbacks fire on real events. Their state writes are real. The SQLite traces DB is a real file.

8. **Skill loading**: When `config.enabled_skills` includes `["test_skill"]`, the real `collect_skill_repl_globals()` and `load_adk_skills()` functions run. `run_test_skill` is injected into REPL globals via the real module-import loader, with `llm_query_fn` auto-wired by the loader wrapper.

9. **Artifact service**: `FileArtifactService` writes real files. REPL code artifacts (`repl_code_iter_N.py`) and final answer artifacts are saved to disk.

### Components That Are Mocked/Faked

1. **The Gemini API**: `FakeGeminiServer` is an `aiohttp` web server listening on a random local port. The `GOOGLE_GEMINI_BASE_URL` env var is set to point at this server. The `google.genai` SDK sends real HTTP requests, but they hit the fake server instead of Google's API.

2. **Model responses**: Every response from the "model" is pre-scripted JSON in the fixture file. The fake server returns them in sequence. The model has zero agency -- it cannot decide anything, generate anything, or choose differently based on context. Whatever is in `responses[N].body` is returned verbatim.

3. **API key validation**: The fake server accepts any non-empty `x-goog-api-key` header. `GEMINI_API_KEY` is set to `"fake-key-for-testing"`.

4. **Token counts / usage metadata**: The `usageMetadata` in each fixture response body (`promptTokenCount`, `candidatesTokenCount`) is static fiction. These numbers are returned to the pipeline, and callbacks that read them (like `InstrumentationPlugin.after_model_callback`) will see these values. But they are not measured -- they are fixture constants.

5. **Finish reasons**: `finishReason: "STOP"` in fixture bodies is scripted. The pipeline trusts it, but it was not computed by a real model.

### The Boundary Line

The boundary is the HTTP request/response at `POST /v1beta/models/{model}:generateContent`. Everything above that boundary (the pipeline code making the request) is real. Everything at or below that boundary (the response content) is fake. The pipeline processes the fake responses using real code, which produces real side effects (REPL execution, state mutations, artifacts, traces).

Critically: **the `args.code` field inside a scripted `functionCall` for `execute_code` is fake in the sense that a real model did not generate it, but it is real in the sense that it actually executes as Python**. This dual nature is the fundamental insight of provider-fake testing.

---

## Section 2: Fixture Response Mechanics

### How Responses Are Served

Responses are served **sequentially from a global FIFO queue**, with fault injection overlay. The mechanism lives in `ScenarioRouter.next_response()` (`fixtures.py` lines 301-396).

The router maintains two counters protected by a `threading.Lock`:
- `_call_index`: monotonically incrementing counter across ALL calls from ALL components (reasoning, workers, children at any depth). Every call to `next_response()` increments this.
- `_response_pointer`: index into the `responses[]` array. Only incremented when a normal (non-fault) response is consumed.

The routing logic per call:

```
1. Acquire lock
2. idx = _call_index; _call_index += 1
3. If idx is in _faults dict: return fault response (do NOT advance _response_pointer)
4. If _response_pointer >= len(responses): return exhaustion fallback
5. resp = responses[_response_pointer]; _response_pointer += 1
6. Return (resp.status, resp.body)
```

### How `call_index` Maps to Actual API Calls

The `call_index` field in fixture response entries is **purely documentary** -- it is a note for the fixture author indicating which physical API call they expect this response to serve. The router does NOT use `call_index` from the response entry for routing. It simply returns responses in FIFO order.

The `call_index` field IS used for fault injection: `fault_injections[].call_index` maps to the global `_call_index` counter. When call #N arrives and N matches a fault injection entry, the fault is returned and the normal response pointer is NOT advanced.

Example from `fault_429_then_success.json`:
- Call #0 arrives -> matches `fault_injections[0].call_index: 0` -> returns 429 error
- Call #1 arrives -> no fault match -> consumes `responses[0]` (which has `call_index: 1` annotated, but routing ignores this)

### How `caller: "reasoning"` vs `caller: "worker"` Works

The `caller` field on each response entry is **purely documentary metadata**. The router does NOT examine it for routing decisions. It is recorded into `_captured_metadata` for post-run contract assertions (`expected_contract.callers.sequence`, `expected_contract.callers.counts`).

Mechanically:
- When the reasoning agent makes an LLM call (via ADK's internal `generate_content`), it hits the fake server -> `next_response()` returns the next response in sequence
- When a child orchestrator's reasoning agent makes an LLM call, it hits the same fake server -> `next_response()` returns the next response in sequence

There is NO per-caller routing. There is NO per-depth routing. There is ONE global queue. The fixture author must carefully order responses to match the exact sequence of API calls that the pipeline will make.

### How Child Orchestrator Model Calls Get Routed

A child orchestrator at depth=1 does NOT get its own response queue. It shares the same `ScenarioRouter` and the same global FIFO queue. When the child's `reasoning_agent` needs a model response, it calls `generate_content` which sends an HTTP POST to the fake server, which calls `router.next_response()`, which returns the next response in the global queue.

This means: **the fixture author must predict the exact interleaving of all model calls across all depths and all concurrent children, and order the `responses[]` array accordingly.**

For `skill_arch_test.json`:
```
call #0 -> reasoning (depth=0): returns execute_code with run_test_skill code
call #1 -> worker (depth=1 child): returns set_model_response with "arch_test_ok"
call #2 -> reasoning (depth=0): returns set_model_response (final answer)
```

For `fake_recursive_ping.json` (depth=2, 3 layers):
```
call #0 -> reasoning (depth=0): execute_code with llm_query dispatch
call #1 -> worker (depth=1 child reasoning): execute_code with another llm_query
call #2 -> worker (depth=2 child reasoning): execute_code with terminal payload
call #3 -> worker (depth=2 child reasoning): set_model_response
call #4 -> worker (depth=1 child reasoning): set_model_response (forwards)
call #5 -> reasoning (depth=0): execute_code (second turn, verifies state)
call #6 -> reasoning (depth=0): set_model_response (final)
```

### How `llm_query_batched` With K Prompts Consumes Responses

`llm_query_batched` with K prompts dispatches K concurrent child orchestrators via `asyncio.gather()`. Each child orchestrator makes its own model call(s), consuming responses from the global queue. For K=3 with simple single-call children: **3 responses are consumed** (one per child), not 1.

From `structured_output_batched_k3.json`:
```
call #0 -> reasoning: execute_code with llm_query_batched(3 prompts)
call #1 -> worker 0: set_model_response (positive sentiment)
call #2 -> worker 1: set_model_response (negative sentiment)
call #3 -> worker 2: set_model_response (positive sentiment)
call #4 -> reasoning: final FINAL text
```

**Critical concurrency note**: Because `asyncio.gather()` runs children concurrently (semaphore-limited), the ordering of worker responses in the fixture depends on the order children are dispatched. In practice, `tasks = [_run_child(p, model, output_schema, idx) for idx, p in enumerate(prompts)]` creates tasks in prompt order, and the semaphore (default max 3) allows them to proceed in order. But under different concurrency conditions, the order could vary. For provider-fake tests with deterministic sequential responses, this works because each child acquires the semaphore and makes its API call in the order tasks were created, consuming responses in that order.

### What Happens When Fixtures Have Fewer Responses Than Needed

When `_response_pointer >= len(responses)`, the router returns a fallback response:
```json
{
  "candidates": [{"content": {"role": "model", "parts": [{"text": "FINAL(fixture-exhausted)"}]}, "finishReason": "STOP"}],
  "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2}
}
```

The exhausted call indices are recorded in `_fixture_exhausted_calls`. During contract checking, `check_expectations()` always adds a check:
```python
checks.append({
    "field": "fixture_exhausted_fallback",
    "expected": False,
    "actual": bool(self._fixture_exhausted_calls),
    "ok": not self._fixture_exhausted_calls,
})
```

This means **any fixture that doesn't provide enough responses will fail** the contract automatically, with a diagnostic showing which call indices were exhausted.

### How Status Codes Work

Each response entry can include a `status` field (default 200). The fake server returns this as the HTTP status code. The `google.genai` SDK processes it normally:
- 200: success, body is parsed as `GenerateContentResponse`
- 429: triggers SDK-level retry or propagates as `ClientError` with `code=429`
- 500+: triggers SDK-level retry or propagates as `ServerError`
- 401: propagates as `ClientError` with `code=401`

Fault injections specify `status` explicitly: `"fault_type": "http_error", "status": 429`.

---

## Section 3: The Provider-Fake Contract

### What `expected.final_answer`, `expected.total_iterations`, `expected.total_model_calls` Mean

These are checked in `ScenarioRouter.check_expectations()` (`fixtures.py` lines 398-527):

- **`final_answer`**: Compared against `final_state.get("final_response_text")`. This is the value that `RLMOrchestratorAgent._run_async_impl()` writes to session state via `EventActions(state_delta={depth_key(FINAL_RESPONSE_TEXT, self.depth): final_text})`. Can be an exact string or a matcher dict (`{"$contains": "..."}`, `{"$not_none": true}`, etc.).

- **`total_iterations`**: Compared against `final_state.get("iteration_count")`. This is the value that `REPLTool.run_async()` writes via `tool_context.state[depth_key(ITERATION_COUNT, self._depth)] = self._call_count`. It equals the number of `execute_code` tool calls that the reasoning agent made at depth=0.

- **`total_model_calls`**: Compared against `self._call_index` (the router's global call counter). This is the total number of API calls across ALL components at ALL depths. It includes reasoning calls, worker calls, child orchestrator calls, retried calls -- everything that hit the fake server.

### What `expected_state` Operators Are Available

The `expected_state` section uses the `_match_value()` function with these operators:

| Operator | Meaning | Example |
|---|---|---|
| (plain value) | Exact equality | `"repo_url": "https://example.com"` |
| `$not_none` | Value is not None | `{"$not_none": true}` |
| `$not_empty` | Not None and not zero-length | `{"$not_empty": true}` |
| `$contains` | Substring match (str only) | `{"$contains": "arch_context.txt"}` |
| `$gt`, `$gte`, `$lt`, `$lte` | Numeric comparison | `{"$gte": 3}` |
| `$has_key` | Dict contains key | `{"$has_key": "stdout"}` |
| `$type` | Type check | `{"$type": "dict"}` |
| `$len_gte`, `$len_eq` | Length comparison | `{"$len_gte": 5}` |
| `$oneof` | Value in list | `{"$oneof": ["a", "b"]}` |
| `$absent` | Key should NOT exist in state | `{"$absent": true}` |

Operators can be combined in a single dict (ANDed): `{"$not_none": true, "$contains": "hello"}`.

### How the Contract Test Passes or Fails

`check_expectations()` builds a list of `checks` -- each is a dict with `{field, expected, actual, ok, detail}`. After all checks run, `passed = all(c["ok"] for c in checks)`. The result is a `ContractResult` with `.passed` and `.diagnostics()`.

In tests, the typical assertion is:
```python
result = await run_fixture_contract(fixture_path)
assert result.passed, result.diagnostics()
```

### Diagnostics on Failure

`ContractResult.diagnostics()` produces a multi-line report:
```
FAIL: skill_arch_test  (tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json)
  elapsed: 0.42s

  Checks:
    [ok] final_answer: expected=... actual=...
    [MISMATCH] total_iterations: expected=1 actual=2  (expected 1, got 2)
    [ok] state:user_provided_ctx: expected={'$not_none': True} actual={...}

  Call log (3 calls):
    #0  model=gemini-fake  sys=True  contents=1  preview='...'
    #1  model=gemini-fake  sys=True  contents=1  preview='...'
    #2  model=gemini-fake  sys=True  contents=2  preview='...'
```

The `call_summary` includes all requests the fake server received, with model name, system instruction presence, content count, and text preview. This is essential for debugging response ordering issues.

The `expected_contract` section enables richer structural assertions (see `_check_contract_invariants()` in `fixtures.py`):
- `callers.sequence`: exact sequence of caller types
- `callers.counts`: caller type counts
- `callers.count`: total call count
- `captured_requests.count`: total captured requests
- `events.part_counts`: counts of function_call, function_response, text events
- `events.part_sequence`: ordered subsequence of event parts
- `tool_results.count`: number of tool results
- `tool_results.any[]`: structural match against any tool result
- `tool_results.stdout_contains` / `stderr_contains`: string search in tool stdout/stderr
- `observability`: state key structural assertions (nested matcher support)

---

## Section 4: How to Design a Multi-Depth Fixture

### Prerequisite: Map the Exact Call Sequence

For a fixture with 3+ turns, depth=2+, both `llm_query` and `llm_query_batched`, and a child calling `llm_query`, you must trace through the pipeline code to determine the exact sequence of API calls.

#### Example: Root calls execute_code with `llm_query_batched(2 prompts)`, then execute_code with `llm_query`, then set_model_response. One of the batch children itself calls `llm_query`.

**Step-by-step call sequence:**

```
call #0 (reasoning, depth=0):
  Response: functionCall execute_code
  args.code: Contains llm_query_batched(["prompt_A", "prompt_B"])
  -> REPL executes code for real
  -> llm_query_batched dispatches 2 children at depth=1

call #1 (worker, depth=1 child 0 for prompt_A):
  This child's reasoning agent makes its first API call.
  Response: functionCall execute_code
  args.code: Contains llm_query("sub_prompt") -- this child calls llm_query!
  -> Child 0's REPL executes code, dispatching a depth=2 grandchild

call #2 (worker, depth=2 grandchild of child 0):
  Response: set_model_response with final_answer: "grandchild_result"
  -> Grandchild completes, returns to child 0's REPL

call #3 (worker, depth=1 child 0 again):
  Child 0's reasoning agent sees REPL output, makes second API call.
  Response: set_model_response with final_answer: "child_0_with_grandchild"
  -> Child 0 completes, returns to root's llm_query_batched

call #4 (worker, depth=1 child 1 for prompt_B):
  This child makes a simple single-call response.
  Response: set_model_response with final_answer: "child_1_simple"
  -> Child 1 completes

[Root's llm_query_batched now has both results]

call #5 (reasoning, depth=0):
  Root reasoning sees REPL output from batched results.
  Response: functionCall execute_code
  args.code: Contains llm_query("another_prompt")
  -> Root REPL dispatches another depth=1 child

call #6 (worker, depth=1 child for "another_prompt"):
  Response: set_model_response with final_answer: "another_result"

call #7 (reasoning, depth=0):
  Root reasoning sees all results.
  Response: functionCall set_model_response
  args: {final_answer: "combined result", reasoning_summary: "..."}
```

**CRITICAL CONCURRENCY CAVEAT for `llm_query_batched`**: Children 0 and 1 run concurrently via `asyncio.gather()`. In the example above, I assumed child 0's calls (#1, #2, #3) complete before child 1's call (#4). This works in provider-fake because:
1. The semaphore default is 3, so both children can run "concurrently"
2. `asyncio.gather()` schedules tasks in order
3. Child 0 starts first, acquires the semaphore first, and makes its first API call first
4. While child 0 is blocked waiting for its REPL to execute (which dispatches grandchild at call #2), child 1 may or may not have started yet
5. In practice with the fake server, network latency is ~0, so the ordering is deterministic within a single event loop

However, if child 0's code execution is fast (no `llm_query` inside) and child 1's is also fast, their API calls might interleave differently. **The safest design for multi-depth batched fixtures is to have simple single-call children, or to carefully test the actual interleaving.**

### What Code Goes in `execute_code` args

The `args.code` field is a string of Python code that will actually execute in the REPL. Since the "model" can't reason about what to write, the fixture author scripts this code to exercise the desired pipeline behavior.

Key points:
- Code can reference `llm_query`, `llm_query_batched` (wired into REPL globals by thread bridge)
- Code can reference `_rlm_state` (injected by REPLTool as the state snapshot)
- Code can reference `user_ctx` (injected by orchestrator if `user_provided_ctx` is in initial state)
- Code can reference skill functions like `run_test_skill` (if `enabled_skills` is configured)
- Code can reference `LLMResult` (injected by orchestrator)
- `print()` output becomes real `stdout` in the tool result
- Variable assignments persist across `execute_code` calls within the same depth
- `import` statements work normally

### What Goes in `set_model_response` args

For reasoning agent (depth=0) finalization:
```json
{"name": "set_model_response", "args": {"final_answer": "...", "reasoning_summary": "..."}}
```
ADK's `SetModelResponseTool` processes this. The `final_answer` field populates the `reasoning_output` output key, which the orchestrator reads via `_collect_completion()`.

For child orchestrators (depth > 0):
```json
{"name": "set_model_response", "args": {"final_answer": "...", "reasoning_summary": "..."}}
```
Same mechanism. The child's `CompletionEnvelope` is built from the `set_model_response` result, and `_read_child_completion()` in `dispatch.py` extracts the `display_text` to return as the `LLMResult` string to the parent's REPL.

For structured output children (with `output_schema`):
```json
{"name": "set_model_response", "args": {"sentiment": "positive", "confidence": 0.95}}
```
The args are the schema fields directly. ADK validates against the schema, and the result goes into `LLMResult.parsed`.

### How to Determine Correct `call_index` Ordering

1. Start with the root reasoning agent's first call (always call #0)
2. Read its response: if it's `execute_code`, look at the code
3. If the code calls `llm_query(prompt)`: the NEXT call (#1) is the child's first model call
4. If the child's response is `execute_code` with code that calls `llm_query()`: follow the recursion
5. When a child calls `set_model_response`, that depth unwinds. The NEXT call after is either another child (if batched) or the parent's next model call
6. Track the order carefully on paper before writing the fixture

**Use the `caller` annotations and `note` fields to document your reasoning.** The `caller` field has no mechanical effect but is essential for human understanding and for `expected_contract.callers.sequence` assertions.

---

## Section 5: What Can Be Asserted and Where

### Signals From REAL Execution

| Signal | Source | How to Assert |
|---|---|---|
| REPL stdout | `print()` in execute_code code | `expected_contract.tool_results.stdout_contains`, `expected_contract.observability.last_repl_result.stdout.$contains`, or instrumented runner's `repl_stdout` |
| REPL stderr | Exceptions in execute_code code | `expected_contract.tool_results.stderr_contains` |
| REPL variables | Variable assignments in code | `expected_contract.tool_results.any[].variables` |
| `iteration_count` | REPLTool increments `self._call_count` | `expected.total_iterations` or `expected_state.iteration_count` |
| `last_repl_result` | REPLTool writes after each execution | `expected_state.last_repl_result.$not_none` |
| State keys written by real code | Orchestrator initial state, REPLTool, plugins | `expected_state` with any matcher operator |
| SQLite traces | `SqliteTracingPlugin` real writes | Query `traces_db_path` after run |
| Artifacts | `save_repl_code`, `save_final_answer` | Inspect `artifact_root` after run |
| `[TEST_SKILL:key=value]` tags | `run_test_skill()` prints to stdout | `expected_lineage.py` test_skill expectations, parsed by `stdout_parser.py` |
| `[PLUGIN:hook:agent:key=value]` tags | `InstrumentationPlugin` prints to stdout | `expected_lineage.py` plugin_hook expectations |
| `[STATE:scope:key=value]` tags | `InstrumentationPlugin` state snapshots | `expected_lineage.py` state_key expectations |
| `[TIMING:label=ms]` tags | `InstrumentationPlugin` timing measurements | `expected_lineage.py` timing expectations |
| Thread bridge latency | `time.perf_counter()` around `llm_query_fn()` in skill code | `TEST_SKILL:thread_bridge_latency_ms` tag |
| `total_model_calls` | Router's `_call_index` counter | `expected.total_model_calls` |
| Caller sequence | Router's `_captured_metadata` | `expected_contract.callers.sequence` |
| Event structure | ADK events from `runner.run_async()` | `expected_contract.events.part_counts`, `expected_contract.events.part_sequence` |

### Signals From FAKE Responses

| Signal | Source | Nature |
|---|---|---|
| Token counts | `usageMetadata` in fixture body | Scripted fiction; callbacks that read them see fixture values |
| Finish reasons | `finishReason` in fixture body | Scripted; pipeline trusts them |
| Model version | `modelVersion` in fixture body | Scripted string |
| Response text content | `parts[].text` in fixture body | Scripted; only meaningful when the pipeline uses it (e.g., child response text flowing back to parent REPL as `LLMResult` string) |
| Function call decisions | `functionCall` in fixture body | Scripted; the model did not "decide" to call execute_code or set_model_response |

### The Crucial Dual-Nature Insight

The `execute_code` args contain code that was scripted by the fixture author, NOT generated by a model. But that code **actually runs**. So the outputs of that code (stdout, state mutations, variable values) are real pipeline outputs.

This creates a chain of trust:
1. Fixture scripts `execute_code` with `code: "result = llm_query('prompt')\nprint(result)"` (SCRIPTED)
2. REPLTool executes this code for real (REAL)
3. `llm_query('prompt')` dispatches a child orchestrator via thread bridge (REAL)
4. Child makes an API call to fake server (REAL dispatch, FAKE response)
5. Fake server returns `set_model_response` with `"arch_test_ok"` (FAKE)
6. Child orchestrator processes this via `CompletionEnvelope` (REAL processing)
7. `_read_child_completion()` extracts display_text (REAL)
8. `LLMResult("arch_test_ok")` is returned to the REPL (REAL return)
9. `print(result)` outputs `"arch_test_ok"` to stdout (REAL stdout)

The stdout is real. The state mutations are real. The SQLite traces are real. The only thing that's fake is the content of what the "model" decided to say.

---

## Section 6: Anti-Reward-Hacking in Provider-Fake Context

### What "Non-Reward-Hacking" Means When Responses Are Pre-Scripted

In the provider-fake context, "reward hacking" means writing assertions that merely confirm the fixture's scripted content flows through the pipeline unchanged, without verifying that the pipeline actually did meaningful work. The assertion passes trivially because the fixture was designed to make it pass.

### Strong Assertions (Depend on REAL Execution)

**Assert on REPL stdout from real code execution:**
- `child_result_preview=arch_test_ok` is STRONG because the test_skill code actually called `llm_query_fn(child_prompt)`, the thread bridge actually dispatched a child orchestrator, the child actually made an API call, the child's `CompletionEnvelope` actually processed the response, and the `LLMResult` was actually returned through the thread bridge to the skill function. If any link in this chain breaks, the tag is absent or wrong.

**Assert on `iteration_count`:**
- `iteration_count=1` is STRONG because `REPLTool.run_async()` actually increments `self._call_count` and writes it to `tool_context.state`. If `execute_code` was never invoked by ADK's tool-calling loop, this value stays at 0.

**Assert on `total_model_calls`:**
- `total_model_calls=3` is STRONG because the router's `_call_index` counts every HTTP request that actually hit the fake server. If the pipeline doesn't dispatch a child (e.g., thread bridge is broken), only 1 or 2 calls arrive instead of 3.

**Assert on `callers.sequence`:**
- `["reasoning", "worker", "reasoning"]` is STRONG because it verifies the actual interleaving of API calls. If the child dispatch path changes, the sequence changes.

**Assert on `tool_results.any[].variables`:**
- `"variables": {"root_pong": "pong"}` in `fake_recursive_ping.json` is STRONG because the REPL code `root_pong = root_payload["my_response"]` actually ran, parsing real JSON from the child's returned string.

**Assert on `last_repl_result.has_errors: false`:**
- STRONG because the REPL actually executed the code without raising an exception.

**Assert on `stdout_contains` with content from REPL computation:**
- `"$contains": "iteration_2_count=2"` is STRONG because the REPL code `print(f"iteration_2_count={_rlm_state.get('iteration_count', 'MISSING')}")` reads from the real `_rlm_state` snapshot, which reflects the real `iteration_count` state key.

**Assert on `[TEST_SKILL:COMPLETE=True]`:**
- STRONG because `run_test_skill()` only emits this tag if the entire function runs without exception, including the `llm_query_fn()` call through the thread bridge.

### Weak Assertions (Merely Confirm Scripted Content)

**Assert on `final_answer` as exact string match:**
- `"final_answer": "Architecture test complete. Skill expanded..."` is WEAK because the fixture scripts exactly this string in the `set_model_response` args, and the pipeline just passes it through. The only thing this tests is that `CompletionEnvelope` extraction is not broken -- which is a valid but low-value test.

**Assert on token counts:**
- `"input_tokens": 300` is WEAK because the fixture scripted `"promptTokenCount": 300`. The pipeline does nothing meaningful with this value except pass it to observability callbacks.

**Assert on `finish_reason: "STOP"`:**
- WEAK because the fixture scripted `"finishReason": "STOP"`.

### The Spectrum: How to Maximize Assertion Strength

The strongest provider-fake tests design REPL code that:

1. **Performs computation on child results**: Instead of just printing the child's response, parse it as JSON, extract fields, compute derived values, and print/store those. Assert on the derived values.

2. **Reads real state**: Print `_rlm_state` contents and assert on the tagged output. The state values come from real pipeline state mutation, not from the fixture.

3. **Uses multiple iterations**: Have the reasoning agent call `execute_code` twice. On the second call, read state that was written by the first call's real execution. Assert on the second call's stdout.

4. **Exercises error paths**: Script code that might fail (e.g., `json.loads(child_result)` where the child returns non-JSON), and assert on `has_errors` or `stderr_contains`.

5. **Uses `expected_contract` structural assertions**: These verify the pipeline's event structure, call sequence, and tool result shapes -- all of which depend on real ADK event processing.

The weakest provider-fake tests assert only on `final_answer` exact string match.

### Summary Table

| Assertion | Strength | Why |
|---|---|---|
| `child_result_preview=arch_test_ok` | STRONG | Thread bridge + child dispatch must actually work |
| `iteration_count=1` | STRONG | REPLTool must actually execute |
| `total_model_calls=3` | STRONG | Correct number of API calls must occur |
| `callers.sequence=[R,W,R]` | STRONG | Call interleaving must match pipeline behavior |
| `tool_results.any[].variables.root_pong="pong"` | STRONG | REPL code must actually parse child output |
| `stdout_contains "iteration_2_count=2"` | STRONG | Real state read from second REPL turn |
| `[TEST_SKILL:COMPLETE=True]` | STRONG | Full skill function must run without error |
| `last_repl_result.$not_none` | MODERATE | Confirms REPLTool ran, but not what it did |
| `final_answer="exact scripted text"` | WEAK | Just confirms passthrough of scripted response |
| `usageMetadata.promptTokenCount=300` | NONE | Pure fixture fiction |

---

## Appendix: Key File Reference

| File | Role |
|---|---|
| `tests_rlm_adk/provider_fake/fixtures.py` | `ScenarioRouter` (FIFO routing, matchers, `ContractResult`) |
| `tests_rlm_adk/provider_fake/server.py` | `FakeGeminiServer` (aiohttp, HTTP handler) |
| `tests_rlm_adk/provider_fake/contract_runner.py` | `run_fixture_contract()`, `run_fixture_contract_with_plugins()` |
| `tests_rlm_adk/provider_fake/instrumented_runner.py` | `run_fixture_contract_instrumented()`, `InstrumentationPlugin` |
| `tests_rlm_adk/provider_fake/conftest.py` | `fake_gemini` pytest fixture |
| `tests_rlm_adk/provider_fake/expected_lineage.py` | All expectation types and assertion functions |
| `tests_rlm_adk/provider_fake/stdout_parser.py` | `parse_stdout()` -> `ParsedLog` |
| `tests_rlm_adk/fixtures/provider_fake/*.json` | Fixture files |
| `rlm_adk/orchestrator.py` | `RLMOrchestratorAgent._run_async_impl()` |
| `rlm_adk/tools/repl_tool.py` | `REPLTool.run_async()` |
| `rlm_adk/dispatch.py` | `create_dispatch_closures()`, child orchestrator spawning |
| `rlm_adk/repl/thread_bridge.py` | `make_sync_llm_query()`, `make_sync_llm_query_batched()` |
| `rlm_adk/skills/test_skill/skill.py` | `run_test_skill()` -- exercised by `skill_arch_test.json` |
| `rlm_adk/skills/loader.py` | Skill discovery, `collect_skill_repl_globals()` |
