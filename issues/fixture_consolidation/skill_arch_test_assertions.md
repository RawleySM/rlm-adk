# skill_arch_test.json -- Assertion Map

Cross-reference of every assertion made against the `skill_arch_test.json` fixture, organized by fixture call index and mapped to the human-readable walkthrough in `skill_arch_test_walkthrough.md`.

## Assertion Sources

| Source | Location | Description |
|--------|----------|-------------|
| **Fixture JSON** `expected` | `skill_arch_test.json:398-404` | Contract-level assertions checked by `ScenarioRouter.check_expectations()` |
| **Fixture JSON** `expected_state` | `skill_arch_test.json:405-414` | Final session state assertions checked by `ScenarioRouter.check_expectations()` |
| **Test classes** | `test_skill_arch_e2e.py` | 33 test methods across 12 test classes |
| **Expected lineage** | `expected_lineage.py:build_skill_arch_test_lineage()` | 37 individual expectations across 7 assertion groups, run by `TestArchitectureLineage::test_full_lineage` |

---

## Global / Cross-Call Assertions

These don't map to a single call -- they span the entire 15-call pipeline.

### Fixture JSON Contract (`expected`)

| Key | Operator | Expected | What It Checks |
|-----|----------|----------|----------------|
| `final_answer` | `$contains` | `"depth=2 chain succeeded"` | Root's final answer text (Call 14) |
| `total_iterations` | `eq` | `2` | Exactly 2 orchestrator iterations |
| `total_model_calls` | `eq` | `15` | All 15 canned responses consumed |

### Fixture JSON State (`expected_state`)

| Key | Operator | Expected | What It Checks |
|-----|----------|----------|----------------|
| `user_provided_ctx` | `$not_none` | `true` | Initial state survived the pipeline |
| `user_ctx_manifest` | `$contains` | `"arch_context.txt"` | Manifest built from user_provided_ctx |
| `repo_url` | `$contains` | `"test.example.com"` | State key persisted |
| `skill_instruction` | `$contains` | `"run_test_skill"` | State key persisted |
| `last_repl_result` | `$not_none` | `true` | REPL produced output |
| `iteration_count` | `eq` | `2` | Final iteration count |
| `current_depth` | `eq` | `0` | Returned to root depth |
| `should_stop` | `eq` | `true` | Pipeline terminated |

### Test Class: Global Assertions

| Test Class | Test Method | Assertion |
|------------|-------------|-----------|
| `TestContractPasses` | `test_contract_passes` | `contract.passed` -- all fixture JSON expected/expected_state pass |
| `TestDynamicInstruction` | `test_no_unresolved_placeholders` | No `{repo_url?}`, `{root_prompt?}`, `{test_context?}`, `{skill_instruction?}`, `{user_ctx_manifest?}` in captured systemInstruction |
| `TestSqliteTelemetry` | `test_traces_completed` | `traces.status = 'completed'` and `total_calls >= 15` |
| `TestSqliteTelemetry` | `test_max_depth_reached` | `max_depth_reached >= 2` in traces table |
| `TestSqliteTelemetry` | `test_tool_invocation_summary` | `execute_code` and `set_model_response` in JSON summary |
| `TestDepthScopedState` | `test_iteration_count_at_root` | `final_state["iteration_count"] == 2` |
| `TestChildEventReemission` | `test_child_events_have_correct_authors` | Distinct `event_author` values at `key_depth > 0` in session_state_events |
| `TestDiagnosticDump` | `test_write_diagnostic_dump` | Diagnostic JSON written to `issues/dashboard/fixture_runtime_output.json` |

### Expected Lineage: Global Assertions

| Group | Key | Operator | Expected | Source Hint |
|-------|-----|----------|----------|-------------|
| **state_key** | `model_call_1:iteration_count` | `eq` | `"0"` | orchestrator.py -- initial state yields iteration_count=0 |
| **plugin_hook** | `before_agent:reasoning_agent:depth` | `eq` | `"0"` | agent.py -- _rlm_depth=0 on root reasoning_agent |
| **plugin_hook** | `before_model:reasoning_agent:call_num` | `gte` | `1` | InstrumentationPlugin -- monotonic counter |
| **plugin_hook** | `before_model:reasoning_agent:sys_instr_len` | `gt` | `0` | prompts.py -- RLM_STATIC_INSTRUCTION + resolved RLM_DYNAMIC_INSTRUCTION |
| **plugin_hook** | `after_model:reasoning_agent:finish_reason` | `eq` | `"STOP"` | orchestrator.py -- reasoning_agent finishes with STOP |
| **timing** | `agent_reasoning_agent_ms` | `gte` | `0.0` | InstrumentationPlugin.after_agent_callback |
| **timing** | `model_call_1_ms` | `gte` | `0.0` | InstrumentationPlugin.after_model_callback |
| **ordering** | `before_agent` before `before_model` | `before` | (reasoning_agent) | Agent lifecycle order |
| **ordering** | `before_model` before `before_tool` | `before` | (reasoning_agent) | Model decides, then tool fires |
| **ordering** | `before_tool` before `after_tool` | `before` | (reasoning_agent) | Tool bracket pair closed |

---

## Per-Call Assertion Map

---

### Call 0 -- `list_skills` (depth=0, caller=reasoning)

**Walkthrough**: Root reasoning agent begins L1 skill discovery. Returns XML catalog of available skills.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSkillToolsetDiscovery::test_list_skills_telemetry_exists` | >= 1 telemetry row with `tool_name='list_skills'` | SkillToolset wired and telemetry recording |
| `TestSkillToolsetDiscovery::test_list_skills_at_multiple_depths` | `depth=0` present in `list_skills` telemetry depths | L1 discovery works at root |

---

### Call 1 -- `load_skill("test-skill")` (depth=0, caller=reasoning)

**Walkthrough**: Root loads full SKILL.md body for test-skill (L2 discovery).

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSkillToolsetDiscovery::test_load_skill_telemetry_exists` | >= 1 telemetry row with `tool_name='load_skill'` | SkillToolset wired and telemetry recording |
| `TestSkillToolsetDiscovery::test_load_skill_at_multiple_depths` | `depth=0` present in `load_skill` telemetry depths | L2 discovery works at root |

---

### Call 2 -- `execute_code` (depth=0, caller=reasoning) -- `run_test_skill()`

**Walkthrough**: Root's first REPL execution. Calls `run_test_skill()` which internally calls `llm_query()` to spawn a child at depth=1. Also verifies `user_ctx` injection via DYN_INSTR tags.

This is the **densest assertion target** -- the root's first REPL turn spawns the entire depth=2 chain and emits most diagnostic tags.

#### Test class assertions against Call 2

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSqliteTelemetry::test_execute_code_telemetry` | `repl_llm_calls >= 1` in telemetry row | execute_code recorded nested LLM calls |
| `TestDynamicInstruction::test_resolved_values_present` | `DYN_INSTR:repo_url=resolved=True` in stdout | repo_url placeholder resolved |
| `TestDynamicInstruction::test_resolved_values_present` | `DYN_INSTR:user_ctx_manifest=resolved=True` in stdout | user_ctx_manifest placeholder resolved |
| `TestDynamicInstruction::test_resolved_values_present` | `DYN_INSTR:skill_instruction=resolved=True` in stdout | skill_instruction placeholder resolved |
| `TestDynamicInstruction::test_resolved_values_present` | `"test.example.com/depth2-batched"` in stdout | repo_url preview value correct |
| `TestBatchedDispatch::test_depth2_proof_in_stdout` | `"depth2_leaf_ok"` in combined stdout | Full depth=2 chain propagated leaf value back to root |

#### Expected lineage: plugin_hook assertions against Call 2

| Group | Key | Operator | Expected | Source Hint |
|-------|-----|----------|----------|-------------|
| **plugin_hook** | `before_tool:reasoning_agent:tool_name` | `eq` | `"execute_code"` | repl_tool.py -- REPLTool.name == 'execute_code' |

#### Expected lineage: TEST_SKILL tag assertions (emitted by `run_test_skill()` inside Call 2)

| Key | Operator | Expected | Source Hint |
|-----|----------|----------|-------------|
| `depth` | `eq` | `"0"` | repl_tool.py -- _rlm_depth injected into _rlm_state |
| `rlm_agent_name` | `eq` | `"reasoning_agent"` | repl_tool.py -- _rlm_agent_name from tool context |
| `iteration_count` | `eq` | `"1"` | repl_tool.py -- REPLTool increments _call_count before first execute_code |
| `current_depth` | `eq` | `"0"` | repl_tool.py -- current_depth from EXPOSED_STATE_KEYS snapshot |
| `should_stop` | `eq` | `"?"` | repl_tool.py -- None before any tool completes; skill defaults to '?' |
| `state_keys_count` | `gte` | `6` | repl_tool.py -- _rlm_state from EXPOSED_STATE_KEYS + 3 lineage metadata keys |
| `llm_query_fn_type` | `eq` | `"function"` | dispatch.py -- llm_query injected as closure |
| `execution_mode` | `eq` | `"thread_bridge"` | skill.py -- runtime detection: not MainThread |
| `worker_thread_name` | `not_contains` | `"MainThread"` | skill.py -- REPL runs in worker thread |
| `calling_llm_query` | `eq` | `"True"` | skill.py -- emitted immediately before llm_query_fn() call |
| `child_result_preview` | `contains` | `"child_confirmed_depth2"` | dispatch.py -- child at d1 returns via depth=2 chain |
| `thread_bridge_latency_ms` | `gt` | `0.0` | skill.py -- measured via time.perf_counter() |
| `COMPLETE` | `eq` | `"True"` | skill.py -- only emitted if run_test_skill returned without error |

#### Expected lineage: DYN_INSTR assertions (emitted by dyn_instr_capture_hook during Call 2's model call)

| Key | Operator | Expected | Source Hint |
|-----|----------|----------|-------------|
| `repo_url` | `contains` | `"resolved=True"` | prompts.py -- '{repo_url?}' resolved from session state |
| `root_prompt` | `contains` | `"resolved=True"` | prompts.py -- '{root_prompt?}' resolved from session state |
| `test_context` | `contains` | `"resolved=True"` | prompts.py -- '{test_context?}' resolved from raw key |
| `skill_instruction` | `contains` | `"resolved=True"` | prompts.py -- '{skill_instruction?}' resolved from DYN_SKILL_INSTRUCTION |
| `user_ctx_manifest` | `contains` | `"resolved=True"` | orchestrator.py Path B -- built from user_provided_ctx dict |
| `user_ctx_keys` | `contains` | `"arch_context.txt"` | orchestrator.py Path B -- pre-loads repl.globals['user_ctx'] |

#### Expected lineage: REPL_TRACE assertions (optional, emitted by REPLTracingPlugin)

| Key | Operator | Expected | Required | Source Hint |
|-----|----------|----------|----------|-------------|
| `execution_mode` | `eq` | `"thread_bridge"` | No | trace.py -- REPLTrace.execution_mode field |
| `wall_time_ms` | `gt` | `0.0` | No | ipython_executor.py -- pre/post_run_cell timing |
| `llm_call_count` | `gte` | `1` | No | trace.py -- REPLTrace.record_llm_start() |
| `submitted_code_chars` | `gt` | `0` | No | repl_tool.py -- trace.submitted_code_chars = len(expanded_code) |

---

### Call 3 -- `list_skills` (depth=1, caller=worker)

**Walkthrough**: Child reasoning agent (spawned by `run_test_skill`'s `llm_query`) begins L1 discovery. Proves GAP-A fix: children inherit SkillToolset.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSkillToolsetDiscovery::test_list_skills_at_multiple_depths` | Contributes to proving depth > 0 has `list_skills` | GAP-A fix at depth=1 |

---

### Call 4 -- `load_skill("test-skill")` (depth=1, caller=worker)

**Walkthrough**: Depth=1 child loads full test-skill instructions. Confirms L2 discovery at child depth.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSkillToolsetDiscovery::test_load_skill_at_multiple_depths` | Contributes to proving depth > 0 has `load_skill` | GAP-A fix at depth=1 |

---

### Call 5 -- `execute_code` (depth=1, caller=worker) -- `llm_query()` spawns grandchild

**Walkthrough**: Depth=1 child calls `llm_query('Return the leaf value: depth2_leaf_ok')`, spawning a grandchild at depth=2.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| *(no direct per-call assertion)* | Contributes to depth=2 chain; its REPL output (`grandchild_said=depth2_leaf_ok`) is consumed by Call 10's `set_model_response` | Recursive dispatch at depth=1 |

---

### Call 6 -- `list_skills` (depth=2, caller=worker)

**Walkthrough**: Grandchild at depth=2 begins L1 discovery. Proves SkillToolset propagation through two levels of recursion.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSkillToolsetDiscovery::test_list_skills_at_multiple_depths` | **`depth=2` required** in `list_skills` telemetry | GAP-A fix at deepest level |

---

### Call 7 -- `load_skill("test-skill")` (depth=2, caller=worker)

**Walkthrough**: Depth=2 grandchild loads full test-skill instructions. Confirms L2 discovery at deepest recursion level.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSkillToolsetDiscovery::test_load_skill_at_multiple_depths` | **`depth=2` required** in `load_skill` telemetry | GAP-A fix at deepest level |

---

### Call 8 -- `execute_code` (depth=2, caller=worker) -- state verification with `[D2_STATE:]` markers

**Walkthrough**: Grandchild reads `_rlm_state` at depth=2, verifies dynamic instruction state keys are resolved, prints `[D2_STATE:key=value]` proof markers. This is the deepest state-propagation verification in the fixture.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestDepth2StateVerification::test_d2_repl_result_exists` | `last_repl_result@d2` exists in final_state | Child event re-emission (d2->d1->d0) |
| `TestDepth2StateVerification::test_d2_state_markers_in_stdout` | `"[D2_STATE:"` present in d2 REPL stdout | Grandchild execute_code at idx 8 ran |
| `TestDepth2StateVerification::test_d2_depth_correct` | `"[D2_STATE:depth=2]"` in stdout | `_rlm_depth=2` propagated to grandchild |
| `TestDepth2StateVerification::test_d2_has_current_depth` | `"[D2_STATE:current_depth="` in stdout | current_depth key exists at d2 |
| `TestDepth2StateVerification::test_d2_proof_marker` | `"[D2_STATE:proof=depth2_state_verified]"` in stdout | Full d2 code execution completed |
| `TestDepth2StateVerification::test_d2_dyn_instr_skill_instruction_resolved` | `"D2_STATE:dyn_instr_skill_instruction=resolved=True"` in stdout | **GAP-D proof**: skill_instruction propagates to depth=2 |

---

### Call 9 -- `set_model_response` (depth=2, caller=worker) -- returns `"depth2_leaf_ok"`

**Walkthrough**: Grandchild terminates, returning the leaf value. This is the deepest point in the call tree. Control returns to depth=1 child's REPL where `llm_query()` unblocks.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSetModelResponseDepth::test_smr_depth2_exists` | `depth=2` present in SMR telemetry rows | BUG-014: grandchild SMR recorded at correct depth |
| `TestSetModelResponseDepth::test_smr_depth_distribution` | `{0, 1, 2}` all present in SMR depths | Full depth coverage |
| `TestChildEventReemission::test_depth2_final_response_text` | `final_response_text = "depth2_leaf_ok"` at `key_depth=2` | Grandchild's answer bubbled up via re-emission |
| `TestDepthScopedState::test_depth2_state_keys` | `key_depth=2` state keys exist in session_state_events | Two-stage child event re-emission (d2->d1->d0) working |

---

### Call 10 -- `set_model_response` (depth=1, caller=worker) -- returns `"child_confirmed_depth2: depth2_leaf_ok"`

**Walkthrough**: Depth=1 child resumes after grandchild returned. Forwards the grandchild result upward with confirmation prefix. Control returns to root's REPL where `run_test_skill()` completes.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSetModelResponseDepth::test_smr_depth_nonzero_exists` | At least one SMR row with `depth > 0` | BUG-014: child SMR not collapsed to depth=0 |
| `TestSetModelResponseDepth::test_smr_depth_distribution` | `depth=1` in the set | Depth=1 SMR recorded |
| `TestDepthScopedState::test_depth1_state_keys` | `key_depth=1` state keys exist, including `"current_depth"` | Child event re-emission at depth=1 |

---

### Call 11 -- `execute_code` (depth=0, caller=reasoning) -- `llm_query_batched(2 prompts, output_schema=BatchResult)`

**Walkthrough**: Root's second REPL execution (Turn 2). Tests parallel fanout with 2 prompts and structured output via `output_schema=BatchResult`. Also verifies cross-turn state persistence and REPL namespace persistence.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestBatchedDispatch::test_batch_count_in_stdout` | `"batch_count=2"` in stdout | `llm_query_batched` returned 2 results |
| `TestBatchedDispatch::test_batch_results_in_stdout` | `"batch_0="`, `"batch_1="` in stdout | Individual results printed |
| `TestBatchedDispatch::test_batch_results_in_stdout` | `"finding_A_summary"`, `"finding_B_summary"` in stdout | Correct child result values |
| `TestBatchedDispatch::test_turn2_iteration_count` | `"turn2_iteration_count=2"` in stdout | `_rlm_state` iteration_count incremented across turns |
| `TestBatchedDispatch::test_turn1_variable_persisted` | `"turn1_skill_result_persisted=True"` in stdout | Cross-turn REPL namespace persistence |
| `TestStructuredOutputCoverage::test_structured_output_marker_in_stdout` | `"[STRUCTURED_OUTPUT:"` marker present | output_schema=BatchResult code path executed |
| `TestStructuredOutputCoverage::test_structured_output_parsed_results` | `"[STRUCTURED_OUTPUT:batch_0_parsed=True]"` in stdout | Batch child 0 result parsed as BatchResult |
| `TestStructuredOutputCoverage::test_structured_output_parsed_results` | `"[STRUCTURED_OUTPUT:batch_1_parsed=True]"` in stdout | Batch child 1 result parsed as BatchResult |

---

### Call 12 -- `set_model_response` (depth=1, batch child 0) -- `{summary: "finding_A_summary", confidence: 0.92}`

**Walkthrough**: Batch child 0 (fanout_idx=0, prompt='Summarize finding A'). Immediately returns structured result matching BatchResult schema.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSetModelResponseDepth::test_smr_depth_nonzero_exists` | Contributes a `depth=1` SMR row | Batch children recorded at correct depth |
| `TestStructuredOutputCoverage::test_structured_output_field_values` | `"[STRUCTURED_OUTPUT:batch_0_summary=finding_A_summary]"` in stdout | Schema field `summary` accessible via `.parsed` |
| `TestStructuredOutputCoverage::test_structured_output_field_values` | `"[STRUCTURED_OUTPUT:batch_0_confidence=0.92]"` in stdout | Schema field `confidence` accessible via `.parsed` |

---

### Call 13 -- `set_model_response` (depth=1, batch child 1) -- `{summary: "finding_B_summary", confidence: 0.87}`

**Walkthrough**: Batch child 1 (fanout_idx=1, prompt='Summarize finding B'). Immediately returns structured result matching BatchResult schema.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| `TestSetModelResponseDepth::test_smr_depth_nonzero_exists` | Contributes a `depth=1` SMR row | Batch children recorded at correct depth |
| `TestStructuredOutputCoverage::test_structured_output_field_values` | `"[STRUCTURED_OUTPUT:batch_1_summary=finding_B_summary]"` in stdout | Schema field `summary` accessible via `.parsed` |
| `TestStructuredOutputCoverage::test_structured_output_field_values` | `"[STRUCTURED_OUTPUT:batch_1_confidence=0.87]"` in stdout | Schema field `confidence` accessible via `.parsed` |

---

### Call 14 -- `set_model_response` (depth=0, caller=reasoning) -- final pipeline answer

**Walkthrough**: Root reasoning agent returns the final answer after both turns complete. The pipeline is done.

| Source | Assertion | What It Proves |
|--------|-----------|----------------|
| **Fixture JSON** `expected.final_answer` | `$contains "depth=2 chain succeeded"` | Root's final answer contains expected text |
| `TestSetModelResponseDepth::test_smr_depth_distribution` | `depth=0` in the SMR depth set | Root's SMR recorded at depth=0 |
| **Lineage: plugin_hook** | `before_tool:reasoning_agent:tool_name eq "set_model_response"` | ADK SetModelResponseTool fired before_tool for root -- proves upward flow at d0 |

---

## Summary Counts

| Category | Count |
|----------|-------|
| Fixture JSON contract assertions (`expected`) | 3 |
| Fixture JSON state assertions (`expected_state`) | 8 |
| Test class assertions (`test_skill_arch_e2e.py`) | 33 test methods |
| Expected lineage: state_key expectations | 1 |
| Expected lineage: test_skill expectations | 13 |
| Expected lineage: plugin_hook expectations | 6 |
| Expected lineage: timing expectations | 2 |
| Expected lineage: ordering expectations | 3 |
| Expected lineage: dyn_instr expectations | 6 |
| Expected lineage: repl_trace expectations | 4 (all optional) |
| **Total unique assertion points** | **~79** |

---

## Architectural Properties Proven

Each property is proven by the conjunction of specific assertions, not any single one:

| Property | Key Assertions |
|----------|---------------|
| **GAP-A: Children get SkillToolset** | list_skills at depth={0,1,2} in telemetry; load_skill at depth={0,1,2} in telemetry |
| **GAP-D: Children get dynamic instruction** | `D2_STATE:dyn_instr_skill_instruction=resolved=True`; DYN_INSTR tags for all 5 placeholders |
| **Depth=2 recursion** | `depth2_leaf_ok` in stdout; `child_confirmed_depth2` in TEST_SKILL; SMR at depth=2; max_depth_reached >= 2 |
| **Batched dispatch** | `batch_count=2`; both `finding_A_summary` and `finding_B_summary` in stdout |
| **Structured output** | `STRUCTURED_OUTPUT:batch_{0,1}_parsed=True`; field values (`summary`, `confidence`) accessible |
| **Cross-turn REPL persistence** | `turn1_skill_result_persisted=True`; `turn2_iteration_count=2` |
| **Child event re-emission** | `last_repl_result@d2` in final_state; depth=1 and depth=2 state keys in session_state_events; `final_response_text="depth2_leaf_ok"` at key_depth=2 |
| **BUG-014: SMR depth correctness** | SMR depths include {0, 1, 2}; at least one SMR with depth > 0; depth=2 explicitly present |
| **Thread bridge execution** | `execution_mode eq "thread_bridge"`; `worker_thread_name not_contains "MainThread"`; `thread_bridge_latency_ms gt 0.0` |
| **Full observability pipeline** | traces.status='completed'; total_calls >= 15; tool_invocation_summary has execute_code + set_model_response; InstrumentationPlugin hook ordering verified |
