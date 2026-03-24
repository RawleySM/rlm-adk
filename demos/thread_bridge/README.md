# Thread Bridge Showboat Demos

Showboat demos for the Thread Bridge + ADK SkillToolset TDD plan (Plan B). Each demo proves that a specific TDD cycle test exercises real behavior, not reward-hacked assertions.

## How to Use These Demos

1. Complete the TDD implementation for the referenced cycle
2. Run the demo steps in order
3. Check each item in the verification checklist
4. If any step fails, the implementation has a gap

Demos are designed to be run AFTER implementation is complete. They are verification tools, not implementation guides.

## Demo Index

| Demo File | TDD Cycle | Risk Level | Description | Type |
|-----------|-----------|------------|-------------|------|
| `demo_cycle_1_sync_bridge_dispatch.md` | 1 | **HIGH** | Cross-thread dispatch via `run_coroutine_threadsafe` | Manual (runnable scripts) |
| `demo_cycle_4_lock_free_execution.md` | 4 | **HIGH** | `_EXEC_LOCK` deadlock prevention under recursive dispatch | Manual (runnable scripts) |
| `demo_cycle_5_oneshot_executor.md` | 5 | MEDIUM | Thread pool exhaustion prevention via one-shot executors | Manual (runnable scripts) |
| `demo_cycle_6_finalize_telemetry_finally.md` | 6 | MEDIUM | `_finalize_telemetry` fires in `finally` block on all paths | Manual (source inspection + tests) |
| `demo_cycle_7_orchestrator_wiring.md` | 7 | **HIGH** | Sync bridge replaces RuntimeError stub in REPL globals | Manual (runnable scripts) |
| `demo_cycle_11_llm_query_fn_injection.md` | 11 | **HIGH** | Lazy binding auto-injection of `llm_query_fn` from REPL globals | Manual (runnable scripts) |
| `demo_cycle_16_reasoning_before_model_fix.md` | 16 | **CRITICAL** | `reasoning_before_model` no longer destroys SkillToolset L1 XML | Manual (runnable scripts + source inspection) |
| `demo_cycle_21_e2e_thread_bridge_contract.md` | 21 | **CRITICAL** | Full pipeline: skill import -> thread bridge -> child dispatch -> return | Manual + automated (provider-fake e2e) |
| `demo_cycle_22_24_e2e_three_plane_verification.md` | 22-24 | **HIGH** | State, telemetry, and trace planes capture correct data through bridge | Manual (SQLite queries after e2e run) |
| `demo_cycle_26_recursive_ping_capstone.md` | 26 | **CRITICAL** | Capstone: module-imported function calls `llm_query()` via thread bridge | Manual + automated (provider-fake e2e) |

## Cycles NOT Demoed (and why)

The following cycles are pure unit tests or validation cycles where reward-hacking risk is low. Their tests are sufficient without a separate demo.

| Cycle | Description | Why No Demo Needed |
|-------|-------------|-------------------|
| 2 | Timeout, error propagation, thread depth limit | Pure unit tests with deterministic async mocks. The mock coroutine either sleeps (timeout) or raises (error). No ambiguity about what is tested. |
| 3 | `make_sync_llm_query_batched` | Same pattern as Cycle 1 but for lists. The concurrency timing test (sum vs max) is already a strong anti-reward-hack assertion. |
| 8 | `execution_mode` in LAST_REPL_RESULT | Pure state key assertion. Verified end-to-end in Cycle 24 demo. |
| 9 | Full regression (both modes) | Validation cycle, no new tests. |
| 10 | `discover_skill_dirs()` | Filesystem scanning with `tmp_path` -- deterministic, no mocks. |
| 12 | `collect_skill_repl_globals` | Import + export collection. Tested with real temp skill modules. |
| 13 | Recursive-ping skill directory | Directory convention + function contract. Terminal layer test uses real function, non-terminal uses explicit mock `llm_query_fn`. |
| 14 | Wire skill globals in orchestrator | Covered by Cycle 21 and 26 e2e demos. |
| 15 | SkillToolset creation | Covered by Cycle 25 (SkillToolset e2e). |
| 17 | `REPL_SKILL_GLOBALS_INJECTED` state key | Pure import-and-assert. |
| 18 | `LineageEnvelope.decision_mode` expansion | Pure Pydantic model construction. |
| 19 | `SqliteTracingPlugin` skill tool branches | Covered by three-plane verification demo (Cycles 22-24). |
| 20 | Instruction disambiguation + child split gating | String assertion on `RLM_STATIC_INSTRUCTION`. Covered by Cycle 25 e2e. |
| 25 | SkillToolset L1/L2 e2e | Integration test with provider-fake. Lower risk because it builds on Cycle 16 fix which has its own demo. |
| 27 | Full regression both modes | Validation cycle, no new tests. |

## Risk Classification

- **CRITICAL**: Silent failure mode. The feature appears to work but produces wrong results. No error, no warning. Only a demo with observable evidence can prove correctness.
- **HIGH**: The test could be reward-hacked with a mock or fixture that simulates the outcome. The demo proves the real mechanism fires.
- **MEDIUM**: The test exercises a real code path but the risk of accidental reward-hacking is lower (e.g., source inspection can verify the structure).
- **LOW**: Pure unit test of a utility function. The test itself is the proof.

## Key Anti-Reward-Hacking Principle

The strongest demos in this collection share one pattern: **disabling the thread bridge breaks the test**.

```bash
# This should PASS:
.venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py -x -q

# This should FAIL:
RLM_REPL_THREAD_BRIDGE=0 .venv/bin/python -m pytest tests_rlm_adk/test_skill_thread_bridge_e2e.py -x -q
```

If both pass, the test is reward-hacked -- it does not actually require the thread bridge. If only the first passes, the thread bridge is genuinely exercised.
