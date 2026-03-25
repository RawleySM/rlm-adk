# skill_arch_test.json -- Annotated Walkthrough

## Overview

- **Scenario**: `skill_arch_test`
- **Total responses**: 15
- **Depths exercised**: 0, 1, 2
- **Tools exercised**: `list_skills`, `load_skill`, `execute_code`, `set_model_response`
- **Description**: Full pipeline exercise v2. Exercises SkillToolset L1/L2 discovery at depths 0, 1, and 2. Reaches depth=2 via a `run_test_skill` -> `llm_query` chain. Tests `llm_query_batched` with 2 prompts. Verifies cross-turn REPL persistence. Proves GAP-A (children get SkillToolset) and GAP-D (children get dynamic instruction) fixes.

### What This Fixture Tests

This fixture is a deterministic, canned-response script for the provider-fake test harness. It replaces the real Gemini API so the entire RLM-ADK pipeline -- orchestrator, REPL, thread bridge, skill system, and recursion -- runs end-to-end with no network calls. Each of the 15 responses below is served in order by a local `FakeGeminiServer` whenever the pipeline makes a model call.

The fixture validates several architectural properties:

1. **Skill discovery at every depth** -- `list_skills` (L1) and `load_skill` (L2) are called at depth 0, 1, and 2, proving children inherit the SkillToolset.
2. **Depth-2 recursion** -- The root agent calls `run_test_skill()`, which internally calls `llm_query()` to spawn a child. That child calls `llm_query()` again to spawn a grandchild. The grandchild returns a leaf value that propagates all the way back up.
3. **Batched dispatch** -- After the depth-2 chain completes, the root agent calls `llm_query_batched()` with 2 prompts, spawning 2 parallel child agents.
4. **Cross-turn REPL persistence** -- Variables set in REPL turn 1 are still accessible in turn 2.
5. **State propagation** -- `_rlm_state` keys (including dynamic instruction keys like `repo_url`, `root_prompt`) are verified at depth=2.

---

## Config

| Key | Value |
|-----|-------|
| model | `gemini-fake` |
| thinking_budget | `0` |
| max_iterations | `10` |
| retry_delay | `0.0` |
| enabled_skills | `["test_skill"]` |

### Initial State Keys

| Key | Value |
|-----|-------|
| `user_provided_ctx` | `{"arch_context.txt": "Architecture validation context for depth=2 + batched dispatch test.", "test_metadata.json": "{\"scenario\": \"skill_arch_test\", ...}"}` |
| `repo_url` | `https://test.example.com/depth2-batched` |
| `root_prompt` | `Exercise depth=2 dispatch and batched queries.` |
| `test_context` | `Provider-fake e2e run: depth=2 chain + batched dispatch verification.` |
| `skill_instruction` | `Use run_test_skill() for depth=2 chain, then llm_query_batched for fanout.` |

### Expected Outcomes

| Assertion | Value |
|-----------|-------|
| `final_answer` | Must contain `"depth=2 chain succeeded"` |
| `total_iterations` | `2` |
| `total_model_calls` | `15` |
| `iteration_count` (state) | `2` |
| `should_stop` (state) | `true` |

---

## Response Sequence

---

### Call 0 -- list_skills (depth=0, caller=reasoning)

**Context**: The root reasoning agent begins its first turn by discovering what skills are available. `list_skills` is the L1 (Level 1) discovery tool -- it returns an XML catalog of all registered skills with their names and short descriptions. The agent uses this to decide which skills might be useful before loading any of them.

**Note**: idx 0 / d0: Root reasoning agent calls list_skills for L1 skill discovery. SkillToolset returns available skills XML catalog.

**Tool call**: `list_skills` with no arguments.

**Usage**: prompt=300 | candidate=15 | total=315 tokens

> Flow: The agent now knows `test-skill` exists. Next it will load the full instructions for that skill (Call 1).

---

### Call 1 -- load_skill (depth=0, caller=reasoning)

**Context**: Having seen `test-skill` in the L1 catalog, the root reasoning agent now calls `load_skill` for L2 (Level 2) discovery. This returns the full SKILL.md body -- the skill's detailed instructions, including what functions it exposes to the REPL and how to call them.

**Note**: idx 1 / d0: Root reasoning agent calls load_skill for L2 instructions on test-skill. SkillToolset returns SKILL.md body.

**Tool call**: `load_skill` with `name = "test-skill"`

**Usage**: prompt=350 | candidate=20 | total=370 tokens

> Flow: The agent now has full skill instructions. It will use `execute_code` to call the skill's `run_test_skill()` function (Call 2).

---

### Call 2 -- execute_code (depth=0, caller=reasoning)

**Context**: The root reasoning agent's first REPL execution. It calls `run_test_skill()`, which is a function exposed by the `test_skill` skill and auto-imported into REPL globals. Internally, `run_test_skill()` calls `llm_query()`, which dispatches a child orchestrator at depth=1 via the thread bridge. The code also checks whether `user_ctx` (populated by the dynamic instruction template) is accessible in the REPL namespace.

**Note**: idx 2 / d0: Root reasoning agent calls execute_code with run_test_skill. The skill internally calls llm_query() which dispatches a child at depth=1. Also verifies user_ctx injection via DYN_INSTR tags.

**Code submitted**:

```python
result = run_test_skill(
    child_prompt='Analyze the context and call llm_query to dispatch a grandchild at depth=2.',
    emit_debug=True,
    rlm_state=_rlm_state,
    llm_query_batched_fn=None,
)
print(f'skill_result={result.child_result}')
print(f'skill_latency_ms={result.thread_bridge_latency_ms:.1f}')
print(f'skill_depth={result.state_snapshot.get("_rlm_depth", "MISSING")}')

# Dynamic instruction verification
if 'user_ctx' in dir():
    print(f'[DYN_INSTR:user_ctx_keys={sorted(user_ctx.keys())}]')
    print(f'[DYN_INSTR:arch_context_preview={user_ctx.get("arch_context.txt", "")[:40]}]')
```

**What this does**: Calls the test skill with a prompt instructing the child to recurse one more level. Prints the child's result, thread-bridge latency, and depth. Then checks that the dynamic instruction system injected `user_ctx` into the REPL namespace and prints its keys and a preview.

**Usage**: prompt=500 | candidate=80 | total=580 tokens

> Flow: `run_test_skill()` internally calls `llm_query()`, which blocks the REPL thread and dispatches a child orchestrator at depth=1. The next model call (Call 3) is from that child agent, not the root.

---

### Call 3 -- list_skills (depth=1, caller=worker)

**Context**: This is the child reasoning agent spawned by `run_test_skill()`'s internal `llm_query()` call. It is now running at depth=1. Just like the root did, it begins with L1 skill discovery. The fact that `list_skills` is available here proves **GAP-A is fixed** -- child agents inherit the SkillToolset.

**Note**: idx 3 / d1: Child reasoning agent (spawned by run_test_skill's llm_query) calls list_skills. Proves GAP-A fix: children get SkillToolset.

**Tool call**: `list_skills` with no arguments.

**Usage**: prompt=120 | candidate=10 | total=130 tokens

> Flow: The child sees the skill catalog. Next it loads the test-skill instructions (Call 4).

---

### Call 4 -- load_skill (depth=1, caller=worker)

**Context**: The depth=1 child loads the full test-skill instructions, just as the root did. This confirms L2 discovery works at child depth.

**Note**: idx 4 / d1: Child reasoning agent calls load_skill for L2 instructions on test-skill at depth=1.

**Tool call**: `load_skill` with `name = "test-skill"`

**Usage**: prompt=140 | candidate=15 | total=155 tokens

> Flow: The child now has skill instructions. It will call `execute_code` to dispatch a grandchild via `llm_query()` (Call 5).

---

### Call 5 -- execute_code (depth=1, caller=worker)

**Context**: The depth=1 child agent writes code that calls `llm_query()` with a simple prompt, spawning a grandchild at depth=2. This is the second level of recursion. The code also reads `_rlm_state` to verify depth and iteration metadata are propagated correctly.

**Note**: idx 5 / d1: Child reasoning agent calls execute_code with code that calls llm_query() to spawn a grandchild at depth=2.

**Code submitted**:

```python
grandchild_result = llm_query('Return the leaf value: depth2_leaf_ok')
print(f'grandchild_said={grandchild_result}')
print(f'd1_depth={_rlm_state.get("_rlm_depth", "MISSING")}')
print(f'd1_iteration={_rlm_state.get("iteration_count", "MISSING")}')
```

**What this does**: Calls `llm_query()` with a prompt asking the grandchild to return a specific leaf value. When the grandchild completes, the result is printed. Also prints the current depth and iteration count from `_rlm_state` for verification.

**Usage**: prompt=200 | candidate=40 | total=240 tokens

> Flow: `llm_query()` blocks this REPL thread and dispatches a grandchild orchestrator at depth=2. The next model call (Call 6) is from that grandchild.

---

### Call 6 -- list_skills (depth=2, caller=worker)

**Context**: The grandchild agent at depth=2 begins with L1 skill discovery. The fact that `list_skills` is available at depth=2 proves SkillToolset propagation works through two levels of recursion.

**Note**: idx 6 / d2: Grandchild reasoning agent calls list_skills. Proves SkillToolset available at depth=2.

**Tool call**: `list_skills` with no arguments.

**Usage**: prompt=80 | candidate=10 | total=90 tokens

> Flow: The grandchild sees the skill catalog. Next it loads the test-skill instructions (Call 7).

---

### Call 7 -- load_skill (depth=2, caller=worker)

**Context**: The depth=2 grandchild loads the full test-skill instructions. This confirms L2 discovery works at the deepest recursion level tested.

**Note**: idx 7 / d2: Grandchild reasoning agent calls load_skill for L2 instructions at depth=2.

**Tool call**: `load_skill` with `name = "test-skill"`

**Usage**: prompt=100 | candidate=15 | total=115 tokens

> Flow: The grandchild now has skill instructions. It will call `execute_code` to verify state propagation (Call 8).

---

### Call 8 -- execute_code (depth=2, caller=worker)

**Context**: The grandchild agent writes code to comprehensively verify that `_rlm_state` has been correctly propagated through two levels of recursion. It checks all state keys, the current depth, the agent name, and critically, the dynamic instruction keys (`repo_url`, `root_prompt`, `test_context`, `skill_instruction`) that prove **GAP-D is fixed** -- children receive dynamic instruction state.

**Note**: idx 8 / d2: Grandchild reasoning agent calls execute_code. Reads _rlm_state, verifies dynamic instruction state keys are resolved, prints proof markers [D2_STATE:key=value].

**Code submitted**:

```python
# Read _rlm_state at depth=2 -- proves state propagation
state_keys = sorted(_rlm_state.keys())
print(f'[D2_STATE:keys={state_keys}]')
print(f'[D2_STATE:depth={_rlm_state.get("_rlm_depth", "MISSING")}]')
print(f'[D2_STATE:agent_name={_rlm_state.get("_rlm_agent_name", "MISSING")}]')
print(f'[D2_STATE:current_depth={_rlm_state.get("current_depth", "MISSING")}]')

# Verify dynamic instruction resolution: check that state has the expected keys
# injected by the dynamic instruction template at this depth
for key in ['repo_url', 'root_prompt', 'test_context', 'skill_instruction']:
    val = _rlm_state.get(key, 'MISSING')
    resolved = val != 'MISSING'
    print(f'[D2_STATE:dyn_instr_{key}=resolved={resolved}]')
    if resolved and isinstance(val, str):
        print(f'[D2_STATE:dyn_instr_{key}_preview={val[:50]}]')

print(f'[D2_STATE:proof=depth2_state_verified]')
```

**What this does**: Enumerates all keys in `_rlm_state` at depth=2. Checks that depth, agent name, and dynamic instruction keys are present and non-missing. Each key is printed as a structured `[D2_STATE:...]` proof marker that tests can assert against. This is the deepest state-propagation verification in the fixture.

**Usage**: prompt=120 | candidate=60 | total=180 tokens

> Flow: The grandchild has verified state propagation. It will now return its result upward via `set_model_response` (Call 9).

---

### Call 9 -- set_model_response (depth=2, caller=worker)

**Context**: The grandchild agent at depth=2 is done. It calls `set_model_response` to return a typed response upward to its parent (the depth=1 child). This is the leaf of the recursion -- the deepest point in the call tree. The `final_answer` contains the value that was requested by the depth=1 agent's `llm_query('Return the leaf value: depth2_leaf_ok')`.

**Note**: idx 9 / d2: Grandchild reasoning agent calls set_model_response. Leaf node returns the requested value.

**Final answer**:

> depth2_leaf_ok

**Reasoning summary**:

> Returned leaf value as requested at depth=2.
> Verified _rlm_state propagation and dynamic instruction resolution.

**Usage**: prompt=150 | candidate=25 | total=175 tokens

> Flow: This terminates the depth=2 agent. Control returns to the depth=1 agent's REPL, where `llm_query()` unblocks and returns `"depth2_leaf_ok"` as the value of `grandchild_result`. The depth=1 agent resumes (Call 10).

---

### Call 10 -- set_model_response (depth=1, caller=worker)

**Context**: The depth=1 child agent's REPL has resumed. Its `llm_query()` call returned `"depth2_leaf_ok"`, which was printed as `grandchild_said=depth2_leaf_ok`. Having verified the depth=2 chain works, the child now calls `set_model_response` to return its own result upward to the root agent. It wraps the grandchild's value with a confirmation prefix.

**Note**: idx 10 / d1: Child reasoning agent (resumed after grandchild returned). Sees REPL stdout with grandchild_said=depth2_leaf_ok. Calls set_model_response forwarding the grandchild result.

**Final answer**:

> child_confirmed_depth2: depth2_leaf_ok

**Reasoning summary**:

> Dispatched to depth=2, received leaf value depth2_leaf_ok, confirmed.

**Usage**: prompt=250 | candidate=30 | total=280 tokens

> Flow: This terminates the depth=1 agent. Control returns to the root agent's REPL (depth=0), where `run_test_skill()` completes and returns a result object. The root agent sees the REPL output and proceeds to its second REPL turn (Call 11).

---

### Call 11 -- execute_code (depth=0, caller=reasoning)

**Context**: The root reasoning agent's second REPL execution (turn 2). Having completed the depth=2 chain via `run_test_skill()`, it now tests `llm_query_batched()` -- the parallel fanout mechanism that dispatches multiple child agents simultaneously. It sends 2 prompts and expects 2 results back. It also reads `_rlm_state` to verify cross-turn state persistence (iteration count should have incremented) and checks whether the `result` variable from turn 1 is still in the REPL namespace.

**Note**: idx 11 / d0: Root reasoning agent sees Turn 1 REPL stdout. Calls execute_code with llm_query_batched(2 prompts). Also reads _rlm_state to print iteration count, proving state persistence across turns.

**Code submitted**:

```python
batch_results = llm_query_batched(['Summarize finding A', 'Summarize finding B'])
for i, r in enumerate(batch_results):
    print(f'batch_{i}={r}')
print(f'batch_count={len(batch_results)}')
print(f'turn2_iteration_count={_rlm_state.get("iteration_count", "MISSING")}')
print(f'turn2_depth={_rlm_state.get("_rlm_depth", "MISSING")}')

# Verify turn 1 variable persists in REPL namespace
print(f'turn1_skill_result_persisted={"result" in dir()}')
```

**What this does**: Calls `llm_query_batched()` with a list of 2 prompts. This dispatches 2 child agents in parallel. When both return, their results are printed. Also verifies that the REPL namespace still contains the `result` variable from the previous `execute_code` turn, proving cross-turn persistence.

**Usage**: prompt=700 | candidate=60 | total=760 tokens

> Flow: `llm_query_batched()` blocks the REPL thread and dispatches 2 child agents at depth=1. Calls 12 and 13 are from those batch children.

---

### Call 12 -- set_model_response (depth=1, caller=worker)

**Context**: Batch child 0 (fanout index 0), spawned by the first prompt in `llm_query_batched()`: `"Summarize finding A"`. This is a simple leaf agent -- it immediately returns a summary without using the REPL or skill system.

**Note**: idx 12 / d1: Batch child 0 (fanout_idx=0, prompt='Summarize finding A'). Simple set_model_response -- no interleaving risk.

**Final answer**:

> finding_A_summary

**Reasoning summary**:

> Summarized finding A.

**Usage**: prompt=80 | candidate=15 | total=95 tokens

> Flow: This batch child is done. The batched dispatch waits for all children to complete before returning. Call 13 is the other batch child.

---

### Call 13 -- set_model_response (depth=1, caller=worker)

**Context**: Batch child 1 (fanout index 1), spawned by the second prompt in `llm_query_batched()`: `"Summarize finding B"`. Like batch child 0, it immediately returns a summary.

**Note**: idx 13 / d1: Batch child 1 (fanout_idx=1, prompt='Summarize finding B'). Simple set_model_response -- no interleaving risk.

**Final answer**:

> finding_B_summary

**Reasoning summary**:

> Summarized finding B.

**Usage**: prompt=80 | candidate=15 | total=95 tokens

> Flow: Both batch children are done. `llm_query_batched()` unblocks in the root REPL and returns `["finding_A_summary", "finding_B_summary"]`. The root agent sees the REPL output and proceeds to its final response (Call 14).

---

### Call 14 -- set_model_response (depth=0, caller=reasoning)

**Context**: The root reasoning agent has completed both turns. Turn 1 exercised the full depth=2 chain with skill discovery at every level. Turn 2 exercised batched dispatch with 2 parallel children. The root now calls `set_model_response` to return the final answer upward to the test harness.

**Note**: idx 14 / d0: Root reasoning agent sees Turn 1 (skill + depth=2 chain with SkillToolset discovery) and Turn 2 (batch) results. Calls set_model_response with final answer.

**Final answer**:

> Pipeline verified: depth=2 chain succeeded (depth2_leaf_ok via child),
> SkillToolset discovery confirmed at d0/d1/d2,
> batched dispatch returned 2 results (finding_A_summary, finding_B_summary).

**Reasoning summary**:

> Exercised list_skills + load_skill at all depths,
> run_test_skill for depth=2 chain,
> and llm_query_batched for fanout.
> All components confirmed including GAP-A/GAP-D fixes.

**Usage**: prompt=900 | candidate=70 | total=970 tokens

> Flow: The pipeline is complete. The test harness asserts that `final_answer` contains `"depth=2 chain succeeded"`, that `total_iterations == 2`, and that `total_model_calls == 15`.

---

## Execution Flow Diagram

```
TURN 1 (root iteration 1)
==========================

depth=0  reasoning
  |
  |-- Call 0:  list_skills ............... L1 discovery (skill catalog XML)
  |-- Call 1:  load_skill("test-skill") . L2 discovery (full SKILL.md)
  |-- Call 2:  execute_code .............. run_test_skill() -> llm_query() blocks
  |     |
  |     |  depth=1  worker (child spawned by llm_query inside run_test_skill)
  |     |    |
  |     |    |-- Call 3:  list_skills ............ L1 at depth=1 [GAP-A proof]
  |     |    |-- Call 4:  load_skill("test-skill") L2 at depth=1
  |     |    |-- Call 5:  execute_code ........... llm_query() -> blocks
  |     |    |     |
  |     |    |     |  depth=2  worker (grandchild spawned by llm_query)
  |     |    |     |    |
  |     |    |     |    |-- Call 6:  list_skills ............ L1 at depth=2 [GAP-A proof]
  |     |    |     |    |-- Call 7:  load_skill("test-skill") L2 at depth=2
  |     |    |     |    |-- Call 8:  execute_code ........... state verification [GAP-D proof]
  |     |    |     |    |-- Call 9:  set_model_response ..... returns "depth2_leaf_ok"
  |     |    |     |    |                                     ~~~ depth=2 done ~~~
  |     |    |     |
  |     |    |     |  <- llm_query() unblocks, grandchild_result = "depth2_leaf_ok"
  |     |    |
  |     |    |-- Call 10: set_model_response .... returns "child_confirmed_depth2: depth2_leaf_ok"
  |     |    |                                    ~~~ depth=1 done ~~~
  |     |
  |     |  <- run_test_skill() returns, REPL prints result
  |

TURN 2 (root iteration 2)
==========================

depth=0  reasoning (resumed)
  |
  |-- Call 11: execute_code .............. llm_query_batched(2 prompts) -> blocks
  |     |
  |     |  depth=1  worker (batch child 0)       depth=1  worker (batch child 1)
  |     |    |                                      |
  |     |    |-- Call 12: set_model_response         |-- Call 13: set_model_response
  |     |    |   returns "finding_A_summary"         |   returns "finding_B_summary"
  |     |    |   ~~~ batch child 0 done ~~~          |   ~~~ batch child 1 done ~~~
  |     |
  |     |  <- llm_query_batched() unblocks, returns ["finding_A_summary", "finding_B_summary"]
  |
  |-- Call 14: set_model_response ........ final pipeline answer
  |                                        ~~~ depth=0 done, pipeline complete ~~~
```

---

## Token Usage Summary

| Call | Tool | Depth | Prompt | Candidate | Total |
|------|------|-------|--------|-----------|-------|
| 0 | list_skills | 0 | 300 | 15 | 315 |
| 1 | load_skill | 0 | 350 | 20 | 370 |
| 2 | execute_code | 0 | 500 | 80 | 580 |
| 3 | list_skills | 1 | 120 | 10 | 130 |
| 4 | load_skill | 1 | 140 | 15 | 155 |
| 5 | execute_code | 1 | 200 | 40 | 240 |
| 6 | list_skills | 2 | 80 | 10 | 90 |
| 7 | load_skill | 2 | 100 | 15 | 115 |
| 8 | execute_code | 2 | 120 | 60 | 180 |
| 9 | set_model_response | 2 | 150 | 25 | 175 |
| 10 | set_model_response | 1 | 250 | 30 | 280 |
| 11 | execute_code | 0 | 700 | 60 | 760 |
| 12 | set_model_response | 1 | 80 | 15 | 95 |
| 13 | set_model_response | 1 | 80 | 15 | 95 |
| 14 | set_model_response | 0 | 900 | 70 | 970 |
| **Total** | | | **4,070** | **480** | **4,550** |

---

## Glossary

- **L1 discovery** (`list_skills`): Returns an XML catalog of available skills with names and short descriptions. The agent uses this to decide which skills to investigate further.
- **L2 discovery** (`load_skill`): Returns the full SKILL.md body for a specific skill, including detailed instructions and exposed functions.
- **GAP-A**: The bug where child agents did not inherit the SkillToolset, so `list_skills` and `load_skill` were unavailable at depth > 0.
- **GAP-D**: The bug where child agents did not receive dynamic instruction state keys, so template variables like `{repo_url?}` were not resolved.
- **Thread bridge**: The mechanism that lets synchronous REPL code call `llm_query()` and block until a child agent completes. Internally uses `asyncio.run_coroutine_threadsafe()`.
- **`_rlm_state`**: A dictionary injected into the REPL namespace containing the current session state (depth, iteration count, agent name, user-provided keys, etc.).
- **`run_test_skill()`**: A function exposed by the `test_skill` skill, auto-imported into REPL globals. It internally calls `llm_query()` to dispatch a child agent.
- **`llm_query_batched()`**: A function that dispatches multiple child agents in parallel, one per prompt, and returns a list of results.
- **`set_model_response`**: The ADK tool that terminates the current agent's reasoning loop and returns a typed response upward to the caller.
- **Provider-fake**: The test harness that replaces the Gemini API with a local HTTP server serving canned fixture responses.
