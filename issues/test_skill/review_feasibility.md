# Feasibility Review: Multi-Depth Provider-Fake Fixture

**Document**: `/home/rawley-stanhope/dev/rlm-adk/issues/test_skill/review_feasibility.md`
**Date**: 2026-03-25
**Reviewer**: Feasibility Review Agent
**Scope**: Verify proposed fixture design against real code; draft exact response array

---

## 1. Verified Call Sequence

The proposed scenario has three root reasoning turns: two `execute_code` calls and one `set_model_response`. Turn 1 exercises depth=2 via `run_test_skill` -> `llm_query` -> child `execute_code` -> `llm_query` -> grandchild `set_model_response`. Turn 2 exercises `llm_query_batched` with 2 prompts. Turn 3 is the root's final `set_model_response`.

### Turn 1 Trace (depth=0 execute_code with run_test_skill -> depth=2 chain)

**Call #0 (depth=0, reasoning agent)**
- Root reasoning agent makes first model API call.
- Fixture response: `functionCall execute_code` with code calling `run_test_skill(child_prompt='...', emit_debug=True, rlm_state=_rlm_state)`.
- **What happens in REPLTool.run_async()**:
  1. `repl_tool.py:130` — `self._call_count` incremented to 1, written to `tool_context.state[depth_key(ITERATION_COUNT, 0)]`.
  2. `repl_tool.py:165-187` — `_rlm_state` snapshot built from `EXPOSED_STATE_KEYS` + lineage metadata, injected into `repl.globals["_rlm_state"]`.
  3. `repl_tool.py:193` — `self.repl.execute_code_threaded(exec_code, trace=trace)` called.
  4. `local_repl.py:437-490` — Code runs in a worker thread via `loop.run_in_executor()`.
  5. Inside the worker thread, `run_test_skill()` executes. The loader wrapper (`loader.py:84-94`) injects `llm_query_fn=repl_globals["llm_query"]` at call time.
  6. `skill.py:97` — `llm_query_fn(child_prompt)` is called.
- **What happens in thread_bridge when llm_query() is called**:
  1. `thread_bridge.py:70-88` — The sync `llm_query()` closure runs in the worker thread.
  2. Thread depth counter incremented (`_THREAD_DEPTH.set(depth + 1)`).
  3. `asyncio.run_coroutine_threadsafe(llm_query_async(prompt), loop)` submits the coroutine to the event loop.
  4. `future.result(timeout=300.0)` blocks the worker thread.
  5. On the event loop thread: `dispatch.py:441` — `llm_query_async` delegates to `llm_query_batched_async([prompt])`.
  6. `dispatch.py:499` — `_run_child(prompt, model, None, 0)` creates a child orchestrator at depth=1.

**Call #1 (depth=1, child reasoning agent)**
- Child `RLMOrchestratorAgent(depth=1)` is created by `create_child_orchestrator()` (`agent.py:329-385`).
- Child's `_run_async_impl` runs: creates a new `LocalREPL`, injects skill globals via `collect_skill_repl_globals()`, wires dispatch closures, creates its own `REPLTool`, wires `reasoning_agent.tools = [repl_tool, set_model_response_tool]`.
- Child's reasoning agent makes a model API call — consumes response #1 from the FIFO queue.
- Fixture response: `functionCall execute_code` with code that calls `llm_query("some_grandchild_prompt")`.
- Child's REPLTool runs the code in a worker thread. Inside, `llm_query()` dispatches via the child's own thread bridge to the event loop.
- A grandchild orchestrator at depth=2 is created.

**Call #2 (depth=2, grandchild reasoning agent)**
- Grandchild `RLMOrchestratorAgent(depth=2)` created. Its reasoning agent makes a model API call — consumes response #2.
- Fixture response: `functionCall set_model_response` with `final_answer: "grandchild_result"`.
- ADK processes the `set_model_response` tool call. The grandchild's reasoning loop terminates.
- `_collect_completion()` builds a `CompletionEnvelope`. The grandchild orchestrator yields final state events and content.
- The grandchild's `LLMResult("grandchild_result")` is returned to depth=1's REPL code via the thread bridge.

**Call #3 (depth=1, child reasoning agent — resumed)**
- The child's REPL code completes (the `llm_query()` returned). REPLTool writes `LAST_REPL_RESULT`.
- ADK's tool loop sends the REPL output back to the child's reasoning agent. The reasoning agent makes another model API call — consumes response #3.
- Fixture response: `functionCall set_model_response` with `final_answer: "child_with_grandchild_result"`.
- Child orchestrator terminates. `LLMResult("child_with_grandchild_result")` is returned to depth=0's `run_test_skill()` call.

**Back in run_test_skill at depth=0**:
- `skill.py:99` — `child_result = llm_query_fn(child_prompt)` returns.
- The skill prints `[TEST_SKILL:child_result_preview=child_with_grandchild_result]`, `[TEST_SKILL:COMPLETE=True]`, etc.
- REPLTool finishes: writes `LAST_REPL_RESULT` with `llm_calls_made: true, execution_mode: thread_bridge`.

**IMPORTANT CORRECTION**: The `run_test_skill()` function calls `llm_query_fn()` which dispatches to a **child at depth=1**. That child's fixture response says `execute_code` (which creates its own REPL and calls `llm_query`), spawning a **grandchild at depth=2**. This is correct for depth=2.

However, the child at depth=1 receives the `run_test_skill` call's prompt, NOT "run_test_skill" itself. The skill function only runs at depth=0 in the root REPL. The child at depth=1 is a plain child orchestrator whose reasoning agent decides (per the fixture) to call `execute_code` with code containing `llm_query(...)`.

### Turn 2 Trace (depth=0 execute_code with llm_query_batched)

**Call #4 (depth=0, reasoning agent — resumed for turn 2)**
- Root reasoning agent sees REPL output from Turn 1 and makes another model API call — consumes response #4.
- Fixture response: `functionCall execute_code` with code calling `llm_query_batched(["prompt_A", "prompt_B"])`.
- REPLTool runs the code. In the worker thread, `llm_query_batched(["prompt_A", "prompt_B"])` is called.
- `thread_bridge.py:123-132` — sync `llm_query_batched` dispatches to the event loop.
- `dispatch.py:464-535` — `llm_query_batched_async` creates 2 tasks: `_run_child(prompt_A, ..., fanout_idx=0)` and `_run_child(prompt_B, ..., fanout_idx=1)`.
- `asyncio.gather(*tasks)` runs both concurrently (semaphore default=3).

**Call #5 (depth=1, batch child 0 reasoning agent)**
- Child orchestrator at depth=1 (fanout_idx=0) makes a model API call — consumes response #5.
- Fixture response: `functionCall set_model_response` with `final_answer: "batch_result_A"`.
- Child completes.

**Call #6 (depth=1, batch child 1 reasoning agent)**
- Child orchestrator at depth=1 (fanout_idx=1) makes a model API call — consumes response #6.
- Fixture response: `functionCall set_model_response` with `final_answer: "batch_result_B"`.
- Child completes.

**Back in root REPL**:
- `llm_query_batched` returns `[LLMResult("batch_result_A"), LLMResult("batch_result_B")]`.
- Root REPL code prints results. REPLTool writes updated `LAST_REPL_RESULT`.

### Turn 3 Trace (depth=0 set_model_response)

**Call #7 (depth=0, reasoning agent — final)**
- Root reasoning agent sees Turn 2 REPL output, makes final model API call — consumes response #7.
- Fixture response: `functionCall set_model_response` with final answer.
- Reasoning loop terminates. Orchestrator builds `CompletionEnvelope`, yields final state and content events.

### Complete Call Table

| Call # | Depth | Caller | Agent | Action | Notes |
|--------|-------|--------|-------|--------|-------|
| 0 | 0 | reasoning | reasoning_agent | execute_code | run_test_skill code |
| 1 | 1 | worker | child_reasoning_d1 | execute_code | child calls llm_query for d2 |
| 2 | 2 | worker | child_reasoning_d2 | set_model_response | grandchild leaf |
| 3 | 1 | worker | child_reasoning_d1 | set_model_response | child returns after grandchild |
| 4 | 0 | reasoning | reasoning_agent | execute_code | llm_query_batched code |
| 5 | 1 | worker | child_reasoning_d1 (f0) | set_model_response | batch child A |
| 6 | 1 | worker | child_reasoning_d1 (f1) | set_model_response | batch child B |
| 7 | 0 | reasoning | reasoning_agent | set_model_response | final answer |

**Total model API calls: 8**

---

## 2. Skill Loading at Child Depths

### Confirmed: Child orchestrators DO get skill functions in their REPL

**Code reference**: `orchestrator.py:266-274`

```python
# Inject skill globals into REPL namespace unconditionally.
# All orchestrators (root and children) get skill functions in REPL
# so child code can call them via the thread bridge.
_skill_globals = collect_skill_repl_globals(
    enabled_skills=self.enabled_skills or None,
    repl_globals=repl.globals,
)
repl.globals.update(_skill_globals)
```

The comment explicitly states "All orchestrators (root and children)" and the code is unconditional. `collect_skill_repl_globals()` is called inside `_run_async_impl()` for every orchestrator instance.

### Confirmed: llm_query is injected into child REPLs

**Code reference**: `orchestrator.py:308-316`

When `self.worker_pool is not None` (which it is for all orchestrators — `create_child_orchestrator` at `agent.py:368-369` creates a `WorkerPool` if none provided):
1. `create_dispatch_closures()` returns `(llm_query_async, llm_query_batched_async, ...)`.
2. `make_sync_llm_query()` and `make_sync_llm_query_batched()` create sync callables.
3. `repl.set_llm_query_fns(sync_llm_query, sync_llm_query_batched)` injects them into the child REPL's globals.

### Confirmed: Child's REPL code can call run_test_skill()

Since `collect_skill_repl_globals()` runs for every orchestrator, and the wrapper reads `repl_globals["llm_query"]` lazily at call time (`loader.py:86`), a child REPL at any depth can call `run_test_skill()` with the correct `llm_query_fn` auto-injected.

### Confirmed: enabled_skills propagation

`create_child_orchestrator()` (`agent.py:329-385`) does NOT pass `enabled_skills` to the child orchestrator. The child's `enabled_skills` defaults to `()` (empty tuple).

However, `collect_skill_repl_globals(enabled_skills=None)` at `orchestrator.py:270-271` will be called with `self.enabled_skills or None`. When `enabled_skills = ()`, this evaluates to `None`, which means `discover_skill_dirs(enabled_skills=None)` returns ALL skill directories. So child orchestrators actually discover and inject ALL skills, not just enabled ones.

**Implication**: The `run_test_skill` function will be available in child REPLs even though the child does not explicitly have `enabled_skills=["test_skill"]`. However, the `SkillToolset` (ADK L1/L2 discovery) is only added to tools when `self.enabled_skills` is truthy (`orchestrator.py:351-354`), so children do NOT get the SkillToolset. This is fine — the skill function in REPL globals is what matters for this fixture.

---

## 3. test_skill.py Depth Compatibility

### Confirmed: run_test_skill() works at any depth

**Code reference**: `skill.py:29-128`

The function signature:
```python
def run_test_skill(
    child_prompt: str = "Reply with exactly: arch_test_ok",
    *,
    emit_debug: bool = True,
    rlm_state: dict[str, Any] | None = None,
    llm_query_fn=None,
) -> TestSkillResult:
```

- `llm_query_fn` is auto-injected by the loader wrapper from `repl_globals["llm_query"]` at call time.
- `rlm_state` is passed explicitly from REPL code (reads `_rlm_state` which is depth-aware via REPLTool).
- The function does NOT access `globals()` or any depth-specific state directly.
- At any depth, it will correctly report `_rlm_depth`, `current_depth`, `iteration_count` from the `_rlm_state` snapshot.

### stdout tags emitted:
```
[TEST_SKILL:depth=<N>]
[TEST_SKILL:rlm_agent_name=<agent_name>]
[TEST_SKILL:iteration_count=<count>]
[TEST_SKILL:current_depth=<N>]
[TEST_SKILL:should_stop=<bool>]
[TEST_SKILL:state_keys_count=<count>]
[TEST_SKILL:state_keys=<list>]
[TEST_SKILL:execution_mode=thread_bridge]
[TEST_SKILL:llm_query_fn_type=function]
[TEST_SKILL:calling_llm_query=True]
[TEST_SKILL:child_result_preview=<result>]
[TEST_SKILL:thread_bridge_latency_ms=<ms>]
[TEST_SKILL:COMPLETE=True]
[TEST_SKILL:summary=depth=<N> mode=thread_bridge latency_ms=<ms> child_ok=<bool>]
```

**Visibility**: At depth=0, these tags appear in `result.stdout` which is returned to the root reasoning agent and captured in `LAST_REPL_RESULT["stdout"]`. At deeper depths, the tags appear in the child's REPL stdout, which is captured in the child's `LAST_REPL_RESULT@d<N>` and propagated via child event re-emission. However, the parent REPL does NOT see the child's stdout directly — the `LLMResult` string returned to the parent is the child's `final_answer`, not its REPL stdout.

---

## 4. Blockers Found

### Blocker 1: Depth limit check uses `>=` not `>` — SEVERITY: LOW

**Code**: `dispatch.py:281` — `if depth + 1 >= max_depth:`

With default `max_depth=5`:
- depth=0 can dispatch to depth=1 (1 < 5, OK)
- depth=1 can dispatch to depth=2 (2 < 5, OK)
- depth=4 CANNOT dispatch to depth=5 (5 >= 5, blocked)

**Assessment**: Depth=2 is well within limits. NO BLOCKER.

### Blocker 2: REPL timeout for nested dispatch — SEVERITY: MEDIUM

**Code**: `local_repl.py:189-191` — Default `sync_timeout = float(os.environ.get("RLM_REPL_SYNC_TIMEOUT", "30"))`.

When Turn 1 runs `run_test_skill()`:
1. Root REPL's worker thread blocks on `llm_query()` → dispatches child at depth=1.
2. Child's `_run_async_impl` runs on the event loop. Child creates its own REPL.
3. Child's REPL's worker thread blocks on `llm_query()` → dispatches grandchild at depth=2.
4. Grandchild runs on the event loop.

The root REPL's `execute_code_threaded` timeout (`asyncio.wait_for` at `local_repl.py:463`) is 30 seconds. Inside that timeout, the entire depth=2 chain (child creation, child REPL execution, grandchild creation, grandchild response) must complete.

With the fake Gemini server (zero network latency), each model call takes ~0ms. The overhead is Python object creation and event loop scheduling. In practice, this completes in <1 second.

**Assessment**: With provider-fake, 30s timeout is more than sufficient. For safety, the fixture could set `RLM_REPL_SYNC_TIMEOUT=60` in config. NO BLOCKER for provider-fake.

### Blocker 3: llm_query_batched inside run_test_skill — NOT SUPPORTED (but not needed)

The `run_test_skill()` function calls `llm_query_fn()` (singular), not `llm_query_batched()`. The `llm_query_batched` is called directly from REPL code in Turn 2, not through the skill function.

**Assessment**: NO BLOCKER. The fixture design correctly separates skill usage (Turn 1) from batched dispatch (Turn 2).

### Blocker 4: Concurrency ordering for llm_query_batched — SEVERITY: LOW

`asyncio.gather(*tasks)` at `dispatch.py:500` runs tasks in creation order. With semaphore=3 and 2 prompts, both children can proceed immediately. The first child (fanout_idx=0) will acquire the semaphore first and make its API call first. The second child follows.

With the fake server returning responses sequentially from a global FIFO queue, the ordering is deterministic: child 0 consumes response #5, child 1 consumes response #6.

**Assessment**: Deterministic in provider-fake. NO BLOCKER.

### Blocker 5: InstrumentedRunner can handle 8 model calls — SEVERITY: NONE

The `ScenarioRouter` uses a simple FIFO queue with no limit on response count. The router's `_call_index` counter is unbounded. 8 responses is well within capability.

**Assessment**: NO BLOCKER.

### Blocker 6: Child's `include_contents="none"` — SEVERITY: NONE

`create_child_orchestrator` sets `include_contents="none"` on the child's reasoning agent (`agent.py:365`). The orchestrator's `_run_async_impl` only overrides this for `depth==0` (`orchestrator.py:381-382`). This means child reasoning agents do NOT see prior conversation history in their context, but they DO receive the root_prompt as a user content event (`orchestrator.py:504-512`).

**Assessment**: Children see only the root_prompt (which is the `llm_query` prompt text). This is correct — the fixture response for each child only needs to respond to that single prompt. NO BLOCKER.

---

## 5. Observability at Each Depth

### Depth=0 (Root)

**Captured by REPLTool** (`repl_tool.py:269-283`):
- `last_repl_result` — full dict with `stdout`, `stderr`, `has_errors`, `total_llm_calls`, `execution_mode`, `stdout_preview`.
- `iteration_count` — incremented on each `execute_code` call.
- `repl_submitted_code` / `repl_submitted_code_chars` / `repl_submitted_code_hash` — per code submission.

**Captured by InstrumentationPlugin** (`instrumented_runner.py:68-338`):
- `[PLUGIN:before_agent:reasoning_agent:depth=0]`
- `[PLUGIN:before_model:reasoning_agent:call_num=N]`
- `[PLUGIN:before_tool:reasoning_agent:tool_name=execute_code]`
- `[PLUGIN:after_tool:reasoning_agent:...]`
- `[STATE:...]` tags for all curated state keys.
- `[TIMING:...]` tags for agent, model, tool durations.

**Captured by REPLCapturePlugin** (`repl_capture_plugin.py:80-157`):
- `before_tool_callback` / `after_tool_callback` — captures `depth`, `agent_name`, `submitted_code`, `stdout`, `stderr`, `variables`, `rlm_state_snapshot` for each `execute_code` at depth=0.

**Captured by SqliteTracingPlugin**:
- `traces` table: row for the invocation with depth, model, timing.
- `session_state_events` table: rows for each state_delta yield.
- `tool_telemetry` table: rows for each tool invocation.

### Depth=1 (Child)

**Captured within child's execution**:
- Child's `REPLTool` writes `last_repl_result@d1`, `iteration_count@d1`, etc. to `tool_context.state`.
- These state writes create events with `state_delta` containing depth-suffixed keys.

**Visible to parent via child event re-emission** (`dispatch.py:318-343`):
- `_run_child()` iterates over child events. For each event with `state_delta`:
  - Keys are parsed via `parse_depth_key()`.
  - Keys matching `should_capture_state_key()` are curated into a new Event.
  - Event is put onto `child_event_queue` with `custom_metadata={"rlm_child_event": True, "child_depth": 1}`.
- The orchestrator drains `child_event_queue` after each reasoning event (`orchestrator.py:522-528`).
- These re-emitted events flow to the ADK Runner, which commits them to session state.

**Result**: `session_state_events` table will contain rows with keys like `current_depth@d1`, `should_stop@d1`, `final_response_text@d1` with `key_depth=1`.

**InstrumentationPlugin for child agents**:
- The `InstrumentationPlugin` is a global plugin on the Runner. However, child orchestrators run via `child.run_async(child_ctx)` inside `_run_child()` — these are NOT processed by the Runner's event loop. The plugin callbacks fire for the Runner's event stream, not for nested `run_async` calls.
- **Consequence**: InstrumentationPlugin does NOT fire for depth=1 or depth=2 agents directly. Only the curated child events re-emitted to the parent's event stream are visible.

**REPLCapturePlugin for child agents**:
- Same limitation: `REPLCapturePlugin` callbacks fire only for tool invocations processed by the Runner. Child tool invocations at depth=1 are NOT visible to the plugin.

### Depth=2 (Grandchild)

**Captured within grandchild's execution**:
- Grandchild calls `set_model_response` immediately (no `execute_code`). So `last_repl_result@d2` is NOT written (no REPL execution at depth=2 for this grandchild).
- However, `current_depth@d2=2`, `should_stop@d2=True`, `final_response_text@d2="grandchild_result"` ARE written via `EventActions(state_delta=...)`.

**Visible to parent (depth=1) via child event re-emission**:
- Depth=1's `_run_child()` captures depth=2's state delta events and pushes them to depth=1's `child_event_queue`.
- Depth=1's orchestrator drains those events into its own event stream.

**Visible to root (depth=0)**:
- Depth=0's `_run_child()` captures depth=1's events (which include re-emitted depth=2 events). These get pushed to depth=0's `child_event_queue`.
- The root orchestrator drains them after each reasoning event.
- **Result**: Root's `session_state_events` table will contain rows for depth=2 keys, BUT the re-emission is NOT recursive across multiple levels automatically.

**CRITICAL FINDING**: Let me re-examine the re-emission chain.

When depth=1's orchestrator runs:
1. Depth=1's `_run_async_impl()` creates a `_child_event_queue` for depth=2 events.
2. Depth=1's `create_dispatch_closures()` receives this queue as `child_event_queue`.
3. When depth=2 grandchild runs inside depth=1's `_run_child()`, grandchild events are pushed to depth=1's `_child_event_queue`.
4. Depth=1's `_run_async_impl()` drains `_child_event_queue` after each reasoning event (`orchestrator.py:522-528`) and yields them.

Now, depth=1 itself runs inside depth=0's `_run_child()`. Depth=0's `_run_child()` iterates over depth=1's yielded events (which include the re-emitted depth=2 events). These are then pushed to depth=0's `child_event_queue`.

**Conclusion**: Depth=2 events DO bubble up to depth=0 through the two-stage re-emission chain. The `session_state_events` table at the root level will contain rows for `key_depth=1` AND `key_depth=2`.

---

## 6. Draft Response Array

```json
{
  "scenario_id": "test_skill_depth2_batched",
  "description": "Full pipeline exercise: 3+ reasoning turns, depth=2 via llm_query, llm_query_batched with 2 prompts, child agents calling llm_query, skill function via REPL globals, all observable via stdout/callbacks/SQLite.",
  "config": {
    "model": "gemini-fake",
    "thinking_budget": 0,
    "max_iterations": 10,
    "retry_delay": 0.0,
    "enabled_skills": ["test_skill"],
    "initial_state": {
      "user_provided_ctx": {
        "arch_context.txt": "Architecture validation context for depth=2 + batched dispatch test."
      },
      "repo_url": "https://test.example.com/depth2-batched",
      "root_prompt": "Exercise depth=2 dispatch and batched queries.",
      "skill_instruction": "Use run_test_skill() for depth=2 chain, then llm_query_batched for fanout."
    }
  },
  "responses": [
    {
      "call_index": 0,
      "caller": "reasoning",
      "note": "Turn 1: Root reasoning agent calls execute_code with run_test_skill (skill dispatches depth=1 child via llm_query inside skill code).",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "execute_code",
                "args": {
                  "code": "result = run_test_skill(\n    child_prompt='Analyze the context and call llm_query to go deeper.',\n    emit_debug=True,\n    rlm_state=_rlm_state,\n)\nprint(f'skill_result={result.child_result}')\nprint(f'skill_latency_ms={result.thread_bridge_latency_ms:.1f}')"
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 400, "candidatesTokenCount": 80, "totalTokenCount": 480},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 1,
      "caller": "worker",
      "note": "Depth=1 child reasoning agent (spawned by run_test_skill's llm_query). Child decides to execute_code with its own llm_query to create depth=2.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "execute_code",
                "args": {
                  "code": "grandchild_result = llm_query('Return the leaf value: depth2_leaf_ok')\nprint(f'grandchild_said={grandchild_result}')"
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 150, "candidatesTokenCount": 40, "totalTokenCount": 190},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 2,
      "caller": "worker",
      "note": "Depth=2 grandchild reasoning agent. Leaf node — calls set_model_response immediately.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": {
                  "final_answer": "depth2_leaf_ok",
                  "reasoning_summary": "Returned leaf value as requested."
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 80, "candidatesTokenCount": 20, "totalTokenCount": 100},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 3,
      "caller": "worker",
      "note": "Depth=1 child reasoning agent (resumed after grandchild returned). Sees REPL stdout with grandchild_said=depth2_leaf_ok. Calls set_model_response.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": {
                  "final_answer": "child_confirmed_depth2: depth2_leaf_ok",
                  "reasoning_summary": "Dispatched to depth=2, received leaf value, confirmed."
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 200, "candidatesTokenCount": 30, "totalTokenCount": 230},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 4,
      "caller": "reasoning",
      "note": "Turn 2: Root reasoning agent sees Turn 1 REPL stdout (TEST_SKILL tags + skill_result). Calls execute_code with llm_query_batched(2 prompts).",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "execute_code",
                "args": {
                  "code": "batch_results = llm_query_batched(['Summarize finding A', 'Summarize finding B'])\nfor i, r in enumerate(batch_results):\n    print(f'batch_{i}={r}')\nprint(f'batch_count={len(batch_results)}')"
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 600, "candidatesTokenCount": 60, "totalTokenCount": 660},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 5,
      "caller": "worker",
      "note": "Batch child 0 at depth=1 (fanout_idx=0, prompt='Summarize finding A'). Simple set_model_response.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": {
                  "final_answer": "finding_A_summary",
                  "reasoning_summary": "Summarized finding A."
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 80, "candidatesTokenCount": 15, "totalTokenCount": 95},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 6,
      "caller": "worker",
      "note": "Batch child 1 at depth=1 (fanout_idx=1, prompt='Summarize finding B'). Simple set_model_response.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": {
                  "final_answer": "finding_B_summary",
                  "reasoning_summary": "Summarized finding B."
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 80, "candidatesTokenCount": 15, "totalTokenCount": 95},
        "modelVersion": "gemini-fake"
      }
    },
    {
      "call_index": 7,
      "caller": "reasoning",
      "note": "Turn 3: Root reasoning agent sees both Turn 1 (skill) and Turn 2 (batch) results. Calls set_model_response with final answer.",
      "status": 200,
      "body": {
        "candidates": [{
          "content": {
            "role": "model",
            "parts": [{
              "functionCall": {
                "name": "set_model_response",
                "args": {
                  "final_answer": "Pipeline verified: depth=2 chain succeeded (depth2_leaf_ok via child), batched dispatch returned 2 results (finding_A_summary, finding_B_summary).",
                  "reasoning_summary": "Exercised run_test_skill for depth=2 chain and llm_query_batched for fanout. All components confirmed."
                }
              }
            }]
          },
          "finishReason": "STOP",
          "index": 0
        }],
        "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 60, "totalTokenCount": 860},
        "modelVersion": "gemini-fake"
      }
    }
  ],
  "fault_injections": [],
  "expected": {
    "final_answer": {
      "$contains": "depth=2 chain succeeded"
    },
    "total_iterations": 2,
    "total_model_calls": 8
  },
  "expected_state": {
    "user_provided_ctx": {"$not_none": true},
    "last_repl_result": {"$not_none": true, "$has_key": "execution_mode"},
    "iteration_count": 2,
    "current_depth": 0,
    "should_stop": true,
    "repl_skill_globals_injected": {"$not_none": true}
  },
  "expected_contract": {
    "callers": {
      "sequence": ["reasoning", "worker", "worker", "worker", "reasoning", "worker", "worker", "reasoning"],
      "counts": {"reasoning": 3, "worker": 5},
      "count": 8
    },
    "tool_results": {
      "stdout_contains": ["TEST_SKILL:COMPLETE=True", "batch_count=2", "depth2_leaf_ok"]
    }
  }
}
```

---

## 7. Total Model Calls

**Grand total: 8 model API calls**, cross-checked against the trace:

| Phase | Calls | Subtotal |
|-------|-------|----------|
| Turn 1: Root execute_code | 1 (call #0) | 1 |
| Turn 1: Depth=1 child execute_code | 1 (call #1) | 2 |
| Turn 1: Depth=2 grandchild set_model_response | 1 (call #2) | 3 |
| Turn 1: Depth=1 child set_model_response | 1 (call #3) | 4 |
| Turn 2: Root execute_code | 1 (call #4) | 5 |
| Turn 2: Batch child 0 set_model_response | 1 (call #5) | 6 |
| Turn 2: Batch child 1 set_model_response | 1 (call #6) | 7 |
| Turn 3: Root set_model_response | 1 (call #7) | 8 |

**Formula verification**:
- Turn 1 depth=2 chain: `2 * 2 + 1 = 5` responses... but that formula counts a standalone depth=2 fixture. Here the depth=2 chain is embedded inside Turn 1, which itself is one root call. So: 1 (root execute) + 1 (d1 execute) + 1 (d2 set) + 1 (d1 set) = 4 calls for the depth chain.
- Turn 2: 1 (root execute) + 2 (batch children) = 3 calls.
- Turn 3: 1 (root set) = 1 call.
- Total: 4 + 3 + 1 = **8 calls**.

**Caller sequence**: `[reasoning, worker, worker, worker, reasoning, worker, worker, reasoning]`
- reasoning: 3 (calls #0, #4, #7)
- worker: 5 (calls #1, #2, #3, #5, #6)

---

## Summary

**FEASIBLE**: The proposed scenario is fully implementable with the current codebase. No architectural blockers exist.

Key verified findings:
1. **Depth=2 works**: The depth limit (`max_depth=5` default, `depth + 1 >= max_depth` check) permits dispatch up to depth=4.
2. **Skill functions available at all depths**: `collect_skill_repl_globals()` runs unconditionally in `_run_async_impl()`.
3. **Thread bridge nesting works**: Each depth gets its own event loop submission via `run_coroutine_threadsafe()`.
4. **llm_query_batched ordering is deterministic**: Tasks created in order, semaphore allows all through, fake server is sequential.
5. **Child event re-emission is transitive**: depth=2 events bubble through depth=1 to depth=0.
6. **8 total model calls needed**: 3 reasoning + 5 worker.
7. **InstrumentationPlugin does NOT fire for child agents** — only curated child events re-emitted to the root event stream are visible at the SQLite/plugin level.

---

**End of Feasibility Review**
