# E2E Test Gap Analysis: skill_arch_test

**Reviewer**: Demo markdown reviewer (automated)
**Date**: 2026-03-24
**Inputs**: SHOWBOAT demo, CLAUDE.md, consolidated plan, expected_lineage.py, test module, fixture JSON

---

## Architecture Coverage

### Downward flow (Reasoning Agent -> execute_code -> REPL)

- [x] **COVERED** -- Strong evidence
- Fixture response[0] calls `execute_code` with `run_test_skill(...)` code
- `PLUGIN:before_tool:reasoning_agent:tool_name=execute_code` appears in tagged output
- `STATE:pre_tool:repl_submitted_code=result = run_test_skill(...)` captured
- `PluginHookExpectation` asserts `before_tool` with `tool_name=execute_code`
- `TestSkillExpectation` asserts `depth=0`, `rlm_agent_name=reasoning_agent`, `iteration_count=1`
- SQLite telemetry row: `event_type=tool_call, tool_name=execute_code, repl_llm_calls=1`
- **No gap here.** The downward flow is well-validated through multiple independent signals.

### Lateral flow (REPL code -> llm_query() -> child agents -> returned values)

- [x] **COVERED** -- Strong evidence
- `TEST_SKILL:calling_llm_query=True` emitted before dispatch
- `TEST_SKILL:child_result_preview=arch_test_ok` confirms child returned a value
- `TEST_SKILL:thread_bridge_latency_ms=~130` confirms measurable round-trip
- `PLUGIN:before_agent:child_orchestrator_d1:agent_type=RLMOrchestratorAgent` visible
- `PLUGIN:before_agent:child_reasoning_d1:depth=1` visible
- `session_state_events` shows `key_depth=1` rows for child state (current_depth@d1, etc.)
- **No gap in observation.** See Thread Bridge Validation below for assertion-level gaps.

### Upward flow (Reasoning Agent -> set_model_response -> typed response)

- [x] **COVERED** -- Moderate evidence
- Fixture response[2] calls `set_model_response` with `final_answer` and `reasoning_summary`
- `PLUGIN:before_tool:reasoning_agent:tool_name=set_model_response` appears in tagged output
- `CALLBACK:after_agent:rlm_orchestrator:final_response_text=Architecture test complete...` captured
- `expected.final_answer` checked by contract runner
- **Gap A1**: No assertion in `expected_lineage.py` for `set_model_response` as a tool call. The `PluginHookExpectation` list checks `before_tool` only for `execute_code`, not for `set_model_response`. The child's `set_model_response` call is also unasserted despite being visible in plugin tags.

---

## Thread Bridge Validation

### Evidence of thread bridge usage

- [x] `TEST_SKILL:execution_mode=thread_bridge` -- emitted by skill code
- [x] `TEST_SKILL:llm_query_fn_type=function` -- confirms a real callable, not AST rewriter
- [x] `TEST_SKILL:thread_bridge_latency_ms=~130` -- confirms real async dispatch round-trip
- [x] Fixture note says "Dispatched via thread bridge (run_coroutine_threadsafe + future.result())"
- [x] Child orchestrator visible at depth=1 in plugin tags and session_state_events

### Assertion-level gaps

- **Gap B1**: `execution_mode` assertion uses `operator="oneof", expected=["async_rewrite", "thread_bridge"]`. The consolidated plan (Future-Focused Corrections section) explicitly says to change this to `expected="thread_bridge"` (strict). The `oneof` operator still accepts the deleted AST rewriter path. This is a thread-bridge validation regression -- the assertion should ONLY accept `thread_bridge` since the AST rewriter has been deleted.

- **Gap B2**: No assertion validates the `run_coroutine_threadsafe` mechanism specifically. The test observes latency and the `function` type of `llm_query_fn`, but these are indirect. A direct signal would be checking that the REPL executed in a worker thread (e.g., via `threading.current_thread().name` emitted by the skill). Currently, `execution_mode` is hardcoded in the skill source (`execution_mode = "thread_bridge"` at line 87 of `skill.py`), not detected from runtime behavior. This means the assertion would pass even if the thread bridge were broken, as long as the skill code ran at all.

- **Gap B3**: Child event re-emission is NOT directly asserted. The showboat demo shows `session_state_events` with `key_depth > 0` rows (current_depth@d1, iteration_count@d1, etc.), confirming child events reached the parent session. But `expected_lineage.py` has zero expectations for child-scoped state keys. No `StateKeyExpectation` checks for `current_depth@d1=1` or `should_stop@d1=True`.

---

## State Mutation (AR-CRIT-001)

### Compliance evidence

- [x] `orchestrator.py` yields initial state via `Event(actions=EventActions(state_delta=...))` -- compliant
- [x] `repl_tool.py` writes via `tool_context.state[...]` -- compliant
- [x] `dispatch.py` pushes child events via `child_event_queue.put_nowait(Event(...))` -- compliant
- [x] `post_dispatch_state_patch_fn()` is applied through `tool_context.state` in `repl_tool.py:258-260` -- compliant
- [x] Orchestrator final state written via `EventActions(state_delta={FINAL_RESPONSE_TEXT: ..., SHOULD_STOP: True})` -- compliant

### Gaps

- **Gap C1**: The test has NO explicit assertion that state was written through the correct mutation path. It observes state values (iteration_count, should_stop, etc.) but does not verify they arrived via `tool_context.state` or `EventActions(state_delta=...)` rather than raw `ctx.session.state[key] = value`. The `session_state_events` table in SQLite records `event_author`, which could be used to verify the mutation path, but no test queries this. The `event_author` column shows the correct authors (rlm_orchestrator, reasoning_agent, child_orchestrator_d1), which is indirect evidence of correct mutation paths, but this is not asserted.

- **Gap C2**: `flush_fn()` is no longer part of the architecture (replaced by `post_dispatch_state_patch_fn` in the collapsed orchestrator). The consolidated plan mentions `flush_fn` but the actual implementation uses `post_dispatch_state_patch_fn`. No assertion validates that `DYN_SKILL_INSTRUCTION` is restored after dispatch (the only thing `post_dispatch_state_patch_fn` does).

- **Gap C3**: Depth-scoped key prefixing is observed (session_state_events shows `current_depth` at key_depth=0 and key_depth=1) but not explicitly asserted. No `StateKeyExpectation` checks that `current_depth@d1` exists with value `1` while `current_depth` (depth 0) exists with value `0`.

---

## Anti-Reward-Hacking Audit

### Pre-seeded vs pipeline-produced values

The fixture's `initial_state` seeds 5 keys:
- `user_provided_ctx` -- pre-seeded dict (required for Path B context injection)
- `repo_url` -- pre-seeded string
- `root_prompt` -- pre-seeded string
- `test_context` -- pre-seeded string
- `skill_instruction` -- pre-seeded string

These are **input configuration**, not output values. They are appropriately pre-seeded because they represent what a real caller would provide. The pipeline then processes them (resolving `{var?}` placeholders, building `user_ctx_manifest`, injecting into REPL globals).

### Assertions on pipeline-produced values

- [x] `child_result_preview=arch_test_ok` -- can only be produced by real child dispatch (fixture response[1] returns "arch_test_ok" but only through the full orchestrator dispatch pipeline)
- [x] `iteration_count=1` inside REPL -- produced by REPLTool incrementing `_call_count`
- [x] `user_ctx_manifest` containing `arch_context.txt` -- produced by orchestrator Path B manifest builder
- [x] Dynamic instruction resolution (`{repo_url?}` etc.) -- verified by `dyn_instr_capture_hook`

### Gaps

- **Gap D1**: `repl_did_expand` appears in `STATE:model_call_1:repl_did_expand=False` but this value is read from `callback_context.state.get("repl_did_expand", False)` in `InstrumentationPlugin.before_model_callback`. At model_call_1, the REPLTool has not yet run, so the value is the `False` default, not a pipeline-written value. The `StateKeyExpectation` for `repl_did_expand` at phase `model_call_1` asserts `eq False`, which is checking a default value, not a pipeline output. This is borderline: it confirms the key is NOT prematurely set, which has diagnostic value. But there is NO assertion that `repl_did_expand` is ever set to `True` after skill expansion. The showboat demo does not show `repl_did_expand=True` anywhere in the tagged output. **This is a significant gap** -- the consolidated plan table says "Skill source expansion" should be validated by `repl_did_expand == True`, but the actual test never checks this.

- **Gap D2**: `should_stop` at model_call_1 asserts `eq False`. The `InstrumentationPlugin` reads this with `callback_context.state.get("should_stop", False)`. The `False` is the default argument, not a state-written value. Meanwhile, the `TEST_SKILL:should_stop=?` tag shows the value was never explicitly set in state before the first REPL run. This mismatch is documented in the showboat demo and the expected_lineage was corrected to `"?"` for the TEST_SKILL expectation, but the STATE expectation still checks `False` which comes from the `get()` default. This is testing the default parameter of `dict.get()`, not a pipeline-produced value.

---

## SQLite Telemetry Gaps

### Tables present and populated

- [x] `traces` table: status=completed, total_input_tokens=880, total_output_tokens=160, total_calls=3, iterations=1
- [x] `telemetry` table: 6 rows (3 model_call + 3 tool_call events)
- [x] `session_state_events` table: 20+ rows with chronological state evolution

### Missing/NULL data

- **Gap E1**: `traces` table has NULL columns: `child_dispatch_count`, `child_total_batch_dispatches`, `child_error_counts`, `structured_output_failures`, `artifact_saves`, `artifact_bytes_saved`, `per_iteration_breakdown`. These are documented as "optional columns populated only when those features are actively used." But `child_dispatch_count` SHOULD be 1 (a child was dispatched) and `artifact_saves` SHOULD be 1 (the code artifact was saved). This suggests `SqliteTracingPlugin` is not receiving these signals, which is an observability gap in the plugin, not just in the test.

- **Gap E2**: The `telemetry` row for `tool_call:set_model_response` at child depth shows `depth=0` instead of expected `depth=1`. The showboat demo shows: `tool_call | set_model_response | child_reasoning_d1 | 0`. This is likely because the child's `set_model_response` does not read the depth-scoped `current_depth` key. No assertion catches this incorrect depth value.

- **Gap E3**: No assertion checks `max_depth_reached=1` in the `traces` table. The showboat demo shows this value is correctly populated, but neither the test module nor `expected_lineage.py` validates it. This is a key indicator that child dispatch occurred.

- **Gap E4**: No assertion checks `tool_invocation_summary` in `traces`. The value `{"execute_code": 1, "set_model_response": 2}` would validate the correct tool call distribution across parent and child, but it is unasserted.

### What IS asserted in the test module

- `traces.status == "completed"` and `traces.total_calls >= 2` -- checked
- `telemetry.repl_llm_calls >= 1` for `execute_code` tool call -- checked
- These are minimal. The test could validate far more from the SQLite data.

---

## Unasserted Tagged Output

### TEST_SKILL tags

| Tag Family | Key | Value | Has Assertion? | Priority |
|-----------|-----|-------|---------------|----------|
| TEST_SKILL | depth | 0 | YES (eq "0") | -- |
| TEST_SKILL | rlm_agent_name | reasoning_agent | YES (eq) | -- |
| TEST_SKILL | iteration_count | 1 | YES (eq "1") | -- |
| TEST_SKILL | current_depth | 0 | YES (eq "0") | -- |
| TEST_SKILL | should_stop | ? | YES (eq "?") | -- |
| TEST_SKILL | state_keys_count | 7 | YES (gte 6) | -- |
| TEST_SKILL | state_keys | [list] | NO | LOW -- state_keys_count covers cardinality |
| TEST_SKILL | execution_mode | thread_bridge | YES (oneof) | **HIGH -- should be strict eq** |
| TEST_SKILL | llm_query_fn_type | function | YES (eq) | -- |
| TEST_SKILL | calling_llm_query | True | YES (eq) | -- |
| TEST_SKILL | child_result_preview | arch_test_ok | YES (contains) | -- |
| TEST_SKILL | thread_bridge_latency_ms | ~130 | YES (gt 0) | -- |
| TEST_SKILL | COMPLETE | True | YES (eq) | -- |
| TEST_SKILL | summary | depth=0 mode=thread_bridge... | NO | MEDIUM -- composite summary not checked |

### PLUGIN tags (produced but not in expected_lineage)

| Tag Family | Key | Value | Has Assertion? | Priority |
|-----------|-----|-------|---------------|----------|
| PLUGIN:before_agent | rlm_orchestrator:depth | 0 | NO | MEDIUM -- verifies root orch depth |
| PLUGIN:before_agent | rlm_orchestrator:agent_type | RLMOrchestratorAgent | NO | MEDIUM -- verifies agent type |
| PLUGIN:after_model | reasoning_agent:input_tokens | 300 | NO | **HIGH -- token accounting** |
| PLUGIN:after_model | reasoning_agent:output_tokens | 80 | NO | **HIGH -- token accounting** |
| PLUGIN:before_model | reasoning_agent:tools_count | 6 | NO | MEDIUM -- verifies tool wiring |
| PLUGIN:before_model | reasoning_agent:contents_count | 3 | NO | LOW |
| PLUGIN:before_tool | reasoning_agent:tool_name | set_model_response | NO | **HIGH -- upward flow** |
| PLUGIN:after_tool | reasoning_agent:tool_name | set_model_response | NO | **HIGH -- upward flow** |
| PLUGIN:before_agent | child_orchestrator_d1:agent_type | RLMOrchestratorAgent | NO | **HIGH -- child dispatch proof** |
| PLUGIN:before_agent | child_reasoning_d1:depth | 1 | NO | **HIGH -- child depth verification** |
| PLUGIN:before_model | child_reasoning_d1:sys_instr_len | 2201 | NO | MEDIUM |
| PLUGIN:before_model | child_reasoning_d1:tools_count | 2 | NO | MEDIUM |
| PLUGIN:after_model | child_reasoning_d1:finish_reason | STOP | NO | MEDIUM |
| PLUGIN:after_tool | child_reasoning_d1:tool_name | set_model_response | NO | MEDIUM -- child upward flow |
| PLUGIN:after_agent | child_reasoning_d1:elapsed_ms | ~116 | NO | LOW |
| PLUGIN:after_agent | child_orchestrator_d1:elapsed_ms | ~129 | NO | LOW |

### CALLBACK tags (produced but not in expected_lineage)

| Tag Family | Key | Value | Has Assertion? | Priority |
|-----------|-----|-------|---------------|----------|
| CALLBACK:after_agent | rlm_orchestrator:final_state_key_count | 32 | NO | MEDIUM -- state cardinality |
| CALLBACK:after_agent | rlm_orchestrator:should_stop | True | NO | MEDIUM -- final state |
| CALLBACK:after_agent | rlm_orchestrator:iteration_count | 1 | NO | LOW -- already checked elsewhere |

### STATE tags (produced but not in expected_lineage)

| Tag Family | Key | Value | Has Assertion? | Priority |
|-----------|-----|-------|---------------|----------|
| STATE:model_call_3 | iteration_count | 1 | NO | MEDIUM -- post-REPL state |
| STATE:pre_tool | skill_instruction | Use run_test_skill()... | NO | **HIGH -- DYN_SKILL_INSTRUCTION in state** |
| STATE:pre_tool | repl_skill_globals_injected | [list] | NO | **HIGH -- skill loading proof** |
| STATE:pre_tool | artifact_save_count | 1 | NO | MEDIUM -- artifact tracking |
| STATE:pre_tool | current_depth@d1 | 1 | NO | **HIGH -- child depth state** |
| STATE:pre_tool | iteration_count@d1 | 0 | NO | MEDIUM |
| STATE:pre_tool | reasoning_output@d1 | {"final_answer": "arch_test_ok"...} | NO | **HIGH -- child completion** |
| STATE:pre_tool | final_response_text@d1 | arch_test_ok | NO | **HIGH -- child final answer** |
| STATE:pre_tool | should_stop@d1 | True | NO | **HIGH -- child termination** |

### DYN_INSTR tags

| Tag Family | Key | Value | Has Assertion? | Priority |
|-----------|-----|-------|---------------|----------|
| DYN_INSTR | repo_url | resolved=True | YES | -- |
| DYN_INSTR | repo_url_preview | https://test.example.com/arch-test | NO | LOW |
| DYN_INSTR | root_prompt | resolved=True | YES | -- |
| DYN_INSTR | root_prompt_preview | Run the architecture introspection... | NO | LOW |
| DYN_INSTR | test_context | resolved=True | YES | -- |
| DYN_INSTR | skill_instruction | resolved=True | YES | -- |
| DYN_INSTR | user_ctx_manifest | resolved=True | YES | -- |
| DYN_INSTR | user_ctx_keys | ['arch_context.txt', 'test_metadata.json'] | YES | -- |
| DYN_INSTR | arch_context_preview | Architecture validation context: this is | NO | LOW |

### TIMING tags

| Tag Family | Key | Value | Has Assertion? | Priority |
|-----------|-----|-------|---------------|----------|
| TIMING | model_call_1_ms | ~144 | YES (gte 0) | -- |
| TIMING | tool_execute_code_ms | ~135 | NO | MEDIUM |
| TIMING | model_call_2_ms | ~112 | NO | MEDIUM -- child model call |
| TIMING | model_call_3_ms | ~116 | NO | LOW |
| TIMING | tool_set_model_response_ms | ~0.38 | NO | LOW |
| TIMING | agent_reasoning_agent_ms | ~716 | YES (gte 0) | -- |
| TIMING | agent_rlm_orchestrator_ms | ~1007 | NO | MEDIUM |
| TIMING | agent_child_reasoning_d1_ms | ~116 | NO | MEDIUM -- child timing |
| TIMING | agent_child_orchestrator_d1_ms | ~129 | NO | MEDIUM -- child timing |

### REPL_TRACE tags

- **None emitted.** All REPL_TRACE expectations have `required=False`. This means the entire REPL trace assertion group is a no-op. The trace data exists inside `last_repl_result['trace_summary']` but is not surfaced as tagged output. **7 expectations exist but 0 are exercised.**

---

## Missing Observability Dimensions

### REPL trace data (execution time, memory, var snapshots)

- **Gap F1**: Despite `RLM_REPL_TRACE=2` being set (which should activate tracemalloc), no `[REPL_TRACE:...]` tags are emitted anywhere. The `REPLTracingPlugin` does not emit tagged stdout lines -- it saves JSON artifacts. The trace data is available inside `last_repl_result['trace_summary']` but the assertion framework has no way to reach it. All 7 `ReplTraceExpectation` entries have `required=False`, making them dead code. To actually validate REPL tracing, the test would need to read `run_result.final_state["last_repl_result"]["trace_summary"]` directly.

### Skill expansion metadata

- **Gap F2**: The `repl_skill_globals_injected` key is captured in `STATE:pre_tool:` tags with value `['RecursivePingResult', 'TestSkillResult', 'run_recursive_ping', 'run_test_skill']`, but no `StateKeyExpectation` or `PluginHookExpectation` checks this. It is the primary proof that skill loading worked correctly. The consolidated plan table says `repl_did_expand == True` should validate this, but `repl_did_expand` is NEVER observed as `True` in the showboat demo -- it remains `False` at every model callback.

### Token accounting (input/output tokens per model call)

- **Gap F3**: `PLUGIN:after_model:reasoning_agent:input_tokens=300` and `output_tokens=80` are emitted but not in `expected_lineage.py`. Token accounting is a key observability dimension per CLAUDE.md. The `traces` table has `total_input_tokens=880` and `total_output_tokens=160` but neither the test module nor the lineage assertions check these.

### Dynamic instruction resolution -- all 5 placeholders verified

- [x] All 5 `DynInstrExpectation` entries assert `contains "resolved=True"` -- covered
- [x] `user_ctx_keys` asserted to contain `arch_context.txt` -- covered
- [x] `test_no_unresolved_placeholders` checks raw system instruction text -- covered
- [x] `test_resolved_values_present` checks repo_url and arch_context.txt in SI text -- covered
- **No gap here.** Dynamic instruction is the best-covered dimension.

---

## Recommended Additions

### Priority 1 (Architecture-critical)

1. **Strict thread bridge assertion**: Change `execution_mode` from `oneof ["async_rewrite", "thread_bridge"]` to `eq "thread_bridge"`. The AST rewriter is deleted; accepting it is misleading.

2. **Add `set_model_response` tool assertion**: Add a `PluginHookExpectation` for `before_tool:reasoning_agent:tool_name=set_model_response`. This validates the upward flow (currently unasserted in the lineage).

3. **Add child agent assertions**: Add `PluginHookExpectation` entries for:
   - `before_agent:child_orchestrator_d1:agent_type=RLMOrchestratorAgent`
   - `before_agent:child_reasoning_d1:depth=1`
   These are the strongest proof that lateral dispatch actually occurred.

4. **Add child state key assertions**: Add `StateKeyExpectation` entries for:
   - `pre_tool:current_depth@d1=1`
   - `pre_tool:should_stop@d1=True`
   - `pre_tool:final_response_text@d1=arch_test_ok`
   These validate child event re-emission and depth-scoped state.

5. **Add `repl_skill_globals_injected` assertion**: Add a `StateKeyExpectation` for `pre_tool:repl_skill_globals_injected` containing `run_test_skill`. This is the primary proof that skill loading worked.

### Priority 2 (Observability completeness)

6. **Add token accounting assertions**: Add `PluginHookExpectation` entries for `after_model:reasoning_agent:input_tokens` (gte 1) and `output_tokens` (gte 1). Alternatively, add a SQLite assertion for `traces.total_input_tokens > 0`.

7. **Add SQLite `max_depth_reached` assertion**: Query `SELECT max_depth_reached FROM traces LIMIT 1` and assert `>= 1`. This confirms child dispatch was recorded in the telemetry.

8. **Add SQLite `tool_invocation_summary` assertion**: Query and verify `execute_code` count is 1 and `set_model_response` count is 2.

9. **Investigate `repl_did_expand`**: The showboat demo never shows this as `True`. Either (a) the module-import skill loader does not set this key (only the deleted source-expansion codepath did), or (b) it is set but not captured. If (a), the consolidated plan's claim that `repl_did_expand == True` validates skill expansion is incorrect for the thread-bridge architecture. The assertion should either be removed or the pipeline should be updated to set the key.

### Priority 3 (Hardening)

10. **Make REPL trace assertions effective**: Either (a) modify `REPLTracingPlugin` to emit `[REPL_TRACE:...]` tagged lines, or (b) add a direct test that reads `run_result.final_state["last_repl_result"]["trace_summary"]` and asserts `wall_time_ms > 0`, `llm_call_count >= 1`, etc. Currently all 7 `ReplTraceExpectation` entries are dead code.

11. **Add timing assertion for child**: Add `TimingExpectation` for `agent_child_orchestrator_d1_ms` (gte 0). This validates the child agent timing is captured by the `InstrumentationPlugin`.

12. **Add ordering assertion for upward flow**: Add `OrderingExpectation` that `before_tool:reasoning_agent` (for set_model_response) appears AFTER `after_tool:reasoning_agent` (for execute_code). This validates the architectural sequence: downward first, then upward.

13. **Fix `telemetry.depth` for child set_model_response**: The showboat demo shows depth=0 for the child's `set_model_response` tool call, which is incorrect (should be 1). This is a bug in `SqliteTracingPlugin`, not the test, but the test should assert the correct depth to catch regressions.

---

## Summary

The e2e test validates the **happy path** through all three architectural flows (downward, lateral, upward), but its assertion coverage has significant gaps in three areas:

1. **Child dispatch proof** -- The test observes child agents in plugin tags and session_state_events but asserts on NONE of them. The strongest evidence of lateral flow (child agent name, child depth, child state keys) is produced but unchecked.

2. **Thread bridge strictness** -- The `execution_mode` assertion still accepts the deleted AST rewriter. The `execution_mode` value is hardcoded in the skill source rather than detected at runtime. Together these mean the thread bridge assertion would pass even if the bridge were broken.

3. **Observability depth** -- Token accounting, skill expansion metadata, REPL trace data, and depth-scoped state are all captured in tagged output or SQLite but have zero assertions. The test validates "did it run?" but not "did the observability pipeline capture everything it should?"

The 13 recommended additions would elevate this from a "does it run" smoke test to a complete architecture validation harness, as intended by the consolidated plan.
