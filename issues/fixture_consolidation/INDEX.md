# Fixture Consolidation Index

## Legend
- `[ ]` = pending analysis
- `[x]` = analyzed, SUBSUMED → deleted
- `[~]` = analyzed, KEPT (error path or unique feature)
- `[d]` = already excluded (in _WORKER_FIXTURE_EXCLUSIONS)
- `[s]` = special (index, comprehensive fixture itself)

## Already Excluded (`_WORKER_FIXTURE_EXCLUSIONS`)

| Status | Fixture | Classification | Reason |
|--------|---------|---------------|--------|
| [d] | all_workers_fail_batch | ALREADY_EXCLUDED | Worker-only fixture |
| [d] | worker_429_mid_batch | ALREADY_EXCLUDED | Worker-only fixture |
| [d] | worker_500_retry_exhausted | ALREADY_EXCLUDED | Worker-only fixture |
| [d] | worker_500_retry_exhausted_naive | ALREADY_EXCLUDED | Worker-only fixture |
| [d] | worker_empty_response | ALREADY_EXCLUDED | Worker-only fixture |
| [d] | worker_empty_response_finish_reason | ALREADY_EXCLUDED | Worker-only fixture |
| [d] | worker_safety_finish | ALREADY_EXCLUDED | Worker-only fixture |
| [d] | skill_toolset_discovery | ALREADY_EXCLUDED | Skill fixture, dedicated tests |
| [d] | skill_recursive_ping_e2e | ALREADY_EXCLUDED | Skill fixture, dedicated tests |
| [d] | skill_thread_bridge | ALREADY_EXCLUDED | Skill fixture, dedicated tests |
| [d] | adaptive_confidence_gating | ALREADY_EXCLUDED | Thread-bridge-incompatible |
| [d] | deterministic_guardrails | ALREADY_EXCLUDED | Thread-bridge-incompatible |
| [d] | full_pipeline | ALREADY_EXCLUDED | Thread-bridge-incompatible |
| [d] | structured_control_plane | ALREADY_EXCLUDED | Thread-bridge-incompatible |
| [d] | fake_polya_t4_debate | ALREADY_EXCLUDED | Thread-bridge-incompatible |

## Special

| Status | Fixture | Classification | Reason |
|--------|---------|---------------|--------|
| [s] | index | SPECIAL | Not a fixture |
| [s] | skill_arch_test | SPECIAL | The comprehensive fixture itself |

## Error Path / Fault Injection (KEEP)

| Status | Fixture | Classification | Reason |
|--------|---------|---------------|--------|
| [~] | empty_reasoning_output | ERROR_PATH | Empty output handling |
| [~] | empty_reasoning_output_safety | ERROR_PATH | Safety stop on empty |
| [~] | fault_429_then_success | ERROR_PATH | Rate limit retry |
| [~] | max_iterations_exceeded | ERROR_PATH | Iteration limit |
| [~] | max_iterations_exceeded_persistent | ERROR_PATH | Persistent iteration limit |
| [~] | reasoning_safety_finish | ERROR_PATH | Safety stop |
| [~] | repl_cancelled_during_async | ERROR_PATH | Async cancellation |
| [~] | repl_error_then_retry | ERROR_PATH | REPL error recovery |
| [~] | repl_exception_then_retry | ERROR_PATH | Exception recovery |
| [~] | repl_runtime_error | ERROR_PATH | Runtime error |
| [~] | repl_runtime_error_partial_state | ERROR_PATH | Partial state on error |
| [~] | repl_syntax_error | ERROR_PATH | Syntax error handling |
| [~] | structured_output_retry_empty | ERROR_PATH | Empty structured output |
| [~] | structured_output_retry_exhaustion | ERROR_PATH | Retry exhaustion |
| [~] | structured_output_retry_exhaustion_pure_validation | ERROR_PATH | Pure validation exhaustion |
| [~] | structured_output_retry_validation | ERROR_PATH | Validation retry |
| [~] | worker_500_then_success | ERROR_PATH | Worker retry success |
| [~] | worker_auth_error_401 | ERROR_PATH | Auth error |
| [~] | worker_malformed_json | ERROR_PATH | Malformed JSON |
| [~] | worker_max_tokens_naive | ERROR_PATH | Token truncation |
| [~] | worker_max_tokens_truncated | ERROR_PATH | Token truncation |
| [~] | structured_output_batched_k3 | ERROR_PATH | Batched structured k=3 |
| [~] | structured_output_batched_k3_mixed_exhaust | ERROR_PATH | Mixed exhaust k=3 |
| [~] | structured_output_batched_k3_multi_retry | ERROR_PATH | Multi retry k=3 |
| [~] | structured_output_batched_k3_with_retry | ERROR_PATH | With retry k=3 |

## Analyzed — SUBSUMED (deleted)

| Status | Fixture | Reason |
|--------|---------|--------|
| [x] | happy_path_single_iteration | Single-response FINAL, no tools exercised |
| [x] | multi_iteration_with_workers | 1-depth 1-worker, subset of skill_arch_test |
| [x] | hierarchical_summarization | llm_query_batched + llm_query, old FINAL() protocol |
| [x] | polymorphic_dag_routing | DAG routing is REPL-side Python, old FINAL() protocol |
| [x] | sliding_window_chunking | Repeated llm_query_batched, old FINAL() protocol |
| [x] | exec_sandbox_codegen | execute_code + llm_query + cross-turn, fully covered |
| [x] | user_context_preseeded | user_ctx injection covered by skill_arch_test DYN_INSTR |
| [x] | battlefield_report_telemetry | Pure local REPL computation, no dispatch |
| [x] | custom_metadata_experiment | llm_query_batched K=2, subset of skill_arch_test |
| [x] | structured_output_batched_k1 | K=1 degenerate subset of K=2 batched path |
| [x] | multi_turn_repl_session | Cross-turn REPL + batched dispatch, fully covered |
| [x] | request_body_comprehensive | Dynamic context injection, no dedicated test file |
| [x] | request_body_roundtrip | Request validation, only referenced by demo script |

## Analyzed — KEPT (have dedicated test references)

| Status | Fixture | Reason |
|--------|---------|--------|
| [~] | instruction_router_fanout | Referenced by test_state_accuracy_diagnostic.py |
| [~] | repl_state_introspection | Referenced by test_repl_state_snapshot.py |
| [~] | dashboard_telemetry_completeness | Referenced by test_dashboard_telemetry.py |
| [~] | structured_output_happy_path | Unique output_schema feature not in skill_arch_test |
| [~] | fake_recursive_ping | Referenced by 4 test files |
| [~] | lineage_completion_planes | Referenced by test_telemetry_lineage_columns.py |
