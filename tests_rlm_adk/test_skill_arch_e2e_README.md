# test_skill_arch_e2e.py — Test Module Documentation

## 1. Overview

`test_skill_arch_e2e.py` is an end-to-end test that exercises the full RLM-ADK pipeline through a single provider-fake fixture with **8 model calls**, **3 reasoning turns**, recursive child dispatch to **depth=2**, both `llm_query()` and `llm_query_batched()`, and the complete observability stack (SQLite telemetry, child event re-emission, dynamic instruction resolution). The fixture drives a test skill (`run_test_skill`) that dispatches a child at d=1 which itself dispatches a grandchild at d=2, then a separate batched fanout with 2 prompts. **18+ assertions** across **8 test classes** validate that the full pipeline executed correctly, with every assertion depending on real pipeline execution rather than scripted fixture content.

## 2. Architecture Under Test

```
Root (d=0): execute_code → run_test_skill(child_prompt=...) → llm_query()
  Child (d=1): execute_code → llm_query('Return the leaf value: depth2_leaf_ok')
    Grandchild (d=2): set_model_response("depth2_leaf_ok")
  Child (d=1): set_model_response("child_confirmed_depth2: depth2_leaf_ok")
Root (d=0): execute_code → llm_query_batched(["Summarize finding A", "Summarize finding B"])
  Batch Child 0 (d=1): set_model_response("finding_A_summary")
  Batch Child 1 (d=1): set_model_response("finding_B_summary")
Root (d=0): set_model_response(final)
```

The depth=2 chain proves: root REPL → skill function → thread bridge → child orchestrator → child REPL → thread bridge → grandchild orchestrator → grandchild answer → unwind back through both bridges to root REPL. The batched path proves `llm_query_batched` dispatches N children in parallel via `asyncio.gather` and returns all results.

## 3. FIFO Response Sequence

| call_index | depth | caller | tool | What happens |
|---|---|---|---|---|
| 0 | 0 | reasoning | `execute_code` | Root calls `run_test_skill(child_prompt=..., emit_debug=True, rlm_state=_rlm_state)`. Skill emits `[TEST_SKILL:...]` diagnostic tags, calls `llm_query_fn()` which blocks the REPL thread until d=1 child returns. Also prints `[DYN_INSTR:...]` tags to verify dynamic instruction resolution. |
| 1 | 1 | worker | `execute_code` | Child d=1 reasoning agent calls `execute_code` with code: `grandchild_result = llm_query('Return the leaf value: depth2_leaf_ok')`. The `llm_query()` call blocks the child REPL thread and dispatches a grandchild at d=2. |
| 2 | 2 | worker | `set_model_response` | Grandchild d=2 is a leaf node. Immediately returns `final_answer: "depth2_leaf_ok"`. No REPL execution at d=2. |
| 3 | 1 | worker | `set_model_response` | Child d=1 REPL resumes after grandchild returns. Reasoning agent sees `grandchild_said=depth2_leaf_ok` in tool output. Returns `final_answer: "child_confirmed_depth2: depth2_leaf_ok"`. |
| 4 | 0 | reasoning | `execute_code` | Root reasoning sees Turn 1 output (skill tags + `skill_result=child_confirmed_depth2: depth2_leaf_ok`). Calls `execute_code` with `llm_query_batched(['Summarize finding A', 'Summarize finding B'])`, prints each result, `batch_count=2`, `turn2_iteration_count=2`, and verifies Turn 1 variable persistence (`turn1_skill_result_persisted=True`). |
| 5 | 1 | worker | `set_model_response` | Batch child 0 (fanout_idx=0). Returns `final_answer: "finding_A_summary"`. |
| 6 | 1 | worker | `set_model_response` | Batch child 1 (fanout_idx=1). Returns `final_answer: "finding_B_summary"`. |
| 7 | 0 | reasoning | `set_model_response` | Root returns final answer: `"Pipeline verified: depth=2 chain succeeded (depth2_leaf_ok via child), batched dispatch returned 2 results (finding_A_summary, finding_B_summary)."` |

FIFO order is deterministic because each `llm_query()` call blocks its REPL thread via `run_coroutine_threadsafe`, so the next model call always comes from the deepest pending child. Batch children (calls 5-6) run sequentially in the zero-latency fake server.

## 4. What Each Test Class Validates

### 4.1 TestContractPasses

**What it tests**: The fixture contract (expected final_answer, total_iterations=2, total_model_calls=8, and expected_state assertions) all pass.

**Pipeline component**: End-to-end fixture contract system (`run_fixture_contract_instrumented`). Proves the entire pipeline ran to completion and produced expected state.

**Assertion strength**: Strong. Contract assertions check `iteration_count=2`, `should_stop=true`, `current_depth=0`, `last_repl_result` not-none, and `final_answer` contains `"depth=2 chain succeeded"` -- all of which require the full pipeline to execute.

### 4.2 TestArchitectureLineage

**What it tests**: The full expected lineage (state keys, `[TEST_SKILL:...]` tags, plugin hooks, timing constraints, ordering invariants, `[DYN_INSTR:...]` tags, and REPL trace fields) all match expected values.

**Pipeline component**: `build_skill_arch_test_lineage()` defines 40+ expectations across 7 categories. `run_all_assertions()` evaluates every expectation against parsed stdout. This is the most comprehensive single assertion in the test module.

**Assertion strength**: Mixed. Strong assertions include `execution_mode=thread_bridge` (runtime thread detection), `child_result_preview` containing `"child_confirmed_depth2"` (requires full d=0 to d=2 to d=0 chain), `llm_query_fn_type=function` (proves loader wrapper injection). Structural assertions include plugin hook ordering (before_agent before before_model before before_tool).

### 4.3 TestDynamicInstruction

**What it tests**: All dynamic instruction placeholders (`{repo_url?}`, `{root_prompt?}`, `{test_context?}`, `{skill_instruction?}`, `{user_ctx_manifest?}`) were resolved before the first model call, and specific resolved values appear in DYN_INSTR tags.

**Pipeline component**: `rlm_adk/utils/prompts.py` placeholder resolution, `orchestrator.py` Path B user_ctx manifest building.

**Assertion strength**: Strong. `test_no_unresolved_placeholders` reads `_captured_system_instruction_0` (captured by the instrumentation plugin at the first model call) and scans for literal placeholder strings. `test_resolved_values_present` checks for `"test.example.com/depth2-batched"` in output, confirming the fixture's `repo_url` value was injected into the dynamic instruction.

### 4.4 TestSqliteTelemetry

**What it tests**: The SQLite traces.db contains correct telemetry: `traces.status='completed'`, `total_calls >= 8`, `execute_code` tool rows with `repl_llm_calls >= 1`, `max_depth_reached >= 2`, and `tool_invocation_summary` contains both `execute_code` and `set_model_response`.

**Pipeline component**: `SqliteTracingPlugin` (`rlm_adk/plugins/sqlite_tracing.py`) -- the full observability pipeline from plugin callbacks through SQLite insertion.

**Assertion strength**: Strong. `max_depth_reached >= 2` can only be true if the grandchild at d=2 actually executed and the plugin recorded its depth. `repl_llm_calls >= 1` requires the REPLTool to have detected `llm_query` calls during code execution.

### 4.5 TestSetModelResponseDepth (BUG-014 regression)

**What it tests**: `set_model_response` tool_call rows in the SQLite `telemetry` table have correct depth values: at least one row with `depth > 0`, at least one row with `depth = 2`, and the full set `{0, 1, 2}` is represented.

**Pipeline component**: `SqliteTracingPlugin.before_tool_callback` depth resolution. This is a regression test for BUG-014, where all `set_model_response` tool_call rows were recorded with `depth=0` because the plugin read `tool._depth` (only set on REPLTool) instead of `agent._rlm_depth`.

**Assertion strength**: Strong. These assertions directly query the SQLite telemetry table and will fail if the BUG-014 fix regresses.

### 4.6 TestDepthScopedState

**What it tests**: Depth-scoped state keys (`current_depth@d1`, `current_depth@d2`, etc.) appear in `session_state_events` at the correct `key_depth` values, and `iteration_count=2` at depth=0.

**Pipeline component**: Child event re-emission pipeline (`dispatch.py` curated filter -> `asyncio.Queue` -> `orchestrator.py` drain loop -> `SqliteTracingPlugin.on_event_callback`). Proves that child state deltas bubble up through the re-emission queue to the root session.

**Assertion strength**: Strong. `key_depth=2` rows can only exist if the grandchild's state events traversed two stages of re-emission (d=2 -> d=1 -> d=0). `iteration_count=2` in `final_state` requires both `execute_code` calls to have incremented the counter.

### 4.7 TestChildEventReemission

**What it tests**: Child events have distinct `event_author` values at `key_depth > 0`, and the grandchild's `final_response_text='depth2_leaf_ok'` appears in `session_state_events` at `key_depth=2`.

**Pipeline component**: The full re-emission data path: child orchestrator yields `state_delta` -> dispatch curated filter -> `asyncio.Queue` -> parent drain -> SQLite insertion with `event_author` preserved.

**Assertion strength**: Strong. `final_response_text='depth2_leaf_ok'` at `key_depth=2` is the strongest single proof that the depth=2 grandchild executed, returned a value, and that value was correctly re-emitted through two queue hops to the root's `session_state_events` table.

### 4.8 TestBatchedDispatch

**What it tests**: `llm_query_batched` returned 2 results (`batch_count=2`), individual results `finding_A_summary` and `finding_B_summary` appear in stdout, Turn 2 read `iteration_count=2` from `_rlm_state`, the Turn 1 `result` variable persisted into Turn 2's REPL namespace, and `depth2_leaf_ok` flows through the depth=2 chain into root stdout.

**Pipeline component**: `llm_query_batched` dispatch (via `asyncio.gather` with parallel workers), REPL namespace persistence across `execute_code` calls, `_rlm_state` snapshot correctness.

**Assertion strength**: Strong. `batch_count=2` is printed by REPL code that calls `len(batch_results)` on the real return value of `llm_query_batched`. `turn2_iteration_count=2` reads from `_rlm_state` which is a snapshot of session state at the time of the second `execute_code` call. `turn1_skill_result_persisted=True` checks `"result" in dir()`, proving REPL globals persist across tool calls.

## 5. Anti-Reward-Hacking Design

Every assertion in this test module depends on **real pipeline execution**, not on values that could be trivially satisfied by a scripted fixture response. The fixture provides the model's tool-call decisions (what code to execute, what to answer), but all observable signals are produced by the pipeline processing those decisions.

### Key "proof chain" assertions

| Assertion | Why it cannot be faked |
|---|---|
| `child_result_preview` contains `"child_confirmed_depth2"` | Requires the full chain: root REPL -> skill -> thread bridge -> d=1 child -> d=1 REPL -> thread bridge -> d=2 grandchild -> `"depth2_leaf_ok"` return -> d=1 resume -> `"child_confirmed_depth2: depth2_leaf_ok"` return -> root REPL resume. |
| `execution_mode=thread_bridge` | Detected at runtime via `threading.current_thread().name != "MainThread"` inside the test skill. Only true if REPL code runs in a worker thread, which only happens via the thread bridge. |
| `batch_count=2` | Printed by `len(batch_results)` where `batch_results` is the real return value of `llm_query_batched()`. The fixture only provides the child responses; the count comes from the dispatch machinery. |
| `turn2_iteration_count=2` | Printed by `_rlm_state.get("iteration_count")` inside the second `execute_code` call. Requires REPLTool to have incremented the counter twice and the `_rlm_state` snapshot to reflect the current session state. |
| `turn1_skill_result_persisted=True` | Printed by `"result" in dir()` in Turn 2 code. Requires the `result` variable from Turn 1's `run_test_skill()` call to persist in the REPL namespace across tool calls. |
| `final_response_text='depth2_leaf_ok'` at `key_depth=2` | Requires the grandchild's output to traverse two stages of event re-emission (d=2 -> d=1 -> d=0) and be inserted into `session_state_events` with correct depth tagging. |

### What was REMOVED as reward-hackable

| Removed assertion | Why it was reward-hackable |
|---|---|
| `should_stop=False` at model_call_1 | `dict.get("should_stop", False)` returns `False` by default -- the assertion passes even if the key was never set. |
| `repl_did_expand` | Dead signal from the deleted AST rewriter. Source expansion no longer occurs; the field was always false or absent. |
| `execution_mode` with `oneof` operator | Accepted both `"thread_bridge"` and `"async_rewrite"`, but the `async_rewrite` path was deleted. Changed to strict `eq` against `"thread_bridge"`. |

## 6. Observable Signals

| Signal | Source | Origin |
|---|---|---|
| `[TEST_SKILL:depth=0]` | REPL stdout | **Real**: `_rlm_state["_rlm_depth"]` injected by REPLTool from session state |
| `[TEST_SKILL:execution_mode=thread_bridge]` | REPL stdout | **Real**: `threading.current_thread().name` checked at runtime |
| `[TEST_SKILL:child_result_preview=child_confirmed_depth2...]` | REPL stdout | **Real**: return value from `llm_query_fn()` after full d=1->d=2 chain |
| `batch_count=2` | REPL stdout | **Real**: `len(batch_results)` on `llm_query_batched()` return |
| `turn2_iteration_count=2` | REPL stdout | **Real**: `_rlm_state.get("iteration_count")` snapshot at second execute_code |
| `turn1_skill_result_persisted=True` | REPL stdout | **Real**: `"result" in dir()` checks REPL namespace persistence |
| `[DYN_INSTR:repo_url=resolved=True]` | REPL stdout | **Real**: instrumentation plugin emits after checking dynamic instruction resolution |
| `final_answer` text | Fixture JSON | **Scripted**: fixture provides the exact `set_model_response` content |
| REPL code content | Fixture JSON | **Scripted**: fixture provides the exact `execute_code` args |
| `finding_A_summary`, `finding_B_summary` | Fixture JSON (but delivered via pipeline) | **Hybrid**: values originate in fixture, but reach root stdout only if `llm_query_batched` dispatch + thread bridge + result return all work |
| `depth2_leaf_ok` | Fixture JSON (but delivered via pipeline) | **Hybrid**: value originates in fixture call_index=2, but reaches root stdout only through the full d=0->d=1->d=2->d=1->d=0 chain |
| SQLite `traces.status='completed'` | SQLite telemetry | **Real**: `SqliteTracingPlugin` writes status based on actual run completion |
| SQLite `max_depth_reached >= 2` | SQLite telemetry | **Real**: computed from `MAX(depth)` across all telemetry rows |
| SQLite `set_model_response` depth distribution | SQLite telemetry | **Real**: `before_tool_callback` records depth from agent object |
| SQLite `session_state_events` at `key_depth > 0` | SQLite telemetry | **Real**: child event re-emission pipeline inserts these rows |

## 7. Bugs Discovered

### BUG-014: Child set_model_response depth=0 (Real Bug)

**File**: `/home/rawley-stanhope/dev/rlm-adk/issues/014_child_set_model_response_depth_zero.md`

`SqliteTracingPlugin.before_tool_callback` resolves depth via `getattr(tool, "_depth", 0)`. The `_depth` attribute is only set on `REPLTool` instances; ADK's internal `SetModelResponseTool` has no such attribute, so `getattr` falls through to the default `0`. This causes all child `set_model_response` tool_call rows to report `depth=0` regardless of the actual agent depth. The fix is to read `agent._rlm_depth` from the invocation context (the same pattern used by `before_model_callback`, which gets depth correct). `TestSetModelResponseDepth` is the regression test for this bug.

### Issue 015: Child state events value_text NULL (Not a Bug)

**File**: `/home/rawley-stanhope/dev/rlm-adk/issues/015_child_state_events_value_text_null.md`

Querying `value_text` from `session_state_events` for child state keys like `current_depth` and `iteration_count` returns NULL. This is **not a serialization bug** -- it is expected behavior of the type-discriminated column layout. Integer values are stored in `value_int`, booleans in `value_int` (as 0/1), and only strings go to `value_text`. The `_typed_value()` function works correctly. The fix is a query-layer convenience (e.g., a SQL view with `COALESCE`) rather than a pipeline change.

## 8. Running the Test

```bash
# Run all 8 test classes (18+ assertions)
.venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py -v -m "provider_fake"

# Run a single test class
.venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py::TestBatchedDispatch -v

# Run with full output on failure
.venv/bin/python -m pytest tests_rlm_adk/test_skill_arch_e2e.py -v -m "provider_fake" --tb=long -s
```

The test uses a `run_result` fixture (module-scoped via `tmp_path`) that runs the fixture once and shares the result across all test classes. Total runtime is typically under 5 seconds with the provider-fake backend.

## 9. Files Involved

| File | Role |
|---|---|
| `tests_rlm_adk/test_skill_arch_e2e.py` | Test module: 8 test classes, 18+ assertions |
| `tests_rlm_adk/fixtures/provider_fake/skill_arch_test.json` | Fixture: 8 scripted model responses defining the call sequence |
| `rlm_adk/skills/test_skill/skill.py` | Test skill: `run_test_skill()` function exercising thread bridge + child dispatch |
| `tests_rlm_adk/provider_fake/expected_lineage.py` | Lineage assertions: `build_skill_arch_test_lineage()` defines 40+ expectations across 7 categories |
| `tests_rlm_adk/provider_fake/instrumented_runner.py` | Test runner: `run_fixture_contract_instrumented()` runs fixture through full pipeline with plugins |
| `tests_rlm_adk/provider_fake/stdout_parser.py` | Stdout parser: `parse_stdout()` extracts tagged values from combined REPL/instrumentation output |
| `tests_rlm_adk/provider_fake/conftest.py` | Provides `FIXTURE_DIR` path constant |
| `rlm_adk/plugins/sqlite_tracing.py` | SQLite telemetry plugin: writes `traces`, `telemetry`, `session_state_events` tables |
| `rlm_adk/tools/repl_tool.py` | REPLTool: `execute_code` tool, injects `_rlm_state`, increments `iteration_count` |
| `rlm_adk/dispatch.py` | Worker dispatch: `llm_query` / `llm_query_batched` closures, child event re-emission queue |
| `rlm_adk/orchestrator.py` | Orchestrator: delegates to reasoning agent, drains child event queue, yields state deltas |
| `rlm_adk/repl/thread_bridge.py` | Thread bridge: `run_coroutine_threadsafe` sync wrappers for `llm_query` from REPL threads |
| `rlm_adk/skills/loader.py` | Skill loader: discovers test_skill module, wraps with `llm_query_fn` injection |
| `rlm_adk/state.py` | State keys: `depth_key()`, `parse_depth_key()`, `DEPTH_SCOPED_KEYS`, `EXPOSED_STATE_KEYS` |
| `rlm_adk/utils/prompts.py` | Dynamic instruction: placeholder resolution for `{repo_url?}`, `{skill_instruction?}`, etc. |
| `issues/014_child_set_model_response_depth_zero.md` | BUG-014 documentation: depth=0 for child set_model_response tool_call rows |
| `issues/015_child_state_events_value_text_null.md` | Issue 015 documentation: value_text NULL for int/bool state keys (not a bug) |
| `issues/test_skill/plan_implementation.md` | Implementation plan: Section 1 call sequence, fixture design, test structure |
