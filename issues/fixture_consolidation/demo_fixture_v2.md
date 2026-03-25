# Comprehensive Fixture v2: `skill_arch_test.json`

Date: 2026-03-25

---

## 1. What the Comprehensive Fixture Covers

The `skill_arch_test.json` fixture exercises the full RLM-ADK pipeline in a single deterministic run:

- **4 tools**: `list_skills`, `load_skill`, `execute_code`, `set_model_response`
- **3 depths**: d0 (root reasoning agent), d1 (child worker), d2 (grandchild worker)
- **REPL dispatch functions**: `llm_query()` (depth chain) + `llm_query_batched()` (2-prompt fanout)
- **Dynamic instruction resolution**: `{repo_url?}`, `{root_prompt?}`, `{test_context?}`, `{skill_instruction?}`, `{user_ctx_manifest?}` resolved at all depths
- **Cross-turn REPL persistence**: Turn 1 variable `result` readable in Turn 2
- **SkillToolset at all depths**: L1 (`list_skills`) and L2 (`load_skill`) at d0, d1, d2 -- proves GAP-A fix
- **State propagation**: `_rlm_state` snapshot readable at d2 with depth-scoped keys
- **Child event re-emission**: d2 state keys bubble through d1 to d0 session
- **SQLite telemetry**: traces, telemetry, session_state_events tables populated across all depths

---

## 2. The 15-Response Sequence

```
idx  depth  caller     tool               purpose
───  ─────  ─────────  ─────────────────  ──────────────────────────────────────────────
 0   0      reasoning  list_skills        L1 skill discovery at d0
 1   0      reasoning  load_skill         L2 instructions (test-skill) at d0
 2   0      reasoning  execute_code       run_test_skill() + user_ctx + DYN_INSTR tags
   3 1      worker     list_skills        L1 discovery at d1 (proves GAP-A fix)
   4 1      worker     load_skill         L2 instructions at d1
   5 1      worker     execute_code       d1 REPL: llm_query() -> d2 grandchild
     6  2   worker     list_skills        L1 discovery at d2
     7  2   worker     load_skill         L2 instructions at d2
     8  2   worker     execute_code       d2 REPL: reads _rlm_state, prints [D2_STATE:] markers
     9  2   worker     set_model_response d2 leaf returns "depth2_leaf_ok"
  10 1      worker     set_model_response d1 returns "child_confirmed_depth2: depth2_leaf_ok"
11   0      reasoning  execute_code       llm_query_batched(2) + cross-turn persistence check
  12 1      worker     set_model_response batch child 0 returns "finding_A_summary"
  13 1      worker     set_model_response batch child 1 returns "finding_B_summary"
14   0      reasoning  set_model_response terminal completion
```

Fixture path: `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json`

---

## 3. Coverage Matrix

### Test classes in `test_skill_arch_e2e.py` (11 classes, 31 test methods)

| Test Class | # Tests | What It Asserts | Depth Coverage |
|---|---|---|---|
| `TestContractPasses` | 1 | Contract runner passes (final_answer, total_iterations=2, total_model_calls=15, state assertions) | d0 |
| `TestArchitectureLineage` | 1 | 40+ expectations via `build_skill_arch_test_lineage()` across 7 categories (state_key, test_skill, plugin_hook, timing, ordering, dyn_instr, repl_trace) | d0 |
| `TestDynamicInstruction` | 2 | No unresolved `{var?}` placeholders in captured system instruction; `DYN_INSTR:*=resolved=True` tags for repo_url, user_ctx_manifest, skill_instruction | d0, d2 |
| `TestSqliteTelemetry` | 4 | traces.status=completed, total_calls>=15, execute_code repl_llm_calls>=1, max_depth_reached>=2, tool_invocation_summary contains execute_code+set_model_response | d0-d2 |
| `TestSetModelResponseDepth` | 3 | BUG-014: set_model_response telemetry rows have depths {0, 1, 2}; at least one nonzero; depth=2 exists | d0, d1, d2 |
| `TestDepthScopedState` | 3 | session_state_events has key_depth=1 and key_depth=2 rows; current_depth at d1; iteration_count=2 at d0 | d0, d1, d2 |
| `TestChildEventReemission` | 2 | Child event authors with key_depth>0; grandchild final_response_text="depth2_leaf_ok" at key_depth=2 | d1, d2 |
| `TestBatchedDispatch` | 5 | batch_count=2 in stdout; batch_0/batch_1 results; finding_A_summary/finding_B_summary; turn2_iteration_count=2; turn1_skill_result_persisted=True; depth2_leaf_ok in stdout | d0, d1 |
| `TestSkillToolsetDiscovery` | 4 | list_skills and load_skill telemetry rows exist; both appear at depth=0 AND depth>0 (proves GAP-A) | d0, d1, d2 |
| `TestDepth2StateVerification` | 5 | [D2_STATE:] markers in last_repl_result@d2 stdout; depth=2, current_depth, proof=depth2_state_verified, dyn_instr_skill_instruction=resolved=True | d2 |
| `TestDiagnosticDump` | 1 | Writes comprehensive JSON diagnostic dump for dashboard investigation | all |

### Test classes in `test_child_feature_parity.py` (9 classes, 12 test methods)

| Test Class | # Tests | What It Asserts |
|---|---|---|
| `TestCreateChildOrchestratorEnabledSkills` | 2 | `create_child_orchestrator` accepts/defaults `enabled_skills` |
| `TestDispatchPropagatesEnabledSkills` | 1 | Dispatch closure forwards `enabled_skills` to child |
| `TestOrchestratorPassesEnabledSkillsToDispatch` | 1 | `_run_async_impl` passes `self.enabled_skills` to dispatch |
| `TestDepth2InductionEnabledSkills` | 1 | d1 child re-passes `enabled_skills` to its own dispatch (induction step) |
| `TestCreateChildOrchestratorRepoUrl` | 2 | `create_child_orchestrator` accepts/defaults `repo_url` |
| `TestDispatchPropagatesRepoUrl` | 1 | Dispatch closure forwards `repo_url` to child |
| `TestOrchestratorPassesRepoUrlToDispatch` | 1 | `_run_async_impl` passes `self.repo_url` to dispatch |
| `TestChildStaticInstructionMentionsSkillTools` | 2 | `RLM_CHILD_STATIC_INSTRUCTION` mentions list_skills/load_skill; parity with root |
| `TestChildOrchestratorSeedsDynRepoUrl` | 1 | Child emits `DYN_REPO_URL` in initial state delta |

---

## 4. Runnable Verification Commands

```bash
# Full e2e suite (11 classes, 31 assertions) -- provider-fake, ~6s
.venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py -x -v -o "addopts="

# Child feature parity (9 classes, 12 assertions) -- unit tests, ~2s
.venv/bin/python -m pytest tests_rlm_adk/test_child_feature_parity.py -x -q -o "addopts="

# Both together
.venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py tests_rlm_adk/test_child_feature_parity.py -x -v -o "addopts="

# Single class quick-check (e.g., GAP-A proof)
.venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py::TestSkillToolsetDiscovery -x -v -o "addopts="
```

---

## 5. Before/After Comparison

### Fixture v1 vs v2

| Dimension | v1 (pre-consolidation) | v2 (consolidated) |
|---|---|---|
| Fixture file | `skill_arch_test.json` (8 responses) | `skill_arch_test.json` (15 responses) |
| Max depth exercised | 1 | 2 |
| Tools exercised | execute_code, set_model_response | list_skills, load_skill, execute_code, set_model_response |
| SkillToolset at child depths | Not tested | Proven at d0, d1, d2 |
| `llm_query_batched` | Not exercised | 2-prompt fanout with result verification |
| Cross-turn REPL persistence | Not tested | Turn 1 `result` variable verified in Turn 2 |
| Dynamic instruction at d2 | Not tested | `DYN_INSTR:skill_instruction=resolved=True` at d2 |
| State propagation at d2 | Not tested | `[D2_STATE:]` markers prove `_rlm_state` at d2 |
| Total model calls | 3 | 15 |
| Total REPL iterations | 1 | 2 |

### Test class count

| Module | v1 | v2 | Delta |
|---|---|---|---|
| `test_skill_arch_e2e.py` | 6 classes, ~18 tests | 11 classes, 31 tests | +5 classes, +13 tests |
| `test_child_feature_parity.py` | did not exist | 9 classes, 12 tests | +9 classes, +12 tests |
| **Total** | **6 classes, ~18 tests** | **20 classes, 43 tests** | **+14 classes, +25 tests** |

### Gaps closed

| Gap ID | Description | How v2 Closes It |
|---|---|---|
| GAP-A | Children miss SkillToolset | `enabled_skills` propagated through 4-hop chain; list_skills/load_skill telemetry at d1/d2 |
| GAP-B | Thread bridge assertion accepted deleted AST rewriter | `execution_mode` changed to strict `eq "thread_bridge"`; `worker_thread_name` assertion added |
| GAP-C | Skills can't use `llm_query_batched_fn` | Loader detects both params; wrapper injects both; `run_test_skill` signature updated |
| GAP-D | Children miss dynamic instruction + repo_url | `repo_url` propagated; `RLM_CHILD_STATIC_INSTRUCTION` mentions skill tools; `DYN_REPO_URL` seeded in child state delta |

---

## 6. Verification Checklist

- [ ] `skill_arch_test.json` has exactly 15 responses (call_index 0-14)
- [ ] Fixture config has `enabled_skills: ["test_skill"]` and `initial_state` with `repo_url`, `skill_instruction`
- [ ] `test_skill_arch_e2e.py` -- 11 test classes, all pass
- [ ] `test_child_feature_parity.py` -- 9 test classes, all pass
- [ ] `TestSkillToolsetDiscovery` -- list_skills/load_skill telemetry at depth=0 AND depth>0
- [ ] `TestSetModelResponseDepth` -- set_model_response telemetry at depths {0, 1, 2}
- [ ] `TestDepth2StateVerification` -- `[D2_STATE:depth=2]` and `[D2_STATE:proof=depth2_state_verified]` in d2 stdout
- [ ] `TestBatchedDispatch` -- batch_count=2, both results present, cross-turn persistence confirmed
- [ ] `TestDynamicInstruction` -- no unresolved `{var?}` placeholders; resolved values present at d0 and d2
- [ ] `TestChildEventReemission` -- grandchild `final_response_text="depth2_leaf_ok"` at key_depth=2
- [ ] `TestDepthScopedState` -- key_depth=1 and key_depth=2 rows in session_state_events
- [ ] `TestSqliteTelemetry` -- traces.status=completed, total_calls>=15, max_depth_reached>=2
- [ ] Contract runner: total_iterations=2, total_model_calls=15
- [ ] `build_skill_arch_test_lineage()` -- 40+ expectations across 7 assertion groups, 0 failures

---

## 7. Bug Found During Implementation: InstrumentationPlugin Stdout Contamination

**Location:** `tests_rlm_adk/provider_fake/instrumented_runner.py`, lines 68-97

**Problem:** The `InstrumentationPlugin` originally printed `[PLUGIN:...]` tags directly to `sys.stdout` via `print()`. Plugin callbacks fire on the asyncio event loop while `execute_code` blocks on the thread bridge. During child agent execution, stdout prints from plugin callbacks leaked into the REPL tool response text, because ADK captures stdout during tool execution. This caused ADK's output parser to see unexpected content in the tool result, which terminated child agent loops prematurely.

**Fix:** `InstrumentationPlugin` now buffers all output to `self._log_lines` (a `list[str]`) instead of printing to stdout. The `_emit()` method appends to the list. After the run completes, the instrumented runner merges the buffered lines into the full log for assertion parsing:

```python
# Before (broken): plugin callbacks printed to sys.stdout during execution
def _emit(self, hook, agent_name, **kwargs):
    for key, value in kwargs.items():
        print(f"[PLUGIN:{hook}:{agent_name}:{key}={value}]")  # leaked into REPL

# After (fixed): buffer to list, merge after run completes
def _emit(self, hook, agent_name, **kwargs):
    for key, value in kwargs.items():
        self._log_lines.append(f"[PLUGIN:{hook}:{agent_name}:{key}={value}]")
```

**Impact:** Without this fix, any fixture with child dispatch (depth>0) would fail non-deterministically because plugin output would corrupt the REPL tool response at unpredictable points. This was the root cause of the "child agent terminates after one turn" symptom observed during v2 fixture development.
