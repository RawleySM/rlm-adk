# Pólya Understand Phase — Complete Deliverable

## 1. Problem Restatement

Define, from first principles, the minimum fixture that exercises **every non-error-stopping execution path** through the RLM-ADK reasoning agent's 4 tools across multiple iterations and depth=2, with full observability assertion coverage. Then determine which existing fixtures are subsumed by it and can be deleted.

## 2. Exact Objective

Produce:
- (a) A specification of what `skill_arch_test.json` must contain (response sequence + expected assertions)
- (b) A looping command (`loop_test_trim.md`) that processes existing fixtures, confirms they're subsumed, deletes them, and updates pytest references
- (c) A categorized list of fixtures that CANNOT be absorbed (error-stopping fixtures)

## 3. Knowns / Givens (from code exploration)

### The 4 tools and their observable side-effects

| Tool | State Keys Written | Telemetry Columns | Artifacts |
|---|---|---|---|
| `execute_code` | REPL_SUBMITTED_CODE, _CHARS, _HASH, _PREVIEW, ITERATION_COUNT, LAST_REPL_RESULT (all depth-scoped) | tool_call row: repl_has_errors, repl_has_output, repl_llm_calls, repl_stdout, execution_mode | repl_code_d{D}_f{F}_iter_{N}.py |
| `set_model_response` | output_key (reasoning_output@dN), agent attrs (_structured_result, _rlm_terminal_completion) | tool_call row: decision_mode="set_model_response", terminal_completion, validated_output_json | None |
| `list_skills` | None | tool_call row: decision_mode="list_skills" | None |
| `load_skill` | None | tool_call row: decision_mode="load_skill", skill_name_loaded, skill_instructions_len | None |

### Cross-cutting observables

- **Depth-scoped state isolation**: keys suffixed with `@dN`
- **Child event re-emission**: curated state deltas via asyncio.Queue, tagged `rlm_child_event=True`
- **Lineage envelope**: custom_metadata["rlm"] on every LLM response
- **SQLite tables**: traces (1 row/invocation), telemetry (1 row/model+tool call), session_state_events (1 row/curated state delta)
- **REPL globals**: _rlm_state snapshot, user_ctx, llm_query, llm_query_batched, LLMResult, skill functions
- **Thread bridge**: execution_mode="thread_bridge", worker thread detection

### Test harness fidelity

Uses `create_rlm_runner()` — **same factory as production**. Only difference is FakeGeminiServer via env var. Drift risk: LOW.

## 4. The Execution Graph (Pólya Step 6: externalize the structure)

Every possible non-error-stopping path through the system:

```
Reasoning Agent (depth=0)
├── list_skills()           → L1 discovery (skill names + descriptions)
├── load_skill(name)        → L2 discovery (full instructions)
├── execute_code(code)      → REPL execution
│   ├── Pure Python (no dispatch)
│   ├── llm_query(prompt)   → single child dispatch
│   │   └── Child (depth=1)
│   │       ├── list_skills()       → L1 discovery at d1
│   │       ├── load_skill(name)    → L2 discovery at d1
│   │       ├── execute_code → child REPL
│   │       │   └── llm_query(prompt) → grandchild dispatch
│   │       │       └── Grandchild (depth=2)
│   │       │           ├── list_skills()       → L1 discovery at d2
│   │       │           ├── load_skill(name)    → L2 discovery at d2
│   │       │           ├── execute_code → d2 REPL (state verification)
│   │       │           └── set_model_response → return to child
│   │       └── set_model_response → return to parent REPL
│   ├── llm_query_batched([p1,p2]) → parallel children
│   │   ├── Child-0 (depth=1, fanout=0) → set_model_response
│   │   └── Child-1 (depth=1, fanout=1) → set_model_response
│   └── skill_fn(llm_query_fn=..., llm_query_batched_fn=...) → skill wrapping dispatch
└── set_model_response(final_answer, reasoning_summary) → terminate
```

**By the depth=2 induction principle**: if this graph works at depth 2, it works at depth N.

## 5. Updated Success Criterion

> `skill_arch_test.json` exercises all 4 tools at depth 0-2, REPL function imports (`llm_query`, `llm_query_batched`, `skill_fn` wrapping `llm_query`, and `skill_fn` wrapping `llm_query_batched`) at depth 0-2, and state key injection into `llm_request` through dynamic instruction param for depths 0-2.

## 6. Capability Matrix (pre-gap-closure snapshot)

| Capability | Depth 0 | Depth 1 | Depth 2 | Gap? |
|---|---|---|---|---|
| `execute_code` | **YES** | **YES** | **YES** | No |
| `set_model_response` | **YES** | **YES** | **YES** | No |
| `list_skills` | **YES** | **NO** | **NO** | **GAP-A** |
| `load_skill` | **YES** | **NO** | **NO** | **GAP-A** |
| REPL `llm_query` | **YES** | **YES** | **YES** | No |
| REPL `llm_query_batched` | **YES** | **YES** | **YES** | No |
| `skill_fn(llm_query_fn=...)` | **YES** | **NO** | **NO** | **GAP-B** |
| `skill_fn(llm_query_batched_fn=...)` | **NO** | **NO** | **NO** | **GAP-C** |
| Dynamic instruction w/ state keys | **YES** | **NO** | **NO** | **GAP-D** |

## 7. Four Implementation Gaps (all CLOSED as of Phase 1)

**GAP-A: Children don't get SkillToolset**
- Root cause: `create_child_orchestrator()` (agent.py:329) had no `enabled_skills` parameter
- **Fix**: Propagated `enabled_skills` through `create_child_orchestrator()` → `create_dispatch_closures()` → child orchestrator
- **Status**: CLOSED (Commit 2, Phase 1)

**GAP-B: Children don't get skill REPL globals**
- **Status**: ALREADY CLOSED — `() or None` evaluates to `None`, and `discover_skill_dirs(None)` returns ALL skills. Confirmed by existing test `test_children_get_repl_globals_unconditionally`.

**GAP-C: Skill functions can't use `llm_query_batched`**
- Root cause: `_wrap_with_llm_query_injection()` (loader.py:70-96) only injected `llm_query_fn`
- **Fix**: Extended wrapper to also inject `llm_query_batched_fn`. Added param to `run_test_skill()`. Updated collect guard.
- **Status**: CLOSED (Commit 1, Phase 1)

**GAP-D: Children don't get dynamic instruction template resolution**
- Root cause: `repo_url` not propagated to children. `RLM_CHILD_STATIC_INSTRUCTION` missing skill tools section.
- **Narrower than expected**: Children already got `RLM_DYNAMIC_INSTRUCTION` as default param. Only `repo_url` propagation was missing. `user_ctx_manifest` intentionally NOT propagated (children scope via prompt).
- **Fix**: Propagated `repo_url` through dispatch chain. Added skill tools section to child static instruction.
- **Status**: CLOSED (Commit 3, Phase 1)

## 8. Constraints

- **Runtime cap**: ~20 seconds for the comprehensive fixture
- **AR-CRIT-001**: No `ctx.session.state[key] = value` in dispatch closures
- **Depth=2 sufficiency**: No need to go deeper
- **~15 fake-provider calls**: Well within runtime budget
- **Single deterministic run**: All responses scripted, no randomness
- **FIFO ordering**: FakeGeminiServer uses sequential response pointer; depth-first blocking via thread bridge makes single-chain ordering deterministic; batch children kept simple to avoid non-deterministic interleaving

## 9. Facts vs Assumptions

**Facts:**
- 4 tools are the complete action space
- Test harness uses same `create_rlm_runner()` as production (low drift)
- Depth-scoped keys use `@dN` suffix
- 3 SQLite tables capture all telemetry
- Current skill_arch_test.json has 8 responses, does NOT exercise list_skills or load_skill
- GAP-B was already closed (children get all skill REPL globals unconditionally)
- Children already receive `RLM_DYNAMIC_INSTRUCTION` as default (GAP-D narrower than expected)

**Assumptions:**
- Existing fixtures' assertions are mostly redundant with each other (verified per-fixture during Phase 3)
- 15 response turns is sufficient for full coverage
- No fixture exercises a path that can't be reached from the 4-tool × 3-depth graph above
- user_ctx_manifest non-propagation to children is the correct design choice

## 10. What Stays as Separate Fixtures (error-stopping)

These fixtures assert **pre-completion stop conditions** and cannot be absorbed:

| Fixture | Stop Condition |
|---|---|
| `max_iterations_exceeded.json` | Iteration limit enforced |
| `max_iterations_exceeded_persistent.json` | Persistent iteration limit |
| `all_workers_fail_batch.json` | All children fail |
| `worker_500_retry_exhausted.json` / `_naive.json` | Worker retry exhaustion |
| `worker_auth_error_401.json` | Auth failure |
| `structured_output_retry_exhaustion.json` / `_pure_validation.json` | Schema validation exhaustion |
| `worker_safety_finish.json` | Safety stop |
| `reasoning_safety_finish.json` | Safety stop |
| `worker_max_tokens_truncated.json` / `_naive.json` | Token truncation |
| `worker_empty_response.json` / `_finish_reason.json` | Empty response handling |
| `worker_malformed_json.json` | JSON parse error |
| `empty_reasoning_output.json` / `_safety.json` | Empty output handling |

## 11. What CAN Be Absorbed (run-to-completion fixtures)

These fixtures exercise paths that the comprehensive fixture subsumes:

| Fixture | What It Tests | Subsumed By |
|---|---|---|
| `happy_path_single_iteration.json` | Basic execute_code → set_model_response | T3+T5 |
| `multi_iteration_with_workers.json` | Multiple iterations + child dispatch | T3+T4 |
| `user_context_preseeded.json` | user_ctx injection | T3 (user_ctx read) |
| `hierarchical_summarization.json` | Multi-level dispatch | T3 (depth=2 chain) |
| `sliding_window_chunking.json` | Multi-turn REPL | T3+T4 (cross-turn) |
| `custom_metadata_experiment.json` | Metadata tracking | Lineage assertions |
| `exec_sandbox_codegen.json` | REPL execution | T3+T4 |
| `repl_state_introspection.json` | _rlm_state reading | T3 |
| `full_pipeline.json` | End-to-end | Entire fixture |
| `skill_thread_bridge.json` | Thread bridge dispatch | T3 |
| `skill_recursive_ping_e2e.json` | Recursive dispatch | T3 (depth chain) |
| `skill_toolset_discovery.json` | list_skills + load_skill | T1+T2 |
| `structured_output_happy_path.json` | Validated output | T5 |
| `structured_output_batched_k1.json` | Batched structured output | T4 |
| `instruction_router_fanout.json` | Skill instruction routing | T1+T2+T3 |
| `polymorphic_dag_routing.json` | DAG dispatch | T3+T4 |
| `request_body_roundtrip.json` | Request validation | Implicit |
| `dashboard_telemetry_completeness.json` | Telemetry assertions | SQLite assertions |
| `battlefield_report_telemetry.json` | Telemetry assertions | SQLite assertions |

## 12. Revised Minimum Response Sequence

| Turn | Depth | Tool | What It Exercises |
|---|---|---|---|
| T1 | 0 | `list_skills` | L1 discovery at root |
| T2 | 0 | `load_skill("test-skill")` | L2 discovery at root |
| T3 | 0 | `execute_code` | Skill fn w/ `llm_query_fn` dispatches child at d1. Child exercises full tool set: |
| T3.1 | 1 | `list_skills` | L1 discovery at depth 1 |
| T3.2 | 1 | `load_skill("test-skill")` | L2 discovery at depth 1 |
| T3.3 | 1 | `execute_code` | Skill fn dispatches grandchild at d2. Grandchild exercises: |
| T3.3.1 | 2 | `list_skills` | L1 discovery at depth 2 |
| T3.3.2 | 2 | `load_skill("test-skill")` | L2 discovery at depth 2 |
| T3.3.3 | 2 | `execute_code` | Reads `_rlm_state`, verifies dynamic instruction state keys, prints verification |
| T3.3.4 | 2 | `set_model_response` | Leaf return |
| T3.4 | 1 | `set_model_response` | Mid-chain return |
| T4 | 0 | `execute_code` | Skill fn w/ `llm_query_batched_fn` dispatches 2 children. Cross-turn REPL persistence. |
| T4.1 | 1 | `set_model_response` | Batch child 0 return |
| T4.2 | 1 | `set_model_response` | Batch child 1 return |
| T5 | 0 | `set_model_response` | Final answer, terminal completion |

**~15 fake-provider responses** — well within 20-second runtime budget.

## 13. What This Asserts At Each Depth

| Observable | d0 | d1 | d2 |
|---|---|---|---|
| `list_skills` returns skills | **assert** | **assert** | **assert** |
| `load_skill` returns instructions | **assert** | **assert** | **assert** |
| `execute_code` writes state keys | **assert** | **assert** | **assert** |
| `set_model_response` terminates | **assert** | **assert** | **assert** |
| `llm_query` dispatches child | **assert** | **assert** | N/A (leaf) |
| `llm_query_batched` dispatches K children | **assert** | N/A (batch at d0 only) | N/A (leaf) |
| `skill_fn(llm_query_fn=...)` works | **assert** | **assert** | **assert** |
| `skill_fn(llm_query_batched_fn=...)` works | **assert** | N/A | N/A (leaf) |
| Dynamic instruction state keys resolved | **assert** | **assert** | **assert** |
| Depth-scoped state isolation | **assert** | **assert** | **assert** |
| Child event re-emission | N/A | **assert** | **assert** |
| Lineage envelope | **assert** | **assert** | **assert** |

## 14. Problem Type

**Test consolidation via coverage-matrix-driven fixture design** — not migration, but top-down redefinition followed by equivalence verification and deletion.

## 15. Well-Posedness Judgment

**Well-posed.** The execution graph is finite (4 tools × depth ≤ 2), the observable side-effects are fully inventoried (state keys, SQLite tables, stdout patterns, artifacts, event metadata), and the FakeGeminiServer's FIFO ordering makes the fixture deterministic. The depth=2 induction principle bounds the problem.

## 16. Operational Problem Statement

> Given the finite execution graph of 4 tools × depth ≤ 2, design a single fixture response sequence (~15 turns) that exercises every reachable non-error-stopping code path. Define the corresponding assertion set (state keys + SQLite queries + stdout patterns). Then, for each existing fixture, determine whether its unique coverage is subsumed; if so, delete the fixture and its pytest references. Track progress in an index file. Execute via a looping command with analyzer → merger → verifier → recorder agents.

## 17. Free-Threaded Python Assessment

**Verdict: Do not pursue.** The bottleneck is not the GIL:
- **~40% of wall time**: Python import overhead (10.4s). Free-threaded Python makes imports 5-10% *slower*.
- **~55% of wall time**: Async event loop dispatch, mock HTTP, SQLite I/O. All I/O-bound. GIL irrelevant.
- **~5% of wall time**: Actual Python CPU work. Trivial.

**What would actually help:** lazy imports of heavy deps, pytest-xdist (`-n auto`), fixture caching.
