<!-- generated: 2026-03-19 -->
<!-- source: voice transcription via voice-to-prompt skill -->
<!-- classification: UPDATE -->
# Lineage Control Plane Refactor: Issue Review, Dead Code Removal, and Ground-Up E2E Verification

## Context

The codebase has accumulated dead code, legacy abstractions, and session-state-as-telemetry-bus patterns that contradict the three-plane architecture described in the refactor plan (`prompts/lineage_control_plane_REFACTOR.md`). Twelve issue files in `issues/rlm_adk/` and `issues/tests_rlm_adk/` document specific dead code, wrong-type assumptions, unused functions, and stale telemetry paths across the core modules. This prompt delegates agent teams to (1) confirm each issue against the codebase, (2) close gaps and remove dead code, and (3) build entirely new e2e provider-fake test fixtures and driver scripts that verify state keys, lineage, and telemetry planes are reading and writing values correctly through `execute_code` and `set_model_response` tool calls at different layer depths and fanout instances over different iterations. Backward compatibility is explicitly not a goal. Existing tests may break and should not be relied on as correctness oracles.

## Original Transcription

> Please delegate agent teams to first review @prompts/lineage_control_plane_REFACTOR.md and the to review the issues uncovered in @issues/rlm_adk/. For each delegated set of issues, spawn reviewer teammate to inspect the issue claim against the codebase, and if in agreement, proceed with a gap-closer and dead-code-remover teammates to make the changes. Remember, I am not interested in backwards comptability. Stuff will break, and we should not rely on our current tests to fix then, but rather build new e2e provider-fake json fixtures and driver python scripts that register the proper plugins, session and file services, and start verifying the ground up that our state keys, lineage and telemetry planes are reading and writing values as they would be intended though execute_code and set_model_response tool calls at different layer depths and fanout instances over different iterations.

## Refined Instructions

> **Delegation:** Assign each numbered step below to an Agent Team teammate. Each teammate implements their step using red/green TDD and documents the change with a demo via `uvx showboat --help`.

**Important constraints that apply to all teammates:**

- Backward compatibility is NOT a goal. Breaking changes are expected and acceptable.
- Do NOT rely on existing tests as correctness oracles. Build new fixtures and driver scripts from scratch.
- All state mutations must comply with AR-CRIT-001 (never `ctx.session.state[key] = value` in dispatch closures).
- Read `prompts/lineage_control_plane_REFACTOR.md` `prompts/lineage_control_plane_WORKFLOW_v2.md`and before starting any implementation work to understand the three-plane split (state/lineage/completion).


---

### Phase 1: Review and Confirm Issues

1. **Spawn a `State-Reviewer` teammate to inspect all claims in `issues/rlm_adk/state.py.md` against `rlm_adk/state.py`.**
   - Confirm that `FINAL_ANSWER` (L23), old reasoning/lineage constants (L23-30, L69-73), and `child_obs_key()` (L123-125) are dead or misaligned with the refactor plan.
   - Confirm that BUG-13 and cumulative child dispatch key comments (L95-108) use stale vocabulary.
   - Record which constants are still imported/used across the codebase (grep all `from rlm_adk.state import` sites).

2. **Spawn a `Types-Reviewer` teammate to inspect all claims in `issues/rlm_adk/types.py.md` against `rlm_adk/types.py`.**
   - Confirm that `ReasoningObservability` (L29) and `parse_reasoning_output()` (L41) are legacy completion-era abstractions with no live callers outside the orchestrator's backward-compat path.
   - Confirm that `render_completion_text()` (L316) uses `json.dumps` without `separators=(",", ":")` for compact output.
   - Trace all import sites for these symbols.

3. **Spawn a `Dispatch-Reviewer` teammate to inspect all claims in `issues/rlm_adk/dispatch.py.md` against `rlm_adk/dispatch.py`.**
   - Confirm that child completion normalization (L286-292, L336-345, L553-565) still assumes structured results are dicts.
   - Confirm that accumulator and per-child summary machinery (L194-207, L657-739, L883-892) is alive but never emitted to consumers.
   - Confirm that `_read_child_completion()` (L258) still mines nested obs from child state (L304-333, L347-376, L404-473).
   - Confirm that `_serialize_child_payload()` (L247) is unused dead code.
   - Confirm that `child_obs_key()`-driven child summary construction (L657-739) is dead baggage.

4. **Spawn an `Orchestrator-Reviewer` teammate to inspect all claims in `issues/rlm_adk/orchestrator.py.md` against `rlm_adk/orchestrator.py`.**
   - Confirm that `_collect_completion()` (L139) treats validated structured output as dict-only (L188-194, L218-234).
   - Confirm that the root reasoning agent drops schema name on default `ReasoningOutput` path (L361-381).
   - Confirm that the orchestrator still seeds cumulative child-dispatch totals that dispatch no longer updates (L405-409).
   - Confirm that `_serialize_completion_payload()` (L96) is unused dead code.

5. **Spawn a `Callbacks-Reviewer` teammate to inspect all claims in `issues/rlm_adk/callbacks/reasoning.py.md` and `issues/rlm_adk/callbacks/worker_retry.py.md`.**
   - In `rlm_adk/callbacks/reasoning.py`: confirm that `request_meta` still carries `context_window_snapshot` payload (L172-187), that `_reasoning_depth()` (L81) is redundant with `_agent_runtime()` and `_build_lineage()` (L95-118).
   - In `rlm_adk/callbacks/worker_retry.py`: confirm that successful `set_model_response` only creates `_rlm_terminal_completion` when `tool_response` is dict (L166-197), and that the file mixes direct attribute assignment with `object.__setattr__()` discipline (L49, L175).

6. **Spawn a `Plugins-Reviewer` teammate to inspect all claims in `issues/rlm_adk/plugins/observability.py.md` and `issues/rlm_adk/plugins/sqlite_tracing.py.md`.**
   - In `rlm_adk/plugins/observability.py`: confirm that the plugin still uses session state as telemetry bus with re-persist workaround (L72-111, L129-188), that `reasoning_before_model()` publishes `_rlm_pending_request_meta` but the plugin never consumes it, and that `_SUMMARY_COUNTER_KEYS` (L75) plus repersistence loop (L91-98) are legacy.
   - In `rlm_adk/plugins/sqlite_tracing.py`: confirm that `after_run_callback()` (L738) builds trace summary from state `obs:*` keys not telemetry rows (L742-850), that `_CURATED_PREFIXES` (L113) still captures broad `obs:*` into `session_state_events`, that `after_model_callback()` stores `custom_metadata` but doesn't project into dedicated columns (L1058-1100), that tool-call telemetry omits full lineage scope (L1170-1204), and that `validated_output_json` is written from generic result so retry payloads can be persisted as validated (L1264-1280).

7. **Spawn a `REPLTool-Reviewer` teammate to inspect the claim in `issues/rlm_adk/tools/repl_tool.py.md` against `rlm_adk/tools/repl_tool.py`.**
   - Confirm that `last_repl_result.total_llm_calls` is hardcoded to 0 on L258, L288, and L313.
   - Trace where `total_llm_calls` is consumed downstream and determine if it would affect telemetry correctness.

---

### Phase 2: Dead Code Removal and Gap Closing

For each confirmed issue from Phase 1, proceed with the following teammates. Each teammate should make changes on a dedicated branch, document what was removed/changed, and verify the module still imports and lints cleanly (`ruff check rlm_adk/`).

8. **Spawn a `State-Cleaner` teammate to remove dead exports and rename stale keys in `rlm_adk/state.py`.**
   - Remove or deprecate-with-tombstone: old reasoning/lineage state constants that the refactor plan marks for lineage-plane-only (see refactor plan Section 2).
   - Remove `child_obs_key()` if Phase 1 confirms no live callers outside dead dispatch code.
   - Rename `FINAL_ANSWER` to `FINAL_RESPONSE_TEXT` everywhere (the refactor plan explicitly requests this).
   - Clean up BUG-13 and cumulative child dispatch key comments to use current vocabulary.
   - Update `EXPOSED_STATE_KEYS` (L167) to match the refactor plan's recommended set: `ITERATION_COUNT`, `CURRENT_DEPTH`, `APP_MAX_ITERATIONS`, `APP_MAX_DEPTH`, `SHOULD_STOP`, `LAST_REPL_RESULT`, `REPL_SUBMITTED_CODE_CHARS`.
   - Update all import sites across the codebase that reference removed/renamed symbols.

9. **Spawn a `Types-Cleaner` teammate to remove legacy abstractions from `rlm_adk/types.py`.**
   - Remove `ReasoningObservability` (L29) and `parse_reasoning_output()` (L41) if Phase 1 confirms they can be deleted.
   - Fix `render_completion_text()` (L316) to use `json.dumps(obj, separators=(",", ":"))` for compact output.
   - Update all import sites that reference removed symbols.

10. **Spawn a `Dispatch-Cleaner` teammate to remove dead machinery from `rlm_adk/dispatch.py`.**
    - Delete `_serialize_child_payload()` (L247) -- confirmed unused.
    - Delete `child_obs_key()`-driven child summary construction block (L657-739).
    - Delete `_acc_child_summaries` and its associated write sites (L199, L657).
    - Fix child completion normalization to handle non-dict structured results (support `BaseModel`, list-of-dict, string).
    - Simplify `_read_child_completion()` (L258) to use the priority chain from refactor plan Section 10: `_rlm_terminal_completion` -> `_structured_result` -> `output_key` -> error. Stop mining child state for obs keys.
    - Reduce whatever remains of the flush mechanism to a minimal post-dispatch state patcher (restore parent `DYN_SKILL_INSTRUCTION` only). Remove its role as a telemetry transport.

11. **Spawn an `Orchestrator-Cleaner` teammate to remove dead code and fix completion handling in `rlm_adk/orchestrator.py`.**
    - Delete `_serialize_completion_payload()` (L96).
    - Fix `_collect_completion()` (L139) to handle non-dict validated output (BaseModel, list, string) per refactor plan Section 5.
    - Remove cumulative child-dispatch total seeding (L405-409) that dispatch no longer updates.
    - Ensure root completion rendering follows the priority: `final_answer` field -> string output -> compact JSON.

12. **Spawn a `Callbacks-Cleaner` teammate to clean up `rlm_adk/callbacks/reasoning.py` and `rlm_adk/callbacks/worker_retry.py`.**
    - In `reasoning.py`: remove `context_window_snapshot` payload from `request_meta` (L172-187). Consolidate `_reasoning_depth()` if redundant.
    - In `worker_retry.py`: fix `_rlm_terminal_completion` creation to handle non-dict `tool_response` (L166-197). Normalize to consistent `object.__setattr__()` discipline throughout the file.

13. **Spawn a `Plugins-Cleaner` teammate to clean up `rlm_adk/plugins/observability.py` and `rlm_adk/plugins/sqlite_tracing.py`.**
    - In `observability.py`: remove `_SUMMARY_COUNTER_KEYS` (L75) and the repersistence loop (L91-98). Strip out session-state-as-telemetry-bus writes. Keep the plugin only for lightweight run-summary counters if genuinely needed.
    - In `sqlite_tracing.py`: narrow `_CURATED_PREFIXES` (L113) to exclude `obs:*` lineage keys that should come from telemetry rows, not state events. Add lineage columns to the telemetry table schema per refactor plan Section 7 (`fanout_idx`, `parent_depth`, `parent_fanout_idx`, `branch`, `invocation_id`, `session_id`, `output_schema_name`, `decision_mode`, `structured_outcome`, `terminal_completion`, `custom_metadata_json`, `validated_output_json`). Fix `after_run_callback()` (L738) to build trace summary from telemetry rows, not state `obs:*` keys.

14. **Spawn a `REPLTool-Cleaner` teammate to fix the hardcoded zero in `rlm_adk/tools/repl_tool.py`.**
    - Fix `total_llm_calls` on L258, L288, L313 to read the actual count from the REPL execution result or dispatch accumulator.

15. **Spawn an `Agent-Lineage-Fixer` teammate to fix child lineage in `rlm_adk/agent.py`.**
    - Fix `create_child_orchestrator()` (L340) so that `parent_fanout_idx` (L396) is populated from the caller's actual fanout index instead of being hardcoded to `None`.

---

### Phase 3: Ground-Up E2E Verification (New Fixtures and Driver Scripts)

Build entirely new provider-fake JSON fixtures and pytest driver scripts that verify the state, lineage, and telemetry planes from the ground up. Do NOT modify existing fixtures or tests. These new tests are the correctness oracles for the refactored code.

16. **Spawn a `Fixture-Architect` teammate to design the new fixture schema and driver infrastructure.**
    - Create a new test file: `tests_rlm_adk/test_lineage_plane_e2e.py`.
    - The driver must register the full plugin stack (`ObservabilityPlugin`, `SqliteTracingPlugin`, `REPLTracingPlugin`), use `SqliteSessionService` and `FileArtifactService` (no in-memory services), and use `run_fixture_contract_with_plugins()` from `tests_rlm_adk/provider_fake/contract_runner.py` (L360).
    - Each fixture must exercise `execute_code` and `set_model_response` tool calls and assert on the resulting state keys, telemetry rows, and lineage columns.
    - Define a shared helper that opens the SQLite traces DB after a run and queries telemetry rows for assertion.

17. **Spawn a `Depth0-SingleIter-Fixture` teammate to create a fixture for depth-0, single-iteration, single `execute_code` then `set_model_response`.**
    - Fixture: `tests_rlm_adk/fixtures/provider_fake/lineage_depth0_single_iter.json`
    - Verify: state plane contains only approved keys (`ITERATION_COUNT`, `CURRENT_DEPTH`, `SHOULD_STOP`, `LAST_REPL_RESULT`, `FINAL_RESPONSE_TEXT`). Telemetry rows contain `depth=0`, `fanout_idx=0`, `decision_mode` alternates between `execute_code` and `set_model_response`. The final telemetry row has `terminal_completion=1`.

18. **Spawn a `Depth0-MultiIter-Fixture` teammate to create a fixture for depth-0, multi-iteration (3+ `execute_code` calls before `set_model_response`).**
    - Fixture: `tests_rlm_adk/fixtures/provider_fake/lineage_depth0_multi_iter.json`
    - Verify: `ITERATION_COUNT` increments correctly in state. Each `execute_code` telemetry row has `decision_mode="execute_code"` and `terminal_completion=0`. The final `set_model_response` row has `terminal_completion=1`. No stale `obs:*` reasoning keys in session state.

19. **Spawn a `Depth1-ChildDispatch-Fixture` teammate to create a fixture for depth-0 parent dispatching a depth-1 child via `llm_query()` in REPL code.**
    - Fixture: `tests_rlm_adk/fixtures/provider_fake/lineage_depth1_child_dispatch.json`
    - Verify: child telemetry rows have `depth=1`, `parent_depth=0`, `parent_fanout_idx=0`. Parent telemetry rows have `depth=0`. Child `set_model_response` row has `terminal_completion=1`. Parent state does NOT contain depth-scoped child reasoning keys (`@d1` suffixed obs keys should be absent).

20. **Spawn a `Depth1-Fanout-Fixture` teammate to create a fixture for depth-0 parent dispatching multiple depth-1 children via `llm_query_batched()` (fanout k=3).**
    - Fixture: `tests_rlm_adk/fixtures/provider_fake/lineage_depth1_fanout_k3.json`
    - Verify: three sets of child telemetry rows exist, each with `depth=1` and `fanout_idx` in {0, 1, 2}. Each child has `parent_depth=0`, `parent_fanout_idx=0`. No sibling-overwriting of `@d1` mirrored lineage in parent state.

21. **Spawn a `StructuredOutput-Lineage-Fixture` teammate to create a fixture for structured output with retry at depth-1.**
    - Fixture: `tests_rlm_adk/fixtures/provider_fake/lineage_structured_retry.json`
    - Verify: first `set_model_response` call at depth-1 returns invalid output (triggers retry). Second call returns valid output. Telemetry rows show `structured_outcome="retry_requested"` then `structured_outcome="validated"`. The `validated_output_json` column contains only the final validated payload, not the retry payload.

22. **Spawn a `Telemetry-Columns-Assertion` teammate to create a comprehensive assertion test that queries all new lineage columns across all fixtures.**
    - Test file: `tests_rlm_adk/test_lineage_telemetry_columns.py`
    - For each fixture from steps 17-21, assert that every new lineage column (`fanout_idx`, `parent_depth`, `parent_fanout_idx`, `branch`, `output_schema_name`, `decision_mode`, `structured_outcome`, `terminal_completion`, `custom_metadata_json`, `validated_output_json`) is populated with correct values, not NULL or default placeholders.

---

## Provider-Fake Fixture & TDD

**Fixtures:** Six new JSON fixtures in `tests_rlm_adk/fixtures/provider_fake/`:
- `lineage_depth0_single_iter.json`
- `lineage_depth0_multi_iter.json`
- `lineage_depth1_child_dispatch.json`
- `lineage_depth1_fanout_k3.json`
- `lineage_structured_retry.json`
- *(index.json must be updated to register all new fixtures)*

**Essential requirements the fixtures must capture:**
- State plane purity: after a run, session state contains ONLY approved working-state keys. No `obs:*` reasoning lineage, no depth-scoped child mirror keys.
- Telemetry plane correctness: every model call and tool call produces a telemetry row with correct `depth`, `fanout_idx`, `parent_depth`, `parent_fanout_idx`, `decision_mode`, and `terminal_completion`.
- Completion plane correctness: `set_model_response` produces `_rlm_terminal_completion` on the agent for both dict and non-dict validated outputs.
- Cross-depth lineage: parent telemetry rows and child telemetry rows have correct parent/child linkage via `parent_depth` and `parent_fanout_idx`.
- Fanout isolation: sibling children at the same depth do not overwrite each other's telemetry or state.

**TDD sequence:**
1. Red: Write `test_lineage_plane_e2e.py` with test stubs that assert on telemetry columns. Run, confirm failure (columns don't exist yet).
2. Green: Add lineage columns to `sqlite_tracing.py` schema. Run, confirm column-existence tests pass.
3. Red: Write assertions on `decision_mode` and `terminal_completion` values. Run, confirm failure (values not populated yet).
4. Green: Wire `decision_mode` writes into `before_tool_callback`/`after_tool_callback` in `sqlite_tracing.py`. Run, confirm pass.
5. Red: Write assertions on parent/child linkage. Continue for each fixture.

**Demo:** Run `uvx showboat` after each fixture is complete to generate an executable demo document proving the telemetry rows and state keys are correct.

## Considerations

- **AR-CRIT-001**: Any teammate touching `dispatch.py` must not write `ctx.session.state[key] = value` in closures. Use `tool_context.state`, `callback_context.state`, or `EventActions(state_delta={})`.
- **Pydantic model agents**: Setting runtime attrs on agents requires `object.__setattr__()`. Direct attribute assignment raises Pydantic validation errors.
- **BUG-13 monkey-patch**: The `_patch_output_schema_postprocessor()` in `worker_retry.py` is a process-global monkey-patch. Changes to the structured output path must verify BUG-13 suppression still works (test via `_bug13_stats["suppress_count"]` delta).
- **ADK SetModelResponseTool shapes**: Returns dict for `BaseModel`, list-of-dicts for list-of-`BaseModel`, and raw `response` for non-`BaseModel` schemas. Any code that assumes dict-only is a bug.
- **No in-memory services for testing**: Per project conventions, tests must use `SqliteSessionService` and `FileArtifactService`, not `InMemorySessionService` or `InMemoryArtifactService`.
- **Worker observability path**: `ObservabilityPlugin` does NOT fire for workers (they get isolated invocation contexts from `ParallelAgent`). Worker obs flows through `worker_after_model` -> `_call_record` -> dispatch accumulators -> `tool_context.state`.
- **Existing test breakage**: Existing tests in `test_provider_fake_e2e.py`, `test_dashboard_telemetry.py`, `test_repl_state_snapshot.py`, and `test_rlm_state_snapshot_audit.py` will break. This is expected. Do not constrain refactor choices to preserve them.

## Appendix: Code References

| File | Item | Line | Relevance |
|------|------|------|-----------|
| `rlm_adk/state.py` | `FINAL_ANSWER` | L23 | Deprecated constant to rename to `FINAL_RESPONSE_TEXT` |
| `rlm_adk/state.py` | `child_obs_key()` | L123 | Dead helper for removed obs:child_summary transport |
| `rlm_adk/state.py` | `EXPOSED_STATE_KEYS` | L167 | Set to shrink per refactor plan Section 9 |
| `rlm_adk/state.py` | `depth_key()` | L200 | Depth-scoped state key helper (keep) |
| `rlm_adk/types.py` | `ReasoningOutput` | L15 | Root default schema (keep) |
| `rlm_adk/types.py` | `ReasoningObservability` | L29 | Legacy abstraction to remove |
| `rlm_adk/types.py` | `parse_reasoning_output()` | L41 | Legacy parser to remove |
| `rlm_adk/types.py` | `render_completion_text()` | L316 | Fix to use compact JSON separators |
| `rlm_adk/agent.py` | `create_child_orchestrator()` | L340 | Fix `parent_fanout_idx=None` on L396 |
| `rlm_adk/dispatch.py` | `create_dispatch_closures()` | L160 | Dispatch closure factory |
| `rlm_adk/dispatch.py` | `_acc_child_summaries` | L199 | Dead accumulator to remove |
| `rlm_adk/dispatch.py` | `_serialize_child_payload()` | L247 | Unused dead code to delete |
| `rlm_adk/dispatch.py` | `_read_child_completion()` | L258 | Simplify per refactor plan Section 10 |
| `rlm_adk/dispatch.py` | child summary construction | L657-739 | Dead `child_obs_key()` baggage to delete |
| `rlm_adk/orchestrator.py` | `_serialize_completion_payload()` | L96 | Unused dead code to delete |
| `rlm_adk/orchestrator.py` | `_collect_completion()` | L139 | Fix dict-only assumption |
| `rlm_adk/orchestrator.py` | `RLMOrchestratorAgent` | L237 | Collapsed orchestrator class |
| `rlm_adk/orchestrator.py` | `_run_async_impl()` | L270 | Main orchestrator loop |
| `rlm_adk/callbacks/reasoning.py` | `_reasoning_depth()` | L81 | Potentially redundant helper |
| `rlm_adk/callbacks/reasoning.py` | `reasoning_before_model()` | L121 | Remove context_window_snapshot state writes |
| `rlm_adk/callbacks/reasoning.py` | `reasoning_after_model()` | L193 | Stop writing response obs to state |
| `rlm_adk/callbacks/worker_retry.py` | `WorkerRetryPlugin` | L81 | Structured output self-healing |
| `rlm_adk/callbacks/worker_retry.py` | `make_worker_tool_callbacks()` | L124 | After/error callback factory |
| `rlm_adk/callbacks/worker_retry.py` | `_rlm_terminal_completion` | L186, L248 | Fix dict-only creation |
| `rlm_adk/plugins/observability.py` | `ObservabilityPlugin` | L37 | Strip state-as-telemetry-bus writes |
| `rlm_adk/plugins/observability.py` | `_SUMMARY_COUNTER_KEYS` | L75 | Legacy counter set to remove |
| `rlm_adk/plugins/sqlite_tracing.py` | `_CURATED_PREFIXES` | L113 | Narrow to exclude obs:* lineage keys |
| `rlm_adk/plugins/sqlite_tracing.py` | `SqliteTracingPlugin` | L320 | Add lineage columns to schema |
| `rlm_adk/plugins/sqlite_tracing.py` | `after_run_callback()` | L738 | Fix to build summary from telemetry rows |
| `rlm_adk/tools/repl_tool.py` | `REPLTool` | L54 | Tool class |
| `rlm_adk/tools/repl_tool.py` | `run_async()` | L124 | Fix `total_llm_calls` hardcoded to 0 (L258, L288, L313) |
| `tests_rlm_adk/provider_fake/contract_runner.py` | `run_fixture_contract()` | L324 | Base contract runner |
| `tests_rlm_adk/provider_fake/contract_runner.py` | `run_fixture_contract_with_plugins()` | L360 | Plugin-aware contract runner |
| `tests_rlm_adk/provider_fake/server.py` | `FakeGeminiServer` | L25 | Fake Gemini HTTP server |

## Priming References

Before starting implementation, read these in order:
1. `prompts/lineage_control_plane_REFACTOR.md` -- the three-plane refactor plan that motivates all changes
2. `repomix-architecture-flow-compressed.xml` -- compressed source snapshot for structural context
3. `rlm_adk_docs/UNDERSTAND.md` -- documentation entrypoint (follow branch links for Dispatch & State, Observability, Testing, and Core Loop)
4. `issues/rlm_adk/` and `issues/tests_rlm_adk/` -- the issue files being addressed
