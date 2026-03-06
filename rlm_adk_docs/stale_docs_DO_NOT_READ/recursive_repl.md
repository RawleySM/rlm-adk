# Recursive Worker-Orchestrator Cutover Spec

## Objective
Replace worker leaf `LlmAgent` execution with worker `RLMOrchestratorAgent` execution so every worker can perform recursive reasoning and may optionally use `REPLTool`.

Non-negotiable behavior:
- REPL is optional. Child orchestrators may finish without calling `execute_code`.

## Accuracy-Checked Baseline
Findings below are aligned to current code:
- Workers are currently leaf `LlmAgent` instances with mutable carrier fields and callback-driven result extraction (`rlm_adk/dispatch.py:103-146`, `rlm_adk/dispatch.py:368-497`, `rlm_adk/callbacks/worker.py:52-181`).
- Worker events are consumed and dropped in dispatch (`rlm_adk/dispatch.py:216-219`).
- Root orchestrator uses fixed depth assumptions and fixed `reasoning_output` extraction (`rlm_adk/orchestrator.py:110-115`, `rlm_adk/orchestrator.py:174-178`, `rlm_adk/orchestrator.py:255-275`, `rlm_adk/agent.py:219`).
- State is flat for collision-prone keys (`iteration_count`, `last_repl_result`, `request_id`) (`rlm_adk/orchestrator.py:174-178`, `rlm_adk/tools/repl_tool.py:81-84`, `rlm_adk/tools/repl_tool.py:130-185`).
- Observability currently aggregates to shared unsuffixed counters and unsuffixed iteration context (`rlm_adk/plugins/observability.py:152-233`, `rlm_adk/plugins/repl_tracing.py:31-45`).
- Sync REPL execution uses global process lock and non-killable timeout thread semantics (`rlm_adk/repl/local_repl.py:77-81`, `rlm_adk/repl/local_repl.py:324-339`).

## Hard Decisions
1. `WorkerPool` creates orchestrator workers, not leaf workers.
2. Dispatch execution contract is runtime-driven; leaf callback carriers (`_pending_prompt`, `_result_ready`, `_call_record`) leave the primary path.
3. Child state is fully scoped by depth + lineage. Raw flat child writes are invalid.
4. `request_id` is root-only and immutable after first write.
5. Child telemetry is lineage-first; aggregate counters are rollups.
6. `llm_query(..., output_schema=...)` is explicitly unsupported in cutover v1 unless reimplemented in child orchestrator flow.

## Runtime Contract

### Parent -> Child Execution
For each `llm_query_async` / `llm_query_batched_async` call:
1. Parent allocates child scope `{depth, lineage_id, worker_call_id}`.
2. Parent maps inputs:
   - `prompt` -> child root prompt / initial user content.
   - `model` override -> child reasoning model.
   - `output_schema` -> explicit v1 rejection behavior (below).
3. Parent constructs child orchestrator with scoped output key.
4. Child runs `run_async` and may or may not invoke REPL.
5. Parent consumes child terminal state and maps to `LLMResult`.
6. Parent merges child telemetry into lineage buckets.

### Dispatch Runtime Interface
Replace callback side-channel dependency with runtime interface:
- `start(prompt, ctx, scope) -> Awaitable[None]`
- `result() -> LLMResult`
- `events() -> AsyncIterator[Event]` (optional)
- `teardown(status) -> Awaitable[None]`

### Call-Log and Trace Parity
Cutover must preserve visibility parity currently produced in dispatch:
- `call_log_sink` parity (`RLMChatCompletion`) (`rlm_adk/dispatch.py:499-529`).
- trace/data-flow parity (`rlm_adk/dispatch.py:531-561`).

## State Scoping Contract

### Scope Identity
- `scope_id = d{depth}#{lineage}`
- `scoped_key(base, scope_id) = "{base}@{scope_id}"`

### Keys Required to be Scoped in Child Context
- `iteration_count`
- `last_repl_result`
- `final_answer`
- `should_stop`
- `reasoning_output`
- `message_history`
- worker output artifact keys (including keys currently derived from `worker_<n>_output`)
- child dispatch metrics (`worker_dispatch_count`, worker timeout/rate-limit/error keys)
- reasoning callback accounting keys:
  - `REASONING_PROMPT_CHARS`
  - `REASONING_SYSTEM_CHARS`
  - `REASONING_CONTENT_COUNT`
  - `REASONING_HISTORY_MSG_COUNT`
  - `REASONING_INPUT_TOKENS`
  - `REASONING_OUTPUT_TOKENS`
  - `CONTEXT_WINDOW_SNAPSHOT`
- observability breakdown keys:
  - `OBS_PER_ITERATION_TOKEN_BREAKDOWN`

### Root-Only Keys
- `request_id` (immutable after first write)
- invocation start timestamps

### Required `state.py` additions
- `ORCHESTRATOR_DEPTH`
- `ORCHESTRATOR_LINEAGE_ID`
- `ORCHESTRATOR_RUN_ID`
- `ORCHESTRATOR_PARENT_RUN_ID`
- `ACTIVE_SCOPE_ID`
- `ROOT_REQUEST_ID`
- `scope_id(depth: int, lineage: str) -> str`
- `scoped_key(base: str, scope_id: str) -> str`

### Enforcement Rule
- Child-context writes to raw base keys above must fail (runtime guard + tests).
- Child runtimes execute with state-overlay semantics and commit only through scoped merge.
- Legacy unsuffixed aliases are root-only compatibility outputs and are never authoritative for child reads.

## REPL Behavior in Child Orchestrators
- Child orchestrators include `REPLTool` exactly like root orchestrator.
- Child reasoning decides whether REPL is needed.
- Required validation scenarios:
  - task solved without `execute_code`
  - task solved with one or more `execute_code` calls

## Structured Output Handling (v1)
Current leaf workers support `output_schema` through `SetModelResponseTool` + retry plugin (`rlm_adk/dispatch.py:373-380`, `rlm_adk/callbacks/worker_retry.py:40-134`).

Cutover v1 decision:
- Remove worker `output_schema` support from `llm_query*` orchestrator-worker path.
- `llm_query(..., output_schema=...)` must fail fast with explicit unsupported error.
- Reintroduce schema support later via child-orchestrator-native structured output contract.

## Timing / Threading / Cancellation Contract

### Known Risk Surfaces
- Sync REPL path blocks in tool async flow and uses global `_EXEC_LOCK`.
- Sync timeout cannot terminate active Python execution thread.
- Timeout/release sequence can race with full quiescence.
- On-demand worker growth under pool exhaustion can amplify recursive fanout.
- Dispatch accumulators are closure-scoped today and can smear per-lineage timing under nesting.

### Required Safeguards
1. Child runtime quarantine:
   - any timeout/cancel/error marks runtime non-reusable.
2. Cancel-drain handshake:
   - timeout -> explicit cancel -> bounded await -> teardown.
3. Recursion budget controls:
   - max depth
   - max children per batch
   - max total child calls per parent iteration
4. Timeout budgeting:
   - separate parent call timeout and per-child timeout.
5. REPL critical section:
   - add per-REPL async lock around mutable globals/stdout path for child runs.
6. Accumulator scoping:
   - lineage-bucketed dispatch accumulators, not closure-global.
7. Cancellation contract:
   - v1 preserves current conversion-to-result behavior unless explicitly changed in later migration.
8. Sync lock policy:
   - v1 accepts process-wide serialization under global `_EXEC_LOCK` and tracks throughput impact explicitly.
9. Event-loop safety:
   - recursive mode must not block loop on sync REPL path; tool execution waits must run in thread-offloaded awaits (for example `asyncio.to_thread` / executor await).

## Observability Lineage Contract

### Required Child Fields
- `obs:lineage_id`
- `obs:depth`
- `obs:worker_call_id`
- `obs:parent_request_id`
- `obs:agent_role` (`root_orchestrator`, `recursive_worker`)

### Required State Shape
- `obs:lineage_metrics = {lineage_id: {...}}`
- `obs:lineage_rollup_version`

### Write and Rollup Model
1. Child writes lineage-scoped metrics.
2. Parent merges lineage metrics into invocation summary.
3. Global counters are computed rollups, not child direct writes.
4. Anti-double-count rule: global totals are derived exactly once from lineage buckets.
5. Log correlation: immutable root `request_id` + secondary `lineage_id`.

### Plugin Adjustments
- `rlm_adk/plugins/observability.py`:
  - lineage buckets + explicit rollup pass.
  - stop using child unsuffixed iteration keys as authoritative.
  - replace `after_agent_callback` blind dynamic-prefix rescan with scope-aware lineage merge (`rlm_adk/plugins/observability.py:120-127`).
- `rlm_adk/plugins/repl_tracing.py`:
  - ingest scoped `last_repl_result@scope` snapshots.
  - replace plain iteration indexing with lineage-qualified indexing (`{lineage_id}:{iteration}`).

### Child Event Policy
- Dispatch consumes child events by default.
- Parent emits normalized summary/metric events only in v1 (no raw child event replay).
- Summary envelope schema:
  - `type: "sub_agent_event"`
  - `lineage_id`
  - `depth`
  - `worker_call_id`
  - `phase` (`start`, `complete`, `timeout`, `error`)
  - `payload` (bounded summary fields only)

### Plugin Migration Sequence
1. Implement lineage bucket writes in `observability.py`.
2. Switch rollup computation to lineage-derived totals and disable prefix-blind rescan behavior.
3. Upgrade `repl_tracing.py` to scoped lineage indexing.
4. Remove any remaining reliance on unsuffixed child iteration keys.

## File-Level Implementation

### `rlm_adk/agent.py`
- Parameterize reasoning `output_key`.
- Pass depth/lineage metadata into child orchestrator creation.

### `rlm_adk/orchestrator.py`
- Replace fixed depth assumptions with scope-driven depth.
- Read/write scoped keys in child context.
- Extract terminal output from scoped `output_key`.
- Never overwrite root `request_id` in child context.

### `rlm_adk/dispatch.py`
- Replace leaf callback-carrier loop with orchestrator runtime execution loop.
- Remove leaf schema callback path from v1 cutover flow.
- Add timeout/cancel drain and runtime quarantine.
- Add lineage-scoped accumulator model.

### `rlm_adk/state.py`
- Add lineage/scope keys and helper APIs.
- Add guard utilities for child raw-key write rejection.

### `rlm_adk/tools/repl_tool.py`
- Resolve iteration/result keys from active scope.
- Preserve `flush_fn` writes on success/exception/cancel in scoped form.

### `rlm_adk/plugins/observability.py`
- Implement lineage-first writes + deterministic rollups.

### `rlm_adk/plugins/repl_tracing.py`
- Persist scoped trace summaries keyed by lineage/depth/iteration.

## Red/Green TDD Plan

### Phase 1: RED - Worker Runtime Cutover Contracts
- `tests_rlm_adk/test_recursive_worker_is_orchestrator.py`
  - dispatch worker path instantiates orchestrator workers.
- `tests_rlm_adk/test_recursive_worker_repl_optional.py`
  - child can complete with no REPL call.
  - child can complete with REPL call.
- `tests_rlm_adk/test_recursive_worker_schema_rejected_v1.py`
  - `output_schema` path is explicitly rejected/unsupported in v1.

### Phase 2: GREEN - Core Cutover
- Implement orchestrator-worker runtime path in dispatch.
- Implement scoped output key wiring.

Pass criteria:
- child returns normalized `LLMResult`.
- no leaf callback carrier dependency for cutover path.
- call-log and trace parity tests pass.

### Phase 3: RED - State Collision Defense
- `tests_rlm_adk/test_recursive_state_scoping.py`
  - parent/child `iteration_count` isolation
  - parent/child `last_repl_result` isolation
  - worker output key collision prevention
- `tests_rlm_adk/test_recursive_request_id_immutable.py`
  - child cannot mutate root `request_id`.
- `tests_rlm_adk/test_recursive_raw_key_write_guard.py`
  - child raw key writes fail.

### Phase 4: GREEN - State Guard Implementation
- Add scoped key resolver and write guards.
- Route orchestrator + REPL tool writes through scope-aware key API.

### Phase 5: RED - Timing/Cancellation Hardening
- `tests_rlm_adk/test_recursive_timeout_quarantine.py`
- `tests_rlm_adk/test_recursive_cancel_drain.py`
- `tests_rlm_adk/test_recursive_no_stale_write_after_timeout.py`
- `tests_rlm_adk/test_recursive_fanout_budget_limits.py`
- `tests_rlm_adk/test_recursive_accumulator_lineage_isolation.py`

### Phase 6: GREEN - Hardening Implementation
- Implement cancel-drain handshake.
- Implement runtime quarantine.
- Implement fanout budget enforcement.
- Add REPL async critical-section lock.
- Implement lineage-scoped accumulator model.

### Phase 7: RED - Lineage Observability
- `tests_rlm_adk/test_recursive_observability_lineage.py`
- `tests_rlm_adk/test_recursive_trace_scope_retention.py`
- `tests_rlm_adk/test_recursive_rollup_consistency.py`
- `tests_rlm_adk/test_recursive_after_agent_no_prefix_bleed.py`
- `tests_rlm_adk/test_recursive_sub_agent_event_envelope.py`
  - emitted `sub_agent_event` summaries include required lineage fields.

### Phase 8: GREEN - Observability/Tracing Implementation
- Lineage bucket writes + rollups.
- Scoped trace persistence in tracing plugin.
- Remove dynamic-prefix bleed path in `after_agent_callback`.

## Done Criteria
1. Worker dispatch is orchestrator-based.
2. Child workers can skip REPL or use REPL.
3. Child state collisions are blocked by scope + guard.
4. Root `request_id` stays immutable.
5. Timeout/cancel hardening prevents stale runtime reuse.
6. Lineage observability/tracing is deterministic and test-verified.
7. `output_schema` rejection behavior is explicit and tested in v1.
8. Call-log and trace parity are preserved post-cutover.
